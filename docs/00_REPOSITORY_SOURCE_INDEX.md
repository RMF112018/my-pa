# Repository Source Index

## Operating lineage

The current remediation candidate is `bf/ri-remediation-20260829`, forked from `main@8d5e1d01b209eae1169c4f60c79c6c2c2dc89eb4` — `main`'s head, and the merge commit of PR #163. Its exact moving head/tree and clean-worktree evidence belong in its pull request and closeout report rather than embedded self-referentially here.

Corrected 2026-08-29. This paragraph named `bf/pilot-blocker-remediation`, forked from authenticated `main@9b35476b70fe4fbc03bb8f9835d93c1b71089bbe`, as the **current** candidate. It is not, and had not been for some time: that branch's last commit is `11936dd` (2026-08-12), it merged as PR #73 on 2026-08-12, and it now sits 100 commits behind `main`. It is **retained** as preserved campaign history, together with the older `recovery/pre-20260805-utc-rollback-c9fb513` lineage; both remain classified in [`docs/campaign/PILOT-BLOCKER-REMEDIATION-20260812.md`](campaign/PILOT-BLOCKER-REMEDIATION-20260812.md), which keeps its name and content, and neither is the operating candidate. `tests/architecture/test_readme_state_claims.py` guards that this history is not blurred away; the correction is to the word "current", not to the record.

## Normative governance

- [`AGENTS.md`](../AGENTS.md) — principal repository and coding-agent policy.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — concise human contribution workflow.
- [`SECURITY.md`](../SECURITY.md) — security, privacy, and vulnerability policy.

`AI_OPERATING_MANUAL.md`, `CLAUDE.md`, and `.ai/project-sources/00_AEOS_MASTER_INDEX.md` are compatibility routers and contain no independent policy.

## Product and architecture

- [`README.md`](../README.md) — product orientation and current repository state.
- [`docs/architecture/00_ARCHITECTURE_INDEX.md`](architecture/00_ARCHITECTURE_INDEX.md) — architecture routing.
- [`docs/decisions/00_ADR_INDEX.md`](decisions/00_ADR_INDEX.md) — accepted decision routing.
- [`docs/decisions/ADR-001-modular-monolith-two-processes.md`](decisions/ADR-001-modular-monolith-two-processes.md) — modular monolith with gateway and worker processes.
- [`docs/decisions/ADR-002-database-identity-and-compatibility-alias.md`](decisions/ADR-002-database-identity-and-compatibility-alias.md) — logical database identity and deferred physical alias.
- [`docs/decisions/ADR-003-product-owned-user-authored-source-records.md`](decisions/ADR-003-product-owned-user-authored-source-records.md) — the third authority class: records the user creates inside `my-pa`, append-only, and not a managed-document write.
- [`docs/decisions/ADR-004-mossaic-frontend-nextjs-app-router.md`](decisions/ADR-004-mossaic-frontend-nextjs-app-router.md) — Next.js App Router PWA as the MossAIc frontend, with a synthetic identity provider until a real Entra registration exists.
- [`docs/decisions/ADR-005-principal-partitioned-capture.md`](decisions/ADR-005-principal-partitioned-capture.md) — Principal-partitioned capture with a durable local operator, admission-time ownership verification, and per-Principal idempotency.
- [`docs/decisions/ADR-006-principal-partitioned-review-and-promotion.md`](decisions/ADR-006-principal-partitioned-review-and-promotion.md) — Principal-partitioned review and promotion: owner-derived `principal_id` on review cases, assertions, spans and receipts, Principal-scoped reads and decisions, and non-authoritative AI until human disposition.
- [`docs/decisions/ADR-007-principal-partitioned-relationship-and-project-continuity.md`](decisions/ADR-007-principal-partitioned-relationship-and-project-continuity.md) — Principal-partitioned relationship and project continuity: owner-derived `principal_id` on the relationship graph, situations, frames, traces, projects, relationship events and pulse items.
- [`docs/decisions/ADR-008-nas-runtime-topology.md`](decisions/ADR-008-nas-runtime-topology.md) — accepted NAS runtime placement, filesystem authority, ingress, auth, image-platform, restart, and Mac Apple-TCC split.
- [`docs/decisions/ADR-009-oauth-refresh-token-families.md`](decisions/ADR-009-oauth-refresh-token-families.md) — rotating opaque refresh-token families for remote MCP; 1-hour access tokens remain; existing clients refresh-disabled by default.
- [`docs/decisions/ADR-010-intelligence-artifact-report-plane.md`](decisions/ADR-010-intelligence-artifact-report-plane.md) — product-owned Intelligence Artifact / Report plane: immutable artifacts, cycle-run identity, staged pipeline lineage.
- [`docs/architecture/system-context.md`](architecture/system-context.md) — actors, external systems, trust and authority boundaries.
- [`docs/architecture/module-boundaries.md`](architecture/module-boundaries.md) — module ownership, dependency direction, and split triggers.
- [`docs/architecture/data-authority.md`](architecture/data-authority.md) — data ownership, authority, lifecycle, and disclosure.
- [`native/apple-source-host/README.md`](../native/apple-source-host/README.md) — source-built Swift protocol-v1 core plus separately bounded `AppleSourceHostPlatform` shipping product: streamed/bounded Calendar and minimum-key Contacts, bounded Tasks, closed ScriptingBridge Mail reads, recurrence identity, and owner-only atomic spool. Its executable has a descriptor-relative content-free dry-run and a distinct expiring-grant, one-page read/envelope/handoff path whose bridge/request/envelope IDs are issued by the authenticated Python application. It cannot request permission, reach a database/network, or mutate a source; the live path is implemented but was not executed.
- [`web/README.md`](../web/README.md) — Next.js/PWA runtime, development modes, and validation commands.
- [`web/src/contracts/README.md`](../web/src/contracts/README.md) — frontend contract ownership and generated-shape boundary.

