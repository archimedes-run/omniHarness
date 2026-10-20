"use client";

import { Markdown as Streamdown } from "@/components/ai-elements/markdown";

import { aboutMarkdown } from "./about-content";

export function AboutSettingsPage() {
  return <Streamdown>{aboutMarkdown}</Streamdown>;
}
