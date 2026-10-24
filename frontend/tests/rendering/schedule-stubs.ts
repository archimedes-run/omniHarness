import type { Page, Route } from "@playwright/test";

/**
 * Per-agent schedules (Feature 006-F): a small STATEFUL stand-in for the rule
 * file, in the real response shapes, layered over stubStudio (later routes
 * win). The agent's runs are app/gateway/agent_runs_view.py's AgentRunsView
 * (rules_version, writable, schedules with telegram / show_on_home);
 * schedule writes are the Studio schedule routes (ScheduleWrite in,
 * ScheduleWritten out, a stale version is a 409); the Automations list is
 * /api/triggers/rules (RuleView with `agent`). A schedule written here is a
 * rule the Automations panel then lists: one source of truth for both.
 */

export interface ScheduleRule {
  id: string;
  agent: string | null;
  schedule: string;
  timezone: string;
  destination: string;
  show_on_home: boolean;
  enabled: boolean;
  /** What the firing asks (006-G Studio); a default when absent. */
  prompt?: string;
  /** It has run before (the Agents list then says Active). */
  fired?: boolean;
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

/** The specs pin the browser to this zone (test.use timezoneId). */
const BROWSER_ZONE = "America/New_York";

/** hh:mm in the browser's zone, two days on: what the engine would compute
 * for "0 18 * * *"-like schedules, close enough for the panels' wording.
 * Built in BROWSER_ZONE, not the test process's zone (CI runs in UTC). */
function nextAt(hhmm: string) {
  const day = new Date(Date.now() + 2 * 86_400_000).toLocaleDateString(
    "en-CA",
    { timeZone: BROWSER_ZONE },
  );
  const offset = new Intl.DateTimeFormat("en-US", {
    timeZone: BROWSER_ZONE,
    timeZoneName: "longOffset",
  })
    .formatToParts(new Date(`${day}T12:00:00Z`))
    .find((p) => p.type === "timeZoneName")!
    .value.replace("GMT", "");
  return new Date(`${day}T${hhmm}:00${offset || "Z"}`).toISOString();
}

export async function ruleFile(page: Page) {
  const state = {
    version: 1,
    rules: [] as ScheduleRule[],
    writes: [] as { method: string; agent: string; body: unknown }[],
  };
  const v = () => `v${state.version}`;
  const owner = (agent: string) => (agent === "lead_agent" ? null : agent);

  await page.route("**/api/studio/agents/*/runs", (route) => {
    const agent = decodeURIComponent(route.request().url().split("/").at(-2)!);
    const mine = state.rules.filter((r) => r.agent === owner(agent));
    return json(route, {
      agent,
      engine_enabled: true,
      not_set_up_reason: mine.length ? null : "none-name-this-agent",
      rules_error: null,
      rules_version: v(),
      writable: true,
      schedules: mine.map((r) => ({
        rule_id: r.id,
        schedule: r.schedule,
        timezone: r.timezone,
        timezone_named: true,
        enabled: r.enabled,
        next_run: r.enabled
          ? nextAt(
              `${r.schedule.split(" ")[1]!.padStart(2, "0")}:${r.schedule.split(" ")[0]!.padStart(2, "0")}`,
            )
          : null,
        held_until: null,
        error: null,
        name: "",
        prompt: r.prompt ?? "It is {scheduled_at}. Do your scheduled run now.",
        telegram: r.destination !== "quiet",
        show_on_home: r.show_on_home,
      })),
      recent: mine.some((r) => r.fired) ? [{ firing_id: "f1" }] : [],
      quiet_hours: {
        enabled: true,
        start: "22:00",
        end: "07:00",
        timezone: "America/New_York",
      },
    });
  });

  await page.route("**/api/studio/agents/*/schedules**", (route) => {
    const req = route.request();
    const parts = new URL(req.url()).pathname.split("/");
    const agent = decodeURIComponent(parts[4]!);
    const ruleId = parts[6] ? decodeURIComponent(parts[6]) : null;
    const body = (req.method() === "DELETE" ? null : req.postDataJSON()) as {
      schedule: string;
      timezone: string;
      telegram: boolean;
      show_on_home: boolean;
      enabled?: boolean;
      prompt?: string | null;
      version: string;
    } | null;
    const version =
      body?.version ?? new URL(req.url()).searchParams.get("version");
    state.writes.push({ method: req.method(), agent, body });
    if (version !== v())
      return json(
        route,
        {
          detail:
            "The rules file changed since this page loaded it (edited elsewhere?). Reload to see the current rules, then make the change again.",
        },
        409,
      );
    if (req.method() === "DELETE") {
      state.rules = state.rules.filter((r) => r.id !== ruleId);
    } else {
      const rule: ScheduleRule = {
        id:
          ruleId ??
          (state.rules.some((r) => r.id === `${agent}-schedule`)
            ? `${agent}-schedule-2`
            : `${agent}-schedule`),
        agent: owner(agent),
        schedule: body!.schedule,
        timezone: body!.timezone,
        destination: body!.telegram ? "auto" : "quiet",
        show_on_home: body!.show_on_home,
        enabled: body!.enabled ?? true,
        prompt: body!.prompt ?? undefined,
      };
      state.rules = ruleId
        ? state.rules.map((r) => (r.id === ruleId ? rule : r))
        : [...state.rules, rule];
    }
    state.version += 1;
    return json(
      route,
      { rule_id: ruleId ?? state.rules.at(-1)!.id, version: v() },
      req.method() === "POST" ? 201 : 200,
    );
  });

  await page.route("**/api/triggers/rules", (route) =>
    json(route, {
      engine_enabled: true,
      rules_error: null,
      version: v(),
      writable: true,
      not_writable_reason: null,
      quiet_hours: {
        enabled: true,
        start: "22:00",
        end: "07:30",
        timezone: "America/New_York",
      },
      rules: state.rules.map((r) => ({
        id: r.id,
        name: "",
        type: "cron",
        enabled: r.enabled,
        match: { schedule: r.schedule, timezone: r.timezone },
        prompt: "It is {scheduled_at}. Do your scheduled run now.",
        destination: r.destination,
        urgent: false,
        agent: r.agent,
        show_on_home: r.show_on_home,
        activity: "never-evaluated",
        last_evaluated_at: null,
        last_evaluated: "never",
        last_fired_at: null,
        last_outcome: null,
        next_run: "scheduled",
        next_run_at: "2030-01-07T18:00:00-05:00",
        timezone: r.timezone,
      })),
    }),
  );
  await page.route("**/api/triggers/rules/*/runs", (route) =>
    json(route, { rule_id: "x", runs: [] }),
  );
  await page.route("**/api/automations/templates", (route) => json(route, []));
  return state;
}
