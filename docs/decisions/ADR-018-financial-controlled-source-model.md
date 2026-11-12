# ADR-018: Financial controlled source model

- **Status:** Proposed — **not accepted**. Design and synthetic proof (slice F-1: pure
  domain, a neutral synthetic interchange parser and synthetic fixtures) undertaken under the
  operator's program directive of 2026-10-17 and the operator's 2026-11-12 discretion grant
  ("proceed with the next appropriate step at your discretion"; F-1 selected by the Manager),
  within OD-06's "theoretical schema/fixtures can be prepared" carve-out. The model decisions
  below are **not operator-ratified**. No real financial source is designated (OD-06 open;
  UB-009 `FINANCE_SOURCE_NOT_DESIGNATED` stands); certified Program financial totals are
  unreachable (OD-08). Nothing is persisted, migrated, granted, exposed or deployed; no
  capability, table, identifier kind or switch consumer exists. F-2 (persistence and
  operator-only import) and F-3 (Program financial read) each need separate authorization.
- **Decision date:** 2026-11-12 (design proposal)
- **Repository basis:** `origin/main@10095168dc5f3c4709e0706751e6252db57418b7`, tree
  `15e2cc01fde83d29721a194dc0aa9d1b323c5940`, branch `feat/financial-source-domain`.
  `ADR-018` was unallocated there: `docs/decisions/` held ADR-001 to ADR-017.
- **Authority:** as in Status. The OD-08 default (selected by the operator directive of
  2026-10-17, recorded in [ADR-015](ADR-015-record-lineage-and-issue-situations.md)) governs
  reportability. This ADR does not ratify any source, approval hierarchy, threshold or
  exposure; design review R11 and its re-review 1 are resolved in contract revisions R11-1
  and R11-2.
- **Scope and contract:** WP-05A, CR-011, AT-020 of review package
  `MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`; the concrete contract is
  [`financial-source-contract.md`](../architecture/financial-source-contract.md).

## Context

The Program view (record lineage S4) reports operational metrics with OD-08 reportability
and lists finance as not built. CR-011 asks for an immutable, controlled financial source
model: source runs and versions with hashes, periods, cutoffs and approval, Project
mappings, change orders and balanced scope transfers, exact money and a `NOT_REPORTABLE`
answer whenever a material fact is missing. No finance source has been designated, the
`Project.value` field and collector prose are not a ledger. A migrated legacy PostgreSQL
schema named `financial` exists (67 objects: 28 `MIGRATE_DATA`, 20 `REBUILD_AND_VALIDATE`, 11
`ARCHIVE_LEGACY_SOURCE_ONLY`, 8 `REINITIALIZE_OPERATIONAL_STATE`; 65 `FINANCIAL_OPERATIONAL`, 2
personal), together with legacy `procore.procore_financial_*` tables; both are unanalysed,
their production row content is unverified, and neither is a designated source. They are
flagged to the operator as a possible OD-06 candidate needing its own analysis and
designation; UB-009 stands.

## Decision

1. **The source system is the authority.** my-pa never keeps a mutable accounting ledger and
   never writes to a source. A source version is an immutable snapshot of an external
   export, identified by `(source_system, source_version_ref)` and its canonical content
   SHA-256; the same ref with different content is a conflict, never an update.
2. **Approval is self-asserted export content; authenticity is provenance.** The file's
   status, approver, source system and body hash are consistency-checked against the operator
   designation (a version is usable only when it names a designated approver, is not stale —
   `approved_at < cutoff_at` is stale — not withdrawn and unambiguous), but these checks do
   **not** authenticate the file: a forger can write any of them and recompute the hash.
   Authenticity rests entirely on an operator-only import of a file the operator obtained from
   the designated source; there is no signature. Proposed versions never supersede and never
   feed a figure. No client can approve, designate, import or map.
3. **Mappings from external to native Projects are operator-reviewed, append-only
   revisions** with the single match basis `operator_review`; there is no fuzzy or automatic
   acceptance; a wrong mapping is quarantined by a new revision.
4. **Money is `Decimal` with `NUMERIC(20,4)` semantics**, no `float` anywhere, exact
   arithmetic with inexact results trapped, inputs with more than 4 decimals refused (never
   rounded), currencies from a closed ISO 4217 minor-unit table, no FX conversion until an FX
   authority is decided. Rounding (half-even) exists only for presentation.
5. **Equations are fixed:** `revised_contract = original + Σ approved changes`; EAC is
   `actual + forecast cost to complete` **or** an accepted source EAC, never both;
   `variance = approved current − EAC` within 1 version; pending changes and pending transfers
   are reported separately; a scope transfer is exactly 2 balanced legs of 1 approved
   transfer, eliminated once in Program gross movement; double counting is detected.
6. **Every material gap is `NOT_REPORTABLE`** with closed reasons, an explicit denominator and
   per-Project figures; no zero is substituted; the evaluator has no threshold parameter.
   Without a designation the answer is `source_not_integrated`. `reportable` certifies source
   integrity and coverage only; it is never a certified total (OD-08).
7. **Synthetic only until OD-06.** F-1 defines a neutral, versioned synthetic interchange
   format `my-pa-synthetic-finance-v1` (strict unquoted ASCII CSV, whole-file accept or
   refuse, closed refusal codes) and synthetic fixtures. A real source needs its own adapter,
   mapping review and independent review.
8. **Staging.** F-1 adds no public or persistent surface (pinned by an architecture scope
   guard). F-2 plans 10 append-only, Principal-partitioned tables (including an operator-only
   run-quarantine record), always schema-qualified
   `knowledge.financial_*` (never in schema `financial`; protected in the MCP object-grant
   mechanism, never granted beyond the owner), an operator-only, attested-local import behind the default-off switch
   `MY_PA_FINANCIAL_SOURCE_ENABLED`, and recovery by switch-off with rows retained. F-3 plans
   `programs.financial.overview` withheld from ChatLLM and remote clients until OD-06 and
   OD-08 are decided.

## Consequences

- Program financial totals stay unavailable in every deployment until the operator
  designates a source and, separately, accepts any OD-08 risk.
- The model can be exercised end to end on synthetic data, including AT-020's domain half,
  without any persistence or real data.
- A real source format is a new adapter and a new contract revision, not a change to this
  model's equations or reportability rules.

## Supersession

None. A later ADR is required to designate a real source, add FX conversion, introduce a
materiality threshold, or expose finance reads to a client.
