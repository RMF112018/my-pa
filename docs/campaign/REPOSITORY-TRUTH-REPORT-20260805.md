# Repository Truth Report — RMF112018/my-pa — 2026-08-05

> **Historical record — superseded.** This is a point-in-time record from 2026-08-05 against `main` head `88e8d8193095afa8d903db08324a588a5786908b`. It is superseded by the 2026-08-09 reauthentication against the operating lineage `recovery/pre-20260805-utc-rollback-c9fb513` at `c9fb513a2afadf98f29b6d5ec3ad69db69e5ec1a`, recorded in [`docs/campaign/CAMPAIGN-BRIEF.md`](CAMPAIGN-BRIEF.md). Its branch/PR inventory and sequencing claims are not current. Original text preserved below unchanged.

```yaml
report_id: REPOSITORY-TRUTH-REPORT-20260805
repository: RMF112018/my-pa
remote: https://github.com/RMF112018/my-pa.git
default_branch: main
main_head: 88e8d8193095afa8d903db08324a588a5786908b
main_tree: 418c466b020db1819b575f3206dbbdaf71db7f0a
head_commit_subject: "WP-12C: add application-mediated native-source admission (#43)"
head_commit_date: 2026-08-05T04:36:43-04:00
matches_previously_audited_head: true
open_pull_requests:
  - number: 44
    title: "WP-12E: implement frozen native-source baselines"
    head: bf/wp-12e-frozen-baseline
remote_branches: [main, bf/wp-12b-domain-persistence, bf/wp-12d-native-host-spool, bf/wp-12e-frozen-baseline]
migration_head: 9d5e2f7b4c61
migration_count: 17
runtime: "Python >= 3.12; SQLAlchemy 2 Core; psycopg 3; Alembic; Pydantic 2; PostgreSQL"
test_verification: >
  tests/schema/test_foundation_migration.py and tests/schema/test_head_round_trip.py
  executed 2026-08-05 against PostgreSQL 17.10 (4 passed): full upgrade-from-empty,
  downgrade-to-empty, and head round-trip verified.
```

## 1. Current architecture summary

The repository is a governed Python 3.12 backend in **MCV (Minimum Viable
Candidate)** development for a single-operator personal knowledge layer,
built to strict layering rules (`AGENTS.md` section 4):

- `src/my_pa/domain` — pure domain: identity (`Principal`/`PrincipalKind`
  actor model, operations, purposes), capture, knowledge, extraction, audit,
  policy, relationship, native sources, search, connectors, projection.
- `src/my_pa/application` — use cases behind an `ApplicationService`;
  authorization, capabilities, disclosure, commands/queries; depends inward
  on domain contracts and ports only.
- `src/my_pa/infrastructure` — port implementations: persistence
  (SQLAlchemy Core, hand-declared tables in `persistence/tables.py`),
  database engine, jobs/leases, security, providers, telemetry, migration
  control plane.
- `src/my_pa/adapters` — HTTP, MCP, and CLI transports with capability parity.
- `src/my_pa/bootstrap` — settings (`MY_PA_*` env), composition/gateway.
- `apps/` — gateway, worker, CLI entry points.
- `migrations/` — 17 Alembic revisions of **frozen literal DDL** (no
  `target_metadata`); schemas: `core`, `procore`, `email`, `calendar`,
  `contacts`, `financial`, `schedule`, `construction`, `migration_control`
  (legacy corpus + control plane) and `knowledge` (the application's own
  schema: sources, enrollment, jobs, extraction, capture, proposals,
  review/promotion, relationships, native sources, audit).
- `tests/` — tiered suite (FAST database-free unit/contract tiers with fakes
  in `tests/conftest.py`; `@pytest.mark.database` tiers using a
  disposable-database fixture; security, recovery, concurrency, migration,
  end-to-end, non-vacuity/canary tiers).
- Governance: `AGENTS.md` (normative policy), `AI_OPERATING_MANUAL.md`,
  `CLAUDE.md` (router), `docs/00_REPOSITORY_SOURCE_INDEX.md`, ADRs under
  `docs/decisions`, specs under `docs/specs`, `.ai/` agent harnesses and goals.
- CI enforces strict mypy (`src`, `migrations`, `apps`), ruff, and tiered tests.

### Identity model today (the critical gap)

The existing `Principal` (`domain/identity/principal.py`) is an **actor/process
principal** (`operator`, `gateway`, `worker`, `operator_cli`, adapters, model
gateways) with prefixed string IDs (`prn_…`) issued by the composition root.
There is **no user registry, no Entra `(tid, oid)` derivation, no per-user
partitioning, and no multi-user isolation**. `metadata.principal_id` on
requests is explicitly correlation input, not authority. This matches the v4.0
package's greenfield assessment for R0A.

