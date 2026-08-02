# MCV Completion — Gap Audit and Integrated Implementation Plan

Plan basis: `PLAN-MYPA-APPLICATION-COMPLETION-20260801-078` (Drive `1-jfuAm3p1bQSC3l-37rFw6wk82HFQ9MKalR-LZm_U3Q`).
Audit basis: `main@e773e6f2285da9e453a8ca7e11bdac23619aaf22`, audited 2026-08-01.
Revalidated against `main@8274d88a6211c417c43d2d937edfe2c8ccc369be` on 2026-08-02, after
work packages WP-2 and WP-3 merged and the operator reprioritized the objective.
Section 1 records the current identities; the sections below it were corrected
in place rather than left to be read as current.

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
| Alembic head | `8b3f5c17d904` in the repository; the canonical database remains at `6c4d3ea82f10` because the `knowledge` revisions run only against disposable databases | `migrations/versions/*.py`, `select * from alembic_version` |
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

Sixty-eight Python modules under `src/my_pa`, forty test modules.

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
| Alembic revisions — schemas and extensions, target tables, control plane, indexes, foreign keys, views, `knowledge` schema, extraction tables | Implemented, eight revisions, head `8b3f5c17d904` |
| CI — `repository-checks.yml` including the database tier | Implemented |

All eight capability names, their operator-only flags, and their permitted
purposes already exist in `domain/identity/operation.py`. The v1 request,
response, disclosure, and error shapes already exist and are contract-tested.

## 4. What is not implemented

Nothing below `contracts` and `domain` executes a product workflow. Specifically
absent, with no code beyond a README:

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
4. **WP-4 — application services and transports.** The eight capabilities wired
   to real behavior behind the existing v1 contracts; HTTP gateway on loopback;
   MCP adapter with transport parity; operator CLI.
5. **WP-5 — operations and local candidate.** Startup, shutdown, health,
   readiness, recovery and idempotency tests, empty-to-head validation, the
   end-to-end synthetic slice, operator runbook, honest limitations.

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
| D-08 | Terminal disposition cannot be reached in this scope | Plan §11 requires GoodNotes, frontend, and relationship acceptance criteria that D-03 and D-04 defer. The honest terminal state is MCV-complete with the deferred set named, not `MYPA_CURRENT_PRODUCT_SCOPE_COMPLETE`. | Disclosed to operator |

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
  package rather than in the middle of its list.
- **`coverage_for` runs outside `persistence.search`'s redaction path**, so a
  `SQLAlchemyError` from the coverage read escapes carrying SQL and a bound
  identifier. Not the query-leak path, since nothing there binds query text, but
  the same class of hole.
- **No `statement_timeout` is configured anywhere.** The functional index removes
  the sequential scan as the only possibility without bounding what a query can
  cost. WP-4 owns process and connection configuration.
- **`eligible` is a required integer in the `v1` disclosure** and no integer is
  true for an unmeasured scope. Making it absent is a contract change gated by
  `P00-OD-004`.
- Smaller, and named so they are not rediscovered: the `extractions` check
  constraint admits a status no counting query matches; `record_object` in
  `infrastructure/persistence/registry.py` names a function that does not exist
  (it is `observe_object`); `INDEXED_CONFIGURATIONS` is read as a rebindable
  module global; the offline DDL test asserts constraint names but not index
  names; and `mypy` is configured over a wider tree than the gate runs.

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
capabilities. None of those exist: `apps/gateway/` and `apps/worker/` hold a
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

| WP | Objective | Depends on | Frontend? |
|---|---|---|---|
| WP-4 | Application services and transports | WP-3 | No |
| WP-5 | Operations and local candidate | WP-4 | No |
| WP-6 | Capture domain, contracts, and durable persistence | WP-4 | No |
| WP-7 | Capture processing, proposals, evidence spans, exact search | WP-6 | No |
| WP-8 | Review cases, promotion, and conversation events | WP-7 | No |
| WP-9 | Relationship identity and read-only profiles | WP-4, WP-8 | No |

