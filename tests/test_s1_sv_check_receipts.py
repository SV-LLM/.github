"""SV_CHANGE sv-check-receipt minting: pins, one receipt per row id, schema validity, negatives.

Fixture heads and a fixture Labs checkout are temporary git repositories built
here from the vendored pinned blobs (sandbox/s1_pins); nothing is fetched.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "sandbox"
SPEC = importlib.util.spec_from_file_location("s1_sv_check_receipts", SANDBOX / "s1_sv_check_receipts.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
rc = m.rc
eb = m.eb
READBACKS = SANDBOX / "s1-base-state-readbacks"
LEDGER_HEAD = "a" * 40
PINS = SANDBOX / "s1_pins"
INPUTS = SANDBOX / "s1-sv-check-inputs"
EVIDENCE = ROOT / "evidence" / "sv-check-receipts"
SIX_IDS = ["mutation-negative-suite", "registry-generation-fence", "schema-validate", "supplied-epoch-binder-check",
           "unit-tests", "workflow-surface-registered"]
PASSING = "import sys\nsys.exit(0 if 1 + 1 == 2 else 1)\n"
CLOCK = "import sys, time\nsys.exit(0 if time.time() > 0 else 1)\n"
SCHEMA = json.loads((PINS / "sv-check-receipt.v1.schema.json").read_text())
ROW = json.loads((PINS / "required-checks.json").read_text())


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def repo(path: Path, files: dict[str, bytes]) -> str:
    env = rc.base_env(path.parent)
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    for name, data in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(data)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "fixture"], check=True, env=env)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=True, env=env, capture_output=True,
                          text=True).stdout.strip()


def declaration(*ids: str, target: str = "tests/test_a.py") -> bytes:
    """A per-head .sv/required-checks.json -- which an SV_CHANGE head may carry but the minter must not read."""
    checks = [{"id": i, "kind": "python-unittest", "target": target, "expected_outcome": "PASS"} for i in ids]
    return (json.dumps({"schema": rc.DECLARATION_SCHEMA, "checks": checks}, indent=2) + "\n").encode()


UNITTEST = {"offline_command": ["python", "-B", "tests/test_a.py"], "expected": {"exit_code": 0},
            "command_paths": ["tests/test_a.py"]}
BASE_CHECK = (b"import json, subprocess, sys\nbase = sys.argv[sys.argv.index('--base-ref') + 1]\n"
              b"ok = subprocess.run(['git', 'merge-base', '--is-ancestor', base, 'HEAD']).returncode == 0\n"
              b"print(json.dumps({'disposition': 'ALLOW' if ok and len(base) == 40 else 'FAIL_CLOSED'}))\n")
BASE_CMD = {"offline_command": ["python3", "check.py", "--base-ref", "{base_commit}", "--head-ref", "HEAD"],
            "argument_bindings": {"{base_commit}": "supplied by the verifier"},
            "expected": {"exit_code": 0, "stdout_json_subset": {"disposition": "ALLOW"}}, "command_paths": ["check.py"]}


def commands_row(entries: dict) -> bytes:
    """A fixture row of the shape P1 announced (pending its blob): the pinned row plus per-id commands."""
    row = json.loads((PINS / "required-checks.json").read_text())
    for check_id, entry in entries.items():
        row["checks"][check_id] = {**row["checks"][check_id], **entry}
    return (json.dumps(row, indent=2, sort_keys=True) + "\n").encode()


def sealed_readback(epoch="4000", ledger_head=LEDGER_HEAD, **override):
    """A sealed readback of the shape P1's verify_admission_hb_epoch accepts (what #3266 does not yet seal)."""
    body = {"schema": eb.READBACK_SCHEMA, "component_id": "RTC-SV-CHANGE-BASE-STATE-READBACK-014",
            "disposition": "ALLOW", "base_ref": {"ledger_head": ledger_head, "registry_generation": 1},
            "hb_epoch": epoch, "hb_epoch_source": {"ledger_head": ledger_head, "field": eb.HB_EPOCH_SOURCE_FIELD,
                                                   "derived_from_clock": False}}
    body.update(override)
    return eb.seal({k: v for k, v in body.items() if v is not ...})


