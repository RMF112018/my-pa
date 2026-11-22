# PULSE historical coverage assessment

**Status:** sanitized evidence ([README](README.md)).

## 1. Publications

- Exactly **1 publication per report per project**. No earlier version of any export exists in the workspace: all 20 files were fresh writes on 2026-11-21 between 12:31Z and 12:32Z.
- Date labels: `P250357` exports 2026-11-16 and 2026-11-17; `N302602` financial exports 2026-11-05; both daily-log sets 2026-11-20.
- Daily-log exports are single-day (2026-11-20): 1 weather day, 1 manpower date group, 0 notes, 0 delay detail.

## 2. History inside one export

- The OAC export embeds its own history: 32 meetings (April to November 2026), each re-recording the carried-forward agenda, with minutes that accumulate dated notes. Item-level history can be read from 1 snapshot by meeting number.
- Observation and RFI exports carry creation, initiation and closure dates per record, but a single snapshot cannot show a status change; only a later snapshot can.
- Financial exports carry creation dates on budget changes and PCO lines (3 and 6 distinct dates); no export carries an as-of or cutoff date.

## 3. Report names do not describe filters

| Saved report (slug) | What the slug suggests | What the export holds |
| --- | --- | --- |
| `observations-opened-last-week` | observations opened in the last week | 299 observations created from March 2026 on, closed ones included (62 with a closure date) |
| `observations-open-by-sub` | open observations | includes a `Closed` status group of 15 |
| `observations-closed-last-week` | closed in the last week | header only |
| `rfi-recently-closed` | closed RFIs | 47 of 238 rows have no closure date |

Conclusions:

- The slug is the operator's label. **Filter semantics are `unknown`** unless the operator supplies a verified filter definition for that saved report.
- Status and recency are never inferred from the report name; they come only from status and date columns.
- A header-only export (`observations-closed-last-week`) proves only that this saved report returned no row under its unknown filter at that time.

## 4. Absence is not closure

A record present in one snapshot and absent from a later snapshot of the same report series may have been closed, refiltered, deleted, moved, or dropped by a filter the operator changed. With filter semantics `unknown`, my-pa never infers closure (or any other status) from disappearance: the record's state becomes `not_observed_in_latest`, and its last observed status stays as observed, with its snapshot.

## 5. What can be validated now

- Ingestion, roles, identity, reconciliation and cross-report checks: on the real exports (aggregate-only, Manager-run) and on synthetic fixtures.
- Longitudinal behaviour (re-publication, supersession, compare, `not_observed_in_latest`, record history across snapshots): **synthetic only** until the operator publishes a second generation of exports.
- Coverage per project and family: publication date labels, ingestion time and freshness, never a claimed as-of date.

## 6. Coverage model consequences

- Coverage for PULSE is **per source, family and report series**: which snapshots exist, their date labels, when they were first seen, their completeness class and filter semantics. There is no time window to merge (unlike communications contract section 9); a date label is never a coverage interval.
- Freshness = now − first-seen time of the latest snapshot of the series.
- A read always states the snapshot it answered from, its date label, its filter semantics and its completeness class.
