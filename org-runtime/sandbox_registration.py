#!/usr/bin/env python3
"""Sandbox entity registration predicates over the canonical organization tree.

An SV-LLM entity is Sandbox-registered only when every predicate below holds,
evaluated in order:

  ORGANIZATION_TREE_SCHEMA_VALID
  ORGANIZATION_TREE_NAMES_UNIQUE
  ENTITY_IS_IN_CANONICAL_ORGANIZATION_TREE
  ENTITY_CLASS_IS_SANDBOX_ELIGIBLE
  CAPABILITY_DECLARATION_REF_PRESENT
  DECLARATION_CONTENT_SUPPLIED
  DECLARATION_IS_CANONICAL_JSON          (SV_LLM_CANONICAL_JSON_V1 parser input rules)
  CAPABILITY_DECLARATION_IS_SCHEMA_VALID (sv-llm.entity-capability/v0.1)
  DECLARATION_DIGEST_MATCHES             (declaration_sha256)
  DECLARATION_REPOSITORY_MATCHES         (ref.repository == entry name == declaration.repository)

Every evaluation returns a disposition: ALLOW, or DENY naming the first failed
predicate. A DENY is a result, not an exception.

The caller supplies the declaration content. This module never reads another
repository: the digest binds the content, so where the bytes came from is not
evidence. This module writes no receipt. The receipted outcome is Sandbox's
CAPABILITY_ASSIGNMENT, whose evidence body
(entity-capability.schema.json#/$defs/capability_assignment_evidence) is
returned on ALLOW. Registration confers no governance authority.

Contracts come from the digest-verified vendored copy of SV-LLM/schemas in
org-runtime/vendor/sv-llm-schemas (see vendor-manifest.json).
"""
from __future__ import annotations
import hashlib, importlib.util, json, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "org-runtime/vendor/sv-llm-schemas"
TREE_PATH = ROOT / "data/organization-tree.json"
TREE_SCHEMA_PATH = ROOT / "data/organization-tree.schema.json"
ELIGIBLE_CLASSES = ("INTELLIGENCE_PROVIDER", "ECOSYSTEM_ENTITY")
ALLOW, DENY = "ALLOW", "DENY"


def verify_vendor(vendor: Path = VENDOR) -> dict[str, Any]:
    manifest = json.loads((vendor / "vendor-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        actual = "sha256:" + hashlib.sha256((vendor / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"VENDORED_CONTRACT_DIGEST_MISMATCH: {name}")
    return manifest


def _canonical(vendor: Path = VENDOR):
    spec = importlib.util.spec_from_file_location("sv_llm_canonical_json", vendor / "tools/sv_llm_canonical_json.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validators(vendor: Path = VENDOR):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    schemas = [json.loads((vendor / n).read_text()) for n in ("entity-capability.schema.json", "capability-id.schema.json")]
    tree_schema = json.loads(TREE_SCHEMA_PATH.read_text())
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas + [tree_schema])
    return (Draft202012Validator(tree_schema, registry=registry),
            Draft202012Validator(schemas[0], registry=registry))


verify_vendor()
CANON = _canonical()
TREE_VALIDATOR, DECLARATION_VALIDATOR = _validators()


def load_tree(path: Path = TREE_PATH) -> Any:
    return CANON.parse(path.read_bytes())


def _deny(predicate: str, entity: str, detail: str = "") -> dict[str, Any]:
    out = {"disposition": DENY, "failed_predicate": predicate, "entity": entity, "authority_effect": "NONE"}
    if detail:
        out["detail"] = detail
    return out


def register(entity: str, *, declaration: bytes | str | None, tree: Any | None = None) -> dict[str, Any]:
    """Evaluate Sandbox registration for the tree entry named `entity`."""
    tree = load_tree() if tree is None else tree
    errors = sorted(TREE_VALIDATOR.iter_errors(tree), key=lambda e: list(e.absolute_path))
    if errors:
        return _deny("ORGANIZATION_TREE_SCHEMA_VALID", entity, errors[0].message[:300])
    names = [row["name"] for row in tree["repositories"]]
    if len(names) != len(set(names)):
        return _deny("ORGANIZATION_TREE_NAMES_UNIQUE", entity)
    rows = [row for row in tree["repositories"] if row["name"] == entity]
    if not rows:
        return _deny("ENTITY_IS_IN_CANONICAL_ORGANIZATION_TREE", entity)
    row = rows[0]
    if row["class"] not in ELIGIBLE_CLASSES:
        return _deny("ENTITY_CLASS_IS_SANDBOX_ELIGIBLE", entity, row["class"])
    ref = row.get("capability_declaration_ref")
    if ref is None:
        return _deny("CAPABILITY_DECLARATION_REF_PRESENT", entity)
    if declaration is None:
        return _deny("DECLARATION_CONTENT_SUPPLIED", entity)
    try:
        parsed = CANON.parse(declaration)
    except CANON.CanonicalError as exc:
        return _deny("DECLARATION_IS_CANONICAL_JSON", entity, exc.failed_predicate)
    errors = sorted(DECLARATION_VALIDATOR.iter_errors(parsed), key=lambda e: list(e.absolute_path))
    if errors:
        return _deny("CAPABILITY_DECLARATION_IS_SCHEMA_VALID", entity, errors[0].message[:300])
    digest = CANON.digest(parsed)
    if digest != ref["declaration_sha256"]:
        return _deny("DECLARATION_DIGEST_MATCHES", entity, digest)
    if not (ref["repository"] == row["name"] == parsed["repository"]):
        return _deny("DECLARATION_REPOSITORY_MATCHES", entity)
    return {"disposition": ALLOW, "entity": entity, "class": row["class"],
            "capability_declaration_ref": ref, "declaration_sha256": digest,
            "capabilities": parsed["capabilities"], "declaration": parsed,
            "authority_effect": "NONE"}


def assignment_evidence(registration: dict[str, Any], capability: str) -> dict[str, Any]:
    """CAPABILITY_ASSIGNMENT evidence body for an ALLOWed registration (Step 1, inline declaration)."""
    if registration.get("disposition") != ALLOW:
        raise ValueError("assignment evidence requires an ALLOW registration")
    evidence = {"capability": capability, "capability_declaration_ref": registration["capability_declaration_ref"],
                "declaration": registration["declaration"]}
    CANON.verify_capability_assignment(evidence)
    return evidence


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: sandbox_registration.py ENTITY [DECLARATION_FILE]")
    content = Path(sys.argv[2]).read_bytes() if len(sys.argv) == 3 else None
    result = register(sys.argv[1], declaration=content)
    result.pop("declaration", None)
    print(json.dumps(result, indent=2, sort_keys=True))