class Fixture:
    """A head repository, its SV_CHANGE record, and a Labs-shaped checkout holding the pinned row and schema."""

    def __init__(self, tmp: Path, head_files: dict[str, bytes], *, supplied="4000", readback: object = "sealed",
                 row: bytes | None = None, tamper_content: bool = False, base: bool = False,
                 extra_input: dict | None = None) -> None:
        self.head_repo = tmp / "head"
        self.head = repo(self.head_repo, head_files)
        self.base = None
        if base:  # a second commit on top: the first is the supplied base
            self.base = self.head
            (self.head_repo / "SECOND").write_bytes(b"2\n")
            head_files = {**head_files, "SECOND": b"2\n"}
            env = rc.base_env(tmp)
            subprocess.run(["git", "-C", str(self.head_repo), "add", "-A"], check=True, env=env)
            subprocess.run(["git", "-C", str(self.head_repo), "commit", "-q", "-m", "second"], check=True, env=env)
            self.head = subprocess.run(["git", "-C", str(self.head_repo), "rev-parse", "HEAD"], check=True, env=env,
                                       capture_output=True, text=True).stdout.strip()
        content = [{"path": p, "blob_digest": "sha256:" + hashlib.sha256(d).hexdigest(),
                    "writer_session": {"evidence_class": "DECLARED", "session": "Lane B (91117956)"}}
                   for p, d in sorted(head_files.items())]
        if tamper_content:
            content[0]["blob_digest"] = "sha256:" + "0" * 64
        record = {"schema": "stegverse.sv_change.v1", "record_mode": "NATIVE", "target_repository": "Fixture/repo",
                  "base_ref": {"ledger_head": LEDGER_HEAD, "registry_generation": 1}, "content": content,
                  "touched_paths": sorted(head_files), "projection": {"repo": "Fixture/repo", "head_sha": self.head}}
        if supplied is not ...:
            record["hb_epoch"] = supplied  # the SV_CHANGE's supplied epoch, which the binder check tests
        digest = m.change_digest(record)
        record.update(change_id="svc:" + digest[7:], head={"change_digest": digest})
        self.record = record
        self.labs_repo = tmp / "labs"
        self.labs = repo(self.labs_repo, {
            m.ROW_FILE: row if row is not None else (PINS / "required-checks.json").read_bytes(),
            m.RECEIPT_SCHEMA_FILE: (PINS / "sv-check-receipt.v1.schema.json").read_bytes(),
            "changes.jsonl": (json.dumps(record, sort_keys=True) + "\n").encode()})
        reference = None
        if readback is not None:
            data = readback if isinstance(readback, bytes) else \
                (json.dumps(sealed_readback() if readback == "sealed" else readback, sort_keys=True) + "\n").encode()
            (tmp / "readback.json").write_bytes(data)
            reference = {"file": str(tmp / "readback.json"), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        self.input = tmp / "input.json"
        self.input.write_text(json.dumps({
            "schema": m.INPUT_SCHEMA, "type": "SV_CHANGE", "repository": "Fixture/repo", "head_sha": self.head,
            "hb_epoch_readback": reference, **(extra_input or {}),
            "required_checks_row": {"repository": m.ROW_REPOSITORY, "commit": self.labs, "file": m.ROW_FILE,
                                    "blob_sha": m.ROW_BLOB, "receipt_schema_blob_sha": m.RECEIPT_SCHEMA_BLOB,
                                    "row_id": m.ROW_ID},
            "sv_change": {"repository": m.ROW_REPOSITORY, "commit": self.labs, "file": "changes.jsonl",
                          "change_id": record["change_id"]},
            **({"base_commit": {"sha": self.base, "basis": "fixture parent"}} if self.base else {})}))

    def mint(self):
        return m.mint(self.input, self.head_repo, {m.ROW_DEPENDENCY: self.labs_repo})


class Pins(unittest.TestCase):
    def test_the_pinned_blobs_have_not_drifted(self):
        self.assertEqual(m.PIN_COMMIT, "ba0385113f1fd0e155195269f72d5b91c835fa70")
        self.assertEqual(git_blob((PINS / "required-checks.json").read_bytes()), m.ROW_BLOB)
        self.assertTrue(m.ROW_BLOB.startswith("42405012"))
        self.assertEqual(git_blob((PINS / "sv-check-receipt.v1.schema.json").read_bytes()), m.RECEIPT_SCHEMA_BLOB)
        self.assertTrue(m.RECEIPT_SCHEMA_BLOB.startswith("070f13f4"))
        for path in sorted(INPUTS.glob("*.json")):
            row = json.loads(path.read_text())["required_checks_row"]
            self.assertEqual((row["commit"], row["blob_sha"], row["receipt_schema_blob_sha"]),
                             (m.PIN_COMMIT, m.ROW_BLOB, m.RECEIPT_SCHEMA_BLOB), path.name)

    def test_the_3266_readback_pins_have_not_drifted(self):
        self.assertEqual(eb.READBACK_PIN_COMMIT, "78a0c78e1f1313bd11ff916b26a3ab467f2f54e2")
        vendored = (PINS / "sv_change_base_state_readback.py").read_bytes()
        self.assertEqual(git_blob(vendored), eb.READBACK_COMPONENT_BLOB)
        self.assertTrue(eb.READBACK_COMPONENT_BLOB.startswith("2c369c8e"))
        self.assertIn(('RESULT_SCHEMA = "' + eb.READBACK_SCHEMA + '"').encode(), vendored)
        def segments(source):
            return {n.name: hashlib.sha256(ast.get_source_segment(source, n).encode()).hexdigest()
                    for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
        theirs, mine = segments(vendored.decode()), segments((SANDBOX / "s1_supplied_epoch_binder.py").read_text())
        for name in ("canon", "seal"):
            self.assertEqual(theirs[name], eb.READBACK_SEGMENT_SHA256[name], name)
            self.assertEqual(mine[name], eb.READBACK_SEGMENT_SHA256[name], name)
        self.assertEqual(mine["supplied_epoch_failure"], m.SHARED_RULE_SHA256)
        self.assertEqual(eb.SHARED_RULE_SHA256, m.SHARED_RULE_SHA256)
        for path in sorted(READBACKS.glob("*.json")):  # the committed readbacks are #3266's own sealed output
            body = json.loads(path.read_text())
            self.assertEqual(body["schema"], eb.READBACK_SCHEMA, path.name)
            self.assertEqual(eb.seal(body)["result_sha256"], body["result_sha256"], path.name)
        for path in sorted(INPUTS.glob("*.json")):  # no supplied epoch in any input; a readback bound by sha256
            document = json.loads(path.read_text())
            self.assertNotIn("hb_epoch", document, path.name)
            ref = document["hb_epoch_readback"]
            if ref is not None:
                self.assertTrue(ref["file"].startswith("sandbox/s1-base-state-readbacks/"), path.name)
                self.assertEqual(ref["sha256"], "sha256:" + hashlib.sha256((ROOT / ref["file"]).read_bytes()).hexdigest())

    def test_the_row_declares_exactly_the_six_ids_and_the_schema_enumerates_them(self):
        self.assertEqual(m.row_ids(ROW), SIX_IDS)
        self.assertEqual(sorted(SCHEMA["properties"]["check_id"]["enum"]), SIX_IDS)
        self.assertEqual(SCHEMA["properties"]["schema"]["const"], m.RECEIPT_SCHEMA)

    def test_the_vendored_p1_segments_and_epoch_rule_are_byte_identical(self):
        source = (SANDBOX / "s1_sv_check_receipts.py").read_text()
        lines = source.split("\n")
        found = {}
        for node in ast.parse(source).body:
            name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign)
                                                   and isinstance(node.targets[0], ast.Name) else None)
            if name in m.P1_SEGMENT_SHA256 or name == "supplied_epoch_failure":
                found[name] = hashlib.sha256("\n".join(lines[node.lineno - 1:node.end_lineno]).rstrip().encode()).hexdigest()
        self.assertEqual(found.pop("supplied_epoch_failure"), m.SHARED_RULE_SHA256)
        self.assertEqual(found, m.P1_SEGMENT_SHA256)

    def test_the_schema_subset_validator_fails_closed(self):
        self.assertTrue(m.schema_errors({}, {"oneOf": []}))
        good = m.receipt("unit-tests", "ALLOW", "sha256:" + "1" * 64, "2" * 40, "4000")
        self.assertEqual(m.schema_errors(good, SCHEMA), [])
        self.assertTrue(m.schema_errors({**good, "extra": 1}, SCHEMA))
        self.assertTrue(m.schema_errors({**good, "disposition": "DENY"}, SCHEMA))  # six fields required
        self.assertTrue(m.schema_errors({**good, "hb_epoch": "31"}, SCHEMA))
        self.assertTrue(m.schema_errors({**good, "check_id": "lint"}, SCHEMA))


