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
