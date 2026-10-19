#!/usr/bin/env python3
"""Every inline hb_epoch gate in the ledger workflow is the kernel's six-field rule.

B-P36d. The ledger workflow takes hb_epoch as a dispatch input. Each step that
appends gates it inline before anything is received or appended. This test
finds every such gate in .github/workflows/organization-ledger-transition*.yml,
checks that no other check (a shell case, a regex, an int()) reads the epoch,
and runs each gate exactly as written:

  absent (a push, or a dispatch with HB_EPOCH unset)  HB_EPOCH_NOT_SUPPLIED
  "", "+33", " 33", "３３", "٣٣", "33.0", "31", "abc"  HB_EPOCH_INVALID
  "4096"                                              passes, prints nothing

No repository code reads STEGVERSE_HB_EPOCH; the test checks that too.
Source validation only; no authority effect is claimed.
"""
import json
import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("organization-ledger-transition*.yml"))
INVALID = ("", "+33", " 33", "３３", "٣٣", "33.0", "31", "abc")
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
GATE = re.compile(r"^\s*(python -B -c '.*writer_epoch_refusal.*) \|\| exit 1\s*$")


STEP = re.compile(r"^\s*- name: (.*)$")


def steps():
    """Each step's text, split on its `- name:` line (no YAML dependency on the runner)."""
    for workflow in WORKFLOWS:
        name, lines = None, []
        for line in workflow.read_text().splitlines() + ["- name: <end>"]:
            match = STEP.match(line)
            if match:
                if name is not None:
                    yield workflow.name, name, "\n".join(lines)
                name, lines = match.group(1).strip(), []
            elif name is not None:
                lines.append(line)


def gates():
    found = []
    for workflow, name, run in steps():
        for line in run.splitlines():
            match = GATE.match(line)
            if match:
                found.append((workflow, name, match.group(1)))
    return found


class WorkflowEpochGate(unittest.TestCase):
    def run_gate(self, command, event, epoch):
        env = {k: v for k, v in os.environ.items() if k not in ("HB_EPOCH", "GITHUB_EVENT_NAME")}
        env["GITHUB_EVENT_NAME"] = event
        if epoch is not None:
            env["HB_EPOCH"] = epoch
        return subprocess.run(["bash", "--noprofile", "--norc", "-c", command], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)

    def assertRefused(self, done, failure_code):
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        refusal = json.loads(done.stdout)
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], failure_code)
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)
        self.assertIn("organization-ledger-transition.yml", refusal["retry_entrypoint"])
        self.assertIs(refusal["derived_from_clock"], False)

    def test_each_appending_lane_has_one_kernel_gate(self):
        lanes = {name for _, name, _ in gates()}
        self.assertEqual(len(gates()), 2, gates())
        self.assertEqual(len(lanes), 2, lanes)

    def test_no_other_check_reads_the_epoch(self):
        for workflow, name, run in steps():
            for line in run.splitlines():
                if "HB_EPOCH" not in line or GATE.match(line) or line.lstrip().startswith("#"):
                    continue
                with self.subTest(workflow=workflow, step=name, line=line.strip()):
                    # The only other use hands the gated text to a CLI that applies the same rule.
                    self.assertEqual(line.strip(), '--hb-epoch "$HB_EPOCH" \\')
        for workflow in WORKFLOWS:
            text = workflow.read_text()
            self.assertNotIn('case "$HB_EPOCH"', text)
            self.assertNotRegex(text, r"int\([^)]*HB_EPOCH")

    def test_a_cli_handed_the_epoch_is_gated_first_in_its_step(self):
        for workflow, name, run in steps():
            if '--hb-epoch "$HB_EPOCH"' not in run:
                continue
            with self.subTest(workflow=workflow, step=name):
                gate_at = next(i for i, line in enumerate(run.splitlines()) if GATE.match(line))
                cli_at = next(i for i, line in enumerate(run.splitlines()) if '--hb-epoch "$HB_EPOCH"' in line)
                self.assertLess(gate_at, cli_at)

    def test_an_absent_epoch_is_not_supplied(self):
        for workflow, name, command in gates():
            for event, epoch in (("workflow_dispatch", None), ("push", ""), ("push", "4096")):
                with self.subTest(step=name, event=event, epoch=epoch):
                    self.assertRefused(self.run_gate(command, event, epoch), "HB_EPOCH_NOT_SUPPLIED")

    def test_an_invalid_dispatched_epoch_is_invalid(self):
        for workflow, name, command in gates():
            for epoch in INVALID:
                with self.subTest(step=name, epoch=epoch):
                    self.assertRefused(self.run_gate(command, "workflow_dispatch", epoch), "HB_EPOCH_INVALID")

    def test_4096_passes(self):
        for workflow, name, command in gates():
            with self.subTest(step=name):
                done = self.run_gate(command, "workflow_dispatch", "4096")
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(done.stdout, "")

    def test_no_code_reads_stegverse_hb_epoch(self):
        listed = subprocess.run(["git", "grep", "-l", "STEGVERSE_HB_EPOCH", "--", ".", ":!" + Path(__file__).name],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(listed.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
