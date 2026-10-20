import { expect, test, type Page } from "@playwright/test";

/**
 * T076 — the policy inspector, asserted against what renders.
 *
 * NO BACKEND: the three routes are intercepted. That explain runs nothing and
 * uses live dispatch's classify, and that a refused edit keeps the rules in
 * force, are pytest's (tests/test_policy_inspector.py).
 */

const RULES = {
  source_file: "default_rules.yaml",
  rules: [
    { pattern: "gmail_fetch_*", tier: 1, exceptions: [], source_line: 10 },
    {
      pattern: "calendar_delete_event",
      tier: 3,
      exceptions: [],
      source_line: 20,
    },
  ],
  unreadable: false,
  kept_previous: false,
  error: null as string | null,
  threshold_targets: 10,
  expires_after_seconds: 14400,
  cannot_do: [
    {
      capability: "send email",
      wording: "I can't send email — I have no tool that sends.",
    },
  ],
};

const RUN = {
  at: "2026-10-20T13:00:00Z",
  actor: "default",
  tool: "calendar_delete_event",
  plan_as_stated: "I will delete 1 event: Standup",
  targets: ["Standup"],
  authorised_by: "worker-1",
  outcome: "executed",
  withheld: false,
};

const AUDIT = [RUN];

const SAFETY = "/workspace/settings/safety";
const ACTIVITY = "/workspace/settings/activity";

async function serve(page: Page, rules = RULES, audit = AUDIT, path = SAFETY) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/policy/rules", (route) =>
    route.fulfill(json(rules)),
  );
  await page.route("**/api/policy/audit", (route) =>
    route.fulfill(json(audit)),
  );
  await page.route("**/api/policy/explain*", (route) => {
    const tool = new URL(route.request().url()).searchParams.get("tool");
    const known = tool === "calendar_delete_event";
    return route.fulfill(
      json({
        tool,
        tier: 3,
        deciding_rule: known ? "calendar_delete_event → Tier 3" : null,
        from_default: !known,
        refused: !known,
        raised_by: null,
        in_plain_words: known
          ? `I won't use ${tool} until you confirm. I'll tell you what I intend to do first.`
          : `Refused: ${tool} was not run, because no permission policy rule covers it, and a tool without a rule is never run on a default.`,
        absent:
          tool === "send email"
            ? "I can't send email — I have no tool that sends."
            : null,
      }),
    );
  });
  await page.route("**/api/triggers/firings", (route) =>
    route.fulfill(json({ firings: [] })),
  );
  await page.goto(path);
}

async function check(page: Page, tool: string) {
  await page.getByLabel("Tool name").fill(tool);
  await page.getByRole("button", { name: "Check" }).click();
  return page.getByTestId("tier-result");
}

test("a tool no rule names reads as refused, apart from a classified Tier 3 (FR-027, 007)", async ({
  page,
}) => {
  await serve(page);

  const classified = await check(page, "calendar_delete_event");
  await expect(classified).toHaveAttribute("data-from-default", "false");
  await expect(classified.getByTestId("deciding-rule")).toContainText(
    "calendar_delete_event",
  );
  await expect(classified).toContainText("Tier 3");
  await expect(classified.getByTestId("refused-marker")).toHaveCount(0);

  const unknown = await check(page, "some_tool_nobody_classified");
  await expect(unknown).toHaveAttribute("data-from-default", "true");
  await expect(unknown.getByTestId("refused-marker")).toHaveText(
    "No policy rule — refused",
  );
  // Not given a tier it would never be acted on at.
  await expect(unknown).not.toContainText("Tier 3");
  await expect(unknown.getByTestId("deciding-rule")).toContainText("never run");
});

test("a refused edit is stated, above the rules still in force (FR-029)", async ({
  page,
}) => {
  await serve(page, {
    ...RULES,
    kept_previous: true,
    error: "policy rules malformed: while parsing a flow sequence",
  });

  await expect(page.getByTestId("kept-previous")).toContainText("refused");
  await expect(page.getByTestId("kept-previous")).toContainText("malformed");
  await expect(page.getByTestId("rule")).toHaveCount(2);
});

test("a Tier 3 action shows the plan as stated and who authorised it (FR-028)", async ({
  page,
}) => {
  await serve(page, RULES, AUDIT, ACTIVITY);

  const run = page.getByTestId("execution");
  await expect(run.getByTestId("plan")).toHaveText(
    "I will delete 1 event: Standup",
  );
  await expect(run.getByTestId("authorised-by")).toHaveText("worker-1");
});

test("a recorded plan that failed redaction shows as withheld (FR-031, SC-015)", async ({
  page,
}) => {
  await serve(
    page,
    RULES,
    [
      {
        ...RUN,
        plan_as_stated:
          "Withheld: this could not be safely redacted for display. Check it locally.",
        targets: [
          "Withheld: this could not be safely redacted for display. Check it locally.",
        ],
        withheld: true,
      },
    ],
    ACTIVITY,
  );

  await expect(page.getByTestId("withheld")).toBeVisible();
  await expect(page.getByTestId("plan")).toHaveCount(0);
});

test("the check says what will happen in plain words, and an absent capability is not given a tier (FR-023)", async ({
  page,
}) => {
  await serve(page);
  const result = await check(page, "calendar_delete_event");
  await expect(result.getByTestId("plain-words")).toContainText(
    "I won't use calendar_delete_event until you confirm",
  );

  await page.getByLabel("Tool name").fill("send email");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByTestId("absent")).toContainText("I can't send email");
  await expect(page.getByTestId("tier-result")).toHaveCount(0);
});

test("the Safety page lists what the assistant cannot do at all (FR-023)", async ({
  page,
}) => {
  await serve(page);
  await expect(page.getByTestId("cannot-do")).toContainText("send email");
  await expect(page.getByTestId("cannot-do")).toContainText(
    "I have no tool that sends",
  );
});
