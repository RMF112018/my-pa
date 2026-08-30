# Relationship Intelligence final-completion traceability

**Campaign:** `MYPA-RI-FINAL-COMPLETION-CAMPAIGN-20260828-001`
**Delivery model:** `STANDARD_TWO_GATE_DELIVERY` (non-AEOS)
**Governing requirements:** Relationship Intelligence v0.2. The repository's
v0.3 document remains a demoted, non-authoritative proposal.
**Audited base:** commit `4d2dec1e32ebcef9f11066b258b9ff4b1e48525d`,
tree `734fab4352279f949cb5b13a153b20850f0df3fa`
**Delivered head:** commit `8d5e1d01b209eae1169c4f60c79c6c2c2dc89eb4`,
tree `beb3fe4ae548ee9613c5df70ca8e77173c284504`
**Repository:** `RMF112018/my-pa`

Corrected 2026-08-29. This header stated the audited base alone. `4d2dec1` is
`8d5e1d0~1`, and **this file did not exist at `4d2dec1`**: `8d5e1d0` created it,
all 305 lines (`git show --stat 8d5e1d0` names it as an addition). So the base
line, read by itself, invited a reader to take the audit as covering the
document making the claims. It did not, and could not. The audited base is
retained because it is the true basis of the evidence recorded below; the
delivered head is stated beside it because that is where this document — and the
work-package dispositions in it — actually live. Figures in the validation table
below were measured at that base and are labelled as such; where the tree has
since moved, the current figure is in
[`docs/plans/relationship-intelligence-implementation-plan.md`](../plans/relationship-intelligence-implementation-plan.md)
section 4a, which is bound to collection by
`tests/architecture/test_claimed_test_counts_match_collection.py`.

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
| `RI-FC-WP-01` Identity Correction | Governed split preview/apply restores the semantics of one completed merge with fresh monotonic concurrency tokens; stale state, digest, source-operation, Principal, and one-settlement guards fail closed. | IMPLEMENTED |
| `RI-FC-WP-02` Identity History | One authoritative keyset-paginated history joins direct mutations, completed identity operations/effects, and legacy merge lineage without scraping proposal/review records. | IMPLEMENTED |
| `RI-FC-WP-03` Re-enrichment | All **nine** exact triggers are registered from truthful authorized mutations (corrected 2026-08-29: this cell said "Seven", while the "Load-bearing and mutation controls" table below said "nine-trigger enum"; RI v0.2 section 27.4 lists nine, `ReenrichmentTrigger` declares nine, the `entity_reenrichment_work.trigger` CHECK in `8e1c4a7b2d90` admits nine, and `tests/architecture/test_reenrichment_trigger_callers.py::test_direct_generic_and_version_observers_cover_all_nine_trigger_families` asserts the reached set equals `set(ReenrichmentTrigger)`); source-version and model/rule-version changes use exact version-observation hooks after a verified fetch or newly created authenticated proposal. Fixed-Principal startup observes before serving. Entra HTTP observes the exact server-resolved Principal inside the identity transaction before authentication returns, while authenticated remote MCP observes its exact resolved Principal before publishing request context. First and unchanged observations are no-ops. Every subject/input/producer/policy key and value matches the exact `CurrentReenrichmentBindings` lookup used at apply. All registration shares the same Principal-fenced unit of work. Immutable bounded bindings, Principal/work locks, database-time lease checks, post-apply currency validation, and atomic settlement prevent obsolete or duplicate derived mutation. | IMPLEMENTED |
| `RI-FC-WP-04` Proposal/Review | Generated discriminated payload schemas cover all proposal families; accepted merge/split proposals produce operator-preview handoffs and never execute identity correction. | IMPLEMENTED |
| `RI-FC-WP-05` Security/Principal | `version_content` and `span_faults` require a resolved Principal context and predicate `capture_versions.owner_principal_id`; foreign and absent opaque identifiers have the same result. Two-Principal controls make deletion of either predicate fail. | IMPLEMENTED_CORRECTIVE |
| `RI-FC-WP-06` MCP/Profiles/Documentation | The added public capability names, neutral commands, schemas, dispatch, purpose/profile bindings, runbooks, and current-state counts are synchronized. | IMPLEMENTED |
| `RI-FC-WP-07` Test/Mutation Audit | Executable non-database unit, contract, security, architecture, transport, and migration-shape tests exercise the new paths and known escape classes. The broader isolated-PostgreSQL concurrency selection was collection-only; later focused Relationship Memory corrections executed `82 passed` plus `5 passed` unequal-version cases, as recorded below. | IMPLEMENTED_PENDING_FRESH_EXACT_HEAD_REVIEW |
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
| `RI-AC-070` | PENDING_FRESH_EXACT_HEAD_INDEPENDENT_REVIEW_AND_CI |

