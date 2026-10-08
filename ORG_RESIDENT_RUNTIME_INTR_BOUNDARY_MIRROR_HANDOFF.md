# Organization Resident Runtime + Interlock/InTr Boundary Mirror Handoff

Status: ACTIVE
Updated: 2026-10-08
Organization: `SV-LLM`
Repository: `SV-LLM/.github`
Evidence class: `SOURCE_IMPLEMENTED` (completion evidence contract v1)

This `.github` is the SV-LLM organization boundary, deployed here per the global invariant `organization_role_deployment_scope: PER_ORGANIZATION_IN_ITS_OWN_DOT_GITHUB`. All data leaving or entering SV-LLM crosses here as Interlock/InTr packets on HB-derived frames. Interlock/InTr remains the transition authority; credential authority is TV/TVC. The boundary holds no transition, admission, routing, credential, publication or execution authority.

## Standard

Every action is a manifest-bound attempted state transition (`data/task-registry-global-invariants.json`):

- the manifest determines the destination, and an existing destination is sufficient for ingress and egress;
- destination liveness, an always-on receiver, an external machine, a second device and a post-closure observer are never predicates;
- an unavailable receiver is answered by the durable federation spool (`DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION`), never by waiting;
- SV-LLM's runtime reality is its organization ledger root: a transition is real when appended there by manifest-directed append. Observing a process does not establish it and its absence does not gate it.

## Crossing surface — `org-runtime/crossing.py`

```text
EGRESS   manifest names peer organization
           -> peer exists in federation directory projection?  no -> ORGANIZATION_EGRESS_REFUSED
           -> InTr packet -> HB-derived frame -> federation spool  -> ORGANIZATION_EGRESS_EMITTED
INGRESS  frame addressed to SV-LLM
           -> manifest names an SV-LLM repository in data/organization-tree.json
                -> node standing -> write-once materialization     -> ORGANIZATION_INGRESS_MATERIALIZED
                   (put_once in the supplied node state, never the checkout)
           -> addressed to a registered boundary service -> kernel  -> ORGANIZATION_INGRESS_CONSUMED
           -> anything else                                         -> ORGANIZATION_INGRESS_REFUSED
```

Every disposition, refusals included, is appended to the repository ledger and then the organization ledger. No frame means nothing crossed, so nothing is recorded. SV-LLM repositories are destinations because they exist; none declares an endpoint profile.

## Federation directory — updatable projection

`org-boundary/registry/federation.json` is a projection of the single canonical directory at `StegVerse-Labs/.github/org-boundary/registry/federation.json`. It carries the canonical entries unchanged plus `projection` provenance (source commit, source and entries digests). It is read locally, so no crossing waits on a remote directory. Local additions are prohibited; an organization is added in the canonical directory and every organization re-projects:

```text
python org-boundary/runtime/federation_projection.py reproject --canonical <canonical federation.json> --source-commit <sha>
python org-boundary/runtime/federation_projection.py verify [--canonical <canonical federation.json>]
```

## Machine surfaces

SV-LLM-specific: `org-runtime/{activation.json, interlock-intr.json, runtime_boundary.py, crossing.py}`, `org-boundary/registry/services.json`, `org-boundary/runtime/federation_projection.py`, `.stegverse/transition-ledger/{contract.json, org-contract.json}`, `data/organization-role-runtime-reality-deployment.json`, `data/organization-role-exemption-register.json`, `org-runtime/tests/test_org_crossing.py`.

Vendored unchanged from `StegVerse-Labs/.github@c4ed8de7f567ac16117a17cd05a118c6a52a440d`: `org-boundary/runtime/node_standing.py`, `docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json`. `org-boundary/runtime/intr_transport.py` (vendored from the same commit) was referenced by no code, workflow or contract and minted packet ids from `uuid4` and timestamps from the wall clock; it is removed.

Ported from `StegVerse-org/.github@66749948a6535bc097fc257a7bbf3d18193282e6`: `org-boundary/runtime/manifest_selection.py` (code unchanged; docstring rewritten for SV-LLM).

