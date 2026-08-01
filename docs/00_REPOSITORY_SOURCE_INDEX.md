# Repository Source Index

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
- [`docs/architecture/system-context.md`](architecture/system-context.md) — actors, external systems, trust and authority boundaries.
- [`docs/architecture/module-boundaries.md`](architecture/module-boundaries.md) — module ownership, dependency direction, and split triggers.
- [`docs/architecture/data-authority.md`](architecture/data-authority.md) — data ownership, authority, lifecycle, and disclosure.

## Specifications

- [`docs/specs/mcv-read-only-vertical-slice.md`](specs/mcv-read-only-vertical-slice.md) — read-only Minimum Viable Candidate (MCV) capability, error, and disclosure contract.

## Plans

- [`docs/plans/mcv-completion-plan.md`](plans/mcv-completion-plan.md) — current gap audit and integrated work-package plan: what the repository contains, what the accepted specification requires, and which dispatched workstreams are deferred and why.

## Security

- [`docs/security/threat-model.md`](security/threat-model.md) — entry points, abuse cases, controls, and residual risk.

## Migration

- [`docs/migration/00_MIGRATION_INDEX.md`](migration/00_MIGRATION_INDEX.md) — owning index for `GOAL-MYPA-POSTGRESQL-MIGRATION-001` governance, identity, and phase records, and for the completed migration result. Records and routing only; it is not itself a database, DDL, ETL, or deployment surface.

## Open decisions

- [`PHASE-00-OPEN-DECISION-LEDGER.md`](../PHASE-00-OPEN-DECISION-LEDGER.md) — unresolved Phase 00 decisions and their defaults.
- [`README-PHASE-00-DOCUMENT-PACKAGE.md`](../README-PHASE-00-DOCUMENT-PACKAGE.md) — Phase 00 document package provenance and acceptance status.

The Phase 00 documents were integrated byte-faithfully from their authoring session, so their front matter and prose describe that session rather than this repository. Read them with three corrections: they are now in the repository despite `supersession_state: NEW_CANDIDATE_NOT_IN_REPOSITORY`; the routing updates they defer to a later change are the same change that placed them; and the SHA-256 values in the package README identify the Drive source bytes before encoding normalization, not the files beside it. The in-repository hashes are recorded in the integrating pull request. `docs/specs/mcv-read-only-vertical-slice.md` is the exception: its front matter and section 1 have since been reconciled to this repository, and its normative sections are unchanged.

## Governance review

- [`docs/governance/GOVERNANCE-AUDIT-MYPA-MCV-20260730.md`](governance/GOVERNANCE-AUDIT-MYPA-MCV-20260730.md) — evidence basis, GitHub management plan, test policy rationale, and three-day MCV workflow for the current governance candidate.

## Working records

Use GitHub issues for bounded work, pull requests for review and acceptance evidence, Actions for automated checks, and releases for versioned candidate notes. Add repository documentation only when it defines durable behavior, architecture, security, operations, or developer workflow.
