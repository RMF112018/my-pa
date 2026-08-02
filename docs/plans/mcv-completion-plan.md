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
| WP-6 | Capture domain, contracts, and durable persistence | WP-5 | No |
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
| D-18 | Corrected in place: `RI-OD-001` is not open in the way this plan first listed it | The canonical direction already resolves the naming question — "PRIE is superseded as a product name. The public area is **Relationships**; the domain is **Relationship Intelligence**." This plan initially listed `RI-OD-001` as blocking WP-9 contracts with no recommendation available. A recommendation does exist and is canonical-in-Drive; what remains is operator ratification, which is a smaller thing. Corrected rather than left, because listing a settled recommendation as an open question wastes the operator's attention, which is the resource this whole list is meant to protect. | **Superseded by `D-20` on 2026-08-02, and one clause of it was never verifiable.** The quotation attributed above to "the canonical direction" — "PRIE is superseded as a product name. The public area is Relationships…" — is `my-pa vNext` text. It appears nowhere in the ratified package; `grep` for "public area" across all 24 mirrored artifacts returns nothing. The conclusion it was used to reach is independently correct and now rests on ratified `CR-D-007` instead. Its closing clause, "what remains is operator ratification", stopped being true when that ratification occurred. Left visible for the same reason `D-17` is |
| D-16 | Both feature specifications are mirrored into `docs/specs/` and routed from the specification and source indexes | They are `my-pa`-native product design that now drives work packages, so a reviewer should be able to open them from the repository rather than from a Drive link. `docs/specs/README.md` previously listed the read-only slice as the only specification, which understated product intent. Mirrors follow the `evidence/completion/README.md` precedent: exact Drive identity, export hash, and no claim to repository authority. Neither required redaction. **Correction, 2026-08-02:** the phrase "and source indexes" was false when written. `docs/00_REPOSITORY_SOURCE_INDEX.md` routed only the MCV specification; neither mirror, nor `docs/specs/README.md` itself, appeared there. The routing was added with `D-19`, so the claim is true now — but it was a claim about work that had not been done, which is the kind of thing this register exists to catch rather than to produce. | Accepted; one clause corrected |
| D-14 | Model-assisted extraction stages are excluded from WP-7 | Named-entity extraction, identity resolution, contradiction detection, and summary generation all require a model gateway that does not exist and a disclosure decision (`P00-OD-006`) that is open. `AGENTS.md` section 2 forbids building the abstraction ahead of the need. Deterministic extraction proposes less and cites everything it proposes. | Deferred, disclosed |
| D-15 | Corrected in place: the frontend hold reads as permitting backend work, and this was assumed rather than asked | `D-09` records the operator's words as "no frontend implementation is in scope until they say otherwise." Every package in section 12 is frontend-free, so none of them tests the hold. But the hold was never asked about in the direction that matters — whether backend work on a held feature may proceed at all — and the Quick Capture package's `O-04` asks only *when* to lift it, not whether backend work needs it lifted. The reading here is that it does not. It is an assumption, it is stated as one, and it is on the consolidated list in section 14 for the operator to confirm or overturn. | Assumption, disclosed |
| D-19 | Supersedes `D-17`: the canonical product direction is ratified, and is recorded in the repository as ratified | **The instrument is a direct operator instruction issued 2026-08-02, not anything inside the package.** This matters, and independent review was right to demand it: the package nowhere uses the word "ratified", its status field `CURRENT_CANONICAL_PRODUCT_DEFINITION` is self-declared, its receipt grants nothing, and `15_OPEN_OPERATOR_DECISIONS.md` states "This package performs none." A self-declared status is precisely the evidence `D-17` ruled insufficient for the predecessor, so ratifying on that basis alone would have contradicted the standard this register set. What supplies it instead is the operator's instruction opening this session: that the product documentation, revised considerably, "is RATIFIED", identifying it by Drive ID `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`, with the direction to enforce it through the next implementation phase. That is the same self-executing form as the 2026-08-01 reprioritisation recorded at `D-10` — the instruction is the mechanism, and this row records what happened rather than authorising it. The subject is `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, version 2.1. It supersedes `my-pa vNext` for current whole-product definition and preserves it as source history; the two are siblings under one Drive parent, so this is supersession inside a lineage rather than replacement from outside it. It is mirrored byte-exact at `../specs/canonical-product-definition/` and verified against three independent in-package hash sources: 21/21 against the artifact disposition, 21/21 against the readback verification, and 20/20 against the source manifest, which covers every member except itself and says so. Three limits survive ratification and are the reason this is a decision rather than a scope change: it grants no implementation authority (`implementation_authority: NOT_GRANTED`); under `AGENTS.md` section 1 it is an indexed Workspace publication at precedence rank 4, below repository policy at rank 3; and its own `OP-05` and roadmap step `R10.1` direct that WP-4 and WP-5 finish first. Ratification endorsed this plan's sequence rather than displacing it. | Ratified, and bounded — see section 15 |
| D-20 | `RI-OD-001` stops blocking WP-9 and moves to non-blocking | The ratified decision log records `CR-D-007` — "RI is integrated domain; PRIE historical" — as `Canonical`, and the ratified executive description states that Relationship Intelligence "is the people-centered continuity domain inside my-pa… not a separate PRIE engine, database, frontend, or product", with `PRIE` "historical terminology retained only for provenance". That settles the name that enters `v1` contracts, which is the only part `D-18` said was blocking WP-9. Note what it does **not** settle, since `D-18` overstated this: the ratified information architecture lists Relationships under its **Library** section (`05_INFORMATION_ARCHITECTURE.md` line 51), and the ratified executive description states explicitly that Relationships and the collections listed beside it are "not separate top-level destinations" (`01_EXECUTIVE_PRODUCT_DESCRIPTION.md` line 88). Both citations are given because the first draft of this row credited that quotation to the information architecture, which does not contain it: `05` supplies the listing, `01` supplies the statement, and the conclusion needs both. `D-18` called it "the public area" — inherited from the superseded document, and contradicted by both. That framing is dropped here; only the naming conclusion is carried forward. What remains open is `OP-02`, the final UI label set, which the canonical package gates on "UI freeze" — frontend scope, independently held by `D-09`, and not a WP-9 contract input. Narrowing the claim to what the evidence supports rather than declaring the whole question closed. | Corrected; `RI-OD-001` reclassified |
| D-21 | Section 14's headline counts were wrong and are now derived rather than asserted | Section 14 stated "Forty-one decisions are open … Sixteen of them block." Recomputed from the tables themselves: **46 distinct IDs, no duplicates across the three tables**, and **29 of them blocking** at the moment of recomputation — the second table is itself headed *Blocking*, so counting only the first understated it by thirteen. `D-20` then moved `RI-OD-001` out of the blocking table, so the current figures are 46 open and 28 blocking; the total was never affected, only the split. A corrected constant would rot the same way, so `tests/architecture/test_open_decision_counts.py` now derives every figure from the tables and fails when the prose and the tables disagree. Each of its assertions was proven non-vacuous by planting a readable-but-wrong figure and confirming the count comparison fired for the intended reason. This is the third time in this campaign an inherited number proved stale on recomputation. | Corrected, and the mechanism corrected |
| D-22 | The Frontier NAS MCP Connector feature package is indexed by reference, not mirrored | Ratification brought a third feature package into canonical scope: `MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086` (Drive folder `1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa`, 17 members by `rclone lsf` on 2026-08-02 — a count no repository artifact attests, since the package is not mirrored). `D-16` mirrored the other two because they drive work packages in section 12 and a reviewer needs to check citations against files. This one drives no planned package: the canonical package's own `MCP-OP-001` recommends finishing the WP-4/WP-5 sequence first, and its acceptance crosswalk marks `MCP-AC-02` and `MCP-AC-04` through `MCP-AC-06` `NOT IMPLEMENTED`. Mirroring 17 further artifacts to support no citation would be scope this plan does not need, against `AGENTS.md` section 2. It is routed by exact Drive identity so it cannot be rediscovered as a surprise. | Indexed by reference |

