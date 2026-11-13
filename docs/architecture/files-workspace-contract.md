# Files workspace contract (`files.*`)

- **Status:** Frozen by WP1 under [ADR-019](../decisions/ADR-019-nas-mcp-file-workspace.md) (Accepted by operator directive 2026-11-13). Later work packages implement this text; a change to a name, rule or limit here is a contract change made in this file first.
- **Base:** `main@57d5b1399d59d7afe9fe08063d9bb842c9062dd2`, branch `feat/files-workspace`.
- **Not authorized here:** deployment, NAS mounts or ACLs, tunnel changes, grants, production migration.

One contract for every client. ChatLLM, ChatGPT, Abacus, browser and CLI see the same names, arguments, results and refusals. Access is set only by the per-client grants that already exist. No code path branches on client identity.

## 1. Vocabulary

### 1.1 Capabilities

These 17 names are appended to `Capability` in this order, after the current last member `schedule_baselines.compare`. Appending keeps the positional slices in existing guards valid. `Capability` grows from 281 to 298 members, and the audit `capability_is_known` set grows from 292 to 309.

| # | Name | Purpose | Class |
|---|---|---|---|
| 1 | `files.workspaces.list` | `file_workspace_read` | read |
| 2 | `files.list` | `file_workspace_read` | read |
| 3 | `files.stat` | `file_workspace_read` | read |
| 4 | `files.search` | `file_workspace_read` | read |
| 5 | `files.preview` | `file_workspace_read` | read |
| 6 | `files.history` | `file_workspace_read` | read |
| 7 | `files.download.begin` | `file_workspace_read` | read |
| 8 | `files.mkdir` | `file_workspace_authoring` | write, additive |
| 9 | `files.copy` | `file_workspace_authoring` | write, additive |
| 10 | `files.upload.begin` | `file_workspace_authoring` | write, additive |
| 11 | `files.upload.abort` | `file_workspace_authoring` | write, additive |
| 12 | `files.rename` | `file_workspace_authoring` | write, destructive hint |
| 13 | `files.move` | `file_workspace_authoring` | write, destructive hint |
| 14 | `files.trash` | `file_workspace_authoring` | write, destructive hint |
| 15 | `files.restore` | `file_workspace_authoring` | write, destructive hint |
| 16 | `files.upload.finalize` | `file_workspace_authoring` | write, destructive hint |
| 17 | `files.write_text` | `file_workspace_authoring` | write, destructive hint |

- None is operator-only. Each permits exactly its one purpose. Each is scopeless in `_SCOPELESS`, because it takes no `source_id`.
- `files.write_text` is classified non-additive even when it creates a file. The classification is static, and the tool can replace content.
- `file_workspace_authoring` joins `_WRITE_PURPOSES` in `adapters/mcp/remote.py`. Without it, the writes would be published as reads.

### 1.2 Purposes

There are 2 new `Purpose` members: `FILE_WORKSPACE_READ = "file_workspace_read"` and `FILE_WORKSPACE_AUTHORING = "file_workspace_authoring"`. `Purpose` grows from 68 to 70 members, and audit `purpose_is_known` grows to match.

### 1.3 Identifier kinds

Each prefix was checked unique against the 174 current `IdKind` values; none is a prefix of another. `IdKind` grows to 179.

| Member | Prefix | Identifies |
|---|---|---|
| `FILE_UPLOAD` | `fwupl` | an upload ticket and its staging object |
| `FILE_DOWNLOAD` | `fwdnl` | a download ticket |
| `FILE_VERSION` | `fwver` | a preserved preimage |
| `FILE_TRASH_ITEM` | `fwtrs` | a trashed entry |
| `FILE_RECEIPT` | `fwrcp` | an idempotency receipt |

### 1.4 Ticket token

A ticket token is `gfwtk_` followed by 64 lowercase hex characters (32 CSPRNG bytes). It is minted with the `reports.transfer` helpers (`issue_opaque_token`, `encode_opaque_token`, `digest_bytes`, constant-time `digests_match`). The raw token is returned once, and only its SHA-256 digest is stored. A request intent digest binds the token digest, never the raw token. Any response field that carries a token is named `*_token` (`upload_token`, `download_token`), so the MCP interaction-log redactor masks it.

## 2. Addressing

