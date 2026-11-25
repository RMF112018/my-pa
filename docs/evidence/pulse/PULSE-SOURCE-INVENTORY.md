# PULSE source inventory

**Status:** sanitized evidence ([README](README.md)). Aggregates, basenames and project numbers only.

## 1. What exists

Exactly 20 CSV files, in 3 project folders of the PULSE export area of the `mcp` file workspace; no other file sits in that area. All 20 were written to the NAS on 2026-11-21 between 12:31Z and 12:32Z (fresh writes; no earlier versions exist in the workspace). Totals: about 360 KB, 2,593 data rows.

> **Manager note 2026-11-24 (recorded contradiction).** The 2,593 above contradicts the per-file Data rows column of section 3, which sums to **2,398**; the unit of 2,593 is not stated. The code and the expected-figures file assert 2,398 (`rows.data`), and the real-data runs reproduced it.

| Project number | Files | Report families present |
| --- | --- | --- |
| `P250357` | 8 | OAC meeting items; observations (3 views); coordination issues; RFIs (3 views) |
| `N302602` | 8 | budget changes (2 views); buyout summary; change-order reconciliation; daily log (delays, manpower, notes, weather) |
| `N302601` | 4 | daily log (delays, manpower, notes, weather) |

## 2. File format (all 20 files)

- UTF-8, no byte-order mark, comma-delimited, RFC 4180 quoting, LF record terminators.
- Embedded CRLF inside quoted fields in 3 `P250357` files: the 2 observation views with data carry 21 each, coordination issues carries 93. A parser must honour quoting across line breaks; physical lines are not records.
- Every data row has exactly the header's width (the profile's `row_widths` has one value per file).
- Headers follow the Procore convention `Object > Field` (for example `RFI > Number`, `Budget Code > Budget Code`).
- There is no in-file metadata block: no report name, filter, run time, project or as-of date. The first record is the header.
- Filename shape `YYYYMMDD-<report-slug>.csv`. The date prefix is a publication label, not a verified as-of date. The slug is the operator's saved-report name and does **not** describe the report's filter (see [historical coverage](PULSE-HISTORICAL-COVERAGE-ASSESSMENT.md) section 3).

## 3. Per file

Roles are the Manager's verified row-role counts ([grain analysis](PULSE-REPORT-GRAIN-AND-GROUPING-ANALYSIS.md)). "Data rows" excludes the header.

