#!/usr/bin/env python3
"""S1 supplied-epoch-binder-check: the verifier built-in for the P1 row's supplied-epoch-binder-check.

StegVerse-org/.github#162 (NWI-S1), S1 home #163. The row (StegVerse-Labs/.github#3264
76407068, blob 9c75778f) declares offline_command {verifier_builtin:
supplied-epoch-binder-check, verifier_ref: SV-LLM/.github#46, predicate: the supplied
hb_epoch equals the epoch on the readback receipt sealed by Labs#3266 at
base_ref.ledger_head, and passes 726248a5 validation}, expected {disposition: ALLOW},
command_paths []. sandbox/s1_sv_check_receipts.py dispatches on verifier_builtin to
binder_check here. Invariant ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH.

The source is one sealed stegverse.sv-change-base-state-readback/v1 receipt from Lane
C's StegVerse-Labs/.github#3266 (resident-runtime/sv_change_base_state_readback.py at
641f4b03, blob fbd453e5; canon/seal vendored, segment sha256 pinned). It mirrors P1's
in-repo reference sv_work_items.verify_admission_hb_epoch:
  FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED: no readback, not that schema, broken seal,
    not ALLOW, fixture_only, bound to another ledger head, no hb_epoch_source
    {ledger_head, field: $.hb_reference.epoch} at that head, or a sealed hb_epoch the
    shared rule 726248a5 refuses (absent, non-integer, < 32, derived_from_clock not
    exactly false);
  FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED (ruling 15:59Z/16:03Z; P1 ae8b105d): the
    supplied hb_epoch, as the epoch source (the record's hb_epoch; absent reads as null), is
    null, "", "null" or UNKNOWN_NOT_AUTHENTICALLY_OBSERVED -- checked before 726248a5;
  ALLOW with cross_checked false: the optional cross-check is left out
    (HB_EPOCH_NOT_CROSS_CHECKED; the CLI without --supplied-hb-epoch);
  DENY HB_EPOCH_MISMATCH: any other supplied hb_epoch that fails 726248a5, or a valid
    one not equal by integer value to the sealed epoch ('01024' equals 1024);
  ALLOW otherwise.
Every non-ALLOW carries the six fields (owning_existing_goal StegVerse-org/.github#162).
There is no fallback to a supplied constant or to a clock; no epoch is minted.

CLI: python3 sandbox/s1_supplied_epoch_binder.py --readback <receipt.json>
--ledger-head <base_ref.ledger_head> [--supplied-hb-epoch <epoch>] prints one canonical
JSON object; exit 0 only on ALLOW. Stdlib only; no clock, no network, writes nothing.
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
READBACK_PIN_COMMIT = "641f4b03e612d07047e15f2384d24780e2af86c0"
READBACK_COMPONENT_FILE = "resident-runtime/sv_change_base_state_readback.py"
READBACK_COMPONENT_BLOB = "fbd453e531fc8d8f62261d2a72bc7a596798a445"
# P1's in-repo reference (resident-runtime/sv_work_items.py::verify_admission_hb_epoch, Labs#3264 76407068; rule unchanged from ae8b105d): the
# readback's hb_epoch slot counts only with hb_epoch_source {ledger_head: base_ref.ledger_head, field:
# HB_EPOCH_SOURCE_FIELD}. #3266 at 641f4b03 seals hb_epoch with hb_epoch_source {ledger_head, receipt, field} (both
# null on every FAIL_CLOSED); its 78a0c78e head sealed none (unobserved).
HB_EPOCH_SOURCE_FIELD = "$.hb_reference.epoch"
CHECK_ID = "supplied-epoch-binder-check"
# The canonical rule: P1's sv_work_items.verify_admission_hb_epoch, in this blob at this commit (CI fetches and compares;
# tests/s1_binder_parity.py runs every case against it).
P1_REFERENCE = {"repository": "StegVerse-Labs/.github", "pr": "#3264", "commit": "764070689f0dd793c987d27d7cbf3252f37a6b47",
                "file": "resident-runtime/sv_work_items.py", "function": "verify_admission_hb_epoch",
                "blob_sha": "625b12f7c637b030eccc2fea03d745d12e4d36d8"}
UNOBSERVED_SENTINEL = "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"
# P1 sv_work_items.SUPPLIED_EPOCH_UNOBSERVED_VALUES (Labs#3264 ae8b105d): checked before 726248a5.
SUPPLIED_EPOCH_UNOBSERVED_VALUES = (None, "", "null", UNOBSERVED_SENTINEL)
READBACK_RECEIPT_PATH = re.compile(r"^receipts/[0-9a-f]{64}\.json$")  # P1 READBACK_RECEIPT_PATH


class _NotCrossChecked:
    """P1's HB_EPOCH_NOT_CROSS_CHECKED: an optional cross-check left out (the sealed epoch stands)."""
    def __repr__(self) -> str:
        return "HB_EPOCH_NOT_CROSS_CHECKED"


