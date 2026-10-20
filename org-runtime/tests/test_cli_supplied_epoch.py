#!/usr/bin/env python3
"""Every --hb-epoch command line hands the raw text to the kernel's supplied-epoch rule.

B-P36c. argparse `type=int` (or any int() before the rule) read '+33',
fullwidth '３３', Arabic-Indic '٣٣' and ' 33' as 33 and then wrote a receipt. Each CLI that can
append now takes the epoch as text and refuses an absent or invalid one with
kernel.writer_epoch_refusal's six-field FAIL_CLOSED, exits non-zero, and
writes nothing: no ledger receipt and no --out file. '4096' is admitted.

Every run supplies both ledger roots in a scratch directory that must stay
empty on a refusal. The manifest ingress imports the StegVerse SDK, located by
STEGVERSE_SDK_ROOT (a checkout at the pin) or ./sdk; without it that CLI is
skipped, and with STEGVERSE_SDK_REQUIRED=1 (CI) a missing SDK fails. Source
validation only; no authority effect is claimed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "0" * 64
REFUSED = ("+33", "３３", "٣٣", "٣３", " 33", "True", "abc", "33.7", "33.0", "31", None)
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")

# Each CLI that appends a receipt, with the arguments it needs to get past
# argparse. `{out}` is the --out file a refusal must not write.
CLIS = {
    "emit": [".stegverse/transition-ledger/emit.py", "--transition-id", "b-p36c", "--transition-class",
             "B_P36C_TEST", "--predecessor-state-sha256", DIGEST, "--successor-state-sha256", DIGEST],
    "aggregate": ["resident-runtime/aggregate_repo_transition.py", "--repo-receipt", "{out}.receipt.json",
                  "--predecessor-org-state-sha256", "GENESIS", "--successor-org-state-sha256", DIGEST],
    "crossing-open-ledger": ["org-runtime/crossing.py", "open-ledger"],
    "crossing-egress": ["org-runtime/crossing.py", "egress", "--manifest", "{out}.manifest.json",
                        "--standing", "{out}.standing.json", "--mesh-root", "{out}.mesh"],
    "crossing-ingress": ["org-runtime/crossing.py", "ingress", "--mesh-root", "{out}.mesh",
                         "--node-state-root", "{out}.node"],
    "authentic-live-lane": ["org-runtime/authentic_live_lane.py", "prepare", "--target", "{out}.target.json",
                            "--out", "{out}"],
    "intr-destination-self-close": ["resident-runtime/intr_destination_ingress.py", "--self-close",
                                    "--registry", "org-boundary/registry/services.json",
                                    "--communication-id", "b-p36c", "--packet-id", "b-p36c", "--out", "{out}"],
    "intr-destination-receive": ["resident-runtime/intr_destination_ingress.py", "--payload", "{out}.payload.json",
                                 "--registry", "org-boundary/registry/services.json", "--out", "{out}"],
    "egress-boundary": ["resident-runtime/organization_egress_boundary.py", "--destination-organization",
                        "StegVerse-org", "--payload", "{out}.payload.json", "--standing", "{out}.standing.json",
                        "--out", "{out}"],
    "egress-boundary-close": ["resident-runtime/organization_egress_boundary.py", "--destination-organization",
                              "StegVerse-org", "--close", "--packet-id", "b-p36c", "--communication-id", "b-p36c",
                              "--out", "{out}"],
    "manifest-ingress": ["resident-runtime/organization_manifest_ingress.py", "--manifest", "{out}.manifest.json",
                         "--registry", "org-boundary/registry/services.json", "--out", "{out}"],
}


def _sdk_root():
    declared = os.environ.get("STEGVERSE_SDK_ROOT")
    for candidate in ([Path(declared)] if declared else []) + [ROOT / "sdk"]:
        if (candidate / "stegverse/manifest_builder.py").is_file():
            return candidate.resolve()
    return None


SDK_ROOT = _sdk_root()
SDK_REQUIRED = os.environ.get("STEGVERSE_SDK_REQUIRED") == "1"
NEEDS_SDK = {"manifest-ingress"}


def files_under(path):
    return sorted(str(p) for p in Path(path).rglob("*") if p.is_file())


class CliEpochIsTheKernelRule(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.ledgers = self.base / "ledgers"
        self.env = dict(os.environ, STEGVERSE_REPO_LEDGER_ROOT=str(self.ledgers / "repo"),
                        STEGVERSE_ORG_LEDGER_ROOT=str(self.ledgers / "org"),
                        STEGVERSE_ORG_FEDERATION_ROOT=str(self.ledgers / "mesh"))
        if SDK_ROOT is not None:
            self.env["PYTHONPATH"] = os.pathsep.join(
                filter(None, [str(SDK_ROOT), self.env.get("PYTHONPATH")]))
        self.assertTrue(SDK_ROOT or not SDK_REQUIRED, "STEGVERSE_SDK_REQUIRED=1 but no SDK checkout was found")
        self.clis = {name: argv for name, argv in CLIS.items() if SDK_ROOT or name not in NEEDS_SDK}

    def run_cli(self, argv, epoch):
        out = str(self.base / "out.json")
        args = [a.replace("{out}", out) for a in argv]
        if epoch is not None:
            args += ["--hb-epoch", epoch]
        completed = subprocess.run([sys.executable, "-B", *args], capture_output=True, text=True,
                                   env=self.env, cwd=ROOT, timeout=120)
        return completed, Path(out)

    def test_an_absent_or_coerced_epoch_is_refused_and_writes_nothing(self):
        for name, argv in self.clis.items():
            for epoch in REFUSED:
                with self.subTest(cli=name, epoch=epoch):
                    completed, out = self.run_cli(argv, epoch)
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    refusal = json.loads(completed.stdout)
                    self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
                    self.assertEqual(refusal["failure_code"],
                                     "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID")
                    self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
                    for field in SIX_FIELDS:
                        self.assertTrue(refusal[field], field)
                    self.assertIn("--hb-epoch", refusal["retry_entrypoint"])
                    self.assertIs(refusal["derived_from_clock"], False)
                    self.assertIs(refusal["consequence_committed"], False)
                    self.assertFalse(out.exists())
                    self.assertEqual(files_under(self.base), [])

    def test_a_supplied_epoch_passes_the_rule_on_every_cli(self):
        for name, argv in self.clis.items():
            with self.subTest(cli=name):
                completed, _ = self.run_cli(argv, "4096")
                self.assertNotIn("SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH", completed.stdout + completed.stderr)

    def test_4096_is_written_on_both_ledgers(self):
        completed, _ = self.run_cli(CLIS["emit"], "4096")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        repo_receipt = json.loads(completed.stdout)
        self.assertEqual(repo_receipt["hb_reference"]["epoch"], 4096)
        receipt_path = self.base / "out.json.receipt.json"
        receipt_path.write_text(completed.stdout)
        completed, _ = self.run_cli(CLIS["aggregate"], "4096")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["hb_reference"]["epoch"], 4096)

    def test_4096_opens_the_organization_ledger(self):
        completed, _ = self.run_cli(CLIS["crossing-open-ledger"], "4096")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["org_receipt_sha256"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
