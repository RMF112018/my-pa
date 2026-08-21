# MCV Completion — Gap Audit and Integrated Implementation Plan

Plan basis: `PLAN-MYPA-APPLICATION-COMPLETION-20260801-078` (Drive `1-jfuAm3p1bQSC3l-37rFw6wk82HFQ9MKalR-LZm_U3Q`).
Audit basis: `main@e773e6f2285da9e453a8ca7e11bdac23619aaf22`, audited 2026-08-01.
Revalidated against `main@8274d88a6211c417c43d2d937edfe2c8ccc369be` on 2026-08-02, after
work packages WP-2 and WP-3 merged and the operator reprioritized the objective.
Section 1 records the current identities; the sections below it were corrected
in place rather than left to be read as current. Its five repository-state rows
— the local head, the worktree, the branches, the worktrees, and the open pull
requests — are the exception and are the state at the dispatch basis, named as
such rather than restated, because no document holds them current between two
commits. Its container, database, extension and Alembic rows are current, and
the Alembic row is derived rather than written down:
`../../tests/architecture/test_spelled_counts_match_the_sets_they_name.py` reads
this section and section 3 and fails when either disagrees with the chain.

This document is the current-state gap audit and the integrated work-package plan
required before implementation resumes. It records what the repository actually
contains, what repository policy and specification require, and where the
dispatched plan and repository policy disagree.

The dispatched plan is mirrored at `evidence/completion/PLAN-MYPA-APPLICATION-COMPLETION-20260801-078.md`
so that every section cited below can be checked against a file in this
repository rather than a link a reviewer cannot open. That mirror is evidence of
what was dispatched, not repository authority; `CONTRIBUTING.md` governs, and
Drive mirrors are review surfaces rather than a competing ledger.

## 1. Authenticated identities

| Fact | Value | How verified |
|---|---|---|
| Repository | `RMF112018/my-pa` | `git remote -v` |
| Local `main` head | `8274d88a6211c417c43d2d937edfe2c8ccc369be` | `git rev-parse HEAD` |
| Dispatch basis | identical to local head | comparison |
| Worktree | clean, no untracked files | `git status --porcelain` empty |
| Branches | `main` only; no stale feature branches | `git branch -a` |
| Worktrees | one, the primary checkout | `git worktree list` |
| Open pull requests | none; #1–#22 all merged | `gh pr list --state all` |
| Database container | `my-pa-postgres`, `postgres:17.10`, healthy | `docker ps` |
| Database binding | `127.0.0.1:5433 -> 5432`, loopback only | `docker ps` port map |
| Logical database | `my_pa` | `select current_database()` |
| Alembic head | `e9b2c4d7a150` in the repository, sixty-five revisions; local validation targets disposable databases only | `migrations/versions/*.py`, `alembic heads` |
| Extensions | `pg_trgm`, `unaccent`, `plpgsql` | `select extname from pg_extension` |

## 2. Verified corpus claim

Commit `f34eb96` claims a migrated corpus of 3,263,870 rows across 484 domain
tables. That claim was **recomputed, not restated**, by counting live rows across
the seven domain schemas:

```
total_rows       3263870
domain_tables    484
tables_with_rows 286
```

Per-schema table counts: `core` 161, `procore` 150, `financial` 67,
`schedule` 43, `construction` 26, `email` 26, `calendar` 11. An eighth domain
schema, `contacts`, exists and holds zero base tables, so it changes no count.
Plus `migration_control` 9 and `public` 1, which are not domain tables.

The claim is **exact**. 198 of the 484 tables are empty, which
`migrations/data/disposition_registry.json` already accounts for; an empty table
is not a defect.

## 3. What is implemented

