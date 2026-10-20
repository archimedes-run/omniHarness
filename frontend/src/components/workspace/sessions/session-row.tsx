import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleDotIcon,
  CircleHelpIcon,
} from "lucide-react";

import { BrandLogo } from "@/components/brand";
import { Badge } from "@/components/ui/badge";
import { WithheldNotice } from "@/components/workspace/withheld-notice";
import { STATE_LABEL } from "@/core/sessions/logic";
import type { SessionRow as Row, TodoItem } from "@/core/sessions/types";
import { cn } from "@/lib/utils";

/**
 * One session. Inferred states (waiting, stalled) are drawn with a DASHED
 * border and a question-mark icon; observed ones (working, finished, failed)
 * solid with a check (FR-011, SC-007). The difference is in the shape, so it
 * reads without the label and without colour.
 */
export function SessionRow({ session }: { session: Row }) {
  const inferred = session.epistemic !== "observed";
  const Icon = inferred ? CircleHelpIcon : CircleCheckIcon;
  return (
    <li
      className={cn(
        "border-border flex flex-col gap-1 rounded-md border p-3",
        inferred ? "border-dashed" : "border-solid",
      )}
      data-testid="session"
      data-state={session.display_state}
      data-epistemic={session.epistemic}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="text-foreground truncate font-medium">
            {session.project}
          </span>
          {session.agent_label && (
            // The provider's mark (Anthropic for Claude Code, OpenAI for
            // Codex), named by the agent label it replaces.
            <span
              className="shrink-0 self-center"
              data-testid="agent"
              role="img"
              aria-label={session.agent_label}
              title={session.agent_label}
            >
              <BrandLogo
                source={session.agent ?? session.agent_label}
                name={session.agent_label}
                size={18}
                decorative
              />
            </span>
          )}
        </span>
        <span className="flex items-center gap-1">
          <Icon
            className="text-muted-foreground size-4"
            aria-label={inferred ? "inferred" : "observed"}
            data-testid="epistemic-icon"
          />
          <Badge
            variant={
              session.display_state === "failed" ? "destructive" : "secondary"
            }
          >
            {STATE_LABEL[session.display_state]}
          </Badge>
        </span>
      </div>
      {session.withheld ? (
        <WithheldNotice text={session.summary} />
      ) : (
        session.summary && (
          <p className="text-muted-foreground text-sm">{session.summary}</p>
        )
      )}
      {session.relay_suppressed && (
        <p className="text-muted-foreground text-xs" data-testid="suppressed">
          Summary withheld: it could not be checked for credentials.
        </p>
      )}
      {session.todos && session.todos.length > 0 && (
        <Plan todos={session.todos} />
      )}
      <p className="text-muted-foreground text-xs">
        Observe only · {session.session_id.slice(0, 8)}
        {session.files_changed
          ? ` · ${session.files_changed} file${session.files_changed === 1 ? "" : "s"} changed`
          : ""}
      </p>
    </li>
  );
}

const TODO_ICON = {
  completed: CircleCheckIcon,
  in_progress: CircleDotIcon,
} as Record<string, typeof CircleCheckIcon>;

/**
 * The agent's own task list (Feature 005 FR-030), as of its last CONFIRMED
 * update: a change whose tool call failed or never answered is not shown.
 * Collapsed to its progress; the items open on demand.
 */
function Plan({ todos }: { todos: TodoItem[] }) {
  const done = todos.filter((t) => t.status === "completed").length;
  const current = todos.find((t) => t.status === "in_progress");
  return (
    <details className="group" data-testid="plan">
      <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-2 text-xs">
        <span
          className="bg-muted h-1 w-16 overflow-hidden rounded-full"
          aria-hidden
        >
          <span
            className="bg-foreground/60 block h-full"
            style={{ width: `${(done / todos.length) * 100}%` }}
          />
        </span>
        <span data-testid="plan-progress">
          {`Tasks ${done} of ${todos.length}`}
        </span>
        {current && (
          <span className="text-foreground truncate">· {current.title}</span>
        )}
      </summary>
      <ul className="mt-2 space-y-1">
        {todos.map((todo, index) => {
          const Icon = TODO_ICON[todo.status] ?? CircleDashedIcon;
          return (
            <li
              key={index}
              className={cn(
                "flex items-center gap-2 text-sm",
                todo.status === "completed"
                  ? "text-muted-foreground line-through"
                  : "text-foreground",
              )}
              data-status={todo.status}
            >
              <Icon className="text-muted-foreground size-3.5 shrink-0" />
              <span className="truncate">{todo.title}</span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
