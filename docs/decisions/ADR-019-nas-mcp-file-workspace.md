# ADR-019: NAS MCP file workspace

- **Status:** Accepted by operator directive 2026-11-13
- **Decision ID:** `MYPA-FW-D-019`
- **Repository:** `RMF112018/my-pa`
- **Repository identity:** `main@57d5b1399d59d7afe9fe08063d9bb842c9062dd2` (branch `feat/files-workspace`)
- **Scope:** One new filesystem authority class, the *file workspace*, and the `files.*` capability family that mediates it. The frozen contract is [`../architecture/files-workspace-contract.md`](../architecture/files-workspace-contract.md). No deployment, NAS ACL, grant or production authority.

## Context

AGENTS.md §4 keeps original sources read-only and confines managed-document writes to designated managed storage, unless an accepted ADR supersedes those boundaries. ADR-008's filesystem authority table has no class a connected client may read and write as ordinary files and folders. The operator wants exactly that: one NAS folder that every connected client (ChatLLM, ChatGPT, Abacus, browser, CLI) can browse, upload to, download from and reorganize, through one neutral capability family. The folder is also edited directly by the operator over SMB and DSM, so the product cannot be its only writer.

Existing stores do not fit. Managed documents are content-addressed objects with no user-visible tree. Report content is bounded Markdown/attachments behind a 16 MiB transfer cap. Source roots are read-only by rule.

## Decision

1. **One new authority class, `workspaces`.** A file workspace is a single operator-configured root directory (`MY_PA_FILES_WORKSPACE_ROOT`) addressed by a logical alias (`MY_PA_FILES_WORKSPACE_ID`, default `mcp`). In production it is the NAS subtree bind-mounted at container path `/srv/my-pa/workspaces/mcp`, and only that subtree: `/volume1` and `/volume1/homes` are never mounted. With the root unset the plane is absent and its names are not composed.
2. **Product-mediated read-write for every connected client.** Every client uses the same `files.*` family through the existing capability, policy, audit and remote MCP paths. Access is gated only by existing per-client grants; there is no client-specific code or behaviour. Principal comes from authentication only.
3. **MY-PA is not the sole writer (FW-D04).** External edits are expected. Each entry carries an opaque version token derived from its filesystem fingerprint; a mismatch surfaces `external_change_detected` or `version_conflict`. The product claims no atomicity against external writers, only against its own mutations, which a per-workspace advisory lock serializes.
4. **No destructive loss.** Writes default to no-overwrite; a replace requires an explicit expected version, and the replaced content is preserved as a preimage version before the new content is published. Delete is recoverable trash only (FW-D05): there is no hard-purge capability, and trash retention is set by the operator later.
5. **Containment.** Paths are relative POSIX paths under the root, walked one component at a time with directory file descriptors and `O_NOFOLLOW`; symbolic links and special files are never followed or opened. No host path is ever returned. Staging, preimages and trash live in a reserved `.my-pa/` control directory inside the root, so every rename stays on one mount.
6. **Bytes stream outside model arguments.** Uploads and downloads go through short-lived, single-path ticket tokens on dedicated binary HTTP routes of the remote MCP process, never Base64 in tool arguments. A bounded inline UTF-8 text write (`files.write_text`, at most 120 KiB, set below the 1 MiB ceiling so that a worst-case escaped request fits the transport request bound; contract trim T13) is the only content-bearing tool argument.
7. **Boundaries kept.** Source roots stay read-only. The managed-documents store and the report-content store are unchanged. The workspace root must not equal, contain or lie inside any configured source, managed-document or report-content root; the store refuses to start otherwise.
8. **Minimum technology.** No new process, service, queue, index or storage technology. One additive Alembic revision holds ticket, version, trash and receipt metadata and admits the new names to the audit vocabulary.

## Amendment to ADR-008

This ADR narrowly amends ADR-008's filesystem authority table by adding one row:

| Path class | Container authority |
| --- | --- |
| `workspaces` | scoped read-write, for the gateway and remote MCP processes only, through the `files.*` capability family; one operator-configured subtree per workspace |

Nothing else in ADR-008 is amended or superseded. In particular, generic `/v1/{capability}` stays internal, and the new public routes are exact dedicated paths (`/files/v1/uploads/{id}`, `/files/v1/downloads/{id}`) admitted by the tunnel's path allowlist.

## Consequences

- 17 public capabilities and 2 purposes (`file_workspace_read`, `file_workspace_authoring`) join the audited vocabulary; none is operator-only. ChatLLM profile moves to `chatllm-data-v14` with every `files.*` name data-conditional on a new `FILES_WORKSPACE` prerequisite.
- Files written by the product are owned by the service UID; the operator must grant those UIDs read-write on the NAS subtree (Synology ACL with inheritance) so the folder stays usable over SMB. The `.my-pa/` control directory is visible to SMB users.
- Preimages and trash grow without bound until the operator sets retention. The workspace is not in the database backup; NAS-level backup of the subtree is the operator's.
- A public byte route enlarges the remote MCP host's attack surface; it is bounded by ticket authentication before any body read, size and concurrency caps, and per-request grant re-checks.
- External writers can race a product mutation in the window between its fingerprint re-check and its rename; this is documented, detected afterwards, and not claimed closed.

