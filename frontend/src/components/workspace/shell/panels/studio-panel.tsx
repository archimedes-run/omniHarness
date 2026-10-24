"use client";

import { Studio } from "@/components/workspace/studio/studio";

import type { PanelProps } from "../panels";

/** The Agents and Skills panels: the Agent & Skill Studio (006-G). */
export default function StudioPanel(props: PanelProps) {
  return (
    <Studio
      kind={props.panel === "skills" ? "skills" : "agents"}
      onClose={props.onClose}
      setCloseGuard={props.setCloseGuard}
    />
  );
}
