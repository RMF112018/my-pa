# PULSE report grain and grouping analysis

**Status:** sanitized evidence ([README](README.md)). Row-role counts, fill-pattern shapes and reconciliation outcomes only.

## 1. Two kinds of export

- **Flat** exports: every data row is a record (OAC meeting items, budget changes by code, daily-log weather). A flat export may still end in a `Grand Totals` row.
- **Grouped** exports: rows are a tree written depth-first. The first column (or first 2 columns in a 2-level report) holds the group key.

## 2. The grouped-export convention (verified)

1. A row whose group-key column is non-blank **starts a group**. Its numeric columns carry the group's **subtotal**, not a record's value.
2. Following rows whose group-key column is blank **inherit** that key. Blank cells under a group header are omitted repeated context, not missing data.
3. `(Blank)` is the group of records whose key is null. It is a real group with a real subtotal.
4. `Grand Totals` is the report total: a row whose first column holds that literal.
5. In a 2-level report the second key column starts a sub-group inside the current first-level group, with its own subtotal; detail rows inherit both keys.
6. A **fully blank row** (every cell empty) is a structural spacer, not a record.
7. A group header with no detail row beneath it — none before the next header of the same or a higher level, or the end of the file — is **grouping-only**: the export states that a group exists and gives no record. In a 2-level report a level-1 header followed directly by its level-2 headers is not grouping-only, because detail follows under those sub-groups.

## 3. Row roles

Every data row of every export receives exactly one role. Group headers carry a level and their key; detail rows carry the inherited group path.

| Role | Meaning | Contributes to sums |
| --- | --- | --- |
| `detail` | a business record (or a record line) | **yes**, the only role that does |
| `group_header(level, key)` | starts a group at `level` (1 or 2); its numerics are subtotals | no (stored as stated-total evidence) |
| `grand_total` | the report total row | no (stored as stated-total evidence) |
| `spacer` | every cell empty | no |
| `grouping_only` | a group header with no detail row before the next header of the same or a higher level, or end of file | no |
| `malformed` | a row the family adapter cannot place (wrong width, key pattern it does not recognize) | no; counted and reported |

Verified counts per file are in [the inventory](PULSE-SOURCE-INVENTORY.md) section 3. Across the 20 files no row is `malformed` under the verified rules.

## 4. Per family layout

| Family | Grouping | Group key columns | Detail grain |
| --- | --- | --- | --- |
| OAC meeting items | flat | — | 1 meeting item as recorded in 1 meeting (318 rows; 32 meeting numbers × the carried-forward agenda) |
| Observations (open by sub) | 2-level | `Observation > Assignee Company (Vendor) Name` → `Observation > Status` | 1 observation (299) |
| Observations (opened / closed last week) | 2-level | same | 1 observation (299 / 0) |
| Coordination issues | 1-level | `Coordination Issue > Status` | 1 coordination issue (199) |
| RFIs linked to drawings | flat + `Grand Totals` | — | 1 RFI × 1 drawing-link observation (241) |
| RFIs open outstanding / recently closed | flat + `Grand Totals` | — | 1 RFI row (238 each); an RFI number may repeat |
| Budget changes | 1-level | `Budget Change > Number` | 1 adjustment line (20) |
| Budget changes by code | flat + `Grand Totals` | — | 1 adjustment line (20; the same 20 lines as the grouped view) |
| Buyout summary | 1-level | `Budget Code > Budget Code` | 1 line of one kind: budget line, budget-change line, prime-contract change-order line, commitment line, vendor-only line |
| Change-order reconciliation | 1-level | `Prime Contract Change Order > Number` | 1 PCO line item (45) or 1 commitment change-order line item (7) |
| Daily log manpower | 1-level | `Daily Log Manpower > Date` | 1 vendor-day (5) |
| Daily log weather | flat | — | 1 day (1) |
| Daily log delays | grouping-only in both files | `Daily Log Observed Weather Condition > Is Weather Delay` | none present |
| Daily log notes | header only in both files | — | 1 note (none present) |