## 14. Consolidated open decisions returned to the operator

Forty-six decisions are open: nine from the Phase 00 ledger, twenty from Quick
Capture, and seventeen from Relationship Intelligence. Twenty-eight of them block
a work package in section 12 — fifteen on ordinary grounds and thirteen more that
are reserved to the operator by policy and block for that reason. The remaining
eighteen do not block anything yet and are listed so they are not rediscovered
later as surprises.

These numbers are derived from the three tables below, not maintained beside
them. `tests/architecture/test_open_decision_counts.py` recomputes them from this file
and fails if this paragraph and those tables disagree.

That test exists because this paragraph was wrong. It previously read "Forty-one
decisions are open … Sixteen of them block." Both figures were incorrect: the
tables held forty-six distinct IDs with no duplicates between them, and the
second table is itself headed *Blocking*, so counting only the first understated
the blocking total by thirteen. The correction is recorded as `D-21`, and the
mechanism was corrected alongside the number because a hand-maintained count
goes stale silently and this one already had.

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

`P00-OD-004` contract freeze and `P00-OD-012` `pg_trgm` necessity, both
`OPEN_REVIEW`. `P00-OD-013` audit retention and `P00-OD-014` parser isolation,
both deferred to their phase gates. `O-02` formal product principle, `O-05`
initial platforms, `O-06` offline MVP, `O-07` PWA versus native wrapper, `O-11`
notifications, `O-12` audio scope, `O-13` attachments — every one of these is
frontend, platform, or media scope that section 12 does not plan. `RI-OD-008`
public research, `RI-OD-010` offline posture, `RI-OD-013` importance labels,
`RI-OD-014` device matrix, `RI-OD-015` voice capture, `RI-OD-017` independent
usability and privacy review gate before release.

### Five questions this plan raises that no ledger contains

Ratification on 2026-08-02 answered the third of these outright, changed the
footing of the first and the fourth, and added a fifth. The answered one is kept
and marked rather than deleted, because a list that quietly drops the question it
resolved teaches a reader nothing about how it was resolved.

1. **The MCV end date.** *Still open, and now overdue.* `AGENTS.md` section 1
   said the MCV ran "through August 2, 2026." When this was written that was
   tomorrow; it is now today, and section 12 plans six work packages that plainly
   do not fit behind it. `AGENTS.md` section 1 has since been amended to say the
   date passed and that the MCV runs until the operator declares it complete,
   which is honest but is not a date. Choosing one remains an operator act. The
   operator should either set a date or confirm that the open-ended condition is
   intended.

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
   full. Only this item is answered; the thirty-nine operator decisions inside
   the package — `OP-01` through `OP-30` and `MCP-OP-001` through `MCP-OP-009` —
   remain open and are not tracked here.

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

## 15. Reconciliation against the ratified canonical product definition

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

Two consequences follow. First, the thirty-nine operator decisions inside the
package remain open — `OP-01` through `OP-30`, plus the connector's `MCP-OP-001`
through `MCP-OP-009`. Ratifying the definition did not answer any of them, and
`OP-05` in particular still carries only a recommended default. Section 14's
counts exclude all thirty-nine, for the reason given in item 5: they belong to
the package, not to the three ledgers this plan is accountable for.
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
