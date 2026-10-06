#!/usr/bin/env python3
"""SV-LLM organization-crossing proof through the vendored kernel.

Uses this repository's real boundary registry and standing surfaces as the
SV-LLM root. Peers are synthetic roots carrying only their published
organization identity, so this proves SV-LLM's wiring, not a peer's runtime.
Source-level evidence only: no resident runtime is observed here.
"""
import importlib.util, json, shutil, tempfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("kernel",REPO/"org-kernel/kernel.py"); k=importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
ORG="SV-LLM"
CONTROL="sv-llm.org-control"
STANDING={"mode":"ESTABLISH_GENESIS","node_ref":"sv-llm-crossing-test-node","predecessor":None}
NOW=k.HB_ANCHOR_UNIX_NS+5_000_000_000

def peer_root(base:Path, org:str)->Path:
    root=base/org; (root/"org-boundary/registry").mkdir(parents=True)
    (root/"org-boundary/runtime").mkdir(parents=True); (root/"docs").mkdir(parents=True)
    shutil.copy2(REPO/"org-boundary/runtime/node_standing.py",root/"org-boundary/runtime/node_standing.py")
    shutil.copy2(REPO/"docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json",root/"docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json")
    slug=k.organization_slug(org)
    reg={"organization":org,"services":[{"service_id":slug+".org-control","repository":org+"/.github","boundary_role":"BOUNDARY_LOCAL_CONTROL",
         "accepts":["ecosystem.communication","ecosystem.monitor.request","ecosystem.work.request"]}]}
    (root/"org-boundary/registry/services.json").write_text(json.dumps(reg))
    return root

registry=k.load_registry(REPO)
assert registry["organization"]==ORG
assert {s["service_id"] for s in registry["services"]}=={CONTROL,"sv-llm.boundary-diagnostic"}
directory=k.load_federation_directory(REPO)
peers=[row["organization"] for row in directory["organizations"]]

with tempfile.TemporaryDirectory() as td:
    base=Path(td); mesh=base/"mesh"; sv=base/"sv-llm"
    shutil.copytree(REPO/"org-boundary",sv/"org-boundary"); shutil.copytree(REPO/"docs",sv/"docs")
    roots={org:peer_root(base,org) for org in peers}

    # EGRESS: SV-LLM -> every federation peer, addressed InTr frames on the shared spool.
    for org in peers:
        packet=k.build_packet(origin_org=ORG,origin_service=CONTROL,destination_org=org,
                              destination_service=k.organization_slug(org)+".org-control",
                              payload={"message_class":"ecosystem.monitor.request","subject":"sv-llm-egress-proof"},
                              standing=STANDING,packet_id=f"sv-llm-egress-{k.organization_slug(org)}")
        k.publish_packet(packet,root=mesh,now_ns=NOW)
    assert k.consume_addressed_frames(sv,mesh_root=mesh)==[]
    for org in peers:
        consumed=k.consume_addressed_frames(roots[org],mesh_root=mesh)
        assert len(consumed)==1, org
        ingested=consumed[0]["result"]; result=ingested["execution_result"]
        assert ingested["status"]=="CONSUMED" and ingested["packet"]["origin"]["org"]==ORG
        assert result["organization"]==org and result["reconstruction"]["status"]=="RECONSTRUCTED"
        frame=json.loads(Path(consumed[0]["path"]).read_text())
        assert frame["origin_org"]==ORG and frame["authority_effect"]=="NONE_CARRIER_ONLY"
    print("SV_LLM_EGRESS_PASS",len(peers))

    # INGRESS: a peer -> SV-LLM, consumed only by SV-LLM's real registry.
    packet=k.build_packet(origin_org="StegVerse-Labs",origin_service="stegverse-labs.org-control",destination_org=ORG,
                          destination_service=CONTROL,payload={"message_class":"ecosystem.monitor.request","subject":"sv-llm-ingress-proof"},
                          standing=STANDING,packet_id="sv-llm-ingress-001")
    k.publish_packet(packet,root=mesh,now_ns=NOW)
    consumed=k.consume_addressed_frames(sv,mesh_root=mesh)
    assert len(consumed)==1 and consumed[0]["result"]["status"]=="CONSUMED"
    result=consumed[0]["result"]["execution_result"]
    assert result["organization"]==ORG and result["service_id"]==CONTROL
    assert [x["kind"] for x in result["receipts"]]==["INGRESS_ACCEPTED","DISPATCHED","CONSUMED","RESULT_BOUND","EGRESS_EMITTED"]
    for r in roots.values():
        assert all(x["result"]["packet"]["packet_id"]!="sv-llm-ingress-001" for x in k.consume_addressed_frames(r,mesh_root=mesh))
    print("SV_LLM_INGRESS_PASS")

    # Fail closed: an unregistered SV-LLM service is refused, never auto-created.
    bad=k.build_packet(origin_org="StegVerse-Labs",origin_service="stegverse-labs.org-control",destination_org=ORG,
                       destination_service="sv-llm.unregistered",payload={},standing=STANDING,packet_id="sv-llm-unregistered-001")
    try: k.dispatch(sv,bad); raise AssertionError("unregistered service dispatched")
    except ValueError as e: assert str(e)=="unknown_service"
    print("SV_LLM_FAIL_CLOSED_PASS")
