"""Read the consolidated workflow surface (G17) the way the per-workflow tests did.

writer_job(job): the organization ledger writer's header (name, on, permissions,
concurrency) plus that one job's block - the text a test of the folded writer
workflow used to read. catalog_group(group_id) / catalog_groups(workflow): the
catalog groups a folded validation workflow became, with their step bodies.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / ".github/workflows/organization-ledger-writer.yml"
DISPATCHER = ROOT / ".github/workflows/validation-dispatcher.yml"
CATALOG = ROOT / "tools/tasks/task_catalog.json"
REGISTRY = ROOT / "control/workflow-surface-registry.json"


def writer_job(job: str) -> str:
    text = WRITER.read_text(encoding="utf-8")
    head, jobs = text.split("\njobs:\n", 1)
    lines = jobs.split("\n")
    start = lines.index(f"  {job}:")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z0-9_-]+:$", lines[i]) or lines[i].startswith("  # Folded from "):
            end = i
            break
    return head + "\njobs:\n" + "\n".join(lines[start:end]).rstrip() + "\n"


def registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def catalog_groups(workflow: str) -> list:
    path = workflow if workflow.startswith(".github/") else ".github/workflows/" + workflow
    return [g for g in catalog()["groups"] if g["source"].get("workflow") == path]


def catalog_group(group_id: str) -> dict:
    return next(g for g in catalog()["groups"] if g["id"] == group_id)


def step_bodies(group: dict) -> str:
    return "\n".join((ROOT / s["run_file"]).read_text(encoding="utf-8") for s in group["steps"])


def assert_read_only_validation(test, workflow: str, events=("pull_request",)) -> list:
    """The folded validation workflow's checks run read-only and never push."""
    groups = catalog_groups(workflow)
    test.assertTrue(groups, workflow)
    dispatcher = DISPATCHER.read_text(encoding="utf-8")
    test.assertIn("\npermissions: {}\n", dispatcher)
    test.assertNotIn("contents: write", dispatcher)
    test.assertNotIn("secrets.", dispatcher)
    for group in groups:
        for event in events:
            test.assertIn(event, group["events"], group["id"])
        test.assertFalse(set(group["events"]) - {"pull_request", "push"}, group["id"])
        test.assertNotIn("contents: write", json.dumps(group["source"].get("permissions_before")))
        body = step_bodies(group)
        test.assertNotIn("git push", body)
        test.assertNotIn("secrets.", body)
        test.assertFalse([s for s in group["steps"] if s.get("if")], group["id"])
    return groups


def dispatch_record(workflow: str) -> str:
    """Text of a workflow_dispatch workflow G17 removed from .github/workflows/.

    SV-LLM/.github (P1, StegVerse-org/.github#163): a dispatcher that a manifest
    binding names is no longer an executing workflow. Its verbatim record is kept
    (tools/tasks/folded/ or tools/tasks/retired/, sha256-pinned in the registry)
    and the registry carries a six-field FAIL_CLOSED pending row for it, so the
    binding is recorded unreachable, never silently dropped. Raises AssertionError
    when either is missing.
    """
    path = workflow if workflow.startswith(".github/") else ".github/workflows/" + workflow
    live = ROOT / path
    if live.is_file():
        return live.read_text(encoding="utf-8")
    import hashlib
    reg = registry()
    row = next((r for r in reg["folded"] if r["workflow"] == path), None)
    if row is None or not row.get("record"):
        raise AssertionError(f"{path}: neither in tree nor a registered G17 record")
    raw = (ROOT / row["record"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["record_sha256"]:
        raise AssertionError(f"{row['record']}: record drifted from its pinned sha256")
    name = path.rsplit("/", 1)[1]
    pending = [p for p in reg["fail_closed_pending"] if p["surface"].startswith(name)]
    if not pending or any(p.get("disposition") != "FAIL_CLOSED" for p in pending):
        raise AssertionError(f"{path}: removed dispatcher has no FAIL_CLOSED pending row")
    return raw.decode("utf-8")
