import { expect, test } from "@playwright/test";

import { THREAD, bar, chip, message, openPicker, stub } from "./chat-bar-stubs";

/**
 * Feature 006 chat bar, on the production build, with every API stubbed.
 *
 * The Integrations tab is the existing per-thread tool selection made
 * visible, so the toggle is asserted on the request that leaves the browser
 * (PUT /api/threads/{id}/tools), not on the switch's own state.
 */

test("every piece of context is its own chip; removing a project detaches it", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(bar(page).getByTestId("chip-project")).toHaveText(/OmniHarness/);
  // The chat's own agent stays: no ×, and it says why.
  await expect(chip(page, "agent", "Lead agent")).toBeVisible();
  await expect(chip(page, "agent", "Lead agent")).toContainText(
    "A chat keeps the agent it started with",
  );
  await expect(
    chip(page, "agent", "Lead agent").getByRole("button"),
  ).toHaveCount(0);
  await expect(chip(page, "integration", "Google Calendar")).toBeVisible();
  // A pinned integration is always on: no ×.
  await expect(chip(page, "integration", "filesystem")).toContainText(
    "Always on in every chat",
  );
  await expect(
    chip(page, "integration", "filesystem").getByRole("button"),
  ).toHaveCount(0);
  // Skills are set in the picker, not shown as chips.
  await expect(bar(page).getByTestId("chip-skill")).toHaveCount(0);

  await page
    .getByRole("button", { name: "Remove project OmniHarness" })
    .click();
  await expect.poll(() => seen.deletes.length).toBe(1);
  expect(seen.deletes[0]).toContain("/api/ledger/links/l1");
});

test("removing an integration chip deselects it for the thread; a pinned one cannot be removed", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await page
    .getByRole("button", { name: "Remove Google Calendar from this chat" })
    .click();
  await expect.poll(() => seen.puts.length).toBe(1);
  expect(seen.puts[0]).not.toContain("connector:GOOGLECALENDAR");
  await expect(
    page.getByRole("button", { name: "Remove filesystem from this chat" }),
  ).toHaveCount(0);
});

