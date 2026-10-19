"use client";

import dynamic from "next/dynamic";
import { type ComponentProps, useEffect, useState } from "react";

import type { SettingsDialog as Eager } from "./settings-dialog";

/**
 * The settings dialog, loaded on first open (Phase 2.5).
 *
 * The sidebar menu and the command palette are on every page, and imported the
 * dialog eagerly. Its About and Memory sections render markdown, so every page
 * shipped the markdown/highlighting stack (streamdown, shiki, katex) to show a
 * dialog that is usually never opened.
 */
const SettingsDialog = dynamic(
  () => import("./settings-dialog").then((m) => m.SettingsDialog),
  { ssr: false },
);

export function LazySettingsDialog(props: ComponentProps<typeof Eager>) {
  // Mount on first open, then stay mounted so closing still animates.
  const [opened, setOpened] = useState(props.open);
  useEffect(() => {
    if (props.open) setOpened(true);
  }, [props.open]);
  return opened ? <SettingsDialog {...props} /> : null;
}
