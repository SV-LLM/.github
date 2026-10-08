#!/usr/bin/env python3
"""SV-LLM organization crossings as manifest-bound, recorded state transitions.

Every action crossing the SV-LLM boundary is an attempted state transition bound
to a manifest, and the manifest determines the destination:

* EGRESS -- the manifest names a peer organization. If that organization exists
  in the federation directory projection, the packet is published by the
  declared carrier (org-kernel/kernel.py::publish_packet) to the mesh the
  materializer supplied, and the transition succeeds at egress. Nothing waits
  for the receiver: the mesh is the durable queue, so receiver availability
  and liveness are never predicates.
* INGRESS -- a frame addressed to SV-LLM. If its manifest names an SV-LLM
  repository that exists in this organization's inventory, the manifest is
  materialized for that repository, write-once. Existence of the destination is
  sufficient; no endpoint profile, listener or resident receiver is required.
  A frame addressed to a registered boundary service is dispatched by the
  kernel.

Every disposition -- including every refusal -- is appended to the repository
ledger and then the organization ledger, which is where SV-LLM's runtime reality
is located. An absence is not recorded: no frame means nothing crossed.

Locations are supplied, never derived from the host. The mesh is the
`mesh_root` argument; there is no environment, home-directory or hosted
transport fallback. A crossing attempted without one is FAIL_CLOSED
MESH_LOCATION_REQUIRED_FROM_MATERIALIZER and recorded. This node's own state
-- consumption markers, work intake and ingress materializations -- is the
`node_state_root` argument, written once by key through org-kernel/node_store.py;
an ingress pass without one is FAIL_CLOSED
NODE_STATE_LOCATION_REQUIRED_FROM_MATERIALIZER and recorded, and nothing is
written under the repository checkout. The ledgers are
STEGVERSE_REPO_LEDGER_ROOT and STEGVERSE_ORG_LEDGER_ROOT; without both nothing
is appended to either and the attempt is FAIL_CLOSED
LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER.

Interlock/InTr remains the transition authority. Credential authority is TV/TVC.
Nothing here grants routing, admission, credential or execution authority.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]

def _module(name:str, relative:str, root:Path=ROOT):
    spec=importlib.util.spec_from_file_location(name,root/relative)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

kernel=_module("org_kernel","org-kernel/kernel.py")
organization_ledger=_module("aggregate_repo_transition","resident-runtime/aggregate_repo_transition.py")

ORG=kernel.load_registry(ROOT)["organization"]
SLUG=kernel.organization_slug(ORG)
CONTROL=SLUG+".org-control"
CREDENTIAL_AUTHORITY="TV/TVC"

LEDGER_OPENED="ORGANIZATION_LEDGER_OPENED"
EGRESS_EMITTED="ORGANIZATION_EGRESS_EMITTED"
EGRESS_REFUSED="ORGANIZATION_EGRESS_REFUSED"
INGRESS_MATERIALIZED="ORGANIZATION_INGRESS_MATERIALIZED"
INGRESS_CONSUMED="ORGANIZATION_INGRESS_CONSUMED"
INGRESS_REFUSED="ORGANIZATION_INGRESS_REFUSED"
ALLOW,DENY,FAIL_CLOSED="ALLOW","DENY","FAIL_CLOSED"
MESH_LOCATION_REQUIRED="MESH_LOCATION_REQUIRED_FROM_MATERIALIZER"
LEDGER_LOCATION_REQUIRED="LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER"
NODE_STATE_LOCATION_REQUIRED="NODE_STATE_LOCATION_REQUIRED_FROM_MATERIALIZER"
MATERIALIZATION_PREFIX="ingress/materialized/"
EGRESS_RETRY="org-runtime/crossing.py::egress"
INGRESS_RETRY="org-runtime/crossing.py::ingress"
SDK_MANIFEST_CROSSING_PAYLOAD="stegverse.sdk-manifest-crossing-payload/v1"
CAPABILITY_PROFILE_ID=re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
#: How processing was selected, carried on every admitted inbound outcome.
SELECTION_FIELDS=("processing_selection","declared_capability","declared_route_id",
                  "declared_capability_processed","route_admissibility")
#: Materialization is a boundary-local surface: it hands the manifest to an
#: existing repository and selects no processor.
MATERIALIZATION_ROW={"service_id":CONTROL+"#materialization","boundary_role":"BOUNDARY_LOCAL_MATERIALIZATION"}

class Refused(Exception):
    disposition=DENY
    def __init__(self, failed_predicate:str, reason:str="") -> None:
        super().__init__(failed_predicate); self.failed_predicate=failed_predicate; self.reason=reason

class FailClosed(Refused):
    """A refusal because a precondition the materializer owes was not supplied."""
    disposition=FAIL_CLOSED

class LedgerLocationRefused(SystemExit):
    """No ledger location was supplied; nothing was appended to either ledger.

    There is no ledger to record this refusal on, so it is the attempt's own
    disposition, raised to the caller with its failed predicate and retry edge.
    """
    disposition=FAIL_CLOSED; failed_predicate=LEDGER_LOCATION_REQUIRED
    def __init__(self, variable:str) -> None:
        self.refusal={"schema":"stegverse.organization-ledger-append-refusal/v1","organization":ORG,
                      "disposition":FAIL_CLOSED,"failed_predicate":LEDGER_LOCATION_REQUIRED,
                      "required_evidence_or_repair":"supply the ledger root as "+variable,
                      "retry_entrypoint":"org-runtime/crossing.py::record","consequence_committed":False,
                      "authority_effect":"NONE_REFUSAL_ONLY"}
        super().__init__(LEDGER_LOCATION_REQUIRED+": "+json.dumps(self.refusal,sort_keys=True))

def require_ledger_locations()->None:
    """Both ledger roots are supplied, or neither ledger is touched."""
    if not os.environ.get("STEGVERSE_REPO_LEDGER_ROOT"): raise LedgerLocationRefused("STEGVERSE_REPO_LEDGER_ROOT")
    try: organization_ledger.ledger_root()
    except organization_ledger.LedgerLocationRequired as missing: raise LedgerLocationRefused(missing.variable) from None

def refusal_outcome(refused:Refused, retry_entrypoint:str, **identity:Any)->dict[str,Any]:
    return {"disposition":refused.disposition,"failed_predicate":refused.failed_predicate,"reason":refused.reason,
            "retry_entrypoint":retry_entrypoint,**identity}

def sha(v:Any)->str: return kernel.sha(v)

def organization_repositories(root:Path=ROOT)->set[str]:
    tree=json.loads((root/"data/organization-tree.json").read_text())
    return {row["name"] for row in tree["repositories"]}

def require_manifest(manifest:Any)->dict[str,Any]:
    if not isinstance(manifest,dict): raise Refused("MANIFEST_MISSING")
    if not isinstance(manifest.get("manifest_id"),str) or not manifest["manifest_id"]: raise Refused("MANIFEST_ID_MISSING")
    destination=manifest.get("destination")
    if not isinstance(destination,dict) or not isinstance(destination.get("organization"),str):
        raise Refused("MANIFEST_DESTINATION_MISSING")
    return manifest

def record(transition_class:str, *, subject:Any, outcome:dict[str,Any], root:Path=ROOT, genesis:bool=False)->dict[str,Any]:
    """Append one transition to the repository ledger, then the organization ledger.

    The organization chain is opened only by an explicit genesis transition
    (open_organization_ledger); on an empty organization ledger any other record
    is refused FAIL_CLOSED ORG_LEDGER_GENESIS_NOT_DECLARED.
    """
    require_ledger_locations()
    predecessor=sha(subject); successor=sha(outcome)
    transition_id=transition_class+":"+successor[7:31]
    run=subprocess.run([sys.executable,str(root/".stegverse/transition-ledger/emit.py"),
                        "--transition-id",transition_id,"--transition-class",transition_class,
                        "--predecessor-state-sha256",predecessor,"--successor-state-sha256",successor,
                        "--evidence-json",json.dumps(outcome,sort_keys=True),"--authority-effect","NONE"],
                       capture_output=True,text=True,env=dict(os.environ))
    if run.returncode!=0: raise SystemExit("REPO_LEDGER_APPEND_FAILED:"+run.stderr.strip()[-300:])
    repo_receipt=json.loads(run.stdout)
    org_receipt=organization_ledger.aggregate_transition(
        repo_receipt,org_transition_class=transition_class,
        boundary_evidence={"disposition":outcome["disposition"],"credential_authority":CREDENTIAL_AUTHORITY,
                           "transition_authority":"Interlock/InTr"},
        authority_effect="NONE",genesis=genesis)
    return {"repo_receipt_sha256":repo_receipt["receipt_sha256"],"org_receipt_sha256":org_receipt["receipt_sha256"]}

def open_organization_ledger(root:Path=ROOT)->dict[str,Any]:
    """Open this organization's ledger chain with a declared genesis transition.

    Genesis is declared state, never inferred from an empty ledger. Against a
    ledger that already has a HEAD this is refused DENY
    ORG_LEDGER_GENESIS_ON_NON_EMPTY_LEDGER and nothing is written.
    """
    subject={"intended_action":"OPEN_ORGANIZATION_LEDGER","organization":ORG}
    outcome={"disposition":"ALLOW","organization":ORG,"authority_effect":"NONE"}
    return {"transition_class":LEDGER_OPENED,**outcome,
            **record(LEDGER_OPENED,subject=subject,outcome=outcome,root=root,genesis=True)}

def carrier_custody(root:Path)->dict[str,Any]:
    """This organization's custody over its supplied ledgers, which the kernel requires.

    The kernel's carrier and dispatch refuse a caller that cannot record what
    they do on both ledgers of the kernel's own organization. Egress records
    its own emission (EGRESS_EMITTED) and ingress every disposition it reaches,
    so each holds that custody.
    Resolved before the frame is published: an organization chain with no
    declared genesis is refused here, exactly as its record would be, rather
    than after a frame has already left.
    """
    require_ledger_locations()
    try:
        return kernel.crossing_custody(root,repo_ledger_root=Path(os.environ["STEGVERSE_REPO_LEDGER_ROOT"]),
                                       org_ledger_root=organization_ledger.ledger_root())
    except ValueError as refused:
        if "org_ledger_genesis_not_declared" in str(refused):
            raise organization_ledger.OrgLedgerAppendRefused(FAIL_CLOSED,"ORG_LEDGER_GENESIS_NOT_DECLARED") from None
        raise

def resolve_peer(organization:str, root:Path=ROOT)->dict[str,Any]:
    if organization==ORG: raise Refused("DESTINATION_IS_THIS_ORGANIZATION","an intra-organization manifest does not cross the boundary")
    rows=[r for r in kernel.load_federation_directory(root)["organizations"] if r.get("organization")==organization]
    if len(rows)!=1: raise Refused("DESTINATION_NOT_IN_FEDERATION_DIRECTORY")
    if rows[0].get("transport_profile")!=kernel.PACKET_SCHEMA: raise Refused("DESTINATION_TRANSPORT_PROFILE_UNSUPPORTED")
    return rows[0]

def destination_address(manifest:dict[str,Any], peer:dict[str,Any])->tuple[str,dict[str,Any]]:
    """The manifest's destination determines the addressed service and payload.

    A destination declaring a `capability` is addressed to the peer's service for
    that capability (ORGANIZATION_SLUG_DOT_CAPABILITY_PROFILE_ID) and carries the
    manifest in manifest["payload"]["manifest"] as an SDK manifest crossing
    payload. Fail closed on a capability that is not a profile id, or one with no
    carried manifest. Without a capability, the peer's control service is
    addressed and the whole manifest is carried, as before.
    """
    destination=manifest["destination"]
    if "capability" not in destination:
        return (peer.get("addressed_service") or kernel.organization_slug(peer["organization"])+".org-control",
                {"manifest":manifest})
    capability=destination["capability"]
    if not isinstance(capability,str) or not CAPABILITY_PROFILE_ID.fullmatch(capability):
        raise Refused("MANIFEST_CAPABILITY_INVALID","a declared capability must be a profile id (lowercase letters, digits, hyphens)")
    carried=manifest.get("payload",{}).get("manifest") if isinstance(manifest.get("payload"),dict) else None
    if not isinstance(carried,dict): raise Refused("MANIFEST_CAPABILITY_PAYLOAD_MISSING","a declared capability requires payload.manifest")
    return (kernel.organization_slug(peer["organization"])+"."+capability,
            {"schema":SDK_MANIFEST_CROSSING_PAYLOAD,"declared_transition_surface":destination.get("surface"),
             "manifest":carried,"manifest_sha256":sha(carried)})

def egress(manifest:Any, *, standing:dict[str,Any], mesh_root:Path|None=None, root:Path=ROOT,
           now_ns:int|None=None)->dict[str,Any]:
    subject={"intended_action":"CROSS_AN_ORGANIZATION_BOUNDARY_OUTBOUND","manifest":manifest}
    require_ledger_locations()  # before any frame is published: an unrecordable emission must not happen
    try:
        manifest=require_manifest(manifest)
        peer=resolve_peer(manifest["destination"]["organization"],root)
        destination_service,payload=destination_address(manifest,peer)
        packet=kernel.build_packet(origin_org=ORG,origin_service=CONTROL,destination_org=peer["organization"],
                                   destination_service=destination_service,payload=payload,
                                   standing=standing,transition_reference=manifest["manifest_id"],
                                   packet_id=SLUG+"-"+sha(manifest)[7:31])
        if mesh_root is None:
            raise FailClosed(MESH_LOCATION_REQUIRED,"the declared carrier publishes only to a mesh supplied as mesh_root")
        published=kernel.carry_packet(packet,custody=carrier_custody(root),root=mesh_root,now_ns=now_ns)
    except Refused as refused:
        outcome=refusal_outcome(refused,EGRESS_RETRY,manifest_sha256=sha(manifest))
        return {"transition_class":EGRESS_REFUSED,**outcome,**record(EGRESS_REFUSED,subject=subject,outcome=outcome,root=root)}
    outcome={"disposition":ALLOW,"manifest_id":manifest["manifest_id"],"manifest_sha256":sha(manifest),
             "destination_organization":packet["destination"]["org"],"destination_service":destination_service,
             "packet_id":packet["packet_id"],"frame_sha256":published["frame"]["frame_sha256"],
             "receiver_unavailable_disposition":"DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION",
             "awaits_receiver":False}
    return {"transition_class":EGRESS_EMITTED,**outcome,"spool_path":published["path"],
            **record(EGRESS_EMITTED,subject=subject,outcome=outcome,root=root)}

def _materialize(node_state:Any, repository:str, packet:dict[str,Any])->tuple[str,dict[str,Any]]:
    """Materialize a manifest for an existing repository, once, in this node's own state.

    It used to be a bare write_text under resident-runtime/ in the repository
    checkout, so an ingress pass mutated committed space and a reader could see
    a partial file. It is now one put_once at a key in the node state the
    materializer supplied: atomic, write-once, and a different document at the
    same key is a collision rather than an overwrite.
    """
    key=MATERIALIZATION_PREFIX+repository+"/"+hashlib.sha256(packet["packet_id"].encode()).hexdigest()+".json"
    record={"schema":"stegverse.organization-ingress-materialization/v1","organization":ORG,
            "repository":ORG+"/"+repository,"packet":packet,"authority_effect":"NONE"}
    try: node_state.put_once(key,record)
    except kernel.node_store_module.WriteOnceCollision: raise Refused("MATERIALIZATION_WRITE_ONCE_COLLISION")
    return node_state.locator(key),record

def _ingest(root:Path, frame:dict[str,Any], node_state:Any, custody:dict[str,Any])->dict[str,Any]:
    subject={"intended_action":"CROSS_AN_ORGANIZATION_BOUNDARY_INBOUND","frame_sha256":frame.get("frame_sha256")}
    try:
        try: packet=kernel.recover_packet(frame)
        except (ValueError,KeyError) as exc: raise Refused("FRAME_UNVERIFIABLE",str(exc))
        manifest=packet.get("payload",{}).get("manifest")
        repository=(manifest or {}).get("destination",{}).get("repository") if isinstance(manifest,dict) else None
        if repository is None:
            # Dispatch resolves how processing was selected before any receipt,
            # and refuses a selection the addressed service does not admit.
            try: result=kernel.dispatch(root,packet,custody=custody,node_state=node_state)
            except ValueError as exc: raise Refused("BOUNDARY_DISPATCH_REFUSED",str(exc))
            outcome={"disposition":ALLOW,"packet_id":packet["packet_id"],"origin_organization":packet["origin"]["org"],
                     "destination_service":result["service_id"],"terminal_receipt_id":result["reconstruction"]["terminal_receipt_id"],
                     **{key:result[key] for key in SELECTION_FIELDS}}
            return {"transition_class":INGRESS_CONSUMED,**outcome,**record(INGRESS_CONSUMED,subject=subject,outcome=outcome,root=root)}
        manifest=require_manifest(manifest)
        if manifest["destination"]["organization"]!=ORG: raise Refused("MANIFEST_DESTINATION_ORGANIZATION_MISMATCH")
        standing=kernel.node_standing(root)
        try: standing.require(standing.load_contract(root),packet)
        except SystemExit as refused: raise Refused("NODE_STANDING_REFUSED",str(refused))
        name=repository.split("/",1)[1] if repository.startswith(ORG+"/") else repository
        if name not in organization_repositories(root): raise Refused("DESTINATION_REPOSITORY_DOES_NOT_EXIST")
        # Materialization hands the manifest to an existing repository; nothing
        # here processes it. A declared capability is carried, and the outcome
        # says it was not processed at this boundary.
        selected=kernel.manifest_selection(root).select_processing(MATERIALIZATION_ROW,manifest)
        path,materialized=_materialize(node_state,name,packet)
    except Refused as refused:
        outcome=refusal_outcome(refused,INGRESS_RETRY,packet_id=frame.get("packet_id"),
                                origin_organization=frame.get("origin_org"))
        return {"transition_class":INGRESS_REFUSED,**outcome,**record(INGRESS_REFUSED,subject=subject,outcome=outcome,root=root)}
    outcome={"disposition":ALLOW,"packet_id":packet["packet_id"],"origin_organization":packet["origin"]["org"],
             "manifest_id":manifest["manifest_id"],"manifest_sha256":sha(manifest),"destination_repository":ORG+"/"+name,
             "materialization_sha256":sha(materialized),**{key:selected[key] for key in SELECTION_FIELDS}}
    return {"transition_class":INGRESS_MATERIALIZED,**outcome,"materialization_path":path,
            **record(INGRESS_MATERIALIZED,subject=subject,outcome=outcome,root=root)}

def ingress(*, mesh_root:Path|None=None, node_state_root:Path|None=None, root:Path=ROOT)->list[dict[str,Any]]:
    """Consume every frame addressed to SV-LLM not already consumed. Never waits for one.

    Without a supplied mesh there is nothing this boundary may scan, and
    without supplied node state there is nowhere to remember what was
    consumed, so either attempt is FAIL_CLOSED and recorded rather than
    resolved against the host or the checkout. Nothing is consumed then.
    """
    require_ledger_locations()  # before any frame is consumed or marked seen
    for location,predicate,reason,field in (
            (mesh_root,MESH_LOCATION_REQUIRED,"frames are scanned only from a mesh supplied as mesh_root","mesh_location"),
            (node_state_root,NODE_STATE_LOCATION_REQUIRED,
             "markers, work intake and materializations are written only to node state supplied as node_state_root",
             "node_state_location")):
        if location is None:
            refused=FailClosed(predicate,reason)
            subject={"intended_action":"CROSS_AN_ORGANIZATION_BOUNDARY_INBOUND",field:None}
            outcome=refusal_outcome(refused,INGRESS_RETRY,packet_id=None,origin_organization=None)
            return [{"transition_class":INGRESS_REFUSED,**outcome,
                     **record(INGRESS_REFUSED,subject=subject,outcome=outcome,root=root)}]
    node_state=kernel.addressed_node_state_store(node_state_root)
    # Dispatch processes nothing for a caller that cannot record it; this pass
    # records every disposition below, so it holds the organization's custody.
    custody=carrier_custody(root)
    results=[]
    for item in kernel.scan_addressed_frames(ORG,root=mesh_root,seen=kernel.federation_seen_frame_names(root,store=node_state)):
        result=_ingest(root,item["frame"],node_state,custody)
        kernel.mark_federation_frame_seen(root,item["path"],item["frame"],{"status":result["transition_class"]},store=node_state)
        results.append(result)
    return results

def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    e=sub.add_parser("egress"); e.add_argument("--manifest",required=True); e.add_argument("--standing",required=True)
    e.add_argument("--mesh-root",type=Path,required=True)
    i=sub.add_parser("ingress"); i.add_argument("--mesh-root",type=Path,required=True)
    i.add_argument("--node-state-root",type=Path,required=True)
    sub.add_parser("open-ledger")
    ns=p.parse_args()
    if ns.cmd=="open-ledger":
        out=open_organization_ledger()
    elif ns.cmd=="egress":
        out=egress(json.loads(Path(ns.manifest).read_text()),standing=json.loads(Path(ns.standing).read_text()),
                   mesh_root=ns.mesh_root)
    else:
        out=ingress(mesh_root=ns.mesh_root,node_state_root=ns.node_state_root)
    print(json.dumps(out,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
