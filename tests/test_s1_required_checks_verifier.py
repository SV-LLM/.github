"""S1 required-checks verifier: a head's own declared checks, offline, twice, bound to the head.

Fixture heads are temporary git repositories built here; nothing is fetched.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "sandbox" / "s1_required_checks_verifier.py"
SPEC = importlib.util.spec_from_file_location("s1_required_checks_verifier", VERIFIER)
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)

INPUTS = ROOT / "sandbox" / "s1-required-checks-inputs"
RECEIPTS = ROOT / "evidence" / "s1-required-checks"
PASSING = '''import unittest
class T(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(1 + 1, 2)
'''
FAILING = PASSING.replace("1 + 1, 2", "1 + 1, 3")
CLOCK = PASSING.replace("self.assertEqual(1 + 1, 2)", "import time; self.assertGreater(time.time(), 0)")
DATETIME = PASSING.replace("self.assertEqual(1 + 1, 2)",
                           "from datetime import datetime, timezone; self.assertTrue(datetime.now(timezone.utc))")
NETWORK = PASSING.replace("self.assertEqual(1 + 1, 2)",
                          "import socket\n        try:\n            socket.getaddrinfo('example.invalid', 80)\n"
                          "        except OSError:\n            pass")
RANDOM_OUT = "import os\nprint(os.urandom(8).hex())\n"


def declaration(*checks, dependencies=None):
    document = {"schema": v.DECLARATION_SCHEMA, "checks": list(checks)}
    if dependencies is not None:
        document["dependencies"] = dependencies
    return json.dumps(document, indent=2) + "\n"


def unit(check_id, target):
    return {"id": check_id, "kind": "python-unittest", "target": target, "expected_outcome": "PASS"}


class Fixture:
    def __init__(self, tmp: Path, files: dict[str, str]):
        self.repo = tmp / "head"
        self.repo.mkdir()
        env = v.base_env(tmp)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, env=env)
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "fixture"], check=True, env=env)
        self.head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True, env=env,
                                   capture_output=True, text=True).stdout.strip()
        self.input = tmp / "input.json"
        self.input.write_text(json.dumps({"schema": v.INPUT_SCHEMA, "type": "SV_CHANGE", "repository": "Fixture/repo",
                                          "pull_request": 1, "head_sha": self.head}))

    def verify(self, dependencies=None):
        return v.verify(self.input, self.repo, dependencies or {})


class RequiredChecks(unittest.TestCase):
    def run_fixture(self, files, dependencies=None):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), files)
            first = fixture.verify(dependencies)
            second = fixture.verify(dependencies)
        self.assertEqual(v.render(first), v.render(second), "the receipt must re-derive byte for byte")
        self.assertEqual(first["head_sha"], fixture.head)
        if first["disposition"] != "ALLOW":
            for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                          "owning_existing_goal", "next_attempt"):
                self.assertTrue(first.get(field), field)
        return first

    def test_no_declaration_is_fail_closed_not_declared(self):
        receipt = self.run_fixture({"README": "x\n"})
        self.assertEqual((receipt["disposition"], receipt["failure_code"]),
                         ("FAIL_CLOSED", "REQUIRED_CHECKS_NOT_DECLARED"))
        self.assertIn("INTERIM", receipt["declaration_basis"])
        self.assertEqual(receipt["checks"], [])

    def test_passing_declared_checks_are_allow_bound_to_the_head(self):
        receipt = self.run_fixture({".sv/required-checks.json": declaration(unit("unit", "tests/test_a.py")),
                                    "tests/test_a.py": PASSING})
        self.assertEqual(receipt["disposition"], "ALLOW")
        [check] = receipt["checks"]
        self.assertEqual((check["id"], check["outcome"], check["tests"], check["exit_code"]), ("unit", "PASS", 1, 0))
        self.assertTrue(check["stdout_sha256"].startswith("sha256:"))
        self.assertEqual(receipt["deterministic_across_runs"], 2)
        self.assertTrue(receipt["declaration_sha256"].startswith("sha256:"))

    def test_a_failing_check_is_deny(self):
        receipt = self.run_fixture({".sv/required-checks.json": declaration(unit("unit", "tests/test_a.py")),
                                    "tests/test_a.py": FAILING})
        self.assertEqual((receipt["disposition"], receipt["failure_code"]), ("DENY", "REQUIRED_CHECK_FAILED_AT_HEAD"))
        self.assertEqual(receipt["checks"][0]["failing_tests"], ["test_a.T.test_ok"])

    def test_a_clock_read_is_deny(self):
        for source in (CLOCK, DATETIME):
            with self.subTest(source=source.splitlines()[3].strip()):
                receipt = self.run_fixture({".sv/required-checks.json": declaration(unit("clock", "tests/test_a.py")),
                                            "tests/test_a.py": source})
                self.assertEqual((receipt["disposition"], receipt["failure_code"]),
                                 ("DENY", "REQUIRED_CHECK_READS_THE_CLOCK"))
                self.assertEqual(receipt["checks"][0]["stdout_sha256"], v.NOT_BOUND)
                self.assertTrue(receipt["checks"][0]["clock_reads"][0].endswith("@ tests/test_a.py:4"))

    def test_a_network_read_is_deny(self):
        receipt = self.run_fixture({".sv/required-checks.json": declaration(unit("net", "tests/test_a.py")),
                                    "tests/test_a.py": NETWORK})
        self.assertEqual((receipt["disposition"], receipt["failure_code"]), ("DENY", "REQUIRED_CHECK_READS_THE_NETWORK"))

    def test_output_that_differs_across_two_runs_is_deny(self):
        check = {"id": "random", "kind": "argv", "argv": ["python", "-B", "rand.py"], "expected_outcome": "PASS"}
        receipt = self.run_fixture({".sv/required-checks.json": declaration(check), "rand.py": RANDOM_OUT})
        self.assertEqual((receipt["disposition"], receipt["failure_code"]),
                         ("DENY", "REQUIRED_CHECK_OUTPUT_DIFFERS_ACROSS_TWO_RUNS"))
        self.assertEqual(receipt["checks"][0]["stdout_sha256"], v.NONDETERMINISTIC)

    def test_an_invalid_declaration_is_fail_closed(self):
        for text in ("{", json.dumps({"schema": "x", "checks": []}),
                     declaration({"id": "x", "kind": "shell", "expected_outcome": "PASS"}),
                     declaration(unit("missing", "tests/absent.py"))):
            with self.subTest(text=text[:40]):
                receipt = self.run_fixture({".sv/required-checks.json": text})
                self.assertEqual((receipt["disposition"], receipt["failure_code"]),
                                 ("FAIL_CLOSED", "REQUIRED_CHECKS_DECLARATION_INVALID"))

    def test_an_unsupplied_dependency_is_fail_closed(self):
        dependency = [{"id": "dep", "repository": "Fixture/dep", "commit": "a" * 40, "env": "DEP_ROOT"}]
        receipt = self.run_fixture({".sv/required-checks.json": declaration(unit("unit", "tests/test_a.py"),
                                                                            dependencies=dependency),
                                    "tests/test_a.py": PASSING})
        self.assertEqual((receipt["disposition"], receipt["failure_code"]),
                         ("FAIL_CLOSED", "REQUIRED_CHECK_DEPENDENCY_NOT_SUPPLIED"))

    def test_a_head_absent_from_the_checkout_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), {"README": "x\n"})
            fixture.input.write_text(fixture.input.read_text().replace(fixture.head, "b" * 40))
            receipt = fixture.verify()
        self.assertEqual((receipt["disposition"], receipt["failure_code"]), ("FAIL_CLOSED", "HEAD_NOT_MATERIALIZED"))


class CommittedReceipts(unittest.TestCase):
    def test_every_input_has_its_receipt_from_this_verifier(self):
        inputs = sorted(p.name for p in INPUTS.glob("*.json"))
        self.assertEqual(inputs, sorted(p.name for p in RECEIPTS.glob("*.json")))
        self.assertGreaterEqual(len(inputs), 15)
        for name in inputs:
            receipt = json.loads((RECEIPTS / name).read_text())
            document = json.loads((INPUTS / name).read_text())
            self.assertEqual(receipt["head_sha"], document["head_sha"], name)
            self.assertEqual(receipt["verifier"]["paths_sha256"], v.verifier_files(), name)
            self.assertIn(receipt["disposition"], ("ALLOW", "DENY", "FAIL_CLOSED"))
            body = {k: val for k, val in receipt.items() if k != "receipt_sha256"}
            self.assertEqual(receipt["receipt_sha256"], "sha256:" + v.sha256_hex(v.canon(body)), name)


if __name__ == "__main__":
    unittest.main()
