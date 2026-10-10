#!/usr/bin/env python3
"""SV-LLM kernel parity with StegVerse-org/.github #93-#97, and the gaps it closes.

SDK-MANIFEST-ECOSYSTEM-TRANSITION-DISPOSITION-001 (COSV 71000000100126), step 6.
Each case names the gap it reproduces on main ed27bc4:

1. Processing was selected by `boundary_role` alone. Dispatch now resolves
   org-boundary/runtime/manifest_selection.py before any receipt.
2. Ledger appends were not idempotent, publish_packet took no epoch, answers
   were stamped by the host clock, and consume_and_respond /
   consume_addressed_frames consumed and answered crossings with nothing on
   either ledger, threw on a refusal, and accepted a foreign dispatch root.
3. SV-LLM-EXEMPTION-001 declared DENY_DIRECT_USE with no code enforcing it.
4. crossing.py::_materialize wrote under the checkout with write_text, and
   consumption markers fell back to the checkout.

Every case runs on scratch: ledgers, mesh and node state are supplied under a
temporary directory, and SV-LLM's own checkout is never written. Source
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
GENESIS = {"mode": "ESTABLISH_GENESIS", "node_ref": "sv-llm-parity-test", "predecessor": None}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


peers = load("peer_organization_parity", REPO / "org-runtime/tests/peer_organization.py")
selection = load("manifest_selection_parity", REPO / "org-boundary/runtime/manifest_selection.py")


def scratch(case):
    path = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, path, True)
    return path


class SVLLMNode(unittest.TestCase):
    """SV-LLM's own kernel, over ledgers and node state supplied on scratch."""

    def setUp(self):
        self.base = scratch(self)
        self.sv = peers.Peer(REPO, self.base / "sv-llm", "SV-LLM")
        self.sv.open_ledger()
        self.k = self.sv.kernel
        self.origin = peers.materialize(self.base, "Origin-Org", [
            {"service_id": "origin-org.org-control", "repository": "Origin-Org/.github",
             "boundary_role": "BOUNDARY_LOCAL_CONTROL"}])
        self.mesh = self.base / "mesh"

    def send(self, service, payload, *, packet_id, standing=GENESIS, epoch=None):
        packet = self.origin.kernel.build_packet(
            origin_org="Origin-Org", origin_service="origin-org.org-control", destination_org="SV-LLM",
            destination_service=service, payload=payload, standing=standing, packet_id=packet_id)
        return self.origin.publish(packet, mesh_root=self.mesh, epoch=epoch or self.k.HB_ANCHOR_EPOCH + 500)

    def monitor(self, packet_id="parity-monitor-1"):
        return self.send("sv-llm.org-control", {"message_class": "ecosystem.monitor.request",
                                                "communication_id": packet_id, "subject": "s", "body": {}},
                         packet_id=packet_id)

    def consume(self, **overrides):
        return self.sv.consume(mesh_root=self.mesh, **overrides)

    def answers(self):
        return self.k.scan_addressed_frames("Origin-Org", root=self.mesh)

    def by_class(self, transition_class):
        return [r for r in self.sv.receipts("repo") if r.get("transition_class") == transition_class]

    def tearDown(self):
        # Nothing in this suite writes under SV-LLM's checkout.
        for path in ("resident-runtime/federation", "resident-runtime/control", "resident-runtime/materialized"):
            self.assertFalse((REPO / path).exists(), path)


