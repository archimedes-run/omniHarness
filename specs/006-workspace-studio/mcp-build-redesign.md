# MCP Build (PR #59): redesign plan

Status: **PLAN ONLY. Waiting for the user's OK before any product code changes.**
Branch: `006-E-mcp-build`. Prerequisite: the security baseline (review round 2, item C.0: owner-only registration, server-owned context, ownership checks, 127.0.0.1 bindings) lands on `main` first; this work rebases onto it.

Revision 2 (2026-10-20) addresses an independent review: 4 HIGH, 4 MED and 5 LOW findings. The changes are listed per finding in §10.

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
   - Base: `python:3.12-slim`, pinned by digest.
   - Packages: `mcp` and `httpx`, pinned with hashes.
   - User: `app` (uid 10001), with no shell login and no sudo.
   - A launcher, `/opt/omni/launch.py`. It imports `/app/server.py` as a module, finds its `FastMCP` instance, and runs it with stdio or SSE, chosen by `MCP_TRANSPORT`. The generated code is **never rewritten**: `_patch_main_for_sse` and `_DOCKER_MAIN_NEW` are deleted.
   - The gateway builds this image once, from a tar context it streams to the Docker daemon. Our own Dockerfile is the only thing that ever runs `pip` with network access.
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
  --env-file /dev/shm/omni-mcp-<rand>.env        # placeholders only; file 0600, deleted in finally
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e MCP_TRANSPORT=stdio \
  sha256:<built image ID> \
  python -I -B /opt/omni/launch.py
