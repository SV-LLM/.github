"""SV-LLM's manifest-directed organization ledger append path (SV-LLM/.github#30 W4).

The path is adopted from StegVerse-org/.github (data/organization-role-reference-adoption.json):
a request committed under .stegverse/transition-requests/ is built by the
pinned StegVerse-SDK Manifest Builder, received by
resident-runtime/organization_manifest_ingress.py, appended to the repository
and organization ledgers on the designated ref, published fast-forward only and
read back from a fresh fetch.

These tests cover the contract binding, request validation, the dispatch
guards of .github/workflows/organization-ledger-transition.yml, and a local
end-to-end dry run that executes that workflow's own step scripts against a
temporary local bare origin with the real SDK. Nothing here reaches a network
or the published ledger ref, and nothing here is a runtime observation: every
ledger these tests write is a temporary one.

The SDK is located by STEGVERSE_SDK_ROOT (a checkout at the pin), or ./sdk.
With STEGVERSE_SDK_REQUIRED=1 (CI) a missing SDK fails instead of skipping.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PIN = "74d9b473aa415b06a9d550c28b2779a691b4ba32"
REFERENCE_COMMIT = "10d141041fd0fa3b8bd696f6c6236bef199845b8"
REQUEST = ".stegverse/transition-requests/SV-LLM-W04-MANIFEST-DIRECTED-APPEND-001.json"
WORKFLOW = ROOT / ".github/workflows/organization-ledger-transition.yml"
LEDGER_REF = "refs/stegverse/organization-ledger"
BOUNDARY = json.loads((ROOT / "org-runtime/interlock-intr.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "org-boundary/registry/services.json").read_text(encoding="utf-8"))
ORG_CONTRACT = json.loads((ROOT / ".stegverse/transition-ledger/org-contract.json").read_text(encoding="utf-8"))
REPO_LOCATION = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text(
    encoding="utf-8"))["repository_ledger_location"]
ADDRESS = "sv-llm.sdk-manifest-ingress"
OPERATION_ID = "ORGANIZATION_SDK_MANIFEST_INGRESS"


def _sdk_root():
    declared = os.environ.get("STEGVERSE_SDK_ROOT")
    for candidate in ([Path(declared)] if declared else []) + [ROOT / "sdk"]:
        if (candidate / "stegverse/manifest_builder.py").is_file():
            return candidate.resolve()
    return None


SDK_ROOT = _sdk_root()
if SDK_ROOT is not None and str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))
try:
    from stegverse.manifest_builder import build_manifest
    from stegverse.manifest_contract import validate_ingress_manifest
    from stegverse.manifest_state_transition_runtime import derive_execution_request
    SDK = True
except ImportError:  # the SDK is absent; SDK tests skip, or fail when required
    SDK = False
SDK_REQUIRED = os.environ.get("STEGVERSE_SDK_REQUIRED") == "1"
needs_sdk = unittest.skipUnless(SDK, "StegVerse-SDK checkout not on the import path")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capability = load("w04_capability_ingress", "org-boundary/runtime/capability_ingress.py")
runtime_boundary = load("w04_runtime_boundary", "org-runtime/runtime_boundary.py")
inputs = load("w04_run_inputs", "resident-runtime/manifest_directed_run_inputs.py")
if SDK:
    ingress = load("w04_organization_manifest_ingress", "resident-runtime/organization_manifest_ingress.py")


def binding(profile_id):
    matches = [entry for entry in BOUNDARY["ingress"]["capability_endpoint_bindings"]
               if entry.get("profile_id") == profile_id]
    assert len(matches) == 1, profile_id
    return matches[0]


def row(service_id):
    return next(item for item in REGISTRY["services"] if item["service_id"] == service_id)


def committed_request():
    return json.loads((ROOT / REQUEST).read_text(encoding="utf-8"))


def built(**overrides):
    arguments = {**committed_request()["build_manifest"], **overrides}
    return build_manifest(**arguments)


class SdkPresence(unittest.TestCase):
    def test_the_sdk_is_present_where_ci_requires_it(self):
        if SDK_REQUIRED:
            self.assertTrue(SDK, "STEGVERSE_SDK_REQUIRED=1 but the SDK is not importable")
            head = subprocess.run(["git", "-C", str(SDK_ROOT), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(head, SDK_PIN)

    def test_the_workflow_pins_the_sdk_and_installs_nothing(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("repository: StegVerse-org/StegVerse-SDK", text)
        self.assertEqual(re.findall(r"ref: ([0-9a-f]{40})", text), [SDK_PIN])
        self.assertNotIn("pip install", text)
        self.assertIn('echo "PYTHONPATH=$GITHUB_WORKSPACE/sdk" >> "$GITHUB_ENV"', text)

    def test_the_workflow_uses_no_action_beyond_checkout(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        actions = set(re.findall(r"uses: ([^@\s]+)@", text))
        self.assertEqual(actions, {"actions/checkout"})


class ContractBinding(unittest.TestCase):
    """sdk-manifest-ingress / SUBMIT_MANIFEST resolves to one operation owned here."""

    def test_the_binding_names_this_organizations_receiving_operation(self):
        declared = binding("sdk-manifest-ingress")
        self.assertEqual((declared["profile_name"], declared["operation"]), ("SDK:ManifestIngress", "SUBMIT_MANIFEST"))
        receiving = declared["receiving_operation"]
        self.assertEqual(receiving["owner_repository"], "SV-LLM/.github")
        self.assertEqual(receiving["owner_repository"], BOUNDARY["owner_repository"])
        self.assertEqual(receiving["operation_id"], OPERATION_ID)
        self.assertEqual(receiving["operation"], "resident-runtime/organization_manifest_ingress.py")
        self.assertEqual(receiving["addressed_service"], ADDRESS)
        self.assertEqual(declared["binding_role"], "ORGANIZATION_RECEIVING_OPERATION_RESOLUTION")
        self.assertEqual(declared["authority_effect"], "NONE_BINDING_ONLY")
        for flag in ("grants_routing_authority", "grants_admission_authority", "grants_execution_authority",
                     "environment_selected_ingress"):
            self.assertIs(declared[flag], False, flag)
        for record in (declared, receiving):
            for name in ("routing_authority_constraint", "admission_authority_constraint",
                         "execution_authority_constraint", "time_constraint"):
                self.assertEqual(record[name], "CONSTRAINT_VARIABLE", name)
            self.assertEqual(record["disposition_role"], "TRANSITION_EVIDENCE_ONLY")

    def test_the_address_is_a_registry_row_and_not_an_admission(self):
        served = row(ADDRESS)
        self.assertEqual(served["boundary_role"], capability.ROLE)
        self.assertEqual(served["capability_profile_id"], "sdk-manifest-ingress")
        self.assertIs(served["selects_processing_at_this_address"], False)
        self.assertNotIn("endpoint_adapter", served)
        self.assertNotIn("admits_processing", served)
        resolved = capability.resolve(ROOT, served)
        self.assertEqual(resolved["receiving_operation_id"], OPERATION_ID)
        self.assertEqual(resolved["resolution_source"], "ORGANIZATION_CAPABILITY_OVERLAY")

    def test_the_boundary_still_validates(self):
        report = runtime_boundary.validate()
        self.assertIs(report["valid"], True, report["checks"])

    def test_one_route_receives_a_submitted_manifest(self):
        # No second route: the inter-organization ingress stays crossing.py's,
        # and SUBMIT_MANIFEST resolves to exactly one binding and one module.
        self.assertEqual(BOUNDARY["ingress"]["receiving_operation"]["operation_id"], "ORGANIZATION_INTER_ORG_INGRESS")
        submit = [b for b in BOUNDARY["ingress"]["capability_endpoint_bindings"] if b["operation"] == "SUBMIT_MANIFEST"]
        self.assertEqual(len(submit), 1)
        named = [b for b in BOUNDARY["ingress"]["capability_endpoint_bindings"]
                 if b["receiving_operation"]["operation"] == "resident-runtime/organization_manifest_ingress.py"]
        self.assertEqual(named, submit)
        rows = [r for r in REGISTRY["services"] if r.get("capability_profile_id") == "sdk-manifest-ingress"]
        self.assertEqual([r["service_id"] for r in rows], [ADDRESS])
        self.assertNotIn("capability_destination_bindings", BOUNDARY["egress"])

    def test_the_ledger_contracts_bind_this_organization_and_one_ref(self):
        self.assertEqual(ORG_CONTRACT["organization_ledger_repository"], BOUNDARY["owner_repository"])
        self.assertEqual(ORG_CONTRACT["organization"], BOUNDARY["organization"])
        self.assertEqual(ORG_CONTRACT["organization_ledger_ref"], LEDGER_REF)
        self.assertEqual(REPO_LOCATION["ref"], LEDGER_REF)
        self.assertEqual(ORG_CONTRACT["write_mode"], "MANIFEST_DIRECTED_APPEND")

    def test_the_adoption_names_the_reference_commit_and_sdk_pin(self):
        record = json.loads((ROOT / "data/organization-role-reference-adoption.json").read_text())
        self.assertEqual(record["reference"]["commit"], REFERENCE_COMMIT)
        self.assertEqual(record["sdk"]["commit"], SDK_PIN)
        entry = record["files"]["resident-runtime/organization_manifest_ingress.py"]
        self.assertEqual(entry["rule"], "declared_substitutions")
        self.assertEqual(sum(s["count"] for s in entry["substitutions"]), 28)
        boundary_ci = (ROOT / ".github/workflows/org-runtime-boundary.yml").read_text()
        self.assertIn("ref: " + REFERENCE_COMMIT, boundary_ci)

    @needs_sdk
    def test_the_identity_is_read_from_this_organizations_boundary(self):
        self.assertEqual(ingress.OWNER_REPOSITORY, "SV-LLM/.github")
        self.assertEqual(ingress.ORGANIZATION, "SV-LLM")
        self.assertEqual(ingress.OPERATION_ID, OPERATION_ID)

    @needs_sdk
    def test_the_sdk_resolves_the_destination_to_this_binding(self):
        request = derive_execution_request(built(), BOUNDARY)
        destination = request["manifest_declared_destination"]
        self.assertEqual(destination["organization"], "SV-LLM")
        self.assertEqual(destination["owner_repository"], "SV-LLM/.github")
        self.assertEqual(destination["receiving_operation"]["operation_id"], OPERATION_ID)
        self.assertEqual(ingress.bound_here(request)["addressed_service"], ADDRESS)


class RequestValidation(unittest.TestCase):
    def requests(self):
        return sorted((ROOT / ".stegverse/transition-requests").glob("*.json"))

    def test_every_committed_request_is_well_formed(self):
        self.assertTrue(self.requests())
        for path in self.requests():
            request = json.loads(path.read_text())
            self.assertEqual(request["schema"], "stegverse.organization-transition-request/v1")
            self.assertEqual(request["request_id"], path.stem)
            self.assertTrue(request["owning_existing_goal"])
            self.assertIn("predecessor", request["standing"])
            self.assertNotEqual(("build_manifest" in request), ("manifest" in request), path.name)
            # No mesh lane is adopted here; a request declaring one would be refused.
            self.assertNotIn("mesh_root", request, path.name)

    def test_the_first_request_is_w04s_own_registered_transition(self):
        request = committed_request()
        self.assertEqual(request["owning_existing_goal"], "SVORG-LLM-ORG-FOUNDATION-001")
        self.assertEqual(request["registered_task"], "SVORG-LLM-ORG-FOUNDATION-001-W04-CANONICAL-RUNTIME-SUBSTRATE")
        arguments = request["build_manifest"]
        self.assertIs(arguments["data"]["external_side_effect"], False)
        self.assertIs(arguments["processor_request"]["mutation_permitted"], False)
        self.assertIs(arguments["publisher_required"], False)
        self.assertEqual(request["standing"]["mode"], "ESTABLISH_GENESIS")

    @needs_sdk
    def test_the_request_builds_one_canonical_manifest(self):
        def canonical_of(manifest):
            validate_ingress_manifest(manifest)
            return ingress.derive_execution_request(manifest, ingress.boundary())["canonical_manifest_sha256"]
        first = inputs.committed_manifest(committed_request(), build=build_manifest, canonical_of=canonical_of)
        second = inputs.committed_manifest(committed_request(), build=build_manifest, canonical_of=canonical_of)
        self.assertEqual(first["disposition"], "ALLOW", first)
        self.assertEqual(first["source"], "BUILT_BY_PINNED_SDK")
        self.assertEqual(first["canonical_manifest_sha256"], second["canonical_manifest_sha256"])
        self.assertRegex(first["canonical_manifest_sha256"], r"^[0-9a-f]{64}$")

    @needs_sdk
    def test_malformed_requests_are_refused_with_six_fields(self):
        def canonical_of(manifest):
            validate_ingress_manifest(manifest)
            return ingress.derive_execution_request(manifest, ingress.boundary())["canonical_manifest_sha256"]
        request = committed_request()
        manifest = built()
        cases = {
            "TRANSITION_REQUEST_MANIFEST_FORM_INVALID": {**request, "manifest": manifest},
            "EXACT_MANIFEST_UNBOUND": {k: v for k, v in {**request, "manifest": manifest}.items() if k != "build_manifest"},
            "EXACT_MANIFEST_DIGEST_MISMATCH": {**{k: v for k, v in request.items() if k != "build_manifest"},
                                               "manifest": manifest, "expected_canonical_manifest_sha256": "0" * 64},
            "TRANSITION_REQUEST_NOT_BUILDABLE": {**request, "build_manifest": {**request["build_manifest"], "nope": 1}},
        }
        for code, value in cases.items():
            refused = inputs.committed_manifest(value, build=build_manifest, canonical_of=canonical_of)
            self.assertEqual(refused["disposition"], "FAIL_CLOSED", code)
            self.assertEqual(refused["failure_code"], code)
            for field in ("failed_predicate", "required_evidence_or_repair", "retry_entrypoint", "next_attempt"):
                self.assertTrue(refused.get(field), (code, field))

    def test_a_declared_mesh_root_is_resolved_and_the_workflow_refuses_it(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "r.json"
            path.write_text(json.dumps({**committed_request(), "mesh_root": "git+x#refs/m"}))
            self.assertEqual(inputs.transition_mesh_root("", [str(path)])["mesh_root"], "git+x#refs/m")
            self.assertEqual(inputs.transition_mesh_root("", [str(ROOT / REQUEST)])["mesh_root"], "")
        self.assertIn("MESH_LANE_NOT_ADOPTED", WORKFLOW.read_text())


@needs_sdk
class Receive(unittest.TestCase):
    """The receiving operation against temporary POSIX ledgers."""

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        previous = {k: os.environ.get(k) for k in ("STEGVERSE_REPO_LEDGER_ROOT", "STEGVERSE_ORG_LEDGER_ROOT")}
        os.environ["STEGVERSE_REPO_LEDGER_ROOT"] = str(self.work / "repo")
        os.environ["STEGVERSE_ORG_LEDGER_ROOT"] = str(self.work / "org")
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in previous.items()])

    def receipts(self, level, schema):
        return [json.loads(p.read_text()) for p in (self.work / level).rglob("*.json")
                if json.loads(p.read_text()).get("schema") == schema]

    def receive(self, manifest=None, standing="default", **extra):
        standing = committed_request()["standing"] if standing == "default" else standing
        return ingress.receive(manifest or built(), registry=REGISTRY, standing=standing,
                               packet_id="w04-test", hb_epoch=32, **extra)

    def test_the_committed_manifest_is_received_and_recorded_at_both_levels(self):
        result = self.receive()
        self.assertEqual(result["disposition"], "ALLOW", result.get("detail"))
        self.assertEqual(result["organization"], "SV-LLM")
        self.assertEqual(result["owner_repository"], "SV-LLM/.github")
        self.assertEqual(result["resolved_service_id"], "sv-llm.boundary-diagnostic")
        self.assertIs(result["organization_receipt_observed"], True)
        self.assertIs(result["organization_receipt_preserves_repository_receipt"], True)
        self.assertEqual(result["sdk_admitted_result"]["manifest_receipt_id"], result["organization_receipt_sha256"])
        repository, = self.receipts("repo", "stegverse.repo-transition-receipt/v1")
        organization, = [r for r in self.receipts("org", "stegverse.organization-transition-receipt/v1")]
        self.assertEqual(repository["repository"], "SV-LLM/.github")
        self.assertEqual(repository["transition_class"], OPERATION_ID)
        self.assertEqual(organization["repo_receipt_sha256"], repository["receipt_sha256"])
        self.assertEqual(organization["source_repository"], "SV-LLM/.github")

    def test_a_redelivery_is_answered_with_the_recorded_receipts(self):
        first = self.receive()
        again = self.receive()
        self.assertIs(again["transition_replayed"], True)
        self.assertEqual(again["organization_receipt_sha256"], first["organization_receipt_sha256"])
        self.assertEqual(len(self.receipts("repo", "stegverse.repo-transition-receipt/v1")), 1)

    def test_a_surface_this_organization_does_not_expose_is_a_recorded_refusal(self):
        refused = self.receive(built(egress_surface="LLM_ADAPTER", source_output_id="w04-unexposed"))
        self.assertEqual(refused["disposition"], "FAIL_CLOSED")
        self.assertEqual(refused["failed_predicate"], "CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED")
        self.assertIn("ORG_EXPOSES_NO_SUCH_TRANSITION_SURFACE", refused["detail"])
        self.assertIs(refused["refusal_recorded"], True)
        self.assertIs(refused["organization_receipt_observed"], False)
        for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                      "owning_existing_goal", "next_attempt"):
            self.assertTrue(refused[field], field)
        # No outbound disposition binding is declared here, so the NON-ALLOW is
        # the receipt and nothing is emitted.
        self.assertIs(refused["disposition_delivered"], False)
        self.assertNotIn("emission_transition_class", refused)
        repository, = self.receipts("repo", "stegverse.repo-transition-receipt/v1")
        self.assertEqual(repository["transition_class"], "ORGANIZATION_SDK_MANIFEST_INGRESS_REFUSED")

    def test_standing_is_an_ingress_precondition(self):
        refused = self.receive(standing=None)
        self.assertEqual(refused["failed_predicate"], "CROSSING_IS_DRIVABLE_FROM_THE_MANIFEST_AS_DECLARED")
        self.assertIn("CROSSING_REQUIRES_DECLARED_STANDING", refused["detail"])
        self.assertIs(refused["refusal_recorded"], True)

    def test_a_tampered_boundary_chain_fails_closed(self):
        crossing = ingress.crossing_module.cross(built(), registry=REGISTRY,
                                                 standing=committed_request()["standing"], packet_id="w04-chain")
        self.assertIs(crossing["crossing_completed"], True)
        self.assertEqual(len(ingress.reconstruct_closures(crossing)), 5)
        crossing["boundary_receipts"][2]["evidence_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "BOUNDARY_RECEIPT_RECONSTRUCTION_MISMATCH"):
            ingress.reconstruct_closures(crossing)

    def test_the_capability_address_reaches_the_same_operation(self):
        # The registry address (kernel dispatch's route) hands the submission to
        # this same receive; it is not a second receiving operation.
        result = capability.receive(ROOT, row(ADDRESS), {"payload": {"manifest": built()},
                                                         "standing": committed_request()["standing"],
                                                         "packet_id": "w04-address"},
                                    registry=REGISTRY, hb_epoch=32)
        self.assertEqual(result["receiving_operation_id"], OPERATION_ID)
        self.assertEqual(result["receiving_operation_result"]["disposition"], "ALLOW")
        with self.assertRaisesRegex(SystemExit, "SUBMISSION_CARRIES_A_MANIFEST"):
            capability.receive(ROOT, row(ADDRESS), {"payload": {}}, registry=REGISTRY)

    # --- PB-EXIT-SPLIT (lead 09:54Z): the caller keeps the processor's exits apart ---

    def kernel_route(self):
        """A manifest frame addressed to this organization's capability, and a consuming cycle."""
        kernel = load("w04_pb_kernel", "org-kernel/kernel.py")
        crossing = load("w04_pb_crossing", "org-runtime/crossing.py")
        crossing.open_organization_ledger(root=ROOT, hb_epoch=32)
        mesh, node = self.work / "mesh", self.work / "node"
        packet = kernel.build_packet(origin_org="StegVerse-org", origin_service="stegverse-org.org-control",
                                     destination_org="SV-LLM", destination_service=ADDRESS,
                                     payload={"manifest": built()}, standing=committed_request()["standing"],
                                     packet_id="pb-exit-split")
        kernel._publish_frame(kernel.carrier_frame(packet, epoch=32), root=mesh)
        run = lambda: kernel.consume_and_respond(ROOT, mesh_root=mesh, node_state_root=node,
                                                 repo_ledger_root=self.work / "repo", org_ledger_root=self.work / "org")
        return run, node

    def processor_fault(self, op, match):
        """The next processor run faults once on `op` (write_text / read_text) of a path containing `match`."""
        sys.path.insert(0, str(ROOT / "org-runtime/tests"))
        self.addCleanup(sys.path.remove, str(ROOT / "org-runtime/tests"))
        import fault_injection
        hook = fault_injection.directory()
        self.addCleanup(shutil.rmtree, hook, True)
        counter = self.work.parent / (self.work.name + "-count")
        self.addCleanup(lambda: counter.unlink(missing_ok=True))
        saved = {k: os.environ.get(k) for k in ("PYTHONPATH", "STEGVERSE_FAULT_ROOT", "STEGVERSE_FAULT_COUNTER",
                                                "STEGVERSE_FAULT_MATCH", "STEGVERSE_FAULT_AT", "STEGVERSE_FAULT_OPS")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in saved.items()])
        os.environ.update(PYTHONPATH=os.pathsep.join(filter(None, [str(hook), os.environ.get("PYTHONPATH")])),
                          STEGVERSE_FAULT_ROOT="/", STEGVERSE_FAULT_COUNTER=str(counter),
                          STEGVERSE_FAULT_MATCH=match, STEGVERSE_FAULT_AT="0", STEGVERSE_FAULT_OPS=op)

        def clear():
            for name in ("STEGVERSE_FAULT_AT", "STEGVERSE_FAULT_OPS"):
                os.environ.pop(name, None)
        return clear

    def manifest_receipts(self):
        return [r for r in self.receipts("repo", "stegverse.repo-transition-receipt/v1")
                if (r.get("transition_class") or "").startswith("ORGANIZATION_SDK_MANIFEST_INGRESS")]

    def test_a_processor_write_fault_exit_75_leaves_the_frame_pending(self):
        # Exit 75: the processor's own --out write faulted, nothing durable was
        # written. Six-field non-terminal, no seen-marker; the next cycle consumes
        # the frame exactly once.
        run, node = self.kernel_route()
        clear = self.processor_fault("write_text", "execution.json")
        first, = run()
        clear()
        self.assertEqual((first["result"]["failure_code"], first["result"]["terminal"]),
                         ("FRAME_DISPATCH_IO_FAILED", False), first)
        self.assertIn("PROCESS_BOUNDARY_WRITE_FAULT", first["result"]["detail"])
        for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                      "owning_existing_goal", "next_attempt"):
            self.assertTrue(first["result"][field], field)
        self.assertIsNone(first["seen_marker"])
        self.assertEqual(self.manifest_receipts(), [])
        second, = run()
        self.assertEqual(second["result"]["status"], "CONSUMED", second)
        self.assertTrue(second["seen_marker"])
        self.assertEqual(len(self.manifest_receipts()), 1)
        self.assertEqual(run(), [])

    def test_a_processor_input_fault_exit_65_is_terminal_and_marked(self):
        # Exit 65: the processor could not read its input. A terminal six-field
        # refusal recorded on both ledgers, and the frame is marked: never pending.
        run, node = self.kernel_route()
        clear = self.processor_fault("read_text", "ingress.json")
        first, = run()
        clear()
        self.assertTrue(first["seen_marker"], first)
        refused = first["result"]["execution_result"]["application_result"]["receiving_operation_result"]
        self.assertEqual(refused["failed_predicate"], "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT", refused)
        self.assertIn("PROCESS_BOUNDARY_INPUT_FAULT", refused["detail"])
        self.assertIs(refused["refusal_recorded"], True)
        self.assertEqual(len(self.manifest_receipts()), 1)
        self.assertEqual(run(), [])

    def test_any_other_processor_exit_is_terminal(self):
        # Exit 1 (a processor refusal), an unknown code, or a crash (traceback) is a
        # terminal six-field refusal recorded on both ledgers: never pending.
        for name, body in (("exit 1", "raise SystemExit('wrong-destination-org')"),
                           ("unknown code", "print('{}'); raise SystemExit(3)"),
                           ("crash", "raise RuntimeError('processor crashed')")):
            with self.subTest(processor=name):
                stub = self.work / ("stub-" + name.replace(" ", "-") + ".py")
                stub.write_text(body + "\n")
                original = ingress.crossing_module.PROCESSOR
                ingress.crossing_module.PROCESSOR = stub
                try:
                    refused = ingress.receive(built(), registry=REGISTRY, standing=committed_request()["standing"],
                                              packet_id="pb-exit-" + name.replace(" ", "-"), hb_epoch=32)
                finally:
                    ingress.crossing_module.PROCESSOR = original
                self.assertEqual(refused["disposition"], "FAIL_CLOSED", refused)
                self.assertEqual(refused["failed_predicate"], "ADMITTED_CROSSING_REACHES_ITS_INTERNAL_ENDPOINT")
                self.assertIs(refused["refusal_recorded"], True)
                for field in ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                              "owning_existing_goal", "next_attempt"):
                    self.assertTrue(refused[field], field)

    def test_the_processor_prints_six_fields_for_each_exit_class(self):
        processor = ROOT / "org-boundary/runtime/process_boundary.py"
        (self.work / "not.json").write_text("{not json")
        (self.work / "deep.json").write_text('{"a":' + "[" * 100000)  # F-SCAN-RECURSION
        (self.work / "registry.json").write_text(json.dumps(REGISTRY))
        for name, argv, code, failure, terminal in (
                ("missing envelope", ["--envelope", str(self.work / "missing.json"), "--registry",
                                      str(self.work / "registry.json")], 65, "PROCESS_BOUNDARY_INPUT_FAULT", True),
                ("non-JSON registry", ["--envelope", str(self.work / "registry.json"), "--registry",
                                       str(self.work / "not.json")], 65, "PROCESS_BOUNDARY_INPUT_FAULT", True),
                ("deeply nested envelope", ["--envelope", str(self.work / "deep.json"), "--registry",
                                            str(self.work / "registry.json")], 65, "PROCESS_BOUNDARY_INPUT_FAULT", True)):
            with self.subTest(case=name):
                done = subprocess.run([sys.executable, "-B", str(processor), *argv, "--out", str(self.work / "out.json")],
                                      capture_output=True, text=True, cwd=ROOT, timeout=60)
                self.assertEqual(done.returncode, code, done.stdout + done.stderr)
                self.assertNotIn("Traceback", done.stderr)
                record = json.loads(done.stdout)
                self.assertEqual((record["failure_code"], record["terminal"]), (failure, terminal))
                self.assertFalse((self.work / "out.json").exists())


