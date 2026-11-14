/*
 * npm run check:render (or: node omni-kit/check-render.mjs) — renders the app
 * WITHOUT a browser, in every mock state, and fails with React's own error
 * message and the component that threw. Run it before you finish; the
 * system's verify command for apps runs it too.
 *
 * It bundles omni-kit/render-entry.tsx (which imports the default export of
 * src/App.tsx) with the project's own Vite, as a development build, then
 * renders it with react-dom/client in a small in-memory DOM
 * (check-render-core.mjs). Written by the system; do not edit.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const kit = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(kit);
const out = path.join(root, ".omni-check");
process.env.NODE_ENV = "development";
await build({
  root,
  configFile: false,
  logLevel: "error",
  mode: "development",
  define: { "process.env.NODE_ENV": JSON.stringify("development") },
  esbuild: { jsx: "automatic" },
  ssr: { noExternal: true, target: "node" },
  build: {
    ssr: path.join(kit, "render-entry.tsx"),
    outDir: out,
    emptyOutDir: true,
    minify: false,
    rollupOptions: { output: { format: "es", entryFileNames: "entry.mjs", inlineDynamicImports: true } },
  },
});
const { run } = await import(pathToFileURL(path.join(out, "entry.mjs")).href);
const ok = await run(fs.readFileSync(path.join(kit, "omni-mock.js"), "utf8"));
process.exit(ok ? 0 : 1);
