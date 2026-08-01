# GOAL-MYPA-POSTGRESQL-MIGRATION-001 — Migration Goal Charter

**Goal ID:** `GOAL-MYPA-POSTGRESQL-MIGRATION-001`
**Repository:** `RMF112018/my-pa`
**Active phase:** `PHASE-00` — `IN_PROGRESS`
**Charter first recorded at:** `2026-07-31T20:48:55Z`
**Charter reconciled at:** `2026-08-01T04:24:49Z`
**Charter non-recursive baseline correction recorded at:** `2026-08-01T05:35:09Z`

### Current state

| | |
|---|---|
| Initial governed work item | `WP-P00-01` |
| Current active work item | **none** |
| Last closed work item | `WP-P00-01` |
| Next eligible work item | `WP-P00-02` — `NOT_ACTIVATED` |
| Exact current repository identity authority | **runtime Git** (`main`) |
| Committed exact-current SHA/tree | **intentionally not stored** |

Exact current SHA and tree are resolved at authorization time from local and remote Git.
Committed records describe lifecycle state and historical provenance only. Post-commit identity
belongs in external evidence.

### Non-recursion rule

A governed repository record must not claim that an exact SHA embedded within that record is
the continuously current identity of the commit containing the record. Current identity is
resolved from runtime Git; committed exact identities are historical or input bindings only.

An embedded predecessor SHA must never be treated as the live current repository identity.

### Historical record

This charter was first written under `WP-P00-01`, whose authorization
`AUTH-MYPA-MIGRATION-WP-P00-01-20260731-001` bound base
`d4fed7ec12f0b25ad5520d806aeb7766e95228d5` / tree `faf44a32ba54b13fb6ce75c25e4bf4cd4e2fa1c4`
(`ORIGINAL_AUTHORIZATION_BASE`). That authorization is **consumed** and that base is
**historical**. Both are retained here as provenance, not as current authority.

The identity bindings in this charter remain accurate as the record of what `WP-P00-01`
authenticated. They are not restated as though they had always described the post-merge state.

