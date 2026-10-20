"use client";

import Link from "next/link";

import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { OmniBrandMark } from "./omni-brand-mark";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { state } = useSidebar();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div className="block group-hover/workspace-header:hidden">
              <OmniBrandMark animated size="lg" />
            </div>
            <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link
                href="/"
                className="text-foreground ml-2 flex items-center gap-2 text-[0.95rem] font-medium tracking-[0.02em]"
              >
                <OmniBrandMark size="sm" />
                <span>OmniHarness</span>
              </Link>
            ) : (
              <div className="text-foreground ml-2 flex cursor-default items-center gap-2 text-[0.95rem] font-medium tracking-[0.02em]">
                <OmniBrandMark size="sm" />
                <span>OmniHarness</span>
              </div>
            )}
            <SidebarTrigger />
          </div>
        )}
      </div>
    </>
  );
}