# --- the workflow's own steps, run locally ---------------------------------

def workflow_steps():
    """{step name: run script} for every step of the ledger workflow that runs a script."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    steps, name, index = {}, None, 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^      - name: (.+)$", line)
        if match:
            name = match.group(1).strip()
        elif name and line == "        run: |":
            body, index = [], index + 1
            while index < len(lines) and (lines[index].startswith("          ") or not lines[index].strip()):
                body.append(lines[index][10:])
                index += 1
            steps[name] = "\n".join(body).rstrip() + "\n"
            continue
        elif name and line.startswith("        run: "):
            steps[name] = line[len("        run: "):] + "\n"
        index += 1
    return steps


STEPS = workflow_steps()
VALIDATE = "Validate committed requests and the readback implementation before any append"
BIND = "Bind the designated organization ledger ref and the repository ledger subtree within it"
SDK_PATH = "Put the pinned SDK on the import path"
SELECT = "Select committed transition requests"
RECEIVE = "Receive each request and append to the repository and organization ledgers"
CLOSE = "Close an intr-destination diagnostic against this organization"
PUBLISH = "Publish the ledger ref (fast-forward only)"
READBACK = "Read the organization and repository ledgers back from a fresh fetch"
CLOSURE_READBACK = "Read the intr-destination self-closure back from a fresh fetch"


class Workspace:
    """A checkout of this repository's tracked files with a local bare origin."""

    def __init__(self, test, *, with_request=True):
        work = tempfile.TemporaryDirectory()
        test.addCleanup(work.cleanup)
        self.base = Path(work.name)
        self.ws = self.base / "ws"
        self.origin = self.base / "origin.git"
        self.temp = self.base / "runner-temp"
        self.temp.mkdir()
        (self.base / "gitconfig").write_text("[user]\n\tname = w04-test\n\temail = w04@test.invalid\n"
                                             "[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.base),
                    "GIT_CONFIG_GLOBAL": str(self.base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                    "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True,
                                 check=True).stdout.decode().split("\0")
        for name in filter(None, tracked):
            source = ROOT / name
            if not source.is_file() or (not with_request and name.startswith(".stegverse/transition-requests/")):
                continue
            target = self.ws / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("init", "-q", "--bare", str(self.origin), cwd=self.base)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        # Stands in for the credentials actions/checkout leaves; a fetch from a
        # local path does not send it.
        self.git("config", "--local", "http.https://github.com/.extraheader", "AUTHORIZATION: basic dGVzdA==")
        if SDK_ROOT is not None:
            (self.ws / "sdk").symlink_to(SDK_ROOT)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.ws, env=self.env, capture_output=True,
                              text=True, check=True).stdout.strip()

    def job(self, mode, **extra):
        github_env = self.temp / ("github-env-" + mode)
        github_env.write_text("")
        return {**self.env, "GITHUB_ENV": str(github_env), "GITHUB_STEP_SUMMARY": str(self.temp / "summary.md"),
                "RUNNER_TEMP": str(self.temp), "GITHUB_WORKSPACE": str(self.ws), "GITHUB_RUN_ID": "4242",
                "GITHUB_SHA": self.git("rev-parse", "HEAD"), "LEDGER_REF": LEDGER_REF, "MODE": mode,
                "HB_EPOCH": "", **extra}

    def step(self, name, env, **step_env):
        script = self.temp / "step.sh"
        script.write_text(STEPS[name])
        merged = {**env, **step_env}
        done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=self.ws,
                              env=merged, capture_output=True, text=True)
        for line in Path(env["GITHUB_ENV"]).read_text().splitlines():
            key, _, value = line.partition("=")
            env[key] = value
        return done

    def published(self):
        listed = subprocess.run(["git", "ls-remote", str(self.origin), LEDGER_REF], env=self.env,
                                capture_output=True, text=True, check=True).stdout.split()
        return listed[0] if listed else None


