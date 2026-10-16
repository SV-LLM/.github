# InTr Destination Capability Mirror Handoff

**Repository:** `SV-LLM/.github`
**Mirrors:** [StegVerse-org/.github#175](https://github.com/StegVerse-org/.github/pull/175), [StegVerse-Labs/.github#3200](https://github.com/StegVerse-Labs/.github/pull/3200)
**Coordinating issue:** [StegVerse-Labs/.github#2897](https://github.com/StegVerse-Labs/.github/issues/2897)
**Capability:** `intr-destination` / `InTr:Destination` / `DIAGNOSTIC_CROSSING`
**Address:** `sv-llm.intr-destination` → `ORGANIZATION_INTR_DESTINATION_INGRESS`
**Operation:** `resident-runtime/intr_destination_ingress.py`
**Boundary document:** `org-runtime/interlock-intr.json` → `ingress.capability_endpoint_bindings`, `egress.peer_capability_resolution`
**Status:** ADVERTISED_AND_SERVED_HERE_PEER_INSTALLATION_UNPROVEN

## Why this capability exists

A peer could be addressed at a purpose route — governance — or at
`org-control`. Neither is a universal destination. `org-control` answers a
control message. A diagnostic that only asks whether an organization is
reachable as an InTr destination had to borrow one of those, and a borrowed
purpose route reads as that purpose.

`intr-destination` is the mesh primitive those routes sit on. Every
organization can advertise it. A crossing that uses it is a purpose-neutral
diagnostic: an `ecosystem.communication` whose body schema is
`stegverse.org-intr-destination-diagnostic/v1`. It acknowledges. It does not
govern, classify, admit, route, or execute.

Authority and time are constraint variables. The disposition is transition
evidence only.

## What is declared here

The overlay remains the declaration of which capability is bound. One
binding, owned here:

```text
profile_id     intr-destination
profile_name   InTr:Destination
operation      DIAGNOSTIC_CROSSING
reader         ECOSYSTEM_COMMUNICATION
address        sv-llm.intr-destination
role           BOUNDARY_LOCAL_CAPABILITY_INGRESS
operation_id   ORGANIZATION_INTR_DESTINATION_INGRESS
authority      constraint variable (CONSTRAINT_VARIABLE)
time           constraint variable (CONSTRAINT_VARIABLE)
disposition    TRANSITION_EVIDENCE_ONLY
```

`selects_processing_at_this_address` is false on the registry row and on the
binding. An address cannot select its own capability: `capability_ingress.receive`
refuses a row the overlay does not name, and it refuses a module whose
`OPERATION_ID` is not the one the binding publishes.

The profile name is local. The pinned SDK subsystem baseline does not declare
it, and `StegVerse-Labs/StegOS` `specs/universal-intr-connector-profiles.v1.json`
was not readable when this binding was added. This repository therefore does
not claim the canonical connector registry already named `InTr:Destination`.
The declaration owner is `SV-LLM/.github`.

SV-LLM does not serve `sdk-manifest-ingress`. This is the one capability
address served here, so `proven_on_this_organization` is the string
`sv-llm.intr-destination`. A list is required only when more than one address
is served. A peer address in that field is refused. The field is not a peer map.

`SUBMIT_MANIFEST` still uses the manifest reader inside the resolver. The
diagnostic names `ECOSYSTEM_COMMUNICATION`, so a communication is not refused
for lacking a manifest and a manifest is not accepted as a diagnostic. The
validator refuses a non-manifest operation that tries to inherit the manifest
reader.

SV-LLM dispatch previously refused `BOUNDARY_LOCAL_CAPABILITY_INGRESS` as an
uninstalled endpoint adapter. Serving the address required the kernel to
resolve that role through `capability_ingress.receive`. The receiving
operation records both ledger levels itself. The kernel does not write a
second federation-crossing receipt for the same frame. A refusal at this
address is raised, not swallowed as a federation refusal, because the
operation records its own refusal when it is the operation that ran.

The organization append owner is `append` on
`resident-runtime/aggregate_repo_transition.py`, the same writer the kernel
uses for a crossing it records itself. The binding names that function.

Manifest egress in `org-runtime/crossing.py` still does not close. Those
manifests request no response. The diagnostic is an `ecosystem.communication`,
which the transport profile answers, so emit and close for this capability
live in `resident-runtime/organization_egress_boundary.py`. That module does
not add a governance or remediation destination binding. `federation.json` is
unchanged.

## What a peer address is

`resolve_destination(peer, capability="intr-destination")` derives
`organization_slug(peer) + "." + "intr-destination"`. Peer capability services
are not written into `federation.json`.
`peer_serves_this_capability_is_proven_here` stays false at resolution. An
unserved address does not close.

`stegverse-org.intr-destination` is derived when SV-LLM emits outbound. It is
not listed as proven here.

## What the crossing proves

| | |
| --- | --- |
| This organization advertises and serves the address | yes — a frame published to `sv-llm.intr-destination` is consumed and receipted at both ledger levels |
| The acknowledgement changes an authority or time constraint | no — both stay constraint variables; the disposition is transition evidence only |
| A peer address is derived, not enumerated | yes — outbound emission addresses `stegverse-org.intr-destination` |
| The peer installed the receiving operation | **not proven at resolution** |
| Something at the addressed service ran this packet | yes, **at closure**, when the far-side terminal receipt recomputes from the responded request class and the `communication_id` |
| Which organization that boundary belongs to | **no** |
| The far side persisted the chain on its own ledger | **no** |
| No answer is a close | no — `close` returns `PENDING` and writes nothing |

The unit test's far side is this repository's `kernel.receipt` and
`build_control_response`, placed in a temporary mesh. That is a fabricated
answer. It is not a live peer, and it is not an authentic production receipt.

`capability_destination_bindings` are absent, as they were. This change does
not add a governance or remediation destination binding.

## Verified

`tests.test_intr_destination_capability` covers the declaration, the overlay
fail-closed miswires, derived resolution, the refused undeclared capability,
receipt of a diagnostic at this address, emit `ALLOW`, close `PENDING` with no
answer, and close `ALLOW` when the fabricated far side answers.

`org-runtime/runtime_boundary.py validate` includes `capability_addresses_resolve`
and `peer_capability_addresses_derive`.

Both ledger roots in the unittest and in CI are redirected. The mesh is a
temporary directory.

## What other organizations do next

StegVerse-org/.github#175 is the template. StegVerse-Labs/.github#3200 is the
mirror this repository followed where the kernel had to learn
`BOUNDARY_LOCAL_CAPABILITY_INGRESS`. Other federation organizations mirror the
same binding in their own `.github` repositories. This change does not install
the capability for them, and it does not claim they already serve it.

## Follow-up

`org-boundary/runtime/capability_ingress.py` is a byte copy of the
StegVerse-org resolver and was left byte-identical. It still uses the upstream
wording for the admission-constraint field and the upstream prose about what
an address can do to itself. Those strings are named in the pull request
description. Replacing them belongs in a later change that can edit the copied
resolver, or in the upstream copy, without drifting this file from the bytes
it was taken from.
