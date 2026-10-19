#!/usr/bin/env python3
"""Capability-addressed egress: derive a peer address, emit, and close.

SV-LLM's manifest egress (``org-runtime/crossing.py``) addresses a peer and
does not observe a response, because those manifests request none. A
purpose-neutral diagnostic is an ``ecosystem.communication``. That class is
answered, and closure is the only place this boundary can show that something
at the addressed service ran the packet.

The peer address is ``organization_slug + "." + profile_id``. It is derived.
It is not read out of ``federation.json``, and resolution does not prove the
peer installed the receiving operation. No answer stays ``PENDING`` and writes
nothing. An answer closes only when the far-side terminal receipt recomputes
from the packet id, the addressed service, and the payload digest this
organization already holds. That shows a boundary ran this packet. It does not
show which organization that boundary belongs to, and it does not show that
the far side persisted the chain.

Authority and time are constraint variables. A disposition is transition
evidence only. Origin attestation is not installed on this boundary; an
offered credential authority is refused rather than dropped.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]

OPERATION_ID = "ORGANIZATION_INTER_ORG_EGRESS"
OWNER_REPOSITORY = "SV-LLM/.github"
RESULT_SCHEMA = "stegverse.organization-egress-result/v1"
EMISSION_SCHEMA = "stegverse.organization-egress-emission-record/v1"
CLOSURE_SCHEMA = "stegverse.organization-egress-closure-record/v1"
TRANSPORT_PROFILE = "stegverse.intr.org-boundary.v1"
BOUNDARY_RELATIVE = "org-runtime/interlock-intr.json"
CAPABILITY_ADDRESS_FORM = "ORGANIZATION_SLUG_DOT_CAPABILITY_PROFILE_ID"
ADDRESSED_SERVICE_FIELD = "addressed_service"
DESTINATION_BINDINGS_FIELD = "capability_destination_bindings"

INTENDED_ACTION_EMIT = "CROSS_AN_ORGANIZATION_BOUNDARY_OUTBOUND"
INTENDED_ACTION_CLOSE = "OBSERVE_THE_FAR_SIDE_CLOSURE_OF_AN_OUTBOUND_CROSSING"

EMITTED_CLASS = "ORGANIZATION_EGRESS_EMITTED"
EMIT_REFUSED_CLASS = "ORGANIZATION_EGRESS_REFUSED"
CLOSED_CLASS = "ORGANIZATION_EGRESS_CLOSED"
CLOSURE_REFUSED_CLASS = "ORGANIZATION_EGRESS_CLOSURE_REFUSED"

ALLOW = "ALLOW"
DENY = "DENY"
PENDING = "PENDING"

ACK_CLASSES = frozenset({"ecosystem.monitor.response", "ecosystem.work.ack",
                         "ecosystem.communication.ack"})

#: The receipt kinds ``dispatch`` mints, in order. Closure recomputes them.
FAR_SIDE_RECEIPT_KINDS = ("INGRESS_ACCEPTED", "DISPATCHED", "CONSUMED",
                          "RESULT_BOUND", "EGRESS_EMITTED")


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kernel = _module("org_kernel_egress", "org-kernel/kernel.py")
repository_ledger = _module("repo_transition_emit_egress", ".stegverse/transition-ledger/emit.py")
organization_ledger = _module("aggregate_repo_transition_egress",
                              "resident-runtime/aggregate_repo_transition.py")
ledger_store = _module("ledger_store_egress", "resident-runtime/ledger_store.py")


class EgressRefused(Exception):
    """A refusal carrying its own disposition, so a caller is never left guessing."""

    def __init__(self, failed_predicate: str, reason: str) -> None:
        super().__init__(reason)
        self.failed_predicate = failed_predicate
        self.reason = reason


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value)).hexdigest()


def this_organization(root: Path | None = None) -> str:
    return kernel.load_registry(root or ROOT)["organization"]


def _boundary(root: Path | None = None) -> dict[str, Any]:
    return json.loads((Path(root or ROOT) / BOUNDARY_RELATIVE).read_text(encoding="utf-8"))


def declared_capabilities(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Capabilities this organization's overlay declares, by profile id."""
    declared = (_boundary(root).get("ingress") or {}).get("capability_endpoint_bindings") or []
    return {entry["profile_id"]: entry for entry in declared
            if isinstance(entry, dict) and entry.get("profile_id")}


