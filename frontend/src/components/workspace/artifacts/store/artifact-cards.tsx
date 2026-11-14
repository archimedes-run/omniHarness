"use client";

import type { Message } from "@langchain/langgraph-sdk";

import { artifactBindingsOf } from "@/core/artifacts/store-logic";

import { ArtifactCard } from "./artifact-card";

/** Spec 012 FR-009: one card per artifact_create/artifact_update result in
 * a turn's tool messages (their `artifact` field), in order. */
export function ArtifactCards({ messages }: { messages: Message[] }) {
  const bindings = artifactBindingsOf(messages);
  if (bindings.length === 0) return null;
  return (
    <div className="mt-2 flex flex-col gap-2" data-testid="artifact-cards">
      {bindings.map((b, i) => (
        <ArtifactCard
          key={`${b.artifactId}-${b.version}-${i}`}
          artifactId={b.artifactId}
          version={b.version}
          kind={b.kind}
        />
      ))}
    </div>
  );
}