```
There is no `-v` or `--mount` of any kind, no `-p`, no Docker socket and no `--privileged`. The 30 s discovery timeout and the 10 s per-call timeout stay. On a timeout the gateway runs `docker kill` on the named container: closing the pipe alone does not stop it.

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
- **If the agent changes code while the server is on:** the running container keeps running the **approved** image, because it is hash-bound. The card says "New code is waiting for your approval; the approved version is still on" (open question Q3).

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

### Choice: an `--internal` network per server, plus an allowlisting egress proxy sidecar
How it works:
- The MCP container is attached **only** to `omni-mcp-net-<id12>`, which is created `--internal` and so has no route off the network.
- Its sole neighbour is the sidecar `omni-mcp-egress-<id12>`, which is attached to that network and to an outer network (below). Each of its listeners is bound to one network only.
- The sidecar does two jobs:
  1. a **forward proxy** on `:3128`, internal interface only. It accepts only `CONNECT <host>:443` for hosts on this server's approved allowlist, after normalising the host (exact match, no wildcards). The full hardening is below. Every refusal is logged with its host and reason and shown on the server's page ("Blocked: tried to reach evil.example").
  2. a **reverse proxy** on `:8080` that forwards SSE to `omni-mcp-<id12>:8080`. It requires a per-server random bearer token.
     - **The token is never written to `extensions_config.json`.** The entry carries `server_id` and `"auth": "built-server-token"`, and no secret.
     - The token is stored in the vault as `__INBOUND_TOKEN` under the server's id. The `__` prefix is reserved: it is never handed to the server container.
     - At tool-load time, `omniharness/mcp/tools.py` asks a token provider for it. The gateway lifespan registers that provider, so the harness package does not import the app's vault. The provider adds the `Authorization` header to the in-memory server params only.
     - Why not keep it in the file: I did not prove that the agent's `read_file` mappings can't reach `extensions/`, so keeping the token out of the file is the safer claim.

**Hardening of the forward proxy (decision logic is one pure function, unit-tested):**
1. **Normalise the CONNECT target before any check:**
   - lower-case it;
   - strip **one** trailing dot;
   - IDNA-encode it (UTF-8 → A-label, refusing on encoding error);
   - refuse any target containing `@`, `/`, whitespace, `%` or a userinfo part;
   - refuse **IP literals** (v4, v6, bracketed, decimal/octal/hex integer forms; parsed with `ipaddress` after stripping brackets, plus an all-digits/0x check);
   - refuse a port other than 443.
   It then compares the result to the allowlist, which is normalised the same way.
2. **Resolve once, check every answer, then connect to the vetted address:**
   - `getaddrinfo` once;
   - **every** result must satisfy `ipaddress.ip_address(a).is_global`, which excludes loopback, RFC 1918, link-local, CGNAT, ULA, multicast, the Docker Desktop host and gateway ranges, and IPv4-mapped forms after unmapping. If any one fails, the request is refused, not filtered.
   - The proxy then opens the TCP connection to **that vetted IP**, never to the name again. That closes the DNS-rebinding window between check and connect.
   - There is no production switch to relax this. The positive-control test uses a public host instead (§7 T7).
3. **SNI check (on):**
   - the proxy peeks the TLS ClientHello on the tunnel; its SNI must equal the normalised CONNECT host;
   - a missing or different SNI closes the tunnel;
   - it reads only the plaintext ClientHello and never terminates TLS.
4. **Residual risk, stated:** the allowlist bounds **where** traffic goes, not **what** it carries.
   - Code allowed to reach `api.github.com` can still exfiltrate through that API (gist, issue body), using whatever token it holds.
   - Domain fronting is partly closed by the SNI check, but **not** against a mismatched HTTP `Host` header inside TLS, which the proxy can't see. A CDN that routes on `Host` could carry traffic to another tenant.
   - Mitigations are the user's review of the code and hosts, plus Tier 3 by default. The proxy does not prevent it.

**Each listener is bound to one network's interface only:**
- The sidecar is **created** (`docker create`) on the outer network, so any `127.0.0.1` publish attaches to a network that can carry it. It is then connected to the internal network, then started. So when its process starts, both interfaces exist.
- The gateway passes each network's subnet, from `docker network inspect` (`INTERNAL_SUBNET`, `OUTER_SUBNET`). The sidecar binds `:3128` **only** on its address inside `INTERNAL_SUBNET`, and `:8080` **only** on its address inside `OUTER_SUBNET`.
  - The forward proxy is therefore unreachable from the gateway's network, so nothing else in the stack can use it to get out.
  - The reverse proxy is unreachable from the server's own network.
  - If the sidecar can't find exactly one address in each subnet, it refuses to start.
- "Outer network" means the gateway's compose network (Docker gateway). For a bare-host gateway it is a dedicated non-internal bridge, `omni-mcp-pub-<id12>`, the only network the `127.0.0.1` publish attaches to.
- The sidecar's own outbound traffic leaves through the outer network's route.
- The MCP container gets `HTTPS_PROXY`/`HTTP_PROXY` pointing at the sidecar. `httpx` honours these by default.
- Code that ignores the proxy (raw sockets, its own DNS) **has no route at all**. Enforcement comes from the network topology; the code doesn't have to cooperate.

Why this, on Docker Desktop for Mac:
- `--internal` networks and multi-network containers work unchanged in Docker Desktop's VM. They need no `NET_ADMIN` and no host changes.
- The alternative, iptables in a sidecar sharing the network namespace, has three problems:
  - it needs `NET_ADMIN`;
  - it allowlists by **IP**, which breaks on CDN-fronted APIs (api.github.com rotates) unless we also snoop DNS;
  - Docker Desktop's VM iptables are not ours to manage and are rebuilt on restart.
- A proxy decides by **hostname**, which is what the user approves, and it gives a readable log of denials.
- Docker Desktop's own network policies (Enhanced Container Isolation) are a paid Business feature, so we can't rely on them.

**The sidecar is our own code:** about 200 lines of stdlib-only Python under `backend/app/gateway/mcp_egress_proxy/`. It runs in the same `omni-mcp-runtime` base image with a different entrypoint. Its allow/deny decision is a pure function that unit tests cover without Docker.

**DNS.** The MCP container gets `--dns 127.0.0.1`. Docker's embedded resolver still answers container names (which the sidecar needs), but external names have no upstream, which closes a DNS exfiltration channel even on Docker versions that forward DNS from internal networks. T13 checks that external names fail to resolve inside the deployed container, and records whether the flag was what made the difference on this Docker version.

**Ports.** `build_egress_rules` drops port 80 and allows HTTPS (443) only (open question Q2). Its output becomes the sidecar's `ALLOW_HOSTS`. The function is no longer computed and thrown away; the deploy uses it, and the wiring gate covers it.

**Reachability:**
- Gateway in Docker (the daily stack): `docker network connect <gateway-network> omni-mcp-egress-<id12>`, with URL `http://omni-mcp-egress-<id12>:8080/sse`. **No host port is published at all.** The gateway's network name comes from `OMNI_HARNESS_MCP_GATEWAY_NETWORK`, which compose sets (`omni-harness-dev` / `omni-harness`).
- Gateway on the bare host (`make dev`): the sidecar publishes `-p 127.0.0.1:<port>:8080`, and only the sidecar.
- `_find_free_port` probes `127.0.0.1`.
- `connect()` writes through `atomic_write_json` (already in `extensions_config.py:23`), not `open(..., "w")` (`mcp_server_manager.py:964`).

