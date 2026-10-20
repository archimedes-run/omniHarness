# Feature 006 design reference (Graphite)

Mockups from the "OmniHarness Workspace Studio" design canvas. Each `.dc.html` file is one screen.
They are design references, not production code. Read the markup for layout, copy, spacing and
colour tokens, then build the real UI with the app's own components and theme tokens.
The `support.js` script tag only works inside the design canvas; ignore it.

`OmniHarness_Workspace_Studio.html` is a self-contained viewer of the whole canvas, for opening in a browser.
Its boards are packed (gzip + base64), so don't grep it. Read the `.dc.html` files instead.

## Precedence: read this first
**Chat-Bar-v2.dc.html is the source of truth for the top bar, the capsule and the chat bar on EVERY screen.**
The other boards were drawn earlier and still show the old small capsule (with ⌘K inside it) and the
old narrow chat bar with grouped chips. For those two components, ignore the other boards and use v2.
Everything else on those boards still stands.

| File | Screen |
|---|---|
| Chat-Bar-v2.dc.html | New chat. Centred capsule (3-column grid top bar, Search ⌘K on the right), 960px chat bar, one removable chip per project/agent/integration/skill, "+N" overflow, Add chip, 36px controls, 40px send |
| Main.dc.html | Home (greeting, Waiting on you, projects, sessions, upcoming) |
| Chat.dc.html | Chat with several agents, @ dropdown, approval card |
| Chat-Picker.dc.html | "+" picker: Integrations tab with logos, status and per-chat toggles |
| Agent-Studio.dc.html | Agents capsule panel, tabbed (Overview, Instructions, Tools, Autonomy, Schedule) |
| Skill-Studio.dc.html | Skills capsule panel, tabbed (Details, Instructions, Files, Test) |
| Tasks.dc.html | Tasks capsule panel: projects, tasks with owners and observed/reported evidence |
| Automations.dc.html | Automations capsule panel: list, on/off, run history with outcomes |
| Connections.dc.html | MCP Suite > Connected: counts, failing source, app cards, MCP servers |
| MCP-Suite.dc.html | MCP Suite > Build: describe, build in sandbox, approve first run |
| Settings.dc.html | Settings > Memory (Summary cards) |
| canvas.json | Board layout and titles |

Logo squares with letters (A, OAI, GH, 31, M, S, GD, N) are PLACEHOLDER slots for the official brand icons in assets/.