class ProcessingSelection(unittest.TestCase):
    """Item 1: processing is selected by an admitted capability and route, never by role alone."""

    ROUTE = {"capability": "ecosystem_diagnostic", "route_id": "stegverse.route.ecosystem-diagnostic.v1"}
    ENDPOINT = {"service_id": "x.endpoint", "boundary_role": "INTERNAL_ENDPOINT", "admits_processing": [ROUTE]}

    def test_undeclared_internal_endpoint_processing_is_refused_by_name(self):
        with self.assertRaises(SystemExit) as refused:
            selection.select_processing(self.ENDPOINT, {"request": {}})
        self.assertTrue(str(refused.exception).startswith(
            "PROCESSING_SELECTED_ONLY_BY_ADMITTED_PROCESSING_CAPABILITY_AND_ROUTE_ID:"
            "IDENTITY_SELECTED_NO_MANIFEST_DECLARATION:x.endpoint"))

    def test_only_a_bound_endpoint_response_returns_without_a_declaration(self):
        response = {"schema": "stegverse.org-endpoint-response/v1", "response_to_packet_id": "p",
                    "request_manifest_sha256": "sha256:" + "a" * 64}
        accepting = {**self.ENDPOINT, "accepts": ["stegverse.org-endpoint-response/v1"]}
        self.assertEqual(selection.select_processing(accepting, response)["processing_selection"],
                         "RETURN_BOUND_TO_REQUEST")
        for service, payload in ((self.ENDPOINT, response),
                                 (accepting, {**response, "response_to_packet_id": " "}),
                                 (accepting, {**response, "schema": "other"})):
            with self.assertRaises(SystemExit):
                selection.select_processing(service, payload)

    def test_an_admitted_pair_is_manifest_selected_and_any_other_is_refused(self):
        chosen = selection.select_processing(self.ENDPOINT, {"manifest": {"processing": self.ROUTE}})
        self.assertEqual((chosen["processing_selection"], chosen["declared_capability_processed"]),
                         ("MANIFEST_DECLARED", True))
        for processing in ({"capability": "governance", "route_id": self.ROUTE["route_id"]},
                           {"capability": "ecosystem_diagnostic", "route_id": "other"},
                           {"capability": "ecosystem_diagnostic"}):
            with self.assertRaises(SystemExit):
                selection.select_processing(self.ENDPOINT, {"processing": processing})

    def test_a_boundary_local_surface_selects_nothing_and_says_so(self):
        chosen = selection.select_processing({"boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"},
                                             {"processing": self.ROUTE})
        self.assertEqual((chosen["processing_selection"], chosen["declared_capability"],
                          chosen["declared_capability_processed"]),
                         ("BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED", "ecosystem_diagnostic", False))

    def test_sv_llm_registers_no_processor_and_declares_no_admission_it_never_consults(self):
        services = json.loads((REPO / "org-boundary/registry/services.json").read_text())["services"]
        self.assertTrue(all(s["boundary_role"].startswith("BOUNDARY_LOCAL_") for s in services))
        self.assertTrue(all("admits_processing" not in s for s in services))
        self.assertFalse((REPO / "org-boundary/runtime/process_boundary.py").exists())


class DispatchSelects(SVLLMNode):
    def test_a_declared_capability_crossing_to_the_diagnostic_is_not_reported_processed(self):
        self.send("sv-llm.boundary-diagnostic", {"manifest": {"processing": ProcessingSelection.ROUTE}},
                  packet_id="parity-diag-1")
        consumed, = self.consume()
        execution = consumed["result"]["execution_result"]
        self.assertEqual(execution["processing_selection"], "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")
        self.assertEqual(execution["declared_capability"], "ecosystem_diagnostic")
        self.assertIs(execution["declared_capability_processed"], False)
        self.assertEqual(execution["route_admissibility"], "NOT_RESOLVED_AT_BOUNDARY_ROUTE_OWNER_IS_SDK")
        recorded, = self.by_class(self.k.CROSSING_CONSUMED_CLASS)
        self.assertEqual(recorded["evidence"]["processing_selection"], "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")

    def test_a_root_with_no_selection_module_fails_closed_before_any_receipt(self):
        bare = peers.materialize(self.base, "No-Selection", [
            {"service_id": "no-selection.boundary-diagnostic", "repository": "No-Selection/.github",
             "boundary_role": "BOUNDARY_LOCAL_DIAGNOSTIC"}])
        (bare.root / "org-boundary/runtime/manifest_selection.py").unlink()
        packet = bare.kernel.build_packet(origin_org="Origin-Org", origin_service="origin-org.org-control",
                                          destination_org="No-Selection",
                                          destination_service="no-selection.boundary-diagnostic",
                                          payload={"probe": 1}, standing=GENESIS)
        with self.assertRaisesRegex(ValueError, "org_boundary_manifest_selection_missing"):
            bare.kernel.dispatch(bare.root, packet, custody=bare.custody())