Two hundred and fifty-nine Python modules under `src/my_pa` and three hundred and thirteen test modules —
`find src/my_pa -name "*.py"` and `find tests -name "test_*.py"`. The figures
published here have now gone stale twice: sixty-eight and forty were true at the
2026-08-02 revalidation basis `main@8274d88`, ninety-three and sixty-nine were
true at WP-4B3 `main@6660dbb`, and each was carried through the packages that
followed. (The audit basis `main@e773e6f` was fifty-six and twenty-seven; the
pair recorded against it here was the revalidation's, one basis out.) **"Nothing checks them" was the
diagnosis and it is now wrong**:
`../../tests/architecture/test_spelled_counts_match_the_sets_they_name.py` runs
both commands above, and the revision count and head below, and fails when this
section disagrees with the tree.

| Area | State |
|---|---|
| `contracts/v1` — envelope, disclosure, errors, capabilities, base | Implemented and tested |
| `domain/identity` — capability, purpose, principal, operation binding | Implemented and tested |
| `domain/common` — identifiers, provenance, classification, time | Implemented and tested |
| `domain/policy`, `domain/audit` | Implemented and tested |
| `bootstrap/settings` — strict `MY_PA_` configuration, fail-closed | Implemented and tested |
| `infrastructure/database/engine` | Implemented |
| `infrastructure/migration/*` — legacy ETL, control plane, redaction | Implemented and tested |
| `domain/source`, `domain/extraction`, `domain/search` — registry, bounded enrollment, provider port, extraction outcomes, quarantine, coverage, search query | Implemented and tested |
| `infrastructure/persistence` — registry, enrollment, jobs, extraction, quarantine, coverage, lexical search | Implemented; covered by the database tier |
| `infrastructure/providers/fixture.py` — read-only fixture source provider | Implemented and tested |
| Alembic revisions — schemas and extensions, target tables, control plane, indexes, foreign keys, views, `knowledge` schema, extraction tables, audit events, enrolled objects, continuity, native sources, managed documents, GoodNotes, operations, task management, context prepare/feedback, OAuth refresh-token families, GoodNotes notebook lineage, GoodNotes NOTE_UNIT occurrence persistence, GoodNotes semantic work/proposal receipts, GoodNotes entity associations with NEW-only delivery receipts, and additive GoodNotes exact visual render digests, additive `goodnotes.content` vocabulary, additive durable-note stage ledger and Principal-bound page rasters, additive GoodNotes server-grounded NOTE_UNIT crop identity with immutable revision provenance, additive GoodNotes Meeting/Agenda association kinds, and an additive dormant GoodNotes delivery-attempt ledger, and the relationship-intelligence entity plane — `entities`, `entity_external_identifiers`, `entity_assignments`, `entity_relationships`, the additive `entity_aliases` table, and the `entities.*` capability family with the `entity_read` purpose, and the entity observation, proposal, and merge-lineage tables, and the Intelligence Artifact report plane — cycle runs, producer runs, immutable artifacts, commit receipts, pipeline dependencies, and external provenance, with the eight `reports.*` capabilities and the `report_authoring`/`report_read` purposes | Implemented, sixty-five revisions, head `e9b2c4d7a150` |
| CI — `repository-checks.yml` including the database tier | Implemented |

All sixty-two capability names, their operator-only flags, and their permitted
purposes exist in `domain/identity/operation.py`, alongside twenty-five purposes. The v1 request,
response, disclosure, and error shapes already exist and are contract-tested.

## 4. What is not implemented

Nothing below `contracts` and `domain` executes a product workflow. Specifically
absent, with no code beyond a README:

*The list that follows is state at the audit basis and is deliberately not
updated, in the same way and for the same reason as the sentence in section 12
below. Five of its entries have since been built: WP-4A wired the application
services, WP-4B1 made the worker a process, WP-4B2a made the gateway one and
built the HTTP transport, and WP-4B2b built the MCP adapter and the operator
CLI beyond `apps/cli/migration.py` — so `apps/worker/` and `apps/gateway/` are
both gone, `apps/worker.py` and `apps/gateway.py` are real composition roots,
and all three transports exist with `SPEC-AC-001` parity proven across them. It
is left standing because what this section is for is recording what the audit
found, and rewriting it clause by clause would leave a record of nothing.*

- application services binding the eight capabilities to the persistence and provider behavior that now exists;
- HTTP transport (`apps/gateway` is a README);
- MCP adapter;
- worker process (`apps/worker` is a README);
- operator CLI beyond `apps/cli/migration.py`;
- managed documents, structured knowledge records, relationship services,
  GoodNotes ingestion, Obsidian projection, and any frontend. There is no
  JavaScript toolchain in the repository at all — no `package.json` exists.

At the audit basis `e773e6f`, `README.md` said "This branch contains a
documentation-only repository scaffold... does not implement runtime behavior."
That was false, and WP-1 corrects it in the same change that publishes this
document.

## 5. Specification conflict, and how it resolves

The dispatched plan requires ten workstreams, A through J, including a full
frontend MVP (H), a PaddleOCR/TrOCR handwriting pipeline (G), relationship
intelligence (F), managed documents (E), and an Obsidian projection (I).

Repository policy says the opposite, in terms that are not ambiguous.

`AGENTS.md` is the load-bearing authority here, because it is unambiguously
accepted policy — `AGENTS.md` §1 places "accepted repository specifications,
ADRs, and this policy" above "indexed Workspace publications" in its own
precedence list, and `AGENTS.md` is itself that policy. §1: "The objective is one
complete, read-only vertical slice—not a broad platform." §3 defers
implementation "merely because a scaffold path exists" and directs "one
end-to-end vertical slice over multiple partial systems."

`docs/specs/mcv-read-only-vertical-slice.md` agrees and is more specific, but it
carries `status: PROPOSED_FOR_REPOSITORY_REVIEW` and describes itself as a
candidate. It is therefore corroborating detail, not the authority the deferral
rests on. Accepting it is an operator act that has not happened. §2:

> The MCV therefore proves one complete, bounded, read-only vertical slice. It
> does not attempt to build a broad personal-assistant platform.

The same specification, §5.2, lists as **explicitly excluded**: personal email,
calendar, contact, and relationship connectors; managed-document writes and
version/recovery workflows; and "vector search, graph infrastructure,
relationship intelligence, and projection implementation."

The dispatched plan does not override this, and does not claim to. Its §5.1 says
"Repository governance and runtime truth control implementation over older Drive
planning assumptions." Its §5.6 says "`AGENTS.md` is the principal repository
policy. Preserve its minimum-correct-implementation... rules." Its §7 preamble
qualifies the whole workstream list with "unless repository truth proves that a
requirement is superseded or already complete," and its §6 requires every
requirement to be classified, including as "superseded" or "deliberately
deferred."

So the conflict resolves inside the plan's own rules rather than against them.
Workstreams E, F, and I are classified **deferred — outside the vertical slice
`AGENTS.md` defines, and named as excluded by the proposed specification**. They
are not silently dropped; they are named here, and they remain available scope.
Promoting them takes an explicit operator reprioritisation of the objective
under `AGENTS.md` §3; amending the proposed specification alone would not do it,
because `AGENTS.md` is what currently carries the deferral.

Workstreams G and H are not excluded by the specification — they are absent from
it, arriving from Drive feature packages. They are classified **deferred —
dependency-blocked**: both consume backend contracts that do not yet exist. The
plan itself forbids building H ahead of them ("Do not invent backend behavior to
make a screen look complete," §7-H), and G's live source root is gated by
`P00-OD-009`, which is an operator-only open decision.

## 6. Requirements traceability

*The classifications below are state at the audit basis and are deliberately not
updated, in the same way and for the same reason as the lists in sections 4 and
12. Several are now false — A was built by WP-1, B and C by WP-2 and WP-3, and
**D by WP-4A, WP-4B1, WP-4B2a and WP-4B2b**, so "transport does not [exist]" is
no longer true of any of the three: HTTP, MCP and the operator CLI all exist and
`SPEC-AC-001` parity is proven over them. The **Disposition** column stays
correct, which is what this table is for; the split of WP-4 into WP-4A and WP-4B
is recorded by `D-28` in the register, and the split of WP-4B again by `D-36` —
which had no row until WP-0R2 added one; see the note under the register in
section 13. This table
had carried no marker until WP-4B2b added one, which is why row A has read
"Missing and required" since the day WP-1 merged.*

| Workstream | Classification | Disposition |
|---|---|---|
| A — repository and product truth | Missing and required | WP-1 |
| B — registry, jobs, canonical services | Partially implemented (contracts and audit exist; persistence and services do not) | WP-2, WP-3 |
| C — read-only source provider, indexing, search | Missing and required | WP-2, WP-3 |
| D — gateway, MCP parity, operator CLI | Partially implemented (contracts exist; transport does not) | WP-4 |
| E — managed documents, recovery | Deferred — outside the `AGENTS.md` slice; named as excluded by spec §5.2 | Deferred, disclosed |
| F — personal-data domains, relationship intelligence | Deferred — outside the `AGENTS.md` slice; named as excluded by spec §5.2 | Deferred, disclosed |
| G — GoodNotes handwriting MVP | Deferred — dependency-blocked and `P00-OD-009` operator-gated | Deferred, disclosed |
| H — interactive frontend MVP | Deferred — dependency-blocked on B/C/D | Deferred, disclosed |
| I — Obsidian projection | Deferred — outside the `AGENTS.md` slice; named as excluded by spec §5.2 ("projection implementation") | Deferred, disclosed |
| J — operations, packaging, local activation | Missing and required | WP-5 |

The migrated PostgreSQL corpus is retained and verified but is **not** exposed
through product services in this scope, because doing so is Workstream F.

## 7. Work packages and merge order

Each is one branch, one pull request, squash-merged, implemented by a delegated
agent with disjoint file ownership and reviewed at exact head by a separate
agent that did not author it.

1. **WP-1 — repository and product truth.** This document; corrected `README.md`;
   source-index routing; Phase 00 ledger dispositions the migration superseded;
   spec status reconciliation. Documentation only, no behavior change.
2. **WP-2 — registry, enrollment, jobs, fixture provider.** New `knowledge`
   schema by Alembic, empty-to-head. Source registry, bounded enrollment with
   idempotency keys, job lease/retry, opaque ID issuance. Read-only fixture
   provider proving root containment and traversal denial.
3. **WP-3 — extraction, quarantine, coverage, search.** Text and Markdown
   extraction; PDF reported `unsupported` because `P00-OD-003` is open;
   quarantine triggers; coverage states; version-fingerprint binding;
   PostgreSQL FTS with `pg_trgm`.
4. **WP-0R — canonical re-mirror and reconciliation.** Refreshes the mirrored
   canonical product definition against the 2026-08-02 Remote Quick Capture
   revision and reconciles this plan against it. Documentation only, no behavior
   change. Out of numeric order because it was raised after WP-4 was planned and
   depends on nothing.
5. **WP-4A — application services.** Use cases for the eight capabilities, ports,
   the shared policy and disclosure path, and the derived capability manifest,
   behind the existing v1 contracts.
6. **WP-4B — transports.** HTTP gateway on loopback, MCP adapter with proven
   transport parity, operator CLI, both composition roots, the worker lease loop,
   and the parity and negative-evidence matrices.
7. **WP-5 — operations and local candidate.** Startup, shutdown, health,
   readiness, recovery and idempotency tests, empty-to-head validation, the
   end-to-end synthetic slice, operator runbook, honest limitations.
8. **WP-6 — capture domain and durable-first persistence.** Capture contracts,
   `capture.create`, submission, receipt, and outbox, committed in one
   transaction — **the redacted audit event excepted**, which commits first and
   separately on the audit connection per `D-34`. *Corrected 2026-08-03
   (`D-75`): this item said "all committed in one transaction" and named a
   registered client. The audit was never in that transaction and cannot be
   without overturning `D-34`; `RegisteredCaptureClient` is deferred by `D-74`
   because `D-30`, `O-21` and `P00-OD-010` leave it unpopulatable. Section 559's
   objective carries the corrected sentence in full.*
9. **WP-7 — capture processing.** Proposals, evidence spans, deterministic
   classification and domain assignment, exact search.
10. **WP-8 — review and promotion.** Review cases, promotion, conversation
    events, corrections.
11. **WP-9 — relationship identity and read-only profiles.**
12. **WP-10 — PWA capture surface and offline recovery.** **Deferred until after
    MCV completion by direct operator instruction on 2026-08-04 (`D-104`).** It
    remains the only frontend package here; active gates `D-09`, `O-04`, and
    `O-20` remain unresolved.
13. **WP-11 — Native Apple Reminders execution projection.** Internal sequence
    `NAR-00` canonical policy amendment, `NAR-01` target-Mac EventKit
    feasibility proof, `NAR-02` provider-neutral domain and contracts, `NAR-03`
    backend application services, `NAR-04` signed native bridge, `NAR-05`
    one-way creation and updates, `NAR-06` completion roundtrip, `NAR-07`
    conflicts and recovery, `NAR-08` security and operational proof.
    `D-39` records the historical sequencing provenance; WP-11 remains dependent
    on WP-10, and nothing in it is built. `D-104` keeps WP-10 deferred until MCV
    completion, so WP-11 remains dependency-blocked and its own pre-completion or
    post-completion placement is unresolved. `D-104` does not answer its active
    gates `NAR-OP-001` through `NAR-OP-009` or authorize any part of it.
14. **WP-12 — Apple Mail, Calendar & Contacts.** **Promoted ahead of deferred
    WP-10 and WP-11 for bounded pre-completion implementation by direct operator
    authorization `AUTH-WP12-20260804-OPERATOR-001` (`D-106`).** Its internal
    dependency order is A, B, D, C, E, F, G, H. Slice A freezes repository truth,
    the exact acceptance map, and source-built protocol-v1 feasibility contracts;
    live Apple access, TCC, signing, activation, deployment, source mutation, and
    risk acceptance remain prohibited.

Items 4 through 14 restate section 12's sequence table, which is the authoritative
one; `D-28` split WP-4, the Remote Quick Capture revision added WP-0R and
WP-10, the Native Apple Reminders revision added WP-11, `D-105` records the
historical provisional WP-12 state, and `D-106` records its later promotion.
Section 7 originally stopped at WP-5, and listing only half
the merge order was how a reader ended up consulting two tables that disagreed.

## 8. Boundaries held throughout

- No source mutation. The fixture root and any later NAS root are opened
  read-only, and containment is revalidated immediately before read.
- No live personal data in tests, fixtures, logs, or evidence. Fixtures are
  synthetic.
- No connection to an unverified physical database. Today the only guard is
  configuration-level: settings reject an unknown `MY_PA_` name, an unparseable
  value, or a URL that is not `postgresql+psycopg` naming a host and a database.
  There is no runtime `current_database()` check. An absent `MY_PA_DATABASE_URL`
  no longer defaults: `P00-OD-008` was resolved by the operator and the setting
  is required, so an unconfigured process refuses to start rather than choosing a
  target. The legacy SQLite source is never written.
- Services bind to loopback. No internet exposure, no multi-user claim.
- PDF stays `unsupported` rather than silently skipped, until `P00-OD-003` is
  resolved by the operator.
- Live NAS and GoodNotes roots stay unused; `P00-OD-009` requires separate
  operator authorization naming an exact root.

## 9. Decision register

Corrections to entries here are made in place, in public, with the original
claim left visible.

| ID | Decision | Basis | State |
|---|---|---|---|
| D-01 | Plan accepted on identity, not on byte-exact hash | The dispatch declared both `representation: native_google_doc` and a source SHA-256 of the pre-conversion Markdown. A native Google Doc does not preserve source bytes, so the two are not jointly satisfiable. File ID, title, parent, owner, and native type all verified; every export format was hashed and none matched, as expected. | Departure, disclosed |
| D-02 | tmux channel replaced by subagent delegation | `tmux` is not installed on this machine and no `claude-code` session exists. The dispatched plan assumed a separate orchestrator driving this session through tmux; this session is itself the implementation agent. Plan §3 and §9.2 independently require fresh subagents for implementation and exact-head review, which is the substituted mechanism. | Departure, disclosed |
| D-03 | Workstreams E, F, I deferred | Outside the single read-only vertical slice `AGENTS.md` §1 and §3 define, and named as excluded by `docs/specs/mcv-read-only-vertical-slice.md` §5.2. The specification is `PROPOSED_FOR_REPOSITORY_REVIEW`, so `AGENTS.md` carries the argument and the specification corroborates it. | Deferred |
| D-04 | Workstreams G, H deferred | Dependency-blocked on B/C/D, which do not exist. The specification is silent on both, so nothing excludes them; they are sequenced, not ruled out. Plan §7-H forbids fabricating backend behavior; `P00-OD-009` gates G's source root to the operator. | Deferred |
| D-09 | Workstream H additionally held by operator instruction | The operator directed on 2026-08-01 that no frontend implementation is in scope until they say otherwise. This is a stronger and more durable hold than D-04's dependency argument, which would lapse once B/C/D exist. Recorded separately so that satisfying the dependency does not read as authorisation to start. | Operator-directed |
| D-05 | Corpus claim accepted | Recomputed from the live database, not restated. Exact match. | Verified |
| D-06 | PDF remains `unsupported` | `P00-OD-003` is `OPEN_OPERATOR`. Reporting `unsupported` is the specified behavior; silently skipping is forbidden. | Accepted |
| D-07 | Corrected in place: this document first said "five revisions" | The count came from a truncated directory listing. Recounted from `migrations/versions/*.py`: six, chained `5d75f23847c9 → 1e6c0a94f3b7 → 4b9f0d27ac31 → 2f7d1ba05c48 → 3a8e2cb16d59 → 6c4d3ea82f10`, the last creating target views, and the head matching `alembic_version` in the live database. The mechanism, not just the number, is fixed: the count is now stated with the head revision beside it, so a future drift between the files and the database is visible rather than latent. | Corrected |
| D-08 | Terminal disposition cannot be reached in this scope | Plan §11 requires GoodNotes, frontend, and relationship acceptance criteria that D-03 and D-04 defer. The eventual terminal disposition must name the deferred set and must not assert `MYPA_CURRENT_PRODUCT_SCOPE_COMPLETE`. **Updated 2026-08-04:** the operator explicitly confirmed the MCV is not complete. `D-104` defers WP-10 until completion. `D-105`'s provisional WP-12 sequence is historical and superseded by `D-106`, which promotes WP-12 ahead of WP-10/WP-11 without declaring MCV complete. `D-107` defines the future full-MVP handoff only after independent completion verification. | MCV not complete; WP-12 active; terminal declaration still reserved |

## 10. Carried forward

### Closed by WP-3

Both items this section carried out of WP-2's review were closed in WP-3 and are
left here rather than deleted, so the ledger reads as a sequence rather than as a
list of open things. Descriptor exhaustion and six other errno conditions now
report `unavailable` rather than `denied`, by allowlist so an unrecognised errno
stays denied. The refused hard link that vanished from listings now surfaces
through the aggregate coverage limitation WP-3 built.

### Carried into WP-4

WP-3 took seven independent reviews and five correction commits. What follows is
what those reviews found and the change deliberately did not fix, disclosed in
the code that carries it and repeated here so it is scheduled rather than
rediscovered.

- **A live snapshot race in search.** The page read and the coverage read take
  separate `READ COMMITTED` snapshots, so a quarantine committed between them
  yields a page of extracted text beside `no_extracted_text_in_scope` — the
  section 9.7 collapse the module exists to prevent. The claims about it are
  qualified rather than absolute. Reading coverage before the page is one line
  and moves the failure to the understating direction; it was not taken, and the
  operator accepted shipping it deferred.
- **Root containment and the unmeasured denominator are one missing fact.** A
  root-selector enrollment authorizes its whole source rather than the subtree
  under its root, because nothing persists which objects lie under a root — the
  same absence that leaves its coverage denominator unmeasured. Persisting the
  enumerated set once at enrollment closes both. Fix them together.
- **`record_outcome`'s persisted provenance payload has no round-trip
  assertion** — extractor identity, extractor version, the truncation flag, and
  `observed_at` against `processed_at` can each be corrupted with both test tiers
  green. WP-4 is what builds on those columns, so this belongs first in that
  package rather than in the middle of its list. *Corrected 2026-08-08: **closed,
  and the four fields were not in the same state**, which is why the bullet
  reading them as one item understated part of it and overstated the rest.
  Measured field by field before anything was written. `observed_at` was already
  pinned end to end, against the fixture file's modification time — an
  independent fact, not another read of the row — so nothing was added to it.
  `extractor` had assertions, and they were **self-referential**: both sides were
  fed from the same read, so renaming the extractor left them green. That was
  measured rather than argued — with the constant renamed, the pre-existing
  assertions passed and only the new one failed. `extractor_version` and
  `is_truncated` had **no read-back assertion anywhere in the suite**; the three
  existing `is_truncated` assertions concern disclosure truncation, which is a
  different thing wearing the same name. Each field is now pinned against an
  independently known expected value rather than against whatever the row holds,
  and each was proven non-vacuous by planting a corruption and reading the
  failure. The truncation flag is parametrised over both values with the
  known-caught case beside the plant in the same parametrisation, because a
  boolean pinned only at `False` is satisfied by a column that is always `False`.
  These land across the FAST, `database` and `e2e` tiers, and only the contract
  assertions run in FAST — the PostgreSQL round trip is `database`-tier and is
  not FAST coverage.*
- **`coverage_for` runs outside `persistence.search`'s redaction path**, so a
  `SQLAlchemyError` from the coverage read escapes carrying SQL and a bound
  identifier. Not the query-leak path, since nothing there binds query text, but
  the same class of hole. **Closed** — after WP-4 shipped rather than in it,
  which is the whole finding. `_coverage` now classifies the delegated failure
  with `_execute`'s handler set, and
  `tests/architecture/test_search_reads_leave_through_the_redaction_path.py`
  derives the rule from the module's own syntax tree, so the next read written
  outside the redaction path fails a test rather than being disclosed in a
  paragraph and scheduled here again.
- **No `statement_timeout` is configured anywhere.** The functional index removes
  the sequential scan as the only possibility without bounding what a query can
  cost. WP-4 owns process and connection configuration. *Corrected 2026-08-08:
  **this bullet is false at `6e491c2`.** `statement_timeout` is configured, on
  the connection rather than in the server, and it cannot be configured away.
  `src/my_pa/bootstrap/settings.py:244` carries `statement_timeout_ms` as a
  validated `MY_PA_` field with `gt=0` and a `DEFAULT_STATEMENT_TIMEOUT_MS`
  default (`:109`); `src/my_pa/bootstrap/gateway.py:163` and `:166` pass it to
  **both** engines as a libpq `options` connection parameter. A `database_url`
  smuggling its own `options=-c statement_timeout=0` is refused rather than
  honoured — the four cases are pinned in `tests/unit/test_settings.py`
  (`test_the_statement_timeout_cannot_be_configured_away`,
  `test_a_misspelled_statement_timeout_is_not_silently_ignored`) and the
  both-engines property in `tests/unit/test_gateway_composition.py:160`. Closed
  by #52 at `6e491c2`, which is the change that also wrote this correction's
  subject into existence. The superseded wording is kept and negated rather than
  deleted, per the `D-78`/`D-81` shape. No new `D-` identifier is minted — see
  the identifier-reservation note under section 13's decision table.*
- **`eligible` is a required integer in the `v1` disclosure** and no integer is
  true for an unmeasured scope. Making it absent is a contract change gated by
  `P00-OD-004`.
- Smaller, and named so they are not rediscovered: the `extractions` check
  constraint admits a status no counting query matches; `record_object` in
  `infrastructure/persistence/registry.py` names a function that does not exist
  (it is `observe_object`); `INDEXED_CONFIGURATIONS` is read as a rebindable
  module global; the offline DDL test asserts constraint names but not index
  names; and `mypy` is configured over a wider tree than the gate runs.
  *Corrected 2026-08-08: **three of these five are closed at `6e491c2` and this
  bullet still asserts all five.** Taken in the order written. **(1) The
  `extractions` check constraint — open**, and the only one of the five whose
  wording still holds exactly as written. **(2) `record_object`
  — closed.** No `record_object` symbol occurs anywhere in the repository; the
  function is `observe_object` at
  `src/my_pa/infrastructure/persistence/registry.py:246`, and the comment that
  named the wrong one is gone. Closed by #52 at `6e491c2`. **(3)
  `INDEXED_CONFIGURATIONS` — closed, and closed more strongly than this bullet
  asked.** Rebindability was the wrong property to chase: the value is resolved
  once at import into the `literal_column` every statement in the module holds,
  so rebinding the global after import changes no statement, and the guard in
  `_configuration` (`src/my_pa/infrastructure/persistence/search.py:330`) refuses
  any name outside the closed set before it can reach SQL interpolation.
  `src/my_pa/infrastructure/persistence/capture_search.py:186` carries the same
  guard for the second plane. Closed by #52 at `6e491c2`. **(4) The offline DDL
  test — open, and narrower than this bullet says.** The bullet reads as though
  index names are unpinned; they are not. Both functional GIN indexes are pinned
  online by `EXPLAIN`-plan assertion —
  `tests/search_quality/test_lexical_search.py:3727` for `extractions_full_text`
  and `tests/search_quality/test_capture_search.py:285` for
  `capture_versions_full_text`, with the index *definition* additionally checked
  at `tests/schema/test_capture_schema_migration.py:781`. The residue is the
  **offline `--sql` review artifact alone**:
  `test_offline_mode_emits_the_knowledge_ddl_without_connecting`
  (`tests/schema/test_knowledge_schema_migration.py:182`) asserts the schema, the
  tables, the unique constraints and the check constraints, and asserts nothing
  about indexes — so the artifact a reviewer reads without a server does not
  attest them. That is a disclosure gap in one artifact, not an unpinned index,
  and it should be stated that way rather than as a wider hole. **It was open
  when this correction was written and is closed by the change carrying it**:
  the offline test now asserts three whole `CREATE INDEX` statements rather than
  three names, because a name alone is satisfied by the same name over a plain
  btree — the expression and the access method are the part worth attesting. It
  is a subset assertion and says so, since the chain emits further indexes into
  `knowledge` that it does not attest. **(5) `mypy` —
  closed, and closed before either of the two pull requests that have since
  restated it as open.** `D-64` widened both workflow jobs to a bare
  `python -m mypy` at `08e7c81` (#33); `pyproject.toml:204` holds
  `files = ["src", "migrations", "apps"]` and
  `.github/workflows/repository-checks.yml:101` and `:248` invoke `mypy` with no
  path argument, so the configured tree and the gated tree agree by construction
  rather than by a maintained number. **#51's body restated this item as
  remaining, and #52 did not correct it** — in both cases the list was inherited
  from this bullet rather than recomputed, which is the defect this correction
  exists to stop propagating. Neither pull request's history is rewritten; the
  correction is recorded here, where the list they inherited from lives, and as a
  comment on #51. **`D-64`'s invariant was held by three prose comments and
  nothing else until the change carrying this correction, and is now
  mechanized**: `tests/architecture/test_ci_invokes_mypy_over_the_declared_tree.py`
  parses the workflow and fails on any `mypy` invocation in any job that carries
  a path argument, and separately asserts that every repository root holding
  Python is either in `[tool.mypy] files` or named as deliberately unchecked. It
  is a parse and not a text search, and the reason is measured: a search for the
  string `mypy src` in that workflow matches four times, and all four are the
  prose comments explaining why it must not be written. The parser is
  hand-written over the block-YAML subset the workflows use, because no YAML
  library is available to this repository. **Its first version claimed to raise
  on any construct it did not understand, and that claim was false** — an
  independent review at `f44f45d` put the `D-64` defect back into the real
  workflow behind a folded `>` scalar and behind a `.yaml` suffix, and watched
  the guard stay green both times. A guard that advertises fail-closed and
  fails open is worse than no guard, because the disclosure buys confidence the
  mechanism has not earned. The parser now folds `>` per YAML's rules, reads
  both suffixes GitHub honours, and unquotes only simple quoting while raising
  on the rest; its docstring is a four-way ledger — what it reads, what it
  reads without interpreting, what it raises on, and what it ignores — rather
  than a single claim of totality. The superseded wording is kept and
  negated rather than deleted,
  per the `D-78`/`D-81` shape. No new `D-` identifier is minted — see the
  identifier-reservation note under section 13's decision table.*

### What the WP-3 reviews cost, and what they bought

Seven reviews, seven blocks, and CI green on all three jobs for every head every
one of them examined.

The first found a coverage crash that killed an enrollment's entire read path, a
search result claiming `processed` coverage over a denominator it never measured,
a module docstring that told a reviewer the opposite of what its own commit did,
and a test cited in two source comments as proof of a property it did not test —
which stayed green when that property was deliberately broken.

The rest found one pattern six more times: **a correction closes exactly the case
its finding named and leaves the adjacent one open.** The clamp covered one
coverage state and not its two siblings. The crash was fixed for one cause of
three. An authorization boundary was added for cross-source objects but not
same-source ones. Both halves of that boundary were violated at once in every
test, so neither was pinned. An entire dimension of the grant — the enrollment's
content-type allowlist, stored and validated and read by nothing — was enforced
nowhere at all, and survived five reviews because each sweep was built from what
the branch had changed rather than from what the code enforced.

Three of the findings were reachable only by planting a violation. The clearest
is the vacuous index test: correct rows come back whether or not the index is
used, so no result-comparing test could ever have caught it, and only breaking it
on purpose showed that nothing was watching.

Twice the false claim was introduced by the correction itself. That is the part
worth carrying into WP-4 as method rather than as history: brief a fix against
the assumption underneath a finding rather than against the finding, build a
mutation sweep from the code rather than from the diff, and treat every sentence
written beside the code as a claim a reviewer will check.


Findings from WP-2's review that were deliberately not fixed there, recorded so
they are scheduled rather than forgotten.

- **Not every unavailability is a denial.** `fetch` now reports a read timeout
  as `unavailable` rather than `denied`, but `EMFILE`, `ENFILE`, `ENOMEM`,
  `EIO`, and `ESTALE` still fall into the blanket `except OSError` and become a
  non-retryable refusal. Proven with `RLIMIT_NOFILE` clamped: descriptor
  exhaustion tells the caller to stop retrying something that is merely
  unavailable, which `INV-PKL-007` forbids. WP-2 established the principle on
  one errno; WP-3 should finish applying it.
- **A refused hard link vanishes from listings with no signal.** A root holding
  two names for one legitimate in-root file lists neither. That converts present
  evidence into "not there". Spec section 9.2 permits the remedy — "safe
  aggregate limitations may be disclosed" — but this layer has no coverage
  plumbing until WP-3 builds it. Hard links are not exotic on a backup-derived
  NAS root, so this matters before `P00-OD-009` is answered.

## 11. Operator decisions this plan does not make

- Whether to promote E, F, G, or I into current scope. That takes an explicit
  reprioritisation of the objective under `AGENTS.md` §3, not an implementation
  choice, and not a specification amendment alone.
- H is held by direct operator instruction (D-09) and resumes only when the
  operator lifts it, independently of whether its backend dependencies exist.
- Note that the `AGENTS.md` basis is strongest for E and F, which a read-only
  slice excludes directly, and weakest for I, where the deferral leans on §3's
  preference for one slice over partial systems and on the proposed
  specification. An operator weighing I should know it rests on thinner ground
  than E or F.
- `P00-OD-003` — selecting a reviewed PDF extractor.
- `P00-OD-009` — authorizing a live NAS or GoodNotes source root by exact path.
- Production deployment, risk acceptance, and credential mutation, all of which
  remain outside every work package here.

## 12. Promoted scope: work packages WP-4 through WP-9

The operator reprioritised two features into scope on 2026-08-01: Relationship
Intelligence and Quick Capture. Section 13 records the instruments that admitted
them. This section is the resulting work-package plan. It replaces nothing in
section 7; WP-1 through WP-3 are merged, and WP-4 and WP-5 keep the objectives
section 7 gave them.

Two facts constrain the sequence more than anything in the feature packages.

First, **neither feature has a surface**. Both are specified against an HTTP
gateway, a worker process, and application services wired to the eight
capabilities. *The sentence that follows is state at time of writing
(2026-08-01) and is deliberately not updated: WP-4A wired the application
services, WP-4B1 made the worker a process, WP-4B2a made the gateway one, and
WP-4B2b added the MCP and CLI surfaces — so `apps/worker/` and `apps/gateway/`
are both gone, `apps/worker.py` and `apps/gateway.py` are real composition
roots, and both features now have the surface this paragraph says neither has. It is left standing because the
argument it supports is about the sequence, not about the tree today.* None of
those exist: `apps/gateway/` and `apps/worker/` hold a
README each, and `application/` holds one module that derives the capability
manifest. Quick Capture's own architecture file says so, and the Relationship
Intelligence specification makes "current MCV substrate completed" the first
prerequisite of its R1 stage. Building either feature before WP-4 would mean
inventing the transport it is supposed to travel over.

Second, **the read-only slice is two packages from complete**. WP-4 and WP-5 are
the last of it. Finishing them first yields the thing `AGENTS.md` section 1 asks
for — one complete vertical slice — and gives both features a substrate that has
been proven end to end rather than one assembled underneath them. The
alternative, interleaving feature work, leaves the slice permanently at ninety
percent while the surface area grows. The recommendation is therefore to finish
the slice first. The operator may reorder; see `D-12`.

### Sequence

**This table was superseded on 2026-08-02 and is kept for the shape it records.**
`D-28` split WP-4 into two pull requests, the Remote Quick Capture revision
added WP-0R and a conditional WP-10, and the Native Apple Reminders revision
added a conditional WP-11. The sequence the campaign is executing is below; the
original rows above are what section 15's divergence 2 corrected.

| WP | Objective | Depends on | Frontend? |
|---|---|---|---|
| WP-0R | Canonical re-mirror and reconciliation against the Remote Quick Capture revision | — | No |
| WP-4A | Application services: use cases, ports, shared policy and disclosure path, derived manifest | WP-3 | No |
| WP-4B | Transports: HTTP gateway, MCP adapter, operator CLI, composition roots, worker lease loop, parity matrices | WP-4A | No |
| WP-5 | Operations and local candidate | WP-4B | No |
| WP-6 | Capture domain, contracts, durable-first persistence, `capture.create`, registered client, submission, receipt, outbox | WP-5 | No |
| WP-7 | Capture processing, proposals, evidence spans, deterministic classification, restricted entity mentions, exact search | WP-6 | No |
| WP-8 | Review cases, promotion, conversation events, corrections | WP-7 | No |
| WP-9 | Relationship identity and read-only profiles | WP-4B, WP-8 | No |
| WP-10 | PWA capture surface and offline recovery — **deferred until after MCV completion by `D-104`; active gates `D-09`, `O-04`, and `O-20` remain** | WP-8 | **Yes** |
| WP-11 | Native Apple Reminders execution projection, internal sequence `NAR-00` policy amendment, `NAR-01` EventKit feasibility proof, `NAR-02` domain and contracts, `NAR-03` application services, `NAR-04` signed native bridge, `NAR-05` creation and updates, `NAR-06` completion roundtrip, `NAR-07` conflicts and recovery, `NAR-08` security and operational proof — **dependency-blocked by deferred WP-10; its completion-boundary placement is unresolved; active gates `NAR-OP-001`–`NAR-OP-009` remain** | WP-10 | No |
| WP-12 | Apple Mail, Calendar & Contacts — **authorized before MCV completion under `AUTH-WP12-20260804-OPERATOR-001`; internal order A, B, D, C, E, F, G, H; live and extreme-risk actions remain excluded** | WP-9; WP-10/WP-11 remain deferred, not prerequisites | Slice G only |

Two things about that table are worth stating rather than leaving to be inferred.

`D-28` split WP-4 because WP-4 as section 7 and this section specified it is
application services plus three transports plus two composition roots plus a
worker loop, which is more than one review can hold at the quality this campaign
requires. The split is a packaging decision and changes no objective: WP-4A and
WP-4B together are exactly the old WP-4, and every dependency that named WP-4
now names whichever half it actually needs — WP-9 needs the transports, so it
names WP-4B.

**WP-6 through WP-8 absorb the six new Remote Quick Capture record types rather
than growing a new package.** The revision added `CaptureSubmission`,
`RegisteredCaptureClient`, `CaptureDeliveryAttempt`, `CaptureClassification` and
`CaptureDomainAssignment`, `CaptureEntityMention`, and `CaptureCorrection` to the
canonical object model. None of them needs a package of its own: the durable-first
transaction, immutability, idempotency, evidence spans, and proportional review
they depend on are already the acceptance criteria of WP-6, WP-7, and WP-8. Adding
a package would duplicate those criteria; section 16 maps each type onto the
package that already carries them.

WP-0R through WP-9 are frontend-free and proceeded under `D-09`. **WP-10 is
not**, and the operator directly deferred it until after MCV completion on
2026-08-04 (`D-104`), superseding `D-32`'s assumed pre-completion sequencing.
WP-11 remains frontend-free — its surface is a signed macOS bridge, not a web
surface, so `D-09` does not reach it — but its declared WP-10 dependency makes
its placement conflict with that deferral rather than proving a post-completion
disposition. It also remains held by nine open operator decisions
`NAR-OP-001` through `NAR-OP-009`, one of which is the EventKit permission grant
and another the code-signing identity. `AUTH-WP12-20260804-OPERATOR-001` and
`D-106` expressly promote WP-12 ahead of WP-10/WP-11 for bounded synthetic-only
repository implementation; this reorders only WP-12 and does not reactivate the
two deferred packages. The remaining
frontend stages — Quick Capture `QC-05` through `QC-08`, and every responsive
surface in the Relationship Intelligence specification — are not planned here
and remain held.

`D-107` records the next-campaign handoff without starting it: only after MCV
completion is independently verified, a fresh orchestrator defines a
comprehensive MVP `CAMPAIGN-BRIEF` and executes the full MVP, including WP-10
and WP-11. That future instruction supplies no present authority to implement
either package, declare MCV complete, deploy, or cross an operator-only gate.

### WP-4 — application services and transports

**Objective.** Wire the eight existing `v1` capabilities to the behavior WP-2
and WP-3 built, and expose them over HTTP, MCP, and the operator CLI with proven
transport parity.

**In scope.** `src/my_pa/application/` use cases for the eight capabilities;
policy evaluation on one path shared by all three transports;
`src/my_pa/adapters/http/`, `adapters/mcp/`, `adapters/cli/` (or the equivalent
paths the implementing PR names, reconciled with `module-boundaries.md` section
3 — see the note below); `apps/gateway.py` and `apps/worker.py` composition
roots; the worker lease loop over the job plane WP-2 built; disclosure envelope
assembly from real coverage rather than constants.

**Out of scope.** Any capture or relationship behavior. Authentication mechanism
selection beyond a local principal (`P00-OD-010` stays open). Network exposure
beyond loopback. PDF (`P00-OD-003` stays open).

**Acceptance criteria mapped to tests.**

- `SPEC-AC-001` transport parity — a conformance matrix asserting HTTP and MCP
  produce byte-equivalent normalized requests and semantically identical
  responses and errors for all eight capabilities.
- `P05-SPEC-AC-002` negative evidence — traversal, source mutation, unknown
  scope, purpose escalation, and prompt-injection denial, each proven through
  every transport, not only one.
- `MB-AC-002` — architecture tests extended so `application` imports no
  transport, ORM, SQL, or provider module, and only composition roots
  instantiate concrete implementations.
- Capability manifest and readiness stop reporting `not_implemented` and
  `contracts_only` **because the manifest is derived**, not because a constant
  changed. `tests/contract/test_capabilities_and_readiness.py` already asserts
  derivation; extend it to assert the derived value tracks real availability.

**Note on path drift.** `module-boundaries.md` section 3 proposes
`src/my_pa/adapters/…` and `src/my_pa/apps/…`. The implementation instead uses
`infrastructure/providers/` and `infrastructure/persistence/`, and `apps/` is a
sibling of `src/`. Section 3 permits refinement, but the document and the tree
should stop disagreeing. WP-4 reconciles them in the same change that creates
the transports, and states which way it reconciled.

### WP-5 — operations and local candidate

**Objective.** Make the read-only slice runnable, observable, and recoverable by
one operator on one machine, and state its limitations honestly.

**In scope.** Startup and shutdown for gateway and worker; health and readiness
endpoints; empty-to-head migration validation as a gate rather than a test;
recovery and idempotency tests for interrupted extraction; the end-to-end
synthetic vertical slice from enrollment to `knowledge.read`; an operator
runbook; a limitations document that names what the slice does not do.

**Out of scope.** Deployment, production activation, packaging for distribution,
multi-user operation, and risk acceptance. All operator-gated.

**Acceptance criteria mapped to tests.** The seven numbered conditions in spec
section 3 each demonstrated by one synthetic end-to-end test; recovery tests
that kill a worker mid-extraction and prove no duplicate and no lost coverage;
a migration test that runs empty-to-head and head-to-empty against a disposable
database.

### WP-6 — capture domain, contracts, and durable persistence

**Objective.** Persist a user-authored capture durably, immutably, and
idempotently, and read it back with its provenance. Nothing derived.

Delivers the **durable-capture portion** of Quick Capture stages `QC-01` and
`QC-02`. *Corrected 2026-08-03 (`D-79`): this line read "Corresponds to Quick
Capture stages `QC-01` and `QC-02`", which overclaims. Read at
`../specs/quick-capture/19_MVP_DEFERRED_CAPABILITIES_AND_ROADMAP.md:143` and
`:152`, `QC-01` also requires "proposal/span schemas" and `QC-02` an
"original-text read/search stub" — both outside WP-6's seven acceptance criteria
and both assigned by this plan to WP-7. A sentence claiming WP-6 corresponds to
those stages whole would be a claim no criterion here supports.*

**In scope.** `domain/capture/` — capture and version entities, lifecycle
states, authority states, the immutability invariant, typed errors;
`contracts/v1/` additions for capture create, version create, read, and list;
new capability names and purposes added to `domain/identity/operation.py`;
one Alembic revision creating capture tables in the `knowledge` schema (or a new
schema the PR names and justifies); `infrastructure/persistence/capture.py`;
**`CaptureSubmission`, its `NOT NULL UNIQUE` idempotency key, and the capture
outbox**; the save transaction, as corrected below.

*Corrected 2026-08-03 (`D-73`): the in-scope list above omitted
`CaptureSubmission` and the outbox. It was written by `9096fa4` (#23), **before**
the Remote Quick Capture revision existed, and was not revisited when `c60f5cc`
(#25) extended WP-6 in three other places — section 7's merge order, section 12's
sequence table, and section 16's record-type mapping. It is an omission rather
than a narrowing, because it cannot have narrowed material that did not yet
exist, and section 7's closing precedence sentence settles it: "Items 4 through 13
restate section 12's sequence table, which is the authoritative one." The two remaining Remote
Quick Capture record types are deferred rather than in scope — see `D-74`.*

**The save transaction, corrected 2026-08-03 (`D-75`).** This paragraph read
"capture, version, receipt, **redacted audit**, and enqueued processing job
committed together or not at all", and the audit clause was false:
`SqlAlchemyAuditSink.record` takes its **own** connection and commits before
returning (`../../src/my_pa/infrastructure/persistence/audit.py`,
`../../src/my_pa/infrastructure/persistence/unit_of_work.py`), which is `D-34`
and cannot be undone without overturning it. The true statement is:

> capture + version + submission + receipt + enqueued capture job commit
> together or not at all, on the work connection. The redacted audit event
> commits **first and separately**, on the audit connection, per `D-34`; the
> version stores the audit **reference**. A failed audit fails the request closed
> and no capture exists afterwards. A failed work transaction leaves an audit
> event describing an authorization whose work never landed, which `D-34` records
> as the correct direction of the trade.

**Out of scope.** Extraction of any kind. Proposals, spans, review, conversation
events. Offline queue. Any frontend. Attachments. Model calls.

**Acceptance criteria mapped to tests.**

**Five of these were wrong or narrowed against the spec and are corrected in
place, 2026-08-03 (`D-75`).** Where a paraphrase here disagreed with
`../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md`, the spec
governs. Each correction is marked so a reader can see what moved.

**Two of those five are not plan errors, and calling them that was itself wrong
(`D-82`, `D-84`).** The idempotency code and the atomicity sentence were both
taken faithfully from the spec package; the disagreement is between the spec and
this repository's `v1` contracts, and between the spec and `D-34`. The
dispositions stand and the classifications are corrected — a conflict between two
instruments is recorded as open, where a plan error is closed by fixing the plan.
**And `QC-AC-034`, which `D-75` pronounced correct, is filed under the wrong
criterion (`D-85`).**

- `QC-AC-010` immutability **and independent retrievability** — a domain test
  proving no code path updates stored text, a database test proving the
  constraint holds under concurrent write, **and a test proving a superseded
  version is retrievable at its own identifier**. *Corrected: the paraphrase
  covered immutability only; spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:189` also requires "and independently
  retrievable", and a build resolving every read to the head of the chain would
  have satisfied the old wording.*
- `QC-AC-012` distinct timestamps — **five**, not three: `client_created_at`
  (device), `server_received_at` (server), `occurred_at`, `recorded_at`, and
  `accepted_at`, separately stored and never substituted for one another, with a
  genuinely absent client time stored as `NULL` rather than invented. *Corrected:
  this named three and silently dropped **occurred** and **accepted**. Spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:191` requires all five to remain distinct, so the paraphrase narrowed the
  criterion by two columns. Corrected a second time, 2026-08-03: the first
  correction glossed `recorded_at` as the criterion's "processed", which
  `../specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md` forbids —
  `:49` makes `recorded_at` "product event representing capture recording",
  `:51` makes `processed_at` "when a processing stage ran", and `:56` says "do
  not substitute one for another". WP-6 runs no processing stage, so it stores no
  `processed_at`; the five columns above are what WP-6 keeps distinct and the
  criterion's fifth slot is **`recorded_at` in its own right**, with
  `processed_at` arriving with WP-7's worker. A correction that fixed a count by
  mis-binding a name is the same class of defect as the one it fixed.*
- `QC-AC-013` editing appends — an edit creates a successor version, the
  predecessor stays retrievable, and the supersession chain is unbroken.
- `QC-AC-031`/`QC-AC-032` idempotency — replaying an identical request returns
  the stored receipt; reusing the key with different content returns **`conflict`
  with `safe_details: ["idempotency_key"]`** and stores nothing. *Corrected: this
  said `idempotency_conflict`. `../../src/my_pa/contracts/v1/errors.py` is a
  closed set of **eleven** public codes and that is not one of them, so the `v1`
  answer is `conflict`. Corrected a second time, 2026-08-03 (`D-82`): the first
  correction called this a plan error and said a twelfth code "would have been an
  unauthorised `v1` expansion" — as though the plan had invented the name. **It
  did not.** `idempotency_conflict` is the spec package's own word, at
  `../specs/quick-capture/18_PROPOSED_API_AND_CONTRACT_PACKAGE.md:255` and `:316`
  and `../specs/quick-capture/09_LOGICAL_DATA_MODEL.md:296`. Under `D-75`'s own
  rule that the spec governs, this is an **unresolved conflict between the spec
  and the `v1` contract**, not a corrected plan error. The disposition is
  unchanged and `18:14` is why: the proposed contracts "do not authorize
  implementation or change the repository's current `v1` capability set".*
- `QC-AC-034` — an induced audit or receipt failure fails the whole transaction
  closed, and no capture exists afterwards. Prove by planting the failure.
  *Unchanged, and deliberately so: this is right even though the mechanism
  sentence above it was wrong. Note what "afterwards" means at each end — an
  induced **audit** failure leaves nothing at all, while an induced **receipt**
  failure leaves no capture **and an audit row that survives**, because `D-34`
  makes the audit outlive the work it describes. A test asserting both absent
  would be asserting `D-34` is false.* **Corrected 2026-08-03 (`D-85`): the test
  is right and the criterion label is wrong.** Spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:208` reads "`QC-AC-034`:
  Processing failure never loses the source capture" — a *post-save* failure,
  requiring the capture to **survive**. The bullet above describes a *save-time*
  audit or receipt failure requiring **no capture to exist**, which is a real
  requirement with its own spec ground at
  `../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:37` — "if
  audit/receipt persistence required by policy fails, the server fails closed" —
  but is not `QC-AC-034`. Spec `QC-AC-034` is **not exercisable in WP-6**: nothing
  consumes `knowledge.capture_jobs` until WP-7, so there is no processing stage
  whose failure could lose a capture. `D-75` read this bullet as "true as worded"
  and did not compare it to the criterion it names.
- `QC-AC-041` — a redaction test asserting no capture text reaches logs, audit
  rows, **event payloads, or URL parameters**, and that the text **is**
  retrievable through `capture.read`. *Corrected: this named three sinks. Spec
  `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:214` names five — "logs, telemetry, event payloads, URL parameters, or
  lock-screen notifications" — and URL parameters is live here, because
  `capture.create` over HTTP must not accept text in a query string. The
  retrievability clause is what stops a build that stored nothing from passing.
  Corrected a second time, 2026-08-03: the first correction quoted the criterion
  as "error payloads" where the spec says the wider **"event payloads"**, and
  quietly kept "audit rows", which the spec does not name at all. Both are now as
  the spec has them, with audit rows kept as an addition this repository makes
  rather than as a quotation. **The two sinks still not covered by a test are
  telemetry and lock-screen notifications, and both are verified absent rather
  than assumed**: no telemetry emitter exists anywhere in `../../src/` or
  `../../apps/`, and there is no frontend, so neither sink is reachable. Head is
  strictly wider than base — three sinks became four — so nothing was narrowed;
  what is open is a criterion whose full sink list cannot be exercised until those
  sinks exist.*
- ADR-003 clause 5 — an architecture test asserting the source-provider port
  still exposes no write method and that capture persistence does not import it.

### WP-7 — capture processing, proposals, evidence spans, exact search

**Objective.** Turn a stored capture version into typed, span-bound, explicitly
noncanonical proposals, and make the original text searchable — without a model.

Corresponds to Quick Capture stage `QC-03`, restricted.

**In scope.** Worker stages `P-01` validate — which includes **loading the
processing-policy snapshot recorded at save** and branching on it (`11:46`,
`D-95`) and **denying prohibited destinations** — `P-02` normalise with a
reversible offset mapping **and identify quoted or pasted regions** (`11:55`),
`P-03` language detection allowing `unknown` and translating nothing silently,
`P-04` segmentation **including quoted and pasted regions** (`11:69`), `P-05`
deterministic extraction (dates, amounts, identifiers, URLs, explicit commitment
cues, **and known aliases where an alias table exists**) **each carrying an
authority classification** (`11:81`), `P-08` date normalisation **preserving the
raw phrase and identifying ambiguity rather than resolving it**, `P-09`
work-object proposals from deterministic cues only **recording the required
fields they could not fill** (`11:131`), `P-15` transactional proposal
persistence, `P-16` indexing of original text **immediately** (`11:191`).
Evidence spans on `unicode_code_point_v1` with quoted-text hashes re-validated
against the immutable version.

**Six stage deltas, admitted rather than left to a reviewer** (`D-89`). The
sentence above previously dropped: `P-01`'s policy-snapshot load and destination
denial; `P-02`'s and `P-04`'s quoted-and-pasted-region identification, which is
the *structural* half of `QC-AC-042` — marking pasted regions is how captured
content is made recognisable as data rather than as instruction; `P-05`'s known
aliases and its authority classification; `P-09`'s missing-required-fields, which
is what keeps a partial proposal honest instead of invented; and `P-16`'s
"immediately", which is what forbids indexing from sitting behind extraction.
Three of the six are implemented as written. `P-05`'s **known aliases** is in
scope and unreachable — it needs an alias table `Person`/`Organization` will
bring in WP-9 — and `P-05`'s **phone- and email-like strings** stay out, because
`11:78` permits them only "where policy permits" and the one policy this build
stores says nothing about contact detail. `P-08` resolves **no relative phrase**:
resolving one needs a clock, and a stage that reads a clock cannot satisfy
`QC-AC-035`'s replay clause, so ambiguity is recorded instead.

**`P-13` is in scope**, and this plan previously placed it neither in nor out —
a gap rather than a decision (`D-89`). It carries `QC-AC-042`'s retrieval
sentence (`11:177`: "Retrieval scope is explicit and recorded. Pasted/captured
text cannot expand tool authority"), so leaving it unruled would have left the
criterion's first half with no stage to live in. It is discharged **structurally**
rather than by a stage of its own: the pipeline resolves no source provider,
imports no network module, and takes every record's `version_id` from the job's
subject, so there is no retrieval for captured text to widen.
`tests/architecture/test_capture_reaches_no_source.py` is the static form and
`tests/pipeline/test_injection_corpus.py` the runtime one.

**Out of scope, and why — the exclusion stands and its stated reason did not.**
`P-06` named-entity extraction, `P-07` identity resolution, `P-12` contradiction
detection, and `P-14` summary generation are excluded because **each requires a
resolver or a generator this repository has not built and `P00-OD-006` is open**.
The previous wording called all four "model-assisted", and measured against
`11_EXTRACTION_AND_PROPOSAL_PIPELINE.md` that is **not what the specification
says** for three of them: `11` never uses the word "model" for `P-06`, `P-07` or
`P-12`, and `P-07`'s candidate ranking explicitly permits deterministic inputs
(`11:100` exact aliases, `11:107` chronology). Only `P-14` is tied to AI, and
indirectly. A reviewer checking the old reason against the spec would not have
found it there; the new one is checkable (`D-89`). Excluding them costs recall,
not correctness: a deterministic-only pipeline proposes less but proposes nothing
it cannot cite. **`P-06`'s output object is partly in scope even though the stage
is not** — `CaptureEntityMention` is built for the deterministic subset under
`D-93`.

**Acceptance criteria mapped to tests.** There are **six**, not five: `D-85`
carried `QC-AC-034` here, and `D-89` corrects five of the six statements below to
their spec strength. The binding text of each is
`../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md`, not this plan's
paraphrase.

- `QC-AC-011` — spec `20:190`: "Every proposal / **accepted derived record**
  points to **exact validated** source spans." Two corrections. "At least one
  span" is a *cardinality* and the spec asks for a *validation*, so the test
  asserts **re-derivation** of each cited span's digest from
  `capture_versions.content`, not a count. And the plan's stated proof —
  "mutating a version and re-running" — **cannot be executed on this schema**:
  merged revision `1a4c9e77b2d5` installs `capture_versions_are_append_only`, a
  `BEFORE UPDATE OR DELETE` trigger raising `restrict_violation`, so no writer
  including a test can update a version. The proof is **persistence-layer span
  injection** instead. **The accepted-derived-record half is out of WP-7's reach
  and is disclosed as half-discharged here**, to be re-proved by WP-8; it is not
  claimed. Tests: `tests/pipeline/test_proposal_spans.py`.
- `QC-AC-050` — spec `20:221`: "**Exact** original text is searchable
  independently of enrichment success." The word *Exact* was dropped and it is
  load-bearing (`D-89`, `D-90`): measured, `to_tsvector('english','…running…')`
  stores `run`, so a query for `run` matches text that never contains the word,
  and `to_tsvector('english','a the of and')` is **empty**, so a stop-word-only
  capture is saved, valid, and unfindable with no exception anywhere. The plane
  is therefore `simple` with an exact-substring confirmation, and **which queries
  that confirmation applies to is read from the server rather than decided in
  Python** — deciding it in Python falsified this criterion twice. The
  `P-16`-before-`P-15` ordering asserted in `test_save_does_not_wait.py` belongs
  to **this** criterion and not to `QC-AC-002`: a searchability confirmation
  sequenced behind proposal persistence never runs for the capture whose
  enrichment failed, which is the capture this criterion is about. Tests:
  `tests/search_quality/test_capture_search.py`,
  `tests/search_quality/test_exact_confirmation_matrix.py`.
- `QC-AC-035` — replaying a completed stage returns the prior output and creates
  no duplicate proposal; a lost lease cannot commit. Both additions are grounded
  (`11:212`, `D-45`(e)). **`capture_stage_results` stores no output blob**, so
  "returns the prior output" holds only while every stage is deterministically
  re-derivable from the immutable version plus the recorded pipeline version;
  that is proved per stage for all nine and the comparison is shown able to fail.
  The lost-lease proof is the **narrow** one — the lease is stolen from a second
  connection between two stages, and the test asserts both that the later stage
  committed nothing and that the earlier ones remain. **The spec's "or accepted
  objects" clause is discharged vacuously here** — no accepted object exists
  until WP-8 — and is stated as such rather than recorded as proven. Tests:
  `tests/pipeline/test_stage_replay.py`,
  `tests/jobs/test_capture_pipeline_recovery.py`.
- `QC-AC-042` — spec `20:215`: "Captured/pasted instructions cannot invoke tools
  or broaden **retrieval/disclosure**." "Widened scope" is not "retrieval and
  disclosure" (`D-89`): **disclosure is a first-class object here** —
  `application/disclosure.py`, canonical `09:130`'s `DisclosureEnvelope` — so the
  criterion also requires that captured text cannot suppress a limitation,
  inflate a coverage count, or alter a freshness label, which is the half least
  like a tool call and most easily missed. **The injection corpus's synthetic
  requirement is grounded in `QC-AC-073` (`20:239`) and `AGENTS.md` section 5,
  not in `QC-AC-042`**, which says nothing about where a corpus comes from. Tests:
  `tests/architecture/test_capture_reaches_no_source.py`,
  `tests/pipeline/test_injection_corpus.py`.
- `QC-AC-002` — spec `20:182`: "Save acknowledgment does not wait for
  AI/extraction/indexing." The stated proof is insufficient (`D-89`): "the
  committed set contains no proposal row" is about *membership* and the criterion
  is about *ordering*, so a save could commit no proposal while blocking on a
  synchronous index write and pass it. The test asserts the **whole** committed
  set. **One thing is disclosed rather than claimed**: WP-7 built the capture
  plane as a **functional GIN index over `capture_versions.content`**, not as an
  index table, so there is no index row for a committed set to contain and that
  half is structurally true rather than measured — and structurally true in the
  stronger direction, because a searchability the pipeline never wrote is one it
  cannot discard. What is measured for **this** criterion instead is the whole
  committed set, and that the saved capture is searchable **before any worker
  runs**. The `P-16`-before-`P-15` ordering the same module also asserts is a
  **`QC-AC-050`** property and not this one — a confirmation sequenced behind
  `P-15` never runs for the capture whose enrichment failed, which is the capture
  `QC-AC-050` is about — and the test's own docstring attributes it that way.
  Tests: `tests/pipeline/test_save_does_not_wait.py`.
- `QC-AC-034` — spec `20:208`: "Processing failure never loses the source
  capture." **The sixth criterion**, carried here by `D-85`, which ruled it not
  exercisable in WP-6 because nothing consumed `knowledge.capture_jobs` yet. WP-7
  is the package that consumes it. A second, independent ground `D-85` does not
  cite: canonical `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:108`, invariant 7 —
  "No processing failure hides Capture." Tests:
  `tests/jobs/test_capture_pipeline_recovery.py`.

**Processing-state vocabulary — ruled, because two instruments disagree.**
`../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:224-234` gives
nine aggregate processing states (`pending`, `processing`, `complete`, `partial`,
`needs_review`, `failed_retryable`, `failed_terminal`, `policy_denied`,
`superseded`); canonical
`../specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:98`
gives a **different seven** (`waiting`, `running`, `partial`,
`retryable_failure`, `permanent_failure`, `policy_denied`, `complete`). **WP-7
takes the canonical seven**, on the same ruling section 12 already makes for the
proposal states — canonical governs where the two disagree — and because `D-19`
ratified that document. **Neither is mapped onto `JobState`**, which is four
because four is what a worker needs: a job says whether a worker holds work and a
processing state says how far the pipeline got, and `partial` and `policy_denied`
have no job meaning at all. Implementing both vocabularies would give one fact two
names and no way to tell which a stored row meant. The instrument the ruling came
from is the canonical product definition; `domain/capture/pipeline.py` records the
same choice at the code.

### WP-8 — review cases, promotion, and conversation events

**Objective.** Give consequential proposals a governed path to canonical, and
give an explicit Conversation Log its skeletal event.

Corresponds to Quick Capture stage `QC-04`.

**In scope.** Review case model binding exact capture, version, proposal, spans,
target object, and expected version; all seven dispositions, five reachable in
this build; promotion receipts;
`domain/conversation/` skeletal, proposed, accepted, superseded states;
conversation participants including unresolved mention text; capture context
links with deterministic, user-confirmed, and proposed authority states;
re-validation of accepted downstream records when a source edit materially
changes a cited span.

**Out of scope.** Identity merge and split. External actions of any kind.
Notifications. Pulse or Today eligibility. Automatic promotion of anything.

**Acceptance criteria mapped to tests.**

- `QC-AC-020` — commitments, decisions, amounts, critical dates, and sensitive
  relationship conclusions cannot reach canonical without a review disposition.
  Prove the closed consequential-class policy exhaustively, then call the only
  canonical promotion writer without a decision and require denial before it
  reads persistence. The writer accepts only a proposal identifier, not a
  duplicated consequential-class input, so its no-decision guard is global.
- `QC-AC-021` — no code path executes an external action from an accepted
  record. An architecture test, not a runtime one.
- `QC-AC-022` — rejected and corrected proposals retain lineage; nothing is
  deleted.
- ADR-003 clause 8 — editing a capture whose span supports an accepted record
  moves that record to `revalidation_required` rather than silently rewriting or
  silently keeping it.

### WP-9 — relationship identity and read-only profiles

**Objective.** Person and organisation identity, unresolved mentions, duplicate
review, and source-backed profiles and timelines — over synthetic fixtures only.

Corresponds to Relationship Intelligence stage `R1`, restricted.

**The restriction comes from the specification, not from this plan.** `R1` as
specified reads contacts, email, and calendar. Section 38 item 5 of that
specification makes "personal-source access separately authorized by exact
connector, account, and scope" a precondition of any implementation, and section
33 lists "personal-source contracts approved" among R1's own prerequisites. No
such authorization exists, and `AGENTS.md` section 5 prohibits live email,
calendar, and contacts. Because the specification is `my-pa`-native rather than
an outside proposal, those gates are product intent and bind harder, not softer.

WP-9 therefore builds the identity and read-model layer against a **fixture
personal-source provider**, exactly as WP-2 built the read-only fixture source
provider. When the operator authorizes a real connector, it implements the same
port. Until then nothing in WP-9 touches personal data, and the package makes no
claim that it has.

**In scope.** `domain/relationship/` — person, organisation, identity
observation, alias, affiliation, unresolved mention; the duplicate-candidate
model with explicit candidate sets; profile and timeline read models assembled
from observations with coverage and freshness disclosure; a fixture
personal-source provider behind a read-only port with the same containment
conformance the file provider passes.

**Out of scope.** Live contacts, email, or calendar. Automatic identity merge.
Relationship scores. Sensitive-trait inference. Public research. Commitments and
briefings (they depend on WP-8 and on a model boundary). Pulse. Any frontend.

**Acceptance criteria mapped to tests.**

- Identity merge is impossible without a governed review disposition. Prove by
  attempting a direct merge and requiring denial.
- A profile discloses coverage and freshness for its exact observation set and
  never implies completeness. An absent observation is `unavailable`, never
  empty.
- Specification invariant 6.4 holds structurally: no composite relationship
  score field exists anywhere in the schema or contracts, no protected- or
  sensitive-trait field exists at all, and every permitted indicator carries its
  calculation basis and time window. A static test, so none of it can be added
  quietly.
- Specification invariant 6.1 holds: a contact-row observation cannot become a
  canonical person without a governed resolution, and identity merge is
  reversible and review-required.
- Specification invariant 6.3 holds: source observation, accepted assertion,
  user-authored private note, model inference, unresolved claim, contradiction,
  and stale assertion are distinguishable in the contract, not only in the UI.
  Private observations are the ADR-003 authority class, not a new one.
- The fixture personal-source provider passes the same containment and
  read-only conformance suite as the file provider, including the three exploit
  classes WP-2 closed.

### Mapping onto the canonical object model

`D-19` supersedes `D-17`: the canonical product direction is ratified as of
2026-08-02. Nothing above builds toward the canonical model beyond what the
operator promoted, because ratification granted no implementation authority
(`implementation_authority: NOT_GRANTED`) and the canonical roadmap's own first
step is to finish WP-4 and WP-5. No abstraction is created for it; this table is
documentation, not a design.

**This table was re-derived on 2026-08-02 and most of it was wrong.** It was
originally written against `my-pa vNext`. When ratification superseded that
document, the first version of this change relabelled the column from "vNext
object" to "Canonical object" and left every target unchanged — which assumed a
mapping stays valid when the document it maps onto is replaced. Independent
review caught it. The targets below are now derived from
[`../specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`](../specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md),
sections *Definitions*, *Supporting records*, and *State patterns*, with two
exceptions stated where they occur. `09` lists `SourceSpan` and `SourceRegion` as
bare names without definitions, so the basis for choosing between them is
[`10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md`](../specs/canonical-product-definition/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md)
sections *Text spans* and *Page regions*. `Affiliation` is in that same bare-name
list, and the name occurs exactly once in the whole package — nowhere else, and
under no definition — so its row claims name-identity and nothing more, and says
so.

A name appearing in `09`'s *Supporting records* list is **not** on its own a
derivation. That list is bare names with no definitions, and a second draft of
this table used one of them, `ContextLink`, as a mapping target on that basis
alone. It was removed. Two rows below do still map onto names from that list,
`SourceSpan` and `Affiliation`, and neither is offered as a derivation: each
discloses in its note that `09` does not define the name, and states what its row
actually rests on instead. Every other target below is a name `09` defines under
*Definitions*. Where a target rests on a definition, the note says what the
definition is.

The result is better news than the old table carried. The ratified model uses
this repository's own names for most of these objects, so the majority of rows
are identity rather than translation, and the "foreseeable rework" the previous
draft warned about largely does not exist. One row was actively misleading and
is corrected.

| Built here | Canonical object | Note |
|---|---|---|
| Capture, CaptureVersion (WP-6) | `Capture`, `CaptureVersion` | **Identity.** Defined under those exact names. `Capture` is a "product-owned Source envelope created through explicit authoring"; `CaptureVersion` is the immutable committed text and hash, and drafts are not versions until Save — which is ADR-003's shape |
| EvidenceSpan (WP-7) | `SourceSpan` | Both names appear in `09`'s *Supporting records* without definitions. `10` supplies the distinction: *Text spans* are UTF-8 code-point offsets under a versioned scheme with a quote hash, *Page regions* are a coordinate system with polygon or bounding box and a transcription candidate. WP-7 handles text, so `SourceSpan` |
| ExtractionProposal (WP-7) | `Proposal`, supporting an `Assertion` | The ratified model keeps **both** as distinct objects: `Proposal` is "candidate record/link/classification/transition before promotion", `Assertion` is the structured claim carrying authority state. See the note below |
| ReviewCase (WP-8) | `ReviewCase` | **Identity**, including the spelling |
| Promotion receipt (WP-8) | `Receipt` | **Identity.** "Immutable evidence of source acceptance or transition under exact identity/policy/authority/time" |
| Conversation (WP-8) | `Conversation` | **Identity.** A specialized `Interaction`/`Event` aggregate, not a generic Event. `Interaction` is the *supertype* — "meaningful exchange/contact", of which `Conversation` and `Meeting` are the specialized forms — and neither the supertype nor the `Meeting` sibling is built here |
| Person, Organization (WP-9) | `Person`, `Organization` | **Identity.** The previous draft mapped these to `Entity`, generalised across person, organisation, project, location, topic and document. **`Entity` does not exist in the ratified model** — `Person` and `Organization` are first-class, and that claim came from the superseded document |
| Affiliation, project association (WP-9) | `Affiliation`; project association has no distinct target | `Affiliation` is **name-identity only**, and rests on weaker footing than the rows above: `09` carries it in the same *Supporting records* line of bare names as `SourceSpan`, without definitions, and the name occurs nowhere else in the package. So this row discloses, as the `SourceSpan` row does, that its target is undefined in `09` rather than claiming a definition it does not have — what the name matches is a concept `09` does define elsewhere, `Person` carrying "aliases, affiliations" and `Organization` carrying "temporal affiliations and project relationships". Project association is *not* a separate object in the ratified model for that same second reason: `Organization` is defined as carrying "temporal affiliations and project relationships" directly. An earlier draft of this row named `ContextLink` — which exists only as a bare name in *Supporting records*, is defined nowhere, and was asserted rather than derived. Removed for the same reason `Entity` was. `Relationship` is a separate first-class object, the time and context-aware association domain explicitly "not a score", and is broader than what WP-9 builds |
| — | `Situation`, `Frame`, `Trace` | Still not built by any package here. The reason has changed: ratification satisfied the condition this row used to name, so what defers them now is that they are canonical stage `R1` scope, arriving after `R0` — which is WP-4 and WP-5 — and they carry no implementation authority |

The one place to be careful is still the proposal-to-accepted lifecycle, but not
for the reason the previous draft gave. It claimed a single Assertion carries a
trust state through "Confirmed, Strongly Supported, Probable, Possible,
Unverified, Contradicted, Stale, and Unknown", and told WP-7 to adopt that
ladder. **None of those values appear in the ratified model.** The ratified state
sets are:

- `Proposal`: `proposed`, `needs_review`, `accepted`, `corrected_accepted`,
  `rejected`, `deferred`, `unresolved`, `superseded`, `invalidated`;
- `Assertion`: `proposed`, `accepted`, `contradicted`, `stale`, `superseded`,
  `withdrawn`, `revalidation_required`.

The underlying guidance survives, because `Assertion` spans `proposed` through
`accepted` in one object: modelling a proposal and its accepted record as two
unrelated tables is still the rework to avoid. What changes is the vocabulary.
**WP-7 must take its state values from the two sets above, not from the ladder
the previous draft named**, and it should expect to carry a `Proposal` state and
an `Assertion` state rather than one blended trust score.

### Method for every package above

Unchanged from section 7. One branch, one pull request, squash-merged,
implemented by a delegated agent with disjoint file ownership, reviewed at exact
head by a separate agent that did not author it, with every test proven
non-vacuous by planting the violation and watching it go red.

## 13. The scope promotion, and the two instruments that made it

Section 5 said promoting the deferred workstreams "takes an explicit operator
reprioritisation of the objective under `AGENTS.md` section 3, not an
implementation choice, and not a specification amendment alone." On 2026-08-01
the operator issued that reprioritisation, naming two features and directing
that the specification and `AGENTS.md` be amended and the work packaged.

Both features arrive as `my-pa`-native product specifications, and that matters
to how they are handled. Section 5 described workstreams G and H as "absent from
[the MCV specification] — arriving from Drive feature packages," which framed
Drive material as an outside input to be reconciled inward. That framing is
wrong for these two. `FEATURE-MYPA-RELATIONSHIP-INTELLIGENCE-v0.2` was authored
against `my-pa@40391b78` in the current product design: it supersedes the
HBPA-branded `FEAT-HBPA-PRIE-001` v0.1 for current product intent, it cites this
repository's authority model and accepted ADRs, and its own scope gates name
`D-09` and the active MCV. The Quick Capture package was authored against the
same commit and reads the repository's state correctly, down to which work
package was next. These are not third-party proposals. They are the product
design, and the repository's specification index should say so rather than
listing the read-only slice as the only specification `my-pa` has.

Both are therefore mirrored into `docs/specs/`, following the precedent
`evidence/completion/README.md` set: exact Drive identity, export hash, and a
statement that a mirror is a review surface rather than repository authority.
Neither needed redaction; both scan clean of paths, addresses, and credentials.

Two different instruments were required to admit them, and conflating those
would have been the easy mistake.

**`AGENTS.md` section 3** defers scope "unless the operator explicitly
reprioritizes the objective." That sentence is self-executing: the operator's
instruction is the whole mechanism, and the amendment to section 3 records what
happened rather than authorising it. This is what admits Relationship
Intelligence. Its records are `observed` connector observations and `proposed`
inferences — rows that already exist in the authority matrix marked `Excluded`.
Promoting them changes a status, not a boundary.

**`AGENTS.md` section 4** is different. It preserves architecture boundaries
"unless an accepted ADR supersedes them", and an operator instruction is not an
ADR. Quick Capture stores bytes that `my-pa` itself owns, which no row of the
authority matrix described. The matrix had exactly two writable classes:
original source bytes, which `my-pa` may never write, and managed documents,
which are excluded and carry a separate-store, versioning, retention, and
restore contract. A note typed into a text field is neither.

The tempting shortcut was to lift the managed-write exclusion. That would have
opened a boundary far wider than the feature needs, and would have weakened the
rule that keeps a source provider from ever acquiring a write method.
[`../decisions/ADR-003-product-owned-user-authored-source-records.md`](../decisions/ADR-003-product-owned-user-authored-source-records.md)
instead adds one narrow row — a product-owned, user-authored, append-only,
PostgreSQL-resident source record — and states explicitly that it is not a
managed-document write and grants the source-provider port nothing.

### Additions to the decision register

| ID | Decision | Basis | State |
|---|---|---|---|
| D-10 | `D-03` partially lifted: Relationship Intelligence promoted into scope | Operator reprioritisation of the objective on 2026-08-01 under `AGENTS.md` section 3, which is the instrument `D-03` itself named. Managed documents (workstream E) and the Obsidian projection (workstream I) were **not** promoted and remain deferred under `D-03`. | Operator-directed |
| D-11 | Quick Capture promoted into scope, and admitted by ADR-003 rather than by reprioritisation alone | Quick Capture crosses `AGENTS.md` section 4, which only an accepted ADR may cross. ADR-003 adds one authority row and holds the managed-document boundary closed. Recorded separately from `D-10` so that a future reader cannot read one operator instruction as having moved both a scope line and an architecture line. | Accepted, ADR-003 |
| D-12 | The read-only slice is finished before either feature is built | WP-4 and WP-5 are all that remain of it, both features are specified against transports that do not exist, and Relationship Intelligence makes "current MCV substrate completed" its own first prerequisite. This is an ordering recommendation inside promoted scope, not a re-deferral; the operator may reorder. | Recommended, operator may reorder |
| D-13 | Relationship Intelligence R1 is built against a fixture personal-source provider, not a live connector | This is the specification's own gate, not a narrowing imposed on it. Section 38 item 5 requires personal-source access "separately authorized by exact connector/account/scope", section 33 makes "personal-source contracts approved" a prerequisite of R1, and section 2.3 states the feature is not part of the authorized slice until reprioritised. No connector authorization exists, and `AGENTS.md` section 5 prohibits live email, calendar, and contacts. Because the specification is `my-pa`-native, these gates carry more weight than an external proposal's caveats would, not less. Building identity and read models over synthetic fixtures is severable and mirrors how the file provider was built. `RI-OD-004` and `RI-OD-005` remain open. | Bounded by the specification's own gate |
| D-17 | The canonical product direction is recorded in the repository, by reference, as proposed | `my-pa vNext` (`SPEC-MYPA-VNEXT-PRODUCT-SYNTHESIS-v1.0`, Drive `17olnyUF5oX-KJWB6owRIJBB8B4QTlRjJhkLG47gio9s`) is named by the owning Drive index as the "sole canonical product-vision reference" and the "canonical implementation-agent instruction … for MVP framing and roadmap." The repository contained no reference to it, so an agent reading only the repository would not know the product has a defined mental model, a five-destination information architecture, or an object model built on Situations, Frames, Assertions, and Receipts, and could build a shape that has to be undone. It is recorded as `PROPOSED_CANONICAL_PRODUCT_DIRECTION`, which is its own declared status, and it is **not** treated as accepted: it grants no implementation authority, and nothing in section 12 builds toward it beyond what the operator promoted. Ratifying it is an operator decision nobody has asked for; see section 14. | **Superseded by `D-19` on 2026-08-02.** Left visible: every clause was true when written, and the last one stopped being true when the operator ratified the direction |
| D-18 | Corrected in place: `RI-OD-001` is not open in the way this plan first listed it | The canonical direction already resolves the naming question — "PRIE is superseded as a product name. The public area is **Relationships**; the domain is **Relationship Intelligence**." This plan initially listed `RI-OD-001` as blocking WP-9 contracts with no recommendation available. A recommendation does exist and is canonical-in-Drive; what remains is operator ratification, which is a smaller thing. Corrected rather than left, because listing a settled recommendation as an open question wastes the operator's attention, which is the resource this whole list is meant to protect. | **Superseded by `D-20` on 2026-08-02, and one clause of it was never verifiable.** The quotation attributed above to "the canonical direction" — "PRIE is superseded as a product name. The public area is Relationships…" — is `my-pa vNext` text. It appears nowhere in the ratified package; `grep` for "public area" across all of the then-24 mirrored artifacts returned nothing. The mirror is 27 members since the 2026-08-02 Remote Quick Capture revision, and re-running the same search across all of them still returns nothing, so the conclusion is unchanged and only the figure is historical. The conclusion it was used to reach is independently correct and now rests on ratified `CR-D-007` instead. Its closing clause, "what remains is operator ratification", stopped being true when that ratification occurred. Left visible for the same reason `D-17` is |
| D-16 | Both feature specifications are mirrored into `docs/specs/` and routed from the specification and source indexes | They are `my-pa`-native product design that now drives work packages, so a reviewer should be able to open them from the repository rather than from a Drive link. `docs/specs/README.md` previously listed the read-only slice as the only specification, which understated product intent. Mirrors follow the `evidence/completion/README.md` precedent: exact Drive identity, export hash, and no claim to repository authority. Neither required redaction. **Correction, 2026-08-02:** the phrase "and source indexes" was false when written. `docs/00_REPOSITORY_SOURCE_INDEX.md` routed only the MCV specification; neither mirror, nor `docs/specs/README.md` itself, appeared there. The routing was added with `D-19`, so the claim is true now — but it was a claim about work that had not been done, which is the kind of thing this register exists to catch rather than to produce. | Accepted; one clause corrected |
| D-14 | Model-assisted extraction stages are excluded from WP-7 | Named-entity extraction, identity resolution, contradiction detection, and summary generation all require a model gateway that does not exist and a disclosure decision (`P00-OD-006`) that is open. `AGENTS.md` section 2 forbids building the abstraction ahead of the need. Deterministic extraction proposes less and cites everything it proposes. | Deferred, disclosed |
| D-15 | Corrected in place: the frontend hold reads as permitting backend work, and this was assumed rather than asked | `D-09` records the operator's words as "no frontend implementation is in scope until they say otherwise." Every package in section 12 is frontend-free, so none of them tests the hold. But the hold was never asked about in the direction that matters — whether backend work on a held feature may proceed at all — and the Quick Capture package's `O-04` asks only *when* to lift it, not whether backend work needs it lifted. The reading here is that it does not. It is an assumption, it is stated as one, and it is on the consolidated list in section 14 for the operator to confirm or overturn. | Assumption, disclosed |
| D-19 | Supersedes `D-17`: the canonical product direction is ratified, and is recorded in the repository as ratified | **The instrument is a direct operator instruction issued 2026-08-02, not anything inside the package.** This matters, and independent review was right to demand it: the package nowhere uses the word "ratified", its status field `CURRENT_CANONICAL_PRODUCT_DEFINITION` is self-declared, its receipt grants nothing, and `15_OPEN_OPERATOR_DECISIONS.md` states "This package performs none." A self-declared status is precisely the evidence `D-17` ruled insufficient for the predecessor, so ratifying on that basis alone would have contradicted the standard this register set. What supplies it instead is the operator's instruction opening this session: that the product documentation, revised considerably, "is RATIFIED", identifying it by Drive ID `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`, with the direction to enforce it through the next implementation phase. That is the same self-executing form as the 2026-08-01 reprioritisation recorded at `D-10` — the instruction is the mechanism, and this row records what happened rather than authorising it. The subject is `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, version 2.1. It supersedes `my-pa vNext` for current whole-product definition and preserves it as source history; the two are siblings under one Drive parent, so this is supersession inside a lineage rather than replacement from outside it. It is mirrored byte-exact at `../specs/canonical-product-definition/` and verified against three independent in-package hash sources: 21/21 against the artifact disposition, 21/21 against the readback verification, and 20/20 against the source manifest, which covers every member except itself and says so. Three limits survive ratification and are the reason this is a decision rather than a scope change: it grants no implementation authority (`implementation_authority: NOT_GRANTED`); under `AGENTS.md` section 1 it is an indexed Workspace publication at precedence rank 4, below repository policy at rank 3; and its own `OP-05` and roadmap step `R10.1` direct that WP-4 and WP-5 finish first. Ratification endorsed this plan's sequence rather than displacing it. | Ratified, and bounded — see section 15 |
| D-20 | `RI-OD-001` stops blocking WP-9 and moves to non-blocking | The ratified decision log records `CR-D-007` — "RI is integrated domain; PRIE historical" — as `Canonical`, and the ratified executive description states that Relationship Intelligence "is the people-centered continuity domain inside my-pa… not a separate PRIE engine, database, frontend, or product", with `PRIE` "historical terminology retained only for provenance". That settles the name that enters `v1` contracts, which is the only part `D-18` said was blocking WP-9. Note what it does **not** settle, since `D-18` overstated this: the ratified information architecture lists Relationships under its **Library** section (`05_INFORMATION_ARCHITECTURE.md` line 51), and the ratified executive description states explicitly that Relationships and the collections listed beside it are "not separate top-level destinations" (`01_EXECUTIVE_PRODUCT_DESCRIPTION.md` line 88). Both citations are given because the first draft of this row credited that quotation to the information architecture, which does not contain it: `05` supplies the listing, `01` supplies the statement, and the conclusion needs both. `D-18` called it "the public area" — inherited from the superseded document, and contradicted by both. That framing is dropped here; only the naming conclusion is carried forward. What remains open is `OP-02`, the final UI label set, which the canonical package gates on "UI freeze" — frontend scope, independently held by `D-09`, and not a WP-9 contract input. Narrowing the claim to what the evidence supports rather than declaring the whole question closed. | Corrected; `RI-OD-001` reclassified |
| D-21 | Section 14's headline counts were wrong and are now derived rather than asserted | Section 14 stated "Forty-one decisions are open … Sixteen of them block." Recomputed from the tables themselves: **46 distinct IDs, no duplicates across the three tables**, and **29 of them blocking** at the moment of recomputation — the second table is itself headed *Blocking*, so counting only the first understated it by thirteen. `D-20` then moved `RI-OD-001` out of the blocking table, so the figures immediately after this correction were 46 open and 28 blocking; the total was never affected, only the split. They have moved twice since — section 16 opened two more, and `D-24` reclassified `P00-OD-011` — and deliberately no current figure is repeated in this row, because a count restated beside the derived one is the exact defect this row exists to close. A corrected constant would rot the same way, so `tests/architecture/test_open_decision_counts.py` now derives every figure from the tables and fails when the prose and the tables disagree. Each of its assertions was proven non-vacuous by planting a readable-but-wrong figure and confirming the count comparison fired for the intended reason. This is the third time in this campaign an inherited number proved stale on recomputation. | Corrected, and the mechanism corrected |
| D-22 | The Frontier NAS MCP Connector feature package is indexed by reference, not mirrored | Ratification brought a third feature package into canonical scope: `MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086` (Drive folder `1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa`, 17 members by `rclone lsf` on 2026-08-02 — a count no repository artifact attests, since the package is not mirrored). `D-16` mirrored the other two because they drive work packages in section 12 and a reviewer needs to check citations against files. This one drives no planned package: the canonical package's own `MCP-OP-001` recommends finishing the WP-4/WP-5 sequence first, and its acceptance crosswalk marks `MCP-AC-02` and `MCP-AC-04` through `MCP-AC-06` `NOT IMPLEMENTED`. Mirroring 17 further artifacts to support no citation would be scope this plan does not need, against `AGENTS.md` section 2. It is routed by exact Drive identity so it cannot be rediscovered as a surprise. | Indexed by reference |
| D-23 | Reconcile the module-boundary paths toward the tree, by a driving/driven split | Driving (inbound) adapters go in `src/my_pa/adapters/{http,mcp,cli}/`. Driven (outbound) adapters stay exactly where they already are, under `src/my_pa/infrastructure/{persistence,providers,migration,extraction}/`. Composition roots stay at repository-root `apps/`, a sibling of `src/`. **No existing module moves.** `docs/architecture/module-boundaries.md` section 3 permits refinement, and section 12's WP-4 entry requires the document and the tree to stop disagreeing rather than leaving a reader to work out which of the two is current. A driving/driven split is one rule instead of an ad-hoc list of exceptions, and it costs no churn: `infrastructure/providers/` already **is** section 5.8's `adapters.sources` under another name, so the reconciliation is largely a matter of saying what is already true. The amendment to `module-boundaries.md` section 3 is made by **WP-4B**, in the same change that creates the transports, so that the document and the tree move together rather than the document moving first and being wrong in a new way. | Accepted direction, binding WP-4A and WP-4B. **Performed by WP-4B2a**, which created `src/my_pa/adapters/{normalization.py,http/}` and amended `module-boundaries.md` section 3 — reconciling it *toward the tree*, by the driving/driven rule, moving no module. `adapters/mcp/` and `adapters/cli/` are placed by that section and remain unbuilt |
| D-24 | `capabilities.get` publishes effective limits derived from validated `MY_PA_` configuration, not from a module constant | The current `PHASE_01_LIMITS` values in `src/my_pa/application/capabilities.py` become the configuration defaults, so no published number changes on the day this lands. What changes is where the number comes from: **the published maximum is derived from the code path that enforces it rather than maintained beside it.** This resolves `P00-OD-011` for the MCV as a bounded, reversible configuration decision inside delegated authority — the operator can change a limit without a code change, which is the property a constant cannot offer. A corrected constant would rot exactly the way section 14's headline counts did before `D-21` mechanised them; this campaign has now had three inherited numbers prove stale on recomputation, and the fix each time was to derive rather than to restate. **`P00-OD-011` therefore moves out of section 14's blocking table**, since what remains of it is the operator setting different numeric values, which this decision is designed to accept without code change. | Accepted direction, binding WP-4A. **Not built.** The constant is still a constant; `P00-OD-011` reclassified in section 14. *Corrected 2026-08-08: **this state cell is false at `8dd4ef6`, and so is the rationale cell's pointer.** The direction was carried out. `src/my_pa/bootstrap/settings.py` builds `EffectiveLimits` from validated `MY_PA_` configuration in `effective_limits()`, called from the settings `@model_validator` so a bad limit fails at startup rather than at first request; `src/my_pa/bootstrap/gateway.py` passes `limits=settings.effective_limits()` through to `application/service.py`, and `src/my_pa/application/capabilities.py` takes `limits: EffectiveLimits` as a parameter (`:79`) and publishes it (`:100`) — which is exactly the derivation this row directed. Those two `bootstrap` citations are deliberately given without line numbers: the change carrying this correction modifies both files, and this plan's citation rule reserves a line number for a file the change does not touch. **No `PHASE_01_LIMITS` symbol exists anywhere** under `src`, `apps`, `tests`, `migrations`, `scripts` or `ops`; its only occurrences in the repository are inside this plan document, at this row and in the section 14 prose that restates it. So "the constant is still a constant" names a constant that is gone, and a reader following the rationale cell to `src/my_pa/application/capabilities.py` finds no such constant there. What was never done is not the work but the update: the row shipped its direction in WP-4A and carried "Not built" through every package since. The superseded wording is kept and negated rather than replaced, per the `D-78`/`D-81` shape. No new `D-` identifier is minted — see the note on identifier reservation below this table.* |
| D-25 | The HTTP transport uses Starlette and uvicorn, not FastAPI, bound to loopback | `SPEC-AC-001` requires HTTP and MCP to produce byte-equivalent normalised requests. That is provable when both transports share exactly one validation path — the existing `contracts/v1` pydantic models — and progressively harder to prove when they do not. FastAPI would add a second, HTTP-only validation layer that the MCP adapter has no counterpart for, duplicating validation this repository already owns and weakening the parity claim rather than strengthening it. Loopback binding is not a property of this choice; it is `P00-OD-010` and section 8, and it holds whichever framework is used. | Accepted direction, binding WP-4B. **Built by WP-4B2a**: Starlette and uvicorn, one route, loopback only, no FastAPI and no second validation layer. `apps/gateway/` is deleted and `apps/gateway.py` is the composition root. **Completed by WP-4B2b:** the parity half of `SPEC-AC-001` no longer waits — MCP and the CLI call the same `normalize`, and parity is proven structurally (no transport can construct a `RequestMetadata` or a command; only `adapters/normalization.py` may) as well as comparatively over all eight capabilities and nine refusals. The choice was vindicated in the way it was made for: there is one validation path and nothing to reconcile. **Corrected in place:** WP-4B2a's uvicorn floor of 0.29 was bisected from behaviour — the `SIGTERM` re-raise — and that derivation still holds, but it is no longer what binds. `mcp` 2.0.0's own metadata declares `uvicorn>=0.31.1`, so the declared floor rose to 0.31.1 or the `dependency-floor` job fails `ResolutionImpossible`; see `D-26` |
| D-26 | The MCP adapter uses the official `mcp` Python SDK over stdio | `AGENTS.md` section 2 admits a dependency that solves a problem the standard library reasonably cannot, and protocol conformance is that problem. Hand-rolling JSON-RPC framing, `initialize`, `tools/list`, and `tools/call` risks silent drift against a specification this repository does not own and cannot pin — a class of defect that surfaces as an incompatible client rather than as a failing test. ~~The SDK's transitive surface substantially overlaps what `D-25` already takes, so the marginal dependency cost is small.~~ **That last clause is false and is struck rather than deleted, so the correction is legible.** WP-4B2b measured it: `mcp` 2.0.0 forces `pydantic` from 2.7 to 2.12 and `uvicorn` from 0.29 to 0.31.1 — the second displacing WP-4B2a's bisected behavioural floor with a metadata constraint — and pulls `httpx2`, `cryptography`, `pyjwt`, `jsonschema`, `python-multipart`, `sse-starlette` and an OpenTelemetry API to serve the OAuth and streamable-HTTP surfaces `D-30` refuses outright. There is no extra that omits them. The overlap with `D-25` is `starlette` and `anyio` and nothing else. | Accepted direction, binding WP-4B. **Built by WP-4B2b**, and the decision stands on its first clause alone: protocol conformance against a specification this repository does not own is what `AGENTS.md` section 2's "cannot reasonably be solved with the standard library" contemplates. `mcp` moved from the prohibited list to the confined one, importable by `adapters/mcp` and nowhere else, exactly as `starlette` is confined to `adapters/http`. **Corrected a second time, and this correction is the more serious of the two.** The sentence first written here said that every unused package is prohibited from being imported and that `tests/architecture/test_scope_and_hygiene.py` "enforces that rather than trusting it". *That was false when it was written.* The guard was a hand-typed list; an independent review added `import cryptography`, `import httpx2`, `import jwt`, `import jsonschema`, `import sse_starlette` and `from opentelemetry import trace` to `application/service.py` and the entire FAST tier stayed green, because not one of those roots appeared on the list and the single entry meant to cover the HTTP client named `httpx` while `mcp` 2.0 declares `httpx2` — an entry that could never fire. Since the prohibition *is* this decision's whole surviving cost argument, the claim being unenforced meant the decision was resting on nothing. What makes it true now is a derivation rather than a longer list: the guard walks `mcp`'s declared requirement closure, extras included — which is how `cryptography` arrives, two hops away through `pyjwt[crypto]` — and maps each distribution to the import names it actually installs, since `pyjwt` installs `jwt`, `opentelemetry-api` installs `opentelemetry`, and `python-multipart` installs `multipart`. All six planted imports were re-planted against the derived guard and each fires. A future SDK release that adds a package nobody thought of is prohibited by having been declared. **The decision is more expensive than its rationale claimed**, and the struck clause is why; it is recorded here because a register row whose basis is measurably wrong is the defect this campaign keeps correcting. The floor is `mcp>=2.0,<3`, derived from the API this adapter uses: `Server(name, on_list_tools=…, on_call_tool=…)` is 2.0's constructor-based registration, and 1.29.0 raises `TypeError: Server.__init__() got an unexpected keyword argument 'on_list_tools'` — observed in a scratch environment, not read from a changelog. stdio only; no socket is opened and the network transports are never imported |
| D-27 | Async stays at the transport edge | `domain`, `application`, and `infrastructure` remain synchronous. Starlette endpoints are `def`, so Starlette runs them in its threadpool; the MCP adapter's async handlers call the synchronous application through `anyio.to_thread.run_sync`. `AGENTS.md` section 2 permits async only where real I/O concurrency justifies its lifecycle, testing, and debugging cost. The concurrency here belongs to the transport, not to the use cases: an async application core would buy nothing that the threadpool does not already provide and would force async SQLAlchemy through every layer beneath it. | Accepted direction, binding WP-4A and WP-4B. **Held by WP-4B2a for the HTTP half**: the endpoints are `def` and run in Starlette's threadpool, the application core is synchronous, and no `async def` or `await` exists anywhere in the package. Reading a request body is the one thing that must happen on the event loop, and it is bridged with stdlib `asyncio` rather than a new dependency. **Held by WP-4B2b for the MCP half, with one departure from this row's own wording:** the SDK's handler signatures force `async def`, so the edge is three coroutine functions and two `await`s in `adapters/mcp/server.py` and nothing else in `src/` or `apps/` — `serve_stdio` is an ordinary `def` that owns an event loop for one connection and returns `None`, so no caller ever sees a coroutine. The offload is stdlib `asyncio.run_in_executor`, **not** the `anyio.to_thread.run_sync` this row names, following WP-4B2a's precedent that a new dependency is not admitted for what four lines of the standard library do; owning the loop through `asyncio.run` is what fixes the backend and makes that safe. It is not decoration: the SDK dispatches each request into its own task, so running the synchronous application on the loop would stall every other request on the connection. `tests/architecture/test_async_stays_at_the_transport_edge.py` parses the tree rather than grepping it — the adapter's own docstring says "await" repeatedly — and pins both the location and the size of the edge |
| D-28 | WP-4 ships as two pull requests | WP-4A is the application core — use cases for the eight capabilities, ports, the shared policy and disclosure path, and the derived capability manifest. WP-4B is the transports — HTTP gateway, MCP adapter, operator CLI, both composition roots, the worker lease loop, and the parity and negative-evidence matrices, together with the `D-23` boundary amendment. `AGENTS.md` section 3 requires pull requests to be single-purpose and reviewable, and WP-4 as section 12 specified it is application services plus three transports plus two composition roots plus a worker lease loop — more than one review can hold at the standard this campaign is held to. **This is a packaging decision and changes no scope:** WP-4A and WP-4B together are exactly the WP-4 section 12 defines, every objective and exclusion is preserved, and dependencies that named WP-4 now name whichever half they actually need. | Accepted; sections 7 and 12 updated to match |
| D-29 | Remote Quick Capture is in MCV scope | The canonical package was revised in place on 2026-08-02 so that `12_MVP_DEFINITION.md` states "Remote Quick Capture is included in the MCV" and enumerates the complete minimal remote text-capture slice, and `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md` states it "is moved into the MCV delivery sequence rather than treated as a post-MCV enhancement." The operator's standing objective for this campaign is to complete the MCV **as defined by Drive folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`**. A revision to that folder's definition of the MCV is therefore a revision to the objective, reaching this plan through the objective's own reference rather than through the package's rank-4 authority. This is the same self-executing form as `D-10` and `D-19`: the row records what the objective now says, it does not authorise it. | Operator-directed, through the objective's own reference |
| D-30 | The capture endpoint is built behind the gateway boundary on loopback and is not exposed | Roadmap step 3 of the revision requires exposing "the capture-only authenticated HTTP endpoint on the existing gateway boundary", and MCV item 4 requires "an authenticated HTTPS endpoint with a capture-only device/client grant". Three things bound how far that may be taken here, and they agree. `P00-OD-010` — the authentication mechanism — is open. `AGENTS.md` section 5 reserves credential mutation and production activation to the operator. And the revised package restates both limits itself: `MYPA-RQC-D-008` states that MCV product inclusion "does not itself authorize repository mutation, credentials, ingress activation, deployment, production, or risk acceptance", and its own roadmap step 8 defers those to "separate operator activation decisions". So the endpoint is implemented and tested against a local capture-only principal on loopback. **No credential is issued, no ingress is activated, and no authentication mechanism is selected for external use.** Activation stays an operator act, and is tracked as `O-21` and `O-22`. | Bounded by policy the package itself restates |
| D-31 | The iOS Shortcut client is not built | It is roadmap step 4 and MCV item 5, and it is a client that must reach the endpoint across a network — which `D-30` does not open. Building it would produce something that cannot be exercised end to end without the operator act `D-30` withholds, and testing it "against a non-production endpoint" as the roadmap suggests still requires the endpoint to be reachable off the loopback interface. It is named here rather than left silent so it is not rediscovered as a surprise when WP-6 lands and the MCV is not remotely capturable. | Deferred, disclosed |
| D-32 | The PWA capture surface is admitted to scope, sequenced last, and this reading is an assumption stated as one | `D-09` records a direct operator instruction of 2026-08-01 that no frontend implementation is in scope "until they say otherwise". The revised package puts the PWA capture surface and the offline-recovery path inside the MCV (item 6) and inside the delivery sequence (roadmap step 5), and `D-29` binds the objective to that documentation — which is the condition `D-09` set for its own lifting. **The reading is not certain.** The package also carries `implementation_authority: NOT_GRANTED`, and under `AGENTS.md` section 1 a rank-4 indexed Workspace publication cannot on its own lift a direct operator instruction; the instruction that would lift `D-09` is the objective's reference to the folder, which is a thinner instrument than the 2026-08-01 words it would be overriding. So it is recorded as an assumption rather than a finding, the package is sequenced after every backend package as WP-10, and nothing else depends on it. If the operator overturns it, one package is dropped and none of the others is wasted — which is the whole reason for sequencing it last rather than for treating the question as settled. `O-04` and `RI-OD-003` already ask the operator when to lift the hold. | **Historical sequencing superseded by `D-104` on 2026-08-04.** Active WP-10 gates are `D-09`, `O-04`, and `O-20`; this row remains as provenance, not a current gate. |
| D-33 | The revised canonical package carries three disclosed defects | Stale front matter: all eight revised artifacts still carry `version: 2.1`, `prior_version: 2.0`, a `coordination_request_id` naming the earlier MCP-integration roundtrip, and `repository_head: 9096fa4…`, one commit behind `main` at `ef08ddd`. Unpublished readback evidence: the `revised-artifact-readbacks/`, `publication-controls/`, and `noop/` subfolders of the RQC control folder are empty while the publication receipt asserts `canonical_specification_readback_observed: true`. And no readback-verification artifact was published at all, unlike the MCP-integration set. Section 16 records each as verified here rather than inherited, and records which check therefore carries the mirror's integrity claim. They are disclosed rather than averaged into a general statement of confidence, because the first of them is the reason a version-field check would have reported no change at all. | Disclosed, not smoothed |
| D-34 | WP-4B adds the durable audit store and closes the audit asymmetry | An Alembic revision creates an audit table in the `knowledge` schema — `migrations/versions/20260802_9c6b4a18ed72_create_the_audit_events_table.py`, adding `knowledge.audit_events` — and WP-4B's composition roots supply the production `AuditSink`. WP-4A defined the port and called it on every authorization decision but had no migration authority, so the only implementations were test doubles; a process that authorizes without a durable audit trail violates `AGENTS.md` section 5. The sharper half of this is an **asymmetry, not a gap**: an *allowed* request whose handler then failed rolled its audit event back with the work transaction, so a failed security-relevant action left no trace while a denial committed. WP-4B closed it by giving the audit a separate transaction, which `src/my_pa/application/service.py` states in its own module docstring. | Implemented by WP-4B1, PR #27 |
| D-35 | Provider reads may happen inside the database transaction, while the provider is local | [`../architecture/module-boundaries.md`](../architecture/module-boundaries.md) section 10 discourages holding source fetches inside database transactions, but it carries `status: PROPOSED_FOR_REPOSITORY_REVIEW` and is a candidate rather than accepted policy, and `AGENTS.md` section 4 is silent on the interleaving. The read is bounded by `max_fetch_bytes` against a local filesystem adapter, and one consistent read means the disclosed coverage and the returned bytes come from the same instant. **Invalidated by a source provider that is not local.** `src/my_pa/application/service.py` carries the sentence that says so, and it is the first thing to change if a remote provider is ever admitted. | Accepted, bounded by locality, invalidation named |
| D-36 | WP-4B splits again, into WP-4B1 and WP-4B2 | WP-4B1 is the durable audit store (`D-34`), the `apps/worker.py` composition root, and the worker lease loop — no transports and no new dependencies. WP-4B2 is the HTTP gateway, the MCP adapter, the operator CLI, `apps/gateway.py`, the parity and negative-evidence matrices, and [`../architecture/module-boundaries.md`](../architecture/module-boundaries.md)'s reconciliation. WP-4B as scoped was a migration, a durable store, two composition roots, a lease loop, three transports, and two conformance matrices; WP-4A was already at the edge of what one review can hold at this standard and took four review rounds, and this was larger. The split is natural rather than arbitrary — the audit store and the worker need no transport, and the transports need the audit store to exist before a gateway can run authorized requests. It is a packaging decision and changes no scope. | **Implemented as three pull requests, not two.** WP-4B2 split once more on the same reasoning, so the outcome is WP-4B1 (PR #27, `93cb98e`), WP-4B2a (PR #28, `7390879`), and WP-4B2b (PR #29, `77ed807`) — mapping recomputed from `git log main`, not restated. The two-way split is what was decided; the three-way split is what happened |
| D-37 | The vertical slice has a hole in the middle, and closing it is WP-4B3 | Two identifier spaces do not meet. `sources.enroll` stores `obj_…` identifiers with no foreign key, while `persistence.extraction` records outcomes only against `source_objects` rows that `observe_object` issued from a native locator. WP-4B3 builds the production write path to `knowledge.sources`, persists the enumerated object set at enrollment through `observe_object`, and builds the worker's extraction executor. **Corrected in place, and the correction is the point.** The original wording said `sources.enroll` stores identifiers "a provider instance minted". Recomputation against the code at `77ed807` shows `sources.enroll` never consults a provider at all: `EnrollSource.__post_init__` (`src/my_pa/application/commands.py`, cited by symbol rather than by the line it stood on at `77ed807` — 208, with its validation block at 229-242 — because WP-6 moved every one of those numbers) stores whatever `obj_…` strings the caller supplied, shape-validated only, against no referential check. The original citation of `commands.py:230-238` is also narrower than the block it names — 230-238 covers the source, media-type, idempotency-key, and selector checks, and the per-object shape check is at 239-240. Both corrections are recorded rather than quietly applied, because the campaign does not conceal decision errors. | Corrected in place; **closed by WP-4B3**, which built the write path to `knowledge.sources`, the enrollment-time enumeration, and the executor — on `D-41`'s diagnosis rather than on this row's |
| D-38 | The canonical package was revised again on 2026-08-02T15:01Z to v2.2, and the re-mirror is its own work package | `REQ-MYPA-CANONICAL-PRODUCT-NATIVE-REMINDERS-INTEGRATION-20260802T150100Z` took the package from v2.1 to v2.2 and admitted Native Apple Reminders to the MCV. A documentation re-mirror is not folded into a behavioural package, for the reason WP-0R was separated from WP-4: the two need different reviewers and have different failure modes. Ten mirrored artifacts differed, detected by SHA-256 against the WP-0R mirror. Nine are a front-matter edit plus an appended section; one, `18_PACKAGE_SOURCE_MANIFEST.json`, is a structural in-place rewrite. **Two corrections to what was expected.** First, the nine are *not* a pure byte-suffix append: recomputed at `77ed807`, each new body equals the old body **minus its final newline**, plus the appended section, and each front matter changed six fields in place — so the whole-file prefix-append property that carried the v2.1 mirror's integrity claim does **not** hold here and is not claimed. Second, the `version:` field **did** bump, 2.1 → 2.2, unlike the RQC revision that `D-33` records. That is a fact about this revision only and is not evidence the stale-front-matter hazard is gone; a hash check remains the only reliable detector, and it is what found this one. | Re-mirrored by WP-0R2 |
| D-39 | Native Apple Reminders is in MCV scope as `WP-11`, sequenced last, and **nothing in it is built** | The reading is the one `D-32` states: the operator's objective binds the MCV to Drive folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`, so a revision to that folder's MVP definition is a revision to the objective. `12_MVP_DEFINITION.md` now includes an opt-in Native Apple Reminders execution projection, and `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md` recommends it as `WP-11` "after the PWA capture/Review path" — which is why it is sequenced after WP-10 rather than negotiated. The mitigation is the same as `D-32`'s: sequence it last, so overturning it costs one package and wastes none of the others. **Every activation is gated.** `NAR-OP-001` through `NAR-OP-009` are all open, and `implementation_authority: NOT_GRANTED` holds across the package. No code-signing identity, no credential issuance, no EventKit permission grant, no live Reminders access, and no external action on any Apple application. The operator must resolve `NAR-OP-001`–`NAR-OP-009` before `WP-11` can start. | **Historical pre-completion sequencing superseded by `D-104` on 2026-08-04.** Active WP-11 gates are `NAR-OP-001`–`NAR-OP-009`; this row remains as provenance, not a current gate. |
| D-40 | Carry `D-34`, `D-35`, and `D-37` into this plan in WP-0R2, not WP-4B3 | WP-0R2 *is* the plan-reconciliation package, so it is their right home. A register row citing a decision the repository does not carry is the `D-16` defect. **The handoff's own claim was stale, and this decision's first correction of it was itself wrong.** The handoff asserted that `D-28` and `D-34`-`D-38` lived only in the campaign brief; `D-38` did not exist and was minted in the same session. The correction then said `D-28` and `D-36` were already in the plan, on the strength of a `grep` for the bare identifier. WP-0R2's implementer overturned that: `D-36` appeared exactly once, inside section 6's sentence "recorded by `D-28` and `D-36` in the register" — a citation with no register row behind it. Verified independently, `grep -c "^\| D-36 \|"` returned 0 at `77ed807` while `D-28` returned 1. So WP-4B2b shipped the `D-16` defect it had been warned about, a bare `grep` was the wrong instrument for detecting it, and **four** decisions were missing rather than three. Invalidated by nothing; this is a placement decision. | Implemented by WP-0R2, PR #30 |
| D-41 | WP-4B3's scope is larger than its assignment stated, and the assignment's mechanism claim is wrong | Recomputed at `77ed807`, four findings. (i) `sources.enroll` **never consulted a provider** — it stored whatever `obj_…` strings the caller supplied, shape-validated only, into `enrollments.object_ids` and `enrollments.root_object_id`, which carry **no foreign key**. (ii) `authorized_object` therefore evaluated **false for every object, silently**, producing empty coverage and empty search with no error anywhere. (iii) The entire extraction *write* path — `record_outcome`, `quarantine_object`, `record_limitation` — had zero production callers, as did `register_source` and `observe_object`. (iv) **There was no production write path to `knowledge.sources` at all**, so `sources.enroll` always returned `not_found` and was unreachable. The direction that follows: **do not bridge the two identifier spaces — make `source_objects` the single authoritative one** and stop treating a provider's per-instance identifiers as authoritative; `infrastructure/providers/fixture.py`'s argument that a locator-derived identifier would defeat `INV-PKL-005` stands unchanged. `D-37` was written from two implementers' reports rather than from the modules, and recomputation found the blocker strictly *upstream* of where `D-37` put it. Persisting the enumerated object set is **one** fact that closes both the root-selector containment gap and the unmeasured denominator, and fixing either alone would have meant building the same persistence twice. Invalidated by evidence that any of the four findings is wrong. | Accepted; supersedes `D-37`'s diagnosis; implemented by WP-4B3 |
| D-42 | Source registration is an operator command under `apps/cli/`, not a ninth capability | The capability set is closed at eight by the canonical contract (`src/my_pa/domain/identity/operation.py`), and `adapters/cli/app.py` is a generic dispatcher over exactly those eight. `apps/cli/invoke.py`'s module docstring already made this argument for `migration.py`: operator commands live beside the capability dispatcher and share nothing with it, because merging them "would have made a migration phase look like a ninth capability." Adding a capability would also be a scope expansion beyond the canonical definition, which is precedence rank 4 and not this campaign's to amend. Invalidated by a canonical revision adding a registration capability. | Implemented by WP-4B3 — `apps/cli/sources.py` |
| D-43 | WP-4B3 stays one package despite its size | The split judgement (`D-28`, `D-36`) has been right twice and this package is larger than WP-4B1, and it is still not split, because its seven acceptance criteria interlock. Criterion 7 requires the identifier bridge proven from **both** ends, and `sources.fetch` resolves `source_object_id` in provider memory while `knowledge.read` resolves it in the database. Any split leaves criterion 7 half-proven, and shipping a half-proven acceptance criterion is the "silently narrow the acceptance criteria" failure this campaign exists to avoid. The size is managed with disjoint worker ownership and review rounds instead. Invalidated by a design showing a split that leaves **no** criterion half-proven. | Held; re-assessed and reaffirmed by `D-52` |
| D-44 | Make the canonical mirror's readback receipts executable, in WP-0R2 | A FAST test binds each mirrored artifact to the newest `READBACK-VERIFICATION-*.json` naming it and asserts the file's SHA-256 and byte count equal the recorded values. The mirror's entire value is that a reviewer can check a citation against a file, and **nothing had ever checked those bytes**: the receipts record per-artifact SHA-256 and assert `match: true`, but they are claims published by the process that wrote the files, and `D-33` already recorded one publication asserting readback was observed while its readback subfolders were empty. A guarantee that exists only in prose is not a control. Two wrinkles made it worth doing properly — the two receipt cycles use **different schemas**, and the older MCP receipt legitimately binds superseded bytes for the ten twice-revised artifacts, so the test resolves the *newest* receipt per artifact and fails loudly on an unrecognised schema rather than silently checking nothing. **Two scope limits, stated so they are not overclaimed.** It proves the mirror matches what the publisher recorded and **not** that the mirror is current against Drive, which needs network access and stays a manual reconciliation. And **10 of the 31 mirrored members are named by no receipt and are checked by nothing** — three dispositions, three publication receipts, two roundtrip receipts, and the two readback receipts themselves; independent review proved it by flipping `NOT_GRANTED` to `GRANTED____` inside a publication receipt with all 72 tests staying green. It is not fixable in-repo by binding them to recorded byte counts, because that plant was a same-length substitution. Of the ten, six carry a published in-package SHA-256 and four are hashed by nothing. The correction cycle first wrote that split as 5/5, having recomputed over the **31 mirrored files** while making a claim scoped to **the 42-member package** — recomputing over the wrong universe inside the paragraph correcting exactly that defect, which re-review caught and BLOCKed. Invalidated by nothing. | Implemented by WP-0R2, PR #30 — 72 cases |
| D-45 | Accept the WP-4B3 design | Its five load-bearing choices are adopted as direction. (a) **Enumerate at enroll time, inside the enroll transaction**, not in the worker: worker-side enumeration opens a window with an accepted grant and no measured denominator, which would need a *new* disclosure token to distinguish "not measured yet" from "not measurable" — more machinery to describe a window the design itself created. (b) A **new `knowledge.enrollment_objects` table**, composite primary key `an_enrollment_holds_an_object_once`, both columns foreign-keyed — not a foreign-keyed array, because PostgreSQL has no element-level foreign key and because `object_ids` is part of `request_fingerprint` and so records what was *asked for*, a different fact from what enumeration *found*. (c) **Delete `ELIGIBLE_TOTAL_NOT_PERSISTED`, `SCOPE_IS_SOURCE_WIDE`, the clamp, and the `eligible: int or None` parameter** — removed rather than redefined, because leaving `None` in place with a new meaning is the same defect class being fixed. (d) **`SourceRepository` gains no write method**: the operator command is a composition root and calls `register_source` and `observe_object` directly, exactly as `apps/cli/migration.py` calls `infrastructure.migration.*`, and it writes **no audit event** because `audit_events.capability` is closed to the eight and a ninth member is what `D-42` forbids. (e) **`JobHandler` becomes `(Engine, LeasedJob, str)` and work commits per object**, with the provider read outside any transaction and lease ownership re-established one level down by a new `hold_lease` taken inside every write transaction. (a)-(d) are argued from the tree rather than asserted. (e) decides itself: `module-boundaries.md` forbids holding source bytes inside a database transaction, and at the existing ceilings — 10 000 objects times 8 MiB against a 300 s lease — a per-enrollment transaction **cannot finish inside its lease**, giving rollback, three attempts, terminal `failed`, and **no object ever recorded**. That is a livelock, not a scale concern. Invalidated by evidence that per-object commit violates a boundary the design did not check. | Accepted; the second half of (b) overturned by `D-48` |
| D-46 | Widen the CI database-tier job to `-m "database or recovery or e2e"` | Do not drop the `recovery` and `e2e` markers from the tests, and keep the FAST exclusion as it is. The rationale first recorded here — that the repository held zero `recovery`-marked and zero `e2e`-marked tests, so both markers were declared and unused and WP-4B3's criterion-5 recovery tests and criterion-7 end-to-end slice would be committed and never executed — was **half wrong, and `D-53` records the measurement that corrected it**. `AGENTS.md` section 7 places recovery and idempotency tests in FULL and criterion 5 is a FULL-tier property, so the markers carry meaning and must survive; a green CI that never ran the hardest tests is not evidence. Invalidated by a separate FULL-tier CI job that runs them. | Implemented by WP-4B3; premise corrected in place by `D-53` |
| D-47 | Execute WP-4B3 in one isolated git worktree per parallel ownership set | With `PYTHONPATH="$PWD/src"` on every test command, integrated by the orchestrator onto a single branch. The `.venv` editable install resolves `my_pa` to the primary checkout, so concurrent workers sharing one checkout silently import each other's half-finished edits — this produced twelve phantom failures once already. Worktrees with an explicit `PYTHONPATH` make concurrency safe and keep file ownership disjoint and enforceable. Invalidated by a non-editable install, or by a permanent single-worker cap. | **Superseded in practice** on 2026-08-02 by the operator's one-worker-at-a-time cap; retained because it is correct whenever concurrency returns |
| D-48 | Remove the `enrollments.root_object_id` foreign key from WP-4B3 entirely | Keep `enrollment_objects` and both of *its* foreign keys — those are on a new table and are not retroactive. Re-attribute the "a root that does not exist is refused" guarantee to enumeration plus `record_scope`, and record in the code **why** the constraint is absent so a later reader does not add it back. Measured by S1's implementer and independently confirmed: `20260801_7e5a1fb93d62_create_knowledge_schema.py` creates `enrollments` via `METADATA.create_all(bind, tables=_TABLES)`, and `METADATA` is shared at import time — so declaring a `ForeignKey` on `root_object_id` in `tables.py` **retroactively changes what an already-merged revision emits**, and a base-to-head replay produces different DDL than it did before the declaration existed. At head it yields two identical constraints, and downgrading the new revision leaves the first behind, so `9c6b4a18ed72` stops denoting one schema. **Proved inherent rather than a mechanism choice**: with the `tables.py` declaration removed, the same **13** `test_knowledge_schema_migration.py` tests still failed on the revision-created constraint, because that file's helpers legitimately mint synthetic never-observed `root_object_id` values for schema tests. A migration chain whose earlier revisions change meaning when a later one is written is not a chain. **And the constraint is redundant with a control this package already builds**: enumeration runs inside the enroll transaction, a root naming no observed object cannot be enumerated, and `record_scope` refuses an empty set. Belt-and-braces, at the price of chain integrity. **No acceptance criterion is narrowed** — the root foreign key appears in none of the seven. Invalidated by a mechanism that adds the constraint without altering what a prior revision emits **and** without requiring 13 schema tests to observe their synthetic roots first. | Implemented by WP-4B3; overturns the design's section 3.3 and the second half of `D-45`(b) |
| D-49 | `record_scope` raises `ValueError`, not `InvalidRequestError` | `InvalidRequestError` lives in `src/my_pa/application/errors.py`, and `tests/architecture/test_dependency_direction.py` forbids any `infrastructure/` module importing `my_pa.application.*`. `ValueError` is the idiom of the neighbouring writers in `infrastructure/persistence/extraction.py` and `registry.py`, and `unit_of_work._Knowledge.coverage` already classifies it at the port boundary. The design's section 7 reference to `InvalidRequestError` is simply wrong; the property it names survives unchanged. `UnknownScopeError` *was* named correctly. Invalidated by an accepted change to the dependency direction. | Implemented by WP-4B3; corrects the design |
| D-50 | Merge ownership sets S2 and S4 into one assignment, S24 | Execute the remainder as three implementer runs — S24, then S5, then S6 — not four. S2 and S4 were split for *concurrency*, and the operator's serial cap removed the concurrency; under the cap the split has no benefit and two real costs. (i) S2's tree **cannot** typecheck or pass a tier by construction, so a standalone S2 run produces no independently verifiable state, and this campaign's whole method is verifying each head. (ii) The `eligible`/clamp deletion is the campaign's **signature two-copy defect**, and splitting it across two runs is precisely the shape that has blocked a pull request before; merged, both copies plus the `FORBIDDEN_NAMES` entry land in one worker's hands under one search. Ownership stays disjoint from S5. Invalidated by evidence that S2's and S5's file sets in fact overlap, which would mean the design's ownership tables are wrong. | Executed — S24 landed as one commit |
| D-51 | S6 additionally owns the `docs/` files carrying the stale Alembic revision count | `docs/architecture/system-context.md`, `docs/architecture/00_ARCHITECTURE_INDEX.md`, and `docs/migration/00_MIGRATION_INDEX.md`, in addition to two lines of this file. The count was **two** revisions stale, not one, and WP-4B3 adds another — so leaving these makes them wronger, which is the stale-claim defect this campaign has recorded three times. `README.md`'s copy was already fixed by WP-4B3's first wave in exactly this spirit; leaving its four siblings stale would prove the fix in one shape and not in its neighbours. S6 is the `docs`-owning set and no other set touches these files. Invalidated by a set other than S6 taking `docs/` ownership. | Implemented by WP-4B3 |
| D-52 | WP-4B3 is **not** split into two pull requests, and `D-43` stands unmodified | The package ships whole — S1, S3 and S24 landed, plus S5 and S6 — under one independent review against one head. Assessed against the seven acceptance criteria rather than against convenience, because splitting would overturn a standing decision. **(i) The boundary is not defensible.** A first pull request of S1, S3 and S24 plus the `D-46` widening satisfies **exactly one** criterion outright — criterion 3 — and only partially criteria 1 and 4; criteria **2, 5, 6 and 7** all need S5's executor and the operator command, neither of which would exist. Six of seven left over is not a split, it is a prefix. **(ii) It would narrow criterion 3, which is the stated bar for refusing.** Criterion 3 requires that where the eligible total *cannot* be measured, the envelope discloses that rather than implying completeness; S24 deleted `ELIGIBLE_TOTAL_NOT_PERSISTED` and `SCOPE_IS_SOURCE_WIDE` from the emittable vocabulary on the strength of "eligible is now always a true one", a claim only *testable* once the executor and the both-ends bridge exercise the enumerated set. Merging that deletion ahead of S5 removes the disclosure escape hatch **before the code that could reveal a case needing it exists**. **(iii) The economics invert.** A split needs **two** independent review cycles against two heads instead of one, and review plus corrections is the dominant cost under the one-worker cap, so the split spends more of the scarce resource it was proposed to save. Invalidated by S5 or S6 proving materially larger than budgeted **and** a re-assessment showing the first pull request no longer narrows any criterion. | Held; the package ships whole |
| D-53 | `D-46`'s widening still lands, but its stated premise was wrong and the register must not carry the wrong reason | Widen the database-tier job to `-m "database or recovery or e2e"`, keep the markers on the tests, and leave the two FAST jobs excluding both. The premise recorded in `D-46` and repeated in three handoffs was that recovery and e2e tests "will never run in CI" unless the job is widened. Measured and independently confirmed: `-m database` selects **any** test carrying the `database` marker whatever else it also carries, every `recovery`-marked test carries both, and `-m "recovery and not database"` collects **0 of 2478**. The existing recovery tests therefore **did** execute in CI and the widening does not rescue them. It is still required for the two reasons that do hold: **`-m e2e` collected 0 of 2478**, so WP-4B3's criterion-7 end-to-end tests would run in no job unless they also happened to carry `database`; and the present safety is **contingent on every future recovery or e2e test also carrying `database`**, which nothing enforces. A decision that survives on a false premise is one measurement away from being discarded along with the premise. Invalidated by a mechanical guard asserting that every `recovery`- or `e2e`-marked test is selected by some CI job, which would make the widening redundant — no such guard exists. | Implemented by WP-4B3, with the corrected reason in the workflow's own comment |
| D-54 | S6 additionally owns four items S5 surfaced that belonged to no ownership set | `README.md`'s two now-false claims, `docs/architecture/module-boundaries.md`'s "two programs", the missing `all_sources` reader in `infrastructure/persistence/registry.py`, and the absent `tests/jobs/README.md`. S5 refused to edit outside its ownership and reported instead, which is correct behaviour and is why these are visible at all. Three of the four are **stale claims created by this package's own change** — the exact defect class the campaign has recorded three times — and leaving them would ship a README that denies the executor the same commit adds. The `all_sources` gap is different in kind: the design's section 5.4 guard allowlist names a reader that does not exist, so S5's guard names a *table* instead, a documented workaround that must either be closed or explicitly justified rather than left silent. Invalidated by an owner other than S6 taking `docs/` and `registry.py`. | Implemented by WP-4B3; see the closing note of this section for what each item resolved to |
| D-55 | The design's section 9 criterion-7 plant does not isolate end (b); it fails both ends | **The isolating pair is a plant on the executor's provider identity — which fails end (a) while end (b) still answers — plus a `sources.fetch` that succeeds and returns nothing, which fails end (b) while end (a) stays green.** The design and the S6 assignment both claimed that reverting `fixture._locate` to a per-instance map fails (b) while (a) passes. Measured on `500cf32`: `_locate` is the single resolution point for the executor **and** for `sources.fetch`, so the revert quarantines every object, coverage goes `(4, 0, 0, 4)`, and end (a) has nothing to read. No single-point reversion isolates end (b), because end (a) transits end (b)'s whole mechanism. This matters beyond bookkeeping: **either plant alone is green on a broken bridge**, so a reviewer accepting the design's stated pair would have accepted a vacuous proof of the criterion this package is most likely to be attacked on. The replacement pair was independently verified to isolate both ends. Invalidated by a change making `_locate` no longer the shared resolution point, which would restore the design's asymmetry. | Corrects the design's section 9; the replacement pair is what proves criterion 7 |
| D-56 | The v2.2 mirror was current against Drive when checked on 2026-08-03 | Recomputed before WP-5 was scoped, because the package had been revised in place twice mid-campaign and the first revision went unnoticed across four merged pull requests. At that check all 31 mirrored files compared identical by SHA-256 and the newest canonical-package modification was `2026-08-02T15:09:42.461Z`. This was a time-bound verification, not a permanent "no later revision" assertion. The check fired again on 2026-08-04: version 2.3 changed 17 numbered artifacts and invalidated this row's current-state conclusion. `D-105` records the new reconciliation. | Historical verification; superseded by `D-105` |
| D-57 | WP-5 splits into WP-5A and WP-5B, WP-5A first | WP-5A ships WP-5's **three stated acceptance criteria and nothing else**: the seven conditions of `../specs/mcv-read-only-vertical-slice.md` section 3 each demonstrated by one synthetic end-to-end test, recovery tests that kill a worker mid-extraction proving no duplicate and no lost coverage, and empty-to-head and head-to-empty migration against a disposable database. WP-5B ships the remaining in-scope items — health and readiness endpoints, console entry points and the ordered start and stop sequence, migration validation as a *gate*, the end-to-end operator runbook, the limitations document, and index and README staleness. `D-52`'s own test was applied rather than convenience. `D-52` refused to split WP-4B3 because the proposed first pull request satisfied **one of seven** criteria and **narrowed** criterion 3 — a prefix, not a split. This boundary differs in kind: WP-5A satisfies **all three** acceptance criteria outright and WP-5B **none**, so neither half leaves a criterion half-proven, which is the bar `D-43` and `D-52` set. The ordering is forced by the limitations rule: WP-5B's limitations document must state what the slice does **not** do, and a limitation may only be stated at or slightly below demonstrated capability — which is writable only after WP-5A measures it. **Citation corrected in place by WP-5B, and it was the `D-16` defect class again.** This clause cited "`AGENTS.md` section 15", which does not exist: `AGENTS.md` has **9** `##` sections, ending at "9. Mandatory stops", and the phrase appears nowhere in that file. The rule itself is real and its home is the campaign's operating brief, not repository policy. Left visible rather than silently repointed, because a register that corrected its own citations without saying so would be the instrument this plan uses to catch exactly this. The cost is named rather than hidden: `D-52` established that under the operator's one-worker cap **review is the dominant cost**, so this split spends two review cycles where one might have done, and that is accepted deliberately. | Split; WP-5A in delivery |
| D-58 | `capabilities.get`'s `readiness` is a build-time property, not a runtime probe, and WP-5B must make that unmistakable rather than quietly widen what it measures | Measured at `6660dbb` from the modules, not from a report. `build_readiness_report` (`../../src/my_pa/application/capabilities.py:136`) derives its state by **counting wired handlers**, and `ApplicationService._capabilities_get` (`../../src/my_pa/application/service.py`) never opens a database connection, so with all eight handlers wired it answers `readiness.state: ready` **even when PostgreSQL is unreachable**. The function is honest about what it measures and its docstring says so. The hazard is where that value is read: `../../ops/runbooks/gateway-operations.md` presents `readiness.state: ready` as observed gateway output, which is exactly the position an operator reads a runtime probe. Meanwhile a real probe already exists and no transport can reach it — `healthcheck(engine)` (`healthcheck` in `../../src/my_pa/infrastructure/database/engine.py`, cited by name rather than by line since the package carrying this correction adds lines above it) is exported from `my_pa.infrastructure.database` and has **zero callers** in `src/`, `apps/`, or `migrations/`. So the repository holds a working database probe nothing can call, beside a build-time report an operator would mistake for one. Adding a health or readiness route would be the **first non-`POST /v1/{capability}` route in the process** — `../../src/my_pa/adapters/http/app.py` declares exactly one `Route` — and would therefore sit outside the capability, authorization, and audit envelope every existing path transits. That is a design question for WP-5B to argue, not a wiring task. Recorded now so it is not rediscovered as a surprise; it is not a defect WP-4B3 created and it is not WP-5A's, which adds no production code. **SUPERSEDED by `D-61` on 2026-08-03, and the original text above is preserved deliberately.** Its central inference — that `capabilities.get` answers `readiness.state: ready` even when PostgreSQL is unreachable — was measured **false**: `ApplicationService._run` opens the unit of work before it dispatches, so an unreachable server answers `unavailable` and a reachable one that cannot commit the request's audit row answers `internal_error`. (This clause first read "a reachable one behind head", which `D-61` overgeneralised and which was re-measured and corrected in both rows on 2026-08-03; the boundary is `9c6b4a18ed72`, not head.) The row read one function without its caller, which is the same failure shape `D-41` corrected in `D-37`. Its disclosure half is withdrawn — the gateway runbook's transcript was taken against a disposable database at head and is accurate. What survives is the missing runtime probe, which `D-62` builds, and the observation that a health route would be the first non-`POST /v1/{capability}` route. | **Superseded by `D-61`**; preserved, not deleted. The probe it asked for is built; the premise it asked for it on was wrong |
| D-59 | The WP-5A design is accepted, and six of the assignment's own ground-truth claims were wrong — one of them retires an acceptance criterion | The design at `wp5a-design/DESIGN.md` is adopted as direction. Its corrections matter more than its plan. **(A) WP-5's migration criterion is already satisfied at `6660dbb`, three times over** — `test_upgrade_from_empty_and_downgrade_back_to_empty` in `../../tests/schema/test_foundation_migration.py`, `test_the_audit_revision_runs_empty_to_head_and_head_to_empty` in `../../tests/schema/test_audit_schema_migration.py`, and `test_upgrade_from_empty_and_downgrade_back_to_empty` in `../../tests/schema/test_extraction_schema_migration.py` each run empty to head and back against a disposable database, and the second is named verbatim after the criterion. (Cited by test name rather than by the lines they stood on at `6660dbb` — 109, 274 and 375 — because WP-6 lengthened two of the three files and both numbers rotted inside this branch.) The claim that none did was drawn from `test_knowledge_schema_migration.py`'s docstring, which explains why *that file* targets a named revision rather than head; it was read as a statement about the whole suite. WP-5A therefore adds a residue assertion, not a fourth round trip. **(B) and (C) the hardest design question was already solved**: `../../tests/wire.py` runs a real uvicorn server on a real loopback socket and `../../tests/transports.py`'s `all_transports` takes an `ApplicationService`, so condition 6 needs no harness; and the connection-pool cycle the assignment feared was designed out by the two-engine composition at `../../src/my_pa/bootstrap/gateway.py`. **(D) at `6660dbb`, before this package, two of the six negative-evidence categories were proven nowhere over any transport, and `ambiguous_request` nowhere at all** — `SafeDetail.MULTIPLE_ENROLLMENTS_COVER_THE_SCOPE` is declared in `../../src/my_pa/application/errors.py`, raised in `service.py`, and named in no test at that head; a declared refusal that had never fired is the guard-that-cannot-fire shape this campaign has now recorded three times. **All three gaps are closed by the same commit that carries this row** — WP-5A's `ambiguous_request` test is the first thing ever to make that branch fire, and its cross-source test the first to exercise that guard. The row is written in the past tense deliberately: a register cell asserting a gap is open in the commit that closes it is the exact defect WP-4B3's review caught, and the implementer flagged this one rather than editing text it did not own, which is why it reads correctly now. **(E) the traversal mechanism named in the assignment was wrong and the truth is stronger**: `authorized_object` bounds the knowledge plane only and never guards the source capabilities, while `RegistryIdentity.locate`'s cross-source ownership test — whose own docstring names the defect it prevents — is structurally unreachable with the ephemeral identity and, at `6660dbb`, was exercised by no test at any tier. **(F) `D-56` and `D-57` were cited before these rows existed**, found by a first-cell parse that returned 84 rows ending at `D-55`; the design declined to invent them and the orchestrator supplied the text, the same sequence recorded beneath `D-55` for `D-36`. The design's sixteen non-vacuity plants each isolate one end of a property and name the other end that must stay green, answering `D-55` directly, and one of them is recorded as correctly staying **green** so that a later reader cannot over-claim what the process-kill test covers. | Accepted as direction |
| D-60 | `OP-02a` never existed; every citation of it is corrected to `OP-02` plus `D-39`, and the fabricated register row is deleted | Cite **`OP-02`** for "build nothing toward WP-11" — the bound it states in the campaign's operator record — and **`D-39`** for "WP-11 is sequenced last". `OP-02a` is not a valid identifier and must not be reintroduced. **This is the `D-16` defect class — a citation to a decision the record does not carry — for the third time in this campaign, and the first time the campaign *minted* the phantom rather than inheriting one.** **Two `OP-nn` namespaces exist, and this row means the campaign one.** The campaign's operator record is `OPERATOR-DECISIONS.md`, a manager-held artifact **outside this repository**, which carries decisions as `## <ID> — …` headings; a heading parse of it returns exactly `OP-01` and `OP-02`, **2 of 2**, with the literal string `OP-02a` occurring **0** times. The repository's own `../specs/canonical-product-definition/15_OPEN_OPERATOR_DECISIONS.md` is a **different** ledger carrying **30** `OP-` rows, whose `OP-02` is "Final labels", a UI-freeze decision unrelated to WP-11. **An earlier draft of this row cited that file as the source of the bound, which was false — the `D-16` defect class reproduced inside the row that retires it, caught at integration by the correction worker and by first-cell parse.** The collision was predicted by this campaign's own ledger and has now happened once: **do not read an `OP-nn` in this plan as the canonical ledger's.** A first-cell parse of the campaign brief's own register found `OP-02a` present as a **row**, so this was a fabricated decision with a rationale and an invalidation condition attached rather than a loose citation. Its text is verbatim `OP-02`'s own bound, so **no direction is lost by the deletion** — only a false provenance. Universes: **10 citations across 8 scratchpad files; 0 in the repository**, tracked or untracked, so this plan and `docs/` were never contaminated and no repository correction was needed. (The literal string now occurs once in the repository — in this row, which retires it. Naming a phantom in order to retire it is not citing it, and the count above is of citations.) Disclosed rather than smoothed over: the defect shipped into the published bodies of merged pull requests #31 and #32, both corrected by appended note rather than silent rewrite | Corrected; `OP-02a` retired. An operator decision genuinely numbered `OP-02a` would have to appear as a heading in the operator record first |
| D-61 | **Supersedes `D-58`.** Its core premise is false: `capabilities.get` does **not** answer `readiness.state: ready` with PostgreSQL unreachable. The defect it was reaching for is different and worse — a **reachable** database that cannot commit a request's audit row answers `internal_error`. **This lede first read "reachable but behind head", which was wrong and is corrected in place rather than concealed** | Measured by the WP-5B design and re-verified independently. `ApplicationService._run` (`../../src/my_pa/application/service.py`) wraps dispatch in `with self._unit_of_work()`, and `SqlAlchemyUnitOfWork.__enter__` (`../../src/my_pa/infrastructure/persistence/unit_of_work.py`) connects **there**, before any handler runs. **Re-measured on 2026-08-03, and the original generalisation of that measurement was wrong.** The design measured one database — canonical `my_pa`, four revisions back — and generalised it to the whole not-at-head class. Stepping a disposable database (`my_pa_chain_probe`, created empty and dropped) through all ten revisions and invoking `capabilities.get` and `sources.list` through `../../apps/cli/invoke.py` at every chain position: a closed port answers `unavailable`; an empty database and every revision from `5d75f23847c9` through `8b3f5c17d904` answer `internal_error` to both; and `9c6b4a18ed72` — **one revision behind head** `af3d35efb9c0` — **serves**, `capabilities.get` exiting `0` with the envelope it returns at head and `sources.list` returning the same `denied` it returns at head, with six audit rows written while the database sat one revision behind head. **So the boundary below which *every* capability fails is `9c6b4a18ed72`, which creates `knowledge.audit_events`, and not head**: every served request commits an audit row, and a request that cannot be audited fails rather than being served unaudited. **There is a second, per-capability boundary at head itself, and it is why the probe's refusal below head is still right.** On a second disposable database (`my_pa_chain_probe2`, dropped), a source was registered at `9c6b4a18ed72` and `sources.enroll` through `../../apps/cli/invoke.py` answered `internal_error` — head creates `enrollment_objects` — while the same call on the same database after `alembic upgrade head` answered `created true` with `coverage.eligible 4`. So one revision behind head is a state in which some capabilities serve and at least one does not, and "not at head" is a correct statement about the build rather than a diagnosis of any single capability. `D-58` inferred "returns `ready` with PostgreSQL down" from the fact that `_capabilities_get` opens no connection *itself* — true, but the envelope around it does. **`D-58` was written from the modules and was still wrong, because it read one function without its caller** — the same failure shape as `D-37`, corrected by `D-41` for the same reason. **Two of its findings survive intact**: at `bcdbf6d` `healthcheck` had zero callers, now *proven* rather than asserted (the design gutted it and both a bare `mypy` over 109 files and the FAST tier at 2150 of 2489 stayed green, with the plant proven live at its two real call sites), and a health route would be the first non-`POST /v1/{capability}` route. **`D-58`'s disclosure half is withdrawn**: `../../ops/runbooks/gateway-operations.md` states its run was against a disposable database at head, so its `ready` transcript is accurate and misrepresents nothing. The failing case is not hypothetical — it is the state canonical `my_pa` is in, at `6c4d3ea82f10`, three revisions before the boundary and carrying no `knowledge` schema at all. What this row got wrong was the class it generalised that one observation to, not the observation | Supersedes `D-58`, which is preserved in place. Invalidated by evidence that `_run` does not open the unit of work before dispatch |
| D-62 | The runtime probe is an operator command, `../../apps/cli/health.py`, shaped like `../../apps/cli/sources.py` — and it reports **revision versus head**, not merely reachability | Exit `0` only when the configured database is reachable **and** at head; non-zero with **mutually distinguishable** answers for unreachable and for not-at-head. **(a) A new HTTP route is rejected**: it would break the structural "every served request is audited" property that every existing path transits, and it would disclose the server version, the extension list, and the schema revision to an unauthenticated caller while `P00-OD-010` is open. **(b) A ninth capability is rejected and the wall has doubled** — the set is closed in `../../src/my_pa/domain/identity/operation.py` *and* by a `CHECK` constraint on `knowledge.audit_events` in `../../src/my_pa/infrastructure/persistence/tables.py`; `D-42` forbids it. **(c) has direct precedent** that `D-42` itself cites approvingly: operator commands live beside the capability dispatcher and share nothing with it, exactly as `../../apps/cli/migration.py` does. **(d) Disclosure alone is insufficient**, though for a different reason than `D-58` gave — the gap is the `internal_error` returned by a database that cannot commit a request's audit row, not a misleading runbook. **Revision-versus-head is the part that earns the command**: without it the probe wraps a function the runbook could already call with `python -c`, and `healthcheck` alone would report canonical `my_pa` **healthy** while it cannot serve a single capability. **(e) Exit `0` only at head is an operational policy, not an empirical claim — recorded on 2026-08-03 because the distinction was not made when this row was written, and the row was resting on a claim that has since been withdrawn.** Re-measured (`D-61`): a database at `9c6b4a18ed72`, one revision behind head `af3d35efb9c0`, serves `capabilities.get` and `sources.list` exactly as head does, so "below head" and "no capability serves" are **not** the same set, and the probe's `not_at_head` is not a per-capability diagnosis. The command still exits `1` there, and the measurement supports that rather than undermining it: at the same revision `sources.enroll` answered `internal_error` while the same call at head answered `created true`, because head creates `enrollment_objects`. So a database behind head cannot serve this build even when it can serve some of it, which is the statement the command's message makes. **This decision therefore does not depend on the withdrawn claim that every capability fails below head, and it survives that claim's withdrawal** | Accepted; built by WP-5B. Invalidated by a design showing the probe can audit without a capability |
| D-63 | **No console entry points.** `D-57`'s "console entry points" clause is superseded; the rest of `D-57` stands | The plan's own WP-5 in-scope list says **"startup and shutdown for gateway and worker"** — it never says "console entry points". That phrase was `D-57`'s **gloss** on the plan rather than the plan's text, and the WP-5B design measured that startup and shutdown are **already built**: signal handling that sets one stop event and restores `SIG_DFL`, a graceful-shutdown bound derived from the engine's checkout timeout, and resources released in `finally`. Adding `[project.scripts]` would oblige re-transcribing four runbooks whose invocations are already executed and verified, which is churn against an item no acceptance criterion needs. **Recorded as a supersession rather than silently dropped**, because a later reader comparing `D-57` to the shipped package would otherwise read it as an omission | Supersedes one clause of `D-57`. Invalidated by evidence that some in-scope item requires an installed console script |
| D-64 | Widen CI's type check from `mypy src` to cover `../../apps/` and `../../migrations/` too | Routine engineering inside delegated authority rather than an escalation. Measured at `bcdbf6d`: both workflow jobs ran `python -m mypy src`, and an explicit path argument **overrides** `[tool.mypy] files` in `../../pyproject.toml`, so CI checked **93** source files while a bare `mypy` checked **109** — leaving 16 files in `apps/` and `migrations/` type-checked by nothing. Proven with a plant rather than argued: a deliberate `-> str` returning `int` in `apps/` left `mypy src` reporting "Success: no issues found in 93 source files", and the same plant in `migrations/env.py` did too, while a bare `mypy` caught both. **Not academic for WP-5B** — `apps/cli/health.py` is the package's principal new module and landed squarely in the unchecked set. Bare `mypy` was already clean, so the widening surfaced no pre-existing debt, and `pyproject.toml`'s own comment claimed the two invocations already agreed, which was false when written and is corrected in place | Accepted; applied by WP-5B. Invalidated by a bare `mypy` proving to carry pre-existing errors, which would make this a separate remediation |
| D-65 | The taxonomy fix for the `internal_error` a database returns when it cannot commit a request's audit row is **out of** WP-5B's scope. Named, deferred, and not absorbed | **The condition is named correctly here as of 2026-08-03, and only the description moved.** This row first called it "schema drift", inheriting `D-61`'s overgeneralisation; re-measurement put the boundary at `9c6b4a18ed72`, which creates `knowledge.audit_events`, rather than at head. `../../src/my_pa/application/errors.py` is untouched, the deferral stands unchanged, and correcting the wording is not taking the fix. WP-5B's probe *detects* the condition; correcting the application's error classification for it is a separate change against `../../src/my_pa/application/errors.py` and the three transports' negative-evidence matrices. The WP-5B design flagged it as tempting and refused to absorb it, which is the behaviour `D-57` asked its own design for. It is a real defect of the same class `unit_of_work.__enter__`'s docstring records WP-4B2a fixing for the *unreachable* case — "a caller told the product is broken when the truth is that PostgreSQL is not running, which are different things to do about it." The unreachable case was fixed; the unrecordable-audit-row case was not. Absorbing it would widen WP-5B past its in-scope list and would touch `SPEC-AC-001` parity evidence across three transports. **Recorded so it cannot be rediscovered as a surprise**, exactly as `D-58` was recorded for WP-5B | Deferred and named. Invalidated by a package taking it, which needs its own decision row and acceptance criterion |
| D-66 | The plant procedure in the WP-5 worker rules is unsound and is corrected: **a scratch-copy plant under `src/` is a no-op unless `PYTHONPATH` is set** | The `.venv` holds an **editable** install resolving `my_pa` to `<repo>/src`, so a plant made in a scratch copy is ignored and the tests keep importing the primary checkout's unplanted source. The WP-5B design hit it live: a scratch-copy plant reported `3 passed` and became `2 failed, 1 passed` only once `PYTHONPATH=<scratch>/src` was set. **The rules file actively caused this** — it told workers "you are in the primary checkout, no `PYTHONPATH` is needed", which is true for *running tests* and false for *scratch-copy plants*, and the two were not distinguished. This is the vacuous-plant failure mode arriving through the tooling rather than through the plant's logic, and it would have produced silent false greens for every future worker. Plant **in place** and revert, or set `PYTHONPATH`; either way, prove the plant fired. **Scope limit, stated so it is not overclaimed: it does not invalidate this campaign's prior plant evidence.** Prior plants were applied in place in the primary checkout and then reverted, which the editable install resolves correctly; only the scratch-copy variant is affected | Corrected; binds every future worker. Invalidated by a non-editable install |
| D-67 | A local principal does not survive its process, so the operator CLI cannot read back what it enrolled. Recorded as a limitation; **not fixed in WP-5B** | **Found by *executing* the runbook sequence rather than by reading the modules** — the method `../../ops/runbooks/README.md` requires of every procedure it carries, and the reason that convention exists. `local_principal()` (`../../src/my_pa/bootstrap/gateway.py`) minted a fresh identifier per composition and `../../apps/cli/invoke.py` composed a runtime **per invocation**, while `authorize` (`../../src/my_pa/application/authorization.py`) derived the authorized scope from the enrollments that principal held — so an enrollment created by one invocation was held by an identifier that never existed again. Measured at `bcdbf6d`: a CLI `sources.enroll` returned `allowed` and wrote its enrollment, and three later CLI `sources.status` calls for that same enrollment each returned `denied` with `denial_reason scope_not_authorized`, under **three different** principal identifiers — while the same four capabilities through **one running gateway** returned `allowed` four times under **one** identifier. The gateway is a coherent session; the CLI is not. `capabilities.get` was the exception and worked from the CLI, because it carries no source scope (`../../src/my_pa/domain/policy/decision.py`). **This is not a transport-parity defect.** `SPEC-AC-001` binds byte-equivalent *normalised requests*, which still holds; what differs is identity lifetime, which parity never claimed. Not absorbed, because issuing a durable local principal is exactly the authentication decision `P00-OD-010` reserves to the operator and `D-30` refuses to pre-empt. Disclosed as limitation 2 of `../operations/mcv-limitations.md` and in `../../ops/runbooks/end-to-end-operations.md`, so an operator meets it in the document rather than in the field | Recorded as a limitation; deferred to `P00-OD-010`. Invalidated by an operator resolution of `P00-OD-010` that selects an authentication mechanism, which is what a durable local identity would be |
| D-68 | `D-42` is **narrowed, not overturned**, and `D-62`(b) and `D-45`(d) are narrowed with it, as a class. All three originals are preserved | `D-42`'s ruling that *source registration* is an operator command under `../../apps/cli/` **stands unchanged**: source registration is named by no canonical capability. What is superseded is `D-42`'s general premise (ii) — that admitting a capability expands scope beyond the canonical definition — and only **for capture capabilities**. Two independent grounds, and the second is the stronger: (1) `capture.create` is named by the canonical package in six places, all verified line-anchored — `02:487`, `12:113`, `13:102`, `00:92`, `14:70`, `08:83` — so admitting it *conforms to* the canonical definition rather than expanding past it; (2) `ADR-003:107` says the ADR "does not select capability names, schemas, tables, or transports. **Those belong to an implementing work package and its pull request.**" That is repository-internal, rank-appropriate, and authorises precisely what WP-6 needed. **A canonical sweep for `noun.verb` tokens returns exactly one distinct name — `capture.create` — so ground 1 reaches that name alone**; `capture.revise`, `capture.read` and `capture.list` rest on ground 2, and claiming canonical authority for all four would be the overclaim this campaign exists to catch. `D-42`'s own invalidation clause reads "a canonical revision adding a *registration* capability", and capture is not one, so `D-42` is **not** self-invalidating here and this supersession is explicit and partial. `D-62`(b) ("a ninth capability is rejected and the wall has doubled") and `D-45`(d) ("`audit_events.capability` is closed to the eight and a ninth member is what `D-42` forbids") restate the same closure and are narrowed identically | Narrowed as stated; all three originals preserved. Invalidated by a canonical revision naming further capture capabilities, which would move them from ground 2 to ground 1, or by an ADR superseding `ADR-003:107` |
| D-69 | Freeze the historical vocabulary as literals inside merged revision `9c6b4a18ed72`; widen by explicit `ALTER` in WP-6's own revision. Freeze **both** `capability` and `purpose` | The retroactive-DDL hazard is **PROVED TRUE by measurement**, not asserted: with a ninth member planted, a disposable database stopped at already-merged `9c6b4a18ed72` received `capability IN (…, 'zzprobe.create')` where the baseline received the historical eight. That is `D-48`'s failure in a new shape, and `D-48`'s own invalidation clause asks for exactly this mechanism — one that widens "without altering what a prior revision emits". Three corrections to how it had been described, all measured: **(a) it is *less* damaging than `D-48`'s case** — naive widening produced 10 checks on `audit_events`, each exactly once, no duplicate constraint, and head→base left only `public.alembic_version`; the harm is solely that `9c6b4a18ed72` stops denoting one schema, which is still disqualifying but is not schema corruption. **(b) `Purpose` carries the identical hazard on the same table in the same revision** — `tables.py` also held `_one_of("purpose", Purpose)` — and nothing had named it; half a fix is a live bug. **(c) the "two walls" question is time-dependent**: at DDL-emission time the enum and the CHECK are coupled, and for a database that already exists they are genuinely independent — measured, with a ninth capability in code and a pre-existing head database an audit insert was **REFUSED** by the stored eight-value constraint. **That is why this decision matters at all: a WP-6 that added the capability without a migration would pass every test, because every test builds its database from scratch, and would fail in the field on the first audited capture.** Cost, argued rather than buried: one edit to a merged migration file, acceptable because it is **meaning-preserving** — after it that revision emits DDL byte-identical to what it emitted on the day it merged, measured both ways, so no deployed schema moves. Two obligations attach and both are met: the broken enum→CHECK coupling is replaced by a checked claim (`tests/schema/test_capture_schema_migration.py` asserts head's `capability_is_known` admits exactly `{c.value for c in Capability}` and `purpose_is_known` exactly `{p.value for p in Purpose}`, on the `tables.py` `_IDENTIFIER_SUFFIX` precedent), and a standing rule is written into `9c6b4a18ed72`: **no Alembic revision may derive a closed-set constraint from a domain enum** | Adopted and implemented in WP-6. Invalidated by a mechanism that keeps the derivation and still leaves each revision denoting one schema |
| D-70 | Four capability names and two purposes, **none operator-only**: `capture.create` and `capture.revise` under `capture_authoring`; `capture.read` and `capture.list` under `capture_review` | `capture.create` is canonically fixed in six places and is not open. The other three are chosen by an implementing work package under `ADR-003:107`. `revise` rather than `update` because repository convention is a **domain act**, not CRUD — `sources.enroll` not `sources.create`, `sources.fetch` not `sources.get` — and `revise` is ADR-003 clause 3's own frame; two segments each, like the eight existing names, where `capture.version.create` would have been the only three-segment name in the contract. `capture.read` mirrors `knowledge.read` and `capture.list` mirrors `sources.list`. **Two new `Purpose` members rather than reuse**: a purpose admitting both the knowledge plane and the capture plane would let a `knowledge.read` request return raw capture text, and the existing map is near 1:1 capability→purpose. `IdKind` gains `CAPTURE = "cap"`, `CAPTURE_VERSION = "capver"`, `RECEIPT = "rcpt"`, `SUBMISSION = "sub"` — not reusing `VERSION = "ver"`, which already denotes a *source object* version and would make two unrelated things indistinguishable in an audit row. **Not operator-only is a decision, not a default**: `_OPERATOR_ONLY` holds `sources.enroll` alone because enrollment **grants authority** and widens the authorized scope, while a capture creates content the principal already owns and grants nothing; making capture operator-only would also contradict `09`'s `RegisteredCaptureClient`, which carries a permitted capability for a non-operator device client, and `08:83`'s iOS Shortcut caller. Consequence handled rather than discovered: capture capabilities are **scopeless**, which widens the set `tests/policy/test_application_authorization.py` asserted was exactly `{capabilities.get}` | Adopted and implemented in WP-6. **`O-01` stays open**: these are names chosen by an implementing work package, and renaming after merge is a breaking `v1` change. Invalidated by an operator resolution of `O-01` naming different capabilities |
| D-71 | Replace the mutating-name proxy in `tests/security/test_mcp_and_cli_negative_evidence.py` with the property it proxies for. **Do not weaken it** | That test asserted no capability name contains `create`, which **blocked `capture.create` outright** — the one name the canon fixes and the one that is not negotiable. The property the section protects is ADR-003 clause 5 / `MB-AC-003`, *no source mutation*, and the substring list is a **proxy** that was already imprecise: `sources.enroll` writes to the database and passed only because "enroll" is not on the list. The recording-provider test three lines below carries the real property. Moving `capture.*` from the proxy to the property makes the guarantee **stronger**, not weaker, and it is WP-6's own ADR-003-clause-5 acceptance criterion, so it is proven twice. **This is the finding most likely to be mistaken for an accommodation.** Presented as "we renamed the test so our capability fits" it should be rejected; it ships only with the recording-provider extension in the same commit, and without that extension the guarantee genuinely does weaken | Adopted, and implemented **stronger than its letter** — see `D-80`. Invalidated by evidence that the recording-provider test does not in fact cover `capture.*` |
| D-72 | `D-67`'s disposition: **store the owner, do not authorize on owner equality, and pin that mechanically** | Shape (i), designing ownership away, is **unavailable**: `ADR-003` clause 6 requires every stored version to bind the owning principal, and routing around it would violate a rank-higher instrument to dodge a limitation. So: (1) the acting principal is stored on every capture version; (2) `capture.read`, `capture.list` and `capture.revise` authorize on **capability and purpose alone** — under `P00-OD-010`-open, loopback-only, single-local-principal operation there is exactly one human operator, so owner-scoped authorization would enforce a distinction the deployment cannot make, and it would make **`QC-AC-013` unprovable across processes** because the predecessor's owner never exists again; (3) the behaviour is pinned by one `database`-marked test composing **two** runtimes, creating under the first and revising and reading under the second, asserting both that the two `owner_principal_id` values **differ** and that the read and the revise **succeed** — a test that fails the moment someone "fixes" this by adding an owner-equality check, forcing the decision back to the operator instead of letting it be made silently; (4) `../operations/mcv-limitations.md` limitation 2 is corrected **as a class**, from "the CLI cannot read back what it enrolled" to **"ownership survives only as long as the serving process"**, measured — 3 CLI processes → 3 distinct principals, one gateway runtime → 1 across three reads, a restart mints a new one — because WP-5B wrote it from the CLI case alone; (5) it is worded as **blocking on multi-principal operation**. **No identity mechanism is invented**: the envelope `principal_id` is correlation input only and `../../apps/cli/invoke.py` refuses a `--principal` option, calling it "the bypass this file exists not to be" | Adopted and implemented in WP-6; disclosed as limitation 2. Invalidated by an operator resolution of `P00-OD-010`, which supplies the mechanism this defers and at which point the absence of owner-scoped access control becomes a live exposure |
| D-73 | Section 559's in-scope list is **stale, not a narrowing**; section 12's sequence table governs, and section 559 is corrected in place | From the plan's own revision history: `git log -L` shows the WP-6 in-scope list last touched by **`9096fa4` (#23)**, while section 7's WP-6 item, section 12's sequence-table row for WP-6, and the whole of section 16's *Six new canonical record types* table were written or rewritten by **`c60f5cc` (#25)**, the Remote Quick Capture reconciliation. `9096fa4` precedes `c60f5cc`, so the in-scope list was written **before the RQC revision existed** and was not revisited when `c60f5cc` extended WP-6 in three other places. It cannot be a deliberate narrowing of material that did not yet exist. The plan resolves its own conflict in section 7's closing sentence — "Items 4 through 13 restate **section 12's sequence table, which is the authoritative one**." *Citations de-numbered 2026-08-03 (`D-83`): this row cited five line numbers into the file the same commit lengthened by 97 lines, and every one of them rotted on the way to head.* Corrected visibly rather than silently rewritten, in the `D-57` style | Corrected in place by WP-6's pull request. Invalidated by nothing; this is a reading of the plan's own precedence rule |
| D-74 | WP-6 ships whole as `{section-559 core + CaptureSubmission}`, one review cycle. `RegisteredCaptureClient` and `CaptureDeliveryAttempt` are **deferred, not split** | Applying `D-43`/`D-52`/`D-57`, which is a test about criteria rather than about size. **The obvious boundary fails it**: `CaptureSubmission` is **inside** the durable-first transaction — this plan says so in section 16's *Six new canonical record types* table, and structurally the `idempotency_key UNIQUE` on `capture_submissions` **is** the `QC-AC-031`/`032` mechanism — so splitting it out builds that transaction twice (`D-41`) and leaves both criteria half-proven. **A defensible partition does exist** — all seven criteria versus none, exactly `D-57`'s shape — **and it is still refused**, because the second half is not buildable honestly today: `RegisteredCaptureClient`'s defining fields are a revocable credential reference and a permitted capability for a remote device, and `D-30` issues no credential, `O-21` has decided no issuance, and `P00-OD-010` has selected no mechanism; `CaptureDeliveryAttempt` logs delivery attempts and there is no remote transport to attempt one. **Both would be permanently-empty tables**, which `AGENTS.md` section 2 rules out and which `tables.py` already cites as the reason `audit_events` has no `item_count` column: "a zero that means 'never measured' reads as 'nothing happened', which is worse than absent." Deferring narrows no acceptance criterion, because those two types carry none. An independent argument against any split that adds capability names in a first half: `README.md` claims every capability is `available` and readiness `ready`, and `tests/architecture/test_readme_state_claims.py` derives that from `_HANDLERS`, so a named-but-unwired capability drops readiness to `degraded` and falsifies the README — **every capability WP-6 names is wired in the same pull request**. Consequence: `capture_submissions` carries **no** `registered_client_id` column, absent rather than nullable-and-never-written | Adopted; WP-6 shipped as one package. Invalidated by a package activating a remote transport, at which point both types become populatable and their deferral ends |
| D-75 | Take the seven criteria at their **spec strength**, not this plan's paraphrase. Four of this plan's criterion statements were wrong or narrowed and are corrected in place | Measured against `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md`: (1) the save-transaction sentence in the WP-6 objective, and its second site in section 7's WP-6 item, claimed the **redacted audit** commits with the capture — the implementation is corrected, because `SqlAlchemyAuditSink.record` takes its own connection and commits before returning, which is `D-34` and cannot be undone without overturning it. **Reclassified 2026-08-03 (`D-84`): this is a conflict between instruments, not a plan error** — the spec package states it in five places, most nearly verbatim at `../specs/quick-capture/05_END_TO_END_WORKFLOW_INVENTORY.md:20` and `../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:33`, and contradicts itself at `20_TESTING_EVALUATION_AND_ACCEPTANCE.md:47`, which omits the audit; (2) `QC-AC-012` named **three** timestamps where spec `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:191` requires **five** distinct — device, server, occurred, processed, accepted — silently dropping *occurred* and *accepted*; (3) `QC-AC-032` named **`idempotency_conflict`**, which is not one of the **eleven** public codes `../../src/my_pa/contracts/v1/errors.py` declares, so the `v1` answer is `conflict` with `safe_details: ["idempotency_key"]`. **Reclassified 2026-08-03 (`D-82`): this row said a twelfth code "would have been an unauthorised `v1` expansion", as though the plan had invented the name. It did not** — the word is the spec package's own, three times over, and this is an open spec-versus-`v1` conflict; (4) `QC-AC-041` named logs, audit rows and error payloads where spec `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:214` also names telemetry, **URL parameters**, and lock-screen notifications, and URL parameters is live because `capture.create` over HTTP must not accept text in a query string; (5) `QC-AC-010` omitted "**and independently retrievable**" from spec `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:189`. `QC-AC-034` was called **true as worded and kept exactly** — **and that verdict is itself wrong (`D-85`)**: the bullet is a correct test filed under the wrong criterion, because spec `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:208` makes `QC-AC-034` about a *processing* failure not losing a capture, and WP-6 has no processing stage. Taking the paraphrase would have silently narrowed two criteria and invented a public error code, and operating doctrine forbids both. **This is the sixth consecutive package in which measurement contradicted a plan or design claim, and the fourth in which the contradiction was in the acceptance criteria themselves** | Corrected in place by WP-6's pull request; each correction marked where it sits. Invalidated by a corrected spec |
| D-76 | `knowledge.capture_jobs` is a **new** table. Do not widen `jobs.enrollment_id` | `tables.py` declares `jobs.enrollment_id` **`NOT NULL`** with a foreign key to `knowledge.enrollments`, and a capture has no enrollment. Relaxing it would retroactively change what merged revision `8b3f5c17d904` emits — **the third instance of the `D-48` hazard class inside WP-6, and the only one on a `NOT NULL` column.** All five new capture tables are new, so their own constraints and foreign keys carry no retroactive hazard, per `D-48`'s own carve-out. Schema is `knowledge`, not a new one: section 16's *The new prohibition* on a "second knowledge store" and `D-20` both point there. **The `D-41` "same persistence twice" objection is real and is answered by sharing code, not tables** — the lease and retry *functions* in `infrastructure/persistence/jobs.py` are parameterised over the job plane, so there is one implementation of the lease rule and two tables it runs against. This is the design's most contestable choice and the pull request says so rather than letting a reviewer find it. Nothing consumes the queue until WP-7; that is what durable-first means, not a speculative column | Adopted and implemented in WP-6. Invalidated by a revision mechanism that widens `jobs.enrollment_id` without altering what `8b3f5c17d904` emits |
| D-77 | `D-76` is reconciled with canonical `09_LOGICAL_DATA_MODEL.md` section 4 by **one job-plane implementation over two tables** | `D-76` stands. The tension the implementer named — that `09_LOGICAL_DATA_MODEL.md` section 4 directs reuse of the generic job plane rather than new Quick-Capture queue infrastructure — is answered by parameterising `infrastructure/persistence/jobs.py` over a `JobPlane`, which gives **one lease/retry implementation and two physical tables**. `D-76`'s stated cause is unchanged and real: `jobs.enrollment_id` is `NOT NULL` with a foreign key to `enrollments`, and relaxing it is the `D-48` hazard on a `NOT NULL` column. The canonical instruction is about *queue infrastructure*, not about table count, and a single lease/retry implementation **is** the generic job plane. **The implementer named the tension rather than re-litigating `D-76` or absorbing it silently, which is the required behaviour and is why this row exists** | Reconciled; implemented as one job plane over two tables. Invalidated by a mechanism that widens `jobs.enrollment_id` without altering what `8b3f5c17d904` emits |
| D-78 | `capture_submissions`' four single-valued closed-set columns — `transport`, `capture_method`, `trust_state`, `admission_result` — are **kept**, on canonical grounds rather than on precedent | Each admits exactly one value in this build, and the pull request discloses that rather than letting a reviewer find it. The implementer kept them on the `extractions.trust_level` precedent; **the stronger argument, which the pull request leads with, is canonical**: `../specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:143` enumerates transport, capture method, trust state and admission result among the defining fields of `CaptureSubmission`, the record type section 16's *Six new canonical record types* table assigns to WP-6. *Corrected 2026-08-03 (`D-83`): this row cited `09_LOGICAL_DATA_MODEL.md`, which is the quick-capture document of that number and contains **no** occurrence of `CaptureSubmission` or of any of the four fields; two different `09_` documents exist and this package cites both. The substance is unchanged — the fields are canonically mandated — but the pointer a reader followed was wrong and this row rested entirely on it. The intra-plan line-number citation is replaced by the section name for the reason `D-83` gives.* They are mandated fields, not speculative columns. **And they are categorically different from `registered_client_id`, which `D-74` excluded**: these four are **written on every row** with the only value this build can produce, and a later transport widens the vocabulary, whereas `registered_client_id` could **never** be populated while `D-30`, `O-21` and `P00-OD-010` stand. `AGENTS.md` section 2 and `tables.py`'s own note bar the permanently-empty column — "a zero that means 'never measured' reads as 'nothing happened'" — and that bar catches the second case, not the first | Kept and disclosed. Invalidated by a reviewer showing any of the four is in fact never written |
| D-79 | This plan's "Corresponds to Quick Capture stages `QC-01` and `QC-02`" **overclaims** and is corrected to the durable-capture portion of those stages | **Found by the implementer, against an assignment that cited the wrong file.** The orchestrator's assignment sent it to `02_COMPREHENSIVE_IMPLEMENTATION_SPECIFICATION.md`; the stages are actually at `../specs/quick-capture/19_MVP_DEFERRED_CAPABILITIES_AND_ROADMAP.md:143` and `:152`, and are defined nowhere else in the package. Read there, `QC-01` requires "proposal/span schemas" and `QC-02` an "original-text read/search stub" — **both exceed WP-6's seven acceptance criteria and both are named out of scope by this plan itself**, which assigns proposals, spans and exact search to WP-7. A plan sentence claiming WP-6 *corresponds to* those stages is the stale-claim class this campaign has now recorded five times. **The implementer named it and left it rather than absorbing it — the fifth time that behaviour has produced a decision row** (`D-37`, `D-54`, `D-65`, `D-67`, and now this) | Corrected in place by WP-6's pull request. Invalidated by a plan revision moving proposals and span schemas into WP-6, which would require new acceptance criteria |
| D-80 | `D-71` is implemented **stronger than its letter**, and the defect it named had a second site | `D-71` said "restrict the substring check to the `sources.*` family". **That was wrong and the implementer overruled it correctly**: restricting *to* `sources.*` would have left `knowledge.*` unchecked, widening the hole instead of narrowing it. The shipped form exempts **exactly the capture family**, asserts the exemption set equals that family so it cannot quietly grow, and extends the recording-provider test to `capture.*` with the stronger claim that a capture path reaches the provider **not at all**. **The same defect existed at a second site the decision did not name** — `tests/security/test_http_negative_evidence.py`. One site named, two found: the class-sweep pattern holds for a fourth consecutive package. **And the plant nearly proved nothing.** The provider-lookup plant **fired nothing at first**, because the assertion was on `RecordingProvider.calls`, which does not observe a resolution; had that gone unnoticed, `D-71`'s entire exemption would have rested on a test structurally incapable of seeing the property it claimed to prove — the vacuous-guard shape arriving through the fixture rather than through the assertion. `FakeProviders` now records lookups. **This is the third time this campaign that proving a plant fires has caught a guard that could not fire** (`D-26`'s import guard, `D-44`'s citation universe, and now this) | Implemented as stated, at both sites. Invalidated by evidence that the exemption set does not equal the capture family |
| D-81 | The enum-derived-constraint hazard is **closed** for `audit_events` and for WP-6's own revision, and **controlled**, not closed, for the rest of the chain | `D-69` claimed to leave every already-merged revision denoting exactly one schema and **it did not**: the independent reviewer planted a `DenialReason` member and measured already-merged `9c6b4a18ed72` emitting `denial_reason IN (…, 'zz_reviewer_probe')` with **nothing reddening anywhere**, because the freeze and its checked claim covered `capability` and `purpose` only. All four closed-set constraints on `audit_events` are now frozen. **So are the eight on `1a4c9e77b2d5`, which nobody had named**: WP-6's own new revision derived from `Classification`, `ProcessingPolicy`, `CaptureTransport`, `CaptureMethod`, `TrustState`, `AdmissionResult`, `JobState` and the public error-code set, so the package writing the standing rule was breaking it eight more times in the same pull request. The rule is converted from prose into a control — `../../tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` walks every revision in the chain, compares what it emits against every live closed set the package declares, and asserts the still-derived sites equal an explicit allowlist that pins each site's exact vocabulary, so a member added to any listed set reddens and a new derived constraint reddens. **The allowlist holds ten sites in two revisions, drawn from ten distinct sources — not the nine in eight enums the review named, and not the "ten sites in nine sources" this row itself later carried** (corrected by `D-92`, which re-derived the list from the guard's `ALLOWED` ledger rather than restating it; the source that both undercounts omit is `my_pa.contracts.v1.errors.ErrorCode`). **The list is derived, not typed**: `quarantine_review_state_is_known` derives from `QuarantineReviewState`, which the list omitted, and `jobs.last_error_code_is_a_public_error_code` derives from the eleven public `v1` error codes rather than from a `StrEnum`, which is why a sweep for the declarative enum helper does not see it. **WP-6 changes the membership of none of the ten**, so none of them fires today. Freezing them across `7e5a1fb93d62` and `8b3f5c17d904` is a separate package; a guard plus a shrinking allowlist closes the class honestly today. Byte-identity of the edit was proved by a whole-schema dump — schemas, tables, columns, constraints, indexes, triggers, routines, views, sequences, extensions — of a database stopped at `9c6b4a18ed72` built from `08e7c81` and from this head: **18569 lines each, SHA-256 `88f18af8f405c7476fc72b85f59de9365b4d3dc3cfcd7ea3795cf18376664912` on both sides**, and the comparison proved non-vacuous by re-running the base side with the reviewer's plant live, which moved exactly one line and the hash to `2ef47d51…` | Controlled by a mechanical guard. Invalidated by the allowlist reaching empty, or by any listed set gaining a member without the guard reddening |
| D-82 | `idempotency_conflict` is an **open spec-versus-`v1`-contract conflict**, not a plan error. The `v1` disposition stands: `conflict` with `safe_details: ["idempotency_key"]` | `D-75` recorded that this plan invented `idempotency_conflict` and that a twelfth code "would have been an unauthorised `v1` expansion". **The word is the spec package's own**, verified at `../specs/quick-capture/18_PROPOSED_API_AND_CONTRACT_PACKAGE.md:255` and `:316` and at `../specs/quick-capture/09_LOGICAL_DATA_MODEL.md:296` — and notably **not** at `20_TESTING_EVALUATION_AND_ACCEPTANCE.md:206`, which names no code at all, so the plan drew it from the contract package rather than from the criterion it paraphrases. Under `D-75`'s own rule that the spec governs, that makes this a conflict between two instruments rather than a defect in one. The disposition is unchanged because the spec itself defers to the repository: `18:14` says the proposed contracts "do not authorize implementation or change the repository's current `v1` capability set", `../../src/my_pa/contracts/v1/errors.py` is a closed set of eleven whose retry guidance and validator both enumerate every member, and `18:344` requires generated-client compatibility evidence before a new code lands. **What changes is the classification, and it matters: a plan error is closed by fixing the plan, and a conflict stays open until an instrument moves.** | Open. Invalidated by a decision expanding the `v1` error vocabulary, or by a spec revision withdrawing the twelfth code |
| D-83 | An **intra-file citation carries a stable identifier, never a line number**; a line number is used only for a file the change does not modify, and is verified to resolve at head | The independent reviewer found eight citations in the `D-73`/`D-74`/`D-75`/`D-76` register rows that resolve at `08e7c81` and not at head — because **the same commit that wrote them lengthened this file from 1683 lines to 1780**. Nothing was fabricated; every one had rotted before it shipped. This is the citation-integrity class this campaign has recorded five times, now inside the register itself, and it is *structurally* guaranteed: a line-number citation into the file a commit edits cannot survive that commit. Fixing the eight numbers would have left the mechanism intact and the next package would repeat it. **The rule is therefore about form, not about arithmetic**: within this file, cite the section heading or the register row ID; outside it, cite `file:line` and check it at head. **Scope, stated because the first statement of it understated it**: that correction edited **five** register rows — `D-73`, `D-74`, `D-75`, `D-76` and `D-78` — not the one `D-78` its summary named. **And the rule did not hold**: the same commit gave `D-85` a bare `:NNN` for an external spec, in a row naming no file, so it pointed at this plan; four more sat in `D-75` and four in section 12's WP-6 criterion bullets. Prose was not enough, and the rule is now a control — `../../tests/architecture/test_citations_resolve_at_head.py` reads every citation in repository-authored `.md` and `.py`, requires each cited path to name exactly one file and each cited line to exist in it, and requires a bare `:NNN` to have a path in its own block, which is the rule this row wrote and the one it broke. A whole-repository sweep of every citation this package added found **154 checked across four locations, 12 defective in six classes** — one wrong *file* (`D-78`, corrected here), one ambiguous shorthand in the pull-request body, four stale intra-file line numbers, one body-prose citation six lines off the sentence it quotes verbatim, one "in the same sentence" claim about two lines seventeen apart, and one path containing a literal ellipsis. **The six `capture.create` shorthand citations `D-68` rests on are all correct**, and resolve in `../specs/canonical-product-definition/`. **Amended by WP-6's third correction cycle, because the rule stopped one step short and the guard says so.** A line number that *resolves* is not a line number that is *right*: `../../tests/architecture/test_citations_resolve_at_head.py` decides that a citation lands, never that it lands on what the sentence claims about it, so a pointer into a file the same change lengthens rots silently while every rule in that guard stays green. **Measured at `862846e` over the class the reviewer named — every citation into a file this branch modifies — ten pointers had moved, across five files, of which the review named three; three of the ten were written by this branch and were already wrong when they shipped, one of them inside a guard module.** The form rule therefore reaches outside this file as well as inside it: **cite a function, a test, or a constant by name whenever the target is a file the change touches**, because a symbol does not move when a file grows, and reserve `file:line` for a file the change leaves alone. One pointer is deliberately left as a line number — `commands.py:230-238` in the `D-37` row — because that row is quoting the citation it is correcting, and rewriting a quotation to be accurate destroys the record it exists to keep | Standing form rule, now covering the symbol form as well as the bare-line form. Invalidated by a mechanism that makes intra-file line numbers survive an edit to the same file |
| D-84 | The save transaction's atomicity is an **open spec-versus-`D-34` conflict**, not a plan error. `D-34` stands and the implementation is unchanged | `D-75` recorded that this plan's "capture, version, receipt, **redacted audit**, and job commit together or not at all" was **false**. The sentence is faithfully copied from the spec package, which states it in five places — `../specs/quick-capture/05_END_TO_END_WORKFLOW_INVENTORY.md:20` ("Server transaction persists capture, version, receipt, audit event, and processing job/outbox"), `../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:33` (which is where the word *redacted* comes from), `../specs/quick-capture/02_COMPREHENSIVE_IMPLEMENTATION_SPECIFICATION.md:260`, `../specs/quick-capture/17_TECHNICAL_ARCHITECTURE_RECOMMENDATION.md:124`, and `../specs/canonical-product-definition/12_MVP_DEFINITION.md:115`. **The spec package also contradicts itself**: `../specs/quick-capture/13_OFFLINE_AND_SYNCHRONIZATION_SPECIFICATION.md:106` and `20_TESTING_EVALUATION_AND_ACCEPTANCE.md:47` both list the atomic set **without** the audit, and `20_…` is the file `D-75` names as governing. The repository sides with the two that omit it, on `D-34`'s ground that a security-relevant decision must outlive the work it authorized. **So the correction is right and its label was wrong**, and the same reasoning that produced `D-82` produces this: the plan was restating an instrument, not misreading one | Open. Invalidated by a spec revision resolving its own contradiction, or by a decision overturning `D-34` |
| D-85 | The `QC-AC-034` bullet is a **correct test filed under the wrong criterion**, and spec `QC-AC-034` is **not exercisable in WP-6** | `D-75` reviewed six of this plan's criterion statements, found five wrong or narrowed, and pronounced `QC-AC-034` **"TRUE — keep exactly as worded"**. It did not compare the bullet to the criterion it names. Spec `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:208` reads "`QC-AC-034`: Processing failure never loses the source capture" — a failure *after* the save, requiring the capture to **survive**, corroborated by `../specs/quick-capture/05_END_TO_END_WORKFLOW_INVENTORY.md:124`. The bullet describes a *save-time* audit or receipt failure requiring **no capture to exist afterwards** — the opposite direction, about a different failure. The bullet's requirement is real and has its own spec ground at `../specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:37`; what it is not is `QC-AC-034`. **Spec `QC-AC-034` cannot be proven here at all**: nothing consumes `knowledge.capture_jobs` until WP-7, so no processing stage exists whose failure could lose a capture. The test is kept, the label is disclosed as wrong, and the criterion is carried to the package that builds the worker. **The finding that matters beyond this row is that a verdict of "correct" received no sweep** — five statements were checked against the spec and the sixth was checked against itself | **Closed by WP-7**, which is the package that consumes the capture outbox: `infrastructure/jobs/capture_pipeline.py` is the processing stage whose failure could lose a capture, and `tests/jobs/test_capture_pipeline_recovery.py` proves it does not — the failure injected inside `P-15`'s transaction after the proposal `INSERT` and before the commit, with the version's content and digest re-read and compared afterwards, a clean re-run producing proposals as the control, and `UPDATE` and `DELETE` on the version both refused with `SQLSTATE 23001`, which is what makes "never loses" a property of the schema rather than of the code that happened to be running. Invalidated by a package that removes the append-only trigger |
| D-86 | The six **single-value-embedding** constraints are **ledger, not blocker**, and the guard must state that it does not cover them | Six constraints embed a single enum *value* rather than a closed set — one on `audit_events` and three on `extractions`, plus the `jobs` and `capture_jobs` lease checks. **WP-7 added a seventh and named it rather than letting it pass**: `capture_proposals`' `(state = 'invalidated') = (quarantine_reason IS NOT NULL)` embeds the single value `'invalidated'`, and it is the honest posture — the alternative was a proposal that records evidence failed without recording how, or a reason attached to a state that was not refused. It is implemented in the guard's ledger and named in its docstring, which is what this row's second half requires. Note that `capture_spans.offset_basis` is **not** an eighth: `D-97` writes `'unicode_code_point_v1'` as a literal inside the frozen revision precisely so that no new site of this class is created. The reviewer measured the gap rather than inferring it: renaming `AuditOutcome.DENIED` moves the DDL an already-merged revision emits and `../../tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` **stays green**, so this is the same family as `D-69` and `D-81`. It is judged **materially weaker**, and the asymmetry is the whole reason: adding an enum member is **silent**, whereas renaming a value **breaks loudly** at every consumer of that string — the constant, the persistence mapping, every fixture, every assertion. `D-81`'s hazard is silent drift; this one announces itself. **The second half is not optional and is implemented, not promised**: that guard's docstring now states in terms that this class is outside its coverage, names all six sites, and says what would close it. A control described as closing a class it does not close is the overclaim this campaign has caught repeatedly — most recently `D-44`'s citation guard, whose universe admitted root directories but not root files while the document asserted every cited path was checked | Recorded as ledger; the guard names its own boundary. Invalidated by evidence that a value rename can drift silently — at which point it becomes `D-81`'s class and blocks |
| D-87 | The FAST budget is **accepted at ~38s of 60s**, and the growth model is **measured rather than feared** | The worry was that one package consumed a third of the remaining budget. Measured at `d2494cb`, the measurement says otherwise about *why*: **collection is 0.75s** of the run, so it is not the bottleneck; **no module is expensive**, the slowest being `../../tests/architecture/test_open_decision_counts.py` at **0.08s**, with the top twelve modules summing under 0.4s and **6756 of the durations each under 0.005s**. FAST is therefore **≈15.7 ms per test and roughly linear in test count** (base 2195 tests / 31.27s = 14.2 ms; head 2354 / 36.90s = 15.7 ms). **The useful consequence**: the ~22s of headroom is worth roughly **1400 more FAST tests** (*superseded 2026-08-03 by `D-100`, which re-measured this row's own model rather than restating it: the ≈15.7 ms per test below is replaced by a measured **≈42 ms**, and **≈1400 is wrong twice over** — once on that model, and once on the **60s** denominator it is drawn against while this same row names **55s** as the trigger. **The number a package plans against is ≈235**, and it re-measures before spending any of it*), not "a third of five packages", and the cartesian term everyone fears — `len(Capability) × len(Purpose)`, now 12 × 9 = 108 — costs about **1.7s** even if WP-7 and WP-8 take it to 18 × 13 = 234. There is no `slow`-test problem to solve; there is a test-count budget and it is generous. The next package **re-measures before adding capabilities**, and if a package would take FAST past **55s** the cartesian policy and parity matrices move off the FAST tier — **coverage is not trimmed to fit the budget** (`../../AGENTS.md` section 7: "Do not omit a critical contract merely to meet the target. Adjust the target from measured evidence rather than silently reducing coverage.") | Accepted, with a measured growth model rather than a worry. Invalidated by a package introducing a FAST test with a materially different cost profile, which the re-measurement requirement exists to catch — **and that condition has since fired**: WP-7 did, the re-measurement caught it, and this row's **arithmetic** is superseded by `D-100` while its conclusion survives. Preserved, not deleted |
| D-88 | The `AS head` guard's **alias pattern is widened to the spellings PostgreSQL actually accepts**, rather than disclosed as a gap | `_ALIAS` in `../../tests/architecture/test_no_stored_revision_is_labelled_head.py` matched only `AS <word>`, so two further spellings of the one thing that rule forbids each produced a column **literally named `head`** which it passed: `AS "head"`, where the quotes are not `\w`, and a **bare implicit** `head`, which has no `AS` to key on. **Measured, not argued**: each spelling was planted *in place* at `../../ops/runbooks/postgres-operations.md:187` against the unwidened rule and the rule reported **11 passed**, while the already-caught `AS head` planted at that same site reddened — so the site was live and the hole was demonstrated rather than asserted. **No live instance existed** — every revision-reading query in the corpus aliases `revision` — so this was a **future-miss, not a defect**. **Closed rather than disclosed, which is where this departs from `D-86`**: that row disclosed a gap because closing it meant a second derivation of a different class, whereas this is a widening of the pattern the guard already owns. The guard's whole reason to exist is that this class escaped **three consecutive human sweeps**, so a known hole in it is not something to carry. **The implicit branch is positional, not an optional `AS`** — the reviewer's suggested shape, taken as a suggestion rather than a measurement: making the keyword optional matches every word in the region, and the regions are not all SQL, since `database_revisions` in `../../apps/cli/health.py` qualifies as a revision-reading query while being English prose (cited by name rather than by line for the reason `D-83` gives; the package carrying this correction edits that file). Swept over all **14805** regions the rule reads, an optional-`AS` branch finds one such word — `head` in the prose of `../../tests/schema/test_head_round_trip.py`, a region one `SELECT` away from being read — and the positional branch finds **none** | Closed in WP-6. The widened pattern is pinned by five further cases in the guard's own table, and its one residual over-reach — a *table* aliased `head`, which names no column — is stated in the docstring and asserted rather than left to be found. Invalidated by a PostgreSQL alias form the widened pattern still does not reach |
| D-89 | WP-7's criteria are taken at **spec** strength. There are **six**, and **five** of this plan's statements were wrong | The binding text of each criterion is `../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md`, not this plan's paraphrase; the WP-7 section is corrected in place. `QC-AC-050` **narrowed, load-bearing**: `20:221` says "**Exact** original text is searchable" and the plan dropped "Exact"; measured, `to_tsvector('english','…running…')` stores `run` so `run` matches text that never contains it, and `to_tsvector('english','a the of and')` is **empty**, so a stop-word-only capture is saved, valid, and unfindable **with no exception anywhere**. `QC-AC-011` **narrowed twice and its stated proof is impossible**: `20:190` says "exact **validated**" and covers "proposal/**accepted derived record**", the plan says "at least one" and drops the accepted half; and "prove by mutating a version and re-running" **cannot run** because merged `1a4c9e77b2d5` installs `capture_versions_are_append_only` (`BEFORE UPDATE OR DELETE`, `restrict_violation`), measured present at head — the proof is persistence-layer span injection instead. The accepted-record half is **half-discharged here** and re-proved by WP-8, disclosed rather than absorbed. `QC-AC-042` **narrowed**: `20:215` says "broaden retrieval/**disclosure**" and the plan says "widened scope"; disclosure is a first-class object here (`application/disclosure.py`, canonical `09:130`), so captured text must also not alter coverage, limitations, or freshness. The corpus's synthetic requirement is grounded in `QC-AC-073` (`20:239`) and `../../AGENTS.md` section 5, **not** in `QC-AC-042`. `QC-AC-002` **proof insufficient**: "no proposal row in the committed set" is membership and the criterion is ordering; WP-6 did not discharge it and WP-7 owes the indexing half. `QC-AC-035` **true**, with the "or accepted objects" clause disclosed as **vacuous** here. `QC-AC-034` is the **sixth**, carried by `D-85`. Six stage deltas are admitted into the in-scope sentence, `P-13` is ruled **in scope** and discharged structurally, and the out-of-scope **reason** is corrected — the exclusion survives, but "model-assisted" is absent from `11` for `P-06`, `P-07` and `P-12`, and `P-07` explicitly permits deterministic inputs. This is the `D-75` finding reproduced: the plan is a paraphrase and the spec is the instrument, and six of the last nine packages found a plan claim measurement contradicted | Adopted and corrected in place by WP-7. Invalidated by a spec revision |
| D-90 | Exact capture search is a **second** FTS plane over `capture_versions.content` using `simple`, not `english`, with exact-substring confirmation | One `capture_text_in_scope()` predicate **and** one statement builder parameterised over a `SearchPlane` — the shape `D-76`/`D-77` established for `JobPlane`, so the page and the totals agree **by construction** rather than by comparison. That control is the point: `coverage_for` and `match_statement` on the extraction plane were *asserted equal* for six review rounds and were false for two of six conditions. **Candidate (a) is refused** — routing captures through `knowledge.extractions` needs an `enrollment_id`, which is `NOT NULL` with a foreign key on a table merged revision `8b3f5c17d904` creates, and that is `D-76` on the identical column shape. **Why `simple`**: measured, it keeps stop words, does not stem, and matches `RFI-0421` and `$12,500.00` as adjacent lexemes; `english` fails `QC-AC-050` in two measured ways (`D-89`). **The cost is disclosed, not smoothed over**: no stemming, so a search for `meetings` will not find `meeting`. That is published as a `Limitation` through the disclosure envelope — `capture_search_matches_words_as_written` — rather than left for a caller to discover. Plus a larger index and a second predicate. **Two defects this decision's own implementation carried, both found after it was adopted, and both the same class — the confirmation and the predicate disagreeing about what the query text means**. (i) The confirmation compared bytes while the predicate compares lowercased lexemes, so a query for `buyout` silently removed a capture whose text says `Buyout`; both sides are now case-folded. (ii) The eligibility test read the **raw** query text while `websearch_to_tsquery` strips a double quote as syntax and a trailing full stop as nothing, so `"buyout"` and `buyout.` were confirmed against needles containing them and were removed after the index had matched. Measured over query forms generated from PostgreSQL's own character classification, **328 of 402** index-matching cells were dropped; the fix reads both the needle and the decision to use it from the server, and the class is guarded by a generated matrix rather than by a third list of cases. Fixing (i) and leaving (ii) open in the same cycle is why the guard is now mechanical | Adopted and implemented in WP-7. Invalidated by a measured need for stemming on capture text, which would need its own plane and its own disclosure rather than a configuration change to this one |
| D-91 | `capture.search` is the **thirteenth** `Capability`; reuse `Purpose.CAPTURE_REVIEW`; **write the freeze before the member** | `knowledge.search` does not serve both planes: `domain/identity/purpose.py` already argues that a single grant spanning two scopes is the escalation the purpose split exists to refuse, and a `knowledge.read` request returning raw user-authored capture text is that escalation by another route. **Add no `Purpose` member** — a new purpose costs another `ALTER` and would map to exactly one capability. The freeze is written **first**, not after the guard reddens: WP-7's revision carries a 13-value `_CAPABILITIES_AT_THIS_REVISION`, a 12-value before-literal, a `_restate()` in `1a4c9e77b2d5`'s shape, `_FROZEN` plus `_historical_wp7_tables()` for its own new tables, and the new callable's name in `_EMISSION_CALLABLES`. **Measured, and this is why the row exists**: on a disposable database with plants live, the still-derived `quarantine_reason_is_known` gained `'zz_wp7_probe'` and `jobs.state_is_known` gained a fifth value, while the frozen `capability_is_known` stayed at **12** with 13 members in code and `capture_job_state_is_known` stayed at **4** with 5. The freeze works — **which is exactly why adding `capture.search` without the `ALTER` passes every test and is refused in the field on the first audited search**, because every test builds its database from scratch. Green tests would not catch it. **Extend no other frozen enum**: `JobState`, `ErrorCode` and `QuarantineReason` each cost a still-derived *and* a frozen site, so processing state and proposal-quarantine reasons take **new** enums on **new** tables where `D-48`'s carve-out applies | Adopted and implemented in WP-7. Invalidated by a canonical revision renaming the capability, which is a `v1` break (`O-01`) |
| D-92 | `D-81`'s site count is corrected to **10 sites in 10 sources**, and plan section 16's classification row does **not** extend the `Classification` enum | Two corrections to inherited claims, both found by deriving the list from the code rather than restating it. **First**: `D-81` and the WP-7 brief both said "10 sites in **9** sources". The tenth source is **`my_pa.contracts.v1.errors.ErrorCode`**, at `jobs.last_error_code_is_a_public_error_code`, which the nine-name list omits. This is the same undercount `D-81`'s own text warns about — "the independent reviewer's list named nine sites and eight sources, both numbers were low" — repeated once more, one source higher, inside the row that warns about it. The list is **derived, not typed**: it is read out of `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`'s `ALLOWED` ledger rather than transcribed, which is what stops the count going stale a fourth time. **Second**: the classification row in section 16 assigns the **record types** `CaptureClassification`/`CaptureDomainAssignment` to WP-7. It does **not** assign `my_pa.domain.common.classification.Classification`, which is a **data-sensitivity** enum (`private_local`, `restricted_local`, `synthetic_test`) and a different subject with a similar name. Reading the row as an enum extension would have triggered a freeze nothing needed | Adopted in WP-7. Invalidated by a further derivation returning a different count, which must then correct this row rather than replace it silently |
| D-93 | `CaptureEntityMention` is **built, restricted to the deterministic subset**, and section 16's state ladder is misattributed and corrected | The conflict is real and this plan contains both sides: the WP-7 section excludes `P-06` named-entity extraction, while section 16 assigns `CaptureEntityMention` — the object `P-06` produces — to WP-7. Resolved by building the deterministic subset rather than by deferring the record type. **In**: document and project identifiers, and URLs, all already produced by `P-05` (`11:75-77`), each carrying a span and each always **`unresolved`**. **Out**: people and organisations, which need an alias table that does not exist; locations and topics, which have no deterministic source at all. `resolution_state_is_known` is frozen at the single value `('unresolved')` — the `D-78` and `QuarantineReviewState` one-value precedent this campaign has already accepted. **Why build rather than defer**: `D-74` defers a record type that is **permanently empty**, and this one is populatable on day one; and WP-8's `ConversationParticipant` binds an unresolved mention to a span (`09_LOGICAL_DATA_MODEL.md:236-237`), so deferring means building mention-to-span binding **twice**, which is the `D-41` objection in the direction that actually applies. **Correction to section 16's row**: it says the unresolved/candidate/resolved ladder is "the same shape as the `Proposal` states section 12 already directs WP-7 to use". **It is not.** That ladder is canonical `09:96`'s **`Identity`** state set (`resolved`, `candidate`, `unresolved`, `merge_proposed`, `split_proposed`, `superseded`); `09:94`'s `Proposal` set contains neither `candidate` nor `resolved`. The sentence is corrected; the row's assignment survives | Adopted and implemented in WP-7. Invalidated by an alias table arriving, which widens the subset rather than overturning it |
| D-94 | **One package.** `CaptureDomainAssignment` is deferred to WP-8; WP-7 is not split | The candidate boundary — pipeline, proposals and spans against exact search — **is not a partition**. `QC-AC-050` and `QC-AC-002` both straddle it: a search-only package can prove "searchable" but **not** "independently of enrichment success", because proving that needs an enrichment that **fails**, which is the other package's machinery. Shipping it split would therefore **narrow `QC-AC-050`** to its first clause, which is `D-52`'s exact refusal shape. `D-57` split WP-5 only because the partition was clean — three criteria against none — and this is not that. `D-74`'s README argument bites too: `capture.search` is a capability and `tests/architecture/test_readme_state_claims.py` derives README's readiness from `_HANDLERS`, so a package that named it without wiring it would falsify README between two merges. **`P-16` sits outside `P-15`'s transaction and must** — `11:191` "immediately" and `QC-AC-050` "independently of enrichment success" together require it — so the `D-41` "build that transaction twice" objection does **not** apply and is not used. **`D-74`'s other test fires instead**: `CaptureDomainAssignment` is **unpopulatable** in WP-7, its only deterministic input being a launch-context link that WP-8 owns, and a permanently-empty table is barred by `../../AGENTS.md` section 2. **The boundary between the two record types, which section 16 says outright it does not answer**: `CaptureClassification` is **evidence-bound and about the text** — one row per `(version, scheme, scheme_version, label)`, each carrying its deterministic rule, that rule's version, and **at least one span**; `CaptureDomainAssignment` is **interpretation and about placement** — one row per `(version, domain, assignment_version)`, superseded rather than updated, carrying **no span**, because it is a claim about the whole capture. The test that makes them two records: a classification can be *cited*; a domain assignment cannot, because no phrase means "this belongs to the Riverside project" | Adopted in WP-7. Invalidated by a design that leaves **no** criterion half-proven under a split |
| D-95 | **`O-19` is closed.** The processing-policy slot already exists; WP-7 adds no member | `O-19` asked whether "save without AI processing" appears in MVP, and ruled that it is a stored processing-policy value rather than a UI toggle, so it "must exist in the schema or not at all". **It exists**: `knowledge.capture_versions.processing_policy` is a real column, backed by `ProcessingPolicy` with one member `LOCAL_ONLY`, and `processing_policy_is_known` is frozen at `('local_only')` in `1a4c9e77b2d5`. WP-6 built it, so the "or not at all" branch is already closed. WP-7 adds **no** member: `P00-OD-006` is open and there is no model in the system, so every capture is already processed without AI and a `no_ai` member would change no behaviour and be distinguishable from `local_only` by nothing — which `../../AGENTS.md` section 2 bars. What WP-7 **does** owe is `P-01`'s dropped requirement (`11:46`): **load the processing-policy snapshot recorded at save and branch on it**, so the policy that governs is the one recorded when the capture was written rather than the one current at processing time, and the package that opens the model boundary adds its route by a forward `ALTER` and finds the branch already there. Implemented as an **allowlist** rather than an equality test, because an `is not` comparison against a single-member enum is statically constant and a build that grew a second policy would process it through a branch nobody wrote; a policy outside the allowlist stops at `P-01` as `policy_denied` | Closed in WP-7. Invalidated by a canonical revision defining a second policy value |
| D-96 | **No twelfth `v1` error code.** `D-82` stands undisturbed | `contracts/v1/errors.py` stays closed at **eleven**. WP-7 does not need a twelfth: the pipeline's idempotency is *stage replay returning prior output* (`11:212`), which is not a client-facing error at all, and `D-82`'s standing disposition — `conflict` with `safe_details: ["idempotency_key"]` — already serves the save path and WP-6 shipped it. **The cost is now measured rather than argued.** A twelfth member moves **two** already-merged constraint texts in opposite directions: `jobs.last_error_code_is_a_public_error_code` is **still derived** in `7e5a1fb93d62` and would move, reddening `test_no_revision_derives_a_closed_set_outside_the_allowlist` and forcing a freeze of a revision WP-7 has no other reason to touch; while `capture_job_error_code_is_a_public_error_code` is **frozen** in `1a4c9e77b2d5` and would *not* move, so head silently stops admitting the new code on the capture plane — the same failure shape `D-91` measured at the capability site. Plus `18_PROPOSED_API_AND_CONTRACT_PACKAGE.md:344`'s generated-client compatibility evidence and an operator-authorized scope change. If a later package wants it, **it needs its own decision row before implementation starts, not at review** | Adopted in WP-7. Invalidated by an operator-authorized `v1` scope change with compatibility evidence |
| D-97 | `unicode_code_point_v1` is written as a **literal inside the frozen revision**, not read from a Python constant, so `D-86`'s ledger gains no new site | `capture_spans.offset_basis` is constrained to the single value `'unicode_code_point_v1'`. Writing that literal in the revision keeps the value where the freeze mechanism already owns it; deriving it from a Python constant would create a **new** single-value-embedding site of exactly the class `D-86` records as its blind spot, and would oblige the guard's docstring to name it. Confirmed against the specification: **`unicode_code_point_v1` is the specification's own name, not this plan's invention** — `../specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:82`, again at `../specs/quick-capture/09_LOGICAL_DATA_MODEL.md:177`, and in the contract example at `18:293`. The hypothesis that the plan invented it is **refuted** | Adopted and implemented in WP-7. Invalidated by a second offset scheme, at which point the constraint becomes a closed set and takes the freeze mechanism proper |
| D-98 | "Every proposal carries at least one span" is a **`DEFERRABLE INITIALLY DEFERRED` constraint trigger**, not an application invariant | PostgreSQL cannot express a `[1..n]` cardinality across tables declaratively. The alternative — an application invariant plus a `database`-marked test — is "immutability as a property of the code that happens to be running", which `1a4c9e77b2d5`'s own docstring rejects for the same reason; and `QC-AC-011` is the criterion most likely to be violated by a future repair script, which does not run the application. Two triggers, not one: `AFTER INSERT` on `capture_proposals` and `AFTER DELETE` on `capture_proposal_spans`, so the rule cannot be evaded by writing the rows and then removing the link. **The `downgrade base` residue was measured, both directions**: `7e5a1fb93d62` drops the schema with `RESTRICT` and `1a4c9e77b2d5` had to drop its function explicitly, so this revision does too — measured, `downgrade base` leaves **only `public.alembic_version`**, and with the explicit `DROP FUNCTION` removed it fails with `DependentObjectsStillExist`. The revision's docstring says so | Adopted and implemented in WP-7. Invalidated by a measured inability to make the trigger's function reversible, which would need its own row rather than a silent fallback to the application invariant |
| D-99 | The `D-81` guard's blind spots are **disclosed in its own docstring** and **not fixed in WP-7** | Three findings sit outside WP-7's scope and are named rather than absorbed. **(1)** Revision `4b9f0d27ac31` is **structurally invisible** to the guard: it calls `METADATA.create_all(bind)` on `my_pa.infrastructure.migration.control_plane`'s **separate** `MetaData`, never imports `my_pa.infrastructure.persistence.tables`, and holds no `Table` in its namespace, so `test_every_revision_declares_its_emission_readably` `continue`s past it and `_emitted` returns `None` — and `control_plane.py` derives **five** further closed-set constraints from live enums (`RunStatus`, `PhaseStatus`, `TableState`, `QuarantineCode`, `AuditEvent`). This is a larger hole than the documented `D-86` class: not detected-and-allowlisted but structurally unreachable, because `DECLARATION` hard-codes one declaration module. **(2)** The guard's own docstring said "`ALLOWED` is the ten sites in the **three** revisions `D-81` deliberately does not edit" while its data and its own `test_the_allowlist_names_only_revisions_this_package_does_not_edit` both say **two** — a false statement inside the control WP-7 depends on. **(3)** `release_job` has no bounded exponential backoff or jitter against `11:216` — a released job returns to `queued` and is immediately reclaimable — and it is on the **shared** plane, so adding backoff would change enrollment-extraction retry behaviour. **What WP-7 does**: correct (2), and add (1) to the guard's docstring as a **named blind spot**. **What WP-7 does not do**: fix (1) or (3). A control that names its own blind spot beats one that implies totality; widening the guard to a second `MetaData` is its own package with its own review, and (3) is a change to merged behaviour WP-7 has no criterion for | Adopted in WP-7, with (1) and (3) left open and named. Invalidated by a package that widens the guard, which must then delete the disclosure rather than leave it stale. *Corrected 2026-08-08: **that invalidation condition has fired for (1), and this row is corrected rather than left standing.** The guard no longer holds a declaration-module name at all: `_declaration_modules()` discovers them by shape — a module-level `MetaData` plus at least one module-level `Table` bound to it — across a `pkgutil` walk of `my_pa`, so `control_plane` is found, and a third declaration module added tomorrow is covered with no edit to the guard. The blind-spot paragraph is gone from the docstring, as this row required. **(1) is closed and (3) remains open and deferred.** Finding (2) has not recurred: it was a docstring saying "three revisions" where the data said two, WP-7 corrected the word to "two", and the widening now makes three the correct answer again — so the docstring is true, for a different reason than when it was first written. Nothing about (2) is open. What the widening bought is narrower than "fixed" and is stated at that strength in the guard itself: `4b9f0d27ac31`'s five sites moved from **structurally unreachable** to **detected and vocabulary-pinned**, not to frozen. Freezing them means editing a merged revision, which `D-81` exists to avoid. Each allowlist row now records the exact vocabulary its site emits, so a member added to `RunStatus`, `PhaseStatus`, `TableState`, `QuarantineCode` or `AuditEvent` reddens the guard — none of which was true of any of them before. Two further findings came out of the measurement, and both say the hazard was undercounted rather than overcounted: **the independent reviewer's own list of this hole named nine sites and eight sources, and both figures were low** — `quarantine_review_state_is_known` derives from `QuarantineReviewState`, which that list omits, and `jobs.last_error_code_is_a_public_error_code` derives from the public error-code set rather than from a `StrEnum`, so a sweep looking for the declarative enum helper alone never sees it. No count of the allowlist is restated here on purpose; the guard asserts its own size and its own revision set, and a figure copied into this row would rot the way `D-21` describes. No new `D-` identifier is minted — see the identifier-reservation note below this table.* |
| D-100 | **`D-87`'s cost model is invalidated by measurement and replaced, and the replacement is independently recomputed and confirmed. The budget is accepted at 45.05s against a 60s hard limit, 9.95s under the 55s policy trigger that is the number a package plans against; the marginal cost of a FAST test is ≈42 ms, not ≈16 ms** | `D-87` accepted the FAST budget on a model of **≈16 ms per test, roughly linear in count**, and set its own invalidation condition: "a package introducing a FAST test with a materially different cost profile, **which the re-measurement requirement exists to catch**." **The re-measurement caught it, which is the control working rather than failing.** Measured by the orchestrator on one machine in one session, so the two figures are comparable rather than inherited from separate runs: `main` at `c0854b6` **2400 passed / 367 deselected of 2767 collected, 38.51s**; WP-7 at `61c178a` **2557 passed / 395 deselected of 2952 collected, 45.05s**. That is **+157 selected tests for +6.54 s**, and 6.54 s ÷ 157 = **≈41.7 ms per test**, or 41.7 ÷ 16 = about **2.6×** `D-87`'s figure. **Independently recomputed and confirmed, which is what separates a measurement from a claim.** The reviewer re-derived this row end to end, paired, on one machine in one session from a clean export, and reached the same place by a separate path: `main` at `c0854b6` **2400 passed / 367 deselected of 2767 collected, 38.16 s**; WP-7 at `a06bd95` **2557 passed / 395 deselected of 2952 collected, 44.91 s** — **+157 selected tests for +6.75 s**, and 6.75 s ÷ 157 = **≈43.0 ms per test**, 43.0 ÷ 16 = **≈2.69×**. Both universes are stated inline so either can be re-derived; the selected/deselected/collected counts are identical across the two, and the costs agree to within ≈3%. Wall-clock totals are machine- and session-dependent, so **the ratio is the portable figure and the seconds are not**. **Where it did *not* go, measured rather than assumed — and each percentage named to the measurement it comes from, because these are two different attributions and the narrower one sits inside the wider**: the transport-parity cartesian everyone watches grew `12 × 3` → `13 × 3` for **+2 tests and +0.61 s** (module total 66/8.89 s → 68/9.50 s), so the **cartesian term** is 0.61 ÷ 6.54 = **9.3% of the increase** and **≈91% falls outside it**; the whole `tests/contract` tier — which *contains* that cartesian module — grew **+6 tests and +0.92 s**, so **`tests/contract`** is 0.92 ÷ 6.54 = **14.1%** and **≈86% falls outside `tests/contract`**. **The 86% is the `tests/contract` attribution, not the cartesian one**; the reviewer reproduced the `tests/contract` term at **+6 tests / +0.97 s** = 0.97 ÷ 6.75 = 14.4%, ≈86% outside, in their own universe. The residue is 157 − 6 = ~151 new deterministic units for 6.54 − 0.92 = 5.62 s, and 5.62 s ÷ 151 = **≈37 ms** each, none individually slow enough to enter the slowest-twelve list (whose floor is 0.22 s and whose entries are all pre-existing transport tests). **The consequence for the packages that follow, stated against the denominator that binds — the 55 s policy trigger, not the 60 s hard budget**: headroom to **55 s** is 55 − 45.05 = **9.95 s**, and 9.95 ÷ 0.0417 = **≈239 more FAST tests** at the orchestrator's profile; in the reviewer's universe it is 55 − 44.91 = **10.09 s**, and 10.09 ÷ 0.0430 = **≈235**. **A package plans against ≈235**, the lower of the two, and re-measures before it spends any of it. The **60 s** figure is the hard budget and is kept in view rather than deleted, so a reader can see both denominators and which one binds: headroom to 60 s is **14.95 s ≈ 359 tests** (orchestrator) or **15.09 s ≈ 351** (reviewer), against the ≈930 that `D-87`'s ≈16 ms model predicts for that same 60 s. Crossing 55 s does not fail the build — it fires the standing policy below, which is why 55 s is the planning number and 60 s is only the wall. An earlier statement of this row gave the consequence as ≈360 against the 60 s budget while naming 55 s as the trigger in the same passage; the denominator is corrected here and a bare number whose denominator must be inferred is not left standing, since that inference is how the error arose. **`D-87`'s conclusion survives and only its arithmetic is replaced** — no WP-7 work needs re-marking, because every new behavioural test is already `database`-marked and FAST *selection* was unchanged across the correction cycle; and the standing policy is unchanged: a package that would take FAST past **55 s** moves the cartesian matrices and parity matrices off the FAST tier, and **coverage is not trimmed to fit** (`../../AGENTS.md` section 7). **The next package re-measures on its own machine in its own session before adding FAST tests, and compares against a base it measured itself** — comparing two numbers produced by different agents at different times is what made this figure look like drift until it was measured properly. **`D-87`'s own forward projection is superseded here rather than rewritten in place, because it carries the identical defect this row was corrected for**. **That defect was `MINOR-7`, raised as a MINOR finding against an already-approved head at `a06bd95` and fixed in cycle rather than ledgered — not a BLOCK. The only BLOCK this package has seen was `QC-AC-050` at `4fe30e8`, and it was unrelated. An earlier statement of this sentence called it "the identical defect this row was BLOCKed for", which was false, was written by the orchestrator, and is the stale-claim class landing inside the row that exists to correct a number**: `D-87` reads "the ~22 s of headroom is worth roughly **1400** more FAST tests" while naming **55 s** in the same row as the trigger for moving the matrices off FAST — the 60 s denominator again, against a 55 s policy. Both of `D-87`'s figures are superseded: **≈1400 is wrong twice over**, once on the ≈16 ms model this row replaces and once on the 60 s denominator, and the number a package plans against is **≈235** above. The original row's wording is left verbatim per this campaign's practice of preserving superseded decisions rather than rewriting their history, and `D-87` now carries a dated forward pointer to this row in the `D-78`/`D-81` shape — added beside the ≈1400, not substituted for it — so a reader who never reaches `D-100` is not left planning against a number that is wrong twice over; **the correction is that the defect was a class of two, not a case of one, and the second instance was found by the worker that fixed the first** | Accepted for WP-7 and carried forward. Invalidated by a further re-measurement returning a materially different marginal cost, which must then correct this row's arithmetic rather than restate its conclusion |
| D-101 | **Resolve WP-8's six overlapping operator decisions as one fail-closed policy** | `O-15` and `RI-OD-011`: deterministic launch context is the only automatically accepted link; inferred links stay proposed. `O-16` and `RI-OD-012`: commitments, decisions, financial facts or amounts, critical dates, contradictions, and sensitive relationship conclusions always require review, regardless of confidence; low-risk technical enrichment alone may avoid mandatory review. `O-17`: an accepted record grants no external-action authority. `O-18`: explicit Conversation Log creates one skeletal event, while a conversation inferred from a Quick Note remains proposed. These are the recommendations already carried by the blocking table, now adopted under the operator authority delegated for WP-8 rather than silently assumed in code | Adopted and implemented in WP-8. Invalidated only by a later explicit operator policy revision, which must change the decision register, code, and tests together |
| D-102 | **Conversation participants are deferred to WP-9; WP-8 does not add a permanently-empty participant table** | The WP-8 in-scope sentence named participant associations, but this build has no person/organization identity record and WP-7 deliberately restricted entity mentions to deterministic document/project identifiers and URLs. A participant row would therefore have no valid target or writer. Adding nullable free text would duplicate sensitive capture content and contradict the evidence-span rule; adding an unpopulatable table would violate `AGENTS.md` section 2. WP-8 still creates the explicit skeletal Conversation event required by `O-18`, with unknown participants represented by absence as the specification permits. WP-9 owns person identity and unresolved people mentions and is the first package able to populate participant associations honestly | Deferred, not implemented. Invalidated when WP-9 supplies the identity/mention target and a bounded writer. *Corrected 2026-08-08: **the invalidation condition fired and the row was not updated, so this state cell is false at `8dd4ef6`.** WP-9 supplied both halves it named. `migrations/versions/20260804_7f2a9d6c4e18_create_relationship_identity_profiles.py:181` creates `knowledge.relationship_conversation_participants` unconditionally, with `a_conversation_participant_names_one_identity_target` (`:188`) enforcing that exactly one of `person_id` or `unresolved_mention_id` is present — the identity target whose absence was this row's entire reason to defer — plus the two partial unique indexes at `:192` and `:195`, triggers, and a matching `DROP TABLE` in the downgrade. The table is declared in `infrastructure/persistence/tables.py:2209-2210` and read by `infrastructure/persistence/relationships.py:40, 343-344`. **The deferral was correct when it was taken**, and the reasoning that produced it — no identity record, no honest writer, and `AGENTS.md` section 2's bar on an unpopulatable table — is why WP-9 was the right package to own it. Only the terminal state is wrong: it is **implemented by WP-9**, not **deferred**. The superseded wording is kept and negated rather than replaced, per the `D-78`/`D-81` shape. No new `D-` identifier is minted — see the note on identifier reservation below this table.* |
| D-103 | **The campaign briefing file named by the WP-8 execution directive is absent from repository history; execution uses the pasted operator directive plus repository authority** | A bounded repository/ref search found no `CAMPAIGN-BRIEF.md`. Its absence is a plan/reality discrepancy, not permission to invent its contents. The pasted directive supplies the campaign objective, operator delegation, single-worker constraint, exact-head review/merge gates, and prohibition on deployment. `AGENTS.md`, this plan's WP-8 section, ADR-003, and the mirrored Quick Capture specifications supply the implementation and acceptance criteria. The missing file therefore weakens provenance convenience but does not prevent safe acceptance mapping; exact implementation and review evidence remain bound to Git/CI and the governed external audit artifact | Recorded by WP-8. Invalidated if an authenticated byte-exact campaign brief is later recovered, at which point it must be reconciled rather than silently substituted |
| D-104 | **WP-10 is deferred until MCV completion; WP-11 remains dependency-blocked on it** | Direct operator instruction on 2026-08-04: “defer wp-10 until mcv is complete.” This explicitly overturns `D-32`'s assumed placement of WP-10 inside the pre-completion sequence without lifting active WP-10 gates `D-09` and `O-04` or deciding `O-20`. WP-11's published sequence and this plan both make WP-10 its prerequisite, so WP-11 cannot run while WP-10 is deferred. The operator's later `D-105` clarification explicitly says the MCV is not complete and does not assign WP-11 to either side of the completion boundary. Its active gates `NAR-OP-001`–`NAR-OP-009` remain open. WP-0R through WP-9 are merged, but that fact is not a completion-readiness claim and does not resolve the sequence conflict, declare the MCV complete, assert `MYPA_CURRENT_PRODUCT_SCOPE_COMPLETE`, or authorize deployment. | Operator-directed; WP-10 deferred; WP-11 dependency-blocked; boundary unresolved |

| D-105 | **Canonical version 2.3 is re-mirrored; Apple Mail, Calendar & Contacts yields provisional WP-12 with planning reserved to the operator** | `REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z` revised 17 of the canonical package's 21 numbered artifacts in place, preserved all 21 Drive identities and parent bindings, and took the package from 2.2 to 2.3. The publisher labels the Native Apple Personal Data Capture Bridge as conditional MCV scope and calls its sequence WP-12. Authority evidence is layered rather than identical: the numbered canonical artifacts carry their own implementation-not-granted blocks; the disposition denies implementation, live access, source mutation, deployment, production, and risk acceptance; the readback asserts only that implementation authority was not granted; and the publication and roundtrip receipts carry the fuller denial list covering live personal data, TCC/credential mutation, source mutation, deployment/watchers, production activation, external-model disclosure, destructive retention, and risk acceptance. The operator then clarified that the MCV is explicitly not complete and that WP-12 is provisional after WP-10 and WP-11; separate operator authorization is required before WP-12 implementation planning. The operator assigned WP-12 no pre-MCV or post-MCV disposition. Because `D-104` still defers WP-10 until completion and WP-11 depends on WP-10, the resulting completion-boundary conflict is recorded rather than resolved by inference. Nothing in WP-12 is planned, implemented, or authorized. | Historical state, superseded by the later direct authorization in `D-106`; retained as provenance |
| D-106 | **WP-12 is promoted ahead of WP-10/WP-11 for bounded implementation before MCV completion** | Direct operator authorization `AUTH-WP12-20260804-OPERATOR-001` supersedes only WP-12's provisional sequencing and implementation hold. WP-10 remains deferred by `D-104`; WP-11 remains dependency-blocked on WP-10. WP-12 executes in reviewed slice order A, B, D, C, E, F, G, H against the exact 48-row `NAPDCB-AC-*` map. The authority permits repository planning and synthetic implementation but not live Apple or personal-data access, TCC/credential/entitlement changes, signing/notarization, installation or watcher activation, external-model disclosure, source mutation, destructive retention, deployment/production, or risk acceptance. Slice A freezes the map and protocol-v1 source boundary but discharges no final acceptance criterion. | Operator-directed; WP-12 active before MCV completion; WP-10/WP-11 remain deferred |
| D-107 | **After independently verified MCV completion, a fresh orchestrator owns a comprehensive full-MVP campaign** | Direct operator instruction establishes a future handoff, not present implementation scope. After MCV completion has been independently verified, a fresh orchestration context must define a comprehensive MVP `CAMPAIGN-BRIEF` and execute the full MVP, explicitly including WP-10 and WP-11. Until that condition is met, this row does not start MVP, reactivate either package, declare MCV complete, authorize deployment, resolve their open product/operator gates, or relax `AGENTS.md` section 8.2. | Durable future handoff; condition not yet met; no current MVP execution authority |

**Identifier reservation: `D-106` and `D-107` are not available, and the two
corrections dated 2026-08-08 therefore mint no new row.** Parsed structurally at
`8dd4ef6` — every line whose stripped form begins `|`, outer pipes stripped,
split on `|`, first cell stripped of backticks and asterisks, kept when it
matches `^D-\d+$` — this table holds **105 rows, 105 distinct identifiers,
`D-1` through `D-105` with no gaps and no duplicates**. The next free number
looks like `D-106`. It is not free. The same parse over
`docs/plans/mcv-completion-plan.md` on `recovery/pre-20260805-utc-rollback-c9fb513`
and on the `custody/wp12-local-main-88e8d81` tag returns **107 rows through
`D-107`**: those two identifiers were minted on the WP-12 line that was removed
from `main` by a non-fast-forward move and preserved on those refs rather than
deleted. Reusing the numbers here would give one identifier two different
meanings across refs that are both retained on purpose, which is the failure the
register exists to prevent — and it would do so silently, because nothing parses
across refs. So the `D-24` and `D-102` corrections above are dated in place
against the claim they correct, in the `D-78`/`D-81` shape, and carry no new
identifier. **This is a deliberate departure from the register's usual habit of
naming a correcting decision, and the reason is recorded here rather than left
for a reader to infer.** Whether `D-106` and `D-107` are ever readmitted to
`main`, and under which meaning, is a question about the WP-12 line and is not
resolved by this note.

**`D-36`'s citation shipped ahead of its row, and that is recorded rather than
quietly closed.** WP-4B2b added the section 6 sentence attributing the second
split of WP-4B to `D-36`, but added no `D-36` row. Recomputed at `77ed807`, the
identifier appeared exactly once in this file — in that citation — and in no
commit before it, so the gap opened at `77ed807` (PR #29) itself and the register
cited a decision it did not carry from that merge until WP-0R2 closed it. WP-0R2 found it, declined
to invent the row, and the orchestrator supplied the authoritative text, which is
the row above. This is the `D-16` defect class: a claim routed to a source that
does not hold it. The campaign records the sequence because a register that
silently backfills a missing row teaches a reader nothing about how the gap
opened.

**What `D-54`'s four items resolved to.** They are recorded here because two of
the four were decided against the instruction that raised them, and a decision
that only exists in a worker's report is not a decision a later reader can find.

1. `README.md`'s two false claims — that nothing calls `register_source` and that
   no extraction executor is wired to the worker — are **corrected in place, with
   the superseded wording quoted** rather than deleted, because both were true of
   every commit before WP-4B3. A third clause in the same file, in the paragraph
   beginning "Accordingly", said the slice "still does not run end to end,
   because nothing registers a source for it to read". It was false for the same
   reason and was named by nothing; it is corrected too. Fixing two of three
   would have been the proven-in-one-shape-and-not-its-neighbours defect at the
   scale of a single file.
2. [`../architecture/module-boundaries.md`](../architecture/module-boundaries.md)'s
   "`apps/cli/` now holds two programs" is **corrected to three**, and so is the
   directory tree six paragraphs above it, which named the same two. The
   instruction named only the prose.
3. `all_sources` **was landed** in `infrastructure/persistence/registry.py` and
   the workaround it replaced was reverted. The operator-command guard's
   permitted-name allowlist had been widened to admit the `sources` **table
   declaration** so that the listing could select from it — and a `Table` is a
   write surface, since `insert()` and `update()` reach through it exactly as
   `select()` does. An allowlist whose purpose is to keep an operator command
   narrow had therefore been widened by a write in order to permit a read. The
   reader closes that; the allowlist is back to four functions and no table.
4. `tests/jobs/README.md` was **not** added, and the reason is that the premise
   for adding it is false. The claim was that every other test directory has one.
   Measured: `tests/architecture/` has none either, and has had none since it was
   created — all eighteen of the existing test-directory READMEs are byte
   identical and were created by one commit, `d534502` "chore: scaffold
   recommended repository architecture", on 2026-07-30. The file marks a
   directory that existed at that scaffold commit; `tests/architecture/` and
   `tests/jobs/` were both created later by implementation work and neither has
   one. Adding one would also assert `Status: SCAFFOLD_ONLY` and "Directory
   presence does not authorize runtime implementation" over a directory holding a
   working executor test suite, which is a false claim rather than a missing
   file.

## 14. Consolidated open decisions returned to the operator

Forty-one decisions are open: nine from the Phase 00 ledger, seventeen from Quick
Capture, and fifteen from Relationship Intelligence. Twenty-two of them block
a work package in section 12 — seven on ordinary grounds and fifteen more that
are reserved to the operator by policy and block for that reason. The remaining
nineteen do not block anything yet and are listed so they are not rediscovered
later as surprises.

**`O-19` was here until WP-7 and is recorded rather than deleted**, because it
was blocking in every earlier commit and a reader of one of those should be able
to find out when it stopped. It asked whether "save without AI processing"
appears in MVP, and ruled that the answer must be a stored processing-policy
value or nothing at all. `D-95` closes it by pointing at the mechanism that
already answers it: `knowledge.capture_versions.processing_policy` exists, WP-6
built it, and WP-7 adds no member to it — a value that changes no behaviour and
is distinguishable from `local_only` by nothing is what `AGENTS.md` section 2
bars. What WP-7 owed instead was `P-01` reading that snapshot and branching on
it, which it does.

**Six overlapping decisions were here until WP-8 and are recorded rather than
deleted.** `D-101` closes `O-15` through `O-18` plus `RI-OD-011` and
`RI-OD-012` as one fail-closed review policy. Their former blocking rows are
removed below so the open-decision counts remain statements about open decisions,
not a historical ledger; this paragraph and `D-101` preserve the history.

These numbers are derived from the three tables below, not maintained beside
them. `tests/architecture/test_open_decision_counts.py` recomputes them from this file
and fails if this paragraph and those tables disagree.

That test exists because this paragraph was wrong. It previously read "Forty-one
decisions are open … Sixteen of them block." Both figures were incorrect: at that
moment the tables held forty-six distinct IDs with no duplicates between them, and
the second table is itself headed *Blocking*, so counting only the first understated
the blocking total by thirteen. The correction is recorded as `D-21`, and the
mechanism was corrected alongside the number because a hand-maintained count
goes stale silently and this one already had.

The figures above have since moved twice, which is the mechanism working rather
than failing. Section 16 added two operator decisions to the reserved table, and
`D-24` moved `P00-OD-011` out of the blocking table into the non-blocking group.
Both times the paragraph was recomputed from the tables rather than edited to
taste, and the second move was found by the test rather than remembered. The
forty-six is left in the previous paragraph as the historical figure it is.

Nothing below is decided here. Where a recommendation exists it is named as a
recommendation.

**The third group is prose, deliberately, and that is not the `D-16`/`D-60`
defect.** The first two groups are tables whose first column is the ID; "Not
blocking any planned package" is a paragraph, and
`tests/architecture/test_open_decision_counts.py` reads **both** forms and says
so in its own docstring. A first-cell parse of this file therefore returns no row
for the nineteen IDs named only there, and that is the structure working rather
than a citation with nothing behind it. Recorded because the appearance is
convincing and the reading is prefix-dependent: looking at the `O-` family alone
shows seven orphans and reads like a finding, while a family-blind parse of the
same paragraph shows **nineteen** — seven `O-`, five `P00-OD-`, seven `RI-OD-` —
which is exactly the "remaining nineteen" the paragraph above counts. Every one
of the nineteen resolves in its own ledger: the seven `O-` at
[`../specs/quick-capture/21_RISKS_MITIGATIONS_AND_OPEN_OPERATOR_DECISIONS.md`](../specs/quick-capture/21_RISKS_MITIGATIONS_AND_OPEN_OPERATOR_DECISIONS.md),
which carries `O-01` through `O-20` as headed subsections. Verified 2026-08-03 by
first-cell parse rather than by `grep`.

### Blocking — a work package in section 12 cannot pass acceptance without these

| ID | Source | Question | Blocks |
|---|---|---|---|
| `P00-OD-003` | Phase 00 ledger | Which reviewed PDF extractor, if any | WP-5 acceptance; PDF stays `unsupported` until then, which is specified behavior, not a defect |
| `P00-OD-010` | Phase 00 ledger | HTTP/MCP authentication mechanism | WP-4 beyond loopback. WP-4 can be built and tested locally with a local principal; it cannot be exposed |
| `O-01` | Quick Capture | Final capability, action, and mode names | WP-6 — capability names enter `domain/identity/operation.py` and the public `v1` contract, where renaming later is a breaking change |
| `O-09` | Quick Capture | Private-note default classification | WP-6. Recommendation: `private_local`, no training, no lock-screen content |
| `O-14` | Quick Capture | Editing semantics | WP-6. ADR-003 assumes immutable versions with append-only edits; confirming `O-14` ratifies that assumption |
| `RI-OD-004` | Relationship Intelligence | First personal source set | WP-9. `D-13` builds against fixtures precisely so this can stay open |
| `RI-OD-005` | Relationship Intelligence | Authentication posture for relationship data | WP-9 beyond fixtures |

### Blocking, and reserved to the operator by policy

| ID | Source | Question |
|---|---|---|
| `P00-OD-006` | Phase 00 ledger | Whether any cloud model may receive `my-pa` content. Governs `D-14`; while it is open there is no model-assisted extraction |
| `P00-OD-009` | Phase 00 ledger | Whether a live NAS or GoodNotes root is authorized, by exact path |
| `O-03` | Quick Capture | Priority of Quick Capture against the active objective. Partly answered by the reprioritisation; the ordering question in `D-12` is what remains |
| `O-04` | Quick Capture | When to lift the frontend hold — and, per `D-15`, whether backend work on a held feature needs it lifted at all |
| `O-08` | Quick Capture | Cloud-model eligibility for capture content. Duplicates `P00-OD-006` for this feature |
| `O-10` | Quick Capture | Retention and deletion: active retention, archive duration, draft expiry, hard-delete authority, audit retention |
| `O-20` | Quick Capture | Device-local encryption posture, and whether restricted classifications may be captured offline |
| `RI-OD-002` | Relationship Intelligence | When Relationship Intelligence enters implementation relative to the MCV. Overlaps `D-12` |
| `RI-OD-003` | Relationship Intelligence | Whether and when to lift the `D-09` frontend hold. Duplicates `O-04` |
| `RI-OD-006` | Relationship Intelligence | Private-note classification and reveal behavior. Overlaps `O-09` |
| `RI-OD-007` | Relationship Intelligence | Cloud eligibility for relationship briefings. Overlaps `P00-OD-006` |
| `RI-OD-009` | Relationship Intelligence | Retention and deletion for captures and private notes. Overlaps `O-10` |
| `RI-OD-016` | Relationship Intelligence | External-action scope after the read-only stages. Overlaps `O-17` |
| `O-21` | Quick Capture — RQC amendment | Which credential issues the capture-only device/client grant, and who issues it. The revised canonical package requires "an authenticated HTTPS endpoint with a capture-only device/client grant" in the MCV, but `AGENTS.md` section 5 reserves credential creation to the operator and the package's own `MYPA-RQC-D-008` restates that MCV inclusion "does not itself authorize … credentials". `D-30` bounds the work to a local capture-only principal on loopback so the package can pass acceptance without it |
| `O-22` | Quick Capture — RQC amendment | Whether the capture endpoint may leave loopback, and under what authentication. This presses directly on `P00-OD-010`, which asks the same question for the gateway generally; this narrows it to an endpoint the revised MCV now requires by name, so resolving `P00-OD-010` resolves this one and not the reverse. Ingress activation is reserved by `AGENTS.md` section 5 and by `MYPA-RQC-D-008`. `D-30` builds the endpoint behind the gateway boundary and does not expose it |

The last two rows are opened by this plan rather than inherited from a ledger.
The 2026-08-02 Remote Quick Capture revision added the material that raises them
but did **not** revise `15_OPEN_OPERATOR_DECISIONS.md`, so the package that
created the questions tracks neither. Section 16 records that gap; these rows are
where it stops being untracked. They are placed here rather than in the ordinary
blocking table for the reason `P00-OD-006` is: the package is bounded so it can
pass acceptance without them, and what they block is the operator act on the far
side of that boundary.

### Not blocking any planned package

`RI-OD-001` public feature name, which ratification moved here out of the
blocking table. The ratified decision log records `CR-D-007` — "RI is integrated
domain; PRIE historical" — as `Canonical`, and the ratified executive
description makes Relationship Intelligence "the people-centered
continuity domain inside my-pa", with `PRIE` retained only for provenance. That
settles the name entering `v1` contracts, which was the whole of its claim on
WP-9. What is left is the final UI label set, tracked by the canonical package as
`OP-02` and gated on UI freeze: frontend scope, already held by `D-09`, and not a
contract input. See `D-20`, which also records that the ratified package
treats Relationships as a Library collection rather than a top-level
destination — a point the earlier `D-18` framing got wrong.

`P00-OD-011` numeric resource limits, which `D-24` moved here out of the blocking
table. It previously blocked WP-4 on the grounds that `capabilities.get`
publishes effective maxima and the values were Phase-01 placeholders. `D-24`
derives the published maximum from validated `MY_PA_` configuration rather than
from a module constant, keeping the current `PHASE_01_LIMITS` values as the
defaults. That removes the block without answering the question: the operator may
still set different numbers, but doing so is a configuration change rather than a
code change, which is precisely the outcome the decision was shaped to produce.
What is left is not blocking anything.

`P00-OD-004` contract freeze and `P00-OD-012` `pg_trgm` necessity, both
`OPEN_REVIEW`. `P00-OD-013` audit retention and `P00-OD-014` parser isolation,
both deferred to their phase gates. `O-02` formal product principle, `O-05`
initial platforms, `O-06` offline MVP, `O-07` PWA versus native wrapper, `O-11`
notifications, `O-12` audio scope, `O-13` attachments — every one of these is
frontend, platform, or media scope that section 12 does not plan. `RI-OD-008`
public research, `RI-OD-010` offline posture, `RI-OD-013` importance labels,
`RI-OD-014` device matrix, `RI-OD-015` voice capture, `RI-OD-017` independent
usability and privacy review gate before release.

### Six questions this plan raises that no ledger contains

Ratification on 2026-08-02 answered the third of these outright, changed the
footing of the first and the fourth, and added a fifth. The answered one is kept
and marked rather than deleted, because a list that quietly drops the question it
resolved teaches a reader nothing about how it was resolved. The sixth was opened
on 2026-08-08 by a gap #52 disclosed and deliberately left, and it is a contract
change rather than a repair, which is why it is a question here rather than work
in a package.

1. **The MCV completion declaration.** *Still reserved to the operator.* `AGENTS.md` section 1
   said the MCV ran "through August 2, 2026." When this was written that was
   tomorrow; it is now today, and section 12 plans six work packages that plainly
   do not fit behind it. `AGENTS.md` section 1 has since been amended to say the
   date passed and that the MCV runs until the operator declares it complete,
   which is honest but is not a date. On 2026-08-04 the operator directed that
   WP-10 be deferred until after MCV completion. The operator then explicitly
   confirmed the MCV is not complete and later authorized WP-12 ahead of
   deferred WP-10/WP-11 (`D-106`). WP-11 still depends on deferred WP-10.
   WP-0R through WP-9 being merged is not evidence that the repository is ready
   for a completion decision, and WP-12 authorization is not a completion
   declaration. No date or terminal disposition is inferred. `D-107` governs
   only the later handoff: after independent verification of MCV completion, a
   fresh orchestrator defines and executes the comprehensive full-MVP campaign.

2. **Whether promoted scope is still MCV.** `AGENTS.md` section 1 describes the
   objective as "one complete, read-only vertical slice." Quick Capture is not
   read-only — that is the whole point of ADR-003 — so the sentence no longer
   describes the objective. The amendment names the promoted features
   explicitly and keeps "not a broad platform." If the operator intends the
   features as a *successor* objective rather than an enlarged current one, the
   framing should change again.

3. **Whether to ratify the canonical product direction.** **Answered on
   2026-08-02. No operator action remains.** This was described here as the
   largest unasked question and the only one that could invalidate section 12's
   shapes rather than merely reorder them. It was asked, and answered, and the
   answer invalidated nothing.

   The operator ratified `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006` by
   direct instruction on 2026-08-02, which supersedes `my-pa vNext` for current
   whole-product definition and preserves it as source history. The instrument is
   the instruction, not the package's own self-declared status — `D-19` records
   why that distinction matters, and section 15 records the reconciliation in
   full. Only this item is answered; the 58 operator decisions inside the
   package — `OP-01` through `OP-30`, `MCP-OP-001` through `MCP-OP-009`,
   `NAR-OP-001` through `NAR-OP-009`, and `NAPDCB-OP-001` through
   `NAPDCB-OP-010` — remain open and are not tracked here. The figure was 39
   before the 2026-08-02 Native Apple Reminders revision, 48 after it added nine,
   and 58 after the 2026-08-04 Apple Mail, Calendar & Contacts revision added ten;
   see the subsection below the five questions.

   The part worth keeping is why the fear did not materialise. The concern was
   that ratification would make a broad vision's acceptance criteria binding and
   re-shape WP-8 and WP-9. Instead the ratified package sequences *itself* behind
   this plan: its `OP-05` recommends completing the MCV before an explicit
   transition, and its roadmap step `R10.1` names finishing repository WP-4 and
   WP-5 as the first move. It also carries `implementation_authority:
   NOT_GRANTED` on every artifact. So the conservative path section 12 took —
   build only what was promoted, name the object mapping without creating the
   abstractions — turned out to be the path the ratified direction asks for.

   That is a good outcome and a slightly lucky one. Had ratification gone the
   other way, this plan would have been reconciled against it rather than
   confirmed by it, which is why section 15 records the comparison explicitly
   instead of asserting agreement.

4. **The GoodNotes and frontend workstreams (`D-04`).** Both were deferred as
   dependency-blocked on B, C, and D. WP-4 removes that dependency. `D-09`
   independently holds the frontend, so nothing changes there without an
   operator act. GoodNotes has no such second hold — only `P00-OD-009`, which
   gates its source root.

   Two things the operator should know. `D-04`'s argument for GoodNotes lapses
   when WP-4 lands, leaving only `P00-OD-009` between it and being plannable.
   And GoodNotes is further along than `D-04` implies: beyond the v0.1 feature
   description it now has a full implementation specification,
   `SPEC-MYPA-GOODNOTES-KNOWLEDGE-INGESTION-v1.0` (Drive
   `111zA3Osva_tdi7oW-8TIBcC0uS9_cQ6VZ-w3pqmGhCA`), and the ratified canonical
   definition strengthens this further: GoodNotes is now named in the ratified
   MVP as a required "GoodNotes proof" capability — one synthetic region, no live
   NAS — and carries its own roadmap stage `R6` and its own operator decision
   `OP-07`. It is not planned here — the operator promoted two features and
   GoodNotes was not one of them — but it is
   closer to plannable than the register currently suggests, and saying so is
   cheaper than having it surface as a surprise.

5. **A third feature package arrived with ratification, and nobody has been
   asked about it.** *New on 2026-08-02.* The ratified package incorporates the
   **Frontier NAS MCP Connector** (`MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086`,
   Drive folder `1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa`) as canonical product scope:
   a governed external surface letting authorized frontier clients — ChatGPT,
   Claude, Grok — invoke the same use cases, policy decisions, and disclosure
   envelopes as first-party surfaces.

   This is the single largest scope addition ratification made, and it is worth
   being precise about what it does and does not do. It is canonical scope, and
   it is explicitly **not** inserted into the active repository MCV: the package
   says so directly, its `MCP-OP-001` recommends finishing the WP-4/WP-5 sequence
   first, and its own acceptance crosswalk marks most of its criteria
   `NOT IMPLEMENTED`. It carries nine operator decisions of its own,
   `MCP-OP-001` through `MCP-OP-009`, none of which is answered here and none of
   which blocks any package in section 12. Those nine are deliberately *not*
   added to the counts above, which cover the three ledgers this plan tracks;
   folding a package's internal decisions into this plan's totals would misstate
   what this plan is accountable for.

   `D-22` records why it is indexed by reference rather than mirrored. What the
   operator should know is that the connector's arrival does not change WP-4 —
   if anything it raises the value of WP-4's transport-parity work, since a thin
   MCP adapter over stable application contracts is exactly what the connector
   assumes. The decision that will eventually be needed is `MCP-OP-001`:
   whether the connector is sequenced after the MCV, as its own package
   recommends, or reprioritised ahead of it. Nothing needs deciding today.

6. **`_Captures.search` lets a `CaptureSearchInternalError` reach the application
   past the port's vocabulary, and closing it is a contract change.** *Opened
   2026-08-08.* #52 found this on the way to something else, deliberately did not
   fix it, and recorded it at the site in
   `src/my_pa/infrastructure/persistence/unit_of_work.py` — pinned by a test read
   from the `except` clauses themselves, so closing the gap without removing the
   note reddens rather than leaving a false sentence behind. That is disclosure
   done well, and it is why this entry is a question rather than a defect
   awaiting a worker.

   The reason it is listed here rather than fixed is that the two available
   repairs are not equivalent, and neither is the orchestrator's to choose.
   **Either** the port's error vocabulary widens to admit the internal-error
   case, which changes what every caller of the capture port must handle;
   **or** the adapter translates the internal error into an existing member of
   the vocabulary, which is the narrower change but discards the distinction
   between "the search plane failed" and whatever member it is folded into. The
   first is a contract change in the sense `P00-OD-004` uses for the `eligible`
   field; the second is a defect-laundering risk of exactly the kind section 10
   of `AGENTS.md` forbids, and it would have to be argued rather than assumed
   safe. Nothing in the repository establishes which the operator wants.

   No `D-` identifier is minted for it — `D-106` and `D-107` are reserved, for
   the reason recorded under section 13's decision table — and no ledger this
   plan tracks contains a question it fits, which is why it is here. It blocks no
   package in section 12 and is deliberately **not** added to the counts above,
   on the same grounds as the connector's nine: those counts cover the three
   ledgers this plan tracks, and this is not in one of them. It is direction-
   neutral: the gap and both repairs are identical under either product line.

### Nine more package decisions arrived with the v2.2 revision

The 2026-08-02 Native Apple Reminders revision added `NAR-OP-001` through
`NAR-OP-009` to the package's own
[`15_OPEN_OPERATOR_DECISIONS.md`](../specs/canonical-product-definition/15_OPEN_OPERATOR_DECISIONS.md),
which is where they are tracked. They are named here and not tabulated here, for
the same reason `MCP-OP-001` through `MCP-OP-009` are: they belong to the
package, the package tracks them, and reproducing the table in this plan would
create a second copy that drifts. They are excluded from the counts above on the
same grounds — those counts cover the three ledgers this plan is accountable
for, and `tests/architecture/test_open_decision_counts.py` reads only
`P00-OD-*`, `RI-OD-*`, and `O-nn`.

What the operator should know without opening the file: all nine are open, and
between them they gate every path into `WP-11`. `NAR-OP-007` is the
code-signing and notarization identity, `NAR-OP-008` is the EventKit permission
grant and live reminder access, `NAR-OP-001` is the reminders-only credential
and grant issuance, and `NAR-OP-009` is production activation and residual-risk
acceptance — four operator-only acts under `AGENTS.md` section 5. The other
five, `NAR-OP-002` list binding, `NAR-OP-003` undated reminder policy,
`NAR-OP-004` external edit policy, `NAR-OP-005` cancellation withdrawal, and
`NAR-OP-006` minimum macOS and hardware, are scope and behaviour questions that
`WP-11`'s own `NAR-00` policy amendment would otherwise have to assume. `D-39`
records that none of them is answered and that nothing in `WP-11` is built.

Unlike the RQC revision, which `D-33` records as having created operator
questions while revising no decisions artifact — the gap this plan carries as
`O-21` and `O-22` — the v2.2 revision **did** revise
`15_OPEN_OPERATOR_DECISIONS.md`. So this plan opens no row of its own for
Native Apple Reminders: the package that created the questions tracks them.

## 15. Reconciliation against the ratified canonical product definition

### 2026-08-12 remediation authority note

The operator has reprioritized the current remediation objective to include the
frontend and managed-document implementation necessary to close the six
pilot-readiness blockers. That objective-specific instruction is implementation
authority for this remediation only; it does not amend repository policy and it
does not make `PLAN_APPROVED` an authorization to amend `AGENTS.md`.

The resulting inconsistency with the older policy statements that defer
frontend and managed-document work is deliberately recorded in this plan, the
remediation pull request, and the final-state report. `AGENTS.md` remains
unchanged for later operator correction unless the operator separately and
explicitly authorizes amendment of that policy. All other policy boundaries,
including live-data, deployment, destructive-action, credential, and
independent-review gates, continue to apply.

On 2026-08-02 the operator ratified `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`.
Section 14 item 3 anticipated that this could invalidate section 12's shapes. It
did not. This section is the evidence for that claim rather than the assertion of
it, because "the plan already agreed with it" is exactly the conclusion a
reconciliation is most likely to reach lazily.

The package is mirrored byte-exact at [`../specs/canonical-product-definition/`](../specs/canonical-product-definition/00_README.md);
its provenance, verification strength, and two disclosed defects are recorded in
[`../specs/README.md`](../specs/README.md).

### The instrument, and what it is not

Ratification rests on a **direct operator instruction of 2026-08-02**, recorded
at `D-19`. It does not rest on anything inside the package, and the distinction
is load-bearing.

The package never claims to be ratified. It carries a self-declared front-matter
status, `CURRENT_CANONICAL_PRODUCT_DEFINITION`; its publication receipt grants
`NOT_GRANTED` on implementation, deployment, production activation and risk
acceptance; and `15_OPEN_OPERATOR_DECISIONS.md` closes with "This package
performs none." A newer package asserting a stronger status about itself is
exactly the evidence `D-17` refused for the predecessor, and treating it as
sufficient here would have quietly lowered the standard this register set one
pull request earlier.

Two consequences follow. First, the 58 operator decisions inside the package
remain open — `OP-01` through `OP-30`, the connector's `MCP-OP-001` through
`MCP-OP-009`, Native Apple Reminders' `NAR-OP-001` through `NAR-OP-009`, and
Apple Mail, Calendar & Contacts' `NAPDCB-OP-001` through `NAPDCB-OP-010`.
Ratifying the definition did not answer any of them, and `OP-05` in particular
still carries only a recommended default. Section 14's counts exclude all 58,
for the reason given in item 5: they belong to the package, not to the three
ledgers this plan is accountable for.
Second, the only question section 14 marks answered is its own item 3, the
ratification question itself. Nothing else was removed from the operator's queue.

### What ratification binds, and what it does not

| Question | Answer | Evidence |
|---|---|---|
| Does it grant implementation authority? | No | `implementation_authority: NOT_GRANTED` in the YAML front matter of all 20 markdown artifacts, and under `authority` in the manifest, which is JSON and has no front matter; the publication receipt records `NOT_GRANTED` for implementation, deployment, production activation and risk acceptance |
| Does it outrank repository policy? | No | `AGENTS.md` section 1 places indexed Workspace publications at rank 4, below accepted specifications, ADRs, and policy at rank 3 |
| Does it change the active objective? | No | Its `OP-05` recommends "Complete MCV then explicit transition"; its `R10.1` names finishing repository WP-4 and WP-5 first |
| Does it supersede the two feature specifications? | No | "Owning Quick Capture, RI, and GoodNotes specs remain current where more detailed and not explicitly reconciled" |
| Does it lift the frontend hold? | No | Its `OP-06` states the hold "Remains until expressly lifted", matching `D-09` |
| Does it add scope? | Yes, one package | The Frontier NAS MCP Connector, canonical but explicitly outside the active MCV — section 14 item 5, `D-22` |

### Stage mapping

The canonical roadmap and this plan's work packages run in the same order, but
they are **not the same scope**. Every "planned" row below is a subset of the
canonical stage it sits under, because the canonical stages carry frontend and
continuity surface that section 12 excludes. Reading this table as equivalence
would overstate what the work packages deliver.

| Canonical stage | This plan | Status |
|---|---|---|
| `R0` complete active read-only MCV | WP-4 + WP-5 | Next, and unchanged by ratification. The closest to a true match |
| `R1` product contracts / frontend proof | Not planned | **Split.** Its frontend half is held by `D-09` and `OP-06`; its contracts half — canonical object, state, error, span, region, Situation, Frame, Trace, Review and Receipt contracts — is simply unplanned, and no hold explains that |
| `R2` product-owned Capture source | WP-6 | **Subset.** `R2` also requires responsive PWA, global and contextual launch, and capture modes; WP-6 is frontend-free and builds none of them |
| `R4` proposal / review / promotion | WP-7 + WP-8 | **Subset.** `D-14` excludes the model-assisted extraction stages `R4` assumes |
| `R5` relationship and project continuity | WP-9 | **Subset**, and the largest gap. `R5` adds commitments, briefings, Situations, Frame, Trace and Today/Pulse gates; WP-9 builds identity and read-only profiles over fixtures per `D-13` |
| `R3` offline Capture, `R6`–`R9` | Not planned | Beyond promoted scope |
| `R10` Frontier connector | Not planned | `D-22`; `MCP-OP-001` sequences it after `R0` |

### Five divergences, recorded rather than smoothed over

Agreement was close but not total. These are the places the two documents do not
say the same thing.

1. **The canonical MVP is deliberately larger than the repository MCV.** The
   canonical `12_MVP_DEFINITION.md` requires a GoodNotes proof, offline Capture,
   Situations, Frames, and a five-destination shell. The repository MCV requires
   none of these. This is not a conflict — the canonical document states in its
   own objective that it "is not the active repository MCV and is not
   implementation authority" — but the two must never be read as the same list.
   **Resolution: the repository MCV governs what gets built; the canonical MVP
   governs what the product eventually means.** No plan change.

2. **The sequence table understates `D-12`.** The table at section 12 lists WP-6
   as depending on WP-4 alone, while `D-12` states the read-only slice — WP-4
   *and* WP-5 — is finished before either feature is built. The canonical `R0`
   agrees with `D-12`, not with the table. **Resolution: `D-12` and canonical
   `R0` govern. WP-6 begins after WP-5, not after WP-4.** The table is corrected
   below.

3. **`RI-OD-001` was carried as blocking after it had been answered.** The
   ratified `CR-D-007` settles the domain name; only the UI label set remains,
   as `OP-02`, and that is frontend. **Resolution: reclassified — `D-20`.**

4. **The canonical package binds a stale head in one place.** Its `00_README.md`
   body cites `b48b1b1`, two merges behind the `9096fa4` its own front matter and
   manifest bind. **Resolution: the front matter and manifest binding is
   authoritative; the discrepancy is disclosed in `../specs/README.md` and
   mirrored as authored rather than silently corrected.**

5. **The section 12 object-model mapping did not survive the change of target
   document, and the first draft of this reconciliation missed it.** The mapping
   table was written against `my-pa vNext`. The first version of this change
   relabelled its column header and left every target unchanged, which asserted
   agreement that had not been checked — and did so in the one passage the same
   change had just described as consequential. Independent review caught it.

   Re-derived against `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`, three claims
   were false and one was misdirected. `Entity` does not exist in the ratified
   model; `Person` and `Organization` are first-class. `Capture` and
   `CaptureVersion` are defined under those exact names rather than as a generic
   "Source Record". `ReviewCase`, `Receipt`, `Conversation` and `Affiliation` are
   likewise identity mappings. And the Assertion trust ladder the table gave WP-7
   as an instruction — Confirmed, Strongly Supported, Probable, Possible,
   Unverified — appears nowhere in the ratified package.

   **Resolution: the table is re-derived in section 12, the corrections are
   stated in it rather than only here, and WP-7's state vocabulary is rebound to
   the ratified `Proposal` and `Assertion` state sets.** This is recorded as a
   divergence rather than quietly fixed because it is the exact failure this
   section warns about in its opening paragraph — reaching "the plan already
   agreed with it" without checking — and the warning is worth less if the
   instance is hidden.

### Correction to the section 12 sequence table

Per divergence 2, WP-6's dependency is corrected from WP-4 to WP-5. The original
row is left visible here rather than only in git history:

| WP | Objective | Depends on | Was | Frontend? |
|---|---|---|---|---|
| WP-6 | Capture domain, contracts, and durable persistence | **WP-5** | WP-4 | No |

Nothing else in that table changes.

### WP-4 as it now stands

Ratification did not change WP-4's objective, scope, or exclusions. It added two
acceptance criteria and confirmed the rest. The package definition at section 12
remains authoritative; this is the delta.

**Objective, in scope, and out of scope.** Unchanged. `P00-OD-010` still keeps
WP-4 at loopback, `P00-OD-003` still leaves PDF unsupported, and neither is
resolved by ratification.

**Added acceptance criteria.**

- `CPD-AC-01` **disclosure-envelope parity by field.** The canonical
  source-authority model and connector crosswalk row `MCP-AC-07` require scope,
  coverage, freshness, authority, and limitations to be disclosed identically
  across transports. `SPEC-AC-001` asserts transport parity generally; this
  narrows it to those five fields by name, so that a future MCP adapter inherits
  a proven envelope rather than reconstructing one.
- `CPD-AC-02` **`record_outcome` round-trip.** Carried forward from WP-3, not
  from ratification, and stated here because WP-4 is what builds on it. The
  extractor identity, extracted-at, and observed-at columns are written and read
  by nothing that asserts they survive the round trip. WP-4 pins them with an
  assertion before adding behavior on top.

**Confirmed unchanged.** `SPEC-AC-001` transport parity, `P05-SPEC-AC-002`
negative evidence through every transport, `MB-AC-002` layering, and the derived
capability manifest. The path-drift reconciliation between
`module-boundaries.md` section 3 and the actual tree stays WP-4's job.

**What WP-4 still may not do.** Network exposure beyond loopback, authentication
mechanism selection, any capture or relationship behavior, and any connector
work. Ratification widened none of these.

### Invalidation

This reconciliation binds `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`
version 2.1 at package folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`, verified
on 2026-08-02 against three independent in-package hash sources (21/21,
21/21, and 20/20 — the manifest does not hash itself),
against this plan at the commit that introduces this
section. A new package version, a revision to any mirrored artifact, or an
operator decision on `MCP-OP-001` invalidates the affected rows above and
requires re-reconciliation. It does not invalidate WP-4, whose acceptance
criteria are bound to repository tests rather than to the package.

**That clause fired on 2026-08-02.** Eight mirrored artifacts were revised in
place later the same day. Section 16 is the re-reconciliation it requires.

## 16. Reconciliation against the Remote Quick Capture revision

Section 15's invalidation clause names "a revision to any mirrored artifact" as a
condition requiring re-reconciliation. On 2026-08-02 at approximately 11:49–11:50Z
a second coordination roundtrip,
`REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`, revised eight of
the mirrored artifacts in place to fold **Remote Quick Capture** into the MCV.
This section is that re-reconciliation.

The thing worth saying first is how nearly this was missed. Every revised
artifact still declares `version: 2.1` — the same version section 15 bound — and
every one still names the *earlier* roundtrip in its `coordination_request_id`.
A reader checking the package's own version fields would have concluded that
nothing had changed. Only a hash comparison found it.

### What was re-mirrored, and how it was verified

Eight artifacts were refreshed from Drive folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`
with `rclone`, which retrieves stored raw bytes; the Drive-reported byte count of
each matched the retrieved bytes exactly, so no conversion or normalisation
occurred on the read path.

Each was checked twice, against two independent properties.

| Artifact | Drive ID | Bytes | Receipt hash | Prefix-append |
|---|---|---|---|---|
| `00_README.md` | `1NKw2gDkl_C5iFRQqh2mRDxmSZtoZpDgQ` | 6,137 | match | holds |
| `01_EXECUTIVE_PRODUCT_DESCRIPTION.md` | `15Umcs2JBMdFvxfRgNaA-P-Nc_iC3jDHV` | 16,241 | match | holds |
| `02_CANONICAL_PRODUCT_SYNTHESIS_SPECIFICATION.md` | `18l1S2iz5v_qgKZg8iVBAw47xvuHkbOjI` | 28,118 | match | holds |
| `08_DEVICE_AND_PLATFORM_STRATEGY.md` | `1Y7dDra-1NlN5sTrbg4yBrdEeo1F8B6HA` | 5,218 | match | holds |
| `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md` | `1xwJPqXyXR0UepmF_lmkrOspEX8Xosq_W` | 11,322 | match | holds |
| `12_MVP_DEFINITION.md` | `1CwOBwGsRuxF8O3tazLFK3UnW_I-5aSAq` | 8,524 | match | holds |
| `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md` | `12dfRuODgib94H53RWH1wWJcGUdDHYZ7Y` | 8,245 | match | holds |
| `14_DECISION_LOG.md` | `1ty-sjhwJ5q8-XpUqwKINh_WO61CXg7Um` | 6,447 | match | holds |

*Receipt hash* is the retrieved bytes re-hashed and compared against the SHA-256
published for that artifact in
`PUBLICATION-RECEIPT-REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z.json`:
eight of eight, zero mismatches, and the same eight verified again after being
written into this repository. The `CANONICAL-ARTIFACT-DISPOSITION` publishes the
same eight hashes, so the two agree — but they are not independent sources, since
the same roundtrip produced both.

*Prefix-append* is the independent property. Every revision is a pure byte-prefix
append: the new bytes begin with the previously mirrored bytes, verified against
the blobs committed at `ef08ddd`, with a new trailing section added. Nothing that
this repository had already reviewed was altered, so the reconciliation in section
15 remains valid for everything it covered and this section only has to account
for what was added.

The RQC control set lives in a new subfolder,
`RQC-INTEGRATION-20260802T114700Z` (`1t6fzDfHVrLQe6Wd2qjAtZ2ll--fYNPaF`). Three of
its members are mirrored beside the artifacts they attest, following the precedent
the MCP-integration control artifacts already set: the `CANONICAL-ARTIFACT-DISPOSITION`,
the `PUBLICATION-RECEIPT`, and the `COORDINATION-ROUNDTRIP-RECEIPT`. The
coordination request (`1yhkRgk6qcd2V-PWucS7WuRrbCO72FVAn`) and response
(`1qVhuUeeApFEGQQrq22lUzQwYhkQWyXN7`) are indexed by exact Drive ID and **not**
mirrored, following `D-22`: they are governance correspondence supporting no
citation in this repository, and mirroring material to support no citation is
scope `AGENTS.md` section 2 does not want. As with the MCP-integration control
artifacts, nothing in the package hashes these three, so they rest on the weaker
check of Drive-reported byte count matching the retrieved bytes — 3,356, 3,805,
and 786 respectively.

### What the revision changed in substance

**Remote Quick Capture is included in the MCV.** `12_MVP_DEFINITION.md` states it
directly and enumerates the slice; `13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md` moves
it into the MCV delivery sequence "rather than treated as a post-MCV enhancement."
`D-29` records what that does to this campaign's objective.

**The Stage 1 transport is an iOS Shortcut posting one text field to
`capture.create`.** One unrestricted text field is stated to be sufficient;
prefixes such as Person, Project, or Task are "optional accelerators only". The
service is transport-neutral, which is what lets the endpoint and the client be
sequenced separately — as `D-30` and `D-31` do.

**The durable-first contract.** Successful capture requires *one committed
transaction* containing the stable Capture and CaptureVersion identities, the
exact original content, a content hash, the authenticated principal, the
registered client or device, the idempotency result, the classification and
processing policy, an audit reference, a processing outbox job, and the receipt.
Classification, model availability, entity resolution, domain routing, search
indexing, and downstream promotion "cannot block or redefine capture success."
This is a strong and welcome constraint: it is the same shape ADR-003 already
gives Capture, and it rules out the failure mode where a capture is acknowledged
and then lost because enrichment failed.

**Captured content is untrusted data and never authorization.** It "is
source-authoritative for what the operator wrote and for nothing else… It cannot
send messages, delete records, modify external systems, execute shell or code,
expand source scope, invoke unrestricted MCP tools, approve proposals, or accept
risk." This agrees with `AGENTS.md` and with the threat model, and it is worth
noting that the package states it rather than leaving it to the repository.

**A PWA capture surface and offline-recovery path are named inside the MCV.**
MCV item 6 and roadmap step 5. This is the one part of the revision that touches
a standing operator instruction, and `D-32` records it as an assumption rather
than as a finding.

**SMS, iMessage, and hosted messaging are excluded from the MCV baseline.**
`MYPA-RQC-D-004`, with `01_EXECUTIVE_PRODUCT_DESCRIPTION.md` giving the reason:
meeting the no-incremental-service-charge constraint would otherwise require an
already-paid receiving number and a relay device.

### Six new canonical record types, and which package would build each

`09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md` gained six record types under a
*Remote Quick Capture object-model amendment* heading. The table below maps each
onto the work package that would build it, in the same manner as section 12's
mapping table.

**A caution carried forward from that table.** It was corrected once for treating
a bare name in `09`'s *Supporting records* list as a derivation it did not have.
The same discipline applies here, and the honest report is that this amendment is
*better* documented than that list: all six arrive with at least a one-clause
gloss, so none is a bare name. Two rows are nonetheless weaker than the rest, and
say so.

| Built here | Canonical record type | Package | Note |
|---|---|---|---|
| Capture submission envelope | `CaptureSubmission` | **WP-6** | **Defined, and the most fully specified of the six.** `09` enumerates its fields: request, correlation, idempotency, principal, registered client/device or relay, transport, capture method, trust state, transport message identifier, client timestamps, server receipt time, payload hash, admission result, CaptureVersion, and receipt. WP-6 already owns idempotency, receipt, and the durable-first transaction, so this is the record that transaction writes |
| Registered capture client | `RegisteredCaptureClient` | **WP-6** | **Defined.** Principal binding, device/client type, revocable credential reference, permitted capability, rate and size limits, creation, last-seen, and revocation state. Note that WP-6 builds the *record*, not a credential: `D-30` issues none, and the "revocable credential reference" is a reference to something `O-21` has not yet decided how to issue |
| Delivery attempt log | `CaptureDeliveryAttempt` | **WP-6** | **Defined, but thinly.** `09` gives one clause — "bounded delivery attempts and safe error classification" — and no fields, unlike `CaptureSubmission` beside it. What "bounded" and the error taxonomy mean is not specified, so WP-6 derives them from the existing job lease/retry work in WP-2 rather than from `09`. Stated because the row rests on a gloss, not on a specification |
| Classification and domain assignment | `CaptureClassification`, `CaptureDomainAssignment` | **WP-7** | **One shared gloss covering two names.** `09` defines them jointly — "versioned multi-label interpretation without relocating or overwriting the Capture" — and gives `CaptureDomainAssignment` nothing that distinguishes it from `CaptureClassification`. So this row claims the pair, not each separately, and the boundary between them was a WP-7 design question this plan did not answer. **`D-94` answers it**: `CaptureClassification` is evidence-bound and about the text — one row per `(version, scheme, scheme_version, label)`, each carrying its rule, that rule's version, and at least one span, and each therefore *citable*; `CaptureDomainAssignment` is interpretation and about placement — one row per `(version, domain, assignment_version)`, superseded rather than updated, carrying no span, because no phrase means "this belongs to the Riverside project". **Only the first is built in WP-7**: the second's only deterministic input is a launch-context link and `capture_context_links` is WP-8's, so it would be a permanently-empty table, which `../../AGENTS.md` section 2 bars. **This row assigns record types and not the `Classification` enum** — `my_pa.domain.common.classification.Classification` is a data-sensitivity vocabulary (`private_local`, `restricted_local`, `synthetic_test`), a different subject with a similar name, and WP-7 does not extend it (`D-92`). The *versioned* and *without relocating or overwriting* clauses are the load-bearing part and are unambiguous |
| Entity mention | `CaptureEntityMention` | **WP-7** | **Defined.** Exact surface text, evidence span, entity type, unresolved/candidate/resolved state, and later resolution lineage. This lands squarely on WP-7's evidence-span work. ~~The unresolved/candidate/resolved ladder is the same shape as the `Proposal` states section 12 already directs WP-7 to use.~~ **That clause is struck rather than deleted, so the correction is legible: it is wrong** (`D-93`). The ladder is canonical `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`'s **`Identity`** state set — `resolved`, `candidate`, `unresolved`, `merge_proposed`, `split_proposed`, `superseded` — and the `Proposal` set it names contains **neither `candidate` nor `resolved`**. The row's assignment survives the correction: `D-93` builds `CaptureEntityMention` restricted to the deterministic subset — document and project identifiers and URLs, each with a span and each always `unresolved`, since resolution is `P-07` and `P-07` is out of scope — and freezes `resolution_state_is_known` at that single value on the `D-78` precedent. **Exact surface text is deliberately not stored**: the span already points at it in the immutable version and re-derives on read, and a second copy would be a further place capture content sits and would make the mention's "exact" a claim about the copy |
| Correction | `CaptureCorrection` | **WP-8** | **Defined.** Four kinds — source-text successor version, derived-value correction, identity correction, routing correction — "each with immutable lineage". WP-8 owns promotion and correction, and immutable lineage is the same append-only discipline ADR-003 gives CaptureVersion |

No new package is created for these. The durable-first transaction, immutability,
idempotency, evidence spans, and proportional review they depend on are already
the acceptance criteria of WP-6 through WP-8, and a seventh package would
duplicate them.

### The new prohibition

`09` closes the amendment with a prohibition this repository should adopt without
qualification:

> No transport-specific note store, SMS memory, PRIE memory database, second
> knowledge store, or model-specific memory is permitted.

This agrees with `docs/architecture/module-boundaries.md` and with `D-20`'s
disposal of the separate-PRIE-database framing. It is stated here because it is
the kind of constraint that is cheap to hold now and expensive to retrofit: every
one of the six record types above hangs off the single Capture chain, and the
prohibition is what keeps a second transport from growing its own.

### Eight new package decisions

`14_DECISION_LOG.md` gained `MYPA-RQC-D-001` through `-008`: RQC incorporated into
the MCV as an extension of Quick Capture (`-001`); iOS Shortcut over authenticated
HTTPS as the initial transport (`-002`); the first-party PWA as the canonical
cross-platform, offline-recovery, history, correction, and Review client (`-003`);
SMS, hosted messaging APIs, additional cellular service, and iMessage relays
excluded from the MCV baseline (`-004`); capture success meaning durable source
persistence and receipt before enrichment (`-005`); message content as evidence
data granting no external-action, deletion, command, policy, or unrestricted-tool
authority (`-006`); and the governing feature package
`MYPA-REMOTE-QUICK-CAPTURE-FEATURE-PACKAGE-20260802-001`, Drive folder
`1lDSkTldgSkaRfJ3v9h-U10lCe-Lmwzsv` (`-007`), which is neither mirrored nor
examined here.

`-008` is the one to read closely, because it is the package limiting itself:

> `MYPA-RQC-D-008`: MCV product inclusion does not itself authorize repository
> mutation, credentials, ingress activation, deployment, production, or risk
> acceptance.

`D-30` and `D-31` are bounded by that sentence rather than in spite of it. When a
publication and this repository's policy agree on a limit, the limit is not in
tension with anything and there is no judgement call to make.

### Authority did not change

`implementation_authority: NOT_GRANTED` survives the revision. It is present in
the front matter of all eight revised artifacts — the exact field, unchanged —
and the RQC disposition JSON carries the same in its authority block:

```json
"authority": {
  "implementation": "NOT_GRANTED",
  "deployment": "NOT_GRANTED",
  "production": "NOT_GRANTED",
  "risk_acceptance": "NONE"
}
```

The publication receipt independently lists `blocked_actions` covering repository
mutation, credential creation, ingress activation, deployment, production
activation, and risk acceptance. So the three limits section 15 recorded all
survive: no implementation authority, rank 4 under `AGENTS.md` section 1, and the
package sequencing itself behind the repository's own work. What authorises the
work packages is the operator's objective, exactly as before — see `D-29`.

### Three defects in the revised package

Each was verified against the retrieved bytes and the Drive listing rather than
inherited from a report.

**1. Stale front matter.** All eight revised artifacts still carry `version: 2.1`
and `prior_version: 2.0` — unchanged across a revision that added between 967 and
2,620 bytes of new normative content each. All eight still carry
`coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-MCP-INTEGRATION-20260802T095600Z`,
naming the *earlier* roundtrip rather than the one that revised them. And all
eight bind `repository_head: 9096fa4fbe64ff1cdabc07e53a3e68c52efc8575`, which is
one commit behind `main` at `ef08ddd` — the commit that mirrored the package in
the first place. The disposition JSON repeats the same stale head.

The consequence is the part worth recording. **A version-field check would not
have detected this revision at all**, because no version field moved. Only a hash
check did. A future reader deciding how to test this mirror for staleness should
trust the hash and not the version, and should treat `version: 2.1` in these eight
files as naming the package generation rather than the artifact revision.

**2. Unpublished readback evidence.** The RQC control folder contains three
subfolders — `revised-artifact-readbacks/` (`1YG4ibwYuWGaieCYhKlxggtaDEfDZZeEh`),
`publication-controls/` (`1V_6x0gaxULtU69HCrRS0A1elAjocmZof`), and `noop/`
(`1EYk2P5VEu_HtbymbXicX8YmODAUtSYu4`) — and a recursive listing returns no members
in any of them. They are empty. Meanwhile the publication receipt asserts
`"canonical_specification_readback_observed": true`. The assertion may well be
true; what is missing is the evidence that would let anyone check it. The claim
and its support were published to the same folder in the same roundtrip, and only
the claim arrived.

One correction to how this defect has been described elsewhere: the assertion is
in the **publication receipt**, not in the coordination roundtrip receipt. The
roundtrip receipt carries only `index_registration_verified: true` and the
identity bindings. The distinction matters because the two artifacts are attested
by different steps.

**3. No readback-verification artifact.** The MCP-integration control set
published `READBACK-VERIFICATION-REQ-MYPA-CANONICAL-PRODUCT-MCP-INTEGRATION-20260802T095600Z.json`,
which is one of the three independent hash sources section 15 relied on. The RQC
set publishes no equivalent.

So it is worth being exact about what carries the mirror's integrity claim here,
because it is weaker than what section 15 had. Section 15 verified 21 artifacts
against three in-package hash sources. This section has **one** hash source —
the publication receipt, with the disposition repeating it rather than
corroborating it — plus **one independent structural property**, the
prefix-append check against the bytes committed at `ef08ddd`. The prefix-append
check is what does the real work: it is the only check here not derived from the
RQC roundtrip's own output, and it independently establishes that the previously
verified content was not altered. There is no independent readback, and this
section does not claim one.

### `15_OPEN_OPERATOR_DECISIONS.md` was not revised

It is not among the eight revised artifacts; its Drive modification time is
2026-08-02T10:07:51Z, from the earlier roundtrip. The revision therefore created
operator decisions that the package's own ledger does not track — and, before
this section, that no ledger tracked at all.

Two of them are concrete enough to name:

- **Which credential issues the capture-only device/client grant.** MCV item 4
  requires the grant; `RegisteredCaptureClient` carries a "revocable credential
  reference"; nothing says who issues it or how. Now tracked as `O-21`.
- **Whether the capture endpoint may leave loopback.** Roadmap step 3 puts an
  authenticated endpoint on the gateway boundary; roadmap step 8 defers
  activation to the operator; neither says what the intermediate state is. Now
  tracked as `O-22`.

`O-22` presses directly on the already-open **`P00-OD-010`**, the HTTP/MCP
authentication mechanism. They are not duplicates and the relationship runs one
way: `P00-OD-010` asks the general question for the gateway, `O-22` narrows it to
an endpoint the revised MCV now requires by name. Resolving `P00-OD-010` resolves
`O-22`; resolving `O-22` alone would leave the gateway question open. Both are in
section 14, whose counts are derived from its tables and enforced by
`tests/architecture/test_open_decision_counts.py`, so adding them moved the
headline figures automatically rather than by hand.

### Invalidation

This reconciliation binds the eight artifacts revised by
`REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`, at the SHA-256
values published in
`PUBLICATION-RECEIPT-REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z.json`
and re-verified here on 2026-08-02, against this plan at the commit that
introduces this section. Section 15 continues to bind everything it covered,
because the prefix-append property means none of it changed.

A further revision to any mirrored artifact invalidates the affected rows above
and requires re-reconciliation — and, given defect 1, **that condition must be
tested by hash rather than by version field**, since the last revision moved no
version. An operator decision on `D-32`, `O-21`, or `O-22` invalidates the rows
that depend on it. Publication of the missing readback evidence would strengthen
defects 2 and 3 rather than invalidate anything.

## 17. Reconciliation against canonical product definition version 2.3

The condition in sections 15 and 16 fired again on 2026-08-04.
`REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z`
revised the same canonical package in place from version 2.2 to 2.3. Direct raw
readback from canonical folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq` established
the exact revision:

- package `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, 21 numbered
  artifacts, 17 revised and 4 unchanged;
- 21 of 21 Drive IDs preserved, 21 of 21 parent bindings verified, and 21 of 21
  stored-raw-byte readbacks matching;
- manifest `18_PACKAGE_SOURCE_MANIFEST.json`, Drive ID
  `1xxQG_fsUlTxX7VRXOCm8SSCjYF2xPV1j`, 13,899 bytes, SHA-256
  `d1b3f7a91fbe07d11f9100346f0ef65f0e3576d35dcf27708f585bb5e6ca038a`;
- publication repository basis `RMF112018/my-pa`, `main`,
  `195fa54206996dddd6c6e0b6da0872781aa4f5f0`; the re-mirror occurs after the
  documentation-only `D-104` merge at `7ae3917b7d95548883211aa64a12edf99351e59a`.

The control folder is `1PLw2r7MmNXKi2pZxaIRiXTNVg-itiZ99`. Following the
existing Native Reminders policy, four raw control records are mirrored and the
coordination request and response remain external:

| Control artifact | Drive ID | Bytes | SHA-256 |
|---|---|---:|---|
| Canonical artifact disposition | `1vCigEEP3Rmj60-ukkLze37pU0BXmj7Lg` | 12,568 | `08f62eec99e8ae8b369e248c2fa1efa451c3bb34a965316dc8d2670d9676e15f` |
| Publication receipt | `1N-Jduf-hXcpH-kugP9HsxnqVsau4QONU` | 5,309 | `b6dc9d02471407a53cd5308b67903677aeb500e7c516bde9c9f407946d2cedab` |
| Readback verification | `1qFk2KVI217QxIM5X7FwYD533g_VZSUX5` | 11,873 | `a1e193d36d9436f6b473924e6182c5351fba2698301b20875d81763471f70bc4` |
| Coordination roundtrip receipt | `15th9q7BiMQpzZqi5YKedadBbeBH33KoW` | 5,116 | `ce1b25b75d53cb355270c52011614233c5050ef501f9acc3cba2d221c9d6f8c0` |

### Scope disposition

Version 2.3 adds the Native Apple Personal Data Capture Bridge, user-facing
**Apple Mail, Calendar & Contacts**, feature package
`MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087`
at Drive folder `13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5` (manifest Drive ID
`1gBPfHAtPClqFoT7skQJlpp9Sf2L72q_J`, publication receipt Drive ID
`1ATS9ONwZmA9Ar1_-sHaxCKcRUUwvoOqT`). The canonical roadmap calls its sequence
WP-12 and the MVP definition calls it conditional MCV scope.

Those product statements do not grant repository implementation authority.
The authority evidence is precise but not uniform. The numbered canonical
artifacts carry their own implementation-not-granted blocks. The disposition's
narrower authority block denies implementation, live access, source mutation,
deployment, production, and risk acceptance. The readback asserts only
`implementation_authority_not_granted: true`. The publication and roundtrip
receipts carry the fuller denial list for implementation, live personal data,
TCC/credential mutation, source mutation, deployment/watchers, production
activation, external-model disclosure, destructive retention, and risk
acceptance. The operator first identified the feature as provisional WP-12
after WP-10 and WP-11, which `D-105` preserves as historical provenance. The
later direct authorization `AUTH-WP12-20260804-OPERATOR-001` resolves that
sequencing hold for WP-12 only: `D-106` promotes bounded synthetic repository
implementation ahead of WP-10/WP-11. `D-104` still defers WP-10 until MCV
completion, and WP-11 still depends on WP-10. Live Apple access,
TCC/credentials, signing, installation/watcher activation, external disclosure,
source mutation, destruction, deployment/production, and risk acceptance remain
unauthorized. `D-107` separately records the future full-MVP handoff after
independently verified MCV completion; it does not start that campaign now.

The ten `NAPDCB-OP-001` through `NAPDCB-OP-010` decisions remain in the
canonical package's own ledger. Like `NAR-OP-*`, they are excluded from section
14's three-ledger counts and none is answered here.

### WP-12C implementation checkpoint — 2026-08-05

Slice C now has a bounded synthetic-only application admission and control
implementation for its eleven final criteria. Its local PR-tier evidence is
complete: 467 database/recovery/e2e tests passed against a separate disposable
PostgreSQL 17 database, and 2,950 FAST tests passed. Slice C still requires a
green PR rerun and independent review of the corrected exact head, so this
checkpoint does not declare Slice C complete. The first independent review
returned `BLOCK` with six findings; a corrective rereview found one call-order
defect; the next precommit rereview passed pending database CI; and the PR source
review then found request-ID and composite-locator binding defects. All reports
remain preserved. A subsequent corrected-manifest review found that admission
status could commit before response acceptance and final current-scope
validation. The bounded correction now rejects response-identity mismatch
before any write, commits reachable status atomically with final locked
authority validation, consumption, and evidence, and records an operational
preflight denial only after the same current-scope validation without consuming
the authority. Focused unit and architecture regressions pass, the full Slice C
admission schema file passes ten tests, and the exact database/recovery/e2e tier
passes 467 tests against disposable PostgreSQL 17. A green PR-CI rerun remains
mandatory. The correction also binds preflight to the exact request and `(kind,
account, bucket)` locator, retains serialized scope/admission and durable exact
authority, and repairs historical migration and disposable-test isolation
without weakening the authority-to-audit foreign key. Native-host
operation, baseline execution, watchers, frontend routes, live Apple access,
and every other Slice E/F/G/H behavior remain absent or deferred. The
machine-readable disposition is
`.ai/goals/wp-12-apple-mcc/slice-c-implementation-checkpoint.json`.

### Invalidation

This reconciliation binds the 21 numbered artifacts and four selected controls
to the exact raw hashes above. Any later canonical artifact revision, Drive-ID
or parent change, manifest mismatch, superseding feature decision, or explicit
operator scope/authority decision invalidates the affected statements and
requires fresh raw readback and re-reconciliation. A green repository hash test
proves only that the mirror matches these receipts; it does not prove Drive has
not changed again.
