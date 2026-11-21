# ADR-021 (PROPOSED) — SDCR subtree placement admission

- **Status:** PROPOSED — NOT OPERATOR-ACCEPTED
- **Issue:** RMF112018/my-pa#369
- **Target:** MY-PA Files workspace `mcp`, under API-relative `SDCR/` only.
- **Basis:** `SDCR-PATH-CONTROL-20261121-001` and the separately ratified future hybrid v3 target; existing ADR-019 and its Files contract remain normative until a valid amendment is accepted.

## Context

ADR-019 currently provides one neutral `files.*` interface, scoped by authenticated client capability grants, file-workspace boundaries, and generic file/path protections. It does **not** enforce project-specific owners, folders, or content-type routing. Legacy Google Drive acquired unregistered root-level artifacts and cross-work-item evidence.

Client-only checks are bypassable when another client can call `files.mkdir`, `files.write_text`, `files.upload.begin/finalize`, `files.copy/move/rename`, `files.trash` or `files.restore` directly.

## Proposed decision (not active)

Permit an **opt-in workspace subtree placement policy** at the existing Files store and upload-issuance boundaries, provided:
- It is configured from an operator-owned, read-only policy outside every writable Files/source/managed/report root; no client-supplied registration or path is authoritative.
- It is off by default and applies only to explicitly configured path prefixes; no new public capability or client identity-specific behavior.
- Every normal Files write into that subtree is admitted against a closed taxonomy and a registered work-item owner. Missing/unsafe configuration fails startup, not open.
- The public response uses the existing safe `invalid_path` refusal; the internal policy violation is auditable without leaking sensitive names.
- Copy/move/trash/restore transitions under the subtree are denied except through a separately accepted migration capability (NOT part of this candidate).
- Existing pre-cutover nonconforming paths remain preserved for inventory. No implicit migration or deletion.
- The publishing client remains responsible for truthful semantic artifact roles, session completeness, and source eligibility; structural admission alone is insufficient.
- NAS/SMB writes outside Files cannot be prevented by the application layer alone and require independent ACL restrictions or a downgraded detection-only assurance claim.

## Consequences and gates

A new optional bootstrap setting `MY_PA_FILES_SDCR_POLICY_FILE` loads the guard into the `mcp` workspace store. This PR introduces no active setting. Binding policy to real client grants, trusted auto-registration, actual server denial tests, alignment with Issue #365, and NAS ACL qualification remain separate required gates.

No new process, table, IAM grant, deployment action, or authority cutover is authorized. ADR-019's existing general capability behavior remains unchanged while this setting is unset.

**Operator ratification is required before treating this ADR as accepted, changing the frozen Files contract, or commissioning the guard.** A PR merge alone is not ratification or deployment permission.
