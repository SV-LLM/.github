#!/usr/bin/env python3
"""S1 nwi-s0-exit-gate: the NWI-S1 verifier built-in for the NWI-S0 stage manifest's exit_gate_check.

StegVerse-org/.github#162 (NWI-S1), S1 home #163. Declared complete in StegVerse-Labs/.github#3264's
data/sv-work-items/stages/NWI-S0.json (resolved through the pinned contract-pins.json, see
s1_sv_check_receipts.CONTRACT_PINS); invariant STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE.

Cadence: once per STAGE_GATE evaluation (stage_gate.evaluate_gate('NWI-S0', 'NWI-S1', ..., subject=)) of one
evaluation subject. Never on a push, a pull-request head or a schedule, and not a row check: the SV_CHANGE minter
(s1_sv_check_receipts.py) never emits it. The same subject has the same digest and the same receipts.

evaluate(input, checkout, p1):
  0. P1's sv_work_items.py and stage_gate.py are imported from the contract-pinned tree (every used file's bytes
     checked against its contract-pins.json entry; org-kernel/kernel.py, which the manifest omits, by blob).
  1. Subject stegverse.nwi-stage-evaluation-subject/v1 = {repository, stage_id, manifest_blob (git blob of the
     manifest at evaluated_commit), evaluated_commit, base_ref {registry_generation read at evaluated_commit from the
     repository's own registry, ledger_head}} via sv_work_items.stage_evaluation_subject; anything unobserved or
     contradicted is FAIL_CLOSED STAGE_EVALUATION_SUBJECT_UNOBSERVED and nothing is emitted.
  2. sv_work_items.validate_gate_declaration(manifest at evaluated_commit) must be ALLOW; else FAIL_CLOSED
     STAGE_GATE_DECLARATION_INCOMPLETE and nothing is emitted.
  3. hb_epoch = $.hb_reference.epoch from the Labs#3266 readback at subject.base_ref.ledger_head, checked with
     sv_work_items.verify_admission_hb_epoch(..., target_repository=subject.repository) (and this verifier's
     binder_check, which must agree); unobserved is FAIL_CLOSED STAGE_EVIDENCE_UNOBSERVED and nothing is emitted.
  4. Each evidence producer runs its row argv verbatim, twice, offline under the clock/network probe, in the exact
     evaluated commit (command_paths absent there: FAIL_CLOSED CHECK_COMMAND_ABSENT_AT_HEAD, nothing run).
  5. stage_gate.evaluate_gate over the producers' receipts (receipt_ref = sha256 of the receipt bytes) with the
     subject; the nwi-s0-exit-gate receipt carries its disposition (and P1's six fields on non-ALLOW).
  Every receipt is stegverse.sv_check_receipt.v1 with change_digest = stage_evaluation_digest(subject) and head_sha =
  evaluated_commit, validated against the pinned schema and P1's validate_gate_receipt before anything is written.
Reads no clock, opens no network connection, passes no credential, appends no ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_sv_check_receipts as m  # noqa: E402
import s1_supplied_epoch_binder as eb  # noqa: E402

CHECK_ID = "nwi-s0-exit-gate"
STAGE_ID, TARGET_STAGE = "NWI-S0", "NWI-S1"
INPUT_SCHEMA = "stegverse.sv-llm.s1-stage-evaluation-input/v1"
OUTPUT_SCHEMA = "stegverse.sv-llm.s1-stage-evaluation/v1"
TRIGGER = "STAGE_GATE_EVALUATION"
OWNING_EXISTING_GOAL = "StegVerse-org/.github#163 / NWI-S0 exit_gate_check (NWI-S1, #162)"
RETRY_ENTRYPOINT = ("sandbox/s1_nwi_s0_exit_gate.py evaluate --input <stage-evaluation input> --checkout "
                    "<repository clone> --p1 <StegVerse-Labs/.github clone> --out-dir <dir>")
READBACKS_PATHS_FROM = Path(__file__).resolve().parent / "s1_pins" / "sv_change_base_state_readback.py"
INPUT_KEYS = {"schema", "stage_id", "target_stage", "repository", "evaluated_commit", "base_ref", "hb_epoch_readback",
              "trigger", "note", "manifest_source"}
# Where the manifest under evaluation comes from. EVALUATED_COMMIT: the manifest (and every NWI-S* stage) at
# evaluated_commit. CONTRACT_PINS (orchestrator 16:57Z, base-side evaluation): the contract-pinned manifest (blob from
# contract-pins.json) and the pinned tree's stages, evaluated against a commit that need not carry them.
MANIFEST_SOURCES = ("EVALUATED_COMMIT", "CONTRACT_PINS")


def gate_verifier_ref() -> str:
    """receipt_form.verifier_ref is "SV-LLM/.github#46@<verifier commit>"; sv_work_items.is_s1_verifier accepts
    "#46" qualified by "@" or ":". A receipt cannot name the commit that carries it, so the qualifier is the sha256 of the
    verifier files (content-addressed, same as s1_sv_check_receipts.verifier_ref)."""
    return "SV-LLM/.github#46:sha256:" + m.sha256_hex(m.canon(m.verifier_files()))


def gate_receipt(check_id: str, disposition: str, digest: str, commit: str, epoch: str, fields: Any = None) -> dict[str, Any]:
    return {**m.receipt(check_id, disposition, digest, commit, epoch, fields), "verifier_ref": gate_verifier_ref()}


class Refused(Exception):
    def __init__(self, disposition: str, fields: Mapping[str, Any], detail: Any = None) -> None:
        super().__init__(fields.get("failure_code"))
        self.disposition, self.fields, self.detail = disposition, dict(fields), detail


def six(code: str, predicate: str, repair: str, next_attempt: str) -> dict[str, str]:
    return {"failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY_ENTRYPOINT, "owning_existing_goal": OWNING_EXISTING_GOAL, "next_attempt": next_attempt}


def p1_six(record: Mapping[str, Any]) -> dict[str, Any]:
    return {k: record.get(k) for k in m.SIX_FIELDS}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True)


def load_p1(p1: Path, work: Path) -> tuple[Any, Any]:
    """sv_work_items and stage_gate from the contract-pinned tree, every used file checked against the manifest."""
    commit = m.CONTRACT_PINS["commit"]
    tree = work / "p1"
    tree.mkdir(parents=True)
    archive = git(p1, "archive", commit)
    if archive.returncode:
        raise RuntimeError("the contract pin " + commit + " is not in the P1 clone")
    subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
    raw = (tree / m.CONTRACT_PINS["file"]).read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != m.CONTRACT_PINS["sha256"] or raw != m.CONTRACT_PINS_COPY.read_bytes():
        raise RuntimeError("contract-pins.json at the pin is not the pinned manifest")
    entries = json.loads(raw)["files"]
    for path in m.USED_P1_FILES:
        data = (tree / path).read_bytes()
        if entries[path] != {"blob": m.rc_blob(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}:
            raise RuntimeError(path + " at the pin is not its contract-pins entry")
    for path, blob in m.UNLISTED_P1_FILES.items():
        if m.rc_blob((tree / path).read_bytes()) != blob:
            raise RuntimeError(path + " at the pin is not blob " + blob)
    for name in ("sv_work_items", "stage_gate"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("sv_work_items", tree / "resident-runtime/sv_work_items.py")
    wi = importlib.util.module_from_spec(spec)
    sys.modules["sv_work_items"] = wi
    spec.loader.exec_module(wi)
    spec = importlib.util.spec_from_file_location("stage_gate", tree / "resident-runtime/stage_gate.py")
    sg = importlib.util.module_from_spec(spec)
    sys.modules["stage_gate"] = sg
    spec.loader.exec_module(sg)
    return wi, sg, tree


def registry_paths() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("s1_pinned_readback", READBACKS_PATHS_FROM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.REGISTRY_PATHS)


def observe_subject(wi: Any, document: Mapping[str, Any], checkout: Path, tree: Path) -> tuple[dict[str, Any], bytes | None]:
    commit, repo = document.get("evaluated_commit"), document.get("repository")
    if document.get("manifest_source", "EVALUATED_COMMIT") == "CONTRACT_PINS":
        data = (tree / m.STAGE_GATE_MANIFEST_FILE).read_bytes()
        manifest_bytes, manifest_blob = data, m.rc_blob(data)
        if manifest_blob != m.STAGE_GATE_MANIFEST_BLOB:
            raise RuntimeError("the pinned tree's manifest is not the contract-pins blob")
        if isinstance(commit, str) and m.rc.git(checkout, "cat-file", "-e", commit + "^{commit}").returncode:
            manifest_blob = None  # the evaluated commit itself is unobserved
    else:
        got = m.read_at(checkout, commit, m.STAGE_GATE_MANIFEST_FILE) if isinstance(commit, str) else None
        manifest_bytes, manifest_blob = got if got else (None, None)
    try:
        subject = wi.stage_evaluation_subject(repo, document.get("stage_id"), manifest_blob, commit, document.get("base_ref"))
    except wi.Refusal as r:
        raise Refused("FAIL_CLOSED", p1_six(r.record), r.record.get("fields")) from None
    path = registry_paths().get(repo)
    reg = m.read_at(checkout, commit, path) if path else None
    try:
        generation = json.loads(reg[0]).get("generation") if reg else None
    except ValueError:
        generation = None
    if generation is None or generation != subject["base_ref"]["registry_generation"]:
        raise Refused("FAIL_CLOSED", six(
            "STAGE_EVALUATION_SUBJECT_UNOBSERVED", wi.GATE_DECLARATION_PREDICATE,
            "base_ref.registry_generation is the generation read at evaluated_commit from the repository's own registry ("
            + str(path) + ")", "re-evaluate with the observed generation; nothing was evaluated"),
            {"declared": subject["base_ref"]["registry_generation"], "observed_at_evaluated_commit": generation})
    return subject, manifest_bytes


def load_readback(spec: Any) -> Any:
    try:
        return m.load_readback(spec)
    except m.Global:
        return None


def evaluate(input_path: Path, checkout: Path, p1: Path) -> tuple[dict[str, Any], dict[str, dict]]:
    out: dict[str, Any] = {"schema": OUTPUT_SCHEMA, "check_id": CHECK_ID, "stage_id": STAGE_ID, "target_stage": TARGET_STAGE,
                           "trigger": TRIGGER, "cadence": "once per STAGE_GATE evaluation subject; never push, PR head or schedule",
                           "in_required_checks_row": False, "authority_effect": "NONE", "appended_by": "StegVerse-Labs/.github#3255/#3270 (not here)",
                           "ledger_appended": False, "verifier_ref": gate_verifier_ref(), "contract_pins": dict(m.CONTRACT_PINS),
                           "input_sha256": None, "evaluation_subject": None, "evaluation_subject_digest": None,
                           "declaration": None, "hb_epoch": None, "producers": [], "gate_outcome": None, "receipts": {}}
    receipts: dict[str, dict] = {}
    work = Path(tempfile.mkdtemp(prefix="sv-llm-s1gate-"))
    try:
        raw = input_path.read_bytes()
        out["input_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get("schema") != INPUT_SCHEMA or set(document) - INPUT_KEYS \
                or document.get("trigger") != TRIGGER or document.get("stage_id") != STAGE_ID \
                or document.get("target_stage") != TARGET_STAGE \
                or document.get("manifest_source", "EVALUATED_COMMIT") not in MANIFEST_SOURCES:
            raise Refused("FAIL_CLOSED", six("STAGE_EVALUATION_SUBJECT_UNOBSERVED", "STAGE_GATE_DECLARATION_IS_COMPLETE",
                                             "a " + INPUT_SCHEMA + " input for one STAGE_GATE_EVALUATION NWI-S0 -> NWI-S1",
                                             "re-run with a well-formed input; nothing was evaluated"))
        wi, sg, tree = load_p1(p1, work)
        source = document.get("manifest_source", "EVALUATED_COMMIT")
        out["manifest_source"] = source
        subject, manifest_bytes = observe_subject(wi, document, checkout, tree)
        digest = wi.stage_evaluation_digest(subject)
        out.update(evaluation_subject=subject, evaluation_subject_digest=digest)
        manifest = json.loads(manifest_bytes)
        try:
            out["declaration"] = wi.validate_gate_declaration(manifest)
        except wi.Refusal as r:
            out["declaration"] = dict(r.record)
            raise Refused("FAIL_CLOSED", p1_six(r.record), r.record.get("missing")) from None
        if out["declaration"] is None:
            raise Refused("FAIL_CLOSED", six("STAGE_GATE_DECLARATION_INCOMPLETE", wi.GATE_DECLARATION_PREDICATE,
                                             "the manifest declares exit_gate_check", "re-evaluate once it is declared"))
        # Every NWI-S* manifest at the evaluated commit (the gate reads the stages there, not the pin's copies).
        stages = []
        for path in [] if source == "CONTRACT_PINS" else sorted(git(checkout, "ls-tree", "--name-only", subject["evaluated_commit"], "data/sv-work-items/stages/")
                           .stdout.decode().split()):
            if Path(path).name.startswith("NWI-S") and path.endswith(".json"):
                stages.append(json.loads(m.read_at(checkout, subject["evaluated_commit"], path)[0]))
        stages = sg.load_stages() if source == "CONTRACT_PINS" else sorted(stages, key=lambda s: s.get("ordinal", -1))
        readback = load_readback(document.get("hb_epoch_readback"))
        ledger_head = subject["base_ref"]["ledger_head"]
        mine = eb.binder_check(eb.HB_EPOCH_NOT_CROSS_CHECKED, readback, ledger_head, subject["repository"])
        try:
            ok = wi.verify_admission_hb_epoch(wi.HB_EPOCH_NOT_CROSS_CHECKED, readback, ledger_head,
                                              target_repository=subject["repository"])
        except wi.Refusal as r:
            if mine["disposition"] == "ALLOW":
                raise RuntimeError("binder_check disagrees with P1 verify_admission_hb_epoch") from None
            out["hb_epoch"] = {"observed": False, "p1": {k: r.record.get(k) for k in ("disposition", "failure_code")}}
            raise Refused("FAIL_CLOSED", six(
                "STAGE_EVIDENCE_UNOBSERVED", "UNKNOWN_NEVER_YIELDS_PASS",
                "the Labs#3266 readback (" + eb.READBACK_PIN_COMMIT[:8] + ", blob " + eb.READBACK_COMPONENT_BLOB[:8] + ") of "
                + subject["repository"] + " sealing $.hb_reference.epoch at base_ref.ledger_head " + ledger_head
                + " (verify_admission_hb_epoch: " + str(r.record.get("failure_code")) + ")",
                "re-evaluate once the readback seals the epoch; no receipt was emitted, nothing moved")) from None
        if mine["disposition"] != "ALLOW" or mine["readback_hb_epoch"] != ok["hb_epoch"]:
            raise RuntimeError("binder_check disagrees with P1 verify_admission_hb_epoch")
        epoch = ok["hb_epoch"]
        out["hb_epoch"] = {"observed": True, "hb_epoch": epoch, "ledger_head": ledger_head, "field": eb.HB_EPOCH_SOURCE_FIELD,
                           "readback_result_sha256": readback.get("result_sha256"),
                           "readback_cross_check": eb.readback_cross_check(readback),
                           "readback_component": {"pr": eb.READBACK_PR, "commit": eb.READBACK_PIN_COMMIT,
                                                  "file": eb.READBACK_COMPONENT_FILE, "blob_sha": eb.READBACK_COMPONENT_BLOB},
                           "check": "sv_work_items.verify_admission_hb_epoch(HB_EPOCH_NOT_CROSS_CHECKED, readback, "
                                    "ledger_head, target_repository=subject.repository)"}
        commit = subject["evaluated_commit"]
        evidence: dict[str, dict] = {}
        planned = []
        for p in manifest["exit_gate_check"]["evidence_producers"]:
            check_id = p["check_id"]
            missing = [q for q in p["command_paths"] if m.read_at(checkout, commit, q) is None]
            if missing:
                receipts[check_id] = gate_receipt(check_id, "FAIL_CLOSED", digest, commit, epoch, six(
                    "CHECK_COMMAND_ABSENT_AT_HEAD", "EVERY_COMMAND_PATH_IS_PRESENT_AT_THE_EXACT_HEAD",
                    "the evaluated commit carrying " + ", ".join(missing), "re-evaluate at a commit that carries them"))
                out["producers"].append({"predicate": p["predicate"], "id": check_id, "outcome": "CHECK_COMMAND_ABSENT_AT_HEAD",
                                         "absent_command_paths": missing, "disposition": "FAIL_CLOSED"})
                continue
            planned.append((check_id, list(p["offline_command"]), dict(p["expected"]), p["predicate"]))
        if planned:
            run = [(c, a, e) for c, a, e, _ in planned]
            first = m.run_row_commands(checkout, commit, run, work / "run")
            second = m.run_row_commands(checkout, commit, run, work / "run")
            for (check_id, _a, _e, predicate), a, b, bound in zip(planned, first, second, m.rc.bind(first, second)):
                disp, f = m.judge_runs(a, b)
                receipts[check_id] = gate_receipt(check_id, disp, digest, commit, epoch, None if f is None else six(
                    f[0], f[1], "repair " + check_id + " at a new evaluated commit (see the evaluation's producers entry)",
                    "repair and re-evaluate the stage"))
                out["producers"].append({"predicate": predicate, **bound, "disposition": disp})
        for p in manifest["exit_gate_check"]["evidence_producers"]:
            body = receipts[p["check_id"]]
            evidence[p["predicate"]] = {"receipt_ref": "sha256:" + hashlib.sha256(m.render(body)).hexdigest(),
                                        "check_id": p["check_id"], "disposition": body["disposition"]}
        outcome = sg.evaluate_gate(STAGE_ID, TARGET_STAGE, evidence, hb_epoch=epoch, stages=stages, subject=subject)
        out["gate_outcome"] = outcome
        disp = outcome.get("disposition")
        receipts[CHECK_ID] = gate_receipt(CHECK_ID, disp, digest, commit, epoch, None if disp == "ALLOW" else p1_six(outcome))
        schema = json.loads((m.HERE / "s1_pins" / "sv-check-receipt.v1.schema.json").read_bytes())
        checked = {}
        for check_id, body in receipts.items():
            errors = m.schema_errors(body, schema)
            try:
                checked[check_id] = None if errors else wi.validate_gate_receipt(body, subject, readback)["disposition"]
            except wi.Refusal as r:
                errors = [str(r.record.get("failure_code"))]
            if errors:
                raise Refused("FAIL_CLOSED", six("SV_CHECK_RECEIPT_INVALID", "RECEIPT_VALIDATES_AGAINST_THE_PINNED_SCHEMA",
                                                 "receipts valid against the pinned schema and P1 validate_gate_receipt",
                                                 "repair the verifier; nothing was written"), {check_id: errors})
        out["receipts_validated"] = {"schema_blob": m.RECEIPT_SCHEMA_BLOB, "p1": "sv_work_items.validate_gate_receipt",
                                     "results": checked}
        out["disposition"] = disp
        if disp != "ALLOW":
            out.update(p1_six(outcome))
    except Refused as refusal:
        receipts = {}
        out["disposition"], out["detail"] = refusal.disposition, refusal.detail
        out.update(refusal.fields)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        for name in ("sv_work_items", "stage_gate"):
            sys.modules.pop(name, None)
    out["receipts"] = {k: "sha256:" + hashlib.sha256(m.render(v)).hexdigest() for k, v in sorted(receipts.items())}
    return {**out, "evaluation_sha256": "sha256:" + hashlib.sha256(m.canon(out)).hexdigest()}, receipts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--input", type=Path, required=True)
    e.add_argument("--checkout", type=Path, required=True, help="local clone holding the evaluated commit")
    e.add_argument("--p1", type=Path, required=True, help="local StegVerse-Labs/.github clone holding the contract pin")
    e.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    evaluation, receipts = evaluate(args.input, args.checkout, args.p1)
    if args.out_dir.exists():
        shutil.rmtree(args.out_dir)
    args.out_dir.mkdir(parents=True)
    (args.out_dir / "evaluation.json").write_bytes(m.render(evaluation))
    for check_id, body in receipts.items():
        (args.out_dir / (check_id + ".json")).write_bytes(m.render(body))
    return 0 if evaluation["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