- **Workspace:** `workspace_id` is a logical alias. The only one is `MY_PA_FILES_WORKSPACE_ID`, default `mcp`. An unknown alias is `not_found`.
- **Entry:** an entry is addressed by `workspace_id` plus a relative POSIX `path`. The root is the empty path `""`, accepted only where a directory is expected (`list`, `search`, `mkdir` parent resolution).
- **Version:** each file or directory observation carries an opaque `version` token (§4).
- **Opaque ids:** only uploads, downloads, preimage versions, trash items and receipts get opaque ids. Files have no persistent id registry (trim T9).
- **Host paths:** a host or container path is never returned, logged or put in an error. All results are relative to the workspace root.

## 3. Path rules

A path is validated as a whole, then split on `/` and validated per component. Every refusal is `invalid_path`.

1. It must be relative. A leading `/` is refused, and so is a trailing `/`. It is a `str` encoded as UTF-8 and must be well-formed (no lone surrogates).
2. No component may be empty. That covers `//`, a leading or trailing `/`, and an empty path where an entry is required. No component may be `.` or `..`.
3. NUL is refused. So are the other C0 controls U+0001–U+001F and U+007F. **The backslash `\` is refused**, because SMB clients treat it as a separator, so a name containing it would mean different files to different writers.
4. Each component is at most 255 bytes in UTF-8. The whole path is at most 4096 bytes.
5. **Reserved names** are refused as any component, at any depth, compared with ASCII case folding: `.my-pa` (the control directory), `@eaDir`, `#recycle`, `#snapshot`. Folding defends against case-insensitive SMB views of a case-sensitive volume. Listing and search silently omit entries with these names. `.DS_Store` and other dotfiles are ordinary entries.
6. Names are case-sensitive and compared as bytes. **No Unicode normalization is applied:** the bytes the client sends are the bytes stored. NFC and NFD spellings of one name are two different names.

Resolution walks one component at a time from a root directory fd. It uses `openat(dir_fd, component, O_DIRECTORY|O_NOFOLLOW)` for directories and `O_NOFOLLOW` (plus `lstat` checks) for the leaf. A symlink or special file anywhere on the path stops the walk with `unsupported_entry`.

## 4. Entries and version tokens

- **Kinds:** an entry's `kind` is one of `file`, `directory` or `other`. `other` covers symlinks, FIFOs, sockets and devices. Such entries are **listed but never followed, opened, read, copied, moved, renamed, trashed or replaced**; any operation naming one is refused `unsupported_entry`. A symlink's target is never disclosed.
- **Entry shape:** `{workspace_id, path, name, kind, size, modified_at, version}`. `size` is the byte count for files and `null` otherwise. `modified_at` is RFC 3339 UTC from `st_mtime_ns`.
- **Version token:** `fv1_` followed by 64 lowercase hex characters, the SHA-256 of a canonical encoding of `(st_dev, st_ino, kind, st_size, st_mtime_ns, st_ctime_ns)` taken from `lstat`. It does not include a content hash. SHA-256 of the content is computed only on request (`include_sha256`) and returned as a separate field. The token is opaque, and clients compare it only for equality. Any external edit that changes size, mtime, ctime or inode changes the token. This is fingerprint detection, not proof of unchanged bytes (FW-D04).

## 5. Mutation semantics

- **Idempotency.** Every write takes a required `idempotency_key` (existing key rules). A receipt (`fwrcp`) records the key, scoped to Principal, client reference and capability, together with an intent digest of the normalized arguments and the result. Replaying the same key with the same intent returns the stored result with `replayed: true` and touches nothing. The same key with a different intent is `conflict` on `idempotency_key`.
- **CAS.** `expected_version` is optional on every write that names an existing entry. When supplied, it must equal the current token, or the write is refused `version_conflict`.
- **No overwrite by default.** A write whose destination exists is refused `exists`. Replacing a file's content (`upload.finalize`, `write_text`) requires `expected_version` of the current target. Directories are never replaced, and move, rename, copy and restore never overwrite.
- **Preimage.** Before replaced content is published, the current file is preserved under `<root>/.my-pa/versions/<fwver id>` (hard-linked there, or renamed where hard links are unsupported) and a version row is recorded. Then the new content is renamed into place over the name. The response carries `preimage_version_id`.
- **Trash.** `files.trash` renames the entry (file or whole directory) into `<root>/.my-pa/trash/<fwtrs id>` and records its original path, kind and fingerprint. `files.restore` renames it back to the original path, or to an optional `to_path`, without overwriting. If the trashed object's fingerprint no longer matches the record, restore is refused `external_change_detected`. There is no purge capability. Retention is set by the operator later (FW-D05).
- **Staging.** Upload and copy content is staged in `<root>/.my-pa/staging/` and published by `rename`. The control directory sits inside the root because a rename across bind mounts fails with `EXDEV`. It is created lazily at mode 0700 and is never addressable through the API.
- **Locking.** A per-workspace PostgreSQL advisory lock serializes product mutations only. Immediately before every rename, the store re-reads the target's fingerprint. A change by an external writer since the request's check is `external_change_detected`. The remaining check-to-rename window against external writers cannot be closed with the standard library and is documented, not claimed atomic.
- **Upload tickets** bind `(Principal, client reference, workspace, path, expected_version or "absent", declared size and sha256 if given)`. At finalize, the length and SHA-256 of the staged bytes must equal the finalize arguments and any declared values, or the call is refused `digest_mismatch` and the target is untouched. Expired staging is reaped in-process on `upload.begin` (trim T6).

