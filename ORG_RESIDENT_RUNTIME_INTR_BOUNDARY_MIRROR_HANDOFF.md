# Organization Resident Runtime + Interlock/InTr Boundary Mirror Handoff

Status: ACTIVE
Updated: 2026-10-06
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

Vendored unchanged from `StegVerse-Labs/.github@c4ed8de7f567ac16117a17cd05a118c6a52a440d`: `org-boundary/runtime/{node_standing.py, intr_transport.py}`, `docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json`.

Adopted from `StegVerse-org/.github` at the commit recorded in `data/organization-role-reference-adoption.json` and proven by `resident-runtime/reference_adoption.py verify`: `resident-runtime/ledger_store.py`, `.stegverse/transition-ledger/emit.py`, `resident-runtime/aggregate_repo_transition.py` (with the declared SV-LLM wrapper). Ledger roots are supplied (`STEGVERSE_REPO_LEDGER_ROOT`, `STEGVERSE_ORG_LEDGER_ROOT`) or the append is FAIL_CLOSED `LEDGER_LOCATION_REQUIRED_FROM_MATERIALIZER`; nothing is derived from `XDG_STATE_HOME` or the home directory.

`org-kernel/` (1.3.2 lineage) holds the shared kernel contract at semantic parity with `StegVerse-org/.github:org-kernel/kernel.py` (no byte identity): the mesh is the location the materializer supplies or the kernel fails closed `mesh_location_required_from_materializer`; there is no environment-variable or home-directory fallback; node and mesh state go through `org-kernel/node_store.py` (atomic `os.link` write-once); frames stay at `frames.d/<sha256(packet_id|frame_sha256)>.json`. `crossing.py` takes the mesh as `mesh_root` (CLI `--mesh-root`) and records an unsupplied mesh as FAIL_CLOSED `MESH_LOCATION_REQUIRED_FROM_MATERIALIZER`. The carrier is declared in `org-runtime/interlock-intr.json` (`egress.emitting_operation`, `ingress.receiving_operation`) and checked by `runtime_boundary.py validate`.

`runtime_boundary.py ingress|egress` only generate envelopes; they send and receive nothing. Crossings go through `crossing.py`.

## Exemptions

`SV-LLM-EXEMPTION-001`: the kernel's direct crossing entrypoints do not record ledger receipts. Disposition is to deny direct use and route through `crossing.py` until the canonical kernel records crossings.

## Evidence

- `SOURCE_IMPLEMENTED`: this change.
- Locally, every workflow step passes, including `org-runtime/tests/test_org_crossing.py`: egress to all 14 directory peers with no receiver present, recorded refusals, inbound materialization to `SV-LLM/sandbox`, and 22 dispositions in unbroken repository and organization ledger chains.
- `CI_VALIDATED` once the workflow passes on GitHub. Stronger classes are not claimed.

## Open item

The canonical directory in `StegVerse-Labs/.github` does not yet list SV-LLM, so SV-LLM is absent from this projection and from peers' directory-driven fan-out. This session could not write to `StegVerse-Labs/.github`. The required canonical change adds SV-LLM, raises `denominator` to 15 and `generation` to 2; every organization then re-projects. SV-LLM then re-projects here.