**Secrets.**
- They go in a `--env-file` written to `/dev/shm` (tmpfs; inside the gateway container in Docker mode) with mode 0600, deleted in `finally`. They never appear on argv, in a log or in a host file.
- **The env-file is validated before it is written**, for placeholders, secrets and the sidecar alike. One malformed key or value refuses the whole deploy, naming the key but never the value.
  - Each key must match `^[A-Z][A-Z0-9_]{0,63}$`.
  - Reserved names are refused, because a stored "secret" could otherwise redirect the proxy or the interpreter:
    - `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `ALL_PROXY` (and their lower-case forms);
    - `HOME`, `PATH`;
    - `MCP_*`, `PYTHON*`, `LD_*`, `SSL_*`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`;
    - anything starting with `__`.
  - Each value must not contain `\n`, `\r` or NUL: a newline would inject a second variable.
  - The vault's `PUT /secrets` applies the same key rules, so a bad name is refused when it is stored, not just at deploy.
  - The file is created with `os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600)` and removed in `finally`, on success and on failure.
- Residual, stated plainly: Docker stores env-file values in the container's config, so `docker inspect` still shows them to whoever holds the Docker socket. That is the gateway, which already holds the vault key, and the user.
- A follow-up could deliver them over stdin to the launcher at start, but that breaks `--restart` (secrets lost on daemon restart) and is not proposed now.

### Exact `docker run` flags: deploy phase
```
docker network create --internal --label omni.mcp.server=<server_id> omni-mcp-net-<id12>

# bare-host gateway only: the outer network that carries the 127.0.0.1 publish
docker network create --label omni.mcp.server=<server_id> omni-mcp-pub-<id12>
# OUTER = $OMNI_HARNESS_MCP_GATEWAY_NETWORK (Docker gateway) or omni-mcp-pub-<id12> (bare host)
# INTERNAL_SUBNET / OUTER_SUBNET read with `docker network inspect`

# sidecar: created on OUTER, connected to the internal network, THEN started, so it can bind per interface
docker create --name omni-mcp-egress-<id12> \
  --label omni.mcp.server=<server_id> --label omni.mcp.role=egress \
  --network $OUTER \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=4m \
  --user 10002:10002 --cap-drop ALL --security-opt no-new-privileges \
  --memory 64m --memory-swap 64m --pids-limit 32 --cpus 0.25 \
  --restart unless-stopped \
  --env-file /dev/shm/omni-egress-<rand>.env     # INBOUND_TOKEN; validated, 0600, removed in finally
  -e ALLOW_HOSTS=<normalised list from build_egress_rules> -e ALLOW_PORTS=443 \
  -e INTERNAL_SUBNET=<cidr> -e OUTER_SUBNET=<cidr> \
  -e UPSTREAM=omni-mcp-<id12>:8080 \
  [-p 127.0.0.1:<port>:8080]                     # bare-host gateway only
  sha256:<runtime image ID> python -I -B /opt/omni/egress_proxy.py
docker network connect omni-mcp-net-<id12> omni-mcp-egress-<id12>
docker start omni-mcp-egress-<id12>
# :3128 binds on the INTERNAL_SUBNET address only; :8080 on the OUTER_SUBNET address only

# the built server itself: no -p, no mounts, internal network only
docker run -d --name omni-mcp-<id12> \
  --label omni.mcp.server=<server_id> --label omni.mcp.role=server \
  --label omni.code_sha256=<full sha> \
  --network omni-mcp-net-<id12> --dns 127.0.0.1 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges \
  --memory 256m --memory-swap 256m --pids-limit 64 --cpus 0.5 --ulimit nofile=512:512 \
  --restart unless-stopped \
  --env-file /dev/shm/omni-mcp-<rand>.env        # real secrets; validated, 0600, removed in finally
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e MCP_TRANSPORT=sse -e MCP_PORT=8080 \
  -e HTTPS_PROXY=http://omni-mcp-egress-<id12>:3128 -e HTTP_PROXY=http://omni-mcp-egress-<id12>:3128 \
  sha256:<built image ID, label verified == approved sha> python -I -B /opt/omni/launch.py
```
**Undeploy, delete and stop** all remove both containers, the network and the `extensions_config` entry. Today, delete and stop leave the container running (see Current behaviour).

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

