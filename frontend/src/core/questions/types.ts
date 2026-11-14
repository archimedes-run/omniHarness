/** A question card as the gateway sends it (GET /api/threads/{id}/questions,
 *  GET /api/questions). Contract: specs/009-orchestration/question-card.md. */
export type QuestionState = "open" | "answered" | "expired";

export interface QuestionOption {
  label: string;
  description: string;
}

export interface QuestionAnswer {
  option: number | null;
  text: string | null;
  via: "button" | "tagged_message";
  at: string;
}

export interface QuestionView {
  id: string;
  thread_id: string;
  /** Who asks: `kind` is lead, code_job, builder, ...; `name` is what the
   *  header shows ("OmniHarness asks"). */
  asker: { kind: string; name: string; tool_call_id: string | null };
  /** server: the asker's code wrote it; content: a model or worker did. */
  origin: "server" | "content";
  question: string;
  context: string;
  options: QuestionOption[];
  recommended: number | null;
  /** "Recommended" (server) or "Suggested by <asker>" (content). */
  recommended_label: string | null;
  on_expiry: string;
  expires_at: string;
  created_at: string;
  state: QuestionState;
  expired_reason: "" | "timeout" | "asker_ended";
  answer: QuestionAnswer | null;
  /** What happened, in the words the asker was told. */
  outcome: string;
  free_text_max: number;
}

export interface AnswerResult {
  question: QuestionView;
  /** A run the server started for the asker to carry on in (join it). */
  resume_run_id: string | null;
}

export type QuestionAnswerInput = { option: number } | { text: string };