## 2. Retain / adapt vs rebuild vs retire inventory

### Retain and adapt (reusable capability and evidence)

| Asset | Disposition |
|---|---|
| Evidence envelopes, immutable versioning, exact source spans | Retain |
| Proposals, Review cases, decisions, promotion receipts | Retain |
| Source authority & provenance model; read-only source rule | Retain |
| Capture pipeline, idempotency keys, request fingerprints | Retain; add `principal_id` partition (WP-03) |
| PostgreSQL/Alembic discipline (frozen-literal revisions, round-trip tests) | Retain as the campaign's migration doctrine |
| Bounded jobs, leases, retry, recovery, quarantine | Retain |
| Audit redaction, no-payload audit events, safe disclosure | Retain |
| Application-service reuse across HTTP/MCP/CLI | Retain where compatible |
| Synthetic fixtures, non-vacuity/canary tests, disposable-database fixture | Retain |
| Relationship identity concepts (WP-9 substrate) | Retain; partition per Principal (WP-06) |

### Rebuild or materially reshape

| Asset | Disposition |
|---|---|
| Principal identity & authorization (actor-only today) | Rebuild: `UserAccount`/Principal registry from Entra `(tid, oid)` (WP-01) |
| Persistence partitioning (no per-user column anywhere) | Reshape: universal `principal_id` partition + fail-closed predicates (WP-01 foundation, then per-table migrations) |
| Connector profiles & token cache | Rebuild: per-Principal encrypted token cache keyed `(tid, oid)` (WP-07) |
| Graph adapters, baseline/delta/webhooks/drift recovery | Build new against v4.0 connector spec (WP-07) |
| Offline capture ownership & encryption policy | Rebuild Principal-bound (WP-04) |
| API route structure | Reshape for authenticated multi-user access |
| First-party frontend & PWA | Build new: MossAIc Next.js App Router + MSAL (WP-02) |
| Deployment composition | Reshape (later, operator-gated) |
| Any behavior permitting cross-Principal reads/writes | Rebuild; blocking defect if found |

### Retire only after replacement evidence and separate operator authorization

| Asset | Disposition |
|---|---|
| Swift Apple source host (`native/`) | Retire later; not destructively removed now |
| Apple-specific native bridge vocabulary/control plane | Retire later after provider-neutral replacement |
| TCC/signing/notarization/always-on-Mac assumptions | Retire later |
| Apple watcher simulation without provider-neutral value | Retire later |
| Tests that would require cross-Principal access | Retire when superseded |

## 3. Gap analysis vs v4.0 requirements

| v4.0 requirement | Current state | Gap |
|---|---|---|
| R0A `UserAccount`/Principal registry from `(tid, oid)` | Absent | Full build (WP-01, this campaign's first implementation package) |
| Universal `principal_id` partition, fail-closed predicates | Absent | Foundation in WP-01; retrofit of existing knowledge tables sequenced in later WPs |
| Cross-Principal negative tests | Absent | WP-01 |
| Entra/MSAL auth boundary (synthetic tokens first) | Absent | WP-01 contracts; WP-02 frontend wiring |
| Next.js App Router + TS + Tailwind + MSAL frontend | Absent (frontend deferred by prior operator instruction; now in scope per v4.0) | WP-02 |
| Product-owned Capture partitioned per Principal | Capture exists, single-operator | WP-03 reshape |
| Offline Principal-bound capture queue | Absent | WP-04 |
| Proposal/Review/promotion | Substantially present, single-operator | WP-05 adapt + partition |
| Relationship/Project continuity | Identity substrate present | WP-06 adapt + partition |
| Microsoft 365 Graph read connectors | Absent (fixture/native providers only) | WP-07 |
| Bounded AI (context manifests, no autonomous promotion) | Policy skeleton present | WP-08 |
| Microsoft To-Do write projection | Absent (`ExternalTaskBinding` replaces Apple binding) | WP-09 |

## 4. Constraints carried forward

- `AGENTS.md` minimal-implementation and scope rules govern every work package.
- No live credentials, live personal data, production deployment, or
  destructive Apple/native retirement anywhere in the campaign.
- Migration revisions must be frozen-literal, round-trip (upgrade-from-empty /
  downgrade-to-empty) tested, and emit exactly the objects they name.
- Open PR #44 (`WP-12E`) and the three `bf/*` branches belong to the pre-v4
  native-source line; this campaign does not modify or close them.
