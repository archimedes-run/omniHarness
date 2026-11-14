# Apps, Slice 1: gateway API contract (PR 1)

The contract between the gateway (PR 1) and the frontend host page, library and
approval card (PR 2), and the coding job's app mode (PR 3a). Requirements are in
`specs/011-apps/spec.md`; this file names routes, JSON shapes and error codes only.

## Conventions

- Every route needs the **owner's browser session** (the `access_token` cookie).
  A request carrying the internal token (`X-OmniHarness-Internal-Token`: channels,
  the trigger engine, anything acting for the system) is refused with
  `403 owner_session_required`, on every route, reads included. Apps of another
  account are `404 app_not_found`, never `403`, so their ids are not confirmed.
- State-changing routes (`POST`, `PUT`) need the CSRF double-submit header
  (`X-CSRF-Token`), like every other gateway write.
- Errors are FastAPI's shape with a stable code:

  ```json
  {"detail": {"code": "not_approved", "message": "This app's data sources have not been approved."}}
  ```

- Times are ISO 8601 with offset (UTC).
- An app id is `[a-z0-9][a-z0-9-]{0,47}`. A source name is `[a-z][a-z0-9_]{0,31}`.

### Error codes

| HTTP | code | When |
|---|---|---|
| 401 | (auth middleware) | no session |
| 403 | `owner_session_required` | internal token, or a session that is not a person's |
| 404 | `app_not_found` | no such app for this owner |
| 404 | `version_not_found` | no such version of the app |
| 404 | `unknown_source` | the source is not in the current version's manifest |
| 404 | `no_pending_approval` | the app needs no approval (or the card is gone) |
| 403 | `not_approved` | the current version's manifest hash has no active grant (bridge) |
| 403 | `source_refused` | the source failed a read-only check (catalog allowlist, Tier 1, runtime floor) |
| 409 | `hash_mismatch` | approve: the hash posted is not the current version's hash |
| 409 | `stale_version` | restore: `base_version` is no longer the current version |
| 422 | `invalid_request` | pins that are not distinct apps of yours. Other body validation failures use FastAPI's default 422 shape (`detail` is a list) |
| 429 | `rate_limited` | 60 bridge requests per app per minute per owner; `Retry-After` header set |
| 500 | `bridge_failed` | the bridge failed unexpectedly (logged by error type only) |
| 503 | `apps_unavailable` | the gateway has no SQL store |

## Library

### `GET /api/apps`

```json
{
  "apps": [
    {
      "id": "today",
      "name": "Today",
      "description": "My day at a glance",
      "current_version": 3,
      "manifest_hash": "9f2c…(64 hex)",
      "status": "approved",
      "pinned": true,
      "updated_at": "2026-11-13T10:00:00+00:00",
      "last_opened_at": "2026-11-13T10:05:00+00:00",
      "pending_version": null
    }
  ]
}
```

`current_version` is the version the app SERVES. `pending_version` is a newer
version waiting on the owner's button (registered after content led the
request: even a code-only change waits), or `null`. Until it is approved the
served version keeps serving, and the pending card's `version` names the
pending one.

`status` is one of:

- `approved`: an active grant exists for the current version's manifest hash.
- `needs_approval`: no active grant for that hash (new app, or a version whose
  sources changed, or a restore to a version never approved).
- `revoked`: the owner pressed Revoke and nothing was approved since. Shown as
  "Access revoked" with an Approve again card.

### `GET /api/apps/{id}`

```json
{
  "id": "today",
  "name": "Today",
  "description": "My day at a glance",
  "current_version": 3,
  "manifest_hash": "9f2c…",
  "status": "approved",
  "pinned": true,
  "updated_at": "…",
  "last_opened_at": "…",
  "html_url": "/api/apps/today/versions/3/app.html",
  "sources": [ SourceView, … ],
  "approval": ApprovalCard | null
}
```

`SourceView` (one per manifest source, in manifest order):

```json
{
  "name": "inbox",
  "use": "gmail.unread_subjects",
  "words": "Read subjects of unread mail in Primary from the last 3 days, not from you (not bodies): how many, subject, received time, link",
  "fields": ["count", "subject", "received_at", "link"],
  "params": {"limit": 25},
  "refresh_s": 300,
  "refresh_words": "Refreshes every 5 minutes while you use it",
  "link_hosts": ["mail.google.com"],
  "last_fetched_at": "…" ,
  "last_state": "fresh",
  "last_error": null
}
```