def outbound_entries(root: Path | None = None) -> list[dict[str, Any]]:
    """Egress destination bindings, in declaration order. Absent means none."""
    declared = (_boundary(root).get("egress") or {}).get(DESTINATION_BINDINGS_FIELD) or []
    return [entry for entry in declared
            if isinstance(entry, dict) and entry.get("profile_id")]


def select_outbound_binding(capability: str, organization: str, *,
                            root: Path | None = None) -> dict[str, Any] | None:
    """The binding that sends ``capability`` to ``organization``, or None.

    A capability declared only as an ingress profile, with no egress
    destination binding, returns None so the address stays the derived
    capability service. Authority and time stay constraint variables. A
    disposition is transition evidence only.
    """
    matches = [entry for entry in outbound_entries(root)
               if entry.get("profile_id") == capability or entry.get("capability") == capability]
    if not matches:
        if capability not in declared_capabilities(root):
            raise EgressRefused(
                "CAPABILITY_IS_DECLARED_IN_THIS_ORGANIZATIONS_OVERLAY",
                "no capability_endpoint_binding or capability_destination_binding declares "
                + str(capability))
        return None
    addressed = [entry for entry in matches
                 if entry.get("destination_organization") == organization]
    if len(addressed) > 1:
        raise EgressRefused(
            "CAPABILITY_DESTINATION_BINDING_IS_UNAMBIGUOUS",
            "capability " + str(capability) + " has more than one binding to "
            + str(organization))
    if not addressed:
        owners = ", ".join(sorted({str(entry.get("destination_organization")) for entry in matches}))
        raise EgressRefused(
            "CAPABILITY_IS_SENT_TO_THE_ORGANIZATION_THAT_OWNS_IT",
            "capability " + str(capability) + " is bound to " + owners
            + ", not " + str(organization))
    return addressed[0]


def peer_capability_service(organization: str, capability: str) -> str:
    """``organization_slug(org) + "." + profile_id``. Derived, not enumerated."""
    return kernel.organization_slug(organization) + "." + capability


def resolve_destination(organization: str, *, capability: str | None = None,
                        root: Path | None = None) -> dict[str, Any]:
    """Resolve a peer from the federation directory, and derive a capability address.

    The directory says who the peers are. It does not say which capability
    services they serve. With no capability, the destination is the peer's
    control service. With one, the destination is the derived capability
    address, and ``peer_serves_this_capability_is_proven_here`` stays false.
    """
    directory = kernel.load_federation_directory(root or ROOT)
    binding = (select_outbound_binding(capability, organization, root=root)
               if capability is not None else None)
    for row in directory.get("organizations", []):
        if row.get("organization") != organization:
            continue
        profile = row.get("transport_profile")
        if profile != TRANSPORT_PROFILE:
            raise EgressRefused(
                "DESTINATION_SPEAKS_THIS_BOUNDARY_TRANSPORT_PROFILE",
                "peer declares transport_profile " + str(profile)
                + "; this boundary speaks " + TRANSPORT_PROFILE)
        control = row.get("org_control_service")
        addressed = row.get(ADDRESSED_SERVICE_FIELD) or control
        address_capability = (binding or {}).get("capability") or capability
        declared_service = (binding or {}).get("destination_service")
        if isinstance(declared_service, str) and declared_service.strip():
            service = declared_service
        else:
            service = addressed if capability is None else peer_capability_service(
                organization, address_capability)
        if not service:
            raise EgressRefused(
                "DESTINATION_DECLARES_A_SERVICE_THIS_DIRECTORY_CAN_ADDRESS",
                "peer declares neither " + ADDRESSED_SERVICE_FIELD
                + " nor org_control_service: " + str(organization))
        return {
            "destination_organization": organization,
            "destination_repository": row.get("repository"),
            "destination_org_control_service": control,
            "destination_addressed_service": addressed,
            "destination_service": service,
            "destination_capability_profile_id": (binding or {}).get("profile_id") or capability,
            "addressed_capability": address_capability,
            "destination_binding_authority_effect": (binding or {}).get("authority_effect"),
            "destination_capability_address_form": CAPABILITY_ADDRESS_FORM,
            "destination_resolution_source": "ORGANIZATION_FEDERATION_DIRECTORY",
            "destination_resolved_from_caller_argument": False,
            "destination_capability_declared_by_the_peer_directory": False,
            "peer_serves_this_capability_is_proven_here": False,
            "unserved_capability_is_observable_as_an_unclosed_crossing": True,
            "transport_profile": profile,
        }
    raise EgressRefused(
        "DESTINATION_IS_A_DECLARED_PEER_OF_THIS_ORGANIZATION",
        "organization not in org-boundary/registry/federation.json: " + str(organization))


