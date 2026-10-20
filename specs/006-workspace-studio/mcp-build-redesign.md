# MCP Build (PR #59): redesign plan

Status: **PLAN ONLY. Waiting for the user's OK before any product code changes.**
Branch: `006-E-mcp-build`. Prerequisite: the security baseline (review round 2, item C.0: owner-only registration, server-owned context, ownership checks, 127.0.0.1 bindings) lands on `main` first; this work rebases onto it.

Revision 2 (2026-10-20) addresses an independent review: 4 HIGH, 4 MED and 5 LOW findings (§10).
Revision 3 (2026-10-20) records the user's answers to the four questions, and replaces our own proxy with **Squid** (§4, §10.2).
Revision 5 (2026-10-20): **built** on this branch; what shipped and where it differs is in §11.
Revision 4 (2026-10-20, **plan approved; building**) folds in the user's build-time changes (§10.3):
- Alpine is pinned by digest;
- **no secrets in environment variables at all**: they are delivered as 0400 files on a tmpfs;
- the CDN-fronting residual is **accepted**;
- the runtime image gets its Python packages without a pip download.

Every claim about current behaviour below was read in the code at `366765e`, or observed on the live stack with read-only commands (`docker ps`, `docker inspect` (names only, never values)). Line references are to that commit.

---

## 0. What is live right now and breaks these rules

`docker ps` on the user's machine (observed 2026-10-20):

| Observed | Rule it breaks |
|---|---|
| `omni-mcp-c641ac8dc68d` publishes `0.0.0.0:18100->8080` | Bind to 127.0.0.1. Today any device on the LAN can open its SSE endpoint, which has no authentication, and call its tools with the user's GitHub token. |
| `docker inspect`: `User=""` (root), `ReadonlyRootfs=false`, `CapDrop=[]`, `NetworkMode=bridge` (unrestricted egress), `Memory=0`, `PidsLimit=nil` | Non-root, read-only rootfs, cap-drop ALL, limits, egress allowlist |
| Env names include `GITHUB_TOKEN`, passed with `-e` (`mcp_server_manager.py:846-847`) | No `-e K=V`. The value is readable by anyone with `docker inspect` (which means anything holding the Docker socket). |
| `RestartPolicy=unless-stopped` | It survives reboots, so it stays live even though `mcp_builder.enabled: false` in the live `config.yaml`. With the flag off, the UI can't turn it off: every `/api/mcp-studio` route returns 503. |
| Live `extensions/extensions_config.json` has `github-issue-connector` (sse → `host.docker.internal:18100`), next to a stdio server named `github` | Not in a reserved namespace. Its tools are tiered by the shared rules. |

The same class of problem (0.0.0.0) also applies to `omni-harness-session-watcher` (`0.0.0.0:18101`). Item C.0 owns that one.

**Recommended now, by the user:** run `docker rm -f omni-mcp-c641ac8dc68d` and rotate that GitHub token. The token sat in `docker inspect`, and its server was reachable from the LAN. This plan's startup reconcile (§9) also stops non-conforming built containers, but it should not be the first line of defence for a token that is already exposed.

**Update, reported by the coordinator (not re-observed by me):**
- the container `omni-mcp-c641ac8dc68d` is now **stopped**;
- the `github-issue-connector` config entry still points at `host.docker.internal:18100`;
- `mcp_servers` is **empty**;
- 21 orphaned `mcp_secrets` rows remain, across 12 server ids.

§9 plans their retirement.

### A worse finding than the user's list: the test phase can escape to the host today

In the daily stack the gateway runs in Docker (`docker/docker-compose-dev.yaml:182-240`) with these mounts:
- `/var/run/docker.sock`;
- `../backend/` read-write (uvicorn `--reload` watches it);
- `../config.yaml`;
- `~/.claude` and `~/.codex` (read-only).

The sandbox test runs the generated code as a **subprocess of the gateway, inside that container** (`mcp_server_manager.py:350-354, 389-393`, `command=sys.executable`). It runs with `HOME=Path.home()` (=`/root`, `:338`) and `PYTHONPATH` set to the gateway's site-packages. So the generated code can:
- read `/root/.claude` credentials, `/app/config.yaml`, `/app/backend/.omni-harness/dev_vault.key` and the SQLite DB. Together the key and the DB decrypt every stored secret.
- write into `/app/backend`, which gives code execution in the gateway on the next reload.
- talk to `/var/run/docker.sock`, for example over httpx's `uds=` transport, which the static scanner does not model. Through the socket it can `docker run -v /Users/<you>:/h`, which reaches `~/.ssh` on the Mac, because Docker Desktop shares `/Users` into its VM.

The only things in the way are the static and LLM scanners. The redesign makes containment structural: it no longer depends on the scanners catching anything.

**What this plan does not fix (stated plainly):** **code execution in the gateway is game over** for everything in this plan. The gateway holds:
- the vault key, so every built server's secrets;
- the Docker socket (`docker-compose-dev.yaml:206`), so root in the Docker VM and, through Docker Desktop's file sharing, the host's `/Users`;
- a read-write mount of `backend/` (`:187`), so persistence through `--reload`.

This plan's job is to keep generated code **out of** the gateway. Hardening the gateway's own mounts (a read-only backend mount in the daily stack, a socket proxy that only allows the `docker` verbs we use) is a separate item, and is recommended.

This plan also adds a startup check: the gateway refuses to enable MCP Build while `sandbox.allow_host_bash` is true. Host bash would give the agent, and so prompt-injected content, the same reach as generated code (live `config.yaml` has it false, observed).

---

## 1. Sandbox: a container for the test phase too

### Current behaviour
- `mcp_server_manager.py:332-393`: test discovery and test calls run `sys.executable server.py` as a subprocess. The env is `PYTHONPATH`=the gateway's site-packages, `HOME=str(Path.home())` (`:338`), and `PATH`. There is no filesystem, network, user or resource isolation.
- `mcp_build_tool.py:27-28`: the agent is told the pipeline "verifies required secrets are stored, starts the server in an isolated subprocess". Both claims are false: secrets are informational (`mcp_server_manager.py:495-499`), and the subprocess is not isolated. (The user cited `:27`. The word "isolated" is on `:28`; `:27` carries the other false claim.)
- Deploy patches the source (`_patch_main_for_sse`, `:147-153, :798`), so **the code that runs is not the code that was reviewed**.

### Design
1. **One runtime image, built from our Dockerfile:** `omni-mcp-runtime:<version>`, in a new file `docker/mcp-runtime/Dockerfile`.
   - Base: `python:3.12-slim`, pinned by digest (`python@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9`, already in the local image store, arm64).
   - **Packages, without a pip download (revision 4).** The user allowed only the Alpine and Squid download. So `mcp`, `httpx` and their dependency closure are **copied from the gateway's own installed environment**, which `uv` installed from `uv.lock` with hashes.
     - Every copied file is checked against its distribution's `RECORD` sha256 as the build context is assembled. A mismatch refuses the build.
     - Where the files come from:
       - a gateway running in Docker (Linux) uses its own `sys.prefix`;
       - anywhere else (a bare-host gateway on macOS, or the tests) uses a throwaway, labelled, `--rm`, `--network none` container of the configured packages-source image (`OMNI_MCP_RUNTIME_PACKAGES_IMAGE`, default `omni-harness-dev-gateway:latest`), which writes the tar to stdout.
       - A platform or Python-version mismatch refuses, visibly.
     - The image labels record the package versions.
   - User: `app` (uid 10001), with no shell login and no sudo.
   - A launcher, `/opt/omni/launch.py`. It imports `/app/server.py` as a module, finds its `FastMCP` instance, and runs it with stdio or SSE, chosen by `MCP_TRANSPORT`. The generated code is **never rewritten**: `_patch_main_for_sse` and `_DOCKER_MAIN_NEW` are deleted.
   - The gateway builds this image once, from a tar context it streams to the Docker daemon. Nothing runs `pip`, and the build uses `--network none`.
   - Probed on Docker 29.5.3 (2026-10-20): the classic builder accepts `FROM sha256:<local image ID>`. BuildKit **tried to resolve it on docker.io** and failed. So MED 6 is real, and the classic builder is what we use.
2. **One image per code hash:** `omni-mcp-built:<full 64-hex sha256>`. Tags are never truncated.
   - **The build:** `DOCKER_BUILDKIT=0 docker build --pull=false --network none -t omni-mcp-built:<sha> -`. The classic builder on the local daemon uses images already in the local store; a BuildKit `docker-container` driver could otherwise resolve `FROM` remotely. The tar context holds only:
     `FROM sha256:<runtime image ID>` / `COPY server.py /app/server.py` / `LABEL omni.code_sha256=<sha> omni.runtime_id=<runtime ID>`.
     `FROM <name>@<image-id>` is not valid syntax (`@` takes a registry digest). The classic builder accepts a bare local image ID.
     If the classic builder is removed in a future Docker, the fallback is `docker buildx build --builder default` (the `docker` driver), still with `--pull=false`.
   - **Before each build:** `docker image inspect omni-mcp-runtime:<version>` must return the expected image ID **and** the label `omni.runtime_version=<version>`. The expected ID is recorded when the gateway built the runtime image. If they don't match, the build refuses: someone retagged it.
   - **After the build:** `docker image inspect omni-mcp-built:<sha>` gives the **image ID**, and its `omni.code_sha256` label must equal `<sha>`. `docker run` then uses that exact `sha256:<image ID>`, never the tag, so a retag between inspect and run can't swap the code.
   - There is no `RUN`, so the generated code never executes during the build. The test phase and the deploy phase run **the same image ID**. That ID's label is the hash the approval is bound to (§3).
3. **The test phase** runs that image, and the MCP stdio client spawns `docker` as its command:
   `StdioServerParameters(command="docker", args=[...])`. That works because the gateway image already ships the Docker CLI (`backend/Dockerfile:65,86`). Code is delivered by the image, never by a bind mount.
4. `HOME=Path.home()` and the gateway's `PYTHONPATH` are removed. Inside the container, `HOME=/tmp` (a tmpfs).
5. Test calls now have no network, so a tool that calls its API fails with a connection error. A new badge type, `offline` ("expected in the sandbox: no network during tests"), is added in `_classify_output`. Like `auth` and `args`, it never blocks `verified`.
6. **The tool description** changes in two commits:
   - first commit: an honest interim text ("runs as a subprocess of the gateway; NOT isolated").
   - the commit that makes it true: the real text ("runs in a locked container with no network, no access to your files, and placeholder keys").
   The "verifies required secrets are stored" claim is removed in the first commit.

