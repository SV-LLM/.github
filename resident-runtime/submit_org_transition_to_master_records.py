#!/usr/bin/env python3
"""Release one verified organization receipt batch to Master Records as downstream evidence.

Master Records is the recorder of released organization batch receipts: it
preserves, downstream, organization batches this organization has already
verified and released. It is not an authority, a gate, a custodian or the
locus of runtime reality. An organization transition is real when it is
appended under this organization's ledger lock; nothing here, and nothing in
this organization, awaits the batch being recorded. A batch not yet released
or recorded is a value in the transition's evidence state, never a blocker.

The release predecessor is a verified organization receipt-chain segment: the
receipts are supplied in chain order, each must be this organization's
receipt with a matching self-digest, and each must link to the one before it.
A segment that does not verify is refused before any packet is built.

Publication path ported from the StegVerse-org reference
(StegVerse-org/.github resident-runtime/submit_org_transition_to_master_records.py)
and parameterized: the organization comes from this repository's organization
ledger contract and the origin service from its own service registry, so
nothing here names another organization. No predecessor standing is defaulted.
Every refusal is a DENY carrying failure_code, failed_predicate,
required_evidence_or_repair, retry_entrypoint, owning_existing_goal and
next_attempt.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("org_kernel", ROOT / "org-kernel/kernel.py")
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)
_agg_spec = importlib.util.spec_from_file_location("svllm_org_ledger_for_release",
                                                   ROOT / "resident-runtime/aggregate_repo_transition.py")
AGG = importlib.util.module_from_spec(_agg_spec)
_agg_spec.loader.exec_module(AGG)

DESTINATION_ORG = "master-records"
DESTINATION_SERVICE = "organization.ecosystem-transition-ledger"
TRANSITION_REFERENCE = "ecosystem.transition.organization-record.v1"
RECORDER_ROLE = "RELEASED_ORGANIZATION_BATCH_RECEIPT_RECORDER"
RELEASE_PREDECESSOR = "VERIFIED_ORGANIZATION_RECEIPT_CHAIN_SEGMENT"
ORG_RECEIPT_SCHEMA = "stegverse.organization-transition-receipt/v1"
RETRY_ENTRYPOINT = "python -B resident-runtime/submit_org_transition_to_master_records.py"
OWNING_EXISTING_GOAL = "SVORG-LLM-ORG-FOUNDATION-001"

# failed_predicate -> (failure_code, required_evidence_or_repair, next_attempt)
_REFUSALS = {
    "ORGANIZATION_CONTROL_SERVICE_RESOLVES_TO_EXACTLY_ONE_ROW": (
        "MASTER_RECORDS_RELEASE_ORIGIN_SERVICE_UNRESOLVED",
        "register exactly one <organization>.org-control service for this organization in org-boundary/registry/services.json",
        "re-run the release after the registry resolves one organization control service"),
    "RELEASED_BATCH_IS_NOT_EMPTY": (
        "MASTER_RECORDS_RELEASE_BATCH_EMPTY",
        "supply at least one organization receipt with --org-receipt",
        "re-run the release with the receipt-chain segment to be released"),
    "ORGANIZATION_RECEIPT_SCHEMA_MATCHES": (
        "MASTER_RECORDS_RELEASE_RECEIPT_SCHEMA_MISMATCH",
        "release only " + ORG_RECEIPT_SCHEMA + " receipts",
        "re-run the release with organization transition receipts only"),
    "ORGANIZATION_RECEIPT_OWNER_MATCHES": (
        "MASTER_RECORDS_RELEASE_RECEIPT_OWNER_MISMATCH",
        "release only receipts emitted by this organization's own ledger",
        "re-run the release with this organization's receipts only"),
    "ORGANIZATION_RECEIPT_SELF_DIGEST_MATCHES": (
        "MASTER_RECORDS_RELEASE_RECEIPT_DIGEST_MISMATCH",
        "supply the receipt bytes exactly as appended to the organization ledger",
        "re-run the release with unaltered receipts read from the organization ledger"),
    "ORGANIZATION_RECEIPT_CHAIN_SEGMENT_IS_CONTIGUOUS": (
        "MASTER_RECORDS_RELEASE_SEGMENT_NOT_CONTIGUOUS",
        "supply a contiguous segment in chain order: each receipt's previous_receipt_sha256 names the receipt before it",
        "re-run the release with the receipts in ledger chain order and no gaps"),
    "STANDING_DECLARES_PREDECESSOR": (
        "MASTER_RECORDS_RELEASE_STANDING_UNDECLARED",
        "declare standing with the predecessor key; null is explicit genesis",
        "re-run the release with a standing file that declares its predecessor"),
}


class ReleaseRefused(SystemExit):
    """A DENY of the release. Raised before any packet is built or published."""

    def __init__(self, predicate, detail):
        failure_code, repair, next_attempt = _REFUSALS[predicate]
        self.refusal = {"disposition": "DENY", "failure_code": failure_code, "failed_predicate": predicate,
                        "required_evidence_or_repair": repair, "retry_entrypoint": RETRY_ENTRYPOINT,
                        "owning_existing_goal": OWNING_EXISTING_GOAL, "next_attempt": next_attempt,
                        "detail": detail, "authority_effect": "NONE",
                        "gates_organization_runtime_reality": False}
        super().__init__(json.dumps(self.refusal, sort_keys=True))


def load(path):
    return json.loads(Path(path).read_text())


def organization(root=ROOT):
    return load(root / ".stegverse/transition-ledger/org-contract.json")["organization"]


def origin_service(org, root=ROOT):
    """This organization's own control service, from its own registry; exactly one."""
    rows = [row for row in load(root / "org-boundary/registry/services.json")["services"]
            if row.get("repository") == org + "/.github" and str(row.get("service_id", "")).endswith(".org-control")]
    if len(rows) != 1:
        raise ReleaseRefused("ORGANIZATION_CONTROL_SERVICE_RESOLVES_TO_EXACTLY_ONE_ROW",
                             "organization control service must resolve to exactly one row")
    return rows[0]["service_id"]