Adopted from `StegVerse-org/.github` at the commit recorded in `data/organization-role-reference-adoption.json` and proven by `resident-runtime/reference_adoption.py verify`: `resident-runtime/ledger_store.py`, `.stegverse/transition-ledger/emit.py`, `resident-runtime/aggregate_repo_transition.py` (with the declared SV-LLM wrapper). Ledger roots are supplied (`STEGVERSE_REPO_LEDGER_ROOT`, `STEGVERSE_ORG_LEDGER_ROOT`) or the append is FAIL_CLOSED `LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER`; nothing is derived from `XDG_STATE_HOME` or the home directory.

`org-kernel/` (1.3.3 lineage) holds the shared kernel contract at semantic parity with `StegVerse-org/.github:org-kernel/kernel.py` (no byte identity): the mesh is the location the materializer supplies or the kernel fails closed `mesh_location_required_from_materializer`; there is no environment-variable or home-directory fallback; node and mesh state go through `org-kernel/node_store.py` (atomic `os.link` write-once); frames stay at `frames.d/<sha256(packet_id|frame_sha256)>.json`. `crossing.py` takes the mesh as `mesh_root` (CLI `--mesh-root`) and records an unsupplied mesh as FAIL_CLOSED `MESH_LOCATION_REQUIRED_FROM_MATERIALIZER`. The carrier is declared in `org-runtime/interlock-intr.json` (`egress.emitting_operation`, `ingress.receiving_operation`) and checked by `runtime_boundary.py validate`.

`runtime_boundary.py ingress|egress` only generate envelopes; they send and receive nothing. Crossings go through `crossing.py`.

## Kernel parity with StegVerse-org/.github #93-#97 (SDK-MANIFEST-ECOSYSTEM-TRANSITION-DISPOSITION-001, step 6)

Each gap was reproduced on `main` ed27bc4 before it was closed; `org-runtime/tests/test_kernel_crossing_parity.py` holds the cases.