### Exact `docker run` flags: test phase (discovery and test calls)
```
docker run --rm -i \
  --name omni-mcp-test-<id12>-<rand6> \
  --label omni.mcp.server=<server_id> --label omni.mcp.role=test \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --user 10001:10001 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 256m --memory-swap 256m \
  --pids-limit 64 \
  --cpus 0.5 \
  --ulimit nofile=256:256 \
  --stop-timeout 2 \
  --tmpfs /run/omni:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid=10001,gid=10001 \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e MCP_TRANSPORT=stdio \
  sha256:<built image ID> \
  python -I -B /opt/omni/launch.py
```
There is no `-v` or `--mount` of any kind, no `-p`, no Docker socket and no `--privileged`. **No env-file:** the placeholders are delivered the same way as real secrets (§4 Secrets), through `docker exec` into `/run/omni`, and the launcher waits for them. The 30 s discovery timeout and the 10 s per-call timeout stay. On a timeout the gateway runs `docker kill` on the named container: closing the pipe alone does not stop it.

---

## 2. Vault key out of `config.yaml`

### Current behaviour
- `mcp_builder_config.py:11-14` reads `vault_key` from `config.yaml`, and `mcp_secrets.py:46-47` uses it directly.
- In dev mode the fallback key is `.omni-harness/dev_vault.key` (`mcp_secrets.py:54-70`). That path is relative to cwd, so it lands at `backend/.omni-harness/dev_vault.key`.
  - The live file is `-rw-r--r--` (0644, observed).
  - It sits inside `backend/`, which is bind-mounted **read-write** into the gateway (and so is reachable by the in-gateway test subprocess).
  - The SQLite DB holding the ciphertexts is in the same directory.
- `config.yaml` is mounted into the gateway (`:/app/config.yaml`).

### Choice: a 0600 file outside every mount that generated code or agent sandboxes see. Not the macOS Keychain.
The Keychain is reachable only from a macOS process. The gateway runs in Docker Desktop's Linux VM, so it cannot call `security`/Keychain APIs, and any bridge (a host helper serving the key over a socket) would be a new privileged surface to secure. A file works the same way in both modes: the Docker stack and `make dev` on the bare host.

- **Host path:** `~/.omni-harness-secrets/mcp_vault.key`, mode 0600, in a directory with mode 0700. It is created by `make vault-key`, a new target that refuses to overwrite an existing key.
- **Into the gateway only:** a compose `secrets:` entry (file source), which appears at `/run/secrets/mcp_vault_key`, read-only. No other service gets it.
  - `/run/secrets` is not under `backend/`, `/app`, the skills dir or the threads dir. That keeps it out of `LocalSandboxProvider`'s path mappings, and the agent's `read_file` can't reach it.
- **Bare-host mode:** read the same file through the `OMNI_HARNESS_MCP_VAULT_KEY_FILE` env var.
- **Generated code can never read it.** Under §1 and §4, generated code runs only in containers that have no mounts at all, so this is structural. The escape test (§T1) also tries both the old and the new paths.
- **Startup refusals.** The vault refuses to start, and says why, if:
  - `config.yaml` still has `mcp_builder.vault_key` (the message names the migration command);
  - the key file's mode is wider than 0600;
  - the key file sits under the project root or `OMNI_HARNESS_HOME`.
  The dev-mode ephemeral and `dev_vault.key` fallback is deleted.
- **Migration (`make vault-key-migrate`):**
  1. It generates a new key.
  2. It re-encrypts every `mcp_secrets` row with `MultiFernet([new, old]).rotate()`.
  3. It writes the new key file, deletes the old `dev_vault.key`, and removes `vault_key` from `config.yaml`.
  4. It runs `VACUUM` on the database (SQLite; on Postgres, `VACUUM FULL mcp_secrets`) so that pages holding the old ciphertexts are rewritten, not just unlinked.

  **Rotation is the control, not deletion.** Overwriting a file on APFS (copy-on-write, snapshots, SSD wear-levelling) does not erase its old blocks, so the plan doesn't claim "shredded". After rotation, an old copy of the key decrypts nothing that is still stored. Any copy of an old DB file in a backup or snapshot is still decryptable with the old key; the plan says so in the migration's output.

---

## 3. Approval bound to a code hash

### Current behaviour
- `approved` is a bare boolean (`persistence/mcp_server/model.py`). `McpServerRepository.update_source_code` (`sql.py:133-142`) replaces the source and **leaves `approved` alone**. So code the agent submits after approval is deployed with real credentials and no fresh review (the `mcp_build` tool → `submit_source_and_test` → `update_source_code`).
- `/enable` (`mcp_studio.py:359-365`) calls `manager.approve()`, which sets approved=True in the DB (`mcp_server_manager.py:605`), and then `deploy()`.
  - A `ValueError` from `deploy` returns 400 with approved left True.
  - `deploy` returns before Docker runs (`:761-771`). Any build or run failure in `_run_docker_deploy` (`:816-818, :851-853, :883-885`) also leaves approved=True.
- The legacy `POST /servers/{id}/approve` (`mcp_studio.py:625-641`) approves with no hash, no code view and no tiers. The old detail page calls it right before `/deploy` (`mcp-server-detail.tsx:2443`). `/register` and `/deploy` trust the same boolean.
- The UI: "View code" (`build-view.tsx:351`) is a link to another page, and "Approve and turn on" (`:385-391`) works without it. No hash or outbound hosts are shown anywhere.

### Design
- **New columns**, added through the existing `_run_additive_migrations` list (`persistence/engine.py:174`). `mcp_servers` is made by `create_all`; no alembic revision covers it.
  - `approved_code_sha256 VARCHAR(64) NULL`
  - `approval JSON NULL`. It holds `{code_sha256, egress_hosts, tool_tiers: {tool: 1|2|3}, runtime_image_id, approved_by, approved_at}`.
  - `pending_approval JSON NULL`, used while turning on.
- **`approved` becomes derived and is never stored as truth:**
  `approved = approval is not None and approval.code_sha256 == sha256(source_code) and approval.egress_hosts == egress_hosts`.
  The legacy boolean column is ignored, and existing rows read as **not approved**, so the live server needs re-approval. Two layers back this:
  - `update_source_code` (and any egress change) also sets `approved_code_sha256`/`approval` to NULL in the same transaction, so the change is explicit too;
  - the comparison is re-done at every use, so a missed clear can't approve new code.
- **Where `egress_hosts` comes from (today `[]`, `mcp_studio.py:328`; client-supplied at `:418`):** it is **recomputed from the hashed source only**, at test time. That means the same `_extract_egress_hosts` URL-literal scan, run on the same bytes that were hashed, and persisted together with the hash. `POST /servers` no longer accepts `egress_hosts` from the client.
  - A host the code builds at run time (concatenation, config) is not on the list, so the proxy refuses it and the refusal shows in the blocked log. That is visible, and fails closed.
  - The approval binds the list, so the hosts the user saw are exactly the hosts enforced.
- **Hash:** SHA-256 of the exact UTF-8 bytes of `server.py` as stored. That is also what the image contains, since nothing patches it any more (§1). It is shown as `sha256:` plus the full hex, with the first 12 characters prominent and a copy button.
- **Approval packet:** `GET /servers/{id}/approval`. It returns:
  - the full code and its hash;
  - the outbound hosts that will be enforced (§4);
  - the tools discovered, each with its proposed tier (always 3, §5);
  - the secret names it will receive;
  - a **view token**: a random value bound to (server, user, hash), lasting 15 min, single-use, held in memory.
  The token is how "the code was viewed" becomes something the server observed, rather than a UI promise.
- **`POST /servers/{id}/enable`**, body `{code_sha256, view_token, tool_tiers}`. It refuses with 409 and a reason when:
  - the hash doesn't match the current source;
  - the token is missing, expired or for another hash;
  - the phase isn't `verified`;
  - a tool tier is outside 1-3 or names an unknown tool.
  It writes `pending_approval` only. The background deploy task:
  - **commits** `approval` after the container is up and its tools are listed through the sidecar;
  - on any failure, clears `pending_approval` and leaves the server not approved, with the step that failed shown ("Couldn't turn on: …; approve again to retry");
  - if the gateway restarts mid-deploy, finds a `pending_approval` with no container, and it reads as not approved.
- **The deploy re-checks at `docker run` time (closing the enable→deploy race).**
  - `/enable` stores `pending_approval.code_sha256 = H`. The deploy task builds from the source bytes it read, whose hash must be H.
  - Immediately before `docker run`, under the per-server lock that `submit_source_and_test` also takes, it re-reads the row and requires all four to agree: sha256(current source) == H == the image's `omni.code_sha256` label == the hash the image ID was built for.
  - It then runs the exact image ID.
  - Any mismatch refuses, clears `pending_approval`, and leaves the server not approved ("The code changed while turning on; review it again").
  - `update_source_code` also clears `pending_approval`.
- **Legacy routes:**
  - `POST /servers/{id}/approve` and `/register` are **removed**: one approval path, nothing to bypass.
  - `/deploy` becomes "turn back on". It needs a derived-approved server and re-uses the approved image.
  - `/connect` is no longer a route; only the deploy task calls it.
  - The old detail page's "Approve and deploy" button opens the new approval screen.
- **If the agent changes code while the server is on:** the running container keeps running the **approved** image, because it is hash-bound. The card says "New code is waiting for your approval; the approved version is still on" (answered: Q3). Until the new hash is approved:
- the new code gets **placeholders only**: test runs never get real values (§1);
- the vault's decrypt-for-deploy refuses any hash that isn't the approved one (§4);
- `/deploy` refuses the new code (T19).

### UI: the approval screen (in `build-view.tsx`, Graphite components)
- A dialog opened by "Review and approve", replacing the direct "Approve and turn on". It has a focus trap, closes on Esc and returns focus, and its tabs are a real tablist:
  1. **Code** (opened first): the full `server.py` in JetBrains Mono with line numbers and the full hash. Viewing it fetches the packet, which issues the token.
  2. **Outbound hosts**: the enforced allowlist, one host per row, port 443. "None: this tool can't reach the internet" when it's empty.
  3. **Tools and tiers**: every tool with a Tier 1/2/3 control, all **defaulting to 3**, each with a one-line meaning ("asks every time").
  4. Secrets it will receive (names only).
