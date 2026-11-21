# SDCR Session Publisher — Issue #365

**Status:** Implementation candidate, not deployed; repository/Project policy authority unchanged.

This stdlib-orchestrated CLI uses the repository's existing MCP 2.x client and
`scripts/my_pa_files.py` reference byte-route implementation. It creates no
new MY-PA server, credentials, grants, tables, source connection or service.

## Interface

An agent puts **every generated deliverable**, including rejected drafts,
source ZIPs, failed test logs and evidence, beneath one output directory. The
publisher inventories the directory recursively. Only tool caches (`__pycache__`,
`.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.pyc`, `.pyo`) are excluded and
counted; a symlink refuses publication. No file is dropped just because an
artifact is a failed test or draft.

Create `session.json` outside the output folder (or inside it if intended to
archive the session specification):

```json
{
  "session_id": "SESSION-20261119-MYPA-365-001",
  "session_date": "2026-11-19",
  "work_item_id": "365",
  "program": "shared-platform",
  "workstream": "cross-client-publication",
  "source_client": "local-code-agent",
  "publisher_client": "local-code-agent",
  "execution_lane": "C",
  "next_action": "review PR and publication evidence",
  "artifact_statuses": {"failed-test.log": "FAILED_EVIDENCE"},
  "github": {
    "repo": "RMF112018/my-pa",
    "base_sha": "<actual 40-char SHA>",
    "head_sha": "<actual 40-char SHA>",
    "tree_sha": "<actual 40-char SHA>"
  }
}
```

Placeholders must be replaced with actual observed values. Spec IDs accept only
alphanumerics, dots, underscores and hyphens. Git identities are checked for
40-character lowercase hex. `artifact_statuses` is optional; unspecified files
are `FINAL`. Status values: `FINAL`, `DRAFT`, `FAILED_EVIDENCE`, `SUPERSEDED`,
`SOURCE`.

When a local code agent has a directly available, **already granted**, remote
MY-PA MCP endpoint and OAuth access token, invoke:

```sh
SDCR_MYPA_TOKEN="$EXISTING_AUTHORIZED_TOKEN" \
python scripts/sdcc_publish.py \
  --endpoint "https://<your-existing-mcp-host>/mcp" \
  --source-dir ./session-outputs --spec ./session.json \
  --repo-dir ./my-pa
```

`--repo-dir` is optional and read-only against the repository. Git capture
resolves the **actual worktree and Git metadata roots**, rather than trusting
`--repo-dir` as the top level. A session output equal to, inside, or containing
the worktree, Git directory, or common Git directory is refused. So are symlinked
output roots/ancestors, conflicting files, dirty worktrees, and incorrect SHA/tree
identity. After preflight the publisher creates `_git/changes.patch`,
`_git/changed-paths.txt` and `_git/IDENTITY.json` in the output directory.
It does not commit or push. All Git artifact writes are descriptor-relative,
use `O_NOFOLLOW` and exclusive creation, and check inode/device bindings;
same-byte replay does not overwrite previous evidence.

Repeat `--protected-root /absolute/known/root` for **each authoritative,
configured source or managed-data root** on the client machine. Every supplied
root must exist, and any parent/child overlap with the output root is refused.
The publisher cannot discover other clients' arbitrary source directories:
the operator/client must qualify the output as generated session evidence,
identify known protected roots and pass them explicitly. An undisclosed or
unidentified source root is **not** implicitly authorized as output. The
supported local writing environment is POSIX with directory FDs and no-follow
operations. OS rename privileges can still relocate an already-open output
directory, but cannot make descriptor-relative writes follow a substituted
symlink into a protected target.

The token is read from the environment, never argv, an output manifest or a
GitHub issue/PR. Missing or locally malformed authentication material, bad
HTTPS endpoint syntax and unavailable SDKs fail before Git capture writes.
The MCP client must initialize before local capture, but this does **not**
establish remote grant/receiver authority without an authorized real-client
qualification test. Do not place a token in a recorded shell command, saved
prompt or file. Configure it in the local agent's approved secret
injection mechanism. Grant setup and remote deployment are outside Issue #365.

## Storage protocol

**Proposed ADR-021 interoperability hold (not commissioned):** This Issue #365 publisher currently writes session artifacts at `artifacts/<relative-path>` plus session-root metadata. The separate Issue #369 default-off placement candidate proposes typed `artifacts/<role>/<artifact-id>__<filename>` and operator-registered ownership. The present publisher has **not** been qualified against that future guard, so activating `MY_PA_FILES_SDCR_POLICY_FILE`, ratifying ADR-021, or representing the two layouts as compatible requires a separately authorized alignment and client/receiver qualification. No source records, policy status, credentials, grants, or production settings are changed by this notice.

