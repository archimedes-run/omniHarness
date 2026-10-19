import { CircleCheckIcon, CircleHelpIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { STATE_LABEL } from "@/core/sessions/logic";
import type { SessionRow as Row } from "@/core/sessions/types";
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
        <span className="text-foreground font-medium">{session.project}</span>
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
      {session.summary && (
        <p className="text-muted-foreground text-sm">{session.summary}</p>
      )}
      {session.relay_suppressed && (
        <p className="text-muted-foreground text-xs" data-testid="suppressed">
          Summary withheld: it could not be checked for credentials.
        </p>
      )}
      <p className="text-muted-foreground text-xs">
        Observe only · {session.session_id.slice(0, 8)}
      </p>
    </li>
  );
}
