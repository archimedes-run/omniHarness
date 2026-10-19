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
}

export interface TierCheck {
  tool: string;
  tier: number;
  deciding_rule: string | null;
  /** No rule matched: this is the unknown-tool default, not a classification. */
  from_default: boolean;
  raised_by: ExceptionView | null;
}

export interface Tier3Execution {
  at: string;
  actor: string;
  tool: string;
  plan_as_stated: string;
  targets: string[];
  authorised_by: string | null;
  outcome: string | null;
}
