# Contract: Classification Policy Configuration

The user-owned, declarative rule set that assigns tiers to tool calls (FR-007, FR-008). This is a public contract: the user edits it directly, so its failure modes must be legible to a person, not only to a parser.

## Shape

```yaml
policy:
  # Optional. Absent behaves identically to TIER_3 for everything.
  rules:
    - pattern: "session_watcher_*"      # glob over the tool name as the agent sees it
      tier: 1

    - pattern: "googlecalendar_*"
      tier: 1                            # reading events and free/busy

    - pattern: "googlecalendar_create_event"
      tier: 2                            # a hold the assistant can itself remove

    - pattern: "googlecalendar_delete_event"
      tier: 3

    - pattern: "browser_*"
      tier: 1
      exceptions:
        - when: { action: ["click", "submit"] }
          tier: 3                        # RAISES only — see below

  # Optional. Applies to Tier 3 actions awaiting an answer.
  confirmation:
    expires_after: "4h"                  # heuristic default; see below
```

## Rules the loader enforces

| Rule | Behaviour on violation | Requirement |
|---|---|---|
| An exception's tier must be **higher** than its rule's | **rejected at load**, naming file and line | FR-037 |
| A tool matching no pattern | resolves to Tier 3 | FR-009 |
| The file is missing, unreadable, or malformed | **every** tool resolves to Tier 3 | FR-009 |
| Two patterns match one tool | the **highest** tier wins | FR-037 |

Rejecting a lowering exception at load rather than ignoring it at match time is deliberate: the mistake becomes visible when it is made, not when something fails to be guarded.

The highest-tier-wins rule for overlapping patterns follows the same direction as FR-037 — ambiguity resolves toward asking.

## Inspection (FR-038)

The effective tier of a hypothetical call is inspectable without executing it, and reports which rule decided:

```
$ <inspect> googlecalendar_delete_event --args '{"event_id": "abc"}'
tier:          3
decided_by:    rules[3]  pattern "googlecalendar_delete_event"  (policy.yaml:14)
raised_by:     —
```

```
$ <inspect> browser_click --args '{"action": "click"}'
tier:          3
decided_by:    rules[5]  pattern "browser_*"  (policy.yaml:19)  → tier 1
raised_by:     exceptions[0]  when action in [click, submit]  (policy.yaml:22)
```

The second form is the reason FR-038 exists. Raise-only classification is safe but opaque; without a way to see *why* a call was raised, the pressure to add lowering exceptions returns — not because they are needed, but because the policy is unreadable.

Inspection MUST use the same code path as live classification. An inspector with its own implementation answers a different question and would diverge silently.

## `expires_after`

Default **4 hours**. **This is a starting guess, not a measured value** — long enough to survive a meeting, short enough that a forgotten action does not linger for days. It is labelled as a guess here, in the configuration the user reads, and not only in the rationale, so it does not acquire authority it has not earned (Article X).

## Hot reload

The rule set is reloadable without restart. A reload that fails validation **keeps the previous rules and says so**, matching how Feature 002's rule loader already behaves — a config error must not silently widen what is permitted.
