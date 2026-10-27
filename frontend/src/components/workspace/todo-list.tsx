import {
  CheckCircle2Icon,
  ChevronUpIcon,
  CircleDotIcon,
  CircleIcon,
  ListTodoIcon,
  TargetIcon,
} from "lucide-react";
import { useId, useState } from "react";

import { splitDoneCriteria, todoProgress, type Todo } from "@/core/todos";
import { cn } from "@/lib/utils";

import { QueueList } from "../ai-elements/queue";

const STATUS_TEXT = {
  pending: "Not started",
  in_progress: "In progress",
  completed: "Done",
} as const;

/**
 * The agent's visible plan for the turn (spec 009 Slice 0, FR-050): shown
 * whenever the thread has to-dos, in every chat mode. The header always says
 * how far the plan is and which step is in progress; the first item, when it
 * is "Done when: …", is the turn's done-criteria and is drawn as such.
 */
export function TodoList({
  className,
  todos,
  collapsed: controlledCollapsed,
  hidden = false,
  onToggle,
  action,
}: {
  className?: string;
  todos: Todo[];
  collapsed?: boolean;
  hidden?: boolean;
  onToggle?: () => void;
  /** A control in the header, e.g. promoting the to-dos (Feature 005). */
  action?: React.ReactNode;
}) {
  const [internalCollapsed, setInternalCollapsed] = useState(true);
  const isControlled = controlledCollapsed !== undefined;
  const collapsed = isControlled ? controlledCollapsed : internalCollapsed;
  const listId = useId();
  const { criteria, steps } = splitDoneCriteria(todos);
  const progress = todoProgress(steps);

  const handleToggle = () => {
    if (isControlled) {
      onToggle?.();
    } else {
      setInternalCollapsed((prev) => !prev);
    }
  };

  return (
    <div
      className={cn(
        "bg-card flex h-fit w-full origin-bottom translate-y-4 flex-col overflow-hidden rounded-t-xl border border-b-0 backdrop-blur-sm transition-all duration-200 ease-out",
        hidden ? "pointer-events-none invisible translate-y-8 opacity-0" : "",
        className,
      )}
      data-testid="todo-list"
    >
      <header className="bg-accent flex min-h-8 shrink-0 items-center justify-between gap-3 px-4 text-sm">
        <button
          type="button"
          onClick={handleToggle}
          aria-expanded={!collapsed}
          aria-controls={listId}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left focus-visible:ring-2 focus-visible:outline-none"
        >
          <ListTodoIcon className="size-4 shrink-0" aria-hidden="true" />
          <span className="shrink-0">Plan</span>
          {steps.length > 0 && (
            <span className="shrink-0 tabular-nums" data-testid="todo-progress">
              {progress.done}/{progress.total} done
            </span>
          )}
          {progress.current?.content && (
            <span className="text-foreground-2 min-w-0 truncate">
              <span className="sr-only">In progress: </span>
              {progress.current.content}
            </span>
          )}
          <ChevronUpIcon
            aria-hidden="true"
            className={cn(
              "ml-auto size-4 shrink-0 transition-transform duration-300 ease-out",
              collapsed ? "" : "rotate-180",
            )}
          />
        </button>
        {action}
      </header>
      <div
        id={listId}
        className={cn(
          "bg-accent flex grow flex-col px-2 transition-all duration-300 ease-out",
          collapsed ? "hidden" : "pb-4",
        )}
      >
        <QueueList className="bg-background mt-0 w-full rounded-t-xl">
          {criteria && (
            <li
              className="text-foreground flex items-start gap-2 px-3 py-1.5 text-sm"
              data-testid="todo-done-criteria"
            >
              <TargetIcon
                className="text-primary mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
              <span>
                <span className="font-medium">Done when: </span>
                {criteria}
              </span>
            </li>
          )}
          {steps.map((todo, i) => {
            const status = todo.status ?? "pending";
            const Icon =
              status === "completed"
                ? CheckCircle2Icon
                : status === "in_progress"
                  ? CircleDotIcon
                  : CircleIcon;
            return (
              <li
                key={i + (todo.content ?? "")}
                className="flex items-start gap-2 px-3 py-1 text-sm"
                data-status={status}
              >
                <Icon
                  aria-hidden="true"
                  className={cn(
                    "mt-0.5 size-4 shrink-0",
                    status === "completed" && "text-success",
                    status === "in_progress" && "text-primary",
                    status === "pending" && "text-muted-foreground",
                  )}
                />
                <span
                  className={cn(
                    status === "completed" &&
                      "text-muted-foreground line-through",
                    status === "in_progress" && "text-foreground font-medium",
                    status === "pending" && "text-foreground-2",
                  )}
                >
                  <span className="sr-only">{STATUS_TEXT[status]}: </span>
                  {todo.content}
                </span>
              </li>
            );
          })}
        </QueueList>
      </div>
    </div>
  );
}
