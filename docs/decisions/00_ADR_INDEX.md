# ADR Index

| ADR | Decision | Status |
|---|---|---|
| [ADR-001](ADR-001-modular-monolith-two-processes.md) | Modular monolith with separate gateway and worker processes | Accepted |
| [ADR-002](ADR-002-database-identity-and-compatibility-alias.md) | Canonical `my_pa` database identity with existing-database compatibility alias | Accepted with deferred physical alias value |
| [ADR-003](ADR-003-product-owned-user-authored-source-records.md) | Product-owned user-authored source records as a third authority class, distinct from original sources and managed documents | Accepted |
| [ADR-004](ADR-004-mossaic-frontend-nextjs-app-router.md) | MossAIc first-party frontend on Next.js App Router with MSAL-shaped identity and a synthetic development issuer | Accepted |
| [ADR-005](ADR-005-principal-partitioned-capture.md) | Principal-partitioned capture with a durable local operator, admission-time ownership verification, and per-Principal idempotency | Accepted |
| [ADR-006](ADR-006-principal-partitioned-review-and-promotion.md) | Principal-partitioned review and promotion — owner-derived `principal_id` on review cases, assertions, spans, and receipts, principal-scoped reads and decisions, and non-authoritative AI until human disposition | Accepted |
| [ADR-007](ADR-007-principal-partitioned-relationship-and-project-continuity.md) | Principal-partitioned relationship and project continuity — owner-derived `principal_id` on the relationship graph, situations, frames, traces, projects, relationship events, and pulse items; principal-scoped situation/project/timeline reads; and accepted-only continuity surfaces | Accepted |

Later ADRs must identify repository identity, context, decision, consequences, supersession rules, and implementation status.

## Unresolved decisions

Decisions not yet accepted as ADRs are tracked in [`PHASE-00-OPEN-DECISION-LEDGER.md`](../../PHASE-00-OPEN-DECISION-LEDGER.md). A ledger entry records a working default so work can proceed; it does not carry ADR authority. Promote an entry to an ADR when it is accepted.