## Test and migration evidence

The table distinguishes the final corrective-tree execution from preserved
historical receipts. The final pull-request head must retain this tree content,
pass CI, and receive a fresh independent exact-head review. The implementation
uses these evidence classes:

**Every figure in the table below is a receipt from a run at the audited base
and is not restated as a current measurement.** Stated here rather than beside
each row, added 2026-08-29: the tree has moved since, so `424` source files for
`mypy` and head `8e1c4a7b2d90` were true when printed and are not true now. The
figures that must track the tree are the ones in
[`docs/plans/relationship-intelligence-implementation-plan.md`](../plans/relationship-intelligence-implementation-plan.md)
section 4a, which `tests/architecture/test_claimed_test_counts_match_collection.py`
holds to collection. A receipt is preserved rather than rewritten; a current-state
figure is corrected.

- static: Ruff format/lint, configured mypy, `git diff --check`;
- FAST: the repository's exact non-database marker expression;
- focused application/transport/security/concurrency: identity correction,
  identity history, re-enrichment, proposal/review, remote exposure, Principal
  isolation (including capture-version and proposal-span validation), and
  profile parity;
- migration: a single Alembic head and offline SQL generation, with historical
  digest settlement deliberately fail-closed offline because canonical digests
  are data-dependent;
- isolated PostgreSQL: the immutable-origin and proposal-token corrective cycles
  each used a separately named, localhost-only PostgreSQL 17.10 container from
  the already-cached image. Auto-remove identity was verified before use;
  focused tests created and dropped their own databases, and each container was
  then stopped and confirmed removed.

| Evidence | Exact result |
|---|---|
| Integrated corrective FAST | `14,243 passed, 1,562 deselected` |
| Integrated corrective architecture | `4,712 passed` |
| Exact-observer focused unit/contract/architecture set | `65 passed in 0.82s` |
| Startup lifecycle, re-enrichment, and affected child-process set | `74 passed in 4.91s` |
| Authenticated-Principal observation and re-enrichment focused set | `81 passed in 0.71s` |
| Preserved pre-final parallel FAST attempt | `3 failed, 14,238 passed, 1,551 deselected in 583.07s`; the three child processes used an intentionally unreachable database and exited at the new fail-closed startup observer before reaching their transport assertions; the tests now isolate only that separately proven observer boundary |
| Exact-observer and currency-alignment affected set | `296 passed in 1.03s` |
| Integrated focused application/contract set | `201 passed, 7 deselected` |
| Integrated focused architecture/schema/domain set | `960 passed, 81 deselected` |
| Integrated focused concurrency/schema set | `114 passed, 457 deselected` |
| Ruff format | `1,140 files already formatted` |
| Ruff lint | `All checks passed!` |
| mypy | `Success: no issues found in 424 source files` |
| Whitespace | `git diff --check` passed |
| Alembic graph | one head: `8e1c4a7b2d90` — the head at the audited base. The chain has since taken the additive corrective `b727e870d45e`, which is the single head at the delivered head and after; `alembic heads` is the derivation |
| Alembic offline SQL | passed with a synthetic non-connecting PostgreSQL URL; the preceding no-URL attempt failed closed as required |
| Isolated PostgreSQL affected persistence set | `121` tests collected from `test_entity_reenrichment.py`, `test_identity_correction_ledger.py`, and `test_identity_correction_merge.py`; source, producer, and generic mutation builders have real `SqlCurrentReenrichmentBindings` callback/stale contracts, and Relationship Memory merge/split has monotonic-token, stale-command, immutable-origin, and proposal-token rebound regressions; eight focused Relationship Memory cases were executed across the immutable-origin and proposal-token corrections, so no pass is claimed for the other 113 |
| Entra production-composition persistence set | `33` tests collected from `test_entra_authentication.py`, including the durable initial/repeat/policy-advance observer contract; outside the immutable-origin focused database selection and not executed, so no database pass is claimed |
| Immutable-origin PostgreSQL correction | `82 passed`: `3` focused proposal→merge→accept/correct-and-accept/reprocess regressions, all `68` Relationship Memory review persistence tests, and `11` database-marked Relationship Memory capability tests; each module migrated a fresh disposable database to head |
| Proposal-token PostgreSQL correction | `5 passed, 81 deselected in 10.48s`: unequal-version proposal→merge→accept/correct-and-accept and proposal→merge→split→accept/correct-and-accept/reprocess; each case also proves stale external subject-version CAS, stale review-version refusal, Principal isolation, atomicity, and preserved immutable origins |

