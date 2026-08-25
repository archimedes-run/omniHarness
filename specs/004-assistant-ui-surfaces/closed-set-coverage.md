# Closed-Set Coverage — what confirmation actually accepts (T014/T015, FR-037)

**Measured 2026-08-25** by normalising each phrase and testing membership, not by
reading the source. `tests/policy/test_confirm_forms.py` is driven from this table, so
the document and the code cannot drift.

## The asymmetry that decides each judgement

**A generous DECLINE set is safe; a generous CONFIRM set is not.**

Wrongly reading a phrase as a decline resolves the action and nothing executes — the
user asks again. Wrongly reading a phrase as a confirmation executes an irreversible
action the user may not have authorised. So a confirm entry must be unambiguous on its
own, while a decline entry only needs to be clearly not-an-approval.

This is the same fail-closed direction as the redactor, and the reason "maybe later" is
accepted as a decline and would never be accepted as a confirmation.

## A normalisation defect found while measuring

`"yes, do it"` normalised to `"yes  do it"` — **two spaces**. `_NORMALISE` substitutes a
space for each stripped character and `.strip()` only trims the ends, so internal runs
survive. Adding the phrase to the set would not have fixed it; the entry would have sat
there looking correct and never matching. Normalisation now collapses internal
whitespace, and T018 asserts punctuation cannot change a verdict.

## The table

| Phrase | Normalised | Before | After | Judgement |
|---|---|---|---|---|
| `yes` | `yes` | CONFIRM | CONFIRM | — |
| `y` | `y` | CONFIRM | CONFIRM | — |
| `do it` | `do it` | CONFIRM | CONFIRM | — |
| `go ahead` | `go ahead` | CONFIRM | CONFIRM | — |
| `confirm` / `confirmed` | | CONFIRM | CONFIRM | — |
| `approve` / `approved` | | CONFIRM | CONFIRM | — |
| `proceed` | `proceed` | CONFIRM | CONFIRM | — |
| `yes please` | `yes please` | rejected | **CONFIRM** | Unambiguous affirmation; among the most common things a person types |
| `yes, do it` | `yes do it` | rejected | **CONFIRM** | The phrase the implementation probe itself typed. Needed the whitespace fix as well as the entry |
| `yes do it` | `yes do it` | rejected | **CONFIRM** | As above |
| `sure` | `sure` | rejected | **CONFIRM** | Unambiguous in reply to a direct question |
| `ok` / `okay` | | rejected | **CONFIRM** | Unambiguous in reply to a direct question |
| `yep` / `yeah` | | rejected | **CONFIRM** | Colloquial but unambiguous |
| `please do` | `please do` | rejected | **CONFIRM** | Unambiguous |
| `send it` | `send it` | rejected | **rejected** | Names an action rather than answering. In reply to a *decline meetings* plan it is not an approval of that plan, and a confirm entry must be unambiguous alone |
| `no` / `n` | | DECLINE | DECLINE | — |
| `don't` / `do not` | | DECLINE | DECLINE | — |
| `cancel` / `stop` | | DECLINE | DECLINE | — |
| `decline` / `declined` | | DECLINE | DECLINE | — |
| `nope` | `nope` | rejected | **DECLINE** | Unambiguous refusal |
| `no thanks` | `no thanks` | rejected | **DECLINE** | Unambiguous refusal |
| `never mind` | `never mind` | rejected | **DECLINE** | Withdrawal. Safe direction |
| `not now` | `not now` | rejected | **DECLINE** | Refusal for this occasion. Safe direction |
| `leave it` | `leave it` | rejected | **DECLINE** | Withdrawal. Safe direction |
| `maybe later` | `maybe later` | rejected | **DECLINE** | Deferral, not approval. Resolving it means nothing happens, which is what the user meant. Would never be a confirm entry |

## What did not change

The set remains **closed and matched exactly after normalisation**. Nothing here
introduces similarity scoring, fuzzy matching, or a model judgement about whether a
reply meant agreement — interpretation was rejected as a security property in Feature
003 and is not reopened. Every addition above is a literal string, and adding another is
a deliberate edit to a list, with a line of reasoning beside it.

A phrase carrying an instruction alongside the affirmation — `"yes and also delete the
rest"` — is still rejected, because the normalised text is not a member. That is
asserted in T018, not merely expected.
