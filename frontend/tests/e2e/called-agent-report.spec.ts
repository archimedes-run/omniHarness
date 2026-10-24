import { expect, test } from "@playwright/test";

import {
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
  mockLangGraphAPI,
} from "./utils/mock-api";

/**
 * An agent writes a report file, and the file panel shows its content.
 *
 * The live failure (a lead -> repo-analyst chat): the called-in agent's
 * write_file step streams into the chat while it runs, and the panel opens on
 * it. Its message is the AGENT'S, not the chat's: the thread's saved messages
 * hold only the hand-off and the agent's answer. When the run ends that
 * message is gone, and the panel, which read the file from that message's
 * tool call, went blank although the file was written.
 *
 * The stream is fed in steps from inside the page (route.fulfill sends the
 * whole body at once), so the step is on screen while the run is going.
 */
const REPORT = "/mnt/user-data/outputs/omniHarness_repo_analysis_2026-10-24.md";
const REPORT_BODY = [
  "# omniHarness repo analysis",
  "",
  "Snapshot of the repository on 2026-10-24.",
  "",
  "## Findings",
  "",
  "- Releases are tagged and signed.",
].join("\n");

const human = {
  type: "human",
  id: "h1",
  content: [{ type: "text", text: "@repo-analyst run this on omniHarness" }],
};
const handoff = {
  type: "ai",
  id: "a1",
  content: "",
  tool_calls: [
    {
      name: "call_agent",
      id: "c1",
      args: { agent: "repo-analyst", prompt: "run this on omniHarness" },
    },
  ],
};
// The agent's own step, as it streams into the chat while it runs.
const agentWrite = {
  type: "ai",
  id: "agent-step-1",
  name: "repo-analyst",
  content: "",
  tool_calls: [
    {
      name: "write_file",
      id: "w1",
      args: {
        description: "Write concise repo analysis report",
        path: REPORT,
        content: REPORT_BODY,
      },
    },
  ],
};
// What the thread keeps: the hand-off, its result and the agent's answer.
const saved = [
  human,
  handoff,
  {
    type: "tool",
    id: "t1",
    name: "call_agent",
    tool_call_id: "c1",
    content: `I wrote the report: ${REPORT}`,
  },
  {
    type: "ai",
    id: "a2",
    name: "repo-analyst",
    content: `Deliverable: a concise analysis report.\n\n- File: ${REPORT}`,
  },
];

test("a report an agent writes shows its content in the file panel", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const artifactRequests: string[] = [];
  await page.route(`**/api/threads/*/artifacts${REPORT}*`, (route) => {
    artifactRequests.push(route.request().url());
    return route.fulfill({
      status: 200,
      contentType: "text/markdown; charset=utf-8",
      body: REPORT_BODY,
    });
  });
  await page.addInitScript(
    ({ steps, runId, threadId }) => {
      const original = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        if (!url.includes("/runs/stream")) return original(input, init);
        const encoder = new TextEncoder();
        const sse = (event: string, data: unknown) =>
          encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
        const body = new ReadableStream<Uint8Array>({
          async start(controller) {
            controller.enqueue(
              sse("metadata", { run_id: runId, thread_id: threadId }),
            );
            for (const step of steps) {
              controller.enqueue(sse("values", step));
              await new Promise((r) => setTimeout(r, 1500));
            }
            controller.enqueue(sse("end", {}));
            controller.close();
          },
        });
        return Promise.resolve(
          new Response(body, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        );
      };
    },
    {
      steps: [
        { messages: [human, handoff, agentWrite] },
        { messages: saved, title: "Repo analysis" },
      ],
      runId: MOCK_RUN_ID,
      threadId: MOCK_THREAD_ID,
    },
  );

  await page.goto("/workspace/chats/new");
  const input = page.getByRole("textbox", { name: "Message" });
  await expect(input).toBeVisible({ timeout: 15_000 });
  await input.fill("@repo-analyst run this on omniHarness");
  await input.press("Enter");

  // While the agent runs, its write step opens the panel on the report.
  const panel = page.locator("#artifacts");
  await expect(
    panel.getByText("omniHarness_repo_analysis_2026-10-24.md").first(),
  ).toBeVisible({ timeout: 15_000 });

  // The run ends: the agent's step is no longer in the thread...
  await expect(
    page.getByText("Deliverable: a concise analysis report."),
  ).toBeVisible({ timeout: 15_000 });
  await expect(
    page.getByText("Write concise repo analysis report"),
  ).toHaveCount(0);
  // ...and the panel still shows the report, read from the file itself.
  await expect(
    panel.getByRole("heading", { name: "omniHarness repo analysis" }),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    panel.getByText("Releases are tagged and signed."),
  ).toBeVisible();
  expect(artifactRequests.length).toBeGreaterThan(0);
});
