# ADR-018: Financial controlled source model

- **Status:** Proposed — accepted by directive for **design and synthetic proof only**
  (slice F-1: pure domain, a neutral synthetic interchange parser and synthetic fixtures).
  No real financial source is designated (OD-06 open; UB-009
  `FINANCE_SOURCE_NOT_DESIGNATED` stands); certified Program financial totals are
  unreachable (OD-08). Nothing is persisted, migrated, granted, exposed or deployed; no
  capability, table, identifier kind or switch consumer exists. F-2 (persistence and
  operator-only import) and F-3 (Program financial read) each need separate authorization.
- **Decision date:** 2026-11-12 (design proposal)
- **Repository basis:** `origin/main@10095168dc5f3c4709e0706751e6252db57418b7`, tree
  `15e2cc01fde83d29721a194dc0aa9d1b323c5940`, branch `feat/financial-source-domain`.
  `ADR-018` was unallocated there: `docs/decisions/` held ADR-001 to ADR-017.
- **Authority:** the record lineage program's operator-selected defaults (OD-08 selected by
  the operator directive of 2026-10-17, recorded in
  [ADR-015](ADR-015-record-lineage-and-issue-situations.md)), under which OD-06 permits
  "theoretical schema/fixtures" while blocking import and real totals; and the Manager's F-1
  slice authorization relayed to the design worker. This ADR does not ratify any source,
  approval hierarchy, threshold or exposure.
- **Scope and contract:** WP-05A, CR-011, AT-020 of review package
  `MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`; the concrete contract is
  [`financial-source-contract.md`](../architecture/financial-source-contract.md).

## Context

The Program view (record lineage S4) reports operational metrics with OD-08 reportability
and lists finance as not built. CR-011 asks for an immutable, controlled financial source
model: source runs and versions with hashes, periods, cutoffs and approval, Project
mappings, change orders and balanced scope transfers, exact money and a `NOT_REPORTABLE`
answer whenever a material fact is missing. No finance source has been designated, the
`Project.value` field and collector prose are not a ledger, and the migrated legacy
PostgreSQL schema named `financial` is archived legacy data, not a designated source.

## Decision

1. **The source system is the authority.** my-pa never keeps a mutable accounting ledger and
   never writes to a source. A source version is an immutable snapshot of an external
   export, identified by `(source_system, source_version_ref)` and its canonical content
   SHA-256; the same ref with different content is a conflict, never an update.
2. **Approval is the source's assertion, checked against an operator designation.** A
   version is usable only when approved by a designated approver, not stale (`approved_at <
   cutoff_at` is stale), not withdrawn and unambiguous. Proposed versions never supersede and
   never feed a figure. No client can approve, designate, import or map.
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
   Without a designation the answer is `source_not_integrated`.
7. **Synthetic only until OD-06.** F-1 defines a neutral, versioned synthetic interchange
   format `my-pa-synthetic-finance-v1` (strict unquoted ASCII CSV, whole-file accept or
   refuse, closed refusal codes) and synthetic fixtures. A real source needs its own adapter,
   mapping review and independent review.
8. **Staging.** F-1 adds no public or persistent surface (pinned by an architecture scope
   guard). F-2 plans 9 append-only, Principal-partitioned `financial_*` tables in schema
   `knowledge`, an operator-only import behind the default-off switch
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