## 5. Subtotals are aggregates (decimal reconciliation)

For every grouped financial or numeric export the Manager compared each group header's stated value with the decimal sum of its detail rows, per numeric column.

| Export | Groups / columns checked | Outcome |
| --- | --- | --- |
| Buyout summary | 143 non-empty column-groups (782 both-empty) | 143 match, 0 mismatch |
| Budget changes | 9 groups | 9 match, 0 mismatch |
| Change-order reconciliation | 3 groups × both amount columns | 3 match, 0 mismatch |

> **Manager correction 2026-11-24 (after the real-data run).** The buyout's 782 both-empty column-groups count all 185 level-1 headers × 5 money columns − 143. But of the 185 buyout level-1 headers (the 184 code headers and the `(Blank)` header), 96 have no line beneath them, so under rule 7 (section 2) they are `grouping_only`, and grouping-only headers are not reconciled. The code therefore asserts **302** both-empty column-groups (89 headers with lines × 5 − 143); the 143 matches and 0 mismatches are unchanged.
| Daily log manpower | 3 numeric columns of 1 date group | 3 match, 0 mismatch |
| Every export with `Grand Totals` | `Grand Totals` against the sum of its first-level group headers | match in every case |

Conclusion: group headers and `Grand Totals` are aggregates of the detail rows and **must be excluded from any sum**. Summing all numeric rows of a 1-level export counts every amount twice (detail plus subtotal), and 3 times once `Grand Totals` is included.

## 6. Two-level double counting

The observation exports are 2-level (vendor → status → detail). A naive 1-level reading that treats every non-detail row as one level of header double counts:

| Check | Correct (detail only) | Naive 1-level sum |
| --- | ---: | ---: |
| One first-level row, `Observation > Count` | 99 | 198 |
| Another first-level row, `Observation > Count` | 200 | 400 |

Group headers must be classified **by level**, and only detail rows are business observations. The level is decided by which key column is filled (fill-pattern shapes `x.x.....` for a first-level row and `.xx.....` for a second-level row, against `..xxxxxx` for detail in the 8-column view).

## 7. Spacers, grouping-only and sparse rows

- Buyout carries 97 fully blank spacer rows (fill pattern `........`) and 23 distinct fill patterns overall: each line kind fills its own columns.
- The 2 delay exports carry 1 grouping-only row each and no delay detail; the export proves only that the grouping value was present.
- A `(Blank)` group may hold rows that are neither budget nor commitment lines (25 vendor-only rows in buyout).
- **Manager note 2026-11-24 (the vendor-only rule as built).** A buyout row that names a vendor and whose only other filled cell is the never-loaded original-budget column is a vendor-only line, not a budget line; with that rule the code reproduces the inventory's 25 vendor-only rows. A buyout code header with no line beneath it is grouping-only by rule 7 (96 of the 185 level-1 headers).

## 8. Non-additive totals

`Grand Totals` is computed by the exporter over columns that are not additive:

- `rfi-open-outstanding` sums `RFI > Due Date Variance (Days)` across RFIs;
- `rfi-linked-to-drawings` sums `Drawing Markup Link > Count` across RFI × link rows;
- `RFI > Count` and `Observation > Count` totals count rows, including duplicate RFI rows.

These rows are stored as source evidence of what the exporter printed and are **never** presented as metrics.

## 9. Design consequences

- Layer A stores every row with its role, group level, key and inherited group path, so a source export can be reconstructed and every sum can be restricted to `detail` rows (plan sections 5.1, 7).
- Role classification is per family adapter, keyed by header signature, because the group-key columns differ per family ([schema catalog](PULSE-REPORT-SCHEMA-CATALOG.md)).
- Ingest re-runs the section 5 reconciliation on every snapshot and records match/mismatch counts; a mismatch makes that snapshot's measures `not_reportable` (plan section 7).
