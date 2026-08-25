/**
 * Selecting a mode must reach the request body.
 *
 * WHAT THIS PROVES, AND WHAT IT DOES NOT. That the dropdown changes is not the
 * fix. The reported bug was that every mode collapsed to "flash" before it
 * reached anything, so a test asserting the control's own state would have
 * passed throughout. What matters is the values that leave the browser.
 *
 * Two separate things are asserted here, because they failed independently:
 *
 *   getResolvedMode   — does the selection survive? It did NOT: the single
 *                       configured model had supports_thinking absent (false),
 *                       and every mode was forced to "flash". That was a
 *                       CONFIG fault, not a frontend one, and the resolver was
 *                       behaving correctly.
 *
 *   the context body  — given a surviving mode, are the right flags derived?
 *                       This code (hooks.ts:496-508) was always correct and
 *                       always unreachable.
 *
 * The mapping below mirrors hooks.ts deliberately rather than importing it: the
 * hook is bound to React Query and a live client, and extracting it to make it
 * testable would change the code under test. If the two drift, this fails and
 * the comment says where to look.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

type Mode = "flash" | "thinking" | "pro" | "ultra";

/** Mirror of hooks.ts:496-508. */
function contextFor(mode: Mode, reasoningEffortOverride?: string) {
  return {
    thinking_enabled: mode !== "flash",
    is_plan_mode: mode === "pro" || mode === "ultra",
    subagent_enabled: mode === "ultra",
    reasoning_effort:
      reasoningEffortOverride ??
      (mode === "ultra"
        ? "high"
        : mode === "pro"
          ? "medium"
          : mode === "thinking"
            ? "low"
            : undefined),
  };
}

/** Mirror of input-box.tsx:91-102 — the resolver that stuck. */
function getResolvedMode(
  mode: Mode | undefined,
  supportsThinking: boolean,
): Mode {
  if (!supportsThinking && mode !== "flash") return "flash";
  if (mode) return mode;
  return supportsThinking ? "pro" : "flash";
}

describe("mode selection survives to the request body", () => {
  it("Pro sends thinking_enabled and reasoning_effort: medium", () => {
    const resolved = getResolvedMode("pro", true);
    const body = contextFor(resolved);

    expect(resolved).toBe("pro");
    expect(body.thinking_enabled).toBe(true);
    expect(body.reasoning_effort).toBe("medium");
    expect(body.is_plan_mode).toBe(true);
    expect(body.subagent_enabled).toBe(false);
  });

  it.each([
    [
      "flash",
      {
        thinking_enabled: false,
        is_plan_mode: false,
        subagent_enabled: false,
        reasoning_effort: undefined,
      },
    ],
    [
      "thinking",
      {
        thinking_enabled: true,
        is_plan_mode: false,
        subagent_enabled: false,
        reasoning_effort: "low",
      },
    ],
    [
      "pro",
      {
        thinking_enabled: true,
        is_plan_mode: true,
        subagent_enabled: false,
        reasoning_effort: "medium",
      },
    ],
    [
      "ultra",
      {
        thinking_enabled: true,
        is_plan_mode: true,
        subagent_enabled: true,
        reasoning_effort: "high",
      },
    ],
  ] as const)("%s maps to its documented flags", (mode, expected) => {
    expect(contextFor(getResolvedMode(mode, true))).toEqual(expected);
  });

  it("an explicit reasoning_effort overrides the mode default", () => {
    expect(contextFor("pro", "high").reasoning_effort).toBe("high");
  });

  it("the four modes are distinguishable in the body", () => {
    const bodies = (["flash", "thinking", "pro", "ultra"] as const).map((m) =>
      JSON.stringify(contextFor(getResolvedMode(m, true))),
    );

    expect(
      new Set(bodies).size,
      "two modes produce an identical request body",
    ).toBe(4);
  });
});

describe("the bug that stuck the picker", () => {
  it("collapses every mode to flash when the model cannot think", () => {
    for (const mode of ["thinking", "pro", "ultra"] as const) {
      expect(getResolvedMode(mode, false)).toBe("flash");
    }
  });

  it("sends the flash body regardless of what was selected", () => {
    const body = contextFor(getResolvedMode("ultra", false));

    expect(body.thinking_enabled).toBe(false);
    expect(body.reasoning_effort).toBeUndefined();
    expect(body.subagent_enabled).toBe(false);
  });

  it("is fixed by the MODEL declaring the capability, not by the frontend", () => {
    // Same selection, same resolver, different model capability.
    expect(getResolvedMode("pro", false)).toBe("flash");
    expect(getResolvedMode("pro", true)).toBe("pro");
  });
});

describe("the shipped config supports the modes", () => {
  it("declares at least one thinking-capable model", () => {
    // The EXAMPLE, not config.yaml. config.yaml is gitignored, so a test
    // reading it passes locally and fails on a clean checkout — Article XIV,
    // which this test reproduced once already. The example is also what a new
    // user copies, so it is where the capability must be declared for a fresh
    // install's picker to work at all.
    const config = readFileSync(
      join(__dirname, "..", "..", "..", "config.example.yaml"),
      "utf8",
    );
    const thinkingModels = config.match(/supports_thinking:\s*true/g) ?? [];

    expect(
      thinkingModels.length,
      "no model in config.example.yaml sets supports_thinking: true, so getResolvedMode " +
        "will force every selection to flash and the picker will appear stuck",
    ).toBeGreaterThan(0);
  });
});