The full database tier is not required by the campaign exception rule and was
not run: `FULL_DB_TIER_NOT_RUN_TARGETED_EVIDENCE_SUFFICIENT`. No production,
shared, or live-personal-data system was used.

## Findings closure

The following findings were corrected before the frozen FAST gate. Independent
review finding 4 additionally identified stale documentation claims; this
corrective reconciles those claims but remains pending fresh-head tests, CI, and
independent review:

1. MCP catalog order now follows the closed `Capability` order filtered by the
   implemented command map; transport schemas, annotations, and fixture maps
   include all three added capabilities.
2. Identity history first verifies the requested entity through the
   Principal-partitioned entity repository, so a foreign entity identifier is
   indistinguishable from an absent one.
3. The new capability names are frozen into the migration's audit vocabulary;
   upgrade and downgrade both restate the closed constraint without deriving a
   historical revision from a mutable runtime enum.
4. Revision, table, model, capability, and publication counts were reconciled
   to one Alembic head, 77 revisions, 47 tables, 60 relationship dataclasses,
   104 application capabilities, and 55 default MCP tools. Superseded in part
   2026-08-29: the chain is now 78 revisions at single head `b727e870d45e`,
   `b727e870d45e` being additive on `8e1c4a7b2d90`. Superseded again 2026-08-30:
   the chain is now 79 revisions at single head `7e114f822af2`, additive on
   `b727e870d45e` and adding the `entity_names`/`entity_organization_profiles`
   tables (RI-ENT-WP-02, outside this completion campaign). The capability
   figure (104) and the default MCP tool figure (55) are unchanged. The
   2026-08-28 figures are kept as the record of what was reconciled then.
5. The entity privacy sweep derives all 34 entity capabilities and now collects
   96 cases; the remote profile distinguishes 11 reads from 23 writes.
6. Split preview/apply joins the keyless write-replay map, preserving request
   digest and result replay behavior for the new operator-only writes.
7. Relationship Memory origin binding is immutable across merge/split, and
   generated proposal payloads cover every accepted review family without
   allowing review acceptance to execute identity correction.
8. The separately claimed architecture tier initially produced three
   restricted-harness `PermissionError` results for synthetic local sockets;
   the permitted rerun passed all 4,706 tests before the exact-observer correction. No repository correction was
   indicated or made for those harness-only failures. The final integrated
   architecture selection then passed all 4,712 tests.
