#!/usr/bin/env python3
"""Issue #30: read-only provider declaration reference inventory.

This checks repository topology and digest *syntax*, not remote content authenticity,
provider standing, runtime availability, or governance authorization.
"""
import argparse
import json
import re
from pathlib import Path

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def inspect(tree):
    providers = [r for r in tree["repositories"] if r.get("class") == "INTELLIGENCE_PROVIDER"]
    names = [r["name"] for r in providers]
    if len(names) != len(set(names)):
        raise ValueError("duplicate provider identities")
    results = []
    for provider in providers:
        ref = provider.get("capability_declaration_ref")
        problems = []
        if ref is None:
            status = "MISSING_REFERENCE"
        else:
            if ref.get("repository") != provider["name"]:
                problems.append("REPOSITORY_MISMATCH")
            path = ref.get("path")
            if not isinstance(path, str) or not path.startswith("contracts/") or ".." in Path(path).parts:
                problems.append("INVALID_DECLARATION_PATH")
            digest = ref.get("declaration_sha256")
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
                problems.append("INVALID_DIGEST_SYNTAX")
            status = "INVALID_REFERENCE" if problems else "REFERENCE_DECLARED_UNVERIFIED"
        results.append({"provider": provider["name"], "status": status, "problems": problems})
    return {
        "schema": "sv-llm.provider-reference-inventory/v1",
        "authority_effect": "NONE",
        "runtime_observation": False,
        "provider_count": len(providers),
        "declared_reference_count": sum(r["status"] == "REFERENCE_DECLARED_UNVERIFIED" for r in results),
        "missing_reference_count": sum(r["status"] == "MISSING_REFERENCE" for r in results),
        "invalid_reference_count": sum(r["status"] == "INVALID_REFERENCE" for r in results),
        "providers": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, default=Path("data/organization-tree.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect(json.loads(args.tree.read_text(encoding="utf-8")))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    if report["invalid_reference_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
