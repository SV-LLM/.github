#!/usr/bin/env python3
"""S1 supplied-epoch binder check: the supplied hb_epoch is the bound ledger head's sealed epoch.

StegVerse-org/.github#162 (NWI-S1), S1 home #163. Invariant
ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH: for admission, hb_epoch is the
epoch on the organization-ledger head receipt the base is bound to, as sealed in
Lane C's base-state readback (StegVerse-Labs/.github#3266,
resident-runtime/sv_change_base_state_readback.py, schema
stegverse.sv-change-base-state-readback/v1).

`readback_epoch` reads that epoch from one sealed readback receipt: the receipt
must carry the readback schema, its result_sha256 seal must verify (canon/seal
vendored from #3266, segment sha256 pinned), its disposition must be ALLOW, and
its bound_main_commit must be the base. The epoch is the receipt's
READBACK_EPOCH_FIELD. The readback's own `hb_epoch` slot is the caller's supplied
value (null when none) and is never read as the source. A receipt that is
missing, unsealed, not ALLOW, bound to another base, or that seals no epoch is
FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED; a sealed epoch the shared rule (726248a5)
refuses is that rule's code. There is no fallback to a supplied constant or to a
clock.

`binder_check` then requires the supplied hb_epoch to pass the shared rule
(HB_EPOCH_NOT_SUPPLIED / HB_EPOCH_INVALID otherwise) and to equal the readback
epoch (HB_EPOCH_MISMATCH otherwise). Every non-ALLOW carries the six fields.

CLI (the argv proposed for the P1 row's supplied-epoch-binder-check):
  python3 <this script> --readback {base_state_readback} --bound-main-commit {base_commit}
      --supplied-hb-epoch {supplied_hb_epoch}
prints one canonical JSON object and exits 0 only on ALLOW. Stdlib only; reads
no clock, opens no network connection, writes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

RESULT_SCHEMA = "stegverse.sv-llm.s1-supplied-epoch-binder-check/v1"
READBACK_SCHEMA = "stegverse.sv-change-base-state-readback/v1"
READBACK_REPOSITORY = "StegVerse-Labs/.github"
READBACK_PR = "StegVerse-Labs/.github#3266"
READBACK_PIN_COMMIT = "78a0c78e1f1313bd11ff916b26a3ab467f2f54e2"
READBACK_COMPONENT_FILE = "resident-runtime/sv_change_base_state_readback.py"
READBACK_COMPONENT_BLOB = "2c369c8e6db39c6ef1e6a55e953f16a66bd36c77"
# The sealed field naming the ledger head receipt's epoch. #3266 at 78a0c78e seals no such field (its hb_epoch is
# the caller's supplied value), so every readback at that head is HB_EPOCH_SOURCE_UNOBSERVED.
READBACK_EPOCH_FIELD = "ledger_head_hb_epoch"
INVARIANT = "ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH"
OWNING_EXISTING_GOAL = "StegVerse-org/.github#162"
SOURCE_RETRY = (READBACK_PR + " " + READBACK_COMPONENT_FILE + "::evaluate (Lane C sealed base-state readback of the "
                "bound base, sealing the ledger head receipt's epoch as " + READBACK_EPOCH_FIELD + ")")
BINDER_RETRY = ("sandbox/s1_supplied_epoch_binder.py --readback <sealed readback> --bound-main-commit <base> "
                "--supplied-hb-epoch <epoch>")
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
              "owning_existing_goal", "next_attempt")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
SHARED_RULE_SHA256 = "726248a585904b52cfe2eec1754e7ce582f67d6b501bd664bb7bee80bce9b7ef"


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


# ---- vendored from READBACK_PR at READBACK_PIN_COMMIT (segment sha256 in READBACK_SEGMENT_SHA256) ----
def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal(body: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != "result_sha256"}
    return {**clean, "result_sha256": "sha256:" + hashlib.sha256(canon(clean)).hexdigest()}
# ---- end of #3266 segments ----


READBACK_SEGMENT_SHA256 = {"canon": "04066ad82faff107f0b2fcb956f83abdce94e9024e4247039cd821292ceb75ca",
                           "seal": "fde2abb781ee6a7b2533856b2228ce800cc8002c0e15dad6181268d5b77f8321"}


def six(code: str, predicate: str, repair: str, next_attempt: str, retry: str = BINDER_RETRY) -> dict[str, str]:
    return {"failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
            "retry_entrypoint": retry, "owning_existing_goal": OWNING_EXISTING_GOAL, "next_attempt": next_attempt}


def unobserved(predicate: str, detail: str) -> dict[str, str]:
    return {**six("HB_EPOCH_SOURCE_UNOBSERVED", predicate,
                  "a sealed " + READBACK_SCHEMA + " ALLOW receipt from " + READBACK_PR + " for the bound base, sealing "
                  "the organization-ledger head receipt's epoch as " + READBACK_EPOCH_FIELD + " (" + INVARIANT + "); "
                  "no supplied constant and no clock stands in for it",
                  "after Lane C's readback seals the bound ledger head epoch for this base; re-run unchanged",
                  SOURCE_RETRY), "detail": detail}


def readback_epoch(receipt: Any, bound_main_commit: Any, repository: str | None = None
                   ) -> tuple[str | None, dict[str, str] | None]:
    """(epoch, None) from a sealed readback of the bound base, or (None, six fields + detail)."""
    if not isinstance(receipt, dict) or receipt.get("schema") != READBACK_SCHEMA:
        return None, unobserved("THE_BOUND_BASE_HAS_A_SEALED_BASE_STATE_READBACK", "no " + READBACK_SCHEMA + " receipt")
    if seal(receipt).get("result_sha256") != receipt.get("result_sha256"):
        return None, unobserved("THE_BASE_STATE_READBACK_SEAL_VERIFIES", "result_sha256 does not verify")
    if receipt.get("disposition") != "ALLOW":
        return None, unobserved("THE_BASE_STATE_READBACK_IS_ALLOW",
                                "readback " + str(receipt.get("disposition")) + " " + str(receipt.get("failure_code")))
    if not isinstance(bound_main_commit, str) or not HEX40.match(bound_main_commit) \
            or receipt.get("bound_main_commit") != bound_main_commit:
        return None, unobserved("THE_BASE_STATE_READBACK_BINDS_THIS_BASE",
                                "readback binds " + str(receipt.get("bound_main_commit")) + ", base " + str(bound_main_commit))
    if repository is not None and receipt.get("repository") != repository:
        return None, unobserved("THE_BASE_STATE_READBACK_BINDS_THIS_BASE",
                                "readback repository " + str(receipt.get("repository")) + ", head " + repository)
    sealed = receipt.get(READBACK_EPOCH_FIELD)
    if sealed is None:
        return None, unobserved("THE_BASE_STATE_READBACK_SEALS_THE_LEDGER_HEAD_EPOCH",
                                "the sealed readback carries no " + READBACK_EPOCH_FIELD + " (its hb_epoch slot is the "
                                "caller's supplied value, " + json.dumps(receipt.get("hb_epoch")) + ", never the source)")
    failure = supplied_epoch_failure(sealed)
    if failure is not None:
        return None, {**six(failure[0], INVARIANT, "a sealed ledger head epoch of ASCII digits >= 32",
                            "after the readback seals a valid ledger head epoch; re-run unchanged", SOURCE_RETRY),
                      "detail": "readback " + failure[1]}
    return str(sealed), None


def binder_check(supplied: Any, receipt: Any, bound_main_commit: Any, repository: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"schema": RESULT_SCHEMA, "invariant": INVARIANT, "bound_main_commit": bound_main_commit,
                              "supplied_hb_epoch": supplied, "readback_hb_epoch": None,
                              "readback_result_sha256": receipt.get("result_sha256") if isinstance(receipt, dict) else None}
    epoch, refusal = readback_epoch(receipt, bound_main_commit, repository)
    if refusal is not None:
        return {**result, "disposition": "FAIL_CLOSED", **refusal}
    result["readback_hb_epoch"] = epoch
    failure = supplied_epoch_failure(supplied)
    if failure is not None:
        return {**result, "disposition": "FAIL_CLOSED", "detail": failure[1],
                **six(failure[0], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH", "a supplied hb_epoch of ASCII digits >= 32",
                      "re-submit with the bound ledger head epoch " + epoch)}
    if str(supplied) != epoch:
        return {**result, "disposition": "FAIL_CLOSED", "detail": "supplied " + str(supplied) + ", sealed " + epoch,
                **six("HB_EPOCH_MISMATCH", INVARIANT, "the supplied hb_epoch equal to the bound ledger head epoch " + epoch,
                      "re-submit with hb_epoch " + epoch)}
    return {**result, "disposition": "ALLOW"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--readback", type=Path, required=True, help="sealed " + READBACK_SCHEMA + " receipt (JSON)")
    parser.add_argument("--bound-main-commit", required=True)
    parser.add_argument("--repository", default=None)
    parser.add_argument("--supplied-hb-epoch", default=None, help="omitted -> HB_EPOCH_NOT_SUPPLIED")
    args = parser.parse_args(argv)
    try:
        receipt: Any = json.loads(args.readback.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        receipt = None
    result = binder_check(args.supplied_hb_epoch, receipt, args.bound_main_commit, args.repository)
    sys.stdout.buffer.write(canon(result) + b"\n")
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
