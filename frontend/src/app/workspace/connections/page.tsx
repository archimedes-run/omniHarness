"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConnectionRow } from "@/components/workspace/connections/connection-row";
import { McpSuite } from "@/components/workspace/mcp/mcp-suite";
import { useMCPConfig } from "@/core/mcp/hooks";
import { useToolSources } from "@/core/tool-sources/hooks";

/**
 * Connections (Phase 2.6: a sidebar item again, after Automations). Two tabs:
 *
 *  - Connected: every app (Composio connector) and MCP server with its status
 *    (Live / Off / Unreachable / Not configured) and connect, disconnect or
 *    turn on/off. Feature 004's honesty holds: "cannot tell" is never "none".
 *  - MCP Suite: building and registering MCP servers.
 *
 * The tab is in the URL (?tab=suite) so a link can open either.
 */
export default function ConnectionsPage() {
  const router = useRouter();
  const tab = useSearchParams().get("tab") === "suite" ? "suite" : "connected";
  const { view, isLoading, error } = useToolSources();
  const { config } = useMCPConfig();
  const configured = new Set(Object.keys(config?.mcp_servers ?? {}));
  const local = view?.sources.filter((s) => s.kind === "local") ?? [];
  const connectors = view?.sources.filter((s) => s.kind === "connector") ?? [];

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Connections</h1>
        <p className="text-muted-foreground text-sm">
          The apps and servers the agent&apos;s tools come from, and whether
          each is working.
        </p>
      </header>

      <Tabs
        value={tab}
        onValueChange={(value) =>
          router.replace(
            value === "suite"
              ? "/workspace/connections?tab=suite"
              : "/workspace/connections",
          )
        }
      >
        <TabsList>
          <TabsTrigger value="connected">
            Connected
            {view && view.failing > 0 && (
              <span
                className="bg-destructive ml-1.5 inline-block size-1.5 rounded-full"
                aria-label={`${view.failing} failing`}
              />
            )}
          </TabsTrigger>
          <TabsTrigger value="suite">MCP Suite</TabsTrigger>
        </TabsList>

        <TabsContent value="connected" className="space-y-8 pt-4">
          {isLoading && (
            <p className="text-muted-foreground text-sm">Loading…</p>
          )}
          {error != null && (
            <Alert variant="destructive" data-testid="unreadable">
              <AlertTitle>
                I cannot tell which tool sources are working
              </AlertTitle>
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
                Agents do not have the tools of a source that failed to load.
                The reason is shown on it below.
              </AlertDescription>
            </Alert>
          )}

          {view && (
            <section className="space-y-2" aria-labelledby="connector-heading">
              <h2 id="connector-heading" className="text-sm font-semibold">
                Apps
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
                  Apps are not available: Composio is not configured on this
                  gateway, so none can be connected here.
                </p>
              )}
            </section>
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
        </TabsContent>

        <TabsContent value="suite" className="pt-4">
          <McpSuite />
        </TabsContent>
      </Tabs>
    </div>
  );
}
