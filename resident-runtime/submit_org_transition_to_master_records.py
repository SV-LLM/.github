#!/usr/bin/env python3
"""Publish one organization transition receipt to the Master Records organization record for reconstruction.

Per-organization-transition record publication, ported from the StegVerse-org reference
(StegVerse-org/.github resident-runtime/submit_org_transition_to_master_records.py)
and parameterized: the organization comes from this repository's organization
ledger contract and the origin service from its own service registry, so
nothing here names another organization.
Master Records relates only to organization records and reconstruction.
Publishing never gates this organization's runtime reality, and no
predecessor standing is defaulted.
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

DESTINATION_ORG = "master-records"
DESTINATION_SERVICE = "organization.ecosystem-transition-ledger"
TRANSITION_REFERENCE = "ecosystem.transition.organization-record.v1"


def load(path):
    return json.loads(Path(path).read_text())


def organization(root=ROOT):
    return load(root / ".stegverse/transition-ledger/org-contract.json")["organization"]


def origin_service(org, root=ROOT):
    """This organization's own control service, from its own registry; exactly one."""
    rows = [row for row in load(root / "org-boundary/registry/services.json")["services"]
            if row.get("repository") == org + "/.github" and str(row.get("service_id", "")).endswith(".org-control")]
    if len(rows) != 1:
        raise SystemExit("organization control service must resolve to exactly one row")
    return rows[0]["service_id"]


def build_organization_record_packet(receipt, predecessor_ecosystem_state_sha256, successor_ecosystem_state_sha256,
                                     relation_evidence, standing, root=ROOT):
    org = organization(root)
    if receipt.get("schema") != "stegverse.organization-transition-receipt/v1":
        raise SystemExit("organization receipt schema mismatch")
    if receipt.get("organization") != org:
        raise SystemExit("organization receipt owner mismatch")
    # Standing is declared, never derived here; there is no default predecessor.
    if not isinstance(standing, dict) or "predecessor" not in standing:
        raise SystemExit("standing must declare the predecessor key; null is explicit genesis")
    payload = {"operation": "ORGANIZATION_RECORD_ORGANIZATION_TRANSITION", "organization_receipt": receipt,
               "predecessor_ecosystem_state_sha256": predecessor_ecosystem_state_sha256,
               "successor_ecosystem_state_sha256": successor_ecosystem_state_sha256,
               "relation_evidence": relation_evidence, "authority_transfer": False}
    return K.build_packet(origin_org=org, origin_service=origin_service(org, root), destination_org=DESTINATION_ORG,
                          destination_service=DESTINATION_SERVICE, payload=payload, standing=standing,
                          transition_reference=TRANSITION_REFERENCE, authority_effect="NONE")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--org-receipt", required=True)
    p.add_argument("--predecessor-ecosystem-state-sha256", required=True)
    p.add_argument("--successor-ecosystem-state-sha256", required=True)
    p.add_argument("--relation-evidence-json", default="{}")
    p.add_argument("--standing", required=True, help="JSON file declaring mode, node_ref and the predecessor key")
    # The mesh this node was materialized with; the kernel refuses without one.
    p.add_argument("--mesh-root", type=Path, required=True)
    a = p.parse_args()
    packet = build_organization_record_packet(load(a.org_receipt), a.predecessor_ecosystem_state_sha256,
                                              a.successor_ecosystem_state_sha256, json.loads(a.relation_evidence_json),
                                              load(a.standing))
    # The submission is an emission of this organization, so it is recorded on
    # both ledgers its materializer supplied (STEGVERSE_REPO_LEDGER_ROOT and
    # STEGVERSE_ORG_LEDGER_ROOT) before the frame is written; without them the
    # kernel refuses and nothing is published. Stamped with the epoch of the
    # receipt it carries, so submitting the same receipt again publishes the
    # same frame -- a write-once no-op -- instead of a second record request
    # stamped by the host clock.
    custody = K.crossing_custody(ROOT, repo_ledger_root=os.environ.get("STEGVERSE_REPO_LEDGER_ROOT") or None,
                                 org_ledger_root=os.environ.get("STEGVERSE_ORG_LEDGER_ROOT") or None)
    receipt = load(a.org_receipt)
    published = K.publish_packet(packet, root=a.mesh_root, custody=custody,
                                 epoch=(receipt.get("hb_reference") or {}).get("epoch"))
    print(json.dumps({"status": "PUBLISHED_FOR_ORGANIZATION_RECORD", "packet_id": packet["packet_id"],
                      "frame_sha256": published["frame"]["frame_sha256"], "authority_effect": "NONE"}, sort_keys=True))


if __name__ == "__main__":
    main()
