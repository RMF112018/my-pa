# Glossary

**BFF** — Backend for Frontend. In MY-PA, server-side Next.js routes adapt browser/session concerns to Python gateway capabilities.

**Capability** — A named application operation exposed through one or more transports. Availability depends on application composition and policy; a name existing in code does not mean a process serves it.

**Canonical source / authoritative source** — A system whose data is treated as authoritative for a fact/content class. Original source providers are read-only by default.

**Disclosure** — Structured information accompanying a result about evidence, coverage, freshness, limitations or trust; not a log dump.

**Drive product intent** — Accepted product/UX intent in the cleaned MY-PA Drive library. It guides what should be built but does not override current executable repository truth.

**Entity** — Principal-scoped Relationship Intelligence identity record and related governed fact plane.

**GSQS** — GoodNotes-specific semantic/evaluation workflow retained under the GoodNotes implementation and runbooks.

**Managed document** — Content MY-PA is authorized to create/revise in a designated managed storage plane. It is distinct from an original read-only source.

**MCV** — Minimum Viable Candidate: the repository's current unreleased development stage.

**MCP** — Model Context Protocol. MY-PA exposes derived application capabilities as tools over local stdio and, when separately configured, authenticated remote transport.

**Principal** — Server-derived acting identity/partition key. Callers must not acquire authority by supplying a Principal field.

**Product-owned record** — User-authored/application-owned canonical record in PostgreSQL under ADR-003; neither an original source write nor a managed-document write.

**Provenance** — Evidence of where a derived assertion/record came from and how it was produced.

**Repository truth** — Current executable technical truth established from the authenticated repository tree, tests, contracts, configuration and runtime evidence.

**Source provider** — Adapter that reads authoritative source content under a bounded read-only contract.

**Worker plane** — Bounded asynchronous processing plane with explicit queue/lease/health semantics.

**Write gate** — Explicit feature/security/authorization condition required in addition to the capability existing in code.
