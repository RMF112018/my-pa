# Relationship Intelligence final-completion traceability

**Campaign:** `MYPA-RI-FINAL-COMPLETION-CAMPAIGN-20260828-001`  
**Delivery model:** `STANDARD_TWO_GATE_DELIVERY` (non-AEOS)  
**Governing requirements:** Relationship Intelligence v0.2. The repository's
v0.3 document remains a demoted, non-authoritative proposal.  
**Audited base:** commit `4d2dec1e32ebcef9f11066b258b9ff4b1e48525d`,
tree `734fab4352279f949cb5b13a153b20850f0df3fa`  
**Repository:** `RMF112018/my-pa`

## Objective and boundary

Complete the bounded Relationship Intelligence identity-correction,
identity-history, re-enrichment, proposal/review, MCP/profile, security, and
verification gaps without reimplementing the accepted entity and Relationship
Memory planes.

Acceptance requires the three added public capabilities, additive persistence
only where current repository truth requires it, Principal isolation, exact
preview/apply binding, deterministic audit/history, bounded re-enrichment, MCP
and profile parity, and focused validation. Production commissioning and a
synthetic live canary receive procedures only.

Out of scope: merge or deployment; production/shared database access; live
personal data or NAS traversal; grant, OAuth, credential, or source-system
mutation; managed-document mutation; broad provider work; and acceptance of
operator-reserved risk.

## Authoritative external records

| Record | Google Drive ID |
|---|---|
| Campaign record | `1RmRKJsDGOJKAtGLynjLXeE-waymSfoimMK2wBU4K0co` |
| MCP completion contract | `1FZTU0cwbMePKMmXSijZ4xrZ-hTalbea9jXoVxT0rhwk` |
| Persistence completion contract | `15vQEUQUVc1mXDKXOAdRztJ4tJ3XvCjz3D3mc6m6ymLw` |
| Completion plan | `11fZH2EwtMN2XL6leuVk8a-mHyW4UJbcxw-IN44QUEM0` |
| Test contract | `1_lNYEO0iTd_EV-1OODmB0i40oZzbODUf6MzvZywFEd8` |
| Gap record | `1n-Vfdt5Db2690Bm6fYp9fXZY4B9WHbanCb3TqnqtvPE` |
| 2026-08-28 live-evidence package | `1YH5eGzM84qYR1WpuNmamoAOtAe7NNuDv` |

The IDs are identifiers and traceability anchors, not runtime configuration.

## Work-package disposition

| Work package | Repository result | Disposition |
|---|---|---|
| `RI-FC-WP-01` Identity Correction | Governed split preview/apply is the exact inverse of one completed merge; stale state, digest, source-operation, Principal, and one-settlement guards fail closed. | IMPLEMENTED |
| `RI-FC-WP-02` Identity History | One authoritative keyset-paginated history joins direct mutations, completed identity operations/effects, and legacy merge lineage without scraping proposal/review records. | IMPLEMENTED |
| `RI-FC-WP-03` Re-enrichment | Nine exact triggers create immutable bindings; bounded lease/retry states and stale-before-apply checks prevent obsolete derived work from applying. | IMPLEMENTED |
| `RI-FC-WP-04` Proposal/Review | Generated discriminated payload schemas cover all proposal families; accepted merge/split proposals produce operator-preview handoffs and never execute identity correction. | IMPLEMENTED |
| `RI-FC-WP-05` Security/Principal | `version_content(version_id)` remains an internal method behind the already Principal-scoped capture workflow; no RI capability can invoke it directly. | `NOT_APPLICABLE_TO_RI_FINAL_COMPLETION` |
| `RI-FC-WP-06` MCP/Profiles/Documentation | The added public capability names, neutral commands, schemas, dispatch, purpose/profile bindings, runbooks, and current-state counts are synchronized. | IMPLEMENTED |
| `RI-FC-WP-07` Test/Mutation Audit | Unit, contract, security, architecture, concurrency, migration-shape, and isolated-database tests cover the new paths and known escape classes. | IMPLEMENTED |
| `RI-FC-WP-08` Commissioning | A fail-closed commissioning procedure is documented in `ops/runbooks/relationship-intelligence.md`. | PROCEDURE_ONLY_NOT_EXECUTED |
| `RI-FC-WP-09` Synthetic live canary | A non-personal synthetic canary and rollback procedure is documented in the same runbook. | PROCEDURE_ONLY_NOT_EXECUTED |

