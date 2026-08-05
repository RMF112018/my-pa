# WP-12 Apple Mail, Calendar & Contacts repository truth

Disposition: `CORRECTIVE_WORK_READY_FOR_REAUDIT`

## 1. Scope and authority

- Goal: `WP-12-APPLE-MCC`
- Authorization: `AUTH-WP12-20260804-OPERATOR-001`
- Objective: plan and then implement the 48 `NAPDCB-AC-*` requirements for a synthetic-only Apple Mail, Calendar & Contacts source integration before MCV completion, while WP-10 and WP-11 remain deferred.
- Repository: `RMF112018/my-pa`; repository-relative path: `.`
- Branch/upstream: `main` / `origin/main`
- HEAD: `634890e0bc089294a242be176280c09766bac493`
- Tree: `5cc28830cc213ec9c45441376202d9476ccfed05`
- Worktree at pre-edit: clean; local `main` equalled `origin/main`.
- Permitted now: repository planning and implementation, synthetic fixtures/fakes, disposable isolated PostgreSQL, routine branch/PR/review/merge lifecycle under `AGENTS.md` section 8.1.
- Prohibited: live Apple account or personal-data access; TCC, entitlement, credential or signing mutation; watcher activation; external-model disclosure; deployment/production; destructive retention; source mutation; risk acceptance; reactivating WP-10 or WP-11.

## 2. Repository state

The repository implements a Python modular monolith with gateway, worker and operator CLI surfaces, 15 public capabilities, a read-only pull `SourceProvider`, durable source enrollment/extraction/job/audit planes, Capture proposal/Review, and fixture-only relationship profiles. Alembic head is `7f2a9d6c4e18`. No frontend, native macOS host, Apple adapter, Apple configuration plane, protected spool, Apple sync run, per-bucket checkpoint, or watcher registration exists.

The existing source plane is reusable but not sufficient unchanged. `knowledge.sources` and `source_objects` provide opaque stable identities and version history, but their current provider vocabulary and pull adapter composition are fixture/filesystem-specific. Existing `jobs` is enrollment-shaped and `capture_jobs` is Capture-shaped. WP-12 therefore needs a bounded native-source control plane while continuing to write admitted evidence through the existing provider-neutral source object/version and proposal/Review planes.

## 3. Evidence-access limitations

- No live Apple API, Mail, EventKit, Contacts, TCC, signing, notarization, or runtime evidence was accessed or authorized.
- The feature package's package-time repository basis (`907c2bd…`, PR #36) and observed canonical version (2.2) are historical. Current repository and canonical v2.3 evidence supersede those fields.
- Drive text fetches and listings were used only for non-sensitive published package artifacts. No credentials or personal content were read.
- The canonical crosswalk groups `NAPDCB-AC-015–022` as baseline integrity, while the governing feature criterion 015 is membership separation. The exact numbered feature criterion controls; the crosswalk grouping is a summary defect.
- The feature package contains 25 package decisions and 14 original open-decision prompts. Canonical v2.3 explicitly reconciles these to 15 `MYPA-NAPDCB-D-*` decisions and 10 `NAPDCB-OP-*` operator decisions. The canonical counts control current planning.

## 4. System/component map

| Surface | Current evidence | WP-12 use/gap |
|---|---|---|
| Domain/ports | `domain/source`, `contracts/ports.py` | Reuse source authority; add native bridge/account/bucket/run/checkpoint values and admission ports. |
| Authorization | `application/authorization.py`, policy/audit | Extend closed capability/purpose maps; configuration and lifecycle commands remain operator-authorized and exact-scope bound. |
| Persistence | `persistence/tables.py`, source registry, jobs, proposals, Review | Reuse source objects/versions, evidence lineage, audit, proposals and Review; add native control-plane tables and a native job plane. |
| Providers | fixture pull provider and synthetic personal fixture | Add synthetic native adapter contracts; live Swift adapters are separately gated. |
| Gateway | loopback Starlette HTTP, MCP stdio, CLI | Add same application use cases and same-origin UI/API; no new external listener. |
| Worker | PostgreSQL lease loop | Add native baseline/reconcile/watch-simulation plane with monotonic checkpoint rules. |
| Frontend | absent | Add only the Apple source configuration/status module. No WP-10 Capture PWA/offline behavior. |
| Native host | absent | Add source-built Swift protocol/adapters before application integration; live signing/TCC/service activation stays gated. |
| Schema | 14 revisions, head `7f2a9d6c4e18` | Forward-only native control-plane migration(s) add simulation-only watcher/receipt evidence types and tables plus a closed fail-closed live-activation gate. They do not create live-attestation, live-registration, authoritative-watcher, or live activation-receipt types or tables; those remain future, separately operator-authorized work. Test empty-to-head and prior-head-to-head. |
| CI | FAST, dependency-floor, disposable PostgreSQL | Add deterministic frontend/native contract checks and affected database/recovery suites; no personal canary. |

