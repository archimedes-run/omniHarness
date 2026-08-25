# Rules coverage — what the engine would ask about, and why that blocked turning it on

**Measured 2026-08-25** by building the real lead agent and classifying every tool it
actually holds. Not read off the rules file: reading the rules to decide what the rules
should cover proves nothing.

## The finding

| Tool source loaded | Tools | Explicitly classified | Unmatched → Tier 3 |
|---|---|---|---|
| Sandbox + filesystem MCP | 26 | 12 | 14 |
| Sandbox + github + postgres (your real config) | 39 | **3** | **36** |

With your real `extensions_config.json`, three of thirty-nine tools were classified.
Everything else — `ls`, `grep`, `read_file`, every GitHub read — fell to the FR-009
default of Tier 3.

**FR-009 was behaving correctly.** Absence of a rule is meaningful and Tier 3 is the safe
resolution. The defect was coverage: a gate that asks before a directory listing teaches
people to approve without reading, which is the failure the whole tier model exists to
prevent.

## Applied: local reads, listings and metadata → Tier 1

Seven new rules, **each naming one tool**. No `read*` or `*_list*` shortcut — the
existing test rejects any pattern broad enough to swallow the world, and a tool added
later must be classified deliberately rather than inherit Tier 1 from a glob that
happened to fit.

```
ls                          glob                        grep
read_file                   filesystem_directory_tree   filesystem_get_file_info
filesystem_search_files
```

Guarded by `test_a_local_read_never_asks`, with `test_a_local_write_is_not_silenced_by_the_read_rules`
as the control — sabotaged by widening `read_file` to `*file*`, which correctly reported
`write_file became silent`.

## Not applied — these are yours to decide

I have not classified any of the following. Each is a judgement about what the assistant
may do without asking, and guessing them is exactly what you asked me not to do.

### A. Local mutations (4)

`write_file` · `str_replace` · `filesystem_edit_file` · `filesystem_create_directory`

The existing rules already say `filesystem_write*` is Tier 2 and `filesystem_delete*` is
Tier 3, so the shape of an answer exists. The open question is whether the *sandbox*
equivalents follow it: `write_file` and `str_replace` write inside the thread's own
workspace, which is more contained than the MCP filesystem server's allowed directories.
Tier 2 would disclose without interrupting; Tier 1 would make routine file edits silent.

### B. Outbound reads (3)

`web_search` · `web_fetch` · `image_search`

Read-only, and **not local**. Each sends something outward — a query, a URL — to a third
party. Read-only argues Tier 1; Article VIII's privacy default and the fact that the
query itself leaves the machine argue Tier 2. This is the one group where I think the
answer is genuinely non-obvious rather than merely unmade.

### C. GitHub reads (14)

`github_get_file_contents` · `github_get_issue` · `github_get_pull_request` ·
`github_get_pull_request_comments` · `github_get_pull_request_files` ·
`github_get_pull_request_reviews` · `github_get_pull_request_status` ·
`github_list_commits` · `github_list_issues` · `github_list_pull_requests` ·
`github_search_code` · `github_search_issues` · `github_search_repositories` ·
`github_search_users`

Reads of a remote system using your token. By the logic applied to local reads these are
Tier 1; by the logic applied to `web_fetch` they are outbound. They are listed separately
from B because the destination is one you already authorised.

### D. GitHub writes (12)

`github_add_issue_comment` · `github_create_branch` · `github_create_issue` ·
`github_create_or_update_file` · `github_create_pull_request` ·
`github_create_pull_request_review` · `github_create_repository` ·
`github_fork_repository` · `github_merge_pull_request` · `github_push_files` ·
`github_update_issue` · `github_update_pull_request_branch`

Several are outbound in Article II's sense — a comment, a review and a PR all reach other
people, and none can be unsent. `github_merge_pull_request` is irreversible in practice.
Left Tier 3 by default, which is probably right, but by default rather than by decision.

### E. `postgres_query` — a special case worth its own look

**The name cannot tell you what it does.** `SELECT` and `DELETE FROM` arrive through the
same tool. No name-pattern rule can classify it correctly, so it is the first real case
for the per-argument exception mechanism (FR-037, raise-only), which can lift the tier
when an argument matches while never lowering it.

Until then it stays Tier 3 by default, which is the safe end of a rule that cannot be
written by name alone.

## What to expect while living with it

With the applied rules and your real config, the assistant will still ask before every
GitHub read, every web search, and every file write. That is Tier 3 by *default* rather
than by decision, and it is the list above. A day of use is what tells us which of those
prompts read as protection and which read as noise — cheaper to learn now than after
three more surfaces are built on top.
