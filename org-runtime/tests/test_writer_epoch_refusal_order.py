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
RELEASE_CLI = "resident-runtime/submit_org_transition_to_master_records.py"


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
                [sys.executable, "-B", str(self.root / RELEASE_CLI),
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
        # derived false); the capability routes carry it too (see below).
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
                   if frame["frame_sha256"] in json.dumps(d) and "receipt_sha256" in d]
        self.assertTrue(written)
        for receipt in {d["receipt_sha256"]: d for d in written}.values():
            self.assertEqual(receipt["hb_reference"]["source"], "ORGANIZATION_LEDGER_HEAD")
            self.assertEqual(receipt["hb_reference"]["head_receipt_sha"], head)
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def carried_receipts(self, frame):
        """Every ledger receipt written for `frame`, by digest: its repository receipts and the
        organization receipts consuming them."""
        repository = {d["receipt_sha256"]: d for d in self.documents(self.base / "repo-ledger")
                      if "receipt_sha256" in d and (frame["frame_sha256"] in json.dumps(d)
                                                    or frame["packet_id"] in json.dumps(d))}
        organization = {d["receipt_sha256"]: d for d in self.documents(self.base / "org-ledger")
                        if d.get("source_transition_sha256") in repository}
        return {**repository, **organization}

    def test_a_verified_carried_crossing_carries_its_provenance_through_every_writer(self):
        # B-P36m ruling (lead, 09:00Z): the current-head check is the admission,
        # made once at ingest and recorded; each downstream writer of the crossing
        # verifies chain membership, digest, a SUPPLIED equal epoch and the
        # admission's head. A capability crossing on crossing.ingress writes 2+
        # organization receipts, every one CARRIED, none UNVERIFIED.
        diagnostic = {"message_class": "ecosystem.communication", "communication_id": "b-p36m",
                      "subject": "purpose-neutral mesh diagnostic",
                      "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "m"}}
        for route in ("crossing.ingress", "consume_addressed_frames"):
            with self.subTest(route=route):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                head = self.org_genesis()["receipt_sha256"]
                carried = lambda ref: {**ref, "source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": head}
                frame = self.reframed(k, "b-p36m-capability-" + route, carried, service="sv-llm.intr-destination",
                                      payload=diagnostic)
                self.no_clock()
                if route == "crossing.ingress":
                    out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=self.base / "node",
                                                root=self.root, hb_epoch="32")
                    self.assertEqual([r["disposition"] for r in out], ["ALLOW"], out)
                else:
                    out = k.consume_addressed_frames(self.root, mesh_root=self.mesh,
                                                     repo_ledger_root=self.base / "repo-ledger",
                                                     org_ledger_root=self.base / "org-ledger")
                    self.assertEqual([r["result"].get("status") for r in out], ["CONSUMED"], out)
                self.assertNotIn("CARRIED_PROVENANCE_UNVERIFIED", json.dumps(out))
                receipts = self.carried_receipts(frame)
                organization = [r for r in receipts.values()
                                if r.get("schema") == "stegverse.organization-transition-receipt/v1"]
                self.assertGreaterEqual(len(organization), 2 if route == "crossing.ingress" else 1, receipts)
                for receipt in receipts.values():
                    self.assertEqual(receipt["hb_reference"]["source"], "ORGANIZATION_LEDGER_HEAD")
                    self.assertEqual(receipt["hb_reference"]["head_receipt_sha"], head)
                    self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)
                    self.assertNotIn("admission_key", receipt["hb_reference"])

    def test_a_forged_head_is_unverified_at_admission_and_downstream(self):
        # The negative of the ruling: a sha that is not the head at admission is
        # refused there; a downstream writer handed a sha other than its
        # admission's, one outside the chain, or no admission record refuses.
        self.open_ledger()
        k, custody = self.kernel_custody()
        head = self.org_genesis()["receipt_sha256"]
        forged = "sha256:" + "e" * 64
        frame = self.reframed(k, "b-p36m-forged-capability",
                              lambda ref: {**ref, "source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": forged},
                              service="sv-llm.intr-destination")
        before = files_under(self.base / "repo-ledger") + files_under(self.base / "org-ledger")
        out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=self.base / "node", root=self.root,
                                    hb_epoch="32")
        self.assertEqual([(r.get("quarantine"), r["failure_code"]) for r in out],
                         [("FRAME_REFUSED_QUARANTINED", "CARRIED_PROVENANCE_UNVERIFIED")], out)
        self.assertEqual(files_under(self.base / "repo-ledger") + files_under(self.base / "org-ledger"), before)
        admitted = k.admit_carried(32, {"source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha": head},
                                   custody=custody, crossing_id="b-p36m-negative", retry_entrypoint="test")
        for name, provenance in (("another sha", {**admitted, "head_receipt_sha": forged}),
                                 ("no admission", {**admitted, "admission_key": k.admission_key("never-admitted")}),
                                 ("outside the store", {**admitted, "admission_key": "receipts/x.json"})):
            with self.subTest(provenance=name):
                written = files_under(self.base)
                with self.assertRaises(ValueError) as raised:
                    self.egress.repository_ledger.append(
                        "B:forged-" + name, "B", "sha256:" + "0" * 64, "sha256:" + "1" * 64, {}, "NONE", hb_epoch=32,
                        hb_provenance=provenance, provenance_store=custody["organization_store"])
                self.assertEqual(raised.exception.refusal["failure_code"], "CARRIED_PROVENANCE_UNVERIFIED")
                for field in SIX_FIELDS:
                    self.assertTrue(raised.exception.refusal[field], field)
                self.assertEqual(files_under(self.base), written)

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

    def ledger_state(self):
        """What a run leaves durable: receipts per class, response frames, markers, and a sound chain."""
        for root in ("repo-ledger", "org-ledger"):
            head_path = self.base / root / "HEAD.json"
            receipts = {Path(p).name: json.loads(Path(p).read_text())
                        for p in files_under(self.base / root / "receipts")} if (self.base / root / "receipts").exists() else {}
            if not receipts:
                continue
            self.assertTrue(head_path.is_file(), root + ": receipts without HEAD")
            cursor, reachable = json.loads(head_path.read_text())["receipt_sha256"], set()
            while cursor:
                receipt = receipts.get(cursor.split(":", 1)[1] + ".json")
                self.assertIsNotNone(receipt, root + ": chain names a missing receipt")
                body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
                self.assertEqual(self.crossing.kernel.sha(body), cursor, root + ": receipt does not recompute")
                reachable.add(cursor.split(":", 1)[1] + ".json")
                cursor = receipt.get("previous_receipt_sha256")
            self.assertEqual(set(receipts), reachable, root + ": orphan receipts")
            self.assertFalse((self.base / root / "PENDING_APPEND.json").exists(), root + ": an unfinished append")
        frames = [d for d in self.documents(self.mesh) if "frame_sha256" in d]
        markers = [d for d in self.documents(self.base / "node") if d.get("frame_name")] if (self.base / "node").exists() else []
        return {"receipts": self.ledger_classes(), "frames": sorted(f["packet_id"] for f in frames),
                "markers": sorted((m["frame_name"], m.get("status"), m.get("failure_code")) for m in markers)}

    def sweep(self, prepare, run, settle=3):
        """B-P36q: an OSError before and after every durable write of `run`; the next runs finish it once.

        `prepare()` builds the state the path starts from (unfaulted); `run()`
        is the multi-step path. Each faulted run must raise or return a
        non-terminal six-field record, and up to `settle` further runs must
        leave exactly the state one clean run leaves, with a sound chain.
        """
        import fault_injection
        fault_injection.install()
        self.addCleanup(fault_injection.uninstall)
        hook = fault_injection.directory()
        self.addCleanup(shutil.rmtree, hook, True)
        counter = Path(tempfile.mkdtemp(prefix="stegverse-fault-count-")) / "count"
        self.addCleanup(shutil.rmtree, counter.parent, True)

        def environment(at, mode):
            os.environ.update(STEGVERSE_FAULT_ROOT=str(self.base.resolve()), STEGVERSE_FAULT_COUNTER=str(counter),
                              PYTHONPATH=os.pathsep.join(filter(None, [str(hook), os.environ.get("PYTHONPATH")])),
                              STEGVERSE_FAULT_MODE=mode)
            os.environ.pop("STEGVERSE_FAULT_AT", None)
            if at is not None:
                os.environ["STEGVERSE_FAULT_AT"] = str(at)
            counter.unlink(missing_ok=True)

        self.setUp()
        environment(None, "before")
        prepare()
        counter.unlink(missing_ok=True)
        run()
        writes = fault_injection.census(counter)
        clean = self.ledger_state()
        self.assertGreater(writes, 0)
        outcomes = []
        for mode in ("before", "after"):
            for at in range(writes):
                with self.subTest(mode=mode, write=at):
                    self.setUp()
                    environment(None, mode)
                    prepare()
                    environment(at, mode)
                    try:
                        faulted = run()
                    except (Exception, SystemExit) as exc:
                        faulted = exc
                    outcomes.append((mode, at, faulted))
                    self.assertResumable(faulted)
                    environment(None, mode)
                    for _ in range(settle):
                        try:
                            run()
                        except (Exception, SystemExit) as exc:
                            self.fail("the run after a fault at write %d (%s) did not complete: %r" % (at, mode, exc))
                    self.assertEqual(self.ledger_state(), clean)
        return outcomes

    def assertResumable(self, faulted):
        """A faulted run reports a six-field, non-terminal record, or completed anyway."""
        if isinstance(faulted, BaseException):
            refusal = getattr(faulted, "refusal", None)
            self.assertIsInstance(refusal, dict, "a writer fault left without its six fields: %r" % (faulted,))
            rows = [refusal]
        elif isinstance(faulted, list):
            rows = [r for r in faulted if isinstance(r, dict) and r.get("failure_code")]
        else:
            rows = [faulted] if isinstance(faulted, dict) and faulted.get("failure_code") else []
        for row in rows:
            if row.get("quarantine") == "FRAME_REFUSED_QUARANTINED":
                continue  # a frame's own content refusal, not the injected fault
            if row["failure_code"] in ("CARRIED_PROVENANCE_UNVERIFIED",) and isinstance(faulted, dict):
                continue  # the release's re-release refusal, once its frame landed
            self.assertIn(row["failure_code"], ("FRAME_DISPATCH_IO_FAILED", "LEDGER_WRITE_FAULT_RESUMABLE"), row)
            self.assertIs(row["terminal"], False, row)
            for field in SIX_FIELDS:
                self.assertTrue(row[field], field)

    def consume_inbound(self):
        self.open_ledger()
        k, _ = self.kernel_custody()
        self.inbound(k, "b-p36q-request", epoch=4096)

    def test_every_write_of_consume_and_respond_is_resumable(self):
        k = self.crossing.kernel
        self.sweep(self.consume_inbound, lambda: [row["result"] for row in k.consume_and_respond(
            self.root, mesh_root=self.mesh, node_state_root=self.base / "node",
            repo_ledger_root=self.base / "repo-ledger", org_ledger_root=self.base / "org-ledger")])

    def test_every_write_of_crossing_ingress_is_resumable(self):
        self.sweep(self.consume_inbound, lambda: self.crossing.ingress(
            mesh_root=self.mesh, node_state_root=self.base / "node", root=self.root, hb_epoch="4096"))

    def test_every_write_of_a_carried_capability_crossing_is_resumable(self):
        # B-P36m ruling with B-P36q: a CARRIED crossing resumed after a fault, whose
        # earlier receipts moved the head, is verified against its admission record.
        def prepare():
            self.open_ledger()
            k, _ = self.kernel_custody()
            head = self.org_genesis()["receipt_sha256"]
            self.reframed(k, "b-p36q-carried", lambda ref: {**ref, "source": "ORGANIZATION_LEDGER_HEAD",
                                                            "head_receipt_sha": head},
                          service="sv-llm.intr-destination",
                          payload={"message_class": "ecosystem.communication", "communication_id": "b-p36q",
                                   "subject": "purpose-neutral mesh diagnostic",
                                   "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "q"}})
        def run():
            out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=self.base / "node", root=self.root,
                                        hb_epoch="32")
            self.assertNotIn("CARRIED_PROVENANCE_UNVERIFIED", json.dumps(out))
            return out
        self.sweep(prepare, run)

    def test_every_write_of_the_master_records_release_is_resumable(self):
        # The release records its emission on both ledgers and then publishes the
        # frame. A fault at any step resumes from its admission; once the frame is
        # published the segment is released, and releasing it again is refused.
        state = {}

        def prepare():
            self.open_ledger()
            state["genesis"] = self.org_genesis()

        def run():
            done = self.release(state["genesis"])
            self.assertNotIn("Traceback", done.stderr, done.stderr)  # F-WRITER-TRACE
            if done.returncode == 0:
                return json.loads(done.stdout)
            refusal = json.loads(done.stdout)
            frames = list((self.mesh / "frames.d").glob("*.json")) if (self.mesh / "frames.d").exists() else []
            if refusal.get("failure_code") == "CARRIED_PROVENANCE_UNVERIFIED" and frames:
                return refusal  # already released: the re-release refusal
            if refusal.get("failure_code") == "LEDGER_WRITE_FAULT_RESUMABLE":
                return refusal
            raise AssertionError(done.stdout + done.stderr)
        self.sweep(prepare, run)

    def test_every_write_of_crossing_egress_is_resumable(self):
        manifest = {"manifest_id": "b-p36q-egress", "destination": {"organization": PEER}, "payload": {"probe": 1}}
        self.sweep(self.open_ledger, lambda: self.crossing.egress(
            manifest, standing=STANDING, mesh_root=self.mesh, root=self.root, hb_epoch="4096"))

    def test_every_write_of_opening_the_ledger_is_resumable(self):
        def run():
            try:
                return self.crossing.open_organization_ledger(root=self.root, hb_epoch=32)
            except (Exception, SystemExit) as exc:
                if "ORG_LEDGER_GENESIS_ON_NON_EMPTY_LEDGER" in str(exc):
                    return exc  # opened: a second genesis is refused
                raise
        self.sweep(lambda: None, run)

    def faulted_once(self, match, mode, run):
        """Run `run` with an OSError at the first write whose path contains `match`."""
        import fault_injection
        fault_injection.install()
        self.addCleanup(fault_injection.uninstall)
        counter = Path(tempfile.mkdtemp(prefix="stegverse-fault-count-")) / "count"
        self.addCleanup(shutil.rmtree, counter.parent, True)
        os.environ.update(STEGVERSE_FAULT_ROOT=str(self.base.resolve()), STEGVERSE_FAULT_COUNTER=str(counter),
                          STEGVERSE_FAULT_MATCH=match, STEGVERSE_FAULT_MODE=mode, STEGVERSE_FAULT_AT="0")
        try:
            return run()
        finally:
            for name in ("STEGVERSE_FAULT_ROOT", "STEGVERSE_FAULT_COUNTER", "STEGVERSE_FAULT_MATCH",
                         "STEGVERSE_FAULT_MODE", "STEGVERSE_FAULT_AT"):
                os.environ.pop(name, None)

    def test_a_torn_receipt_and_head_append_is_finished_by_the_next_cycle(self):
        # Lane B 09:29Z / 09:31Z torn write: an OSError on the HEAD write after the
        # receipt landed, on the repository append and on the organization append.
        # The next cycle leaves exactly one receipt, a consistent HEAD, and a later
        # frame is consumed as if nothing had happened.
        k = self.crossing.kernel
        for ledger in ("repo-ledger", "org-ledger"):
            with self.subTest(ledger=ledger):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                self.inbound(k, "torn-first", epoch=4096)
                node = self.base / "node"
                run = lambda: [row["result"] for row in k.consume_and_respond(
                    self.root, mesh_root=self.mesh, node_state_root=node,
                    repo_ledger_root=self.base / "repo-ledger", org_ledger_root=self.base / "org-ledger")]
                first = self.faulted_once(ledger + "/HEAD.json", "before", run)
                self.assertEqual([(r["failure_code"], r["terminal"]) for r in first],
                                 [("FRAME_DISPATCH_IO_FAILED", False)], first)
                self.assertTrue((self.base / ledger / "PENDING_APPEND.json").is_file(), "the torn append is journaled")
                second = run()
                self.assertEqual([r.get("status") for r in second], ["CONSUMED"], second)
                self.assertFalse((self.base / ledger / "PENDING_APPEND.json").exists())
                state = self.ledger_state()  # one receipt per class, HEAD consistent, no orphans
                consumed = [n for n, c in state["receipts"].items() if "CONSUMED" in n or "None" in n]
                self.assertTrue(consumed)
                self.assertEqual(state["receipts"]["repo-ledger:ORGANIZATION_FEDERATION_CROSSING_CONSUMED"], 1)
                self.inbound(k, "torn-later", epoch=4096)
                self.assertEqual([r.get("status") for r in run()], ["CONSUMED"])
                self.assertEqual(self.ledger_state()["receipts"]["repo-ledger:ORGANIZATION_FEDERATION_CROSSING_CONSUMED"], 2)
                self.assertEqual(run(), [])

    def test_a_published_answer_is_never_published_twice(self):
        # F-REPUB (Lane B 09:25Z): a fault after the response is published -- the
        # seen-marker write, or the publication's own acknowledgement -- leaves the
        # request pending; the next cycle rebuilds the answer byte-identically and
        # the write-once frame is a no-op, so exactly one response exists.
        for name, match, mode in (("marker OSError", "/seen", "before"),
                                  ("ack OSError", "frames.d", "after")):
            with self.subTest(fault=name):
                self.setUp()
                self.open_ledger()
                k, _ = self.kernel_custody()
                request = self.inbound(k, "f-repub-" + name.split()[0], epoch=4096)
                node = self.base / "node"
                run = lambda: k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node,
                                                    repo_ledger_root=self.base / "repo-ledger",
                                                    org_ledger_root=self.base / "org-ledger")
                first = self.faulted_once(match, mode, run)
                self.assertEqual([row["result"]["failure_code"] for row in first], ["FRAME_DISPATCH_IO_FAILED"], first)
                second = run()
                self.assertEqual([row["result"].get("status") for row in second], ["CONSUMED"])
                self.assertEqual(run(), [])
                responses = [d for d in self.documents(self.mesh / "frames.d")
                             if d.get("packet_id") != request["packet_id"]]
                self.assertEqual(len(responses), 1, responses)
                self.assertEqual(second[0]["response_publication"]["frame"], responses[0])

    def test_every_write_of_a_quarantine_is_resumable(self):
        # A fault writing a quarantine marker leaves the bad frame pending; the
        # next cycle quarantines it once, and the valid frame is consumed once.
        def prepare():
            self.open_ledger()
            k, _ = self.kernel_custody()
            self.reframed(k, "b-p36q-unmarked", lambda ref: {a: b for a, b in ref.items() if a != "derived_from_clock"})
            self.inbound(k, "b-p36q-valid", epoch=4096)
        for route in ("consume_and_respond", "crossing.ingress"):
            with self.subTest(route=route):
                self.sweep(prepare, lambda: self.consume_route(self.crossing.kernel, route, self.base / "node")())

    def test_every_write_of_the_egress_boundary_emit_is_resumable(self):
        payload = {"message_class": "ecosystem.communication", "communication_id": "b-p36q-emit",
                   "subject": "purpose-neutral mesh diagnostic",
                   "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "b-p36q"}}

        def run():
            try:
                return self.egress.emit(PEER, payload, standing=STANDING, capability="intr-destination",
                                        root=self.root, mesh_root=self.mesh, hb_epoch="4096")
            except (Exception, SystemExit) as exc:
                if self.egress.kernel.writer_fault(exc):
                    raise self.egress.kernel.WriterFaultRefused(self.egress.kernel.writer_fault_refusal(
                        exc, retry_entrypoint="resident-runtime/organization_egress_boundary.py::emit"))
                raise
        self.sweep(self.open_ledger, run)

    def test_a_fault_after_head_returns_the_recorded_receipt(self):
        # F-POST-HEAD: HEAD lands, then its durability step fails. The retry of the
        # same transition returns the receipt HEAD names; there is exactly one.
        emit = self.egress.repository_ledger
        args = ("F-POST-HEAD:emit", "F_POST_HEAD", "sha256:" + "0" * 64, "sha256:" + "1" * 64, {}, "NONE")
        with self.assertRaises(OSError):
            self.faulted_once("repo-ledger/HEAD.json", "after", lambda: emit.append(*args, hb_epoch=32))
        again = emit.append(*args, hb_epoch=32)
        receipts = [d for d in self.documents(self.base / "repo-ledger" / "receipts")]
        self.assertEqual([r["receipt_sha256"] for r in receipts], [again["receipt_sha256"]])
        head = json.loads((self.base / "repo-ledger" / "HEAD.json").read_text())
        self.assertEqual(head["receipt_sha256"], again["receipt_sha256"])
        self.assertFalse((self.base / "repo-ledger" / "PENDING_APPEND.json").exists())
        # A later, different transition is appended as usual.
        later = emit.append("F-POST-HEAD:later", "F_POST_HEAD", "sha256:" + "1" * 64, "sha256:" + "2" * 64, {},
                            "NONE", hb_epoch=32)
        self.assertEqual(later["previous_receipt_sha256"], again["receipt_sha256"])
        # The organization append likewise.
        self.open_ledger()
        source = self.repo_receipt()
        aggregate = lambda: self.agg.append(source, "REPO_STATE_PROPAGATION", self.agg.FROM_HEAD,
                                            "sha256:" + "3" * 64, {}, "NONE", hb_epoch=32)
        with self.assertRaises(OSError):
            self.faulted_once("org-ledger/HEAD.json", "after", aggregate)
        recorded = aggregate()
        consuming = [d for d in self.documents(self.base / "org-ledger" / "receipts")
                     if d.get("source_transition_sha256") == source["receipt_sha256"]]
        self.assertEqual([r["receipt_sha256"] for r in consuming], [recorded["receipt_sha256"]])

    def test_a_content_collision_is_terminal_and_a_store_collision_is_not(self):
        # VALIDATOR: the same transition id over different content is the caller's
        # conflict (terminal); a collision the store meets is its own state (non-terminal).
        k = self.crossing.kernel
        emit = self.egress.repository_ledger
        emit.append("COLLIDE:1", "COLLIDE", "sha256:" + "0" * 64, "sha256:" + "1" * 64, {}, "NONE", hb_epoch=32,
                    idempotent_on=())
        with self.assertRaises(ValueError) as raised:
            emit.append("COLLIDE:1", "COLLIDE", "sha256:" + "0" * 64, "sha256:" + "9" * 64, {}, "NONE", hb_epoch=32,
                        idempotent_on=())
        self.assertEqual(str(raised.exception), "ledger_receipt_collision")
        self.assertFalse(k.writer_fault(raised.exception))
        refusal = k.content_collision_refusal(raised.exception, retry_entrypoint="test")
        self.assertEqual((refusal["failure_code"], refusal["terminal"]), ("TRANSITION_CONTENT_COLLISION", True))
        for field in SIX_FIELDS:
            self.assertTrue(refusal[field], field)
        self.assertTrue(k.writer_fault(ValueError("ledger_receipt_collision")))  # raised by the store itself

    def test_a_different_request_never_receives_another_requests_response(self):
        # F-REPUB keying: the same request reuses its response; a different request
        # under the same communication id is RESPONSE_ID_COLLISION, terminal, and the
        # first response is not handed to it.
        self.open_ledger()
        k, _ = self.kernel_custody()
        def request(packet_id, subject):
            packet = k.build_packet(origin_org=PEER, origin_service="stegverse-org.org-control", destination_org="SV-LLM",
                                    destination_service="sv-llm.org-control",
                                    payload={"message_class": "ecosystem.monitor.request", "subject": subject,
                                             "communication_id": "f-repub-shared"},
                                    standing=STANDING, packet_id=packet_id)
            frame = k.carrier_frame(packet, epoch=4096)
            k._publish_frame(frame, root=self.mesh)
            return frame
        node = self.base / "node"
        run = lambda node: k.consume_and_respond(self.root, mesh_root=self.mesh, node_state_root=node,
                                                 repo_ledger_root=self.base / "repo-ledger",
                                                 org_ledger_root=self.base / "org-ledger")
        first = request("f-repub-first", "one")
        answered, = run(node)
        self.assertEqual(answered["result"]["status"], "CONSUMED")
        again, = run(self.base / "fresh-node")  # the same request again: the same response, published once
        self.assertEqual(again["response_publication"]["frame"], answered["response_publication"]["frame"])
        request("f-repub-second", "two")
        refused, = run(node)
        self.assertEqual((refused["result"]["failure_code"], refused["result"]["quarantine"]),
                         ("RESPONSE_ID_COLLISION", "FRAME_REFUSED_QUARANTINED"))
        for field in SIX_FIELDS:
            self.assertTrue(refused["result"][field], field)
        responses = [d for d in self.documents(self.mesh / "frames.d")
                     if d.get("packet_id") not in (first["packet_id"], "f-repub-second")]
        self.assertEqual(len(responses), 1, responses)
        self.assertEqual(run(node), [])

    def cli(self, argv):
        done = subprocess.run([sys.executable, "-B", *argv], cwd=self.root, capture_output=True, text=True,
                              env=dict(os.environ), timeout=120)
        self.assertNotIn("Traceback", done.stderr, done.stderr)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            lines = [line for line in done.stdout.splitlines() if line.strip().startswith("{")]
            out = json.loads(lines[-1]) if lines else None
        if isinstance(out, list):  # crossing ingress prints one row per frame
            failed = [r for r in out if isinstance(r, dict) and r.get("failure_code")]
            out = failed[0] if failed else {"disposition": "ALLOW", "rows": out}
        return done.returncode, out, done

    def cli_inputs(self):
        """Each epoch-taking CLI with each JSON input argument it reads, and what else it needs."""
        bad = self.base.parent / (self.base.name + "-inputs")
        bad.mkdir(exist_ok=True)
        (bad / "not.json").write_text("{not json")
        (bad / "list.json").write_text("[1]")
        (bad / "ok.json").write_text(json.dumps(STANDING))
        self.addCleanup(shutil.rmtree, bad, True)
        mesh, node, registry = str(self.mesh), str(self.base / "node"), "org-boundary/registry/services.json"
        rows = [
            ("emit", [".stegverse/transition-ledger/emit.py", "--transition-id", "i", "--transition-class", "I",
                      "--predecessor-state-sha256", "sha256:" + "0" * 64, "--successor-state-sha256",
                      "sha256:" + "1" * 64, "--hb-epoch", "32"], "--evidence-json", "inline"),
            ("aggregate", ["resident-runtime/aggregate_repo_transition.py", "--predecessor-org-state-sha256",
                           "FROM_HEAD", "--successor-org-state-sha256", "sha256:" + "1" * 64, "--hb-epoch", "32"],
             "--repo-receipt", "file"),
            ("aggregate", ["resident-runtime/aggregate_repo_transition.py", "--repo-receipt", str(bad / "ok.json"),
                           "--predecessor-org-state-sha256", "FROM_HEAD", "--successor-org-state-sha256",
                           "sha256:" + "1" * 64, "--hb-epoch", "32"], "--boundary-evidence-json", "inline"),
            ("crossing egress", ["org-runtime/crossing.py", "egress", "--standing", str(bad / "ok.json"),
                                 "--mesh-root", mesh, "--hb-epoch", "32"], "--manifest", "file"),
            ("crossing egress", ["org-runtime/crossing.py", "egress", "--manifest", str(bad / "ok.json"),
                                 "--mesh-root", mesh, "--hb-epoch", "32"], "--standing", "file"),
            ("authentic lane", ["org-runtime/authentic_live_lane.py", "prepare", "--out", str(bad / "out.json"),
                                "--hb-epoch", "32"], "--target", "file"),
            ("intr receive", ["resident-runtime/intr_destination_ingress.py", "--registry", registry,
                              "--hb-epoch", "32"], "--payload", "file-any"),
            ("intr receive", ["resident-runtime/intr_destination_ingress.py", "--payload", str(bad / "ok.json"),
                              "--hb-epoch", "32"], "--registry", "file"),
            ("intr self-close", ["resident-runtime/intr_destination_ingress.py", "--self-close",
                                 "--communication-id", "i", "--packet-id", "i", "--hb-epoch", "32"], "--registry", "file"),
            ("egress boundary", ["resident-runtime/organization_egress_boundary.py", "--destination-organization", PEER,
                                 "--standing", str(bad / "ok.json"), "--mesh-root", mesh, "--hb-epoch", "32"],
             "--payload", "file"),
            ("egress boundary", ["resident-runtime/organization_egress_boundary.py", "--destination-organization", PEER,
                                 "--payload", str(bad / "ok.json"), "--mesh-root", mesh, "--hb-epoch", "32"],
             "--standing", "file"),
            ("release", [RELEASE_CLI,
                         "--predecessor-ecosystem-state-sha256", "sha256:" + "0" * 64,
                         "--successor-ecosystem-state-sha256", "sha256:" + "1" * 64,
                         "--standing", str(bad / "ok.json"), "--mesh-root", mesh], "--org-receipt", "file"),
            ("release", [RELEASE_CLI, "--org-receipt",
                         str(bad / "ok.json"), "--predecessor-ecosystem-state-sha256", "sha256:" + "0" * 64,
                         "--successor-ecosystem-state-sha256", "sha256:" + "1" * 64, "--mesh-root", mesh],
             "--standing", "file"),
            ("release", [RELEASE_CLI, "--org-receipt",
                         str(bad / "ok.json"), "--standing", str(bad / "ok.json"),
                         "--predecessor-ecosystem-state-sha256", "sha256:" + "0" * 64,
                         "--successor-ecosystem-state-sha256", "sha256:" + "1" * 64, "--mesh-root", mesh],
             "--relation-evidence-json", "inline"),
        ]
        return bad, rows

    def test_every_cli_input_is_refused_terminally_before_anything_is_written(self):
        # F-INPUT-TRACE: a missing path, a directory, non-JSON or the wrong top-level
        # type is a TERMINAL six-field CLI_INPUT_INVALID, exit 1, nothing written,
        # no traceback; never a non-terminal write fault.
        self.open_ledger()
        bad, rows = self.cli_inputs()
        for name, argv, argument, kind in rows:
            if kind == "inline":
                values = {"non-JSON": "{not json", "wrong type": "[1]"}
            else:
                values = {"missing": str(bad / "missing.json"), "directory": str(bad), "non-JSON": str(bad / "not.json")}
                if kind == "file":
                    values["wrong type"] = str(bad / "list.json")
            for label, value in values.items():
                with self.subTest(cli=name, argument=argument, input=label):
                    before = files_under(self.base)
                    code, refusal, done = self.cli(argv + [argument, value])
                    self.assertEqual(code, 1, done.stdout + done.stderr)
                    self.assertEqual((refusal["failure_code"], refusal["terminal"]), ("CLI_INPUT_INVALID", True), refusal)
                    for field in SIX_FIELDS:
                        self.assertTrue(refusal[field], field)
                    self.assertIn(argument, refusal["detail"])
                    self.assertEqual(files_under(self.base), before)

    def cli_sweep(self, prepare, argv, settle=1):
        """F-WRITER-TRACE: every write of a CLI faulted; six fields, no traceback, the next run completes once."""
        def run():
            code, out, done = self.cli(argv() if callable(argv) else argv)
            self.assertIsNotNone(out, done.stdout + done.stderr)
            if code != 0 and out.get("failure_code") == "LEDGER_WRITE_FAULT_RESUMABLE":
                return out
            if code != 0 and out.get("disposition") not in ("ALLOW", "PENDING"):
                if out.get("failure_code") == "ORG_LEDGER_GENESIS_ON_NON_EMPTY_LEDGER":
                    for field in SIX_FIELDS:
                        self.assertTrue(out[field], field)
                    return {}  # opened: a second genesis is refused, with its six fields
                raise AssertionError(json.dumps(out))
            return out
        self.sweep(prepare, run, settle=settle)

    def test_every_write_of_the_emitter_cli_prints_six_fields_and_resumes(self):
        self.cli_sweep(lambda: None, [".stegverse/transition-ledger/emit.py", "--transition-id", "w", "--transition-class",
                                      "W", "--predecessor-state-sha256", "sha256:" + "0" * 64,
                                      "--successor-state-sha256", "sha256:" + "1" * 64, "--hb-epoch", "32"])

    def test_every_write_of_the_aggregate_cli_prints_six_fields_and_resumes(self):
        source = self.base.parent / (self.base.name + "-source.json")
        self.addCleanup(lambda: source.unlink(missing_ok=True))

        def prepare():
            self.open_ledger()
            source.write_text(json.dumps(self.repo_receipt()))
        self.cli_sweep(prepare, lambda: ["resident-runtime/aggregate_repo_transition.py", "--repo-receipt", str(source),
                                         "--predecessor-org-state-sha256", "FROM_HEAD",
                                         "--successor-org-state-sha256", "sha256:" + "4" * 64, "--hb-epoch", "32"])

    def test_every_write_of_the_crossing_clis_prints_six_fields_and_resumes(self):
        files = self.base.parent / (self.base.name + "-crossing")
        files.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, files, True)
        (files / "manifest.json").write_text(json.dumps({"manifest_id": "f-writer-trace",
                                                         "destination": {"organization": PEER}, "payload": {"probe": 1}}))
        (files / "standing.json").write_text(json.dumps(STANDING))
        with self.subTest(cli="open-ledger"):
            self.cli_sweep(lambda: None, ["org-runtime/crossing.py", "open-ledger", "--hb-epoch", "32"], settle=2)
        with self.subTest(cli="egress"):
            self.cli_sweep(self.open_ledger, lambda: ["org-runtime/crossing.py", "egress", "--manifest",
                                                      str(files / "manifest.json"), "--standing",
                                                      str(files / "standing.json"), "--mesh-root", str(self.mesh),
                                                      "--hb-epoch", "4096"], settle=2)
        with self.subTest(cli="ingress"):
            self.cli_sweep(self.consume_inbound, lambda: ["org-runtime/crossing.py", "ingress", "--mesh-root",
                                                          str(self.mesh), "--node-state-root", str(self.base / "node"),
                                                          "--hb-epoch", "4096"], settle=2)

    def test_every_write_of_the_intr_destination_cli_prints_six_fields_and_resumes(self):
        self.cli_sweep(self.open_ledger, ["resident-runtime/intr_destination_ingress.py", "--self-close",
                                          "--registry", "org-boundary/registry/services.json",
                                          "--communication-id", "f-writer-trace", "--packet-id", "f-writer-trace",
                                          "--hb-epoch", "32"], settle=2)

    def test_every_write_of_the_egress_boundary_cli_prints_six_fields_and_resumes(self):
        files = self.base.parent / (self.base.name + "-egress")
        files.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, files, True)
        (files / "payload.json").write_text(json.dumps({
            "message_class": "ecosystem.communication", "communication_id": "f-writer-trace",
            "subject": "purpose-neutral mesh diagnostic",
            "body": {"schema": "stegverse.org-intr-destination-diagnostic/v1", "probe": "f-writer-trace"}}))
        (files / "standing.json").write_text(json.dumps(STANDING))
        self.cli_sweep(self.open_ledger, lambda: ["resident-runtime/organization_egress_boundary.py",
                                                  "--destination-organization", PEER, "--capability", "intr-destination",
                                                  "--payload", str(files / "payload.json"), "--standing",
                                                  str(files / "standing.json"), "--mesh-root", str(self.mesh),
                                                  "--hb-epoch", "4096"], settle=2)

    def manifest_sdk(self):
        root = os.environ.get("STEGVERSE_SDK_ROOT")
        if not root or not (Path(root) / "stegverse/manifest_builder.py").is_file():
            if os.environ.get("STEGVERSE_SDK_REQUIRED") == "1":
                self.fail("STEGVERSE_SDK_REQUIRED=1 but no SDK checkout was found")
            self.skipTest("the manifest ingress imports the StegVerse SDK (STEGVERSE_SDK_ROOT)")
        os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(root).resolve()),
                                                                 os.environ.get("PYTHONPATH")]))

    def test_the_manifest_ingress_cli_inputs_are_refused_terminally(self):
        # F-INPUT-TRACE on the manifest ingress CLI: each input argument.
        self.manifest_sdk()
        self.open_ledger()
        bad, _ = self.cli_inputs()
        (bad / "empty.json").write_text("{}")
        base = ["resident-runtime/organization_manifest_ingress.py", "--hb-epoch", "32"]
        inputs = {"--manifest": str(bad / "empty.json"), "--registry": "org-boundary/registry/services.json",
                  "--standing": str(bad / "ok.json")}
        for argument in inputs:
            others = [part for name, value in inputs.items() if name != argument for part in (name, value)]
            for label, value in (("missing", str(bad / "missing.json")), ("directory", str(bad)),
                                 ("non-JSON", str(bad / "not.json")), ("wrong type", str(bad / "list.json"))):
                with self.subTest(argument=argument, input=label):
                    before = files_under(self.base)
                    code, refusal, done = self.cli(base + others + [argument, value])
                    self.assertEqual(code, 1, done.stdout + done.stderr)
                    self.assertEqual((refusal["failure_code"], refusal["terminal"]), ("CLI_INPUT_INVALID", True))
                    for field in SIX_FIELDS:
                        self.assertTrue(refusal[field], field)
                    self.assertEqual(files_under(self.base), before)

    def test_every_write_of_the_manifest_ingress_cli_prints_six_fields_and_resumes(self):
        # F-WRITER-TRACE on the manifest ingress CLI: an unresolvable manifest is a
        # recorded refusal (both ledgers); every write of it is faulted.
        self.manifest_sdk()
        files = self.base.parent / (self.base.name + "-manifest")
        files.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, files, True)
        (files / "manifest.json").write_text("{}")

        def run():
            code, out, done = self.cli(["resident-runtime/organization_manifest_ingress.py", "--manifest",
                                        str(files / "manifest.json"), "--registry",
                                        "org-boundary/registry/services.json", "--hb-epoch", "32"])
            self.assertIsNotNone(out, done.stdout + done.stderr)
            if out.get("failure_code") in ("LEDGER_WRITE_FAULT_RESUMABLE", "TRANSITION_CONTENT_COLLISION"):
                return out
            self.assertEqual(out.get("receiving_operation"), "ORGANIZATION_SDK_MANIFEST_INGRESS", out)
            return {}  # the refusal this operation records, written once
        self.sweep(self.open_ledger, run, settle=2)

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