9. Re-enrichment is composed into the production unit of work and gateway. A
   closed production caller inventory reaches all nine v0.2 triggers from
   truthful generic or specialized authorized mutations (corrected 2026-08-29:
   this said "seven"; the direct-caller, generic-mutation and version-observer
   sets together equal `set(ReenrichmentTrigger)`, which
   `tests/architecture/test_reenrichment_trigger_callers.py` asserts). Source-version and model/rule-version changes are not
   proxy mappings: exact observation hooks run after metadata/fetch agreement
   and authenticated proposal-origin resolution, respectively. First and
   unchanged observations are no-ops; advances register one deduplicated work
   item under the same Principal-fenced unit of work, and policy is excluded
   from the observed-version digest. Handler-attested stable receipt identities
   register new mutations only; replay, no-op, and invalidated-review results
   register nothing.
10. Claim recovery atomically marks expired final-attempt work `FAILED` before
    selecting reclaimable rows, so a dead final worker cannot leave a permanent
    `RUNNING` orphan.
11. Re-enrichment application now holds the Principal advisory lock and work-row
    lock through currency evaluation, mutation, post-mutation currency
    validation, and terminal settlement. PostgreSQL wall-clock lease predicates
    and a savepoint roll back a derived mutation if the lease expires or a
    binding becomes stale; the binding digest is the callback's idempotency key.
    Watermark observation takes the same Principal transaction lock, so a
    producer or policy version cannot advance between currentness validation and
    successful settlement.
12. Input and producer version collections are capped at 100 unique keys in the
    domain and by JSONB type/cardinality checks in the additive migration/schema.
13. Source, proposal-producer, and generic mutation builders now bind only exact
    SQL-readable subject versions and observed watermark keys. SQL-equivalent
    currency tests prove each newly registered binding reaches the apply callback,
    while source, proposal-state, producer-contract, and policy advances make the
    prior binding stale without weakening `assess_currency`.
14. Gateway startup now calls the server-owned version observer through the one
    shared composition executed by HTTP, stdio MCP, and remote MCP before any
    transport serves. Executable startup-path tests prove the exact process
    Principal/cause, initial and repeated no-op behavior, and changed-policy work.
15. The lease-rollback, watermark-fence, and stale-callback PostgreSQL tests no
    longer pass rejected helper doubles. They construct the exact transactional
    SQL current-binding view, a versioned synthetic entity, and matching input,
    producer, and policy watermarks. They were collected, not executed in that
    earlier corrective cycle; the later immutable-origin database authorization
    did not broaden to this unrelated selection.
16. Entra HTTP no longer skips policy observation when the process has no fixed
    Principal. Token verification and identity resolution establish the exact
    server-owned Principal, then the same authentication transaction observes
    policy before returning it; observer failure therefore prevents application
    dispatch. Authenticated remote MCP observes its resolved Principal through
    the same runtime contract before returning request context. No Principal
    enumeration, traversal, fallback identity, or backfill was added.
17. Source-version, proposal-producer, and generic mutation builders now have
    isolated-PostgreSQL contracts using the real SQL current-binding view. Each
    new binding reaches its callback while current; advancing its actual source
    or producer watermark produces the exact stale reason, excludes the callback,
    and settles `STALE`. The Entra persistence contract likewise proves first and
    repeat observation create no work while an old policy watermark advances to
    one durable deduplicated `policy_change` item. These database-marked tests
    were collected but not executed without a verified disposable target.
18. Generic mutation registration now owns only its four Principal-bound
    capabilities. All eleven subject-specific handlers are excluded and absent
    from the generic map; assignment create/revise/end therefore emit exactly one
    `role_or_organization_change` item, and exact replay emits none. A structural
    guard binds the direct caller set, trigger vocabulary, and disjointness.
19. Relationship Memory proposal subject and per-Entity context origins now
    survive proposal hydration, governed merge/split, acceptance, correction
    acceptance, and reprocess. Review promotion/reprocess writes every required
    head-schema origin, and the head migration backfills proposal-link lineage.
    Focused disposable-PostgreSQL execution also exposed and corrected the
    migration's malformed SQL comment and current-metadata duplicate-DDL path.
