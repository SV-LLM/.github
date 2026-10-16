#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, importlib.util, json
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]; ACT=ROOT/"org-runtime/activation.json"; TR=ROOT/"org-runtime/interlock-intr.json"; ORG="SV-LLM"
STANDARD={"actions_by_manifest_required":True,"manifest_determines_destination":True,"destination_existence_sufficient_for_ingress_and_egress":True,"destination_liveness_is_transition_predicate":False,"external_machine_awaiting_allowed":False,"always_on_receiver_required":False,"receiver_unavailable_disposition":"DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION","post_closure_authentic_observer_gate_allowed":False}
def load(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise SystemExit(f"object required: {path}")
    return value
def canonical(value:Any)->str: return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
NON_AUTHORIZING_FLAGS=("environment_selected_ingress","host_required","environment_url_required","host_environment_mesh_fallback")
CONSTRAINT="CONSTRAINT_VARIABLE"
DISPOSITION_EVIDENCE="TRANSITION_EVIDENCE_ONLY"
OPERATION_CONSTRAINTS=("routing_authority_constraint","admission_authority_constraint","execution_authority_constraint","time_constraint")
HB_CONSTRAINTS=("admission_authority_constraint","execution_authority_constraint","credential_authority_constraint","routing_authority_constraint","transition_authority_constraint","receiving_authority_constraint","time_constraint")
REGISTRY=ROOT/"org-boundary/registry/services.json"
CAPABILITY_INGRESS_ROLE="BOUNDARY_LOCAL_CAPABILITY_INGRESS"
def _constraints(op:Any)->bool:
    """Authority and time stay constraint variables. The disposition is transition evidence only."""
    return isinstance(op,dict) and all(op.get(name)==CONSTRAINT for name in OPERATION_CONSTRAINTS) and op.get("disposition_role")==DISPOSITION_EVIDENCE
def _bound(op:Any,*,operation_id:str,entry:str,carrier:str,binding_role:str)->bool:
    """One operation owned here, carried by the declared kernel operation over the supplied mesh."""
    if not isinstance(op,dict): return False
    return (op.get("owner_repository")==f"{ORG}/.github" and op.get("operation_id")==operation_id and str(op.get(entry) or "").startswith("org-runtime/crossing.py::")
            and op.get("carrier")==carrier and op.get("transport")=="INTERLOCK_INTR" and op.get("mesh_location")=="SUPPLIED_BY_MATERIALIZER_AS_mesh_root"
            and op.get("mesh_location_unsupplied_disposition")=="FAIL_CLOSED" and op.get("credential_authority")=="TV/TVC" and op.get("github_token_runtime_authority")=="NONE"
            and op.get("binding_role")==binding_role and op.get("authority_effect")=="NONE_BINDING_ONLY" and op.get("every_disposition_is_receipted") is True
            and all(op.get(flag) is False for flag in NON_AUTHORIZING_FLAGS) and _constraints(op))
def egress_emitting_operation_bound(t:dict[str,Any])->bool:
    op=(t.get("egress") or {}).get("emitting_operation")
    return _bound(op,operation_id="ORGANIZATION_INTER_ORG_EGRESS",entry="emission",carrier="org-kernel/kernel.py::carry_packet",binding_role="ORGANIZATION_EMITTING_OPERATION_RESOLUTION") and op.get("origin_is_verified_by_this_boundary") is False and op.get("origin_attestation_state")=="NOT_PROVEN"
def ingress_receiving_operation_bound(t:dict[str,Any])->bool:
    op=(t.get("ingress") or {}).get("receiving_operation")
    return _bound(op,operation_id="ORGANIZATION_INTER_ORG_INGRESS",entry="consumption",carrier="org-kernel/kernel.py::scan_addressed_frames",binding_role="ORGANIZATION_RECEIVING_OPERATION_RESOLUTION")
def capability_bindings(t:dict[str,Any])->list[dict[str,Any]]:
    declared=(t.get("ingress") or {}).get("capability_endpoint_bindings") or []
    return [entry for entry in declared if isinstance(entry,dict)]
def submission_readers()->set[str]:
    """Read from the resolver rather than restated, so a binding cannot name a reader nothing implements."""
    spec=importlib.util.spec_from_file_location("capability_ingress_readers",ROOT/"org-boundary/runtime/capability_ingress.py")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return set(module.SUBMISSION_READERS)
def capability_addresses_resolve(t:dict[str,Any])->bool:
    """Every bound capability is reachable at the address the overlay names.

    The addressed service exists, carries the role whose dispatch resolves a
    capability, agrees with the binding on which capability arrives there, and
    names an operation module present in this repository. SUBMIT_MANIFEST keeps
    the manifest reader it had before the field existed. Any other operation
    must name a reader this resolver implements, and must not inherit the
    manifest reader. Authority and time on the binding stay constraint variables.
    """
    if (t.get("ingress") or {}).get("capability_address_rule")!="A_BOUND_RECEIVING_OPERATION_IS_ADDRESSABLE_IN_THE_SERVICE_REGISTRY_OR_IT_IS_UNREACHABLE": return False
    bindings=capability_bindings(t)
    if not bindings: return False
    rows={row.get("service_id"):row for row in load(REGISTRY).get("services",[]) if isinstance(row,dict)}
    known=submission_readers()
    for binding in bindings:
        if not _constraints(binding): return False
        receiving=binding.get("receiving_operation")
        if not _constraints(receiving): return False
        row=rows.get(receiving.get("addressed_service"))
        if row is None: return False
        if row.get("boundary_role")!=CAPABILITY_INGRESS_ROLE: return False
        if receiving.get("addressed_service_boundary_role")!=CAPABILITY_INGRESS_ROLE: return False
        if row.get("capability_profile_id")!=binding.get("profile_id"): return False
        if receiving.get("address_is_resolvable_from_the_service_registry") is not True: return False
        if receiving.get("selects_processing_at_the_capability_address") is not False: return False
        if row.get("selects_processing_at_this_address") is not False: return False
        if row.get("admission_authority_constraint")!=CONSTRAINT: return False
        if row.get("time_constraint")!=CONSTRAINT: return False
        if row.get("disposition_role")!=DISPOSITION_EVIDENCE: return False
        operation=receiving.get("operation")
        if not isinstance(operation,str) or not (ROOT/operation).is_file(): return False
        resolution=receiving.get("address_resolution")
        if not isinstance(resolution,str) or not (ROOT/resolution.split("::",1)[0]).is_file(): return False
        reader=binding.get("submission_reader")
        if binding.get("operation")=="SUBMIT_MANIFEST":
            if reader not in (None,"MANIFEST"): return False
            if reader is not None and reader not in known: return False
        elif not isinstance(reader,str) or reader not in known or reader=="MANIFEST":
            return False
    return True
def peer_capability_addresses_derive(t:dict[str,Any])->bool:
    """proven_on_this_organization names every capability address served here, and only those.

    A string still names the one address a single-capability organization
    serves. Two or more are a list. A peer address in the list is refused:
    the field is not a peer map.
    """
    resolution=(t.get("egress") or {}).get("peer_capability_resolution")
    if not isinstance(resolution,dict): return False
    if resolution.get("address_form")!="ORGANIZATION_SLUG_DOT_CAPABILITY_PROFILE_ID": return False
    if resolution.get("capability_must_be_declared_in_this_organizations_overlay") is not True: return False
    if resolution.get("derivation_is_the_same_one_this_organization_answers_at") is not True: return False
    if resolution.get("peer_serves_this_capability_is_proven_here") is not False: return False
    if resolution.get("peer_declares_its_capability_services_in_the_peer_directory") is not False: return False
    if resolution.get("unserved_capability_address_is_observable_as_an_unclosed_crossing") is not True: return False
    if resolution.get("default_without_a_declared_capability")!="ORG_CONTROL_SERVICE": return False
    served=[(binding.get("receiving_operation") or {}).get("addressed_service") for binding in capability_bindings(t)]
    if not served or any(not isinstance(item,str) or not item for item in served): return False
    if len(set(served))!=len(served): return False
    proven=resolution.get("proven_on_this_organization")
    if isinstance(proven,str):
        named=[proven]
    elif isinstance(proven,list) and proven and all(isinstance(item,str) and item for item in proven):
        named=list(proven)
    else:
        return False
    if len(set(named))!=len(named) or set(named)!=set(served): return False
    rows={row.get("service_id") for row in load(REGISTRY).get("services",[]) if isinstance(row,dict)}
    return all(item in rows for item in named)
def validate()->dict[str,Any]:
    a,t=load(ACT),load(TR); h=t["heartbeat_derived_carrier"]; checks={"activation_owner":a.get("organization")==ORG and a.get("owner_repository")==f"{ORG}/.github","activation_local":a.get("activation_source_scope")=="ORG_DOT_GITHUB_ONLY","runtime_reality_ledger":a.get("runtime_reality_locus")=="ORGANIZATION_LEDGER_ROOT" and a.get("runtime_reality_write_mode")=="MANIFEST_DIRECTED_APPEND","manifest_bound_no_awaiting":all(x.get("conformance_standard")==STANDARD for x in (a,t)),"no_endpoint_profile":t.get("repository_endpoint_rule")=="MANIFEST_DETERMINES_DESTINATION_EXISTING_DESTINATION_SUFFICIENT_NO_ENDPOINT_PROFILE_REQUIRED","transport_owner":t.get("organization")==ORG and t.get("owner_repository")==f"{ORG}/.github","all_io_here":t.get("communication_policy")=="ALL_ORGANIZATION_INGRESS_EGRESS_GENERATED_AT_ORG_DOT_GITHUB_BOUNDARY","tvtvc":a.get("credential_authority")=="TV/TVC" and t.get("credential_authority")=="TV/TVC","github_none":a.get("github_token_runtime_authority")=="NONE" and t.get("github_token_runtime_authority")=="NONE","effects_transition_derived":a.get("authority_effect_resolution")=="DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS" and t.get("authority_effect_resolution")=="DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","egress_emitting_operation_bound":egress_emitting_operation_bound(t),"ingress_receiving_operation_bound":ingress_receiving_operation_bound(t),"capability_addresses_resolve":capability_addresses_resolve(t),"peer_capability_addresses_derive":peer_capability_addresses_derive(t),"hb_constraints":all(h.get(k)==CONSTRAINT for k in HB_CONSTRAINTS) and h.get("disposition_role")==DISPOSITION_EVIDENCE}; return {"schema":"stegverse.organization-boundary-validation/v1","organization":ORG,"checks":checks,"valid":all(checks.values()),"authority_effect":"NONE_VALIDATION_ONLY"}
def activation_request(runtime_id:str)->dict[str,Any]:
    body={"schema":"stegverse.organization-resident-runtime-activation-request/v1","organization":ORG,"runtime_id":runtime_id,"owner_repository":f"{ORG}/.github","state":"REQUESTED","credential_authority":"TV/TVC","request_authority_constraint":CONSTRAINT,"time_constraint":CONSTRAINT,"disposition_role":DISPOSITION_EVIDENCE,"github_token_runtime_authority":"NONE","authority_transfer_assumed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS"}; return {**body,"request_sha256":canonical(body)}
def envelope(direction:str,peer_org:str,interlock_id:str,payload_sha256:str,transition_elements_ref:str,authority_ref:str|None)->dict[str,Any]:
    if direction not in {"INGRESS","EGRESS"}: raise SystemExit("direction")
    if len(payload_sha256)!=64: raise SystemExit("payload_sha256 must be 64 hex chars")
    body={"schema":"stegverse.organization-intr-envelope/v1","organization":ORG,"boundary_repository":f"{ORG}/.github","direction":direction,"peer_organization":peer_org,"interlock_id":interlock_id,"protocol":"InTr","payload_sha256":payload_sha256.lower(),"transition_elements_ref":transition_elements_ref,"authority_ref":authority_ref,"credential_authority":"TV/TVC","authority_transfer_assumed":False,"authority_effect_resolution":"DERIVED_FROM_APPLICABLE_TRANSITION_ELEMENTS","hb_carrier":{"frequency_hz":100,"period_ms":10,"progression_dependency":"OSCILLATOR_ONLY","authority_effect":"NONE_CARRIER_ONLY"},"github_token_runtime_authority":"NONE"}; return {**body,"envelope_sha256":canonical(body)}
def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True); sub.add_parser("validate"); a=sub.add_parser("activation-request"); a.add_argument("--runtime-id",required=True)
    for name in ("ingress","egress"):
      q=sub.add_parser(name); q.add_argument("--peer-org",required=True); q.add_argument("--interlock-id",required=True); q.add_argument("--payload-sha256",required=True); q.add_argument("--transition-elements-ref",required=True); q.add_argument("--authority-ref")
    ns=p.parse_args(); out=validate() if ns.cmd=="validate" else activation_request(ns.runtime_id) if ns.cmd=="activation-request" else envelope(ns.cmd.upper(),ns.peer_org,ns.interlock_id,ns.payload_sha256,ns.transition_elements_ref,ns.authority_ref); print(json.dumps(out,sort_keys=True)); return 0 if out.get("valid",True) else 1
if __name__=="__main__": raise SystemExit(main())
