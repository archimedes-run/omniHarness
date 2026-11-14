import type { Message } from "@langchain/langgraph-sdk";

/**
 * The server's verification record for one lead run (spec 009 Slice 0,
 * FR-052). It is computed by the backend from the evidence the agent's loop
 * recorded (tool results of this run), never from the reply's prose, and is
 * carried on the run's final AI message as
 * `additional_kwargs.omniharness_verification`.
 */
export type VerificationStatus = "verified" | "unverified" | "none";

export interface VerificationCheck {
  claim: string;
  verified: boolean;
  evidence: string;
}

export interface VerificationRecord {
  version: number;
  run_id: string | null;
  status: VerificationStatus;
  done_criteria: string | null;
  items: { content: string; status: string }[];
  checks: VerificationCheck[];
  not_verified: string[];
  links: { verified: string[]; unverified: string[] };
  evidence_count: number;
}

export const VERIFICATION_KEY = "omniharness_verification";

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}

/**
 * Parse a record defensively: anything malformed yields null (no badge),
 * never a guessed "verified".
 */
export function parseVerification(raw: unknown): VerificationRecord | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const status = r.status;
  if (status !== "verified" && status !== "unverified" && status !== "none")
    return null;
  const checks = Array.isArray(r.checks)
    ? r.checks.flatMap((c): VerificationCheck[] => {
        if (!c || typeof c !== "object") return [];
        const o = c as Record<string, unknown>;
        const claim = asString(o.claim);
        if (!claim) return [];
        return [
          {
            claim,
            verified: o.verified === true,
            evidence: asString(o.evidence) ?? "",
          },
        ];
      })
    : [];
  const items = Array.isArray(r.items)
    ? r.items.flatMap((i) => {
        if (!i || typeof i !== "object") return [];
        const o = i as Record<string, unknown>;
        const content = asString(o.content);
        return content
          ? [{ content, status: asString(o.status) ?? "pending" }]
          : [];
      })
    : [];
  const links = (r.links ?? {}) as Record<string, unknown>;
  return {
    version: typeof r.version === "number" ? r.version : 1,
    run_id: asString(r.run_id),
    // A "verified" record with an unverified check is not verified.
    status:
      status === "verified" && checks.some((c) => !c.verified)
        ? "unverified"
        : status,
    done_criteria: asString(r.done_criteria),
    items,
    checks,
    not_verified: asStrings(r.not_verified),
    links: {
      verified: asStrings(links.verified),
      unverified: asStrings(links.unverified),
    },
    evidence_count: typeof r.evidence_count === "number" ? r.evidence_count : 0,
  };
}

/** The record on one message, if any. */
export function verificationOf(
  message: Message | undefined,
): VerificationRecord | null {
  if (message?.type !== "ai") return null;
  const kwargs = (message as { additional_kwargs?: Record<string, unknown> })
    .additional_kwargs;
  return parseVerification(kwargs?.[VERIFICATION_KEY]);
}

/**
 * The record for a turn's displayed messages: the last AI message's own,
 * else the same message (by id) in the thread state, where the server's
 * stamped copy lives even when the display history holds the raw one.
 */
export function findTurnVerification(
  displayed: Message[],
  stateMessages: Message[] | undefined,
  verifications?: Record<string, unknown> | null,
): VerificationRecord | null {
  const lastAi = [...displayed].reverse().find((m) => m.type === "ai");
  if (!lastAi) return null;
  const own = verificationOf(lastAi);
  if (own) return own;
  if (!lastAi.id) return null;
  const inState = stateMessages
    ? verificationOf(stateMessages.find((m) => m.id === lastAi.id))
    : null;
  if (inState) return inState;
  // The thread state's `verifications` map (message id -> record) survives a
  // reload and summarisation, which drops old messages from state.
  return parseVerification(verifications?.[lastAi.id]);
}

export interface BadgeView {
  label: "Verified" | "Unverified";
  tone: "success" | "warning";
  summary: string;
}

/** What the badge says; null means no badge (status "none"). */
export function badgeFor(record: VerificationRecord | null): BadgeView | null {
  if (!record || record.status === "none") return null;
  const total = record.checks.length;
  const ok = record.checks.filter((c) => c.verified).length;
  const counted =
    total > 0
      ? `${ok} of ${total} checks backed by evidence`
      : `${record.evidence_count} tool results as evidence`;
  if (record.status === "verified") {
    return { label: "Verified", tone: "success", summary: counted };
  }
  const missing = record.not_verified.length;
  return {
    label: "Unverified",
    tone: "warning",
    summary: missing > 0 ? `${counted}; ${missing} not verified` : counted,
  };
}

export function traceHref(runId: string) {
  return `/workspace/traces/${encodeURIComponent(runId)}`;
}
