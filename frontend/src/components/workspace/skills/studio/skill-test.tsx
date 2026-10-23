"use client";

import { useState } from "react";

import { useStudioCopy } from "@/components/workspace/agents/studio/copy";
import { outlineButton } from "@/components/workspace/agents/studio/studio-frame";
import { testSkill, type SkillTestResult } from "@/core/studio";
import { cn } from "@/lib/utils";

const TRIES = 3;

/**
 * Skill Studio's Test tab (Skill-Studio.dc.html, Clarification 6). Runs only
 * when the user presses Test: each try is a real model call, the same model
 * and prompt a run would use. Each message reads as the board has it, "Loads"
 * or "Doesn't load", decided by what was OBSERVED (most of the tries that
 * answered), with the count and the model beside it. When no try answered it
 * says "Can't tell", never a guess.
 */
export function testVerdict(
  r: SkillTestResult,
): "loads" | "doesntLoad" | "cantTell" {
  if (!r.listed) return "doesntLoad";
  const answered = r.tries.filter((t) => !t.error).length;
  if (answered === 0) return "cantTell";
  return r.loaded * 2 > answered ? "loads" : "doesntLoad";
}

export function SkillTest({
  name,
  dirty,
}: {
  /** null: the skill is not saved yet. */
  name: string | null;
  dirty: boolean;
}) {
  const c = useStudioCopy().skills;
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState<
    { message: string; result?: SkillTestResult; error?: string }[]
  >([]);

  if (!name) {
    return <p className="text-muted-foreground">{c.testNeedsSave}</p>;
  }

  async function run() {
    const text = message.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      const result = await testSkill(name!, text, TRIES);
      setRows((r) => [{ message: text, result }, ...r]);
      // Keep anything typed while the test ran.
      setMessage((m) => (m.trim() === text ? "" : m));
    } catch (e) {
      setRows((r) => [
        {
          message: text,
          error: c.testFailed(e instanceof Error ? e.message : String(e)),
        },
        ...r,
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="text-muted-foreground m-0">{c.testIntro}</p>
      <p className="text-muted-foreground m-0 text-xs">{c.testHow(TRIES)}</p>
      {dirty ? (
        <p className="text-warning m-0 text-xs" role="status">
          {c.testUnsaved}
        </p>
      ) : null}
      {rows.map((row, i) => {
        const r = row.result;
        const errors = r?.tries.filter((t) => t.error).length ?? 0;
        const others = [
          ...new Set(r?.tries.flatMap((t) => t.other_skills) ?? []),
        ];
        return (
          <div
            key={`${row.message}-${rows.length - i}`}
            className="bg-card border-border-strong flex flex-col gap-0.5 rounded-lg border px-3.5 py-2.5"
            data-testid="skill-test-row"
          >
            <div className="flex flex-wrap justify-between gap-3">
              <span>{`“${row.message}”`}</span>
              {row.error ? (
                <span className="text-destructive text-[13px]">
                  {row.error}
                </span>
              ) : r ? (
                <span
                  className={cn(
                    "text-[13px] font-medium",
                    testVerdict(r) === "loads"
                      ? "text-success"
                      : testVerdict(r) === "cantTell"
                        ? "text-warning"
                        : "text-muted-foreground",
                  )}
                  data-testid="skill-test-outcome"
                >
                  {c[testVerdict(r)]}
                </span>
              ) : null}
            </div>
            {r ? (
              <span className="text-muted-foreground text-xs">
                {!r.listed
                  ? `${c.notListed} · `
                  : `${c.triesLoaded(r.loaded, r.total)} · `}
                {c.byModel(r.model)}
                {errors ? ` · ${c.errors(errors)}` : ""}
                {others.length ? ` · ${c.otherSkills(others)}` : ""}
              </span>
            ) : null}
          </div>
        );
      })}
      <div className="flex flex-wrap gap-2">
        <label className="block min-w-0 flex-[1_1_320px]">
          <span className="sr-only">{c.testMessage}</span>
          <input
            type="text"
            value={message}
            placeholder={c.testPlaceholder}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void run();
              }
            }}
            className="bg-background border-border-strong text-foreground placeholder:text-muted-foreground focus-visible:ring-ring min-h-11 w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus-visible:ring-2"
            data-testid="skill-test-input"
          />
        </label>
        <button
          type="button"
          className={outlineButton}
          onClick={() => void run()}
          disabled={busy || !message.trim()}
          data-testid="skill-test-run"
        >
          {busy ? c.testing : c.runTest}
        </button>
      </div>
    </>
  );
}
