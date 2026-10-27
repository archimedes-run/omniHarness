import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import {
  baselineCell,
  historyPoints,
  isRegression,
  sortTasks,
  type EvalSummary,
  type EvalTask,
} from "@/core/evals";
import { splitDoneCriteria, todoProgress } from "@/core/todos";
import {
  formatCost,
  formatDuration,
  parseTrace,
  statusTone,
  stepTree,
  withheldReason,
} from "@/core/traces";
import {
  badgeFor,
  findTurnVerification,
  parseVerification,
  VERIFICATION_KEY,
} from "@/core/verification";

const record = (over: Record<string, unknown> = {}) => ({
  version: 1,
  run_id: "run-1",
  status: "verified",
  done_criteria: "5 restaurants, each with a link",
  items: [{ content: "Search", status: "completed" }],
  checks: [
    { claim: "5 links", verified: true, evidence: "web_search returned them" },
  ],
  not_verified: [],
  links: { verified: ["https://a.example"], unverified: [] },
  evidence_count: 3,
  ...over,
});

describe("verification badge", () => {
  it("maps verified / unverified / none", () => {
    expect(badgeFor(parseVerification(record()))?.label).toBe("Verified");
    expect(
      badgeFor(
        parseVerification(
          record({ status: "unverified", not_verified: ["x"] }),
        ),
      ),
    ).toMatchObject({
      label: "Unverified",
      tone: "warning",
    });
    expect(badgeFor(parseVerification(record({ status: "none" })))).toBeNull();
  });

  it("never shows Verified when a check is unverified", () => {
    const r = parseVerification(
      record({
        checks: [
          { claim: "5 links", verified: false, evidence: "no tool result" },
        ],
      }),
    );
    expect(r?.status).toBe("unverified");
    expect(badgeFor(r)?.label).toBe("Unverified");
  });

  it("rejects malformed records (no badge, no guess)", () => {
    expect(parseVerification(null)).toBeNull();
    expect(parseVerification({ status: "done" })).toBeNull();
    expect(parseVerification("verified")).toBeNull();
  });

  it("finds the record on the turn's last AI message, else in thread state by id", () => {
    const raw = {
      type: "ai",
      id: "m2",
      content: "answer",
      additional_kwargs: {},
    };
    const stamped = {
      ...raw,
      additional_kwargs: { [VERIFICATION_KEY]: record() },
    };
    const human = { type: "human", id: "m1", content: "q" };
    const displayed = [human, raw] as unknown as Message[];
    expect(
      findTurnVerification(displayed, [human, stamped] as unknown as Message[])
        ?.status,
    ).toBe("verified");
    expect(findTurnVerification(displayed, undefined)).toBeNull();
    expect(
      findTurnVerification([human, stamped] as unknown as Message[], undefined)
        ?.run_id,
    ).toBe("run-1");
  });

  it("falls back to the thread state's verifications map (after a reload or a summary)", () => {
    const raw = {
      type: "ai",
      id: "m9",
      content: "answer",
      additional_kwargs: {},
    };
    const displayed = [raw] as unknown as Message[];
    expect(findTurnVerification(displayed, [], { m9: record() })?.status).toBe(
      "verified",
    );
    expect(findTurnVerification(displayed, [], { other: record() })).toBeNull();
  });
});

describe("todos", () => {
  it("splits the Done when item off as the criteria", () => {
    const { criteria, steps } = splitDoneCriteria([
      { content: "Done when: 3 tasks exist", status: "pending" },
      { content: "Add tasks", status: "in_progress" },
      { content: "Check", status: "completed" },
    ]);
    expect(criteria).toBe("3 tasks exist");
    expect(steps).toHaveLength(2);
    expect(todoProgress(steps)).toMatchObject({
      done: 1,
      total: 2,
      current: { content: "Add tasks" },
    });
  });

  it("leaves a list without criteria alone", () => {
    const todos = [{ content: "Write it", status: "pending" as const }];
    expect(splitDoneCriteria(todos)).toEqual({ criteria: null, steps: todos });
  });
});

