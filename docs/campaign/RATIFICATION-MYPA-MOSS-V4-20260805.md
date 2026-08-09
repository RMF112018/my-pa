# Product Package Ratification Record — my-pa Moss v4.0

> **Historical record — superseded.** This is a point-in-time record from the 2026-08-05 Moss v4.0 campaign. It is superseded by `MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001` and `MYPA-CANONICAL-PRODUCT-DEFINITION-20260809-009`. Its `main`-head binding and sequencing claims are not current; the current operating lineage is `recovery/pre-20260805-utc-rollback-c9fb513`, recorded in [`docs/campaign/CAMPAIGN-BRIEF.md`](CAMPAIGN-BRIEF.md). Original text preserved below unchanged.

```yaml
record_id: RATIFICATION-MYPA-MOSS-V4-20260805
record_type: PRODUCT_PACKAGE_RATIFICATION
package_id: MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008
package_version: "4.0"
package_sha256: 60e886e9dd19c6d39929990cd939ab1eb8c9c11eea8b0fb8faffac971516d6a4
package_bytes: 101104
status_at_publication: CANONICAL_PRODUCT_CANDIDATE_FOR_OPERATOR_RATIFICATION
ratified_status: RATIFIED_FOR_IMPLEMENTATION_BASELINE
ratification_date: 2026-08-05
ratification_authority: >
  Operator instruction embedded in
  PROMPT-MYPA-MOSS-FULL-IMPLEMENTATION-MANAGER-20260805-001
  (coordination_request_id
  REQ-MYPA-MOSS-FULL-IMPLEMENTATION-MANAGER-20260805T122900Z-001):
  "The operator's use of this package as the build target in this prompt
  ratifies it as the product baseline for the campaign."
repository: RMF112018/my-pa
repository_main_head_at_ratification: 88e8d8193095afa8d903db08324a588a5786908b
repository_main_tree_at_ratification: 418c466b020db1819b575f3206dbbdaf71db7f0a
```

## 1. What is ratified

The canonical Moss product package `MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008`
(version 4.0, archive SHA256
`60e886e9dd19c6d39929990cd939ab1eb8c9c11eea8b0fb8faffac971516d6a4`) is ratified
as the **product-definition baseline** for the full my-pa Moss implementation
campaign. The package comprises documents `00_README.md` through
`24_PACKAGE_MANIFEST.json` plus `SHA256SUMS.txt`.

## 2. Product baseline definition

The ratified target product is:

> An evidence-grounded executive continuity system for authenticated Moss
> employees that converts each Principal's authorized Microsoft 365 evidence,
> explicit captures, reviewed interpretations, and managed work records into a
> durable operating system for attention, commitments, decisions, projects,
> and relationships.

- **Governing user loop:** Today → Pulse → Situation → Frame → Trace or Review → Close.
- **Primary destinations:** Today, Situations, Review, Library, System.
- **Persistent global capabilities:** Capture, Reveal.
- **Frontend target:** MossAIc web application — Next.js App Router + TypeScript
  + Tailwind + MSAL (supersedes the earlier React+TS+Vite assumption).
- **Persistence:** PostgreSQL canonical persistence with Alembic migrations.
- **Identity:** single-tenant Moss Microsoft Entra; delegated OAuth 2.0
  authorization-code flow with PKCE; immutable Principal derivation from
  validated `(tid, oid)` claims; strict `principal_id` partitioning on every
  durable user-scoped record; fail-closed data-access isolation.
- **Connectors:** Microsoft Graph delegated read connectors (Outlook Mail,
  Calendar, Contacts, OneDrive) and a bounded Microsoft To-Do write projection.
- **AI boundary:** AI may derive and propose but may not silently promote
  consequential facts, decisions, commitments, tasks, or external actions.

## 3. Scope of the ratification

- Ratification defines **product intent**. It does not waive repository
  governance (`AGENTS.md`), acceptance criteria, independent review, or safety
  controls.
- Ratification does not authorize operator-only actions: production deployment,
  live Microsoft Graph credentials or app registration, live personal-data
  access, destructive retirement of Apple/native implementation, destructive
  production migrations, or material risk acceptance.
- The repository build status is treated as **greenfield (0% verifiable build)**
  per package document `22_REPOSITORY_TRUTH_AND_PRODUCT_GAP_BASIS.md`: the
  existing Python/PostgreSQL implementation is reusable evidence and backend
  capability, not automatically the final frontend, identity, connector, or
  deployment architecture.

## 4. Verification performed

- Repository `RMF112018/my-pa` cloned and authenticated on 2026-08-05; current
  `main` head `88e8d8193095afa8d903db08324a588a5786908b` (tree
  `418c466b020db1819b575f3206dbbdaf71db7f0a`) **matches** the previously
  audited head recorded in the manager prompt.
- The extracted package documents (00–24 plus `SHA256SUMS.txt`) were read as
  the product authority for campaign formation.

## 5. Truth precedence (restated for the campaign)

1. authenticated runtime and test evidence;
2. current repository/GitHub and local worktree state;
3. repository governance, accepted ADRs, specifications, active goal state, and acceptance criteria;
4. this ratified Moss v4.0 product package;
5. indexed Workspace publications;
6. prior audits, reports, prompts, and handoffs as claims;
7. assumptions and memory.