## 6. Capability arguments and results

Every call takes `workspace_id`. Writes also take `idempotency_key`. Optional arguments are marked `?`.

| Capability | Arguments | Result |
|---|---|---|
| `files.workspaces.list` | (none) | `workspaces: [{workspace_id, writable, limits}]` |
| `files.list` | `path`, `after?`, `page_size?` (≤ 200, default 200) | `entries[]` sorted by name bytes, `next_after` (last name, or null) |
| `files.stat` | `path`, `include_sha256?` | entry, `sha256?` |
| `files.search` | `path` (subtree), `query` (1–255 chars, case-insensitive name substring), `page_size?` (≤ 200) | `entries[]`, `truncated` (walk cap or page reached); no continuation |
| `files.preview` | `path`, `offset?`, `max_bytes?` (≤ 262144), `expected_version?` | `text`, `next_offset` (null at EOF), `version`; non-UTF-8 content gives `binary: true` and no text; the cut never splits a character |
| `files.history` | `path?`, `after?`, `page_size?` (≤ 200) | product-recorded preimage versions and trash items for the path (or the workspace), newest first; external edits have no history |
| `files.download.begin` | `path` + `expected_version?`, or `version_id`; `include_sha256?`; `ttl_seconds?` | `download_id`, `download_token`, `route`, `size`, `version`, `sha256?`, `expires_at` |
| `files.mkdir` | `path`, `parents?` (default false) | entry |
| `files.copy` | `path`, `to_path`, `expected_version?` | entry at `to_path` |
| `files.upload.begin` | `path`, `expected_version?` (required to replace), `size?`, `sha256?`, `ttl_seconds?` | `upload_id`, `upload_token`, `route`, `offset` (0), `chunk_max_bytes`, `expires_at` |
| `files.upload.abort` | `upload_id` | `aborted: true` |
| `files.rename` | `path`, `new_name` (one component), `expected_version?` | entry |
| `files.move` | `path`, `to_path`, `expected_version?` | entry |
| `files.trash` | `path`, `expected_version?` | `trash_item_id`, original entry |
| `files.restore` | `trash_item_id`, `to_path?` | entry |
| `files.upload.finalize` | `upload_id`, `length`, `sha256` | entry, `preimage_version_id?` |
| `files.write_text` | `path`, `text` (≤ 1 MiB as UTF-8), `expected_version?` (required to replace) | entry, `preimage_version_id?` |

- A directory copy is staged and then renamed into place. It is bounded by the search walk caps (20,000 entries, depth 32) and by the disk reserve; exceeding them is `too_large`.
- Trashing a directory moves the whole subtree as one item.
- `route` is a relative URL path (`/files/v1/uploads/<id>`, `/files/v1/downloads/<id>`). Clients join it to the remote MCP origin.

## 7. Refusals

Files refusals use the existing public `ErrorCode`s. The specific reason is a new closed `SafeDetail` token. Each token names a condition and never carries a path or content.

| Reason token | ErrorCode | HTTP (byte routes) | When |
|---|---|---|---|
| `invalid_path` | `invalid_request` | — | §3 violated |
| `not_found` | `not_found` | 404 | entry, workspace, ticket target or parent absent |
| `exists` | `conflict` | — | destination exists and no replace is allowed |
| `version_conflict` | `conflict` | — | `expected_version` differs from current |
| `external_change_detected` | `conflict` | 412 | target changed outside the product since the product observed it (pre-rename re-check, ticket-bound version, trash fingerprint) |
| `unsupported_entry` | `unsupported` | — | `other` kind on the path, or a directory where a file is required (or the reverse) |
| `too_large` | `invalid_request` | 413 | a size limit in §8 exceeded |
| `quota` | `unavailable` | 507 | the write would leave less than the disk reserve free |
| `digest_mismatch` | `conflict` | 409 | finalize length or SHA-256 differs from the staged bytes or declared values |
| `offset_mismatch` | `conflict` | 409 | `Upload-Offset` is not the current staged offset (response carries the current `Upload-Offset`) |
| `ticket_invalid` | `denied` | 401 | token unknown, malformed, expired, used, aborted, or bound to another route |

