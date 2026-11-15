# Files workspace contract (`files.*`)

- **Status:** Frozen by WP1 under [ADR-019](../decisions/ADR-019-nas-mcp-file-workspace.md) (Accepted by operator directive 2026-11-13). Later work packages implement this text; a change to a name, rule or limit here is a contract change made in this file first. PR1 (WP1–3) and PR2 (WP4–5) are merged on `main`; PR3 (WP6–7, `feat/files-workspace-pr3`) delivers the byte routes, the reference client and the closure recorded in §10, §11 and T14. ADR-019 Amendment 1 (2026-11-15) adds native file handles and MCP resource delivery (§17, `feat/files-native-handles`); it changes §6, §7, §9, §11 and §15 here first. Deployment stays operator-gated (§16).
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

- **Kinds:** an entry's `kind` is one of `file`, `directory` or `other`. `other` covers symlinks, FIFOs, sockets and devices. Such entries are **listed but never followed, opened, read, copied, moved, renamed, trashed or replaced**; any operation naming one is refused `unsupported_entry`. A symlink's target is never disclosed. A regular file with more than one hard link is listed and `stat`ed as kind `file`, but its bytes are never read or written (preview, download, `include_sha256`, copy and upload staging refuse it `unsupported_entry`).
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
| `files.workspaces.list` | (none) | `workspaces: [{workspace_id, writable, limits}]`; `writable` reflects the caller's grants only (any `files.*` write grant, or no grant restriction), not the remote writes-disabled switch |
| `files.list` | `path`, `after?`, `page_size?` (≤ 200, default 200) | `entries[]` sorted by name bytes, `next_after` (last name, or null) |
| `files.stat` | `path`, `include_sha256?` | entry, `sha256?` |
| `files.search` | `path` (subtree), `query` (1–255 chars, case-insensitive name substring), `page_size?` (≤ 200) | `entries[]`, `truncated` (walk cap or page reached); no continuation |
| `files.preview` | `path`, `offset?`, `max_bytes?` (≤ 262144), `expected_version?` | `text`, `next_offset` (null at EOF), `version`; non-UTF-8 content gives `binary: true` and no text; the cut never splits a character, so a window may exceed `max_bytes` only to return a single character wider than the limit (≤ 4 bytes) |
| `files.history` | `path?`, `after?`, `page_size?` (≤ 200) | product-recorded preimage versions and trash items for the path (or the workspace), newest first; external edits have no history |
| `files.download.begin` | `path` + `expected_version?`, or `version_id`; `include_sha256?`; `ttl_seconds?` | `download_id`, `download_token`, `route`, `transfer` (§17.5), `browser_download?` (§17.6), `resource_uri`, `name`, `size`, `version`, `sha256?`, `expires_at` (§17.3) |
| `files.mkdir` | `path`, `parents?` (default false) | entry |
| `files.copy` | `path`, `to_path`, `expected_version?` | entry at `to_path` |
| `files.upload.begin` | `path`, `expected_version?` (required to replace), `size?`, `sha256?`, `ttl_seconds?`, `source_file?` (§17.2) | `upload_id`, `upload_token`, `route`, `transfer` (§17.5), `offset` (0), `chunk_max_bytes`, `expires_at`; with `source_file`: `upload_id`, `entry`, `preimage_version_id?`, `size`, `sha256` |
| `files.upload.abort` | `upload_id` | `aborted: true` |
| `files.rename` | `path`, `new_name` (one component), `expected_version?` | entry |
| `files.move` | `path`, `to_path`, `expected_version?` | entry |
| `files.trash` | `path`, `expected_version?` | `trash_item_id`, original entry |
| `files.restore` | `trash_item_id`, `to_path?` | entry |
| `files.upload.finalize` | `upload_id`, `length`, `sha256` | entry, `preimage_version_id?` |
| `files.write_text` | `path`, `text` (≤ 120 KiB as UTF-8), `expected_version?` (required to replace) | entry, `preimage_version_id?` |

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
| `file_handle_unsupported` | `unsupported` | — | a `source_file` was given and this process composes no handle fetcher (§17.2) |
| `file_handle_refused` | `invalid_request` | — | the `source_file` URL was refused or could not be fetched: scheme, host, address, redirect, status, TLS, network or deadline (§17.2) |

The set is minimal. Expired and invalid tickets share one token because the client's remedy is the same (begin a new ticket), and distinguishing them would only give a probing oracle. Grant revocation reuses the existing `denied` path (HTTP 403). Idempotency misuse reuses `conflict` on `idempotency_key`. A Range the file cannot satisfy is HTTP 416 with no reason token.

## 8. Limits (Manager-approved)