20. Governed merge now rebinds each moved Relationship Memory proposal's
    `expected_subject_version` to the locked survivor token; a context-only move
    leaves the proposal's unchanged subject token alone. Split derives the
    restored proposal token from the restored Entity's monotonic `N+2` effect
    state and writes that already-digested inverse under the exact merge-after
    CAS guard. Five unequal-version disposable-PostgreSQL cases prove current
    accept, correction acceptance and reprocess after merge/split while stale
    external tokens, foreign Principals and stale review versions change no row.

## Post-merge record and campaign findings (2026-08-29)

Added by the RI remediation campaign on `bf/ri-remediation-20260829`. Each item
is a finding of that campaign, recorded here because this file is where the
Relationship Intelligence campaign record lives. Nothing above is deleted.

### RI-P1-BLK-001 — the delivered head merged with no recorded review

Stated as fact, without editorialising. PR #163,
`fix(ri): close terminal database-tier regressions`, head
`e95c918bdee2644a9c27b18362599b9b79f701f2`, merged `2026-08-29T08:27:14Z`,
producing merge commit `8d5e1d01b209eae1169c4f60c79c6c2c2dc89eb4` — the
delivered head named at the top of this file. It carries **zero recorded
reviews**: `gh pr view 163 --json reviews` returns `[]`. CI against its exact
head did pass. `RI-FC-WP-07`'s disposition above is
`IMPLEMENTED_PENDING_FRESH_EXACT_HEAD_REVIEW`, and that review is what the empty
list says did not happen before the merge. The disposition is the operator's;
this record exists so that it is not reconstructed later from an absence.

### RI-P6 findings — what the tree actually does

**1. There is no persisted derived Relationship Intelligence cache at this
head.** `src/my_pa/domain/relationship/context_card.py:18` states it in the
source: "the invalidation rule (there is no cache to invalidate)". There are
zero materialized views anywhere in `migrations/` (`grep -rn MATERIALIZED
migrations/` finds none), and `knowledge.context_runs` /
`knowledge.context_run_items` (`migrations/versions/20260815_9b2d5f8c3e01_create_context_run_tables.py`)
are an append-only disclosure manifest — held immutable by the
`context_runs_are_append_only` and `context_run_items_are_append_only` triggers —
with no entity binding: neither table carries an `entity_id` or any entity
foreign key. Therefore RI v0.2 section 15.3's "invalidate cached summaries and
context packets" is discharged here by **deterministic mention→identity
re-resolution** on the `reenrichment` plane, not by cache invalidation. There is
no cache; the obligation is met by recomputation, and saying "invalidated" would
name a mechanism that does not exist.

**2. WP-07 residual limitation — the append-only trigger is a real control and
it is not a privilege boundary.** `b727e870d45e` adds
`entity_proposal_review_decisions_are_append_only`, a `BEFORE UPDATE OR DELETE`
trigger on `knowledge.entity_proposal_review_decisions`. It is real: triggers of
this kind fire for superusers too, so an ordinary `UPDATE` or `DELETE` against a
decided review row is refused at the server. What it is not is protection against
the role that runs this repository. There is exactly **one** database role,
`my_pa`, created by initdb from `POSTGRES_USER` (`ops/compose/postgres.yml:25`,
`ops/nas/compose.example.yml:15`); it is cluster superuser and owner of schema
`knowledge`; and there are **zero** `GRANT`, `REVOKE`, `CREATE ROLE`,
`CREATE USER` or `ALTER ROLE` statements anywhere in the repository. A superuser
can `ALTER TABLE … DISABLE TRIGGER`, `SET session_replication_role = 'replica'`,
or `DROP TRIGGER`, and the trigger stops the accident rather than the operator.
Reducing that privilege was evaluated and **deliberately deferred**: it is
net-new work with zero repository precedent — no role, grant or ownership
statement exists to extend — and inventing a privilege model inside a
documentation and remediation campaign would exceed the authorised scope
(`AGENTS.md` sections 2 and 3). It is recorded, not closed.