Every package above is frontend-free and may proceed under `D-09`. The frontend
stages — Quick Capture `QC-05` through `QC-08`, and every responsive or PWA
surface in the Relationship Intelligence specification — are not planned here
and remain held.

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

Corresponds to Quick Capture stages `QC-01` and `QC-02`.

**In scope.** `domain/capture/` — capture and version entities, lifecycle
states, authority states, the immutability invariant, typed errors;
`contracts/v1/` additions for capture create, version create, read, and list;
new capability names and purposes added to `domain/identity/operation.py`;
one Alembic revision creating capture tables in the `knowledge` schema (or a new
schema the PR names and justifies); `infrastructure/persistence/capture.py`;
the save transaction — capture, version, receipt, redacted audit, and enqueued
processing job committed together or not at all.

**Out of scope.** Extraction of any kind. Proposals, spans, review, conversation
events. Offline queue. Any frontend. Attachments. Model calls.

**Acceptance criteria mapped to tests.**

- `QC-AC-010` immutability — a domain test proving no code path updates stored
  text, and a database test proving the constraint holds under concurrent write.
- `QC-AC-012` distinct timestamps — `client_created_at`, `server_received_at`,
  and `recorded_at` are separately stored and never substituted for one another.
- `QC-AC-013` editing appends — an edit creates a successor version, the
  predecessor stays retrievable, and the supersession chain is unbroken.
- `QC-AC-031`/`QC-AC-032` idempotency — replaying an identical request returns
  the stored receipt; reusing the key with different content returns
  `idempotency_conflict` and stores nothing.
- `QC-AC-034` — an induced audit or receipt failure fails the whole transaction
  closed, and no capture exists afterwards. Prove by planting the failure.
- `QC-AC-041` — a redaction test asserting no capture text reaches logs, audit
  rows, or error payloads.
- ADR-003 clause 5 — an architecture test asserting the source-provider port
  still exposes no write method and that capture persistence does not import it.

### WP-7 — capture processing, proposals, evidence spans, exact search

**Objective.** Turn a stored capture version into typed, span-bound, explicitly
noncanonical proposals, and make the original text searchable — without a model.

Corresponds to Quick Capture stage `QC-03`, restricted.

**In scope.** Worker stages `P-01` validate, `P-02` normalise with a reversible
offset mapping, `P-03` language detection allowing `unknown`, `P-04`
segmentation, `P-05` deterministic extraction (dates, amounts, identifiers,
URLs, explicit commitment cues), `P-08` date normalisation, `P-09` work-object
proposals from deterministic cues only, `P-15` transactional proposal
persistence, `P-16` indexing of original text through the FTS plane WP-3 built.
Evidence spans on `unicode_code_point_v1` with quoted-text hashes re-validated
against the immutable version.

**Out of scope, and why.** `P-06` named-entity extraction, `P-07` identity
resolution, `P-12` contradiction detection, and `P-14` summary generation are
model-assisted. No model gateway exists, `P00-OD-006` is open, and
`AGENTS.md` section 2 forbids building the abstraction before the need. They
belong to a later package that begins with a model-boundary decision. Excluding
them costs recall, not correctness: a deterministic-only pipeline proposes less
but proposes nothing it cannot cite.

**Acceptance criteria mapped to tests.**

- `QC-AC-011` — every persisted proposal carries at least one span, and a span
  whose quoted-text hash no longer matches its version quarantines the proposal
  rather than presenting it. Prove by mutating a version and re-running.
- `QC-AC-050` — original text is searchable whether or not extraction succeeded.
- `QC-AC-035` — replaying a completed stage returns the prior output and
  creates no duplicate proposal; a lost lease cannot commit.
- `QC-AC-042` — an injection corpus (`ignore previous instructions`, fake tool
  calls, embedded URLs) produces bounded proposals or safe failure, and never a
  fetch, tool call, or widened scope.
