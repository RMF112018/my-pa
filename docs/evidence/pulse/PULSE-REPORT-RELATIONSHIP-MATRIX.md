# PULSE report relationship matrix

**Status:** sanitized evidence ([README](README.md)).

A relationship is **explicit** when one export states it in a row (a shared identifier or a grouping). It is **inferred** when it could only be guessed from text, amounts or dates. my-pa stores explicit relationships as source facts. Inferred relationships are not stored, not returned as facts and not used for joins; at most a later, separately reviewed feature may present them as candidates with their basis.

## 1. Matrix

| From | To | Kind | Basis | Stored |
| --- | --- | --- | --- | --- |
| RFI | drawing number(s) | explicit | `rfi-linked-to-drawings` row: `RFI > Number` beside `RFI > Drawing Number` (50 filled cells, 43 distinct) | yes, as an RFI drawing-link observation |
| Budget change line | budget code | explicit | `Budget Change > Number` group and `Budget Code > Budget Code` on the line | yes |
| Commitment | vendor and budget code | explicit | buyout commitment line under a budget-code group | yes |
| PCO line | prime change order | explicit | change-order reconciliation grouping by `Prime Contract Change Order > Number` (`(Blank)` = not yet on a change order) | yes |
| Observation | assignee vendor and status | explicit | the 2-level grouping keys | yes, as inherited group context |
| Coordination issue | status | explicit | the 1-level grouping key | yes |
| Meeting item | meeting | explicit | `Meeting > Number` on the row | yes |
| Manpower row | date | explicit | the date group | yes |
| Commitment change-order line | budget change "committing funds" line | **inferred** | matching amounts and descriptions only | no |
| Commitment change-order line | commitment | **unknown** | the commitment is not exported in the reconciliation; 1 CO number on 7 lines | no (ambiguous) |
| RFI | OAC meeting item | **inferred** | text only | no |
| Observation | coordination issue | **inferred** | a status group named "Moved to Observation" suggests a workflow, but no shared identifier exists | no |
| Daily-log delay | weather | **inferred** | same date | no |
| Buyout prime change-order lines | change-order reconciliation | **verified aggregate** | grand totals reconcile exactly ([financial integrity](PULSE-FINANCIAL-DATA-INTEGRITY-ASSESSMENT.md) section 5) | the reconciliation outcome only; no row-level link |
| Any export | its Project | **operator binding** | folder-to-Project registry data (plan section 6.4); project numbers in budget codes and commitment numbers are a cross-check | yes, as the binding revision |

## 2. Across sources

| From | To | Kind | Rule |
| --- | --- | --- | --- |
| Communication | RFI | explicit identifier match | communications `rfi:<n>` (contract section 7) matched to a PULSE RFI by exact numeric suffix; more than one prefix with that suffix → `ambiguous_prefix`, every candidate returned, none chosen |
| Meeting (my-pa) | OAC meeting (export) | **not established** | no shared identifier; matching by date or title is prohibited (contract section 12.2 rule 4's principle). A later operator or client binding call may link them explicitly |
| Project (my-pa) | export | operator binding | as above |
| Project | Program | **unverified** | program membership of the 3 projects is not established; the plan leaves it unresolved (section 16) |

## 3. Consequences

- PULSE adds no record-lineage family and no `record_links` rows (ADR-015 decision 6 is not amended), the same position ADR-022 decision 19 takes for communications.
- Explicit within-export relationships are columns of the typed Layer B rows, not a link table.
- Every relationship returned by a read states its kind (`explicit`, `operator_binding`, `identifier_match`, `ambiguous`).