def closability_refusal(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    """Why this payload's crossing could never close, or None if it can."""
    declared = payload.get("message_class")
    if declared not in kernel.RESPONDED_REQUEST_CLASSES:
        return ("PAYLOAD_DECLARES_A_REQUEST_CLASS_THE_BOUNDARY_ANSWERS",
                "message_class " + repr(declared) + " is answered by no "
                "acknowledgement, so this crossing could be consumed and never "
                "closed; the profile answers "
                + ", ".join(sorted(kernel.RESPONDED_REQUEST_CLASSES)))
    identifier = payload.get("communication_id")
    if not isinstance(identifier, str) or not identifier.strip():
        return ("PAYLOAD_CARRIES_THE_COMMUNICATION_ID_CLOSURE_CORRELATES_ON",
                "closure collects a response by communication_id and this "
                "payload declares " + repr(identifier))
    return None


def _unattested() -> dict[str, Any]:
    return {
        "origin_attestation_state": "NOT_PROVEN",
        "origin_is_attested_by_the_credential_authority": False,
        "origin_is_verified_by_this_boundary": False,
    }


def emission_record(resolved: Mapping[str, Any], origin: str, packet: Mapping[str, Any],
                    frame: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": EMISSION_SCHEMA,
        "operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "intended_action": INTENDED_ACTION_EMIT,
        "disposition": ALLOW,
        "transition_is_the_disposition_of_the_intended_action": True,
        "origin_organization": origin,
        **dict(resolved),
        "packet_id": packet["packet_id"],
        "frame_sha256": frame.get("frame_sha256"),
        "payload_sha256": sha(dict(payload)),
        "far_side_payload_hash": kernel.sha(dict(payload)),
        "far_side_service_id": resolved["destination_service"],
        "transition_reference": (packet.get("transition") or {}).get("reference"),
        "crossed_an_organization_boundary": True,
        "interlock_intr_involved": True,
        **_unattested(),
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


def emit_refusal_record(failed_predicate: str, reason: str, organization: Any,
                        origin: str, payload: Any) -> dict[str, Any]:
    return {
        "schema": EMISSION_SCHEMA,
        "operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "intended_action": INTENDED_ACTION_EMIT,
        "disposition": DENY,
        "transition_is_the_disposition_of_the_intended_action": True,
        "origin_organization": origin,
        "requested_destination_organization": organization if isinstance(organization, str) else None,
        "failed_predicate": failed_predicate,
        "refusal_reason": reason,
        "refusal_is_verbatim": True,
        "payload_sha256": sha(dict(payload) if isinstance(payload, Mapping) else payload),
        "packet_emitted": False,
        "crossed_an_organization_boundary": False,
        "retry_is_a_transition_not_a_lost_signal": True,
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


def closure_record(resolved: Mapping[str, Any], origin: str, packet_id: str,
                   communication_id: str, response: Mapping[str, Any],
                   findings: list[str], recomputed: list[str]) -> dict[str, Any]:
    verified = not findings
    return {
        "schema": CLOSURE_SCHEMA,
        "operation": OPERATION_ID,
        "owner_repository": OWNER_REPOSITORY,
        "intended_action": INTENDED_ACTION_CLOSE,
        "disposition": ALLOW if verified else DENY,
        "transition_is_the_disposition_of_the_intended_action": True,
        "origin_organization": origin,
        "destination_organization": resolved["destination_organization"],
        "request_packet_id": packet_id,
        "communication_id": communication_id,
        "responding_organization": response.get("organization"),
        "response_packet_id": response.get("response_packet_id"),
        "response_message_class": response.get("message_class"),
        "response_frame_sha256": response.get("frame_sha256"),
        "far_side_terminal_receipt": response.get("receipt_terminal"),
        "far_side_terminal_receipt_recomputed": recomputed[-1] if recomputed else None,
        "far_side_receipt_chain_recomputed": recomputed,
        "far_side_receipt_reconstructed_here": True,
        "far_side_chain_recomputed_from_emitter_held_inputs": True,
        "verified_the_response_answers_the_emitted_packet": True,
        "verified_the_response_came_from_the_resolved_peer": True,
        "verified_the_response_carries_an_acknowledgement_class": True,
        "verified_the_far_side_terminal_receipt_recomputes": not findings,
        "reconstruction_proves_the_boundary_ran_this_packet": True,
        "reconstruction_proves_who_the_far_side_is": False,
        "reconstruction_proves_the_far_side_persisted_its_chain": False,
        "bilateral_match_requires_the_far_side_chain_to_be_readable": True,
        "closure_findings": findings,
        "far_side_application_result_sha256": sha(response.get("application_result")),
        "crossed_an_organization_boundary": True,
        "interlock_intr_involved": True,
        **_unattested(),
        "authority_effect": "NONE_CLOSURE_RECORD_ONLY",
    }


def _record(transition_id: str, transition_class: str, predecessor: str, successor: str,
            record: Mapping[str, Any], hb_epoch: int | None,
            hb_provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Append at both levels. The organization owner is ``append``.

    A supplied epoch makes a replay of the same emission return the recorded
    pair. The organization receipt takes the repository receipt's epoch.
    ``hb_provenance`` is the admitted CARRIED provenance of the crossing this
    emission answers; both writers verify it against that admission and
    record it (B-P36m ruling).
    """
    idempotent = hb_epoch is not None
    carried = {} if hb_provenance is None else {"hb_provenance": dict(hb_provenance)}
    repository_receipt = repository_ledger.append(
        transition_id, transition_class, predecessor, successor,
        dict(record), "NONE", hb_epoch=hb_epoch,
        idempotent_on=("frame_sha256", "payload_sha256") if idempotent else None,
        **({**carried, "provenance_store": organization_ledger.open_store(organization_ledger.ledger_root())}
           if carried else {}))
    # The SUPPLIED epoch, never one read back from a receipt (B-P36f).
    epoch = hb_epoch
    organization_receipt = organization_ledger.append(
        repository_receipt, "REPO_STATE_PROPAGATION", predecessor, successor,
        {"operation": OPERATION_ID, "intended_action": record["intended_action"],
         "disposition": record["disposition"],
         "crossed_an_organization_boundary": record["crossed_an_organization_boundary"]},
        "NONE", hb_epoch=epoch, idempotent=True, **carried)
    return {"repository_receipt": repository_receipt,
            "organization_receipt": organization_receipt}


def _custody():
    """Custody for a frame this operation records itself.

    ``carry_packet`` writes the frame and does not append a second federation
    emission. It still refuses a caller that cannot record on both ledgers.
    """
    repo = os.environ.get("STEGVERSE_REPO_LEDGER_ROOT")
    if not repo:
        raise ValueError("ledger_location_required_from_materializer")
    return kernel.crossing_custody(
        ROOT, repo_ledger_root=Path(repo),
        org_ledger_root=Path(organization_ledger.ledger_root()))


def _refusal_result(record: Mapping[str, Any], appended: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "operation": OPERATION_ID,
        "disposition": DENY,
        "emitted": False,
        "failed_predicate": record["failed_predicate"],
        "detail": record["refusal_reason"],
        "refusal_recorded": True,
        "emission_transition_class": EMIT_REFUSED_CLASS,
        "emission_record": dict(record),
        "emission_repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
        "emission_organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


def emit(destination_organization: Any, payload: Mapping[str, Any], *,
         standing: Mapping[str, Any], capability: str | None = None,
         credential_authority: Mapping[str, Any] | None = None,
         transition_reference: str = "ecosystem.transition.interorg.v1",
         root: Path | None = None, mesh_root: Path | None = None,
         hb_epoch: int | None = None, hb_provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Emit one closable crossing to a derived capability address, and record it.

    ``hb_epoch`` is checked by the kernel's shared supplied-epoch rule before
    anything else: an absent or invalid one raises SuppliedEpochRefused (the
    repository emitter's class, six fields) before a frame is built, so no
    frame is published and no clock is read. The frame carries that epoch.
    """
    hb_epoch = repository_ledger.kernel.supplied_hb_reference(
        hb_epoch, retry_entrypoint="resident-runtime/organization_egress_boundary.py::emit (hb_epoch=, or --hb-epoch)"
    )["epoch"]
    origin = this_organization(root)
    try:
        if credential_authority is not None:
            raise EgressRefused(
                "ORIGIN_ATTESTATION_IS_NOT_INSTALLED_ON_THIS_BOUNDARY",
                "an offered credential authority is not dropped and is not treated as proof")
        unclosable = closability_refusal(payload or {})
        if unclosable is not None:
            raise EgressRefused(*unclosable)
        resolved = resolve_destination(destination_organization, capability=capability, root=root)
        addressed_capability = resolved.get("addressed_capability") or capability
        packet = kernel.build_packet(
            origin_org=origin,
            origin_service=peer_capability_service(origin, addressed_capability) if capability
            else kernel.organization_slug(origin) + ".org-control",
            destination_org=resolved["destination_organization"],
            destination_service=resolved["destination_service"],
            payload=dict(payload), standing=dict(standing),
            transition_reference=transition_reference, authority_effect="NONE")
        published = kernel.carry_packet(packet, custody=_custody(), root=mesh_root, epoch=hb_epoch)
    except EgressRefused as exc:
        record = emit_refusal_record(exc.failed_predicate, exc.reason,
                                     destination_organization, origin, payload)
        appended = _record(EMIT_REFUSED_CLASS + ":" + sha(record)[7:23], EMIT_REFUSED_CLASS,
                           record["payload_sha256"], sha(record), record, hb_epoch, hb_provenance)
        return _refusal_result(record, appended)
    except (ValueError, KeyError, TypeError) as exc:
        record = emit_refusal_record("PACKET_IS_BUILDABLE_AND_PUBLISHABLE_AS_DECLARED",
                                     str(exc), destination_organization, origin, payload)
        appended = _record(EMIT_REFUSED_CLASS + ":" + sha(record)[7:23], EMIT_REFUSED_CLASS,
                           record["payload_sha256"], sha(record), record, hb_epoch, hb_provenance)
        return _refusal_result(record, appended)

    record = emission_record(resolved, origin, packet, published["frame"], payload)
    appended = _record(EMITTED_CLASS + ":" + packet["packet_id"], EMITTED_CLASS,
                       record["payload_sha256"], sha(record), record, hb_epoch, hb_provenance)
    return {
        "schema": RESULT_SCHEMA,
        "operation": OPERATION_ID,
        "disposition": ALLOW,
        "emitted": True,
        "packet_id": packet["packet_id"],
        "communication_id": (payload or {}).get("communication_id"),
        **{key: record[key] for key in (
            "destination_organization", "destination_repository",
            "destination_org_control_service", "destination_service",
            "destination_capability_profile_id",
            "peer_serves_this_capability_is_proven_here",
            "transport_profile", "destination_resolution_source", "frame_sha256",
            "crossed_an_organization_boundary",
            "origin_attestation_state",
            "origin_is_attested_by_the_credential_authority")},
        "emission_record": record,
        "emission_transition_class": EMITTED_CLASS,
        "emission_repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
        "emission_organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
        "authority_effect": "NONE_EGRESS_RECORD_ONLY",
    }


def reconstruct_far_side_chain(packet_id: str, service_id: str, payload_hash: str) -> list[str]:
    """Recompute the receipt chain a boundary mints for this packet.

    The inputs are the packet id this organization minted, the service it
    addressed, and the digest of the payload it sent. A terminal id that does
    not recompute did not come from a boundary that ran this packet.
    """
    chain, previous = [], None
    for kind in FAR_SIDE_RECEIPT_KINDS:
        receipt = kernel.receipt(kind, packet_id, service_id, previous,
                                 {"payload_hash": payload_hash})
        chain.append(receipt["receipt_id"])
        previous = receipt["receipt_id"]
    return chain


def recorded_emission(packet_id: str) -> dict[str, Any] | None:
    store = ledger_store.PosixLedgerStore(repository_ledger.lr())
    head = store.get(ledger_store.HEAD_KEY)
    cursor = (head or {}).get("receipt_sha256")
    wanted = EMITTED_CLASS + ":" + packet_id
    while cursor:
        receipt = store.get(ledger_store.receipt_key(cursor))
        if receipt is None:
            return None
        if (receipt.get("transition_class") == EMITTED_CLASS
                and receipt.get("transition_id") == wanted):
            evidence = receipt.get("evidence")
            return dict(evidence) if isinstance(evidence, Mapping) else None
        cursor = receipt.get("previous_receipt_sha256")
    return None


def verify_closure(resolved: Mapping[str, Any], packet_id: str,
                   response: Mapping[str, Any],
                   emission: Mapping[str, Any] | None = None) -> list[str]:
    findings = []
    if response.get("request_packet_id") != packet_id:
        findings.append("RESPONSE_ANSWERS_A_DIFFERENT_PACKET:"
                        + str(response.get("request_packet_id")))
    if response.get("organization") != resolved["destination_organization"]:
        findings.append("RESPONSE_CAME_FROM_A_DIFFERENT_ORGANIZATION:"
                        + str(response.get("organization")))
    if response.get("message_class") not in ACK_CLASSES:
        findings.append("RESPONSE_CARRIES_NO_ACKNOWLEDGEMENT_CLASS:"
                        + str(response.get("message_class")))
    terminal = response.get("receipt_terminal")
    if not isinstance(terminal, str) or not terminal.strip():
        findings.append("RESPONSE_CARRIES_NO_FAR_SIDE_TERMINAL_RECEIPT")
        return findings
    if emission is None:
        findings.append("THIS_ORGANIZATION_HAS_NO_EMISSION_RECORD_FOR_THIS_PACKET")
        return findings
    recomputed = reconstruct_far_side_chain(
        packet_id, emission["far_side_service_id"], emission["far_side_payload_hash"])
    if terminal != recomputed[-1]:
        findings.append("FAR_SIDE_TERMINAL_RECEIPT_DOES_NOT_RECOMPUTE:" + terminal)
    return findings


def close(destination_organization: str, packet_id: str, communication_id: str, *,
          root: Path | None = None, mesh_root: Path | None = None,
          hb_epoch: int | None = None) -> dict[str, Any]:
    """Observe a far-side answer. No answer is ``PENDING`` and writes nothing."""
    origin = this_organization(root)
    resolved = resolve_destination(destination_organization, root=root)
    collected = kernel.collect_ecosystem_responses(origin, communication_id, mesh_root=mesh_root)
    responses = [row for row in collected.get("organizations", [])
                 if row.get("organization") == resolved["destination_organization"]]
    if not responses:
        return {
            "schema": RESULT_SCHEMA,
            "operation": OPERATION_ID,
            "disposition": PENDING,
            "closed": False,
            "closure_recorded": False,
            "absence_is_not_a_transition": True,
            "communication_id": communication_id,
            "request_packet_id": packet_id,
            "destination_organization": resolved["destination_organization"],
            "authority_effect": "NONE_OBSERVATION_ONLY",
        }
    response = responses[0]
    emission = recorded_emission(packet_id)
    findings = verify_closure(resolved, packet_id, response, emission)
    recomputed = reconstruct_far_side_chain(
        packet_id, emission["far_side_service_id"], emission["far_side_payload_hash"]
    ) if emission else []
    record = closure_record(resolved, origin, packet_id, communication_id, response,
                            findings, recomputed)
    transition_class = CLOSED_CLASS if not findings else CLOSURE_REFUSED_CLASS
    appended = _record(transition_class + ":" + packet_id, transition_class,
                       sha({"packet_id": packet_id, "communication_id": communication_id}),
                       sha(record), record, hb_epoch)
    return {
        "schema": RESULT_SCHEMA,
        "operation": OPERATION_ID,
        "disposition": record["disposition"],
        "closed": not findings,
        "closure_recorded": True,
        "closure_findings": findings,
        "communication_id": communication_id,
        "request_packet_id": packet_id,
        "destination_organization": resolved["destination_organization"],
        "responding_organization": response.get("organization"),
        "far_side_terminal_receipt": response.get("receipt_terminal"),
        "far_side_receipt_reconstructed_here": True,
        "far_side_terminal_receipt_recomputed": recomputed[-1] if recomputed else None,
        "far_side_application_result": response.get("application_result"),
        "closure_record": record,
        "closure_transition_class": transition_class,
        "closure_repository_receipt_sha256": appended["repository_receipt"]["receipt_sha256"],
        "closure_organization_receipt_sha256": appended["organization_receipt"]["receipt_sha256"],
        "authority_effect": "NONE_CLOSURE_RECORD_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--destination-organization", required=True)
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--standing", type=Path)
    parser.add_argument("--transition-reference", default="ecosystem.transition.interorg.v1")
    parser.add_argument("--hb-epoch", default=None,
                        help="heartbeat epoch from the carrier tick; required, never derived from the host clock")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--packet-id")
    parser.add_argument("--communication-id")
    parser.add_argument("--capability")
    parser.add_argument("--mesh-root", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    # The raw text goes to the kernel rule; an int() here would admit '+33'.
    refusal = kernel.writer_epoch_refusal(
        args.hb_epoch, retry_entrypoint="resident-runtime/organization_egress_boundary.py --hb-epoch")
    if refusal is not None:
        print(json.dumps(refusal, sort_keys=True))
        return 1
    args.hb_epoch = int(args.hb_epoch)
    if args.close:
        if not args.packet_id or not args.communication_id:
            raise SystemExit("--close requires --packet-id and --communication-id")
        result = close(args.destination_organization, args.packet_id, args.communication_id,
                       mesh_root=args.mesh_root, hb_epoch=args.hb_epoch)
    else:
        if args.payload is None or args.standing is None:
            raise SystemExit("emit requires --payload and --standing")
        # Read before any write and outside the fault classifier (F-INPUT-TRACE).
        entry = "resident-runtime/organization_egress_boundary.py"
        standing = kernel.read_cli_json(args.standing, argument="--standing", retry_entrypoint=entry + " --standing")
        payload = kernel.read_cli_json(args.payload, argument="--payload", retry_entrypoint=entry + " --payload")
        result = emit(args.destination_organization, payload, standing=standing,
                      capability=args.capability, transition_reference=args.transition_reference,
                      mesh_root=args.mesh_root, hb_epoch=args.hb_epoch)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("disposition") in {ALLOW, PENDING} else 1


if __name__ == "__main__":
    sys.exit(kernel.run_cli(main, retry_entrypoint="resident-runtime/organization_egress_boundary.py (the same command again)"))
