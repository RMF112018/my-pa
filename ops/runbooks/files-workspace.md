# Files workspace (NAS MCP workspace) commissioning

**Status: UNEXECUTED / OPERATOR-GATED.** Nothing in this runbook has been run
against the NAS, the production database, Cloudflare or a live client. It
authorizes no deployment, migration, ACL change, tunnel change or grant; each
step below is the operator's (`AGENTS.md` §5). The authority is
[ADR-019](../../docs/decisions/ADR-019-nas-mcp-file-workspace.md) and the
[files-workspace contract](../../docs/architecture/files-workspace-contract.md)
(§9 settings, §10 byte routes, §16 operator residuals); this runbook is the §16
list as a procedure.

The plane is optional. With `MY_PA_FILES_WORKSPACE_ROOT` unset nothing is
composed: no `files.*` name is served, the byte routes are not mounted (they
answer 404), and ChatLLM `chatllm-data-v14` desires exactly the v13 set.

## 1. Prerequisites

1. **Image.** An image built from merged `main` that carries the files workspace
   (PR1–PR3). It also carries whatever merged work is not yet deployed; read the
   deploy notes for those first.
2. **Migration.** Revision `640aaacc78e8` (`files_workspace`, down-revision
   `b77334135653`) on top of the deployed chain. It adds four `knowledge.file_workspace_*`
   tables and restates the audit `capability_is_known` (292 → 309) and
   `purpose_is_known` (68 → 70) checks, taking a brief ACCESS EXCLUSIVE lock on
   `knowledge.audit_events` under `SET LOCAL lock_timeout`. **Take a `pg_dump`
   first** ([`postgres-operations.md`](postgres-operations.md)), then migrate with
   the deploy recipe's migrate step. The migration grants nothing.
3. **Folder.** The workspace is exactly one NAS subtree,
   `/volume1/homes/bfetting/MCP` — never `/volume1`, never `/volume1/homes`, and
   not equal to, inside or containing any configured source, managed-document or
   report-content root. Verify on the NAS that `MY_PA_NAS_SOURCE_ROOT`,
   `MY_PA_NAS_MANAGED_ROOT`, `MY_PA_NAS_CONFIG_ROOT` and the report-content root
   are none of those (compare against the live env files, do not guess). The
   store refuses to start on an overlap, and `ops/nas/remote/live-gate.py`
   refuses a read-only, too-broad (the share, the homes root or a whole home)
   or overlapping workspace mount on the remote MCP container, and any source
   other than exactly `/volume1/homes/bfetting/MCP`
   (`workspace_mount_source_mismatch`; the gate's `WORKSPACE_SOURCE`, pinned to
   the overlay). A different folder means changing the overlay and the gate
   together.

## 2. NAS ACL

The containers run as `MY_PA_UID` (gateway) and `MY_PA_REMOTE_UID` (remote MCP),
not as `bfetting`. Grant **both** uids read-write **with inheritance** on
`/volume1/homes/bfetting/MCP` (DSM File Station → Properties → Permission, or
`synoacltool`), keeping `bfetting`'s own access so the folder stays usable over
SMB. Files the product creates are owned by the service uid; inheritance is what
keeps them readable and writable by `bfetting`.

The product keeps its control directory **inside** the root,
`.my-pa/` (`staging`, `versions`, `trash`), because a rename across bind mounts
fails with `EXDEV`. It is visible over SMB; do not delete it while uploads or
trash items exist. Synology `@eaDir` and `#recycle` are refused as paths.

```sh
# read-only checks, as an administrator on the NAS
ls -ld /volume1/homes/bfetting/MCP
synoacltool -get /volume1/homes/bfetting/MCP
```

## 3. Overlays

Two example overlays ship in the repository and are copied into the live config
directory beside the existing overlays (they hold no secret):

| Example | Service | Base |
| --- | --- | --- |
| `ops/nas/compose.files-workspace.gateway.example.yml` | `gateway` | `ops/nas/compose.example.yml` (project `my-pa-nas-contract`) |
| `ops/nas/remote/compose.files-workspace.remote.example.yml` | `my-pa-mcp-remote` | `ops/nas/remote/compose.yml` (project `my-pa-remote-mcp`) |

