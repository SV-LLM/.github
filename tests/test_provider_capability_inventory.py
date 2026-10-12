"""Issue #30 deterministic provider inventory tests (standard library only)."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provider_inventory", ROOT / "tools" / "validate_provider_capability_inventory.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProviderInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tree = json.loads((ROOT / "data" / "organization-tree.json").read_text(encoding="utf-8"))

    def test_current_inventory_is_18_with_all_references(self):
        result = module.inspect(self.tree)
        self.assertEqual(result["provider_count"], 18)
        self.assertEqual(result["declared_reference_count"], 18)
        self.assertEqual(result["missing_reference_count"], 0)
        self.assertEqual(result["invalid_reference_count"], 0)
        self.assertFalse(result["runtime_observation"])

    def test_mismatched_identity_is_rejected(self):
        provider = next(r for r in self.tree["repositories"] if r.get("class") == "INTELLIGENCE_PROVIDER" and r.get("capability_declaration_ref"))
        provider["capability_declaration_ref"]["repository"] = "Other"
        self.assertEqual(module.inspect(self.tree)["invalid_reference_count"], 1)

    def test_invalid_digest_is_rejected(self):
        provider = next(r for r in self.tree["repositories"] if r.get("class") == "INTELLIGENCE_PROVIDER" and r.get("capability_declaration_ref"))
        provider["capability_declaration_ref"]["declaration_sha256"] = "sha256:not-a-digest"
        self.assertEqual(module.inspect(self.tree)["invalid_reference_count"], 1)

    def test_duplicate_provider_is_rejected(self):
        provider = next(r for r in self.tree["repositories"] if r.get("class") == "INTELLIGENCE_PROVIDER")
        self.tree["repositories"].append(dict(provider))
        with self.assertRaises(ValueError):
            module.inspect(self.tree)


if __name__ == "__main__":
    unittest.main()
