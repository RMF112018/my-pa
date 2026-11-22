# PULSE report schema catalog

**Status:** sanitized evidence ([README](README.md)). Header names, column statistics (filled, distinct and shape counts) and header signatures only; no cell value.

## 1. Header signature

A report family is recognized by its **ordered header list**, never by its filename slug. The signature used throughout this package and the plan is `pulse_header_signature_v1`:

```
sha256( utf8( json.dumps(header_fields, ensure_ascii=False, separators=(",", ":")) ) )
```

where `header_fields` is the list of header cells exactly as decoded from the first CSV record (no trimming, no case folding, order kept). Reordering, renaming, adding or removing a column produces a new signature; a new signature is a new adapter version or a quarantine, never a silent fallback (plan section 4).

The 20 files carry **15 distinct signatures**. 5 signatures occur in 2 files each: the 4 daily-log families (one file in each of 2 projects) and the 9-column observations view (2 saved reports of `P250357` with different slugs and different contents but identical headers). Two saved reports that share a signature are still distinct report series (plan section 6.2).

## 2. Shape vocabulary

The profile classifies each non-empty cell into one shape. `number`: a plain integer or decimal. `money`: a currency-sign amount with thousands separators and 2 decimals. `text`: anything else on one line, which includes parenthesized negative amounts (so a money column with `text` cells is expected, see [financial integrity](PULSE-FINANCIAL-DATA-INTEGRITY-ASSESSMENT.md) section 1). `longtext`: a long single-line text. `multiline`: text with an embedded line break. `date`: `M/D/YYYY`. `bool`: `Yes`/`No`. `empty`: an empty cell. Counts are over all data rows of the file, so group headers, totals and spacer rows contribute; [grain analysis](PULSE-REPORT-GRAIN-AND-GROUPING-ANALYSIS.md) separates them.

## 3. OAC meeting items

### Signature `bc395d0f219ab8e2` (8 columns)

Full signature: `bc395d0f219ab8e2dded2c9b2ba23a984221e16e28016944d20c77a18160664d`. Files: `P250357` `20261116-oac-meeting-report.csv`.