**3. RT-03 premise correction — `entities.identity_history` is in the read
profiles.** The capability is `entities.identity_history` and it **is** a member
of `_ENTITY_READS` (`src/my_pa/bootstrap/relationship_intelligence_profiles.py:37`).
`_STANDARD` is built from `_ENTITY_READS`, `_REVIEWER` from `_STANDARD`, and
`_OPERATOR` from `_REVIEWER`, so `relationship_standard`,
`relationship_reviewer` and `relationship_operator` all carry it. It is absent
only from `relationship_producer`, which is assembled independently. Any report
that a client cannot see this capability is therefore a durable per-client grant
question or a compact-facade publication question — not a code-level profile
omission, and not something a change to these profiles would fix.

**4. WP-01's family-coverage gap is closed on both its disposition and
discovery sides.** Corrected 2026-08-29 (`7f5bda1`, closing the disposition-side
half of the `RI-P2-BLK-001` family-coverage gap this paragraph previously left
open) and corrected again the same day (closing the discovery-side half item 5
below named as the reason WP-01 was still PARTIAL). The disposition-side gate,
unchanged by the second correction, is `not dispositions_for(effect.family)`
(`src/my_pa/application/identity_correction.py:1876`), which raises an ambiguity
for any family `dispositions_for` admits at least one disposition for, rather
than the narrower `not in _ATTRIBUTABLE_FAMILIES` test it replaced. `alias`,
`identifier`, `assignment`, `relationship` and `observation` keep the full set
`dispositions_for` gives them (`_ATTRIBUTABLE_FAMILIES`,
`src/my_pa/application/identity_correction.py:3140`, unchanged at five members).
For `proposal`, `relationship_memory`, `memory_proposal` and
`memory_context_link` **no rebinding primitive exists**: `entity_proposals`
carries `entity_columns=()` (`src/my_pa/infrastructure/persistence/entity.py:3838`)
and makes its references inside its payload, so there is nothing for an
assignment to rewrite; and `RelationshipMemoryRepository` publishes no
operator-directed rebinding — its two identity writers apply and restore a
planned merge effect. `LEAVE_UNRESOLVED` needs no such primitive — it is a
settlement record, not a mutation — so it does not share `ASSIGN_TO_ENTITY`'s
dependency on one: `_DISPOSITIONS_BY_FAMILY` narrows these four to
`(LEAVE_UNRESOLVED,)` only (`src/my_pa/domain/relationship/identity_correction.py`).
`ASSIGN_TO_ENTITY` for one of the four is refused before any write
(`InvalidRequestError`, since it is outside `allowed_dispositions`), and an
unanswered ambiguity still blocks apply — fail-closed is preserved, not
loosened.

The second correction closed what the first one could not reach: **discovery**,
not just disposition. `not dispositions_for(effect.family)` only raises an
ambiguity for a row the merge's own effect ledger already names, changed since
(`POST_MERGE_MODIFIED`) — it says nothing about a row bound to the survivor that
the ledger never mentions at all (`POST_MERGE_CREATED`), which is
`_post_merge_created`'s (`src/my_pa/application/identity_correction.py:1925`)
question, not this gate's. Before the second correction, `_post_merge_created`
walked only `_ATTRIBUTABLE_FAMILIES`, so a `proposal`, `relationship_memory`,
`memory_proposal` or `memory_context_link` row newly bound to the survivor after
a merge, with no ledger effect for it, was never discovered as
`POST_MERGE_CREATED` — the residual gap item 5 named and `RI-P2-BLK-001` was
reopened over. `_ATTRIBUTABLE_FAMILIES` now gates only
`EntitiesRepository.records_bound_to_entity_outside` discovery and
`ASSIGN_TO_ENTITY` execution, not whether `POST_MERGE_CREATED` discovery runs
for a family at all: `relationship_memory`, `memory_proposal` and
`memory_context_link` are now also discovered through
`RelationshipMemoryRepository.records_bound_to_entity_outside`
(`src/my_pa/contracts/ports.py`, implemented in
`src/my_pa/infrastructure/persistence/relationship_memory.py`) — the memory
plane's own version of the same method, over the same three columns
`plan_identity_merge` already reparents (`subject_entity_id` twice,
`target_id` once). `proposal` has no such column to query at all, so it is
discovered the way `preview()` already asks whether a merge materially affects
an open proposal: `self._entities.proposals` read whole and
`_proposal_is_materially_affected` applied against the survivor, over every
proposal state rather than only the open ones. All four keep the disposition
set they already had — this correction changed discovery, not what an operator
may answer with.

