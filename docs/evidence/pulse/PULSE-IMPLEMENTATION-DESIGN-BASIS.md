# PULSE implementation design basis

**Status:** sanitized evidence ([README](README.md)). Each finding of this package mapped to the design decision it forces and to the section of [`pulse-implementation-plan.md`](../../plans/pulse-implementation-plan.md) ("plan") that carries it. Communications-contract sections are cited as "contract section N" ([`communications-intelligence-contract.md`](../../architecture/communications-intelligence-contract.md)).

## 1. Findings to decisions

| # | Finding (evidence) | Decision | Plan |
| ---: | --- | --- | --- |
| 1 | Exports are files written by an external producer into the `mcp` workspace ([inventory](PULSE-SOURCE-INVENTORY.md)) | Read-only original-source evidence; read through the files store; never written, renamed or trashed | 1, 11 |
| 2 | Same lifecycle needs as communications: snapshot, SHA-256, runs, idempotency, quarantine, freshness | Reuse the ADR-022 decision 2 lifecycle built in WP3 as its second consumer `pulse_csv_export`; no second lifecycle | 1.2, 3 |
| 3 | 1 header-only file is byte-identical in 2 project folders ([inventory](PULSE-SOURCE-INVENTORY.md) section 3) | One lifecycle source per project folder; snapshot identity `(principal, source, sha256)`; aliasing only within a source | 6.1 |
| 4 | Procore exports are not user-authored and not managed documents | Not ADR-003 product-owned records and not ADR-010 report artifacts; the Reports plane is not reused for storage | 1.4 |
| 5 | No in-file metadata; slug does not describe the filter ([historical coverage](PULSE-HISTORICAL-COVERAGE-ASSESSMENT.md) section 3) | `filter_semantics = unknown` by default; slug and date prefix stored as labels only | 6.2, 8 |
| 6 | 15 header signatures over 20 files; 2 saved reports share a signature ([schema catalog](PULSE-REPORT-SCHEMA-CATALOG.md)) | Adapters keyed by `pulse_header_signature_v1`; report series keyed `(source, slug label, signature)` | 4.2, 6.2 |
| 7 | An unknown signature must not be guessed | Unknown signature → snapshot quarantined, every row kept in Layer A as `unclassified` | 4.5 |
| 8 | RFC 4180 quoting with embedded CRLF; constant width | Strict CSV reader; physical records ≠ lines; width mismatch → `malformed` row | 4.1 |
| 9 | Grouped-export convention verified; subtotals reconcile 143/143, 9/9, 3/3, 3/3 ([grain](PULSE-REPORT-GRAIN-AND-GROUPING-ANALYSIS.md) section 5) | Layer A row roles with level, key and inherited group path; sums over `detail` only | 4.3, 5.1, 7 |
| 10 | 2-level observations double count when read as 1 level (99 vs 198) | Roles carry level; tests pin the double-count case | 4.3, 12 |
| 11 | 97 spacer rows; grouping-only delay exports | Roles `spacer`, `grouping_only`; completeness class per snapshot | 4.3, 5.1 |
| 12 | Non-additive `Grand Totals` (variance days, link counts) | Stated totals stored as evidence with additivity `non_additive`; never metrics | 5.3, 7 |
| 13 | Money with currency sign, parentheses negatives ([financial](PULSE-FINANCIAL-DATA-INTEGRITY-ASSESSMENT.md) section 1) | `Decimal` parse, `NUMERIC(20,4)`, no float; raw text kept beside the value | 4.4, 7 |
| 14 | Change-order subtotals mix approved, pending, void | Measures separated by status class; never from subtotals | 7 |
| 15 | Buyout mixes revenue and cost columns | Each measure names one column and side | 7, 8 |
| 16 | Original budget column unloaded | `not_reportable` / `source_column_unpopulated`; no zero substituted | 7 |
| 17 | Budget-change views duplicate the same 20 lines | A measure reads 1 named view per snapshot | 7 |
| 18 | Cross-report check exact to the cent | Ingest-time and test-time cross-report reconciliation; outcome stored | 7, 12, 15 |
| 19 | OAC identity is `(meeting number, item number)`; item number alone is not unique ([identity](PULSE-RECORD-IDENTITY-ASSESSMENT.md) section 3) | Canonical item plus per-meeting observation | 6.3 |
| 20 | Observation and issue numbers unique | Canonical `(project, number)` | 6.3 |
| 21 | RFI numbers are stage-prefixed text and repeat; 3 rows have none | Canonical `(project, number as exported)`; every row an observation; unnumbered rows have no identity; suffix-and-prefix matching | 6.3, 8, 10 |
| 22 | Budget-change lines and PCO lines carry no line identifier | Snapshot-scoped line identity; content-matched compare flagged as such | 6.3, 8 |
| 23 | Commitment numbers in 2 padding styles; 1 commitment under several codes | Store as exported; versioned match normalization; key `(commitment, budget code)` | 6.3, 7 |
| 24 | 1 commitment CO number on 7 lines, commitment not exported | `ambiguous_commitment_co`; no canonical identity; operator question | 6.3, 16 |
| 25 | Exactly 1 publication per report; no history in the workspace | Longitudinal behaviour validated synthetically; record history across snapshots designed, not measured | 12, 15 |
| 26 | A record can vanish from a later snapshot for unknown reasons | `not_observed_in_latest`; closure never inferred from disappearance | 6.3, 8 |
| 27 | Project numbers appear inside budget codes and commitment numbers | Cross-check only; binding is explicit registry data | 6.4 |
| 28 | Crosswalk is operator data, not committable | Operator-supplied registry, applied by operator CLI as append-only revisions; fails closed | 6.4 |
| 29 | Explicit vs inferred relationships ([relationships](PULSE-REPORT-RELATIONSHIP-MATRIX.md)) | Only explicit relationships are stored; no lineage family; no meeting-to-OAC matching by date or title | 5.2, 10 |
| 30 | Communications identifiers include `rfi:<n>` without prefix | WP5 joins by exact suffix and flags `ambiguous_prefix` | 10 |
| 31 | Communications must work when PULSE is absent (contract section 15) | `pulse: {state: "unavailable"}`; no communications code path depends on PULSE | 10, 15 |
| 32 | Exports carry vendor and person names, descriptions and minutes | Content is inert data; logs and audit carry codes and counts; external-model eligibility is an operator decision before any grant | 8, 9, 13 |

## 2. Not decided by the evidence (operator questions, plan section 16)

- Filter semantics of each saved report.
- Whether repeated RFI rows in the status views are revisions or duplicate export rows.
- How a commitment change-order line is tied to its commitment.
- Program membership of the 3 projects.
- Whether any PULSE text (titles, descriptions, minutes) is eligible to be returned to an external-model client.