Each binds `/volume1/homes/bfetting/MCP` → `/srv/my-pa/workspaces/mcp`
read-write and sets `MY_PA_FILES_WORKSPACE_ROOT=/srv/my-pa/workspaces/mcp`,
`MY_PA_FILES_WORKSPACE_ID=mcp`, `MY_PA_FILES_MAX_UPLOAD_BYTES=10737418240` and
`MY_PA_FILES_DISK_RESERVE_BYTES=21474836480`.

**Reuse the live file list.** Read each running container's
`com.docker.compose.project.config_files` label and pass **that list plus the new
overlay**, in order, to `docker compose ... up -d --no-deps <service>`; never
rebuild the list from memory, or a live overlay (report content, façade, GSQS)
silently drops out.

```sh
docker inspect my-pa-remote-mcp-my-pa-mcp-remote-1 \
  --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}'
```

After the remote MCP is recreated, run `ops/nas/remote/live-gate.py` with the
deploy recipe's arguments; it must pass with the workspace mount present.

## 4. Cloudflare Tunnel

The byte routes are public only through exact path rules in
`ops/nas/remote/cloudflared-config.example.yml` (12 hostname rules before the
404 catch-all; `validate.py` pins the list):

- `^/files/v1/uploads/[^/]+$`
- `^/files/v1/downloads/[^/]+$`
- `^/files/v1/browser-downloads/[^/]+$` (contract §17.6, browser download
  links; added 2026-11-15 and operator-gated: the live tunnel has only the
  first two until the operator re-renders and restarts `cloudflared`; until
  then a browser link answers the catch-all 404)

Keep a copy of the current rendered config, render the new one to a fresh path
(the renderer refuses to overwrite), move it into place, and restart only
`cloudflared`. **The restart is a brief public blip of `/mcp`.**

```sh
python ops/nas/remote/validate.py
python ops/nas/remote/render-cloudflared-config.py \
  --output /volume1/my-pa/cloudflared/config.files-workspace.yml \
  --tunnel-id "$TUNNEL_ID" --hostname "$MCP_HOSTNAME"
```

Cloudflare's request-body cap (100 MB) is why a PATCH carries at most 32 MiB.

## 5. Grants

The 17 `files.*` names (contract §1.1): 7 reads with purpose
`file_workspace_read`, and 10 writes with purpose `file_workspace_authoring`
granted with `--write`. Which clients receive which names is the Manager's
deploy decision; there is no per-client code. Either converge a ChatLLM client
on the profile, or grant names individually, inside the remote MCP container:

```sh
python apps/cli/remote_mcp.py profile-diff --oauth-client-id "$CLIENT" --scope my-pa.read \
    --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v16
python apps/cli/remote_mcp.py profile-apply --oauth-client-id "$CLIENT" --scope my-pa.read \
    --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v16 --apply
python apps/cli/remote_mcp.py grant --oauth-client-id "$CLIENT" --scope my-pa.read \
    --capability files.upload.begin --purpose file_workspace_authoring --write \
    --resource "$OAUTH_AUDIENCE"
```

`profile-apply` adds only composed data names, so run it after step 3. Clients
reconnect or refresh their tool list afterwards. Every byte-route request
re-checks the issuing grant, so revocation is immediate.

## 6. Verification

1. `/healthz` and `/readyz` of both processes answer as before (readiness from
   inside the container, as in [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md)).
2. Unauthenticated byte routes are refused, over the public hostname:

   ```sh
   curl -sS -o /dev/null -w '%{http_code}\n' -I "https://$MCP_HOSTNAME/files/v1/uploads/fwupl_probe"
   # 401
   curl -sS -o /dev/null -w '%{http_code}\n' -I "https://$MCP_HOSTNAME/files/v1/uploads/fwupl_probe?x=1"
   # 400 (query strings are refused before authentication)
   curl -sS -o /dev/null -w '%{http_code}\n' "https://$MCP_HOSTNAME/files/v1/other"
   # 404 (the tunnel catch-all)
   ```

3. A synthetic round trip in a test subfolder (e.g. `_commissioning/`), with a
   granted client: `files.mkdir`, then `files.upload.begin` for
   `_commissioning/probe.bin`. Write the returned `upload_token` to an owner-only
   file (never a command-line argument, never a ticket) and run the reference
   client [`scripts/my_pa_files.py`](../../scripts/my_pa_files.py):

   ```sh
   python scripts/my_pa_files.py upload ./probe.bin --origin "https://$MCP_HOSTNAME" \
       --route "$ROUTE" --token-file ./ticket
   python scripts/my_pa_files.py download ./probe.out --origin "https://$MCP_HOSTNAME" \
       --route "$DOWNLOAD_ROUTE" --token-file ./ticket --sha256 "$SHA256"
   ```

   Then `files.stat`, `files.trash` and `files.restore` on it, compare the bytes,
   and delete the ticket files. Expect `.my-pa/` to appear in the folder.