Column statistics from `P250357` `20261116-oac-meeting-report.csv` (318 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Meeting > Number` | 318 | 32 | number 318 |
| 1 | `Meeting > Date` | 318 | 29 | date 318 |
| 2 | `Meeting Item > Category` | 318 | 5 | text 318 |
| 3 | `Meeting Item > Agenda/Item Number` | 318 | 11 | number 318 |
| 4 | `Meeting Item > Title` | 318 | 13 | text 318 |
| 5 | `Meeting Item > Description` | 313 | 32 | text 257, longtext 48, multiline 8, empty 5 |
| 6 | `Meeting Item > Date Updated` | 318 | 36 | date 318 |
| 7 | `Meeting Item > Minutes` | 234 | 230 | longtext 148, empty 84, multiline 64, text 22 |

## 4. Observations

### Signature `4ddbf6c5cfbd42a4` (9 columns)

Full signature: `4ddbf6c5cfbd42a41651a25b0cb377c76f4113e57367f62200012b310006a5af`. Files: `P250357` `20261116-observations-closed-last-week.csv`, `P250357` `20261116-observations-opened-last-week.csv`.

Column statistics from `P250357` `20261116-observations-opened-last-week.csv` (306 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Observation > Assignee Company (Vendor) Name` | 3 | 3 | empty 303, text 3 |
| 1 | `Observation > Status` | 4 | 2 | empty 302, text 4 |
| 2 | `Observation > Count` | 306 | 8 | number 306 |
| 3 | `Observation > Date Created` | 299 | 19 | date 299, empty 7 |
| 4 | `Observation > Date Closed` | 62 | 7 | empty 244, date 62 |
| 5 | `Observation > Number` | 299 | 299 | number 299, empty 7 |
| 6 | `Observation > Title` | 299 | 125 | text 299, empty 7 |
| 7 | `Observation > Type` | 299 | 2 | text 299, empty 7 |
| 8 | `Observation > Description` | 296 | 281 | text 263, longtext 29, empty 10, multiline 4 |

### Signature `bf1ffde9268fd40b` (8 columns)

Full signature: `bf1ffde9268fd40bb2915f1d85210b691d615605be0983758d4b65bb61593241`. Files: `P250357` `20261116-observations-open-by-sub.csv`.

Column statistics from `P250357` `20261116-observations-open-by-sub.csv` (306 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Observation > Assignee Company (Vendor) Name` | 3 | 3 | empty 303, text 3 |
| 1 | `Observation > Status` | 4 | 2 | empty 302, text 4 |
| 2 | `Observation > Count` | 306 | 8 | number 306 |
| 3 | `Observation > Date Created` | 299 | 19 | date 299, empty 7 |
| 4 | `Observation > Number` | 299 | 299 | number 299, empty 7 |
| 5 | `Observation > Title` | 299 | 125 | text 299, empty 7 |
| 6 | `Observation > Type` | 299 | 2 | text 299, empty 7 |
| 7 | `Observation > Description` | 296 | 281 | text 263, longtext 29, empty 10, multiline 4 |

## 5. Coordination issues

### Signature `6a3377daa519d55d` (11 columns)

Full signature: `6a3377daa519d55dfc4f4b949ed204c1071ad6d4f6c0e64de8201e527f96bf15`. Files: `P250357` `20261117-coordination-issues.csv`.

Column statistics from `P250357` `20261117-coordination-issues.csv` (202 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Coordination Issue > Status` | 3 | 3 | empty 199, text 3 |
| 1 | `Coordination Issue > Issue Number` | 199 | 199 | number 199, empty 3 |
| 2 | `Coordination Issue > Title` | 199 | 14 | text 199, empty 3 |
| 3 | `Coordination Issue > Description` | 199 | 189 | text 192, multiline 6, empty 3, longtext 1 |
| 4 | `Coordination Issue > Assignee Company Name` | 199 | 1 | text 199, empty 3 |
| 5 | `Coordination Issue > Assignee Name` | 199 | 1 | text 199, empty 3 |
| 6 | `Coordination Issue > Date Created` | 199 | 4 | date 199, empty 3 |
| 7 | `Coordination Issue > Due Date` | 0 | 0 | empty 202 |
| 8 | `Coordination Issue > Type` | 199 | 1 | text 199, empty 3 |
| 9 | `Coordination Issue > Trade` | 0 | 0 | empty 202 |
| 10 | `Coordination Issue > Date Updated` | 199 | 6 | date 199, empty 3 |

## 6. RFIs

### Signature `36e4ba6dcc3c2e0b` (6 columns)

Full signature: `36e4ba6dcc3c2e0b1c54540912179835ff2aa3c2dbab155474b4a655e60644d1`. Files: `P250357` `20261117-rfi-linked-to-drawings.csv`.

Column statistics from `P250357` `20261117-rfi-linked-to-drawings.csv` (242 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `RFI > Number` | 242 | 234 | text 242 |
| 1 | `RFI > Subject` | 241 | 233 | text 241, empty 1 |
| 2 | `RFI > Drawing Number` | 50 | 43 | empty 192, text 50 |
| 3 | `Drawing Markup Link > Count` | 242 | 11 | number 242 |
| 4 | `Drawing Markup Link > Tool Type` | 204 | 1 | text 204, empty 38 |
| 5 | `Drawing Markup Link > Type` | 204 | 2 | text 204, empty 38 |

### Signature `fd8ceefefca08af9` (7 columns)

Full signature: `fd8ceefefca08af911d7d598012a5f1a0201b7210de4c5ff427f1e7809a9767b`. Files: `P250357` `20261117-rfi-open-outstanding.csv`.

Column statistics from `P250357` `20261117-rfi-open-outstanding.csv` (239 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `RFI > Number` | 236 | 234 | text 236, empty 3 |
| 1 | `RFI > Subject` | 238 | 236 | text 238, empty 1 |
| 2 | `RFI > Ball In Court` | 50 | 18 | empty 189, text 48, longtext 2 |
| 3 | `RFI > RFI Priority` | 236 | 2 | text 236, empty 3 |
| 4 | `RFI > Date Initiated` | 235 | 44 | date 235, empty 4 |
| 5 | `RFI > Due Date` | 235 | 43 | date 235, empty 4 |
| 6 | `RFI > Due Date Variance (Days)` | 236 | 43 | number 236, empty 3 |

### Signature `41c0bdf8aa414ce9` (6 columns)

Full signature: `41c0bdf8aa414ce9082b45454faa997ab9cb9c30bd073d5849dada3ee3d72887`. Files: `P250357` `20261117-rfi-recently-closed.csv`.

Column statistics from `P250357` `20261117-rfi-recently-closed.csv` (239 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `RFI > Number` | 236 | 234 | text 236, empty 3 |
| 1 | `RFI > Subject` | 238 | 236 | text 238, empty 1 |
| 2 | `RFI > RFI Priority` | 236 | 2 | text 236, empty 3 |
| 3 | `RFI > Date Initiated` | 235 | 44 | date 235, empty 4 |
| 4 | `RFI > Date Closed` | 188 | 39 | date 188, empty 51 |
| 5 | `RFI > Count` | 239 | 2 | number 239 |

## 7. Budget changes

### Signature `975b497cad710281` (6 columns)

Full signature: `975b497cad710281d61f4b612a52219e5b188f96c88b418e892a9421a4197456`. Files: `N302602` `20261105-budget-changes-by-code.csv`.

Column statistics from `N302602` `20261105-budget-changes-by-code.csv` (21 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Budget Code > Budget Code` | 21 | 14 | text 21 |
| 1 | `Budget Code > Budget Code Description` | 20 | 12 | text 20, empty 1 |
| 2 | `Budget Change Adjustment Line Item > Amount` | 21 | 21 | money 11, text 10 |
| 3 | `Budget Change Adjustment Line Item > Description` | 20 | 20 | text 20, empty 1 |
| 4 | `Budget Change > Number` | 20 | 9 | number 20, empty 1 |
| 5 | `Budget Change > Date Created` | 20 | 3 | date 20, empty 1 |

### Signature `0340c32b37c19e66` (8 columns)

Full signature: `0340c32b37c19e662f4ce38481f9e20ad020713e62c4cad5810db7952473bcb1`. Files: `N302602` `20261105-budget-changes.csv`.

Column statistics from `N302602` `20261105-budget-changes.csv` (30 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Budget Change > Number` | 10 | 10 | empty 20, number 9, text 1 |
| 1 | `Budget Change > Date Created` | 20 | 3 | date 20, empty 10 |
| 2 | `Budget Change > Title` | 20 | 9 | text 20, empty 10 |
| 3 | `Budget Change > Status` | 20 | 1 | text 20, empty 10 |
| 4 | `Budget Code > Budget Code` | 20 | 13 | text 20, empty 10 |
| 5 | `Budget Code > Budget Code Description` | 20 | 12 | text 20, empty 10 |
| 6 | `Budget Change Adjustment Line Item > Amount` | 30 | 21 | money 20, text 10 |
| 7 | `Budget Change Adjustment Line Item > Description` | 20 | 20 | text 20, empty 10 |

## 8. Buyout summary

### Signature `5dce7f210ad1a1f9` (8 columns)

Full signature: `5dce7f210ad1a1f9d279a9cbaa4378778b1a08eb904b8ae7e0bf908edbd28a48`. Files: `N302602` `20261105-buyout-summary.csv`.

Column statistics from `N302602` `20261105-buyout-summary.csv` (429 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Budget Code > Budget Code` | 186 | 186 | empty 243, text 186 |
| 1 | `Budget Line Item > Original Budget Amount` | 162 | 1 | empty 267, money 162 |
| 2 | `Budget Change Adjustment Line Item > Amount` | 33 | 21 | empty 396, money 20, text 13 |
| 3 | `Prime Contract Change Order Line Item > Approved Amount` | 49 | 25 | empty 380, money 49 |
| 4 | `Commitment > Number` | 28 | 23 | empty 401, text 28 |
| 5 | `Company (Vendor) > Name` | 84 | 48 | empty 345, text 84 |
| 6 | `Commitment Line Item > Amount` | 57 | 22 | empty 372, money 57 |
| 7 | `Commitment Change Order Line Item > Approved Amount (Including Markup)` | 15 | 8 | empty 414, money 15 |

## 9. Change-order reconciliation

### Signature `d08eb82e2cd4ea79` (11 columns)

Full signature: `d08eb82e2cd4ea797f70f0e7a53699930d9d84e0a68ddbc0611c1a1606360aa2`. Files: `N302602` `20261105-change-order-reconciliation.csv`.

Column statistics from `N302602` `20261105-change-order-reconciliation.csv` (56 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Prime Contract Change Order > Number` | 4 | 4 | empty 52, text 2, number 2 |
| 1 | `Prime Contract Potential Change Order > Number` | 45 | 15 | number 45, empty 11 |
| 2 | `Prime Contract Potential Change Order > Date Created` | 45 | 6 | date 45, empty 11 |
| 3 | `Prime Contract Potential Change Order > Status` | 45 | 6 | text 45, empty 11 |
| 4 | `Prime Contract Change Order Line Item > Description` | 29 | 29 | text 29, empty 27 |
| 5 | `Prime Contract Change Order Line Item > Amount` | 49 | 44 | money 49, empty 7 |
| 6 | `Prime Contract Change Order Line Item > Date Created` | 45 | 6 | date 45, empty 11 |
| 7 | `Commitment Change Order > Number` | 7 | 1 | empty 49, number 7 |
| 8 | `Commitment Change Order > Status` | 7 | 1 | empty 49, text 7 |
| 9 | `Commitment Change Order Line Item > Description` | 7 | 7 | empty 49, text 7 |
| 10 | `Commitment Change Order Line Item > Amount` | 9 | 8 | empty 47, money 9 |

## 10. Daily log

### Signature `ec234742713fe41c` (6 columns)

Full signature: `ec234742713fe41cd66e05c370cb451b8c49e652dd0774f08d00236aa6c5e6c9`. Files: `N302602` `20261120-daily-log-delays.csv`, `N302601` `20261120-daily-log-delays.csv`.

Column statistics from `N302602` `20261120-daily-log-delays.csv` (1 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Daily Log Delay > Date` | 0 | 0 | empty 1 |
| 1 | `Daily Log Delay > Delay Type` | 0 | 0 | empty 1 |
| 2 | `Daily Log Delay > Start Time` | 0 | 0 | empty 1 |
| 3 | `Daily Log Delay > End Time` | 0 | 0 | empty 1 |
| 4 | `Daily Log Delay > Comments` | 0 | 0 | empty 1 |
| 5 | `Daily Log Observed Weather Condition > Is Weather Delay` | 1 | 1 | bool 1 |

### Signature `cb7292a935751ef3` (6 columns)

Full signature: `cb7292a935751ef3b55575a2197a7cef5e172a3e275af8fd7e1b86db2bd81bcd`. Files: `N302602` `20261120-daily-log-manpower.csv`, `N302601` `20261120-daily-log-manpower.csv`.

Column statistics from `N302602` `20261120-daily-log-manpower.csv` (7 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Daily Log Manpower > Date` | 2 | 2 | empty 5, date 1, text 1 |
| 1 | `Daily Log Manpower > Company (Vendor) Name` | 5 | 5 | text 5, empty 2 |
| 2 | `Daily Log Manpower > Workers` | 7 | 5 | number 7 |
| 3 | `Daily Log Manpower > Hours` | 7 | 2 | number 7 |
| 4 | `Daily Log Manpower > Total Hours` | 7 | 5 | number 7 |
| 5 | `Daily Log Manpower > Comments` | 4 | 4 | empty 3, text 3, multiline 1 |

### Signature `ea8b8dc551db37ce` (2 columns)

Full signature: `ea8b8dc551db37ce8539f24bfcebbe9eb579648eaaa6dcc6090c9c6092458f52`. Files: `N302602` `20261120-daily-log-notes.csv`, `N302601` `20261120-daily-log-notes.csv`.

| # | Header | Fill / distinct / shapes |
| ---: | --- | --- |
| 0 | `Daily Log Note > Date` | header only (0 data rows) |
| 1 | `Daily Log Note > Comment` | header only (0 data rows) |

### Signature `9aece52bb01e577e` (6 columns)

Full signature: `9aece52bb01e577ef20ba5e978951e3be8c09c16bd57407d40665c536dd17f2c`. Files: `N302602` `20261120-daily-log-weather.csv`, `N302601` `20261120-daily-log-weather.csv`.

Column statistics from `N302602` `20261120-daily-log-weather.csv` (1 data rows; filled and distinct counts over all data rows, group rows included):

| # | Header | Filled | Distinct | Shapes |
| ---: | --- | ---: | ---: | --- |
| 0 | `Daily Log Observed Weather Condition > Date` | 1 | 1 | date 1 |
| 1 | `Daily Log Observed Weather Condition > Measured Humidity Average` | 1 | 1 | number 1 |
| 2 | `Daily Log Observed Weather Condition > Measured Temperature Average` | 1 | 1 | number 1 |
| 3 | `Daily Log Observed Weather Condition > Measured Wind Speed Average` | 1 | 1 | number 1 |
| 4 | `Daily Log Observed Weather Condition > Measured Dew Point` | 1 | 1 | number 1 |
| 5 | `Daily Log Observed Weather Condition > Measured Precipitation Since Midnight` | 1 | 1 | number 1 |

## 11. Observations about the catalog

- **Group-key columns are sparse by construction.** In grouped families the first column (vendor, status, budget code, change-order number, date) is filled only on group rows; the blanks under it are inherited context, not missing data.
- **Money columns in one row grain mix kinds.** Buyout carries 7 amount-bearing columns for budget, budget change, prime-contract change order, commitment and commitment change order; any one row fills only the columns of its line kind (financial integrity section 4).
- **Non-additive numeric columns** (`RFI > Due Date Variance (Days)`, `Drawing Markup Link > Count`, `Observation > Count`, `RFI > Count`) are summed by the export's `Grand Totals` row anyway; those totals are not measures.
- **Empty columns are evidence of the export, not of the project.** `Coordination Issue > Due Date` and `Coordination Issue > Trade` are empty in every row; `Budget Line Item > Original Budget Amount` holds 1 distinct value throughout (the zero amount or blank: the budget is not loaded in this export).
- **Low-cardinality columns** (`Coordination Issue > Assignee Company Name`, `Coordination Issue > Assignee Name`, `Coordination Issue > Type`: 1 distinct value each; `Budget Change > Status`: 1) are stored as observed, never assumed constant for the family.
- **Two padding styles** for `Commitment > Number` coexist in buyout (`<project number>.000NN` and `<project number>.00NN`); see [record identity](PULSE-RECORD-IDENTITY-ASSESSMENT.md) section 7.