- Canonical owner path:
  `mcp:SDCR/20-Programs/<program>/workstreams/<workstream>/work-items/<id>/sessions/<session-id>/`.
- Each artifact is **create-only**. A retry accepts pre-existing identical
  size+SHA-256 and observed version; different bytes cause `PUBLICATION_INCOMPLETE`
  and no overwrite.
- The server computes stored bytes' SHA-256 via `files.stat` after upload.
  Source bytes are hashed again after transfer to detect a local race.
- Before any artifact bytes transfer, the publisher writes and SHA/verifies an
  immutable `SESSION_RECOVERY.json` with `NOT_READY`, plus the dated discoverable
  pointer `mcp:SDCR/40-Publication/sessions/YYYY/MM/<session-id>.recovery.json`.
  This immutable recovery pair binds the spec and exact inventoried file set; it
  survives manifest, registry or receipt errors and allows safe same-ID replay
  when the source, metadata and stored bytes are unchanged. A best-effort first
  `SESSION_PUBLICATION_FAILURE.json` records the initial failure; it never
  supersedes a later verified terminal receipt. Neither recovery nor failure
  records declare readiness.
- The publisher writes `SESSION_MANIFEST.json` via `files.write_text` only when
  the exact UTF-8 bytes fit 122,880 bytes; otherwise it uses the existing
  resumable, ticketed binary upload with size, SHA-256 and version readback.
  The declared 10,000-file bound is not reduced. Temporary metadata staging is
  outside the user output directory and is removed after transfer.
- The final immutable registry locator
  `mcp:SDCR/40-Publication/sessions/YYYY/MM/<session-id>.json` binds the
  verified manifest SHA/version but says `AWAITING_TERMINAL_RECEIPT`.
  `SESSION_PUBLICATION_RECEIPT.json` then binds the manifest, registry and
  recovery pointer hashes and versions. Only a verified terminal receipt
  may declare `READY_FOR_HANDOFF`. There is no multi-file transaction.
- A complete run reports `READY_FOR_HANDOFF` and a compact locator string. A
  withheld or failed artifact reports `PUBLICATION_INCOMPLETE` and exit 2.
  Incomplete manifests/receipts never authorize handoff. After a **terminal**
  incomplete receipt, issue a **new session ID** for corrected artifacts; do not
  rewrite the old evidence.
- Before using this with real content, the source owner/client must separately
  establish MY-PA disclosure eligibility and the completeness of the supplied
  output directory. `READY_FOR_HANDOFF` verifies the inventoried and published
  set; it is not proof that the caller discovered every session-generated file.
  Missing explicitly status-mapped files are refused before transfer. The
  publisher enforces Git and caller-supplied protected-root overlap checks,
  but qualifying otherwise unknown source/managed-data roots remains the
  originating client's obligation. It must not aim at a source root.
- Source material scanned as suspected live secret, private key or uninspectable
  ZIP is **not** uploaded. Manifest contains `PROTECTED_WITHHELD` and no raw
  content or hash. Plain S1 inputs go to authenticated MY-PA, never public GitHub.
  The built-in scanner is a narrow, high-confidence baseline **not complete DLP**;
  independent policy checks remain necessary for classified or otherwise
  restricted material.

The implementation uses `my_pa.read` / `my_pa.write` and `files.upload.begin`;
large bytes are transferred through the existing authenticated ticket route
using the reference client. The remote provider, OAuth grants, and HTTP route
reachability must be independently qualified before unattended client rollout.
No credentials are generated by this script.

## Synthetic tests

```sh
PYTHONPATH=. python -m pytest tests/unit/test_sdcc_publish.py -q
```

Tests use a fake in-memory files workspace: recursive inventory, raw bytes,
failed evidence, archive handling, multi-MB binary, no-clobber, retry,
versioned handoff, secret withholding, injection refusal, local Git patch
capture, source-root and worktree overlap refusal, no-follow ancestor/file
refusal, deterministic output/_git replacement races, malformed
endpoint/token preflight, and two-client receiver simulation. Race injections
establish protection against following substituted symlinks, not against an
adversary able to relocate a previously admitted directory inode. The fake
does not prove real ChatLLM/Abacus grants, OAuth, unattended GitHub Actions
network access, live MCP transport or deployment.

**Release boundary:** PR implementation and synthetic tests only. Do not use
this publisher to declare `MCP/SDCR/` authoritative until the operator-approved
migration/cutover is verified. If a client lacks MY-PA access, report
`INTEGRATION_GAP`; do not ask the operator to ferry ZIPs.
