"""Every credential declaration in org-runtime/interlock-intr.json names TV/TVC as the
authority and the SKAP Vault as the only storage place, for credentials and PII alike.

Rigel 2026-10-24T17:52Z: "EVERY DISCUSSION, EVERY DESIGN DOCUMENT, EVERY COORDINATION
SURFACE SHOULD DEMONSTRATE THE INVARIANT REQUIRING THE SKAP VAULT TO BE A PII AND
CREDENTIAL STORAGE VAULT FOR EVERY USER"; 17:54Z: "INCLUDING StegVerse Ecosystem's PII and
Credentials!" / "THE HST IS THE INVARIANT ALREADY". The HST path@sha is not located yet
(StegVerse-org/.github#163 issuecomment-6387655436); interim source: continuity-vault-kit
specs/skap-vault-double-interlock.v1.json L4-6 @bcc2d75168b84b3d35b7f831df0b4fe039119631.
"""
from __future__ import annotations
import json, unittest
from pathlib import Path

BOUNDARY = Path(__file__).resolve().parents[1] / "interlock-intr.json"


def declarations(node, path="$"):
    if isinstance(node, dict):
        if "credential_authority" in node:
            yield path, node
        for k, v in node.items():
            yield from declarations(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from declarations(v, f"{path}[{i}]")


class SkapVaultCustodyDeclaration(unittest.TestCase):
    def test_tv_tvc_is_the_authority_and_the_skap_vault_the_only_storage(self):
        found = list(declarations(json.loads(BOUNDARY.read_text(encoding="utf-8"))))
        self.assertGreaterEqual(len(found), 5)
        for path, node in found:
            with self.subTest(path=path):
                self.assertEqual(node["credential_authority"], "TV/TVC")
                self.assertEqual(node.get("credential_storage_owner"), "SKAP_VAULT")
                self.assertEqual(node.get("pii_storage_owner"), "SKAP_VAULT")


if __name__ == "__main__":
    unittest.main()
