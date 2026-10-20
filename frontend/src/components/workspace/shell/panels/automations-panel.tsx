"use client";

import { useState } from "react";

import {
  AutomationsBoard,
  type AutomationSelection,
} from "@/components/workspace/automations/automations-board";
import { useAutomationTemplates } from "@/core/automations/hooks";

import type { PanelProps } from "../panels";

/** Automations panel (Feature 006, Automations.dc.html): list, history,
 * editing and new automations, all inside the sheet. */
export default function AutomationsPanel(_props: PanelProps) {
  const [selection, setSelection] = useState<AutomationSelection>(null);
  const { templates } = useAutomationTemplates();
  return (
    <AutomationsBoard
      selection={selection}
      onSelect={setSelection}
      templates={templates}
    />
  );
}
