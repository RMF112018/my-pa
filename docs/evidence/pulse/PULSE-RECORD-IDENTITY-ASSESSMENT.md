# PULSE record identity assessment

**Status:** sanitized evidence ([README](README.md)). Distinct counts and identifier shapes only.

## 1. Principles

- A record identity is always **project-scoped**: `(principal, project, family, key)`. The project comes from the operator's folder-to-Project binding, never from the filename, a slug or a code prefix (section 9).
- Where the export carries no stable key, the record has **no canonical identity**: its rows are observations addressed by `(snapshot, row ordinal)` only.
- An identifier is stored as exported. Normalization exists only for matching and is versioned.
- No identity is inferred from a title, subject, description, amount or date.

## 2. Summary

| Family | Canonical identity | Evidence | Strength |
| --- | --- | --- | --- |
| OAC meeting items | `(project, meeting number, agenda/item number)` | 32 meeting numbers; 11 item numbers recur in each meeting (carried-forward agenda) | item number alone is **not** unique |
| Observations | `(project, observation number)` | 299 distinct numbers = 299 detail rows | strong |
| Coordination issues | `(project, issue number)` | 199 distinct = 199 detail rows | strong |
| RFIs | `(project, RFI number as exported)` | 234 distinct numbers over 238 rows; stage-prefixed text | canonical with repeats; 3 rows have none |
| Budget changes | `(project, budget change number)`; lines snapshot-scoped | 9 numbers; no line identifier exported | change strong; line weak |
| Buyout | per row kind; commitments by `(project, commitment number, budget code)` | 186 distinct budget codes; 23 distinct commitment numbers over 28 lines | see section 7 |
| Change-order reconciliation | prime change order by number; PCO lines snapshot-scoped; commitment CO ambiguous | 15 distinct PCO numbers over 45 lines; 1 commitment CO number on 7 lines | see section 8 |
| Daily log manpower | `(project, date, vendor)` | 5 vendor-days | strong within a day |
| Daily log weather | `(project, date)` | 1 day | strong |

## 3. OAC meeting items

- One export holds 32 meetings, meeting numbers contiguous from 1, dated April to November 2026 (29 distinct meeting dates).
- 11 distinct agenda/item numbers recur across meetings: the agenda is carried forward and each meeting re-records the item.
- `Meeting Item > Minutes` accumulate dated `(MM/DD)` notes, so the same item's minutes in a later meeting contain the earlier notes.
- Identity: the **item** is `(project, agenda/item number)`; each row is the item's **observation in one meeting**, keyed `(project, meeting number, agenda/item number)`. 318 rows = 318 such observations.

## 4. Observations and coordination issues

- `Observation > Number` is a plain integer, unique within the project (299 of 299).
- `Coordination Issue > Issue Number` is a plain integer, unique within the project (199 of 199).
- The same observation appears in 2 views (`open-by-sub`, `opened-last-week`) of 1 publication: 2 observations of 1 record, not 2 records.

## 5. RFIs

- `RFI > Number` is **stage-prefixed text**: shapes `GMP-<n>` and `CD 50%-<n>`. 234 distinct numbers.
- The same number repeats on several rows:
  - in `rfi-linked-to-drawings` the grain is RFI × drawing-link (242 rows, 234 numbers);
  - in `rfi-open-outstanding` and `rfi-recently-closed` some numbers repeat with different dates. Whether these are RFI revisions or duplicate export rows is **unresolved** (operator question, plan section 16).
- 3 rows in each status view carry **no RFI number** (possibly drafts). They are observations without canonical identity.
- Identity: canonical `(project, RFI number as exported)`; every row is also an observation keyed `(snapshot, row ordinal)`, so repeated rows are kept, never collapsed.
- **Matching.** A query for `RFI 174` must match the numeric suffix exactly (`174`, never `1740` or `17`) **and** respect the prefix: with a prefix given (`GMP-174`) only that prefix matches; with none, every prefix whose suffix is `174` matches and the answer is flagged `ambiguous_prefix` when there is more than one. The communications extractor's `rfi:174` (contract section 7) carries no prefix and therefore always takes the second path.

## 6. Budget changes

- `Budget Change > Number` is a small integer (9 distinct). It identifies the change.
- Adjustment lines carry budget code, amount and description only: **no line identifier** is exported. A line's identity is snapshot-scoped, `(snapshot, row ordinal)`; across snapshots a line can be compared only by its content `(change number, budget code, amount sign, amount)`, flagged as content-matched.
- Lines come in `+X` / `(X)` pairs within a change: intra-change fund moves that net to zero.
- `budget-changes` and `budget-changes-by-code` hold **the same 20 lines** in 2 layouts: a cross-view duplicate, never 40 lines.

## 7. Buyout summary

- `Budget Code > Budget Code`: 186 distinct non-empty values, unique per group. Its prefix is the project number, a cross-check only (section 9).
- `Commitment > Number` has 2 padding styles side by side: `<project number>.000NN` and `<project number>.00NN`. They are stored as exported and normalized (leading zeros of the suffix removed) **only for matching**, with the normalization version recorded.
- One commitment can appear under several budget codes (23 distinct numbers on 28 commitment lines). A commitment amount is therefore keyed `(commitment number, budget code)`; summing commitment amounts across codes as if each row were a distinct commitment is wrong.
- Vendor names, budget lines, budget-change lines and prime-contract change-order lines carry no identifier of their own beyond the budget code they sit under.

## 8. Change-order reconciliation

- Prime change orders: `Prime Contract Change Order > Number` names the group (2 numbered groups plus `(Blank)` for PCOs not yet on a change order).
- PCOs: `Prime Contract Potential Change Order > Number` repeats across lines (15 distinct over 45 lines): one PCO has several line items, and status is per line. A PCO line is snapshot-scoped; the PCO is `(project, PCO number)`.
- Commitment change orders: one commitment CO number repeats on all 7 commitment-CO lines. The commitment is **not exported** in this report, so the same CO number on different commitments cannot be told apart. These lines have **no canonical identity** (`ambiguous_commitment_co`, operator question, plan section 16).

## 9. Project binding

- The project of every record is the Project bound to the export's folder by explicit operator registry data, verified against the Project's own project number (plan section 6.4).
- Project numbers also appear inside budget codes and commitment numbers. That is a **cross-check** (a mismatch is a diagnostic and blocks the snapshot's financial measures), never the binding.
- The filename carries no project.

## 10. Daily log

- Manpower: `(project, date, vendor)`; a date header row carries the day's subtotal.
- Weather: `(project, date)`.
- Delays and notes: no detail rows present, so no identity is observed; the expected key is `(project, date, ordinal within date)`.
