"""Sandbox entity registration predicates (successor order 2).

Fixture entities live only in this file's fixture tree. The canonical
data/organization-tree.json never contains them.

Run: python -B org-runtime/tests/test_sandbox_registration.py   (requires jsonschema)
"""
from __future__ import annotations
import copy, hashlib, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "org-runtime"))
import sandbox_registration as reg  # noqa: E402

C = reg.CANON
FIXTURES = ("FixtureEntityA", "FixtureEntityB")


def declaration(name: str, capabilities=("adversarial_review", "synthesis")) -> dict:
    return {"schema": "sv-llm.entity-capability/v0.1", "entity": name, "repository": name,
            "role": "INTELLIGENCE_CAPABILITY", "authority_effect": "NONE",
            "accepts": {"work_schema": "sv-llm.sandbox-work/v0.1"}, "capabilities": list(capabilities),
            "contribution": {"contribution_schema": "sv-llm.contribution/v0.1"},
            "interface_constraints": {"live_invocation": False},
            "prohibited": ["GOVERNANCE_DISPOSITION", "TRANSITION_AUTHORITY", "CREDENTIAL_AUTHORITY"]}


def fixture_tree() -> dict:
    rows = [{"name": ".github", "class": "ORGANIZATION_COORDINATION", "role": "coordination"},
            {"name": "sandbox", "class": "COLLABORATION_PLANE", "role": "collaboration"},
            {"name": "FixtureEntityC", "class": "INTELLIGENCE_PROVIDER", "role": "fixture without ref",
             "authority_effect": "NONE"}]
    for name in FIXTURES:
        rows.append({"name": name, "class": "ECOSYSTEM_ENTITY", "role": "fixture", "authority_effect": "NONE",
                     "capability_declaration_ref": {"repository": name, "path": "contracts/entity-capability.json",
                                                    "declaration_sha256": C.digest(declaration(name))}})
    return {"schema": "sv-llm.organization-tree/v0.2", "organization": "SV-LLM", "repositories": rows}


def text(value) -> bytes:
    return json.dumps(value, indent=2).encode()


class Vendor(unittest.TestCase):
    def test_vendored_contracts_match_manifest(self):
        manifest = reg.verify_vendor()
        self.assertEqual(manifest["canonical_source"], "SV-LLM/schemas")
        self.assertEqual(set(manifest["files"]), {"entity-capability.schema.json", "capability-id.schema.json",
                                                  "tools/sv_llm_canonical_json.py"})

    def test_vendor_drift_is_detected(self):
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as td:
            copy_root = Path(td) / "v"
            shutil.copytree(reg.VENDOR, copy_root)
            path = copy_root / "capability-id.schema.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(RuntimeError):
                reg.verify_vendor(copy_root)


class CanonicalTree(unittest.TestCase):
    def test_canonical_tree_is_valid_and_has_no_fixtures(self):
        tree = reg.load_tree()
        self.assertEqual(list(reg.TREE_VALIDATOR.iter_errors(tree)), [])
        names = {row["name"] for row in tree["repositories"]}
        self.assertFalse(names & set(FIXTURES) | {n for n in names if n.lower().startswith("fixture")})

    def test_canonical_entries_registration_state(self):
        # R1(a): only entries whose migrated declarations are bound carry a ref.
        tree = reg.load_tree()
        with_ref = {row["name"] for row in tree["repositories"] if "capability_declaration_ref" in row}
        self.assertEqual(with_ref, {"Anthropic", "OpenAI"})
        for row in tree["repositories"]:
            result = reg.register(row["name"], declaration=None)
            self.assertEqual(result["disposition"], reg.DENY)
            if row["class"] not in reg.ELIGIBLE_CLASSES:
                expected = "ENTITY_CLASS_IS_SANDBOX_ELIGIBLE"
            elif row["name"] in with_ref:
                expected = "DECLARATION_CONTENT_SUPPLIED"
            else:
                expected = "CAPABILITY_DECLARATION_REF_PRESENT"
            self.assertEqual(result["failed_predicate"], expected, row["name"])

    def test_existing_consumer_unaffected(self):
        import crossing
        self.assertIn("Anthropic", crossing.organization_repositories())


