#!/usr/bin/env python3
"""What P1's issue derivation makes of a committed nwi-s0-exit-gate stage evaluation -- pure calls, nothing appended.

STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE: a failing gate receipt, once the org-ledger writer (Labs#3255/#3270) appends it,
derives exactly one NATIVE SV_ISSUE through sv_work_items.derive_issue_from_check_receipt. No receipt is on any ledger,
so the append is SIMULATED in memory with P1's own org-ledger fixture layout (tests/sv_ledger_fixtures.py at the contract
pin: repo receipt -> org receipt, the real field layout, fixture boundary/observed_at values) at a placeholder ledger
commit. The derived issue shape and the one-receipt-one-issue property are P1's; the issue_id itself depends on the org
receipt bytes, so the real id is fixed only by the real append. Nothing is written to any ref, file or ledger.

derive(evaluation_dirs, p1) -> one record: for every receipt, derive_issue_from_check_receipt twice (same id) or its
refusal (an ALLOW receipt is DENY CHECK_RECEIPT_NOT_FAILING); then derive_resolved_issue_facts for a change citing the
gate issue, at the change's real base ledger head (no receipt there: no fact) and at the simulated post-append commit.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_nwi_s0_exit_gate as g  # noqa: E402
import s1_sv_check_receipts as m  # noqa: E402

SCHEMA = "stegverse.sv-llm.s1-stage-gate-issue-derivation/v1"
SIMULATED_LEDGER_COMMIT = "0" * 40  # placeholder: no append happened
FIXTURE_FILES = {"tests/sv_ledger_fixtures.py": "30a9fe8980671e63348810c837882f3dab525459",
                 "resident-runtime/aggregate_repo_transition.py": "7660d2bc10231c68f9c8b1015caee558ee9423d8"}


def refusal(wi: Any, fn: Any, *a: Any, **k: Any) -> dict[str, Any]:
    try:
        return {"result": fn(*a, **k)}
    except wi.Refusal as r:
        return {"refused": {key: r.record.get(key) for key in ("disposition", "failure_code", "failed_predicate")}}


def derive(evaluations: list[Path], p1: Path, change_bundle: Path) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="sv-llm-s1issue-"))
    try:
        wi, _sg, tree = g.load_p1(p1, work)
        for path, blob in FIXTURE_FILES.items():
            if m.rc_blob((tree / path).read_bytes()) != blob:
                raise RuntimeError(path + " at the pin is not blob " + blob)
        sys.path.insert(0, str(tree))
        spec = importlib.util.spec_from_file_location("s1_p1_ledger_fixtures", tree / "tests/sv_ledger_fixtures.py")
        lf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lf)
        out: dict[str, Any] = {"schema": SCHEMA, "simulated_append": True, "ledger_appended": False,
                               "simulated_ledger_commit": SIMULATED_LEDGER_COMMIT,
                               "fixture_layout": {"pin": m.CONTRACT_PINS["commit"], "files": FIXTURE_FILES},
                               "contract_pins": dict(m.CONTRACT_PINS), "evaluations": {}}
        gate_issue = None
        for d in evaluations:
            ev = json.loads((d / "evaluation.json").read_bytes())
            subject = ev["evaluation_subject"]
            rows = {}
            for f in sorted(d.glob("*.json")):
                if f.name == "evaluation.json":
                    continue
                body = json.loads(f.read_bytes())
                repo = lf.repo_receipt(body, int(body["hb_epoch"]), repository=subject["repository"])
                org = lf.org_receipt(repo, int(body["hb_epoch"]), boundary_evidence=lf.boundary())
                objs, ref = lf.ledger_objects(SIMULATED_LEDGER_COMMIT, org, repo), lf.org_ref(SIMULATED_LEDGER_COMMIT, org)
                first = refusal(wi, wi.derive_issue_from_check_receipt, objs, ref, observed_base=subject["base_ref"])
                again = refusal(wi, wi.derive_issue_from_check_receipt, objs, ref, observed_base=subject["base_ref"])
                assert first == again
                entry: dict[str, Any] = {"receipt_sha256": "sha256:" + m.sha256_hex(f.read_bytes()),
                                         "disposition": body["disposition"], "simulated_ledger_ref": ref}
                if "result" in first:
                    issue = first["result"]
                    entry["sv_issue"] = issue
                    entry["sv_issue_digest"] = issue["issue_sha256"]
                    if body["check_id"] == g.CHECK_ID:
                        gate_issue = (issue, objs)
                else:
                    entry.update(first)
                rows[body["check_id"]] = entry
            out["evaluations"][d.name] = {"evaluation_sha256": ev["evaluation_sha256"], "disposition": ev["disposition"],
                                          "evaluation_subject_digest": ev["evaluation_subject_digest"], "receipts": rows}
        if gate_issue is not None:
            issue, objs = gate_issue
            sv = json.loads(change_bundle.read_bytes())["sv_change"]
            change = {"change_id": sv["change_id"], "base_ref": dict(sv["base_ref"]), "resolves": [issue["issue_id"]]}
            real = "refs/stegverse/organization-ledger@" + sv["base_ref"]["ledger_head"]
            sim = "refs/stegverse/organization-ledger@" + SIMULATED_LEDGER_COMMIT
            rebased = {**change, "base_ref": {**change["base_ref"], "ledger_head": SIMULATED_LEDGER_COMMIT}}
            out["resolution"] = {
                "change": {"change_id": sv["change_id"], "base_ref": sv["base_ref"], "cites": issue["issue_id"],
                           "note": "the #3264 record carries resolves []; this cites the gate issue to show what remains"},
                "at_change_base": {"ledger_ref": real, **refusal(wi, wi.derive_resolved_issue_facts, objs, real, change, [issue])},
                "at_change_base_without_ledger_bytes": refusal(wi, wi.derive_resolved_issue_facts, {}, real, change, [issue]),
                "after_simulated_append_and_rebase": {"ledger_ref": sim, **refusal(wi, wi.derive_resolved_issue_facts, objs,
                                                                                   sim, rebased, [issue])}}
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
        for name in ("sv_work_items", "stage_gate"):
            sys.modules.pop(name, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evaluation", type=Path, action="append", required=True)
    parser.add_argument("--p1", type=Path, required=True)
    parser.add_argument("--change-bundle", type=Path, required=True, help="the #3264 sv-check-receipts bundle.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.write_bytes(m.render(derive(args.evaluation, args.p1, args.change_bundle)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