- **Processing selection.** `kernel.dispatch` and the dispatch branch of `crossing.py::_ingest` chose processing by `boundary_role` alone. Dispatch now resolves `manifest_selection.select_processing` before any receipt and carries `processing_selection`, `declared_capability`, `declared_route_id`, `declared_capability_processed` and `route_admissibility` on the result and on the recorded crossing; `_ingest` carries the same fields on every admitted outcome, materializations included. Undeclared `INTERNAL_ENDPOINT` processing is refused `PROCESSING_SELECTED_ONLY_BY_ADMITTED_PROCESSING_CAPABILITY_AND_ROUTE_ID`, and `RETURN_BOUND_TO_REQUEST` is admitted only for a bound endpoint response. SV-LLM registers only `BOUNDARY_LOCAL_*` services, which are the processor and select none, so no SV-LLM service declares `admits_processing` (the reference likewise declares none on boundary-local rows) and the subprocess `INTERNAL_ENDPOINT` path is not ported: SV-LLM has no endpoint adapter.
- **Idempotent ledgers.** `emit.append(idempotent_on=)` and `aggregate_repo_transition.append(idempotent=)` are adopted from the reference commit above (the reference-adoption record and the workflow's reference checkout now name it). A transition already on the chain is returned rather than minted; the same id over another predecessor or evidence is `ledger_receipt_collision`.
- **Epochs.** `publish_packet(epoch=)`; an answer is stamped with the epoch of the frame it answers, so consuming the frame again reproduces the same answer frame (a write-once no-op). A monitor answer still carries `resident_status`'s host-clock sample (marked `derived_from_clock`), so its answer frame differs per pass, as in the reference. `submit_org_transition_to_master_records.py` takes `--mesh-root`, publishes at the epoch of the receipt it carries, and records the emission.
- **Recorded crossings.** `consume_and_respond(node_state_root=, repo_ledger_root=, org_ledger_root=)` and `consume_addressed_frames(...)` record every consumed crossing (`ORGANIZATION_FEDERATION_CROSSING_CONSUMED`) and every refused one (`ORGANIZATION_FEDERATION_CROSSING_REFUSED`: `DENY` recorded and marked; `FAIL_CLOSED` recorded once, unmarked, retried) on both ledgers before answering or marking. A refusal no longer stops the frames behind it. The emitters are the kernel's own repository's; a foreign dispatch root is refused `dispatch_root_is_not_this_kernels_organization`. SV-LLM adds one guard to the reference: custody also requires a declared organization-ledger genesis (`org_ledger_genesis_not_declared`), because SV-LLM's chain is opened only by `crossing.py open-ledger`. `ingest_frame`, `publish_packet`, `publish_ecosystem_message` and `publish_ecosystem_from_directory` record what they consume or emit (`ORGANIZATION_FEDERATION_CROSSING_EMITTED`) under the same custody and refuse before any effect without it.
- **Supplied node state.** Consumption markers, work intake and ingress materializations go only to supplied node state; the kernel's checkout fallback (`node_state_store`, `resident-runtime/` under the dispatch root) is removed. `crossing.py ingress` takes `node_state_root` (CLI `--node-state-root`) and records an unsupplied one as FAIL_CLOSED `NODE_STATE_LOCATION_REQUIRED_FROM_MATERIALIZER`. `_materialize` is one `node_store.put_once` at `ingress/materialized/<repository>/<sha256(packet_id)>.json` instead of a bare `write_text` under the checkout.
- **Egress closure.** Not ported. StegVerse-org's `organization_egress_boundary.py::close` observes a far-side response to an emission; SV-LLM's egress emits manifest crossings that request no response, so there is nothing for a closure to observe. Recorded as `closure_operation_not_installed_reason` in `org-runtime/interlock-intr.json`.

Tests that stood a bare directory in for a peer now materialize the peer as its own organization (`org-runtime/tests/peer_organization.py`), with its own kernel, emitters, ledgers and declared genesis.

## Exemptions

`SV-LLM-EXEMPTION-001` (corrected): it declared `DENY_DIRECT_USE` for the kernel's direct crossing entrypoints, and no code enforced it. Those entrypoints now record on both ledgers and are no longer exempt. What remains are three primitives that record nothing themselves because the operation calling them records the crossing they belong to: `carry_packet` and `publish_frame` (the carrier write; `crossing.py::egress` records the emission) and `dispatch` (`crossing.py::ingress` records the disposition). Each refuses with `crossing_custody_required_from_recording_operation` unless handed the custody `crossing_custody` resolves. The declared egress carrier in `interlock-intr.json` is therefore `org-kernel/kernel.py::carry_packet`. Repair: a custody that binds the caller's appended receipt to the primitive's effect, released in the canonical kernel.

## Evidence

- `SOURCE_IMPLEMENTED`: the kernel parity change above. Every org-runtime-boundary workflow step and every test file was run on `main` ed27bc4 and on this branch in separate worktrees, with HOME and XDG pointed at scratch and `PYTHONDONTWRITEBYTECODE=1`: no host or checkout writes, no `.pyc`, and no new dependency. No terminal predicate of SDK-MANIFEST-ECOSYSTEM-TRANSITION-DISPOSITION-001 is closed by this change; all six stay open. Source and CI are not runtime evidence.
- `SOURCE_IMPLEMENTED` (earlier): the crossing surface.
- Locally, every workflow step passes, including `org-runtime/tests/test_org_crossing.py`: egress to all 14 directory peers with no receiver present, recorded refusals, inbound materialization to `SV-LLM/sandbox`, and 22 dispositions in unbroken repository and organization ledger chains.
- `CI_VALIDATED` once the workflow passes on GitHub. Stronger classes are not claimed.

## Open item

The canonical directory in `StegVerse-Labs/.github` does not yet list SV-LLM, so SV-LLM is absent from this projection and from peers' directory-driven fan-out. This session could not write to `StegVerse-Labs/.github`. The required canonical change adds SV-LLM, raises `denominator` to 15 and `generation` to 2; every organization then re-projects. SV-LLM then re-projects here.
