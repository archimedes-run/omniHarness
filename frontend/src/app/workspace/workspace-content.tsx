import { cookies } from "next/headers";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Capsule } from "@/components/workspace/shell/capsule";
import { CommandPalette } from "@/components/workspace/shell/command-palette";
import { PanelSheet } from "@/components/workspace/shell/panel-sheet";
import { ShellProvider } from "@/components/workspace/shell/shell-context";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function WorkspaceContent({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return (
    <QueryClientProvider>
      <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
        <ShellProvider>
          <WorkspaceSidebar />
          <SidebarInset className="h-screen min-w-0 overflow-hidden">
            <Capsule />
            {/* The page scrolls here, under the capsule. A panel opens over
                it without a navigation, so this keeps its scroll. */}
            <div
              className="relative min-h-0 flex-1 overflow-y-auto"
              data-testid="workspace-scroll"
            >
              {children}
            </div>
          </SidebarInset>
          <PanelSheet />
          <CommandPalette />
        </ShellProvider>
      </SidebarProvider>
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}