| Limit | Value |
|---|---|
| Max upload size | 10 GiB, `MY_PA_FILES_MAX_UPLOAD_BYTES` |
| Free-space reserve | 20 GiB, `MY_PA_FILES_DISK_RESERVE_BYTES` (`statvfs`, checked at `upload.begin`, on every PATCH, at finalize, `write_text` and `copy`) |
| Ticket TTL | default 3600 s, max 86400 s |
| Upload request body | ≤ 32 MiB per PATCH (under the tunnel's 100 MB request cap) |
| Preview | ≤ 256 KiB per call, continued by `offset` |
| `write_text` | ≤ 120 KiB (122,880 bytes) UTF-8 (trim T13) |
| List / search / history page | 200 entries; `after` cursor for list and history |
| Search walk | 20,000 entries, depth 32 |
| Byte-route concurrency | its own per-process cap, default 4, outside the `/mcp` semaphore |

The `write_text` bound is set below the 1 MiB Q3 ceiling because every transport refuses a request above `MAX_REQUEST_BYTES` (762,288 bytes) and a worst-case text (C0 controls, six JSON bytes each under `ensure_ascii`) of 120 KiB is the largest whole-KiB size that still fits beside the other fields at their bounds; the arithmetic is beside `MAX_WRITE_TEXT_BYTES` in `src/my_pa/domain/files/vocabulary.py`.

Zero-byte files are valid everywhere. There is no MIME-type or extension allowlist. There is no tree-wide quota ledger (trim T4).

## 9. Settings and composition

| Variable | Meaning |
|---|---|
| `MY_PA_FILES_WORKSPACE_ROOT` | Absolute container path of the root. **Unset means the plane is absent:** no store is composed, no `files.*` name is served, and the ChatLLM prerequisite is false. Production value `/srv/my-pa/workspaces/mcp`. |
| `MY_PA_FILES_WORKSPACE_ID` | The alias, default `mcp`; a lower-case token. |
| `MY_PA_FILES_MAX_UPLOAD_BYTES` | Default 10737418240. |
| `MY_PA_FILES_DISK_RESERVE_BYTES` | Default 21474836480. |
| `MY_PA_FILES_HANDLE_HOST_SUFFIXES` | Comma-separated host suffixes a native handle's `download_url` may name, each with a leading `.`; default `.blob.core.windows.net,.oaiusercontent.com` (the Azure blob host seen in the proof, `oaisdmntprcentralus.blob.core.windows.net`, and the host real ChatGPT used at the 2026-11-15 re-proof, `sdmntprcentralus.oaiusercontent.com`). Empty composes no handle fetcher (`file_handle_unsupported`). §17.2. |
| `MY_PA_FILES_BROWSER_DOWNLOAD_CLIENT_IDS` | Comma-separated OAuth client ids that get a browser download link (§17.6). **Empty (the default) turns the feature off.** |
| `MY_PA_FILES_BROWSER_DOWNLOAD_TTL_SECONDS` | A browser link's lifetime; default 300, 60..900. §17.6. |
| `MY_PA_FILES_HANDLE_FETCH_DEADLINE_SECONDS` | The whole-fetch deadline of one handle; default 25, at most 60. §17.2. |

At composition the store refuses to start unless the root exists, is a directory, and is not a symlink. It also refuses unless the root equals, contains and lies inside none of the configured source, managed-document or report-content roots. The production mount is that one NAS subtree, never `/volume1`, `/volume1/homes` or a whole home; `ops/nas/remote/live-gate.py` requires the remote MCP container's workspace bind source to be exactly `/volume1/homes/bfetting/MCP` (`WORKSPACE_SOURCE`, pinned to the overlay's `source:`).

The plane is not composed in the restricted MCP database-profile composition: when `MY_PA_MCP_DATABASE_PROFILES_ENABLED` injects a `data_engine`, the gateway composes `file_workspace=None` (`src/my_pa/bootstrap/gateway.py`), so no `files.*` name is served there (fail-closed).

## 10. Byte routes (remote MCP process only)

The routes are added through `create_remote_mcp_app(..., additional_routes=...)`. They are not mounted on the private HTTP gateway, and generic `/v1/{capability}` is never used for bytes. The public tunnel admits exactly `^/files/v1/uploads/[^/]+$` and `^/files/v1/downloads/[^/]+$`, and -- only once the operator adds the rule for §17.6 -- `^/files/v1/browser-downloads/[^/]+$`.

