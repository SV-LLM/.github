# SV-LLM Organization Architecture

## Purpose

SV-LLM provides the centralized coordination plane for constructing and maintaining the StegVerse ecosystem with multiple intelligence capabilities while preserving existing StegVerse authority boundaries.

The central problem is not simply choosing a model. It is ensuring that work begins with the correct understanding of what a component is intended to do, which ecosystem contracts constrain it, what evidence establishes current state, what is actually divergent, and what smallest change restores intended behavior without architectural drift.

## Organization model

Provider/entity repositories should contain only entity-specific material: interfaces, capability declarations, invocation constraints, evidence/output types, and provider-specific evaluation history.

Canonical ecosystem knowledge remains in its authoritative repositories and is resolved through InTr when relevant to a manifested work request.

The organization coordination repository defines common contracts shared by all participating repositories.

## Work cycle

```text
TASK
 -> resolve canonical purpose
 -> resolve applicable ecosystem contracts
 -> resolve current implementation/evidence
 -> identify demonstrated divergence
 -> resolve required capabilities
 -> coordinate attributable intelligence work
 -> preserve disagreement/refusal/uncertainty
 -> produce candidate repair/work product
 -> cross-ecosystem drift analysis
 -> existing governance
 -> authorized execution/publication if admitted
 -> organization-ledger transition receipt (closure)
 -> future work context
```

The organization-ledger transition receipt is the closure of an admitted transition. Any observation of the result is evidence only; it is never a step, predicate or gate after closure, and its absence does not hold a transition open.

Master Records is not a step of this cycle. Once the organization has verified and released a batch of its receipts, Master Records may record that released batch downstream as organization records for reconstruction. That recording is evidence preservation only: it is not an authority, gate, custodian or runtime-reality locus, nothing in the cycle awaits it, and an unrecorded batch holds nothing open.

## Foundational invariant

> No repair is evaluated solely against the repository being repaired when that repository participates in cross-ecosystem contracts.

## Work-context resolver

A conceptual `RESOLVE_WORK_CONTEXT(work)` returns a reconstructable, relevance-bounded context graph:

```text
work
├── intended purpose
├── canonical authority
├── affected repositories
├── governing contracts
├── relevant documentation
├── schemas
├── tests
├── current handoffs
├── manifests
├── known evidence
├── receipt / Master Records organization-record references
├── dependencies
├── prohibited architectural drift
└── unresolved predicates
```

The resolver identifies canonical references; it does not make provider repositories new sources of truth.

## Multi-entity collaboration

Multi-entity participation is evidence production, not voting. Parallel agreement may be useful information, but consensus does not establish admissibility.

Independent contributions remain addressable. A synthesis records its input contribution identifiers and evidence lineage. Challenges and refusals are retained rather than normalized away.

## Temporal model

### Historical plane

Receipted history establishes what has authentically occurred or been observed, including applicable authority and evidence.

### Forward plane

The Inference Window evaluates every available Admissibility Matrix disposition independently:

```text
Disposition D
 -> states/consequences that might become reachable
 -> states/consequences that might not become reachable
 -> assumptions / conditions
 -> uncertainty
 -> evidence basis
```

The forward plane cannot rewrite the historical plane.

An authorized transition closes when its transition receipt is appended to the organization ledger; that receipt becomes part of the historical plane used by future work. An observation made afterwards is evidence that later work may cite, never a gate on the closed transition and never a substitute for its receipt.

## Capability marketplace without authority hierarchy

SV-LLM may evolve into an evidence-driven capability marketplace. Selection can consider declared capability, interface compatibility, evidence requirements, demonstrated governed history, cost, latency, privacy constraints, and requested work mode.

Selection means “appropriate capability to attempt this work.” It never means “authority to decide this transition.”

## StegVerse AI Entity

The initial StegVerse AI Entity role is ecosystem orchestration and evidence/history matching. It is intentionally not defined as an LLM.

Future inference capabilities may be separately declared and evaluated without retroactively converting its governance/evidence role into model authority.

## Explicit non-goals

This architecture does not:
- replace the Task Registry;
- assign worker claims;
- replace Interlock/InTr;
- create a second Admissibility Matrix;
- create provider credentials;
- replace LLM-adapter routing or distributed workload;
- publish directly around Publisher;
- replace Master Records;
- make model consensus evidence of truth;
- treat projected consequences as observed history;
- require a persistent user-operated second device.

## Canonical repository topology

The topology below is derived from the repositories actually enumerated in the connected `SV-LLM` organization:

- `.github` — organization architecture, topology, policy documentation and handoffs;
- `schemas` — shared provider-neutral machine-readable contracts;
- `sandbox` — provider-neutral multi-entity collaboration;
- `StegVerse_AI` — StegVerse ecosystem orchestration/evidence-matching entity;
- `OpenAI`, `Anthropic`, `Google`, `Microsoft`, `Meta`, `DeepSeek`, `MoonShot_AI`, and `xAI` — peer provider capability repositories.

The machine-readable source for this inventory and role map is `data/organization-tree.json`.

Repository separation is intentional. Shared schemas must not become provider-owned. Multi-entity collaboration must not become provider-owned. The StegVerse AI entity must retain an identity and governed history distinct from both collaboration sessions and model providers. `.github` defines organization architecture but is not the runtime implementation of those roles.

### Organizational completeness

For the architecture currently defined, the enumerated organization already contains the required **classes** of repository: organization coordination, shared contracts, provider-neutral collaboration, ecosystem entity, and provider capabilities. No additional non-provider repository is justified merely to satisfy the current architecture.

That is an organizational-topology statement only. It does not imply runtime completeness: empty or uninitialized repositories still require their contracts, implementation, validation, and integration with existing StegVerse authority surfaces.
