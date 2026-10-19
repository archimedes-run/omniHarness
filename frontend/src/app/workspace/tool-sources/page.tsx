"use client";

import { useSearchParams } from "next/navigation";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ToolSourceRow } from "@/components/workspace/tool-sources/tool-source-row";
import { useToolSources } from "@/core/tool-sources/hooks";

export default function ToolSourcesPage() {
  const threadId = useSearchParams().get("thread") ?? undefined;
  const { view, isLoading, error } = useToolSources(threadId);
  const local = view?.sources.filter((s) => s.kind === "local") ?? [];
  const connectors = view?.sources.filter((s) => s.kind === "connector") ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Tool sources</h1>
        <p className="text-muted-foreground text-sm">
          Where the agent&apos;s tools come from, and whether each is working.
          {threadId ? " Connector state is for this conversation." : ""}
        </p>
      </header>

      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}

      {error != null && (
        <Alert variant="destructive" data-testid="unreadable">
          <AlertTitle>I cannot tell which tool sources are working</AlertTitle>
          <AlertDescription>{String(error)}</AlertDescription>
        </Alert>
      )}

      {view && view.failing > 0 && (
        <Alert variant="destructive" data-testid="failing">
          <AlertTitle>
            {view.failing} tool source{view.failing === 1 ? " is" : "s are"}{" "}
            failing
          </AlertTitle>
          <AlertDescription>
            Agents do not have the tools of a source that failed to load. The
            reason is shown on it below.
          </AlertDescription>
        </Alert>
      )}

      {view && (
        <section className="space-y-2" aria-labelledby="local-heading">
          <h2 id="local-heading" className="text-sm font-semibold">
            MCP servers
          </h2>
          <ul className="space-y-2">
            {local.map((source) => (
              <ToolSourceRow key={source.id} source={source} />
            ))}
          </ul>
        </section>
      )}

      {view && (
        <section className="space-y-2" aria-labelledby="connector-heading">
          <h2 id="connector-heading" className="text-sm font-semibold">
            Connectors
          </h2>
          {view.connectors_available ? (
            <ul className="space-y-2">
              {connectors.map((source) => (
                <ToolSourceRow key={source.id} source={source} />
              ))}
            </ul>
          ) : (
            <p
              className="text-muted-foreground text-sm"
              data-testid="no-connectors"
            >
              Connectors are not available: Composio is not configured on this
              gateway, so none can be authorised here.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