- **Approve and turn on** is disabled until the Code tab has been shown (a token is held). The note "Open the code first" is wired up with `aria-describedby`. It is the only solid button on the screen.
- If the hash changes while the dialog is open (polling detects it), the dialog shows "The code changed since you opened it" and fetches a fresh packet.

---

## 4. Egress enforced, 127.0.0.1 only, secrets via env-file

### Current behaviour
- `build_egress_rules(egress_hosts)` is called and its return value **discarded** (`mcp_server_manager.py:532`). The deployed container runs on the default bridge with unrestricted egress (`:835-848`).
- `egress_hosts` comes from URL literals (`:504-505`) and is never persisted. The row keeps `[]` (`mcp_studio.py:328`).
- `-p {host_port}:8080` binds all interfaces (`:841-842`), so the live container is on `0.0.0.0:18100`. `_find_free_port` probes `""` (`:707`).
- Secrets go in as `-e K=V` on argv (`:846-847`).
- Deleting a server calls `manager.stop()` (`mcp_studio.py:810`), which only updates a status (`:650-667`). **The container keeps running, with its secrets, and its `extensions_config` entry stays.**

### Choice: an `--internal` network per server, plus a **Squid** egress sidecar (with dnsmasq in front of its DNS)
Revision 3 (the user's instruction): **we do not write our own proxy.** The sidecar runs Squid, a proven proxy, from a pinned image. Our code is limited to:
- a pure Python function in the gateway that **renders** the Squid and dnsmasq configs (unit-tested);
- a short POSIX `sh` entrypoint that writes those configs to tmpfs and starts the two daemons.

How it works:
- **The built server** is attached **only** to `omni-mcp-net-<id12>`. That network is created `--internal` (no route off it) with a `/28` subnet the gateway allocates. The server gets the fixed address `.3`.
- **Its only neighbour is the sidecar** `omni-mcp-egress-<id12>`, at the fixed address `.2` on the internal network, and also attached to an outer network (below).
- **Squid** does two jobs, each on its own `http_port`, bound to one network's address only:
  1. a **forward proxy**, `http_port <internal .2>:3128`, that only accepts `CONNECT` to allowlisted hosts on port 443, and needs a login. The ACLs are below.
     - The server reaches it as `HTTPS_PROXY=http://mcp:<proxy password>@<internal .2>:3128`. It uses the literal IP, so no DNS is needed. `httpx` honours this, including the login.
     - The **login** (`auth_param basic`, with an `htpasswd` hash rendered from a per-server random password) is defence in depth: only the server can reach this port in the first place.
  2. a **reverse proxy in front of the endpoint**, `http_port <outer IP>:8080 accel`. It forwards to `cache_peer <internal .3> 8080 originserver`, but only when the request carries the per-server bearer token (`acl inbound_token req_header Authorization ^Bearer\ <token>$`; the token is hex, so it is safe inside a regex). Anything without it gets 403. This is the endpoint's login.
     - **The token is never written to `extensions_config.json`.** The entry carries `server_id` and `"auth": "built-server-token"`, and no secret.
     - The token is stored in the vault as `__INBOUND_TOKEN`. That name is reserved and never handed to the server container.
     - At tool-load time, `omniharness/mcp/tools.py` asks a token provider for it. The gateway lifespan registers that provider. The provider adds the `Authorization` header to the in-memory server params only.
- **dnsmasq**, inside the sidecar on `127.0.0.1:53`, is **Squid's only resolver** (`dns_nameservers 127.0.0.1`).
  - It runs with `--stop-dns-rebind`, which **drops any upstream answer in a private, loopback or link-local range before Squid ever sees it**. That closes DNS rebinding by construction, however fast an answer flips.
  - It also runs with `--no-hosts --no-resolv --server=127.0.0.11` (Docker's embedded DNS) and `--cache-size=0`.
  - Port 53 binds without a capability via `--sysctl net.ipv4.ip_unprivileged_port_start=53`, so `--cap-drop ALL` still holds.
- **Code that ignores the proxy** (raw sockets, its own DNS) **has no route at all**. Enforcement comes from the network topology; the code doesn't have to cooperate.

**The forward-proxy ACLs, rendered into `squid.conf`.** Order matters: the first match wins.
```
acl fwd myportname fwd                      # http_port <internal .2>:3128 name=fwd ssl-bump tls-cert=/tmp/never-presented.pem
acl inbound myportname inbound              # http_port <outer ip>:8080 name=inbound accel defaultsite=mcp no-vhost
acl CONNECT method CONNECT
acl tls_port port 443
acl allowed dstdomain -n <A-label hosts, from build_egress_rules>      # -n: never reverse-resolve
acl ip_literal dstdom_regex -n ^[0-9.]+$ ^\[ ^[0-9a-f:]+$ ^0x
acl private_dst dst 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 \
                    192.0.0.0/24 192.168.0.0/16 198.18.0.0/15 224.0.0.0/3 ::/128 ::1 ::ffff:0:0/96 \
                    64:ff9b::/96 fc00::/7 fe80::/10 ff00::/8
acl mcp_login proxy_auth REQUIRED
acl inbound_token req_header Authorization ^Bearer\ <hex token>$
http_access deny fwd !CONNECT               # no plain-HTTP forwarding at all
http_access deny fwd !tls_port              # HTTPS 443 only (answered: Q2)
http_access deny fwd ip_literal
http_access deny fwd !allowed
http_access deny fwd private_dst            # evaluated on the RESOLVED addresses; any private answer denies
http_access allow fwd mcp_login
http_access allow inbound inbound_token
http_access deny all
acl step1 at_step SslBump1
acl sni_ok ssl::server_name --client-requested -n <same hosts>
ssl_bump peek step1                         # read the ClientHello only
ssl_bump splice sni_ok                      # SNI the client sent must be on the allowlist
ssl_bump terminate all                      # missing or other SNI: closed; TLS is never decrypted
on_unsupported_protocol respond all         # non-TLS bytes in a tunnel: refused, never tunnelled
cache deny all
via off
forwarded_for delete
httpd_suppress_version_string on
dns_nameservers 127.0.0.1
cache_peer <internal .3> parent 8080 0 no-query originserver name=mcp
cache_peer_access mcp allow inbound inbound_token
cache_peer_access mcp deny all
never_direct allow inbound
read_timeout 60 minutes                     # SSE streams stay open
```
Notes:
- `dns_v4_first` was removed in Squid 5, so it isn't used. `private_dst` lists the IPv6 ranges explicitly instead.
- `-n` on `dstdomain` stops Squid from reverse-resolving an IP literal to a name that might happen to be allowlisted.
- Squid strips one trailing dot from a hostname when it parses the URL.
- Squid has no IDNA support: a non-ASCII CONNECT host fails URL parsing and is refused. The renderer writes allowlist entries as A-labels only, and refuses wildcards, IPs or ports in the allowlist.
- The renderer refuses to output a config missing any directive above. A unit test checks that.

**Why Squid, not Envoy:**

| Need | Squid 6 | Envoy (dynamic forward proxy) |
|---|---|---|
| CONNECT allowlist by host, 443 only | `dstdomain` + `port` ACLs: mature and one line each | Route/RBAC match on `:authority`: workable |
| SNI check inside the CONNECT tunnel | `ssl_bump peek` + `ssl::server_name --client-requested`, without decrypting | The tunnel's TLS is opaque to the HTTP connection manager; it needs an internal listener with `tls_inspector`. Complex. |
| Refusing private destinations **after** resolution | `dst` ACL on resolved addresses: any private answer denies | No built-in filter on resolved IPs in the DFP DNS cache; it needs a Lua or ext_authz filter, which would be our own code again |
| DNS rebinding | dnsmasq `--stop-dns-rebind` as the only resolver, plus `dst` | It would need the same dnsmasq trick, plus a filter |
| Image and pinning | Our image: `alpine@sha256:<digest>` + `apk add squid=<6.x pinned> dnsmasq=<pinned> openssl=<pinned>`, about 25 MB. The image ID is recorded at build, and the build checks that `squid -v` lists `--with-openssl`. | Official `envoyproxy/envoy@sha256:…` (distroless), about 60-150 MB. Pinnable. |
| Config reload | `squid -k reconfigure`. Not needed: the config is fixed per approval, so a change means a new sidecar. | xDS or hot restart. More moving parts. |

Squid wins on the two properties that matter most here: the SNI check and refusal by resolved IP. Both are built in, so neither needs code of ours. Envoy would need custom filters for both.

**Each listener is bound to one network's address only:**
- The internal side is fixed (`.2`, from the allocated `/28`).
- The sidecar is created (`docker create`) on the outer network, connected to the internal network with `--ip <.2>`, then started.
- The entrypoint finds its one address inside `OUTER_SUBNET`, which the gateway passes from `docker network inspect`, and writes it into `http_port`. If it doesn't find exactly one, the entrypoint refuses to start.
- So the forward proxy is unreachable from the gateway's network, and the endpoint is unreachable from the server's own network.
- "Outer network" means the gateway's compose network (Docker gateway). For a bare-host gateway it is a dedicated non-internal bridge, `omni-mcp-pub-<id12>`, the only network the `127.0.0.1` publish attaches to.
- Squid's own outbound traffic leaves through the outer network's route.

**Residual risk, stated, and the CDN-fronting part ACCEPTED by the user (2026-10-20):** the allowlist bounds **where** traffic goes, not **what** it carries.
- **Updated (2026-10-20, the user's addition): CDN fronting is now possible only through a deliberate SNI/Host-header mismatch on the same CDN.** The SNI must equal the CONNECT host, and a connection without SNI is refused. The inner HTTP `Host` header is not inspected, because TLS is never decrypted.
- Code allowed to reach `api.github.com` can still exfiltrate through that API (gist, issue body), using whatever token it holds.
- The SNI check requires the SNI to be **on the allowlist**, not equal to the CONNECT host. With two allowlisted hosts on the same CDN, one can be fronted through the other.
- A mismatched HTTP `Host` header inside TLS can't be seen at all.
- Mitigations are the user's review of the code and hosts, plus Tier 3 by default. The proxy does not prevent this.

Why this topology, on Docker Desktop for Mac:
- `--internal` networks and multi-network containers work unchanged in Docker Desktop's VM. They need no `NET_ADMIN` and no host changes.
- The alternative, iptables in a sidecar, has three problems:
  - it needs `NET_ADMIN`;
  - it allowlists by IP, which breaks on CDN-fronted APIs;
  - Docker Desktop's VM iptables are not ours to manage.
- Docker Desktop's network policies (Enhanced Container Isolation) are a paid Business feature, so we can't rely on them.

**DNS for the server.** The server gets `--dns 127.0.0.1`, where nothing listens. It needs no names, since its proxy is a literal IP. T13 checks that external names don't resolve inside it.

**Ports.** `build_egress_rules` drops port 80 and allows HTTPS (443) only (answered: Q2). Its output feeds the renderer. The function is no longer computed and thrown away, and the wiring gate covers it.

**Reachability:**
- Gateway in Docker (the daily stack): the sidecar's outer network is the gateway's compose network (`OMNI_HARNESS_MCP_GATEWAY_NETWORK`: `omni-harness-dev` / `omni-harness`). URL: `http://omni-mcp-egress-<id12>:8080/sse`. **No host port is published.**
- Gateway on the bare host (`make dev`): the sidecar publishes `-p 127.0.0.1:<port>:8080` on `omni-mcp-pub-<id12>`. It is the only publish.
- `_find_free_port` probes `127.0.0.1`.
- `connect()` writes through `atomic_write_json` (`extensions_config.py:23`), not `open(..., "w")` (`mcp_server_manager.py:964`).

**Secrets (revision 4): never in environment variables, never in `docker inspect`.**
- **Nothing secret goes in `-e` or `--env-file`**, for the built server or the sidecar. That covers the stored keys, the placeholders, the proxy login and the endpoint token. The env-file design is dropped.
- **Delivery.** Each container gets `--tmpfs /run/omni:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid=<its uid>,gid=<its gid>`. After the container starts, the gateway delivers each file over **stdin** with:
  `docker exec -i -u <uid> <container> sh -c 'umask 0377 && cat > /run/omni/<name>'`
  where `<name>` comes from a fixed set (`secrets`, `squid.conf`, `dnsmasq.conf`, `passwd`). It then runs `touch /run/omni/ready && chmod 0500 /run/omni`.
  - Each file is **mode 0400, owned by the container's non-root user**, on a tmpfs, so it lives only in memory.
  - The values travel on stdin, so they are not in the container config and not in any exec's recorded command.
- **"Read-only", honestly.** A truly read-only tmpfs needs either a remount (`CAP_SYS_ADMIN`) or a host bind mount, and both are ruled out. What we have instead: the file is 0400 and its directory 0500, both owned by the container's own non-root user. The only thing that could change them is the code the file is for.
- **The containers read them at startup:**
  - the launcher waits for `/run/omni/ready` (up to 30 s), reads `/run/omni/secrets` (`KEY=VALUE` lines) into its **own process's** `os.environ` (which `docker inspect` never sees), then imports the server;
  - the sidecar's entrypoint waits for `ready`, then runs Squid and dnsmasq against the delivered configs.
- **After a restart.** tmpfs content is lost when a container restarts, so a container brought back by `--restart` (for example after Docker Desktop restarts) waits for its files.
  - The gateway re-delivers them on its startup reconcile, and whenever a built server fails to load its tools.
  - Until then the server isn't usable, and the board shows "Waiting for the gateway to hand over its keys".
- **File-format validation**, kept from the env-file design. One bad key or value refuses the whole deploy, naming the key but never the value.
  - Each key must match `^[A-Z][A-Z0-9_]{0,63}$`.
  - Reserved names are refused:
    - `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `ALL_PROXY` (and their lower-case forms);
    - `HOME`, `PATH`;
    - `MCP_*`, `PYTHON*`, `LD_*`, `SSL_*`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`;
    - anything starting with `__`.
  - Each value must not contain `\n`, `\r` or NUL.
  - `PUT /secrets` applies the same key rules.
- **The proxy setting is not a secret, but its password is.** The server's `HTTPS_PROXY=http://mcp:<pw>@<.2>:3128` is written by the gateway into the secrets **file**, not into `-e`. Only the gateway's deploy code writes proxy variables.
- **Real secrets go only to an approved image.** The vault's decrypt-for-deploy takes the approved sha256 and refuses unless the server's derived approval is for exactly that hash (answered: Q3). The test phase only ever gets placeholders (§1).
- **Test (T20):** `docker inspect` of a running built server **and** its sidecar contains no secret value: no stored key, proxy password or endpoint token, also searched for in base64. The sabotage passes one secret with `-e`, and the test turns red.
- **Residual:** anyone holding the Docker socket can still `docker exec` and read `/run/omni`. That is the gateway, which already holds the vault key, and the user.

### Exact `docker` commands: deploy phase
```
docker network create --internal --subnet <allocated /28> --label omni.mcp.server=<server_id> omni-mcp-net-<id12>
# bare-host gateway only: the outer network that carries the 127.0.0.1 publish
docker network create --label omni.mcp.server=<server_id> omni-mcp-pub-<id12>
# OUTER = $OMNI_HARNESS_MCP_GATEWAY_NETWORK (Docker gateway) or omni-mcp-pub-<id12> (bare host)

# 1. the built server: no -p, no mounts, internal network only, fixed address .3
docker run -d --name omni-mcp-<id12> \
  --label omni.mcp.server=<server_id> --label omni.mcp.role=server \
  --label omni.code_sha256=<full sha> \
  --network omni-mcp-net-<id12> --ip <.3> --dns 127.0.0.1 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges \
  --memory 256m --memory-swap 256m --pids-limit 64 --cpus 0.5 --ulimit nofile=512:512 \
  --restart unless-stopped \
  --tmpfs /run/omni:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid=10001,gid=10001 \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e MCP_TRANSPORT=sse -e MCP_PORT=8080 \
  sha256:<built image ID, label verified == approved sha> python -I -B /opt/omni/launch.py

# 2. the Squid sidecar: created on OUTER, connected to the internal network at .2, THEN started
docker create --name omni-mcp-egress-<id12> \
  --label omni.mcp.server=<server_id> --label omni.mcp.role=egress \
  --network $OUTER \
  --read-only --tmpfs /tmp:rw,nosuid,nodev,size=16m \
  --user <squid uid>:<squid gid> --cap-drop ALL --security-opt no-new-privileges \
  --sysctl net.ipv4.ip_unprivileged_port_start=53 \
  --memory 128m --memory-swap 128m --pids-limit 64 --cpus 0.5 \
  --restart unless-stopped \
  --tmpfs /run/omni:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid=<squid uid>,gid=<squid gid> \
  -e OUTER_SUBNET=<cidr>                       # not a secret
  [-p 127.0.0.1:<port>:8080]                   # bare-host gateway only
  sha256:<omni-mcp-egress image ID>            # entrypoint: decode configs to /tmp, bind by subnet, dnsmasq, then exec squid -N
docker network connect --ip <.2> omni-mcp-net-<id12> omni-mcp-egress-<id12>
docker start omni-mcp-egress-<id12>

# 3. hand over the files (values on stdin only), for the sidecar and then the server
docker exec -i -u <uid> <container> sh -c 'umask 0377 && cat > /run/omni/<name>'   # once per file
docker exec -u <uid> <container> sh -c 'touch /run/omni/ready && chmod 0500 /run/omni'
```
**Undeploy, delete and stop** remove both containers, the networks and the `extensions_config` entry. The separate hotfix makes stop and delete remove containers and secrets from now on (§8 step 11 builds on it).

---

## 5. Names: the reserved namespace, collision refusal, Tier 3 until set

### Current behaviour
- The name is a slug of the description (`mcp_build_flow.py:114-119`). Nothing checks it against existing servers.
- `connect()` writes `config_data["mcpServers"][server_name] = {...}` (`mcp_server_manager.py:958`), so a built server named `github` or `session-watcher` **silently replaces** the real one.
- MCP tools are named `<server>_<tool>` (`omniharness/mcp/tools.py:125`, `tool_name_prefix=True`), and the tier classifier matches those names against the shared rules (`app/policy/classify.py:36-46`). So:
  - a built server named `github` with a tool `get_issue` would be **Tier 1** through `github_get_issue` (`default_rules.yaml:214`);
  - one named `session-watcher` would get Tier 1 for every tool through `session-watcher_*` (`:38`);
  - `filesystem` would pick up `filesystem_read*`.

### Design
- **Display name `built/<slug>`. Wire key `built__<slug>`.** Provider tool-name rules (`^[a-zA-Z0-9_-]{1,64}$`) forbid `/` in the prefixed tool name, so the slug is capped so that `built__<slug>_<tool>` stays within 64 characters.
- **Slugs are `[a-z0-9-]` only, with no underscore,** and every entry point goes through one slug function.
  - Today `POST /servers` stores `body.name` raw (`mcp_studio.py:414`), so it can contain `_`. That made `built__a_b_c` ambiguous between server `a` / tool `b_c` and server `a_b` / tool `c`.
  - With no `_` in the slug, the first `_` after `built__` always ends the server part, so a prefixed tool name parses one way only.
- **Tool names go through one normaliser.** The separate branch `007-policy-tool-names` is adding a single tool-name normaliser for the policy layer (not yet pushed when this was written). This plan uses that normaliser for:
  - the collision checks;
  - the `classify()` branch;
  - the `built_tiers` lookup.
  It adds no second normaliser. If 007 has not merged when step 6 starts, step 6 waits for it, or takes its normaliser as-is and leaves the merge to 007.
- **Collision refusal**, at `POST /builds` and `POST /servers`, and again in `connect()`. Comparison goes through the normaliser (case-folded, `-` and `_` treated alike). It refuses (409, with the conflicting name) when:
  - the slug equals any existing `extensions_config` key (`github`, `filesystem`, `postgres`, `session-watcher`, Composio connectors…), with or without the `built__` prefix. So `GitHub`, `git_hub` and `git-hub` all collide with `github`;
  - the slug equals another built server's slug;
  - at connect time, any of the server's **fully prefixed** tool names (`built__<slug>_<tool>`, normalised) is already registered by another loaded server. That covers prefix overlap such as server `git` exposing a tool `hub_x` while a server `git-hub` exists.
  `connect()` never overwrites a key it does not own: it refuses if the key exists and is not tagged with this `server_id`.
- **The prefix is reserved.**
  - The `extensions_config` loader skips any `built__*` entry that doesn't carry a `server_id` with a derived-approved row, and reports it as a failing source (visible, never silent).
  - `POST /api/mcp/config` refuses to add a `built__*` key by hand.
- **Built tools never match the shared rules.** `classify()` gets a first branch: for a name starting with `built__`, the rules are **not consulted**. The tier is looked up in `built_tiers[(server_id, tool)]`, keyed by the server's **id** (resolved from the wire key through the `server_id` tag on its config entry), never by the name alone. It comes from the approval record bound to the current hash, and is **3 when absent**. So:
  - a user rule `*` (Tier 1) can't reach a built tool;
  - neither can any future glob;
  - a re-approval after a code change starts from Tier 3 again for any new tool.
  The ruleset gains a read-only `built_tiers` map, which the gateway refreshes when an approval commits. `explain.py` already calls `classify()`, so the inspector agrees.
- **Interaction with #53's grants:** Tier 3 always asks. A user who sets a built tool to Tier 2 gets "run, then disclose".

---

## 6. `extract_secrets` improvements

### Current behaviour (`mcp_build_flow.py:41-45`)
Probed with synthetic values against the current code:

| Input | Today |
|---|---|
| `https://alice:s3cr3tpw@api.example.com/v1` | **not lifted** |
| `postgres://bob:pa55@db.internal:5432/x` | **not lifted** |
| `Authorization: Bearer abc123.def` | **not lifted** |
| `my password is hunter2` | **not lifted** (under 8 chars) |
| `use pwd=letmein` | **not lifted** |
| `password: Tr0ub4dor&3x` | **partly lifted**: `{{secret:PASSWORD}}&3x` leaks a tail |
| `x-api-key: 12345678`, `token is ghp_short1` | lifted |

### Design
New patterns run **before** the existing ones:
1. **URL userinfo**, `scheme://user:pass@host`, for any scheme. The password is lifted as `<HOST>_PASSWORD`. The user is kept, because it is usually not secret (open to change).
2. **`Authorization: Bearer <token>`** and **`Basic <b64>`**: any length of 6 characters or more, up to whitespace or a quote. Lifted as `BEARER_TOKEN` / `BASIC_AUTH`.
3. **Short passwords after a password word** (`password|passwd|pwd|passcode|pin`, followed by `is`, `:` or `=`): any non-space run of 4 characters or more. It takes the **whole** non-space run, which fixes the partial lift.
4. `_WORDED` and `_NAMED` take the whole non-space token (except trailing punctuation `.,;)`), instead of a restricted character class.

Kept as-is: "token is required" and "password field" stay unlifted (a stop-word list plus a check that the value isn't a dictionary word for the `token` and `key` words). The `scrub()` side of the existing exact-match logic is unchanged. Round 2's item #55 adds base64- and URL-encoded variants for scrubbing; this plan adds the encoded form of URL userinfo only, because the URL pattern needs it.

---

## 7. Tests (each one sabotaged)

The Docker tests are marked `@pytest.mark.docker`. They run on the developer's Docker Desktop (answered: Q1), with throwaway resources only:
- every container is `--rm` and labelled `omni.mcp.test=<run id>`;
- names start with `omni-mcp-t-`;
- **no host mounts at all.** The fixture runs `docker inspect` on every container it starts and **fails the test** if `Mounts` is not empty.
- Cleanup runs in a fixture finalizer.
- **Every container, network and image the run created is listed in the test report.** The pytest terminal summary has a section with name, ID, image, created and removed times, and the observed `Mounts=[]`. The same list goes to `backend/test-results/docker-resources.json`, and the stop report quotes it.
- A leftover resource (not removed) is a test failure.
- Where Docker is unavailable, the tests **skip, and the skip is reported**. A skip is never reported as a pass.

The HTTP tests go through `create_app()` and its lifespan, as in `backend/tests/ledger/conftest.py`. The lifespan builds a `DockerRunner` port. The tests that don't need real Docker swap in a recording fake that captures argv and env-file contents; the Docker tests use the real one.

| # | Test | Through | Sabotage that must turn it red |
|---|---|---|---|
| T1 | **Escape: files.** The tool tries to read: `~/.ssh` (listing and `id_*`), `$HOME` listing, `/var/run/docker.sock`, `/app/config.yaml`, `/app/backend/.omni-harness/*`, `/run/secrets/mcp_vault_key`, `/root/.claude`, `/Users`. The test also writes a canary file into a temp dir and points the gateway's `HOME` at it. Every read must return missing. | Docker, `_run_server_sandbox_test` with the scanners **stubbed to allow** (containment must hold without them) | Add `-v {Path.home()}:/tmp/home:ro` and `HOME=/tmp/home` to the test argv: the canary is read. (A second sabotage reverts to the subprocess runner: the canary is read.) |
| T2 | **Escape: socket (test phase).** The fixture starts a TCP listener container `omni-mcp-t-listener` on an ordinary (non-internal) test bridge and records its **literal IP**. It also records the host gateway's literal IP, by resolving `host.docker.internal` in a throwaway bridge container. The tool connects to both **literal IPs** (no DNS involved), resolves `example.com`, and connects to `1.1.1.1:443`. All must fail, and the listener must log **no** connection. Needs no internet. | Docker, test phase | `--network none` → `bridge`: the listener logs a connection. |
| T3 | **Escape: privileges.** `os.getuid() != 0`; writing to `/app/server.py` raises EROFS; forking more than the pids limit fails. | Docker, test phase | Drop `--read-only`, then `--user`: each turns T3 red on its own assertion. |
| T4 | **Code changed after approval.** Build → test (fake runner) → `GET /approval` → `POST /enable {hash, token, tiers}` → deploy commits. The agent then submits new code through the `mcp_build` tool path. Expect: `GET /servers/{id}` shows `approved:false` and state awaiting approval; `POST /deploy` gives 409; `POST /enable` with the old hash gives 409; the deploy re-check refuses an image whose label ≠ current hash. | HTTP, `create_app()` | (a) Remove the clear in `update_source_code`, which is still red through the derived check; (b) make the derived check return the stored record without comparing hashes, which is red on a row written without a clear (direct DB write). One sabotage per layer. |
| T5 | **`/enable` with a failed deploy.** The fake runner returns rc=1 on `docker run`. Expect: not approved, state "Couldn't turn on", `pending_approval` cleared. Again with a gateway restart mid-deploy. | HTTP | Commit `approval` before the Docker work: red. |
| T6 | **View code before Approve.** `POST /enable` → 409 in each of these cases:<br>- no token;<br>- an expired token;<br>- a token for another hash;<br>- a token issued **to another user** (a second account through real HTTP, after C.0);<br>- a token issued for **another server**;<br>- a token **already used once**. Playwright: Approve is disabled until the Code tab is shown; the dialog shows the full hash, the hosts and all code lines. | HTTP + rendering spec | Server: skip the token check. UI: `{false && …}` around the disabled condition. Both red. |
| T7 | **Egress through the real Squid sidecar (deployed).** The production deploy path, unmodified, with allowlist `[allowed.test, api.github.com]`. The test-only fake resolver is a `omni-mcp-t-dns` container running dnsmasq, used as the sidecar's dnsmasq **upstream**. That is a renderer parameter which keeps `--stop-dns-rebind` on; T9 asserts production renders `127.0.0.11`. From inside the deployed server:<br>(1) `httpx.get("https://blocked.test")` → 403 (`ERR_ACCESS_DENIED`), listed in the server's blocked log;<br>(2) raw sockets to the T2 listener's **literal IP** and to the host gateway's **literal IP** fail, and the listener logs nothing. That proves **routing**;<br>(3) the fake resolver answers `allowed.test` with the **listener's gateway-network IP**. `CONNECT allowed.test:443` fails with `ERR_DNS_FAIL`, because dnsmasq dropped the private answer; the listener logs nothing;<br>(4) **rebinding:** the fake resolver alternates a public TEST-NET answer and the listener's IP, with TTL 0, over 50 attempts. The listener logs **no** connection;<br>(5) positive control: `HEAD https://api.github.com` (no credentials) succeeds. It is marked `internet`, and skipped **visibly** when offline. | Docker, deploy phase | (a) Render `allowed` as `.` (all domains): blocked.test succeeds. (b) Put the server on `bridge`: the literal-IP socket reaches the listener. (c) Drop `--stop-dns-rebind` from the renderer: case 3 becomes `ERR_ACCESS_DENIED` instead of `ERR_DNS_FAIL` (red on the asserted reason). Drop it **and** `deny fwd private_dst`: the listener receives a connection. |
| T7d | **Squid's resolved-address layer on its own.** The renderer is called **in the test** with `stop_dns_rebind=False`, so dnsmasq passes private answers. This parameter has no production caller; the wiring gate whitelists it as test-only, and T9 asserts the production config has `stop-dns-rebind`. The fake resolver answers `allowed.test` with `[public TEST-NET, listener IP]`. Expect `ERR_ACCESS_DENIED`, and the listener logs nothing. | Docker | Remove `http_access deny fwd private_dst`: the listener receives a connection. |
| T13 | **Deployed DNS.** Inside the deployed server, `socket.getaddrinfo("example.com", 443)` and a lookup of a random name both **fail**; the sidecar's own name still resolves. | Docker, deploy phase | Remove `--dns 127.0.0.1`: whether this goes red depends on the Docker version's internal-network DNS forwarding, so the test records which. If it stays green without the flag, the flag is kept anyway, and the report says it was unproven on this Docker version. |
| T14 | **Squid listeners bound per network; the endpoint's login.**<br>- From a test container on the **outer** network: `:3128` is refused (connection refused, not 407).<br>- `:8080` without the token → 403; with a wrong token → 403; with the right token, `tools/list` over SSE returns the server's tools, which also proves SSE streams through Squid's accel port.<br>- From inside the server, `:8080` on `.2` is refused.<br>- `:3128` without the proxy login → 407. | Docker, deploy phase | Render `http_port 3128` without an address: `:3128` reachable from outer. Drop `inbound_token` from the `http_access`/`cache_peer_access` lines: no-token gets through. Drop `mcp_login`: 407 becomes 200. |
| T15 | **Enable→deploy race.** The fake runner **blocks** inside `docker build` on an event. While it is held, the agent submits new code through the `mcp_build` path; then the event is released. Expect: no `docker run` is issued (argv log), `pending_approval` is cleared, the server is not approved, and the state reads "The code changed while turning on". Also: a retagged built image (the label doesn't match) makes the deploy refuse, and `docker run` is always given `sha256:<ID>`, never a tag. | HTTP, `create_app()` | Drop the under-lock re-read before `docker run`: a run is issued for the new code. Run by tag: the argv assertion goes red. |
| T16 | **Secrets-file safety** (revision 4: a file, no longer an env-file). Storing secret names `HTTPS_PROXY`, `ld_preload`, `MCP_PORT`, `__INBOUND_TOKEN`, or a value containing `\n` is refused at `PUT /secrets` and again at deploy. The recording runner sees the values **only** on `docker exec -i` stdin, never on any argv. Docker variant: the delivered `/run/omni/secrets` is mode 0400 and owned by uid 10001, and `/run/omni` is 0500. | HTTP + fake runner + Docker | Remove the reserved-name check: `HTTPS_PROXY` is stored. Write the file with umask 022: the mode assertion goes red. |
| T20 | **Nothing secret in `docker inspect`.** For a running built server and its sidecar, the full `docker inspect` JSON contains none of: the stored values, the proxy password, the endpoint token, or their base64 forms. | Docker | Pass one stored secret with `-e K=V`: red. |
| T8 | **The collision with `github`.** `extensions_config` has `github`. `POST /builds` for a description that slugs to `github` gives 409 naming it, and no row is created. `connect()` for a row whose key exists and isn't tagged with its id refuses, and the file is unchanged (byte compare). The same 409 for `GitHub`, `git_hub` and `git-hub`. A `POST /servers` body name containing `_` is slugged with no `_`. Prefix overlap: a built `git` server whose tool `hub_x` would produce a prefixed name already registered by another server is refused at connect. The classifier: with the shipped rules plus a user rule `*` → Tier 1, `built__github_get_issue` is **Tier 3**. After an approval sets `get_issue: 1` it is Tier 1, and it is Tier 3 again after a code change. Two built servers each with a tool `x`: a tier set on one doesn't apply to the other (tiers are keyed by `(server_id, tool)`). | HTTP + unit | (a) Remove the collision check: 201. (b) Remove the `built__` branch in `classify()`: Tier 1 from `*`. (c) Key `built_tiers` by tool name only: the second server inherits the tier. (d) Skip the normaliser in the collision check: `git_hub` is accepted. |
| T9 | **No secret on argv or in config; no 0.0.0.0.** Over the fake runner's recorded argv: no stored secret value appears; `extensions_config.json` contains no inbound token (byte search for the token); no `-p` on the server container; the sidecar's `-p` (bare-host mode only) starts with `127.0.0.1:`. Docker variant: `docker port` shows 127.0.0.1 only. The **production-rendered** configs (decoded from the recorded sidecar env-file) contain `stop-dns-rebind`, `server=127.0.0.11` and `deny fwd private_dst`, and the test-only renderer parameters are at their defaults. | HTTP (fake) + Docker | Re-add `-e K=V`: red. `"0.0.0.0:"` in `-p`: red. Make the deploy path pass `stop_dns_rebind=False`: red. |
| T10 | **Vault key.** Startup refuses when `config.yaml` has `mcp_builder.vault_key`, when the key file's mode is 0644, or when the file is under the project root; MCP Build also refuses to enable with `sandbox.allow_host_bash: true`. The migration re-encrypts, the old key decrypts **no** remaining row, the new key decrypts all of them, and `VACUUM` ran. | `create_app()` lifespan | Sabotaged **one check at a time**, each turning its own assertion red: (a) accept the config key; (b) skip the mode check; (c) skip the path check; (d) skip the host-bash check. |
| T11 | **`extract_secrets` table.** Every row of §6, plus negatives ("token is required", "password field"). No output contains any character of a lifted value's tail. | Unit | Remove each new pattern in turn: its row goes red. |
| T17 | **Squid conformance matrix, against the real egress image.** Raw CONNECTs from inside the deployed server; each case asserts its Squid error code.<br>Allowed: `api.github.com:443`, `API.GitHub.com.:443`.<br>Refused:<br>- `api.github.com..:443`;<br>- `1.2.3.4:443`, `[::1]:443`, `2130706433:443`, `0x7f000001:443`;<br>- `user@api.github.com:443`;<br>- `api.github.com:80`;<br>- the Cyrillic homograph `аpi.github.com` (raw UTF-8 and xn--);<br>- `GET http://api.github.com/` (plain forwarding);<br>- a CONNECT to an allowed host whose ClientHello carries SNI `evil.example`;<br>- a ClientHello with **no** SNI;<br>- non-TLS bytes inside an allowed tunnel. | Docker | One rendered line removed at a time (`-n`, `ip_literal`, `!tls_port`, `!CONNECT`, the `sni_ok`/`terminate` pair, `on_unsupported_protocol`). Each turns its own row red. |
| T17u | **Config renderer (unit).**<br>- The A-label output is deterministic.<br>- It refuses `*`, IPs, ports or non-ASCII in the allowlist.<br>- It refuses to render without each required directive.<br>- The env-file values decode back to the same config.<br>- The token is hex only. | Unit | Remove the directive check: a config missing `deny fwd private_dst` renders. |
| T18 | **Retirement of the old connector and the orphaned secrets (§9).** Fixture: an empty `mcp_servers`; `mcp_secrets` rows for several ids with no server; a config entry `github-issue-connector`; a **stopped** container plus image from a fake old-style deploy.<br>Expect, in order:<br>- audit rows were written first, with key **names** only (no values, no hints) and the recovered `server.py` with its sha256;<br>- the code was extracted with `docker create`/`docker cp` and **never started** (the event log shows no `start`);<br>- the container and image are gone, and the config entry is removed (byte check of the rest of the file);<br>- every orphaned secret row is deleted, then `VACUUM`;<br>- a `retired` server row exists with the recovered code and no approval;<br>- the Build board says what was retired.<br>A second run changes nothing (idempotent). | HTTP lifespan + Docker | Delete secrets before writing audit: the audit-first assertion goes red. Skip the config-entry removal: red. Start the container to read its code: red. |
| T19 | **No real secrets for unapproved code (answered: Q3).** After the agent changes an approved, running server's code:<br>- the approved container keeps running and the old image ID is unchanged;<br>- the new code's test env-file holds placeholders only;<br>- `decrypt_for_deploy(sha=<new>)` refuses;<br>- `/deploy` gives 409;<br>- the card reads "New code is waiting for your approval; the approved version is still on". | HTTP + fake runner | Drop the approved-hash check in `decrypt_for_deploy`: the new hash gets real values. |
| T12 | **Delete really stops it.** After delete there is no container, no network and no `extensions_config` entry (fake runner argv plus a file check). The hotfix ships the basic stop and delete behaviour; this test extends it to the sidecar and the networks. | HTTP | Revert delete to `manager.stop()`: red. |

Every new public definition is reached from production or listed in `tests/gates/test_wiring.py` with a reason that isn't "UNWIRED". A separate review agent that hasn't seen the build re-checks every safety claim with its own adversarial HTTP test before the stop report (round 2's process change).

---

## 8. Sequencing: small commits, pushed after each feature

1. `fix(mcp-build): the build tool says what the test really is`. Only the honest interim description; the false "verifies secrets" claim is removed.
2. `feat(mcp-build): extract_secrets lifts URL credentials, bearer tokens and short passwords whole`, plus T11.
3. `feat(mcp-build): approval is bound to the code's hash`:
   - columns and derived `approved`;
   - `update_source_code` clears approval;
   - `/enable` commits only on a successful deploy;
   - `/approve` and `/register` removed;
   - `/deploy` re-checks the hash under the per-server lock and runs by image ID;
   - `egress_hosts` recomputed from the hashed source;
   - T4, T5, T15.
4. `feat(mcp-build): the approval packet and view token`. The `GET /approval` endpoint, plus T6 (server half).
5. `feat(006): Review and approve shows the code, its hash, outbound hosts and tool tiers`. The UI dialog, T6 (Playwright), and the old detail page rewired.
6. `feat(mcp-build): built servers live under built/, never collide, and start at Tier 3`:
   - the namespace;
   - collision refusal;
   - `connect()` never overwrites and writes atomically;
   - `[a-z0-9-]` slugs everywhere;
   - the `classify()` branch and `built_tiers` keyed by `(server_id, tool)`, through 007's tool-name normaliser (this step waits for, or takes, that normaliser);
   - T8.
7. `feat(mcp-build): runtime image and launcher; generated code is never rewritten`. The runtime Dockerfile, launcher, per-hash image build and `_patch_main_for_sse` removed.
8. `feat(mcp-build): sandbox tests run in a locked container`:
   - the test-phase argv;
   - `HOME` and the site-packages path removed;
   - the `offline` badge;
   - the tool description made true;
   - T1-T3.
9. `feat(mcp-build): the Squid egress image and config renderer`:
   - `docker/mcp-egress/Dockerfile` (`alpine@sha256` + pinned `squid`, `dnsmasq`, `openssl`; the build checks `--with-openssl`);
   - the POSIX entrypoint;
   - the pure config renderer in the gateway;
   - T17u, and T17 against the real image.
10. `feat(mcp-build): deployed servers sit on an internal network behind the allowlist, reachable only on 127.0.0.1 or the gateway's network`:
    - deploy argv (create, connect, start);
    - validated env-file secrets;
    - the inbound token kept in the vault and injected at load time;
    - `build_egress_rules` used;
    - port 443 only;
    - T7, T7d, T9, T13, T14, T16, T19.
11. `feat(mcp-build): startup reconcile, and retirement of the old connector and the orphaned secrets`: §9, T12 (extending the hotfix's stop and delete to the sidecar and networks), and T18. **It runs before step 12**, so orphaned rows are deleted rather than rotated.
12. `feat(mcp-build): vault key lives in a 0600 secrets file, rotated on migration`. Compose `secrets:`, `make vault-key` and `vault-key-migrate`, the startup refusals (including `allow_host_bash`), `VACUUM`, and T10.
13. `docs(006): spec and plan updated to what shipped`.

Steps 1-6 need no Docker. Steps 7-12 do.

## 9. Startup reconcile, and retiring what is left over
When the gateway starts, it lists containers labelled `omni.mcp.*` and those named `omni-mcp-*`. It stops and removes (and removes the `extensions_config` entry for) any built container that:
- lacks the hardened labels;
- runs an image whose `omni.code_sha256` ≠ the row's derived approval;
- or whose row no longer exists.

Each removal is reported on the Build board. Nothing is removed silently.

### Retiring `github-issue-connector` and the orphaned secrets (answered: Q4)
The user's decision: remove the container and its secrets, **keep a record for the audit trail**, and re-approve under the new flow. Its `mcp_servers` row no longer exists, so the record is rebuilt from what remains.

**New table.** Append-only `mcp_build_audit` (`id`, `at`, `actor`, `event`, `server_id`, `name`, `details JSON`). It is created by `create_all`. No route updates or deletes rows.

**The retirement.** It is one idempotent job, run by the startup reconcile **once**, keyed by an audit marker `event=retirement-2026-10`. Its dry-run lists every action in the log before it acts. Steps, in order:
1. **Write the audit rows first, and commit:**
   - one `retired` row for `github-issue-connector`: the config entry's name and URL, the container name and ID, the image ID, and the env **names** seen in `docker inspect`;
   - one `orphaned-secrets` row per orphaned server id, with key **names** only.
   No values and no `key_hint`: the last five characters of a secret are part of the secret.
2. **Recover the code without running it.** `docker create` from the old image, `docker cp :/app/server.py`, then `docker rm`. The container is never started. Its old rootfs isn't read-only, so `docker cp` works.
   - The recovered source and its sha256 go into the audit row's details.
   - A new `mcp_servers` row is made: status `retired`, name `github-issue-connector` (shown as `built/github-issue-connector`), the recovered source, no approval, owned by the owner account (C.0).
   - "Re-approve under the new flow" is then concrete: open it, run **Test again** (the sandbox from §1), then the approval screen. The user enters a **new** GitHub token; the old one should be rotated.
   - If the image is already gone, the audit row says "code not recoverable", and no row is made.
3. Remove the container `omni-mcp-c641ac8dc68d` and its image (`docker rm -f`, `docker rmi`).
4. Remove the `github-issue-connector` entry from `extensions_config.json` with `atomic_write_json`, leaving every other byte's meaning unchanged.
5. **Delete every orphaned `mcp_secrets` row**: every row whose `server_id` has no `mcp_servers` row. That is the reported 21 rows across 12 ids, but the job counts what it finds rather than trusting those numbers. Then `VACUUM`.
6. Report on the Build board: "Retired github-issue-connector: started before approvals were bound to code. Its code is kept; test and approve it again to use it. Deleted N stored secrets left by M removed servers."

**Ordering with the other work:**
- The separate **hotfix** makes stop and delete remove containers and secrets from now on, so no new orphans appear. This job cleans up what came before it.
- The job runs **before** the vault-key rotation (step 12), so orphaned rows are deleted, not re-encrypted.

---

## The user's answers (2026-10-20); no questions are open

1. **Docker tests on your Docker Desktop.** May the build and the review agents start throwaway containers (labelled `omni-mcp-t-*`, `--rm`, cleaned up by the fixture) on your Docker Desktop to run T1-T3, T7, T9, T13 and T14? T7's positive control also makes one credential-less `HEAD https://api.github.com`. They don't touch the live stack's containers. **Answer: yes.** Throwaway containers, labelled, with no host mounts, auto-removed, and **listed in the test report** (§7).
2. **Egress ports.** HTTPS (443) only, dropping the plain-HTTP port 80 that `build_egress_rules` allows today. **Answer: yes, 443 only.**
3. **The agent changes the code of a server that is on.** **Answer: yes.** The approved version keeps running. New code shows "waiting for approval" and gets **no real secrets** until it is approved: placeholders only (§3, T19).
4. **The live `github-issue-connector` container.** **Answer: yes, retire it.** Remove its container and secrets, **keep its record** for the audit trail, and re-approve it under the new flow. Plus the cleanup of all orphaned secrets (§9).

Decided in this plan (tell me if you disagree):
- the vault key is a 0600 secrets file, not the Keychain (§2);
- egress uses an internal network plus a **Squid** sidecar, with dnsmasq `--stop-dns-rebind` as its resolver, **not** a proxy of our own (§4; the user's change);
- the legacy `/approve` and `/register` routes are removed, not re-bound (§3);
- the wire key is `built__<slug>`, displayed as `built/<slug>` (§5);
- `--env-file` for secrets, with the `docker inspect` residual stated (§4).

## 10. Revision history

### 10.1 Revision 2: what changed per review finding

| Finding | Change | Where |
|---|---|---|
| HIGH 1: proxy's private-IP refusal incomplete and raceable | The CONNECT host is normalised (one trailing dot, IDNA, refuses IP literals in every form, `@`, userinfo and ports other than 443). It is resolved **once**, **every** answer must be `is_global`, and the proxy connects to the vetted IP. SNI must equal the CONNECT host. The residual (exfiltration through allowlisted APIs; `Host`-header fronting) is stated. | §4 hardening, T17 |
| HIGH 2: the sidecar bridges both networks | The sidecar is created, connected, then started. `:3128` binds only on its internal-subnet address and `:8080` only on its outer-subnet address; it refuses to start otherwise. A test checks `:3128` is unreachable from the outer network. | §4, flags, T14 |
| HIGH 3: tests don't prove deployed DNS and routing | T2 and T7 connect to **literal IPs**. T13 asserts external `getaddrinfo` fails in the deployed container. T7 case 3 (an allowlisted name resolving to a gateway-network IP) is refused by the **unmodified** sidecar. The positive control is a public host; the proxy has no relax switch. | T2, T7, T13 |
| HIGH 4: enable→deploy race untested; 12-char tag | Under the per-server lock, a four-way hash check runs right before `docker run`. Tags are the full sha256; the label is verified on the **image ID**, and `docker run` gets `sha256:<ID>`. T15 blocks the runner mid-build, submits new code, releases it, and expects a refusal and no approval. | §1.2, §3, T15 |
| MED 5: tool-name ambiguity across built servers | Slugs are `[a-z0-9-]` from one function (including `POST /servers`, `mcp_studio.py:414`). `built_tiers` is keyed by `(server_id, tool)`. A fully prefixed name already registered is refused. 007's normaliser is used, not a second one. T8 is extended with `GitHub`, `git_hub` and prefix overlap. | §5, T8 |
| MED 6: invalid `FROM name@id`; BuildKit could pull | Built with the classic builder (`DOCKER_BUILDKIT=0`) and `--pull=false`, `FROM sha256:<runtime ID>`. The runtime image's ID and label are verified before each build. The fallback is the buildx `docker` driver. | §1.2 |
| MED 7: env-file injection | Keys must match `^[A-Z][A-Z0-9_]{0,63}$`; reserved names are refused (proxy vars, `HOME`, `PATH`, `MCP_*`, `PYTHON*`, `LD_*`, `SSL_*`, CA-bundle vars, `__*`); values with CR, LF or NUL are refused, at `PUT /secrets` and at deploy. The file is created `O_EXCL` 0600 and removed in `finally`. T16 checks the mode, and that the file is gone after success and after failure. | §4 Secrets, T16 |
| MED 8: inbound token in plaintext in `extensions_config.json` | The token lives in the vault (reserved `__INBOUND_TOKEN`, never given to the server). A provider the gateway registers injects it into in-memory server params at load time. The file carries only `server_id`. T9 byte-searches the file. I did not try to prove `read_file` can't reach `extensions/`; moving the token makes that unnecessary. | §4, T9 |
| LOW 9: `egress_hosts` source undefined | It is recomputed from the hashed source bytes only, and stored with the hash. The client-supplied list (`mcp_studio.py:418`) is dropped. A runtime-built host fails closed and shows in the blocked log. | §3 |
| LOW 10: view-token tests | T6 adds a token from another user, from another server, and one already used. | T6 |
| LOW 11: T10 sabotage | The mode, path, config-key and host-bash checks are sabotaged separately. | T10 |
| LOW 12: shredding on APFS isn't erasure | "Shred" is dropped. Rotation is the control: the old key decrypts nothing still stored. `VACUUM` runs after the migration. Backups and snapshots of the old DB are stated as a residual. | §2 |
| LOW 13: gateway compromise | §0 states that code execution in the gateway gets every built server's secrets and the host's `/Users` (rw `backend/` mount, compose `:187`; `docker.sock`, `:206`). It recommends gateway-mount hardening as a separate item. MCP Build refuses to enable while `sandbox.allow_host_bash` is true (tested in T10). | §0, T10 |

No finding was rejected.

### 10.3 Revision 4: build-time changes (plan approved 2026-10-20)
1. **Alpine pinned by digest.** The `docker/mcp-egress/Dockerfile` names `alpine:<tag>@sha256:<digest>`. The digest is recorded at the approved pull, the `apk` package versions are pinned, and the built sidecar image is run by its recorded **ID**.
2. **No secrets in environment variables:**
   - files are delivered over `docker exec` stdin into a per-container tmpfs, 0400, owned by the non-root user (§4 Secrets);
   - the env-file design is dropped, and its key and value validation is kept for the file format;
   - new test **T20**: `docker inspect` of a running server and sidecar contains no secret, with a sabotage that passes one with `-e`.
   - This changes MED 7's meaning: the injection risk is now the file's line format, guarded by the same validation. T16 now checks the delivered file's mode and owner instead of env-file cleanup.
3. **The CDN-fronting residual is accepted** by the user (2026-10-20).
4. **The runtime image's packages come from the gateway's installed environment**, verified against `RECORD` hashes, not from pip. The user didn't approve a pip download.

### 10.2 Revision 3: the user's answers, and Squid in place of our own proxy

**The answers:**
- Q1: the Docker tests' resources are listed in the report, and any host mount fails the test (§7 header).
- Q2: 443 only.
- Q3: new code gets placeholders only, the vault refuses a hash that isn't approved, and T19 tests it.
- Q4: the retirement and orphaned-secret cleanup, with the audit-first ordering, recovery of the code without running it, and a `retired` row (§9, T18).

**The proxy change.** The 200-line Python proxy is gone. In its place: Squid 6 with a rendered config, plus dnsmasq `--stop-dns-rebind` as its only resolver. Squid's accel port, guarded by a bearer-token ACL, is the login in front of the endpoint. The forward port needs a proxy login. Envoy was considered and not chosen (§4 table).

**Which reviewer findings change meaning with Squid:**

| Finding | Before (our proxy) | Now (Squid) | Change in meaning |
|---|---|---|---|
| HIGH 1: normalisation | Our function: lower-case, one trailing dot, IDNA, refuse literals and `@` | Squid's URL parser (lower-case; strips one trailing dot; refuses userinfo in the CONNECT authority), `dstdomain -n`, the `ip_literal` ACL, `!tls_port`. Non-ASCII hosts fail parsing. The renderer writes A-labels only. | **Same intent, different proof.** No unit test can cover Squid's parser, so T17 is now a matrix of raw CONNECTs against the real image, sabotaged one config line at a time. |
| HIGH 1: "every answer global" | `is_global` on every answer | `dst private_dst`, explicit ranges: any private answer denies (Squid's `dst` matches if **any** resolved address matches) | `is_global` becomes an explicit range list. I added the IPv6 ranges (`::ffff:0:0/96`, `64:ff9b::/96`, `fc00::/7`, `fe80::/10`). T7d tests this layer on its own. |
| HIGH 1: "connect to the vetted IP" (rebinding) | Our proxy connected to the IP it checked | Squid resolves again internally. **The guarantee now comes from dnsmasq `--stop-dns-rebind`**: a private answer never reaches Squid at any moment, so a flip has nothing to flip to. | **Changed mechanism.** "Same IP for check and connect" becomes "private answers are dropped at the resolver". T7 case 4 (TTL-0 flipping, 50 tries) is the proof. |
| HIGH 1: SNI check | SNI **equal to** the CONNECT host | `ssl::server_name --client-requested` **on the allowlist** | **Weaker.** Fronting **between allowlisted hosts** stays possible; that is stated as a residual. Missing SNI and SNI off the allowlist are still refused (T17). |
| HIGH 2: per-network binding | Our proxy bound by subnet | `http_port <ip>:port`, with the IP fixed (`.2`) on the internal side and found by subnet on the outer side | Same meaning. T14 now also covers the proxy login (407) and the endpoint token (403). |
| HIGH 3: proving deployed DNS and routing | Literal-IP sockets; T13; allowlisted name → gateway IP refused by the sidecar | Same, but the refusal is `ERR_DNS_FAIL` (dnsmasq). Squid's own layer is proven separately in T7d. | Same meaning, two layers. One test-only renderer parameter (`stop_dns_rebind=False`) exists for T7d. It has **no production caller**, and T9 asserts the production config keeps the flag. This is the only relaxation, and it is disclosed. |
| MED 6: image pinning | One runtime image | The egress image is our Dockerfile from `alpine@sha256` with pinned `apk` versions. Its image ID is recorded and verified before each run, like the runtime image. | New image, same rule. Risk: Alpine drops old package versions, so a rebuild can fail. It fails visibly, and the recorded image is kept. |
| MED 7: env-file validation | Secrets | Also carries the rendered configs (base64) | Same rules. The configs are generated by us and never by the user. |
| MED 8: token out of `extensions_config.json` | Our reverse proxy checked the token | Squid's `req_header` ACL checks it. The token is now also in the sidecar's env-file (base64 config). | Same `docker inspect` residual as the other secrets. |
| HIGH 4, MED 5, LOW 9-13 | — | — | Unchanged. |

**Open risk:** SSE through Squid's accel port must stream without buffering. T14's `tools/list` over SSE is the check. If it fails, the endpoint side moves to Squid's `http_port` in plain forward-to-peer mode, or we report back before choosing anything else.

Out of scope, noted: `GET /servers/{id}/secrets/reveal` (`mcp_studio.py:565-584`) returns plaintext secrets to any holder of `threads:write`. Worth a re-auth or removal under item C.0.


---

## 11. What shipped (build notes, 2026-10-20)

Built on `006-E-mcp-build` and pushed; PR #59 stays a gated draft.

### Where the build differs from this plan, and what was learned

1. **The SNI must EQUAL the CONNECT host, and a connection without SNI is refused** (the user's addition, 2026-10-20).
   - Squid's `ssl::server_name --client-requested` falls back to the CONNECT host when no SNI is sent (seen on 6.12), so it can't express this.
   - A tiny external ACL helper (`mcp_runtime/egress/sni_check.sh`, about 10 lines of `sh`) compares `%ssl::>sni` with `%DST` after the same normalisation (lower-case, one trailing dot dropped). It answers OK only when they are equal.
   - The rule is `ssl_bump splice sni_ok sni_matches_connect`, then `terminate all`.
   - Tests against the real sidecar: no SNI is refused; an SNI naming another allowlisted host is refused; a matching SNI reaches upstream (the positive control, skipped visibly when offline).
2. **A refused CONNECT on the ssl-bump port is answered by Squid inside TLS.** The answer is its error page, with `X-Squid-Error`, over the throwaway certificate. So "never presented" is wrong for Squid's own error pages. It still holds for upstream traffic: TLS to any upstream is never decrypted. The tests read `X-Squid-Error`.
3. **`PRIVATE_DESTINATIONS` leaves out `::ffff:0:0/96` and `::/128`.** `squid -k parse` (6.12) read them as `0.0.0.0/0`. Squid stores IPv4-mapped addresses as IPv4, so the IPv4 ranges cover them.
4. **Squid needs `max_filedescriptors 1024` and `--ulimit nofile=4096`.** With Docker's default fd limit (1M) it sized its tables to about 670 MB and aborted.
5. **The proxy login uses `$1$` MD5-crypt.** basic_ncsa_auth refused `{SHA}`, seen as 407. The MD5-crypt implementation was checked against `openssl passwd -1`.
6. **`--dns 127.0.0.1` is unproven on Docker 29.5.3.** T13 stays green without it: Docker's resolver on an `--internal` network does not forward external names. The flag is kept anyway, as planned.
7. **The runtime image takes `mcp`/`httpx` from the gateway's uv-installed environment, not pip.** Every file is checked against its `RECORD` hash (§1, revision 4). On a non-Linux gateway, and in the tests, the packages come from a throwaway container of `omni-harness-dev-gateway:latest`.
8. **`/connect` is still a route.** The old detail page uses it. It is guarded by the derived approval and by the name checks.
9. **The approval record is kept when code changes.** Only the pending approval is cleared, so the approved version can keep running (Q3), and approval is derived from the hash. T4's layer-1 sabotage ("remove the clear") became "derived check without the hash comparison".
10. **Tool tiers live in the server's `extensions_config.json` entry** (`built.tool_tiers`), and the classifier reads the file by mtime. Without this, every gateway worker would not see an approval.
11. **The look-alike check is stricter than the canonical tool name.** Case and all separators are ignored, so `git_hub`, `GitHub` and `git-hub` all collide with `github`.
12. **The secrets file is "read-only" in this sense:** mode 0400, its directory 0500, both owned by the container's non-root user. A truly read-only tmpfs needs `CAP_SYS_ADMIN` or a host mount.
13. **Restarts (closed):** a container brought back by `--restart` (empty tmpfs) waits for its files, and the gateway hands them over again.
    - It does this on its startup reconcile, and on every container start it sees in `docker events` (filtered on the `omni.mcp.role` label).
    - It only hands them over when the server container's `omni.code_sha256` label is the approved hash, and never through env vars.
    - The proxy login is kept in the vault (`__PROXY_PASSWORD`), so either container can be restarted alone.
    - Tested on real Docker: deploy, `docker restart` the server and then the sidecar; each serves again with its key, and `docker inspect` shows no secret.
15. **No registry contact.** Every `docker` command goes through `check_no_registry`:
    - `pull`, `push`, `login` and `search` are refused;
    - `run` and `create` need `--pull=never`;
    - `build` needs `--pull=false`, and the classic builder is forced.
    - A base image missing from the local store is an error that names the approved pull; the gateway never pulls.
    - The sandbox's stdio `docker run`, which bypasses the runner, is checked too.
16. **Rebased** onto `006-security-baseline` (which contains main, with 007's normaliser and `classify`). The built-tool branch sits before 007's refusal of unmatched tools.
    - Main's stop/delete hotfix is kept, now removing both containers and both networks; its tests were adapted to the topology and to hash-bound approval.
    - The broken intermediate commit (empty files) was folded into its fix.
14. **The `docker` and `internet` pytest markers** are registered in `backend/pyproject.toml`.

### Sabotage results
Every check was sabotaged: broken on purpose, seen to fail, and restored. Each result is listed in the stop report.

Three sabotages turned their test red for a different reason than the targeted assertion:
- dropping `--user`: a discovery timeout;
- dropping `--internal`: a deploy failure;
- the first T7(a): a later assertion.

These are said in the report as such.
17. **Review H1 (fixed): test results are bound to the code they tested.**
    - `verified_code_sha256` is stored with the tools, hosts and verdict. Only code whose hash equals it can be shown for approval, pending-approved or deployed.
    - A test that waited on another one re-runs for the current code, and never returns another hash's record.
    - The approval's hosts are read again from the approved bytes, and the deploy's allowlist is the one bound to the approval (pending or committed) for that hash, never the row's.
    - The reviewer's attack is kept as `tests/mcp_studio/test_review_attacks_59.py`, rewritten to assert the safe behaviour. A statically blocked A is never approvable; a clean C is tested itself, with its own hosts.
18. **Review #72 (fixed, it was small):**
    - a built tool's tier needs exactly one parse of its name as one built server's APPROVED tool; an ambiguous or unapproved name is Tier 3;
    - the loader offers only the tools on a built server's approval.
19. **Not fixed, filed:** #73 (re-delivery trusts the container label, not its name or image) and #74 (concurrent /enable calls tear down each other's containers).
