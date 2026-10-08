#!/usr/bin/env python3
"""The mesh and the ledgers are written only where they were supplied.

SDK-MANIFEST-ECOSYSTEM-TRANSITION-DISPOSITION-001. The kernel resolved the
federation mesh from STEGVERSE_ORG_FEDERATION_ROOT, then XDG_STATE_HOME, then
the home directory, and the ledgers fell back the same way. A frame or receipt
written there belongs to whichever host ran the execution. Each location is now
supplied by the materializer or the attempt fails closed, names the failed
predicate and the retry edge, and the host is left untouched.

Every test runs against a copy of this repository with HOME and XDG_STATE_HOME
pointed at an empty scratch "host" directory that must stay empty. Source
validation only; no authority effect is claimed.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
STANDING = {"mode": "ESTABLISH_GENESIS", "node_ref": "sv-llm-supplied-location-test", "predecessor": None}
PEER = "StegVerse-org"
LOCATION_VARIABLES = ("STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_REPO_LEDGER_ROOT",
                      "STEGVERSE_ORG_FEDERATION_ROOT", "XDG_STATE_HOME", "HOME")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def files_under(path):
    return sorted(str(p) for p in Path(path).rglob("*") if p.is_file())


class Scratch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "sv-llm"
        shutil.copytree(REPO, self.root, ignore=shutil.ignore_patterns(".git", "__pycache__", "materialized"))
        self.host = self.base / "host"
        self.host.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in LOCATION_VARIABLES}
        env.update(HOME=str(self.host), XDG_STATE_HOME=str(self.host / "xdg"),
                   STEGVERSE_ORG_FEDERATION_ROOT=str(self.host / "env-mesh"))
        self.host_env = env
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def supply_ledgers(self):
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.base / "repo-ledger")
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(self.base / "org-ledger")

    def assertHostUntouched(self):
        self.assertEqual(files_under(self.host), [])

    def crossing(self, name):
        return load(name, self.root / "org-runtime/crossing.py")


class KernelMeshIsSupplied(Scratch):
    def setUp(self):
        super().setUp()
        self.k = load("svllm_kernel_supplied", self.root / "org-kernel/kernel.py")
        self.packet = self.k.build_packet(origin_org="SV-LLM", origin_service="sv-llm.org-control",
                                          destination_org=PEER, destination_service="stegverse-org.org-control",
                                          payload={"probe": 1}, standing=STANDING, packet_id="supplied-probe")

    def test_an_unsupplied_mesh_fails_closed_and_the_host_is_untouched(self):
        for call in (lambda: self.k.publish_packet(self.packet, now_ns=self.k.HB_ANCHOR_UNIX_NS),
                     lambda: self.k.scan_addressed_frames(PEER),
                     lambda: self.k.resolve_federation_root(None)):
            with self.assertRaisesRegex(ValueError, "mesh_location_required_from_materializer"):
                call()
        self.assertHostUntouched()

    def test_a_host_environment_mesh_binding_is_refused(self):
        with self.assertRaisesRegex(ValueError, "host_environment_mesh_binding_forbidden"):
            self.k.mesh_store(self.base / "mesh", env=dict(os.environ))
        with self.assertRaisesRegex(ValueError, "host_environment_node_state_binding_forbidden"):
            self.k.addressed_node_state_store(self.base / "node", env=dict(os.environ))

    def test_a_supplied_mesh_keeps_the_frame_layout(self):
        mesh = self.base / "mesh"
        published = self.k.publish_packet(self.packet, root=mesh, now_ns=self.k.HB_ANCHOR_UNIX_NS)
        frame = published["frame"]
        import hashlib
        expected = mesh / "frames.d" / (hashlib.sha256(
            (frame["packet_id"] + "|" + frame["frame_sha256"]).encode()).hexdigest() + ".json")
        self.assertEqual(Path(published["path"]), expected.resolve())
        self.assertEqual(json.loads(expected.read_text()), frame)
        scanned = self.k.scan_addressed_frames(PEER, root=mesh)
        self.assertEqual([item["frame"] for item in scanned], [frame])
        self.assertEqual(scanned[0]["name"], expected.name)
        self.assertEqual(self.k.node_state_provenance(mesh)["mesh_provenance"], "SUPPLIED")
        self.assertHostUntouched()

    def test_write_once_is_not_overwritten(self):
        store = self.k.mesh_store(self.base / "mesh")
        store.put_once("frames.d/x.json", {"a": 1})
        store.put_once("frames.d/x.json", {"a": 1})
        with self.assertRaises(self.k.node_store_module.WriteOnceCollision):
            store.put_once("frames.d/x.json", {"a": 2})
        self.assertEqual(store.get("frames.d/x.json"), {"a": 1})

    def test_a_frame_with_a_fabricated_heartbeat_reference_is_not_recovered(self):
        frame = self.k.carrier_frame(self.packet, epoch=40)
        body = {k: v for k, v in frame.items() if k != "frame_sha256"}
        body["heartbeat_reference"] = {**body["heartbeat_reference"], "generation": 41}
        with self.assertRaisesRegex(ValueError, "heartbeat_generation_mismatch"):
            self.k.recover_packet({**body, "frame_sha256": self.k.sha(body)})

    def test_node_markers_stay_in_the_node_state_root(self):
        mesh = self.base / "mesh"
        published = self.k.publish_packet(self.packet, root=mesh, now_ns=self.k.HB_ANCHOR_UNIX_NS)
        marker = self.k.mark_federation_frame_seen(self.root, published["path"], published["frame"], {"status": "X"})
        self.assertTrue(str(marker).startswith(str(self.root / "resident-runtime/federation/seen.d")))
        self.assertEqual(self.k.federation_seen_frame_names(self.root), {Path(published["path"]).name})
        self.assertEqual(self.k.scan_addressed_frames(PEER, root=mesh,
                                                      seen=self.k.federation_seen_frame_names(self.root)), [])


class CrossingMeshIsSupplied(Scratch):
    def setUp(self):
        super().setUp()
        self.supply_ledgers()
        self.c = self.crossing("svllm_crossing_supplied_mesh")
        self.c.open_organization_ledger(root=self.root)

    def test_egress_without_a_supplied_mesh_is_fail_closed_and_recorded(self):
        manifest = {"manifest_id": "unsupplied-mesh", "destination": {"organization": PEER}}
        out = self.c.egress(manifest, standing=STANDING, root=self.root)
        self.assertEqual((out["transition_class"], out["disposition"], out["failed_predicate"]),
                         ("ORGANIZATION_EGRESS_REFUSED", "FAIL_CLOSED", "MESH_LOCATION_REQUIRED_FROM_MATERIALIZER"))
        self.assertEqual(out["retry_entrypoint"], "org-runtime/crossing.py::egress")
        self.assertTrue(out["org_receipt_sha256"].startswith("sha256:"))
        self.assertNotIn("spool_path", out)
        self.assertHostUntouched()

    def test_ingress_without_a_supplied_mesh_is_fail_closed_and_recorded(self):
        [out] = self.c.ingress(root=self.root)
        self.assertEqual((out["transition_class"], out["disposition"], out["failed_predicate"]),
                         ("ORGANIZATION_INGRESS_REFUSED", "FAIL_CLOSED", "MESH_LOCATION_REQUIRED_FROM_MATERIALIZER"))
        self.assertEqual(out["retry_entrypoint"], "org-runtime/crossing.py::ingress")
        self.assertHostUntouched()

    def test_a_denied_crossing_names_its_retry_edge(self):
        out = self.c.egress({"manifest_id": "nowhere", "destination": {"organization": "Not-A-Peer"}},
                            standing=STANDING, mesh_root=self.base / "mesh", root=self.root)
        self.assertEqual((out["disposition"], out["failed_predicate"], out["retry_entrypoint"]),
                         ("DENY", "DESTINATION_NOT_IN_FEDERATION_DIRECTORY", "org-runtime/crossing.py::egress"))

    def test_the_command_line_requires_the_mesh(self):
        completed = subprocess.run([sys.executable, "-B", str(self.root / "org-runtime/crossing.py"), "ingress"],
                                   capture_output=True, text=True, env=dict(os.environ), cwd=self.base, timeout=120)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--mesh-root", completed.stderr)
        self.assertHostUntouched()


class LedgersAreSupplied(Scratch):
    def test_an_unsupplied_ledger_appends_nothing_anywhere(self):
        c = self.crossing("svllm_crossing_unsupplied_ledger")
        for missing in ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT"):
            with self.subTest(missing=missing):
                self.supply_ledgers()
                del os.environ[missing]
                with self.assertRaises(c.LedgerLocationRefused) as refused:
                    c.open_organization_ledger(root=self.root)
                self.assertEqual((refused.exception.disposition, refused.exception.failed_predicate),
                                 ("FAIL_CLOSED", "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER"))
                self.assertIs(refused.exception.refusal["consequence_committed"], False)
                self.assertIn(missing, refused.exception.refusal["required_evidence_or_repair"])
                self.assertTrue(refused.exception.refusal["retry_entrypoint"])
        self.assertFalse((self.base / "repo-ledger").exists())
        self.assertFalse((self.base / "org-ledger").exists())
        self.assertHostUntouched()

    def test_an_unsupplied_ledger_publishes_and_consumes_nothing(self):
        c = self.crossing("svllm_crossing_unsupplied_ledger_mesh")
        mesh = self.base / "mesh"
        mesh.mkdir()
        with self.assertRaises(c.LedgerLocationRefused):
            c.egress({"manifest_id": "unrecordable", "destination": {"organization": PEER}},
                     standing=STANDING, mesh_root=mesh, root=self.root)
        with self.assertRaises(c.LedgerLocationRefused):
            c.ingress(mesh_root=mesh, root=self.root)
        self.assertEqual(files_under(mesh), [])
        self.assertFalse((self.root / "resident-runtime/federation").exists())
        self.assertHostUntouched()

    def test_the_adopted_ledger_roots_do_not_fall_back_to_the_host(self):
        sys.path.insert(0, str(self.root / "resident-runtime"))
        self.addCleanup(sys.path.remove, str(self.root / "resident-runtime"))
        organization = load("svllm_agg_unsupplied", self.root / "resident-runtime/aggregate_repo_transition.py")
        repository = load("svllm_emit_unsupplied", self.root / ".stegverse/transition-ledger/emit.py")
        with self.assertRaises(organization.LedgerLocationRequired) as raised:
            organization.ledger_root()
        self.assertEqual(raised.exception.failed_predicate, "LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER")
        with self.assertRaisesRegex(ValueError, "ledger_location_required_from_materializer"):
            repository.lr()
        self.supply_ledgers()
        self.assertEqual(organization.ledger_root(), (self.base / "org-ledger").resolve())
        self.assertEqual(repository.lr(), (self.base / "repo-ledger").resolve())
        self.assertHostUntouched()


class CarrierIsDeclared(unittest.TestCase):
    def setUp(self):
        self.boundary = load("svllm_runtime_boundary_carrier", REPO / "org-runtime/runtime_boundary.py")
        self.document = json.loads((REPO / "org-runtime/interlock-intr.json").read_text())

    def test_the_validator_requires_the_declared_carrier(self):
        report = self.boundary.validate()
        self.assertIs(report["checks"]["egress_emitting_operation_bound"], True)
        self.assertIs(report["checks"]["ingress_receiving_operation_bound"], True)
        self.assertIs(report["valid"], True)
        egress = self.document["egress"]["emitting_operation"]
        self.assertEqual((egress["transport"], egress["carrier"], egress["github_token_runtime_authority"]),
                         ("INTERLOCK_INTR", "org-kernel/kernel.py::publish_packet", "NONE"))
        self.assertEqual(self.document["ingress"]["receiving_operation"]["carrier"],
                         "org-kernel/kernel.py::scan_addressed_frames")

    def test_the_declared_classes_are_the_ones_crossing_records(self):
        c = load("svllm_crossing_classes", REPO / "org-runtime/crossing.py")
        self.assertEqual(sorted(self.document["egress"]["emitting_operation"]["emission_transition_classes"]),
                         sorted([c.EGRESS_EMITTED, c.EGRESS_REFUSED]))
        self.assertEqual(sorted(self.document["ingress"]["receiving_operation"]["consumption_transition_classes"]),
                         sorted([c.INGRESS_MATERIALIZED, c.INGRESS_CONSUMED, c.INGRESS_REFUSED]))

    def test_an_unbound_or_authorizing_or_located_carrier_fails(self):
        for direction, key, check in (("egress", "emitting_operation", self.boundary.egress_emitting_operation_bound),
                                      ("ingress", "receiving_operation", self.boundary.ingress_receiving_operation_bound)):
            document = json.loads(json.dumps(self.document))
            document[direction].pop(key)
            self.assertIs(check(document), False)
            for field, value in [(flag, True) for flag in self.boundary.NON_AUTHORIZING_FLAGS] + [
                    ("transport", "HOSTED_GATEWAY"), ("github_token_runtime_authority", "READ"),
                    ("mesh_location", "XDG_STATE_HOME"), ("carrier", "org-kernel/kernel.py::persist_outbox")]:
                with self.subTest(direction=direction, field=field):
                    document = json.loads(json.dumps(self.document))
                    document[direction][key][field] = value
                    self.assertIs(check(document), False)


if __name__ == "__main__":
    unittest.main()