| Project | File | Bytes | Data rows | Roles (verified) | Completeness class |
| --- | --- | ---: | ---: | --- | --- |
| `P250357` | `20261116-oac-meeting-report.csv` | 147,383 | 318 | 318 detail (flat) | populated |
| `P250357` | `20261116-observations-closed-last-week.csv` | 225 | 0 | header only | valid empty export |
| `P250357` | `20261116-observations-open-by-sub.csv` | 49,125 | 306 | 2-level groups: 3 first-level rows (vendor groups including `(Blank)`, and `Grand Totals`), 4 status sub-headers, 299 detail | populated |
| `P250357` | `20261116-observations-opened-last-week.csv` | 50,071 | 306 | same structure plus a `Date Closed` column; 299 detail | populated |
| `P250357` | `20261117-coordination-issues.csv` | 32,961 | 202 | 1-level groups by status: 3 headers, 199 detail | populated |
| `P250357` | `20261117-rfi-linked-to-drawings.csv` | 13,402 | 242 | 241 detail (RFI × drawing-link grain), 1 `Grand Totals` | populated |
| `P250357` | `20261117-rfi-open-outstanding.csv` | 21,963 | 239 | 238 detail (3 without an RFI number), 1 `Grand Totals` | populated |
| `P250357` | `20261117-rfi-recently-closed.csv` | 16,744 | 239 | 238 detail (3 without an RFI number), 1 `Grand Totals` | populated |
| `N302602` | `20261105-budget-changes.csv` | 3,902 | 30 | 1-level groups by budget change number: 9 headers, 20 adjustment lines, 1 `Grand Totals` | populated |
| `N302602` | `20261105-budget-changes-by-code.csv` | 2,629 | 21 | 20 flat adjustment lines, 1 `Grand Totals` | populated |
| `N302602` | `20261105-buyout-summary.csv` | 13,392 | 429 | 1-level groups by budget code: 1 `(Blank)` header with 25 vendor-only rows, 184 code headers, 97 fully blank spacer rows, 50 budget lines, 19 budget-change lines (7 with a vendor), 24 prime-contract change-order lines, 28 commitment lines, 1 `Grand Totals` | populated, sparse |
| `N302602` | `20261105-change-order-reconciliation.csv` | 5,792 | 56 | 1-level groups by prime change-order number: 1 `(Blank)` header, 2 numbered change-order headers, 45 PCO line rows, 7 commitment change-order line rows, 1 `Grand Totals` | populated |
| `N302602` | `20261120-daily-log-delays.csv` | 200 | 1 | 1 grouping-only row (`Is Weather Delay` = Yes), no delay detail | grouping-only, no details |
| `N302602` | `20261120-daily-log-manpower.csv` | 619 | 7 | 1-level group by date: 1 date header (subtotal), 5 vendor detail, 1 `Grand Totals` | populated |
| `N302602` | `20261120-daily-log-notes.csv` | 47 | 0 | header only | valid empty export |
| `N302602` | `20261120-daily-log-weather.csv` | 410 | 1 | 1 detail (one day) | populated |
| `N302601` | `20261120-daily-log-delays.csv` | 199 | 1 | 1 grouping-only row (= No) | grouping-only, no details |
| `N302601` | `20261120-daily-log-manpower.csv` | 188 | 0 | header only | valid empty export |
| `N302601` | `20261120-daily-log-notes.csv` | 47 | 0 | header only; **byte-identical** to the `N302602` notes file (same SHA-256) | valid empty export |
| `N302601` | `20261120-daily-log-weather.csv` | 379 | 0 | header only | valid empty export |

Summary: 12 populated, 6 valid empty exports (header only), 2 grouping-only. Every row of every file is accounted for by a role: the role counts sum to the data-row count in each file.

> **Manager notes 2026-11-24 (after the real-data run; counts only).**
>
> - **Recorded contradiction.** The summary's 12 / 6 / 2 contradicts the Completeness class column of this same table, which counts **13 populated, 5 valid empty, 2 grouping-only** (one daily-log weather file is listed as populated with 1 detail). The code asserts the per-file values, 13 / 5 / 2.
> - **Correction: buyout grouping-only headers.** of the 185 buyout level-1 headers (the 184 code headers and the `(Blank)` header), 96 have no line beneath them, so under this evidence's own rule 7 ([grain analysis](PULSE-REPORT-GRAIN-AND-GROUPING-ANALYSIS.md) section 2) they are `grouping_only`, not group headers; the inventory counted them as headers. The code asserts 89 buyout group headers and 96 grouping-only level-1 rows (117 group headers and 98 grouping-only rows across the 20 files).
> - **Correction: the vendor-only rule.** A buyout row that names a vendor and whose only other filled cell is the never-loaded original-budget column is a vendor-only line, not a budget line (a budget line carries no vendor). With that rule the code reproduces the 25 vendor-only rows and 50 budget lines stated above; reading such a row as a budget line was 1 of the 7 differences of the first file-level run (333 of 340 figures, then 340 of 340).

## 4. Completeness classes

| Class | Meaning | Count |
| --- | --- | ---: |
| populated | at least 1 detail row | 12 (13 by the per-file column; see the note in section 3) |
| valid empty export | a well-formed header and no data row; evidence that the report returned nothing **under its unknown filter**, never evidence that the project has no such records | 6 (5 by the per-file column) |
| grouping-only | group rows and no detail; the export says a group exists and gives no record | 2 |

"Sparse" (buyout) is a property of a populated file: most cells are empty because a row carries only the columns of its line kind.

## 5. Consequences

- One source per project folder: a byte-identical header-only file appears in 2 project folders, so snapshot identity by SHA-256 must be scoped to a source, never global (plan sections 1, 6).
- Empty and grouping-only exports are first-class snapshots with their own completeness class; they are never skipped and never read as "no records".
- The date prefix and slug are stored as labels; neither decides time coverage or filter semantics.
