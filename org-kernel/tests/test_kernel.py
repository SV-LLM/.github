#!/usr/bin/env python3
import importlib.util, json, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location("kernel","org-kernel/kernel.py"); k=importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
_peer_spec=importlib.util.spec_from_file_location("peer_organization","org-runtime/tests/peer_organization.py")
peers=importlib.util.module_from_spec(_peer_spec); _peer_spec.loader.exec_module(peers)

#: Every node below is a materialized organization: its own copy of the kernel,
#: emitters and ledger contracts, its own supplied ledgers and node state, and a
#: declared genesis. The kernel records every crossing it consumes or publishes
#: on its own organization's ledgers and refuses a root that is not its own, so
#: a bare directory standing in for a node would prove nothing.
STANDING={"mode":"ESTABLISH_GENESIS","node_ref":"kernel-test-node","predecessor":None}
ORGS=["AaCT-E","Admissible-Existence","AdmittedCode","Data-Continuation","ECAT-ICAT-Formal",
      "formalism-tests","GCAT-BCAT-Engine","Infrastructure-Continuity-Ventures","master-records",
      "StegGhost","StegVerse-002","StegVerse-Labs","StegVerse-org","Triad-Test"]

def node(base,org,role,*,directory=None,activation=None):
    peer=peers.materialize(base,org,[{"service_id":k.organization_slug(org)+"."+role,"repository":org+"/.github",
                                      "boundary_role":"BOUNDARY_LOCAL_"+("CONTROL" if role=="org-control" else "DIAGNOSTIC")}])
    if directory is not None:
        (peer.root/"org-boundary/registry/federation.json").write_text(json.dumps(directory))
    if activation is not None:
        (peer.root/"resident-runtime/activation-manifest.json").write_text(json.dumps(activation))
    return peer

with tempfile.TemporaryDirectory() as td:
 peer=node(Path(td),"Kernel-Test","boundary-diagnostic")
 packet={"schema_version":"stegverse.intr.org-boundary.v1","packet_id":"kernel-test-001","direction":"INGRESS",
 "origin":{"org":"Peer","service":"peer.boundary-diagnostic"},"destination":{"org":"Kernel-Test","service":"kernel-test.boundary-diagnostic"},
 "carrier":{"kind":"HB_DERIVED","reference":"canonical"},"intr_profile":"stegverse.intr.org-boundary.v1",
 "transition":{"reference":"diagnostic","authority_effect":"NONE"},"payload":{"probe":"ping"},"standing":STANDING,
 "evidence":{"ingress_receipt":None,"dispatch_receipt":None,"consumption_receipt":None,"egress_receipt":None,"reconstruction_reference":None}}
 frame=k.carrier_frame(packet,now_ns=k.HB_ANCHOR_UNIX_NS+1_000_000_000)
 recovered=k.recover_packet(frame); assert recovered==packet
 # A direct ingest is a recorded crossing: without custody it refuses before dispatching.
 try:
     peer.kernel.ingest_frame(peer.root,frame); raise AssertionError("an unrecorded ingest was accepted")
 except ValueError as refused:
     assert "ledger_location_required_from_materializer" in str(refused)
 out=peer.kernel.ingest_frame(peer.root,frame,**peer.ledgers()); assert out["status"]=="CONSUMED"; assert out["execution_result"]["reconstruction"]["status"]=="RECONSTRUCTED"
 assert [x["kind"] for x in out["execution_result"]["receipts"]]==["INGRESS_ACCEPTED","DISPATCHED","CONSUMED","RESULT_BOUND","EGRESS_EMITTED"]
 # A diagnostic is the processor, so nothing selected one, and the result says
 # so rather than leaving a declaration looking like one that was processed.
 assert out["execution_result"]["processing_selection"]=="BOUNDARY_LOCAL_NO_PROCESSOR_SELECTED"
 assert out["execution_result"]["declared_capability_processed"] is False
 assert out["organization_record"]["organization_receipt_sha256"].startswith("sha256:")
 assert {r["transition_class"] for r in peer.receipts("repo")}=={"ORGANIZATION_LEDGER_OPENED","ORGANIZATION_FEDERATION_CROSSING_CONSUMED"}
 print("PASS")


