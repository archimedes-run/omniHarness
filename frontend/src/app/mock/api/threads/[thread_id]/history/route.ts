import fs from "fs";
import path from "path";

import type { NextRequest } from "next/server";

import { demoThreadDir } from "@/core/demo/demo-files";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ thread_id: string }> },
) {
  const threadId = (await params).thread_id;
  const dir = demoThreadDir(process.cwd(), threadId);
  if (!dir) return new Response("Not found", { status: 404 });
  const jsonString = fs.readFileSync(path.join(dir, "thread.json"), "utf8");
  const json = JSON.parse(jsonString);
  if (Array.isArray(json.history)) {
    return Response.json(json);
  }
  return Response.json([json]);
}
