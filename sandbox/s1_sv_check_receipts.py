#!/usr/bin/env python3
"""S1 sv-check-receipt minting for SV_CHANGE heads: one receipt per row check id.

StegVerse-org/.github#162 (NWI-S1), S1 home #163. This is the only minter of
required-check receipts (row invariant
REQUIRED_CHECK_RECEIPTS_ARE_S1_VERIFIER_OUTPUTS_APPENDED_BY_ORG_WRITER); the
organization writer, StegVerse-Labs/.github#3255, appends them. Non-SV_CHANGE
heads keep sandbox/s1_required_checks_verifier.py and its interim
per-repository list.

Pins (StegVerse-Labs/.github#3264 head 76407068; tests fail on drift):
data/sv-work-items/required-checks.json blob 9c75778f (row
SV-CHANGE-REQUIRED-CHECKS-001) and schemas/sv-check-receipt.v1.schema.json blob
a4934cc1. Both are read from a supplied `--dependency labs-row=<git checkout>`
at that commit and blob; nothing is fetched.

Which ids. Exactly the row's `checks` ids, one receipt each, for every SV_CHANGE
head. The surface-required subset is P1's own required_for(touched_paths),
vendored byte-identically from resident-runtime/sv_work_items.py and pinned by
segment sha256; it is recorded in the bundle. The SV_CHANGE record is read from
the same checkout by change_id, its change_digest is recomputed with P1's rule,
and every content blob digest must be the head's bytes.

How each id runs. The row carries the commands; the head never does. For each
row id the minter reads checks.<id> verbatim: offline_command (an argv list run
from the repository root at the exact head, no network), expected
{exit_code[, stdout_json_subset][, stderr_last_line]} compared as P1's
check_outcome_matches, command_paths, and argument_bindings. The one binding the
verifier supplies is {base_commit}: the input's base_commit.sha (the merge-base
of the head with the target main, computed in the local clone; it must be an
ancestor of the head there, never fetched) -- recorded in the bundle, because
the pinned receipt schema has no field for it. A row offline_command
{verifier_builtin, verifier_ref SV-LLM/.github#46, predicate} with command_paths []
is dispatched on verifier_builtin to this verifier's own implementation
(supplied-epoch-binder-check: sandbox/s1_supplied_epoch_binder.py::binder_check;
its disposition is the receipt's: ALLOW, or DENY HB_EPOCH_MISMATCH). No per-head pass criteria are
accepted: the head's .sv/required-checks.json is not read for an SV_CHANGE head.
offline_command UNKNOWN_NOT_AUTHENTICALLY_OBSERVED (or none) is a FAIL_CLOSED
CHECK_COMMAND_UNDECLARED receipt carrying the row's command_status six fields --
an explicit refusal, never an ALLOW and never silence; a command_path absent at
the head is FAIL_CLOSED CHECK_COMMAND_ABSENT_AT_HEAD and nothing is run.
Declared commands run twice offline under the clock/network probe: a clock or
network read or output that differs is DENY; a result other than `expected` is
FAIL_CLOSED REQUIRED_CHECK_FAILED_AT_HEAD (no check is special-cased: the row's
expected stands), as is a run that does not complete; clean and as expected is ALLOW.

Receipt stegverse.sv_check_receipt.v1: check_id, disposition, change_digest
(== head.change_digest == 'sha256:' + change_id hex), head_sha, hb_epoch
(ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH: the epoch Lane C's readback,
StegVerse-Labs/.github#3266 641f4b03, sealed at the record's base_ref.ledger_head,
read from the input's hb_epoch_readback {file, sha256}; the input carries no
hb_epoch, and an unobserved source is a bundle-level FAIL_CLOSED
HB_EPOCH_SOURCE_UNOBSERVED with no receipts -- never a supplied constant or a
clock), verifier_ref, and the six fields on
any non-ALLOW. Every receipt is validated against the pinned schema before it
is written. `check` re-verifies a receipt against its head: an id outside the
row is CHECK_ID_UNDECLARED; a change_digest that is not the head's is
CHECK_SKIPPED_OR_UNOBSERVED (RECEIPT_CHANGE_DIGEST_EQUALS_HEAD).

Reads no clock, opens no network connection, passes no credential, appends no
ledger. Exit code 0 only when every minted receipt is ALLOW.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_required_checks_verifier as rc  # noqa: E402
import s1_supplied_epoch_binder as eb  # noqa: E402

HERE = Path(__file__).resolve().parent
RECEIPT_SCHEMA = "stegverse.sv_check_receipt.v1"
RECEIPT_SCHEMA_FILE = "schemas/sv-check-receipt.v1.schema.json"
BUNDLE_SCHEMA = "stegverse.sv-llm.s1-sv-check-receipt-bundle/v1"
INPUT_SCHEMA = "stegverse.sv-change.s1-sv-check-input/v1"
ROW_ID = "SV-CHANGE-REQUIRED-CHECKS-001"
ROW_FILE = "data/sv-work-items/required-checks.json"
ROW_REPOSITORY = "StegVerse-Labs/.github"
ROW_DEPENDENCY = "labs-row"
OUT_OF_TREE = "OUT_OF_TREE"  # a record outside any repository (e.g. P1's posted record), bound only by its sha256
SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
PIN_COMMIT = "764070689f0dd793c987d27d7cbf3252f37a6b47"
ROW_BLOB = "9c75778f0a88e0bb4c50a44a9d54a72bc40a496d"
RECEIPT_SCHEMA_BLOB = "a4934cc1afb5f9c65d12f4ab5ae29f462b76b3f3"
# nwi-s0-exit-gate (schema a4934cc1 enumerates it; STAGE_GATE_RECEIPT_DERIVES_NATIVE_ISSUE) is declared at #3264 76407068
# in the stage manifest data/sv-work-items/stages/NWI-S0.json (blob d5467533, vendored at sandbox/s1_pins/NWI-S0.json),
# not in the row (required-checks.json blob 9c75778f is unchanged and carries no such id). That declaration names the
# built-in and its predicate but not its inputs, so this verifier emits no receipt for it (no invented semantics) and
# records what is missing in the bundle.
STAGE_GATE_MANIFEST_FILE = "data/sv-work-items/stages/NWI-S0.json"
STAGE_GATE_MANIFEST_BLOB = "d5467533df4d604e7948805a07792829472992f1"
STAGE_GATE_CHECKS = {"nwi-s0-exit-gate": {
    "emitted": False, "status": "NOT_EMITTED_DECLARATION_INCOMPLETE",
    "declared_in": STAGE_GATE_MANIFEST_FILE + "#exit_gate_check @ " + "764070689f0dd793c987d27d7cbf3252f37a6b47",
    "declared": ["check_id", "offline_command.verifier_builtin", "offline_command.verifier_ref",
                 "offline_command.predicate (stage_gate.evaluate_gate NWI-S0 -> NWI-S1)", "expected {disposition: ALLOW}",
                 "command_paths []", "surface", "invariant", "minter", "appender"],
    "missing": [
        "evidence inputs: exit_gate predicates SV_WORK_ITEM_SCHEMAS_VALIDATE and EVERY_MIGRATION_FIXTURE_LOADS declare "
        "evidence 'receipt' but no producer, check id, path or ledger ref for those receipts; evaluate_gate needs "
        "evidence[predicate] = {receipt_ref, disposition} and nothing declares where the verifier reads them",
        "receipt subject: sv-check-receipt.v1 requires change_digest and head_sha, but the gate is 'required of no change' "
        "and no head/change the gate receipt binds to is declared",
        "hb_epoch: evaluate_gate takes hb_epoch; no Labs#3266 readback/base_ref is declared for the gate",
        "trigger: not in the row, so required_for() selects it for no SV_CHANGE; when the verifier emits it (per head "
        "minted here, or per stage evaluation) is not declared"]}}
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
              "owning_existing_goal", "next_attempt")
DISPOSITIONS = ("ALLOW", "DENY", "FAIL_CLOSED")
OWNING_EXISTING_GOAL = "StegVerse-org/.github#163 / SV-CHANGE-REQUIRED-CHECKS-001 (NWI-S1, #162)"
RETRY_ENTRYPOINT = ("sandbox/s1_sv_check_receipts.py mint --input <input.json> --checkout <head checkout> "
                    "--dependency labs-row=<StegVerse-Labs/.github checkout> --out-dir <dir>")
HB_EPOCH_PREDICATE = "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"
EXACT_HEAD_PREDICATE = "RECEIPT_CHANGE_DIGEST_EQUALS_HEAD"
SHARED_RULE_SHA256 = "726248a585904b52cfe2eec1754e7ce582f67d6b501bd664bb7bee80bce9b7ef"
P1_SOURCE = {"repository": ROW_REPOSITORY, "commit": PIN_COMMIT, "path": "resident-runtime/sv_work_items.py"}
P1_SEGMENT_SHA256 = {"LEDGER_WRITER_PATHS": "2a854d7b2ff1f0eeef7259befd2e0998a092d4610eab685412b3ee7556fe49db",
                     "surface_kind": "ad28dd85120a90740b2f85556658d61a774dafe1e4f28a39349bcd3a88b038d6",
                     "required_for": "710f20a2078b2079ebdf7734913d8acb8f99726d8b6f3d7f57badbe1c9f2d180",
                     "UNKNOWN": "e66ddd56722a720a1b9b264d41f803c04adc60d7aea70febdaeb1d585ffc8f98",
                     "sentinel_pointers": "42ef15466b7738d0532279e26ddb6f564836fd192d8af979a57674e5e00c724b"}
# P1 decision UNKNOWN_IN_NATIVE_RECORD (#3264 76407068): a NATIVE record field holding UNKNOWN is FAIL_CLOSED, never DENY;
# at admission /hb_epoch is excluded (its own FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED, decided earlier).
NATIVE_FIELDS_PREDICATE = "NATIVE_RECORD_FIELDS_ARE_OBSERVED"
ADMISSION_UNKNOWN_EXCLUDED = ("/hb_epoch",)
REQUIRED_CHECKS: Any = None  # P1's module-level default; the row is always passed explicitly here


# ---- vendored byte-identically from P1_SOURCE (segment sha256 in P1_SEGMENT_SHA256) ----
LEDGER_WRITER_PATHS = ("resident-runtime/aggregate_repo_transition.py", "resident-runtime/ledger_store.py",
                       ".stegverse/transition-ledger/emit.py", "org-kernel/kernel.py", "org-kernel/organization-ledger/",
                       "resident-runtime/propagate_repository_receipts.py", "resident-runtime/federation_cycle.py",
                       ".github/workflows/organization-ledger-transition.yml")


def surface_kind(path: str) -> str:
    """Typed surface for coverage (Q-SCENARIO-GENERALIZATION rule S1)."""
    if any(path == p or (p.endswith("/") and path.startswith(p)) for p in LEDGER_WRITER_PATHS):
        return "ledger_writer"
    if path.startswith(".github/workflows/"):
        return "workflow"
    if path.startswith("schemas/") or path.endswith(".schema.json"):
        return "schema"
    if path == "data/canonical-task-registry.json" or path.startswith("data/canonical-task-records/"):
        return "registry"
    if path.endswith(".py"):
        return "transition"
    return "doc"


def required_for(paths: Iterable[str], row: Mapping[str, Any] = REQUIRED_CHECKS) -> tuple[list[str], list[str]]:
    kinds = {surface_kind(p) for p in paths}
    checks, signoffs = set(row["surface_kinds"]["all"]["checks"]), set()
    for k in kinds:
        checks |= set(row["surface_kinds"][k]["checks"])
        signoffs |= set(row["surface_kinds"][k]["signoffs"])
    return sorted(checks), sorted(signoffs)


UNKNOWN = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"


def sentinel_pointers(rec: Any, path: str = "") -> list[str]:
    """JSON pointers holding UNKNOWN (exact or embedded). /projection is a non-authority view and is not scanned;
    writer_session.evidence_class is an enum whose value happens to be the sentinel."""
    out: list[str] = []
    if isinstance(rec, Mapping):
        for k, v in rec.items():
            p = path + "/" + str(k)
            if p == "/projection" or (k == "evidence_class" and "/writer_session" in path):
                continue
            out += sentinel_pointers(v, p)
    elif isinstance(rec, list):
        for i, v in enumerate(rec):
            out += sentinel_pointers(v, path + "/" + str(i))
    elif isinstance(rec, str) and UNKNOWN in rec:
        out.append(path or "/")
    return out
# ---- end of P1 segments ----


# ---- vendored shared supplied-epoch rule (segment sha256 SHARED_RULE_SHA256) ----
def supplied_epoch_failure(hb_epoch: Any, reference: Any = None) -> tuple[str, str] | None:
    """The shared supplied-epoch rule (SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH).

    Byte-identical in StegVerse-org/.github#185 and StegVerse-Labs/.github#3212
    and #3213. `hb_epoch` absent (None) is HB_EPOCH_NOT_SUPPLIED. Otherwise it
    must be ASCII [0-9]+ only -- an int is read as its decimal text; a bool, a
    float or anything coerced ('+33', ' 33', '3_3', '33.0') is refused -- with
    integer value >= 32 (the HB32 anchor). `reference`, the carrier frame's
    heartbeat reference when there is one, must be an object, and a
    `derived_from_clock` it carries must be exactly false. Any failure is
    HB_EPOCH_INVALID. Returns (failure_code, detail), or None when the epoch is
    supplied. No clock is read.
    """
    if reference is not None and not isinstance(reference, dict):
        return "HB_EPOCH_INVALID", "the carrier's heartbeat reference is not an object"
    if hb_epoch is None:
        return "HB_EPOCH_NOT_SUPPLIED", "no hb_epoch was supplied and no clock is read"
    if isinstance(hb_epoch, bool):
        text = None
    elif isinstance(hb_epoch, int):
        text = str(hb_epoch)
    elif isinstance(hb_epoch, str):
        text = hb_epoch
    else:
        text = None
    if text is None or not text.isascii() or not text.isdigit():
        return "HB_EPOCH_INVALID", "hb_epoch " + repr(hb_epoch) + " is not ASCII [0-9]+"
    if int(text) < 32:
        return "HB_EPOCH_INVALID", "hb_epoch " + text + " is below the HB32 anchor (32)"
    if reference is not None and "derived_from_clock" in reference \
            and reference["derived_from_clock"] is not False:
        return "HB_EPOCH_INVALID", ("the carrier's derived_from_clock is not exactly false; "
                                    "a clock-derived epoch is not a supplied one")
    return None
# ---- end of shared rule ----


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def change_identity_input(rec: Mapping[str, Any]) -> dict[str, Any]:
    """P1's sv_work_items.change_identity_input: the hashed form of change_id and head.change_digest."""
    content = []
    for c in rec.get("content") or []:
        if isinstance(c, Mapping):
            deleted = c.get("deleted", False) is True
            content.append({"path": c.get("path"), "blob_digest": None if deleted else c.get("blob_digest"),
                            "deleted": deleted})
    return {"target_repository": rec.get("target_repository"), "base_ref": dict(rec.get("base_ref") or {}),
            "content": sorted(content, key=lambda c: str(c["path"]))}


