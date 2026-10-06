# SV-LLM

SV-LLM is the organization-level coordination surface for StegVerse intelligence work. It exists to resolve the canonical context required to understand ecosystem work, select appropriate intelligence capabilities, coordinate attributable multi-entity work, and return candidate work to existing StegVerse governance.

SV-LLM is **not** a second governance authority, Task Registry, WorkerCoordinator, provider broker, credential authority, Publisher, custody system, or execution authority.

## Architecture

```text
Manifested intelligence request
        |
        v
Canonical work-context resolution
        |
        v
Capability resolution
   |                 |
   | local           | participating LLM / AI entity
   v                 v
bounded work       SV-LLM Sandbox
                       |
                       v
             attributable contributions
             disagreement / refusal / uncertainty
             transitive evidence provenance
                       |
                       v
               candidate work product
                       |
                       v
              existing StegVerse governance
                       |
                       v
        authorized consequence / publication /
               execution as applicable
                       |
                       v
                 receipted history
```

## Canonical separation

SV-LLM preserves four distinct functions:

1. **Knowledge / intelligence** — participating entities may retrieve, reason, calculate, synthesize, challenge, or propose.
2. **Inference** — the Inference Window projects disposition-dependent futures.
3. **Governance** — Ecosystem AI and the existing governance path evaluate manifested claims/proposed transitions against admissible evidence and reconstructable receipted history.
4. **Execution** — only the existing authorized execution surface may cause an admitted state transition.

An LLM or other participating AI entity acquires none of those authorities merely by participating in SV-LLM.

## Canonical ecosystem context

SV-LLM does not copy canonical ecosystem truth into provider repositories. Context is resolved through InTr from the relevant canonical evidence needed for the work, including as applicable:

- Task Registry state;
- repository documentation and implementation contracts;
- schemas and tests;
- manifests;
- mirror handoffs;
- receipts and Master Records references;
- cross-repository contracts;
- current implementation state.

Resolution is relevance-bounded. “All ecosystem evidence is available” does not mean every artifact is injected into every model context.

A repair to a component participating in cross-ecosystem contracts must not be evaluated solely against the repository being repaired.

## Capability resolution

“All intelligence requests go to SV-LLM” means that the request resolves through the SV-LLM capability contract. It does not require every operation to leave the current execution surface.

Capability resolution may select:

- an already available local capability;
- one participating LLM or AI entity;
- several entities in parallel;
- sequential specialist work;
- an explicit challenger;
- another bounded capability exposed through the organization.

Provider routing, transport, distributed workload semantics, contributor provenance, and provider-specific connection behavior already owned by `StegVerse-org/LLM-adapter` are reused rather than duplicated here.

## Sandbox

The Sandbox coordinates bounded work objects. Each work object retains:

- task/work identity;
- manifested request;
- canonical context references;
- permitted capabilities;
- participating entity identities;
- independently attributable contributions;
- disagreements, refusals, and uncertainty;
- tests and derived artifacts;
- evidence references and provenance;
- governance handoff state.

A synthesis is another attributable derived artifact. It does not erase the individual contributions from which it was derived.

## Evidence provenance

Evidence provenance is transitive:

```text
source evidence
  -> attributable observation / analysis
  -> derived claim
  -> synthesis
  -> proposed transition
```

A downstream claim does not automatically inherit evidentiary standing merely because it cites another model's output.

## Epistemic state

SV-LLM distinguishes:

- `OBSERVED` — established through admissible observation/evidence;
- `DERIVED` — derived from identified evidence and declared reasoning/transformations;
- `PROJECTED` — forward-looking consequence inference.

Agreement by additional entities does not promote `DERIVED` or `PROJECTED` information to `OBSERVED`.

## Ecosystem AI

The StegVerse Ecosystem AI is initially an ecosystem governance/evidence-matching capability, not an LLM provider peer and not an interpretive judge.

It matches manifested claims and proposed transitions against admissible evidence and reconstructable receipted history. It does not determine truth through appearance, majority vote, model consensus, reputation, or model confidence.

Its capability may grow through reconstructable governed work history without redefining participation as governance authority.

## Inference Window

The Inference Window is forward-looking and disposition-complete.

For **every disposition available in the applicable Admissibility Matrix**, it asks:

> If this disposition is applied, what states or consequences might or might not become reachable?

Each projection binds its disposition, evidence basis, assumptions/conditions, uncertainty where applicable, and reachable/non-reachable consequences.

Projection is not evidence of occurrence. A projected consequence becomes historical evidence only through subsequent admissible observation and receipted history.

## Capability declarations

Provider/entity capability declarations may describe:

- capability classes;
- required inputs;
- output/evidence types;
- supported work modes;
- cost/latency/privacy properties where available;
- demonstrated governed work history;
- provider/entity-specific interface constraints.

These declarations support evidence-driven capability selection. They do not create an authority hierarchy.

## Existing authority boundaries

SV-LLM reuses and does not supersede:

- **Task Registry** — work-intent authority;
- **WorkerCoordinator** — worker claim/fence authority;
- **Interlock/InTr** — transition authority and organization-crossing evidence/context path;
- **StegVerse SDK** — manifest construction/validation and SDK-side contracts;
- **LLM-adapter** — provider-neutral access, provider transport, distributed workload and contribution provenance;
- **TV/TVC** — credential/provider-operation and applicable route authority;
- **Master Records** — custody/reconstruction authority;
- **Publisher** — governed publication/output continuation where applicable.

## Consumer integration

The later Ecosystem Chat consumer loop is a separate integration objective:

```text
Ecosystem Chat
  -> SDK Manifest Builder
  -> manifested SV-LLM intelligence request
  -> capability resolution / Sandbox
  -> existing governance
  -> Publisher
  -> SDK return assembly
  -> Ecosystem Chat desired output
```

This organization foundation does not claim that consumer loop is implemented merely because the architecture is documented.

See `docs/LLM_ORG_ARCHITECTURE.md` and `docs/LLM_ORG_FOUNDATION_MIRROR_HANDOFF.md`.