class IdempotentLedgers(unittest.TestCase):
    """Item 2: one transition is one receipt however many times it is appended."""

    def setUp(self):
        self.base = scratch(self)
        self.emit = load("emit_parity", REPO / ".stegverse/transition-ledger/emit.py")
        self.org = load("aggregate_parity", REPO / "resident-runtime/aggregate_repo_transition.py")
        self.repo_store = self.emit.ledger_store.PosixLedgerStore(self.base / "repo")
        self.org_store = self.emit.ledger_store.PosixLedgerStore(self.base / "org")
        self.args = ("T-1", "C", "sha256:" + "0" * 64, "sha256:" + "1" * 64, {"frame_sha256": "f", "packet_id": "p"}, "NONE")

    def receipts(self, level):
        return list((self.base / level / "receipts").glob("*.json"))

    def test_an_idempotent_repository_append_returns_the_recorded_receipt(self):
        first = self.emit.append(*self.args, hb_epoch=40, store=self.repo_store, idempotent_on=("frame_sha256",))
        again = self.emit.append(*self.args, hb_epoch=41, store=self.repo_store, idempotent_on=("frame_sha256",))
        self.assertEqual(first, again)
        self.assertEqual(len(self.receipts("repo")), 1)

    def test_one_id_over_another_predecessor_or_evidence_is_a_collision(self):
        self.emit.append(*self.args, hb_epoch=40, store=self.repo_store, idempotent_on=("frame_sha256",))
        changed = list(self.args)
        changed[4] = {"frame_sha256": "other", "packet_id": "p"}
        with self.assertRaisesRegex(ValueError, "ledger_receipt_collision"):
            self.emit.append(*changed, hb_epoch=40, store=self.repo_store, idempotent_on=("frame_sha256",))
        changed = list(self.args)
        changed[2] = "sha256:" + "2" * 64
        with self.assertRaisesRegex(ValueError, "ledger_receipt_collision"):
            self.emit.append(*changed, hb_epoch=40, store=self.repo_store, idempotent_on=())

    def test_without_idempotency_each_append_is_its_own_receipt(self):
        self.emit.append(*self.args, hb_epoch=40, store=self.repo_store)
        self.emit.append(*self.args, hb_epoch=40, store=self.repo_store)
        self.assertEqual(len(self.receipts("repo")), 2)

    def test_an_organization_receipt_consumes_its_source_once(self):
        source = self.emit.append(*self.args, hb_epoch=40, store=self.repo_store)
        first = self.org.append(source, "REPO_STATE_PROPAGATION", self.org.GENESIS, source["receipt_sha256"],
                                {}, "NONE", hb_epoch=40, store=self.org_store, idempotent=True)
        again = self.org.append(source, "REPO_STATE_PROPAGATION", self.org.GENESIS, source["receipt_sha256"],
                                {}, "NONE", hb_epoch=40, store=self.org_store, idempotent=True)
        self.assertEqual(first, again)
        with self.assertRaisesRegex(ValueError, "ledger_receipt_collision"):
            self.org.append(source, "OTHER_CLASS", self.org.FROM_HEAD, source["receipt_sha256"],
                            {}, "NONE", hb_epoch=40, store=self.org_store, idempotent=True)
        self.assertEqual(len(self.receipts("org")), 1)