## Supersession

AGENTS.md is not amended: this ADR is the route AGENTS.md §4 names for changing its boundaries, and it changes them only by admitting the `workspaces` class. Adding a second writable class, writing to a source root, adding a hard purge, exposing host paths, letting a client choose an arbitrary root, or serving workspace bytes through generic `/v1/{capability}` requires a superseding ADR. Adding further workspace roots, exact NAS paths, UIDs, ACLs, limits and retention values are configuration or contract changes and do not by themselves supersede this decision.

## Amendment 1 (2026-11-15): native file handles and MCP resource delivery

- **Status:** Accepted by operator directive 2026-11-15 ("tear it down and proceed with implementation in my-pa"), after the synthetic P1-P5 interface proof. Implementation only: deployment, grants, production and the Cloudflare tunnel stay unauthorized.
- **Evidence:** the proof report (client compatibility matrix and security findings F1-F7) is summarized in contract section 17.1. ChatGPT passes a user-attached file to a tool that declares `_meta["openai/fileParams"]` as `{download_url, file_id, file_name?, mime_type?}`, where `download_url` is a short-lived Azure blob SAS link (usable at 60 s, refused by 300 s). ChatGPT reads an MCP-URI `resource_link` through `resources/read` and delivers it to the user as a file (1 KiB, 5 MiB and 50 MiB verified). Abacus passes no file handle but its sandbox reaches the existing ticket routes over HTTP.

Decision, within this ADR's boundaries (no new authority class, store, process or capability name; the seventeen `files.*` capabilities stay exactly as they are):

1. **Handle ingestion.** `files.upload.begin` gains one optional argument, `source_file` (the OpenAI file-object shape). Given one, the server fetches `download_url` itself, streams it into the existing staging area and publishes it through the existing finalize rules (no overwrite by default, `expected_version` to replace, preimage preserved) in the same call. It is an additive optional field on the one contract every client sees, not a per-client descriptor: a client that does not send it is served exactly as before. The remote MCP surface publishes it as a top-level argument with `_meta["openai/fileParams"] = ["source_file"]`, because that is the shape the client fills.
2. **Outbound through MCP resources.** `files.download.begin` additionally answers `name` and `resource_uri` (`mcp-files://downloads/<download_id>`), and on the remote MCP surface its tool result carries an MCP `resource_link` to that URI. `resources/read` of it streams the ticket's file as one base64 blob, under the same ticket, grant, expiry and version checks as the byte route, without buffering the file. Embedded base64 blobs in tool results are not used for files (contract trim T16). The ticket byte routes stay unchanged for clients whose sandbox makes its own HTTP calls.
3. **Primary file tools top-level for façade clients.** A compact-façade client is also offered `files.upload.begin`, `files.download.begin`, `files.list` and `files.search` as top-level MCP tools under their canonical names (operator ruling 2026-11-15, contract section 17.4): an additional route to the same capabilities, listed only when the client may call them; all 17 stay behind `my_pa.describe/read/write`. Their behaviour in real ChatGPT is unverified until a re-proof the operator authorizes.
4. **No `files.fetch_url`.** A server-side fetch of an arbitrary client-supplied URL is not built (trim T15): its fallback condition (a client that can neither pass a handle nor make HTTP calls) is not met, because the Abacus sandbox reaches the ticket routes.
5. **Controls (proof findings F1-F7).** The handle URL is a bearer credential: it is never logged, audited, persisted, returned or put in an error, and the MCP interaction log redacts `download_url`. The fetch is https only, to a host under an allowlisted suffix (default `.blob.core.windows.net`, `MY_PA_FILES_HANDLE_HOST_SUFFIXES`), resolved once with every address required to be public and the connection pinned to it, with no redirects, a whole-fetch deadline (default 25 s, at most 60 s) and a byte cap enforced before (`Content-Length`) and during the stream (`MY_PA_FILES_MAX_UPLOAD_BYTES`, the disk reserve). Client MIME types and file names are never trusted. An empty suffix list composes no fetcher and a handle is refused `file_handle_unsupported` (fail closed on platform drift). The proof's stub-only risks (F4, F6, F7) do not reach this repository.

The amendment adds two section 7 reason tokens (`file_handle_unsupported`, `file_handle_refused`) and two settings; it adds no capability, purpose, identifier kind, table, route or public tunnel path (handle fetches are outbound; resource reads ride `/mcp`).

## Implementation status

PR1 (this contract, the pure domain, and the filesystem store) and PR2 (migration, persistence, the seventeen `files.*` capabilities, policy and ChatLLM v14) are merged on `main`. PR3 (`feat/files-workspace-pr3`) delivers WP6 (the byte routes, the reference client and the ops artifacts) and WP7 (the synthetic vertical slice and documentation closure). The files audit is the generic `authorize` decision row only (contract §11); a richer files audit is deferred (contract trim T14). Deployment, the NAS mount overlay, NAS ACLs, tunnel route admission and client grants are operator-gated and not authorized by this ADR's acceptance. Amendment 1 is implemented on `feat/files-native-handles` (contract section 17); its deployment is operator-gated as well.
