"use client";

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { ConnectedView } from "@/components/workspace/connections/connected-view";
import {
  PageColumn,
  PageHeader,
  UnderlineTab,
  UnderlineTabsList,
} from "@/components/workspace/page-kit";

// Each heavy view loads only when it is opened.
const BuildView = dynamic(() =>
  import("@/components/workspace/connections/build-view").then(
    (m) => m.BuildView,
  ),
);
const AppCatalog = dynamic(() =>
  import("@/components/workspace/mcp/mcp-suite").then((m) => m.AppCatalog),
);

/**
 * MCP Suite (Feature 006, boards "Connections" and "MCP-Suite"): the sidebar's
 * MCP Suite item. Two tabs, in the URL so a link opens either:
 *
 *  - Connected: counts, failing sources with their real error, apps with
 *    their logos, MCP servers.
 *  - Build (?tab=build; the old ?tab=suite opens it too): describe a tool, an
 *    agent builds and tests it in a sandbox, you approve its first run.
 */
export default function McpSuitePage() {
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab = raw === "build" || raw === "suite" ? "build" : "connected";
  const [browsing, setBrowsing] = useState(false);

  return (
    <PageColumn>
      <PageHeader
        title="MCP Suite"
        description="Where your agents' tools come from, and whether each one works right now."
        actions={
          tab === "connected" ? (
            <Button
              className="rounded-lg font-semibold"
              onClick={() => setBrowsing(true)}
            >
              Browse apps
            </Button>
          ) : undefined
        }
      />

      <Tabs
        value={tab}
        onValueChange={(value) =>
          router.replace(
            value === "build"
              ? "/workspace/connections?tab=build"
              : "/workspace/connections",
          )
        }
        className="gap-[22px]"
      >
        <UnderlineTabsList aria-label="MCP Suite views">
          <UnderlineTab value="connected">Connected</UnderlineTab>
          <UnderlineTab value="build">Build</UnderlineTab>
        </UnderlineTabsList>
        <TabsContent value="connected">
          <ConnectedView />
        </TabsContent>
        <TabsContent value="build">
          <BuildView selected={params.get("server")} />
        </TabsContent>
      </Tabs>

      <Dialog open={browsing} onOpenChange={setBrowsing}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Browse apps</DialogTitle>
            <DialogDescription>
              Connect an account once; a chat then chooses whether to use it.
            </DialogDescription>
          </DialogHeader>
          {browsing && <AppCatalog />}
        </DialogContent>
      </Dialog>
    </PageColumn>
  );
}