## Public Relationship Intelligence capability matrix

All entries use the existing application authorization, Principal, purpose,
policy, and audit path. “Existing” means unchanged capability behavior was
revalidated; “added” means this campaign publishes the capability for the first
time.

| Plane | Capability | Campaign disposition |
|---|---|---|
| Review | `review.list` | Existing, revalidated |
| Review | `review.decide` | Existing, revalidated |
| Entity read | `entities.search` | Existing, revalidated |
| Entity read | `entities.get` | Existing, revalidated |
| Entity read | `entities.resolve` | Existing, revalidated |
| Entity read | `entities.context` | Existing, revalidated |
| Entity read | `entities.relationships` | Existing, revalidated |
| Entity read | `entities.unresolved_mentions` | Existing, revalidated |
| Entity read | `entities.identifiers.list` | Existing, revalidated |
| Entity read | `entities.aliases.list` | Existing, revalidated |
| Entity write | `entities.create` | Existing, revalidated |
| Entity write | `entities.update` | Existing, revalidated |
| Entity write | `entities.archive` | Existing, revalidated |
| Entity write | `entities.restore` | Existing, revalidated |
| Entity write | `entities.identifiers.bind` | Existing, revalidated |
| Entity write | `entities.identifiers.retire` | Existing, revalidated |
| Entity write | `entities.identifiers.supersede` | Existing, revalidated |
| Entity write | `entities.aliases.add` | Existing, revalidated |
| Entity write | `entities.aliases.retire` | Existing, revalidated |
| Entity write | `entities.aliases.supersede` | Existing, revalidated |
| Entity read | `entities.assignments.list` | Existing, revalidated |
| Entity write | `entities.assignments.create` | Existing, revalidated |
| Entity write | `entities.assignments.revise` | Existing, revalidated |
| Entity write | `entities.assignments.end` | Existing, revalidated |
| Entity write | `entities.relationships.create` | Existing, revalidated |
| Entity write | `entities.relationships.revise` | Existing, revalidated |
| Entity write | `entities.relationships.end` | Existing, revalidated |
| Entity read | `entities.observations.list` | Existing, revalidated |
| Entity write | `entities.observe` | Existing, revalidated |
| Entity write | `entities.unresolved_mentions.resolve` | Existing, revalidated |
| Entity write | `entities.proposals.create` | Existing, revalidated |
| Identity correction | `entities.merge.preview` | Existing, revalidated |
| Identity correction | `entities.merge` | Existing, revalidated |
| Identity history | `entities.identity_history` | Added by `RI-FC-WP-02` |
| Identity correction | `entities.split.preview` | Added by `RI-FC-WP-01` |
| Identity correction | `entities.split` | Added by `RI-FC-WP-01` |
| Relationship Memory | `relationship_memory.create` | Existing, revalidated |
| Relationship Memory | `relationship_memory.get` | Existing, revalidated |
| Relationship Memory | `relationship_memory.list` | Existing, revalidated |
| Relationship Memory | `relationship_memory.search` | Existing, revalidated |
| Relationship Memory | `relationship_memory.history` | Existing, revalidated |
| Relationship Memory | `relationship_memory.revise` | Existing, revalidated |
| Relationship Memory | `relationship_memory.archive` | Existing, revalidated |
| Relationship Memory | `relationship_memory.restore` | Existing, revalidated |
| Relationship Memory | `relationship_memory.propose` | Existing, revalidated |

## Acceptance mapping

