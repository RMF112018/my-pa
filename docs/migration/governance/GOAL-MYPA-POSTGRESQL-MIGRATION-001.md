# GOAL-MYPA-POSTGRESQL-MIGRATION-001 — Migration Goal Charter

**Goal ID:** `GOAL-MYPA-POSTGRESQL-MIGRATION-001`
**Repository:** `RMF112018/my-pa`
**Active phase:** `PHASE-00`
**Active work item:** `WP-P00-01`
**Charter recorded at:** `2026-07-31T20:48:55Z`
**Bound base:** `d4fed7ec12f0b25ad5520d806aeb7766e95228d5` / tree `faf44a32ba54b13fb6ce75c25e4bf4cd4e2fa1c4`

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

`WP-P00-01` — the only currently authorized work item — binds migration identities and the
governance ledger against acceptance criteria `P00-AC-01` through `P00-AC-05`.

`P00-AC-06`, `P00-AC-07`, and `P00-AC-08` belong to `WP-P00-02`. `WP-P00-02` is not
activated, not authorized, and not implemented. No successor activates automatically.

## Identity bindings

| Identity | Value | Authority |
|---|---|---|
| Target repository | `RMF112018/my-pa` `main` @ `d4fed7ec12f0b25ad5520d806aeb7766e95228d5` | Local Git plumbing and read-only GitHub metadata |
| Target tree | `faf44a32ba54b13fb6ce75c25e4bf4cd4e2fa1c4` | Local Git plumbing |
| Legacy repository | `RMF112018/hb-personal-assistant` `main` @ `fc7386fb925bfcb7370f969ac737acee0d32ddd0` | Read-only GitHub repository metadata only |
| Legacy tree | `70c0b5647ffc7119be9ab28ae53f654fe2d463d2` | Read-only GitHub repository metadata only |
| Legacy schema version | `135` | Legacy `LATEST_SCHEMA_VERSION` at the authenticated legacy tree |
| Retained snapshot | SHA-256 `fa3631f7…f52a9`, `7417266176` bytes, not opened | Declared identity; the artifact was not accessed |
| Logical target identity | `my_pa` | `AGENTS.md` §4 and `ADR-002` |

Full values are recorded in `exact-identity.json` and `source-read-only-identity.json` beside
this charter. Those JSON records are authoritative for exact strings; this table is a reading aid.

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

## Invalidation

Any drift in target head or tree, legacy head, tree, or schema version, snapshot identity, plan
package hash, independent-review disposition, branch or worktree identity, authorized paths,
acceptance criteria, or mutation limits invalidates the governing authorization and every
acceptance result bound to it.