- **Auth.** `Authorization: Bearer gfwtk_…` is checked against the ticket digest before any body byte is read, and before the request takes a byte-route slot or waits on an upload's lock. Every request also re-checks that the ticket's client still holds an active grant for the capability that issued it (`files.upload.begin`, `files.download.begin`), so revocation takes effect immediately. Query strings are refused (400). Path ids must match the ticket.
- **`HEAD /files/v1/uploads/{id}`** returns 204 with `Upload-Offset: <n>`, `Upload-Length` (if declared) and `Cache-Control: no-store`.
- **`PATCH /files/v1/uploads/{id}`** requires `Upload-Offset` to equal the current offset (`offset_mismatch` otherwise). The raw body is streamed from `request.stream()` to the staging file at that offset, never buffered whole, then fsynced. The response is 204 with the new `Upload-Offset`. A final request may carry `Upload-Complete: sha256=<64 hex>, length=<n>`. That invokes the same `files.upload.finalize` handler, with the same audit, CAS and refusals as the MCP tool, and returns 200 with its JSON result. A PATCH with an empty body and `Upload-Complete` finalizes without appending. Interrupted uploads resume by HEAD then PATCH.
- **`GET /files/v1/downloads/{id}`** streams the file, with optional single `Range: bytes=a-b` (206) and 416 for an unsatisfiable range. It sends `ETag: "<version token>"`, `X-Content-SHA256` (only when the ticket carries a sha256), `Content-Length` and `Content-Type: application/octet-stream`. If the file's current version differs from the ticket's, it returns 412 `external_change_detected`. A download ticket may serve many range requests until it expires.
- **Errors** are JSON `{error, reason}` with the §7 status codes. They never echo the token, a path or body bytes.
- A stdlib reference client `scripts/my_pa_files.py` (WP6) exercises upload with resume and download with Range and SHA-256 verification.

### 10.1 As delivered (WP6a/WP6b)

The routes answer these statuses beyond §7, each as JSON `{error, reason}` with a `null` reason unless a §7 token applies:

| Status | When |
|---|---|
| 400 `invalid_request` | any query string (a token in it included); a multi-range or malformed `Range`; a malformed `Upload-Offset`, `Upload-Complete` or `Content-Length` |
| 405 `invalid_request` (`Allow: GET`) | any method but GET on a download route, HEAD included |
| 408 `unavailable` | no body byte for 30 s (`BODY_IDLE_TIMEOUT_SECONDS`), or a PATCH past 600 s (`PATCH_DEADLINE_SECONDS`) |
| (stream cut) | a GET whose reader accepts no bytes for 30 s (`BODY_IDLE_TIMEOUT_SECONDS`), one streaming past 600 s (`DOWNLOAD_DEADLINE_SECONDS`), or one whose ticket expired or grant was revoked (re-checked every 5 s, `DOWNLOAD_RECHECK_SECONDS`): the headers already left, so the body stops short of `Content-Length` and the connection is closed; the client resumes with `Range` |
| 422 `unsupported` / `unsupported_entry` | the ticket's target became an `other` entry, or a directory where a file is needed |
| 503 `unavailable` + `Retry-After: 1` | a request with a ticket-shaped bearer finds the per-process pre-slot authentication cap (8, twice the slot count) in use; an authenticated request finds the per-process byte-route slot cap (4) full; or another PATCH of the same upload holds its lock past 30 s |

Behaviour a client must know (each bounded by a test where one exists):

