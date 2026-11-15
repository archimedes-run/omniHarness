import fs from "fs";
import path from "path";

/**
 * The demo threads' files (the Next mock API under /mock/api/threads/, used
 * by `?mock=true` chats). Spec 012 S2 review: a thread id is a plain name, and
 * a file path must resolve (links followed) inside that thread's own folder
 * under public/demo/threads/: no `..`, encoded or not, in either segment.
 */

export const THREAD_ID = /^[A-Za-z0-9_-]{1,128}$/;

export function demoThreadDir(cwd: string, threadId: string): string | null {
  if (!THREAD_ID.test(threadId)) return null;
  return path.resolve(cwd, "public", "demo", "threads", threadId);
}

/** The real path of a demo file inside its thread's folder, or null. */
export function resolveDemoFile(
  cwd: string,
  threadId: string,
  relative: string,
): string | null {
  const dir = demoThreadDir(cwd, threadId);
  if (!dir || relative.includes("\0")) return null;
  const target = path.resolve(dir, relative);
  if (target !== dir && !target.startsWith(dir + path.sep)) return null;
  try {
    const real = fs.realpathSync(target);
    const realDir = fs.realpathSync(dir);
    if (!real.startsWith(realDir + path.sep)) return null;
    return fs.statSync(real).isFile() ? real : null;
  } catch {
    return null;
  }
}

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".htm": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".md": "text/markdown; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".mp4": "video/mp4",
  ".pdf": "application/pdf",
};

/** Every demo file response: an explicit type, no sniffing, and a sandbox
 * (a demo page never runs with this origin's powers). */
export function demoHeaders(file: string): Record<string, string> {
  return {
    "Content-Type":
      TYPES[path.extname(file).toLowerCase()] ?? "application/octet-stream",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
  };
}
