// Builds the kit's starter (omni-kit/starter + omni-kit) into one plain
// script for the probe end-to-end test, with no bundler and no download:
// TypeScript from the frontend's node_modules transpiles each file to
// CommonJS, and React's production CommonJS files are wrapped beside them.
//
//   node bundle_starter.mjs <project dir> <frontend dir> <out app.js>
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const [project, frontend, out] = process.argv.slice(2).map((p) => path.resolve(p));
const req = createRequire(path.join(frontend, "package.json"));
const ts = req("typescript");
const reactDir = path.dirname(req.resolve("react/package.json"));
const domDir = path.dirname(req.resolve("react-dom/package.json"));
const schedDir = path.dirname(createRequire(path.join(domDir, "package.json")).resolve("scheduler/package.json"));
const BARE = {
  react: path.join(reactDir, "cjs/react.production.js"),
  "react/jsx-runtime": path.join(reactDir, "cjs/react-jsx-runtime.production.js"),
  "react-dom": path.join(domDir, "cjs/react-dom.production.js"),
  "react-dom/client": path.join(domDir, "cjs/react-dom-client.production.js"),
  scheduler: path.join(schedDir, "cjs/scheduler.production.js"),
};

const modules = new Map();
function resolve(spec, from) {
  if (BARE[spec]) return BARE[spec];
  if (!spec.startsWith(".")) throw new Error(`unknown import ${spec} in ${from}`);
  const base = path.resolve(path.dirname(from), spec);
  for (const ext of ["", ".tsx", ".ts", ".js"]) {
    try {
      readFileSync(base + ext);
      return base + ext;
    } catch {}
  }
  throw new Error(`cannot resolve ${spec} from ${from}`);
}
function add(file) {
  if (modules.has(file)) return;
  modules.set(file, null);
  let code = readFileSync(file, "utf8");
  if (file.endsWith(".css")) code = "";
  else if (/\.tsx?$/.test(file)) {
    code = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  }
  const deps = {};
  for (const m of code.matchAll(/require\("([^"]+)"\)/g)) deps[m[1]] = resolve(m[1], file);
  modules.set(file, { code, deps });
  Object.values(deps).forEach(add);
}
const entry = path.join(project, "src/main.tsx");
add(entry);
const ids = [...modules.keys()];
const parts = ids.map((f, i) => {
  const { code, deps } = modules.get(f);
  const map = Object.fromEntries(Object.entries(deps).map(([k, v]) => [k, ids.indexOf(v)]));
  return `[function (module, exports, require) {\n${code}\n}, ${JSON.stringify(map)}]`;
});
writeFileSync(
  out,
  `(function () {
var process = { env: { NODE_ENV: "production" } };
var defs = [${parts.join(",\n")}];
var cache = {};
function load(i) {
  if (cache[i]) return cache[i].exports;
  var module = (cache[i] = { exports: {} });
  defs[i][0].call(module.exports, module, module.exports, function (s) { return load(defs[i][1][s]); });
  return module.exports;
}
load(${ids.indexOf(entry)});
})();
`,
);
