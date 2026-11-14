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

## Implementation status

PR1 (this contract, the pure domain, and the filesystem store) is in progress on `feat/files-workspace`. Capabilities, policy, migration and persistence (PR2) and the byte routes, reference client and ops artifacts (PR3) follow. Deployment, the NAS mount overlay, NAS ACLs, tunnel route admission and client grants are operator-gated and not authorized by this ADR's acceptance.