The campaign record's seventy-row map is reproduced here by exact identifier.
`MET` means repository evidence directly discharges the criterion. `PARTIAL`
means the bounded MCV slice provides only part of the broader outcome. `OUTSIDE`
means the criterion belongs to a deferred or operator-only surface. `BLOCKED`
means its frontend or runtime dependency remains explicitly blocked. `UNMET`
means no current repository evidence discharges it. The final exact-head review
row is updated only after that review completes.

| IDs | Disposition |
|---|---|
| `RI-AC-001`, `002`, `005`-`008`, `013`, `039`, `040`, `043`-`046`, `049`, `053`-`057`, `067`-`069` | MET |
| `RI-AC-003`, `009`, `011`, `012`, `014`-`016`, `018`, `020`, `028`, `030`, `035`, `036`, `041`, `042`, `048`, `058`-`060`, `066` | PARTIAL |
| `RI-AC-021`-`024`, `026`, `033`, `034`, `037`, `047` | OUTSIDE_FINAL_COMPLETION |
| `RI-AC-004`, `017`, `019`, `029`, `031`, `032`, `061`-`064` | BLOCKED_BY_DEFERRED_FRONTEND_OR_RUNTIME |
| `RI-AC-010`, `025`, `027`, `038`, `050`-`052`, `065` | UNMET |
| `RI-AC-070` | PENDING_EXACT_HEAD_INDEPENDENT_REVIEW |

## Test and migration evidence

The final pull-request head owns the authoritative results. The implementation
uses these evidence classes:

- static: Ruff format/lint, configured mypy, `git diff --check`;
- FAST: the repository's exact non-database marker expression;
- focused application/transport/security/concurrency: identity correction,
  identity history, re-enrichment, proposal/review, remote exposure, Principal
  isolation, and profile parity;
- migration: a single Alembic head and offline SQL generation, with historical
  digest settlement deliberately fail-closed offline because canonical digests
  are data-dependent;
- isolated PostgreSQL: collection and migration/test mapping only in this
  environment because `MY_PA_DATABASE_URL` is unset.

| Evidence | Exact result |
|---|---|
| Claimed-count guard | `16 passed in 64.85s` |
| FAST | `14164 passed, 1543 deselected in 582.13s` |
| Architecture, permission-matched synthetic local fixtures | `4706 passed in 303.78s` |
| Architecture, restricted-sandbox attempt | `4703 passed, 3 failed in 296.28s`; all three failures were `PermissionError: [Errno 1]` at synthetic local TCP/Unix socket bind, and the permission-matched rerun above passed |
| Focused transport | `447 passed, 1 deselected` |
| Transport parity | `257 passed` |
| Policy/security exhaustive | `582 passed` |
| Focused schema/relationship | `126 passed, 434 deselected` |
| Identity history/privacy/transport | `362 passed` |
| Entity privacy regression | `96 passed` |
| Remote-request replay | `55 passed` |
| Ruff format | `1135 files already formatted` |
| Ruff lint | `All checks passed!` |
| mypy | `Success: no issues found in 304 source files` |
| Whitespace | `git diff --check` passed |
| Alembic graph | one head: `8e1c4a7b2d90` |
| Alembic offline SQL | passed with a synthetic non-connecting PostgreSQL URL; the preceding no-URL attempt failed closed as required |
| Isolated PostgreSQL affected set | `27` tests collected; not executed because `MY_PA_DATABASE_URL` is unset |

The full database tier is not required by the campaign exception rule and was
not run: `FULL_DB_TIER_NOT_RUN_TARGETED_EVIDENCE_SUFFICIENT`. No production,
shared, or live-personal-data system was used.

## Operator-only remaining actions

After an eligible pull request is reviewed against its exact head, the operator
still owns merge, production/runtime commissioning, the WP-09 synthetic canary,
deployment or activation, all credential/grant/OAuth changes, and every live or
personal-data decision. This campaign performs none of those actions.
