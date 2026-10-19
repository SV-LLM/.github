#!/usr/bin/env python3
"""The SV-LLM organization's own steps before the Sandbox authentic lane, in one run.

SV-LLM-ORGANIZATION-ROLE-EXACT-STEGVERSE-ORG-DUPLICATION-001. The organization
ledger is the StegVerse-org reference ledger, bound exactly as the reference
binds it (PosixLedgerStore(ledger_root()), STEGVERSE_ORG_LEDGER_ROOT): it is
execution-scoped, and nothing here claims durability beyond the run. In that
one execution this:

  1. opens the organization ledger with the manifested genesis transition
     (crossing.open_organization_ledger; explicit GENESIS, never inferred);
  2. appends one authentic parent through crossing.record, whose recorded
     outcome names the Sandbox lane's intended action and target, so the lane
     can take its subject from the parent itself (D11);
  3. writes the parent's organization receipt digest for the lane
     (PARENT_ORG_RECEIPT_SHA256).

An already-opened ledger is refused DENY ORG_LEDGER_GENESIS_ON_NON_EMPTY_LEDGER
by the reference and nothing is written. authority_effect is NONE.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "org-runtime"))
import crossing  # noqa: E402

PARENT_CLASS = "ORGANIZATION_INGRESS_MATERIALIZED"
INTENDED_ACTION = "STEGBROWSER_LIVE_PATH_CONFORMANCE"


def ledger_persistence(store) -> str:
    """What outlives this run: the reference's git-ref store does, a POSIX root under the runner does not."""
    return "DURABLE_GIT_REF_SAME_AS_REFERENCE" if getattr(store, "kind", None) == "GIT_REF" \
        else "EXECUTION_SCOPED_SAME_AS_REFERENCE"


def prepare(target: dict, root: Path = ROOT, *, hb_epoch: int | None = None) -> dict:
    target_id = target.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        raise SystemExit("LIVE_TARGET_ID_REQUIRED")
    # Genesis is declared once, on an empty ledger. On the designated git ref
    # (org-contract.json organization_ledger_ref) the chain outlives the run,
    # so a later run continues from the published HEAD rather than declaring
    # genesis again, which the reference would refuse.
    ledger = crossing.organization_ledger
    store = ledger.open_store(ledger.ledger_root())
    head = store.get(ledger.HEAD_KEY)
    opened = crossing.open_organization_ledger(root, hb_epoch=hb_epoch) if head is None else None
    outcome = {"disposition": "ALLOW", "intended_action": INTENDED_ACTION, "target_id": target_id}
    parent = crossing.record(PARENT_CLASS, subject={"intended_action": "AUTHENTIC_PARENT", "for": INTENDED_ACTION},
                             outcome=outcome, root=root, hb_epoch=hb_epoch)
    return {"schema": "sv-llm.authentic-live-lane-organization-steps/v1", "organization": crossing.ORG,
            "ledger_opened_org_receipt_sha256": opened["org_receipt_sha256"] if opened else None,
            "continued_from_org_receipt_sha256": None if opened else head["receipt_sha256"],
            "parent_transition_class": PARENT_CLASS, "parent_outcome": outcome,
            "parent_repo_receipt_sha256": parent["repo_receipt_sha256"],
            "parent_org_receipt_sha256": parent["org_receipt_sha256"],
            "ledger_location": str(ledger.ledger_root()),
            "ledger_persistence": ledger_persistence(store), "authority_effect": "NONE"}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    step = sub.add_parser("prepare")
    step.add_argument("--target", type=Path, required=True, help="the pinned Sandbox live/target.json")
    step.add_argument("--out", type=Path, required=True)
    step.add_argument("--hb-epoch", default=None,
                      help="heartbeat epoch from the carrier tick; required, never derived from the host clock")
    args = parser.parse_args()
    # The raw text goes to the kernel rule; an int() here would admit '+33'.
    refusal = crossing.kernel.writer_epoch_refusal(
        args.hb_epoch, retry_entrypoint="org-runtime/authentic_live_lane.py prepare --hb-epoch")
    if refusal is not None:
        print(json.dumps(refusal, sort_keys=True))
        return 1
    target = crossing.kernel.read_cli_json(args.target, argument="--target",
                                           retry_entrypoint="org-runtime/authentic_live_lane.py prepare --target")
    result = prepare(target, hb_epoch=int(args.hb_epoch))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(crossing.kernel.run_cli(main, retry_entrypoint="org-runtime/authentic_live_lane.py prepare (the same command again)"))
