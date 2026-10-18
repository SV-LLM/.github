"""G4 / NWI-S1: an organization ledger append carries the supplied epoch or is refused.

SV_LLM_LEDGER_APPEND_CLOCK_FALLBACK, SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH,
owning_existing_goal SVORG-LLM-ORG-FOUNDATION-001 W04. Port of the
StegVerse-org/.github 40a5d235 append refusal: append() fell back to the host
clock when no epoch was supplied. A missing or invalid epoch is now a six-field
FAIL_CLOSED from the vendored shared rule, nothing is written, no clock is read.
"""
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
AGG = ROOT / "resident-runtime/aggregate_repo_transition.py"
spec = importlib.util.spec_from_file_location("g4_append_epoch", AGG)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
store_spec = importlib.util.spec_from_file_location("g4_ledger_store", ROOT / "resident-runtime/ledger_store.py")
ledger = importlib.util.module_from_spec(store_spec)
store_spec.loader.exec_module(ledger)

SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
STATE_AFTER = "sha256:" + "b" * 64
MALFORMED = ("+33", " 33", "33 ", "3_3", "31", "0", "", "x", "٣٣", 31, -40, 33.0, True)


def repo_receipt(number):
    body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": "SV-LLM/sandbox",
            "transition_id": "g4-" + str(number)}
    return {**body, "receipt_sha256": module.sha(body)}


def documents(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())


class SharedRule(unittest.TestCase):
    def test_the_vendored_rule_is_the_shared_segment(self):
        text = AGG.read_text()
        [node] = [n for n in ast.parse(text).body if getattr(n, "name", None) == "supplied_epoch_failure"]
        segment = "\n".join(text.splitlines()[node.lineno - 1:node.end_lineno]).rstrip()
        self.assertEqual(hashlib.sha256(segment.encode()).hexdigest(), module.SHARED_RULE_SHA256)
        self.assertTrue(module.SHARED_RULE_SHA256.startswith("726248a5"))


class AppendRefusal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ledger.PosixLedgerStore(self.tmp.name)

    def refused(self, epoch, code):
        with mock.patch("time.time", side_effect=AssertionError("clock read")), \
                mock.patch("time.time_ns", side_effect=AssertionError("clock read")):
            with self.assertRaises(module.OrgLedgerEpochRefused) as caught:
                module.append(repo_receipt(1), "REPO_STATE_PROPAGATION", module.GENESIS, STATE_AFTER, {}, "NONE",
                              hb_epoch=epoch, store=self.store)
        refusal = caught.exception.refusal
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        for field in SIX:
            self.assertTrue(refusal.get(field), field)
        self.assertEqual(refusal["failure_code"], code)
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        self.assertEqual(refusal["failure_class"], "SV_LLM_LEDGER_APPEND_CLOCK_FALLBACK")
        self.assertEqual(refusal["owning_existing_goal"], "SVORG-LLM-ORG-FOUNDATION-001 W04")
        self.assertIn("WorkCycle._propagate", refusal["retry_entrypoint"])
        self.assertIsInstance(caught.exception, module.OrgLedgerAppendRefused)
        self.assertEqual(documents(self.tmp.name), [])
        self.assertIsNone(self.store.get(ledger.HEAD_KEY))

    def test_a_missing_epoch_is_refused_and_no_clock_is_read(self):
        self.refused(None, "HB_EPOCH_NOT_SUPPLIED")

    def test_a_malformed_or_pre_anchor_epoch_is_refused(self):
        for epoch in MALFORMED:
            with self.subTest(epoch=epoch):
                self.refused(epoch, "HB_EPOCH_INVALID")

    def test_the_anchor_and_a_digit_string_are_admitted_as_the_supplied_epoch(self):
        for epoch, expected in ((32, 32), ("4000", 4000)):
            with self.subTest(epoch=epoch), tempfile.TemporaryDirectory() as tmp:
                receipt = module.append(repo_receipt(1), "REPO_STATE_PROPAGATION", module.GENESIS, STATE_AFTER, {},
                                        "NONE", hb_epoch=epoch, store=ledger.PosixLedgerStore(tmp))
                self.assertEqual(receipt["hb_reference"]["epoch"], expected)
                self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_a_moving_clock_does_not_move_the_receipt(self):
        receipts = []
        for clock in (1_000.0, 9_999_999.0):
            with tempfile.TemporaryDirectory() as tmp, mock.patch("time.time", return_value=clock), \
                    mock.patch("time.time_ns", return_value=int(clock * 1e9)):
                receipts.append(module.append(repo_receipt(1), "REPO_STATE_PROPAGATION", module.GENESIS, STATE_AFTER,
                                              {}, "NONE", hb_epoch=4000, store=ledger.PosixLedgerStore(tmp)))
        self.assertEqual(receipts[0], receipts[1])

    def test_the_cli_refuses_six_field_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "receipt.json"
            source.write_text(json.dumps(repo_receipt(1)))
            org = Path(tmp) / "org"
            env = {**os.environ, "STEGVERSE_ORG_LEDGER_ROOT": str(org)}
            for extra, code in (([], "HB_EPOCH_NOT_SUPPLIED"), (["--hb-epoch", "+33"], "HB_EPOCH_INVALID")):
                with self.subTest(extra=extra):
                    run = subprocess.run([sys.executable, "-B", str(AGG), "--repo-receipt", str(source),
                                          "--predecessor-org-state-sha256", "GENESIS",
                                          "--successor-org-state-sha256", STATE_AFTER, *extra],
                                         capture_output=True, text=True, env=env)
                    self.assertEqual(run.returncode, 1, run.stderr)
                    refusal = json.loads(run.stdout)
                    self.assertEqual(refusal["failure_code"], code)
                    self.assertTrue(all(refusal.get(field) for field in SIX))
                    self.assertFalse(org.exists() and documents(org))


class CrossingCarriesTheEpoch(unittest.TestCase):
    """org-runtime/crossing.py records only at a supplied epoch, on neither ledger otherwise."""

    def test_record_without_an_epoch_writes_neither_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, org = Path(tmp) / "repo", Path(tmp) / "org"
            with mock.patch.dict(os.environ, {"STEGVERSE_REPO_LEDGER_ROOT": str(repo),
                                              "STEGVERSE_ORG_LEDGER_ROOT": str(org)}):
                cspec = importlib.util.spec_from_file_location("g4_crossing", ROOT / "org-runtime/crossing.py")
                crossing = importlib.util.module_from_spec(cspec)
                cspec.loader.exec_module(crossing)
                for epoch in (None, "3_3"):
                    with self.subTest(epoch=epoch):
                        with self.assertRaises(crossing.organization_ledger.OrgLedgerEpochRefused):
                            crossing.open_organization_ledger(hb_epoch=epoch)
                        self.assertFalse(repo.exists() and documents(repo))
                        self.assertFalse(org.exists() and documents(org))


if __name__ == "__main__":
    unittest.main()