describe("trace", () => {
  const body = {
    trace: {
      version: 1,
      run_id: "r1",
      thread_id: "t1",
      status: "success",
      duration_ms: 12500,
      tokens: { input: 1200, output: 300, total: 1500 },
      llm_calls: 3,
      cost_usd: 0.0123,
      resumed_from: null,
      resumes: ["r2"],
      retries: 1,
      steps: [
        {
          index: 0,
          type: "checklist",
          name: "write_todos",
          tier: 1,
          status: "ok",
          parent: null,
        },
        {
          index: 1,
          type: "tool",
          name: "web_fetch",
          tier: 1,
          status: "error",
          parent: null,
        },
        {
          index: 2,
          type: "retry",
          name: "web_fetch",
          tier: 1,
          status: "ok",
          parent: 1,
        },
        {
          index: 3,
          type: "card",
          name: "ledger_apply",
          tier: 7,
          status: "needs_confirmation",
          parent: 99,
        },
      ],
      cards: [{ id: "c1", tool: "ledger_apply", tier: 3, outcome: "executed" }],
    },
  };

  it("parses defensively and nests by parent", () => {
    const t = parseTrace(body)!;
    expect(t.steps).toHaveLength(4);
    expect(t.steps[3]!.tier).toBeNull(); // an impossible tier is not shown
    const tree = stepTree(t.steps);
    expect(tree.get(-1)!.map((s) => s.index)).toEqual([0, 1, 3]); // unknown parent -> root
    expect(tree.get(1)!.map((s) => s.index)).toEqual([2]);
  });

  it("reports withheld bodies and non-traces", () => {
    expect(withheldReason({ withheld: "unreadable" })).toBe("unreadable");
    expect(parseTrace({ withheld: "x" })).toBeNull();
    expect(parseTrace({ messages: [] })).toBeNull();
  });

  it("formats status tones, durations and cost", () => {
    expect(statusTone("ok")).toBe("success");
    expect(statusTone("needs_confirmation")).toBe("warning");
    expect(statusTone("error")).toBe("danger");
    expect(statusTone("something-new")).toBe("neutral");
    expect(formatDuration(12500)).toBe("13 s");
    expect(formatDuration(900)).toBe("900 ms");
    expect(formatDuration(null)).toBe("—");
    expect(formatCost(0.004)).toBe("<$0.01");
    expect(formatCost(1.234)).toBe("$1.23");
    expect(formatCost(null)).toBe("—");
  });
});

describe("evals", () => {
  const task = (
    id: string,
    pass: boolean,
    baseline_pass: boolean | null,
  ): EvalTask => ({
    id,
    title: id,
    pass,
    live_only: false,
    baseline_pass,
    checks: [],
    seconds: 1,
    tokens: null,
    cost_usd: null,
    thread_id: null,
  });

  it("marks regressions and baseline cells", () => {
    expect(isRegression(task("T01", false, true))).toBe(true);
    expect(isRegression(task("T02", false, false))).toBe(false);
    expect(baselineCell(task("T03", true, null))).toBe("none");
    expect(baselineCell(task("T03", true, false))).toBe("fail");
  });

  it("sorts regressions, then failures, then passes, by id", () => {
    const ids = sortTasks([
      task("T10", true, true),
      task("T2", false, false),
      task("T1", false, true),
      task("T3", true, null),
    ]).map((t) => t.id);
    expect(ids).toEqual(["T1", "T2", "T3", "T10"]);
  });

  it("builds history points oldest first for one mode", () => {
    const run = (
      id: string,
      at: string,
      mode: "mock" | "real",
      passed: number,
    ): EvalSummary => ({
      id,
      created_at: at,
      mode,
      git_sha: "abc",
      model: null,
      trials: 1,
      passed,
      total: 18,
      strict_passed: null,
      cost_usd: null,
      seconds: 1,
      regressions: [],
    });
    const pts = historyPoints(
      [
        run("b", "2026-10-26T00:00:00Z", "real", 12),
        run("a", "2026-10-24T00:00:00Z", "real", 7),
        run("m", "2026-10-25T00:00:00Z", "mock", 23),
      ],
      "real",
    );
    expect(pts.map((p) => p.id)).toEqual(["a", "b"]);
    expect(pts[0]!.label).toBe("7/18");
  });
});
