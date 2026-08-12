# Pilot-blocker remediation — exact-candidate record

Objective: produce one coherent local canonical-MVP candidate that closes
`MYPA-PILOT-BLOCKER-001` through `-006` without activating production, live
personal data, external ingress, external MCP clients, cloud models, or managed
writes outside a synthetic local boundary.

Acceptance requires one Alembic head, durable acknowledgement, Principal
isolation, backend-served normal UI routes, the four-family Apple source plane,
bounded knowledge/model/GoodNotes/managed-document/MCP planes, recoverable
offline/remote/background operation, exact-candidate tests, and a fresh
independent exact-head review. This document records implementation completion;
it does not make the pilot-readiness determination.

## Objective-specific authority and policy inconsistency

The operator reprioritized this remediation objective to include the frontend
and managed-document work required by the blocker closure criteria. That
instruction is objective-specific implementation authority. It is not an
amendment of `AGENTS.md`, and `PLAN_APPROVED` did not authorize one.

The older policy statements deferring frontend and managed-document
implementation are therefore stale for this objective. The inconsistency is
recorded here, in section 15 of the completion plan, and must be recorded in the
pull request and final-state report. `AGENTS.md` is preserved unchanged for a
later, separate operator correction unless the operator explicitly authorizes
amending it.

## Candidate lineage and selective reconciliation

The remediation branch is `bf/pilot-blocker-remediation`, based on the audited
`main@9b35476b70fe4fbc03bb8f9835d93c1b71089bbe`. Retained work was selected by
capability, not merged wholesale:

| Retained line | Disposition | Candidate result |
|---|---|---|
| recovery lineage and WP-03 through WP-13 | PORT / ALREADY_PRESENT | identity, Principal partitioning, durable Capture, Entra-ready gateway, offline/remote Capture, Reveal, continuity, relationships, and PWA surfaces share one runtime |
| WP-12E frozen baseline | PORT with ancestry reconciliation | admitted-page-bound baseline/checkpoint behavior retained; the merge revision joins it to managed documents without DDL |
| WP-15 through WP-18 | PORT + CLOSE GAP | source-built core and bounded adapters retained; the separately bounded shipping target implements EventKit Calendar and Tasks, bounded Contacts, and an operator-gated read-only Apple Mail automation mechanism |
| missing host, Tasks/To Do, watcher, and operations deltas | REIMPLEMENT | fail-closed executable host admission, Tasks adapter, bounded watcher/cursor/backoff/calendar horizon, retry/dead-letter and worker-liveness semantics added on the candidate |
| WP-23 and WP-27 | PORT | PKL/coverage and managed-document planes retained with Principal and read/write-root separation |
| WP-28 | PORT | stdio Frontier MCP thin adapter, kill switch, conformance and filesystem-race controls retained |
| GoodNotes and bounded model gate | REIMPLEMENT | read-only manifest-indexed streaming source, aggregate-bounded no-shell OCR, stable provenance, local-operator composition, canonical Review and knowledge search integration, model-off default, and proposal-only model gate added |
| `bf/extractions-quarantined-debt`, `bf/mcv-neutral-remainder`, Dependabot | PRESERVE_ONLY / SUPERSEDED | no unique blocker-closing behavior remains outside this candidate; no wholesale merge performed |

## Blocker closure matrix