4. **Native file handles (contract §17), ChatGPT only.** With the ChatGPT
   connector granted `files.upload.begin` and `files.download.begin`, and
   remote writes on: refresh the connector's tool list, attach a small
   synthetic file and ask it to save it to `_commissioning/handle.bin`; compare
   `files.stat` with `include_sha256` against the local SHA-256. Then ask for
   `_commissioning/handle.bin` back and compare the delivered file's SHA-256.
   Nothing in the remote MCP log may show the attachment's link: no log line
   names a `download_url` (the server logs none, and the interaction log
   redacts the key). Settings: `MY_PA_FILES_HANDLE_HOST_SUFFIXES` (default
   `.blob.core.windows.net,.oaiusercontent.com`; empty refuses every handle
   `file_handle_unsupported`) and `MY_PA_FILES_HANDLE_FETCH_DEADLINE_SECONDS`
   (default 25, at most 60). The remote MCP container needs outbound HTTPS to
   the allowed hosts; no tunnel rule changes (handle fetches are outbound and
   resource reads ride `/mcp`). Both of the app's networks are `internal`, so
   add the overlay `ops/nas/remote/compose.files-handle-egress.remote.example.yml`
   to the remote compose invocation: it joins the app to the existing
   non-internal `cloudflare-egress` network (already admitted by the DSM
   firewall; no new subnet or firewall rule). `live-gate.py` accepts exactly
   that one extra app network and still requires it non-internal. Without
   it every handle fetch is `file_handle_refused` with `cause=resolve_failed`.
   Remove the overlay and recreate to cut the route.
   If ChatGPT gets `file_handle_refused`, read the remote MCP container's log
   for the one line `files handle refused cause=<cause> host=<host>` (logger
   `my_pa.files.handle_fetch`, WARNING). `cause=host_not_allowed` names the
   host the platform now uses: add a suffix covering it (leading `.`, e.g.
   `.oaiusercontent.com`) to `MY_PA_FILES_HANDLE_HOST_SUFFIXES`, comma-separated
   with the existing value, and recreate the service. The line never contains
   the URL or its query; still treat the log as operator-only.

5. **Abacus ticket recipe (contract §17.5).** With the Abacus connector
   granted the files names (and `files.upload.finalize`), refresh its tool
   list and ask it to upload a small synthetic file from its sandbox to
   `_commissioning/abacus.bin` and to download it back, using the answer's
   `transfer.usage`; compare SHA-256 both ways. `transfer.url` is absolute only
   when `MY_PA_REMOTE_MCP_PUBLIC_HOST` is set.

6. **Browser download links (contract §17.6), ChatGPT.** Off by default. Set
   `MY_PA_FILES_BROWSER_DOWNLOAD_CLIENT_IDS` to the ChatGPT connector's OAuth
   client id (comma-separated for several) and optionally
   `MY_PA_FILES_BROWSER_DOWNLOAD_TTL_SECONDS` (default 300, 60..900);
   `MY_PA_REMOTE_MCP_PUBLIC_HOST` must be set, or the feature stays off and the
   process logs a warning. After the tunnel rule above is live, ask ChatGPT
   for `_commissioning/probe.bin`, click the link it shows, compare the
   SHA-256, and click it again: the second click must be a plain 404. Each
   completed download writes `<time> INFO my_pa.files.browser_download files
   browser download completed client=<id> size=<n>` to the remote MCP
   container's stderr (`docker logs`); the route attaches that one handler
   itself, because the process configures no logging and would otherwise drop
   INFO. The WARNING lines (`files handle refused ...`, and the composition
   warning for client ids without a public host) reach stderr through
   Python's last-resort handler. The link itself is never logged. Rollback: empty the
   setting and recreate the service.

**Client exit status 5 ("outcome unknown").** A completing PATCH whose response
was lost may still have committed the finalize; the ticket is then closed and
answers 401. The client reports this distinctly from a refusal (3). Check with
`files.stat` (or `files.list`) whether the file is there before beginning a new
upload; do not assume failure.

