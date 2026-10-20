"use client";

import { Markdown as Streamdown } from "@/components/ai-elements/markdown";

import { aboutMarkdown } from "./about-content";

export function AboutSettingsPage() {
  return (
    <div className="bg-card border-border rounded-xl border px-[18px] py-4">
      <Streamdown>{aboutMarkdown}</Streamdown>
    </div>
  );
}