HB_EPOCH_NOT_CROSS_CHECKED = _NotCrossChecked()
INVARIANT = "ADMISSION_HB_EPOCH_IS_THE_BOUND_LEDGER_HEAD_EPOCH"
OWNING_EXISTING_GOAL = "StegVerse-org/.github#162"
SOURCE_RETRY = (READBACK_PR + " " + READBACK_COMPONENT_FILE + "::evaluate (Lane C's sealed base-state readback of "
                "base_ref.ledger_head)")
BINDER_RETRY = ("SV-LLM/.github#46 sandbox/s1_sv_check_receipts.py mint (verifier built-in "
                "supplied-epoch-binder-check) at a successor SV_CHANGE head")
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


def unobserved(detail: str) -> dict[str, Any]:
    return {"disposition": "FAIL_CLOSED", "detail": detail, **six(
        "HB_EPOCH_SOURCE_UNOBSERVED", INVARIANT,
        "a sealed ALLOW " + READBACK_SCHEMA + " receipt (" + READBACK_PR + ") for base_ref.ledger_head whose hb_epoch "
        "slot was read from " + HB_EPOCH_SOURCE_FIELD + " of that ledger head receipt (hb_epoch_source {ledger_head, "
        "field}) and passes the shared supplied-epoch rule (" + SHARED_RULE_SHA256[:8] + "); no supplied constant and no "
        "clock stands in for it",
        "after Lane C's readback seals an epoch read at that ledger head; re-run unchanged (no epoch is minted)",
        SOURCE_RETRY)}


def readback_epoch(receipt: Any, ledger_head: Any) -> tuple[str | None, dict[str, Any] | None]:
    """(sealed epoch, None), or (None, a FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED refusal with the six fields)."""
    if not isinstance(receipt, dict):
        return None, unobserved("no base-state readback receipt")
    if receipt.get("schema") != READBACK_SCHEMA:
        return None, unobserved("not a " + READBACK_SCHEMA + " receipt")
    if not isinstance(receipt.get("result_sha256"), str) or seal(receipt)["result_sha256"] != receipt["result_sha256"]:
        return None, unobserved("the readback receipt does not verify against its own body (result_sha256)")
    # #3266 @641f4b03: the epoch is observed (and sealed) on ALLOW and on DENY HB_EPOCH_MISMATCH (only the producer's
    # --hb-epoch cross-check disagreed); on every FAIL_CLOSED both slots are null.
    if not (receipt.get("disposition") == "ALLOW"
            or (receipt.get("disposition") == "DENY" and receipt.get("failure_code") == "HB_EPOCH_MISMATCH")):
        return None, unobserved("the readback receipt is %s %s, not ALLOW" % (receipt.get("disposition"),
                                                                              receipt.get("failure_code")))
    if receipt.get("fixture_only") is True:
        return None, unobserved("a fixture_only readback is not an observation")
    if not (isinstance(ledger_head, str) and HEX40.match(ledger_head)) \
            or (receipt.get("base_ref") or {}).get("ledger_head") != ledger_head:
        return None, unobserved("the readback is bound to another ledger head (base_ref.ledger_head "
                                + json.dumps(ledger_head) + ")")
    source = receipt.get("hb_epoch_source")
    if not isinstance(source, dict) or source.get("ledger_head") != ledger_head \
            or source.get("field") != HB_EPOCH_SOURCE_FIELD:
        return None, unobserved("no hb_epoch_source naming " + HB_EPOCH_SOURCE_FIELD + " at the bound head (the "
                                "readback's hb_epoch slot is " + json.dumps(receipt.get("hb_epoch")) + ")")
    if not (isinstance(source.get("receipt"), str) and READBACK_RECEIPT_PATH.match(source["receipt"])):
        return None, unobserved("hb_epoch_source.receipt is not the head receipt's ledger path receipts/<hex>.json")
    failure = supplied_epoch_failure(receipt.get("hb_epoch"), source)
    if receipt.get("hb_epoch") is None or failure is not None:
        return None, unobserved("the sealed hb_epoch slot fails the shared supplied-epoch rule: "
                                + (failure[0] + ": " + failure[1] if failure else "absent"))
    return str(receipt["hb_epoch"]), None