`last_*` come from the shared cache for the current manifest hash; all `null`
before the first fetch. `last_error` is the sanitised reason of the last failed
fetch (≤ 300 chars) or `null`.

### `GET /api/apps/{id}/versions`

```json
{
  "current": 4,
  "versions": [
    {"version": 4, "at": "…", "who": "<owner id>", "source": "undo", "changed": ["restored from version 1"], "manifest_hash": "…", "approved": false, "restored_from": 1},
    {"version": 3, "at": "…", "who": "code_job", "source": "code_job", "changed": ["bundle"], "manifest_hash": "…", "approved": true, "restored_from": null}
  ]
}
```

Newest first. `approved`: that version's hash has an active grant now.
`source` is `code_job` (registered by a verified app-mode job) or `undo` (a
library Restore).

### `POST /api/apps/{id}/restore`

Body: `{"to_version": 1, "base_version": 3}` (`base_version` optional; when sent
and not the current version: `409 stale_version`). Creates a NEW version with
`to_version`'s manifest and bundle (undo is a new version). Response: the app as
in `GET /api/apps/{id}` (`200`). If the restored manifest hash has no active
grant, `status` is `needs_approval` and `approval` carries a new card.

### `GET /api/apps/{id}/permissions`

```json
{
  "app_id": "today",
  "version": 3,
  "manifest_hash": "…",
  "status": "approved",
  "sentence": "Data is shown in the app only; the assistant never sees it.",
  "sources": [ SourceView, … ],
  "grants": [
    {"manifest_hash": "…", "approved_at": "…", "revoked_at": null, "version": 3}
  ],
  "activity": [
    {"at": "…", "event": "app_approved", "detail": {"version": 3, "manifest_hash": "…", "card": "…", "via": "button"}}
  ]
}
```

`grants` is newest first and includes ended ones. `activity` is the app's last
20 audit entries, newest first: `app_registered`, `app_approved`,
`app_revoked`, `app_restored`, `bridge_refused` (`detail.reason`:
`not_approved` / `unknown_source` / `source_refused`), `app_message_refused`.
Events and ids only, never data.

### `POST /api/apps/{id}/revoke`

No body. Ends every grant of the app, deletes every cache row of the app and
stops its refreshes, effective on the next bridge call.

```json
{"status": "revoked", "grants_ended": 1, "cache_rows_deleted": 7}
```

Idempotent: revoking again answers with zero counts.

## Approval card (button only)

### `ApprovalCard`

```json
{
  "id": "c0ffee…(32 hex)",
  "app_id": "today",
  "app_name": "Today",
  "version": 3,
  "manifest_hash": "9f2c…",
  "status": "pending",
  "sources": [
    {"name": "calendar", "words": "Read today's events from Google Calendar (title, start, end, all day), for the day in Europe/London", "refresh_words": "Refreshes every 5 minutes while you use it"}
  ],
  "sentence": "Data is shown in the app only; the assistant never sees it.",
  "suggestion": false,
  "suggestion_source": null,
  "suggestion_words": null,
  "thread_id": "…" ,
  "created_at": "…",
  "resolved_at": null
}
```

- Every `words` string is built by the gateway from the catalog entry, the
  chosen fields and params. Nothing the app, the worker or the manifest's
  `name`/`description` wrote is in `sources` (show `app_name` as a title only).