# federation mesh source-level proof
with tempfile.TemporaryDirectory() as td:
    mesh=Path(td)/"mesh"
    a=node(Path(td),"Org-A","boundary-diagnostic"); b=node(Path(td),"Org-B","boundary-diagnostic")
    packet=a.kernel.build_packet(origin_org="Org-A",origin_service="org-a.boundary-diagnostic",
                                 destination_org="Org-B",destination_service="org-b.boundary-diagnostic",
                                 payload={"probe":"mesh"},standing=STANDING,packet_id="mesh-a-to-b-001")
    # Publishing is a recorded emission: without the organization's custody it refuses.
    try:
        a.kernel.publish_packet(packet,root=mesh,epoch=200); raise AssertionError("an unrecorded publish was accepted")
    except ValueError as refused:
        assert "crossing_custody_required_from_recording_operation" in str(refused)
    assert not mesh.exists()
    pub=a.publish(packet,mesh_root=mesh,now_ns=k.HB_ANCHOR_UNIX_NS+2_000_000_000)
    assert Path(pub["path"]).exists() and pub["organization_record"]["organization_receipt_sha256"]
    assert [r["transition_class"] for r in a.receipts("repo") if r["transition_class"]!="ORGANIZATION_LEDGER_OPENED"]==["ORGANIZATION_FEDERATION_CROSSING_EMITTED"]
    assert a.consume_addressed(mesh_root=mesh)==[]
    consumed=b.consume_addressed(mesh_root=mesh)
    assert len(consumed)==1
    assert consumed[0]["result"]["status"]=="CONSUMED"
    assert consumed[0]["result"]["execution_result"]["reconstruction"]["status"]=="RECONSTRUCTED"
    assert consumed[0]["organization_record"]["organization_receipt_sha256"]
print("FEDERATION_PASS")


# 14-node ecosystem-wide communication fanout / aggregation proof
with tempfile.TemporaryDirectory() as td:
    mesh=Path(td)/"mesh"
    nodes={org:node(Path(td),org,"org-control") for org in ORGS}
    origin=nodes["StegVerse-Labs"]
    pub=origin.kernel.publish_ecosystem_message(
        origin_org="StegVerse-Labs",
        origin_service="stegverse-labs.org-control",
        organizations=ORGS,
        standing=STANDING,
        message_class="ecosystem.monitor.request",
        subject="ecosystem-broadcast-001",
        body={"monitor":"runtime-status"},
        requested_action="REPORT_STATUS",
        communication_id="ecosystem-broadcast-001",
        root=mesh,
        now_ns=k.HB_ANCHOR_UNIX_NS+3_000_000_000,
        custody=origin.custody()
    )
    assert pub["published_count"]==14
    assert sum(r["transition_class"]=="ORGANIZATION_FEDERATION_CROSSING_EMITTED" for r in origin.receipts("repo"))==14
    results={org:n.consume_addressed(mesh_root=mesh) for org,n in nodes.items()}
    rollup=k.aggregate_ecosystem_results("ecosystem-broadcast-001",results)
    assert rollup["complete"] is True
    assert rollup["consumed_count"]==14
    assert rollup["pending_count"]==0
print("ECOSYSTEM_BROADCAST_PASS")


# 14-node monitor request -> response roll-up proof
with tempfile.TemporaryDirectory() as td:
    mesh=Path(td)/"mesh"
    directory={"denominator":14,"organizations":[{"organization":org} for org in ORGS]}
    nodes={org:node(Path(td),org,"org-control",directory=directory,
                    activation={"state":"TEST_ACTIVE","kernel":{"version":"1.3.0"}}) for org in ORGS}
    origin=nodes["StegVerse-Labs"]
    pub=origin.kernel.publish_ecosystem_from_directory(
        origin.root,
        standing=STANDING,
        message_class="ecosystem.monitor.request",
        subject="ecosystem-monitor-response-001",
        body={"monitor":"resident-status"},
        requested_action="REPORT_STATUS",
        communication_id="ecosystem-monitor-response-001",
        mesh_root=mesh,
        now_ns=k.HB_ANCHOR_UNIX_NS+4_000_000_000,
        **origin.ledgers()
    )
    assert pub["published_count"]==14
    for org,n in nodes.items():
        n.consume(mesh_root=mesh,now_ns=k.HB_ANCHOR_UNIX_NS+4_100_000_000)
    roll=k.collect_ecosystem_responses("StegVerse-Labs","ecosystem-monitor-response-001",mesh_root=mesh)
    assert roll["response_count"]==14
    assert {x["organization"] for x in roll["organizations"]}==set(ORGS)

# 14-node work request -> local admission queue proof
with tempfile.TemporaryDirectory() as td:
    mesh=Path(td)/"mesh"
    directory={"denominator":14,"organizations":[{"organization":org} for org in ORGS]}
    nodes={org:node(Path(td),org,"org-control",directory=directory) for org in ORGS}
    origin=nodes["StegVerse-Labs"]
    pub=origin.kernel.publish_ecosystem_from_directory(
        origin.root,
        standing=STANDING,
        message_class="ecosystem.work.request",
        subject="ecosystem-work-intake-001",
        body={"goal":"perform local status reconciliation"},
        requested_action="RECONCILE_LOCAL_STATUS",
        communication_id="ecosystem-work-intake-001",
        mesh_root=mesh,
        now_ns=k.HB_ANCHOR_UNIX_NS+5_000_000_000,
        **origin.ledgers()
    )
    assert pub["published_count"]==14
    for org,n in nodes.items():
        n.consume(mesh_root=mesh,now_ns=k.HB_ANCHOR_UNIX_NS+5_100_000_000)
        # Work intake is this node's own state, at the location supplied to it,
        # never under the repository checkout.
        assert not (n.root/"resident-runtime/control").exists()
        inbox=list((n.node_state/"control/inbox").glob("*.json"))
        assert len(inbox)==1
        record=json.loads(inbox[0].read_text())
        assert record["state"]=="QUEUED_FOR_LOCAL_ADMISSION_EVALUATION"
        assert record["execution_authority_inferred"] is False
    roll=k.collect_ecosystem_responses("StegVerse-Labs","ecosystem-work-intake-001",mesh_root=mesh)
    assert roll["response_count"]==14
