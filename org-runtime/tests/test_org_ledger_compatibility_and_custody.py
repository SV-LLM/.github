"""SV-LLM migration to the StegVerse-org reference: wrapper (T5) and organization record parameterization (T6).

ORGANIZATION-ROLE-REFERENCE-MIGRATION-FINAL-REVIEW-002. The temporary
aggregate_transition wrapper keeps SV-LLM's caller shape over the reference
append() and declares the legacy state-digest rule. Organization records are published per
organization transition, with this organization's identity only.
"""
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agg = load("svllm_org_ledger", "resident-runtime/aggregate_repo_transition.py")
ledger = load("svllm_ledger_store", "resident-runtime/ledger_store.py")
record = load("svllm_organization_record", "resident-runtime/submit_org_transition_to_master_records.py")


def repo_receipt(number):
    body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": "SV-LLM/sandbox",
            "transition_id": "wrapper-" + str(number)}
    return {**body, "receipt_sha256": agg.sha(body)}


class Wrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ledger.PosixLedgerStore(self.tmp.name)

    def test_default_on_empty_ledger_fails_closed_without_genesis(self):
        with self.assertRaises(agg.OrgLedgerAppendRefused) as refused:
            agg.aggregate_transition(repo_receipt(1), store=self.store)
        self.assertEqual((refused.exception.disposition, refused.exception.failed_predicate),
                         ("FAIL_CLOSED", "ORG_LEDGER_GENESIS_NOT_DECLARED"))
        self.assertEqual(sorted(Path(self.tmp.name).rglob("*.json")), [])

    def test_T5_legacy_rule_is_declared_and_chain_is_preserved(self):
        first = agg.aggregate_transition(repo_receipt(1), org_transition_class="ORGANIZATION_INGRESS_MATERIALIZED",
                                         genesis=True, boundary_evidence={"source": "SV-LLM/sandbox"}, store=self.store)
        self.assertIs(first["chain_genesis"], True)
        self.assertIsNone(first["predecessor_org_state_sha256"])
        self.assertEqual(first["successor_org_state_sha256"], first["source_transition_sha256"])
        self.assertEqual(first["boundary_evidence"]["state_digest_rule"], "SV_LLM_LEGACY_RECEIPT_CHAIN")
        self.assertEqual(first["boundary_evidence"]["state_digest_rule_fields"], ["successor_org_state_sha256"])
        self.assertEqual(first["boundary_evidence"]["source"], "SV-LLM/sandbox")
        second = agg.aggregate_transition(repo_receipt(2), org_transition_class="SANDBOX_WORK_ADMITTED", store=self.store)
        # Legacy rule: predecessor = the receipt it follows; successor = its source digest.
        self.assertEqual(second["predecessor_org_state_sha256"], first["receipt_sha256"])
        self.assertEqual(second["previous_receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(second["successor_org_state_sha256"], second["source_transition_sha256"])
        self.assertEqual(second["boundary_evidence"]["state_digest_rule_fields"],
                         ["predecessor_org_state_sha256", "successor_org_state_sha256"])
        self.assertIn("hb_reference", second)
        self.assertNotIn("observed_at", second)
        self.assertEqual(self.store.get(ledger.source_key(second["source_transition_sha256"])), repo_receipt(2))
        self.assertEqual(self.store.get(ledger.receipt_key(second["receipt_sha256"])), second)

    def test_explicit_digests_carry_no_legacy_rule(self):
        agg.aggregate_transition(repo_receipt(1), genesis=True, store=self.store)
        explicit = agg.aggregate_transition(repo_receipt(2), predecessor_org_state_sha256="sha256:" + "a" * 64,
                                            successor_org_state_sha256="sha256:" + "b" * 64, store=self.store)
        self.assertNotIn("state_digest_rule", explicit["boundary_evidence"])

    def test_genesis_refusals_propagate_unchanged(self):
        agg.aggregate_transition(repo_receipt(1), genesis=True, store=self.store)
        with self.assertRaises(agg.OrgLedgerAppendRefused) as refused:
            agg.aggregate_transition(repo_receipt(2), genesis=True, store=self.store)
        self.assertEqual(refused.exception.disposition, "DENY")
        with self.assertRaises(agg.OrgLedgerAppendRefused) as refused:
            agg.aggregate_transition(repo_receipt(3), genesis=True, predecessor_org_state_sha256="sha256:" + "a" * 64,
                                     store=self.store)
        self.assertEqual(refused.exception.failed_predicate, "ORG_LEDGER_GENESIS_WITH_EXPLICIT_PREDECESSOR")

    def test_no_dangling_batch_custody_dependency(self):
        text = (ROOT / "resident-runtime/aggregate_repo_transition.py").read_text()
        self.assertNotIn("organization_batch_custody", text)


class OrganizationRecord(unittest.TestCase):
    STANDING = {"mode": "GENESIS", "node_ref": "sv-llm-test", "predecessor": None}

    def segment(self, count):
        with tempfile.TemporaryDirectory() as root:
            store = ledger.PosixLedgerStore(root)
            first = agg.aggregate_transition(repo_receipt(1), genesis=True, store=store)
            return [first] + [agg.aggregate_transition(repo_receipt(n), store=store) for n in range(2, count + 1)]

    def build(self, receipts, standing=None):
        return record.build_released_batch_packet(receipts, "sha256:" + "1" * 64, "sha256:" + "2" * 64, {},
                                                  self.STANDING if standing is None else standing)

    def test_T6_organization_record_packet_carries_only_this_organizations_identity(self):
        packet = self.build(self.segment(1))
        text = json.dumps(packet)
        self.assertEqual(record.organization(), "SV-LLM")
        self.assertEqual(record.origin_service("SV-LLM"), "sv-llm.org-control")
        self.assertIn('"SV-LLM"', text)
        self.assertIn("sv-llm.org-control", text)
        self.assertIn('"organization.ecosystem-transition-ledger"', text)
        self.assertNotIn("master-records.ecosystem-transition-ledger", text)
        self.assertNotIn("StegVerse-org", text)
        self.assertNotIn("stegverse-org", text)
        self.assertIn('"RECORD_RELEASED_ORGANIZATION_BATCH"', text)
        self.assertIn('"ecosystem.transition.organization-record.v1"', text)
        self.assertNotIn("custody", text.lower())

    def test_master_records_receives_a_released_batch_as_downstream_non_gating_evidence(self):
        receipts = self.segment(3)
        payload = self.build(receipts)["payload"]
        self.assertEqual(payload["recorder_role"], "RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER")
        self.assertIs(payload["gates_organization_runtime_reality"], False)
        self.assertIs(payload["awaited_by_organization"], False)
        self.assertIs(payload["authority_transfer"], False)
        batch = payload["released_batch"]
        self.assertEqual(batch["release_predecessor"], "VERIFIED_ORGANIZATION_RECEIPT_CHAIN_SEGMENT")
        self.assertEqual(batch["receipt_count"], 3)
        self.assertEqual(batch["receipts"], receipts)
        self.assertEqual(batch["segment_first_receipt_sha256"], receipts[0]["receipt_sha256"])
        self.assertEqual(batch["segment_head_receipt_sha256"], receipts[-1]["receipt_sha256"])
        self.assertIsNone(batch["segment_base_previous_receipt_sha256"])

    def assertDenied(self, predicate, call):
        with self.assertRaises(record.ReleaseRefused) as refused:
            call()
        refusal = refused.exception.refusal
        self.assertEqual(refusal["disposition"], "DENY")
        self.assertEqual(refusal["failed_predicate"], predicate)
        for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                      "owning_existing_goal", "next_attempt"):
            self.assertTrue(refusal[field], field)
        self.assertIs(refusal["gates_organization_runtime_reality"], False)

    def test_an_unverified_segment_is_refused_with_the_six_fields(self):
        receipts = self.segment(3)
        self.assertDenied("RELEASED_BATCH_IS_NOT_EMPTY", lambda: self.build([]))
        self.assertDenied("ORGANIZATION_RECEIPT_CHAIN_SEGMENT_IS_CONTIGUOUS",
                          lambda: self.build([receipts[0], receipts[2]]))
        self.assertDenied("ORGANIZATION_RECEIPT_CHAIN_SEGMENT_IS_CONTIGUOUS",
                          lambda: self.build([receipts[1], receipts[0]]))
        tampered = {**receipts[1], "successor_org_state_sha256": "sha256:" + "f" * 64}
        self.assertDenied("ORGANIZATION_RECEIPT_SELF_DIGEST_MATCHES", lambda: self.build([receipts[0], tampered]))
        self.assertDenied("ORGANIZATION_RECEIPT_SCHEMA_MATCHES",
                          lambda: self.build([{**receipts[0], "schema": "stegverse.repo-transition-receipt/v1"}]))

    def test_organization_record_refuses_foreign_receipt_and_defaulted_standing(self):
        foreign = {"schema": "stegverse.organization-transition-receipt/v1", "organization": "StegVerse-org"}
        with self.assertRaisesRegex(SystemExit, "owner mismatch"):
            self.build([foreign], {"predecessor": None})
        with self.assertRaisesRegex(SystemExit, "standing must declare"):
            self.build(self.segment(1), {})

    def test_source_names_no_other_organization(self):
        text = (ROOT / "resident-runtime/submit_org_transition_to_master_records.py").read_text()
        self.assertNotIn('"StegVerse-org"', text)
        self.assertNotIn("stegverse-org.", text)



class MasterRecordsRoleAudit(unittest.TestCase):
    """data/master-records-role-audit.json is re-measured, so an occurrence added later fails here."""

    AUDIT = "data/master-records-role-audit.json"
    PATTERN = re.compile(r"master[-_ ]?records", re.I)

    def measured(self):
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True)
        counts = {}
        for name in tracked.stdout.split():
            if name == self.AUDIT:
                continue
            hits = 1 if self.PATTERN.search(name) else 0
            try:
                hits += len(self.PATTERN.findall((ROOT / name).read_text()))
            except (UnicodeDecodeError, FileNotFoundError):
                pass
            if hits:
                counts[name] = hits
        return counts

    def test_the_audit_matches_the_tree_and_leaves_nothing_improper(self):
        audit = json.loads((ROOT / self.AUDIT).read_text())
        after = audit["after"]
        recorded = {}
        for row in after:
            recorded[row["file"]] = recorded.get(row["file"], 0) + 1
        self.assertEqual(recorded, self.measured())
        self.assertEqual(audit["counts"]["after"]["TOTAL"], len(after))
        self.assertEqual([row for row in after if row["classification"].startswith("IMPROPER")], [])
        self.assertEqual(audit["counts"]["after"]["IMPROPER_CODE"] + audit["counts"]["after"]["IMPROPER_DOC"], 0)
        allowed = {"PROPER", "IMPROPER_CODE", "IMPROPER_DOC", "HISTORICAL_EVIDENCE", "NAMING_ONLY"}
        for row in audit["before"]:
            self.assertIn(row["classification"], allowed)
            if row["classification"].startswith("IMPROPER"):
                self.assertTrue(row.get("remediation"), row)


if __name__ == "__main__":
    unittest.main()