class Minting(unittest.TestCase):
    def minted(self, files, commands=None, **kw):
        row = commands_row(commands) if commands is not None else kw.pop("row", None)
        pin = git_blob(row) if commands is not None else m.ROW_BLOB
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(m, "ROW_BLOB", pin):
            fixture = Fixture(Path(tmp), files, row=row, **kw)
            first, receipts = fixture.mint()
            second, again = fixture.mint()
        self.assertEqual(m.render(first), m.render(second))
        self.assertEqual({k: m.render(v) for k, v in receipts.items()}, {k: m.render(v) for k, v in again.items()})
        for body in receipts.values():
            self.assertEqual(m.schema_errors(body, SCHEMA), [], body)
            self.assertEqual(body["change_digest"], fixture.record["head"]["change_digest"])
            self.assertEqual(body["head_sha"], fixture.head)
            if body["disposition"] != "ALLOW":
                for field in m.SIX_FIELDS:
                    self.assertTrue(body[field], field)
        return first, receipts, fixture

    def codes(self, receipts):
        return {k: (v["disposition"], v.get("failure_code")) for k, v in receipts.items()}

    def test_every_row_command_present_and_as_expected_is_six_allow(self):
        bundle, receipts, _ = self.minted({"tests/test_a.py": PASSING.encode()}, {i: UNITTEST for i in SIX_IDS})
        self.assertEqual(sorted(receipts), SIX_IDS)
        self.assertEqual({r["disposition"] for r in receipts.values()}, {"ALLOW"})
        self.assertEqual(bundle["disposition"], "ALLOW")
        self.assertEqual([c["command"] for c in bundle["checks"]], [UNITTEST["offline_command"]] * 6)

    def test_the_pinned_row_is_read_verbatim(self):
        cmds = {i: m.command_declaration(ROW["checks"][i]) for i in SIX_IDS}
        binder = ROW["checks"]["supplied-epoch-binder-check"]  # declared at ba038511 as a verifier built-in
        self.assertEqual(m.verifier_builtin("supplied-epoch-binder-check", binder), "supplied-epoch-binder-check")
        self.assertEqual(binder["offline_command"]["verifier_ref"], "SV-LLM/.github#46")
        self.assertEqual(binder["expected"], {"disposition": "ALLOW"})
        self.assertIn("supplied-epoch-binder-check", ROW["surface_kinds"]["all"]["checks"])
        self.assertEqual(binder["predicate_pins"]["726248a5"]["sha256"], m.SHARED_RULE_SHA256)
        for i in set(SIX_IDS) - {"supplied-epoch-binder-check"}:
            self.assertIsNone(m.verifier_builtin(i, ROW["checks"][i]), i)
        for i in set(SIX_IDS) - {"supplied-epoch-binder-check"}:
            self.assertEqual(cmds[i][0], ROW["checks"][i]["offline_command"], i)
            self.assertEqual(cmds[i][1], ROW["checks"][i]["expected"], i)
        self.assertIn("{base_commit}", cmds["registry-generation-fence"][0])
        self.assertEqual(cmds["workflow-surface-registered"][1]["exit_code"], 0)  # the row's expectation stands

    def test_at_a_head_without_the_rows_command_paths_every_command_is_absent_or_undeclared(self):
        bundle, receipts, _ = self.minted({"tests/test_a.py": PASSING.encode()})
        want = {i: ("FAIL_CLOSED", "CHECK_COMMAND_ABSENT_AT_HEAD") for i in SIX_IDS}
        want["supplied-epoch-binder-check"] = ("ALLOW", None)  # the built-in needs nothing at the head
        self.assertEqual(self.codes(receipts), want)
        self.assertEqual({r["hb_epoch"] for r in receipts.values()}, {"4000"})  # the sealed epoch
        self.assertEqual(bundle["disposition"], "FAIL_CLOSED")

    def test_unknown_not_authentically_observed_is_check_command_undeclared(self):
        unknown = {**UNITTEST, "offline_command": "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"}
        _, receipts, _ = self.minted({"tests/test_a.py": PASSING.encode()},
                                     {**{i: UNITTEST for i in SIX_IDS}, "schema-validate": unknown})
        self.assertEqual(receipts["schema-validate"]["disposition"], "FAIL_CLOSED")
        self.assertEqual(receipts["schema-validate"]["failure_code"], "CHECK_COMMAND_UNDECLARED")
        self.assertEqual({receipts[i]["disposition"] for i in SIX_IDS if i != "schema-validate"}, {"ALLOW"})

    def test_a_command_path_absent_at_the_head_is_check_command_absent_at_head(self):
        absent = {**UNITTEST, "command_paths": ["tests/test_a.py", "scripts/not-at-head.py"]}
        bundle, receipts, _ = self.minted({"tests/test_a.py": PASSING.encode()},
                                          {**{i: UNITTEST for i in SIX_IDS}, "unit-tests": absent})
        self.assertEqual(self.codes(receipts)["unit-tests"], ("FAIL_CLOSED", "CHECK_COMMAND_ABSENT_AT_HEAD"))
        entry = next(c for c in bundle["checks"] if c["id"] == "unit-tests")
        self.assertEqual(entry["absent_command_paths"], ["scripts/not-at-head.py"])  # and it was not run
        self.assertEqual(bundle["disposition"], "FAIL_CLOSED")

    def test_per_head_pass_criteria_are_not_accepted(self):
        source = (SANDBOX / "s1_sv_check_receipts.py").read_text()
        self.assertNotIn("read_declaration", source)
        self.assertNotIn("run_set", source)
        _, receipts, _ = self.minted({".sv/required-checks.json": declaration(*SIX_IDS),
                                      "tests/test_a.py": PASSING.encode()})
        # a head declaring all six as passing changes nothing: the row's commands decide
        self.assertEqual({v.get("failure_code") for v in receipts.values()}, {"CHECK_COMMAND_ABSENT_AT_HEAD", None})

    def test_the_supplied_base_commit_binds_base_commit_and_is_recorded(self):
        files = {"check.py": BASE_CHECK, "tests/test_a.py": PASSING.encode()}
        rows = {**{i: UNITTEST for i in SIX_IDS}, "registry-generation-fence": BASE_CMD}
        bundle, receipts, fixture = self.minted(files, rows, base=True)
        self.assertEqual(receipts["registry-generation-fence"]["disposition"], "ALLOW")
        self.assertEqual(bundle["base_commit"]["sha"], fixture.base)
        fence = next(c for c in bundle["checks"] if c["id"] == "registry-generation-fence")
        self.assertEqual(fence["command"][3], fixture.base)

    def test_an_unsupplied_binding_is_check_argument_not_supplied_and_nothing_runs(self):
        files = {"check.py": BASE_CHECK, "tests/test_a.py": PASSING.encode()}
        bundle, receipts, _ = self.minted(files, {**{i: UNITTEST for i in SIX_IDS}, "registry-generation-fence": BASE_CMD})
        self.assertEqual(self.codes(receipts)["registry-generation-fence"], ("FAIL_CLOSED", "CHECK_ARGUMENT_NOT_SUPPLIED"))
        self.assertIsNone(bundle["base_commit"])

    def test_stdout_json_subset_and_stderr_last_line_are_compared(self):
        files = {"tests/test_a.py": PASSING.encode()}
        wrong_line = {**UNITTEST, "expected": {"exit_code": 0, "stderr_last_line": "OK"}}  # the script prints nothing
        _, receipts, _ = self.minted(files, {**{i: UNITTEST for i in SIX_IDS}, "unit-tests": wrong_line})
        self.assertEqual(self.codes(receipts)["unit-tests"], ("FAIL_CLOSED", "REQUIRED_CHECK_FAILED_AT_HEAD"))
        self.assertTrue(m.outcome_matches({"exit_code": 0, "stdout_json_subset": {"d": 1}}, 0, b'{"d": 1, "x": 2}', b""))
        self.assertFalse(m.outcome_matches({"exit_code": 0, "stdout_json_subset": {"d": 1}}, 0, b'{"d": 2}', b""))
        self.assertTrue(m.outcome_matches({"exit_code": 0, "stderr_last_line": "OK"}, 0, b"", b"Ran 3 tests\n\nOK\n"))
        self.assertFalse(m.outcome_matches({"exit_code": 0}, 1, b"", b""))

    def test_an_exit_code_other_than_expected_is_fail_closed(self):
        failing = PASSING.replace("1 + 1 == 2", "1 + 1 == 3").encode()
        _, receipts, _ = self.minted({"tests/test_a.py": failing}, {i: UNITTEST for i in SIX_IDS})
        self.assertEqual(set(self.codes(receipts).values()), {("FAIL_CLOSED", "REQUIRED_CHECK_FAILED_AT_HEAD")})

    def test_a_clock_reading_check_is_deny(self):
        _, receipts, _ = self.minted({"tests/test_a.py": CLOCK.encode()}, {"unit-tests": UNITTEST})
        self.assertEqual(self.codes(receipts)["unit-tests"], ("DENY", "REQUIRED_CHECK_READS_THE_CLOCK"))

    def test_an_id_outside_the_row_is_check_id_undeclared(self):
        _, receipts, fixture = self.minted({"tests/test_a.py": PASSING.encode()}, {i: UNITTEST for i in SIX_IDS})
        self.assertNotIn("lint", receipts)
        forged = {**receipts["unit-tests"], "check_id": "lint"}
        result = m.check_receipt(forged, fixture.record, ROW, SCHEMA)
        self.assertEqual((result["disposition"], result["failure_code"]), ("FAIL_CLOSED", "CHECK_ID_UNDECLARED"))

    def test_a_receipt_not_at_the_heads_change_digest_is_skipped_or_unobserved(self):
        _, receipts, fixture = self.minted({"tests/test_a.py": PASSING.encode()}, {i: UNITTEST for i in SIX_IDS})
        self.assertEqual(m.check_receipt(receipts["unit-tests"], fixture.record, ROW, SCHEMA), {"disposition": "ALLOW"})
        stale = {**receipts["unit-tests"], "change_digest": "sha256:" + "f" * 64}
        result = m.check_receipt(stale, fixture.record, ROW, SCHEMA)
        self.assertEqual((result["disposition"], result["failure_code"], result["failed_predicate"]),
                         ("FAIL_CLOSED", "CHECK_SKIPPED_OR_UNOBSERVED", "RECEIPT_CHANGE_DIGEST_EQUALS_HEAD"))
        for field in m.SIX_FIELDS:
            self.assertTrue(result[field], field)

    def assert_source_unobserved(self, **kw):
        bundle, receipts, _ = self.minted({"README": b"x\n"}, **kw)
        self.assertEqual(receipts, {})  # no schema-valid receipt can carry an unobserved epoch: the bundle refuses
        self.assertEqual((bundle["disposition"], bundle["failure_code"]), ("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED"))
        self.assertEqual(bundle["owning_existing_goal"], "StegVerse-org/.github#162")
        self.assertTrue(bundle["retry_entrypoint"].startswith("StegVerse-Labs/.github#3266 "))
        for field in m.SIX_FIELDS:
            self.assertTrue(bundle[field], field)
        self.assertIsNone(bundle["hb_epoch"])  # never a supplied constant, never a clock
        return bundle

    def test_an_unobserved_epoch_source_mints_nothing(self):
        cases = {
            "no readback": None,
            "readback file not its sha256": b"{}\n",
            "#3266 at 78a0c78e: hb_epoch null, no hb_epoch_source": sealed_readback(None, hb_epoch_source=...),
            "caller-supplied hb_epoch without hb_epoch_source": sealed_readback("4000", hb_epoch_source=...),
            "absent sealed epoch": sealed_readback(None),
            "clock-derived": sealed_readback(hb_epoch_source={"ledger_head": LEDGER_HEAD, "field": eb.HB_EPOCH_SOURCE_FIELD,
                                                              "derived_from_clock": True}),
            "non-integer": sealed_readback("4000.0"),
            "signed": sealed_readback("+4000"),
            "below the anchor": sealed_readback("31"),
            "bool": sealed_readback(True),
            "other ledger head": sealed_readback(ledger_head="b" * 40),
            "source at another head": sealed_readback(hb_epoch_source={"ledger_head": "b" * 40,
                                                                       "field": eb.HB_EPOCH_SOURCE_FIELD}),
            "other field": sealed_readback(hb_epoch_source={"ledger_head": LEDGER_HEAD, "field": "$.observed_at"}),
            "not ALLOW": sealed_readback(disposition="FAIL_CLOSED", failure_code="BASE_STATE_NOT_OBSERVED"),
            "fixture_only": sealed_readback(fixture_only=True),
            "broken seal": {**sealed_readback(), "hb_epoch": "4001"},
            "other schema": sealed_readback(schema="stegverse.other/v1"),
        }
        for name, readback in cases.items():
            with self.subTest(name):
                self.assert_source_unobserved(readback=readback)
        with self.subTest("the committed #3266 readback (hb_epoch null)"):
            real = (READBACKS / "StegVerse-Labs-bfcf031811caaa65bc44a48c894fce19800b5d90.json").read_bytes()
            body = json.loads(real)
            self.assertIsNone(body["hb_epoch"])
            self.assertNotIn("hb_epoch_source", body)
            self.assert_source_unobserved(readback=real)

    def test_a_supplied_epoch_in_the_input_is_refused(self):
        bundle, receipts, _ = self.minted({"README": b"x\n"}, extra_input={"hb_epoch": "4000"})
        self.assertEqual(receipts, {})
        self.assertEqual(bundle["failure_code"], "S1_INPUT_NOT_A_DECLARED_SV_CHANGE")

    def test_receipts_carry_the_sealed_epoch(self):
        bundle, receipts, _ = self.minted({"README": b"x\n"}, supplied="4321", readback=sealed_readback("4321"))
        self.assertEqual({r["hb_epoch"] for r in receipts.values()}, {"4321"})
        self.assertEqual(bundle["hb_epoch"], "4321")
        self.assertEqual(self.codes(receipts)["supplied-epoch-binder-check"], ("ALLOW", None))
        self.assertEqual(bundle["hb_epoch_source"]["ledger_head"], LEDGER_HEAD)
        self.assertEqual(bundle["hb_epoch_source"]["readback_component"]["commit"], eb.READBACK_PIN_COMMIT)

    def test_a_supplied_epoch_that_contradicts_the_readback_is_deny_mismatch(self):
        for supplied in ("4001", "31", "+4000", "4000.0", "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED", None, ...):
            with self.subTest(supplied=supplied):
                bundle, receipts, _ = self.minted({"README": b"x\n"}, supplied=supplied)
                binder = receipts["supplied-epoch-binder-check"]
                self.assertEqual((binder["disposition"], binder["failure_code"]), ("DENY", "HB_EPOCH_MISMATCH"))
                self.assertEqual(binder["failed_predicate"], "ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH")
                self.assertEqual(binder["owning_existing_goal"], "StegVerse-org/.github#162")
                self.assertEqual(binder["hb_epoch"], "4000")  # the receipt carries the sealed epoch, not the supplied
                self.assertEqual(bundle["disposition"], "DENY")
        _, receipts, _ = self.minted({"README": b"x\n"}, supplied="04000")  # equal by integer value
        self.assertEqual(receipts["supplied-epoch-binder-check"]["disposition"], "ALLOW")

    def test_the_binder_check_in_isolation(self):
        rb = sealed_readback("469411750")
        self.assertEqual(eb.binder_check("469411750", rb, LEDGER_HEAD)["disposition"], "ALLOW")
        self.assertEqual(eb.binder_check("4000", rb, LEDGER_HEAD)["failure_code"], "HB_EPOCH_MISMATCH")
        self.assertEqual(eb.binder_check("4000", rb, LEDGER_HEAD)["disposition"], "DENY")
        refused = eb.binder_check("469411750", rb, "c" * 40)
        self.assertEqual((refused["disposition"], refused["failure_code"]), ("FAIL_CLOSED", "HB_EPOCH_SOURCE_UNOBSERVED"))
        self.assertEqual(eb.binder_check("469411750", None, LEDGER_HEAD)["failure_code"], "HB_EPOCH_SOURCE_UNOBSERVED")
        source = (SANDBOX / "s1_supplied_epoch_binder.py").read_text()
        for word in ("import time", "datetime", "socket", "urllib", "random"):
            self.assertNotIn(word, source)

    def test_only_the_declared_builtin_is_dispatched(self):
        builtin = ROW["checks"]["supplied-epoch-binder-check"]
        for name, entry in {
            "other name": {"offline_command": {**builtin["offline_command"], "verifier_builtin": "lint"}},
            "other verifier": {"offline_command": {**builtin["offline_command"], "verifier_ref": "Other/.github#1"}},
            "command paths": {"command_paths": ["x.py"]},
            "expected": {"expected": {"exit_code": 0}},
        }.items():
            with self.subTest(name):
                _, receipts, _ = self.minted({"README": b"x\n"}, {"supplied-epoch-binder-check": entry})
                self.assertEqual(self.codes(receipts)["supplied-epoch-binder-check"],
                                 ("FAIL_CLOSED", "CHECK_COMMAND_UNDECLARED"))

    def test_check_refuses_a_receipt_whose_epoch_is_not_the_sealed_one(self):
        _, receipts, fixture = self.minted({"tests/test_a.py": PASSING.encode()}, {i: UNITTEST for i in SIX_IDS})
        self.assertEqual(m.check_receipt(receipts["unit-tests"], fixture.record, ROW, SCHEMA, "4000"), {"disposition": "ALLOW"})
        other = m.check_receipt({**receipts["unit-tests"], "hb_epoch": "4001"}, fixture.record, ROW, SCHEMA, "4000")
        self.assertEqual((other["disposition"], other["failure_code"]), ("DENY", "HB_EPOCH_MISMATCH"))

    def test_a_drifted_row_blob_mints_nothing(self):
        drifted = (PINS / "required-checks.json").read_bytes().replace(b'"unit-tests"', b'"unit-test"', 1)
        bundle, receipts, _ = self.minted({"README": b"x\n"}, row=drifted)
        self.assertEqual(receipts, {})
        self.assertEqual(bundle["failure_code"], "REQUIRED_CHECKS_ROW_ABSENT")

    def test_content_that_is_not_the_head_is_fail_closed_for_every_id(self):
        bundle, receipts, _ = self.minted({"README": b"x\n"}, tamper_content=True)
        self.assertEqual(sorted(receipts), SIX_IDS)
        codes = {k: r["failure_code"] for k, r in receipts.items()}
        self.assertEqual(set(codes.values()), {"SV_CHANGE_CONTENT_NOT_AT_HEAD"})  # the built-in included