## Specifications

- [`docs/specs/README.md`](specs/README.md) — owning index for specifications, and the provenance and verification strength of every mirrored package below.
- [`docs/specs/mcv-read-only-vertical-slice.md`](specs/mcv-read-only-vertical-slice.md) — read-only Minimum Viable Candidate (MCV) capability, error, and disclosure contract.
- [`docs/specs/canonical-product-definition/`](specs/canonical-product-definition/00_README.md) — mirror of the canonical whole-product definition (`MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006`, Drive folder `1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq`). **Ratified 2026-08-02 by direct operator instruction**, which is the instrument — the package's own `CURRENT_CANONICAL_PRODUCT_DEFINITION` is a self-declared status and is not ratification. See [`docs/plans/mcv-completion-plan.md`](plans/mcv-completion-plan.md) `D-19` and section 15, and [`docs/specs/README.md`](specs/README.md) for provenance. Supersedes `my-pa vNext` for current whole-product definition. Grants no implementation authority. **Revised in place 2026-08-02** by `REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`, which folded Remote Quick Capture into the MCV across eight artifacts; the mirror is refreshed and re-verified, and the reconciliation is [`docs/plans/mcv-completion-plan.md`](plans/mcv-completion-plan.md) section 16 with decisions `D-29` through `D-33`. The revision moved no `version` field, so staleness must be tested by hash rather than by version. **Revised in place again 2026-08-02** by `REQ-MYPA-CANONICAL-PRODUCT-NATIVE-REMINDERS-INTEGRATION-20260802T150100Z`, which took the package to version 2.2 and admitted **Native Apple Reminders Integration** to the MCV across ten artifacts. **Revised in place a third time on 2026-08-04** by `REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z`, which took the package to version 2.3 and revised 17 of its 21 numbered artifacts. The mirror and four selected control records are refreshed and byte-verified. The added Apple Mail, Calendar & Contacts feature yields a provisional WP-12 after WP-10 and WP-11, but WP-12 planning requires separate operator authorization. It has no pre-MCV or post-MCV disposition yet, and its package grants no implementation or live-data authority.
  - Native Apple Reminders control artifacts mirrored beside the specifications: `CANONICAL-ARTIFACT-DISPOSITION-…`, `PUBLICATION-RECEIPT-…`, `READBACK-VERIFICATION-…`, and `COORDINATION-ROUNDTRIP-RECEIPT-…` for `REQ-MYPA-CANONICAL-PRODUCT-NATIVE-REMINDERS-INTEGRATION-20260802T150100Z`. Their Drive home is control subfolder `NATIVE-REMINDERS-INTEGRATION-20260802T150100Z`. Its coordination request and response are not mirrored, following the same rule the two earlier roundtrips followed.
  - Apple Mail, Calendar & Contacts control artifacts mirrored beside the specifications: `CANONICAL-ARTIFACT-DISPOSITION-…`, `PUBLICATION-RECEIPT-…`, `READBACK-VERIFICATION-…`, and `COORDINATION-ROUNDTRIP-RECEIPT-…` for `REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z`. Their Drive home is control folder `1PLw2r7MmNXKi2pZxaIRiXTNVg-itiZ99`; its coordination request and response remain external.
  - RQC control artifacts mirrored beside the specifications: `CANONICAL-ARTIFACT-DISPOSITION-…`, `PUBLICATION-RECEIPT-…`, and `COORDINATION-ROUNDTRIP-RECEIPT-…` for `REQ-MYPA-CANONICAL-PRODUCT-RQC-INTEGRATION-20260802T114700Z`. Their Drive home is control subfolder `RQC-INTEGRATION-20260802T114700Z` (`1t6fzDfHVrLQe6Wd2qjAtZ2ll--fYNPaF`).
  - Indexed by identity only, not mirrored, per `D-22`: the RQC coordination request (`1yhkRgk6qcd2V-PWucS7WuRrbCO72FVAn`) and response (`1qVhuUeeApFEGQQrq22lUzQwYhkQWyXN7`), and the governing **Remote Quick Capture feature package** `MYPA-REMOTE-QUICK-CAPTURE-FEATURE-PACKAGE-20260802-001` (Drive folder `1lDSkTldgSkaRfJ3v9h-U10lCe-Lmwzsv`), which is named by `MYPA-RQC-D-007` and has not been examined.