class ConsumedCrossingsAreRecorded(SVLLMNode):
    """Item 2: every consumed crossing is on both ledgers before its answer or marker."""

    def test_a_consumed_crossing_is_recorded_at_both_levels_and_answered_at_its_epoch(self):
        sent = self.monitor()
        consumed, = self.consume()
        self.assertEqual(consumed["result"]["status"], "CONSUMED")
        repository, = self.by_class(self.k.CROSSING_CONSUMED_CLASS)
        self.assertEqual(repository["evidence"]["packet_id"], "parity-monitor-1")
        self.assertEqual(repository["evidence"]["frame_sha256"], sent["frame"]["frame_sha256"])
        organization = [r for r in self.sv.receipts("org") if r["repo_receipt_sha256"] == repository["receipt_sha256"]]
        self.assertEqual(len(organization), 1)
        self.assertEqual(organization[0]["organization"], "SV-LLM")
        self.assertEqual(consumed["organization_record"]["organization_receipt_sha256"],
                         organization[0]["receipt_sha256"])
        answer, = self.answers()
        self.assertEqual(answer["frame"]["heartbeat_reference"]["epoch"], sent["frame"]["heartbeat_reference"]["epoch"])
        self.assertIs(answer["frame"]["heartbeat_reference"]["derived_from_clock"], False)

    def test_consuming_the_same_frame_again_reproduces_rather_than_repeats(self):
        """A node that lost its consumption marker consumes the frame again."""
        self.send("sv-llm.org-control", {"message_class": "ecosystem.communication", "communication_id": "c1",
                                         "subject": "s", "body": {}}, packet_id="parity-communication-1")
        first, = self.consume()
        again, = self.consume(node_state_root=self.base / "fresh-node")
        self.assertEqual(first["organization_record"], again["organization_record"])
        self.assertEqual(first["response_publication"]["frame"], again["response_publication"]["frame"])
        self.assertEqual(len(self.by_class(self.k.CROSSING_CONSUMED_CLASS)), 1)
        self.assertEqual(len(self.answers()), 1)

    def mesh_frames(self):
        return sorted(str(path.relative_to(self.mesh)) for path in self.mesh.rglob("*.json"))

    def test_a_monitor_answer_carries_the_frame_epoch_and_replays_as_a_no_op(self):
        """N-CLOCK: the status a monitor answer embeds used to sample the host
        clock, so every re-answer was a different frame and a second answer."""
        sent = self.monitor()
        epoch = sent["frame"]["heartbeat_reference"]["epoch"]
        first, = self.consume()
        status = first["result"]["execution_result"]["application_result"]["monitor_status"]
        self.assertEqual(status["heartbeat_reference"]["epoch"], epoch)
        self.assertIs(status["heartbeat_reference"]["derived_from_clock"], False)
        self.assertNotIn("sampled_unix_ns", status["heartbeat_reference"])
        answer = first["response_publication"]["frame"]
        before = self.mesh_frames()
        again, = self.consume(node_state_root=self.base / "fresh-node")
        self.assertEqual(again["response_publication"]["frame"], answer)
        self.assertEqual(self.mesh_frames(), before)
        self.assertEqual(len(self.answers()), 1)

    def test_a_local_status_read_is_labelled_as_a_clock_sample(self):
        status = self.k.resident_status(self.sv.root)
        self.assertIs(status["heartbeat_reference"]["derived_from_clock"], True)
        self.assertIn("sampled_unix_ns", status["heartbeat_reference"])
        self.assertEqual(self.k.resident_status(self.sv.root, epoch=self.k.HB_ANCHOR_EPOCH + 1)
                         ["heartbeat_reference"]["derived_from_clock"], False)

    def test_without_both_ledger_locations_or_node_state_nothing_is_consumed(self):
        self.monitor()
        for missing in ("repo_ledger_root", "org_ledger_root"):
            with self.subTest(missing=missing):
                options = {**self.sv.ledgers(), missing: None}
                with self.assertRaisesRegex(ValueError, "ledger_location_required_from_materializer"):
                    self.k.consume_and_respond(REPO, mesh_root=self.mesh, node_state_root=self.sv.node_state, **options)
        with self.assertRaisesRegex(ValueError, "node_state_location_required_from_materializer"):
            self.k.consume_and_respond(REPO, mesh_root=self.mesh, **self.sv.ledgers())
        self.assertEqual(len(self.k.scan_addressed_frames("SV-LLM", root=self.mesh)), 1)
        self.assertEqual(self.answers(), [])
        self.assertEqual(self.by_class(self.k.CROSSING_CONSUMED_CLASS), [])

    def test_an_undeclared_organization_genesis_consumes_nothing(self):
        unopened = peers.Peer(REPO, self.base / "unopened", "SV-LLM")
        self.monitor()
        with self.assertRaisesRegex(ValueError, "org_ledger_genesis_not_declared"):
            unopened.consume(mesh_root=self.mesh)
        self.assertFalse((self.base / "unopened/org-ledger/receipts").exists())

    def test_a_root_that_is_not_this_kernels_repository_is_refused(self):
        foreign = self.base / "foreign"
        shutil.copytree(REPO / "org-boundary", foreign / "org-boundary")
        for call in (lambda: self.k.consume_and_respond(foreign, mesh_root=self.mesh, node_state_root=self.sv.node_state,
                                                        **self.sv.ledgers()),
                     lambda: self.k.consume_addressed_frames(foreign, mesh_root=self.mesh, **self.sv.ledgers()),
                     lambda: self.k.crossing_custody(self.origin.root, **self.sv.ledgers())):
            with self.assertRaisesRegex(ValueError, "dispatch_root_is_not_this_kernels_organization"):
                call()

    def test_the_emitters_are_the_kernels_own_repositorys(self):
        custody = self.k.crossing_custody(REPO, **self.sv.ledgers())
        self.assertEqual(Path(custody["emitter"].__file__).resolve(), REPO / ".stegverse/transition-ledger/emit.py")
        self.assertEqual(Path(custody["organization_ledger"].__file__).resolve(),
                         REPO / "resident-runtime/aggregate_repo_transition.py")

    def test_a_failed_organization_append_answers_nothing_and_the_next_pass_completes_once(self):
        self.monitor()
        organization_ledger = self.k._own_module("crossing_organization_ledger",
                                                 "resident-runtime/aggregate_repo_transition.py")
        original = organization_ledger.append
        calls = {"n": 0}

        def fails_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise organization_ledger.OrgLedgerAppendRefused("FAIL_CLOSED", "SIMULATED")
            return original(*args, **kwargs)

        organization_ledger.append = fails_once
        self.addCleanup(setattr, organization_ledger, "append", original)
        with self.assertRaises(organization_ledger.OrgLedgerAppendRefused):
            self.consume()
        self.assertEqual(len(self.by_class(self.k.CROSSING_CONSUMED_CLASS)), 1)
        self.assertEqual(len(self.sv.receipts("org")), 1)  # the genesis only
        self.assertEqual(self.answers(), [])
        consumed, = self.consume()
        self.assertEqual(len(self.by_class(self.k.CROSSING_CONSUMED_CLASS)), 1)
        self.assertEqual(len(self.sv.receipts("org")), 2)
        self.assertEqual(len(self.answers()), 1)
        self.assertIsNotNone(consumed["organization_record"])

    def test_consume_addressed_frames_and_ingest_frame_hold_the_same_custody(self):
        sent = self.monitor()
        with self.assertRaisesRegex(ValueError, "ledger_location_required_from_materializer"):
            self.k.consume_addressed_frames(REPO, mesh_root=self.mesh)
        with self.assertRaisesRegex(ValueError, "ledger_location_required_from_materializer"):
            self.k.ingest_frame(REPO, sent["frame"])
        consumed, = self.k.consume_addressed_frames(REPO, mesh_root=self.mesh, **self.sv.ledgers())
        direct = self.k.ingest_frame(REPO, sent["frame"], **self.sv.ledgers())
        self.assertEqual(consumed["organization_record"], direct["organization_record"])
        self.assertEqual(len(self.by_class(self.k.CROSSING_CONSUMED_CLASS)), 1)

    def test_a_work_request_needs_supplied_node_state(self):
        self.send("sv-llm.org-control", {"message_class": "ecosystem.work.request", "communication_id": "w1",
                                         "subject": "s", "body": {}}, packet_id="parity-work-1")
        # A custody refusal: nothing to retain the intake in, so the pass refuses
        # before any receipt and the frame stays in the mesh.
        with self.assertRaisesRegex(ValueError, "node_state_location_required_from_materializer"):
            self.k.consume_addressed_frames(REPO, mesh_root=self.mesh, **self.sv.ledgers())
        self.assertEqual(self.by_class(self.k.CROSSING_CONSUMED_CLASS) + self.by_class(self.k.CROSSING_REFUSED_CLASS), [])
        consumed, = self.consume()
        self.assertEqual(consumed["result"]["status"], "CONSUMED")
        intake, = (self.sv.node_state / "control/inbox").glob("*.json")
        self.assertEqual(json.loads(intake.read_text())["state"], "QUEUED_FOR_LOCAL_ADMISSION_EVALUATION")


