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

    def repo_receipt_unwritten(self):
        body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": "SV-LLM/.github",
                "transition_id": "b-p36h-unwritten", "hb_reference": self.agg.kernel.hb_reference(epoch=32)}
        return {**body, "receipt_sha256": self.agg.sha(body)}

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

    def release(self, receipt):
        """Run the Master Records release on a one-receipt segment; return the completed process."""
        path = self.base / "receipt.json"
        path.write_text(json.dumps(receipt))
        (self.base / "standing.json").write_text(json.dumps(STANDING))
        try:
            return subprocess.run(
                [sys.executable, "-B", str(self.root / "resident-runtime/submit_org_transition_to_master_records.py"),
                 "--org-receipt", str(path), "--predecessor-ecosystem-state-sha256", "sha256:" + "0" * 64,
                 "--successor-ecosystem-state-sha256", "sha256:" + "1" * 64,
                 "--standing", str(self.base / "standing.json"), "--mesh-root", str(self.mesh)],
                capture_output=True, text=True, env=dict(os.environ), timeout=120)
        finally:
            path.unlink()
            (self.base / "standing.json").unlink()

    def org_genesis(self):
        genesis, = {r["receipt_sha256"]: r for r in self.documents(self.base / "org-ledger")
                    if r.get("schema") == "stegverse.organization-transition-receipt/v1"}.values()
        return genesis

    def test_the_release_refuses_a_clock_head_and_records_a_carried_head(self):
        # B-P36f: the head's epoch is CARRIED:ORGANIZATION_LEDGER_HEAD. A CLOCK head
        # (derived_from_clock not false, or absent beside sampled_unix_ns) is
        # refused and never re-stamped false; a valid head records its provenance.
        self.open_ledger()
        genesis = self.org_genesis()
        body = {k: v for k, v in genesis.items() if k != "receipt_sha256"}
        clock = {**body["hb_reference"], "derived_from_clock": True, "sampled_unix_ns": 1}
        unflagged = {k: v for k, v in clock.items() if k != "derived_from_clock"}
        for name, reference, code in (("derived_from_clock true", clock, "HB_EPOCH_INVALID"),
                                      ("sampled, unflagged", unflagged, "HB_EPOCH_INVALID"),
                                      ("unflagged", {k_: v for k_, v in body["hb_reference"].items()
                                                     if k_ != "derived_from_clock"}, "HB_EPOCH_PROVENANCE_UNMARKED")):
            with self.subTest(head=name):
                receipt = {**body, "hb_reference": reference}
                receipt["receipt_sha256"] = self.agg.sha(receipt)
                before = files_under(self.base)
                done = self.release(receipt)
                self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                refusal = json.loads(done.stdout)
                self.assertEqual(refusal["failure_code"], code)
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual(files_under(self.base), before)
        done = self.release(genesis)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        emitted = [r for r in self.documents(self.base / "repo-ledger")
                   if r.get("transition_class") == "ORGANIZATION_FEDERATION_CROSSING_EMITTED"]
        organization = [r for r in self.documents(self.base / "org-ledger")
                        if (r.get("boundary_evidence") or {}).get("operation") == "ORGANIZATION_FEDERATION_CROSSING_EMITTED"]
        self.assertTrue(emitted and organization)
        for receipt, evidence in [(r, r["evidence"]) for r in emitted] + [(r, r["boundary_evidence"]) for r in organization]:
            # CARRIED is classified from hb_reference alone; evidence keeps a duplicate.
            self.assertEqual(receipt["hb_reference"]["source"], "ORGANIZATION_LEDGER_HEAD")
            self.assertEqual(receipt["hb_reference"]["head_receipt_sha"], genesis["receipt_sha256"])
            self.assertEqual(receipt["hb_reference"]["epoch"], genesis["hb_reference"]["epoch"])
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)
            self.assertNotIn("sampled_unix_ns", receipt["hb_reference"])
            self.assertEqual(evidence["hb_epoch_provenance"], {
                "provenance": "CARRIED:ORGANIZATION_LEDGER_HEAD", "source": "ORGANIZATION_LEDGER_HEAD",
                "head_receipt_sha": genesis["receipt_sha256"], "epoch": genesis["hb_reference"]["epoch"],
                "derived_from_clock": False})

    def kernel_custody(self):
        k = self.crossing.kernel
        return k, k.crossing_custody(self.root, repo_ledger_root=self.base / "repo-ledger",
                                     org_ledger_root=self.base / "org-ledger")

    def packet(self, packet_id):
        k = self.crossing.kernel
        return k.build_packet(origin_org="SV-LLM", origin_service="sv-llm.org-control", destination_org=PEER,
                              destination_service="stegverse-org.org-control", payload={"probe": packet_id},
                              standing=STANDING, packet_id=packet_id)

    def test_a_recorded_emission_takes_only_a_supplied_epoch(self):
        # B-P36f: publish_packet(epoch=None) sampled the clock and record_emission
        # wrote both receipts at that epoch marked derived_from_clock false.
        self.open_ledger()
        self.no_clock()
        k, custody = self.kernel_custody()
        for epoch in REFUSED:
            with self.subTest(epoch=epoch):
                self.assertRefused(lambda: k.publish_packet(self.packet("b-p36f-publish"), root=self.mesh,
                                                            custody=custody, epoch=epoch),
                                   epoch, k.SuppliedEpochRefused)
        with self.subTest(now_ns="sample"):
            self.assertRefused(lambda: k.publish_packet(self.packet("b-p36f-sample"), root=self.mesh, custody=custody,
                                                        now_ns=k.HB_ANCHOR_UNIX_NS),
                               None, k.SuppliedEpochRefused)
        with self.subTest(fanout="publish_ecosystem_message"):
            self.assertRefused(lambda: k.publish_ecosystem_message(
                origin_org="SV-LLM", origin_service="sv-llm.org-control", organizations=[PEER],
                standing=STANDING, message_class="ecosystem.communication", subject="b-p36f", body={"probe": 1},
                root=self.mesh, custody=custody), None, k.SuppliedEpochRefused)
        with self.subTest(frame="clock-stamped"):
            frame = k.carrier_frame(self.packet("b-p36f-clock"), now_ns=k.HB_ANCHOR_UNIX_NS + 10 ** 12)
            self.assertRefused(lambda: k.record_emission(custody, frame, self.packet("b-p36f-clock")),
                               "clock", k.SuppliedEpochRefused)
        published = k.publish_packet(self.packet("b-p36f-4096"), root=self.mesh, custody=custody, epoch="4096")
        self.assertEqual(published["frame"]["heartbeat_reference"]["epoch"], 4096)
        self.assertIs(published["frame"]["heartbeat_reference"]["derived_from_clock"], False)
        receipts = self.receipts_at(4096)
        self.assertEqual(len(receipts), 2, receipts)
        for receipt in receipts:
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def inbound(self, k, packet_id, **reference):
        """Publish a monitor request addressed to SV-LLM with the given frame reference."""
        packet = k.build_packet(origin_org=PEER, origin_service="stegverse-org.org-control", destination_org="SV-LLM",
                                destination_service="sv-llm.org-control",
                                payload={"message_class": "ecosystem.monitor.request", "subject": packet_id},
                                standing=STANDING, packet_id=packet_id)
        frame = k.carrier_frame(packet, **reference)
        k._publish_frame(frame, root=self.mesh)
        return frame

    def forged(self, k, packet_id):
        """A frame that self-asserts a CARRIED provenance naming an invented ledger head."""
        packet = k.build_packet(origin_org=PEER, origin_service="stegverse-org.org-control", destination_org="SV-LLM",
                                destination_service="sv-llm.org-control",
                                payload={"message_class": "ecosystem.monitor.request", "subject": packet_id},
                                standing=STANDING, packet_id=packet_id)
        frame = k.carrier_frame(packet, epoch=4096)
        body = {key: value for key, value in frame.items() if key != "frame_sha256"}
        body["heartbeat_reference"] = {**body["heartbeat_reference"], "source": "ORGANIZATION_LEDGER_HEAD",
                                       "head_receipt_sha": "sha256:" + "f" * 64}
        frame = {**body, "frame_sha256": k.sha(body)}
        k._publish_frame(frame, root=self.mesh)
        return frame

    def test_a_refused_frame_is_quarantined_and_never_blocks_a_later_cycle(self):
        # B-P36j: a CLOCK frame in a mixed batch gets a six-field quarantine
        # seen-marker and nothing else; the valid frame is consumed; a second
        # cycle proceeds without retrying the CLOCK frame; nothing is clock-stamped.
        self.open_ledger()
        k, _ = self.kernel_custody()
        clock = self.inbound(k, "b-p36j-clock", now_ns=k.HB_ANCHOR_UNIX_NS + 10 ** 12)
        self.inbound(k, "b-p36j-valid", epoch=4096)
        clock_epoch = clock["heartbeat_reference"]["epoch"]
        self.no_clock()
        node = self.base / "node"
        ledgers = {"repo_ledger_root": self.base / "repo-ledger", "org_ledger_root": self.base / "org-ledger"}
        first = k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node, **ledgers)
        by_packet = {row["result"].get("packet", {}).get("packet_id") or row["path"]: row for row in first}
        quarantined = [row for row in first if row["result"].get("quarantine") == "FRAME_REFUSED_QUARANTINED"]
        self.assertEqual(len(quarantined), 1, first)
        for field in SIX_FIELDS:
            self.assertTrue(quarantined[0]["result"][field], field)
        self.assertIsNone(quarantined[0]["organization_record"])
        marker = json.loads(Path(quarantined[0]["seen_marker"]).read_text())
        self.assertEqual((marker["status"], marker["quarantine"], marker["failure_code"]),
                         ("REFUSED", "FRAME_REFUSED_QUARANTINED", "HB_EPOCH_NOT_SUPPLIED"))
        self.assertEqual(len([row for row in first if row["result"].get("status") == "CONSUMED"]), 1, by_packet)
        before = files_under(self.base)
        second = k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node, **ledgers)
        self.assertEqual(second, [])
        self.assertEqual(files_under(self.base), before)
        self.assertEqual(self.receipts_at(clock_epoch), [])
        references = [d["hb_reference"] for d in [*self.documents(self.base / "repo-ledger"),
                                                   *self.documents(self.base / "org-ledger")] if "hb_reference" in d]
        for reference in references:
            self.assertIs(reference["derived_from_clock"], False)
            self.assertNotIn("sampled_unix_ns", reference)

    def test_crossing_ingress_consumes_a_clock_frame_lending_no_epoch(self):
        # S1 (07:48Z): a clock-flagged frame is consumed but lends no epoch; it is
        # recorded at the supplied one, and no receipt takes the clock epoch.
        self.open_ledger()
        k, _ = self.kernel_custody()
        clock = self.inbound(k, "b-p36s1-crossing-clock", now_ns=k.HB_ANCHOR_UNIX_NS + 10 ** 12)
        node = self.base / "node"
        out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root, hb_epoch="4096")
        self.assertEqual([r["disposition"] for r in out], ["ALLOW"], out)
        self.assertEqual(self.receipts_at(clock["heartbeat_reference"]["epoch"]), [])
        self.assertTrue(self.receipts_at(4096))
        for receipt in self.receipts_at(4096):
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)
        self.assertEqual(self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root,
                                               hb_epoch="4096"), [])

    def test_crossing_ingress_refuses_an_epoch_its_frame_contradicts(self):
        # B-P36l: an explicit hb_epoch that differs from the frame's is
        # HB_EPOCH_CONFLICT, nothing is written and the frame is not marked; an
        # invalid explicit epoch is HB_EPOCH_INVALID whatever the frame says.
        self.open_ledger()
        k, _ = self.kernel_custody()
        self.inbound(k, "b-p36l-frame", epoch=4096)
        node = self.base / "node"
        before = files_under(self.base)
        out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root, hb_epoch="32")
        self.assertEqual([r["failure_code"] for r in out], ["HB_EPOCH_CONFLICT"], out)
        for field in SIX_FIELDS:
            self.assertTrue(out[0][field], field)
        self.assertEqual(files_under(self.base), before)
        for epoch in ("+33", "abc", None):
            with self.subTest(epoch=epoch):
                with self.assertRaises(ValueError) as raised:
                    self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root, hb_epoch=epoch)
                self.assertEqual(raised.exception.refusal["failure_code"],
                                 "HB_EPOCH_NOT_SUPPLIED" if epoch is None else "HB_EPOCH_INVALID")
                self.assertEqual(files_under(self.base), before)
        taken = self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root, hb_epoch="4096")
        self.assertEqual([r["disposition"] for r in taken], ["ALLOW"], taken)

    def reframed(self, k, packet_id, reference_edit, service="sv-llm.org-control", payload=None):
        """A frame to SV-LLM whose heartbeat reference is edited, re-digested and published."""
        packet = k.build_packet(origin_org=PEER, origin_service="stegverse-org.org-control", destination_org="SV-LLM",
                                destination_service=service,
                                payload=payload or {"message_class": "ecosystem.monitor.request", "subject": packet_id},
                                standing=STANDING, packet_id=packet_id)
        frame = k.carrier_frame(packet, epoch=32)
        body = {key: value for key, value in frame.items() if key != "frame_sha256"}
        body["heartbeat_reference"] = reference_edit(dict(body["heartbeat_reference"]))
        frame = {**body, "frame_sha256": k.sha(body)}
        k._publish_frame(frame, root=self.mesh)
        return frame

    def test_a_verified_carried_frame_keeps_its_provenance_in_every_receipt(self):
        # B-P36m: a frame whose CARRIED claim verifies against this organization's
        # head produces receipts that read CARRIED (source, head_receipt_sha,
        # derived false); routes whose writers take no provenance quarantine it
        # (CARRIED_PROVENANCE_NOT_CARRIED_DOWNSTREAM) rather than strip it.
        self.open_ledger()
        k, custody = self.kernel_custody()
        head = self.org_genesis()["receipt_sha256"]
        carried = lambda ref: {**ref, "source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": head}
        frame = self.reframed(k, "b-p36m-carried", carried)
        self.no_clock()
        ledgers = {"repo_ledger_root": self.base / "repo-ledger", "org_ledger_root": self.base / "org-ledger"}
        rows = k.consume_addressed_frames(self.root, mesh_root=self.mesh, **ledgers)
        self.assertEqual([r["result"].get("status") for r in rows], ["CONSUMED"], rows)
        written = [d for d in [*self.documents(self.base / "repo-ledger"), *self.documents(self.base / "org-ledger")]
                   if frame["frame_sha256"] in json.dumps(d)]
        self.assertTrue(written)
        for receipt in {d["receipt_sha256"]: d for d in written}.values():
            self.assertEqual(receipt["hb_reference"]["source"], "ORGANIZATION_LEDGER_HEAD")
            self.assertEqual(receipt["hb_reference"]["head_receipt_sha"], head)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_a_carried_frame_is_quarantined_where_its_provenance_cannot_be_carried(self):
        self.open_ledger()
        k, _ = self.kernel_custody()
        head = self.org_genesis()["receipt_sha256"]
        carried = lambda ref: {**ref, "source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": head}
        self.reframed(k, "b-p36m-crossing", carried)
        ledgers = lambda: files_under(self.base / "repo-ledger") + files_under(self.base / "org-ledger")
        before = ledgers()
        out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=self.base / "node", root=self.root,
                                    hb_epoch="32")
        self.assertEqual([(r.get("quarantine"), r["failure_code"]) for r in out],
                         [("FRAME_REFUSED_QUARANTINED", "CARRIED_PROVENANCE_NOT_CARRIED_DOWNSTREAM")], out)
        self.assertEqual(ledgers(), before)
        capability = self.reframed(k, "b-p36m-capability", carried, service="sv-llm.intr-destination",
                      payload={"message_class": "ecosystem.communication", "communication_id": "b-p36m",
                               "subject": "purpose-neutral mesh diagnostic",
                               "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "m"}})
        rows = k.consume_addressed_frames(self.root, mesh_root=self.mesh, repo_ledger_root=self.base / "repo-ledger",
                                          org_ledger_root=self.base / "org-ledger")
        refused = [r for r in rows if r["result"].get("failure_code") == "CARRIED_PROVENANCE_NOT_CARRIED_DOWNSTREAM"]
        self.assertEqual(len(refused), 1, rows)
        # The capability frame produced no receipt (the earlier org-control frame, consumed
        # here without seen-state, is recorded with its provenance: see the B-P36m probe above).
        self.assertEqual([d for d in [*self.documents(self.base / "repo-ledger"), *self.documents(self.base / "org-ledger")]
                          if capability["frame_sha256"] in json.dumps(d)], [])

    def test_clock_frames_lend_no_epoch_and_unmarked_frames_are_refused(self):
        # 08:10Z: flagged-true and bare-sampled frames are CLOCK: consumed, lending
        # no epoch (an epoch-needing route refuses NOT_SUPPLIED); only an UNMARKED
        # frame (no flag, no sample) and an unverified CARRIED claim are refused.
        self.open_ledger()
        k, _ = self.kernel_custody()
        bare = self.reframed(k, "b-p36-bare-sampled",
                             lambda ref: {**{a: b for a, b in ref.items() if a != "derived_from_clock"},
                                          "sampled_unix_ns": k.HB_ANCHOR_UNIX_NS})
        node = self.base / "node"
        rows = k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node,
                                     repo_ledger_root=self.base / "repo-ledger", org_ledger_root=self.base / "org-ledger")
        self.assertEqual([r["result"]["failure_code"] for r in rows], ["HB_EPOCH_NOT_SUPPLIED"], rows)
        crossing_node = self.base / "crossing-node"
        out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=crossing_node, root=self.root, hb_epoch="4096")
        self.assertEqual([r["disposition"] for r in out], ["ALLOW"], out)
        for_frame = [d for d in [*self.documents(self.base / "repo-ledger"), *self.documents(self.base / "org-ledger")]
                     if "hb_reference" in d and bare["packet_id"] in json.dumps(d)]
        self.assertTrue(for_frame)
        for receipt in for_frame:
            self.assertEqual(receipt["hb_reference"]["epoch"], 4096)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)
            self.assertNotIn("sampled_unix_ns", receipt["hb_reference"])
        unmarked = self.reframed(k, "b-p36-unmarked",
                                 lambda ref: {a: b for a, b in ref.items() if a != "derived_from_clock"})
        out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=crossing_node, root=self.root, hb_epoch="4096")
        self.assertEqual([(r.get("quarantine"), r["failure_code"]) for r in out],
                         [("FRAME_REFUSED_QUARANTINED", "HB_EPOCH_PROVENANCE_UNMARKED")], out)
        self.assertEqual([d for d in self.documents(self.base / "repo-ledger") if unmarked["packet_id"] in json.dumps(d)], [])

    def bad_frames(self, k):
        """One frame of each B-P36o kind, re-digested where the defect is not the digest itself."""
        def build(packet_id, edit, redigest=True):
            packet = k.build_packet(origin_org=PEER, origin_service="stegverse-org.org-control", destination_org="SV-LLM",
                                    destination_service="sv-llm.org-control",
                                    payload={"message_class": "ecosystem.monitor.request", "subject": packet_id},
                                    standing=STANDING, packet_id=packet_id)
            body = {key: value for key, value in k.carrier_frame(packet, epoch=4096).items() if key != "frame_sha256"}
            body = edit(body)
            frame = {**body, "frame_sha256": k.sha(body) if redigest else "sha256:" + "0" * 64}
            k._publish_frame(frame, root=self.mesh)
            return frame
        reference = lambda body, **change: {**body, "heartbeat_reference": {**body["heartbeat_reference"], **change}}
        return {
            "HB_REFERENCE_INVALID": [build("b-p36o-generation", lambda b: reference(b, generation=4095)),
                                     build("b-p36o-id", lambda b: reference(b, heartbeat_id="HB:1"))],
            "FRAME_INTEGRITY_INVALID": [build("b-p36o-frame-sha", lambda b: b, redigest=False),
                                        build("b-p36o-packet-sha", lambda b: {**b, "packet_sha256": "sha256:" + "1" * 64})],
            "FRAME_INGEST_FAILED": [build("b-p36o-adapter", lambda b: {**b, "packet_base64": "!!not-base64!!"})],
        }

    def test_one_bad_frame_never_stops_a_consume_cycle(self):
        # B-P36o: any error ingesting one frame is a six-field refusal plus the
        # terminal quarantine marker; the valid frame is ledgered, a second cycle
        # offers none of the bad ones, and no clock is read.
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                bad = self.bad_frames(k)
                valid = self.inbound(k, "b-p36o-valid", epoch=4096)
                self.no_clock()
                node = self.base / "node"
                if route == "consume_and_respond":
                    run = lambda: k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node,
                                                        repo_ledger_root=self.base / "repo-ledger",
                                                        org_ledger_root=self.base / "org-ledger")
                    results = [row["result"] for row in run()]
                else:
                    run = lambda: self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root,
                                                        hb_epoch="4096")
                    results = run()
                refused = [r for r in results if r.get("quarantine") == "FRAME_REFUSED_QUARANTINED"]
                self.assertEqual(len(refused), sum(len(v) for v in bad.values()), results)
                for code, frames in bad.items():
                    hits = [r for r in refused if r["failure_code"] == code]
                    self.assertEqual(len(hits), len(frames), (code, refused))
                for r in refused:
                    for field in SIX_FIELDS:
                        self.assertTrue(r[field], field)
                adapter, = [r for r in refused if r["failure_code"] == "FRAME_INGEST_FAILED"]
                self.assertEqual(adapter["failed_predicate"], "Error")
                ledgered = json.dumps([*self.documents(self.base / "repo-ledger"), *self.documents(self.base / "org-ledger")])
                self.assertIn(valid["packet_id"], ledgered)
                for frames in bad.values():
                    for frame in frames:
                        self.assertNotIn(frame["packet_id"], ledgered)
                self.assertEqual(run(), [])

    def test_a_malformed_frames_file_never_starves_the_scan(self):
        # F-SCAN: a frames.d file that is not a frame object is quarantined by name
        # (FRAME_INGEST_FAILED) and the valid frame behind it is still ledgered.
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                frames = self.mesh / "frames.d"
                frames.mkdir(parents=True, exist_ok=True)
                (frames / "000-not-json.json").write_text("{not json")
                (frames / "001-a-list.json").write_text("[1,2,3]")
                valid = self.inbound(k, "f-scan-valid", epoch=4096)
                self.no_clock()
                node = self.base / "node"
                if route == "consume_and_respond":
                    run = lambda: [row["result"] for row in k.consume_and_respond(
                        self.root, mesh_root=self.mesh, node_state_root=node,
                        repo_ledger_root=self.base / "repo-ledger", org_ledger_root=self.base / "org-ledger")]
                else:
                    run = lambda: self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root,
                                                        hb_epoch="4096")
                results = run()
                bad = [r for r in results if r.get("quarantine") == "FRAME_REFUSED_QUARANTINED"]
                self.assertEqual(len(bad), 2, results)
                for r in bad:
                    self.assertEqual(r["failure_code"], "FRAME_INGEST_FAILED", r)
                    for field in SIX_FIELDS:
                        self.assertTrue(r[field], field)
                ledgered = json.dumps([*self.documents(self.base / "repo-ledger"),
                                       *self.documents(self.base / "org-ledger")])
                self.assertIn(valid["packet_id"], ledgered)
                self.assertEqual(run(), [])

    def consume_route(self, k, route, node):
        if route == "consume_and_respond":
            return lambda: [row["result"] for row in k.consume_and_respond(
                self.root, mesh_root=self.mesh, node_state_root=node,
                repo_ledger_root=self.base / "repo-ledger", org_ledger_root=self.base / "org-ledger")]
        return lambda: self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root, hb_epoch="4096")

    def test_each_corrupt_frames_file_is_quarantined_by_name(self):
        # B-P36p: a read error, non-UTF-8, non-JSON and an oversized file are each
        # quarantined by filename (six fields, 0 ledger files); the valid frame is ledgered.
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                frames = self.mesh / "frames.d"
                frames.mkdir(parents=True, exist_ok=True)
                (frames / "000-read-error.json").write_text("{}")
                (frames / "001-not-utf8.json").write_bytes(b'{"\xff\xfe": 1}')
                (frames / "002-not-json.json").write_text("{not json")
                (frames / "003-oversized.json").write_text('{"pad": "' + "x" * k.MAX_FRAME_FILE_BYTES + '"}')
                valid = self.inbound(k, "b-p36p-valid", epoch=4096)
                original = k.PosixStateStore.get

                def get(store, key):
                    if key.endswith("000-read-error.json"):
                        raise OSError("simulated read error")
                    return original(store, key)
                patcher = mock.patch.object(k.PosixStateStore, "get", get)
                patcher.start()
                self.addCleanup(patcher.stop)
                self.no_clock()
                run = self.consume_route(k, route, self.base / "node")
                results = run()
                bad = [r for r in results if r.get("quarantine") == "FRAME_REFUSED_QUARANTINED"]
                self.assertEqual(len(bad), 4, results)
                for r in bad:
                    self.assertEqual(r["failure_code"], "FRAME_INGEST_FAILED", r)
                    for field in SIX_FIELDS:
                        self.assertTrue(r[field], field)
                markers = [json.loads(Path(f).read_text()) for f in files_under(self.base / "node")]
                names = {m.get("frame_name") for m in markers if m.get("quarantine") == "FRAME_REFUSED_QUARANTINED"}
                self.assertEqual(len(names), 4, markers)
                ledgered = json.dumps([*self.documents(self.base / "repo-ledger"),
                                       *self.documents(self.base / "org-ledger")])
                self.assertIn(valid["packet_id"], ledgered)
                self.assertEqual(run(), [])
                patcher.stop()

    def test_a_wrong_typed_field_is_quarantined_on_either_side_of_a_valid_frame(self):
        # F-TYPE: the per-frame guard is total. A wrong-typed packet_base64 raises
        # AttributeError in recovery; it is FRAME_INGEST_FAILED with the class as
        # failed_predicate, quarantined, never re-offered, and the valid frame is ledgered.
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                bad = [self.reframed(k, name, lambda ref: ref) for name in ("000-f-type", "zzz-f-type")]
                for frame in bad:  # re-publish each with packet_base64 of the wrong type
                    body = {key: value for key, value in frame.items() if key != "frame_sha256"}
                    body["packet_base64"] = 123
                    k._publish_frame({**body, "frame_sha256": k.sha(body)}, root=self.mesh)
                valid = self.inbound(k, "f-type-valid", epoch=4096)
                self.no_clock()
                run = self.consume_route(k, route, self.base / "node")
                results = run()
                typed = [r for r in results if r.get("failed_predicate") == "AttributeError"]
                self.assertEqual(len(typed), 2, results)
                for r in typed:
                    self.assertEqual((r["quarantine"], r["failure_code"]), ("FRAME_REFUSED_QUARANTINED", "FRAME_INGEST_FAILED"))
                self.assertIn(valid["packet_id"], json.dumps([*self.documents(self.base / "repo-ledger")]))
                self.assertEqual([r for r in run() if r.get("failed_predicate") == "AttributeError"], [])

    def test_an_io_failure_in_our_own_ledger_leaves_the_frame_pending(self):
        # F-TYPE IO addendum: an OSError writing this organization's ledger is
        # six-field FRAME_DISPATCH_IO_FAILED, writes no marker, and the next cycle
        # consumes the frame exactly once.
        self.open_ledger()
        k, _ = self.kernel_custody()
        valid = self.inbound(k, "b-p36-io-valid", epoch=4096)
        original = k.crossing_custody
        failures = {"left": 1}

        def custody_with_one_failure(*args, **kwargs):
            custody = original(*args, **kwargs)
            store = custody["organization_store"]
            append = store.append_transaction

            def flaky(*a, **kw):
                if failures["left"]:
                    failures["left"] -= 1
                    raise OSError("simulated ledger write failure")
                return append(*a, **kw)
            store.append_transaction = flaky
            return custody
        node = self.base / "node"
        ledgers = {"repo_ledger_root": self.base / "repo-ledger", "org_ledger_root": self.base / "org-ledger"}
        with mock.patch.object(k, "crossing_custody", custody_with_one_failure):
            first = k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node, **ledgers)
        row, = first
        self.assertEqual(row["result"]["failure_code"], "FRAME_DISPATCH_IO_FAILED")
        for field in SIX_FIELDS:
            self.assertTrue(row["result"][field], field)
        self.assertIsNone(row["seen_marker"])
        self.assertEqual(files_under(node / "federation") if (node / "federation").exists() else [], [])
        second = k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node, **ledgers)
        self.assertEqual([r["result"].get("status") for r in second], ["CONSUMED"], second)
        consumed = {d["receipt_sha256"]: d for d in self.documents(self.base / "repo-ledger")
                    if d.get("transition_class") == "ORGANIZATION_FEDERATION_CROSSING_CONSUMED"
                    and valid["frame_sha256"] in json.dumps(d)}
        self.assertEqual(len(consumed), 1, consumed)
        organization = {d["receipt_sha256"]: d for d in self.documents(self.base / "org-ledger")
                        if d.get("source_transition_sha256") in consumed}
        self.assertEqual(len(organization), 1, organization)
        self.assertEqual(k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node, **ledgers), [])

    def test_a_malformed_clock_frame_is_quarantined_not_raised(self):
        # F-S1a: a clock-flagged frame with a malformed epoch is a six-field
        # refusal and quarantined on every consume route.
        for epoch in ("abc", None, 5):
            for route in ("consume_and_respond", "crossing.ingress"):
                with self.subTest(epoch=epoch, route=route):
                    self.setUp()
                    self.open_ledger()
                    k, _ = self.kernel_custody()
                    def edit(ref):
                        ref = {**ref, "derived_from_clock": True, "sampled_unix_ns": k.HB_ANCHOR_UNIX_NS}
                        if epoch is None:
                            ref.pop("epoch")
                        else:
                            ref["epoch"] = epoch
                        return ref
                    self.reframed(k, "f-s1a-" + str(epoch), edit)
                    node = self.base / "node"
                    if route == "consume_and_respond":
                        results = [row["result"] for row in k.consume_and_respond(
                            self.root, mesh_root=self.mesh, node_state_root=node,
                            repo_ledger_root=self.base / "repo-ledger", org_ledger_root=self.base / "org-ledger")]
                    else:
                        results = self.crossing.ingress(mesh_root=self.mesh, node_state_root=node, root=self.root,
                                                        hb_epoch="4096")
                    self.assertEqual([r.get("quarantine") for r in results], ["FRAME_REFUSED_QUARANTINED"], results)
                    self.assertIn(results[0]["failure_code"], ("HB_EPOCH_INVALID", "HB_EPOCH_NOT_SUPPLIED"))

    def test_a_forged_carried_frame_is_refused_on_every_route(self):
        # B-P36k: a self-asserted CARRIED claim is verified against this
        # organization's ledger head; a forged sha is refused, never stripped
        # to SUPPLIED, and nothing but the quarantine marker is written.
        self.open_ledger()
        k, custody = self.kernel_custody()
        ledgers = {"repo_ledger_root": self.base / "repo-ledger", "org_ledger_root": self.base / "org-ledger"}
        frame = self.forged(k, "b-p36k-forged")
        self.no_clock()
        ledger_files = lambda: files_under(self.base / "repo-ledger") + files_under(self.base / "org-ledger")
        before = ledger_files()
        with self.assertRaises(k.SuppliedEpochRefused) as raised:
            k.ingest_frame(self.root, frame, **ledgers)
        self.assertEqual(raised.exception.refusal["failure_code"], "CARRIED_PROVENANCE_UNVERIFIED")
        self.assertEqual(ledger_files(), before)
        rows = k.consume_addressed_frames(self.root, mesh_root=self.mesh, **ledgers)
        self.assertEqual([r["result"]["failure_code"] for r in rows], ["CARRIED_PROVENANCE_UNVERIFIED"])
        self.assertEqual(ledger_files(), before)
        for name, run in (("consume_and_respond", lambda node: k.consume_and_respond(
                              self.root, mesh_root=self.mesh, node_state_root=node, **ledgers)),
                          ("crossing.ingress", lambda node: self.crossing.ingress(
                              mesh_root=self.mesh, node_state_root=node, root=self.root, hb_epoch="4096"))):
            with self.subTest(route=name):
                node = self.base / ("node-" + name)
                out = run(node)
                results = [row.get("result", row) for row in out]
                self.assertEqual([(r.get("quarantine"), r["failure_code"]) for r in results],
                                 [("FRAME_REFUSED_QUARANTINED", "CARRIED_PROVENANCE_UNVERIFIED")], out)
                self.assertEqual(ledger_files(), before)
                written = files_under(node)
                self.assertEqual(len(written), 1, written)
                self.assertEqual(json.loads(Path(written[0]).read_text())["quarantine"], "FRAME_REFUSED_QUARANTINED")

    def test_the_shared_rule_is_the_pinned_final_text(self):
        # StegVerse-Labs/.github#3282 FINAL: sha256(inspect.getsource(supplied_epoch_failure)).
        import hashlib
        import inspect
        k = self.crossing.kernel
        self.assertEqual(k.SHARED_VALIDATOR_SHA256, "ad8ff52936d5bcd9a2ad6caceb2d9a637a099518989b34bbb3370301c7a4cce2")
        self.assertEqual(hashlib.sha256(inspect.getsource(k.supplied_epoch_failure).encode()).hexdigest(),
                         k.SHARED_VALIDATOR_SHA256)
        self.assertFalse(hasattr(k, "reference_provenance_failure"))

    def test_the_shared_rule_marks_provenance_in_its_final_order(self):
        k = self.crossing.kernel
        supplied = k.hb_reference(epoch=4096)
        unmarked = {k_: v for k_, v in supplied.items() if k_ != "derived_from_clock"}
        forged = {**unmarked, "source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": "sha256:" + "f" * 64}
        for name, reference, code in (("no flag + sampled", {**unmarked, "sampled_unix_ns": 1}, "HB_EPOCH_INVALID"),
                                      ("fabricated head, no flag", forged, "HB_EPOCH_PROVENANCE_UNMARKED"),
                                      ("false + sampled", {**supplied, "sampled_unix_ns": 1}, "HB_EPOCH_INVALID"),
                                      ("true", {**supplied, "derived_from_clock": True}, "HB_EPOCH_INVALID"),
                                      ("not an object", [], "HB_EPOCH_INVALID"),
                                      ("unmarked", unmarked, "HB_EPOCH_PROVENANCE_UNMARKED")):
            with self.subTest(reference=name):
                self.assertEqual(k.supplied_epoch_failure(4096, reference)[0], code)
        self.assertIsNone(k.supplied_epoch_failure(4096, {**supplied, "source": "X"}))
        self.assertIsNone(k.supplied_epoch_failure(4096, supplied))
        with self.assertRaises(k.SuppliedEpochRefused) as raised:
            k.carried_epoch(unmarked, retry_entrypoint="test")
        self.assertEqual(raised.exception.refusal["failure_code"], "HB_EPOCH_PROVENANCE_UNMARKED")
        for field in SIX_FIELDS:
            self.assertTrue(raised.exception.refusal[field], field)

    def test_the_aggregate_refuses_a_clock_or_unmarked_source_receipt(self):
        # B-P36h (O-1): a CLOCK-provenance repository receipt is never consumed.
        k = self.agg.kernel
        clock = {**k.hb_reference(epoch=4096), "derived_from_clock": True, "sampled_unix_ns": 1}
        unmarked = {k_: v for k_, v in k.hb_reference(epoch=4096).items() if k_ != "derived_from_clock"}
        self.no_clock()
        for name, reference in (("clock", clock), ("unmarked", unmarked)):
            with self.subTest(source=name):
                body = {"schema": "stegverse.repo-transition-receipt/v1", "repository": "SV-LLM/.github",
                        "transition_id": "b-p36h-" + name, "hb_reference": reference}
                source = {**body, "receipt_sha256": self.agg.sha(body)}
                before = files_under(self.base)
                with self.assertRaises(k.SuppliedEpochRefused) as raised:
                    self.agg.append(source, "REPO_STATE_PROPAGATION", self.agg.GENESIS, "sha256:" + "2" * 64,
                                    {}, "NONE", hb_epoch=4096)
                refusal = raised.exception.refusal
                self.assertEqual(refusal["failure_code"], "SOURCE_RECEIPT_IS_CLOCK_PROVENANCE")
                self.assertIn("CARRIED:LEGACY_CLOCK_RECEIPT", refusal["required_evidence_or_repair"])
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual(files_under(self.base), before)

    def test_an_invented_carried_provenance_is_refused(self):
        # 07:08Z: a caller-supplied CARRIED provenance must name the current
        # ledger head, which must be supplied; an invented sha writes nothing.
        self.open_ledger()
        self.no_clock()
        k, custody = self.kernel_custody()
        head = self.org_genesis()["receipt_sha256"]
        for provenance in ({"source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": "sha256:" + "9" * 64},
                           {"source": "ORGANIZATION_LEDGER_HEAD"},
                           {"source": "SOMEWHERE_ELSE", "head_receipt_sha": head}):
            with self.subTest(provenance=provenance):
                before = files_under(self.base)
                for name, call in (
                        ("publish_packet", lambda: k.publish_packet(self.packet("b-p36h-invented"), root=self.mesh,
                                                                     custody=custody, epoch=32,
                                                                     epoch_provenance=provenance)),
                        ("emit.append", lambda: self.egress.repository_ledger.append(
                            "B:invented", "B", "sha256:" + "0" * 64, "sha256:" + "1" * 64, {}, "NONE", hb_epoch=32,
                            hb_provenance=provenance, provenance_store=custody["organization_store"])),
                        ("aggregate.append", lambda: self.agg.append(
                            self.repo_receipt_unwritten(), "REPO_STATE_PROPAGATION", self.agg.FROM_HEAD,
                            "sha256:" + "2" * 64, {}, "NONE", hb_epoch=32, hb_provenance=provenance))):
                    with self.subTest(writer=name):
                        # Each module loads its own kernel, so match the refusal, not the class.
                        with self.assertRaises(ValueError) as raised:
                            call()
                        refusal = raised.exception.refusal
                        self.assertEqual(refusal["failure_code"], "CARRIED_PROVENANCE_UNVERIFIED")
                        for field in SIX_FIELDS:
                            self.assertTrue(refusal[field], field)
                        self.assertEqual(files_under(self.base), before)

    def test_an_answer_is_published_at_the_answered_frame_epoch(self):
        # B-P36g / 07:10Z: the inbound frame's validated epoch is SUPPLIED for the
        # answer; a caller's now_ns never reaches the kernel's clock default.
        self.open_ledger()
        k, _ = self.kernel_custody()
        packet = k.build_packet(origin_org=PEER, origin_service="stegverse-org.org-control", destination_org="SV-LLM",
                                destination_service="sv-llm.org-control",
                                payload={"message_class": "ecosystem.monitor.request", "subject": "b-p36g"},
                                standing=STANDING, packet_id="b-p36g-monitor")
        k._publish_frame(k.carrier_frame(packet, epoch=4096), root=self.mesh)
        self.no_clock()
        out = k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=self.base / "node",
                                    repo_ledger_root=self.base / "repo-ledger", org_ledger_root=self.base / "org-ledger",
                                    now_ns=k.HB_ANCHOR_UNIX_NS + 10 ** 12)
        answer, = [row["response_publication"]["frame"] for row in out if row["response_publication"]]
        self.assertEqual(answer["heartbeat_reference"]["epoch"], 4096)
        self.assertIs(answer["heartbeat_reference"]["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", answer["heartbeat_reference"])
        for receipt in self.receipts_at(4096):
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_marker_vocabulary(self):
        # 07:16Z: SUPPLIED is derived_from_clock false with no sampled_unix_ns,
        # and a clock value is always marked (derived_from_clock true and sampled_unix_ns).
        k = self.crossing.kernel
        self.no_clock()
        supplied = k.hb_reference(epoch=4096)
        self.assertIs(supplied["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", supplied)
        frame = k.carrier_frame(self.packet("b-p36g-marker"), epoch=4096)
        self.assertIs(frame["heartbeat_reference"]["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", frame["heartbeat_reference"])
        sampled = k.hb_reference(k.HB_ANCHOR_UNIX_NS + 10 ** 12)
        self.assertIs(sampled["derived_from_clock"], True)
        self.assertIn("sampled_unix_ns", sampled)

    def test_every_route_at_a_fixed_clock_writes_only_supplied_epochs(self):
        # B-P36g row 6: with the clock fixed, every receipt and every frame the
        # writer routes produce is SUPPLIED (false, no sample) at the epoch given.
        class FixedClock:
            @staticmethod
            def now(*args, **kwargs):
                import datetime as real
                return real.datetime(2030, 1, 1, tzinfo=real.timezone.utc)
        kernels = {id(k): k for k in (self.crossing.kernel, self.agg.kernel, self.egress.kernel,
                                      self.egress.repository_ledger.kernel, self.egress.organization_ledger.kernel)}
        for k in kernels.values():
            patcher = mock.patch.object(k, "datetime", FixedClock)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.crossing.open_organization_ledger(root=self.root, hb_epoch="4096")
        self.crossing.egress({"manifest_id": "b-p36g-fixed", "destination": {"organization": PEER},
                              "payload": {"probe": 1}}, standing=STANDING, mesh_root=self.mesh, root=self.root,
                             hb_epoch="4096")
        self.egress.emit(PEER, {"message_class": "ecosystem.communication", "communication_id": "b-p36g-fixed",
                                "subject": "purpose-neutral mesh diagnostic",
                                "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "b"}},
                         standing=STANDING, capability="intr-destination", mesh_root=self.mesh, hb_epoch=4096)
        k, custody = self.kernel_custody()
        k.publish_packet(self.packet("b-p36g-fixed-publish"), root=self.mesh, custody=custody, epoch=4096)
        references = [d["hb_reference"] for d in [*self.documents(self.base / "repo-ledger"),
                                                   *self.documents(self.base / "org-ledger")] if "hb_reference" in d]
        references += [d["heartbeat_reference"] for d in self.documents(self.mesh) if "heartbeat_reference" in d]
        self.assertTrue(references)
        for reference in references:
            self.assertEqual(reference["epoch"], 4096)
            self.assertIs(reference["derived_from_clock"], False)
            self.assertNotIn("sampled_unix_ns", reference)

    def ingest_results(self, k, route, node):
        return self.consume_route(k, route, node)()

    def test_a_frame_with_no_epoch_is_not_supplied(self):
        # 48b3bdc (2): a reference with no epoch (and no clock flag) is
        # HB_EPOCH_NOT_SUPPLIED, quarantined, on every consume route.
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                self.reframed(k, "v-2-no-epoch", lambda ref: {a: b for a, b in ref.items() if a != "epoch"})
                results = self.ingest_results(k, route, self.base / "node")
                self.assertEqual([(r.get("quarantine"), r["failure_code"]) for r in results],
                                 [("FRAME_REFUSED_QUARANTINED", "HB_EPOCH_NOT_SUPPLIED")], results)
                for field in SIX_FIELDS:
                    self.assertTrue(results[0][field], field)

    def test_a_carried_claim_on_a_clock_frame_is_unverified(self):
        # 48b3bdc (3): CARRIED fields on a clock-flagged reference never verify;
        # the frame is CARRIED_PROVENANCE_UNVERIFIED, not consumed as CLOCK.
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                head = self.org_genesis()["receipt_sha256"]
                self.reframed(k, "v-3-carried-clock", lambda ref: {
                    **ref, "derived_from_clock": True, "sampled_unix_ns": k.HB_ANCHOR_UNIX_NS,
                    "source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": head})
                ledgers = lambda: files_under(self.base / "repo-ledger") + files_under(self.base / "org-ledger")
                before = ledgers()
                results = self.ingest_results(k, route, self.base / "node")
                self.assertEqual([(r.get("quarantine"), r["failure_code"]) for r in results],
                                 [("FRAME_REFUSED_QUARANTINED", "CARRIED_PROVENANCE_UNVERIFIED")], results)
                self.assertEqual(ledgers(), before)

    def test_a_tampered_head_receipt_never_verifies(self):
        # 48b3bdc (6): the head receipt's digest is recomputed. A head whose epoch
        # was edited to 7777 in place (receipt_sha256 kept) is refused by both writers.
        self.open_ledger()
        k, custody = self.kernel_custody()
        genesis = self.org_genesis()
        path, = [p for p in files_under(self.base / "org-ledger")
                 if p.endswith(".json") and json.loads(Path(p).read_text()) == genesis]
        tampered = {**genesis, "hb_reference": {**genesis["hb_reference"], "epoch": 7777}}
        Path(path).write_text(json.dumps(tampered))
        provenance = {"source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": genesis["receipt_sha256"]}
        before = files_under(self.base)
        for name, call in (
                ("emit.append", lambda: self.egress.repository_ledger.append(
                    "V:tampered", "V", "sha256:" + "0" * 64, "sha256:" + "1" * 64, {}, "NONE", hb_epoch=7777,
                    hb_provenance=provenance, provenance_store=custody["organization_store"])),
                ("aggregate.append", lambda: self.agg.append(
                    self.repo_receipt_unwritten(), "REPO_STATE_PROPAGATION", self.agg.FROM_HEAD,
                    "sha256:" + "2" * 64, {}, "NONE", hb_epoch=7777, hb_provenance=provenance))):
            with self.subTest(writer=name):
                with self.assertRaises(ValueError) as raised:
                    call()
                refusal = raised.exception.refusal
                self.assertEqual(refusal["failure_code"], "CARRIED_PROVENANCE_UNVERIFIED")
                self.assertIn("recompute", refusal["detail"])
                for field in SIX_FIELDS:
                    self.assertTrue(refusal[field], field)
                self.assertEqual(files_under(self.base), before)

    def test_a_wrong_typed_channel_or_destination_is_quarantined(self):
        # 48b3bdc (7) / F-TYPE: a channel that is not the payload's derived channel
        # is FRAME_INTEGRITY_INVALID; a non-string destination_org is quarantined
        # by the scan guard. The valid frame behind them is ledgered.
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                channel = self.reframed(k, "v-7-channel", lambda ref: ref)
                frames = self.mesh / "frames.d"
                for path in files_under(frames):  # only the wrong-typed re-publication stays
                    if json.loads(Path(path).read_text()) == channel:
                        Path(path).unlink()
                body = {key: value for key, value in channel.items() if key != "frame_sha256"}
                body["channel"] = 7
                k._publish_frame({**body, "frame_sha256": k.sha(body)}, root=self.mesh)
                (frames / "000-destination.json").write_text(json.dumps({**body, "destination_org": ["SV-LLM"]}))
                valid = self.inbound(k, "v-7-valid", epoch=4096)
                self.no_clock()
                run = self.consume_route(k, route, self.base / "node")
                results = run()
                bad = [r for r in results if r.get("quarantine") == "FRAME_REFUSED_QUARANTINED"]
                self.assertEqual(len(bad), 2, results)
                self.assertIn("FRAME_INTEGRITY_INVALID", [r["failure_code"] for r in bad])
                for r in bad:
                    for field in SIX_FIELDS:
                        self.assertTrue(r[field], field)
                self.assertIn(valid["packet_id"], json.dumps([*self.documents(self.base / "repo-ledger")]))
                self.assertEqual(run(), [])

    def ledger_classes(self):
        """Receipt counts per transition class on both ledgers (each receipt once)."""
        counts = {}
        for root in ("repo-ledger", "org-ledger"):
            seen = {d["receipt_sha256"]: d for d in self.documents(self.base / root) if "receipt_sha256" in d}
            for d in seen.values():
                name = root + ":" + str(d.get("transition_class") or d.get("organization_transition_class")
                                        or (d.get("boundary_evidence") or {}).get("operation"))
                counts[name] = counts.get(name, 0) + 1
        return counts

    def inject(self, fault, at):
        """Make the at-th in-process ledger append fail with `fault`; returns the call log."""
        _, custody = self.kernel_custody()
        found = [type(custody["organization_store"]), type(custody["repository_store"]),
                 self.crossing.organization_ledger.open_store.__globals__["PosixLedgerStore"],
                 *(getattr(m, "PosixLedgerStore") for m in list(sys.modules.values())
                   if isinstance(getattr(m, "PosixLedgerStore", None), type))]
        classes = {id(cls): cls for cls in found}
        log = {"calls": 0, "patchers": []}
        for cls in classes.values():
            original = cls.append_transaction

            def append(store, *args, _original=original, **kwargs):
                log["calls"] += 1
                if log["calls"] - 1 == at:
                    if fault == "lost_comparison":
                        raise RuntimeError("ledger_append_lost_comparison")
                    if fault == "collision":
                        raise ValueError("ledger_receipt_collision")
                    if fault == "exhausted":
                        log["exhaust"] = True
                if log.get("exhaust"):
                    if log["calls"] - 1 >= at + 127:  # the writers retry 128 times
                        log["exhaust"] = False
                    return False
                return _original(store, *args, **kwargs)
            patcher = mock.patch.object(cls, "append_transaction", append)
            patcher.start()
            self.addCleanup(patcher.stop)
            log["patchers"].append(patcher)
        return log

    @staticmethod
    def heal(log):
        for patcher in log["patchers"]:
            patcher.stop()

    def test_a_writer_fault_on_any_append_leaves_the_frame_pending(self):
        # F-TRANSIENT-RT: a lost comparison, a collision or exhausted contention on
        # any in-process append of a consume cycle is non-terminal
        # FRAME_DISPATCH_IO_FAILED with no seen-marker; the next cycle consumes the
        # frame exactly once (the same receipts a clean cycle writes), the one after none.
        for route in ("consume_and_respond", "crossing.ingress"):
            self.setUp()
            self.open_ledger()
            k, _ = self.kernel_custody()
            self.inbound(k, "f-transient-clean", epoch=4096)
            genesis = self.ledger_classes()
            log = self.inject(None, -1)
            self.assertTrue(self.ingest_results(k, route, self.base / "node"))
            appends = log["calls"]
            clean = {name: n - genesis.get(name, 0) for name, n in self.ledger_classes().items()}
            self.heal(log)
            self.assertGreater(appends, 0)
            for fault in ("lost_comparison", "collision", "exhausted"):
                for at in range(appends):
                    with self.subTest(route=route, fault=fault, append=at):
                        self.setUp()
                        self.open_ledger()
                        k, _ = self.kernel_custody()
                        self.inbound(k, "f-transient-clean", epoch=4096)
                        node = self.base / "node"
                        faulted = self.inject(fault, at)
                        first = self.ingest_results(k, route, node)
                        self.assertEqual([(r["failure_code"], r.get("terminal")) for r in first],
                                         [("FRAME_DISPATCH_IO_FAILED", False)], first)
                        for field in SIX_FIELDS:
                            self.assertTrue(first[0][field], field)
                        self.assertEqual(files_under(node / "federation") if (node / "federation").exists() else [], [])
                        self.heal(faulted)
                        second = self.ingest_results(k, route, node)
                        self.assertTrue(second and all(r.get("failure_code") is None for r in second), second)
                        after = {name: n - genesis.get(name, 0) for name, n in self.ledger_classes().items()}
                        self.assertEqual({n: c for n, c in after.items() if c}, {n: c for n, c in clean.items() if c})
                        self.assertEqual(self.ingest_results(k, route, node), [])

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
        # V-P11 N1: the text "4096" used to commit a DENY; the text and the int both emit.
        for count, epoch in enumerate(("4096", 4096), start=1):
            with self.subTest(epoch=epoch):
                payload = {"message_class": "ecosystem.communication",
                           "communication_id": "b-p36b-emit-4096-" + type(epoch).__name__,
                           "subject": "purpose-neutral mesh diagnostic",
                           "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "b-p36b"}}
                emitted = self.egress.emit(PEER, payload, standing=STANDING, capability="intr-destination",
                                           mesh_root=self.mesh, hb_epoch=epoch)
                self.assertEqual(emitted["disposition"], "ALLOW", emitted.get("detail"))
                frames = [json.loads(Path(p).read_text()) for p in files_under(self.mesh) if p.endswith(".json")]
                references = [f["heartbeat_reference"] for f in frames
                              if isinstance(f, dict) and "heartbeat_reference" in f]
                self.assertEqual(len(references), count)
                for reference in references:
                    self.assertEqual(reference["epoch"], 4096)
                    self.assertIs(reference["derived_from_clock"], False)
                receipts = self.receipts_at(4096)
                self.assertEqual(len(receipts), 2 * count, receipts)
                for receipt in receipts:
                    self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)


if __name__ == "__main__":
    unittest.main()