- **Order of checks.** A query string (400) or a non-GET download (405) is refused first. Then the ticket is authenticated -- a header that cannot carry a `gfwtk_` token on the event loop, anything else (digest and grant re-check) in a worker thread -- and a refused request answers 401 or 403 there, holding no slot and waiting on no lock. A PATCH's `Upload-Offset`, `Upload-Complete` and `Content-Length` are parsed only after that, so an unauthenticated caller always gets the one undistinguished 401, never a 400 for a malformed header (`test_every_bad_ticket_is_one_undistinguished_401` in `tests/security/test_files_transfer_negative.py`); a declared length over the cap is still 413 before any body byte is read. Only then does it take a slot (503 when none is free), and a PATCH the upload's lock, after which the ticket is authenticated again (it may have closed while the PATCH waited) before the offset and length checks. The authentication threads share the event loop's default executor with `/mcp`, so the pre-slot check has its own per-process cap (default 8, `AUTH_SLOTS_PER_TRANSFER_SLOT` times the slot count; `max_concurrent_authentications` in `build_file_transfer_routes`), separate from `/mcp`'s: a permit is taken without waiting, none free is the same 503 `unavailable` with `Retry-After: 1` as a full slot count, and a permit is returned when its worker thread returns -- not when the request is cancelled -- so a disconnecting client neither frees one early nor leaks one. The PATCH re-check under the lock and a download's periodic re-check run while the request holds a slot, so they are bounded by the slot count and take no permit; authentication threads in flight stay at most the auth cap plus the slot count (`test_bad_tickets_never_take_a_slot_nor_wait_on_an_upload_lock` in `tests/security/test_files_transfer_negative.py`; `test_exhausted_auth_permits_are_503_at_once_and_come_back` and `test_a_cancelled_check_keeps_its_permit_until_its_thread_returns` in `tests/security/test_files_transfer_auth_cap.py`).
- **Downloads are bounded like uploads.** Each send is bounded by the idle bound, so a reader that stops reading gives its slot back within about 30 s; the stream by its deadline; and the ticket and grants are re-read every 5 s between 1 MiB chunks, so an expiry or a revocation stops a stream already running (`test_a_stalled_download_reader_releases_its_slot_after_the_idle_bound`, `test_a_download_stops_mid_stream_on_revocation_expiry_or_its_deadline`). A reader of a large file over a slow link is cut at the deadline and resumes with `Range`, as the reference client does.
- **The held-open file is released on every exit.** The download reader (an open descriptor bound to the ticket's version) is registered for release when its opening thread returns -- before the request resumes, and even if it was cancelled meanwhile -- so a 200 or 206 stream, a 416, a refused read, a cut stream and a cancelled request each close it exactly once, before the request's slot is given back, and never while a worker thread of the request is still running (`test_repeated_unsatisfiable_ranges_close_every_file_they_open` in `tests/security/test_files_transfer_negative.py`; `test_every_download_exit_closes_its_reader_exactly_once` and `test_a_download_cancelled_after_its_open_closes_the_reader` in `tests/security/test_files_transfer_auth_cap.py`).

- **A completing PATCH retried after its finalize committed answers 401** `ticket_invalid`, not a replay: the ticket closed when the finalize committed. The reference client exits 5 ("outcome unknown") and the caller verifies with `files.stat` (`test_a_completing_patch_retried_after_its_finalize_committed_is_401` in `tests/integration/test_files_workspace_vertical_slice.py`; client side `test_a_lost_completing_response_then_401_is_unknown_not_failure` in `tests/unit/test_my_pa_files_client.py`).
- **A change after the download headers left** cannot become a 412: the store re-checks the version before every 1 MiB chunk and the stream stops short of `Content-Length`, and the server closes the connection (uvicorn logs one `ASGI callable returned without completing response.` line, which names nothing); the client's SHA-256 check catches it when `include_sha256` was requested, and the retry is 412 (`test_a_change_after_the_headers_truncates_the_stream`).
- **The reference client never clobbers a new `OUT`.** Without `--overwrite` it publishes the verified `.part` with a hard link that fails when `OUT` exists (reserving `OUT` with `O_EXCL` where hard links are unsupported, and removing that empty reservation if the replace then fails), so an `OUT` that appeared during the download is exit 1 with the bytes kept in `OUT.part` for inspection; `--overwrite` replaces atomically (`test_download_never_clobbers_an_out_that_appeared_during_the_download` in `tests/unit/test_my_pa_files_client.py`).
- **After an interrupted append** (disconnect, 408) the staged file may hold more bytes than the row's offset; HEAD reports the staged bytes and the next PATCH or finalize reconciles the row (`test_begin_bytes_interrupt_resume_finalize_list_stat_download`).
- **Concurrency is per process.** The slot cap and the per-upload lock live in one process; across processes the store's offset check and the row's offset CAS serialize (`test_the_slot_cap_answers_503_with_retry_after` in `tests/security/test_files_transfer_negative.py`).
- **`If-Match` is ignored by the server.** The reference client resumes a download only when its stored ETag matches the server's, and restarts otherwise.
- **Tickets bind the hashed client reference.** The per-request grant re-check finds the ticket's client by scanning registered clients and comparing in constant time (a small table).
- Production runs uvicorn with `access_log=False`; a test server's access log would show the request line (never a token, which is a header).

## 11. Audit and logging

Each `files.*` call is audited once, by `authorize` (`src/my_pa/application/authorization.py`), as one `knowledge.audit_events` row: its audit id, correlation id and timestamp, principal, capability, purpose, outcome (`allowed` or `denied`), policy version, the policy denial reason when denied, and `scope_source_id_count` (always 0: the names are scopeless). Those are the table's only columns. It does **not** record `workspace_id`, opaque ids (`fwupl`/`fwdnl`/`fwver`/`fwtrs`/`fwrcp`), byte sizes or the handler's outcome (trim T14).

- The row records the policy decision, not what the handler then did: a refusal raised after authorization (`version_conflict`, `exists`, `digest_mismatch`, `not_found`, `unsupported_entry`, ...) is audited `allowed`.
- Byte-route HEAD, PATCH chunks and GET requests are not audited. A completing PATCH runs `files.upload.finalize` through `invoke` and is audited as `files.upload.finalize`, exactly as the MCP tool is.
- It never records file bodies, `write_text` text, preview text, tokens, paths or host paths; `AuditEvent` has no field that could hold them.

The MCP interaction log omits the `text` argument of `files.write_text` and the `text` result of `files.preview`, in addition to its existing `*token*` redaction, and redacts every `download_url` value whole (a native handle's bearer URL, §17.2). A handle ingest is audited as the one `files.upload.begin` row; the URL, `file_id`, file name and MIME type are recorded nowhere. A `resources/read` of a download resource is, like a byte-route GET, not audited. The byte routes are outside the `/mcp` interaction log: it wraps `/mcp` only.

Bounded by `test_the_audit_records_the_decision_and_nothing_about_the_file` and the audit assertions in `tests/integration/test_files_workspace_vertical_slice.py`.

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
- **T7 (amended):** inline Base64 bytes over MCP. Inline content is limited to `files.write_text` (UTF-8, ≤ 120 KiB; see T13).
- **T8:** multiple roots. `files.workspaces.list` returns the single configured workspace.
- **T9:** persistent per-file ids. Files are addressed by alias, path and version token.
- **T10:** any sole-writer or atomicity claim against external writers (FW-D04).
- **T11:** proof of the Abacus scheduled-task bridge. Only the routes and the reference client ship.
- **T12:** any new process, service, queue or store technology.
- **T13:** `write_text` bound set below 1 MiB to fit the transport request bound under worst-case escaping (120 KiB; §8).
- **T14:** a richer files audit (workspace id, opaque ids, byte sizes, the handler's outcome) is deferred. The audit is the generic `authorize` row (§11).
- **T15:** `files.fetch_url`, a server-side fetch of an arbitrary client-supplied URL, is not built (ADR-019 Amendment 1). Its fallback condition is unmet: the Abacus sandbox reaches the ticket routes over HTTP. Only a native handle's `download_url`, under §17.2's controls, is ever fetched.
- **T16:** embedded base64 blobs in tool results are not used for files: at 5 MiB ChatGPT put the base64 into model context and delivered no file. Outbound bytes leave as a ticket route or a `resources/read` stream (§17.3).
- **T17:** a handle ingest is one call bounded by the remote MCP call timeout (30 s) and the fetch deadline (default 25 s); there is no background or resumable handle fetch. A file that cannot be fetched inside the deadline is `file_handle_refused`; the client uses the ticket route where its sandbox can.

## 16. Operator residuals

- NAS ACL: grant the service UIDs (`MY_PA_UID`, `MY_PA_REMOTE_UID`) read-write with inheritance on the workspace subtree, keeping it usable by the owner over SMB.
- Mount overlays for gateway and remote MCP, binding the subtree to `/srv/my-pa/workspaces/mcp` with the §9 environment.
- Cloudflared re-render with the two byte-route path rules, then a restart.
- Production migration and the `files.*` grants per client (`file_workspace_read`, and `file_workspace_authoring` with write).
- Proof of a scheduled Abacus run using the reference client.
- Backup and retention policy for the subtree, including `.my-pa/versions` and `.my-pa/trash`.

## 17. Native file handles and MCP resource delivery (ADR-019 Amendment 1)

The seventeen names are unchanged. A client that sends no `source_file` and reads no resource is served exactly as §§1-16 describe, so there is still no code path that branches on client identity: the handle field and the resource link are on the one contract every client sees, and only a client that can use them does.

### 17.1 Client compatibility (synthetic proof, 2026-11-15)

| Capability | ChatGPT (`openai-mcp/1.0.0`) | Abacus (`mcp 0.1.0`) |
|---|---|---|
| Inbound native handle (`openai/fileParams`) | Yes: 1 KiB, 5 MiB, 50 MiB, two files in one call, SHA-256 exact | No: the attachment is only a sandbox path; no handle is passed |
| Inbound through the ticket routes (sandbox HTTP) | No: the sandbox cannot resolve external hosts | Yes: 1 KiB and 5 MiB, SHA-256 exact |
| Outbound MCP `resource_link` read through `resources/read` | Yes: 1 KiB, 5 MiB, 50 MiB delivered as files, SHA-256 exact | Not delivered as a file (the link block only) |
| Outbound embedded base64 blob | 1 KiB attached; 5 MiB landed in model context with no file (unusable) | Model-mediated only |
| Outbound https `resource_link` | Not delivered | Link visible only |
| Outbound through the ticket routes (sandbox HTTP) | No (DNS) | Yes: 5 MiB SHA-256 exact |
| Scheduled / unattended runs | No user attachment exists, so no inbound handle; list, search, read, `write_text` and organize work on files already in the workspace | Same |

Remaining unknowns: sizes beyond 50 MiB either way, the exact link lifetime (between 1 and 5 minutes), the publicly reported ~10% missing-file-param rate (0 of 5 observed), and Abacus tool lists cached until refreshed.

### 17.2 Inbound: `files.upload.begin` with `source_file`

- **Shape.** `source_file` is an object with exactly the properties `download_url` (string, required), `file_id` (string, required), `file_name` (string, optional) and `mime_type` (string, optional); any other key is `invalid_request` on `source_file`. `download_url` is at most 8,192 characters, `file_id` at most 256, `file_name` and `mime_type` at most 1,024. The canonical schema carries it under `payload`; the remote MCP schema publishes it as a top-level argument and declares `_meta["openai/fileParams"] = ["source_file"]` on the tool, and the remote boundary moves a top-level `source_file` under `payload` before `normalize` (one given in both places is `invalid_request`). `ttl_seconds` with `source_file` is `invalid_request` on `ttl_seconds` (no ticket outlives the call).
- **Untrusted.** `file_name` and `mime_type` are never used: the workspace path is the call's `path`, and there is no MIME handling (§8). `file_id` is not recorded. The handle is never authority: the write runs under the authenticated client's grants like any `files.upload.begin` (the write grant, and remote writes enabled).
- **Flow.** (1) The target is checked exactly as for a ticket (`exists` without `expected_version`, `version_conflict`, `not_found`, `unsupported_entry`) before any fetch. (2) The URL is fetched (below) and streamed into a fresh staging file under `.my-pa/staging/`; the store re-checks the disk reserve per chunk (`quota`) and the cap (`too_large`), and any failure discards the staging. (3) Then, under the workspace lock and the idempotency receipt of §5, an upload row is recorded and closed at once (its token is never issued), the staged length and SHA-256 are verified against the fetched values and any declared `size`/`sha256` (`digest_mismatch`), and the bytes are published by the same finalize rules: create, or replace at `expected_version` with the preimage preserved. The answer is `upload_id`, `entry`, `preimage_version_id`, `size` and `sha256`; nothing carries the URL. The intent digest binds `path`, `expected_version`, `size`, `sha256` and the handle's `file_id` digest, never the URL.
- **Fetch controls (proof finding F1, F2).** https only; no userinfo; port 443; the host must be a DNS name (not an IP literal) ending in an allowed suffix (`MY_PA_FILES_HANDLE_HOST_SUFFIXES`, with a label before it); the name is resolved once and every address must be public (not loopback, private, link-local, shared, reserved, multicast or unspecified, including IPv4-mapped, 6to4 and NAT64 forms); the connection is pinned to the first address, with TLS verified against the host name; `GET` with no credential, cookie or encoding; any status but 200 (a redirect included) is refused; a `Content-Encoding` other than identity is refused; a `Content-Length` over `MY_PA_FILES_MAX_UPLOAD_BYTES` is `too_large` before a body byte is read and one over the free space less the reserve is `quota`; the body is read in pieces of at most 1 MiB under a per-read idle bound and the whole-fetch deadline, and is `too_large` the moment it passes the cap; a body shorter or longer than its `Content-Length` is refused. At most 2 handle fetches run per process; another is `unavailable`. Every other failure is the one `file_handle_refused`.
- **The URL is a bearer credential (F1).** It is never logged, audited, persisted, put in an exception or returned. Its refusals carry only the field name and a reason token and are raised without a cause; the interaction log redacts `download_url`.
- **Operator diagnostic.** Every refused handle fetch writes exactly one server-log line (logger `my_pa.files.handle_fetch`, level WARNING): `files handle refused cause=<cause> host=<host>`. `cause` is an internal closed token (`host_not_allowed`, `not_https_or_fragment`, `ip_literal`, `port`, `url_shape`, `url_characters`, `url_type_or_length`, `url_unparsable`, `no_host`, `host_shape`, `host_length`, `host_labels`, `resolve_failed`, `non_public_address`, `deadline`, `deadline_or_closed`, `http_status_<n>`, `content_encoding`, `transfer_encoding`, `length_framing`, `connect_tls_or_http_error`, `read_error`, `short_body`, `long_body`, `declared_too_large`, `stream_too_large`); `host` is the URL's lowercased ASCII hostname (at most 100 characters) or `-`. Nothing else is logged: no scheme, userinfo, port, path, query, `file_id` or URL. The line is on the server log only -- never in the tool result (still the one `file_handle_refused`), the audit, a row or the interaction log. It is how an operator learns which host to add to `MY_PA_FILES_HANDLE_HOST_SUFFIXES`; the re-proof's refusal was `cause=host_not_allowed host=sdmntprcentralus.oaiusercontent.com`, which is why `.oaiusercontent.com` is now in the default. A suffix matches only at a label boundary: `.oaiusercontent.com` admits `x.oaiusercontent.com` and refuses `oaiusercontent.com`, `evil-oaiusercontent.com` and `oaiusercontent.com.evil.net`.
- **Missing handle.** A call without `source_file` is an ordinary ticket begin. A `source_file` without `download_url` or `file_id`, or of the wrong shape, is `invalid_request` on `source_file`, and nothing is staged.

### 17.3 Outbound: `files.download.begin` and `resources/read`

- **Result.** `files.download.begin` also answers `name` (the final component of the path the ticket serves) and `resource_uri`, `mcp-files://downloads/<download_id>`. On the remote MCP surface a successful call's result carries, after the envelope text block, a `resource_link` content block `{uri: resource_uri, name, mimeType: "application/octet-stream", size}`. The ticket token and route are unchanged, so a sandbox-HTTP client (Abacus) downloads as before.
- **Read.** The remote MCP server advertises resources: `resources/list` is empty and `resources/templates/list` names `mcp-files://downloads/{download_id}`. `resources/read` of a download URI is an authenticated `/mcp` request and needs no ticket token: the ticket must be a download ticket of this workspace owned by the request's Principal and issued to the same authenticated OAuth client, usable now (not expired), and the client's standing is re-checked exactly as the byte route's (remote access on, client enabled, an active grant for `files.download.begin` under `file_workspace_read`). The file is opened at the ticket's bound version (`external_change_detected` otherwise). A refusal is a JSON-RPC error whose message is the section 7 reason token (`ticket_invalid` covers unknown, expired and another client's ticket alike) and names no path.
- **Streaming.** The answer is one `BlobResourceContents` whose base64 is streamed from the open file in 768 KiB pieces, with an exact `Content-Length`, never buffered whole. The stream runs after the `/mcp` call slot and its timeout are released, under its own per-process cap (4, as the byte routes), the byte route's idle bound (30 s per send), deadline (600 s) and re-check (ticket and grants every 5 s, version before every piece). A failure after the headers left cuts the stream short of `Content-Length`; the client sees an incomplete response and reads again.
- **Not audited**, like a byte-route GET (§11).


### 17.4 Top-level primary file tools for compact-façade clients

A client served the compact façade (`my_pa.describe` / `my_pa.read` / `my_pa.write`) is **also** offered four primary file names as top-level MCP tools, under their canonical names verbatim: `files.upload.begin`, `files.download.begin`, `files.list` and `files.search` (operator ruling 2026-11-15; `FILES_COMPACT_TOP_LEVEL_NAMES` in `domain/identity/chatllm_capability_policy.py`). A native file param is filled only at the top level of the tool a client calls, which a façade wrapper cannot offer, so `files.upload.begin` carries its remote schema (top-level `source_file`) and `_meta["openai/fileParams"] = ["source_file"]` there.

- **An additional route, not a new capability.** No name is added. A top-level call takes the canonical path -- `compose_remote_arguments` (the server-stamped fresh idempotency key, the `source_file` lift), `normalize`, one `invoke` -- under the same grants, policy, audit and handler as the façade route. All 17 names stay reachable through `my_pa.describe/read/write` exactly as before, and the façade schemas are unchanged.
- **Listed only when callable.** A name is listed exactly when it is in the request's eligible canonical set: the plane composed (`FILES_WORKSPACE`), the client's grant for it, and remote writes enabled for `files.upload.begin`. A compact call to any other canonical name, or to one outside that set, is refused `unsupported` before `invoke`.
- **Outbound.** `files.download.begin` answers its `resource_link` whether called top-level or through `my_pa.read`.
- **Unverified against real ChatGPT.** The synthetic proof exercised a top-level tool whose file field was *required*; these four exact descriptors (an optional `source_file` on `files.upload.begin`) need a re-proof against ChatGPT before they are relied on, which the operator must authorize.

### 17.5 Agent-usable ticket transfers (sandbox-HTTP clients: Abacus)

Abacus has no native file handle (an attachment is only a path in its sandbox, and it refuses the file-object param), but its sandbox makes outbound HTTP calls: the proof moved 5 MiB byte-exact both ways through one-time routes, the agent handling the URL and token itself. Its parity with ChatGPT is therefore the **same capability surface** -- the same 17 names, and the same four top-level tools of §17.4 when it is served the compact façade -- plus a ticket answer an agent can act on with no manual step. There is still no `files.fetch_url` (T15) and no base64 path (T16).

- **`source_file` is optional and omitted by default.** Its description says it is only for hosts that supply file objects; a client that cannot supply one omits it (or sends `null`) and gets the ticket answer. The `openai/fileParams` declaration does not make it required.
- **`transfer`.** A ticket answer of `files.upload.begin` (without `source_file`) and of `files.download.begin` carries an additive object `transfer` with:
  - `method` -- `PATCH` (upload) or `GET` (download);
  - `url` -- the `route` joined to `https://<MY_PA_REMOTE_MCP_PUBLIC_HOST>` when that setting is set, else the relative `route`;
  - `auth_header_name` -- `Authorization`, whose value is `Bearer ` followed by the answer's `upload_token` / `download_token`;
  - `headers` -- the request headers besides authorization: for an upload `Upload-Offset` and `Upload-Complete` with `<sha256>` and `<length>` placeholders;
  - `usage` -- a short, deterministic text: a ready `curl` command for a single-request transfer that reads the token from the environment variable `MY_PA_FILES_TICKET` (the reference client's), the rule for resuming (upload: `HEAD` for `Upload-Offset`, then `PATCH` pieces of at most `chunk_max_bytes` with the last carrying `Upload-Complete`; download: `Range: bytes=<n>-`), and the follow-up `files.stat` with `include_sha256` to verify.
- **No secret in `transfer`.** It never contains a token: the token stays only in `upload_token` / `download_token`, shown once (§1.4). `transfer` is kept in an idempotency receipt like any non-token field.
- **The recipe is the route's real semantics** (§10): a completing `PATCH` (`Upload-Offset: 0`, `Upload-Complete: sha256=<hex>, length=<n>`, the whole body, at most `chunk_max_bytes`) finalizes through `files.upload.finalize` and so needs that grant; a download is `GET` with an optional single `Range`.
- **Unverified against the real deployed routes for Abacus** until a re-proof the operator authorizes; whether an Abacus *scheduled* task has a sandbox VM at all is unknown (§17.1, T11).

### 17.6 Browser download links (ChatGPT-class outbound; operator-authorized exception)

**Why.** At the 2026-11-15 re-proof the real ChatGPT runtime (`openai-mcp (Codex)`, protocol 2026-07-28) issued no `resources/read` for a returned `resource_link` (0 in 4 tests), while a human clicking an https link shown in the chat downloaded the file. The ticket route (§10) needs an `Authorization` header and refuses a query string, so it is not clickable. The operator authorized (2026-11-15) one bounded exception to the "no bearer in a URL" posture of §1.4 and §10: a single-use browser link.

- **Off by default; per client.** Only an OAuth client listed in `MY_PA_FILES_BROWSER_DOWNLOAD_CLIENT_IDS` gets one, and only when `MY_PA_REMOTE_MCP_PUBLIC_HOST` is set (with no public host the feature composes off and the process logs one operator warning at start). A local or unlisted caller's answer is unchanged.
- **Result.** `files.download.begin` then also answers `browser_download`: `{url, expires_at, single_use: true, instructions}`, where `instructions` is the static text "Show this link to the user as a clickable link. Do not fetch it yourself." `url` is `https://<MY_PA_REMOTE_MCP_PUBLIC_HOST>/files/v1/browser-downloads/<download_id>.<token>`. `resource_uri`, the `resource_link` and `transfer` are unchanged.
- **Token.** `gfwbd_` followed by 64 lowercase hex (32 CSPRNG bytes), distinct from the `gfwtk_` ticket token; only its SHA-256 digest is stored. It is a second download ticket row (its own `fwdnl_` id) in `knowledge.file_workspace_transfers` -- no migration -- bound to the Principal, the OAuth client (client reference), the workspace, the path or preserved version, and the version token observed at begin; TTL `MY_PA_FILES_BROWSER_DOWNLOAD_TTL_SECONDS` (default 300 s, at most 900 s). The URL segment carries the row id beside the token so the row is found by primary key and the digest compared in constant time (as for tickets), never by a digest lookup.
- **Single use.** A GET that sends the whole body settles the row (`expired`); a HEAD never does, and neither does an interrupted or failed GET. One GET per link at a time per process; across processes two GETs started together may both complete (documented, not claimed closed).
- **Route.** `GET|HEAD /files/v1/browser-downloads/{download_id}.{token}`, remote MCP process only, sharing the byte routes' slot cap and pre-slot authentication cap. **Every refusal is one undistinguished `404` with an empty body**: an unknown, malformed, expired or consumed link, a query string, any other method, the feature off, the client no longer allowlisted, disabled or revoked, the `files.download.begin` grant gone, the file's version changed, the entry gone, or no free slot. The same checks are repeated every 5 s while streaming, and the version before every piece; a change after the headers left stops the stream short.
- **Response.** `200` (no `Range`), `Content-Type: application/octet-stream` always, `Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<percent-encoded>` (the final path component with path separators, control characters, quotes, `;` and `%` removed from both forms, non-ASCII replaced by `_` in the ASCII form, `download` if nothing is left), `Content-Length` exact, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: sandbox`. The body streams and is never buffered whole. HEAD answers the same headers with no body.
- **The token never leaks.** It is not logged (production uvicorn runs `access_log=False`; the route logs nothing but the completion line), not in the interaction log (it redacts every `gfwbd_` token and every `url` key), not in an audit row, receipt (`files.download.begin` is a read and keeps none) or error.
- **Audit.** Like the byte routes, a browser GET is not audited (§11); a completed one writes one operator server-log line (logger `my_pa.files.browser_download`, INFO): `files browser download completed client=<oauth client id> size=<n>` -- no path, no token.
- **Tunnel.** The public tunnel needs one more path rule, `^/files/v1/browser-downloads/[^/]+$`, on the MCP hostname (operator-gated; `ops/nas/remote/cloudflared-config.example.yml`, `ops/runbooks/remote-mcp-cloudflare.md`).
- **Unverified** against real ChatGPT and the deployed tunnel until an operator-authorized re-proof.

