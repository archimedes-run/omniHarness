"use client";

import { SkillSettingsPage } from "@/components/workspace/settings/skill-settings-page";

import type { PanelProps } from "../panels";

/** Skills panel, Phase 1: the Settings > Skills page. */
export default function SkillsPanel({ onClose }: PanelProps) {
  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <SkillSettingsPage onClose={onClose} />
    </div>
  );
}