## 7. Rollback

1. **Plane off.** Recreate both services with the previous `config_files` list
   (without the files overlays). The plane is then absent: no `files.*` names,
   the byte routes answer 404. Files already in the folder stay where they are.
2. **Tunnel.** Move the saved previous `config.yml` back and restart
   `cloudflared` (another brief blip). With the plane off the two rules are
   harmless, so this can wait.
3. **Grants.** Revoke each `files.*` grant with
   `python apps/cli/remote_mcp.py revoke-grant --grant-uuid <uuid>`.
4. **Migration.** The downgrade of `640aaacc78e8` **refuses once any
   `knowledge.file_workspace_*` row or any `files.*` audit name exists** — that
   is, after the first audited call. Treat the migration as forward-only after
   commissioning; restoring the pre-deploy `pg_dump` is the only full reversal.

## 8. Limits and residuals

- No retention or purge: `.my-pa/versions` and `.my-pa/trash` grow until an
  operator-set retention policy exists (contract T3). The operator's decision of
  2026-11-15 is **keep everything**: nothing deletes automatically, and deleting
  files under `.my-pa/` by hand orphans their database rows and breaks restore.
  Measure growth with `ops/nas/remote/files-workspace-size-report.sh` (read-only;
  run it on the NAS with `sudo -n sh`). It reports each control directory and
  warns when free space is within twice the 20 GiB reserve. Revisit when it does.
- The subtree is not in the database backup. Backing up
  `/volume1/homes/bfetting/MCP` (including `.my-pa/`) is the operator's.
- External writers (SMB, DSM) are not serialized; changes surface as
  `external_change_detected` (contract T10).
- An Abacus scheduled-run proof using the reference client is unverified (T11).
- Limits: 10 GiB per upload, 20 GiB free-space reserve, 32 MiB per PATCH, 4
  concurrent byte-route requests per process, ticket TTL 1 h (max 24 h).
- Native handles (contract §17): ChatGPT uploads by `source_file` and
  downloads by `resource_link` + `resources/read`; Abacus keeps the ticket
  routes from its sandbox. Verified only with the synthetic proof (to 50 MiB);
  larger files, the exact link lifetime (between 1 and 5 minutes) and the
  publicly reported missing-file-param flake are unverified. A handle ingest
  must finish inside the 25 s fetch deadline (under the 30 s remote call
  timeout); a slower file is `file_handle_refused`. The allowed host suffix is
  a platform-drift risk: if OpenAI moves its file host, handles fail closed
  until the setting is changed. No `files.fetch_url` exists (trim T15).
- Audit is the generic `authorize` row per call (principal, capability,
  purpose, allowed/denied, policy version, denial reason). It has no workspace
  id, opaque ids, sizes or handler outcome, and byte-route chunks are not
  audited (contract §11, trim T14). The full list is in
  [`docs/operations/mcv-limitations.md`](../../docs/operations/mcv-limitations.md).

## 9. The `work` workspace (approved-only writes)

**Status: UNEXECUTED / OPERATOR-GATED.** ADR-019 Amendment 2 and contract §18.
A second alias, `work`, serves `/volume1/homes/bfetting/Work` and all its
subfolders to the clients the operator lists: reads directly, and every write
only after the operator approves that one operation. `mcp` is unchanged. No
migration: pending changes live in a product state directory.

### 9.1 Prerequisites

1. **Image** built from merged `main` carrying `feat/files-work-workspace`.
   There is no Alembic revision for this feature.
2. **State directory.** Create a product-only directory outside Work, outside
   every other mounted root, owned by `MY_PA_REMOTE_UID`, mode 0700, e.g.
   `/volume1/my-pa/workspace-state/work`. Add
   `MY_PA_NAS_FILES_WORK_STATE_ROOT=<that path>` to the operator's Compose
   interpolation env (beside `MY_PA_NAS_MANAGED_ROOT`). It holds upload staging,
   pending change records and staged bytes (capped at 1 GiB by default,
   `max_pending_bytes`), `decided/` records and `decisions.jsonl`.
3. **Readers.** Collect the OAuth client ids of ChatGPT and both Abacus
   registrations (`SELECT oauth_client_id, client_name FROM
   identity.remote_clients` read-only, or the registration receipts) and set
   `MY_PA_FILES_WORK_CLIENT_IDS=<id>|<id>|<id>` in the same interpolation env.
   Only these clients see `work` at all (`clients=`); every other client,
   whatever its `files.*` grants, gets `not_found`.
