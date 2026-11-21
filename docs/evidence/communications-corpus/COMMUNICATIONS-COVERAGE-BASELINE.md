# Communications coverage baseline

**Basis:** see the [common basis](README.md#common-basis) (aggregate JSON SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, 2026-11-21, Manager-run collection; 31 publications = 29 canonical lean + 2 rich), plus the Manager's contract-CLI result at `ac0d06ae`. Aggregates only.

## Result

| Measure | Value |
| --- | --- |
| Merged coverage (inclusive end, windows at most 1 s apart are contiguous) | **one interval, 2026-10-17T04:00:00Z to 2026-11-20T14:12:05Z** |
| Gaps inside it | **none** |
| Coverage before 2026-10-17T04:00:00Z | none |
| Publications excluded from coverage (not `complete`) | 0 |
| Per-source coverage | inbox `complete` and sent `complete` in all 31; `procore_rfis` `not_authorized` in all 31 |

The contract CLI (`summarize_corpus` in `my_pa.domain.communications.corpus`) produced the same single interval with no gaps, `end_inclusive: true`, `adjacency_tolerance_seconds: 1`.

The v1 baseline reported a 22-hour gap (2026-11-16T07:00Z to 2026-11-17T05:00Z). It was closed by the backfill publication `20261116-comms.json`.

## Window rules seen

| Rule | Publications | Declared hours | Actual hours | Business-date meaning |
| --- | ---: | --- | --- | --- |
| `weekday_prior_24h` | 23 | 24 | 24.0 | the labelled ET day, midnight to 23:59:59 local |
| `weekend_prior_48h` | 4 | 48 | 48.0 | the Saturday and Sunday ending on the labelled Sunday |
| `weekend_prior_49h` | 1 | 49 | 49.0 | the weekend holding the DST fall-back (2026-11-01) |
| `friday_prior_24h` | 1 | 24 | **33.2** | the live run: prior-day local midnight to the collection time |
| `explicit_utc_bounds` | 2 | 72 and 24 | 72.0 and 24.0 | the rich files: explicit UTC bounds, not local-day aligned |

Facts that the design relies on:

- **`window.hours` is a nominal label.** The live Friday file declares 24 and covers 33.2 hours (2026-11-19T05:00:00Z to 2026-11-20T14:12:05Z); the contract raises `window_hours_mismatch` for it. Coverage is computed from `start_utc` and `end_utc` only.
- **The end bound is inclusive.** Backfill windows end at `:59:59` local and the next window starts at `:00:00`, so adjacent windows are 1 second apart and are contiguous. The aggregate analysis counted 1 record "outside the window" in `20261120-comms.json`, while the contract classified 0 records `out_of_window`; that is consistent with the v1 observation of one message stamped exactly at `end_utc`, which an exclusive comparison rejects and the inclusive rule admits.
- **Business-date semantics differ by rule.** Backfill files label the covered ET day; the live Friday file labels the publication day and covers from the prior local midnight to collection time. A business date is therefore a label, not a coverage claim.
- **The UTC anchor moves with DST.** Windows before the fall-back start at `04:00:00Z` (EDT, UTC-4); from 2026-11-02 they start at `05:00:00Z` (EST, UTC-5). The 2026-11-01 publication covers 2026-10-31T04:00:00Z to 2026-11-02T04:59:59Z, 49 hours, and is the only file with `dst_offset_changes_in_window = true`.
- **Overlaps are expected.** The 2 rich files overlap canonical windows (2026-11-13T07:00:00Z to 2026-11-16T07:00:00Z and 2026-11-19T11:58:47Z to 2026-11-20T11:58:47Z). Overlap produces cross-publication repeats of the same items, never new coverage.

## Freshness at measurement

The newest covered instant was 2026-11-20T14:12:05Z (the live Friday run), about 22 hours before the measurement (2026-11-21, about 12:05Z). No publication for a later business date existed at that time.

## DST fixture shape

The 49-hour fall-back window is a real fixture shape: the contract's synthetic fixture `weekend_49h_lanes_publication.json` reproduces it, and the spring-forward shape does not occur in the corpus, so any test of it is synthetic.
