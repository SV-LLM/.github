# Organization Resident Runtime + Interlock/InTr Boundary Mirror Handoff

Status: ACTIVE
Updated: 2026-10-06
Organization: `SV-LLM`
Repository: `SV-LLM/.github`
Evidence class: `SOURCE_IMPLEMENTED` (completion evidence contract v1)

This `.github` is the organization-level owner of resident-runtime activation source and all SV-LLM ingress/egress generation, deployed here per the global invariant `organization_role_deployment_scope: PER_ORGANIZATION_IN_ITS_OWN_DOT_GITHUB`.

SV-LLM application repositories (`schemas`, `sandbox`, `StegVerse_AI` and the eight provider repositories) expose endpoint profiles only. All data leaving or entering SV-LLM crosses the organization boundary here as Interlock/InTr packets carried on HB-derived frames. Interlock/InTr remains the transition authority; this boundary generates and consumes packets and holds no transition, admission, routing, credential, publication or execution authority.

Authentic runtime execution remains a sovereign resident process. GitHub and GitHub Actions are source/evidence/validation surfaces only.

## Machine surfaces

Organization identity (SV-LLM-specific):

- `org-runtime/activation.json` — resident activation contract (`SOURCE_INSTALLED_RUNTIME_NOT_PROVEN`)
- `org-runtime/interlock-intr.json` — Interlock/InTr ingress/egress boundary contract
- `org-runtime/runtime_boundary.py` — validates the contract; emits activation requests and InTr ingress/egress envelopes; cannot self-grant authority
- `org-boundary/registry/services.json` — `sv-llm.org-control` and `sv-llm.boundary-diagnostic`
- `.stegverse/transition-ledger/contract.json`, `org-contract.json` — repository and organization ledger contracts
- `data/organization-role-runtime-reality-deployment.json`, `data/organization-role-exemption-register.json`
- `org-runtime/tests/test_org_crossing.py` — SV-LLM crossing proof

Vendored identically, organization-neutral, from `StegVerse-Labs/.github@c4ed8de7f567ac16117a17cd05a118c6a52a440d`:

- `org-kernel/` (kernel `1.3.2`) and `org-kernel/tests/test_kernel.py`
- `org-boundary/runtime/node_standing.py`, `org-boundary/runtime/intr_transport.py`
- `docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json` (required by the kernel's node-standing gate)
- `org-boundary/registry/federation.json` (canonical federation directory, unmodified)
- `.stegverse/transition-ledger/emit.py`

Vendored files must not be edited locally; changes land in the canonical source and are re-vendored.

## Data transfer to other organizations

```text
SV-LLM work product
  -> manifest (determines destination)
  -> org-runtime/runtime_boundary.py egress | org-kernel build_packet
  -> stegverse.intr.org-boundary.v1 packet + node standing
  -> HB-derived InTr carrier frame (authority_effect NONE_CARRIER_ONLY)
  -> shared sovereign federation spool (write-once, durable)
  -> peer <org>/.github boundary consumes, dispatches, receipts
```

Inbound is symmetric: frames addressed to `SV-LLM` are consumed only against this registry; an unregistered service fails closed (`unknown_service`), and an `INTERNAL_ENDPOINT` without an installed adapter fails closed (`endpoint_adapter_not_installed`).

Receiver availability is never a transition predicate: the spool is the `DURABLE_QUEUE_OR_EVENT_EPHEMERAL_MATERIALIZATION` disposition.

## Authority boundaries (unchanged)

- credential authority: `TV/TVC` only; no secret, token, provider path, OAuth abstraction or credential wrapper is introduced (TVC credential-model freeze respected)
- GitHub token runtime authority: `NONE`; the validation workflow runs with `contents: read` and uses no secrets
- transition authority: Interlock/InTr
- Master Records: released organization batch receipt recorder; holds no runtime-reality or transition authority
- SV-LLM remains no governance, credential, execution or publication authority

## Evidence

- `SOURCE_IMPLEMENTED`: this change.
- Local validation of every `.github/workflows/org-runtime-boundary.yml` step: boundary validate, activation request, ingress/egress envelopes, vendored kernel test, and SV-LLM crossing test (egress to all 14 federation peers, ingress to `sv-llm.org-control`, fail-closed refusal).
- `CI_VALIDATED` only once the workflow passes on GitHub.
- No resident runtime is observed. `SANDBOX_RUNTIME_OBSERVED` and stronger classes are not claimed.

## Open items

1. **Canonical federation directory does not list SV-LLM.** `StegVerse-Labs/.github/org-boundary/registry/federation.json` (denominator 14) must add `SV-LLM` / `SV-LLM/.github` / `sv-llm.org-control` before peers include SV-LLM in directory-driven ecosystem fan-out. Addressed packets to and from SV-LLM already work. Blocked from this session: `StegVerse-Labs/.github` is readable but not writable here. The local copy stays byte-identical to the canonical one until that change lands upstream and is re-vendored.
2. **Resident runtime.** Activation requires a sovereign resident process that consumes `runtime_boundary.py activation-request`; not established here.
3. **Application endpoints.** SV-LLM application repositories register `INTERNAL_ENDPOINT` services in `services.json` only after they declare endpoint profiles (via `schemas`). None are registered now.