The set is minimal. Expired and invalid tickets share one token because the client's remedy is the same (begin a new ticket), and distinguishing them would only give a probing oracle. Grant revocation reuses the existing `denied` path (HTTP 403). Idempotency misuse reuses `conflict` on `idempotency_key`. A Range the file cannot satisfy is HTTP 416 with no reason token.

## 8. Limits (Manager-approved)

| Limit | Value |
|---|---|
| Max upload size | 10 GiB, `MY_PA_FILES_MAX_UPLOAD_BYTES` |
| Free-space reserve | 20 GiB, `MY_PA_FILES_DISK_RESERVE_BYTES` (`statvfs`, checked at `upload.begin`, on every PATCH, at finalize, `write_text` and `copy`) |
| Ticket TTL | default 3600 s, max 86400 s |
| Upload request body | ≤ 32 MiB per PATCH (under the tunnel's 100 MB request cap) |
| Preview | ≤ 256 KiB per call, continued by `offset` |
| `write_text` | ≤ 1 MiB UTF-8 |
| List / search / history page | 200 entries; `after` cursor for list and history |
| Search walk | 20,000 entries, depth 32 |
| Byte-route concurrency | its own per-process cap, default 4, outside the `/mcp` semaphore |

Zero-byte files are valid everywhere. There is no MIME-type or extension allowlist. There is no tree-wide quota ledger (trim T4).

## 9. Settings and composition

| Variable | Meaning |
|---|---|
| `MY_PA_FILES_WORKSPACE_ROOT` | Absolute container path of the root. **Unset means the plane is absent:** no store is composed, no `files.*` name is served, and the ChatLLM prerequisite is false. Production value `/srv/my-pa/workspaces/mcp`. |
| `MY_PA_FILES_WORKSPACE_ID` | The alias, default `mcp`; a lower-case token. |
| `MY_PA_FILES_MAX_UPLOAD_BYTES` | Default 10737418240. |
| `MY_PA_FILES_DISK_RESERVE_BYTES` | Default 21474836480. |

At composition the store refuses to start unless the root exists, is a directory, and is not a symlink. It also refuses unless the root equals, contains and lies inside none of the configured source, managed-document or report-content roots. The production mount is that one NAS subtree, never `/volume1` or `/volume1/homes`.

## 10. Byte routes (remote MCP process only)

The routes are added through `create_remote_mcp_app(..., additional_routes=...)`. They are not mounted on the private HTTP gateway, and generic `/v1/{capability}` is never used for bytes. The public tunnel admits exactly `^/files/v1/uploads/[^/]+$` and `^/files/v1/downloads/[^/]+$`.

- **Auth.** `Authorization: Bearer gfwtk_…` is checked against the ticket digest before any body byte is read. Every request also re-checks that the ticket's client still holds an active grant for the capability that issued it (`files.upload.begin`, `files.download.begin`), so revocation takes effect immediately. Query strings are refused (400). Path ids must match the ticket.
- **`HEAD /files/v1/uploads/{id}`** returns 204 with `Upload-Offset: <n>`, `Upload-Length` (if declared) and `Cache-Control: no-store`.
- **`PATCH /files/v1/uploads/{id}`** requires `Upload-Offset` to equal the current offset (`offset_mismatch` otherwise). The raw body is streamed from `request.stream()` to the staging file at that offset, never buffered whole, then fsynced. The response is 204 with the new `Upload-Offset`. A final request may carry `Upload-Complete: sha256=<64 hex>, length=<n>`. That invokes the same `files.upload.finalize` handler, with the same audit, CAS and refusals as the MCP tool, and returns 200 with its JSON result. A PATCH with an empty body and `Upload-Complete` finalizes without appending. Interrupted uploads resume by HEAD then PATCH.
- **`GET /files/v1/downloads/{id}`** streams the file, with optional single `Range: bytes=a-b` (206) and 416 for an unsatisfiable range. It sends `ETag: "<version token>"`, `X-Content-SHA256` (only when the ticket carries a sha256), `Content-Length` and `Content-Type: application/octet-stream`. If the file's current version differs from the ticket's, it returns 412 `external_change_detected`. A download ticket may serve many range requests until it expires.
- **Errors** are JSON `{error, reason}` with the §7 status codes. They never echo the token, a path or body bytes.
- A stdlib reference client `scripts/my_pa_files.py` (WP6) exercises upload with resume and download with Range and SHA-256 verification.

## 11. Audit and logging

Every capability is audited through the existing `authorize` path. Audit records capability, outcome, reason token, `workspace_id`, opaque ids (`fwupl`/`fwdnl`/`fwver`/`fwtrs`/`fwrcp`) and byte sizes. It never records file bodies, `write_text` text, preview text, tokens, or host paths. Byte-route requests are not separately audited per chunk: begin and finalize are the audited events. The MCP interaction log must omit the `text` argument of `files.write_text` and the `text` result of `files.preview`, in addition to its existing `*token*` redaction (WP5/WP6 requirement).

## 12. ChatLLM and façade

- All 17 names are `DATA_CONDITIONAL` on a new `ChatLLMCompositionPrerequisite.FILES_WORKSPACE`, true exactly when `MY_PA_FILES_WORKSPACE_ROOT` composes the store. A matching flag is added to `ChatLLMCompositionPlanes`. The profile becomes `chatllm-data-v14`.
- `_FEATURE_BY_FAMILY` maps `files` to the façade feature `files`. `my_pa.describe` lists the family when it is composed. Tool hints follow §1.1: reads are read-only, additive writes are non-destructive, and the rest carry the destructive hint.
- There is no per-client code. Which clients receive which names is a grant decision at deploy time.

## 13. Count pins moved by later work packages

`len(Capability)` goes from 281 to 298, `len(Purpose)` from 68 to 70, `len(IdKind)` from 174 to 179, and the audit vocabularies from 292 to 309 capabilities and from 68 to 70 purposes. The cloudflared template's hostname-rule count goes from 9 to 11. WP5 owns every capability, purpose and IdKind pin. WP4 owns the migration's frozen sets. WP6 owns the tunnel pin.

## 14. Work-package map

| PR | WP | Delivers |
|---|---|---|
| PR1 | WP1 | ADR-019 and this contract |
| PR1 | WP2 | Pure domain `src/my_pa/domain/files/` (paths, version tokens, tickets, intent digests, errors) |
| PR1 | WP3 | Filesystem store `src/my_pa/infrastructure/file_workspace/` plus port; containment tests on temp roots |
| PR2 | WP4 | One additive Alembic revision (transfers, versions, trash, receipts tables; audit restatement); persistence |
| PR2 | WP5 | Application handlers, capabilities, policy, settings, composition, ChatLLM v14, façade, count pins |
| PR3 | WP6 | Byte routes, reference client, cloudflared template, live-gate mount check, overlay examples, runbook |
| PR3 | WP7 | Synthetic vertical slice; limitations and runbook closure |

## 15. Out of scope (trims)

- **T1:** report interoperability (attaching a file version to a report) and Daily-Intelligence lineage.
- **T2:** browser UI and file picker. Browser parity comes only through the generic capability path.
- **T3:** hard purge and any trash or preimage retention job (FW-D05).
- **T4:** tree-wide quota accounting. "Quota" means the max upload size plus the `statvfs` free-space reserve.
- **T5:** content search and any index. `files.search` is a bounded name walk.
- **T6:** a separate garbage-collection task. Expired staging is reaped in-process on `upload.begin`.
- **T7 (amended):** inline Base64 bytes over MCP. Inline content is limited to `files.write_text` (UTF-8, ≤ 1 MiB).
- **T8:** multiple roots. `files.workspaces.list` returns the single configured workspace.
- **T9:** persistent per-file ids. Files are addressed by alias, path and version token.
- **T10:** any sole-writer or atomicity claim against external writers (FW-D04).
- **T11:** proof of the Abacus scheduled-task bridge. Only the routes and the reference client ship.
- **T12:** any new process, service, queue or store technology.

## 16. Operator residuals

- NAS ACL: grant the service UIDs (`MY_PA_UID`, `MY_PA_REMOTE_UID`) read-write with inheritance on the workspace subtree, keeping it usable by the owner over SMB.
- Mount overlays for gateway and remote MCP, binding the subtree to `/srv/my-pa/workspaces/mcp` with the §9 environment.
- Cloudflared re-render with the two byte-route path rules, then a restart.
- Production migration and the `files.*` grants per client (`file_workspace_read`, and `file_workspace_authoring` with write).
- Proof of a scheduled Abacus run using the reference client.
- Backup and retention policy for the subtree, including `.my-pa/versions` and `.my-pa/trash`.