The Docker tests are marked `@pytest.mark.docker`. They run on the developer's Docker Desktop with labelled, `--rm` containers, a test-only network name prefix (`omni-mcp-t-`), and cleanup in a fixture finalizer. Where Docker is unavailable they **skip, and the skip is reported**. A skip is never reported as a pass (open question Q1).

The HTTP tests go through `create_app()` and its lifespan, as in `backend/tests/ledger/conftest.py`. The lifespan builds a `DockerRunner` port. The tests that don't need real Docker swap in a recording fake that captures argv and env-file contents; the Docker tests use the real one.

| # | Test | Through | Sabotage that must turn it red |
|---|---|---|---|
| T1 | **Escape: files.** The tool tries to read: `~/.ssh` (listing and `id_*`), `$HOME` listing, `/var/run/docker.sock`, `/app/config.yaml`, `/app/backend/.omni-harness/*`, `/run/secrets/mcp_vault_key`, `/root/.claude`, `/Users`. The test also writes a canary file into a temp dir and points the gateway's `HOME` at it. Every read must return missing. | Docker, `_run_server_sandbox_test` with the scanners **stubbed to allow** (containment must hold without them) | Add `-v {Path.home()}:/tmp/home:ro` and `HOME=/tmp/home` to the test argv: the canary is read. (A second sabotage reverts to the subprocess runner: the canary is read.) |
| T2 | **Escape: socket (test phase).** The fixture starts a TCP listener container `omni-mcp-t-listener` on an ordinary (non-internal) test bridge and records its **literal IP**. It also records the host gateway's literal IP, by resolving `host.docker.internal` in a throwaway bridge container. The tool connects to both **literal IPs** (no DNS involved), resolves `example.com`, and connects to `1.1.1.1:443`. All must fail, and the listener must log **no** connection. Needs no internet. | Docker, test phase | `--network none` → `bridge`: the listener logs a connection. |
| T3 | **Escape: privileges.** `os.getuid() != 0`; writing to `/app/server.py` raises EROFS; forking more than the pids limit fails. | Docker, test phase | Drop `--read-only`, then `--user`: each turns T3 red on its own assertion. |
| T4 | **Code changed after approval.** Build → test (fake runner) → `GET /approval` → `POST /enable {hash, token, tiers}` → deploy commits. The agent then submits new code through the `mcp_build` tool path. Expect: `GET /servers/{id}` shows `approved:false` and state awaiting approval; `POST /deploy` gives 409; `POST /enable` with the old hash gives 409; the deploy re-check refuses an image whose label ≠ current hash. | HTTP, `create_app()` | (a) Remove the clear in `update_source_code`, which is still red through the derived check; (b) make the derived check return the stored record without comparing hashes, which is red on a row written without a clear (direct DB write). One sabotage per layer. |
| T5 | **`/enable` with a failed deploy.** The fake runner returns rc=1 on `docker run`. Expect: not approved, state "Couldn't turn on", `pending_approval` cleared. Again with a gateway restart mid-deploy. | HTTP | Commit `approval` before the Docker work: red. |
| T6 | **View code before Approve.** `POST /enable` → 409 in each of these cases:<br>- no token;<br>- an expired token;<br>- a token for another hash;<br>- a token issued **to another user** (a second account through real HTTP, after C.0);<br>- a token issued for **another server**;<br>- a token **already used once**. Playwright: Approve is disabled until the Code tab is shown; the dialog shows the full hash, the hosts and all code lines. | HTTP + rendering spec | Server: skip the token check. UI: `{false && …}` around the disabled condition. Both red. |
| T7 | **Egress to a host not on the allowlist (deployed).** The real production deploy path runs with allowlist `[allowed.test, api.github.com]`. From inside the deployed server:<br>(1) `httpx.get("https://blocked.test")` → 403 from the proxy, and the denial shows in the server's blocked log;<br>(2) raw sockets to the T2 listener's **literal IP** and to the host gateway's **literal IP** fail, and the listener logs nothing. That proves **routing**, not just DNS;<br>(3) `allowed.test` is made to resolve **to the gateway network's IP of the listener** (`--add-host` on the sidecar, test fixture only). `CONNECT allowed.test:443` must be refused by the **real, unmodified** sidecar as "resolves to a non-global address". This is the rebinding case;<br>(4) positive control: `HEAD https://api.github.com` (no credentials) succeeds through the proxy. It is marked `internet`, and skipped **visibly** when offline. There is **no** switch in the proxy to relax the global-address rule, test or otherwise. | Docker, deploy phase | (a) `ALLOW_HOSTS=*`: blocked.test succeeds. (b) Put the server on `bridge` instead of the internal network: the literal-IP socket reaches the listener. (c) Replace the `is_global` check with a check on the first answer only, or connect by name: case 3 succeeds. |
| T13 | **Deployed DNS.** Inside the deployed server, `socket.getaddrinfo("example.com", 443)` and a lookup of a random name both **fail**; the sidecar's own name still resolves. | Docker, deploy phase | Remove `--dns 127.0.0.1`: whether this goes red depends on the Docker version's internal-network DNS forwarding, so the test records which. If it stays green without the flag, the flag is kept anyway, and the report says it was unproven on this Docker version. |
| T14 | **Sidecar listeners bound per network.** From a test container on the **outer** network: `:3128` is refused, and `:8080` without the token gives 401. From inside the server (internal network), `:8080` on the sidecar is refused. | Docker, deploy phase | Bind both listeners to `0.0.0.0`: `:3128` is reachable from the outer network. |
| T15 | **Enable→deploy race.** The fake runner **blocks** inside `docker build` on an event. While it is held, the agent submits new code through the `mcp_build` path; then the event is released. Expect: no `docker run` is issued (argv log), `pending_approval` is cleared, the server is not approved, and the state reads "The code changed while turning on". Also: a retagged built image (the label doesn't match) makes the deploy refuse, and `docker run` is always given `sha256:<ID>`, never a tag. | HTTP, `create_app()` | Drop the under-lock re-read before `docker run`: a run is issued for the new code. Run by tag: the argv assertion goes red. |
| T16 | **Env-file safety.** Storing secret names `HTTPS_PROXY`, `ld_preload`, `MCP_PORT`, `__INBOUND_TOKEN`, or a value containing `\n` is refused at `PUT /secrets` and again at deploy. The recording runner checks that the env-file existed with mode 0600 while `docker run` ran, and is **gone afterwards on both a successful and a failed run** (rc=1). | HTTP + fake runner | Remove the reserved-name check: `HTTPS_PROXY` is stored. Remove the `finally` unlink: the file is still there after the failed run. |
| T8 | **The collision with `github`.** `extensions_config` has `github`. `POST /builds` for a description that slugs to `github` gives 409 naming it, and no row is created. `connect()` for a row whose key exists and isn't tagged with its id refuses, and the file is unchanged (byte compare). The same 409 for `GitHub`, `git_hub` and `git-hub`. A `POST /servers` body name containing `_` is slugged with no `_`. Prefix overlap: a built `git` server whose tool `hub_x` would produce a prefixed name already registered by another server is refused at connect. The classifier: with the shipped rules plus a user rule `*` → Tier 1, `built__github_get_issue` is **Tier 3**. After an approval sets `get_issue: 1` it is Tier 1, and it is Tier 3 again after a code change. Two built servers each with a tool `x`: a tier set on one doesn't apply to the other (tiers are keyed by `(server_id, tool)`). | HTTP + unit | (a) Remove the collision check: 201. (b) Remove the `built__` branch in `classify()`: Tier 1 from `*`. (c) Key `built_tiers` by tool name only: the second server inherits the tier. (d) Skip the normaliser in the collision check: `git_hub` is accepted. |
| T9 | **No secret on argv or in config; no 0.0.0.0.** Over the fake runner's recorded argv: no stored secret value appears; `extensions_config.json` contains no inbound token (byte search for the token); no `-p` on the server container; the sidecar's `-p` (bare-host mode only) starts with `127.0.0.1:`. Docker variant: `docker port` shows 127.0.0.1 only. | HTTP (fake) + Docker | Re-add `-e K=V`: red. `"0.0.0.0:"` in `-p`: red. |
| T10 | **Vault key.** Startup refuses when `config.yaml` has `mcp_builder.vault_key`, when the key file's mode is 0644, or when the file is under the project root; MCP Build also refuses to enable with `sandbox.allow_host_bash: true`. The migration re-encrypts, the old key decrypts **no** remaining row, the new key decrypts all of them, and `VACUUM` ran. | `create_app()` lifespan | Sabotaged **one check at a time**, each turning its own assertion red: (a) accept the config key; (b) skip the mode check; (c) skip the path check; (d) skip the host-bash check. |
| T11 | **`extract_secrets` table.** Every row of §6, plus negatives ("token is required", "password field"). No output contains any character of a lifted value's tail. | Unit | Remove each new pattern in turn: its row goes red. |
| T17 | **Proxy decision function (unit).** Allowed: `api.github.com` and `API.GitHub.com.` (one trailing dot). Refused, each with its reason:<br>- `api.github.com..`;<br>- `1.2.3.4`, `[::1]`, `2130706433`, `0x7f000001`;<br>- `user@api.github.com`;<br>- `api.github.com:80`;<br>- an IDNA homograph of an allowed host (`аpi.github.com`, Cyrillic а);<br>- answers `[global, 10.0.0.1]` (one bad answer refuses all);<br>- `::ffff:127.0.0.1`;<br>- `100.64.0.1`;<br>- SNI ≠ CONNECT host;<br>- no SNI.<br>The connect target is the vetted IP object, never the name. | Unit | Remove each normalisation step in turn; check `any` instead of `all`; return the name instead of the IP. Each turns its own row red. |
| T12 | **Delete really stops it.** After delete there is no container, no network and no `extensions_config` entry (fake runner argv plus a file check). | HTTP | Revert delete to `manager.stop()`: red. |

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
9. `feat(mcp-build): the egress proxy sidecar`:
   - the pure decision function (normalise, resolve once, all answers global, connect to the vetted IP, SNI);
   - per-interface binding;
   - T17.
10. `feat(mcp-build): deployed servers sit on an internal network behind the allowlist, reachable only on 127.0.0.1 or the gateway's network`:
    - deploy argv (create, connect, start);
    - validated env-file secrets;
    - the inbound token kept in the vault and injected at load time;
    - `build_egress_rules` used;
    - port 443 only;
    - T7, T9, T13, T14, T16.
11. `feat(mcp-build): delete and stop remove the container, network and config entry; startup reconcile`, plus T12 and §9.
12. `feat(mcp-build): vault key lives in a 0600 secrets file, rotated on migration`. Compose `secrets:`, `make vault-key` and `vault-key-migrate`, the startup refusals (including `allow_host_bash`), `VACUUM`, and T10.
13. `docs(006): spec and plan updated to what shipped`.

Steps 1-6 need no Docker. Steps 7-12 do.

## 9. Startup reconcile (for the container that is live today)
When the gateway starts, it lists containers labelled `omni.mcp.*` and those named `omni-mcp-*`. It stops and removes (and removes the `extensions_config` entry for) any built container that:
- lacks the hardened labels;
- runs an image whose `omni.code_sha256` ≠ the row's derived approval;
- or whose row no longer exists.

Each removal is reported on the Build board ("Turned off github-issue-connector: it was started before approvals were bound to code; review and approve it again"). Nothing is removed silently. Under this rule, `omni-mcp-c641ac8dc68d` and its config entry are removed on the first start of the new gateway, unless the user has already removed them.

---

## Open questions (each with a recommended default)

1. **Docker tests on your Docker Desktop.** May the build and the review agents start throwaway containers (labelled `omni-mcp-t-*`, `--rm`, cleaned up by the fixture) on your Docker Desktop to run T1-T3, T7, T9, T13 and T14? T7's positive control also makes one credential-less `HEAD https://api.github.com`. They don't touch the live stack's containers. **Default: yes.** Where Docker is absent they are reported as skipped, never as passed.
2. **Egress ports.** HTTPS (443) only, dropping the plain-HTTP port 80 that `build_egress_rules` allows today. **Default: 443 only.** A tool that needs plain HTTP would need a later, explicit change.
3. **The agent changes the code of a server that is on.** **Default: keep the approved version running** (it is hash-bound) and show "new code is waiting for your approval". The alternative is to turn it off until you approve.
4. **The live `github-issue-connector` container.** **Default: the startup reconcile removes it**, together with its config entry, and you re-approve it under the new flow. Separately, please `docker rm -f omni-mcp-c641ac8dc68d` now and rotate that GitHub token.

Decided in this plan without a question (tell me if you disagree):
- the vault key is a 0600 secrets file, not the Keychain (§2);
- egress uses an internal network plus our own proxy sidecar (§4);
- the legacy `/approve` and `/register` routes are removed, not re-bound (§3);
- the wire key is `built__<slug>`, displayed as `built/<slug>` (§5);
- `--env-file` for secrets, with the `docker inspect` residual stated (§4).

## 10. Revision 2: what changed per review finding

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

Out of scope, noted: `GET /servers/{id}/secrets/reveal` (`mcp_studio.py:565-584`) returns plaintext secrets to any holder of `threads:write`. Worth a re-auth or removal under item C.0.