- [`docs/specs/relationship-intelligence-v0.2.md`](specs/relationship-intelligence-v0.2.md) — the Relationship Intelligence product specification, promoted into scope 2026-08-01 and **still the current requirements source**; see the successor notice at the top of the file. Corrected 2026-08-29: this entry ended "Implementation not authorized", which contradicted both the README's current-state section and the delivered work — the entity plane, Relationship Memory, identity correction, identity history and re-enrichment are all in the tree and in the Alembic chain. Bounded repository implementation against v0.2 **is** authorized and has shipped; what remains unauthorized is deployment, production activation, live personal data, credential/grant/OAuth change and source-system mutation (`AGENTS.md` section 5). Forty of v0.2's seventy `RI-AC-NNN` criteria are scored; `RI-AC-041` … `RI-AC-070` are unscored — see [`docs/plans/relationship-intelligence-implementation-plan.md`](plans/relationship-intelligence-implementation-plan.md) section 3.
- [`docs/specs/relationship-memory-v0.1.md`](specs/relationship-memory-v0.1.md) — **implemented contract**, and the only file here that describes a Relationship Intelligence capability the repository actually serves. The Relationship Memory plane: ten semantic kinds bound to a generalized Entity, an immutable version chain, nine `relationship_memory.*` capabilities under the `relationship_memory_read` and `relationship_memory_authoring` purposes of their own, and eight tables in `knowledge`. Composed off by default behind `MY_PA_RELATIONSHIP_MEMORY_ENABLED`, which additionally requires the entity plane. Derived from the accepted package `MYPA-RELATIONSHIP-MEMORY-ENTITY-NOTES-20260822-001` (Drive folder `1QraevD7durAYrSaTcOBN2YFMnRZkHP6c`); that package remains the product-intent record and this file remains executable truth. Subordinate to `relationship-intelligence-v0.2.md`, whose section 9.10 it implements, and governed by ADR-003 rather than by a new authority class.
- [`docs/specs/relationship-intelligence-v0.3.md`](specs/relationship-intelligence-v0.3.md) — **DEMOTED 2026-08-20. Not a requirements source and governs nothing.** The operator has stated they do not know where it came from; it carries no publisher receipt and its `governing_plan`/`governing_audit` identifiers appear nowhere in this repository. Retained as an artifact. `relationship-intelligence-v0.2.md` is the requirements source.
  - Corrected 2026-08-19: these two entries read "mirror of the **controlling** … specification, current as of …" and "**Superseded lineage evidence**, not a current requirements source; see the notice at the top of the file." The second cited that notice as its authority while stating the reverse of what the notice says. Both now match the notice and v0.3's own front matter.