def verify_released_segment(receipts, org):
    """Verify a receipt-chain segment this organization releases; return its batch summary."""
    if isinstance(receipts, dict):
        receipts = [receipts]
    if not receipts:
        raise ReleaseRefused("RELEASED_BATCH_IS_NOT_EMPTY", "released batch is empty")
    previous = None
    for index, receipt in enumerate(receipts):
        if receipt.get("schema") != ORG_RECEIPT_SCHEMA:
            raise ReleaseRefused("ORGANIZATION_RECEIPT_SCHEMA_MATCHES", f"organization receipt schema mismatch at {index}")
        if receipt.get("organization") != org:
            raise ReleaseRefused("ORGANIZATION_RECEIPT_OWNER_MATCHES", f"organization receipt owner mismatch at {index}")
        body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        if receipt.get("receipt_sha256") != AGG.sha(body):
            raise ReleaseRefused("ORGANIZATION_RECEIPT_SELF_DIGEST_MATCHES", f"organization receipt digest mismatch at {index}")
        if index and receipt.get("previous_receipt_sha256") != previous:
            raise ReleaseRefused("ORGANIZATION_RECEIPT_CHAIN_SEGMENT_IS_CONTIGUOUS",
                                 f"organization receipt at {index} does not link to the receipt before it")
        previous = receipt["receipt_sha256"]
    return {"release_predecessor": RELEASE_PREDECESSOR, "verified_by": org, "receipt_count": len(receipts),
            "segment_base_previous_receipt_sha256": receipts[0].get("previous_receipt_sha256"),
            "segment_first_receipt_sha256": receipts[0]["receipt_sha256"],
            "segment_head_receipt_sha256": receipts[-1]["receipt_sha256"],
            "receipts": list(receipts)}


def build_released_batch_packet(receipts, predecessor_ecosystem_state_sha256, successor_ecosystem_state_sha256,
                                relation_evidence, standing, root=ROOT):
    org = organization(root)
    batch = verify_released_segment(receipts, org)
    # Standing is declared, never derived here; there is no default predecessor.
    if not isinstance(standing, dict) or "predecessor" not in standing:
        raise ReleaseRefused("STANDING_DECLARES_PREDECESSOR",
                             "standing must declare the predecessor key; null is explicit genesis")
    payload = {"operation": "RECORD_RELEASED_ORGANIZATION_BATCH", "recorder_role": RECORDER_ROLE,
               "released_batch": batch,
               "predecessor_ecosystem_state_sha256": predecessor_ecosystem_state_sha256,
               "successor_ecosystem_state_sha256": successor_ecosystem_state_sha256,
               "relation_evidence": relation_evidence, "authority_transfer": False,
               "gates_organization_runtime_reality": False, "awaited_by_organization": False}
    return K.build_packet(origin_org=org, origin_service=origin_service(org, root), destination_org=DESTINATION_ORG,
                          destination_service=DESTINATION_SERVICE, payload=payload, standing=standing,
                          transition_reference=TRANSITION_REFERENCE, authority_effect="NONE")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--org-receipt", required=True, action="append",
                   help="an organization receipt of the released segment; repeat in chain order")
    p.add_argument("--predecessor-ecosystem-state-sha256", required=True)
    p.add_argument("--successor-ecosystem-state-sha256", required=True)
    p.add_argument("--relation-evidence-json", default="{}")
    p.add_argument("--standing", required=True, help="JSON file declaring mode, node_ref and the predecessor key")
    # The mesh this node was materialized with; the kernel refuses without one.
    p.add_argument("--mesh-root", type=Path, required=True)
    a = p.parse_args()
    receipts = [load(path) for path in a.org_receipt]
    packet = build_released_batch_packet(receipts, a.predecessor_ecosystem_state_sha256,
                                         a.successor_ecosystem_state_sha256, json.loads(a.relation_evidence_json),
                                         load(a.standing))
    # The release is an emission of this organization, so it is recorded on
    # both ledgers its materializer supplied (STEGVERSE_REPO_LEDGER_ROOT and
    # STEGVERSE_ORG_LEDGER_ROOT) before the frame is written; without them the
    # kernel refuses and nothing is published. Stamped with the epoch of the
    # segment's head receipt, so releasing the same segment again publishes the
    # same frame -- a write-once no-op -- instead of a second record request
    # stamped by the host clock. Publication is fire-and-forget evidence: no
    # answer is requested and nothing waits for Master Records to record it.
    custody = K.crossing_custody(ROOT, repo_ledger_root=os.environ.get("STEGVERSE_REPO_LEDGER_ROOT") or None,
                                 org_ledger_root=os.environ.get("STEGVERSE_ORG_LEDGER_ROOT") or None)
    published = K.publish_packet(packet, root=a.mesh_root, custody=custody,
                                 epoch=(receipts[-1].get("hb_reference") or {}).get("epoch"))
    print(json.dumps({"status": "RELEASED_ORGANIZATION_BATCH_PUBLISHED_FOR_DOWNSTREAM_RECORD",
                      "packet_id": packet["packet_id"], "receipt_count": len(receipts),
                      "frame_sha256": published["frame"]["frame_sha256"], "authority_effect": "NONE",
                      "gates_organization_runtime_reality": False}, sort_keys=True))


if __name__ == "__main__":
    main()
