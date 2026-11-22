# PULSE financial data integrity assessment

**Status:** sanitized evidence ([README](README.md)). Formats, reconciliation outcomes and counts only; **no amount** appears in this document.

## 1. Money and number formats

| Kind | Format observed | Rule |
| --- | --- | --- |
| Money | currency sign (U+0024), thousands separators, exactly 2 decimals: shape `<sign>1,234.56` | parse to `Decimal`; reject anything else |
| Negative money | the same inside parentheses: shape `(<sign>1,234.56)` | negative `Decimal`; the profile reports these cells as `text` |
| Daily-log numerics | plain decimals (`Workers`, `Hours`, `Total Hours`, weather measures) | `Decimal` |
| Dates | `M/D/YYYY` | calendar date, no time zone, no time |
| Booleans | `Yes` / `No` | closed set |

No `float` is used anywhere: binary floating point cannot represent cent values exactly, and the reconciliations below are exact to the cent only in decimal arithmetic. An input with more than 4 decimals is refused, never rounded (the [ADR-018](../../decisions/ADR-018-financial-controlled-source-model.md) decision 4 precedent, `NUMERIC(20,4)` semantics).

## 2. Subtotal reconciliation

Group headers carry subtotals and `Grand Totals` carries the report total (decimal checks, [grain analysis](PULSE-REPORT-GRAIN-AND-GROUPING-ANALYSIS.md) section 5):

- buyout: 143 of 143 non-empty column-groups match (782 both-empty);
- budget changes: 9 of 9 groups match;
- change-order reconciliation: 3 of 3 groups match on both amount columns;
- every `Grand Totals` equals the sum of its first-level group headers.

0 mismatches in 20 files. Consequence: a measure is computed from `detail` rows only, and stated totals are evidence used to **verify** the computation, never inputs to it.

## 3. Status mixing in change-order reconciliation

- PCO line statuses in one export: `Approved`, `Pending - Pricing`, `Pending - Revised`, `Pending - In Review`, `Pending - Not Pricing`, `Void` (6 distinct values).
- All of them occur inside the `(Blank)` group, and that group's **subtotal mixes approved, pending and void** lines.
- An "approved" measure must therefore be computed from detail lines filtered by status, never from a subtotal. Measures are kept separate by status class: `approved`, `pending` (all `Pending - …` values), `void`, and `unknown` for a status outside the closed mapping.

## 4. Revenue and cost in one row grain (buyout)

- Buyout rows mix **revenue** columns (prime contract, owner side: `Prime Contract Change Order Line Item > Approved Amount`) and **cost** columns (`Commitment Line Item > Amount`, `Commitment Change Order Line Item > Approved Amount (Including Markup)`) plus budget columns (`Budget Line Item > Original Budget Amount`, `Budget Change Adjustment Line Item > Amount`).
- Each row fills only its line kind's columns. A measure names its column (and so its side); no measure adds a revenue column to a cost column.
- `Budget Line Item > Original Budget Amount` holds 1 distinct value (zero or blank) in all 162 filled cells: **the budget is not loaded in this export**. That is not evidence that budgets are zero; the measure is `not_reportable` with reason `source_column_unpopulated`.

## 5. Cross-report reconciliation (buyout against change-order reconciliation)

The Manager checked, in decimal arithmetic, that buyout's `Prime Contract Change Order Line Item > Approved Amount` grand total equals the sum of the 2 numbered prime change-order subtotals of the reconciliation export plus the 2 approved PCO lines in its `(Blank)` group: **exact to the cent (1 check, match)**.

So buyout counts approved prime-contract changes only (revenue side), while the reconciliation subtotals count every status. The 2 reports' totals differ by exactly the pending and void amounts: explained, not an error. This is the reference cross-report test for the plan's acceptance criteria (synthetic in CI, aggregate-only on real data).

## 6. Budget changes

- All 9 budget changes net to zero: each is a transfer between budget codes made of `+X` / `(X)` lines.
- The 2 budget-change views carry the **same 20 lines** (cross-view duplicate). Summing both views doubles every line.
- A net-zero change is not "no change": the gross movement is reported separately from the net.

## 7. Double-count hazards (summary)

| Hazard | Where | Safeguard (plan section 7) |
| --- | --- | --- |
| Group subtotal counted as a line | every grouped export | sum `detail` rows only |
| `Grand Totals` counted | every export with one | `grand_total` role excluded |
| 2-level headers counted as 1 level | observations | roles carry level; detail only |
| Same lines in 2 views | budget changes, budget changes by code | a measure reads 1 named family view per snapshot |
| Same publication date in 2 snapshots of one series | re-publication | measures read the latest snapshot of a series, never a union |
| Commitment under several codes | buyout | key `(commitment, budget code)` |
| Approved mixed with pending and void | change-order reconciliation | status-class separated measures |
| Revenue and cost in one row | buyout | measure names its column |
| Non-additive totals | RFI views, observation counts | never measures |
| Unloaded budget column | buyout | `not_reportable`, no zero substituted |

## 8. What this does not establish

- That any amount is approved by an authority: the exports are self-asserted source content. Authenticity rests on the operator's binding of the folder to the Project (plan section 6.4), as ADR-018 decision 2 states for its own model.
- A cost-to-complete, EAC or variance: no export here carries a forecast.
- Program totals: program membership of the 3 projects is unverified (plan section 16).
