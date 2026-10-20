"use client";

import { useState } from "react";

import {
  TasksBoard,
  type TasksSelection,
} from "@/components/workspace/ledger/tasks-board";

import type { PanelProps } from "../panels";

/** Tasks panel (Feature 006, Tasks.dc.html): projects and their tasks from
 * the Feature 005 ledger. Each project also has its own page. */
export default function TasksPanel(_props: PanelProps) {
  const [selection, setSelection] = useState<TasksSelection>(null);
  return <TasksBoard selection={selection} onSelect={setSelection} />;
}
