"use client";

import { useParams } from "next/navigation";

import { AppHostPage } from "@/components/workspace/apps/app-host-page";

/** Spec 011 FR-029: one app, full page, in its sandboxed frame. */
export default function Page() {
  const { appId } = useParams<{ appId: string }>();
  return <AppHostPage appId={decodeURIComponent(appId)} />;
}
