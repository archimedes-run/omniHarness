import fs from "fs";
import path from "path";

import type { NextRequest } from "next/server";

import { demoHeaders, resolveDemoFile } from "@/core/demo/demo-files";

/**
 * A demo thread's file. `mnt/user-data/...` maps to the thread's folder under
 * public/demo/threads/{id}/user-data/...; anything else, a bad id, or a path
 * that leaves that folder is 404.
 */
export async function GET(
  request: NextRequest,
  {
    params,
  }: {
    params: Promise<{
      thread_id: string;
      artifact_path?: string[] | undefined;
    }>;
  },
) {
  const { thread_id: threadId, artifact_path } = await params;
  const artifactPath = artifact_path?.join("/") ?? "";
  if (artifactPath.startsWith("mnt/")) {
    const file = resolveDemoFile(
      process.cwd(),
      threadId,
      artifactPath.slice("mnt/".length),
    );
    if (file) {
      const headers = new Headers(demoHeaders(file));
      if (request.nextUrl.searchParams.get("download") === "true") {
        const name = path.basename(file).replace(/[^A-Za-z0-9._-]/g, "_");
        headers.set("Content-Disposition", `attachment; filename="${name}"`);
      }
      return new Response(fs.readFileSync(file), { status: 200, headers });
    }
  }
  return new Response("File not found", {
    status: 404,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