- `suggestion: true` when the job that built the app was led by content (an
  email, a page, an automation's turn), with `suggestion_source` naming it
  (for example "an email you read earlier"). The card still grants only by its
  button. `suggestion_source` is cleaned by the gateway (no control or
  formatting characters, quotes or angle brackets; at most 120 characters);
  `suggestion_words` is the line to show, with it quoted:
  `Suggested after reading: “…”`. Render both as text.
- `status`: `pending`, `approved`, or `superseded` (a newer version replaced it
  before it was approved).
- Typed chat text never grants. There is no confirmation-by-message path for
  these cards; they are not pending tool calls.

### `GET /api/apps/{id}/approval`

The current pending card for the app, or `404 no_pending_approval`.

### `GET /api/apps/approvals?thread_id={thread_id}`

Cards raised in one conversation, newest first, any status (so a resolved card
can render "Allowed"): `{"cards": [ApprovalCard, …]}`. `thread_id` is required.

### `POST /api/apps/{id}/approve`

Body: `{"manifest_hash": "<the hash the card showed>", "card_id": "<card id>"}`.

- `200 {"status": "approved", "manifest_hash": "…", "approved_at": "…"}`.
- `409 hash_mismatch` when `manifest_hash` is not the hash of the version the
  card was drawn for (reload the card). A newer registration supersedes a
  pending card (`404` for the old one).
- Approving a pending version makes it the served one.
- `404 no_pending_approval` when `card_id` is not this app's pending card.
- `403 owner_session_required` for any internal-token caller. Only the
  owner's own button press, from the browser, approves.

## Bridge

### `SourceResult`

```json
{
  "source": "calendar",
  "state": "fresh",
  "data": {"items": [{"title": "Design review", "start": "…", "end": "…", "all_day": false}]},
  "fetched_at": "2026-11-13T10:01:00+00:00",
  "stale": false,
  "reason": null
}
```

- `state` ∈ `fresh` (data with at least one item or a non-zero count),
  `empty` (the source answered with nothing), `not_connected` (no active
  connection for the toolkit, from the same lookup Home uses; `data` null),
  `failed` (could not be read: `reason` set, `data` is the last good data or
  null).
- `fetched_at`: when `data` was fetched (for `failed` with last good data, when
  that data was fetched); `null` when nothing was ever fetched.
- `stale`: `fetched_at` older than twice the source's `refresh_s`, or a
  `failed` result carrying last good data.
- `reason`: only for `failed`, sanitised, ≤ 300 chars.

### `GET /api/apps/{id}/data/{source}`

One source of the app's **current** version. Query parameters are ignored,
except `refresh=1`, which asks for a refetch now (still at most one upstream
call per source per 60 s; inside that window the cached result is returned).
Errors: `404 app_not_found`, `404 unknown_source`, `403 not_approved`,
`403 source_refused`, `429 rate_limited`.

### `GET /api/apps/{id}/data`

Every source in one round trip:

```json
{"app_id": "today", "version": 3, "results": {"calendar": SourceResult, "inbox": SourceResult}}
```

Same errors as above (`403 not_approved` when the version is not approved).
A source that fails a read-only check does not fail the whole batch: its
result is `failed` with a `reason` starting `Refused:`.
Calling it (or loading `app.html`) marks the app as opened; the refresher keeps
sources of apps opened in the last 24 h warm.

### Data shapes per catalog entry

Only the fields the manifest selected appear in each item.

| Catalog entry | `data` |
|---|---|
| `googlecalendar.events_today` | `{"items": [{"title", "start", "end", "all_day"}]}` (≤ 50; cancelled events dropped) |
| `github.pr_search` | `{"items": [{"repo", "number", "title", "updated_at", "merged_at", "link"}]}` |
| `omni.ledger.today` | `{"items": [{"bucket": "moved"\|"stuck"\|"overdue", "task", "project", "status", "due_date", "link"}]}` |
| `omni.sessions.active` (install-wide: the session watcher is not per user) | `{"items": [{"tool", "title", "display_state": "working"\|"waiting-on-user", "known": "observed"\|"inferred", "since"}]}` |
| `omni.automations.recent` (install-wide: the trigger engine is not per user) | `{"items": [{"rule", "last_run", "outcome", "next_run"}]}` |
| `gmail.unread_subjects` | `{"count": 12, "count_capped": false, "items": [{"subject", "received_at", "link"}]}` (never body, snippet or sender) |

Strings are clipped (200 chars), arrays capped at 50, the payload ≤ 64 KB.
Links are built by the gateway (`https://github.com/{repo}/pull/{n}`,
`https://mail.google.com/mail/u/0/#inbox/{thread id}`, `/workspace/projects/{id}`).

## App HTML

### `GET /api/apps/{id}/versions/{n}/app.html`

The registered, self-contained document. Headers (exact):

```
Content-Type: text/html; charset=utf-8
Cache-Control: private, max-age=31536000, immutable
Content-Security-Policy: sandbox allow-scripts; default-src 'none'; script-src 'sha256-…' …; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src 'none'; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; require-trusted-types-for 'script'; trusted-types 'none'
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
Cross-Origin-Resource-Policy: same-origin
X-DNS-Prefetch-Control: off
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=(), clipboard-write=()
```

`script-src` lists one `'sha256-…'` per inline script, computed at
registration; the first is always the platform shim, which the gateway injects
as the document's first script from its own copy of the generated
`omni-shim.js` (a shim the bundle carries, by reference or inlined, is
dropped). Trusted Types with no policy: no `innerHTML` or any other
HTML-from-string API works in the app. Embed it only as
`<iframe sandbox="allow-scripts" src="…">`.

## Refusals reported by the host

### `POST /api/apps/{id}/refused`

The host page reports a frame message it dropped (FR-022). Body:

```json
{"reason": "source_not_approved", "type": "data", "source": "inbox_bodies"}
```

Codes only, no free text (a frame cannot carry data into the log through a
report): `reason` matches `[a-z][a-z0-9_]{0,47}` (for example
`source_not_approved`, `unknown_type`, `invalid_message`, `oversized`,
`rate_limited`, `second_load`, `second_document`, `no_hello`, `bad_nonce`); `type` and `source` (both optional) match
`[a-z][a-z0-9_]{0,31}`; send no `source` when the frame's value is not a
valid name. Anything else is `422`. Stored in the apps audit log as
`app_message_refused`. `204`. Rate limited with the bridge's per-app limit.

## Catalog (for the kit and the fake bridge)

### `GET /api/apps/catalog`

```json
{
  "entries": [
    {
      "id": "gmail.unread_subjects",
      "kind": "connector",
      "toolkit": "GMAIL",
      "fields": ["count", "subject", "received_at", "link"],
      "params": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 25}},
      "link_hosts": ["mail.google.com"],
      "default_refresh_s": 300
    }
  ],
  "refresh_s": {"default": 300, "minimum": 60, "maximum": 3600}
}
```

Param schema types: `integer` (`minimum`, `maximum`, `default`), `enum`
(`values`, `default`), `timezone` (IANA name, `default` "UTC"). A param marked
`"required": true` has no default.

## Pins (per-user preferences)

- `GET /api/preferences/app-pins` → `{"pins": ["today", "ci"]}` (sidebar order).
- `PUT /api/preferences/app-pins` body `{"pins": ["today"]}` → `{"pins": [...]}`.
  At most 20, no duplicates, each an app of this owner (`422 invalid_request`
  otherwise).

## Manifest (`omni-app.json`)

```json
{
  "schema": 1,
  "name": "Today",
  "description": "My day at a glance",
  "sources": {
    "calendar": {"use": "googlecalendar.events_today", "params": {"tz": "Europe/London"}, "fields": ["title", "start", "end", "all_day"]},
    "gh_review": {"use": "github.pr_search", "params": {"preset": "review_requested"}, "fields": ["repo", "number", "title", "updated_at", "link"], "refresh_s": 600},
    "inbox": {"use": "gmail.unread_subjects", "fields": ["count", "subject", "received_at", "link"]}
  }
}
```

Unknown keys anywhere are refused. `name` 1–60 chars, `description` ≤ 300,
1–12 sources. The manifest hash is SHA-256 of the canonical JSON (sorted keys,
no whitespace, defaults filled in) of `sources` only.

## Registration (in process, PR 3a)

Not an HTTP route: only the gateway, after a verified app-mode coding job,
registers an app (FR-007, FR-028).

```python
from app.gateway.apps.registry import register_app

result = await register_app(
    app_state,                      # request.app.state or the gateway's app.state
    owner_id=owner_id,
    manifest=manifest_dict,         # parsed omni-app.json
    files={"index.html": b"...", "assets/app.js": b"..."},  # the build output
    app_id=None,                    # None: a new app (id from the name); else a new version of it
    thread_id=thread_id,            # where the approval card is shown
    origin=("user", None),          # or ("content", "an email you read earlier")
)
# origin "content" on an existing app: the version is held (not served) until
# the owner approves its card; the last served version keeps serving.
# result.app_id, result.version, result.manifest_hash, result.needs_approval, result.card_id
```

Raises `AppRegistrationError(code, message)` with codes `invalid_manifest`,
`source_refused` (a connector source failing a read-only check),
`invalid_request` (a malformed `app_id`), `apps_unavailable` (no SQL store),
`invalid_bundle` (entry file not UTF-8),
`forbidden_markup` (`<iframe>`, `<frame>`, `<frameset>`, `<object>`,
`<embed>`, `<portal>`, `<fencedframe>`, `srcdoc`), `bundle_too_large` (> 2 MB after inlining), `forbidden_api` (`RTCPeerConnection`,
`RTCDataChannel`, `WebSocket`, `eval`, `new Function`), `remote_url` (a script,
style, image or font that is not inline or `data:`; also any `src`, `href`,
`action` or `srcset` in markup pointing at a remote or `javascript:` URL,
`<a href="https://…">` included: links go through the `open` message),
`missing_file`. Code inside `<script>` is not scanned for URLs (the CSP
governs it) but is scanned for the forbidden names and frame markup. The scan
is defence in depth: a name built from strings at run time dodges it; the
CSP's Trusted Types and the injected shim are the guards.