class Registration(unittest.TestCase):
    def setUp(self):
        self.tree = fixture_tree()

    def denied(self, predicate, entity="FixtureEntityA", declaration_bytes=None, tree=None):
        if declaration_bytes is None:
            declaration_bytes = text(declaration(entity))
        result = reg.register(entity, declaration=declaration_bytes, tree=self.tree if tree is None else tree)
        self.assertEqual(result["disposition"], reg.DENY, result)
        self.assertEqual(result["failed_predicate"], predicate, result)
        self.assertEqual(result["authority_effect"], "NONE")

    def test_two_fixture_entities_allow(self):
        for name in FIXTURES:
            result = reg.register(name, declaration=text(declaration(name)), tree=self.tree)
            self.assertEqual(result["disposition"], reg.ALLOW, result)
            self.assertEqual(result["declaration_sha256"], C.digest(declaration(name)))
            self.assertEqual(result["authority_effect"], "NONE")

    def test_formatting_does_not_affect_registration(self):
        compact = json.dumps(declaration("FixtureEntityA"), separators=(",", ":")).encode()
        self.assertEqual(reg.register("FixtureEntityA", declaration=compact, tree=self.tree)["disposition"], reg.ALLOW)

    def test_tree_schema(self):
        bad = copy.deepcopy(self.tree)
        bad["repositories"][0]["capability_declaration_ref"] = bad["repositories"][3]["capability_declaration_ref"]
        self.denied("ORGANIZATION_TREE_SCHEMA_VALID", tree=bad)
        bad = copy.deepcopy(self.tree)
        bad["repositories"][3]["capability_declaration_ref"]["declaration_sha256"] = "0" * 64
        self.denied("ORGANIZATION_TREE_SCHEMA_VALID", tree=bad)
        bad = copy.deepcopy(self.tree)
        bad["repositories"][3].pop("authority_effect")
        self.denied("ORGANIZATION_TREE_SCHEMA_VALID", tree=bad)

    def test_tree_names_unique(self):
        bad = copy.deepcopy(self.tree)
        bad["repositories"].append(copy.deepcopy(bad["repositories"][3]))
        self.denied("ORGANIZATION_TREE_NAMES_UNIQUE", tree=bad)

    def test_entity_not_in_tree(self):
        self.denied("ENTITY_IS_IN_CANONICAL_ORGANIZATION_TREE", entity="FixtureEntityZ")

    def test_class_not_eligible(self):
        self.denied("ENTITY_CLASS_IS_SANDBOX_ELIGIBLE", entity="sandbox")

    def test_ref_absent(self):
        self.denied("CAPABILITY_DECLARATION_REF_PRESENT", entity="FixtureEntityC")

    def test_content_not_supplied(self):
        result = reg.register("FixtureEntityA", declaration=None, tree=self.tree)
        self.assertEqual(result["failed_predicate"], "DECLARATION_CONTENT_SUPPLIED")

    def test_declaration_not_canonical_json(self):
        good = json.dumps(declaration("FixtureEntityA"))
        self.denied("DECLARATION_IS_CANONICAL_JSON",
                    declaration_bytes=good.replace('"entity": "FixtureEntityA"',
                                                   '"entity": "FixtureEntityA", "entity": "FixtureEntityA"').encode())
        self.denied("DECLARATION_IS_CANONICAL_JSON", declaration_bytes=b"\xef\xbb\xbf" + good.encode())
        self.denied("DECLARATION_IS_CANONICAL_JSON",
                    declaration_bytes=good.replace('"live_invocation": false', '"latency_ms": 1.0').encode())

    def test_declaration_schema_invalid(self):
        for mutate in (lambda d: d.update(authority_effect="ADVISORY"),
                       lambda d: d["capabilities"].append("governance"),
                       lambda d: d.update(provider="X"),
                       lambda d: d.update(schema="sv-llm.provider-capability/v0.1")):
            d = declaration("FixtureEntityA")
            mutate(d)
            self.denied("CAPABILITY_DECLARATION_IS_SCHEMA_VALID", declaration_bytes=text(d))

    def test_digest_mismatch(self):
        self.denied("DECLARATION_DIGEST_MATCHES",
                    declaration_bytes=text(declaration("FixtureEntityA", ("adversarial_review",))))

    def test_repository_mismatch(self):
        d = declaration("FixtureEntityA")
        d["repository"] = "FixtureEntityB"
        tree = copy.deepcopy(self.tree)
        tree["repositories"][3]["capability_declaration_ref"]["declaration_sha256"] = C.digest(d)
        self.denied("DECLARATION_REPOSITORY_MATCHES", declaration_bytes=text(d), tree=tree)

    def test_assignment_evidence(self):
        allowed = reg.register("FixtureEntityA", declaration=text(declaration("FixtureEntityA")), tree=self.tree)
        evidence = reg.assignment_evidence(allowed, "adversarial_review")
        C.verify_capability_assignment(evidence)
        with self.assertRaises(C.CanonicalError):
            reg.assignment_evidence(allowed, "code_generation")
        with self.assertRaises(ValueError):
            reg.assignment_evidence(reg.register("FixtureEntityC", declaration=None, tree=self.tree), "synthesis")


if __name__ == "__main__":
    unittest.main(verbosity=2)
