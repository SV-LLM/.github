# SV-LLM

SV-LLM is the StegVerse organization for coordinated, attributable intelligence work. Participating LLMs and AI entities provide candidate intelligence; participation does not confer StegVerse governance authority.

## Organization

```text
SV-LLM/
├── .github/        organization architecture and policy
├── schemas/        provider-neutral machine-readable contracts
├── sandbox/        multi-entity collaboration plane
├── StegVerse_AI/   ecosystem orchestration/evidence-matching entity
├── OpenAI/
├── Anthropic/
├── Google/
├── Microsoft/
├── Meta/
├── DeepSeek/
├── MoonShot_AI/
└── xAI/
```

The eight provider repositories are peer capability surfaces. `schemas` owns shared provider-neutral contracts; `sandbox` owns collaboration/session structure; `StegVerse_AI` owns its distinct ecosystem-entity capability surface; `.github` documents organization architecture and boundaries.

Knowledge, inference, governance and execution remain distinct. Canonical ecosystem truth remains in its authoritative StegVerse repositories and is resolved through InTr as relevant context rather than duplicated here.


## Receipted ecosystem review

SV-LLM uses an acquire-once/review-many evidence model for cross-ecosystem review.

```text
authoritative ecosystem repository
  -> InTr governed acquisition
  -> Organization Records receipt
  -> immutable Schema view
  -> one or more LLM / AI reviewers
```

A participating repository, LLM, or AI entity MUST request cross-ecosystem review data through `SV-LLM/schemas`. Directly reading another ecosystem repository does not establish canonical review evidence for an SV-LLM review.

InTr acquires the source data once and receipts the exact acquisition. Organization Records is the custody surface for that receipt and its immutable view lineage. Schema exposes that receipted view. Every reviewer MUST bind its findings to the exact `view_id` and `intr_receipt_id` it consumed. Review findings may be compared or aggregated as review of the same evidence only when those bindings identify the same canonical view.

A newer repository state never silently mutates an existing view. InTr performs a new acquisition and Schema exposes a successor view with explicit lineage.

### Missing review data

`DATA_NOT_IN_CURRENT_VIEW` is not a terminal review finding. When required evidence is outside the current view, the reviewer MUST return `EXPANSION_REQUIRED` and request the additional scope through Schema.

The review then follows:

```text
REVIEWING
  -> EXPANSION_REQUIRED
  -> EXPANSION_REQUESTED
  -> InTr acquisition
  -> VIEW_EXPANDED
  -> REVIEWING
  -> FINAL
```

If acquisition cannot succeed, InTr returns a receipted `EXPANSION_DENIED` or `EXPANSION_FAILED` disposition. Only that receipted terminal disposition may support a final review that identifies required evidence as unavailable. A reviewer MUST NOT finalize with an unverified statement such as “unable to review unconnected data source.”

Master Records relates only to organization records and reconstruction, and has no role in this protocol. Organization Records owns custody of the organization action and acquisition receipts. LLM-adapter remains provider transport only and has no custody role.

The machine-readable contract is `SV-LLM/schemas/ecosystem-review-view.schema.json`.