class RefusedCrossingsAreRecorded(SVLLMNode):
    """Item 2: a refusal is DENY (recorded, marked) or FAIL_CLOSED (recorded, retried), never thrown."""

    def offered(self):
        seen = self.k.federation_seen_frame_names(REPO, store=self.k.addressed_node_state_store(self.sv.node_state))
        return self.k.scan_addressed_frames("SV-LLM", root=self.mesh, seen=seen)

    def test_an_unknown_service_is_deny_recorded_and_does_not_stop_the_frames_behind_it(self):
        self.send("sv-llm.not-registered", {"x": 1}, packet_id="parity-0-unknown")
        self.monitor("parity-1-ok")
        results = self.consume()
        statuses = sorted((r["result"].get("packet_id") or r["result"]["packet"]["packet_id"], r["result"]["status"])
                          for r in results)
        self.assertEqual(statuses, [("parity-0-unknown", "REFUSED"), ("parity-1-ok", "CONSUMED")])
        refused = next(r for r in results if r["result"]["status"] == "REFUSED")
        self.assertEqual((refused["result"]["disposition"], refused["result"]["failed_predicate"]), ("DENY", "unknown_service"))
        self.assertIsNotNone(refused["seen_marker"])
        recorded, = self.by_class(self.k.CROSSING_REFUSED_CLASS)
        self.assertEqual(recorded["evidence"]["disposition"], "DENY")
        self.assertIsNone(recorded["evidence"]["retry_entrypoint"])
        self.assertEqual(self.offered(), [])

    def test_a_standing_refusal_is_deny(self):
        broken = dict(GENESIS)
        del broken["predecessor"]
        self.send("sv-llm.org-control", {"message_class": "ecosystem.communication", "communication_id": "r1"},
                  packet_id="parity-standing", standing=broken)
        refused, = self.consume()
        self.assertEqual(refused["result"]["disposition"], "DENY")
        self.assertIn("node_standing_refused", refused["result"]["failed_predicate"])
        self.assertIsNone(refused["response_publication"])

    def test_a_transient_failure_is_fail_closed_retried_recorded_once_then_admitted_as_a_second_transition(self):
        self.monitor("parity-transient")
        with mock.patch.object(self.k, "resident_status", side_effect=ValueError("status_source_unavailable")):
            first, = self.consume()
            second, = self.consume()
        self.assertEqual((first["result"]["disposition"], first["seen_marker"]), ("FAIL_CLOSED", None))
        self.assertEqual(first["organization_record"], second["organization_record"])
        refused, = self.by_class(self.k.CROSSING_REFUSED_CLASS)
        self.assertEqual(refused["evidence"]["retry_entrypoint"], "org-kernel/kernel.py::consume_and_respond")
        self.assertEqual(self.answers(), [])
        admitted, = self.consume()
        self.assertEqual(admitted["result"]["status"], "CONSUMED")
        self.assertEqual(len(self.by_class(self.k.CROSSING_CONSUMED_CLASS)), 1)
        self.assertEqual(len(self.sv.receipts("org")), 3)  # genesis, refusal, admission
        self.assertEqual(self.offered(), [])


