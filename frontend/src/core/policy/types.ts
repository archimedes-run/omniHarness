/** Mirrors app/policy/inspect.py. */
export interface ExceptionView {
  tier: number;
  when: Record<string, unknown>;
  unless: Record<string, string>;
}

export interface PolicyRule {
  pattern: string;
  tier: number;
  exceptions: ExceptionView[];
  source_line: number | null;
}

export interface RulesInForce {
  source_file: string;
  rules: PolicyRule[];
  unreadable: boolean;
  /** The last edit was refused; these are the previous rules, still in force. */
  kept_previous: boolean;
  error: string | null;
  threshold_targets: number;
  expires_after_seconds: number;
  /** Capabilities that do not exist at all, and what the assistant says (FR-023). */
  cannot_do?: { capability: string; wording: string }[];
}

export interface TierCheck {
  tool: string;
  tier: number;
  deciding_rule: string | null;
  /** No rule matched: this is the unknown-tool default, not a classification. */
  from_default: boolean;
  raised_by: ExceptionView | null;
  /** What will happen, in the assistant's own words (FR-023). */
  in_plain_words?: string;
  /** Set when the name is a capability the assistant does not have at all. */
  absent?: string | null;
  /** 007: no rule names this tool, so it is refused (never offered, never
   * run). `tier` is then not acted on. Absent from an older gateway. */
  refused?: boolean;
}

export interface Tier3Execution {
  at: string;
  actor: string;
  tool: string;
  plan_as_stated: string;
  targets: string[];
  authorised_by: string | null;
  outcome: string | null;
  /** Failed redaction: the text fields carry a sentence saying so (FR-031). */
  withheld: boolean;
}
