# trigger_engine

Lets the assistant speak first. Rules evaluate on a clock tick or an inbound
event; when one fires it injects an ordinary user turn into a target thread, and
the agent's reply is delivered to a destination.

**A firing is just a turn.** That single decision is the design: the agent's
existing skills, tools and memory come along for free, and no second execution
path exists to drift from the first.

## Running

The engine runs **in the gateway process** — not for convenience. The gateway's
internal auth token is generated per process (`secrets.token_urlsafe(32)` at
import) and validated in-process, so a separate process cannot authenticate.
Out-of-process would need a service-account credential concept that does not
exist; a 7-day user JWT is not one.

Registration is `app/trigger_engine/lifespan.py`, started from the gateway's
startup. **A failure to start the engine must never prevent the gateway from
starting** — the engine is an addition to the assistant, not a precondition for
it.

## Authoring rules

See `specs/002-trigger-scheduler-engine/contracts/rule-schema.md`. The rule file
is the public interface; changes to it are breaking changes.

```yaml
rules:
  - id: blocked-session          # unique; the thread-map key
    type: watcher                # watcher | cron | completion
    match: {event: waiting-on-user}
    prompt: "{project} is waiting: {last_message}"
    destination: auto            # auto | remote | quiet
    urgent: false                # explicit; there is no implicit escalation
```

Edits take effect on the next evaluation with no restart. **An invalid edit
leaves the previous configuration active** and reports the error — a config that
fails open is worse than one that fails to load, because nobody notices.

## Configurable values — all heuristics, all stated as such

None of these are measured. They are starting points, and Article X forbids
presenting a guess as a derived value.

| Setting | Default | What it decides |
|---|---|---|
| coalescing window | 60 s | how long firings accumulate into one message |
| presence threshold | 5 min | how recently you must have spoken to count as present |
| queued-turn bound | 5 min | how long a proactive turn waits behind an exchange |
| fingerprint retention | 24 h | how long an event is remembered as already-fired |
| quiet hours | 22:00–07:30 | when non-urgent delivery is suppressed |

## Politeness is not polish (Article VII)

Decisions are made in this order, and the order is asserted by a test:

1. **Quiet hours** — a 3am message is the worst outcome, so nothing downstream
   may undo the decision. Suppressed firings are *deferred*, re-checked at
   release, and released **through coalescing**: a backlog arriving as six
   notifications at 7:30am is the behaviour most likely to get this muted.
2. **Mid-exchange** — talking over someone is the second worst. Unknown busyness
   holds rather than sends: a short delay costs less than an interruption.
3. **Coalescing** — several firings become one message.
4. **Delivery** — through `release()`, the only thing that delivers.

Event types with no re-checkable condition (cron, completion) **expire** rather
than delivering unverified, so "re-check" never degrades into "deliver anything
we cannot disprove".

## Not firing twice

An event's identity is `(rule_id, event_id, fingerprint)`, and the fingerprint's
permitted inputs are **enumerated per trigger type** in `fingerprint.py`.

Only values that change when the event genuinely changes may contribute.
Elapsed time, last-activity and quiet duration are explicitly forbidden: a
drifting input makes every evaluation a "new" event, producing an alert per
cycle. That is the inverse of the repeat failure and the worse of the two.

## Development

```bash
cd backend
uv run pytest tests/trigger_engine/ -q
uv run ruff check app/trigger_engine/
```

### The four gates

Each ships with a way to break it. **A gate never observed failing is
indistinguishable from one that does nothing** — this was not theoretical here:
Gate 4 was configured two different ways that could not see the defect they
existed for, and the sabotage step is what found that.

| Gate | Guards | Break it with |
|---|---|---|
| 1 | Article I imports | add `import langgraph.graph` → ruff must fail; **and** ban `langgraph_sdk` → must also fail, since the SDK is required |
| 2 | the engine cannot crash or stall the gateway | remove the exception barrier, or the timeout |
| 3 | one delivery path | add a second call to `destination.deliver` |
| 4 | nothing defined and never called | add an unreferenced function **or module-level constant** |

Gate 4's whitelist **self-expires**: every deferred entry names the task that
wires it, and the gate fails once that task is marked complete. It went 43 → 20
→ 13 as phases closed, by construction rather than by anyone remembering.
