# WP-12 bounded architecture and acceptance plan

Status: `CORRECTED_PLAN_READY_FOR_REAUDIT`  
Authorization: `AUTH-WP12-20260804-OPERATOR-001`  
Basis: `main@634890e0bc089294a242be176280c09766bac493`, tree `5cc28830cc213ec9c45441376202d9476ccfed05`

## Objective and acceptance

Deliver a synthetic-only, source-read-only Apple Mail, Calendar & Contacts vertical slice satisfying the repository-verifiable portions of all 48 `NAPDCB-AC-*` criteria: frontend configuration, stable discovery identities, frozen baselines, application-mediated admission, durable source evidence, reconciliation/checkpoints, simulated watchers/recovery, Review-gated consequential proposals, and structural negative proof of source mutation.

Acceptance is the exact 48-row map in `gap-matrix.yaml`, not the shifted group ranges in the canonical summary crosswalk. Each slice must pass its mapped tests plus the applicable repository tier and an independent exact-head review.

## In scope

- `docs/plans/mcv-completion-plan.md` and durable repository docs needed to record current authority/behavior.
- `src/my_pa/domain/native_sources/` for bridge/account/bucket/configuration/run/checkpoint/watcher values and state machines.
- `src/my_pa/contracts/v1/native_sources.py`, commands, ports, capability/purpose and error vocabulary.
- `src/my_pa/application/native_sources.py`, shared authorization/audit/disclosure integration.
- `src/my_pa/infrastructure/persistence/native_sources.py`, existing source/version evidence integration and a native job plane.
- Forward-only Alembic migrations and disposable-database validation.
- `native/apple-source-host/` source-built Swift package, read-only adapter protocols, protected-spool implementation, synthetic adapters and tests.
- Same-origin gateway admission and Apple source configuration/status APIs.
- `frontend/` React/TypeScript/Vite source-configuration module only, with accessible System → Sources flow.
- Synthetic Mail/Calendar/Contacts fixtures and fault plants.

## Out of scope

Live Apple accounts/data; TCC/entitlements/credentials; signing/notarization actions or identities; installation/service/watcher activation; external-model disclosure; source writes; destructive purge; deployment/production; risk acceptance; WP-10 Capture PWA/offline behavior; WP-11 Reminders; Messages/Notes/Photos/Files/Safari; attachments by default; unbounded history; multi-Mac checkpoint transfer.

## Architecture

```text
Synthetic Swift adapters / future separately authorized Apple APIs
  -> owner-only atomic bounded spool
  -> authenticated versioned bridge admission
  -> native-source application use cases + policy/audit
  -> existing knowledge.sources/source_objects/source_object_versions
  -> provider-neutral bounded version evidence + observations
  -> native run/job/checkpoint plus simulation-only watcher plane
  -> separately gated live-attestation/authoritative-watcher boundary
  -> existing extraction/proposal/Review/search/relationship planes
  -> same-origin Apple source configuration frontend
```

The native host never receives a database URL. The browser never calls Apple frameworks. The existing pull `SourceProvider` remains read-only by omission; admission is a separate port so a push source cannot add a mutation method or pretend to be filesystem traversal.

## Persistence and migration strategy

One forward migration in slice B establishes the control plane, with any later schema change in its owning slice as a separate revision:

- extend the frozen provider/object vocabularies explicitly for Apple Mail, Calendar and Contacts without deriving DDL from current enums;
- retain `knowledge.sources`, `source_objects`, and `source_object_versions` as canonical opaque source identity/version records;
- add provider-neutral bounded `source_version_evidence` and source observation/membership edges, linked to exact existing versions;
- add `native_bridges`, `native_bridge_observations`, `native_source_accounts`, `native_source_buckets`, `native_discovery_snapshots`, `native_configuration_revisions`, `native_configuration_buckets`, `native_sync_runs`, `native_bucket_runs`, `native_sync_jobs`, and `native_checkpoints`;
- add a strictly simulation-only plane: `native_watcher_simulations` and `native_simulation_receipts`. Its closed states are `simulation_pending`, `simulating`, `simulation_complete`, and `simulation_failed`; neither its type nor its tables contain `watching`, `activated`, or an authoritative-receipt foreign key;
- create only a fail-closed `native_live_activation_gates` record for the live boundary. Its frozen state set is `not_authorized`, `attestation_required`, or `blocked`; it has no `watching` literal and no receipt foreign key. The current domain likewise has no constructor or transition yielding authoritative `watching`;
- reserve, but do not create under this authority, the future non-substitutable live plane: `native_live_attestations`, `native_authoritative_watcher_registrations`, and `native_activation_receipts`. A later separately authorized migration and implementation must introduce distinct ID kinds, types, repositories and foreign keys and bind `environment=live`, exact host binary/version, verified signing identity, notarization ticket, service registration, compatibility result, exact bridge/configuration/bucket/checkpoint, and exact operator activation authority. It may not reuse or convert a simulation receipt;
- enforce append-only run/config/simulation-receipt/checkpoint history, exact foreign keys, one active lease per bucket/range, idempotency uniqueness, monotonic checkpoint compare-and-set, and schema/AST tests proving there is no current live receipt table, live writer, `watching` literal, or cross-plane conversion;
- store private provider locators only in infrastructure columns; public values carry opaque IDs;
- no nullable widening of enrollment or Capture job ownership and no new database/schema/service.

Validation: SQL generation in FAST; empty-to-head, prior-head-to-head, head downgrade/upgrade roundtrip, trigger inventory, concurrent idempotency and rollback snapshots in disposable PostgreSQL. No existing physical database is touched.

## Work slices and gates

### A — truth, contracts and feasibility boundary

Reconcile the repository plan with the operator authorization; freeze exact acceptance/test mapping and native protocol version; build compile-time/synthetic Mail/EventKit/Contacts feasibility interfaces. No live API or TCC call. Gate: independent plan review. Failure: narrow Mail to unavailable while Calendar/Contacts continue; never adopt legacy NAS/SCP/SQLite.

### B — provider-neutral domain and persistence

Add types, state machines, identities, configuration revisions, schema and repositories. Reuse source object/version authority. Prove opaque identity, exact selection, timezone/range semantics, memberships, append-only history, no mutation methods and migrations. Final criteria: 005, 007, 009, 015, 039, 043. B creates configuration-revision schema support for AC-037, but that is non-dischargeable foundation evidence only; AC-037 has exactly one final owner, C.

### D — source-built native host, synthetic adapters and spool

Build a Swift package with protocol-only Mail/Calendar/Contacts adapters, deterministic synthetic adapters, version negotiation and a user-scoped atomic bounded spool. No database library/configuration, Apple mutation symbol, raw LaunchAgent, opaque binary, real permission request or network listener. Prove discovery, recurrence, no DB path, capacity/backpressure, crash/ack/quarantine. Final criteria: 003, 013, 038, 041.

### C — application admission and control use cases

Runs after D so bridge verification, native preflight and authenticated admission are discharged only against the integrated versioned synthetic host, not application fakes alone. Add neutral capability vocabulary: `native_sources.discover`, `native_sources.configure`, `native_sources.preflight`, `native_sources.sync`, `native_sources.status`, `native_sources.retry`, `native_sources.reconcile`, `native_sources.pause`, `native_sources.resume`, `native_sources.backfill`, `native_sources.disable`. Configuration/lifecycle commands are operator-only because they grant or alter source scope; status/discovery remain policy-scoped. Extend frozen capability/purpose checks in the owning migration. Implement bridge attestation, exact bucket authorization, idempotent admission, redacted progress, removal retention, persist-before-enrich, Review routing, and configuration revision audit integration. Final criteria: 002, 004, 008, 018, 021, 022, 032, 037, 042, 044, 045.

### E — frozen baseline and reconciliation inputs

Implement server-issued cutoff, inclusive/overlap ranges, Contacts inventory, bounded paging, durable cursor, resume, no checkpoint past failed admission, idempotent earlier backfill and later-start no-delete. Final criteria: 010–012, 014, 016–017, 019–020, 033–034. AC-018 remains owned only by C; E reuses its idempotent admission result as foundation evidence.

### F — watcher simulation, recovery and rolling horizon

