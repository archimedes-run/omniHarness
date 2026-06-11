/**
 * About OmniHarness markdown content. Inlined to avoid raw-loader dependency
 * (Turbopack cannot resolve raw-loader for .md imports).
 */
export const aboutMarkdown = `# [OmniHarness](https://github.com/archimedes-run/omni-harness)

> A self-extending agent platform — the agent builds, registers, and verifies its own capabilities at runtime.

OmniHarness is a long-horizon agent harness for tasks that take minutes to hours: it researches, codes, and creates inside real sandboxes, with memory, subagents, skills, and a multi-channel gateway. The defining bet: the *capability layer itself* is authored by the agent and hot-loaded — and the agent closes its own build-run-fix loops instead of handing you errors to relay back.

---

## What's live

**Live preview** — the agent builds a web app and the preview runs inside the sandbox, proxied straight to your browser. Preview auto-starts when the agent produces a web artifact; a verification gate keeps the agent iterating until the build is clean. You stop being the courier who copy-pastes errors back.

**The harness** — sandboxed execution, subagents, persistent memory, skills, multi-channel gateway (Slack, Telegram, Feishu, DingTalk), MCP client + OAuth.

---

## What's next

Agent-authored connectors and MCP servers built and registered at runtime. Hot skill installation. Workflow triggers. A sandboxed execution model where secrets are scoped per-capability and never readable back by the model.

---

## Links

[GitHub](https://github.com/archimedes-run/omni-harness) · [omniharness.tech](https://omniharness.tech/) · [support@omniharness.tech](mailto:support@omniharness.tech)

---

## License & Attribution

MIT License · [View on GitHub](https://github.com/archimedes-run/omni-harness/blob/main/LICENSE)

OmniHarness is a derivative work of [**DeerFlow**](https://github.com/bytedance/deer-flow) by ByteDance (MIT), forked and evolved into an independent project with its own thesis and roadmap. OmniHarness is not affiliated with or endorsed by ByteDance.

**Original copyright notices retained per MIT terms:**
© 2025 Bytedance Ltd. and/or its affiliates
© 2025–2026 DeerFlow Authors (Daniel Walnut, Henry Li)

Built on [LangChain](https://github.com/langchain-ai/langchain) · [LangGraph](https://github.com/langchain-ai/langgraph) · [Next.js](https://nextjs.org/) · [Shadcn](https://ui.shadcn.com/)
`;