- [`docs/specs/quick-capture/`](specs/quick-capture/00_README.md) — mirror of the Quick Capture feature package, promoted into scope 2026-08-01 and admitted by ADR-003.

Current authority correction to the historical final sentences in the canonical-package entry above: direct authorization `AUTH-WP12-20260804-OPERATOR-001` now promotes bounded synthetic WP-12 repository implementation ahead of deferred WP-10/WP-11. The package itself still grants no authority; the operator authorization and its limits are recorded in [`docs/plans/mcv-completion-plan.md`](plans/mcv-completion-plan.md) `D-105` through `D-107`.

Not mirrored, routed by identity only: the **Frontier NAS MCP Connector** feature package (`MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086`, Drive folder `1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa`). It became canonical product scope on 2026-08-02 but drives no planned work package; see `docs/plans/mcv-completion-plan.md` `D-22`.

Also indexed by identity only: the **Native Apple Personal Data Capture Bridge**, user-facing **Apple Mail, Calendar & Contacts** (`MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087`, Drive folder `13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5`). It is active only for bounded synthetic repository implementation under `AUTH-WP12-20260804-OPERATOR-001`; live personal data, TCC, credentials, signing, activation, source mutation, deployment, production, destruction, and risk acceptance remain unauthorized. See `docs/plans/mcv-completion-plan.md` `D-105` through `D-107`.

## Plans

- [`docs/plans/mcv-completion-plan.md`](plans/mcv-completion-plan.md) — current gap audit and integrated work-package plan: what the repository contains, what the accepted specification requires, and which dispatched workstreams are deferred and why.
- [`docs/plans/relationship-intelligence-implementation-plan.md`](plans/relationship-intelligence-implementation-plan.md) — the Relationship Intelligence implementation plan: current-state identity, work-package sequencing, the acceptance-criteria ledger against v0.2's seventy criteria (`RI-AC-001` … `RI-AC-040` scored; `RI-AC-041` … `RI-AC-070` unscored), and the evidence table whose tier, corpus and suite figures are bound to collection by `tests/architecture/test_claimed_test_counts_match_collection.py`. Routed here 2026-08-29: it was reachable from `ops/runbooks/relationship-intelligence.md` and from the demoted v0.3 documents, and from no index in `docs/`.
- [`docs/testing/relationship-intelligence-final-completion.md`](testing/relationship-intelligence-final-completion.md) — campaign `MYPA-RI-FINAL-COMPLETION-CAMPAIGN-20260828-001` work-package, capability, acceptance, validation, and operator-only-action traceability. This is the current campaign-state record; [`docs/campaign/CAMPAIGN-BRIEF.md`](campaign/CAMPAIGN-BRIEF.md) is not, and the README no longer routes to it as though it were.

## Campaign

