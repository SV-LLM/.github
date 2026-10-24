#!/usr/bin/env python3
"""Every manifest-declared entrypoint that needs an epoch declares where its epoch comes from.

B-P36n. Under ACTIONS BY MANIFEST, a declared operation that refuses without
a supplied epoch (HB_EPOCH_NOT_SUPPLIED) and has no declared epoch binding is
a stoppage by manifest. Each such operation in org-runtime/interlock-intr.json
carries `hb_epoch_binding`. The binding is required, has no clock default,
and names its sources. A `dispatch_input` source names a dispatcher workflow
that defines the input and passes it to that operation as --hb-epoch. The
activation manifest's crossing surface is one of the bound operations.
Source validation only; no authority effect is claimed.
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from workflow_surface import dispatch_record  # noqa: E402  (G17: removed dispatchers are records + FAIL_CLOSED pending)
INTERLOCK = json.loads((ROOT / "org-runtime/interlock-intr.json").read_text())
ACTIVATION = json.loads((ROOT / "org-runtime/activation.json").read_text())


def operations(node, path="interlock-intr.json"):
    """Every object in the manifest that declares a Python `operation`."""
    if isinstance(node, dict):
        if isinstance(node.get("operation"), str) and node["operation"].endswith(".py"):
            yield path, node
        for key, value in node.items():
            yield from operations(value, path + "." + key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from operations(value, path + "[" + str(index) + "]")


def needs_epoch(relative):
    return '"--hb-epoch"' in (ROOT / relative).read_text()


class ManifestEpochBinding(unittest.TestCase):
    def test_every_epoch_requiring_operation_declares_its_binding(self):
        declared = list(operations(INTERLOCK))
        self.assertTrue(declared)
        requiring = [(path, op) for path, op in declared if needs_epoch(op["operation"])]
        self.assertGreaterEqual(len(requiring), 4)
        for path, op in requiring:
            with self.subTest(operation=path):
                binding = op.get("hb_epoch_binding")
                self.assertIsInstance(binding, dict, "MANIFEST_ENTRYPOINT_LACKS_EPOCH_BINDING: " + path)
                self.assertIs(binding["required"], True)
                self.assertIs(binding["clock_default"], False)
                self.assertEqual(binding["unsupplied_failure_code"], "HB_EPOCH_NOT_SUPPLIED")
                self.assertTrue(binding["sources"])

    def test_a_dispatch_input_binding_is_passed_by_its_dispatcher(self):
        checked = 0
        for path, op in operations(INTERLOCK):
            for source in (op.get("hb_epoch_binding") or {}).get("sources", []):
                if source["from"] != "dispatch_input":
                    continue
                with self.subTest(operation=path):
                    workflow = dispatch_record(source["dispatcher"])
                    self.assertRegex(workflow, r"\n      " + re.escape(source["input"]) + r":\n")
                    self.assertRegex(workflow, r"\n  workflow_dispatch:\n")
                    self.assertRegex(workflow, re.escape("python " + op["operation"])
                                     + r"[^\n]*\\\n(\s+\S.*\\\n)*?\s+--hb-epoch \"\$HB_EPOCH\"")
                    checked += 1
        self.assertGreaterEqual(checked, 4)

    def test_every_binding_names_an_in_tree_workflow_dispatch(self):
        # 08:32Z / 08:43Z: an epoch-requiring entrypoint is dispatched in-tree, by a
        # workflow_dispatch that supplies hb_epoch; a host outside the tree is not one.
        for path, op in operations(INTERLOCK):
            binding = op.get("hb_epoch_binding")
            if not binding:
                continue
            with self.subTest(operation=path):
                dispatchers = [s["dispatcher"] for s in binding["sources"] if s["from"] == "dispatch_input"]
                self.assertTrue(dispatchers, "MANIFEST_DISPATCHER_NOT_IN_TREE: " + path)
                for dispatcher in dispatchers:
                    # in tree, or (G17) its verbatim record with a FAIL_CLOSED pending row
                    self.assertTrue(dispatch_record(dispatcher), dispatcher)

    def test_the_activation_crossing_surface_is_a_bound_operation(self):
        surface = ACTIVATION["crossing_surface"]
        bound = [op for _, op in operations(INTERLOCK) if op["operation"] == surface and op.get("hb_epoch_binding")]
        self.assertEqual(len(bound), 2, "ingress and egress")


if __name__ == "__main__":
    unittest.main()