class DispatchGuards(unittest.TestCase):
    """The selection step's guards, run as the workflow runs them."""

    def setUp(self):
        self.space = Workspace(self)
        self.env = self.space.job("request", GITHUB_EVENT_NAME="workflow_dispatch")

    def select(self, value):
        return self.space.step(SELECT, self.env, INPUT_REQUEST=value, BEFORE="")

    def test_a_dispatch_must_name_a_request(self):
        done = self.select("")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("DISPATCH_REQUEST_REQUIRED", done.stdout)

    def test_a_dispatch_selects_only_committed_requests(self):
        cases = {"docs/LLM_ORG_ARCHITECTURE.md": "DISPATCH_REQUEST_OUTSIDE_COMMITTED_TRANSITION_REQUESTS",
                 ".stegverse/transition-requests/../../x.json": "DISPATCH_REQUEST_PATH_INVALID",
                 ".stegverse/transition-requests/a b.json": "DISPATCH_REQUEST_PATH_INVALID",
                 ".stegverse/transition-requests/x\x01.json": "DISPATCH_REQUEST_CONTROL_CHARACTER",
                 ".stegverse/transition-requests/NOT-COMMITTED.json": "DISPATCH_REQUEST_NOT_COMMITTED"}
        (self.space.ws / ".stegverse/transition-requests/NOT-COMMITTED.json").write_text("{}")
        for value, code in cases.items():
            done = self.select(value)
            self.assertNotEqual(done.returncode, 0, value)
            self.assertIn(code, done.stderr, value)
        self.assertFalse((self.space.temp / "requests.txt").exists())

    def test_a_committed_request_is_selected(self):
        done = self.select(REQUEST)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.space.temp / "requests.txt").read_text(), REQUEST + "\n")

    def test_a_request_declaring_a_mesh_is_refused_before_anything_is_received(self):
        path = self.space.ws / ".stegverse/transition-requests/MESH-001.json"
        path.write_text(json.dumps({**committed_request(), "request_id": "MESH-001", "mesh_root": "git+x#refs/m"}))
        (self.space.temp / "requests.txt").write_text(".stegverse/transition-requests/MESH-001.json\n")
        self.env["REPO_LEDGER_NAMESPACE"] = REPO_LOCATION["namespace"]
        done = self.space.step(RECEIVE, self.env)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("MESH_LANE_NOT_ADOPTED", done.stdout)
        self.assertFalse((self.space.temp / "results/MESH-001").exists())
        self.assertIsNone(self.space.git("for-each-ref", LEDGER_REF) or None)

    def test_a_self_closure_needs_a_supplied_integer_epoch(self):
        env = self.space.job("self-closure", GITHUB_EVENT_NAME="workflow_dispatch", HB_EPOCH="soon")
        env["REPO_LEDGER_NAMESPACE"] = REPO_LOCATION["namespace"]
        done = self.space.step(CLOSE, env, INPUT_COMMUNICATION_ID="c", INPUT_PACKET_ID="")
        self.assertNotEqual(done.returncode, 0)
        refusal = json.loads(done.stdout)
        self.assertEqual((refusal["failure_code"], refusal["failed_predicate"]),
                         ("HB_EPOCH_INVALID", "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH"))

    def test_no_push_trigger_and_a_bare_dispatch_is_a_self_closure(self):
        # B-P36n: a push carries no epoch, so the workflow has no push trigger; a
        # committed request is received only when dispatched with mode=request.
        text = WORKFLOW.read_text()
        self.assertIn("MODE: ${{ github.event.inputs.mode || 'self-closure' }}", text)
        trigger = text[text.index("\non:\n"):text.index("\npermissions:")]
        self.assertNotIn("  push:", trigger)
        self.assertNotIn("  schedule:", trigger)
        self.assertIn("  workflow_dispatch:", trigger)


