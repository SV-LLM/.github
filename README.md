# SV-LLM

## Organization Tree

```text
SV-LLM/
├── .github/              organization architecture, topology and shared policy documentation
├── schemas/              provider-neutral machine-readable SV-LLM contracts
├── tools/                sandbox tools
├── sandbox/              provider-neutral multi-entity collaboration plane
├── StegVerse_AI/         StegVerse ecosystem orchestration/evidence-matching entity
├── Ecosystem_Chat/       Ecosystem Chat participant entity
├── OpenAI/               OpenAI capability surface
├── Anthropic/            Anthropic capability surface
├── Google/               Google capability surface
├── Microsoft/            Microsoft capability surface
├── Meta/                 Meta capability surface
├── DeepSeek/             DeepSeek capability surface
├── MoonShot_AI/          Moonshot AI capability surface
├── xAI/                  xAI capability surface
├── Mistral/              Mistral AI capability surface
├── MiniMax/              MiniMax capability surface
├── Perplexity_AI/        Perplexity AI capability surface
├── Cohere/               Cohere capability surface
├── IBM/                  IBM capability surface
├── Z_AI/                 Z.ai capability surface
├── Alibaba_Cloud/        Alibaba Cloud capability surface
├── NVIDIA/               NVIDIA capability surface
├── Amazon_Web_Services/  Amazon Web Services capability surface
└── AI21_Labs/            AI21 Labs capability surface
```

### Repository roles

| Repository | Class | Role |
| --- | --- | --- |
| `.github` | Organization coordination | Canonical organization tree, architecture, authority boundaries, profile, handoffs and shared policy documentation. |
| `schemas` | Shared contract | Provider-neutral schemas for work objects, capability declarations, contributions, provenance, epistemic state, Inference Window projections and governance handoff references. |
| `sandbox` | Collaboration plane | Provider-neutral bounded multi-entity sessions; preserves attributable contributions, disagreement, refusal, uncertainty, synthesis lineage and handoff packaging. |
| `StegVerse_AI` | Ecosystem entity | Reconstructs ecosystem purpose, matches evidence against receipted history, recognizes capability gaps and orchestrates intelligence requests without becoming governance authority. |
| `Ecosystem_Chat` | Ecosystem entity | Ecosystem Chat participant: declared capabilities, Sandbox participation and the SDK return path; its implementation lives outside SV-LLM. |
| `OpenAI` | Provider capability | OpenAI-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Anthropic` | Provider capability | Anthropic-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Google` | Provider capability | Google-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Microsoft` | Provider capability | Microsoft-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Meta` | Provider capability | Meta-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `DeepSeek` | Provider capability | DeepSeek-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `MoonShot_AI` | Provider capability | Moonshot AI-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `xAI` | Provider capability | xAI-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Mistral` | Provider capability | Mistral AI-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `MiniMax` | Provider capability | MiniMax-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Perplexity_AI` | Provider capability | Perplexity AI-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Cohere` | Provider capability | Cohere-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `IBM` | Provider capability | IBM-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Z_AI` | Provider capability | Z.ai-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Alibaba_Cloud` | Provider capability | Alibaba Cloud-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `NVIDIA` | Provider capability | NVIDIA-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `Amazon_Web_Services` | Provider capability | Amazon Web Services-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |
| `AI21_Labs` | Provider capability | AI21 Labs-specific interfaces, capability declarations, invocation constraints, attributable outputs and provider-specific evaluation history. |

### Dependency shape

```text
                     .github
          architecture / topology / policy
                        |
                     schemas
          provider-neutral shared contracts
              /         |          \
             v          v           v
      StegVerse_AI   sandbox    provider repos
             \          |        / / / /
              \         |       / / / /
               +---------+------+
                         |
                 attributable work
                         |
                         v
              existing StegVerse governance
                         |
                         v
              authorized consequence path
```

Provider repositories are peers under the shared contract; none owns organization governance. `sandbox` is provider-neutral. `schemas` prevents common wire/work contracts from becoming implicitly owned by `.github`, `sandbox`, or any provider. `StegVerse_AI` is a distinct ecosystem entity, not a provider alias.

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
- receipts and Master Records organization-record references;
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
- **SKAP Vault** (`KV/_Vault/SKAP`) — the only storage place of PII and credentials for every user, the StegVerse Ecosystem's own included; TV/TVC is the authority over them, never their storage place (Rigel 2026-10-24T17:52Z/17:54Z; HST path@sha pending, StegVerse-org/.github#163 issuecomment-6387655436);
- **Master Records** — not an authority, gate or custodian: the downstream recorder of released organization batch receipts (organization records and reconstruction). Runtime reality stays with the Organization ledger; nothing awaits Master Records;
- **Publisher** — governed publication/output continuation where applicable.

## Organization Interlock/InTr boundary

All SV-LLM data crossing to or from other StegVerse organizations goes through this `.github` boundary as manifest-bound Interlock/InTr state transitions. The manifest determines the destination, an existing destination is sufficient, nothing waits on a receiver, and every disposition is appended to the organization ledger. The boundary carries data; it grants no transition, credential, routing or execution authority. See `ORG_RESIDENT_RUNTIME_INTR_BOUNDARY_MIRROR_HANDOFF.md`.

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

## Provider installation coordination (2026-10-11)

The 16 provider repository paths and staged installation contract are tracked in [the provider installation mirror handoff](docs/SV_LLM_PROVIDER_INSTALLATION_MIRROR_HANDOFF.md). Provider-specific source must remain capability-only; execution and governance remain in their existing authoritative components. Registry installation identity and runtime certification are separately reconciled.
