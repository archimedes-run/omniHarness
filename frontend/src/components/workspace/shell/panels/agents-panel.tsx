"use client";

import { AgentGallery } from "@/components/workspace/agents/agent-gallery";

import type { PanelProps } from "../panels";

/** Agents panel, Phase 1: the agent gallery as it is on /workspace/agents. */
export default function AgentsPanel(_props: PanelProps) {
  return <AgentGallery />;
}
