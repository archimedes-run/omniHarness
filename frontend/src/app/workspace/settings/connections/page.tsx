"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ConnectionRow } from "@/components/workspace/connections/connection-row";
import { McpSuite } from "@/components/workspace/mcp/mcp-suite";
import { useMCPConfig } from "@/core/mcp/hooks";
import { useToolSources } from "@/core/tool-sources/hooks";

/**
 * Settings → Connections: the MCP Suite and Tool sources, on one page
 * (Phase 2.5). Every source with its status — not configured, off,
 * unreachable, live — and connect/disconnect; then the servers themselves.
 * Feature 004's honesty holds: "cannot tell" is never shown as "none".
 */
export default function ConnectionsPage() {
  const { view, isLoading, error } = useToolSources();
  const { config } = useMCPConfig();
  const configured = new Set(Object.keys(config?.mcp_servers ?? {}));
  const local = view?.sources.filter((s) => s.kind === "local") ?? [];
  const connectors = view?.sources.filter((s) => s.kind === "connector") ?? [];

  return (
    <div className="mx-auto w-full max-w-4xl space-y-8 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Connections</h1>
        <p className="text-muted-foreground text-sm">
          Where the agent&apos;s tools come from, whether each is working, and
          connecting more.
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
              <ConnectionRow
                key={source.id}
                source={source}
                configured={configured.has(
                  source.id.slice(source.id.indexOf(":") + 1),
                )}
              />
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
                <ConnectionRow key={source.id} source={source} configured />
              ))}
            </ul>
          ) : (
            <p
              className="text-muted-foreground text-sm"
              data-testid="no-connectors"
            >
              Connectors are not available: Composio is not configured on this
              gateway, so none can be connected here.
            </p>
          )}
        </section>
      )}

      <section
        className="border-border space-y-3 border-t pt-6"
        aria-labelledby="manage-heading"
      >
        <h2 id="manage-heading" className="text-sm font-semibold">
          Add or manage servers and connectors
        </h2>
        <McpSuite />
      </section>
    </div>
  );
}
