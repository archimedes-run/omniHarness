import { createElement, type ComponentType, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ExternalLink } from "@/components/workspace/citations/external-link";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import { isAppUrl, isLocalImageUrl } from "@/core/display/defang";
import { streamdownPlugins } from "@/core/streamdown";

/**
 * Tighter same-origin and label checks for links and images in agent text
 * (core/display/defang.ts, core/display/link-label.ts,
 * core/streamdown/content-url-guard.ts).
 */
function render(content: string): string {
  return renderToStaticMarkup(
    createElement(MarkdownContent, {
      content,
      isLoading: false,
      rehypePlugins: streamdownPlugins.rehypePlugins,
    }),
  );
}

const Link = ExternalLink as ComponentType<{
  href: string;
  children?: ReactNode;
}>;

describe("same origin", () => {
  it("a URL that names a scheme is never the app's own, whatever the scheme", () => {
    for (const url of [
      "https:evil.example/p",
      "http:evil.example/p",
      "HTTPS:evil.example/p.png",
      " h\ttps:evil.example/p",
      "https:\n//evil.example/p",
      "https://evil.example/p",
    ]) {
      expect(isAppUrl(url), url).toBe(false);
      expect(isLocalImageUrl(url), url).toBe(false);
    }
    for (const url of [
      "/api/threads/t1/artifacts/a.png",
      "chart.png",
      "/workspace/chats/t1",
    ]) {
      expect(isAppUrl(url), url).toBe(true);
    }
    expect(isLocalImageUrl("data:image/png;base64,AAAA")).toBe(true);
  });

  it("a scheme-relative link or image in agent text is neither live nor fetched", () => {
    const html = render(
      [
        "[x](https:evil.example/p)",
        "<https:evil.example/q>",
        "![s](https:evil.example/p.png)",
      ].join("\n\n"),
    );
    expect(html).not.toMatch(/href="https?:/i);
    expect(html).not.toMatch(/<img/i);
    expect(html).not.toMatch(/preload/i);
    expect(html).toContain("Image from evil[.]example not loaded");
    expect(html.match(/data-external-link/g)).toHaveLength(2);
    expect(html).toContain(">https://evil.example/q</button>");
  });
});

describe("labels", () => {
  const misleading: [string, string][] = [
    ["[good​.example](https://evil.example/x)", "https://evil.example/x"],
    ["[good­.example](https://evil.example/x)", "https://evil.example/x"],
    ["[good.example​](https://evil.example/x)", "https://evil.example/x"],
    ["[good.example.](https://evil.example/x)", "https://evil.example/x"],
    ["[good.example:443](https://evil.example/x)", "https://evil.example/x"],
    ["[good.example?a](https://evil.example/x)", "https://evil.example/x"],
    ["[(good.example)](https://evil.example/x)", "https://evil.example/x"],
    ["[good.example,](https://evil.example/x)", "https://evil.example/x"],
    ["[gооgle.com](https://evil.example/x)", "https://evil.example/x"],
    ["[ｇｏｏｄ.com](https://evil.example/x)", "https://evil.example/x"],
    ["[good。com](https://evil.example/x)", "https://evil.example/x"],
    ["[paypal.md](https://evil.example/x)", "https://evil.example/x"],
    ["[good\u2024example](https://evil.example/x)", "https://evil.example/x"],
    ["[good.example\u2026](https://evil.example/x)", "https://evil.example/x"],
    ["[https:good.example](https://evil.example/x)", "https://evil.example/x"],
    [
      "[https:/good.example/](https://evil.example/x)",
      "https://evil.example/x",
    ],
    [
      "[//good.example/login](https://evil.example/x)",
      "https://evil.example/x",
    ],
    [
      "[https://good.com@evil.example/](https://evil.example/)",
      "https://evil.example/",
    ],
  ];

  it.each(misleading)("%s shows the URL the link opens", (markdown, shown) => {
    const html = render(markdown);
    expect(html).toContain(`>${shown}</button>`);
  });

  it("labels that name the link's own host, or are titles or file names, stay", () => {
    for (const [markdown, label] of [
      ["[vetri.example](https://www.vetri.example/menu)", ">vetri.example<"],
      ["[(vetri.example)](https://vetri.example/)", ">(vetri.example)<"],
      ["[Vetri Cucina](https://vetri.example/)", ">Vetri Cucina<"],
      ["[report.pdf](https://files.example/r)", ">report.pdf<"],
      [
        "[README.md](https://github.com/o/r/blob/main/README.md)",
        ">README.md<",
      ],
      ["[setup.py](https://github.com/o/r/blob/main/setup.py)", ">setup.py<"],
    ] as const) {
      expect(render(markdown), markdown).toContain(label);
    }
  });

  it("a bare URL with look-alike letters shows its host as the browser resolves it", () => {
    const bare = "https://gооgle.com/x";
    const punycode = `https://${new URL(bare).host}/x`;
    expect(punycode).toContain("xn--");
    const html = render(`see ${bare} now`);
    expect(html).toContain(`>${punycode}</button>`);
    expect(html).not.toContain("gооgle");
  });

  it("a citation badge never names another host than the link opens", () => {
    const badge = (label: string, href: string) =>
      renderToStaticMarkup(createElement(Link, { href }, label));
    expect(badge("citation:good.example", "https://evil.example/x")).toContain(
      "evil[.]example",
    );
    expect(
      badge("citation:good.example", "https://evil.example/x"),
    ).not.toContain("good.example");
    expect(badge("citation:Vetri Cucina", "https://vetri.example/")).toContain(
      "Vetri Cucina",
    );
    expect(badge("citation:vetri.example", "https://vetri.example/")).toContain(
      "vetri.example",
    );
  });
});
