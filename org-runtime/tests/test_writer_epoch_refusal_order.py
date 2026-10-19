#!/usr/bin/env python3
"""An epoch-taking writer checks the supplied epoch before it writes or publishes anything.

B-P36b. V-P11 (SV-LLM/.github#49) found four writer paths that wrote first or
read a clock. The aggregate append fell back to the host clock and raised a
bare ValueError on an invalid epoch. crossing.egress and the egress boundary's
emit published a frame before the epoch was checked, and crossing.egress
clock-stamped that frame even at a valid epoch. crossing.record cut the
emitter's refusal down to a SystemExit string.

Each path now raises the kernel's SuppliedEpochRefused carrying the six-field
FAIL_CLOSED, before any receipt or frame is written and without reading a
clock. At "4096" the frame and the receipts carry that epoch with
derived_from_clock false. The tests run against a copy of this repository,
with scratch ledgers and mesh. Source validation only; no authority effect
is claimed.
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
PEER = "StegVerse-org"
STANDING = {"mode": "ESTABLISH_GENESIS", "node_ref": "sv-llm-epoch-order-test", "predecessor": None}
REFUSED = (None, "33.0", True, 31, "+33", " 33", "３３", "٣３", "abc", "33.7", 33.7)
SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
              "retry_entrypoint", "owning_existing_goal", "next_attempt")
LEDGER_VARIABLES = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT", "STEGVERSE_ORG_FEDERATION_ROOT")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def files_under(path):
    return sorted(str(p) for p in Path(path).rglob("*") if p.is_file())


class NoClock:
    """Stands in for a kernel's datetime: any clock read fails the test."""
    @staticmethod
    def now(*args, **kwargs):
        raise AssertionError("a clock was read")


class WriterEpochRefusalOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "sv-llm"
        shutil.copytree(REPO, cls.root, ignore=shutil.ignore_patterns(".git", "__pycache__", "materialized"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.mesh = self.base / "mesh"
        env = {k: v for k, v in os.environ.items() if k not in LEDGER_VARIABLES}
        env.update(STEGVERSE_REPO_LEDGER_ROOT=str(self.base / "repo-ledger"),
                   STEGVERSE_ORG_LEDGER_ROOT=str(self.base / "org-ledger"),
                   STEGVERSE_ORG_FEDERATION_ROOT=str(self.base / "env-mesh"))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        tag = self.id().rsplit(".", 1)[-1]
        self.crossing = load("svllm_order_crossing_" + tag, self.root / "org-runtime/crossing.py")
        self.agg = load("svllm_order_agg_" + tag, self.root / "resident-runtime/aggregate_repo_transition.py")
        self.egress = load("svllm_order_egress_" + tag, self.root / "resident-runtime/organization_egress_boundary.py")

    def open_ledger(self):
        self.crossing.open_organization_ledger(root=self.root, hb_epoch=32)

    def no_clock(self):
        kernels = {id(k): k for k in (self.crossing.kernel, self.agg.kernel, self.egress.kernel,
                                      self.egress.repository_ledger.kernel, self.egress.organization_ledger.kernel)}
        stack = [mock.patch.object(k, "datetime", NoClock) for k in kernels.values()]
        for patcher in stack:
            patcher.start()
            self.addCleanup(patcher.stop)

    def assertRefused(self, call, epoch, refused_class):
        before = files_under(self.base)
        with self.assertRaises(refused_class) as raised:
            call()
        refusal = raised.exception.refusal
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID")
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)
        self.assertIs(refusal["derived_from_clock"], False)
        self.assertIs(refusal["consequence_committed"], False)
        self.assertEqual(files_under(self.base), before, "a refused epoch wrote a receipt or a frame")

    def repo_receipt(self):
        emit = self.egress.repository_ledger
        return emit.append("B_P36B:source", "B_P36B_TEST", "sha256:" + "0" * 64, "sha256:" + "1" * 64,
                           {}, "NONE", hb_epoch=32)

    def test_the_aggregate_append_refuses_before_the_store_opens(self):
        source = self.repo_receipt()
        self.no_clock()
        for epoch in REFUSED:
            with self.subTest(epoch=epoch):
                self.assertRefused(lambda: self.agg.append(
                    source, "REPO_STATE_PROPAGATION", self.agg.GENESIS, "sha256:" + "2" * 64, {}, "NONE",
                    hb_epoch=epoch), epoch, self.agg.kernel.SuppliedEpochRefused)

    def test_the_aggregate_append_takes_the_text_4096(self):
        # V-P11 N1: the raw text "4096" used to reach kernel.hb_reference, whose
        # int check refused it with a bare ValueError.
        source = self.repo_receipt()
        self.no_clock()
        receipt = self.agg.append(source, "REPO_STATE_PROPAGATION", self.agg.GENESIS, "sha256:" + "2" * 64,
                                  {}, "NONE", hb_epoch="4096")
        self.assertEqual(receipt["hb_reference"]["epoch"], 4096)
        self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_crossing_record_carries_the_six_field_refusal(self):
        self.no_clock()
        for epoch in REFUSED:
            with self.subTest(epoch=epoch):
                self.assertRefused(lambda: self.crossing.record(
                    "B_P36B_TEST", subject={"probe": 1}, outcome={"disposition": "ALLOW"}, root=self.root,
                    genesis=True, hb_epoch=epoch), epoch, self.crossing.kernel.SuppliedEpochRefused)

    def test_crossing_egress_publishes_no_frame_for_a_refused_epoch(self):
        self.open_ledger()
        self.no_clock()
        manifest = {"manifest_id": "b-p36b-egress", "destination": {"organization": PEER}, "payload": {"probe": 1}}
        for epoch in REFUSED:
            with self.subTest(epoch=epoch):
                self.assertRefused(lambda: self.crossing.egress(
                    manifest, standing=STANDING, mesh_root=self.mesh, root=self.root, hb_epoch=epoch),
                    epoch, self.crossing.kernel.SuppliedEpochRefused)

    def test_crossing_ingress_consumes_nothing_for_a_refused_epoch(self):
        self.open_ledger()
        self.no_clock()
        for epoch in REFUSED:
            with self.subTest(epoch=epoch):
                self.assertRefused(lambda: self.crossing.ingress(
                    mesh_root=self.mesh, node_state_root=self.base / "node", root=self.root, hb_epoch=epoch),
                    epoch, self.crossing.kernel.SuppliedEpochRefused)

    def test_the_egress_boundary_emit_publishes_no_frame_for_a_refused_epoch(self):
        self.open_ledger()
        self.no_clock()
        payload = {"message_class": "ecosystem.communication", "communication_id": "b-p36b-emit",
                   "subject": "purpose-neutral mesh diagnostic",
                   "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "b-p36b"}}
        for epoch in REFUSED:
            with self.subTest(epoch=epoch):
                self.assertRefused(lambda: self.egress.emit(
                    PEER, payload, standing=STANDING, capability="intr-destination", mesh_root=self.mesh,
                    hb_epoch=epoch), epoch, self.egress.repository_ledger.kernel.SuppliedEpochRefused)

    def test_the_master_records_release_refuses_a_head_receipt_without_a_supplied_epoch(self):
        # B-P36e: the release took its epoch from the head receipt and handed
        # None to publish_packet, which then stamped the frame from the clock.
        self.open_ledger()
        genesis, = {r["receipt_sha256"]: r for r in self.documents(self.base / "org-ledger")
                    if r.get("schema") == "stegverse.organization-transition-receipt/v1"}.values()
        (self.base / "standing.json").write_text(json.dumps(STANDING))
        for epoch in REFUSED:
            with self.subTest(epoch=epoch):
                receipt = {k: v for k, v in genesis.items() if k != "receipt_sha256"}
                if epoch is None:
                    receipt.pop("hb_reference")
                else:
                    receipt["hb_reference"] = {**receipt["hb_reference"], "epoch": epoch}
                receipt["receipt_sha256"] = self.agg.sha(receipt)
                path = self.base / "receipt.json"
                path.write_text(json.dumps(receipt))
                before = files_under(self.base)
                done = subprocess.run(
                    [sys.executable, "-B", str(self.root / "resident-runtime/submit_org_transition_to_master_records.py"),
                     "--org-receipt", str(path), "--predecessor-ecosystem-state-sha256", "sha256:" + "0" * 64,
                     "--successor-ecosystem-state-sha256", "sha256:" + "1" * 64,
                     "--standing", str(self.base / "standing.json"), "--mesh-root", str(self.mesh)],
                    capture_output=True, text=True, env=dict(os.environ), timeout=120)
                self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                refusal = json.loads(done.stdout)
                self.assertEqual(refusal["failure_code"],
                                 "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID")
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual(files_under(self.base), before, "a refused release published a frame")
                path.unlink()

    @staticmethod
    def documents(root):
        for path in files_under(root):
            try:
                document = json.loads(Path(path).read_text())
            except ValueError:
                continue
            if isinstance(document, dict):
                yield document

    def receipts_at(self, epoch):
        found = {}
        for document in [*self.documents(self.base / "repo-ledger"), *self.documents(self.base / "org-ledger")]:
            reference = document.get("hb_reference")
            if isinstance(reference, dict) and reference.get("epoch") == epoch:
                # A store keeps a receipt under its key and may mirror it at HEAD.
                found[document["receipt_sha256"]] = document
        return list(found.values())

    def test_4096_frame_and_receipts_carry_the_supplied_epoch(self):
        self.open_ledger()
        self.no_clock()
        manifest = {"manifest_id": "b-p36b-4096", "destination": {"organization": PEER}, "payload": {"probe": 1}}
        out = self.crossing.egress(manifest, standing=STANDING, mesh_root=self.mesh, root=self.root,
                                   hb_epoch="4096")
        self.assertEqual(out["disposition"], "ALLOW", out)
        reference = json.loads(Path(out["spool_path"]).read_text())["heartbeat_reference"]
        self.assertEqual(reference["epoch"], 4096)
        self.assertIs(reference["derived_from_clock"], False)
        receipts = self.receipts_at(4096)
        self.assertEqual(len(receipts), 2, receipts)
        for receipt in receipts:
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_4096_emit_frame_and_receipts_carry_the_supplied_epoch(self):
        self.open_ledger()
        self.no_clock()
        payload = {"message_class": "ecosystem.communication", "communication_id": "b-p36b-emit-4096",
                   "subject": "purpose-neutral mesh diagnostic",
                   "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "b-p36b"}}
        emitted = self.egress.emit(PEER, payload, standing=STANDING, capability="intr-destination",
                                   mesh_root=self.mesh, hb_epoch="4096")
        self.assertEqual(emitted["disposition"], "ALLOW", emitted.get("detail"))
        frames = [json.loads(Path(p).read_text()) for p in files_under(self.mesh) if p.endswith(".json")]
        references = [f["heartbeat_reference"] for f in frames if isinstance(f, dict) and "heartbeat_reference" in f]
        self.assertTrue(references)
        for reference in references:
            self.assertEqual(reference["epoch"], 4096)
            self.assertIs(reference["derived_from_clock"], False)
        receipts = self.receipts_at(4096)
        self.assertEqual(len(receipts), 2, receipts)
        for receipt in receipts:
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)


if __name__ == "__main__":
    unittest.main()
