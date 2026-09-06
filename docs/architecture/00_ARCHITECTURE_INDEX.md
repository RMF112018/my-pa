# Architecture Index

Current architecture is documented here:

- [`system-overview.md`](system-overview.md) — processes, boundaries and end-to-end flow.
- [`backend-domain.md`](backend-domain.md) — Python layering, dependency direction and extension points.
- [`frontend-bff-pwa.md`](frontend-bff-pwa.md) — browser/PWA/BFF architecture.
- [`data-and-storage.md`](data-and-storage.md) — authority classes, PostgreSQL, source and managed storage.
- [`mcp-and-agent-integration.md`](mcp-and-agent-integration.md) — MCP surfaces and capability derivation.
- [`authentication-security.md`](authentication-security.md) — Principal/session/auth and security boundaries.
- [`deployment-runtime.md`](deployment-runtime.md) — process/container/NAS runtime topology.

Durable decisions are indexed by [`../decisions/00_ADR_INDEX.md`](../decisions/00_ADR_INDEX.md).

`system-context.md`, `module-boundaries.md`, and `data-authority.md` are retained historical architecture snapshots. They are no longer the current developer entry points because they contain old exact-head/campaign reconciliation narrative.
