# SV-LLM Provider Installation Mirror Handoff

Updated: 2026-10-11
Scope: 16 provider repositories; provider capability contracts and deterministic offline checks.
Coordination: SV-LLM/.github
Upstream foundation: SVORG-LLM-ORG-FOUNDATION-001 (completed source scope; not reused as installation authorization).
Federation: ORG-FED-SV-LLM-001 (READY; separate).
Installation Goal Task ID: PENDING_CANONICAL_REGISTRY_ASSIGNMENT
COSV: PENDING_CANONICAL_REGISTRY_ASSIGNMENT
Status: SOURCE_IMPLEMENTED + CI_VALIDATED + MERGED (16/16 provider PRs and sandbox#16, expected-head merges, owner-approved 2026-10-11) / REGISTRY_RECONCILIATION_PENDING

## Exact repositories
Google, Meta, Microsoft, xAI, MoonShot_AI, DeepSeek, Mistral, MiniMax, Perplexity_AI, Cohere, IBM, Z_AI, Alibaba_Cloud, NVIDIA, Amazon_Web_Services, AI21_Labs.

## Contract
Provider declarations and deterministic tests only; provider responses are evidence, never authority. No independent governance, custody, ledger, credentials, worker claims, or routing. Preserve existing StegVerse-org Git-backed architecture and InTr/SDK/Publisher chain. No live provider invocation without authentic authorized interface. Non-ALLOW outcomes must be explicit.

## Execution sequence
1. Reconcile canonical Registry installation task and COSV; update this handoff.
2. Check default branch initialization for each provider; initialize safely where possible.
3. Add capability manifests, fail-closed adapter contracts, negative offline tests, CI and README.
4. Validate exact-head checks; merge only with expected-head protection.
5. Update coordination README and evidence here.

## Shared contract
SV-LLM/sandbox#16 (head `1ed0f5c946a3b136e1c335b92b98766e490ecdd4`, merged as `6c0e88990280930fc86377f5cbcbce8c45a7beab`): `sv-llm.provider-capability/v0.1` schema, offline validator `runtime/provider_capability.py` (ALLOW / DENY / FAIL_CLOSED), 16 negative fixtures, CI step. Exact-head `validate`: success.

## Repository completion matrix (2026-10-11)
Before: all 16 repositories had no refs (`list_branches` empty); 0 branches, 0 PRs, 0 merges, 0 runtime certifications.

Initialization: each `main` received one README-only commit so the package could be reviewed by pull request; no base commit was invented beyond that.

| Repository | Before | Init `main` | PR | Head | DOCUMENTED ops | SOURCE_IMPLEMENTED | CI_VALIDATED (exact head) | MERGED | RUNTIME_OBSERVED |
|---|---|---|---|---|---|---|---|---|---|
| Google | no refs | `497aab2` | [#1](https://github.com/SV-LLM/Google/pull/1) | `ce19edc6979e` | 15/18 | yes | yes | `b61d613` | no |
| Meta | no refs | `54816c2` | [#1](https://github.com/SV-LLM/Meta/pull/1) | `c063fb931838` | 6/9 | yes | yes | `4d6840c` | no |
| Microsoft | no refs | `00490b2` | [#1](https://github.com/SV-LLM/Microsoft/pull/1) | `99e4d3c4fc16` | 8/9 | yes | yes | `3341dfa` | no |
| xAI | no refs | `cb09c77` | [#1](https://github.com/SV-LLM/xAI/pull/1) | `3203d600c0db` | 7/9 | yes | yes | `8d18f2d` | no |
| MoonShot_AI | no refs | `56d8e54` | [#1](https://github.com/SV-LLM/MoonShot_AI/pull/1) | `457e7d9bdd9d` | 7/9 | yes | yes | `1856aa6` | no |
| DeepSeek | no refs | `f748173` | [#1](https://github.com/SV-LLM/DeepSeek/pull/1) | `7e28ca0428ed` | 2/9 | yes | yes | `4ce8d1d` | no |
| Mistral | no refs | `b030316` | [#1](https://github.com/SV-LLM/Mistral/pull/1) | `193a2e514398` | 5/9 | yes | yes | `0b9576c` | no |
| MiniMax | no refs | `eccbb6e` | [#1](https://github.com/SV-LLM/MiniMax/pull/1) | `e8f3e5302b4d` | 3/9 | yes | yes | `ea81f9e` | no |
| Perplexity_AI | no refs | `91bd112` | [#1](https://github.com/SV-LLM/Perplexity_AI/pull/1) | `4dc34ae4397b` | 5/9 | yes | yes | `0851c51` | no |
| Cohere | no refs | `cf09624` | [#1](https://github.com/SV-LLM/Cohere/pull/1) | `5f5884556d35` | 8/9 | yes | yes | `204f163` | no |
| IBM | no refs | `95dc21a` | [#1](https://github.com/SV-LLM/IBM/pull/1) | `624f86c66601` | 2/9 | yes | yes | `ef39b62` | no |
| Z_AI | no refs | `e0f1ed1` | [#1](https://github.com/SV-LLM/Z_AI/pull/1) | `9ce4c26cdead` | 5/9 | yes | yes | `eb9efd5` | no |
| Alibaba_Cloud | no refs | `5839150` | [#1](https://github.com/SV-LLM/Alibaba_Cloud/pull/1) | `2741fc384fa7` | 5/9 | yes | yes | `abf6f8d` | no |
| NVIDIA | no refs | `75f2275` | [#1](https://github.com/SV-LLM/NVIDIA/pull/1) | `77dac233e8d8` | 4/9 | yes | yes | `15b86ff` | no |
| Amazon_Web_Services | no refs | `61e8641` | [#1](https://github.com/SV-LLM/Amazon_Web_Services/pull/1) | `30cab6d82c03` | 5/9 | yes | yes | `c990257` | no |
| AI21_Labs | no refs | `b111a26` | [#1](https://github.com/SV-LLM/AI21_Labs/pull/1) | `dabb33afed26` | 5/9 | yes | yes | `0848651` | no |

Each package: `capability.json`, `README.md`, `tests/test_capability.py` (34 offline tests), `.github/workflows/capability-validation.yml`, `docs/PROVIDER_INTERFACE.md`, `docs/EVIDENCE.md`, vendored validator pinned by sha256. Operations are DOCUMENTED only where the term appears in a fetched official page (URL, redirect, HTTP status, body sha256 recorded); all others are UNVERIFIED. Consumer interfaces (Meta AI, Microsoft Copilot) are `DOCUMENTED_NOT_INVOKED`. Each provider's published access policies are recorded under `access-policy/` as stated awareness, with no gating effect.

## Open predicates (non-ALLOW until satisfied)
- Installation task / COSV: canonical Registry assignment; the Registry is not reachable from the executing session.
- RUNTIME_OBSERVED: an admitted Sandbox tool run, credentials stored exclusively in the SKAP Vault (KV/_Vault/SKAP) under TV/TVC authority, accessed only by admitted manifest transitions (an InTr transition only where the access crosses between two distinct organizations; never an InTr hop inside one organization, Rigel's rule 2026-10-25), and admissible runtime evidence. None exist; none claimed. Runtime observation holds SV-LLM-EXEMPTION-004 (`data/organization-role-exemption-register.json`) until an organization receipt is read back.
- Binding terms pages (SV-LLM/.github#30 W3): OpenAI, Perplexity_AI and xAI answer automated retrieval with bot challenges (403). Bot checks are never bypassed and no headless browser is added. Disposition `OWNER_SAVED_COPIES_REQUIRED` (non-ALLOW): the owner saves each page (PDF or web archive) into that provider repository's `access-policy/`, recorded with its sha256. Retry entrypoint: StegVerse-org/.github#152.

## Evidence
Repository inventory verified on 2026-10-11; no provider runtime certification inferred. This handoff is evidence, not state-transition authority.