Proven end-to-end (raise, apply-with-no-disposition-fails,
`ASSIGN_TO_ENTITY`-refused, `LEAVE_UNRESOLVED`-succeeds): `relationship_memory`
for `POST_MERGE_MODIFIED`, pre-existing, in
`tests/database/test_identity_split_ambiguity.py` and
`tests/unit/test_identity_split_service.py`; `relationship_memory` for
`POST_MERGE_CREATED`, added by the second correction, and `proposal`,
`memory_proposal` and `memory_context_link` for `POST_MERGE_CREATED`, also
added by the second correction, all four in
`tests/database/test_identity_split_ambiguity.py` only — the second correction
did not add unit-level (fake-repository) cases for the `POST_MERGE_CREATED`
path, only database-tier ones; the unit-level fakes were extended just enough
(`_Entities.proposals`, `_Memories.records_bound_to_entity_outside` and their
counterparts in `tests/unit/test_identity_correction.py`) that the pre-existing
unit suite keeps exercising the port surface correctly rather than crashing on
an unimplemented method. What remains a narrower, stated limitation, unchanged
by either correction: `proposal`, `memory_proposal` and `memory_context_link`'s
`POST_MERGE_MODIFIED` path is proven at the domain-disposition level only (the
same `_DISPOSITIONS_BY_FAMILY`/`dispositions_for` assertions, plus the shared,
family-agnostic gate and settlement-validation logic all four run through), not
with its own end-to-end database-level case. WP-01 is no longer PARTIAL for the
reason item 5 below named — `POST_MERGE_CREATED` discovery not extended to
these four families — because that reason is now closed.

**5. WP-01 known limitation — post-merge-created discovery over-reports, by
design, for all nine families now, not only the original five.** This item
named the discovery-scope gap item 4 above records as now closed by the second
2026-08-29 correction. It also names a second thing, which that correction did
not close and was never meant to: over-reporting is an accepted, deliberate
fail-safe property of the discovery mechanism itself, not a defect, and it now
applies uniformly across every family the mechanism reaches. The five tables
`_post_merge_created` walked before that correction carry **no creation
timestamp**: `entity_aliases`,
`entity_external_identifiers`, `entity_assignments` and `entity_relationships`
have only `updated_at`, and `entity_observations` has `observed_at`/`recorded_at`.
The four families the second correction added discovery for are not uniformly
the same: `relationship_memories` carries `created_at`, and
`relationship_memory_proposals`/`entity_proposals` carry `proposed_at` — three
of the four newly-discovered tables *do* have a creation-ish column, and
`_post_merge_created` deliberately does not read any of them. A survivor's own
row from before the merge is exactly as invisible to a timestamp check as one
genuinely created afterward, because neither this method nor the merge ledger
records when the survivor's own history began; reading the column would narrow
some rows correctly and drop others silently, with no way from the persisted
state to tell which is which. So "bound to the survivor and absent from the
ledger" — the strongest discriminator the persisted state supports — also
matches the survivor's own pre-merge rows, for every one of the nine families
this method now discovers, not only the original five. The error direction is
fail-closed throughout: it **over-reports and never under-reports**, an operator
is asked to attribute a record whose owner they can see immediately, and no
record is silently attributed for them. Every disposition an operator may
choose is safe (all three, for the five with a rebinding writer; the one
disposition, `LEAVE_UNRESOLVED`, for the four narrowed to it). Narrowing it
needs a creation time these tables do not have, and even where one exists it
cannot distinguish a pre-merge row from a post-merge one, so it is not read.
The limitation is stated in the source at
`src/my_pa/application/identity_correction.py:1934-1953`.

