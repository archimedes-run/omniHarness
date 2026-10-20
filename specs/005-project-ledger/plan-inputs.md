# Feature 005: plan inputs

Things the Project Ledger plan must account for, recorded before the spec was written.

## Unwired definitions that 005 wires (triage, 2026-10-19)

The wiring gate (`backend/tests/gates/test_wiring.py`) found 54 public definitions that no production code reaches. The pre-005 hygiene PR handled them as follows:
- wired 6: four from `app.policy.limits`, `confirm.restate` (FR-035) and `McpSecretsVault.delete_all_for_server`;
- deleted 35, including the two browser-disk constants from `limits.py`;
- reclassified 3 that were reached all along;
- left 10 for this feature.

Each of the 10 stays in `wiring-whitelist.txt`, tagged "wire in Feature 005". The gate fails a stale entry, so wiring one forces its entry to be removed.

| Definition | What 005 uses it for |
|---|---|
| `app.trigger_engine.sources.calendar:CalendarSource`, `DEFAULT_HORIZON` | Calendar evidence, and upcoming meetings on the Today view. Also the trigger for pre-meeting brief automations created from chat. Its rules are rejected at load today (since Phase 1); 005 lifts that. |
| `app.trigger_engine.sources.completion:CompletionSource` | Fires when a ledger task or a workflow run completes (for example, "when the deploy task is done, tell me"). |
| `omniharness.platform.events:PlatformEvent.from_row` | Workflow-run evidence, read back from persisted run events. |
| `omniharness.platform.idempotency:compute_idempotency_key`, `stable_hash` | Scheduled automations created from chat ("every weekday at 9, brief me") must not run twice for one trigger. Today workflow runs are only manual or retry, each with a fresh key. |
| `session_watcher.record_source:RecordStats.drift_signals` | Drift (unknown record types, malformed lines) surfaced per agent, for Claude and Codex alike. It is counted today and read by nothing. |
| `session_watcher.registry:SessionRegistry.is_empty`, `is_observable` | Empty vs can't-tell on the Today view: "no sessions" only when the watcher is live and saw none. |
| `session_watcher.reply:observe_only_notice` | FR-015 wording when the user tries to answer a watched session, Claude or Codex. Audit W-4. |

If 005's plan decides one of these is not needed after all, delete it in 005 and say so. It does not go back on the whitelist.