- `QC-AC-002` — a save does not wait on any pipeline stage. Prove by asserting
  the save transaction's committed set contains no proposal row.

### WP-8 — review cases, promotion, and conversation events

**Objective.** Give consequential proposals a governed path to canonical, and
give an explicit Conversation Log its skeletal event.

Corresponds to Quick Capture stage `QC-04`.

**In scope.** Review case model binding exact capture, version, proposal, spans,
target object, and expected version; the six dispositions; promotion receipts;
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
  Prove by attempting each promotion directly and requiring denial.
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

`D-17` records `my-pa vNext` as proposed canonical product direction. It is not
accepted, and nothing above builds toward it. But it defines the object model
these packages would eventually attach to, and naming the mapping now costs
nothing and prevents avoidable rework. No abstraction is created for it; this
table is documentation, not a design.

| Built here | vNext object | Note |
|---|---|---|
| Capture, CaptureVersion (WP-6) | Source Record, and its exact version | A user-authored one. The version *is* the addressable evidence |
| EvidenceSpan (WP-7) | Source Region | Same role: the addressable sub-part a claim cites |
| ExtractionProposal (WP-7) | Assertion, before acceptance | vNext's Assertion carries trust state; a proposal is one awaiting a trust state |
| ReviewCase (WP-8) | Review Case | Same object, same name |
| Promotion receipt (WP-8) | Receipt | Same object |
| Conversation (WP-8) | Event, specialised | vNext models it as a dated occurrence with distinct event and recorded time |
| Person, Organization (WP-9) | Entity | vNext generalises to person, organisation, project, location, topic, document |
| Affiliation, project association (WP-9) | Relationship | Typed, time-aware, evidence-backed |
| — | Situation, Frame, Trace | Not built by any package here. These are the context layer, and they need vNext ratified first |

The one place to be careful is `Assertion`. WP-7's proposals and WP-8's accepted
records are the same thing at two lifecycle points in vNext's model, where a
single Assertion carries a trust state through Confirmed, Strongly Supported,
Probable, Possible, Unverified, Contradicted, Stale, and Unknown. Modelling
proposal and accepted record as two unrelated tables would be the rework. WP-7
should therefore give a proposal a trust state from the start, even while only
two of the values are reachable.

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
| D-17 | The canonical product direction is recorded in the repository, by reference, as proposed | `my-pa vNext` (`SPEC-MYPA-VNEXT-PRODUCT-SYNTHESIS-v1.0`, Drive `17olnyUF5oX-KJWB6owRIJBB8B4QTlRjJhkLG47gio9s`) is named by the owning Drive index as the "sole canonical product-vision reference" and the "canonical implementation-agent instruction … for MVP framing and roadmap." The repository contained no reference to it, so an agent reading only the repository would not know the product has a defined mental model, a five-destination information architecture, or an object model built on Situations, Frames, Assertions, and Receipts, and could build a shape that has to be undone. It is recorded as `PROPOSED_CANONICAL_PRODUCT_DIRECTION`, which is its own declared status, and it is **not** treated as accepted: it grants no implementation authority, and nothing in section 12 builds toward it beyond what the operator promoted. Ratifying it is an operator decision nobody has asked for; see section 14. | Recorded by reference, not accepted |
| D-18 | Corrected in place: `RI-OD-001` is not open in the way this plan first listed it | The canonical direction already resolves the naming question — "PRIE is superseded as a product name. The public area is **Relationships**; the domain is **Relationship Intelligence**." This plan initially listed `RI-OD-001` as blocking WP-9 contracts with no recommendation available. A recommendation does exist and is canonical-in-Drive; what remains is operator ratification, which is a smaller thing. Corrected rather than left, because listing a settled recommendation as an open question wastes the operator's attention, which is the resource this whole list is meant to protect. | Corrected |
| D-16 | Both feature specifications are mirrored into `docs/specs/` and routed from the specification and source indexes | They are `my-pa`-native product design that now drives work packages, so a reviewer should be able to open them from the repository rather than from a Drive link. `docs/specs/README.md` previously listed the read-only slice as the only specification, which understated product intent. Mirrors follow the `evidence/completion/README.md` precedent: exact Drive identity, export hash, and no claim to repository authority. Neither required redaction. | Accepted |
| D-14 | Model-assisted extraction stages are excluded from WP-7 | Named-entity extraction, identity resolution, contradiction detection, and summary generation all require a model gateway that does not exist and a disclosure decision (`P00-OD-006`) that is open. `AGENTS.md` section 2 forbids building the abstraction ahead of the need. Deterministic extraction proposes less and cites everything it proposes. | Deferred, disclosed |
| D-15 | Corrected in place: the frontend hold reads as permitting backend work, and this was assumed rather than asked | `D-09` records the operator's words as "no frontend implementation is in scope until they say otherwise." Every package in section 12 is frontend-free, so none of them tests the hold. But the hold was never asked about in the direction that matters — whether backend work on a held feature may proceed at all — and the Quick Capture package's `O-04` asks only *when* to lift it, not whether backend work needs it lifted. The reading here is that it does not. It is an assumption, it is stated as one, and it is on the consolidated list in section 14 for the operator to confirm or overturn. | Assumption, disclosed |

