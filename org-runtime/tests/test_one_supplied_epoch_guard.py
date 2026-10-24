"""C8: one supplied-epoch guard per repository (ONE_SUPPLIED_EPOCH_GUARD_PER_REPO).

Every runtime writer in this repository binds org-kernel/kernel.py::supplied_epoch_failure,
the segment byte-pinned as kernel.SHARED_VALIDATOR_SHA256. Offline and deterministic:
no clock, network or credential is read. Lowest supported mode: E0.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Runtime modules (sandbox/ vendors its own S1 contract pins and is out of scope).
RUNTIME_DIRS = ("org-kernel", "org-runtime", "org-boundary", "resident-runtime", ".stegverse")


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OneSuppliedEpochGuard(unittest.TestCase):
    def test_kernel_segment_is_the_pinned_shared_rule(self):
        k = load("c8_kernel", "org-kernel/kernel.py")
        self.assertEqual(hashlib.sha256(inspect.getsource(k.supplied_epoch_failure).encode()).hexdigest(),
                         k.SHARED_VALIDATOR_SHA256)

    def test_egress_binds_the_kernel_rule(self):
        egress = load("c8_egress", "resident-runtime/organization_egress_boundary.py")
        self.assertIs(egress.supplied_epoch_failure, egress.kernel.supplied_epoch_failure)
        self.assertEqual(hashlib.sha256(inspect.getsource(egress.supplied_epoch_failure).encode()).hexdigest(),
                         egress.kernel.SHARED_VALIDATOR_SHA256)

    def test_egress_close_refusal_is_unchanged_for_absent_and_invalid_epochs(self):
        egress = load("c8_egress2", "resident-runtime/organization_egress_boundary.py")
        for value, code in ((None, "HB_EPOCH_NOT_SUPPLIED"), ("31", "HB_EPOCH_INVALID"),
                            (True, "HB_EPOCH_INVALID"), ("+33", "HB_EPOCH_INVALID")):
            refusal = egress.epoch_refusal(value, "resident-runtime/organization_egress_boundary.py::close")
            self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
            self.assertEqual(refusal["failure_code"], code)
            for field in ("failure_code", "failed_predicate", "required_evidence_or_repair",
                          "retry_entrypoint", "owning_existing_goal", "next_attempt"):
                self.assertTrue(refusal[field], field)
        self.assertIsNone(egress.epoch_refusal(4096, "x"))

    def test_no_second_definition_in_runtime_code(self):
        found = []
        for top in RUNTIME_DIRS:
            for path in sorted((ROOT / top).rglob("*.py")):
                if "/tests/" in path.as_posix():
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in tree.body:
                    if isinstance(node, ast.FunctionDef) and node.name == "supplied_epoch_failure":
                        found.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(found, ["org-kernel/kernel.py"])


if __name__ == "__main__":
    unittest.main()
