# Third-party notices

OmniHarness includes ideas and logic ported from the projects below. Each one's licence is reproduced in full.

## sodiumsun/agenttrail

- Source: https://github.com/sodiumsun/agenttrail, read at commit `e4ba2daa270abd7ecb51565bbfb12386f47ea418`.
- Files read: `packages/kitchen/src/connectors/logs.mjs`, `events.mjs`, `desktop-events.mjs`, `setup.mjs`, and `docs/kitchen/CONNECTING.md`.
- No code was copied verbatim, and no part of its daemon or UI is included. The ideas were re-implemented in Python, in `backend/packages/session_watcher/session_watcher/`:
  - **Codex session discovery** (`adapters/codex.py`): rollouts under `sessions/YYYY/MM/DD/`, selected by modification time because a resumed session keeps its original folder. Turn state comes from task_started, task_complete and turn_aborted; tool activity from function_call and custom_tool_call; subagent rollouts are attached to their parent.
  - **Native todo lists** (`todos.py`): Claude TodoWrite, TaskCreate and TaskUpdate, and Codex update_plan, keeping titles and statuses only.
  - **Deliberate differences**:
    - a todo change is applied only once its tool result confirms success, where the reference applies TodoWrite and update_plan at call time;
    - subagent parents are read in every link shape seen, including the top-level `parent_thread_id` the reference does not read;
    - unknown record types are counted as drift instead of being ignored.

```text
MIT License

Copyright (c) 2026 Kelly Sun

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Logos (Feature 006 logo registry)

Brand logos are trademarks of their owners, used only to identify the service a source connects to (nominative use), unmodified. They are drawn only through `frontend/src/components/brand/` (the one registry). Fetched 2026-10-19; each file was checked for scripts, event handlers and external references before it was added. The eight images previously in `frontend/public/icons/integrations/` (commit 02ddf28, source never recorded) were removed.

| Brand | File in this repo | Source | Licence / terms |
|---|---|---|---|
| Gmail | `frontend/public/brand/gmail.svg` | Google's product-logo CDN: `https://fonts.gstatic.com/s/i/productlogos/gmail_2020q4/v8/192px.svg` (sha256 `4a255e631f5e08a0426ec385148d216eb5fe42c82ffa8097b7e44622c6862a6e`) | Google trademark. Google brand terms (https://about.google/brand-resource-center/) and the Google Workspace integration branding guidelines: unmodified, full colour, not combined with other marks. |
| Google Calendar | `frontend/public/brand/googlecalendar.svg` | `https://fonts.gstatic.com/s/i/productlogos/calendar_2020q4/v8/192px.svg` (sha256 `e0020e027f272bdd58126bbeda1df455ad59b95938fd4e4910507648ead35f39`) | As Gmail. |
| Google Drive | `frontend/public/brand/googledrive.svg` | `https://fonts.gstatic.com/s/i/productlogos/drive_2020q4/v8/192px.svg` (sha256 `2897441606067de8560ef21fc1357ce314331f5ac233760b22e3de224cc0bb09`) | As Gmail. |
| Anthropic | path data in `frontend/src/components/brand/marks.ts` | Simple Icons 16.33.0 (`simple-icons-16.33.0.tgz`, sha256 `11e1ab7c25fd0acbf0014c4a88745c33fe0f87341e6d94c7ba1e62334b2d2375`), `icons/anthropic.svg` | Path data CC0-1.0 (Simple Icons). Anthropic trademark; drawn in the theme foreground (black or white), unmodified otherwise. Pending the user's confirmation that Anthropic's brand terms allow this use (Open Question 9). |
| GitHub | `marks.ts` | Simple Icons 16.33.0, `icons/github.svg` (its source: https://github.com/logos) | CC0-1.0 path data; GitHub logo policy (https://github.com/logos): the Mark, black or white, unmodified. |
| Notion | `marks.ts` | Simple Icons 16.33.0, `icons/notion.svg` | CC0-1.0 path data; Notion trademark, black or white mark. |
| Linear | `marks.ts` | Simple Icons 16.33.0, `icons/linear.svg` | CC0-1.0 path data; Linear trademark, monochrome mark. |
| PostgreSQL | `marks.ts` | Simple Icons 16.33.0, `icons/postgresql.svg` (its guidelines: https://www.postgresql.org/about/policies/trademarks/) | CC0-1.0 path data; PostgreSQL Community Association trademark policy. |
| OpenAI | none (monogram "OAI") | pending fetch: https://openai.com/brand | Not in Simple Icons (removed at the owner's request); the brand page could not be fetched here. |
| Slack | none (monogram "S") | pending fetch: https://slack.com/media-kit | Not in Simple Icons (removed at the owner's request); the media kit is a manual download. |
| Outlook | none (monogram "O") | pending fetch: https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks | Microsoft marks were removed from Simple Icons at Microsoft's request. |

Simple Icons is released under CC0-1.0 (https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md); its DISCLAIMER notes that the brands' own trademark terms still apply.
