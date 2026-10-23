import { expect, test, type Route } from "@playwright/test";

import {
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
  mockLangGraphAPI,
} from "./utils/mock-api";

/**
 * A coding request shows its file in the artifact panel (#92). The run's
 * messages have the shapes the real lead agent produces (write_file, then
 * present_files); backend/tests/security/test_coding_request_e2e.py drives the
 * same request through the real gateway and checks it does not reload.
 */
const OUTPUT = "/mnt/user-data/outputs/first_10_primes.py";
const SCRIPT = "print(*[2, 3, 5, 7, 11, 13, 17, 19, 23, 29])\n";

function codingRun(route: Route) {
  const messages = [
    {
      type: "human",
      id: "h1",
      content: [{ type: "text", text: "Write a primes script and show me" }],
    },
    {
      type: "ai",
      id: "a1",
      content: "",
      tool_calls: [
        {
          name: "write_file",
          id: "w1",
          args: {
            description: "Write the script",
            path: OUTPUT,
            content: SCRIPT,
          },
        },
      ],
    },
    {
      type: "tool",
      id: "t1",
      name: "write_file",
      tool_call_id: "w1",
      content: "OK",
    },
    {
      type: "ai",
      id: "a2",
      content: "",
      tool_calls: [
        { name: "present_files", id: "p1", args: { filepaths: [OUTPUT] } },
      ],
    },
    {
      type: "tool",
      id: "t2",
      name: "present_files",
      tool_call_id: "p1",
      content: "Successfully presented files",
    },
    { type: "ai", id: "a3", content: "Here is first_10_primes.py." },
  ];
  const events = [
    {
      event: "metadata",
      data: { run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID },
    },
    { event: "values", data: { messages, artifacts: [OUTPUT] } },
    { event: "end", data: {} },
  ];
  return route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: events
      .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
      .join(""),
  });
}

test("a coding request's file opens in the artifact panel", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.route("**/api/langgraph/runs/stream", codingRun);
  await page.route("**/api/langgraph/threads/*/runs/stream", codingRun);
  await page.route(`**/api/threads/*/artifacts${OUTPUT}*`, (route) =>
    route.fulfill({ status: 200, contentType: "text/plain", body: SCRIPT }),
  );

  await page.goto("/workspace/chats/new");
  const input = page.getByRole("textbox", { name: "Message" });
  await expect(input).toBeVisible({ timeout: 15_000 });
  await input.fill("Write a primes script and show me");
  await input.press("Enter");

  const card = page.getByText("first_10_primes.py", { exact: true }).first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.click();

  // The panel loads the file through the artifacts route and shows its code.
  await expect(
    page.getByText("print(*[2, 3, 5, 7, 11, 13, 17, 19, 23, 29])"),
  ).toBeVisible();
});