class CommittedEvidence(unittest.TestCase):
    def test_every_input_has_six_schema_valid_receipts_or_an_unobserved_epoch_source(self):
        names = sorted(p.stem for p in INPUTS.glob("*.json"))
        self.assertEqual(names, sorted(p.name for p in EVIDENCE.iterdir()))
        self.assertGreaterEqual(len(names), 4)
        for name in names:
            bundle = json.loads((EVIDENCE / name / "bundle.json").read_text())
            self.assertEqual(bundle["verifier"]["paths_sha256"], m.verifier_files(), name)
            body = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
            self.assertEqual(bundle["bundle_sha256"], "sha256:" + m.sha256_hex(m.canon(body)), name)
            files = sorted(p.stem for p in (EVIDENCE / name).glob("*.json") if p.name != "bundle.json")
            if bundle.get("failure_code") == "HB_EPOCH_SOURCE_UNOBSERVED":  # the bundle is the refusal: no receipts
                self.assertEqual((files, bundle["receipts"], bundle["hb_epoch"]), ([], {}, None), name)
                continue
            self.assertEqual(files, SIX_IDS, name)
            for check_id in files:
                data = (EVIDENCE / name / (check_id + ".json")).read_bytes()
                self.assertEqual(bundle["receipts"][check_id], "sha256:" + hashlib.sha256(data).hexdigest())
                self.assertEqual(m.schema_errors(json.loads(data), SCHEMA), [], name + "/" + check_id)


if __name__ == "__main__":
    unittest.main()
