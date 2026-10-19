"""``intr-destination`` is a universal ingress capability, not a purpose route.

SV-LLM advertises it. A peer address is derived as
``organization_slug + "." + "intr-destination"``. A purpose-neutral diagnostic
can be emitted and closed. Peer installation is not proven at resolution.
Closure, when a fabricated far side answers, shows that a boundary ran this
packet. It does not show which organization that boundary belongs to. No
answer stays ``PENDING`` and writes nothing.

Authority and time are constraint variables. A disposition is transition
evidence only. Both ledger roots and the mesh are redirected. Nothing here is
an authentic production receipt or a live peer installation.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROFILE_ID = "intr-destination"
PROFILE_NAME = "InTr:Destination"
OPERATION = "DIAGNOSTIC_CROSSING"
OPERATION_ID = "ORGANIZATION_INTR_DESTINATION_INGRESS"
ADDRESS = "sv-llm." + PROFILE_ID
PAYLOAD_SCHEMA = "stegverse.org-intr-destination-diagnostic/v1"
THIS = "SV-LLM"
PEER = "StegVerse-org"
CONSTRAINT = "CONSTRAINT_VARIABLE"
DISPOSITION_ROLE = "TRANSITION_EVIDENCE_ONLY"
CONSTRAINT_FIELDS = (
    "routing_authority_constraint",
    "admission_authority_constraint",
    "execution_authority_constraint",
    "time_constraint",
)
STANDING = {"mode": "ESTABLISH_GENESIS", "node_ref": "intr-destination-test", "predecessor": None}


def _module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("kernel", "org-kernel/kernel.py")
capability = _module("capability_ingress", "org-boundary/runtime/capability_ingress.py")
egress = _module("organization_egress_boundary",
                 "resident-runtime/organization_egress_boundary.py")
ingress = _module("intr_destination_ingress", "resident-runtime/intr_destination_ingress.py")
runtime_boundary = _module("runtime_boundary", "org-runtime/runtime_boundary.py")
crossing = _module("crossing", "org-runtime/crossing.py")

REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text(encoding="utf-8"))
BOUNDARY = json.loads((ROOT / "org-runtime/interlock-intr.json").read_text(encoding="utf-8"))
FEDERATION = json.loads((ROOT / "org-boundary/registry/federation.json").read_text(encoding="utf-8"))


def binding(profile_id, document=None):
    matches = [entry for entry in (document or BOUNDARY)["ingress"]["capability_endpoint_bindings"]
               if entry.get("profile_id") == profile_id]
    if len(matches) != 1:
        raise AssertionError(profile_id)
    return matches[0]


def row(service_id):
    return next(item for item in REGISTRY["services"] if item["service_id"] == service_id)


def diagnostic(communication_id="intr-destination-diagnostic-001", schema=PAYLOAD_SCHEMA):
    return {
        "message_class": "ecosystem.communication",
        "communication_id": communication_id,
        "subject": "purpose-neutral mesh diagnostic",
        "body": {"schema": schema, "probe": "diagnostic-crossing"},
    }


def assert_constraints(test, record):
    for name in CONSTRAINT_FIELDS:
        test.assertEqual(record[name], CONSTRAINT, name)
    test.assertEqual(record["disposition_role"], DISPOSITION_ROLE)


class DeclarationTests(unittest.TestCase):
    def test_the_overlay_advertises_the_capability_and_sets_no_constraint(self):
        declared = binding(PROFILE_ID)
        self.assertEqual(declared["profile_name"], PROFILE_NAME)
        self.assertEqual(declared["operation"], OPERATION)
        self.assertEqual(declared["payload_schema"], PAYLOAD_SCHEMA)
        self.assertEqual(declared["submission_reader"], capability.COMMUNICATION_READER)
        self.assertEqual(declared["authority_effect"], "NONE_BINDING_ONLY")
        self.assertIs(declared["environment_selected_ingress"], False)
        assert_constraints(self, declared)
        receiving = declared["receiving_operation"]
        self.assertEqual(receiving["operation_id"], OPERATION_ID)
        self.assertEqual(receiving["addressed_service"], ADDRESS)
        self.assertEqual(receiving["addressed_service_boundary_role"], capability.ROLE)
        self.assertIs(receiving["selects_processing_at_the_capability_address"], False)
        self.assertIs(receiving["host_required"], False)
        self.assertIs(receiving["environment_url_required"], False)
        assert_constraints(self, receiving)
        self.assertTrue((ROOT / receiving["operation"]).is_file())

    def test_the_registry_row_is_an_address_and_not_an_admission(self):
        served = row(ADDRESS)
        self.assertEqual(served["boundary_role"], "BOUNDARY_LOCAL_CAPABILITY_INGRESS")
        self.assertEqual(served["capability_profile_id"], PROFILE_ID)
        self.assertEqual(served["admission_authority_constraint"], CONSTRAINT)
        self.assertEqual(served["time_constraint"], CONSTRAINT)
        self.assertEqual(served["disposition_role"], DISPOSITION_ROLE)
        self.assertIs(served["selects_processing_at_this_address"], False)
        self.assertNotIn("endpoint_adapter", served)
        self.assertNotIn("admits_processing", served)
        self.assertIn("ecosystem.communication", served["accepts"])
        self.assertIn(PAYLOAD_SCHEMA, served["accepts"])

    def test_the_served_address_is_named_and_no_peer_address_is(self):
        proven = BOUNDARY["egress"]["peer_capability_resolution"]["proven_on_this_organization"]
        served = {entry["receiving_operation"]["addressed_service"]
                  for entry in BOUNDARY["ingress"]["capability_endpoint_bindings"]}
        # This capability and sdk-manifest-ingress, adopted for the
        # manifest-directed append path (SV-LLM/.github#30 W4).
        self.assertEqual(served, {ADDRESS, "sv-llm.sdk-manifest-ingress"})
        self.assertEqual(set(proven), served)
        self.assertNotIn("stegverse-org.intr-destination", proven)
        report = runtime_boundary.validate()
        self.assertIs(report["valid"], True, report["checks"])
        self.assertIs(report["checks"]["capability_addresses_resolve"], True)
        self.assertIs(report["checks"]["peer_capability_addresses_derive"], True)

    def test_naming_a_proper_subset_of_served_addresses_is_refused(self):
        document = json.loads(json.dumps(BOUNDARY))
        extra = json.loads(json.dumps(binding(PROFILE_ID)))
        extra["profile_id"] = "sdk-manifest-ingress"
        extra["receiving_operation"] = dict(extra["receiving_operation"])
        extra["receiving_operation"]["addressed_service"] = "sv-llm.sdk-manifest-ingress"
        document["ingress"]["capability_endpoint_bindings"].append(extra)
        document["egress"]["peer_capability_resolution"]["proven_on_this_organization"] = ADDRESS
        self.assertIs(runtime_boundary.peer_capability_addresses_derive(document), False)

    def test_a_peer_address_in_the_proven_field_is_refused(self):
        document = json.loads(json.dumps(BOUNDARY))
        document["egress"]["peer_capability_resolution"]["proven_on_this_organization"] = [
            ADDRESS, "stegverse-org.intr-destination"]
        self.assertIs(runtime_boundary.peer_capability_addresses_derive(document), False)

    def test_a_single_served_address_may_still_be_named_as_a_string(self):
        document = json.loads(json.dumps(BOUNDARY))
        document["ingress"]["capability_endpoint_bindings"] = [binding(PROFILE_ID)]
        document["egress"]["peer_capability_resolution"]["proven_on_this_organization"] = ADDRESS
        self.assertIs(runtime_boundary.peer_capability_addresses_derive(document), True)
        self.assertIs(runtime_boundary.peer_capability_addresses_derive(BOUNDARY), True)

    def test_peer_services_are_not_written_into_the_federation_directory(self):
        for entry in FEDERATION["organizations"]:
            for key in ("org_control_service", "addressed_service"):
                self.assertNotIn(PROFILE_ID, str(entry.get(key) or ""))

    def test_no_governance_or_remediation_destination_binding_was_added(self):
        self.assertNotIn("capability_destination_bindings", BOUNDARY["egress"])


class OverlayAuthorityTests(unittest.TestCase):
    def test_resolution_names_the_overlay_and_the_bound_operation(self):
        resolved = capability.resolve(ROOT, row(ADDRESS))
        self.assertEqual(resolved["resolution_source"], "ORGANIZATION_CAPABILITY_OVERLAY")
        self.assertIs(resolved["resolved_from_the_addressed_row_alone"], False)
        self.assertEqual(resolved["receiving_operation_id"], OPERATION_ID)
        self.assertEqual(resolved["capability_operation"], OPERATION)
        self.assertEqual(ingress.OPERATION_ID, OPERATION_ID)

    def test_a_row_the_overlay_does_not_name_resolves_nothing(self):
        with self.assertRaises(SystemExit) as refused:
            capability.resolve(ROOT, {"service_id": "sv-llm.not-bound-anywhere"})
        self.assertIn("ADDRESS_SERVES_A_CAPABILITY_THE_OVERLAY_BINDS_HERE",
                      str(refused.exception))

    def test_a_module_that_is_not_the_bound_operation_is_refused(self):
        resolved = dict(capability.resolve(ROOT, row(ADDRESS)))
        resolved["receiving_operation_path"] = ROOT / "resident-runtime/organization_egress_boundary.py"
        with self.assertRaises(SystemExit) as refused:
            capability.load_operation(resolved)
        self.assertIn("MODULE_IDENTIFIES_ITSELF_AS_THE_BOUND_OPERATION",
                      str(refused.exception))

    def test_an_operation_outside_this_organization_is_refused(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "org-runtime").mkdir(parents=True)
        document = json.loads(json.dumps(BOUNDARY))
        receiving = binding(PROFILE_ID, document)["receiving_operation"]
        receiving["operation"] = "../outside.py"
        (root / "org-runtime/interlock-intr.json").write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(SystemExit) as refused:
            capability.resolve(root, row(ADDRESS))
        self.assertIn("RECEIVING_OPERATION_IS_OWNED_INSIDE_THIS_ORGANIZATION",
                      str(refused.exception))

    def test_the_readers_do_not_cross(self):
        manifest_binding = {"operation": "SUBMIT_MANIFEST"}
        with self.assertRaises(SystemExit) as manifest_refused:
            capability.submission_for(manifest_binding, diagnostic())
        self.assertIn("SUBMISSION_CARRIES_A_MANIFEST", str(manifest_refused.exception))
        with self.assertRaises(SystemExit) as diagnostic_refused:
            capability.submission_for(binding(PROFILE_ID), {"manifest": {"probe": True}})
        self.assertIn("SUBMISSION_DECLARES_A_RESPONDED_REQUEST_CLASS",
                      str(diagnostic_refused.exception))

    def test_a_diagnostic_body_under_another_schema_is_refused(self):
        with self.assertRaises(SystemExit) as refused:
            capability.submission_for(
                binding(PROFILE_ID), diagnostic(schema="stegverse.org-governance-decision/v1"))
        self.assertIn("SUBMISSION_BODY_DECLARES_THE_BOUND_PAYLOAD_SCHEMA", str(refused.exception))


class RedirectedLedgers(unittest.TestCase):
    LEDGER_ROOTS = ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")

    def setUp(self):
        self._work = tempfile.TemporaryDirectory()
        self.addCleanup(self._work.cleanup)
        previous = {name: os.environ.get(name) for name in self.LEDGER_ROOTS}
        for name in self.LEDGER_ROOTS:
            os.environ[name] = str(Path(self._work.name) / name.lower())
        self.mesh = Path(self._work.name) / "mesh"

        def restore():
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)

    def receipts(self, variable, schema, transition_class=None):
        found = []
        root = Path(os.environ[variable])
        if not root.exists():
            return found
        for path in root.rglob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("schema") != schema:
                continue
            if transition_class is not None and record.get("transition_class") != transition_class:
                continue
            found.append(record)
        return found


class OperationReceiptTests(RedirectedLedgers):
    def test_a_diagnostic_is_acknowledged_at_both_ledger_levels(self):
        result = ingress.receive(diagnostic(), registry=REGISTRY, packet_id="direct-diagnostic",
                                 hb_epoch=32)
        self.assertEqual(result["disposition"], "ALLOW", result.get("detail"))
        self.assertIs(result["received"], True)
        self.assertIs(result["communication_acknowledged"], True)
        self.assertIs(result["repository_receipt_observed"], True)
        self.assertIs(result["organization_receipt_observed"], True)
        self.assertIs(result["organization_receipt_preserves_repository_receipt"], True)
        self.assertEqual(result["authority_effect"], "NONE_DIAGNOSTIC_ACK_ONLY")
        assert_constraints(self, result)
        for flag in ("selects_processing", "purpose_specific_route", "standing_rechecked_here"):
            self.assertIs(result[flag], False, flag)
        repository, = self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                    "stegverse.repo-transition-receipt/v1", OPERATION_ID)
        self.assertEqual(repository["evidence"]["profile_id"], PROFILE_ID)
        self.assertEqual(repository["evidence"]["receiving_operation"], OPERATION_ID)
        assert_constraints(self, repository["evidence"])
        organization, = self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                      "stegverse.organization-transition-receipt/v1")
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])

    def test_a_replay_of_the_same_diagnostic_does_not_mint_a_second_pair(self):
        first = ingress.receive(diagnostic(), registry=REGISTRY, packet_id="replayed-diagnostic",
                                hb_epoch=32)
        second = ingress.receive(diagnostic(), registry=REGISTRY, packet_id="replayed-diagnostic",
                                 hb_epoch=32)
        self.assertIs(second["transition_replayed"], True)
        self.assertEqual(first["repository_receipt_sha256"], second["repository_receipt_sha256"])
        self.assertEqual(len(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                           "stegverse.repo-transition-receipt/v1", OPERATION_ID)), 1)

    def test_a_payload_that_is_not_the_diagnostic_is_refused_and_recorded(self):
        result = ingress.receive(
            {"message_class": "ecosystem.work.request", "communication_id": "not-a-diagnostic",
             "body": {"schema": "stegverse.org-governance-decision-request/v1"}},
            registry=REGISTRY, packet_id="refused-diagnostic", hb_epoch=32)
        self.assertEqual(result["disposition"], "DENY")
        self.assertIs(result["communication_acknowledged"], False)
        self.assertIs(result["refusal_recorded"], True)
        self.assertEqual(result["failed_predicate"], "SUBMISSION_DECLARES_A_RESPONDED_REQUEST_CLASS")
        self.assertEqual(result["authority_effect"], "NONE_REFUSAL_ONLY")
        assert_constraints(self, result)
        self.assertEqual(len(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1",
            ingress.REFUSED_CLASS)), 1)
        self.assertEqual(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1", OPERATION_ID), [])


class AddressedAndClosedTests(RedirectedLedgers):
    def setUp(self):
        super().setUp()
        # This kernel's custody requires a declared organization-ledger genesis.
        # The mesh and both ledgers stay in the temporary roots.
        crossing.open_organization_ledger(hb_epoch=32)

    def publish(self, payload, service, packet_id, origin=PEER):
        packet = kernel.build_packet(
            origin_org=origin,
            origin_service=kernel.organization_slug(origin) + "." + PROFILE_ID,
            destination_org=THIS, destination_service=service,
            payload=payload, standing=STANDING,
            transition_reference="intr:transition:" + packet_id,
            authority_effect="NONE", packet_id=packet_id)
        # Place the frame. This kernel's publish_packet would also record an
        # emission; the far side here is fabricated, so only the frame is written.
        frame = kernel.carrier_frame(packet, epoch=32)
        kernel._publish_frame(frame, root=self.mesh)
        return packet

    def consume(self):
        return kernel.consume_addressed_frames(
            ROOT, mesh_root=self.mesh,
            repo_ledger_root=os.environ["STEGVERSE_REPO_LEDGER_ROOT"],
            org_ledger_root=os.environ["STEGVERSE_ORG_LEDGER_ROOT"])

    def frames_to(self, organization):
        directory = self.mesh / "frames.d"
        if not directory.is_dir():
            return []
        frames = []
        for path in directory.glob("*.json"):
            frame = json.loads(path.read_text(encoding="utf-8"))
            if frame.get("destination_org") == organization:
                frames.append(frame)
        return frames

    def test_a_peer_frame_at_the_address_is_received_and_receipted(self):
        self.publish(diagnostic("addressed-diagnostic"), ADDRESS, "addressed-diagnostic")
        results = self.consume()
        self.assertEqual(len(results), 1)
        execution = results[0]["result"]["execution_result"]
        self.assertEqual(results[0]["result"]["status"], "CONSUMED")
        self.assertEqual(results[0]["result"]["packet"]["origin"]["org"], PEER)
        self.assertEqual(execution["service_id"], ADDRESS)
        self.assertEqual(execution["processing_selection"], "BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED")
        application = execution["application_result"]
        self.assertIs(application["capability_received"], True)
        self.assertEqual(application["capability_profile_id"], PROFILE_ID)
        self.assertEqual(application["receiving_operation_id"], OPERATION_ID)
        self.assertIs(application["declared_capability_processed_at_this_address"], False)
        operation = application["receiving_operation_result"]
        self.assertEqual(operation["disposition"], "ALLOW", operation.get("detail"))
        self.assertIs(operation["communication_acknowledged"], True)
        self.assertEqual(operation["authority_effect"], "NONE_DIAGNOSTIC_ACK_ONLY")
        assert_constraints(self, operation)
        self.assertIs(operation["organization_receipt_preserves_repository_receipt"], True)
        repository, = self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                    "stegverse.repo-transition-receipt/v1", OPERATION_ID)
        # The receipt carries the consumed frame's epoch, not a clock reading.
        self.assertEqual(repository["hb_reference"]["epoch"], 32)
        self.assertIs(repository["hb_reference"]["derived_from_clock"], False)
        matched = [record for record in self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
            if record.get("repo_receipt_sha256") == repository["receipt_sha256"]]
        self.assertEqual(len(matched), 1)

    def test_a_manifest_addressed_to_this_capability_is_not_a_diagnostic(self):
        self.publish({"manifest": {"probe": True}}, ADDRESS, "not-a-diagnostic")
        # One frame's failure no longer stops the pass (B-P36o): it is returned
        # as a six-field refusal (no node state here to hold a quarantine marker),
        # and nothing is recorded.
        rows = self.consume()
        refused, = [row["result"] for row in rows if row["result"].get("status") == "REFUSED"]
        self.assertEqual(refused["failure_code"], "FRAME_INGEST_FAILED")
        self.assertIn("SUBMISSION_DECLARES_A_RESPONDED_REQUEST_CLASS", refused["detail"])
        self.assertEqual(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1", OPERATION_ID), [])

    def test_outbound_resolution_derives_the_peer_address_and_does_not_prove_it_serves(self):
        resolved = egress.resolve_destination(PEER, capability=PROFILE_ID)
        self.assertEqual(resolved["destination_service"],
                         kernel.organization_slug(PEER) + "." + PROFILE_ID)
        self.assertEqual(resolved["destination_service"], "stegverse-org.intr-destination")
        self.assertNotEqual(resolved["destination_service"],
                            resolved["destination_org_control_service"])
        self.assertIs(resolved["peer_serves_this_capability_is_proven_here"], False)
        self.assertIs(resolved["destination_capability_declared_by_the_peer_directory"], False)
        self.assertEqual(egress.peer_capability_service(THIS, PROFILE_ID), ADDRESS)

    def test_an_undeclared_capability_is_still_refused(self):
        with self.assertRaises(egress.EgressRefused) as refused:
            egress.resolve_destination(PEER, capability="not-a-declared-capability")
        self.assertEqual(refused.exception.failed_predicate,
                         "CAPABILITY_IS_DECLARED_IN_THIS_ORGANIZATIONS_OVERLAY")

    def test_an_undeclared_peer_is_still_refused(self):
        with self.assertRaises(egress.EgressRefused) as refused:
            egress.resolve_destination("Not-A-Declared-Peer", capability=PROFILE_ID)
        self.assertEqual(refused.exception.failed_predicate,
                         "DESTINATION_IS_A_DECLARED_PEER_OF_THIS_ORGANIZATION")

    def answer(self, packet):
        """Answer as a boundary does: the kernel's own receipt chain and control response.

        The chain is fabricated in this temporary mesh. It is not an authentic
        receipt and not a live peer installation.
        """
        chain, previous = [], None
        for kind in egress.FAR_SIDE_RECEIPT_KINDS:
            receipt = kernel.receipt(kind, packet["packet_id"], packet["destination"]["service"],
                                     previous, {"payload_hash": kernel.sha(packet["payload"])})
            chain.append(receipt["receipt_id"])
            previous = receipt["receipt_id"]
        response = kernel.build_control_response(
            packet, {"application_result": {
                "schema": ingress.RESULT_SCHEMA, "disposition": "ALLOW",
                "authority_effect": "NONE_DIAGNOSTIC_ACK_ONLY"},
                "reconstruction": {"terminal_receipt_id": chain[-1]}})
        frame = kernel.carrier_frame(response, epoch=34)
        kernel._publish_frame(frame, root=self.mesh)
        return chain[-1]

    def test_a_diagnostic_crossing_closes_only_when_the_far_side_answers(self):
        emitted = egress.emit(PEER, diagnostic("closable-diagnostic"), standing=STANDING,
                              capability=PROFILE_ID, mesh_root=self.mesh, hb_epoch=32)
        self.assertEqual(emitted["disposition"], "ALLOW", emitted.get("detail"))
        self.assertIs(emitted["emitted"], True)
        self.assertEqual(emitted["destination_service"], "stegverse-org.intr-destination")
        self.assertIs(emitted["peer_serves_this_capability_is_proven_here"], False)
        self.assertEqual(emitted["emission_record"]["far_side_service_id"],
                         emitted["destination_service"])
        pending = egress.close(PEER, emitted["packet_id"], "closable-diagnostic",
                               mesh_root=self.mesh, hb_epoch=33)
        self.assertEqual(pending["disposition"], "PENDING")
        self.assertIs(pending["closed"], False)
        self.assertIs(pending["closure_recorded"], False)
        self.assertIs(pending["absence_is_not_a_transition"], True)
        self.assertEqual(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                       "stegverse.repo-transition-receipt/v1",
                                       egress.CLOSED_CLASS), [])

        frame, = self.frames_to(PEER)
        packet = kernel.recover_packet(frame)
        self.assertEqual(packet["destination"]["service"], "stegverse-org.intr-destination")
        self.assertEqual(packet["payload"]["message_class"], "ecosystem.communication")
        self.assertEqual(packet["payload"]["communication_id"], "closable-diagnostic")
        terminal = self.answer(packet)
        closed = egress.close(PEER, emitted["packet_id"], "closable-diagnostic",
                              mesh_root=self.mesh, hb_epoch=34)
        self.assertEqual(closed["disposition"], "ALLOW", closed.get("closure_findings"))
        self.assertIs(closed["closed"], True)
        self.assertEqual(closed["far_side_terminal_receipt"], terminal)
        self.assertEqual(closed["communication_id"], "closable-diagnostic")
        self.assertEqual(closed["closure_record"]["response_message_class"],
                         "ecosystem.communication.ack")
        # Closure shows a boundary ran this packet. It does not show which
        # organization that boundary belongs to, and resolution did not claim
        # the peer serves the capability.
        self.assertIs(closed["closure_record"]["reconstruction_proves_the_boundary_ran_this_packet"], True)
        self.assertIs(closed["closure_record"]["reconstruction_proves_who_the_far_side_is"], False)
        self.assertIs(emitted["peer_serves_this_capability_is_proven_here"], False)
        self.assertEqual(len(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                           "stegverse.repo-transition-receipt/v1",
                                           egress.CLOSED_CLASS)), 1)
        self.assertTrue(self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                      "stegverse.organization-transition-receipt/v1"))


class DiagnosticSelfClosureTests(RedirectedLedgers):
    """A self-closure records both receipts on supplied temporary ledgers.

    Nothing in this class is an authentic production receipt, and nothing here
    is a live peer. The temporary chain only shows that the closure appends
    and that a readback can see ``communication_id``.
    """

    def test_a_self_closure_records_communication_id_on_both_receipts(self):
        before = (ROOT / "org-boundary/registry/federation.json").read_bytes()
        result = ingress.closure(
            "self-close-comm-001", registry=REGISTRY, packet_id="self-close-packet-001",
            hb_epoch=32)
        self.assertEqual((ROOT / "org-boundary/registry/federation.json").read_bytes(), before)
        self.assertEqual(result["schema"], ingress.CLOSURE_SCHEMA)
        self.assertEqual(result["disposition"], "ALLOW", result.get("detail"))
        self.assertIs(result["self_closure"], True)
        self.assertIs(result["peer_enumerated"], False)
        self.assertEqual(result["addressed_service"], ADDRESS)
        self.assertEqual(result["communication_id"], "self-close-comm-001")
        self.assertIs(result["communication_acknowledged"], True)
        assert_constraints(self, result)
        repository, = self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1", OPERATION_ID)
        self.assertEqual(repository["evidence"]["communication_id"], "self-close-comm-001")
        matched = [record for record in self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1")
            if record.get("repo_receipt_sha256") == repository["receipt_sha256"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["boundary_evidence"]["communication_id"], "self-close-comm-001")

    def test_a_replay_of_the_same_self_closure_does_not_mint_a_second_pair(self):
        first = ingress.closure(
            "self-close-replay", registry=REGISTRY, packet_id="self-close-replay-packet",
            hb_epoch=32)
        second = ingress.closure(
            "self-close-replay", registry=REGISTRY, packet_id="self-close-replay-packet",
            hb_epoch=99)
        self.assertIs(second["transition_replayed"], True)
        self.assertEqual(first["organization_receipt_sha256"], second["organization_receipt_sha256"])
        self.assertEqual(len(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1", OPERATION_ID)), 1)

    def test_a_blank_communication_id_writes_nothing(self):
        with self.assertRaises(ingress.SelfClosureRefused) as refused:
            ingress.closure(" ", registry=REGISTRY, packet_id="self-close-blank", hb_epoch=32)
        self.assertEqual(refused.exception.failed_predicate, "COMMUNICATION_ID_REQUIRED")
        self.assertEqual(self.receipts(
            "STEGVERSE_REPO_LEDGER_ROOT", "stegverse.repo-transition-receipt/v1"), [])
        self.assertEqual(self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1"), [])

    def test_a_registry_that_does_not_serve_the_address_writes_nothing(self):
        with self.assertRaises(ingress.SelfClosureRefused) as refused:
            ingress.closure(
                "self-close-unserved",
                registry={"organization": "SV-LLM", "services": []},
                packet_id="self-close-unserved", hb_epoch=32)
        self.assertEqual(refused.exception.failed_predicate,
                         "THIS_ORGANIZATION_SERVES_INTR_DESTINATION")
        self.assertEqual(self.receipts(
            "STEGVERSE_ORG_LEDGER_ROOT", "stegverse.organization-transition-receipt/v1"), [])

    def test_self_closure_fast_forwards_an_existing_git_ledger_and_reads_back(self):
        # Supplied temporary git ref. Not the published organization ledger,
        # and not an authentic production receipt.
        repo = Path(self._work.name) / "ledger"
        subprocess.check_call(["git", "init", "-q", str(repo)])
        ref = "refs/stegverse/organization-ledger"
        namespace = "repository-ledger/SV-LLM/.github"
        org_root = "git+" + str(repo) + "#" + ref
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = org_root
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = org_root + ":" + namespace
        first = ingress.closure(
            "git-close-001", registry=REGISTRY, packet_id="git-close-packet-001", hb_epoch=40)
        tip_before = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", ref], text=True).strip()
        count_before = int(subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--count", ref], text=True))
        second = ingress.closure(
            "git-close-002", registry=REGISTRY, packet_id="git-close-packet-002", hb_epoch=41)
        tip_after = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", ref], text=True).strip()
        count_after = int(subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--count", ref], text=True))
        subprocess.check_call(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", tip_before, tip_after])
        self.assertGreater(count_after, count_before)
        self.assertNotEqual(first["organization_receipt_sha256"],
                            second["organization_receipt_sha256"])
        replay = ingress.closure(
            "git-close-002", registry=REGISTRY, packet_id="git-close-packet-002", hb_epoch=77)
        self.assertIs(replay["transition_replayed"], True)
        self.assertEqual(subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", ref], text=True).strip(), tip_after)
        fresh = Path(self._work.name) / "readback.git"
        subprocess.check_call(["git", "init", "-q", "--bare", str(fresh)])
        subprocess.check_call(
            ["git", "--git-dir", str(fresh), "fetch", "-q", str(repo), "+" + ref + ":" + ref])
        verified = ingress.verify_closure(
            "git+" + str(fresh) + "#" + ref, second, repository_namespace=namespace)
        digests = [item["receipt_sha256"] for item in verified["chain"]]
        self.assertIn(first["organization_receipt_sha256"], digests)
        self.assertIn(second["organization_receipt_sha256"], digests)
        self.assertEqual(verified["self_closure_communication_id"], "git-close-002")
        self.assertIs(verified["communication_id_on_organization_receipt"], True)
        self.assertIs(verified["communication_id_on_repository_receipt"], True)
        self.assertIs(verified["self_closure_extends_published_chain"], True)
        self.assertEqual(verified["head_receipt_sha256"], second["organization_receipt_sha256"])
        fresh_tip = subprocess.check_output(
            ["git", "--git-dir", str(fresh), "rev-parse", ref], text=True).strip()
        self.assertEqual(fresh_tip, tip_after)
        subprocess.check_call(
            ["git", "--git-dir", str(fresh), "merge-base", "--is-ancestor", tip_before, fresh_tip])


class SuppliedEpochTests(RedirectedLedgers):
    """A ledger receipt's epoch is supplied by its caller, never read off a clock."""

    SIX_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
                  "retry_entrypoint", "owning_existing_goal", "next_attempt")

    def assertSixFields(self, refusal, failure_code="HB_EPOCH_NOT_SUPPLIED"):
        self.assertEqual(refusal["disposition"], "FAIL_CLOSED")
        self.assertEqual(refusal["failure_code"], failure_code)
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        self.assertEqual(refusal["owning_existing_goal"],
                         "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001")
        for field in self.SIX_FIELDS:
            self.assertTrue(refusal.get(field), field)
        self.assertIs(refusal["derived_from_clock"], False)
        self.assertIs(refusal["consequence_committed"], False)

    def refused_append(self, **epoch):
        """Append with `epoch` against a store and a clock that must not be touched."""
        emit = ingress.repository_ledger

        class Unopenable:
            def __getattr__(self, name):
                raise AssertionError("the store was touched: " + name)

        def clock(*args, **kwargs):
            raise AssertionError("a clock was read")
        with mock.patch.object(emit.kernel, "hb_reference", clock), \
                mock.patch.object(emit.ledger_store, "open_store", clock):
            with self.assertRaises(emit.RepoLedgerEpochRefused) as raised:
                emit.append("T:epoch", "T", "sha256:" + "0" * 64, "sha256:" + "1" * 64,
                            {}, "NONE", store=Unopenable(), **epoch)
        self.assertFalse(Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"]).exists())
        return raised.exception

    def emit_cli(self, *epoch):
        return subprocess.run(
            ["python", str(ROOT / ".stegverse/transition-ledger/emit.py"),
             "--transition-id", "T:epoch", "--transition-class", "T",
             "--predecessor-state-sha256", "sha256:" + "0" * 64,
             "--successor-state-sha256", "sha256:" + "1" * 64, *epoch],
            capture_output=True, text=True, env=dict(os.environ))

    def test_an_append_without_an_epoch_fails_closed_before_the_store_opens(self):
        refused = self.refused_append()
        self.assertIsInstance(refused, ingress.repository_ledger.kernel.SuppliedEpochRefused)
        self.assertSixFields(refused.refusal)

    def test_the_refusal_is_the_kernel_writer_refusal(self):
        emit = ingress.repository_ledger
        self.assertEqual(self.refused_append().refusal, emit.kernel.writer_epoch_refusal(
            None, retry_entrypoint=emit.EPOCH_RETRY_ENTRYPOINT))

    def test_an_append_with_an_invalid_epoch_fails_closed_before_the_store_opens(self):
        for epoch in ("33.0", True, 31, "+33", 33.0, " 33", "3_3"):
            with self.subTest(epoch=epoch):
                self.assertSixFields(self.refused_append(hb_epoch=epoch).refusal, "HB_EPOCH_INVALID")

    def test_the_emitter_cli_without_an_epoch_prints_the_refusal_and_writes_nothing(self):
        run = self.emit_cli()
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertSixFields(json.loads(run.stdout))
        self.assertFalse(Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"]).exists())

    def test_the_emitter_cli_with_an_invalid_epoch_prints_the_refusal_and_writes_nothing(self):
        for epoch in ("33.0", "31", "+33", "True"):
            with self.subTest(epoch=epoch):
                run = self.emit_cli("--hb-epoch", epoch)
                self.assertEqual(run.returncode, 1, run.stderr)
                self.assertSixFields(json.loads(run.stdout), "HB_EPOCH_INVALID")
                self.assertFalse(Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"]).exists())

    def test_a_receiving_operation_handed_no_epoch_records_nothing(self):
        with self.assertRaises(ingress.repository_ledger.RepoLedgerEpochRefused):
            ingress.receive(diagnostic(), registry=REGISTRY, packet_id="no-epoch-diagnostic")
        self.assertEqual(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                       "stegverse.repo-transition-receipt/v1"), [])
        self.assertEqual(self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                       "stegverse.organization-transition-receipt/v1"), [])

    def test_a_receiving_operation_handed_an_invalid_epoch_records_nothing(self):
        with self.assertRaises(ingress.repository_ledger.RepoLedgerEpochRefused) as raised:
            ingress.receive(diagnostic(), registry=REGISTRY, packet_id="invalid-epoch-diagnostic",
                            hb_epoch="+33")
        self.assertSixFields(raised.exception.refusal, "HB_EPOCH_INVALID")
        self.assertEqual(self.receipts("STEGVERSE_REPO_LEDGER_ROOT",
                                       "stegverse.repo-transition-receipt/v1"), [])
        self.assertEqual(self.receipts("STEGVERSE_ORG_LEDGER_ROOT",
                                       "stegverse.organization-transition-receipt/v1"), [])


class LedgerWriterWorkflowTests(unittest.TestCase):
    """The writer workflow appends, pushes fast-forward only, and reads back.

    This inspects the workflow text. It does not dispatch the workflow and it
    does not write the published ledger ref.
    """

    def text(self):
        return (ROOT / ".github/workflows/organization-ledger-transition.yml").read_text(
            encoding="utf-8")

    def test_the_dispatch_appends_pushes_and_reads_the_designated_ref_back(self):
        text = self.text()
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("communication_id:", text)
        self.assertIn("refs/stegverse/organization-ledger", text)
        self.assertIn("group: organization-ledger", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("contents: write", text)
        self.assertIn("--self-close", text)
        self.assertIn("--verify-self-closure", text)
        self.assertIn("resident-runtime/intr_destination_ingress.py", text)
        self.assertIn('git fetch --no-tags origin "+$LEDGER_REF:$LEDGER_REF"', text)
        self.assertNotIn("federation.json", text)
        self.assertNotIn("capability_destination_bindings", text)
        push_lines = [line.strip() for line in text.splitlines() if "git push" in line]
        self.assertEqual(push_lines, ['if ! git push origin "$LEDGER_REF:$LEDGER_REF"; then'])
        for line in push_lines:
            self.assertNotIn("--force", line)
            self.assertNotIn("+", line)
        self.assertNotIn("--force", text)
        prohibited = "gr" + "ant"
        self.assertNotIn(prohibited, text.lower())
        self.assertNotIn(prohibited, (
            ROOT / "resident-runtime/intr_destination_ingress.py").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
