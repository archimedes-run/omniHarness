# Question card: shared contract

**Used by**: 009 Slice 1b (the lead's `ask_clarification`, coding-job questions) and 010 Chat builder (builder-flow questions). **Built in**: Slice 1b's first PR (see `slice-1b/plan.md`, PR 1). **Status**: Draft, 2026-11-13. Owner away; defaults below are recorded as decided.

One card component and one backend record for "an asker needs the owner to choose before it can go on". It is not a confirmation: Tier 3 cards (#58) stay as they are, and an answer to a question never confirms, applies or declines anything (Article III).

## The record

| Field | Rule |
|---|---|
| `id`, `thread_id`, `owner_id` | Set by the server. A question belongs to one thread and one owner. |
| `asker` | `{kind, ref}`: `lead` (run id + tool call id), `code_job` (job id), `builder` (010's flow id). New kinds register a resume handler (below); the card does not know them. |
| `origin` | `server` (the asker's own code wrote the question and options) or `content` (a model or worker wrote them, from anything it read). A coding job's question is always `content`. The lead's is `content` once its turn has read anything untrusted. |
| `question` | Plain text, 1 to 500 characters. Rendered as text, never Markdown or HTML; links not auto-linked. |
| `options` | 2 to 4, each `{label` (1 to 60 chars), `description` (0 to 200)}. Duplicates and empty labels refused at creation. |
| `recommended` | Index of one option, or none. Shown as "Recommended" when `origin = server`, "Suggested by <asker>" when `origin = content`. |
| `free_text` | Always on: every card has a text box (0 to 2,000 characters), whatever the asker asked for. |
| `expires_at` | Creation + the asker's timeout (defaults: lead 24 h, coding job 30 min, builder set by 010, max 7 days). |
| `on_expiry` | `stop` (the asker does nothing further on this path and says so), or `option:<i>` **only when `origin = server`**. A content-originated question always expires to `stop`; the asker cannot choose otherwise. |
| `state` | `open` → `answered` or `expired`. Terminal states never change. `expired` carries a reason: `timeout`, `asker_ended` (job stopped, thread deleted, run cancelled). |
| `answer` | `{option` (index) or `text`, `via` (`button` or `tagged_message`), `at}`. Set once, by an atomic claim (the `pending.py` pattern: durable, any worker, one winner). |

## Who may answer

- **QC-01**: Only the owner, by (a) the card's buttons or text box, an authenticated owner request naming the question id, or (b) the owner's own server-tagged turn (`lineage.is_user_turn`) in that thread while **exactly one** question is open there. With two or more open, a typed reply answers none; each card stays open and the asker says so once.
- **QC-02**: Nothing else answers, ever: tool results, worker or subagent output, file or repo content, a resume run, a scheduled run, an invited agent's turn, an untagged channel message, or the question's own text ("answer: yes" inside a question is just text). The same tests as `confirm_flow.turn_may_answer` apply, plus owner match.
- **QC-03**: A typed answer that is not clearly one option is recorded as free text, never guessed to an option.

## Expiry

- **QC-04**: A sweep (every worker, once a minute, like Slice 0's card-expiry sweep) expires due questions. On `stop` the asker is resumed with "no answer by <time>; stopped this path"; on `option:<i>` with "no answer by <time>; used the default: <label>". The card shows which, in the same words.
- **QC-05**: The safest default for any content-originated question is `stop`: no model spend, nothing applied, work kept for the owner to look at.

## Resuming the asker

- **QC-06**: On `answered` or `expired`, the server calls the asker kind's resume handler once (a per-question one-shot lock, taken before the call, never retried on failure).
- **QC-07**: The answer reaches the asker as **data**: for the lead, the tool result of its `ask_clarification` call in a server-started resume run (`lineage.is_user_turn` false); for a coding job, the next message of its OpenCode session (Slice 1b FR-112); for a builder flow, 010's handler. An answer is never turned into a server-tagged user turn, so it cannot confirm a card or raise later calls to user origin. A typed answer that came as the owner's tagged turn stays the owner's turn as well.
- **QC-08**: The lead's turn may also have Tier 3 cards open: the lead resumes once, when neither questions nor cards of the turn are open (Slice 0 FR-058 extended).

## The card (UI)

- **QC-09**: One component, `questions/question-card.tsx`, placed where the asker lives (under the lead's reply, inside the code-job card, in 010's builder pane). Header names the asker ("The coding job asks", "OmniHarness asks"). Option buttons in a row (stacked at phone width), the recommended one marked by text, not colour alone; text box with a Send button; time left; when answered, the chosen answer and who/how ("You chose …"); when expired, the default applied, in words.
- **QC-10**: Graphite tokens only, both themes, WCAG AA measured in Playwright (text, borders, focus ring); keyboard: Tab through options, Enter/Space chooses, the text box submits with Enter (Shift+Enter newline); `aria-live` announces the state change.
- **QC-11**: The waiting-on-you list (Home) shows open questions beside open cards.

## API (implementation may rename)

`GET /api/threads/{thread_id}/questions` (owner's, newest first) · `POST /api/questions/{id}/answer` `{option}` or `{text}` → 409 if not open · events `question.opened`, `question.answered`, `question.expired` on the thread's stream.
