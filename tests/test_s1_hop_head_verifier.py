"""S1 SV-LLM sandbox verifier: negative cases, determinism and the shared epoch rule.

Heads here are temporary git repositories whose ``resident-runtime/intr_hop.py``
is a stub with a declared behaviour, so every disposition is exercised without
network, dispatch or clock. The real hop at real heads is run by the workflow
step that re-derives the committed receipts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "sandbox" / "s1_hop_head_verifier.py"
SPEC = importlib.util.spec_from_file_location("s1_hop_head_verifier", VERIFIER)
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)

SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair",
       "retry_entrypoint", "owning_existing_goal", "next_attempt")

STUB = r'''
import json, sys, os, random
from pathlib import Path
mode = (Path(__file__).resolve().parents[1] / "stub-mode.txt").read_text().strip()
args = sys.argv[1:]
phase = args[0]
out = Path(args[args.index("--out") + 1])
def emit(result, code=0):
    out.write_text(json.dumps(result))
    sys.exit(code)
if mode == "crash-" + phase:
    sys.exit(3)
if mode == "deny-" + phase:
    emit({"disposition": "FAIL_CLOSED", "failure_code": "STUB_REFUSED", "failed_predicate": "STUB"}, 1)
if phase == "readback":
    emit({"failed_predicates": ["STUB_READBACK"] if mode == "readback-fails" else []})
digest = "sha256:" + ("%064x" % random.getrandbits(256) if mode == "unsupplied" else "ab" * 32)
result = {"disposition": "ALLOW", "frame": "ZnJhbWU=", "packet_id": "pkt", "repository_receipt_sha256": digest,
          "hb_epoch": int(args[args.index("--hb-epoch") + 1])}
if phase == "close":
    result["closed"] = mode != "not-closed"
emit(result)
'''


def _git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_AUTHOR_DATE": "@0 +0000", "GIT_COMMITTER_DATE": "@0 +0000"}
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env).stdout.decode().strip()


def make_head(base: Path, mode: str = "allow", *, hop_job: bool = True, module: bool = True) -> tuple[Path, str]:
    root = base / ("head-" + mode)
    for relative, text in (
        ("org-boundary/registry/services.json", json.dumps({"organization": "Stub-Org", "services": []})),
        (".stegverse/transition-ledger/contract.json",
         json.dumps({"repository_ledger_location": {"namespace": "repository-ledger/Stub-Org/.github"}})),
        (".github/workflows/intr-destination-hop.yml",
         "name: hop\njobs:\n  validate:\n    runs-on: x\n" + ("  hop:\n    runs-on: x\n" if hop_job else "")),
        ("stub-mode.txt", mode),
    ) + ((("resident-runtime/intr_hop.py", STUB),) if module else ()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "head")
    return root, _git(root, "rev-parse", "HEAD")


def write_input(base: Path, head: str, **overrides) -> Path:
    document = {"schema": v.INPUT_SCHEMA, "type": "SV_CHANGE", "repository": "Stub-Org/.github",
                "pull_request": 1, "head_sha": head, "check": v.CHECK, "hb_epoch": "40"}
    document.update(overrides)
    for key in [key for key, value in document.items() if value is _DROP]:
        del document[key]
    path = base / ("input-%d.json" % len(list(base.glob("input-*.json"))))
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


_DROP = object()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def assert_refused(self, receipt: dict, disposition: str, code: str) -> None:
        self.assertEqual(receipt["disposition"], disposition, receipt)
        self.assertEqual(receipt["failure_code"], code, receipt)
        for field in SIX:
            self.assertIsInstance(receipt.get(field), str, field)
            self.assertTrue(receipt[field].strip(), field)
        self.assert_evidence_only(receipt)

    def assert_evidence_only(self, receipt: dict) -> None:
        self.assertIs(receipt["authentic_ledger_receipt"], False)
        self.assertEqual(receipt["evidence_role"], "ADMISSION_INPUT_EVIDENCE_ONLY")
        self.assertIn("Not an authentic organization-ledger receipt", receipt["evidence_note"])
        for flag in ("clock_read", "dispatched", "network_read", "credentials_passed", "ledger_appended_outside_sandbox"):
            self.assertIs(receipt[flag], False, flag)
        body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        self.assertEqual(receipt["receipt_sha256"], "sha256:" + hashlib.sha256(v.canon(body)).hexdigest())


class AllowAndDeterminismTests(Base):
    def test_a_passing_hop_at_the_exact_head_is_allow_bound_to_the_head(self):
        root, head = make_head(self.base)
        receipt = v.verify(write_input(self.base, head), root)
        self.assertEqual(receipt["disposition"], "ALLOW", receipt)
        self.assertEqual(receipt["head_sha"], head)
        self.assertEqual(receipt["head_tree"], _git(root, "rev-parse", head + "^{tree}"))
        self.assertEqual([phase["phase"] for phase in receipt["phases"]],
                         ["send", "receive", "close", "readback-send", "readback-receive", "readback-close"])
        self.assertEqual(receipt["hop_check"]["phase_epochs"], [40, 41, 42])
        self.assertEqual([phase.get("hb_epoch") for phase in receipt["phases"][:3]], [40, 41, 42])
        self.assertFalse(any(field in receipt for field in SIX))
        self.assert_evidence_only(receipt)

    def test_the_same_input_gives_the_same_bytes(self):
        root, head = make_head(self.base)
        path = write_input(self.base, head)
        first = v.render(v.verify(path, root))
        second = v.render(v.verify(path, root))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(first, v.canon(json.loads(first)) + b"\n")

    def test_the_working_tree_is_not_read_only_the_head(self):
        root, head = make_head(self.base)
        (root / "stub-mode.txt").write_text("deny-send", encoding="utf-8")
        self.assertEqual(v.verify(write_input(self.base, head), root)["disposition"], "ALLOW")

    def test_cli_exit_code_and_out_file(self):
        root, head = make_head(self.base)
        out = self.base / "r.json"
        self.assertEqual(v.main(["--input", str(write_input(self.base, head)), "--checkout", str(root),
                                 "--out", str(out)]), 0)
        self.assertEqual(json.loads(out.read_bytes())["disposition"], "ALLOW")


class DenyTests(Base):
    def test_a_refused_phase_is_deny(self):
        for mode in ("deny-send", "deny-receive", "deny-close"):
            root, head = make_head(self.base, mode)
            receipt = v.verify(write_input(self.base, head), root)
            self.assert_refused(receipt, "DENY", "HOP_CHECK_REFUSED_AT_HEAD")
            self.assertEqual(receipt["detail"], mode.split("-")[1])

    def test_a_hop_that_does_not_close_is_deny(self):
        root, head = make_head(self.base, "not-closed")
        self.assert_refused(v.verify(write_input(self.base, head), root), "DENY", "HOP_CHECK_REFUSED_AT_HEAD")

    def test_a_failed_readback_is_deny(self):
        root, head = make_head(self.base, "readback-fails")
        receipt = v.verify(write_input(self.base, head), root)
        self.assert_refused(receipt, "DENY", "HOP_CHECK_REFUSED_AT_HEAD")
        self.assertEqual(receipt["failed_predicate"], "THE_HOP_RECEIPTS_READ_BACK_AT_THE_EXACT_HEAD")

    def test_receipts_that_differ_between_two_runs_are_deny_and_the_receipt_stays_deterministic(self):
        root, head = make_head(self.base, "unsupplied")
        path = write_input(self.base, head)
        receipt = v.verify(path, root)
        self.assert_refused(receipt, "DENY", "HOP_RECEIPTS_DEPEND_ON_AN_UNSUPPLIED_INPUT")
        self.assertEqual(receipt["phases"][0]["repository_receipt_sha256"], v.NONDETERMINISTIC)
        self.assertEqual(v.render(receipt), v.render(v.verify(path, root)))


class FailClosedTests(Base):
    def test_a_phase_with_no_result_is_fail_closed(self):
        root, head = make_head(self.base, "crash-receive")
        receipt = v.verify(write_input(self.base, head), root)
        self.assert_refused(receipt, "FAIL_CLOSED", "HOP_CHECK_DID_NOT_COMPLETE")
        self.assertEqual(receipt["detail"], "receive")

    def test_a_head_without_the_hop_check_is_fail_closed(self):
        for kwargs in ({"module": False}, {"hop_job": False}):
            sub = self.base / str(len(list(self.base.iterdir())))
            sub.mkdir()
            root, head = make_head(sub, **kwargs)
            self.assert_refused(v.verify(write_input(self.base, head), root), "FAIL_CLOSED", "HOP_CHECK_ABSENT_AT_HEAD")

    def test_a_head_not_in_the_checkout_is_fail_closed(self):
        root, _head = make_head(self.base)
        receipt = v.verify(write_input(self.base, "0" * 40), root)
        self.assert_refused(receipt, "FAIL_CLOSED", "HEAD_NOT_MATERIALIZED")
        self.assertEqual(receipt["phases"], [])

    def test_no_checkout_is_fail_closed(self):
        _root, head = make_head(self.base)
        self.assert_refused(v.verify(write_input(self.base, head), None), "FAIL_CLOSED", "HEAD_NOT_MATERIALIZED")

    def test_an_input_that_is_not_a_declared_sv_change_is_fail_closed(self):
        root, head = make_head(self.base)
        for overrides in ({"type": "SV_ISSUE"}, {"schema": "x"}, {"head_sha": head[:12]}, {"head_sha": head.upper()},
                          {"pull_request": True}, {"pull_request": 0}, {"repository": "no-slash"},
                          {"check": "validate"}):
            receipt = v.verify(write_input(self.base, head, **overrides), root)
            self.assert_refused(receipt, "FAIL_CLOSED", "S1_INPUT_NOT_A_DECLARED_SV_CHANGE")
            self.assertEqual(receipt["phases"], [])
        bad = self.base / "bad.json"
        bad.write_bytes(b"{not json")
        self.assert_refused(v.verify(bad, root), "FAIL_CLOSED", "S1_INPUT_NOT_READABLE")
        array = self.base / "array.json"
        array.write_text("[]", encoding="utf-8")
        self.assert_refused(v.verify(array, root), "FAIL_CLOSED", "S1_INPUT_NOT_A_DECLARED_SV_CHANGE")

    def test_cli_exit_code_is_nonzero_for_non_allow(self):
        root, head = make_head(self.base, "deny-send")
        self.assertEqual(v.main(["--input", str(write_input(self.base, head)), "--checkout", str(root),
                                 "--out", str(self.base / "r.json")]), 1)


class SuppliedEpochTests(Base):
    def test_the_vendored_rule_is_byte_identical_to_the_shared_supplied_epoch_failure(self):
        source = VERIFIER.read_text(encoding="utf-8")
        start = source.index("def supplied_epoch_failure")
        end = source.index("\ndef ", start + 5)
        self.assertEqual(hashlib.sha256(source[start:end].rstrip().encode()).hexdigest(), v.SHARED_RULE_SHA256)
        self.assertTrue(v.SHARED_RULE_SHA256.startswith("726248a5"))

    def test_coerced_below_anchor_and_missing_epochs_are_fail_closed_and_nothing_runs(self):
        root, head = make_head(self.base)
        cases = [("+33", "HB_EPOCH_INVALID"), (" 33", "HB_EPOCH_INVALID"), ("3_3", "HB_EPOCH_INVALID"),
                 ("33.0", "HB_EPOCH_INVALID"), (33.0, "HB_EPOCH_INVALID"), (True, "HB_EPOCH_INVALID"),
                 ("", "HB_EPOCH_INVALID"), ("\u0663\u0663", "HB_EPOCH_INVALID"), (None, "HB_EPOCH_NOT_SUPPLIED"),
                 (_DROP, "HB_EPOCH_NOT_SUPPLIED")]
        cases += [(epoch, "HB_EPOCH_INVALID") for epoch in range(32)]
        cases += [(str(epoch), "HB_EPOCH_INVALID") for epoch in range(32)]
        for epoch, code in cases:
            receipt = v.verify(write_input(self.base, head, hb_epoch=epoch), root)
            self.assert_refused(receipt, "FAIL_CLOSED", code)
            self.assertEqual(receipt["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH", repr(epoch))
            self.assertEqual(receipt["phases"], [], repr(epoch))
            self.assertIsNone(receipt["hb_epoch"], repr(epoch))

    def test_epoch_32_and_its_digit_forms_are_accepted(self):
        root, head = make_head(self.base)
        for epoch in (32, "32", "0032"):
            receipt = v.verify(write_input(self.base, head, hb_epoch=epoch), root)
            self.assertEqual(receipt["disposition"], "ALLOW", repr(epoch))
            self.assertEqual(receipt["hb_epoch"], 32)

    def test_no_clock_is_read_by_the_verifier(self):
        source = VERIFIER.read_text(encoding="utf-8")
        for token in ("datetime", "time.time", "import time", "monotonic", "perf_counter", "uuid"):
            self.assertNotIn(token, source)


class CommittedReceiptTests(unittest.TestCase):
    """Every committed receipt recomputes and names an input committed beside it."""

    def test_committed_receipts_are_canonical_and_bound_to_their_inputs(self):
        receipts = sorted((ROOT / "evidence" / "s1-hop-head").glob("*.json"))
        self.assertEqual(len(receipts), 8)
        verifier = hashlib.sha256(VERIFIER.read_bytes()).hexdigest()
        for path in receipts:
            raw = path.read_bytes()
            receipt = json.loads(raw)
            self.assertEqual(raw, v.canon(receipt) + b"\n", path.name)
            body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            self.assertEqual(receipt["receipt_sha256"], "sha256:" + hashlib.sha256(v.canon(body)).hexdigest())
            self.assertEqual(receipt["verifier"]["sha256"], verifier, path.name)
            self.assertIs(receipt["authentic_ledger_receipt"], False)
            organization, _, rest = path.stem.rpartition("-")
            name = organization + ".json"
            source = ROOT / "sandbox" / "s1-inputs" / name
            self.assertEqual(receipt["input_sha256"], hashlib.sha256(source.read_bytes()).hexdigest(), path.name)
            self.assertTrue(receipt["head_sha"].startswith(rest), path.name)
            if receipt["disposition"] != "ALLOW":
                for field in SIX:
                    self.assertTrue(receipt[field].strip(), (path.name, field))


if __name__ == "__main__":
    unittest.main()
