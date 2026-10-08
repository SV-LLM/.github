#!/usr/bin/env python3
"""SV-LLM egress addressed by a manifest-declared capability.

A destination declaring `capability` is addressed to the peer's service for that
capability (ORGANIZATION_SLUG_DOT_CAPABILITY_PROFILE_ID) and carries the
manifest in payload.manifest as an SDK manifest crossing payload. Without a
capability the peer's org-control service is addressed, as before. A capability
that is not a profile id, or one with no carried manifest, is refused, recorded
and publishes nothing. Runs against a copy of this repository. Source-level
evidence only.
"""
import importlib.util, json, os, shutil, tempfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
STANDING={"mode":"ESTABLISH_GENESIS","node_ref":"sv-llm-crossing-test-node","predecessor":None}
PEER="StegVerse-org"

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def frames(mesh):
    return sorted(p for p in mesh.rglob("*.json")) if mesh.exists() else []

with tempfile.TemporaryDirectory() as td:
    base=Path(td); root=base/"sv-llm"
    shutil.copytree(REPO,root,ignore=shutil.ignore_patterns(".git","__pycache__","materialized"))
    os.environ["STEGVERSE_REPO_LEDGER_ROOT"]=str(base/"repo-ledger"); os.environ["STEGVERSE_ORG_LEDGER_ROOT"]=str(base/"org-ledger")
    mesh=base/"mesh"
    c=load("crossing",root/"org-runtime/crossing.py"); k=c.kernel
    c.open_organization_ledger(root=root)

    # A reply declaring the sdk-manifest-ingress capability reaches that service with the SDK manifest payload.
    carried={"manifest_id":"sdk-governance-1","kind":"sdk-manifest-builder.governance","body":{"decision":"requested"}}
    reply={"manifest_id":"reply-sdk-1","destination":{"organization":PEER,"capability":"sdk-manifest-ingress",
           "surface":"SDK-MANIFEST-ECOSYSTEM-TRANSITION"},"payload":{"manifest":carried}}
    out=c.egress(reply,standing=STANDING,mesh_root=mesh,root=root)
    assert out["transition_class"]=="ORGANIZATION_EGRESS_EMITTED" and out["disposition"]=="ALLOW", out
    assert out["destination_service"]=="stegverse-org.sdk-manifest-ingress", out
    packet=k.recover_packet(json.loads(Path(out["spool_path"]).read_text()))
    assert packet["destination"]=={"org":PEER,"service":"stegverse-org.sdk-manifest-ingress"}
    assert packet["payload"]=={"schema":"stegverse.sdk-manifest-crossing-payload/v1",
                               "declared_transition_surface":"SDK-MANIFEST-ECOSYSTEM-TRANSITION",
                               "manifest":carried,"manifest_sha256":k.sha(carried)}
    print("SV_LLM_CAPABILITY_EGRESS_PASS")

    # Without a capability the reply is addressed to the peer's org-control service, carrying the whole manifest.
    plain={"manifest_id":"reply-plain-1","destination":{"organization":PEER},"payload":{"manifest":carried}}
    out=c.egress(plain,standing=STANDING,mesh_root=mesh,root=root)
    assert out["transition_class"]=="ORGANIZATION_EGRESS_EMITTED" and out["destination_service"]=="stegverse-org.org-control", out
    packet=k.recover_packet(json.loads(Path(out["spool_path"]).read_text()))
    assert packet["destination"]["service"]=="stegverse-org.org-control" and packet["payload"]=={"manifest":plain}
    print("SV_LLM_NO_CAPABILITY_EGRESS_UNCHANGED_PASS")

    # Fail closed: a declared capability with no carried manifest, or one that is not a profile id.
    refusals=(
        ({"manifest_id":"r1","destination":{"organization":PEER,"capability":"sdk-manifest-ingress"}},"MANIFEST_CAPABILITY_PAYLOAD_MISSING"),
        ({"manifest_id":"r2","destination":{"organization":PEER,"capability":"sdk-manifest-ingress"},"payload":{"manifest":"not-an-object"}},
         "MANIFEST_CAPABILITY_PAYLOAD_MISSING"),
        ({"manifest_id":"r3","destination":{"organization":PEER,"capability":"sdk-manifest-ingress"},"payload":["not-an-object"]},
         "MANIFEST_CAPABILITY_PAYLOAD_MISSING"),
        ({"manifest_id":"r4","destination":{"organization":PEER,"capability":"SDK_Manifest.Ingress"},"payload":{"manifest":carried}},
         "MANIFEST_CAPABILITY_INVALID"),
        ({"manifest_id":"r5","destination":{"organization":PEER,"capability":"org-control.evil"},"payload":{"manifest":carried}},
         "MANIFEST_CAPABILITY_INVALID"),
        ({"manifest_id":"r6","destination":{"organization":PEER,"capability":""},"payload":{"manifest":carried}},"MANIFEST_CAPABILITY_INVALID"),
        ({"manifest_id":"r7","destination":{"organization":PEER,"capability":None},"payload":{"manifest":carried}},"MANIFEST_CAPABILITY_INVALID"),
    )
    for manifest,predicate in refusals:
        before=frames(mesh)
        out=c.egress(manifest,standing=STANDING,mesh_root=mesh,root=root)
        assert out["transition_class"]=="ORGANIZATION_EGRESS_REFUSED" and out["disposition"]=="DENY", out
        assert out["failed_predicate"]==predicate and out["org_receipt_sha256"], (manifest["manifest_id"],out)
        assert frames(mesh)==before, "a refused capability egress published a frame"
    print("SV_LLM_CAPABILITY_REFUSAL_RECORDED_PASS",len(refusals))
