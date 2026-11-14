/**
 * Spec 012 FR-015: the app's side of the isolated mermaid frame
 * (mermaid.ts explains why). One offscreen frame, real size so mermaid can
 * measure text, `sandbox="allow-scripts"` exactly (no allow-same-origin).
 * The frame's port is taken only from a "ready" message whose source is
 * that frame's window; answers are matched by id, capped in size and
 * timed out (a frame that stops answering is torn down and made again).
 * Requests go one at a time.
 */
import { MAX_SVG } from "./mermaid";

const FRAME_URL = "/mermaid-frame/frame.html";
const READY_TIMEOUT_MS = 15_000;
const DRAW_TIMEOUT_MS = 10_000;

let frame: HTMLIFrameElement | null = null;
let portPromise: Promise<MessagePort> | null = null;
let queue: Promise<unknown> = Promise.resolve();
let nextId = 0;

function teardown() {
  frame?.remove();
  frame = null;
  portPromise = null;
}

function ensurePort(): Promise<MessagePort> {
  if (portPromise) return portPromise;
  portPromise = new Promise<MessagePort>((resolve, reject) => {
    const f = document.createElement("iframe");
    f.setAttribute("sandbox", "allow-scripts");
    f.setAttribute("aria-hidden", "true");
    f.setAttribute("tabindex", "-1");
    f.setAttribute("title", "Diagram drawing (hidden)");
    f.setAttribute("referrerpolicy", "no-referrer");
    f.setAttribute("data-testid", "mermaid-frame");
    f.style.cssText =
      "position:fixed;left:-20000px;top:0;width:1200px;height:900px;border:0;visibility:hidden;pointer-events:none";
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onReady);
      reject(new Error("the diagram frame did not start"));
    }, READY_TIMEOUT_MS);
    function onReady(e: MessageEvent) {
      if (!f.contentWindow || e.source !== f.contentWindow) return;
      const d = e.data as { type?: unknown } | null;
      if (d?.type !== "omni-mermaid-ready") return;
      window.removeEventListener("message", onReady);
      window.clearTimeout(timer);
      const channel = new MessageChannel();
      f.contentWindow.postMessage({ type: "omni-mermaid-port" }, "*", [
        channel.port2,
      ]);
      resolve(channel.port1);
    }
    window.addEventListener("message", onReady);
    f.src = FRAME_URL;
    document.body.appendChild(f);
    frame = f;
  });
  portPromise.catch(() => teardown());
  return portPromise;
}

async function drawOnce(source: string, dark: boolean): Promise<string> {
  const port = await ensurePort();
  const id = ++nextId;
  return new Promise<string>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      port.onmessage = null;
      teardown();
      reject(new Error("the diagram took too long"));
    }, DRAW_TIMEOUT_MS);
    port.onmessage = (e: MessageEvent) => {
      const d = e.data as { id?: unknown; ok?: unknown; svg?: unknown } | null;
      if (d?.id !== id) return;
      window.clearTimeout(timer);
      port.onmessage = null;
      if (
        d.ok === true &&
        typeof d.svg === "string" &&
        d.svg.length <= MAX_SVG
      ) {
        resolve(d.svg);
      } else {
        reject(new Error("mermaid could not draw it"));
      }
    };
    port.postMessage({ id, source, dark });
  });
}

/** Draw in the isolated frame, one request at a time. */
export function renderInFrame(source: string, dark: boolean): Promise<string> {
  const run = () => drawOnce(source, dark);
  const next = queue.then(run, run);
  queue = next.catch(() => undefined);
  return next;
}
