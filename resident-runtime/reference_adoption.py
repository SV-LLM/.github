#!/usr/bin/env python3
"""Prove SV-LLM's Organization Role ledger is the StegVerse-org reference, duplicated.

SV-LLM-ORGANIZATION-ROLE-EXACT-STEGVERSE-ORG-DUPLICATION-001 (X4, D3-D5). The
recorded coordinates in data/organization-role-reference-adoption.json name the
frozen reference commit and the digest of every adopted surface:

  byte_identical     the file is the reference file, byte for byte
  declared_insertion the file is the reference file with exactly one declared
                     block inserted at a recorded offset (the temporary
                     SV_LLM_LEGACY_RECEIPT_CHAIN wrapper); removing it yields
                     the reference byte for byte. It may also carry declared
                     substitutions, reversed as below once the block (at its
                     local offset) is removed
  declared_substitutions
                     the file is the reference file with each declared
                     (reference -> local) substitution applied exactly the
                     recorded number of times; reversing them yields the
                     reference byte for byte, and the local file's own digest
                     is recorded too
  contract           the JSON contract equals the reference apart from the
                     organization- or repository-specific keys named

`adapted` entries name a reference file this repository adapted rather than
duplicated (a workflow). Only its reference digest is recorded and checked
against the reference checkout; the adaptation itself is described in the
entry and is not claimed to be byte-identical.

`verify` runs offline against the recorded digests. `verify --reference-root`
additionally proves the recorded digests equal a checkout of the reference
commit. Any mismatch is FAIL_CLOSED REFERENCE_ADOPTION_MISMATCH and nothing
else happens; authority_effect is NONE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "data/organization-role-reference-adoption.json"
FAILED = "REFERENCE_ADOPTION_MISMATCH"


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def contract_digest(document: dict, excluded: list[str]) -> str:
    kept = {k: v for k, v in document.items() if k not in excluded}
    return digest(json.dumps(kept, sort_keys=True, separators=(",", ":")).encode())


def adopted_reference_bytes(path: str, data: bytes, entry: dict) -> tuple[bytes, list[str]]:
    """The reference bytes this adopted file claims to be, and any mismatch found on the way.

    A declared insertion may also carry declared substitutions. Its offset is
    then the block's position in the local file: the insertion is removed
    first, then the substitutions are reversed, and the local file's own
    digest is checked.
    """
    problems = []
    if "substitutions" in entry and digest(data) != entry.get("local_sha256"):
        problems.append(path + ": local bytes are not the recorded adaptation")
    if "insertion_offset" in entry:
        start, length = entry["insertion_offset"], entry["insertion_bytes"]
        block = data[start:start + length]
        if len(block) != length or digest(block) != entry["insertion_sha256"]:
            problems.append(path + ": declared insertion missing or changed")
        data = data[:start] + data[start + length:]
    if "substitutions" in entry:
        text = data.decode("utf-8")
        for substitution in entry["substitutions"]:
            if text.count(substitution["local"]) != substitution["count"]:
                problems.append(path + ": declared substitution missing or changed")
            text = text.replace(substitution["local"], substitution["reference"])
        return text.encode("utf-8"), problems
    return data, problems


def verify(root: Path = ROOT, record: dict | None = None, reference_root: Path | None = None) -> dict:
    record = record or json.loads(RECORD.read_text())
    problems = []
    for path, entry in record["files"].items():
        local = root / path
        if not local.is_file():
            problems.append(path + ": missing")
            continue
        reference_bytes, found = adopted_reference_bytes(path, local.read_bytes(), entry)
        problems += found
        if digest(reference_bytes) != entry["reference_sha256"]:
            problems.append(path + ": differs from the reference")
        if reference_root is not None and digest((reference_root / path).read_bytes()) != entry["reference_sha256"]:
            problems.append(path + ": recorded digest is not the reference commit's")
    for path, entry in record.get("adapted", {}).items():
        if not (root / path).is_file():
            problems.append(path + ": missing")
        if reference_root is not None and digest((reference_root / path).read_bytes()) != entry["reference_sha256"]:
            problems.append(path + ": recorded digest is not the reference commit's")
    for path, entry in record["contracts"].items():
        local = json.loads((root / path).read_text())
        if contract_digest(local, entry["excluded_keys"]) != entry["reference_sha256"]:
            problems.append(path + ": differs from the reference beyond " + ", ".join(entry["excluded_keys"]))
        if reference_root is not None:
            reference = json.loads((reference_root / path).read_text())
            if contract_digest(reference, entry["excluded_keys"]) != entry["reference_sha256"]:
                problems.append(path + ": recorded digest is not the reference commit's")
    result = {"schema": "sv-llm.organization-role-reference-adoption-check/v1",
              "reference": record["reference"], "checked_against_reference_checkout": reference_root is not None,
              "authority_effect": "NONE"}
    if problems:
        result.update(disposition="FAIL_CLOSED", failed_predicate=FAILED, mismatches=problems,
                      required_evidence_or_repair="Re-adopt the named files from the recorded reference commit, or "
                                                  "record a new reference commit after review.",
                      retry_entrypoint="resident-runtime/reference_adoption.py verify")
    else:
        result.update(disposition="ALLOW")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--reference-root", type=Path, help="checkout of the recorded reference commit")
    check.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = verify(reference_root=args.reference_root)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0 if result["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    sys.exit(main())