Implement reconciliation, sibling partial state, bounded overlap, rolling Calendar horizon, permission/bucket drift, freshness, scope add, contact membership reconciliation and pause/resume. These execute only through `WatcherSimulation` and yield only `SimulationReceipt`; the simulation state vocabulary cannot express authoritative `watching`. Real activation remains impossible. Final criteria: 023, 025–031, 035–036. AC-024 is finalized only at H as a fail-closed live gate and remains operator-gated for actual evidence.

### G — Apple source configuration frontend

Add the minimal canonical React/TypeScript/Vite shell/module under System → Sources. It calls same-origin application APIs; supports bridge/permission cards, account and accessible hierarchical bucket selection, local start date/UTC preview, preflight, progress, partial health, pause/resume/retry/backfill/remap and content-free history. No service worker, IndexedDB Capture queue, Quick Capture UI or WP-10 code. Final criteria: 001, 006. UI tests for other lifecycle criteria are supporting evidence only and do not duplicate final ownership.

### H — security, packaging gates and final synthetic validation

Add structural log/receipt redaction, personal-data/secret fixture containment, prompt-injection/no-implicit-authority tests, five-surface mutation-negative evidence, packaging manifest/skeleton and complete synthetic end-to-end recovery. Add closed simulation types/tables and the separate fail-closed live-activation gate; prove the schema and domain contain no authoritative `watching` literal, no live attestation/activation-receipt table or writer, no simulation-to-live conversion, and no composition root exposing live activation. AC-024's repository evidence is this unrepresentability proof; actual authoritative `watching` evidence remains `NOT_RUN_OPERATOR_GATED`. AC-047 likewise remains `NOT_RUN_OPERATOR_GATED` until a separately authorized change supplies verified signing, notarization, registration and compatibility evidence. Final criteria: 024, 040, 046–048.

## Synthetic validation matrix

- FAST: Ruff/format/mypy; domain state/range/identity/idempotency; capability/purpose freeze; negative port/capability surface; frontend unit/accessibility; Swift protocol/unit tests with no Apple permissions.
- PR: FAST; migration SQL and prior-head-to-head; isolated DB repositories/triggers/concurrency; gateway/CLI/MCP parity where capabilities are exposed; frontend browser E2E; native contract/spool tests.
- FULL: crash points before/after spool ack/admission/checkpoint; lease theft; overlap replay; permission revocation mid-page; scope change/backfill; multi-group/multi-mailbox; recurrence drift; full synthetic frontend-to-evidence-to-Review slice.
- SPECIALIZED: unsigned/incompatible/unregistered host denial; authoritative-watching literal/table/writer absence; synthetic-adapter live-attestation denial; no-live-writer composition proof; reproducible unsigned packaging skeleton. Dedicated non-personal canary, authoritative watcher activation and actual signing/notarization are reported `NOT_RUN_OPERATOR_GATED`.

Required fault plants: display-label collision; bucket identity change; crash before spool acknowledgement; crash after admission before checkpoint; lease theft; permission revocation mid-page; duplicate admission; mail move; recurrence change; multi-group contact; unavailable counts; admission outage; spool full; stale checkpoint overwrite; prompt injection; oversized payload.

## Stop conditions

Stop the affected slice if repository/base identity drifts; an exact criterion becomes ambiguous; a new external service/database is required; any test needs personal data; Mail requires an unsandboxed/live permission choice; signing/TCC/credentials or real watcher activation are needed; source mutation or destructive purge is proposed; an exact-head review blocks; or a migration cannot prove rollback/final-state invariants. Calendar/Contacts may continue only when their independent scope and evidence remain valid.

## Completion evidence

For each PR record base/head/tree, changed paths, migration chain, exact tests/results, criterion rows discharged, failed attempts, limitations and independent reviewer identity. A row is discharged only at its `slice` after all `blocking_dependencies` in `gap-matrix.yaml` are proven; foundation tests are partial evidence only. The final synthetic completion audit must show 48/48 direct mappings, no unresolved implementation finding, green applicable tiers, no drift, and explicit `NOT_RUN_OPERATOR_GATED` for AC-024 authoritative watching and AC-047 live/signing/activation evidence. It must not claim production readiness or live Apple completion.

Disposition: `CORRECTED_PLAN_READY_FOR_REAUDIT`