- [`docs/campaign/PILOT-BLOCKER-REMEDIATION-20260812.md`](campaign/PILOT-BLOCKER-REMEDIATION-20260812.md) — current candidate authority record: objective, authenticated `main` basis, selective lineage reconciliation, blocker-closure matrix, safety boundaries, validation record, and exact-head independent-review gate.
- [`docs/campaign/CAMPAIGN-BRIEF.md`](campaign/CAMPAIGN-BRIEF.md) — historical/superseded 2026-08-09 recovery-lineage snapshot through WP-03. It is retained for traceability and is not authority for present campaign state, work selection, or repository lineage.
- [`docs/campaign/WORK-PACKAGE-MAP.md`](campaign/WORK-PACKAGE-MAP.md) — historical: the superseded Moss v4.0 campaign's work-package sequencing (WP-00 through WP-09). Superseded by `MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001`; see the banner at the top of the file.
- [`docs/campaign/RATIFICATION-MYPA-MOSS-V4-20260805.md`](campaign/RATIFICATION-MYPA-MOSS-V4-20260805.md) — historical: the 2026-08-05 product-package ratification record for the superseded Moss v4.0 campaign.
- [`docs/campaign/REPOSITORY-TRUTH-REPORT-20260805.md`](campaign/REPOSITORY-TRUTH-REPORT-20260805.md) — historical: the 2026-08-05 repository truth report against `main` head `88e8d81…`, superseded by the 2026-08-09 reauthentication against the recovery lineage.

## Security

- [`docs/security/threat-model.md`](security/threat-model.md) — entry points, abuse cases, controls, and residual risk.

## Operations

Running the local candidate on one machine. A procedure under `ops/runbooks/` is normally written only after it has been executed. An explicitly commissioned pre-execution procedure must label itself unexecuted, as the RI final-completion WP-08/WP-09 procedures do — and as section 10 of [`ops/runbooks/relationship-intelligence.md`](../ops/runbooks/relationship-intelligence.md) now does for the NAS `worker-reenrichment` service, whose definition is recorded there as prepared and **not** executed because the NAS gates require live `container_id`/`image_id` deployment evidence that no campaign here is authorized to produce. Deployment, production activation, and destructive data operations remain operator-gated (`AGENTS.md` section 5).

- [`docs/operations/mcv-limitations.md`](operations/mcv-limitations.md) — what the MCV slice does **not** do, each limitation citing the test or measurement that bounds it. Read this before reading the runbooks as a statement of capability.
- [`docs/operations/goodnotes-local-source.md`](operations/goodnotes-local-source.md) — manifest-indexed read-only GoodNotes source, bounded local OCR JSON contract, provenance/Review/search flow, and operator-gated live boundaries.
- [`ops/runbooks/README.md`](../ops/runbooks/README.md) — owning index for the operational runbooks. Read it rather than this line for the list: `ls ops/runbooks/` holds seventeen runbooks beside that README, and the five this entry used to name (the database, the worker, the gateway, the other two transports, and the end-to-end operator sequence) were the set as it stood when the line was written. Corrected 2026-08-19: an enumeration that reads as exhaustive and is not is how [`ops/runbooks/relationship-intelligence.md`](../ops/runbooks/relationship-intelligence.md) — the operator document recording that the entity plane is off by default and that its governance queue can be read but not worked — became reachable from no index in `docs/`.
- [`ops/goodnotes/gsqs/README.md`](../ops/goodnotes/gsqs/README.md) — Gate B GSQS labeled semantic corpus (`gsqs-v2` review target; `gsqs-v1` rejected for B0), independent evaluator, unused B0 harness, and handwriting-admission path. `MEASURED_B0` is not established.
- [`apps/cli/README.md`](../apps/cli/README.md) — the four operator programs: the capability transport, the source configuration plane, the runtime probe, and the migration control plane.
- [`ops/postgres/README.md`](../ops/postgres/README.md) — the PostgreSQL instance itself: image, tuning, locale, collation contract, cluster-creation settings, and reset procedure.
- [`ops/compose/README.md`](../ops/compose/README.md) — the container definition the instance is started from.
- [`ops/nas/README.md`](../ops/nas/README.md) — non-deploying NAS runtime contract and the NAS-01 through NAS-10 implementation boundary.

## Schema, fixtures, and evidence

