# Specification Quality Checklist: Assistant UI Surfaces

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-25
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — **with one deliberate exception, see Notes**
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders — except the Preconditions section, by design
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — zero were needed
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

**The Preconditions section deliberately contains implementation evidence.** It names
modules, functions and enum members. That fails a literal reading of "no implementation
details", and it is kept anyway.

The reason is specific to this project rather than general. The input asserted that
three surfaces are read-only views over data that already exists. Two of those claims
hold and one does not, and the one that does not is load-bearing: a rule's
last-evaluated time is recorded nowhere, so FR-017 — the requirement that makes a
silently-broken rule findable — cannot be satisfied by reading. Discovering that during
implementation would have produced either a blank column or a quietly dropped
requirement. The cost of naming `Outcome.SUPPRESSED` in a spec is lower than the cost of
a requirement written against data that does not exist.

The same check found that coalescing has no recorded linkage, and that no HTTP
confirmation route exists — so "reuse the existing confirmation path" had to be
restated as "call the same recognition, claim and resolution logic", which is what the
input actually intends and what FR-004 now says.

**Two requirements are backend additions, not UI.** FR-020 (record rule evaluations) and
FR-021 (batch identity for coalesced deliveries) are marked as such in the spec. They
are in scope because the success criteria the input itself specifies — SC-008, SC-009,
SC-010 — cannot be met without them.

**One security-relevant judgement is recorded as an assumption rather than asked as a
question**: that pressing an explicit Confirm control is itself the deliberate act, with
no additional typed phrase. The input states that a confirm/decline control *is* the
affordance, so this follows from it; it is flagged because overruling it is cheapest now.