def change_digest(rec: Mapping[str, Any]) -> str:
    return "sha256:" + sha256_hex(canon(change_identity_input(rec)))


def verifier_files() -> dict[str, str]:
    files = {name: "sha256:" + sha256_hex((HERE / name).read_bytes())
             for name in ("s1_sv_check_receipts.py", "s1_supplied_epoch_binder.py")}
    files.update(rc.verifier_files())
    return files


def verifier_ref() -> str:
    return "SV-LLM/.github:sandbox/s1_sv_check_receipts.py#sha256:" + sha256_hex(canon(verifier_files()))


def row_ids(row: Mapping[str, Any]) -> list[str]:
    """P1's declared_check_ids: the only ids a receipt may carry (row["checks"])."""
    return sorted(row["checks"])


SCHEMA_KEYWORDS = {"$id", "$schema", "title", "description", "type", "properties", "required", "additionalProperties",
                   "enum", "const", "pattern", "minLength", "allOf", "if", "then"}


def schema_errors(value: Any, schema: Mapping[str, Any], at: str = "$") -> list[str]:
    """The JSON Schema subset the pinned receipt schema uses; any other keyword is an error (fail closed)."""
    errors = [at + ": unsupported keyword " + k for k in schema if k not in SCHEMA_KEYWORDS]
    kinds = {"object": dict, "string": str}
    if "type" in schema:
        if schema["type"] not in kinds:
            return errors + [at + ": unsupported type " + repr(schema["type"])]
        if not isinstance(value, kinds[schema["type"]]):
            return errors + [at + ": type"]
    if "const" in schema and value != schema["const"]:
        errors.append(at + ": const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(at + ": enum")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(at + ": pattern")
        if len(value) < schema.get("minLength", 0):
            errors.append(at + ": minLength")
    if isinstance(value, dict):
        errors += [at + ": required " + k for k in schema.get("required", []) if k not in value]
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                errors += schema_errors(v, props[k], at + "." + k)
            elif schema.get("additionalProperties") is False:
                errors.append(at + ": additional " + k)
    for sub in schema.get("allOf", []):
        errors += schema_errors(value, sub, at)
    if "if" in schema and not schema_errors(value, schema["if"], at):
        errors += schema_errors(value, schema.get("then", {}), at)
    return errors


class Global(Exception):
    def __init__(self, code: str, predicate: str, repair: str, next_attempt: str, detail: str,
                 disposition: str = "FAIL_CLOSED") -> None:
        super().__init__(code)
        self.disposition, self.detail = disposition, detail
        self.fields = six(code, predicate, repair, next_attempt)

    @classmethod
    def of(cls, refusal: Mapping[str, Any]) -> "Global":
        """A refusal that already carries its own disposition and six fields (the binder's)."""
        g = cls(refusal["failure_code"], refusal["failed_predicate"], "", "", str(refusal.get("detail")),
                refusal["disposition"])
        g.fields = {k: refusal[k] for k in SIX_FIELDS}
        return g


def six(code: str, predicate: str, repair: str, next_attempt: str) -> dict[str, str]:
    return {"failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": RETRY_ENTRYPOINT, "owning_existing_goal": OWNING_EXISTING_GOAL,
            "next_attempt": next_attempt}


def receipt(check_id: str, disposition: str, change: str, head: str, epoch: str,
            fields: dict[str, str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"schema": RECEIPT_SCHEMA, "check_id": check_id, "disposition": disposition,
                            "change_digest": change, "head_sha": head, "hb_epoch": epoch,
                            "verifier_ref": verifier_ref()}
    if disposition != "ALLOW":
        body.update(fields or {})
    return body


def read_at(checkout: Path | None, commit: str, path: str) -> tuple[bytes, str] | None:
    if checkout is None:
        return None
    blob = rc.git(checkout, "rev-parse", "--verify", "--quiet", commit + ":" + path)
    shown = rc.git(checkout, "cat-file", "blob", commit + ":" + path)
    if blob.returncode or shown.returncode:
        return None
    return shown.stdout, blob.stdout.decode().strip()


def validate_input(document: Any) -> dict[str, Any]:
    def bad(detail: str) -> Global:
        return Global("S1_INPUT_NOT_A_DECLARED_SV_CHANGE", "S1_INPUT_DECLARES_ONE_SV_CHANGE_HEAD",
                      "an input with schema " + INPUT_SCHEMA + ", type SV_CHANGE, repository, head_sha, hb_epoch_readback, "
                      "required_checks_row {repository, commit, file, blob_sha, receipt_schema_blob_sha, row_id} and "
                      "sv_change {repository, commit, file, change_id}", "re-run with the corrected input", detail)
    if not isinstance(document, dict) or document.get("schema") != INPUT_SCHEMA or document.get("type") != "SV_CHANGE":
        raise bad("schema/type")
    if not isinstance(document.get("repository"), str) or not rc.REPOSITORY.match(document["repository"]):
        raise bad("repository")
    if not isinstance(document.get("head_sha"), str) or not rc.HEX40.match(document["head_sha"]):
        raise bad("head_sha")
    row, source = document.get("required_checks_row"), document.get("sv_change")
    if not isinstance(row, dict) or row.get("repository") != ROW_REPOSITORY or row.get("file") != ROW_FILE \
            or row.get("row_id") != ROW_ID or not all(isinstance(row.get(k), str) and rc.HEX40.match(row[k])
                                                      for k in ("commit", "blob_sha", "receipt_schema_blob_sha")):
        raise bad("required_checks_row")
    local = isinstance(source, dict) and source.get("repository") == OUT_OF_TREE
    if not isinstance(source, dict) or source.get("repository") not in (ROW_REPOSITORY, OUT_OF_TREE) \
            or not isinstance(source.get("file"), str) \
            or (local and not (set(source) == {"repository", "file", "sha256", "derived_by"}
                               and isinstance(source.get("sha256"), str) and SHA256_REF.match(source["sha256"])
                               and Path(source["file"]).is_absolute() and isinstance(source.get("derived_by"), str))) \
            or (not local and not isinstance(source.get("change_id"), str)) \
            or (not local and not (isinstance(source.get("commit"), str) and rc.HEX40.match(source["commit"]))):
        raise bad("sv_change")
    if "hb_epoch" in document:  # ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH: never a supplied constant
        raise bad("hb_epoch is not an input: the receipt epoch is the one Labs#3266's readback sealed")
    readback = document.get("hb_epoch_readback", "absent")
    if readback is not None and not (isinstance(readback, dict) and set(readback) == {"file", "sha256"}
                                     and isinstance(readback["file"], str)
                                     and (SAFE_PATH.match(readback["file"]) or Path(readback["file"]).is_absolute())
                                     and isinstance(readback["sha256"], str) and SHA256_REF.match(readback["sha256"])):
        raise bad("hb_epoch_readback")
    base = document.get("base_commit")
    if base is not None and not (isinstance(base, dict) and set(base) == {"sha", "basis"}
                                 and isinstance(base["sha"], str) and rc.HEX40.match(base["sha"])
                                 and isinstance(base["basis"], str) and base["basis"]):
        raise bad("base_commit")
    return document


def load_row(spec: Mapping[str, Any], checkout: Path | None) -> tuple[dict[str, Any], str]:
    def absent(detail: str) -> Global:
        return Global("REQUIRED_CHECKS_ROW_ABSENT", "REQUIRED_CHECKS_ROW_RESOLVES",
                      ROW_FILE + " row " + ROW_ID + " at blob " + ROW_BLOB + " (commit " + PIN_COMMIT + "), supplied as "
                      "--dependency labs-row=<checkout>", "re-run with the pinned row supplied", detail)
    if spec["blob_sha"] != ROW_BLOB:
        raise absent("input pins blob " + spec["blob_sha"] + ", the verifier pins " + ROW_BLOB)
    if not rc.head_present(checkout, spec["commit"]):
        raise absent("row commit " + spec["commit"] + " not supplied")
    found = read_at(checkout, spec["commit"], ROW_FILE)
    if found is None or found[1] != ROW_BLOB:
        raise absent("blob " + (found[1] if found else "absent"))
    row = json.loads(found[0].decode("utf-8"))
    union = {c for kind in (row.get("surface_kinds") or {}).values() for c in kind.get("checks", [])}
    if row.get("row_id") != ROW_ID or not isinstance(row.get("checks"), dict) or set(row["checks"]) != union \
            or "all" not in (row.get("surface_kinds") or {}):
        raise absent("row shape")
    return row, "sha256:" + sha256_hex(found[0])


def load_schema(spec: Mapping[str, Any], checkout: Path | None) -> dict[str, Any]:
    found = read_at(checkout, spec["commit"], RECEIPT_SCHEMA_FILE)
    if spec["receipt_schema_blob_sha"] != RECEIPT_SCHEMA_BLOB or found is None or found[1] != RECEIPT_SCHEMA_BLOB:
        raise Global("CHECK_RECEIPT_SCHEMA_ABSENT", "RECEIPT_SCHEMA_RESOLVES_AT_ITS_PINNED_BLOB",
                     RECEIPT_SCHEMA_FILE + " at blob " + RECEIPT_SCHEMA_BLOB, "re-run with the pinned schema supplied",
                     "blob " + (found[1] if found else "absent"))
    schema = json.loads(found[0].decode("utf-8"))
    if ((schema.get("properties") or {}).get("schema") or {}).get("const") != RECEIPT_SCHEMA:
        raise Global("CHECK_RECEIPT_SCHEMA_ABSENT", "RECEIPT_SCHEMA_RESOLVES_AT_ITS_PINNED_BLOB",
                     "a schema whose schema const is " + RECEIPT_SCHEMA, "re-pin and re-run", "const")
    return schema


def load_change(spec: Mapping[str, Any], checkout: Path | None) -> dict[str, Any]:
    def bad(detail: str) -> Global:
        return Global("SV_CHANGE_NOT_RESOLVED", "THE_SV_CHANGE_RECORD_RESOLVES_AT_ITS_PINNED_COMMIT",
                      spec["file"] + " at " + str(spec.get("commit") or spec.get("sha256"))
                      + (" holding change_id " + spec["change_id"] if "change_id" in spec else ""),
                      "re-pin the SV_CHANGE source and re-run", detail)
    if spec["repository"] == OUT_OF_TREE:
        # One record outside any repository (P1's posted record), bound by the sha256 the input names. The input carries
        # no change_id for it: the change_id is derived from the head and must equal the record's (derived_change_id).
        try:
            data = Path(spec["file"]).read_bytes()
        except OSError:
            raise bad("file absent") from None
        if "sha256:" + sha256_hex(data) != spec["sha256"]:
            raise bad("file sha256 is not the input's")
        found = (data, None)
    elif not rc.head_present(checkout, spec["commit"]):
        raise bad("source commit not supplied")
    else:
        found = read_at(checkout, spec["commit"], spec["file"])
    if found is None:
        raise bad("file absent")
    text = found[0].decode("utf-8")
    records = [json.loads(line) for line in text.splitlines() if line.strip()] if spec["file"].endswith(".jsonl") \
        else [json.loads(text)]
    matches = [r for r in records if isinstance(r, dict)
               and ("change_id" not in spec or r.get("change_id") == spec["change_id"])]
    if len(matches) != 1:
        raise bad(str(len(matches)) + " records with that change_id")
    return matches[0]


def derived_change_id(checkout: Path, change: Mapping[str, Any], head: str) -> str:
    """The change_id derived from the head, never cached: P1's identity over target_repository, base_ref and the content of
    `git diff --no-renames --name-status <projection.base_sha> <head>` (bytes at the head; deletions as deleted). The
    record's projection.base_sha must be an ancestor of the head in the clone; it is never fetched."""
    base = (change.get("projection") or {}).get("base_sha") if isinstance(change.get("projection"), Mapping) else None
    def refuse(detail: str) -> Global:
        return Global("SV_CHANGE_ID_NOT_DERIVED_FROM_HEAD", "THE_SV_CHANGE_ID_IS_DERIVED_FROM_THE_EXACT_HEAD",
                      "a record whose change_id equals the identity of git diff projection.base_sha..head at the head",
                      "re-derive the SV_CHANGE at the head", detail)
    if not isinstance(base, str) or not rc.HEX40.match(base) or not rc.head_present(checkout, base) \
            or rc.git(checkout, "merge-base", "--is-ancestor", base, head).returncode:
        raise refuse("projection.base_sha " + str(base) + " is not an ancestor of the head in the clone")
    listed = rc.git(checkout, "diff", "--no-renames", "--name-status", base, head)
    if listed.returncode:
        raise refuse("git diff failed")
    content = []
    for line in listed.stdout.decode("utf-8").splitlines():
        status, _, path = line.partition("\t")
        deleted = status == "D"
        blob = None if deleted else rc.git(checkout, "cat-file", "blob", head + ":" + path)
        if blob is not None and blob.returncode:
            raise refuse("cannot read " + path + " at the head")
        content.append({"path": path, "deleted": deleted,
                        "blob_digest": None if deleted else "sha256:" + sha256_hex(blob.stdout)})
    return "svc:" + change_digest({"target_repository": change.get("target_repository"),
                                   "base_ref": change.get("base_ref"), "content": content})[7:]


def load_readback(spec: Mapping[str, Any] | None) -> Any:
    """The sealed Labs#3266 base-state readback the input names (a file in this repository bound by sha256), or None."""
    if spec is None:
        return None
    path = Path(spec["file"])
    try:
        data = (path if path.is_absolute() else HERE.parent / path).read_bytes()
    except OSError:
        return None
    if "sha256:" + sha256_hex(data) != spec["sha256"]:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None


def sealed_epoch(document: Mapping[str, Any], change: Mapping[str, Any]) -> tuple[str, Any, Any]:
    """(epoch, readback, ledger_head): the receipt epoch, read from the sealed readback at base_ref.ledger_head."""
    readback = load_readback(document.get("hb_epoch_readback"))
    ledger_head = (change.get("base_ref") or {}).get("ledger_head") if isinstance(change.get("base_ref"), Mapping) else None
    epoch, refusal = eb.readback_epoch(readback, ledger_head)
    if refusal is not None:
        raise Global.of(refusal)
    return epoch, readback, ledger_head


def check_receipt(body: Any, change: Mapping[str, Any], row: Mapping[str, Any],
                  schema: Mapping[str, Any], sealed: str | None = None) -> dict[str, Any]:
    """Re-verify one receipt against its head: ALLOW, or a six-field FAIL_CLOSED."""
    head_digest = (change.get("head") or {}).get("change_digest")
    head_sha = (change.get("projection") or {}).get("head_sha")

    def refuse(code: str, predicate: str, repair: str) -> dict[str, Any]:
        return {"disposition": "FAIL_CLOSED", **six(code, predicate, repair, "re-mint the receipt at the exact head")}
    if not isinstance(body, Mapping) or body.get("schema") != RECEIPT_SCHEMA:
        return refuse("SV_CHECK_RECEIPT_SCHEMA_MISMATCH", "RECORD_SCHEMA_IS_" + RECEIPT_SCHEMA, "a " + RECEIPT_SCHEMA + " receipt")
    if body.get("check_id") not in row_ids(row):
        return refuse("CHECK_ID_UNDECLARED", "CHECK_ID_IS_DECLARED_IN_" + ROW_ID.replace("-", "_"),
                      "a check id from " + ROW_ID + ": " + ", ".join(row_ids(row)))
    if body.get("change_digest") != head_digest:
        return refuse("CHECK_SKIPPED_OR_UNOBSERVED", EXACT_HEAD_PREDICATE,
                      "a receipt whose change_digest is the head's " + str(head_digest))
    if body.get("head_sha") != head_sha:
        return refuse("CHECK_SKIPPED_OR_UNOBSERVED", EXACT_HEAD_PREDICATE, "a receipt at the exact head commit " + str(head_sha))
    epoch = body.get("hb_epoch")
    failure = supplied_epoch_failure(epoch) if isinstance(epoch, str) or epoch is None else ("HB_EPOCH_INVALID", "not text")
    if failure is not None:
        return refuse(failure[0], HB_EPOCH_PREDICATE, "hb_epoch as supplied ASCII digits >= 32")
    if sealed is not None and epoch != sealed:
        return {"disposition": "DENY", **six("HB_EPOCH_MISMATCH", eb.INVARIANT,
                                             "a receipt whose hb_epoch is the sealed readback epoch " + sealed,
                                             "re-mint the receipt at the exact head")}
    errors = schema_errors(body, schema)
    if errors:
        return refuse("SV_CHECK_RECEIPT_INVALID", "RECEIPT_VALIDATES_AGAINST_THE_PINNED_SCHEMA", "; ".join(errors))
    return {"disposition": "ALLOW"}


UNDECLARED_COMMAND = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
BASE_COMMIT_ARGUMENT = "{base_commit}"  # the only verifier-supplied binding: input base_commit.sha
SAFE_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\0]+$")


BUILTINS = {eb.CHECK_ID: lambda change, readback, ledger_head: eb.binder_check(change.get("hb_epoch"), readback,
                                                                             ledger_head)}
BUILTIN_REF = "SV-LLM/.github#46"


def verifier_builtin(check_id: str, entry: Any) -> str | None:
    """P1's verifier_builtin/command_declared: offline_command {verifier_builtin, verifier_ref, predicate} (non-empty
    strings, the name is the check id), command_paths [], here also expected {disposition}, verifier_ref this PR and a
    name this verifier implements; else None (and command_declaration says why it is undeclared)."""
    if not isinstance(entry, Mapping):
        return None
    oc = entry.get("offline_command")
    if isinstance(oc, Mapping) and all(isinstance(oc.get(k), str) and oc[k] for k in
                                       ("verifier_builtin", "verifier_ref", "predicate")) \
            and entry.get("command_paths") == [] and oc["verifier_builtin"] == check_id \
            and oc["verifier_ref"] == BUILTIN_REF and check_id in BUILTINS \
            and isinstance(entry.get("expected"), Mapping) and set(entry["expected"]) == {"disposition"} \
            and entry["expected"]["disposition"] in DISPOSITIONS:
        return check_id
    return None


def command_declaration(entry: Any) -> tuple[list[str], dict[str, Any], list[str], dict[str, str]] | str:
    """The row's own command for one check id, read verbatim; a string says why it is undeclared."""
    if not isinstance(entry, Mapping) or "offline_command" not in entry:
        return "no offline_command in the row entry"
    argv, expected, paths = entry.get("offline_command"), entry.get("expected"), entry.get("command_paths")
    bindings = entry.get("argument_bindings") or {}
    if argv == UNDECLARED_COMMAND:
        return "offline_command is " + UNDECLARED_COMMAND
    if isinstance(argv, Mapping):
        return "offline_command is a verifier built-in this verifier does not implement as declared"
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        return "offline_command is not a non-empty argv list"
    if not isinstance(expected, Mapping) or type(expected.get("exit_code")) is not int \
            or not set(expected) <= {"exit_code", "stdout_json_subset", "stderr_last_line"} \
            or not isinstance(expected.get("stdout_json_subset", {}), Mapping) \
            or not isinstance(expected.get("stderr_last_line", ""), str):
        return "expected is not {exit_code[, stdout_json_subset][, stderr_last_line]}"
    if not isinstance(paths, list) or not paths or not all(isinstance(q, str) and SAFE_PATH.match(q) for q in paths):
        return "command_paths is not a non-empty list of repository-relative paths"
    if not isinstance(bindings, Mapping) or not all(isinstance(k, str) for k in bindings):
        return "argument_bindings is not an object"
    return list(argv), dict(expected), list(paths), dict(bindings)


def undeclared_fields(row: Mapping[str, Any], check_id: str) -> dict[str, str]:
    """The six fields of a FAIL_CLOSED CHECK_COMMAND_UNDECLARED receipt: the row's command_status, verbatim."""
    entry = row["checks"].get(check_id)
    status = entry.get("command_status") if isinstance(entry, Mapping) else None
    fields = six("CHECK_COMMAND_UNDECLARED", "CHECK_HAS_OFFLINE_COMMAND",
                 ROW_FILE + " " + ROW_ID + " checks." + check_id + " carrying offline_command, expected and "
                 "command_paths", "after the row declares the command; re-mint at the same head")
    if isinstance(status, Mapping) and status.get("failure_code") == "CHECK_COMMAND_UNDECLARED":
        fields.update({k: status[k] for k in SIX_FIELDS if isinstance(status.get(k), str) and status[k]})
    return fields


def outcome_matches(expected: Mapping[str, Any], code: int | None, stdout: bytes, stderr: bytes) -> bool:
    """P1's check_outcome_matches (row check_command_rule): exit_code equal; every stdout_json_subset key equal
    in the JSON stdout; stderr_last_line equal to the last non-blank stderr line."""
    if code is None or code != expected.get("exit_code"):
        return False
    if "stdout_json_subset" in expected:
        try:
            out = json.loads(stdout.decode("utf-8"))
        except (UnicodeError, ValueError):
            return False
        if not isinstance(out, dict) or any(out.get(k) != v for k, v in expected["stdout_json_subset"].items()):
            return False
    if "stderr_last_line" in expected:
        lines = [line for line in stderr.decode("utf-8", "replace").splitlines() if line.strip()]
        if not lines or lines[-1].strip() != expected["stderr_last_line"]:
            return False
    return True


def stderr_last_line(stderr: bytes) -> str | None:
    lines = [line for line in stderr.decode("utf-8", "replace").splitlines() if line.strip()]
    return lines[-1].strip() if lines else None


def stdout_subset(stdout: bytes, keys: Iterable[str]) -> dict[str, Any] | None:
    try:
        out = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    return {k: out.get(k) for k in sorted(keys)} if isinstance(out, dict) else None


def run_row_commands(head_checkout: Path, head: str, planned: list[tuple[str, list[str], dict[str, Any]]],
                     base: Path) -> list[dict[str, Any]]:
    """One run of each row command from a fresh materialization of the head; offline, clock/network probed."""
    if base.exists():
        shutil.rmtree(base)
    root = base / "head"
    env = rc.base_env(base / "home")
    (base / "home").mkdir(parents=True)
    # The exact head as a git repository (commands such as the registry fence read history): fetched from the
    # local clone by path, so nothing leaves the box; HEAD is detached at the head.
    for step in (["git", "init", "-q", str(root)],
                 ["git", "-C", str(root), "fetch", "-q", "--no-tags", str(head_checkout.resolve()), head],
                 ["git", "-C", str(root), "checkout", "-q", "--detach", head]):
        if subprocess.run(step, capture_output=True, env=env).returncode:
            raise OSError("could not materialize the head as a repository: " + " ".join(step[3:4]))
    env["PYTHONPATH"] = str(rc.PROBE)
    results = []
    for check_id, argv, expected in planned:
        log = base / ("probe-" + check_id + ".log")
        log.write_text("")
        run = [sys.executable if a in ("python", "python3") and i == 0 else a for i, a in enumerate(argv)]
        try:
            completed = subprocess.run(run, cwd=root, env={**env, "S1_PROBE_LOG": str(log)},
                                       capture_output=True, timeout=rc.CHECK_TIMEOUT_S)
            code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        except (subprocess.TimeoutExpired, OSError):
            code, stdout, stderr = None, b"", b""
        reads = sorted(set(log.read_text().split("\n")) - {""})
        met = outcome_matches(expected, code, stdout, stderr)
        # Bound: what the row's expected compares. Raw stderr/stdout carry run timings (unittest's
        # "Ran N tests in Xs") and are not part of the comparison, so only their compared parts are kept.
        results.append({"id": check_id, "kind": "row-offline-command", "command": argv, "expected": expected,
                        "exit_code": code, "stderr_last_line": stderr_last_line(stderr),
                        "stdout_json_subset": stdout_subset(stdout, (expected.get("stdout_json_subset") or {}).keys())
                        if "stdout_json_subset" in expected else None,
                        "outcome": "DID_NOT_COMPLETE" if code is None else ("AS_EXPECTED" if met else "NOT_AS_EXPECTED"),
                        "clock_reads": [r.split(" ", 1)[1] for r in reads if r.startswith("CLOCK ")],
                        "network_reads": [r.split(" ", 1)[1] for r in reads if r.startswith("NETWORK ")]})
    return results


def mint(input_path: Path, checkout: Path | None, dependencies: dict[str, Path]) -> tuple[dict[str, Any], dict[str, dict]]:
    bundle: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA, "stage": "S1", "receipt_schema": RECEIPT_SCHEMA,
        "receipt_schema_file": RECEIPT_SCHEMA_FILE, "receipt_schema_blob_sha": RECEIPT_SCHEMA_BLOB,
        "declaration_basis": "P1_ROW " + ROW_ID + " (ids and, per id, offline_command, expected, command_paths, read "
                             "verbatim); no per-head pass criteria: the head's " + rc.DECLARATION_PATH + " is not read",
        "evidence_role": "ADMISSION_INPUT_EVIDENCE_ONLY", "appended_by": "StegVerse-Labs/.github#3255 (not here)",
        "authentic_ledger_receipt": False, "authority_effect": "NONE", "verifier_clock_read": False,
        "verifier_network_read": False, "credentials_passed": False, "verifier_ref": verifier_ref(),
        "verifier": {"paths_sha256": verifier_files()}, "input_sha256": None, "row": None,
        "required_check_ids": [], "touched_surface_kinds": [], "checks": [], "receipts": {},
        "stage_gate_checks": json.loads(json.dumps(STAGE_GATE_CHECKS)),
    }
    receipts: dict[str, dict] = {}
    work = Path(tempfile.mkdtemp(prefix="sv-llm-s1svc-"))
    receipt_schema: dict[str, Any] = {}
    emit: list[str] = []
    change_d = head = epoch = None
    try:
        try:
            raw = input_path.read_bytes()
            document = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Global("S1_INPUT_NOT_READABLE", "S1_INPUT_IS_A_READABLE_JSON_SV_CHANGE", "a UTF-8 JSON input",
                         "re-run with a readable input", type(exc).__name__) from None
        bundle["input_sha256"] = "sha256:" + sha256_hex(raw)
        document = validate_input(document)
        head = document["head_sha"]
        bundle.update(repository=document["repository"], head_sha=head, hb_epoch=None,
                      hb_epoch_readback=document.get("hb_epoch_readback"))
        labs = dependencies.get(ROW_DEPENDENCY)
        row, row_digest = load_row(document["required_checks_row"], labs)
        bundle["row"] = {**document["required_checks_row"], "sha256": row_digest, "row_check_ids": row_ids(row)}
        receipt_schema = load_schema(document["required_checks_row"], labs)
        change = load_change(document["sv_change"], labs)
        bundle["sv_change"] = {**document["sv_change"], "record_mode": change.get("record_mode"),
                               "change_id": change.get("change_id"), "base_ref": change.get("base_ref"),
                               "base_sha": (change.get("projection") or {}).get("base_sha")
                               if isinstance(change.get("projection"), Mapping) else None,
                               "derived_change_id": None}
        surface_required, _signoffs = required_for(change.get("touched_paths") or [], row)
        bundle["required_check_ids"] = surface_required
        bundle["touched_surface_kinds"] = sorted({surface_kind(p) for p in change.get("touched_paths") or []})
        # ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH: the receipt epoch is the one Labs#3266's readback sealed at
        # base_ref.ledger_head; unobserved -> FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED and no schema-valid receipt can
        # carry an epoch, so the bundle is the refusal. No supplied constant, no clock.
        epoch, readback, ledger_head = sealed_epoch(document, change)
        bundle.update(hb_epoch=epoch, hb_epoch_source={
            "ledger_head": ledger_head, "readback_result_sha256": readback.get("result_sha256"),
            "field": eb.HB_EPOCH_SOURCE_FIELD, "readback_component": {
                "repository": eb.READBACK_REPOSITORY, "pr": eb.READBACK_PR, "commit": eb.READBACK_PIN_COMMIT,
                "file": eb.READBACK_COMPONENT_FILE, "blob_sha": eb.READBACK_COMPONENT_BLOB}})
        change_d = (change.get("head") or {}).get("change_digest")
        recomputed = change_digest(change)
        bundle["change_digest"] = recomputed
        if change_d != recomputed or str(change.get("change_id")) != "svc:" + recomputed[7:]:
            raise Global("SV_CHANGE_DIGEST_MISMATCH", "HEAD_CHANGE_DIGEST_EQUALS_CHANGE_ID",
                         "head.change_digest == sha256(canon(change_identity_input)) == change_id hex",
                         "reseal the SV_CHANGE", "recomputed " + recomputed)
        emit = row_ids(row)  # from here every row id gets a receipt
        if (change.get("projection") or {}).get("head_sha") != head \
                or change.get("target_repository") != document["repository"]:
            raise Global("SV_CHANGE_HEAD_MISMATCH", "THE_INPUT_HEAD_IS_THE_SV_CHANGE_HEAD",
                         "input head_sha/repository equal to the record's projection.head_sha/target_repository",
                         "correct the input", "record names " + str((change.get("projection") or {}).get("head_sha")))
        if not rc.head_present(checkout, head):
            raise Global("HEAD_NOT_MATERIALIZED", "THE_DECLARED_HEAD_IS_PRESENT_IN_THE_CHECKOUT",
                         "--checkout holding commit " + head + " (the verifier never fetches)",
                         "re-run once the checkout holds the head", "commit not present")
        root = work / "declared"
        bundle["head_tree"] = rc.materialize(checkout, head, root)
        for c in change.get("content") or []:
            path = root / str(c.get("path"))
            ok = (not path.exists()) if c.get("deleted") is True else \
                (path.is_file() and "sha256:" + sha256_hex(path.read_bytes()) == c.get("blob_digest"))
            if not ok:
                raise Global("SV_CHANGE_CONTENT_NOT_AT_HEAD", "SV_CHANGE_CONTENT_IS_THE_HEAD_TREE",
                             "every content blob_digest equal to the head's bytes", "re-derive the SV_CHANGE at the head",
                             str(c.get("path")))
        if change.get("record_mode") == "NATIVE":  # UNKNOWN_IN_NATIVE_RECORD (P1 sv_work_items.native_unknown_refusal)
            unknown = sorted(q for q in sentinel_pointers(change) if q not in ADMISSION_UNKNOWN_EXCLUDED)
            bundle["sv_change"]["native_unknown_pointers"] = unknown
            if unknown:
                raise Global("UNKNOWN_IN_NATIVE_RECORD", NATIVE_FIELDS_PREDICATE,
                             "authentically observe every field the NATIVE record holds as " + UNKNOWN + ", or record the "
                             "history as MIGRATED_HISTORICAL (UNKNOWN is FAIL_CLOSED, never DENY)",
                             "after the field is observed, propose a successor record carrying the observed value",
                             "UNKNOWN at " + ", ".join(unknown))
        derived = derived_change_id(checkout, change, head)
        bundle["sv_change"]["derived_change_id"] = derived
        if derived != change.get("change_id"):
            raise Global("SV_CHANGE_ID_NOT_DERIVED_FROM_HEAD", "THE_SV_CHANGE_ID_IS_DERIVED_FROM_THE_EXACT_HEAD",
                         "a record whose change_id equals the identity of git diff projection.base_sha..head at the head",
                         "re-derive the SV_CHANGE at the head", "derived " + derived + ", record " + str(change.get("change_id")))
        base = None
        spec = document.get("base_commit")
        if spec is not None:
            base = spec["sha"]
            if not rc.head_present(checkout, base) or rc.git(checkout, "merge-base", "--is-ancestor", base, head).returncode:
                raise Global("BASE_COMMIT_NOT_AN_ANCESTOR_IN_THE_CLONE", "THE_SUPPLIED_BASE_IS_AN_ANCESTOR_OF_THE_HEAD",
                             "base_commit.sha present in --checkout and an ancestor of " + head + " (never fetched)",
                             "re-run with the merge-base from the local clone", base)
        bundle["base_commit"] = dict(spec) if spec is not None else None
        bundle["row_commands_sha256"] = "sha256:" + sha256_hex(canon({i: row["checks"][i] for i in emit}))
        planned: list[tuple[str, list[str], dict[str, Any]]] = []
        for check_id in emit:
            entry = row["checks"].get(check_id)
            builtin = verifier_builtin(check_id, entry)
            if builtin is not None:  # built into this verifier: dispatched on verifier_builtin, nothing at the head runs
                result = BUILTINS[builtin](change, readback, ledger_head)
                ok = result["disposition"] == entry["expected"]["disposition"]
                receipts[check_id] = receipt(check_id, result["disposition"], change_d, head, epoch,
                                             None if ok else {k: result[k] for k in SIX_FIELDS})
                bundle["checks"].append({"id": check_id, "kind": "verifier-builtin", "verifier_builtin": builtin,
                                         "outcome": "AS_EXPECTED" if ok else "NOT_AS_EXPECTED",
                                         "disposition": result["disposition"],
                                         "failure_code": result.get("failure_code"),
                                         "supplied_hb_epoch": result.get("supplied_hb_epoch"),
                                         "readback_hb_epoch": result.get("readback_hb_epoch"),
                                         "cross_checked": result.get("cross_checked")})
                continue
            declared = command_declaration(entry)
            if isinstance(declared, str):
                receipts[check_id] = receipt(check_id, "FAIL_CLOSED", change_d, head, epoch, undeclared_fields(row, check_id))
                bundle["checks"].append({"id": check_id, "outcome": "CHECK_COMMAND_UNDECLARED", "detail": declared})
                continue
            argv, expected, paths, bindings = declared
            missing = [q for q in paths if not (root / q).is_file()]
            if missing:
                receipts[check_id] = receipt(check_id, "FAIL_CLOSED", change_d, head, epoch, six(
                    "CHECK_COMMAND_ABSENT_AT_HEAD", "EVERY_COMMAND_PATH_IS_PRESENT_AT_THE_EXACT_HEAD",
                    "the head carrying " + ", ".join(missing) + " (command_paths of " + check_id + ")",
                    "re-mint at a head that carries the command paths"))
                bundle["checks"].append({"id": check_id, "outcome": "CHECK_COMMAND_ABSENT_AT_HEAD",
                                         "absent_command_paths": missing})
                continue
            unbound = sorted({a for a in argv if a in bindings and a != BASE_COMMIT_ARGUMENT}
                             | ({BASE_COMMIT_ARGUMENT} if BASE_COMMIT_ARGUMENT in argv and base is None else set()))
            if unbound:
                receipts[check_id] = receipt(check_id, "FAIL_CLOSED", change_d, head, epoch, six(
                    "CHECK_ARGUMENT_NOT_SUPPLIED", "EVERY_ARGUMENT_BINDING_IS_SUPPLIED_BY_THE_VERIFIER",
                    "the input's base_commit (a 40-hex ancestor of the head present in the local clone) for "
                    + ", ".join(unbound), "re-mint with the binding supplied; nothing was run"))
                bundle["checks"].append({"id": check_id, "outcome": "CHECK_ARGUMENT_NOT_SUPPLIED", "unbound": unbound})
                continue
            planned.append((check_id, [base if a == BASE_COMMIT_ARGUMENT and a in bindings else a for a in argv],
                            expected))
        if planned:
            first = run_row_commands(checkout, head, planned, work / "run")
            second = run_row_commands(checkout, head, planned, work / "run")
            for (check_id, _argv, expected), a, b, bound in zip(planned, first, second, rc.bind(first, second)):
                bundle["checks"].append(bound)
                if "DID_NOT_COMPLETE" in (a["outcome"], b["outcome"]):
                    disp, f = "FAIL_CLOSED", ("REQUIRED_CHECK_DID_NOT_COMPLETE", "EVERY_DECLARED_CHECK_COMPLETES_OFFLINE")
                elif a["clock_reads"] or b["clock_reads"]:
                    disp, f = "DENY", ("REQUIRED_CHECK_READS_THE_CLOCK", "EVERY_DECLARED_CHECK_IS_A_FUNCTION_OF_THE_HEAD")
                elif a["network_reads"] or b["network_reads"]:
                    disp, f = "DENY", ("REQUIRED_CHECK_READS_THE_NETWORK", "EVERY_DECLARED_CHECK_RUNS_OFFLINE")
                elif a != b:
                    disp, f = "DENY", ("REQUIRED_CHECK_OUTPUT_DIFFERS_ACROSS_TWO_RUNS",
                                       "EVERY_DECLARED_CHECK_IS_A_FUNCTION_OF_THE_HEAD")
                elif a["outcome"] != "AS_EXPECTED":
                    disp, f = "FAIL_CLOSED", ("REQUIRED_CHECK_FAILED_AT_HEAD", "THE_COMMAND_GIVES_THE_ROWS_EXPECTED_RESULT")
                else:
                    disp, f = "ALLOW", None
                receipts[check_id] = receipt(check_id, disp, change_d, head, epoch, None if f is None else six(
                    f[0], f[1], "repair " + check_id + " at a new head (see the bundle's checks entry)",
                    "repair at a new head and re-mint"))
        receipts = {i: receipts[i] for i in emit}
        values = list(receipts.values())
        bundle["disposition"] = "ALLOW" if values and all(r["disposition"] == "ALLOW" for r in values) \
            else ("DENY" if any(r["disposition"] == "DENY" for r in values) else "FAIL_CLOSED")
        if bundle["disposition"] != "ALLOW":
            bundle.update(six("REQUIRED_CHECK_RECEIPTS_NOT_ALL_ALLOW", "EVERY_ROW_CHECK_IS_ALLOW_AT_THE_HEAD",
                              "an ALLOW receipt for each of " + ", ".join(emit) + " (see each receipt's six fields)",
                              "repair the non-ALLOW checks at a new head and re-mint"))
    except Global as refusal:
        bundle["disposition"], bundle["detail"] = refusal.disposition, refusal.detail
        bundle.update(refusal.fields)
        for check_id in emit:
            # A check the row gives no command is CHECK_COMMAND_UNDECLARED whatever else failed (row receipt_rule).
            undeclared = verifier_builtin(check_id, row["checks"].get(check_id)) is None \
                and isinstance(command_declaration(row["checks"].get(check_id)), str)
            receipts[check_id] = receipt(check_id, "FAIL_CLOSED", change_d, head, epoch, undeclared_fields(row, check_id)) \
                if undeclared else receipt(check_id, refusal.disposition, change_d, head, epoch, refusal.fields)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if receipts:
        invalid = {k: e for k, e in ((k, schema_errors(v, receipt_schema)) for k, v in receipts.items()) if e}
        if invalid:  # never write a receipt the pinned schema refuses
            receipts = {}
            bundle.update(disposition="FAIL_CLOSED", detail="schema errors: " + json.dumps(invalid, sort_keys=True),
                          **six("SV_CHECK_RECEIPT_INVALID", "RECEIPT_VALIDATES_AGAINST_THE_PINNED_SCHEMA",
                                "receipts valid against " + RECEIPT_SCHEMA_FILE + " blob " + RECEIPT_SCHEMA_BLOB,
                                "repair the minter and re-mint"))
        else:
            bundle["receipts_validated_against"] = {"file": RECEIPT_SCHEMA_FILE, "blob_sha": RECEIPT_SCHEMA_BLOB}
    bundle["receipts"] = {k: "sha256:" + sha256_hex(render(v)) for k, v in sorted(receipts.items())}
    return {**bundle, "bundle_sha256": "sha256:" + sha256_hex(canon(bundle))}, receipts


