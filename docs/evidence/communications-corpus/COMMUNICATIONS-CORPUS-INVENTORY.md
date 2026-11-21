# Communications corpus inventory

**Basis:** see the [common basis](README.md#common-basis) (aggregate JSON SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, 2026-11-21, Manager-run collection; 31 publications = 29 canonical lean + 2 rich). Aggregates only.

## Summary

| Measure | Value |
| --- | --- |
| Publications | 31 |
| Canonical folder (lean dialect) | 29, business dates 2026-10-18 to 2026-11-20 |
| Outside the canonical folder (rich dialect) | 2 (business dates 2026-11-16 and 2026-11-20) |
| Schema name / version | `communications_evidence_v2` / `2.0.0` in all 31 |
| Total bytes | 193,933,725 (canonical 185,654,160, about 177 MiB; rich 8,279,565) |
| Smallest / largest file | 162,393 / 13,398,446 bytes |
| Message records (observations) | 4,141 (lean 3,944; rich 197) |
| Records by folder role | inbox 3,594; sent 547 |
| Backfill publications | 28 (every canonical file except `20261120-comms.json`) |
| Live (non-backfill) publications | 3 (`20261120-comms.json` and both rich files) |
| Mailbox references | 1 |
| `cycle_run_id` present | 0 of 31 |
| Overall coverage `complete` | 31 of 31 |
| Source errors / warnings | 0 / 0 in every publication |

Business dates absent from the canonical folder — the Saturdays 2026-10-24, 2026-10-31, 2026-11-07 and 2026-11-14, and 2026-11-19 — are **not** gaps: the Sunday weekend rules and the Friday live rule cover them (see [`COMMUNICATIONS-COVERAGE-BASELINE.md`](COMMUNICATIONS-COVERAGE-BASELINE.md)).

## Per publication

Dialect `L` = lean (9 top-level keys), `R` = rich (14). Hours are declared / actual (`end_utc - start_utc`, end inclusive). Records are in / sent by folder role.

| File | Bytes | Business date | D | Rule | Hours | Records (in/sent) |
| --- | ---: | --- | --- | --- | --- | --- |
| `20261018-comms.json` | 642,154 | 2026-10-18 | L | weekend_prior_48h | 48 / 48.0 | 18 (17/1) |
| `20261019-comms.json` | 8,069,025 | 2026-10-19 | L | weekday_prior_24h | 24 / 24.0 | 156 (141/15) |
| `20261020-comms.json` | 7,305,170 | 2026-10-20 | L | weekday_prior_24h | 24 / 24.0 | 159 (144/15) |
| `20261021-comms.json` | 10,427,895 | 2026-10-21 | L | weekday_prior_24h | 24 / 24.0 | 236 (197/39) |
| `20261022-comms.json` | 10,505,517 | 2026-10-22 | L | weekday_prior_24h | 24 / 24.0 | 200 (172/28) |
| `20261023-comms.json` | 3,763,712 | 2026-10-23 | L | weekday_prior_24h | 24 / 24.0 | 66 (55/11) |
| `20261025-comms.json` | 679,301 | 2026-10-25 | L | weekend_prior_48h | 48 / 48.0 | 12 (12/0) |
| `20261026-comms.json` | 10,398,898 | 2026-10-26 | L | weekday_prior_24h | 24 / 24.0 | 196 (180/16) |
| `20261027-comms.json` | 11,304,018 | 2026-10-27 | L | weekday_prior_24h | 24 / 24.0 | 258 (225/33) |
| `20261028-comms.json` | 10,252,851 | 2026-10-28 | L | weekday_prior_24h | 24 / 24.0 | 216 (187/29) |
| `20261029-comms.json` | 8,156,419 | 2026-10-29 | L | weekday_prior_24h | 24 / 24.0 | 182 (165/17) |
| `20261030-comms.json` | 5,253,499 | 2026-10-30 | L | weekday_prior_24h | 24 / 24.0 | 94 (89/5) |
| `20261101-comms.json` | 693,411 | 2026-11-01 | L | weekend_prior_49h | 49 / 49.0 | 18 (15/3) |
| `20261102-comms.json` | 4,866,042 | 2026-11-02 | L | weekday_prior_24h | 24 / 24.0 | 133 (117/16) |
| `20261103-comms.json` | 8,040,247 | 2026-11-03 | L | weekday_prior_24h | 24 / 24.0 | 185 (154/31) |
| `20261104-comms.json` | 5,212,289 | 2026-11-04 | L | weekday_prior_24h | 24 / 24.0 | 115 (101/14) |
| `20261105-comms.json` | 11,590,161 | 2026-11-05 | L | weekday_prior_24h | 24 / 24.0 | 230 (205/25) |
| `20261106-comms.json` | 7,684,022 | 2026-11-06 | L | weekday_prior_24h | 24 / 24.0 | 201 (176/25) |
| `20261108-comms.json` | 2,542,847 | 2026-11-08 | L | weekend_prior_48h | 48 / 48.0 | 18 (15/3) |
| `20261109-comms.json` | 13,398,446 | 2026-11-09 | L | weekday_prior_24h | 24 / 24.0 | 237 (209/28) |
| `20261110-comms.json` | 7,223,677 | 2026-11-10 | L | weekday_prior_24h | 24 / 24.0 | 149 (133/16) |
| `20261111-comms.json` | 5,884,490 | 2026-11-11 | L | weekday_prior_24h | 24 / 24.0 | 138 (119/19) |
| `20261112-comms.json` | 5,646,255 | 2026-11-12 | L | weekday_prior_24h | 24 / 24.0 | 123 (108/15) |
| `20261113-comms.json` | 4,255,004 | 2026-11-13 | L | weekday_prior_24h | 24 / 24.0 | 125 (107/18) |
| `20261115-comms.json` | 162,393 | 2026-11-15 | L | weekend_prior_48h | 48 / 48.0 | 5 (5/0) |
| `20261116-comms.json` | 5,326,304 | 2026-11-16 | L | weekday_prior_24h | 24 / 24.0 | 110 (83/27) |
| `20261117-comms.json` | 5,294,085 | 2026-11-17 | L | weekday_prior_24h | 24 / 24.0 | 133 (100/33) |
| `20261118-comms.json` | 4,246,917 | 2026-11-18 | L | weekday_prior_24h | 24 / 24.0 | 110 (85/25) |
| `20261120-comms.json` | 6,829,111 | 2026-11-20 | L | friday_prior_24h | 24 / 33.2 | 121 (108/13) |
| `2026-11-16_communications_evidence_v2.json` | 3,130,476 | 2026-11-16 | R | explicit_utc_bounds | 72 / 72.0 | 101 (83/18) |
| `communications_evidence_v2.json` (folder `20261120/`) | 5,149,089 | 2026-11-20 | R | explicit_utc_bounds | 24 / 24.0 | 96 (87/9) |

The record counts per folder role include the backfill lane duplicates described in [`MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md`](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md): in 23 backfill files every Sent item is also listed in the inbox lane, so the inbox counts there over-count distinct items.

## Sources declared per publication

Every publication declares the same 3 sources: `inbox` (mail lane, authorized, coverage `complete`), `sent` (mail lane, authorized, coverage `complete`) and `procore_rfis` (project-system lane, `not_authorized`, 0 records). Paging status is not reported in the lean dialect (`pages` 0). Only the rich dialect carries a `counts` block.

## Contract validation result (Manager, contract head `ac0d06ae`)

The WP1 aggregate CLI accepted **31 of 31** publications (0 rejected; 29 lean, 2 rich), with 0 unknown top-level keys and 0 unknown record keys in every file. Diagnostic codes over the corpus: `multi_lane_item` 421, `subject_empty` 7, `participant_from_absent` 2, `participant_entry_invalid` 2, `duplicate_provider_id` 1, `window_hours_mismatch` 1 (the Friday live file, 24 declared vs 33.2 actual), `body_truncated` 1.

## What changed from v1

v1 counted 5 publications and 561 observations (2026-11-21 about 11:40Z, while the backfill was in progress). The backfill then completed to 29 canonical files; the 2 rich files are unchanged.
