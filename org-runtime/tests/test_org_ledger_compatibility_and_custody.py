"""SV-LLM migration to the StegVerse-org reference: wrapper (T5) and organization record parameterization (T6).

ORGANIZATION-ROLE-REFERENCE-MIGRATION-FINAL-REVIEW-002. The temporary
aggregate_transition wrapper keeps SV-LLM's caller shape over the reference
append() and declares the legacy state-digest rule. Organization records are published per
organization transition, with this organization's identity only.
"""
import importlib.util
import json
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
    def test_T6_organization_record_packet_carries_only_this_organizations_identity(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = agg.aggregate_transition(repo_receipt(1), genesis=True, store=ledger.PosixLedgerStore(root))
        packet = record.build_organization_record_packet(receipt, "sha256:" + "1" * 64, "sha256:" + "2" * 64, {},
                                                         {"mode": "GENESIS", "node_ref": "sv-llm-test", "predecessor": None})
        text = json.dumps(packet)
        self.assertEqual(record.organization(), "SV-LLM")
        self.assertEqual(record.origin_service("SV-LLM"), "sv-llm.org-control")
        self.assertIn('"SV-LLM"', text)
        self.assertIn("sv-llm.org-control", text)
        self.assertIn("master-records.ecosystem-transition-ledger", text)
        self.assertNotIn("StegVerse-org", text)
        self.assertNotIn("stegverse-org", text)
        self.assertIn('"ORGANIZATION_RECORD_ORGANIZATION_TRANSITION"', text)
        self.assertIn('"ecosystem.transition.organization-record.v1"', text)
        self.assertNotIn("custody", text.lower())

    def test_organization_record_refuses_foreign_receipt_and_defaulted_standing(self):
        foreign = {"schema": "stegverse.organization-transition-receipt/v1", "organization": "StegVerse-org"}
        with self.assertRaisesRegex(SystemExit, "owner mismatch"):
            record.build_organization_record_packet(foreign, "sha256:" + "1" * 64, "sha256:" + "2" * 64, {}, {"predecessor": None})
        own = {"schema": "stegverse.organization-transition-receipt/v1", "organization": "SV-LLM"}
        with self.assertRaisesRegex(SystemExit, "standing must declare"):
            record.build_organization_record_packet(own, "sha256:" + "1" * 64, "sha256:" + "2" * 64, {}, {})

    def test_source_names_no_other_organization(self):
        text = (ROOT / "resident-runtime/submit_org_transition_to_master_records.py").read_text()
        self.assertNotIn('"StegVerse-org"', text)
        self.assertNotIn("stegverse-org.", text)


if __name__ == "__main__":
    unittest.main()