print("ECOSYSTEM_CONTROL_RESPONSE_PASS")


# durable federation replay/dedup proof
with tempfile.TemporaryDirectory() as td:
    mesh=Path(td)/"mesh"
    org="Replay-Test"
    n=node(Path(td),org,"org-control",directory={"denominator":1,"organizations":[{"organization":org}]},
           activation={"state":"TEST","kernel":{"version":"1.3.1"}})
    pub=n.kernel.publish_ecosystem_from_directory(
        n.root,
        standing=STANDING,
        message_class="ecosystem.communication",
        subject="dedup",
        body={"value":1},
        communication_id="ecosystem-dedup-001",
        mesh_root=mesh,
        now_ns=k.HB_ANCHOR_UNIX_NS+6_000_000_000,
        **n.ledgers()
    )
    first=n.consume(mesh_root=mesh,now_ns=k.HB_ANCHOR_UNIX_NS+6_100_000_000)
    second=n.consume(mesh_root=mesh,now_ns=k.HB_ANCHOR_UNIX_NS+6_200_000_000)
    assert len(first)==1
    assert len(second)==1 or len(second)==0
    # second cycle may see only the response addressed to self; it must not reconsume the original request.
    originals=[x for x in second if ((x.get("result") or {}).get("packet") or {}).get("packet_id")=="ecosystem-dedup-001:replay-test"]
    assert originals==[]
print("ECOSYSTEM_DEDUP_PASS")


# node-standing gate proof: kernel_required 1.3.0 declares this gate, so the
# gate is proven here rather than implied by the declared version.
with tempfile.TemporaryDirectory() as td:
    org="Gate-Test"
    n=node(Path(td),org,"org-control")
    custody=n.custody()

    # A standing-less packet cannot be constructed: `standing` has no default.
    try:
        k.build_packet(origin_org="Anyone-At-All",origin_service="anyone.org-control",
                       destination_org=org,destination_service="gate-test.org-control",
                       payload={"probe":"unstanding"})
        raise AssertionError("build_packet accepted a packet with no standing")
    except TypeError as expected:
        assert "standing" in str(expected)

    # A hand-forged envelope that skips the constructor is refused fail-closed,
    # as the contract's own disposition rather than a bare error.
    forged={"schema_version":k.PACKET_SCHEMA,"packet_id":"gate-test-001","direction":"INGRESS",
            "origin":{"org":"Anyone-At-All","service":"anyone.org-control"},
            "destination":{"org":org,"service":"gate-test.org-control"},
            "carrier":{"kind":"HB_DERIVED","reference":"org-federation"},
            "intr_profile":"stegverse.intr.org-boundary.v1",
            "transition":{"reference":"federation.v1","authority_effect":"NONE","conditions":[]},
            "payload":{"probe":"unstanding"},
            "evidence":{"ingress_receipt":None,"dispatch_receipt":None,"consumption_receipt":None,"egress_receipt":None,"reconstruction_reference":None}}
    try:
        n.kernel.dispatch(n.root,forged,custody=custody)
        raise AssertionError("dispatch consumed a crossing with no standing")
    except ValueError as refused:
        assert str(refused).startswith("node_standing_refused:"), refused
        assert "no-standing-declared" in str(refused), refused

    # Dispatch records nothing itself, so it refuses a caller without custody.
    try:
        n.kernel.dispatch(n.root,{**forged,"standing":STANDING})
        raise AssertionError("dispatch processed a crossing for a caller that cannot record it")
    except ValueError as refused:
        assert "crossing_custody_required_from_recording_operation" in str(refused), refused

    # The same crossing, carrying standing, is admitted and the resolved
    # standing travels on the result.
    admitted=n.kernel.dispatch(n.root,{**forged,"standing":STANDING},custody=custody)
    assert admitted["consumed"] is True
    assert admitted["application_result"]["execution_authority_inferred"] is False
    assert admitted["node_standing_disposition"]=="ALLOW"
    assert admitted["standing_mode"]=="ESTABLISH_GENESIS"
    assert admitted["standing_node_ref"]=="kernel-test-node"
    assert admitted["standing_generation"]==1
    # The gate makes the crossing provable by node chain. It does not validate
    # the caller-written origin string, and the result says so rather than
    # letting a reader of the chain assume otherwise -- the origin above is
    # still "Anyone-At-All" and the crossing is admitted on its standing.
    assert admitted["caller_editable_origin_established_identity"] is False
    assert admitted["structural_standing_only"] is True
    assert admitted["structural_standing_is_authenticated_standing"] is False
    assert admitted["standing_authority_effect"]=="NONE_STANDING_ONLY"
print("NODE_STANDING_GATE_PASS")
