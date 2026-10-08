# Schema/InTr Receipted Ecosystem Review Contract

Updated: 2026-10-06
Related Goal Task: `SVORG-LLM-ORG-FOUNDATION-001`
COSV ID: `20011100110000`
Machine contract: `SV-LLM/schemas/ecosystem-review-view.schema.json`

## Normative invariant

**Acquire once. Receipt once. Record once. Review many.**

Cross-ecosystem review is performed against an immutable view produced from one governed InTr acquisition. Reviewers do not independently fetch ecosystem repositories to establish canonical review evidence.

## Roles

- **InTr** performs the governed acquisition/transition and produces the acquisition receipt.
- **Organization Records** is the sole custody surface for organization actions, acquisition receipts, view lineage, and review bindings.
- **Schema** defines and exposes the provider-neutral immutable review view and accepts requests to expand that view.
- **LLM/AI reviewers** consume Schema views and produce attributable candidate findings bound to the exact view and InTr receipt.
- **LLM-adapter** is provider transport only. It does not own review evidence or custody.
- **Master Records** relates to organization records and reconstruction only; this protocol does not depend on it or read review data from it.

## Review-source rule

A reviewer MUST NOT establish canonical ecosystem-review evidence by directly accessing another repository.

Each review binding MUST identify:
1. `view_id`;
2. `intr_receipt_id`;
3. `organization_record_id`; and
4. reviewer/entity identity.

Two findings may be represented as reviews of the same evidence only when they bind to the same canonical view and acquisition receipt.

Matching Git commit SHAs alone are insufficient: the canonical review identity is the receipted InTr view.

## Expansion rule

A reviewer encountering required evidence outside its current view MUST NOT finalize with “unconnected source,” “not available to this session,” or an equivalent reviewer-local access limitation.

It MUST return `EXPANSION_REQUIRED` and identify the required scope. Schema submits/resolves the expansion through InTr. InTr either:

- acquires the additional evidence and receipts it, producing a successor immutable view; or
- returns a receipted terminal `EXPANSION_DENIED` or `EXPANSION_FAILED` disposition.

The reviewer resumes from the successor view. Only a receipted terminal acquisition disposition may support a final statement that required evidence was unavailable.

## View immutability and lineage

An existing view is immutable. Repository movement after acquisition does not change it. New source state requires a new InTr acquisition, new receipt, and successor `view_id` linked through `predecessor_view_id`.

## Finalization predicates

A review is finalizable only when:

- all required evidence is present in the bound view; or
- each required item not present is covered by a receipted terminal InTr acquisition disposition.

A reviewer-local connectivity limitation is never a finalization predicate.

## Required failures

- `DIRECT_SOURCE_REVIEW_EVIDENCE_PROHIBITED`: canonical review evidence was independently fetched rather than supplied by Schema/InTr.
- `REVIEW_VIEW_IDENTITY_MISMATCH`: findings represented as reviewing the same evidence bind to different view or InTr receipt identities.
- `EXPANSION_REQUIRED`: required evidence is outside the current view; nonterminal.
- `UNRECEIPTED_UNAVAILABLE_EVIDENCE_PROHIBITED`: unavailable evidence is claimed without a terminal InTr receipt.
- `REVIEW_FINALIZATION_WITH_UNRESOLVED_EVIDENCE_PROHIBITED`: finalization attempted while required evidence remains merely outside the current view.
- `MASTER_RECORDS_REVIEW_DEPENDENCY_PROHIBITED`: this protocol is made dependent on Master Records organization records, their availability, or reconstruction from them.

## Consequence

The owner is not the transport between reviewers. OpenAI, Anthropic, and other participating entities request and consume the same receipted Schema view. Their disagreements are therefore disagreements over the same acquired evidence rather than potentially different repository snapshots.