Closeout correction squash merge (`MERGE_SHA`, PR #9):
`178a7e243cbc6100c6937144ff10a7987206c04a` / tree `25131169d7bbe7846569c2a3cb5afa2712bd3c96`.
That identity is also the `RECORD_BASE` of the non-recursive baseline correction; it is not
continuously current authority after later commits.

This charter is a governed record. It is not an authorization and it grants no access.

## Objective

Establish the governed structure under which `my-pa` migrates to its canonical PostgreSQL
metadata and knowledge store. The goal exists so that identity, authority, and evidence are
bound before any data, schema, or runtime work is considered.

`AGENTS.md` §4 already fixes the durable architectural facts this goal operates under:
PostgreSQL is the canonical metadata and knowledge store, the logical database identity is
`my_pa`, and an existing physical compatibility alias does not authorize a rename, migration,
connection, or mutation. `ADR-002` records the deferred physical alias. This charter binds
governance to those accepted decisions rather than restating or extending them.

## Authority and precedence

Repository files govern implementation. When repository governance and an external
publication conflict materially, implementation stops and publishes a blocker; it does not
reinterpret or broaden scope. Drive publications are review and coordination surfaces, not a
competing ledger.

Precedence follows `AGENTS.md` §1: authenticated runtime evidence, then authenticated
repository and GitHub state, then accepted repository specifications and ADRs, then indexed
Workspace publications, then conversations and legacy repositories as claims.

## Phase 00 scope

Phase 00 binds governance and identity. It produces no data movement, no schema, and no
runtime code.

`WP-P00-01` bound migration identities and the governance ledger against acceptance criteria
`P00-AC-01` through `P00-AC-05`. It is **closed**: implemented at
`d60c25f51964fd2ae05211d0f3e9fef8d8f7f03f` (`IMPLEMENTATION_HEAD`), independently reviewed
`PASS` at that head, squash merged as `3e5aad7b2526b09b1e46c817bd00c401e569f5a4` (`MERGE_SHA`,
PR #8) with byte-identical content, post-merge validated, and cleaned up. A later closeout
correction squash-merged as `178a7e243cbc6100c6937144ff10a7987206c04a` (`MERGE_SHA`, PR #9).
Final closeout remains blocked by `MYPA-WP-P00-01-FINAL-CLOSEOUT-F-001` until the
non-recursive baseline correction is independently reviewed.

`P00-AC-06`, `P00-AC-07`, and `P00-AC-08` belong to `WP-P00-02`. `WP-P00-02` is not activated, not
authorized, and not implemented. No successor activates automatically. Phase 00 therefore remains
`IN_PROGRESS` with no active work item.

## Identity bindings

**Historical.** This table records identities with explicit roles. Exact current repository
identity is **not** listed here; resolve it from runtime Git at authorization time.

| Identity | Value | Role / Authority |
|---|---|---|
| Target repository — historical WP-P00-01 base | `RMF112018/my-pa` `main` @ `d4fed7ec12f0b25ad5520d806aeb7766e95228d5` | `ORIGINAL_AUTHORIZATION_BASE` |
| Target tree — historical WP-P00-01 base | `faf44a32ba54b13fb6ce75c25e4bf4cd4e2fa1c4` | `ORIGINAL_AUTHORIZATION_BASE` |
| WP-P00-01 implementation squash merge | `RMF112018/my-pa` `main` @ `3e5aad7b2526b09b1e46c817bd00c401e569f5a4` | `MERGE_SHA` (PR #8); historical |
| WP-P00-01 implementation merge tree | `9956fe7bed3b2d92e7243b1881f5b31c2d28da1d` | `MERGE_SHA` tree; historical |
| Closeout correction squash merge | `RMF112018/my-pa` `main` @ `178a7e243cbc6100c6937144ff10a7987206c04a` | `MERGE_SHA` (PR #9) / `RECORD_BASE` for non-recursive correction; historical after later commits |
| Closeout correction merge tree | `25131169d7bbe7846569c2a3cb5afa2712bd3c96` | `MERGE_SHA` / `RECORD_BASE` tree |
| Legacy repository | `RMF112018/hb-personal-assistant` `main` @ `fc7386fb925bfcb7370f969ac737acee0d32ddd0` | Read-only GitHub repository metadata only |
| Legacy tree | `70c0b5647ffc7119be9ab28ae53f654fe2d463d2` | Read-only GitHub repository metadata only |
| Legacy schema version | `135` | Legacy `LATEST_SCHEMA_VERSION` at the authenticated legacy tree |
| Retained snapshot | SHA-256 `fa3631f7…f52a9`, `7417266176` bytes, not opened | Declared identity; the artifact was not accessed |
| Logical target identity | `my_pa` | `AGENTS.md` §4 and `ADR-002` |

Full values for the original WP-P00-01 identity attestation are recorded in
`exact-identity.json` and `source-read-only-identity.json` beside this charter. Those JSON
records are historical WP-P00-01 evidence and must not be rewritten as current repository
identity. This table is a reading aid.

## Source authority

The legacy SQLite source and the retained snapshot are read-only historical evidence. Reading,
opening, connecting to, querying, copying, moving, renaming, mutating, deleting, or retiring
either of them is unauthorized. Recording an identity confers no access. Any future access
requires a separate explicit operator authorization naming the exact source, read scope, and
evidence contract.

The legacy repository may supply behavioural evidence, edge cases, and migration knowledge. Its
architecture is not authoritative and must not be copied wholesale.

## Naming

New repository paths, runtime identities, external API names, and MCP capability names use the
neutral `my_pa` / `MY_PA_` namespace. The legacy identity appears only inside explicit
compatibility and evidence records such as `source-read-only-identity.json`.

## Prohibitions carried by this goal

No runtime migration code, DDL, ETL, control plane, or loader. No database, SQLite, snapshot, or
PostgreSQL access. No dependency or CI change. No product functionality. No source-data
processing or target-data creation. No legacy rename or mutation. No broad refactor. No push,
pull request, merge, deployment, cutover, cleanup, retirement, or risk acceptance. No automatic
successor activation. No self-authorization and no self-review.

## Evidence and review

Each authorized work item produces durable, content-safe evidence under
`evidence/migration/<work-item-id>/` bound to the exact implementation head. Evidence excludes
credentials, connection strings, absolute operator host paths, personal data, message bodies,
document contents, and raw source or snapshot payloads. Failed validation is preserved verbatim.

An implementing agent may record demonstrated evidence but may never mark its own work `PASS`,
`APPROVED`, `VERIFIED_FIXED`, `READY_TO_MERGE`, `MERGED`, or `COMPLETE`. Acceptance is
determined by independent review against the exact head. Any later commit invalidates prior
criterion results and the review bound to them.

## Branch cleanup after a squash merge

A program-wide rule, established from `WP-P00-01` and reusable by every later work item.

After a squash merge, failure of `git branch -d` due solely to non-ancestry **does not** establish
unique branch content. Squashing creates a new commit whose history excludes the source, so the
feature head is permanently non-ancestral and the check fails deterministically regardless of
content. The check is a conservative proxy for content loss, and in this situation it returns a
false positive.

Forced local deletion with `git branch -D` is permitted **only** when all of the following exist:

1. exact operator authorization naming one branch and one SHA;
2. merged `main` and the feature head have identical trees;
3. the branch-to-`main` diff is empty;
4. all contributed blobs are present in `main`;
5. no branch-only paths exist;
6. the worktree is clean and not attached to the branch;
7. remote deletion occurs only after successful local deletion;
8. a verified cleanup receipt is published.

This rule authorizes nothing by itself. **Every destructive cleanup still requires an exact
operator decision.** Deleting both refs leaves the reviewed commit object unreferenced and
eventually collectible; its SHA must remain recorded in published evidence, and reviewers verify
against the merged baseline instead.

## Invalidation

Any drift between runtime Git and the exact identity bound in an authorization's external
activation package, or drift in legacy head, tree, or schema version, snapshot identity, plan
package hash, independent-review disposition, branch or worktree identity, authorized paths,
acceptance criteria, or mutation limits invalidates the governing authorization and every
acceptance result bound to it. Committed records do not store continuously current SHA/tree.
