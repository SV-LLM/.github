#!/usr/bin/env python3
"""SV-LLM organization crossings: manifest-bound, ledgered, never awaiting.

Runs against a copy of this repository so ledgers, spool and materializations
land in a temporary tree. Peers are synthetic roots carrying only their
published organization identity: this proves SV-LLM's boundary, not a peer's.
Source-level evidence only.
"""
import importlib.util, json, os, shutil, tempfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
STANDING={"mode":"ESTABLISH_GENESIS","node_ref":"sv-llm-crossing-test-node","predecessor":None}

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def peer_root(base,org,k):
    root=base/"peers"/org; (root/"org-boundary/registry").mkdir(parents=True)
    shutil.copytree(REPO/"org-boundary/runtime",root/"org-boundary/runtime"); (root/"docs").mkdir()
    shutil.copy2(REPO/"docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json",root/"docs")
    slug=k.organization_slug(org)
    (root/"org-boundary/registry/services.json").write_text(json.dumps({"organization":org,"services":[
        {"service_id":slug+".org-control","repository":org+"/.github","boundary_role":"BOUNDARY_LOCAL_CONTROL"}]}))
    return root

def chain(ledger):
    head=json.loads((ledger/"HEAD.json").read_text())["receipt_sha256"]; rows=[]
    while head:
        r=json.loads((ledger/"receipts"/(head.split(":",1)[1]+".json")).read_text()); rows.append(r); head=r["previous_receipt_sha256"]
    return rows[::-1]

with tempfile.TemporaryDirectory() as td:
    base=Path(td); root=base/"sv-llm"
    shutil.copytree(REPO,root,ignore=shutil.ignore_patterns(".git","__pycache__","materialized"))
    os.environ["STEGVERSE_REPO_LEDGER_ROOT"]=str(base/"repo-ledger"); os.environ["STEGVERSE_ORG_LEDGER_ROOT"]=str(base/"org-ledger")
    mesh=base/"mesh"
    c=load("crossing",root/"org-runtime/crossing.py"); k=c.kernel
    assert c.ORG=="SV-LLM"
    peers=[r["organization"] for r in k.load_federation_directory(root)["organizations"] if r["organization"]!=c.ORG]

    # EGRESS to every peer. No peer root exists yet: the transition succeeds at egress, nothing waits.
    for org in peers:
        out=c.egress({"manifest_id":"egress-"+org,"destination":{"organization":org},"payload":{"probe":"egress"}},
                     standing=STANDING,mesh_root=mesh,root=root)
        assert out["transition_class"]=="ORGANIZATION_EGRESS_EMITTED" and out["disposition"]=="ALLOW" and out["awaits_receiver"] is False
        assert Path(out["spool_path"]).exists()
    roots={org:peer_root(base,org,k) for org in peers}
    for org in peers:
        got=k.consume_addressed_frames(roots[org],mesh_root=mesh)
        assert len(got)==1 and got[0]["result"]["status"]=="CONSUMED" and got[0]["result"]["packet"]["origin"]["org"]=="SV-LLM", org
    print("SV_LLM_EGRESS_PASS",len(peers))

    # EGRESS refusals are transitions too, and are recorded.
    for manifest,predicate in (({"manifest_id":"x","destination":{"organization":"Not-An-Org"}},"DESTINATION_NOT_IN_FEDERATION_DIRECTORY"),
                               ({"manifest_id":"y","destination":{"organization":"SV-LLM"}},"DESTINATION_IS_THIS_ORGANIZATION"),
                               ({"destination":{"organization":"StegVerse-Labs"}},"MANIFEST_ID_MISSING")):
        out=c.egress(manifest,standing=STANDING,mesh_root=mesh,root=root)
        assert out["transition_class"]=="ORGANIZATION_EGRESS_REFUSED" and out["failed_predicate"]==predicate and out["org_receipt_sha256"]
    print("SV_LLM_EGRESS_REFUSAL_RECORDED_PASS")

    # INGRESS: the manifest names an existing SV-LLM repository. No endpoint profile is declared or needed.
    def send(pid,payload,service="sv-llm.org-control"):
        k.publish_packet(k.build_packet(origin_org="StegVerse-Labs",origin_service="stegverse-labs.org-control",destination_org="SV-LLM",
                         destination_service=service,payload=payload,standing=STANDING,packet_id=pid),root=mesh)
    send("in-sandbox",{"manifest":{"manifest_id":"m-sandbox","destination":{"organization":"SV-LLM","repository":"sandbox"},"payload":{"work":"w"}}})
    send("in-missing-repo",{"manifest":{"manifest_id":"m-missing","destination":{"organization":"SV-LLM","repository":"does-not-exist"}}})
    send("in-wrong-org",{"manifest":{"manifest_id":"m-wrong","destination":{"organization":"AaCT-E","repository":"sandbox"}}})
    send("in-control",{"message_class":"ecosystem.monitor.request","subject":"probe"})
    send("in-unregistered",{"probe":1},service="sv-llm.unregistered")
    results={r["packet_id"]:r for r in c.ingress(mesh_root=mesh,root=root)}
    assert results["in-sandbox"]["transition_class"]=="ORGANIZATION_INGRESS_MATERIALIZED"
    assert results["in-sandbox"]["destination_repository"]=="SV-LLM/sandbox" and Path(results["in-sandbox"]["materialization_path"]).exists()
    assert results["in-missing-repo"]["failed_predicate"]=="DESTINATION_REPOSITORY_DOES_NOT_EXIST"
    assert results["in-wrong-org"]["failed_predicate"]=="MANIFEST_DESTINATION_ORGANIZATION_MISMATCH"
    assert results["in-control"]["transition_class"]=="ORGANIZATION_INGRESS_CONSUMED"
    assert results["in-unregistered"]["failed_predicate"]=="BOUNDARY_DISPATCH_REFUSED"
    assert all(r["org_receipt_sha256"] for r in results.values())
    assert c.ingress(mesh_root=mesh,root=root)==[]   # consumed once; an empty spool records nothing
    print("SV_LLM_INGRESS_PASS")

    # Every disposition is on both ledgers, in one unbroken chain each.
    repo_chain=chain(base/"repo-ledger"); org_chain=chain(base/"org-ledger")
    expected=len(peers)+3+5
    assert len(repo_chain)==expected and len(org_chain)==expected
    assert all(r["repository"]=="SV-LLM/.github" for r in repo_chain)
    assert [o["repo_receipt_sha256"] for o in org_chain]==[r["receipt_sha256"] for r in repo_chain]
    assert all(o["organization"]=="SV-LLM" and o["authority_effect"]=="NONE" for o in org_chain)
    print("SV_LLM_LEDGER_CHAIN_PASS",expected)