## 14. Consolidated open decisions returned to the operator

Forty-one decisions are open across three ledgers and two feature packages.
Sixteen of them block a work package in section 12. The rest do not block
anything yet and are listed so they are not rediscovered later as surprises.

Nothing below is decided here. Where a recommendation exists it is named as a
recommendation.

### Blocking — a work package in section 12 cannot pass acceptance without these

| ID | Source | Question | Blocks |
|---|---|---|---|
| `P00-OD-003` | Phase 00 ledger | Which reviewed PDF extractor, if any | WP-5 acceptance; PDF stays `unsupported` until then, which is specified behavior, not a defect |
| `P00-OD-010` | Phase 00 ledger | HTTP/MCP authentication mechanism | WP-4 beyond loopback. WP-4 can be built and tested locally with a local principal; it cannot be exposed |
| `P00-OD-011` | Phase 00 ledger | Numeric resource limits | WP-4 `capabilities.get` publishes effective maxima; they are currently Phase-01 placeholders |
| `O-01` | Quick Capture | Final capability, action, and mode names | WP-6 — capability names enter `domain/identity/operation.py` and the public `v1` contract, where renaming later is a breaking change |
| `O-09` | Quick Capture | Private-note default classification | WP-6. Recommendation: `private_local`, no training, no lock-screen content |
| `O-14` | Quick Capture | Editing semantics | WP-6. ADR-003 assumes immutable versions with append-only edits; confirming `O-14` ratifies that assumption |
| `O-15` | Quick Capture | Which links may auto-accept beyond deterministic launch context | WP-8. Recommendation: keep inferred links proposed |
| `O-16` | Quick Capture | Review thresholds by risk and consequence | WP-8 — the routing rule is the package |
| `O-17` | Quick Capture | External-action boundary | WP-8. Recommendation: no action authority; accepted records may later create separate action proposals |
| `O-18` | Quick Capture | Conversation object behavior | WP-8. Recommendation: explicit Conversation Log creates a skeletal event; inferred conversations stay proposed |
| `O-19` | Quick Capture | Whether "save without AI processing" appears in MVP | WP-7 — it is a stored processing-policy value, not a UI toggle, so it must exist in the schema or not at all |
| `RI-OD-001` | Relationship Intelligence | Public feature name. **A canonical recommendation already exists**: the vNext direction states "PRIE is superseded as a product name. The public area is Relationships; the domain is Relationship Intelligence." Ratification, not deliberation | WP-9 contracts |
| `RI-OD-004` | Relationship Intelligence | First personal source set | WP-9. `D-13` builds against fixtures precisely so this can stay open |
| `RI-OD-005` | Relationship Intelligence | Authentication posture for relationship data | WP-9 beyond fixtures |
| `RI-OD-011` | Relationship Intelligence | Which low-risk extracted metadata may auto-accept | WP-8, and overlaps `O-15` |
| `RI-OD-012` | Relationship Intelligence | Which commitment classes always require review | WP-8, and overlaps `O-16` |

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