## 5. Verified facts

1. Feature package identity is `MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087`, Drive folder `13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5`.
2. Its package manifest is Drive ID `1gBPfHAtPClqFoT7skQJlpp9Sf2L72q_J`, terminal SHA-256 `cc7fdf665a844adcddef5beb2c8cb52d2bbd7d69b3c7a79e0babc1b5a793b175`; it reports 16/16 substantive member raw readbacks matching.
3. Direct Drive listing found exactly 18 top-level package files: 00–15, `PACKAGE_MANIFEST.json`, and `PUBLICATION_RECEIPT.md`.
4. Canonical product package `MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006` is v2.3 in folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`.
5. Its manifest is Drive ID `1xxQG_fsUlTxX7VRXOCm8SSCjYF2xPV1j`, 13,899 bytes, SHA-256 `d1b3f7a91fbe07d11f9100346f0ef65f0e3576d35dcf27708f585bb5e6ca038a`.
6. The repository mirror recomputed at this HEAD matches all 20 non-manifest member byte counts/hashes and the exact manifest byte count/hash.
7. Counts recomputed from current authoritative sources: 48 acceptance criteria; 15 canonical decisions; 10 canonical open operator decisions; 13 canonical feature risks.
8. WP-10 and WP-11 remain deferred. The operator's current authorization promotes WP-12 ahead of them without reactivating either.

## 6. Claims not verified

- A general-purpose Mail acquisition mechanism is feasible under the final macOS sandbox/TCC model.
- Any host is signed, notarized, installed, registered, or compatible with a target Mac.
- Any live Apple account, mailbox, calendar, contact collection, or watcher exists.
- A 15-minute live freshness objective is achievable.
- Production activation, deployment readiness, or personal-data eligibility.

## 7. Assumptions and unknowns

See `assumptions-and-unknowns.md`. All live/operator choices are represented as fail-closed configuration or activation gates; none blocks synthetic repository implementation.

## 8. Acceptance-criteria gap matrix

`gap-matrix.yaml` contains all 48 exact criteria. Every row directly records components, one final-discharge slice, foundation slices, test tier, evidence method/artifact, and blocking dependencies. The narrative plan's seven final-criteria lists were mechanically expanded and compared with the matrix: 48 unique criteria, zero duplicates, zero omissions, and exact slice equality. Slice order is A → B → D → C → E → F → G → H. AC-037 has C as its only final owner; B provides non-dischargeable schema foundation only. Existing source, audit, proposal and Review components are reusable foundations, not acceptance of the Apple feature.

## 9. Risks and contradictions

- Critical: a future authoritative watcher must never become authoritative without a reconciled durable checkpoint and a separately authorized live activation receipt.
- Critical: a synthetic adapter, simulation state or simulation receipt must be structurally unable to satisfy the authoritative watcher/live-attestation gate. The current authorized build contains no live activation writer or authoritative `watching` transition.
- Critical: a native helper must never receive PostgreSQL credentials or bypass application authorization.
- Critical: imported content is untrusted data and grants no model/tool/source authority.
- High: current source registry language is filesystem-specific and must be generalized without weakening fixture containment.
- High: Mail feasibility is unknown and must not block independent Calendar/Contacts synthetic work or be papered over by a legacy AppleScript/NAS design.
- High: adding a frontend must not silently implement WP-10 or its offline Capture policy.
- Documentation contradiction: canonical acceptance range grouping shifts criterion 015; exact feature criteria remain authoritative.

## 10. Recommended next gate

Re-audit the corrected architecture/plan against this exact HEAD and the new artifact hashes. If it passes, execute the dependency order in `wp-12-architecture-acceptance-plan.md`, one bounded PR and one independent exact-head review at a time. A failed Mail live-feasibility result narrows live Mail activation; it does not authorize legacy architecture and does not block synthetic Calendar/Contacts implementation.

## 11. Bounded disposition

`CORRECTIVE_WORK_READY_FOR_REAUDIT`
