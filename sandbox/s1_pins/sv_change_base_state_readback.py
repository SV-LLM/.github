#!/usr/bin/env python3
"""RTC-SV-CHANGE-BASE-STATE-READBACK-014: the observed base state an SV_CHANGE admission binds (B1).

SV_CHANGE admission (TVC sv_change_admission, P4 admission_predicate) needs the base
``registry_generation`` and ``ledger_head`` as observed state; without them it fails closed
(SV_CHANGE_BASE_UNBOUND / BASE_STATE_NOT_OBSERVED). Both are readbacks, so no issuer exists or is needed.
Given a local repository and the bound main commit the caller supplies, this:

1. reads ``registry_generation`` from the repository's OWN declared registry file at exactly that commit
   (``git cat-file``; never a working tree, never another commit). The path comes from the pinned
   ``REGISTRY_PATHS`` map (repository -> registry path), keyed by the ``repository_name`` the caller names;
   an unmapped repository is FAIL_CLOSED REGISTRY_PATH_NOT_DECLARED, and a registry that declares no
   ``generation`` is FAIL_CLOSED REGISTRY_GENERATION_NOT_DECLARED (joint item Q-ORG-REGISTRY-GENERATION).
   Nothing here proposes or makes a registry edit;
2. verifies the organization ledger on ``refs/stegverse/organization-ledger`` of that repository with the
   existing ``organization_ledger_readback.readback`` (no second verifier) and reports the ref's commit as
   ``ledger_head``; the ref must not move during the read;
3. returns one sealed receipt ``{schema, base_ref {registry_generation, ledger_head}, bound_main_commit,
   sources [{file, blob_sha}], disposition, result_sha256, hb_epoch}``.

``hb_epoch`` is an explicit slot: the caller's supplied epoch, else ``null`` with ``open_questions``
naming JD-P4-3. It is never derived. Every non-ALLOW carries the six fields. Read-only: nothing is
written to any ref, file or ledger; no clock; no network (the repository is local, as for the existing
readback). Stdlib and ``git`` only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

COMPONENT_ID = "RTC-SV-CHANGE-BASE-STATE-READBACK-014"
RESULT_SCHEMA = "stegverse.sv-change-base-state-readback/v1"
LEDGER_REF = "refs/stegverse/organization-ledger"
# Pinned map: repository -> its own declared registry file (observed on each main, 2026-10-18). Extending it is a
# reviewed change to this file; there is no default path.
REGISTRY_PATHS = {
    "StegVerse-Labs/.github": "data/canonical-task-registry.json",  # carries an integer "generation"
    "StegVerse-org/.github": "orchestration/task-registry.json",    # orchestration_task_registry; declares no generation (40a5d235)
}
REGISTRY_GENERATION_JOINT_ITEM = "Q-ORG-REGISTRY-GENERATION"
LEDGER_HEAD_FILE = LEDGER_REF + ":HEAD.json"
OWNING_EXISTING_GOAL = "StegVerse-org/.github#164"
AUTHORITY_EFFECT = "NONE_READBACK_ONLY"
RETRY = "resident-runtime/sv_change_base_state_readback.py::evaluate"
HB_EPOCH_OPEN_QUESTION = "JD-P4-3"
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
              "owning_existing_goal", "next_attempt")
HERE = Path(__file__).resolve().parent
_OID = re.compile(r"[0-9a-f]{40}\Z")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal(body: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != "result_sha256"}
    return {**clean, "result_sha256": "sha256:" + hashlib.sha256(canon(clean)).hexdigest()}


def seal_verifies(result: Any) -> bool:
    return isinstance(result, dict) and seal(result).get("result_sha256") == result.get("result_sha256")


def _load_readback():
    spec = importlib.util.spec_from_file_location("rtc014_organization_ledger_readback", HERE / "organization_ledger_readback.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("organization_ledger_readback not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    return subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, check=False)


def _out(proc: subprocess.CompletedProcess) -> str | None:
    return proc.stdout.decode().strip() if proc.returncode == 0 else None


def _epoch(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) >= 32:
        return value
    raise ValueError("hb_epoch")


def _receipt(base: dict[str, Any], disposition: str, **fields: Any) -> dict[str, Any]:
    body = {**base, **fields, "disposition": disposition, "authority_effect": AUTHORITY_EFFECT, "readback_writes": False}
    return seal(body)


def _refuse(base: dict[str, Any], code: str, predicate: str, repair: str, next_attempt: str, **extra: Any) -> dict[str, Any]:
    return _receipt(base, "FAIL_CLOSED", **extra, failure_code=code, failed_predicate=predicate,
                    required_evidence_or_repair=repair, retry_entrypoint=RETRY,
                    owning_existing_goal=OWNING_EXISTING_GOAL, next_attempt=next_attempt)


def evaluate(repository: Any, bound_main_commit: Any, *, repository_name: Any = None, hb_epoch: Any = None,
             main_ref: str = "refs/heads/main") -> dict[str, Any]:
    """Read the base state at ``bound_main_commit`` in the local ``repository`` (whose name, e.g.
    ``StegVerse-org/.github``, selects its registry path from REGISTRY_PATHS). Never raises."""
    base: dict[str, Any] = {"schema": RESULT_SCHEMA, "component_id": COMPONENT_ID,
                            "repository": repository_name if isinstance(repository_name, str) else None,
                            "base_ref": {"registry_generation": None, "ledger_head": None},
                            "bound_main_commit": bound_main_commit if isinstance(bound_main_commit, str) else None,
                            "main_ref": main_ref, "sources": [], "hb_epoch": None}
    try:
        epoch = _epoch(hb_epoch)
    except ValueError:
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "HB_EPOCH_SUPPLIED_WELL_FORMED",
                       "hb_epoch, when supplied, is ASCII digits >= 32 from the caller (never a clock)",
                       "re-run with a well-formed supplied hb_epoch, or none (slot left open as JD-P4-3)")
    base["hb_epoch"] = epoch
    if epoch is None:
        base["open_questions"] = [{"id": HB_EPOCH_OPEN_QUESTION, "slot": "hb_epoch",
                                   "status": "OPEN: no epoch supplied by the caller; left null, never derived"}]
    if not isinstance(bound_main_commit, str) or not _OID.match(bound_main_commit):
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "BOUND_MAIN_COMMIT_WELL_FORMED",
                       "the caller supplies the bound main commit as a 40-hex sha", "re-run with the bound main commit sha")
    repo = Path(str(repository)) if isinstance(repository, (str, Path)) else None
    if repo is None or _out(_git(repo, "rev-parse", "--git-dir")) is None:
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "REPOSITORY_READABLE",
                       "a local git repository holding the bound main commit and " + LEDGER_REF,
                       "re-run against a local clone that holds both")
    if _out(_git(repo, "cat-file", "-e", bound_main_commit + "^{commit}")) is None:
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "BOUND_MAIN_COMMIT_PRESENT",
                       f"commit {bound_main_commit} present in the repository", "re-run after the commit is fetched")
    main_tip = _out(_git(repo, "rev-parse", "--verify", "--quiet", main_ref + "^{commit}"))
    if main_tip is None or _git(repo, "merge-base", "--is-ancestor", bound_main_commit, main_tip).returncode != 0:
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "BOUND_COMMIT_IS_ON_MAIN",
                       f"{bound_main_commit} is {main_ref} or in its history", "re-run with a commit on main", main_tip=main_tip)
    base["main_tip"] = main_tip
    # (1) registry_generation at exactly the bound commit, from the repository's own declared registry.
    registry_file = REGISTRY_PATHS.get(repository_name) if isinstance(repository_name, str) else None
    if registry_file is None:
        return _refuse(base, "REGISTRY_PATH_NOT_DECLARED", "REGISTRY_PATH_DECLARED_FOR_REPOSITORY",
                       "repository_name names a repository in the pinned REGISTRY_PATHS map (" + ", ".join(sorted(REGISTRY_PATHS)) + ")",
                       "re-run naming a mapped repository, or extend REGISTRY_PATHS by a reviewed change to this component")
    blob = _out(_git(repo, "rev-parse", "--verify", "--quiet", f"{bound_main_commit}:{registry_file}"))
    generation, registry = None, None
    if blob is not None:
        raw = _git(repo, "cat-file", "blob", blob)
        try:
            registry = json.loads(raw.stdout.decode("utf-8")) if raw.returncode == 0 else None
        except (UnicodeDecodeError, ValueError):
            registry = None
        g = registry.get("generation") if isinstance(registry, dict) else None
        generation = g if isinstance(g, int) and not isinstance(g, bool) and g >= 0 else None
    if isinstance(registry, dict) and "generation" not in registry:
        return _refuse(base, "REGISTRY_GENERATION_NOT_DECLARED", "REGISTRY_DECLARES_GENERATION",
                       f"{registry_file} at {bound_main_commit} declares an integer generation >= 0; it declares none "
                       "(this component proposes and makes no registry edit)",
                       f"after joint item {REGISTRY_GENERATION_JOINT_ITEM} decides how this registry declares its generation",
                       sources=[{"file": registry_file, "blob_sha": blob}],
                       joint_item=REGISTRY_GENERATION_JOINT_ITEM)
    if blob is None or generation is None:
        return _refuse(base, "REGISTRY_GENERATION_UNREADABLE", "REGISTRY_GENERATION_READ_AT_BOUND_COMMIT",
                       f"{registry_file} at {bound_main_commit} parses and carries an integer generation >= 0",
                       "re-run against a bound commit whose registry is readable",
                       sources=[{"file": registry_file, "blob_sha": blob}])
    sources = [{"file": registry_file, "blob_sha": blob}]
    base["sources"] = sources
    base["base_ref"] = {"registry_generation": generation, "ledger_head": None}
    # (2) ledger head via the existing readback; the ref must not move while it is read.
    before = _out(_git(repo, "rev-parse", "--verify", "--quiet", LEDGER_REF + "^{commit}"))
    if before is None:
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "ORGANIZATION_LEDGER_REF_PRESENT",
                       f"{LEDGER_REF} present in the repository (fetched by the caller's existing transport)",
                       "re-run after the organization ledger ref is fetched")
    readback = _load_readback()
    try:
        ledger = readback.readback(f"git+{repo}#{LEDGER_REF}")
    except readback.ReadbackRefused as exc:
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", exc.failed_predicate, exc.detail,
                       "after the ledger chain reads back; nothing is written by this readback")
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "ORGANIZATION_LEDGER_READS_BACK", type(exc).__name__ + ": " + str(exc),
                       "after the ledger reads back; nothing is written by this readback")
    after = _out(_git(repo, "rev-parse", "--verify", "--quiet", LEDGER_REF + "^{commit}"))
    if after != before or not _OID.match(before):
        return _refuse(base, "BASE_STATE_NOT_OBSERVED", "LEDGER_HEAD_STABLE_DURING_READBACK",
                       f"{LEDGER_REF} did not move during the read ({before} -> {after})", "re-run; the next read binds one head")
    head_blob = _out(_git(repo, "rev-parse", "--verify", "--quiet", f"{before}:HEAD.json"))
    sources.append({"file": LEDGER_HEAD_FILE, "blob_sha": head_blob})
    return _receipt(base, "ALLOW", sources=sources,
                    base_ref={"registry_generation": generation, "ledger_head": before},
                    ledger_head_receipt_sha256=ledger["head_receipt_sha256"], ledger_chain_length=ledger["chain_length"],
                    ledger_chain_verifies=ledger["every_receipt_verifies_against_its_body"]
                    and ledger["every_source_receipt_retained_and_verifies"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", type=Path, required=True, help="local git repository (clone) holding both")
    parser.add_argument("--bound-main-commit", required=True)
    parser.add_argument("--repository-name", default=None, help="e.g. StegVerse-org/.github; selects the registry path (REGISTRY_PATHS)")
    parser.add_argument("--main-ref", default="refs/heads/main")
    parser.add_argument("--hb-epoch", default=None, help="supplied by the caller; omitted -> null, open as JD-P4-3")
    args = parser.parse_args(argv)
    result = evaluate(args.repository, args.bound_main_commit, repository_name=args.repository_name,
                      hb_epoch=args.hb_epoch, main_ref=args.main_ref)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
