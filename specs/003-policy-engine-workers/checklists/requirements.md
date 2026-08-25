# Specification Quality Checklist: Permission Policy Engine & Real-World Workers

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-23
**Last validated**: 2026-08-23 (after `/speckit-clarify`, 5 questions)
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
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

## Project-Specific Checks

*Added for this project's standing conventions.*

- [x] Every mechanism the spec depends on is verified against real code before being planned on (Verified Preconditions VP-001..VP-007)
- [x] Mechanisms found broken are stated as broken, not planned around (VP-003 repaired, VP-004 gap, VP-005 blocking, VP-006 bypass)
- [x] Heuristic defaults are labelled as guesses, not presented as measured (Tier 3 expiry interval)
- [x] Gates are specified with an observable failure, not only an assertion (SC-009)
- [x] Blocking dependencies are stated explicitly with their non-blocking scope bounded (DEP-001)
- [x] Requirements that are two mechanisms are written as two requirements (FR-004 / FR-005)
- [x] Honest-limits wording is a requirement, not polish (FR-023, redaction assumption)
- [x] Structural-vs-interpretive gates are structural (FR-034, FR-036, FR-039 — confirmation, decline and disclosure are all system-guaranteed, not model-judged)
- [x] Article XI honoured: acceptance criteria that differ between test and production shape name the production shape (SC-014 real worker count, SC-017 confirm-after-delay)
- [x] Rejected alternatives are recorded with their reasons, not silently dropped (Considered and Rejected — 7 entries)

## Validation Notes — post-clarify (2026-08-23)

Clarification round added 14 requirements (FR-028..FR-041) and 12 success criteria
(SC-013..SC-024). One item regressed and was re-fixed, and one new gap was found:

3. **"Requirements are testable and unambiguous"** briefly regressed on FR-031 (subagent
   confirmation), which asserted a capability the runtime does not have. Verified against the
   code before accepting the answer: a subagent has no checkpointer, so it can be suspended but
   never resumed — the run simply ends, having done nothing, which no test that declines to
   confirm can distinguish from correct refusal. Recorded as VP-008 with the measurement, made
   explicit as FR-032, and SC-017 now requires confirming after a delay so the distinction is
   actually exercised.

4. **"Dependencies and assumptions identified"** — DEP-001 was rewritten from a blocking
   dependency to a resolved one, and the two properties of its resolution that carry into this
   feature are stated so they are not re-derived: the policy layer does NOT run in the elected
   worker, and in-memory state belonging to one worker is lost when it dies.

## Validation Notes — initial

Two items were initially borderline and were corrected before marking complete:

1. **"Success criteria are technology-agnostic"** — SC-004 and SC-009 originally named specific
   files and functions. Rewritten to describe observable outcomes ("inspecting the assistant's
   available capabilities", "the agent-construction site named in VP-006"), with the concrete
   identifiers confined to the Verified Preconditions section where they belong as evidence
   rather than as requirements.

2. **"Requirements are testable and unambiguous"** — the original input's single provenance
   requirement covered two different mechanisms. Split into FR-004 (turn provenance, read at
   dispatch) and FR-005 (content lineage, read from message state), each with its own success
   criterion (SC-001, SC-002), because a combined requirement is satisfiable by implementing
   half of it.

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
