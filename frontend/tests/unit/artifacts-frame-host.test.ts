import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ArtifactFrameController,
  checkFrameMessage,
  cleanVars,
  frameSrc,
  type FrameRefusal,
} from "@/core/artifacts/frame-host";
import {
  liveSlotHolder,
  resetLiveSlot,
  setCardVisible,
} from "@/core/artifacts/live-slot";

/**
 * Spec 012 FR-016, FR-019: the host side of one locked artifact frame. A
 * real MessageChannel; the frame is a stand-in whose contentWindow records
 * what the host posts, and the test plays the shim on port 2.
 */

const NONCE = "n0nce-n0nce-n0nce-0123";
const ports: MessagePort[] = [];
afterEach(() => {
  for (const p of ports.splice(0)) p.close();
  resetLiveSlot();
});

function harness() {
  const refusals: FrameRefusal[] = [];
  const sizes: number[] = [];
  const opens: string[] = [];
  const torn: string[] = [];
  let port2: MessagePort | null = null;
  const frameWindow = {
    postMessage: vi.fn((_m: unknown, _o: string, transfer?: MessagePort[]) => {
      port2 = transfer?.[0] ?? null;
      if (port2) ports.push(port2);
    }),
  };
  const controller = new ArtifactFrameController({
    theme: "dark",
    vars: {
      "--background": "#121316",
      "bad name": "x",
      "--x": "url(https://e)",
    },
    nonce: NONCE,
    settleMs: 0,
    helloGraceMs: 30,
    onSize: (h) => sizes.push(h),
    onOpenRequest: (u) => opens.push(u),
    onTornDown: (r) => torn.push(r),
    reportRefusal: (r) => refusals.push(r),
  });
  controller.attach({ contentWindow: frameWindow as unknown as Window });
  const hello = (nonce = NONCE) =>
    controller.handleWindowMessage({
      source: frameWindow as unknown as Window,
      data: { v: 1, type: "hello", nonce },
    });
  const connect = async () => {
    hello();
    controller.handleLoad();
    await new Promise((r) => setTimeout(r, 5));
    return port2!;
  };
  const send = async (data: unknown, transfer: Transferable[] = []) => {
    port2!.postMessage(data, transfer);
    await new Promise((r) => setTimeout(r, 10));
  };
  return {
    controller,
    frameWindow,
    refusals,
    sizes,
    opens,
    torn,
    hello,
    connect,
    send,
  };
}

describe("artifact frame host", () => {
  it("sends init with the theme and clean vars only after one hello and one load", async () => {
    const h = harness();
    const port = await h.connect();
    expect(port).toBeTruthy();
    expect(h.controller.state).toBe("connected");
    const [init, origin] = h.frameWindow.postMessage.mock.calls[0]!;
    expect(origin).toBe("*");
    expect(init).toEqual({
      v: 1,
      type: "init",
      theme: "dark",
      vars: { "--background": "#121316" },
    });
    expect(JSON.stringify(init)).not.toMatch(/token|csrf|session|cookie/i);
  });

  it("accepts exactly ready, size (clamped) and https open on the port", async () => {
    const h = harness();
    await h.connect();
    await h.send({ v: 1, type: "size", height: 5000 });
    await h.send({ v: 1, type: "size", height: 10 });
    await h.send({ v: 1, type: "open", url: "https://example.org/a" });
    expect(h.sizes).toEqual([1200, 120]);
    expect(h.opens).toEqual(["https://example.org/a"]);
    expect(h.refusals).toEqual([]);
  });

  it.each([
    [{ v: 1, type: "data", id: "1", source: "calendar" }, "unknown_type"],
    [{ v: 1, type: "open", url: "http://example.org" }, "link_refused"],
    [{ v: 1, type: "open", url: "javascript:alert(1)" }, "link_refused"],
    [{ v: 1, type: "open", url: "https://u:p@example.org" }, "link_refused"],
    [{ v: 1, type: "size", height: 300, extra: 1 }, "bad_shape"],
    [{ v: 2, type: "ready" }, "bad_version"],
    ["ready", "not_an_object"],
  ])("refuses %j", async (msg, reason) => {
    const h = harness();
    await h.connect();
    await h.send(msg);
    expect(h.refusals.map((r) => r.reason)).toEqual([reason]);
    expect(h.sizes).toEqual([]);
    expect(h.opens).toEqual([]);
  });

  it("closes transferred ports and limits the rate", async () => {
    const h = harness();
    const port = await h.connect();
    const extra = new MessageChannel();
    ports.push(extra.port1, extra.port2);
    await h.send({ v: 1, type: "ready" }, [extra.port2]);
    expect(h.refusals.at(-1)?.reason).toBe("transfer_refused");
    for (let i = 0; i < 40; i++) port.postMessage({ v: 1, type: "ready" });
    await new Promise((r) => setTimeout(r, 30));
    expect(h.refusals.some((r) => r.reason === "rate_limited")).toBe(true);
  });

  it("tears down on a second load, a second hello, a wrong nonce or no hello", async () => {
    const a = harness();
    await a.connect();
    a.controller.handleLoad();
    expect(a.torn).toEqual(["second_load"]);
    const b = harness();
    await b.connect();
    b.hello();
    expect(b.torn).toEqual(["second_document"]);
    const c = harness();
    c.hello("wrong-nonce-wrong-nonce");
    expect(c.torn).toEqual(["bad_nonce"]);
    const d = harness();
    d.controller.handleLoad();
    await new Promise((r) => setTimeout(r, 60));
    expect(d.torn).toEqual(["no_hello"]);
  });

  it("ignores other windows and refuses non-hello window messages from the frame", async () => {
    const h = harness();
    h.controller.handleWindowMessage({
      source: {} as Window,
      data: { v: 1, type: "hello", nonce: NONCE },
    });
    expect(h.controller.state).toBe("waiting");
    // The real frame's hello and load still connect: the stranger's did not count.
    h.hello();
    h.controller.handleLoad();
    await new Promise((r) => setTimeout(r, 5));
    expect(h.controller.state).toBe("connected");
    h.controller.handleWindowMessage({
      source: h.frameWindow as unknown as Window,
      data: { v: 1, type: "size", height: 300 },
    });
    expect(h.refusals.map((r) => r.reason)).toEqual(["not_on_port"]);
  });

  it("frame URL carries the nonce and theme in the fragment only", () => {
    expect(
      frameSrc("/api/artifacts/a/versions/1/frame.html?t=x", NONCE, "light"),
    ).toBe(`/api/artifacts/a/versions/1/frame.html?t=x#n=${NONCE}&t=light`);
    expect(checkFrameMessage({ v: 1, type: "ready" })).toEqual({
      ok: true,
      message: { v: 1, type: "ready" },
    });
    expect(cleanVars({ "--a": "#fff", "--b": "red;}" })).toEqual({
      "--a": "#fff",
    });
  });
});

describe("live slot", () => {
  it("N visible cards: at most one live frame, the newest visible", () => {
    for (let i = 0; i < 5; i++) setCardVisible(`c${i}`, true);
    expect(liveSlotHolder()).toBe("c4");
    setCardVisible("c4", false);
    expect(liveSlotHolder()).toBe("c3");
    for (let i = 0; i < 4; i++) setCardVisible(`c${i}`, false);
    expect(liveSlotHolder()).toBeNull();
  });
});