### Not blocking any planned package

`P00-OD-004` contract freeze and `P00-OD-012` `pg_trgm` necessity, both
`OPEN_REVIEW`. `P00-OD-013` audit retention and `P00-OD-014` parser isolation,
both deferred to their phase gates. `O-02` formal product principle, `O-05`
initial platforms, `O-06` offline MVP, `O-07` PWA versus native wrapper, `O-11`
notifications, `O-12` audio scope, `O-13` attachments — every one of these is
frontend, platform, or media scope that section 12 does not plan. `RI-OD-008`
public research, `RI-OD-010` offline posture, `RI-OD-013` importance labels,
`RI-OD-014` device matrix, `RI-OD-015` voice capture, `RI-OD-017` independent
usability and privacy review gate before release.

### Four questions this plan raises that no ledger contains

1. **The MCV end date.** `AGENTS.md` section 1 said the MCV ran "through August
   2, 2026." That is tomorrow, and section 12 plans six work packages. The
   amendment replaced the fixed date with a condition rather than inventing a
   new one, because choosing a date is an operator act. The operator should
   either set a date or confirm the condition.

2. **Whether promoted scope is still MCV.** `AGENTS.md` section 1 describes the
   objective as "one complete, read-only vertical slice." Quick Capture is not
   read-only — that is the whole point of ADR-003 — so the sentence no longer
   describes the objective. The amendment names the promoted features
   explicitly and keeps "not a broad platform." If the operator intends the
   features as a *successor* objective rather than an enlarged current one, the
   framing should change again.

3. **Whether to ratify `my-pa vNext` as accepted product direction.** This is
   the largest unasked question here, and the only one that could invalidate
   section 12's shapes rather than merely reorder them.

   The Drive owning index names `my-pa vNext` the "sole canonical product-vision
   reference" and the "canonical implementation-agent instruction" for MVP
   framing and roadmap. The document's own status is
   `PROPOSED_CANONICAL_PRODUCT_DIRECTION` with implementation authority
   `NOT_GRANTED`, and the repository referenced it nowhere at all until `D-17`.
   Its own risk register leads with "the vision is broader than the current MCV."

   Two things follow, and they pull in opposite directions. Against ratifying
   now: it is broad, it is proposed, `AGENTS.md` sections 2 and 3 exist to stop
   exactly this kind of expansion, and none of it is needed to build the two
   features the operator actually promoted. In favour of deciding soon: its
   object model — Situation, Frame, Trace, Assertion, Contradiction Group,
   Review Case, Receipt — is the spine that WP-6 through WP-9 would eventually
   attach to. `Conversation` in the Quick Capture model is a specialised Event;
   `ExtractionProposal` is an Assertion candidate; `ReviewCase` appears in both.
   Building those under different names first is not fatal, but it is rework.

   Section 12 takes the conservative path: it builds only what was promoted, and
   names the mapping onto the vNext object model without creating the
   abstractions. That is reversible in either direction. What the operator should
   decide is whether vNext becomes accepted repository direction — which would
   make its acceptance criteria binding and probably re-shape WP-8 and WP-9 —
   or stays a Drive-side proposal the repository merely knows about.

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
   `111zA3Osva_tdi7oW-8TIBcC0uS9_cQ6VZ-w3pqmGhCA`), and the canonical direction
   gives it acceptance criteria of its own. It is not planned here — the
   operator promoted two features and GoodNotes was not one of them — but it is
   closer to plannable than the register currently suggests, and saying so is
   cheaper than having it surface as a surprise.
