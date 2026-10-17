"""Exact StegVerse-org duplication: adoption proof and the organization's authentic-run steps.

SV-LLM-ORGANIZATION-ROLE-EXACT-STEGVERSE-ORG-DUPLICATION-001 (D1-D5, X4, X1
companion). The adopted ledger files must equal the recorded reference, with
only the declared wrapper inserted; any other change is FAIL_CLOSED
REFERENCE_ADOPTION_MISMATCH. The organization's steps open the execution-scoped
reference ledger with explicit GENESIS and append one parent whose outcome
names the Sandbox lane, all in one ledger root.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TARGET = {"target_id": "stegverse.integration.llm-browser-test.v1"}


def load(name, path, root=ROOT):
    spec = importlib.util.spec_from_file_location(name, root / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adoption = load("svllm_reference_adoption", "resident-runtime/reference_adoption.py")


class ReferenceAdoption(unittest.TestCase):
    def copy(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return root

    def test_adopted_tree_matches_the_recorded_reference(self):
        result = adoption.verify()
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual(result["reference"]["repository"], "StegVerse-org/.github")
        self.assertEqual(result["authority_effect"], "NONE")

    def test_every_adopted_surface_is_recorded(self):
        record = json.loads(adoption.RECORD.read_text())
        self.assertEqual(set(record["files"]), {"resident-runtime/ledger_store.py", ".stegverse/transition-ledger/emit.py",
                                                "resident-runtime/aggregate_repo_transition.py",
                                                "resident-runtime/organization_ledger_readback.py",
                                                # SV-LLM/.github#30 W4: the manifest-directed append path.
                                                "resident-runtime/organization_manifest_ingress.py",
                                                "resident-runtime/sdk_manifest_crossing.py",
                                                "resident-runtime/manifest_directed_run_inputs.py",
                                                "org-boundary/runtime/process_boundary.py",
                                                "org-boundary/runtime/intr_transport.py",
                                                "org-boundary/runtime/capability_ingress.py",
                                                "org-boundary/runtime/node_standing.py"})
        self.assertEqual(set(record["adapted"]), {".github/workflows/organization-ledger-transition.yml"})
        rules = {entry["rule"] for entry in record["files"].values()}
        self.assertEqual(rules, {"byte_identical", "declared_insertion", "declared_substitutions"})
        self.assertEqual(set(record["contracts"]), {".stegverse/transition-ledger/org-contract.json",
                                                    ".stegverse/transition-ledger/contract.json"})

    def assertMismatch(self, root, fragment):
        result = adoption.verify(root=root)
        self.assertEqual((result["disposition"], result["failed_predicate"]), ("FAIL_CLOSED", "REFERENCE_ADOPTION_MISMATCH"))
        self.assertTrue(any(fragment in problem for problem in result["mismatches"]), result["mismatches"])

    def test_a_changed_byte_identical_file_is_a_mismatch(self):
        root = self.copy()
        path = root / "resident-runtime/ledger_store.py"
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertMismatch(root, "ledger_store.py: differs from the reference")

    def test_a_changed_reference_portion_around_the_wrapper_is_a_mismatch(self):
        root = self.copy()
        path = root / "resident-runtime/aggregate_repo_transition.py"
        path.write_text(path.read_text().replace("ORG_LEDGER_APPEND_CONTENTION_EXHAUSTED", "CHANGED", 1))
        self.assertMismatch(root, "aggregate_repo_transition.py")

    def test_a_changed_wrapper_is_a_mismatch(self):
        root = self.copy()
        path = root / "resident-runtime/aggregate_repo_transition.py"
        path.write_text(path.read_text().replace('STATE_DIGEST_RULE = "SV_LLM_LEGACY_RECEIPT_CHAIN"',
                                                 'STATE_DIGEST_RULE = "SV_LLM_LEGACY_RECEIPT_CHAIX"'))
        self.assertMismatch(root, "declared insertion missing or changed")

    def test_a_changed_byte_outside_a_declared_substitution_is_a_mismatch(self):
        root = self.copy()
        path = root / "resident-runtime/organization_manifest_ingress.py"
        path.write_text(path.read_text().replace('ORGANIZATION_REPLAY = "PASS"', 'ORGANIZATION_REPLAY = "FAIL"'))
        self.assertMismatch(root, "organization_manifest_ingress.py: local bytes are not the recorded adaptation")
        self.assertMismatch(root, "organization_manifest_ingress.py: differs from the reference")

    def test_an_undeclared_identity_substitution_is_a_mismatch(self):
        # One more occurrence of the declared local text is not the recorded count.
        root = self.copy()
        path = root / "resident-runtime/organization_manifest_ingress.py"
        path.write_text(path.read_text().replace('"origin_organization": ORGANIZATION,',
                                                 '"origin_organization": ORGANIZATION, "x": ORGANIZATION,'))
        self.assertMismatch(root, "declared substitution missing or changed")

    def test_the_substitutions_reverse_to_the_reference_bytes(self):
        record = json.loads(adoption.RECORD.read_text())
        entry = record["files"]["resident-runtime/organization_manifest_ingress.py"]
        data = (ROOT / "resident-runtime/organization_manifest_ingress.py").read_bytes()
        reference, problems = adoption.adopted_reference_bytes("ingress", data, entry)
        self.assertEqual(problems, [])
        self.assertEqual(adoption.digest(reference), entry["reference_sha256"])
        self.assertIn(b'OWNER_REPOSITORY = "StegVerse-org/.github"', reference)
        self.assertNotIn(b"StegVerse-org", data)

    def test_contracts_may_differ_only_in_their_own_name(self):
        root = self.copy()
        path = root / ".stegverse/transition-ledger/org-contract.json"
        contract = json.loads(path.read_text())
        contract["organization"] = "Another-Org"
        path.write_text(json.dumps(contract))
        self.assertEqual(adoption.verify(root=root)["disposition"], "ALLOW")
        contract["always_on_receiver_required"] = True
        path.write_text(json.dumps(contract))
        self.assertMismatch(root, "org-contract.json: differs from the reference beyond organization")

    def test_the_repository_ledger_is_the_reference_emitter(self):
        receipt_fields = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())
        self.assertNotIn("observed_at", json.dumps(receipt_fields))
        # The reference emitter opens whatever store the supplied location names
        # (a POSIX root, or the designated git ref), never one of its own.
        self.assertIn("ledger_store.open_store(lr())", (ROOT / ".stegverse/transition-ledger/emit.py").read_text())


class OrganizationSteps(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.env = mock.patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": str(self.tmp / "org"),
                                                "STEGVERSE_REPO_LEDGER_ROOT": str(self.tmp / "repo")})
        self.env.start()
        self.addCleanup(self.env.stop)
        sys.path.insert(0, str(ROOT / "org-runtime"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.steps = load("svllm_authentic_steps", "org-runtime/authentic_live_lane.py")
        self.agg = load("svllm_steps_agg", "resident-runtime/aggregate_repo_transition.py")
        self.store = self.agg.open_store(self.agg.ledger_root())

    def test_open_then_parent_in_one_execution_scoped_root(self):
        result = self.steps.prepare(TARGET)
        genesis = self.store.get(self.agg.receipt_key(result["ledger_opened_org_receipt_sha256"]))
        parent = self.store.get(self.agg.receipt_key(result["parent_org_receipt_sha256"]))
        self.assertIs(genesis["chain_genesis"], True)
        self.assertEqual(genesis["org_transition_class"], "ORGANIZATION_LEDGER_OPENED")
        self.assertNotIn("chain_genesis", parent)
        self.assertEqual(parent["predecessor_org_state_sha256"], genesis["receipt_sha256"])
        self.assertEqual(self.store.get(self.agg.HEAD_KEY)["receipt_sha256"], parent["receipt_sha256"])
        source = self.store.get(self.agg.source_key(parent["source_transition_sha256"]))
        self.assertEqual(source["evidence"], {"disposition": "ALLOW", "intended_action": "STEGBROWSER_LIVE_PATH_CONFORMANCE",
                                              "target_id": TARGET["target_id"]})
        self.assertEqual(source["successor_state_sha256"], self.agg.sha(source["evidence"]))
        self.assertEqual(source["repository"], "SV-LLM/.github")
        self.assertEqual(result["ledger_persistence"], "EXECUTION_SCOPED_SAME_AS_REFERENCE")

    def test_a_second_run_on_the_same_root_continues_the_chain_without_a_second_genesis(self):
        first = self.steps.prepare(TARGET)
        before = sorted(self.store.list_prefix(self.agg.RECEIPT_PREFIX))
        second = self.steps.prepare(TARGET)
        self.assertIsNone(second["ledger_opened_org_receipt_sha256"])
        self.assertEqual(second["continued_from_org_receipt_sha256"], first["parent_org_receipt_sha256"])
        parent = self.store.get(self.agg.receipt_key(second["parent_org_receipt_sha256"]))
        self.assertNotIn("chain_genesis", parent)
        self.assertEqual(parent["predecessor_org_state_sha256"], first["parent_org_receipt_sha256"])
        # Exactly one receipt was added, and the chain still has one genesis.
        self.assertEqual(len(self.store.list_prefix(self.agg.RECEIPT_PREFIX)), len(before) + 1)
        chain, cursor = [], self.store.get(self.agg.HEAD_KEY)["receipt_sha256"]
        while cursor:
            receipt = self.store.get(self.agg.receipt_key(cursor))
            chain.append(receipt)
            cursor = receipt.get("predecessor_org_state_sha256") if not receipt.get("chain_genesis") else None
        self.assertEqual([bool(r.get("chain_genesis")) for r in chain], [False, False, True])

    def test_on_the_designated_git_ref_the_chain_is_durable_across_runs(self):
        # The organization ledger bound as org-contract.json designates it: a
        # git ref, with the repository chain in its own subtree (contract.json).
        contract = json.loads((ROOT / ".stegverse/transition-ledger/org-contract.json").read_text())
        location = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())["repository_ledger_location"]
        self.assertEqual(contract["organization_ledger_repository"], "SV-LLM/.github")
        self.assertEqual(location["ref"], contract["organization_ledger_ref"])
        self.assertEqual(location["namespace"], "repository-ledger/SV-LLM/.github")
        organization = "git+" + str(self.tmp / "ledger.git") + "#" + contract["organization_ledger_ref"]
        with mock.patch.dict(os.environ, {"STEGVERSE_ORG_LEDGER_ROOT": organization,
                                          "STEGVERSE_REPO_LEDGER_ROOT": organization + ":" + location["namespace"]}):
            first = self.steps.prepare(TARGET)   # one run: genesis, then the parent
            second = self.steps.prepare(TARGET)  # the next run: continues from the published HEAD
            store = self.agg.open_store(self.agg.ledger_root())
        self.assertEqual(store.kind, "GIT_REF")
        self.assertEqual(first["ledger_persistence"], "DURABLE_GIT_REF_SAME_AS_REFERENCE")
        self.assertTrue(first["ledger_opened_org_receipt_sha256"])
        self.assertEqual(second["continued_from_org_receipt_sha256"], first["parent_org_receipt_sha256"])
        self.assertEqual(store.get(self.agg.HEAD_KEY)["receipt_sha256"], second["parent_org_receipt_sha256"])
        # The repository chain lives in the subtree and links across the two runs.
        repository = self.agg.open_store(self.agg.parse_locator(organization + ":" + location["namespace"]))
        head = repository.get(self.agg.HEAD_KEY)
        self.assertEqual(head["receipt_sha256"], second["parent_repo_receipt_sha256"])
        self.assertEqual(repository.get(self.agg.receipt_key(head["receipt_sha256"]))["previous_receipt_sha256"],
                         first["parent_repo_receipt_sha256"])
        # Nothing was written under the POSIX roots this case does not use.
        self.assertFalse((self.tmp / "org").exists())

    def test_a_target_without_an_id_is_refused_before_any_write(self):
        with self.assertRaisesRegex(SystemExit, "LIVE_TARGET_ID_REQUIRED"):
            self.steps.prepare({})
        self.assertIsNone(self.store.get(self.agg.HEAD_KEY))


class LiveLanesHaveNoExternalMachine(unittest.TestCase):
    """GitHub-hosted runners are external machines (StegVerse-Labs/.github
    data/task-registry-global-invariants.json): no workflow runs a live lane,
    and the lanes that remain as code hold SV-LLM-EXEMPTION-002."""

    def test_no_workflow_runs_a_live_lane_or_installs_a_browser(self):
        workflows = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
        self.assertTrue(workflows)
        for path in workflows:
            text = path.read_text()
            for needle in ("authentic_live_lane", "run_live_llm", "playwright"):
                self.assertNotIn(needle, text.lower(), path.name)

    def test_the_lane_code_holds_a_registered_exemption(self):
        register = json.loads((ROOT / "data/organization-role-exemption-register.json").read_text())
        exemption, = [e for e in register["exemptions"] if e["exemption_id"] == "SV-LLM-EXEMPTION-002"]
        for field in register["required_fields"]:
            self.assertTrue(exemption.get(field), field)
        self.assertNotEqual(exemption["disposition"], "ALLOW")
        self.assertIs(exemption["exemption_grants_authority"], False)
        self.assertIn("org-runtime/authentic_live_lane.py", exemption["surface"])
        self.assertIn("no workflow", exemption["surface"])
        for justification in register["prohibited_justifications"]:
            self.assertNotIn(justification, json.dumps(exemption))

    def test_the_llm_v1_provider_wait_is_gone_and_its_exemption_retired(self):
        register = json.loads((ROOT / "data/organization-role-exemption-register.json").read_text())
        self.assertNotIn("SV-LLM-EXEMPTION-003", [e["exemption_id"] for e in register["exemptions"]])


class NoBrowserEngineOrTestFramework(unittest.TestCase):
    """SV-LLM/.github#30 W1/W2: no surface of this repository depends on a
    browser engine or on pytest; every suite runs on the standard library."""

    def tracked(self):
        # This repository's own files only: CI checks other repositories out
        # inside the workspace (stegverse-org-reference), and they are not ours.
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                                capture_output=True).stdout.decode().split("\0")
        return [ROOT / name for name in listed if name]

    def surfaces(self):
        this = Path(__file__).resolve()
        for path in self.tracked():
            if not path.is_file() or path.resolve() == this:
                continue
            try:
                yield path, path.read_text()
            except UnicodeDecodeError:
                continue

    def test_no_surface_names_a_browser_engine(self):
        checked = 0
        for path, text in self.surfaces():
            checked += 1
            for needle in ("playwright", "chromium"):
                self.assertNotIn(needle, text.lower(), str(path.relative_to(ROOT)))
        self.assertGreater(checked, 0)

    def test_no_surface_imports_or_installs_pytest(self):
        pattern = re.compile(r"^\s*(import pytest|from pytest\b)|pip install[^\n]*\bpytest\b|\bpytest\s+-", re.M)
        for path, text in self.surfaces():
            self.assertIsNone(pattern.search(text), str(path.relative_to(ROOT)))

    def test_no_dependency_manifest_exists(self):
        for name in ("requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile*",
                     "package.json", "*.lock", "conftest.py", "pytest.ini", "tox.ini"):
            found = [p for p in self.tracked() if p.match(name)]
            self.assertEqual(found, [], name)


class RuntimeObservationHoldsARegisteredExemption(unittest.TestCase):
    """Runtime reality is an organization receipt appended by manifest-directed
    append. The append path has one read-back receipt (W04); W4's Sandbox
    observation and W5/W7/W13 have none, so they hold SV-LLM-EXEMPTION-004 and
    are never claimed from source or CI."""

    def test_without_a_transition_request_path_the_exemption_is_registered(self):
        register = json.loads((ROOT / "data/organization-role-exemption-register.json").read_text())
        has_path = (ROOT / ".stegverse/transition-requests").is_dir() and any(
            "transition-requests" in p.read_text() for p in (ROOT / ".github/workflows").glob("*.y*ml"))
        ids = [e["exemption_id"] for e in register["exemptions"]]
        # The exemption is retired only by a path whose receipt is read back.
        self.assertTrue(has_path or "SV-LLM-EXEMPTION-004" in ids)
        if "SV-LLM-EXEMPTION-004" not in ids:
            return
        exemption, = [e for e in register["exemptions"] if e["exemption_id"] == "SV-LLM-EXEMPTION-004"]
        for field in register["required_fields"]:
            self.assertTrue(exemption.get(field), field)
        self.assertNotEqual(exemption["disposition"], "ALLOW")
        self.assertIs(exemption["exemption_grants_authority"], False)
        for justification in register["prohibited_justifications"]:
            self.assertNotIn(justification, json.dumps(exemption))
        for workstream in ("W4", "W5", "W7", "W13"):
            self.assertIn(workstream, exemption["surface"])


if __name__ == "__main__":
    unittest.main()
