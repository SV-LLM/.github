"""InTr paths exist only between distinct organizations (Rigel's rule, 2026-10-25).

Rule, as relayed by Coordination on StegVerse-org/.github#163: InTr paths exist only
between distinct organizations; there is never an InTr hop inside one organization.
LLM-adapter is not an InTr destination; its only InTr use is that an external
machine that has established itself as a healthy node may become an InTr endpoint.

These checks read this repository's committed InTr declarations only (no network)
and fail with the six standard fields. Owner P1 (StegVerse-org/.github#163).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORG = "SV-LLM"
GOAL = "StegVerse-org/.github#163 (P1); Rigel's rule 2026-10-25"
RETRY = "python3 -m unittest tests.test_intr_inter_org_only -v"


def six(code: str, predicate: str, repair: str, detail: object) -> str:
    return json.dumps({"disposition": "FAIL_CLOSED", "failure_code": code, "failed_predicate": predicate,
                       "required_evidence_or_repair": repair, "retry_entrypoint": RETRY,
                       "owning_existing_goal": GOAL,
                       "next_attempt": "after the declaration names two distinct organizations",
                       "detail": detail}, sort_keys=True)


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def ends(path_id: str) -> tuple[str, str]:
    pair = path_id.split(":", 1)[0]
    src, _, dst = pair.partition("->")
    return src, dst


def names_llm_adapter(value: object) -> bool:
    return "llm-adapter" in json.dumps(value).lower()


class InterOrganizationOnly(unittest.TestCase):
    def test_outbound_path_transfers_leave_this_organization(self):
        decl = load(".stegverse/intr-path-transfer/transfers.json")
        self.assertEqual(decl["source_repository"], f"{ORG}/.github")
        for row in decl["transfers"]:
            src, dst = ends(row["path_id"])
            self.assertEqual(src, ORG, six("INTR_PATH_SOURCE_IS_NOT_THIS_ORGANIZATION", "OUTBOUND_SOURCE_IS_THIS_ORGANIZATION",
                                           "declare only paths whose source is this organization", row))
            self.assertTrue(dst and dst != src, six("ORG_INTERNAL_INTR_HOP", "INTR_HOP_IS_BETWEEN_DISTINCT_ORGANIZATIONS",
                                                     "remove the row: an InTr path never stays inside one organization", row))
            self.assertFalse(names_llm_adapter(row), six("LLM_ADAPTER_AS_INTR_DESTINATION", "LLM_ADAPTER_IS_NOT_AN_INTR_DESTINATION",
                                                          "remove the row: LLM-adapter is not an InTr destination", row))

    def test_inbound_path_transfers_come_from_another_organization(self):
        decl = load(".stegverse/intr-path-transfer/inbound.json")
        for row in decl["transfers"]:
            be = row["carried"]["source_organization_receipt"]["boundary_evidence"]
            src, dst = ends(be["path_id"])
            self.assertEqual(dst, ORG, six("INTR_PATH_DESTINATION_IS_NOT_THIS_ORGANIZATION", "INBOUND_DESTINATION_IS_THIS_ORGANIZATION",
                                           "carry only paths into this organization", be["path_id"]))
            self.assertNotEqual(src, ORG, six("ORG_INTERNAL_INTR_HOP", "INTR_HOP_IS_BETWEEN_DISTINCT_ORGANIZATIONS",
                                              "remove the row: an InTr path never stays inside one organization", be["path_id"]))

    def test_egress_bindings_name_another_organization_and_never_llm_adapter(self):
        boundary = load("org-runtime/interlock-intr.json")
        self.assertEqual(boundary["organization"], ORG)
        for b in boundary["egress"]["capability_destination_bindings"]:
            dst = b.get("destination_organization")
            self.assertTrue(dst and dst != ORG, six("ORG_INTERNAL_INTR_HOP", "INTR_HOP_IS_BETWEEN_DISTINCT_ORGANIZATIONS",
                                                     "bind egress only to another organization's boundary", b.get("profile_id")))
            self.assertFalse(names_llm_adapter(b), six("LLM_ADAPTER_AS_INTR_DESTINATION", "LLM_ADAPTER_IS_NOT_AN_INTR_DESTINATION",
                                                        "remove the binding: LLM-adapter is not an InTr destination", b.get("profile_id")))

    def test_master_records_binding_is_cross_organization(self):
        boundary = load("org-runtime/interlock-intr.json")
        rows = [b for b in boundary["egress"]["capability_destination_bindings"]
                if b.get("destination_organization") == "master-records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["destination_repository"], "master-records/.github")
        self.assertNotEqual(rows[0]["destination_organization"], ORG)

    def test_self_closure_is_retired_not_pending_a_request(self):
        reg = load("control/workflow-surface-registry.json")
        rows = [r for r in reg["fail_closed_pending"] if "self-closure" in r["surface"]]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["failed_predicate"], "INTR_HOP_IS_BETWEEN_DISTINCT_ORGANIZATIONS")
        self.assertIn("never an InTr hop inside one organization", row["retired_by_owner_rule"])
        self.assertNotIn("carry self-closure as a committed request", json.dumps(row))
        self.assertFalse(any("self-closure" in d and "retired" not in d for d in reg["open_decisions"]))
        for req in sorted((ROOT / ".stegverse/transition-requests").glob("*.json")):
            text = req.read_text(encoding="utf-8").lower()
            self.assertNotIn("self-clos", text, six("ORG_INTERNAL_INTR_HOP", "INTR_HOP_IS_BETWEEN_DISTINCT_ORGANIZATIONS",
                                                    "remove the request: a self-closure is an InTr hop inside one organization", req.name))


if __name__ == "__main__":
    unittest.main()
