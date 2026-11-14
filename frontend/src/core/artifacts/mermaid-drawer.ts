/**
 * Spec 012 FR-015: the code that runs INSIDE the isolated mermaid frame
 * (served as /mermaid-frame/drawer.js, after the mermaid bundle). It must be
 * self-contained: the route serves `(${drawerMain})(configs)`.
 *
 * It accepts one MessagePort, only from its parent window, then answers
 * `{id, source, dark}` requests with `{id, ok, svg}` or `{id, ok: false}`.
 * Mermaid draws into this frame's own document; the frame's CSP lets
 * nothing load or connect anywhere.
 */
export function drawerMain(configs: {
  light: Record<string, unknown>;
  dark: Record<string, unknown>;
  maxSource: number;
  maxSvg: number;
}): void {
  type Mermaid = {
    initialize(c: Record<string, unknown>): void;
    render(id: string, text: string, el?: Element): Promise<{ svg: string }>;
  };
  let port: MessagePort | null = null;
  let n = 0;
  const box = document.createElement("div");
  box.id = "draw";
  document.body.appendChild(box);

  function answer(id: number, svg: string | null) {
    if (!port) return;
    if (
      typeof svg === "string" &&
      svg.length > 0 &&
      svg.length <= configs.maxSvg
    ) {
      port.postMessage({ id, ok: true, svg });
    } else {
      port.postMessage({ id, ok: false });
    }
  }

  function onRequest(e: MessageEvent) {
    const d = e.data as { id?: unknown; source?: unknown; dark?: unknown };
    if (!d || typeof d !== "object") return;
    const id = d.id;
    if (typeof id !== "number" || !Number.isInteger(id)) return;
    if (
      typeof d.source !== "string" ||
      d.source.length > configs.maxSource ||
      typeof d.dark !== "boolean"
    ) {
      answer(id, null);
      return;
    }
    const mermaid = (globalThis as unknown as { mermaid?: Mermaid }).mermaid;
    if (!mermaid) {
      answer(id, null);
      return;
    }
    try {
      mermaid.initialize(d.dark ? configs.dark : configs.light);
      n += 1;
      mermaid
        .render("omni-mmd-" + n, d.source, box)
        .then(
          (r) => answer(id, r && typeof r.svg === "string" ? r.svg : null),
          () => answer(id, null),
        )
        .finally(() => {
          box.textContent = "";
        });
    } catch {
      answer(id, null);
    }
  }

  window.addEventListener("message", (e: MessageEvent) => {
    if (port || e.source !== window.parent) return;
    const d = e.data as { type?: unknown };
    if (d?.type !== "omni-mermaid-port" || e.ports.length !== 1) return;
    port = e.ports[0]!;
    port.onmessage = onRequest;
  });
  window.parent.postMessage({ type: "omni-mermaid-ready" }, "*");
}
