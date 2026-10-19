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
                                      ("sampled, unflagged", unflagged, "HB_EPOCH_PROVENANCE_UNMARKED")):
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
            self.assertEqual(evidence["hb_epoch_provenance"], {
                "provenance": "CARRIED:ORGANIZATION_LEDGER_HEAD", "source": "ORGANIZATION_LEDGER_HEAD",
                "head_receipt_sha256": genesis["receipt_sha256"], "epoch": genesis["hb_reference"]["epoch"],
                "derived_from_clock": False})
            self.assertEqual(receipt["hb_reference"]["epoch"], genesis["hb_reference"]["epoch"])
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

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

    def test_a_clock_stamped_frame_carries_no_epoch_into_a_receipt(self):
        # B-P36f: an ingress forwards a frame's epoch only when it is CARRIED, not
        # clock-derived. The kernel's consumer refuses the frame and writes
        # nothing; crossing.ingress records the refusal at its supplied epoch,
        # and no receipt takes the clock epoch.
        self.open_ledger()
        k, custody = self.kernel_custody()
        packet = k.build_packet(origin_org=PEER, origin_service="stegverse-org.org-control", destination_org="SV-LLM",
                                destination_service="sv-llm.org-control",
                                payload={"message_class": "ecosystem.monitor.request", "subject": "b-p36f"},
                                standing=STANDING, packet_id="b-p36f-clock-frame")
        frame = k.carrier_frame(packet, now_ns=k.HB_ANCHOR_UNIX_NS + 10 ** 12)
        clock_epoch = frame["heartbeat_reference"]["epoch"]
        self.assertIs(frame["heartbeat_reference"]["derived_from_clock"], True)
        k._publish_frame(frame, root=self.mesh)
        before = files_under(self.base)
        with self.assertRaises(k.SuppliedEpochRefused) as raised:
            k.consume_addressed_frames(self.root, mesh_root=self.mesh, repo_ledger_root=self.base / "repo-ledger",
                                       org_ledger_root=self.base / "org-ledger")
        self.assertEqual(raised.exception.refusal["failure_code"], "HB_EPOCH_INVALID")
        self.assertEqual(files_under(self.base), before)
        out = self.crossing.ingress(mesh_root=self.mesh, node_state_root=self.base / "node", root=self.root,
                                    hb_epoch="4096")
        self.assertEqual([(r["disposition"], r["failed_predicate"]) for r in out],
                         [("DENY", "BOUNDARY_DISPATCH_REFUSED")], out)
        self.assertIn("HB_EPOCH_INVALID", json.dumps(out[0]))
        self.assertEqual(self.receipts_at(clock_epoch), [])
        for receipt in self.receipts_at(4096):
            self.assertIs(receipt["hb_reference"]["derived_from_clock"], False)

    def test_an_unmarked_reference_is_refused(self):
        # B-P36h (P): a heartbeat reference must mark derived_from_clock exactly
        # false, or carry a CARRIED provenance; an unmarked one is refused.
        k = self.crossing.kernel
        unmarked = {k_: v for k_, v in k.hb_reference(epoch=4096).items() if k_ != "derived_from_clock"}
        self.assertEqual(k.supplied_epoch_failure(4096, unmarked)[0], "HB_EPOCH_PROVENANCE_UNMARKED")
        with self.assertRaises(k.SuppliedEpochRefused) as raised:
            k.carried_epoch(unmarked, retry_entrypoint="test")
        self.assertEqual(raised.exception.refusal["failure_code"], "HB_EPOCH_PROVENANCE_UNMARKED")
        for field in SIX_FIELDS:
            self.assertTrue(raised.exception.refusal[field], field)
        self.assertIsNone(k.supplied_epoch_failure(4096, {**unmarked, "provenance": "CARRIED:ORGANIZATION_LEDGER_HEAD"}))

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
        for provenance in ({"source": "ORGANIZATION_LEDGER_HEAD", "head_receipt_sha256": "sha256:" + "9" * 64,
                            "derived_from_clock": False},
                           {"source": "ORGANIZATION_LEDGER_HEAD", "derived_from_clock": False}):
            with self.subTest(provenance=provenance):
                before = files_under(self.base)
                with self.assertRaises(k.SuppliedEpochRefused) as raised:
                    k.publish_packet(self.packet("b-p36h-invented"), root=self.mesh, custody=custody, epoch=32,
                                     epoch_provenance=provenance)
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
