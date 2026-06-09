---
name: web-app-builder
description: Build previewable static or dynamic web apps, dashboards, and sites as OmniHarness artifacts with source projects, exported outputs, live preview sessions, and artifact_manifest.json metadata for the Artifact Canvas.
---

# Web App Builder

Use this skill when the user asks to create a website, web app, dashboard, landing page, frontend prototype, or browser-based artifact that should be previewable in OmniHarness.

## Artifact Layout

Always separate source code from exported artifacts:

- Source projects go under `/mnt/user-data/workspace/<artifact_id>`.
- Static preview outputs go under `/mnt/user-data/outputs/<artifact_id>`.
- Dynamic project manifests still live under `/mnt/user-data/outputs/<artifact_id>/artifact_manifest.json` even when the running app stays in workspace.
- Every website, dashboard, or app artifact must include `/mnt/user-data/outputs/<artifact_id>/artifact_manifest.json`.

Use a stable, lowercase `artifact_id` such as `sales-dashboard`, `omniharness-next-site`, or `research-portal`.

## Required Manifest

Create this file in the output root for static sites:

```json
{
  "id": "artifact-id",
  "title": "Human Friendly Project Title",
  "type": "static_site",
  "entrypoint": "index.html",
  "root": ".",
  "source_path": "/mnt/user-data/workspace/artifact-id",
  "preview": {
    "mode": "static"
  },
  "created_by": "agent"
}
```

Rules:

- `id` must match the output folder name whenever possible.
- `title` should describe the generated project, not just the file.
- `type` is `static_site` for exported builds and `web_app` for live preview projects.
- `root` is relative to the manifest file. Use `"."` for normal exports.
- `entrypoint` is relative to `root`. Required for `static_site`.
- Do not use `..`, absolute paths, symlinks, or paths outside `/mnt/user-data/outputs`.

For dynamic apps, use:

```json
{
  "id": "artifact-id",
  "title": "Human Friendly Project Title",
  "type": "web_app",
  "root": ".",
  "source_path": "/mnt/user-data/workspace/artifact-id",
  "preview": {
    "mode": "dev_server",
    "command": "npm run dev -- --hostname 0.0.0.0",
    "port": 3000
  },
  "created_by": "agent"
}
```

## Static HTML Pattern

Use this for small sites, single-file demos, and lightweight dashboards:

1. Create `/mnt/user-data/workspace/<artifact_id>/index.html`.
2. Put CSS and JS either inline or in relative asset files.
3. Copy the finished static files to `/mnt/user-data/outputs/<artifact_id>/`.
4. Create `artifact_manifest.json` in the output folder.
5. Present the Web App artifact (not the raw `artifact_manifest.json` file path).

## Vite Pattern

Use Vite for React, Vue, Svelte, or rich client apps:

1. Create the project under `/mnt/user-data/workspace/<artifact_id>`.
2. Configure relative assets by setting `base: "./"` in `vite.config.*`, or build with `vite build --base=./`.
3. Run the build.
4. Copy `dist/*` to `/mnt/user-data/outputs/<artifact_id>/`.
5. Create `artifact_manifest.json` with `root: "."` and `entrypoint: "index.html"`.
6. Present the Web App artifact.

Example:

```bash
npm run build -- --base=./
rm -rf /mnt/user-data/outputs/my-vite-app
mkdir -p /mnt/user-data/outputs/my-vite-app
cp -R dist/* /mnt/user-data/outputs/my-vite-app/
```

## Next.js Static Export Pattern

Use Next.js only when the requested app can be statically exported.

`next.config.js` should include:

```js
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  assetPrefix: "./",
};

export default nextConfig;
```

Then:

1. Build with `npm run build`.
2. Copy `out/*` to `/mnt/user-data/outputs/<artifact_id>/`.
3. Create `artifact_manifest.json`.
4. Present the Web App artifact.

If Next cannot statically export the requested app, explain the limitation and build the closest static version. Do not start a dev server for static artifact delivery.

## Dynamic Preview Pattern

Choose dynamic preview when:

- the user explicitly wants a live app
- the app needs API routes, server actions, auth simulation, or server-side state
- the framework does not static-export cleanly

For dynamic apps:

1. Build the project under `/mnt/user-data/workspace/<artifact_id>`.
2. Create `/mnt/user-data/outputs/<artifact_id>/artifact_manifest.json` with `type: "web_app"` and `preview.mode: "dev_server"`.
3. Use a command that binds to `0.0.0.0`, for example `npm run dev -- --hostname 0.0.0.0`.
4. Present the Web App project artifact. The Artifact Canvas will show the app title, a **Start Preview** button, and a logs panel. The user clicks Start Preview — OmniHarness starts the dev server and loads the returned preview URL into the canvas.
5. Do not create a static export unless the user asks for a portable build too.
6. Do not reference `0.0.0.0`, `localhost`, or the internal sandbox port in your response to the user. The user only sees the preview through the Artifact Canvas.
7. Dynamic apps do not require `index.html` in the outputs folder. Do not claim the app is ready by checking for a static entrypoint.

## Dashboard Artifact Pattern

Dashboards should be usable without server state:

- Precompute sample or uploaded-data summaries during the build step.
- Store static JSON/CSV assets under the output folder when needed.
- Use relative `fetch("./data/file.json")` paths.
- Make charts, filters, and panels client-side.
- Include the dashboard name in the manifest title, for example `"title": "Revenue Operations Dashboard"`.

## Presentation Checklist

Before finishing:

- Run the build command when the framework has one.
- For `static_site`: confirm `/mnt/user-data/outputs/<artifact_id>/index.html` exists and asset URLs are relative or work from a nested preview route.
- For `web_app`: confirm `/mnt/user-data/outputs/<artifact_id>/artifact_manifest.json` exists with `type: "web_app"` and a valid `preview.command`.
- Present the Web App project artifact using `present_files` with the manifest path. The Artifact Canvas renders the project card — not the raw JSON.
- Tell the user the app is ready in the Artifact Canvas and that they can click **Start Preview** to launch it.
