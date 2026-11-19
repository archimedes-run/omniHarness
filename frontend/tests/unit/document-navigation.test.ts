import { afterEach, describe, expect, it, vi } from "vitest";

import {
  crossesDocumentPolicy,
  documentLoadTarget,
  navigateWorkspace,
  type DocumentClickAnchor,
} from "@/core/security/document-navigation";

const origin = "https://example.test";
afterEach(() => vi.unstubAllGlobals());
describe("document policy navigation", () => {
  it.each([
    ["/workspace/apps/today", "/workspace/artifacts/id", true],
    ["/workspace/chats/id", "/workspace/apps", true],
    ["/login", "/workspace/apps/today", true],
    ["/workspace/apps/today", "/login", true],
    ["/workspace/apps/today", "/workspace/apps/another", false],
    ["/workspace/artifacts/id", "/workspace/chats/id", false],
    ["/workspace/apps-other", "/workspace/chats/id", false],
    ["/workspace/apps/today", "https://elsewhere.test/path", false],
  ])("classifies %s → %s", (from, to, expected) => {
    expect(
      crossesDocumentPolicy(new URL(from, origin), new URL(to, origin)),
    ).toBe(expected);
  });
  it.each([
    ["/login", "/workspace/apps/today", true],
    ["/workspace/apps/today", "/workspace/chats/id", true],
    ["/workspace/chats/id", "/workspace/artifacts/id", false],
  ])("navigates %s → %s with the matching document", (from, to, full) => {
    const assign = vi.fn();
    const push = vi.fn();
    vi.stubGlobal("window", { location: { href: origin + from, assign } });
    navigateWorkspace(to, push);
    if (full) {
      expect(assign).toHaveBeenCalledWith(origin + to);
      expect(push).not.toHaveBeenCalled();
    } else {
      expect(push).toHaveBeenCalledWith(to);
      expect(assign).not.toHaveBeenCalled();
    }
  });
});

describe("document load on link click", () => {
  const plain = {
    defaultPrevented: false,
    button: 0,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
  };
  const link = (href: string, extra: Partial<DocumentClickAnchor> = {}) => ({
    href: origin + href,
    target: "",
    download: false,
    ...extra,
  });
  const apps = origin + "/workspace/apps/today";
  const chat = origin + "/workspace/chats/id";

  // The sidebar, header, library, recent-chat and portal links all reach
  // the same capture listener; each pair is one of those crossings.
  it.each([
    [chat, "/workspace/apps"], // sidebar "Apps"
    [chat, "/workspace/apps/today"], // sidebar pinned app
    [origin + "/workspace/artifacts", "/workspace/apps/today"],
    [origin + "/workspace/home", "/workspace/apps/budget"], // library to app
    [apps, "/workspace/chats/id"], // recent chat from an app
    [apps, "/workspace/artifacts"], // sidebar menu from an app
    [apps, "/workspace/home"], // sidebar home from an app
    [apps, "/"], // header logo from an app
  ])("forces a document load %s → %s", (current, href) => {
    expect(documentLoadTarget(plain, link(href), current)).toBe(origin + href);
  });

  it.each([
    [chat, "/workspace/artifacts"],
    [apps, "/workspace/apps/another"],
    [origin + "/workspace/apps", "/workspace/apps/today"],
  ])("leaves %s → %s to client routing", (current, href) => {
    expect(documentLoadTarget(plain, link(href), current)).toBeNull();
  });

  it.each([
    ["meta", { metaKey: true }],
    ["ctrl", { ctrlKey: true }],
    ["shift", { shiftKey: true }],
    ["alt", { altKey: true }],
    ["middle button", { button: 1 }],
    ["already handled", { defaultPrevented: true }],
  ])("ignores a %s click", (_name, mod) => {
    expect(
      documentLoadTarget({ ...plain, ...mod }, link("/workspace/apps"), chat),
    ).toBeNull();
  });

  it("ignores download, new-tab and other-origin anchors", () => {
    expect(
      documentLoadTarget(
        plain,
        link("/workspace/apps", { download: true }),
        chat,
      ),
    ).toBeNull();
    expect(
      documentLoadTarget(
        plain,
        link("/workspace/apps", { target: "_blank" }),
        chat,
      ),
    ).toBeNull();
    expect(
      documentLoadTarget(
        plain,
        {
          href: "https://elsewhere.test/workspace/apps",
          target: "",
          download: false,
        },
        chat,
      ),
    ).toBeNull();
    expect(documentLoadTarget(plain, null, chat)).toBeNull();
  });

  it("honours an explicit _self target", () => {
    expect(
      documentLoadTarget(
        plain,
        link("/workspace/apps", { target: "_self" }),
        chat,
      ),
    ).toBe(origin + "/workspace/apps");
  });
});