- [`migrations/README.md`](../migrations/README.md) — the Alembic chain: what each revision owns and where the migration load sits in the sequence.
- [`migrations/versions/README.md`](../migrations/versions/README.md) — the revision files themselves, and the naming they follow.
- [`src/my_pa/infrastructure/database/README.md`](../src/my_pa/infrastructure/database/README.md) — the engine, its pool, and the health check the runtime probe calls.
- [`fixtures/mcv/README.md`](../fixtures/mcv/README.md) — the synthetic corpus the read-only vertical slice is proven over. Synthetic throughout; `P00-OD-009` is open and no live root is configured.
- [`fixtures/remote-capture/README.md`](../fixtures/remote-capture/README.md) — the synthetic, principal-free iOS Shortcut request contract for Remote Capture; it contains no credential or live endpoint.
- [`evidence/README.md`](../evidence/README.md) — owning index for acceptance and completion evidence.
- [`evidence/completion/README.md`](../evidence/completion/README.md) — the completion records themselves, with their Drive provenance.

## Migration

- [`docs/migration/00_MIGRATION_INDEX.md`](migration/00_MIGRATION_INDEX.md) — owning index for `GOAL-MYPA-POSTGRESQL-MIGRATION-001` governance, identity, and phase records, and for the completed migration result. Records and routing only; it is not itself a database, DDL, ETL, or deployment surface.

## Open decisions

- [`PHASE-00-OPEN-DECISION-LEDGER.md`](../PHASE-00-OPEN-DECISION-LEDGER.md) — unresolved Phase 00 decisions and their defaults.
- [`README-PHASE-00-DOCUMENT-PACKAGE.md`](../README-PHASE-00-DOCUMENT-PACKAGE.md) — Phase 00 document package provenance and acceptance status.
- [`docs/plans/mcv-completion-plan.md`](plans/mcv-completion-plan.md) section 14 — the consolidated list returned to the operator, spanning all three ledgers. Its counts are derived from its own tables and enforced by `tests/architecture/test_open_decision_counts.py`.
- [`docs/specs/canonical-product-definition/15_OPEN_OPERATOR_DECISIONS.md`](specs/canonical-product-definition/15_OPEN_OPERATOR_DECISIONS.md) — the ratified package's own 58 operator decisions: `OP-01` through `OP-30`, `MCP-OP-001` through `MCP-OP-009`, `NAR-OP-001` through `NAR-OP-009`, and `NAPDCB-OP-001` through `NAPDCB-OP-010`. Tracked by the package, not by section 14. This file was **not** revised by the 2026-08-02 Remote Quick Capture roundtrip, so the decisions that revision created are tracked by neither it nor `MYPA-RQC-D-001` through `-008`; two of them are carried by the plan as `O-21` and `O-22`. See section 16. It **was** revised by the 2026-08-02 Native Apple Reminders roundtrip, which added `NAR-OP-001` through `NAR-OP-009`, and again by the 2026-08-04 Apple Mail, Calendar & Contacts roundtrip, which added `NAPDCB-OP-001` through `NAPDCB-OP-010`; neither revision left an equivalent ledger gap.

The Phase 00 documents were integrated byte-faithfully from their authoring session, so their front matter and prose describe that session rather than this repository. Read them with three corrections: they are now in the repository despite `supersession_state: NEW_CANDIDATE_NOT_IN_REPOSITORY`; the routing updates they defer to a later change are the same change that placed them; and the SHA-256 values in the package README identify the Drive source bytes before encoding normalization, not the files beside it. The in-repository hashes are recorded in the integrating pull request. `docs/specs/mcv-read-only-vertical-slice.md` is the exception: its front matter and section 1 have since been reconciled to this repository, and its normative sections are unchanged.

## Governance review

- [`docs/governance/GOVERNANCE-AUDIT-MYPA-MCV-20260730.md`](governance/GOVERNANCE-AUDIT-MYPA-MCV-20260730.md) — evidence basis, GitHub management plan, test policy rationale, and three-day MCV workflow for the current governance candidate.

## Working records

- [`.ai/goals/README.md`](../.ai/goals/README.md) — what a goal directory must record: identity, repository and head, scope and acceptance criteria, authorization boundary, evidence, and final state. Directory presence does not activate a goal.

Use GitHub issues for bounded work, pull requests for review and acceptance evidence, Actions for automated checks, and releases for versioned candidate notes. Add repository documentation only when it defines durable behavior, architecture, security, operations, or developer workflow.