**6. WP-04 is PARTIAL, and the residue is an operator decision.** Removing the
unconditional `CONTRADICTION_RESOLUTION` registration
(`src/my_pa/application/service.py:3804-3820`) eliminates false contradiction
work for all **eight** review dispositions and all **four** review subject kinds
(`src/my_pa/domain/capture/review.py:131-157`). What it leaves is this: three
ACCEPT events that genuinely change canonical state — on the
`capture_proposal`, `goodnotes_region` and `relationship_memory` subject kinds —
now register **nothing**, because those three reach the decision handler with no
proposed Entity mutation (`src/my_pa/application/entity_reenrichment.py:157-164`)
and no evidence-grounded member of the closed nine triggers fits the latter two.
Registering one anyway would be inventing a trigger the specification does not
name. This is open for an operator decision and is not claimed as closed.

**7. Recorded, unclosed observation — `merge_entities` has split's mismatch
class.** The proposal payload for `EntityProposalKind.MERGE_ENTITIES` requires
`{retained_entity_id, merged_entity_id}` with optional `{reason}`
(`src/my_pa/domain/relationship/proposal_payload.py:377-380`); the command it
would have to become is
`PreviewEntityMerge(survivor_entity_id, expected_survivor_version, merged_away,
reason, evidence_refs)` (`src/my_pa/application/commands.py:5657`). The
identifier overlap between the two is exactly `{"reason"}`. This is the identical
mismatch class WP-06 addressed for split. It was **scoped out** of this campaign,
whose WP-06 is split; it is **not fixed and not designed around**, and it is
written here so the next reader finds it as a known open item rather than
rediscovering it.

## Load-bearing and mutation controls

The following controls are intentionally coupled to tests that fail when the
guard is removed or weakened:

| Control | Load-bearing evidence |
|---|---|
| Exact split inversion | Preview digest, source merge, effect count/digest, one-completed-split uniqueness, and stale-version checks |
| Principal isolation | Entity-first history authorization, partition predicates on history and re-enrichment persistence, and cross-Principal not-found regressions |
| Immutable history | Direct mutation events plus settled operation/effect ledgers and legacy merge lineage; proposals and review rows are not scraped as history |
| Bounded re-enrichment | Exact nine-trigger enum, immutable binding digest, lease ownership/expiry, bounded attempts, retry timing, and stale-before-apply checks |
| Proposal/review separation | Generated discriminated payload map covers every proposal family; identity-correction acceptance returns a preview handoff and cannot apply |
| Remote write ceiling | Ordinary profiles cannot publish merge/split; exact `remote.operator`, server-resolved grants, purpose, feature, Principal, policy, audit, and global write gates all remain required |
| Capability/audit closure | Architecture guards compare catalogs, commands, profiles, transports, fixtures, migration vocabularies, and spelled counts without deriving old migrations from current enums |
| Database concurrency | The broader isolated-PostgreSQL selection targeting settlement uniqueness, lease claims, replay, stale work, and cross-Principal persistence was collected rather than executed, so no pass is claimed for that unexecuted selection. Later focused Relationship Memory corrections executed `82 passed` plus `5 passed` unequal-version cases, exactly as recorded in the validation table above. |

## Operator-only remaining actions

After an eligible pull request is reviewed against its exact head, the operator
still owns merge, production/runtime commissioning, the WP-09 synthetic canary,
deployment or activation, all credential/grant/OAuth changes, and every live or
personal-data decision. This campaign performs none of those actions.