@needs_sdk
class EndToEndDryRun(unittest.TestCase):
    """The workflow's steps against a temporary bare origin, with the real SDK.

    A self-closure opens the ledger first, then the committed request is
    received on top of it, published fast-forward and read back from a fresh
    fetch. A second run answers the request from the ledger. Every ref written
    is in a temporary directory.
    """

    def run_request(self, space, event, hb_epoch="41", **step_env):
        env = space.job("request", GITHUB_EVENT_NAME=event, HB_EPOCH=hb_epoch)
        for name in (SDK_PATH, VALIDATE, BIND):
            done = space.step(name, env)
            self.assertEqual(done.returncode, 0, name + "\n" + done.stdout + done.stderr)
        self.assertEqual(env["PYTHONPATH"], str(space.ws / "sdk"))
        done = space.step(SELECT, env, **step_env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        received = space.step(RECEIVE, env)
        self.assertEqual(received.returncode, 0, received.stdout + received.stderr)
        published = space.step(PUBLISH, env)
        self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
        readback = space.step(READBACK, env)
        self.assertEqual(readback.returncode, 0, readback.stdout + readback.stderr)
        name = Path(REQUEST).stem
        out = space.temp / "results" / name
        return (json.loads((out / "ingress.json").read_text()), json.loads((out / "readback.json").read_text()),
                received.stdout)

    def test_dispatch_on_an_existing_chain_appends_publishes_and_reads_back(self):
        space = Workspace(self)
        closure_env = space.job("self-closure", GITHUB_EVENT_NAME="workflow_dispatch", HB_EPOCH="40")
        for name in (VALIDATE, BIND):
            self.assertEqual(space.step(name, closure_env).returncode, 0, name)
        closed = space.step(CLOSE, closure_env, INPUT_COMMUNICATION_ID="w04-dry-run", INPUT_PACKET_ID="")
        self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)
        self.assertEqual(space.step(PUBLISH, closure_env).returncode, 0)
        verified = space.step(CLOSURE_READBACK, closure_env)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        tip_before = space.published()
        self.assertTrue(tip_before)

        ingress_result, readback, _ = self.run_request(space, "workflow_dispatch", INPUT_REQUEST=REQUEST, BEFORE="")
        self.assertEqual(ingress_result["disposition"], "ALLOW", ingress_result)
        self.assertEqual(ingress_result["owner_repository"], "SV-LLM/.github")
        self.assertEqual(readback["disposition"], "ALLOW", readback)
        self.assertEqual(readback["head_receipt_sha256"], ingress_result["organization_receipt_sha256"])
        self.assertEqual(readback["chain_length"], 2)
        self.assertIs(readback["ingress_receipt_bound_to_manifest"], True)
        self.assertEqual(readback["repository_ledger"]["ingress_repository_receipt_sha256"],
                         ingress_result["repository_receipt_sha256"])
        self.assertEqual(readback["repository_ledger"]["namespace"], REPO_LOCATION["namespace"])
        tip_after = space.published()
        self.assertNotEqual(tip_after, tip_before)
        subprocess.run(["git", "--git-dir", str(space.origin), "merge-base", "--is-ancestor", tip_before, tip_after],
                       env=space.env, check=True)

        # The same request again is one transition: answered from the ledger.
        shutil.rmtree(space.temp / "results")
        again, readback, stdout = self.run_request(space, "workflow_dispatch", INPUT_REQUEST=REQUEST, BEFORE="")
        self.assertIn("already recorded as", stdout)
        self.assertEqual(again["disposition"], "ALREADY_RECORDED")
        self.assertEqual(again["organization_receipt_sha256"], ingress_result["organization_receipt_sha256"])
        self.assertEqual(readback["disposition"], "ALLOW", readback)
        self.assertEqual(space.published(), tip_after)

    def test_a_push_without_a_supplied_epoch_fails_closed_and_publishes_nothing(self):
        # A push carries no hb_epoch. The request used to be received anyway,
        # its receipts stamped from the runner's clock; it now fails closed
        # before it is received and nothing is appended or published.
        space = Workspace(self, with_request=False)
        before = space.git("rev-parse", "HEAD")
        target = space.ws / REQUEST
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / REQUEST, target)
        space.git("add", REQUEST)
        space.git("commit", "-q", "-m", "commit the W04 request")
        space.git("push", "-q", "origin", "HEAD:refs/heads/main")
        env = space.job("request", GITHUB_EVENT_NAME="push")
        for name in (SDK_PATH, VALIDATE, BIND):
            done = space.step(name, env)
            self.assertEqual(done.returncode, 0, name + "\n" + done.stdout + done.stderr)
        done = space.step(SELECT, env, INPUT_REQUEST="", BEFORE=before)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((space.temp / "requests.txt").read_text(), REQUEST + "\n")
        received = space.step(RECEIVE, env)
        self.assertNotEqual(received.returncode, 0)
        refusal = json.loads(received.stdout.strip().splitlines()[-1])
        self.assertEqual(refusal["failure_code"], "HB_EPOCH_NOT_SUPPLIED")
        self.assertEqual(refusal["failed_predicate"], "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH")
        for field in ("failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
                      "owning_existing_goal", "next_attempt"):
            self.assertTrue(refusal[field], field)
        self.assertFalse((space.temp / "results" / Path(REQUEST).stem / "ingress.json").exists())
        self.assertIsNone(space.published())