class EmissionsAreRecordedOrRefused(SVLLMNode):
    """Items 2 and 3: publish_packet(epoch=) is reproducible and recorded; primitives refuse without custody."""

    def packet(self):
        return self.k.build_packet(origin_org="SV-LLM", origin_service="sv-llm.org-control", destination_org="Origin-Org",
                                   destination_service="origin-org.org-control", payload={"probe": 1},
                                   standing=GENESIS, packet_id="parity-emit-1")

    def test_publishing_at_a_supplied_epoch_is_reproducible_and_recorded_once(self):
        custody = self.k.crossing_custody(REPO, **self.sv.ledgers())
        first = self.k.publish_packet(self.packet(), root=self.mesh, epoch=700, custody=custody)
        again = self.k.publish_packet(self.packet(), root=self.mesh, epoch=700, custody=custody)
        self.assertEqual(first["frame"], again["frame"])
        self.assertEqual(first["organization_record"], again["organization_record"])
        self.assertEqual(first["frame"]["heartbeat_reference"]["epoch"], 700)
        emitted, = self.by_class(self.k.CROSSING_EMITTED_CLASS)
        self.assertEqual(emitted["evidence"]["frame_sha256"], first["frame"]["frame_sha256"])
        self.assertEqual(len(self.answers()), 1)

    def test_every_formerly_exempt_entrypoint_refuses_without_the_ledgers(self):
        sent = self.monitor()
        calls = {
            "publish_packet": lambda: self.k.publish_packet(self.packet(), root=self.mesh, epoch=700),
            "publish_ecosystem_message": lambda: self.k.publish_ecosystem_message(
                origin_org="SV-LLM", origin_service="sv-llm.org-control", organizations=["Origin-Org"],
                standing=GENESIS, message_class="ecosystem.communication", subject="s", body={}, root=self.mesh, epoch=700),
            "publish_ecosystem_from_directory": lambda: self.k.publish_ecosystem_from_directory(
                REPO, standing=GENESIS, message_class="ecosystem.communication", subject="s", body={},
                mesh_root=self.mesh, epoch=700),
            "ingest_frame": lambda: self.k.ingest_frame(REPO, sent["frame"]),
            "consume_addressed_frames": lambda: self.k.consume_addressed_frames(REPO, mesh_root=self.mesh),
            "consume_and_respond": lambda: self.k.consume_and_respond(REPO, mesh_root=self.mesh,
                                                                      node_state_root=self.sv.node_state),
        }
        before = sorted(p.name for p in (self.mesh / "frames.d").glob("*.json"))
        for name, call in calls.items():
            with self.subTest(entrypoint=name):
                with self.assertRaisesRegex(ValueError, "ledger_location_required_from_materializer|"
                                                        "crossing_custody_required_from_recording_operation"):
                    call()
        self.assertEqual(sorted(p.name for p in (self.mesh / "frames.d").glob("*.json")), before)
        self.assertEqual(len(self.sv.receipts("repo")), 1)  # the genesis only

    def test_the_exempt_primitives_refuse_without_custody(self):
        frame = self.k.carrier_frame(self.packet(), epoch=700)
        for name, call in {
                "carry_packet": lambda: self.k.carry_packet(self.packet(), custody=None, root=self.mesh, epoch=700),
                "publish_frame": lambda: self.k.publish_frame(frame, root=self.mesh),
                "dispatch": lambda: self.k.dispatch(REPO, self.packet()),
                "forged_custody": lambda: self.k.carry_packet(self.packet(), custody={"schema": "x"}, root=self.mesh)}.items():
            with self.subTest(primitive=name):
                with self.assertRaisesRegex(ValueError, "crossing_custody_required_from_recording_operation"):
                    call()
        self.assertFalse(self.mesh.exists())

    def test_the_exemption_register_names_only_the_enforced_primitives_with_every_field(self):
        register = json.loads((REPO / "data/organization-role-exemption-register.json").read_text())
        exemption, = register["exemptions"]
        for field in register["required_fields"]:
            self.assertTrue(exemption.get(field), field)
        self.assertEqual(exemption["disposition"], "DENY_DIRECT_USE_WITHOUT_CROSSING_CUSTODY")
        self.assertIs(exemption["exemption_grants_authority"], False)
        for primitive in ("carry_packet", "publish_frame", "dispatch"):
            self.assertIn(primitive, exemption["surface"])
        self.assertIn("no longer exempt", exemption["surface"])

    def test_the_master_records_release_needs_a_mesh_and_publishes_one_frame_per_released_batch(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("STEGVERSE_")}
        env.update(STEGVERSE_REPO_LEDGER_ROOT=str(self.sv.repo_ledger), STEGVERSE_ORG_LEDGER_ROOT=str(self.sv.org_ledger),
                   PYTHONDONTWRITEBYTECODE="1")
        receipt = self.sv.receipts("org")[0]
        (self.base / "receipt.json").write_text(json.dumps(receipt))
        (self.base / "standing.json").write_text(json.dumps(GENESIS))
        command = [sys.executable, "-B", str(REPO / "resident-runtime/submit_org_transition_to_master_records.py"),
                   "--org-receipt", str(self.base / "receipt.json"),
                   "--predecessor-ecosystem-state-sha256", "sha256:" + "0" * 64,
                   "--successor-ecosystem-state-sha256", "sha256:" + "1" * 64,
                   "--standing", str(self.base / "standing.json")]
        missing = subprocess.run(command, capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--mesh-root", missing.stderr)
        outputs = [json.loads(subprocess.run(command + ["--mesh-root", str(self.mesh)], capture_output=True, text=True,
                                             env=env, timeout=120, check=True).stdout) for _ in range(2)]
        self.assertEqual(outputs[0]["frame_sha256"], outputs[1]["frame_sha256"])
        frame, = [json.loads(p.read_text()) for p in (self.mesh / "frames.d").glob("*.json")]
        self.assertEqual(frame["heartbeat_reference"]["epoch"], receipt["hb_reference"]["epoch"])
        self.assertEqual(len(self.by_class(self.k.CROSSING_EMITTED_CLASS)), 1)


class IngressMaterializesInNodeState(unittest.TestCase):
    """Item 4: materialization is one put_once in supplied node state, never under the checkout."""

    def setUp(self):
        self.base = scratch(self)
        self.c = load("crossing_parity_materialize", REPO / "org-runtime/crossing.py")
        self.node = self.c.kernel.addressed_node_state_store(self.base / "node")

    def test_a_materialization_is_written_once_by_key(self):
        packet = {"packet_id": "parity-materialize-1", "payload": {"manifest": {"manifest_id": "m"}}}
        path, record = self.c._materialize(self.node, "sandbox", packet)
        self.assertTrue(Path(path).is_relative_to((self.base / "node").resolve()))
        self.assertEqual(json.loads(Path(path).read_text()), record)
        self.assertEqual(self.c._materialize(self.node, "sandbox", packet)[0], path)
        with self.assertRaises(self.c.Refused) as refused:
            self.c._materialize(self.node, "sandbox", {**packet, "payload": {"other": 1}})
        self.assertEqual(refused.exception.failed_predicate, "MATERIALIZATION_WRITE_ONCE_COLLISION")
        self.assertFalse((REPO / "resident-runtime/materialized").exists())

    def test_the_unreferenced_transport_is_gone(self):
        self.assertFalse((REPO / "org-boundary/runtime/intr_transport.py").exists())
        here = Path(__file__).resolve()
        # SV-LLM's own trees only: CI checks out the StegVerse-org reference
        # beside them, and that organization's files are not SV-LLM's references.
        own = (".github", ".stegverse", "data", "docs", "org-boundary", "org-kernel", "org-runtime", "resident-runtime")
        referencing = [str(p.relative_to(REPO)) for top in own for pattern in ("*.py", "*.json", "*.yml")
                       for p in (REPO / top).rglob(pattern)
                       if p.resolve() != here and "intr_transport" in p.read_text(errors="ignore")]
        self.assertEqual(referencing, [])


if __name__ == "__main__":
    unittest.main()
