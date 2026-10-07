#!/usr/bin/env python3
"""SV-LLM organization crossings as manifest-bound, recorded state transitions.

Every action crossing the SV-LLM boundary is an attempted state transition bound
to a manifest, and the manifest determines the destination:

* EGRESS -- the manifest names a peer organization. If that organization exists
  in the federation directory projection, the packet is published to the shared
  federation spool and the transition succeeds at egress. Nothing waits for the
  receiver: the spool is the durable queue, so receiver availability and
  liveness are never predicates.
* INGRESS -- a frame addressed to SV-LLM. If its manifest names an SV-LLM
  repository that exists in this organization's inventory, the manifest is
  materialized for that repository, write-once. Existence of the destination is
  sufficient; no endpoint profile, listener or resident receiver is required.
  A frame addressed to a registered boundary service is dispatched by the
  kernel.

Every disposition -- including every refusal -- is appended to the repository
ledger and then the organization ledger, which is where SV-LLM's runtime reality
is located. An absence is not recorded: no frame means nothing crossed.

Interlock/InTr remains the transition authority. Credential authority is TV/TVC.
Nothing here grants routing, admission, credential or execution authority.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, subprocess, sys
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
ALLOW,DENY="ALLOW","DENY"

class Refused(Exception):
    def __init__(self, failed_predicate:str, reason:str="") -> None:
        super().__init__(failed_predicate); self.failed_predicate=failed_predicate; self.reason=reason

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

def resolve_peer(organization:str, root:Path=ROOT)->dict[str,Any]:
    if organization==ORG: raise Refused("DESTINATION_IS_THIS_ORGANIZATION","an intra-organization manifest does not cross the boundary")
    rows=[r for r in kernel.load_federation_directory(root)["organizations"] if r.get("organization")==organization]
    if len(rows)!=1: raise Refused("DESTINATION_NOT_IN_FEDERATION_DIRECTORY")
    if rows[0].get("transport_profile")!=kernel.PACKET_SCHEMA: raise Refused("DESTINATION_TRANSPORT_PROFILE_UNSUPPORTED")
    return rows[0]

def egress(manifest:Any, *, standing:dict[str,Any], mesh_root:Path|None=None, root:Path=ROOT,
           now_ns:int|None=None)->dict[str,Any]:
    subject={"intended_action":"CROSS_AN_ORGANIZATION_BOUNDARY_OUTBOUND","manifest":manifest}
    try:
        manifest=require_manifest(manifest)
        peer=resolve_peer(manifest["destination"]["organization"],root)
        destination_service=peer.get("addressed_service") or kernel.organization_slug(peer["organization"])+".org-control"
        packet=kernel.build_packet(origin_org=ORG,origin_service=CONTROL,destination_org=peer["organization"],
                                   destination_service=destination_service,payload={"manifest":manifest},
                                   standing=standing,transition_reference=manifest["manifest_id"],
                                   packet_id=SLUG+"-"+sha(manifest)[7:31])
        published=kernel.publish_packet(packet,root=mesh_root,now_ns=now_ns)
    except Refused as refused:
        outcome={"disposition":DENY,"failed_predicate":refused.failed_predicate,"reason":refused.reason,
                 "manifest_sha256":sha(manifest)}
        return {"transition_class":EGRESS_REFUSED,**outcome,**record(EGRESS_REFUSED,subject=subject,outcome=outcome,root=root)}
    outcome={"disposition":ALLOW,"manifest_id":manifest["manifest_id"],"manifest_sha256":sha(manifest),
             "destination_organization":packet["destination"]["org"],"destination_service":destination_service,
             "packet_id":packet["packet_id"],"frame_sha256":published["frame"]["frame_sha256"],
             "receiver_unavailable_disposition":"DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION",
             "awaits_receiver":False}
    return {"transition_class":EGRESS_EMITTED,**outcome,"spool_path":published["path"],
            **record(EGRESS_EMITTED,subject=subject,outcome=outcome,root=root)}

def _materialize(root:Path, repository:str, packet:dict[str,Any])->Path:
    directory=root/"resident-runtime/materialized"/repository; directory.mkdir(parents=True,exist_ok=True)
    path=directory/(packet["packet_id"]+".json")
    body=json.dumps({"schema":"stegverse.organization-ingress-materialization/v1","organization":ORG,
                     "repository":ORG+"/"+repository,"packet":packet,"authority_effect":"NONE"},indent=2,sort_keys=True)+"\n"
    if path.exists():
        if path.read_text()!=body: raise Refused("MATERIALIZATION_WRITE_ONCE_COLLISION")
    else: path.write_text(body)
    return path

def _ingest(root:Path, frame:dict[str,Any])->dict[str,Any]:
    subject={"intended_action":"CROSS_AN_ORGANIZATION_BOUNDARY_INBOUND","frame_sha256":frame.get("frame_sha256")}
    try:
        try: packet=kernel.recover_packet(frame)
        except (ValueError,KeyError) as exc: raise Refused("FRAME_UNVERIFIABLE",str(exc))
        manifest=packet.get("payload",{}).get("manifest")
        repository=(manifest or {}).get("destination",{}).get("repository") if isinstance(manifest,dict) else None
        if repository is None:
            try: result=kernel.dispatch(root,packet)
            except ValueError as exc: raise Refused("BOUNDARY_DISPATCH_REFUSED",str(exc))
            outcome={"disposition":ALLOW,"packet_id":packet["packet_id"],"origin_organization":packet["origin"]["org"],
                     "destination_service":result["service_id"],"terminal_receipt_id":result["reconstruction"]["terminal_receipt_id"]}
            return {"transition_class":INGRESS_CONSUMED,**outcome,**record(INGRESS_CONSUMED,subject=subject,outcome=outcome,root=root)}
        manifest=require_manifest(manifest)
        if manifest["destination"]["organization"]!=ORG: raise Refused("MANIFEST_DESTINATION_ORGANIZATION_MISMATCH")
        standing=kernel.node_standing(root)
        try: standing.require(standing.load_contract(root),packet)
        except SystemExit as refused: raise Refused("NODE_STANDING_REFUSED",str(refused))
        name=repository.split("/",1)[1] if repository.startswith(ORG+"/") else repository
        if name not in organization_repositories(root): raise Refused("DESTINATION_REPOSITORY_DOES_NOT_EXIST")
        path=_materialize(root,name,packet)
    except Refused as refused:
        outcome={"disposition":DENY,"failed_predicate":refused.failed_predicate,"reason":refused.reason,
                 "packet_id":frame.get("packet_id"),"origin_organization":frame.get("origin_org")}
        return {"transition_class":INGRESS_REFUSED,**outcome,**record(INGRESS_REFUSED,subject=subject,outcome=outcome,root=root)}
    outcome={"disposition":ALLOW,"packet_id":packet["packet_id"],"origin_organization":packet["origin"]["org"],
             "manifest_id":manifest["manifest_id"],"manifest_sha256":sha(manifest),"destination_repository":ORG+"/"+name,
             "materialization_sha256":sha(path.read_bytes())}
    return {"transition_class":INGRESS_MATERIALIZED,**outcome,"materialization_path":str(path),
            **record(INGRESS_MATERIALIZED,subject=subject,outcome=outcome,root=root)}

def ingress(*, mesh_root:Path|None=None, root:Path=ROOT)->list[dict[str,Any]]:
    """Consume every frame addressed to SV-LLM not already consumed. Never waits for one."""
    results=[]
    for item in kernel.scan_addressed_frames(ORG,root=mesh_root,seen=kernel.federation_seen_frame_names(root)):
        result=_ingest(root,item["frame"])
        kernel.mark_federation_frame_seen(root,item["path"],item["frame"],{"status":result["transition_class"]})
        results.append(result)
    return results

def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    e=sub.add_parser("egress"); e.add_argument("--manifest",required=True); e.add_argument("--standing",required=True)
    sub.add_parser("ingress")
    sub.add_parser("open-ledger")
    ns=p.parse_args()
    if ns.cmd=="open-ledger":
        out=open_organization_ledger()
    elif ns.cmd=="egress":
        out=egress(json.loads(Path(ns.manifest).read_text()),standing=json.loads(Path(ns.standing).read_text()))
    else:
        out=ingress()
    print(json.dumps(out,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
