# Data Model: Permission Policy Engine & Real-World Workers

Entities, their fields, and the state transitions that matter. Validation rules trace to the requirement that imposes them.

---

## Tier

One of three levels of consequence. Not a severity scale — a decision about what must happen before and after a call.

| Value | Before | After |
|---|---|---|
| `TIER_1` | execute | nothing |
| `TIER_2` | execute | disclosure guaranteed in the reply (FR-039) |
| `TIER_3` | state plan, await confirmation | audit entry (FR-011) |

**Rules**
- Ordering exists and is meaningful: exceptions may move a call *up* this list only (FR-037).
- There is no fourth value for "unclassified". A call with no matching rule **is** `TIER_3` (FR-009) — absence resolves to a tier rather than to a missing one, so no code path has to handle "unknown".

---

## ClassificationRule

A user-authored, declarative mapping from a tool-name pattern to a tier.

| Field | Meaning |
|---|---|
| `pattern` | tool-name pattern this rule matches |
| `tier` | the tier for calls matching it |
| `exceptions` | argument-conditional overrides, each with its own tier |
| `source` | which config file and line produced it — carried so FR-038 can name the deciding rule |

**Rules**
- An exception whose tier is **lower** than the rule's is rejected at load time, not ignored at match time (FR-037). Rejecting at load makes the mistake visible when it is made rather than when it matters.
- Rules are declarative and user-owned (FR-007); no rule may be expressed only in code.
- A malformed or unreadable rule set resolves every tool to `TIER_3` (FR-009), not to "no rules".

---

## PolicyDecision

The result of classifying one call. Produced both by real dispatch and by inspection (FR-038), from the same code — an inspection that used a different path would answer a different question.

| Field | Meaning |
|---|---|
| `tool_name` | the call being classified |
| `tier` | the effective tier |
| `deciding_rule` | which rule produced it, or `None` for the unknown-tool default |
| `raised_by_exception` | whether an argument exception moved it up, and which |

---

## PendingAction

A Tier 3 call stated to the user and awaiting an answer. **Durable and reachable from any worker** (FR-028).

| Field | Meaning |
|---|---|
| `id` | stable identifier; what a confirmation references (FR-034) |
| `plan_text` | the plan exactly as stated to the user |
| `targets` | **resolved, specific** items the call will act on (FR-029) |
| `tier_at_statement` | the tier in force when the plan was stated |
| `requester` | lead agent, or the subagent and its delegation chain (FR-033) |
| `expires_at` | when it stops being confirmable (FR-019) |
| `claim` | unset, or the single claim that won (FR-030) |

**State transitions**

```
        stated
          │
          ├── confirmed ──► claimed ──► targets re-checked ──┬── match ──► executed ──► audited
          │                (atomic)                          └── drift ──► declined + restated
          ├── declined ────────────────────────────────────────────────► closed
          ├── unrecognised reply ──► plan restated in full ──► stated
          └── expires ─────────────────────────────────────────────────► closed, not executed
```

**Rules**
- `targets` holds identified items, never the criteria that selected them (FR-029). Re-resolving at execution time would let a confirmation act on a set the user never saw.
- Target drift is a **decline with restatement**, not an approximation and not a silent no-op (FR-029).
- `claim` is taken atomically; a second claimant finds it already taken and does nothing (FR-030).
- `tier_at_statement` governs even if the rules change while pending — a reclassification cannot retroactively downgrade something already awaiting an answer.
- Expiry does not execute (FR-019).

---

## Confirmation

A deterministically recognised act authorising one `PendingAction`. **Never a model judgement** (FR-034).

| Field | Meaning |
|---|---|
| `pending_id` | which action it answers |
| `verdict` | `CONFIRM` or `DECLINE` — both recognised the same way (FR-036) |
| `turn_provenance` | from runtime context; a synthetic turn cannot confirm (FR-004) |
| `content_lineage` | from message state; tool-result content cannot confirm (FR-005) |

**Rules**
- A reply that is neither `CONFIRM` nor `DECLINE` is **not** a `Confirmation`. It causes the plan to be restated in full (FR-035).
- Both provenance checks read structure. Neither consults text.

---

## ExecutionRecord

What a Tier 2 call actually did. The sole source for an appended disclosure (FR-041), and deliberately distinct from the model's narration of the same event.

| Field | Meaning |
|---|---|
| `tool_name` | the tool that ran |
| `arguments` | resolved arguments as passed |
| `result_summary` | outcome, from the tool's own return |
| `disclosed` | whether the reply already covered it |

**Rules**
- An appended disclosure is generated from this record, never from the model's text (FR-041). A model that misdescribes its action would otherwise produce a disclosure that satisfies the coverage check and misinforms — worse than silence, because it carries the system's authority.
- When coverage is uncertain, `disclosed` is treated as `False` and a disclosure is appended (FR-040).

---

## ToolSurfaceRule

Per-server allow/deny controlling what reaches the agent at all — not a tier, an existence question (FR-012, FR-013).

| Field | Meaning |
|---|---|
| `server` | the tool source |
| `allow` / `deny` | unprefixed tool names |

**Rules**
- Applied at **both** assembly points (MCP and connector), and asserted on the final assembled list (D2/R4).
- Distinct from `ClassificationRule` by design: a denied tool has no tier because it is not present. Merging the two would make "absent" expressible only as a tier, which is the weaker guarantee FR-012 rejects.

---

## AuditEntry

Extends Feature 002's live audit log rather than introducing a second one.

| Field | Meaning |
|---|---|
| `actor` | the identity acted as — already required by the existing log |
| `plan_as_stated` | the exact text shown to the user |
| `confirmation` | what authorised it |
| `targets` | the resolved items acted on |

---

## BrowserProfile

An isolated storage context for assistant-driven browsing.

| Field | Meaning |
|---|---|
| `storage_path` | where this profile's state lives |
| `granted_sites` | logins the user deliberately granted |

**Rules**
- `storage_path` must be verifiably distinct from the user's everyday browser profile, demonstrated by test (FR-017, SC-007).
- Verification asserts on the **path actually used by the running browser**, not on the configured value — a configured path that the browser ignores is exactly the inert-mechanism case Article XII exists for.