4. **ACL.** `MY_PA_REMOTE_UID` needs read on Work for the serving app and
   read-write for the apply step (the same UID runs both; the serving app's
   bind is read-only at the kernel, so the ACL is not what stops it writing).
   The apply step creates `Work/.my-pa/{staging,versions,trash}` (0700) on first
   use; it is visible over SMB as a hidden folder and must be kept with Work's
   backup (it holds preimages and trash).
5. **Size.** Work is large and holds sensitive data. Nothing indexes or scans it
   eagerly: list and search are bounded (page 200, walk 20,000 entries, depth
   32). Synology `@eaDir`, `#recycle`, `#snapshot` and `.my-pa` are never
   listed or searched and are refused as path components.

### 9.2 Overlay

`ops/nas/remote/compose.files-work.remote.example.yml`, added **after**
`compose.files-workspace.remote.example.yml` (keep the `mcp` bind) to the live
`config_files` list of `my-pa-mcp-remote`:

- binds Work → `/srv/my-pa/workspaces/work` **read-only** and the state
  directory → `/srv/my-pa/workspace-state/work` read-write;
- replaces `MY_PA_FILES_WORKSPACE_ROOT` with `MY_PA_FILES_WORKSPACES`
  (`mcp` direct, `work` approval with its state and `clients=`);
- defines `my-pa-files-apply` (profile `files-apply`, `restart: "no"`), the only
  container that binds Work read-write (`/srv/my-pa/workspaces-apply/work`, set
  in `MY_PA_FILES_APPLY_ROOTS`). `up` never starts it; the operator runs it.

The serving app refuses to start if the Work bind is not a read-only mount (an
unmounted bind is a writable empty directory), and answers `unavailable` if it
stops being one. After recreating `my-pa-mcp-remote`, run
`ops/nas/remote/live-gate.py`: it refuses a writable or misplaced Work mount
(`work_mount_not_read_only`, `work_mount_source_mismatch`), a missing or
read-only state mount, any overlap, and the apply mount on the serving app
(`work_apply_mount_on_app`). The private gateway is not given `work`.

### 9.3 Grants

No new capability exists. The listed clients use their existing `files.*`
grants (the same names as for `mcp`): reads need `file_workspace_read`; a
write request needs the write grant and remote writes enabled, exactly as for
`mcp`, and becomes a pending change. A client without any write grant can only
read `work`. Revoking a grant or a client, or removing it from
`MY_PA_FILES_WORK_CLIENT_IDS` (then recreate the app), takes effect at once,
including on approvals not yet applied.

### 9.4 Approving changes

A client's write answers `approval_required` with a `pending_change_id`
(`fwpnd_…`); nothing is written to Work. The client polls
`files.history` with `pending_change_id`. Each change expires after
`MY_PA_FILES_APPROVAL_TTL_SECONDS` (default 900 s). With `CF` the live
`config_files` list plus this overlay:

```sh
DC="docker compose -p my-pa-remote-mcp $CF --profile files-apply run --rm my-pa-files-apply"
$DC files-pending --workspace work            # id, client, operation, paths, size, sha256, binding
$DC files-approve --workspace work --pending-change-id fwpnd_… --binding <binding from the list>
$DC files-deny    --workspace work --pending-change-id fwpnd_…
```

Review each listed change (operation, `path`/`to_path`, `size`, `sha256`)
before approving; the `binding` is the SHA-256 of exactly what was listed, so
an approval cannot apply anything else. Exit codes: 0 applied/denied/listed,
1 the apply `failed` (the folder changed since the request, the client lost
its grant, ...) or the change `expired`, 2 refused with nothing changed
(`binding_mismatch`, `not_pending`, `not_found`, `no_apply_root`,
`apply_root_mismatch`). An approval is single-use; a failed change is final —
the client asks again. Every decision is a line in
`<state>/.my-pa/decisions.jsonl` and on the apply container's log
(`my_pa.files.approval`).

### 9.5 Rollback

Recreate `my-pa-mcp-remote` without the Work overlay (the `mcp` overlay alone).
Pending changes then simply expire; the state directory can be kept for audit.
Nothing in Work was changed except by approved applies, whose preimages and
trash are in `Work/.my-pa/`.