def binder_check(supplied: Any, receipt: Any, ledger_head: Any) -> dict[str, Any]:
    """The supplied-epoch-binder-check built-in: ALLOW, FAIL_CLOSED HB_EPOCH_SOURCE_UNOBSERVED or DENY HB_EPOCH_MISMATCH."""
    result: dict[str, Any] = {"schema": RESULT_SCHEMA, "check_id": CHECK_ID, "invariant": INVARIANT,
                              "ledger_head": ledger_head, "readback_hb_epoch": None,
                              "supplied_hb_epoch": None if supplied is HB_EPOCH_NOT_CROSS_CHECKED else supplied,
                              "cross_checked": supplied is not HB_EPOCH_NOT_CROSS_CHECKED,
                              "readback_result_sha256": receipt.get("result_sha256") if isinstance(receipt, dict) else None}
    epoch, refusal = readback_epoch(receipt, ledger_head)
    if refusal is not None:
        return {**result, **refusal}
    result["readback_hb_epoch"] = epoch
    if supplied is HB_EPOCH_NOT_CROSS_CHECKED:  # the optional cross-check left out: the sealed epoch stands
        return {**result, "disposition": "ALLOW"}
    if any(supplied is v if v is None else (isinstance(supplied, str) and supplied == v)
           for v in SUPPLIED_EPOCH_UNOBSERVED_VALUES):
        # Ruling 15:59Z / 16:03Z (P1 ae8b105d): absent, null, "", "null" and the sentinel are unobserved, checked
        # before 726248a5: FAIL_CLOSED, never DENY.
        return {**result, "disposition": "FAIL_CLOSED", "detail": "supplied " + json.dumps(supplied), **six(
            "HB_EPOCH_SOURCE_UNOBSERVED", "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
            "the SV_CHANGE carries a supplied hb_epoch (ASCII digits, 726248a5) equal to the sealed epoch " + epoch
            + " at base_ref.ledger_head " + str(ledger_head) + "; absent, null, \"\", \"null\" and "
            + UNOBSERVED_SENTINEL + " are unobserved",
            "after the SV_CHANGE is re-derived carrying the observed epoch " + epoch + "; nothing was admitted")}
    failure = supplied_epoch_failure(supplied)
    if failure is not None or not (isinstance(supplied, str) and re.fullmatch(r"[0-9]+", supplied)
                                   and int(supplied) == int(epoch)):
        detail = "supplied " + json.dumps(supplied) + ", sealed " + epoch
        if failure is not None:
            detail += " (shared rule " + SHARED_RULE_SHA256[:8] + ": " + failure[0] + ")"
        return {**result, "disposition": "DENY", "detail": detail, **six(
            "HB_EPOCH_MISMATCH", INVARIANT,
            "the SV_CHANGE's hb_epoch equals (ASCII digits, by integer value) the epoch " + epoch + " the base-state "
            "readback sealed at base_ref.ledger_head " + str(ledger_head),
            "propose a successor SV_CHANGE at the observed epoch " + epoch + "; nothing was admitted")}
    return {**result, "disposition": "ALLOW"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--readback", type=Path, required=True, help="sealed " + READBACK_SCHEMA + " receipt (JSON)")
    parser.add_argument("--ledger-head", required=True, help="the SV_CHANGE's base_ref.ledger_head")
    parser.add_argument("--supplied-hb-epoch", default=HB_EPOCH_NOT_CROSS_CHECKED,
                        help="the cross-check; omitted -> ALLOW on the sealed epoch with cross_checked false")
    args = parser.parse_args(argv)
    try:
        receipt: Any = json.loads(args.readback.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        receipt = None
    result = binder_check(args.supplied_hb_epoch, receipt, args.ledger_head)
    sys.stdout.buffer.write(canon(result) + b"\n")
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
