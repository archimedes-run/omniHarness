import { Badge } from "@/components/ui/badge";
import { describeState, type Tone } from "@/core/tool-sources/logic";
import type { ToolSource } from "@/core/tool-sources/types";

const BADGE: Record<Tone, "default" | "secondary" | "destructive" | "outline"> =
  {
    ok: "default",
    off: "secondary",
    problem: "destructive",
    unknown: "outline",
  };

export function ToolSourceRow({ source }: { source: ToolSource }) {
  const description = describeState(source);
  return (
    <li
      className="border-border flex flex-col gap-1 rounded-md border p-3"
      data-testid="tool-source"
      data-source={source.id}
      data-state={source.state}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground font-medium">{source.name}</span>
        <Badge variant={BADGE[description.tone]}>{description.label}</Badge>
      </div>
      <p className="text-muted-foreground text-sm">{description.meaning}</p>
      {source.error && (
        <p className="text-destructive text-xs" data-testid="source-error">
          {source.error}
        </p>
      )}
    </li>
  );
}