def render(value: Mapping[str, Any]) -> bytes:
    return canon(value) + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("mint")
    m.add_argument("--input", type=Path, required=True)
    m.add_argument("--checkout", type=Path)
    m.add_argument("--dependency", action="append", default=[], metavar="ID=CHECKOUT")
    m.add_argument("--out-dir", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("--receipt", type=Path, required=True)
    c.add_argument("--input", type=Path, required=True)
    c.add_argument("--dependency", action="append", default=[], metavar="ID=CHECKOUT")
    d = sub.add_parser("derive-change-id", help="the change_id derived from a head for a record's target and base_ref")
    d.add_argument("--checkout", type=Path, required=True)
    d.add_argument("--head", required=True)
    d.add_argument("--record-identity", type=Path, required=True,
                   help="JSON {target_repository, base_ref, projection: {base_sha}} (e.g. a bundle's sv_change)")
    args = parser.parse_args(argv)
    if args.command == "derive-change-id":
        identity = json.loads(args.record_identity.read_text())
        try:
            print(derived_change_id(args.checkout, identity, args.head))
            return 0
        except Global as refusal:
            sys.stdout.buffer.write(render({"disposition": refusal.disposition, **refusal.fields}))
            return 1
    dependencies = {k: Path(v) for k, _, v in (d.partition("=") for d in args.dependency)}
    if args.command == "check":
        try:
            document = validate_input(json.loads(args.input.read_text()))
            labs = dependencies.get(ROW_DEPENDENCY)
            row, _ = load_row(document["required_checks_row"], labs)
            schema = load_schema(document["required_checks_row"], labs)
            change = load_change(document["sv_change"], labs)
            sealed, _readback, _head = sealed_epoch(document, change)
            result = check_receipt(json.loads(args.receipt.read_text()), change, row, schema, sealed)
        except Global as refusal:
            result = {"disposition": refusal.disposition, **refusal.fields}
        sys.stdout.buffer.write(render(result))
        return 0 if result["disposition"] == "ALLOW" else 1
    bundle, receipts = mint(args.input, args.checkout, dependencies)
    if args.out_dir.exists():
        shutil.rmtree(args.out_dir)
    args.out_dir.mkdir(parents=True)
    (args.out_dir / "bundle.json").write_bytes(render(bundle))
    for check_id, body in receipts.items():
        (args.out_dir / (check_id + ".json")).write_bytes(render(body))
    return 0 if bundle["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
