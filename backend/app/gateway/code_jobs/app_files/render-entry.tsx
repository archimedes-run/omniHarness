/* The render check's entry (check-render.mjs). Written by the system; do not edit. */
import * as React from "react";
import * as ReactDOMClient from "react-dom/client";
import App from "../src/App";
// @ts-expect-error plain JavaScript module of the kit
import { checkRender, report } from "./check-render-core.mjs";

export async function run(mockShim: string): Promise<boolean> {
  const act = (React as unknown as { act: (fn: () => Promise<void>) => Promise<void> }).act;
  const outcome = await checkRender({ React, ReactDOMClient, act, App, mockShim });
  console.log(report(outcome));
  return outcome.ok;
}
