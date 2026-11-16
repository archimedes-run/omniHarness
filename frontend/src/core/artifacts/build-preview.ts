/** A published path may be reused by later coding jobs in the same chat. */
export interface BuildPreviewDetails {
  threadId: string;
  jobId: string;
  publishedAt: number;
  title: string;
  sample: boolean;
  appId?: string;
}

/** Polling historical jobs must not relabel the current file as an older build. */
export function registerPreview(
  previous: Record<string, BuildPreviewDetails>,
  path: string,
  details: BuildPreviewDetails,
): Record<string, BuildPreviewDetails> {
  const old = previous[path];
  if (
    old?.threadId === details.threadId &&
    (old.publishedAt > details.publishedAt ||
      (old.publishedAt === details.publishedAt && old.jobId > details.jobId))
  )
    return previous;
  if (JSON.stringify(old) === JSON.stringify(details)) return previous;
  return { ...previous, [path]: details };
}