test("the picker is a real tablist: arrow keys move, Esc closes and focus returns to +", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const picker = await openPicker(page);
  const tablist = picker.getByRole("tablist", { name: "Context type" });
  await expect(tablist.getByRole("tab")).toHaveText([
    "Projects",
    "Agents",
    "Integrations",
    "Skills",
    "Files",
  ]);
  await expect(picker.getByRole("tab", { name: "Integrations" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(picker.getByRole("tab", { name: "Skills" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("ArrowLeft");
  await expect(
    picker.getByRole("tab", { name: "Integrations" }),
  ).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft");
  await expect(picker.getByRole("tab", { name: "Agents" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Escape");
  await expect(picker).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add context" })).toBeFocused();
});

test("integrations: status in words, the two-stage connector status, links to MCP Suite, the tool count", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const picker = await openPicker(page);
  const row = (name: string) =>
    picker.getByRole("listitem").filter({ hasText: name });

  await expect(row("filesystem").getByTestId("integration-status")).toHaveText(
    "Live · 4 tools",
  );
  await expect(row("filesystem")).toContainText("Always on");
  await expect(
    row("Google Calendar").getByTestId("integration-status"),
  ).toHaveText(/^Live · last worked 5 minutes ago$/);
  await expect(row("Gmail").getByTestId("integration-status")).toHaveText(
    "Connected",
  );
  await expect(row("fresh").getByTestId("integration-status")).toHaveText(
    "Not checked yet",
  );
  await expect(row("dead-server").getByTestId("integration-status")).toHaveText(
    "Unreachable",
  );
  await expect(row("dead-server")).toContainText(
    "ConnectError: All connection attempts failed",
  );
  await expect(row("Slack").getByTestId("integration-status")).toHaveText(
    "Not connected",
  );

  // Unreachable and not-connected rows have no switch. An unreachable server
  // links to MCP Suite; an app that is not connected signs in right here.
  for (const name of ["dead-server", "Slack"]) {
    await expect(row(name).getByRole("switch")).toHaveCount(0);
  }
  await expect(
    row("dead-server").getByRole("link", { name: /Check/ }),
  ).toHaveAttribute("href", "/workspace/connections");
  await expect(row("Slack").getByRole("link")).toHaveCount(0);
  await expect(
    row("Slack").getByRole("button", { name: "Connect Slack" }),
  ).toBeVisible();
  await expect(picker.getByTestId("tool-count")).toHaveText(
    "7 / 40 tools for this model",
  );
  await expect(
    row("Slack").getByRole("img", { name: "Slack logo" }),
  ).toBeVisible();
});

test("the integration switch writes the thread's tool selection", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const picker = await openPicker(page);
  await picker.getByRole("switch", { name: "Use Gmail in this chat" }).click();
  await expect.poll(() => seen.puts.length).toBe(1);
  expect(seen.puts[0]).toEqual(
    expect.arrayContaining(["connector:GMAIL", "connector:GOOGLECALENDAR"]),
  );
  await expect(chip(page, "integration", "Gmail")).toBeVisible();
});

test("@ in a new chat: arrows and Enter pick the chat's agent in place; Esc closes", async ({
  page,
}) => {
  await stub(page);
  await page.goto("/workspace/chats/new");
  await message(page).click();
  await page.keyboard.type("@");
  const list = page.getByRole("listbox");
  await expect(list.getByRole("option")).toHaveCount(2);
  await expect(message(page)).toHaveAttribute("role", "combobox");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);

  await page.keyboard.type("r");
  await expect(list.getByRole("option").first()).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("ArrowDown");
  await expect(list.getByRole("option").nth(1)).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(chip(page, "agent", "release-manager")).toBeVisible();
  await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
  await expect(message(page)).toHaveValue("@release-manager ");
});

test("@ in an existing chat calls an agent in (Phase 2): it joins on the server, and the mention stays", async ({
  page,
}) => {
  await stub(page);
  const posted: unknown[] = [];
  await page.route("**/api/threads/*/participants", (route) => {
    if (route.request().method() === "POST")
      posted.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        thread_id: THREAD,
        participants: [
          { name: "lead_agent", description: "", lead: true },
          ...posted.map(() => ({
            name: "researcher",
            description: "",
            lead: false,
          })),
        ],
      },
    });
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  await message(page).click();
  await page.keyboard.type("@res");
  const option = page.getByRole("option", { name: /researcher/ });
  await expect(option).not.toHaveAttribute("aria-disabled", "true");
  await expect(option).not.toContainText("arrives with multi-agent chat");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/workspace/chats/${THREAD}$`));
  await expect(message(page)).toHaveValue("@researcher ");
  await expect.poll(() => posted).toEqual([{ agent: "researcher" }]);
  await expect(chip(page, "agent", "researcher")).toBeVisible();
});

test("/ at the start opens the commands; /project opens the picker on Projects", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await message(page).click();
  await page.keyboard.type("/");
  await expect(page.getByRole("option")).toHaveText([
    /\/new/,
    /\/project/,
    /\/agent/,
    /\/integrations/,
    /\/skill/,
    /\/attach/,
  ]);
  await page.keyboard.type("pro");
  await page.keyboard.press("Enter");
  const picker = page.getByRole("dialog", { name: "Add context" });
  await expect(picker.getByRole("tab", { name: "Projects" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(message(page)).toHaveValue("");
  await picker.getByRole("button", { name: "Attach to Beta launch" }).click();
  await expect.poll(() => seen.links.length).toBe(1);
  expect(seen.links[0]).toMatchObject({
    project_id: "p2",
    to_kind: "thread",
    to_ref: THREAD,
  });

  // "/" anywhere but the start is just text.
  await page.keyboard.press("Escape");
  await message(page).fill("see a/b");
  await expect(page.getByRole("listbox")).toHaveCount(0);
});

test("attachments still work: the file dialog, a file chip, and removing it", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Attach file" }).click();
  await (
    await chooser
  ).setFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("hello"),
  });
  await expect(bar(page).getByTestId("chip-file")).toHaveText(/notes\.txt/);
  await page.getByRole("button", { name: "Remove file notes.txt" }).click();
  await expect(bar(page).getByTestId("chip-file")).toHaveCount(0);
});

test("Send is the one primary button; it sends, and is the Stop button while a reply streams", async ({
  page,
}) => {
  await stub(page);
  let release: () => void = () => undefined;
  const sent: string[] = [];
  await page.route("**/api/langgraph/threads/*/runs/stream", async (route) => {
    sent.push(route.request().postData() ?? "");
    await new Promise<void>((r) => (release = r));
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    });
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  const send = page.getByTestId("send-button");
  await expect(send).toHaveAccessibleName("Send");
  await message(page).fill("hello there");
  await message(page).press("Enter");
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toContain("hello there");
  await expect(send).toHaveAccessibleName(/Stop|Sending/);
  release();
});

test("reasoning effort shows only when the model supports it and the mode thinks", async ({
  page,
}) => {
  await stub(page, {
    models: [
      {
        name: "plain",
        supports_thinking: true,
        supports_reasoning_effort: false,
      },
    ],
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(page.getByRole("button", { name: /^Mode: / })).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^Model: plain/ }),
  ).toBeVisible();
  await expect(page.getByTestId("effort-trigger")).toHaveCount(0);
});

test("with a model that supports effort, the control is there in Pro and gone in Flash", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(page.getByRole("button", { name: "Mode: Pro" })).toBeVisible();
  await expect(page.getByTestId("effort-trigger")).toBeVisible();
  await page.getByRole("button", { name: "Mode: Pro" }).click();
  await page.getByRole("menuitem", { name: /Flash/ }).click();
  await expect(page.getByRole("button", { name: "Mode: Flash" })).toBeVisible();
  await expect(page.getByTestId("effort-trigger")).toHaveCount(0);
});
