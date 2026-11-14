"use client";

import { languages } from "@codemirror/language-data";
import { basicLightInit } from "@uiw/codemirror-theme-basic";
import { monokaiInit } from "@uiw/codemirror-theme-monokai";
import CodeMirror, { EditorView, type Extension } from "@uiw/react-codemirror";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useState } from "react";

/**
 * Spec 012: a code artifact in CodeMirror, read only, highlighted for its
 * language (loaded on demand from @codemirror/language-data). The text is
 * an editor document: nothing in it is ever HTML.
 */

const dark = monokaiInit({
  settings: {
    background: "#000000",
    gutterBackground: "#000000",
    gutterForeground: "#8a8a8a",
    gutterBorder: "transparent",
    fontSize: "var(--text-sm)",
  },
});
const light = basicLightInit({
  settings: { background: "transparent", fontSize: "var(--text-sm)" },
});

export function ArtifactCode({
  text,
  language,
}: {
  text: string;
  language: string;
}) {
  const { resolvedTheme } = useTheme();
  const [lang, setLang] = useState<Extension | null>(null);
  useEffect(() => {
    let live = true;
    const name = language.toLowerCase();
    const desc = languages.find(
      (d) =>
        d.name.toLowerCase() === name ||
        d.alias.includes(name) ||
        d.extensions.includes(name),
    );
    if (!desc) {
      setLang(null);
      return;
    }
    void desc
      .load()
      .then((l) => live && setLang(l))
      .catch(() => live && setLang(null));
    return () => {
      live = false;
    };
  }, [language]);
  const extensions = useMemo(
    () => [EditorView.lineWrapping, ...(lang ? [lang] : [])],
    [lang],
  );
  return (
    <div
      className="border-border min-w-0 overflow-hidden rounded-md border"
      data-testid="artifact-code"
      data-language={language}
    >
      <CodeMirror
        value={text}
        readOnly
        editable={false}
        theme={resolvedTheme === "dark" ? dark : light}
        extensions={extensions}
        basicSetup={{
          foldGutter: false,
          highlightActiveLine: false,
          highlightActiveLineGutter: false,
          lineNumbers: true,
        }}
        className="max-h-[70vh] overflow-auto font-mono text-sm"
      />
    </div>
  );
}
