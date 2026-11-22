# PULSE export evidence (sanitized aggregates)

**Status:** investigation evidence for Project Reporting Intelligence over Procore PULSE CSV exports (scope extension `MYPA-PULSE-INTELLIGENCE-EXTENSION-20261121`) and for its implementation plan [`pulse-implementation-plan.md`](../../plans/pulse-implementation-plan.md). Design input only: no PULSE code, table, capability or switch exists. The shared ingestion lifecycle it builds on is [ADR-022](../../decisions/ADR-022-communications-intelligence.md) decision 2 and section 1 of [`communications-intelligence-contract.md`](../../architecture/communications-intelligence-contract.md) (both Accepted under operator delegation 2026-11-22, Manager ruling R-OP-1; effective on merge of WP2).

These eight documents describe the 20 real PULSE CSV exports the design was reconciled against. They hold **header names, row-role counts, column fill and shape counts, pattern shapes, reconciliation outcomes (match/mismatch counts), file basenames, byte counts and project numbers only**. They hold no vendor, company or person name, no project display name, no description, minute, title or RFI subject, no drawing number, no specific change-order or potential-change-order number, no money amount and no `prj_`/`ent_`/`prn_` identifier. Document numbers are described by shape (`GMP-<n>`). The exports themselves are never committed and are not reachable from this repository.

| Document | What it answers |
| --- | --- |
| [`PULSE-SOURCE-INVENTORY.md`](PULSE-SOURCE-INVENTORY.md) | Which exports exist, per project number: size, rows, roles, completeness class, file format |
| [`PULSE-REPORT-SCHEMA-CATALOG.md`](PULSE-REPORT-SCHEMA-CATALOG.md) | The ordered header list of every report family and its header signature |
| [`PULSE-REPORT-GRAIN-AND-GROUPING-ANALYSIS.md`](PULSE-REPORT-GRAIN-AND-GROUPING-ANALYSIS.md) | What one row means, how grouped exports are laid out, and which rows are aggregates |
| [`PULSE-RECORD-IDENTITY-ASSESSMENT.md`](PULSE-RECORD-IDENTITY-ASSESSMENT.md) | What identifies a record in each family, and where no identity exists |
| [`PULSE-FINANCIAL-DATA-INTEGRITY-ASSESSMENT.md`](PULSE-FINANCIAL-DATA-INTEGRITY-ASSESSMENT.md) | Money format, subtotal reconciliation, status mixing, revenue/cost mixing, double-count hazards |
| [`PULSE-REPORT-RELATIONSHIP-MATRIX.md`](PULSE-REPORT-RELATIONSHIP-MATRIX.md) | Which links between records are explicit in an export and which are only inferred |
| [`PULSE-HISTORICAL-COVERAGE-ASSESSMENT.md`](PULSE-HISTORICAL-COVERAGE-ASSESSMENT.md) | What time and history the exports cover, and what the report names do not tell us |
| [`PULSE-IMPLEMENTATION-DESIGN-BASIS.md`](PULSE-IMPLEMENTATION-DESIGN-BASIS.md) | Each finding mapped to a design decision and to its plan section |

## Common basis

- **Sources:** the Manager's Gate-1 findings (`pulse-findings.md`, SHA-256 `4c8189def3b1562f140ef9468aa830102d26d88eabb0a215ff4ebc538054bcdc`) and structural profile (`pulse-profile.json`, SHA-256 `38242c71e48842a78a2ed103057dccb1068fb5ec7fb588b0de4c9422837aa8bb`), produced 2026-11-21 (about 13:00Z) over local read-only copies of the 20 exports, each verified byte-exact against the NAS SHA-256 listing. The decimal subtotal reconciliations were run by the Manager over the same copies. Both files live in the Manager's run directory, outside this repository; the profile holds structure only (headers, fill, distinct and shape counts), never values.
- **Projects** are named by project number only: `P250357`, `N302602`, `N302601`. Each sits in its own export folder in the workspace. The folder-to-Project binding is operator-supplied runtime registry data and is **not committed** (plan section 6.4); the internal Project identifiers are deliberately absent here.
- **Committable rule:** the strict rule confirmed by the Manager on 2026-11-21 (allowed: aggregates, header names, row-role counts, pattern shapes, reconciliation outcomes, project numbers). A leak scan for currency signs, entity, principal and project identifiers and the project display names is run before every commit of this directory.
- All counts are digits on purpose (spelled-count guard).