| Blocker | Candidate implementation | Direct evidence |
|---|---|---|
| 001 — durable Quick Capture | web Capture calls the authenticated BFF, which invokes `capture.create`; PostgreSQL commits source/version/submission/receipt/job before success; replay/conflict/restart and two-Principal behavior remain structural | capture transaction, remote transaction, recovery, cross-Principal, web gateway and route tests |
| 002 — incoherent lineage | one selective candidate, one 34-revision history, DDL-free branch merge, head `b4e8d2c7a613`; retained lines classified above | Alembic heads, empty/head/round-trip/denotation tests, this record and PR ancestry |
| 003 — synthetic/stub normal UI | normal Capture, Library, Review, Reveal, Pulse, Projects, Situations, Frames, Trace, commitments, decisions, tasks and relationship timeline call backend capabilities; synthetic data remains opt-in test/dev | web route/gateway/session tests, TypeScript/lint, optimized Next.js build |
| 004 — Apple plane incomplete | source-built Swift core plus runnable fail-closed protected non-live handoff; EventKit Calendar and Tasks, bounded Contacts, and a read-only Apple Mail ScriptingBridge mechanism; frozen baseline, reconciliation, cursor watcher, overlap, rolling calendar horizon, pause and bounded failure semantics | Swift build/contract checks, a synthetic four-family executable handoff producing four content-free protected receipts, and platform architecture guards; no live store invocation, personal-data read, TCC request, signing, install, or activation claim |
| 005 — knowledge/tool set | PKL lexical/evidence retrieval; GoodNotes invokes no model, and the general bounded model gate refuses before provider invocation without a durable canonical Review router; streaming GoodNotes reconciliation is exact-registry/enrollment-bound and capped at 100 pages, 100 MiB, 2,000 regions, 2 million characters, and 300 seconds without holding a DB connection during OCR; canonical Review/accepted knowledge search; managed-document lifecycle; stdio Frontier MCP | aggregate-limit/model tests, same-source/two-Principal canonical Review and ordinary knowledge-search PostgreSQL proof, hostile deterministic-ID collision refusal, managed-document, MCP, Principal-isolation, security and conformance tests |
| 006 — offline/remote/operations | Principal-bound encrypted offline queue and replay controls, dedicated remote Capture credential plane and iOS Shortcut fixture, retry/dead-letter, worker heartbeat health, statement timeouts, backup/restore rehearsal and runbooks | web offline tests, remote socket/database tests, worker/recovery/health tests, restored database at exact Alembic head |

## Safety and external prerequisites

- Graph remains configured OFF by default and does not create a delta worker,
  webhook, consent requirement, token activity, or unhealthy source while off.
- Semantic/vector retrieval and cloud models remain disabled until their
  benchmark, security, privacy, and disclosure gates pass.
- Source roots and Apple/GoodNotes/NAS inputs are read-only. Managed writes are
  confined to the separately configured managed root and were tested only with
  synthetic temporary storage.
- Live Entra tenant/app credentials, Remote Capture HTTPS exposure and device
  credential issuance, TCC grants, signing/notarization, pilot-Mac install,
  live Apple/GoodNotes/NAS admission, external MCP activation, cloud-model
  allowlisting, production database migration/deployment, and risk acceptance
  remain operator-only pilot-environment actions.

## Validation record

Validation is against synthetic fixtures and disposable PostgreSQL only. The
final exact totals, commit/tree, PR identity, and independent-review result are
recorded in the PR and final implementation report. At implementation closeout
before the final exact-head commit:

- Ruff lint and formatting pass across 656 files; mypy passes the configured
  `src` and `apps` targets; 2,495 architecture guards pass;
- the exact FAST selection passes 4,825 tests with 709 deselected in 98.19
  seconds. This exceeds the 60-second MCV target and is recorded as a measured
  budget variance rather than treated as a functional failure;
- the database/recovery/e2e selection passes 706 tests with 4,828 deselected
  in 622.91 seconds against disposable PostgreSQL; the focused GoodNotes
  registry/enrollment, same-source/two-Principal, collision, Review, and search
  integration passes 2 tests;
- web unit (297 tests), lint, TypeScript, optimized production build, and
  browser E2E (69 passed, 1 conditional skip) pass;
- Swift builds and `AppleSourceHostContractChecks` passes 37 checks repeatedly
  under a hard 20-second deadline; a synthetic four-selection dry run constructs
  the real inert composition and writes four protected receipts;
- empty-to-head, revision round-trip, migration denotation, database,
  cross-Principal, security, recovery, GoodNotes, managed-document and MCP tests
  are required green on the exact head;
- a `pg_dump`/`pg_restore` rehearsal restored 89 `knowledge` tables and Alembic
  head `b4e8d2c7a613` into a second disposable database;
- GitHub Actions availability is reported, never inferred from local results.

The independent audit of
`3a14b58526fba85d810ad39e18f7d7748cc2f1de` returned BLOCK for an inert-only
Apple executable, platform materialization/cursor bounds, a timing-dependent
Swift spool deadlock, GoodNotes registry/enrollment and cross-Principal identity
gaps, an incomplete model proposal boundary, and contradictory current-state
documentation. Those findings were accepted and corrected. The corrective
database test then exposed and closed a same-source/two-Principal search leak.
That audit is superseded by the final corrective commit and cannot serve as the
required final exact-head review.

## Independent review gate

No statement in this record means `READY_FOR_PILOT_VALIDATION`, independently
verified, or risk accepted. A fresh context with authority to block must review
the exact final head after the PR is published. Any later commit invalidates
that review and requires a new exact-head review.