class ExemptionStaysUntilAReceiptIsReadBack(unittest.TestCase):
    W04_RECEIPT = "sha256:fb84dadd9fa85ac2bce4f503a3b05bd9b5bb293684579001d3f52700587a1760"

    def test_only_the_read_back_path_portion_is_retired(self):
        # The W04 request disclosed the path to the boundary diagnostic with no
        # Sandbox activation, so its receipt retires the missing-path claim and
        # nothing else.
        register = json.loads((ROOT / "data/organization-role-exemption-register.json").read_text())
        exemption, = [e for e in register["exemptions"] if e["exemption_id"] == "SV-LLM-EXEMPTION-004"]
        self.assertNotEqual(exemption["failure_code"], "NO_MANIFEST_DIRECTED_APPEND_PATH_FOR_RUNTIME_OBSERVATION")
        self.assertIn(self.W04_RECEIPT, exemption["surface"])
        self.assertIn(self.W04_RECEIPT, exemption["required_evidence_or_repair"])
        self.assertIn("no provider execution or Sandbox activation", json.loads((ROOT / REQUEST).read_text())["purpose"])
        for workstream in ("W4's Sandbox", "W5", "W7", "W13"):
            self.assertIn(workstream, exemption["surface"])

    def test_exemption_004_names_the_new_path_and_retry(self):
        register = json.loads((ROOT / "data/organization-role-exemption-register.json").read_text())
        exemption, = [e for e in register["exemptions"] if e["exemption_id"] == "SV-LLM-EXEMPTION-004"]
        self.assertNotEqual(exemption["disposition"], "ALLOW")
        self.assertIn("resident-runtime/organization_manifest_ingress.py", exemption["surface"])
        self.assertIn(REQUEST, exemption["required_evidence_or_repair"])
        self.assertIn(".github/workflows/organization-ledger-transition.yml", exemption["retry_entrypoint"])
        for justification in register["prohibited_justifications"]:
            self.assertNotIn(justification, json.dumps(exemption))


if __name__ == "__main__":
    unittest.main()
