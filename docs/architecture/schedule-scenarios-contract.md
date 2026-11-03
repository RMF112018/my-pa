# Schedule Scenarios — whole-slice contract (S6-1 engine, S6-2 persistence, S6-3 capabilities)

**Status:** proposed implementation contract for the Schedule Scenarios slice on the local
branch `feat/schedule-scenarios-engine`. It is the single document the S6-1 (pure domain and
deterministic CPM engine), S6-2 (schema, migrations, persistence, unit of work, worker hook)
and S6-3 (capabilities, handlers, façade, catalog, ChatLLM, remote policy, lineage endpoints,
guidance) implementers code against. Nothing it describes is implemented, merged, migrated,
granted or deployed. It authorizes **no** production migration, grant, `profile-apply`, OAuth
change or deployment, and its switch `MY_PA_SCHEDULE_SCENARIOS_ENABLED` is **off by
default** and stacks on `MY_PA_SCHEDULE_ENABLED` (also off by default). The governing
decision record is
[`ADR-017`](../decisions/ADR-017-schedule-scenarios-and-baselines.md), which partially
supersedes [`ADR-016`](../decisions/ADR-016-cpm-workbench-schedule-evidence.md); the lineage
vocabulary growth is decision 17 of
[`ADR-015`](../decisions/ADR-015-record-lineage-and-issue-situations.md). It extends, and
never forks, the S5a, S5b-1 and S5b-2 contracts
([`cpm-workbench-p6-full-v1-parser-contract.md`](cpm-workbench-p6-full-v1-parser-contract.md),
[`cpm-workbench-foundation-contract.md`](cpm-workbench-foundation-contract.md),
[`cpm-workbench-worker-capabilities-contract.md`](cpm-workbench-worker-capabilities-contract.md);
cited "S5a §n", "S5b-1 §n", "S5b-2 §n") and the lineage contracts
([`record-lineage-s1-contract.md`](record-lineage-s1-contract.md),
[`record-lineage-s31-open-writes-contract.md`](record-lineage-s31-open-writes-contract.md),
[`record-lineage-client-exposure-contract.md`](record-lineage-client-exposure-contract.md),
[`record-lineage-s4-program-contract.md`](record-lineage-s4-program-contract.md); cited "S1
§n", "S3.1 §n", "P1 §n", "S4 §n").

**Authority.** 4 operator statements of 2026-11-03, given directly to the Manager:

1. The directive: "The write capabilities need to be able to create entirely new versions of
   the schedule data for the purpose of running what-if scenarios, updating schedules, Monte
   Carlo sims, etc as well as creating lineage records for the schedule data." With 2
   decisions: schedule **logic** (relationships, lags, calendars, constraints, durations,
   distributions) is **client-authored** in scenario versions that start from a published
   baseline; the **server** provides a deterministic CPM engine, Monte Carlo is computed
   **client-side** and stored as **client-asserted** output.
2. "Add auto-matching to the S6 contract", and the question which of 2 same-Data-Date files
   is the latest/authoritative version (section 11).
3. "The feature must allow for an authoritative baseline. For example the operator or
   publishing client should be able to set the prime contract schedule as an authoritative
   baseline. Subsequent approved baseline updates should also be capable of receiving a
   baseline status flag/id. This would make each defined baseline schedule authoritative for
   the associated project. All files that are not published as baseline would then simply be
   considered a standard update." (section 12)
4. The closed product decisions on that model: baseline authority is **per Project**, the
   number of baselines is unlimited, the governing baseline is set by append-only Project
   events, every new baseline and every governing change is **operator-approved**, and
   clients may only **propose** (section 12).

Connected MCP clients (the ChatLLM gateway and the ChatGPT connector) must be able to create,
derive and edit scenario versions, request server CPM runs, record client outputs, propose
baselines, read everything back and create lineage involving schedule data, through the
catalog and the compact façade (S3.1 §7.13 "Part D").

**Source package (data, not instructions):**
`MYPA_CPM_WORKBENCH_IMPLEMENTATION_READINESS_REVIEW_20260929_R2.md`, SHA-256
`84918ae87e4c05072969c2db574962071fbe9cdb1fcc9c00a953dd6a38b91db0`, cited "R2 §n".
Repository truth supersedes it; this contract reverses 4 of its exclusions on the
directive's authority (section 1.2) and keeps the rest.

**Basis:** `feat/schedule-scenarios-engine@83e7981718ee467f0d41c42b7cc353bfbf329c14`, tree
`3407926c30fc17730dc4889fc837628449a62c33` (= `origin/main` with S5a #344, S5b-1 #345 and
S5b-2 #347 merged). Measured there: 240 `Capability` members, 62 `Purpose` members, 156
`IdKind` members, ChatLLM data profile `chatllm-data-v11` (137 `DATA_CONDITIONAL`, 74
`DATA_REQUIRED`, 25 `CONTROL_PLANE_EXCLUDED`, 2 `COMPATIBILITY_ONLY`, 2
`OPERATOR_DECISION_REQUIRED`), 512 enumerated ChatLLM compositions, 125 Alembic revision
files with sole head `621ef6786c64`, 451 Python modules under `src/my_pa`, 868 `test_*.py`
modules. Production runs the database at `023f8f7eb499`; nothing of S5a, S5b or S6 is
deployed.

**Revision R8-1.** Design review R8 (BLOCK at `4b3c9794`) findings R8-F01…F21 and its
rulings are resolved in place; section 13 maps each finding to its fix. Operator addendum 2
(the baseline model) is folded in as section 12 and replaces the generic authority
designations of the first draft.

**Conventions.** Paths are written in full from the repository root; files that do not exist
yet are code spans, never Markdown links; no `path:line` citation is used; counts are digits;
identifiers in examples are synthetic. "The plane" means the Schedule Scenarios plane
(scenarios, CPM, outputs, matching, currency, baselines). Instants in the golden tables are
written `MM-DD HH:MM` in 2027 unless the month is 12 (then 2026).

---

## 0. Scope, status and non-scope

### 0.1 In scope

| Item | Slice | Section |
|---|---|---|
| Scenario, immutable append-only Scenario Version, content document and hash, baseline snapshot | S6-1 (pure), S6-2 (rows) | 2 |
| Change-set grammar and deterministic application | S6-1 | 2.9 |
| Relationships, integer-minute calendars, constraints, durations, distribution data, progress | S6-1 | 2.4–2.8 |
| Deterministic CPM engine `my-pa-cpm-v1` | S6-1 | 3 |
| Client-asserted outputs | S6-1 (validation), S6-2/S6-3 | 4 |
| Lineage: 6 endpoint families, 3 new relations, 2 widened relations, native virtual edges | S6-2, S6-3 | 5 |
| 26 capabilities, 3 purposes, switch, ChatLLM `chatllm-data-v12`, remote and façade | S6-3 | 6 |
| OD-08 labelling and exclusion from Program reporting | S6-3 guards | 7 |
| Bounds, quotas, DoS analysis, isolation | all | 8 |
| Series auto-matching on import; derived current standard update | S6-1 (pure), S6-2, S6-3 | 11 |
| Operator-approved Project baselines, governing-baseline events, `reference` role retirement | S6-1 (pure), S6-2, S6-3 | 12 |

### 0.2 Status (honest)

Directive-selected design, not ratified for production. Nothing is implemented, merged,
migrated, granted or deployed. Every switch is default off in code. The server verifies
shapes, bounds, ownership, references, idempotency, compare-and-swap and its own
computation; it cannot verify that any client-authored logic, duration, distribution, Monte
Carlo result or baseline proposal is true, nor who composed a client call, and it never says
so (section 7).

### 0.3 Out of scope (all slices)

Production anything; real schedule files; XER/XML; server-side Monte Carlo sampling or any
server randomness; resource loading/levelling; probabilistic branching, risk events and
duration correlation (S6-U03); a Program-level critical path (stays **UNPROVEN**); converting
scenario data into a publication, a Stable Activity or any source-bound row; web UI; editing
S5a/S5b behaviour, profile constants, goldens or merged revisions; a scenario Record Event
family; lineage below the version grain (S6-U05).

---

## 1. Repository reauthentication and divergence table

### 1.1 Repository truth (re-measured at the basis)

| # | Claim | Repository truth at `83e79817` | Decision |
|---|---|---|---|
| T6-01 | Activities have stable identity across publications | `StableScheduleActivity` (`sact_`) = exact published Activity ID inside one Series (`src/my_pa/domain/schedule/model.py`); visible only through a row of the accepted run of a `complete`/`partial` publication (S5b-1 U-03) | baseline-derived scenario activities are keyed by `sact_`; client-added ones by `x:<token>`; a client never mints an `sact_` key |
| T6-02 | The PDF yields schedule logic | Per row only: `published_activity_id`, `activity_name`, `row_type` (`activity`/`milestone`), `hierarchy_path` (≤ 32 labels), `original_duration`/`remaining_duration` (`ScheduleDurationCell`, `Decimal` exponent −3, `0 ≤ value < 1,000,000,000`, **no unit**, S5a §4.8), `start`/`finish` (a `date` and a `*` marker with **no meaning**, S5a §4.7), plus the publication `data_date` (always set for `complete`/`partial`, S5b-2 T2-27). No relationship, lag, calendar, constraint, float or actual | logic is client-authored; the snapshot converts durations through a client-declared `minutes_per_source_unit` and keeps published dates only as an inert `published_reference` |
| T6-03 | Publication states | `SchedulePublicationStatus` 6 members; effective status reads `failed` for an exhausted job | an eligible publication is **effective** `complete`/`partial` |
| T6-04 | Schedule tables | S5b-1 (`6c2306330ceb`) 7 Principal-partitioned tables with F1–F9 guards; S5b-2 (`621ef6786c64`) vocabulary | S6-2 adds tables and one restating revision (section 12.2); no merged revision is edited |
| T6-05 | S5b-2 surface | 7 capabilities (import operator-only attested-local; 6 scopeless reads, purpose `schedule_read`), switch `MY_PA_SCHEDULE_ENABLED`, ChatLLM `chatllm-data-v11` prerequisite `SCHEDULE`, feature `schedule`, targets 164/98 (switch off), 170 (full + schedule), 204 (full + lineage + program + schedule), 136 (default + all 3), 512 compositions | the plane stacks on the schedule switch; `chatllm-data-v12` (section 6.6) |
| T6-06 | Lineage vocabulary | `src/my_pa/domain/lineage/vocabulary.py`: `RecordFamily` 7, `RelationType` 8, `RELATION_MATRIX`, `RECORD_FAMILY_ID_KINDS`, `LINEAGE_FAMILY_READS`, `NativeVirtualEdge` 1; DB CHECKs derived from them in `tables.py`; evidence rules in `src/my_pa/application/lineage_endpoints.py` | widened together in S6-2 (section 5) |
| T6-07 | Lineage provenance and rate | S3.1: `client_identified`/`user_confirmed`, channels, `asserting_client_id`, `user_directed`; budgets 120/hour and 1,000/day per writer bucket, 2,000/day per Principal | reused for schedule-family links; the plane has its own budgets (section 8.3) |
| T6-08 | Program reporting / OD-08 | `ProgramFamily` 6 members; `METRIC_CATALOGUE` has no schedule metric; S4 §12 `programs.schedule.milestones` not built; the manifest lineage section (`src/my_pa/domain/intelligence/source_manifest.py` `_block_seeds`, `lineage_server_counts`, `lineage_section`) reads every `RecordFamily` member | no Program family or metric; the manifest lineage section is pinned to the 7 pre-S6 families (section 7) |
| T6-09 | Counts | 240 capabilities, 62 purposes, 156 `IdKind` | 266, 65, 164 (sections 2.1, 6) |
| T6-10 | `IdKind` prefixes | prefix-free rule asserted by `tests/unit/test_identifiers.py` | `sscn`, `sscv`, `scpm`, `ssco`, `ssmd`, `sbl`, `sbev`, `sgov` are prefix-free against all 156 and each other, and absent from `src`, `tests`, `web/src`, `migrations` (measured) |
| T6-11 | Decimal/time | durations `Decimal` 3 places; dates `datetime.date`; no `float` in canonical objects | the plane uses integer minutes only |
| T6-12 | Canonical JSON | `src/my_pa/domain/schedule/canonical.py` `canonical_json_bytes` (sorted, compact, ASCII, no NaN); digests are `sha256(domain_prefix + canonical)` | reused with a `\n`-terminated prefix per document |
| T6-13 | Cursor | `src/my_pa/domain/schedule/cursor.py` `ScheduleCursorOrder` (5 orders), 512 characters, TTL 300 s | S6-3 appends orders |
| T6-14 | Domain package guards | `tests/architecture/test_cpm_full_parser_scope.py` binds all of `src/my_pa/domain/schedule` (stdlib + itself + identifiers; no logging, printing, file access; no denylisted token) | the S6-1 modules live under that package |
| T6-15 | Trust levels | `TrustLevel` 3 members; `MODEL_PROPOSED` unused in `src` | every plane answer is `MODEL_PROPOSED` with basis tokens (R8 ruling R-3) |
| T6-16 | Remote keys | `src/my_pa/adapters/remote_request.py`: `_IDEMPOTENT_REMOTE_CAPABILITIES` (server-stamped payload key); `_CLIENT_BOUND_KEY_CAPABILITIES` binds the stamped key to the OAuth client (today the open lineage writes); `is_remote_idempotent` | the 6 client-usable plane writes join **both** sets (R8-F09) |
| T6-17 | Scopeless policy | `_SCOPELESS` in `src/my_pa/domain/policy/decision.py` | all 26 plane names join it |
| T6-18 | Restricted MCP profiles | no CPM privilege in any ceiling or opt-in | unchanged |
| T6-19 | Series binding at import | `ScheduleImportRequest` needs exactly one of `series_id`/`series_name`; `admit_publication` resolves or creates the Series in the admission transaction before any byte is fetched; `series_id` is not null | matching (needs parsed IDs) cannot bind the admitted publication itself (section 11) |
| T6-20 | Immutable parse products | rows, runs and Stable Activities are immutable and Series-scoped | a publication is never moved between Series |
| T6-21 | Source-version re-admission | same Series + source version: replay only if role, baseline kind, expected Data Date and supersedes all equal, else `SOURCE_VERSION_CONFLICT`; across Series admissible | section 11.2 defines `already_present` |
| T6-22 | One job per publication | `a_schedule_publication_has_one_job` | every admission gets its own job |
| T6-23 | Same-Data-Date files | both retained; no stored latest pointer; order `(data_date, admitted_at, publication_id)`; `latest_update` in `schedule_series.list` = max among role `update`, `complete`/`partial`; only explicit relation `supersedes_publication_id` (≤ 1 successor) | currency derived (section 11.3) |
| T6-24 | Series rows | `schedule_series` append-only (F1/F2) | no column added; intake marker in a new table |
| T6-25 | Roles today | `SchedulePublicationRole` = `update`, `baseline`, `reference`; `ScheduleBaselineKind` = `working`, `contract` (set iff `baseline`); used by `src/my_pa/application/commands.py` (validation), `tables.py` (CHECKs derived from the enums), `src/my_pa/infrastructure/persistence/schedule.py`, `src/my_pa/application/schedules.py` (`latest_update` = role `update`; the delta pairs any roles); the S5b-1 revision holds frozen literals; FAST guard `tests/architecture/test_cpm_workbench_worker_scope.py` forbids a `BASELINE`/`previous`/`current_baseline` symbol in `application/schedules.py` and `domain/schedule/compare.py` | section 12.2 retires `reference` and redefines the kinds by a new additive revision; baseline logic lives in new modules, never in those 2 files |

### 1.2 R2 exclusions and ADR-016 decisions: reversed and kept (recorded in ADR-017)

| Source | Exclusion / decision | Decision |
|---|---|---|
| R2 §6 | application-computed CPM, calendars, relationships, critical path, float | **Reversed** for scenario versions only, never over a publication |
| R2 §6, §29.6 | persisted derived schedule data | **Reversed** for scenarios: versions, CPM results, outputs, match decisions and baseline events are immutable rows; the publication delta stays on demand |
| R2 §6, §33; ADR-016 decision 1 | schedule-specific links to native records | **Reversed** only as ADR-015 lineage associations (section 5); no native column, coercion or mutation |
| ADR-016 decision 4 | import operator-only, attested-local | **Kept**, extended: an auto-matched import may be completed by a worker-performed second admission that inherits the operator's attested import (section 11.2) |
| ADR-016 decision 7 | changes derived, never stored | **Kept** for the delta; the baseline comparison reuses it on demand |
| ADR-016 decision 8 / R2 §30 | role is a required input; `reference` role; nothing derives a baseline or a previous publication | **Superseded**: a baseline is an operator-approved Baseline object (section 12); `reference` is retired; a derived "current standard update" exists (section 11.3); nothing derives a baseline |
| R2 §6, §34 | fuzzy matching; AI facts; XER/XML; frontend; production | **Kept** (matching is exact-ID only) |
| OD-08 | uncertified totals never reported | **Kept** (section 7) |

---

## 2. Domain model

### 2.1 Identifiers (S6-2 adds them)

| `IdKind` member | Prefix | Row |
|---|---|---|
| `SCHEDULE_SCENARIO` | `sscn` | one Scenario |
| `SCHEDULE_SCENARIO_VERSION` | `sscv` | one immutable Scenario Version |
| `SCHEDULE_CPM_RUN` | `scpm` | one CPM run of one version under one engine version |
| `SCHEDULE_SCENARIO_OUTPUT` | `ssco` | one client-asserted output |
| `SCHEDULE_SERIES_MATCH` | `ssmd` | one auto-match decision |
| `SCHEDULE_BASELINE` | `sbl` | one Baseline (proposed or approved) |
| `SCHEDULE_BASELINE_EVENT` | `sbev` | one baseline lifecycle event |
| `SCHEDULE_GOVERNING_EVENT` | `sgov` | one governing-baseline event |

Appended after `SCHEDULE_IMPORT_ISSUE` (156 → 164). The plane's idempotency ledger is keyed by
`(principal_id, capability, idempotency_key)` and mints no identifier kind of its own.

### 2.2 Scenario and Scenario Version

| Record | Fields | Rules |
|---|---|---|
| Scenario | `scenario_id`, `principal_id`, `project_id`, `series_id`, `name` (`normalize_display_text`, 1..200 characters, the Series-name refusal set), `description` (0..2,000 or null), `origin_kind` ∈ `publication`\|`version`, `origin_publication_id` (`spub`, iff `publication`), `origin_baseline_id` (`sbl`, set iff the Scenario was created `from_baseline_id`; the Baseline's exact publication is `origin_publication_id`), `origin_version_id` (`sscv`, iff `version`), provenance (section 6.5), `created_at` | immutable (S6-U01). The origin publication is eligible and not in an intake Series (section 11.2); a baseline origin is an **approved** Baseline (section 12) |
| Scenario Version | `version_id`, `principal_id`, `scenario_id`, `version_no` (1..500), `parent_version_id` (null iff `version_no = 1`, else `version_no − 1`), `label` ∈ `what_if`\|`update`\|`simulation_input`, `note` (0..2,000 or null), `content_sha256`, `content_size_bytes`, content, `change_set_sha256` and change set (null iff `version_no = 1`), `snapshot_report` (iff `version_no = 1` from a publication), counts, `distribution_spec_sha256`, provenance, `created_at` | immutable, append-only; a Scenario is a **linear** chain; a branch is a new Scenario whose version 1 copies another version byte-for-byte; edits start at version 2 (S6-D03) |

The label is metadata; the engine never reads it, and no label makes a version authoritative.

### 2.3 Content document and its hash

The content of one version is the canonical object `schedule-scenario-content-v1`:

```json
{
  "schema": "schedule-scenario-content-v1",
  "data_date": "YYYY-MM-DDTHH:MM",
  "settings": {
    "default_calendar": "<calendar key>",
    "lag_calendar": "predecessor | successor | twenty_four_hour",
    "progress_policy": "retained_logic | progress_override",
    "must_finish_by": "YYYY-MM-DDTHH:MM | null",
    "critical_float_threshold_minutes": 0
  },
  "calendars": [{"key": "...", "week": [[[480, 960]], "... 7 lists Mon..Sun"], "exceptions": [{"date": "YYYY-MM-DD", "intervals": [[480, 720]]}]}],
  "activities": [{
    "key": "sact_... | x:<token>",
    "name": "...",
    "kind": "task | milestone",
    "wbs_path": ["..."],
    "calendar": "<calendar key> | null",
    "original_minutes": 0,
    "remaining_minutes": 0,
    "constraints": [{"type": "SNET", "at": "YYYY-MM-DDTHH:MM"}],
    "progress": {"actual_start": "... | null", "actual_finish": "... | null"},
    "distribution": {"kind": "triangular", "min": 0, "mode": 0, "max": 0},
    "published_reference": {"publication_id": "spub_...", "published_activity_id": "...", "original_duration": {"state": "...", "value": "1.500"}, "remaining_duration": {"...": "..."}, "start": {"state": "...", "value": "YYYY-MM-DD", "marker": "*"}, "finish": {"...": "..."}}
  }],
  "relationships": [{"pred": "<key>", "succ": "<key>", "type": "FS | SS | FF | SF", "lag_minutes": 0}]
}
```

| Rule | Value |
|---|---|
| Fixed keys | every key above is present; absent values are explicit `null`; `constraints` is a list |
| Ordering | `calendars` by `key`; `exceptions` by `date`; `activities` by `key`; `constraints` by `SNET, FNET, SNLT, FNLT, MSO, MFO`; `relationships` by `(pred, succ)`; Python `str` order (code points) |
| Strings | NFC (`normalize_display_text` for `name` and each `wbs_path` label) |
| Numbers | Python `int` only (never `bool`); no `float`, no `Decimal` |
| Instants | `YYYY-MM-DDTHH:MM`, minute resolution, naive (S6-D07) |
| Hash | `content_sha256 = sha256(b"schedule-scenario-content-v1\n" + canonical_json_bytes(document))` |
| Excluded | every identifier, label, note, provenance and time of the version |
| Bound | ≤ 33,554,432 bytes (32 MiB) or `invalid_request(CONTENT_SIZE)` |

The change set is stored as `schedule-scenario-change-set-v1` (`{"schema", "ops"}`, request
order) with `change_set_sha256 = sha256(b"schedule-scenario-change-set-v1\n" + canonical)`.

### 2.4 Activities and keys

| Field | Rule |
|---|---|
| `key` | baseline: the `sact_` id; added: `x:` + `[A-Za-z0-9_.-]{1,64}`; unique per version; `activity.add` refuses an `sact_` key; a removed `sact_` activity cannot be restored in that Scenario (S6-U02) |
| `name` | 1..2,000 characters after `normalize_display_text` |
| `kind` | `task` or `milestone`; a milestone has both durations 0 |
| `wbs_path` | null or 1..32 labels of 1..2,000 characters; inert |
| `calendar` | null (= default) or an existing key |
| `original_minutes` | null or 0..5,256,000; informational |
| `remaining_minutes` | null or 0..5,256,000; the scheduled duration; null rejects the run (`missing_duration`) |
| `published_reference` | set only by the snapshot; null for added activities |

### 2.5 Baseline snapshot (version 1 from a publication)

Input: an owned, eligible, non-intake publication (else `conflict(STATUS)`), named directly
(`from_publication_id`) or through an approved Baseline (`from_baseline_id`);
`minutes_per_source_unit` (1..1,440, required, no default — the PDF carries no unit);
1..32 calendars; `default_calendar`; optional `data_date_time` (`HH:MM`, default `00:00`).

| Content field | Snapshot value |
|---|---|
| `data_date` | publication `data_date` at `data_date_time` |
| `settings` | given default calendar; `lag_calendar = predecessor`, `progress_policy = retained_logic`, `must_finish_by = null`, threshold 0 |
| activities | exactly the accepted run's `activity`/`milestone` rows (≤ 25,000); never `ambiguous` or summary rows |
| `key`, `name`, `wbs_path` | `schedule_activity_id`, `activity_name`, `hierarchy_path` |
| `kind` | `activity → task`, `milestone → milestone` |
| `calendar` | null |
| `original_minutes` / `remaining_minutes` | for a `published_value` cell `v` (`0 ≤ v`): `m = int((v * minutes_per_source_unit).quantize(Decimal(1), ROUND_HALF_EVEN))`; if `m > 5,256,000` the field is **null** and counted in `durations_out_of_range` (never clamped; the run then rejects with `missing_duration` until the client sets it, R8-F05); other states: null (counted `original_missing`/`remaining_missing`); a milestone gets 0 and 0; a non-integral product is counted in `durations_quantized` |
| `constraints`, `progress`, `distribution` | empty, null, null (the `*` marker is never read) |
| `published_reference` | publication id, published Activity ID and the 4 cells as S5b-2 §3.5.2 serializes them |
| relationships | none |

`snapshot_report` = `{activities, milestones, durations_quantized, durations_out_of_range,
original_missing, remaining_missing}`.

### 2.6 Relationships

`{pred, succ, type ∈ FS|SS|FF|SF, lag_minutes}`; both keys exist; `pred ≠ succ`; ≤ 1
relationship per ordered pair (S6-D05); `lag_minutes ∈ [−1,051,200, 1,051,200]` working
minutes on the lag calendar (on a 480-minute-per-day calendar that is about 8.4 calendar
years; the horizon check of section 3.2 still bounds it, R8-F19). Cycles are storable and
reported by the run.

### 2.7 Calendars

| Item | Rule |
|---|---|
| `key` | `[a-z0-9_-]{1,32}`, unique; 1..32 per version |
| `week` | 7 day patterns, Monday first |
| intervals | 0..4 per day, `0 ≤ s < e ≤ 1,440`, sorted, strictly separated (`e_k < s_{k+1}`) |
| working week | ≥ 1 working minute across the 7 patterns, else `invalid_request(CALENDAR)` |
| `exceptions` | dates 2000-01-01..2099-12-31, unique; replace the day's pattern; empty = holiday; ≤ 1,000 per calendar, ≤ 2,000 per version |
| default | must exist; removing the default or a referenced calendar is refused |

### 2.8 Constraints, progress, durations, distributions

**Constraints:** at most 1 early (`SNET`/`FNET`) and 1 late (`SNLT`/`FNLT`), or exactly 1
mandatory (`MSO`/`MFO`) alone; `at` within the horizon. They apply only to `not_started`
activities (S6-D15, recorded as operator decision S6-O16); a started activity's constraint is
kept and reported `constraint_ignored_started`.

| Type | Kind | Forward | Backward |
|---|---|---|---|
| `SNET` | hard early | start bound `at` | — |
| `FNET` | hard early | start bound `retreat(C, at, d)` | — |
| `SNLT` | soft late | — (violation reported) | finish bound `advance(C, at, d)` |
| `FNLT` | soft late | — (violation reported) | finish bound `at` |
| `MSO` | mandatory | start := `at` | finish := `advance(C, at, d)` |
| `MFO` | mandatory | start := `retreat(C, at, d)` | finish := `at` |

**Progress:** null = `not_started`; `{actual_start, null}` = `in_progress`; both =
`complete`; `actual_start ≤ actual_finish ≤ data_date`; finish without start refused;
`complete` forces `remaining_minutes = 0`. Out-of-sequence progress is stored and reported.

**Distributions** (data only; the server never samples), integer minutes in
`[0, 5,256,000]`, applying to remaining duration: `triangular` (`min ≤ mode ≤ max`,
`min < max`), `pert` (same), `uniform` (`min < max`), `bounded_normal` (`sd > 0`,
`min ≤ mean ≤ max`, `min < max`).

### 2.9 Change-set grammar and application

1..5,000 ops, canonical ≤ 4,194,304 bytes, applied **in request order** to a working copy of
the parent content, each validated against the state left by the ops before it; then the
whole content is re-validated and canonicalized. The pure function returns
`ChangeSetRefusal(op_index, op_error)` on the first failure; a failure of the final
re-validation is `op_index = len(ops)`, `op_error = content_invalid` (R8-F18). The public
error is `invalid_request` with the safe details `CHANGE_SET` and the `SafeDetail` member
named `change_set_<op_error>`; the error contract carries only closed tokens, so `op_index`
is not disclosed (S6-U09). Nothing is written on a refusal. An empty effective change is
allowed and recorded.

| Op | Fields | Effect / refusal |
|---|---|---|
| `activity.add` | `key` (`x:`), `name`, `kind`, `calendar`, `original_minutes`, `remaining_minutes`, `wbs_path` | refuses an existing or `sact_` key |
| `activity.edit` | `key`, any of `name`, `kind`, `calendar`, `wbs_path` | `kind → milestone` needs both durations 0 |
| `activity.remove` | `key` | also removes its relationships (`application_report.relationships_removed`) |
| `duration.set` | `key`, `original_minutes` and/or `remaining_minutes` | — |
| `distribution.set` / `.clear` | `key`, `distribution` | — |
| `relationship.add` / `.edit` / `.remove` | `pred`, `succ`, `type`, `lag_minutes` | existing pair, self-loop, missing key refused |
| `calendar.put` / `.remove` | calendar / `key` | default or referenced calendar not removable |
| `calendar.exception.put` / `.remove` | `key`, `date`, `intervals` | — |
| `constraint.set` / `.clear` | `key`, `type`, `at` | slot rules |
| `progress.set` / `.clear` | `key`, `actual_start`, `actual_finish`, `remaining_minutes` | section 2.8 rules against the current working data date |
| `data_date.set` | `at` | checked again in the final re-validation |
| `settings.set` | any settings field (threshold 0..525,600) | — |

`op_error` (closed, 14): `unknown_op`, `invalid_field`, `key_exists`, `key_absent`,
`source_key_refused`, `relationship_exists`, `relationship_absent`, `self_loop`,
`calendar_absent`, `calendar_in_use`, `constraint_conflict`, `progress_invalid`,
`bound_exceeded`, `content_invalid`. `application_report` = `{ops_applied,
relationships_removed, content_changed}`.

### 2.10 Version and storage bounds

| Bound | Value |
|---|---|
| activities / relationships | 25,000 / 100,000 |
| calendars / exceptions | 32 / 1,000 per calendar, 2,000 per version |
| versions per Scenario | 500 |
| Scenarios per Principal / versions per Principal | 200 / 20,000 |
| content per version | 32 MiB canonical |
| stored plane bytes per Principal (canonical content + results + outputs) | 2 GiB (`rate_limited(STORAGE_QUOTA)` beyond) |
| new stored plane bytes per Principal per rolling day | 256 MiB |

---

## 3. CPM engine `my-pa-cpm-v1`

### 3.1 Time model

Integer minutes on one naive axis: minute `0` = `2000-01-01T00:00`, `H = 52,596,000` =
`2100-01-01T00:00`; valid instants `0 ≤ t ≤ H`. Minute `m` is `[m, m+1)`. Day index
`m // 1440`, minute-of-day `m % 1440`, weekday from `date.weekday()`. No `float` (S6-D06).

### 3.2 Calendar functions (calendar `C`)

| Function | Definition |
|---|---|
| `working(C, m)` | the day's pattern is the exception's intervals if the date has one, else `week[weekday]`; `m` works iff its minute-of-day is in some `[s, e)` |
| `W(C, a, b)` | `a ≤ b`: count of working `m` with `a ≤ m < b`; `a > b`: `−W(C, b, a)` (signed, additive) |
| `advance(C, t, d)` | `d = 0`: `t`; else the smallest `t′ > t` with `W(C, t, t′) = d` |
| `retreat(C, t, d)` | `d = 0`: `t`; else the largest `t′ < t` with `W(C, t′, t) = d` |
| `next_work(C, t)` | smallest `m ≥ t` with `working(C, m)` |
| `prev_end(C, t)` | largest `m ≤ t` with `working(C, m − 1)` |
| `shift(C, t, L)` | `advance(C, t, L)` if `L ≥ 0`, else `retreat(C, t, −L)` |
| `twenty_four_hour` | every minute works |

A result outside `[0, H]` stops the run: `rejected`, 1 issue `horizon_exceeded` naming the
activity being computed and, when the failing call came from a relationship bound, that
relationship (`pred`, `succ`), else `pred = succ = null` (R8-F02). Implementation
requirement: per-calendar cumulative day tables over the span reached, `O(log days)` per
call; minute loops only in tests.

### 3.3 States, durations, lag calendar

`state(j)` from progress. `C_j` = the activity's calendar or the default. `d_j =
remaining_minutes`. `snap(j, t) = next_work(C_j, t)` if `d_j > 0` else `t`;
`snap_back(j, t) = prev_end(C_j, t)` if `d_j > 0` else `t`. `Lc(i, k)` = `C_i`
(`predecessor`, default), `C_k` (`successor`) or `twenty_four_hour`. `D` = the data date.

### 3.4 Validation, topological order and cycles

The first failing check rejects the run with 1 issue per offending element: `empty_network`
(subject fields null), `unknown_calendar` (per activity), `dangling_relationship` (per
relationship), `missing_duration` (per incomplete activity with null `remaining_minutes`),
then the sort.

**Order.** Kahn with a min-heap on `key`; successors decremented in `succ` order; the pop
sequence is the topological order and `topo_index`.

**Cycle.** If not all are popped, `R` = residual set; from `s = min(R)` step repeatedly to the
smallest-key predecessor inside `R` until a node repeats; the repeated segment, reversed into
successor order and rotated to its smallest key, is the cycle. The run is `rejected` with 1
issue `cycle_detected` (subject fields null) and the summary carries `cycle` (first 100 keys),
`cycle_length` and `residual_count = |R|` (R8-F02); all 3 are null when there is no cycle.

### 3.5 Forward pass (topological order)

1. `complete`: `ES = actual_start`, `EF = actual_finish`.
2. Bounds from an incoming `i → j` (lag `L`, `Lc = Lc(i, j)`):

   | Type | Bound on `j`'s start |
   |---|---|
   | FS | `shift(Lc, EF_i, L)` |
   | SS | `shift(Lc, ES_i, L)` |
   | FF | `retreat(C_j, shift(Lc, EF_i, L), d_j)` |
   | SF | `retreat(C_j, shift(Lc, ES_i, L), d_j)` |

3. `not_started`: `x = snap(j, max({D} ∪ bounds ∪ {SNET at} ∪ {retreat(C_j, FNET at,
   d_j)}))`. Mandatory pin `p` (`MSO`: `at`; `MFO`: `retreat(C_j, at, d_j)`): if `p < D`
   report `mandatory_constraint_before_data_date` and drop the pin in both passes; else if
   `x > p` report `mandatory_constraint_overrides_logic`; then `x = p` (no snap).
   `ES = RS = x`, `EF = advance(C_j, x, d_j)`.
4. `in_progress`: `ES = actual_start`; `RS = snap(j, max({D} ∪ bounds))` with the step 2
   bounds under `retained_logic` and none under `progress_override`; `EF = advance(C_j, RS,
   d_j)`; constraints ignored.

`PF = max EF` over all activities.

### 3.6 Backward pass (reverse topological order)

`j → k` is **considered** unless `k` is `complete`, or `k` is `in_progress` under
`progress_override`.

1. `complete`: `LS = ES`, `LF = EF`; floats null; never critical.
2. Finish bounds from each considered `j → k` (`Lc = Lc(j, k)`):

   | Type | Bound | `j` `in_progress` |
   |---|---|---|
   | FS | `shift(Lc, LS_k, −L)` | applies |
   | FF | `shift(Lc, LF_k, −L)` | applies |
   | SS | `advance(C_j, shift(Lc, LS_k, −L), d_j)` | skipped |
   | SF | `advance(C_j, shift(Lc, LF_k, −L), d_j)` | skipped |

3. If step 2 produced no bound, add `must_finish_by` if set, else `PF` (S6-D08, accepted by
   R8 ruling R-2).
4. `not_started` only: add `FNLT at` and `advance(C_j, SNLT at, d_j)`.
5. `y = snap_back(j, min(bounds))`; a kept pin overrides (`MFO`: `y = at`; `MSO`: `y =
   advance(C_j, at, d_j)`). `LF = y`, `LS = retreat(C_j, y, d_j)` (late remaining start for
   `in_progress`).

### 3.7 Floats

| Quantity | Definition |
|---|---|
| `TF_j` (incomplete) | `W(C_j, EF_j, LF_j)`, signed (= `W(C_j, RS_j, LS_j)`) |
| `rff_r` (considered `i → k`) | `B_r` = `shift(Lc, EF_i, L)` (FS/FF) or `shift(Lc, ES_i, L)` (SS/SF); `Q_r` = `RS_k` (FS/SS) or `EF_k` (FF/SF); `rff_r = W(C_k, B_r, Q_r)` |
| `FF_j` (incomplete) | `min({TF_j} ∪ {rff_r : considered outgoing})` |
| driving / violated | `rff_r = 0` / `rff_r < 0` |

### 3.8 Critical activities and paths

Critical = incomplete and `TF ≤ critical_float_threshold_minutes`. Critical graph = critical
activities and driving relationships between them. Start nodes = critical activities with no
incoming critical edge, key order; depth-first, successors in key order; a path is emitted at
each node with no outgoing critical edge. Emission stops at `MAX_CRITICAL_PATHS = 16` or before
a path that would take the emitted key total past `MAX_CRITICAL_PATH_KEYS = 50,000`.
`critical_path_count` = maximal paths by dynamic programming, saturating at 1,000,000;
`critical_paths_truncated = count > emitted`.

### 3.9 Open ends

`open_starts` / `open_finishes` = activities with no incoming / outgoing relationship; first
1,000 each by key, with full counts.

### 3.10 Issues (closed, 16)

| Code | Severity | Emitted when (subject) |
|---|---|---|
| `empty_network` | error | section 3.4 (none) |
| `unknown_calendar` | error | section 3.4 (activity) |
| `dangling_relationship` | error | section 3.4 (relationship) |
| `missing_duration` | error | section 3.4 (activity) |
| `cycle_detected` | error | section 3.4 (none; cycle in summary) |
| `horizon_exceeded` | error | section 3.2 (activity, optional relationship) |
| `operation_budget_exceeded` | error | section 3.11 (none) |
| `out_of_sequence` | warning | `i → k`, `k` started and: FS with `i` not complete; SS with `i` not started; FF with `k` complete and `i` not complete; SF with `k` complete and `i` not started (relationship) |
| `constraint_ignored_started` | warning | a started activity has a constraint (activity) |
| `mandatory_constraint_overrides_logic` | warning | section 3.5 (activity) |
| `mandatory_constraint_before_data_date` | warning | section 3.5 (activity) |
| `start_no_later_than_violated` | warning | `ES_j > SNLT at` (activity) |
| `finish_no_later_than_violated` | warning | `EF_j > FNLT at` (activity) |
| `must_finish_by_violated` | warning | `PF > must_finish_by` (none) |
| `relationship_violated` | warning | `rff_r < 0` (relationship) |
| `dangling_finish` | warning | an incomplete activity with ≥ 1 outgoing relationship and none of type FS or FF: its finish is driven only by the open-end bound (R8-F03) (activity) |

An issue is `{code, severity, activity_key, pred, succ}` (nullable subjects); sorted by
`(error before warning, code in table order, activity_key, pred, succ)`, null first; first
1,000 listed; `issue_counts` holds all 16 codes.

### 3.11 Output, hash, determinism, budget, execution

`schedule-cpm-result-v1`:

```json
{
  "schema": "schedule-cpm-result-v1",
  "engine_version": "my-pa-cpm-v1",
  "input_content_sha256": "<64 hex>",
  "status": "computed | rejected",
  "summary": {"data_date": "...", "project_finish": "... | null", "must_finish_by": "... | null", "activity_count": 0, "relationship_count": 0, "critical_count": 0, "negative_float_count": 0, "open_start_count": 0, "open_finish_count": 0, "critical_path_count": 0, "critical_paths_truncated": false, "cycle": null, "cycle_length": null, "residual_count": null},
  "issue_counts": {"<code>": 0},
  "issues": [],
  "open_starts": [], "open_finishes": [],
  "critical_paths": [["<key>"]],
  "activities": [{"key": "...", "state": "not_started | in_progress | complete", "topo_index": 0, "early_start": "...", "remaining_start": "...", "early_finish": "...", "late_start": "...", "late_finish": "...", "total_float_minutes": 0, "free_float_minutes": 0, "critical": false}],
  "relationships": [{"pred": "...", "succ": "...", "considered": true, "slack_minutes": 0, "driving": true}]
}
```

A `rejected` run has `project_finish = null` and empty lists. `result_sha256 =
sha256(b"schedule-cpm-result-v1\n" + canonical)`. **Result bound 64 MiB** (R8-F16: a maximal
network with 66-character keys measures about 34 MB, so the bound is unreachable from valid
content; persistence treats a larger document as `internal_error`).

- **Determinism.** A pure function of `(content bytes, engine_version)`: no clock,
  randomness, environment, locale or unsorted `set`/`dict` iteration reaching the output, no
  `float`. Byte-identical on every platform. Any change that could alter a result bumps the
  engine version; a run is keyed by `(version_id, engine_version)`.
- **Operation budget** (R8-F04). `run_cpm(content, *, operation_budget:
  int = CPM_OPERATION_BUDGET)`, keyword-only, production value `CPM_OPERATION_BUDGET =
  4,000,000`, never set from a request. Counting rule: +1 per heap pop; +1 per relationship
  examined by the sort; +1 per activity entered and +1 per relationship examined in the
  forward pass, the backward pass and the slack phase; +1 per outermost calendar-function call
  (`W`, `advance`, `retreat`, `next_work`, `prev_end`; `shift` counts as its inner call); +1
  per depth-first step and per dynamic-programming node of section 3.8. Before each increment,
  if the counter equals the budget, the run stops: `rejected`, 1 issue
  `operation_budget_exceeded` (no subject). Test: for G02 the frozen exact count `n` computes
  with budget `n` and rejects with `n − 1` (P16). At the maxima the work is ≤ 2,100,000.
- **Execution** (R8 ruling R-5). `schedule_cpm_runs.create` computes **outside** any database
  transaction or lock: it reads the version, computes, then inserts by the natural key
  `(principal_id, version_id, engine_version)` with `ON CONFLICT DO NOTHING` and returns the
  existing run on conflict. At most 1 concurrent compute per Principal (a process-local lock
  plus `pg_try_advisory_lock` on the Principal; a second caller gets `conflict(CPM_RUN)`
  without computing). S6-1 measures the maximal network (target ≤ 10 s on the CI host); a
  miss moves compute to a worker plane by a contract revision **before** S6-3 (S6-U06).

### 3.12 Golden vectors (S6-1 commits each with these exact expectations)

Common: calendar `std` = Monday–Friday `[[480, 960]]`, weekend `[]`; default `std`;
`D = 2027-01-04T00:00` (Monday) unless stated; `predecessor`, `retained_logic`, threshold 0;
"1d" = 480 minutes. Each was hand-computed and cross-checked with a throwaway minute-by-minute
implementation (not committed); R8 re-derived G01–G16 by hand.

| # | Network | Activity: ES – EF / LS – LF / TF / FF | Critical paths | Issues / other |
|---|---|---|---|---|
| G01 | A 3d | A 01-04 08:00 – 01-06 16:00 / same / 0 / 0 | [A] | PF 01-06 16:00 |
| G02 | A 1d →FS B 2d →FS D 1d; A →FS C 1d →FS D | A 01-04 08:00 – 01-04 16:00 / same / 0 / 0; B 01-05 08:00 – 01-06 16:00 / same / 0 / 0; C 01-05 08:00 – 01-05 16:00 / 01-06 08:00 – 01-06 16:00 / 480 / 480; D 01-07 08:00 – 01-07 16:00 / same / 0 / 0 | [A, B, D] | slack A→B 0, A→C 0, B→D 0, C→D 480 |
| G03 | A 3d; A →SS+480 B 2d; A →FF+480 C 1d | A 01-04 08:00 – 01-06 16:00 / same / 0 / 0; B 01-05 08:00 – 01-06 16:00 / 01-06 08:00 – 01-07 16:00 / 480 / 480; C 01-07 08:00 – 01-07 16:00 / same / 0 / 0 | [A, C] | `dangling_finish` none (A has FF) |
| G04 | A 2d →FS−240 B 1d | A 01-04 08:00 – 01-05 16:00 / same / 0 / 0; B 01-05 12:00 – 01-06 12:00 / same / 0 / 0 | [A, B] | — |
| G05 | A 1d →SF+1440 B 1d | A 01-04 08:00 – 01-04 16:00 / same / 0 / 0; B 01-06 08:00 – 01-06 16:00 / same / 0 / 0 | [A, B] | `dangling_finish` (A) |
| G06a | `c6` = Mon–Sat 08:00–16:00; A 1d on `c6`, `SNET 01-08T00:00`; A →FS+960 B 1d; `predecessor` | A 01-08 08:00 – 01-08 16:00 / same / 0 / 0; B 01-12 08:00 – 01-12 16:00 / same / 0 / 0 | [A, B] | lag on `c6` ends 01-11 16:00 |
| G06b | G06a, `successor` | A 01-08 08:00 – 01-08 16:00 / 01-09 08:00 – 01-09 16:00 / 480 / 0; B 01-13 08:00 – 01-13 16:00 / same / 0 / 0 | [B] | lag on `std` ends 01-12 16:00 |
| G06c | G06a, `twenty_four_hour` | A as G06b (TF 480, FF 0); B 01-11 08:00 – 01-11 16:00 / same / 0 / 0 | [B] | slack A→B on `std` = 0 (on `c6` it would be 480) |
| G07 | `std` + exception `2027-01-05: []`; A 3d | A 01-04 08:00 – 01-07 16:00 / same / 0 / 0 | [A] | — |
| G08 | A 2d →FS B 2d `FNLT 01-05T16:00`; C 1d `SNET 01-06T12:00` | A 01-04 08:00 – 01-05 16:00 / 12-31 08:00 – 01-01 16:00 / −960 / −960; B 01-06 08:00 – 01-07 16:00 / 01-04 08:00 – 01-05 16:00 / −960 / −960; C 01-06 12:00 – 01-07 12:00 / 01-07 08:00 – 01-07 16:00 / 240 / 240 | [A, B] | `finish_no_later_than_violated` (B); negative-float count 2 |
| G09 | A 2d →FS B 1d `MSO 01-05T08:00` | A 01-04 08:00 – 01-05 16:00 / 01-01 08:00 – 01-04 16:00 / −480 / −480; B 01-05 08:00 – 01-05 16:00 / same / 0 / 0 | [A], [B] | `mandatory_constraint_overrides_logic` (B), `relationship_violated` (A→B, −480) |
| G10 | A 5d; `must_finish_by 01-07T16:00` | A 01-04 08:00 – 01-08 16:00 / 01-01 08:00 – 01-07 16:00 / −480 / −480 | [A] | `must_finish_by_violated` |
| G11a | `D = 01-06T00:00`; A complete 01-04 08:00 – 01-04 16:00; B started 01-05 08:00, remaining 2d; C 1d; E started 01-05 08:00, remaining 1d; A→B, B→C, C→E FS | A TF/FF null; B ES 01-05 08:00, RS 01-06 08:00, EF 01-07 16:00 / 01-06 08:00 – 01-07 16:00 / 0 / 0; C 01-08 08:00 – 01-08 16:00 / same / 0 / 0; E ES 01-05 08:00, RS 01-11 08:00, EF 01-11 16:00 / 01-11 08:00 – 01-11 16:00 / 0 / 0 | [B, C, E] | `out_of_sequence` (C→E); slack A→B 480 |
| G11b | G11a, `progress_override` | B as G11a; C 01-08 08:00 – 01-08 16:00 / same / 0 / 0; E ES 01-05 08:00, RS 01-06 08:00, EF 01-06 16:00 / 01-08 08:00 – 01-08 16:00 / 960 / 960 | [B, C] | `out_of_sequence` (C→E); C→E not considered |
| G12 | M0 milestone →FS A 1d →FS M1 milestone | M0 01-04 00:00 – 01-04 00:00 / 01-04 08:00 – 01-04 08:00 / 0 / 0; A 01-04 08:00 – 01-04 16:00 / same / 0 / 0; M1 01-04 16:00 – 01-04 16:00 / same / 0 / 0 | [M0, A, M1] | milestones never snapped |
| G13 | A 1d → B 2d → E 1d; A → C 2d → E (FS) | all TF 0; B and C 01-05 08:00 – 01-06 16:00; E 01-07 08:00 – 16:00 | [A, B, E], [A, C, E] | `critical_path_count` 2 |
| G14 | A→B, B→C, C→A, D→A, C→Z (FS, 1d) | rejected | — | `cycle_detected`; summary `cycle` [A, B, C], `cycle_length` 3, `residual_count` 4 |
| G15 | A 1d → B 3d → E 1d; A → C 1d → X 1d → E (FS) | A, B, E TF 0; C 01-05 08:00 – 16:00 / 01-06 08:00 – 16:00 / 480 / 0; X 01-06 08:00 – 16:00 / 01-07 08:00 – 16:00 / 480 / 480 | [A, B, E] | FF < TF |
| G16 | A with `remaining_minutes = null` | rejected | — | `missing_duration` (A) |
| G17 | A 1d `FNET 01-06T16:00` | A 01-06 08:00 – 01-06 16:00 / same / 0 / 0 | [A] | FNET forward |
| G18 | A 2d →FS B 1d `SNLT 01-05T08:00` | A 01-04 08:00 – 01-05 16:00 / 01-01 08:00 – 01-04 16:00 / −480 / −480; B 01-06 08:00 – 01-06 16:00 / 01-05 08:00 – 01-05 16:00 / −480 / −480 | [A, B] | `start_no_later_than_violated` (B) |
| G19 | A 1d `MFO 01-06T16:00`; B 1d | A 01-06 08:00 – 01-06 16:00 / same / 0 / 0; B 01-04 08:00 – 01-04 16:00 / 01-06 08:00 – 01-06 16:00 / 960 / 960 | [A] | MFO pins both passes |
| G20 | `D = 01-06T00:00`; A 1d `MSO 01-04T08:00` | A 01-06 08:00 – 01-06 16:00 / same / 0 / 0 | [A] | `mandatory_constraint_before_data_date` (A) |
| G21 | `D = 01-06T00:00`; A started 01-05 08:00, remaining 1d, `SNET 01-08T00:00` | A ES 01-05 08:00, RS 01-06 08:00, EF 01-06 16:00 / 01-06 08:00 – 01-06 16:00 / 0 / 0 | [A] | `constraint_ignored_started` (A) |
| G22 | `D = 01-06T00:00`; A started 01-05 08:00, remaining 2d; A →SS B 1d | A ES 01-05 08:00, RS 01-06 08:00, EF 01-07 16:00 / 01-06 08:00 – 01-07 16:00 / 0 / 0; B 01-06 08:00 – 01-06 16:00 / 01-07 08:00 – 01-07 16:00 / 480 / 480 | [A] | S6-D08: A's only outgoing (SS) is skipped, open-end bound PF; `dangling_finish` (A) |
| G23 | `D = 01-06T00:00`, `progress_override`; A 1d →SS B started 01-05 08:00, remaining 1d | A 01-06 08:00 – 01-06 16:00 / same / 0 / 0; B ES 01-05 08:00, RS 01-06 08:00, EF 01-06 16:00 / 01-06 08:00 – 01-06 16:00 / 0 / 0 | [A], [B] | `out_of_sequence` (A→B); `dangling_finish` (A); A→B not considered, so not a critical edge |
| G24 | `D = 2099-12-31T00:00` (Thursday); A 2d | rejected | — | `horizon_exceeded` (A, no relationship) |
| S1 | snapshot, `minutes_per_source_unit = 480`: OD `1.500`, RD `0.001`, OD `999999999.000` (3 activities) | `720`; `0` (0.48 → 0, quantized); null (out of range) | — | `durations_quantized` 1, `durations_out_of_range` 1 |

The `dangling_finish` rule is structural (any outgoing relationship, none FS/FF), whatever is
considered. S6-1 also freezes a `result_sha256` per
vector (a change needs an engine-version bump) and a `content_sha256` for G02.

### 3.13 Oracle approach

1. **Calendar oracle:** a test-only minute-by-minute implementation over seeded random
   calendars (`random.Random(seed)` in the test, fixed seeds) and windows ≤ 21 days,
   compared with every calendar function at every probed instant.
2. **Longest-path oracle:** on `twenty_four_hour`, seeded random DAGs of 2..7 activities, all
   4 types, lags in `[−480, 480]`, durations in `[0, 960]`, no constraints or progress: `ES`
   equals the maximum over **every enumerated path** from the data-date source of summed
   weights (FS `d_i + L`, SS `L`, FF `d_i + L − d_j`, SF `L − d_j`); `LF` likewise to the sink;
   TF and the critical set follow; ≥ 2,000 DAGs.
3. **Properties** on seeded random networks on `std`: byte-identical output across 2 runs and
   across input permutations; `FF ≤ TF`; `TF = W(C, RS, LS) = W(C, EF, LF)`. Restricted to
   **FS-only networks with non-negative lags, no constraint, progress or `must_finish_by`**
   (R8-F03: SS/FF/SF and leads admit dangling-finish float and the duration paradox): at least
   1 activity has `TF = 0`; every critical path ends at an activity with `EF = PF`; increasing
   one remaining duration never decreases `PF`.

---

## 4. Client-asserted outputs

### 4.1 Document `schedule-scenario-output-v1` (canonical ≤ 1,048,576 bytes)

| Part | Fields and bounds |
|---|---|
| binding | `version_id` (owned), `content_sha256` (= the version's), optional `base_cpm_run_id` (an owned `computed` run of that version) |
| `kind` | `monte_carlo` \| `criticality` \| `sensitivity` |
| `run_config` | `tool_name`, `tool_version` (`[A-Za-z0-9._-]{1,64}`), `seed` (`[A-Za-z0-9_-]{1,128}`), `iterations` 1..1,000,000, `sampling = independent`, `engine` ∈ `my-pa-cpm-v1` \| `server_runs` \| `other`, `distribution_spec_sha256` |
| `finish_percentiles` | ≤ 99 `{p: 1..99, finish}`, `p` strictly increasing, `finish` non-decreasing |
| `finish_histogram` | ≤ 200 contiguous bins `{start, end, count}`, `start < end`, counts sum to `iterations` |
| `deterministic_finish` | equals `base_cpm_run_id`'s `project_finish` when given |
| `activity_criticality` | ≤ 25,000 `{activity_key, critical_iterations: 0..iterations}`, keys unique and present |
| `activity_finish_percentiles` | ≤ 2,000 activities × ≤ 9 `{p, finish}`, same monotonic rules |
| `sensitivity` | ≤ 2,000 `{activity_key, metric ∈ spearman_rank_milli \| duration_cruciality_milli, value: −1,000..1,000}` |

Integers only; unknown key `invalid_request(OUTPUT)`; `payload_sha256 =
sha256(b"schedule-scenario-output-v1\n" + canonical)`.

### 4.2 Server checks (schema, bounds, consistency only)

Shape; binding equalities; monotonicity and sums; keys exist; `distribution_spec_sha256`
equals the server's recomputation; kind-specific presence. The server never re-samples or
judges plausibility. Labels `authority = client_asserted`, `authoritative = false`.

### 4.3 Distribution digest

`sha256(b"schedule-scenario-distributions-v1\n" + canonical_json_bytes([{"key",
"distribution"} for each activity with one, by key]))`, stored on every version.

---

## 5. Scenario and schedule lineage (ADR-015 decision 17)

### 5.1 New endpoint families (`RecordFamily`, appended)

| Family | Id kind | Linkable when | Read grant set (`LINEAGE_FAMILY_READS`) |
|---|---|---|---|
| `schedule_publication` | `spub` | eligible and not intake | `schedule_publications.read`, `schedule_publications.list` |
| `schedule_activity` | `sact` | visible (S5b-1 U-03) and its Series is not intake | `schedule_activities.history`, `schedule_activities.list` |
| `schedule_baseline` | `sbl` | exists (any lifecycle state; reads show it) | `schedule_baselines.read`, `schedule_baselines.list` |
| `scenario` | `sscn` | exists | `schedule_scenarios.read`, `schedule_scenarios.list` |
| `scenario_version` | `sscv` | exists | `schedule_scenario_versions.read` |
| `scenario_output` | `ssco` | exists | `schedule_scenario_outputs.read`, `schedule_scenario_outputs.list` |

The 6 families are linkable only while the plane is effective and `MY_PA_LINEAGE_ENABLED` is
on; otherwise naming one in a **new** assertion is answered as absent, and reads withhold such
endpoints as they withhold an unreadable family (S3 §6.4), with no hidden count.

**Existing links when a family is withheld** (R8-F10). The human channel's `confirm`, `end`
and `contest` of an existing link, and Issue close/reopen, never require a withheld endpoint
to be readable: they act on the link's identity and head, re-validate only the endpoints the
caller can see, and record the withheld endpoint by its stored identifier. A
`client_identified` link to a withheld endpoint therefore stays confirmable or endable, and
an Issue never becomes unclosable because the plane was switched off
(`test_withheld_family_link_stays_confirmable_and_endable`, S6-3).

### 5.2 Relations

| Relation | Kind | From | To | Evidence rule | Use case |
|---|---|---|---|---|---|
| `concerns` (new) | semantic | `scenario`, `scenario_version`, `scenario_output` | `situation`, `constraint`, `task`, `commitment`, `schedule_activity`, `schedule_baseline` | none | a what-if or simulation is about an Issue, Constraint, activity or baseline |
| `delays` (new) | semantic | `constraint`, `situation` | `schedule_activity` | ≥ 1 exact-version `corroborates` anchor | a cited causal claim |
| `mitigates` (new) | semantic | `task`, `commitment`, `scenario_version` | `constraint`, `situation` | ≥ 1 exact-version `corroborates` anchor | a cited recovery claim |
| `discusses` (widened) | semantic | `meeting`, `meeting_note_version` | + `schedule_publication`, `schedule_activity`, `schedule_baseline`, `scenario`, `scenario_output` | unchanged | a meeting reviewed it |
| `originated_from` (widened) | semantic | + `scenario_version`, `schedule_baseline` | `meeting_note_version`, `capture_version` | unchanged (exact `origin` anchor) | a version's change set, or a baseline's approval, came from that note or capture (the "approved by" evidence link) |

`issue_member` and the other relations are not widened (S6-D12). The 3 new relations are
contestable, not composite-only, not symmetric.

**Native virtual edges** (columns, never ledger rows; a client cannot assert them):
`scenario_version_of`, `scenario_version_parent`, `scenario_based_on_publication`,
`scenario_based_on_baseline`, `scenario_forked_from_version`, `scenario_output_of`,
`schedule_baseline_designates` (Baseline → its publication), `schedule_baseline_supersedes`
(Baseline → the Baseline it supersedes).

### 5.3 Validators

Strict `IdKind` → Principal ownership (foreign = `not_found`, byte-identical to absent) →
family linkability → relation matrix → evidence rule → `FOR SHARE` on each named row in the S1
`(family token, identifier)` order. S3.1 provenance, budgets, idempotency, replay and the
"clients never remove accepted lineage" rule are unchanged. No link is ever created from
similarity, shared names, dates or WBS.

### 5.4 Schema and ADR process

S6-2's first revision widens, with the Python vocabulary, the `record_links` family CHECKs,
the family → identifier CHECKs, the relation-type CHECK and `a_record_link_pair_is_admitted`;
`LINEAGE_READ_GENERATION` 1 → 2. ADR-015 decision 17 is the amendment decision 6 requires.

---

## 6. Capabilities (S6-3)

### 6.1 Names, kinds, purposes (the one authoritative count set, R8-F21)

3 new purposes, appended: `schedule_analysis_authoring` (client-usable writes; joins
`_WRITE_PURPOSES`), `schedule_analysis_read` (reads) and `schedule_baseline_approval`
(operator-only writes; joins `_WRITE_PURPOSES`, as `schedule_import` did). All 26 names are
scopeless.

| Capability | Kind | Purpose | Summary (first docstring line) |
|---|---|---|---|
| `schedule_scenarios.create` | write | `schedule_analysis_authoring` | Create a Schedule Scenario whose version 1 is a snapshot of one eligible publication or approved baseline, or a copy of an existing scenario version. |
| `schedule_scenario_versions.create` | write | same | Append one immutable version to a Scenario by applying a bounded change set to its current head version. |
| `schedule_cpm_runs.create` | write | same | Run the deterministic server CPM engine over one scenario version and store its result (replays the existing run for the same version and engine). |
| `schedule_scenario_outputs.record` | write | same | Record a client-computed (client-asserted) analysis output such as Monte Carlo percentiles, bound to one scenario version. |
| `schedule_baselines.propose` | write | same | Propose one eligible publication as a Project baseline; a proposal is not a baseline until the operator approves it. |
| `schedule_baselines.withdraw` | write | same | Withdraw a pending baseline proposal (its proposer's channel or the operator). |
| `schedule_baselines.approve` | operator | `schedule_baseline_approval` | Approve a pending baseline proposal, or designate and approve a publication directly (attested local operator only). |
| `schedule_baselines.reject` | operator | same | Reject a pending baseline proposal (attested local operator only). |
| `schedule_baselines.revoke` | operator | same | Revoke an approved, non-governing baseline (attested local operator only). |
| `schedule_baselines.set_governing` | operator | same | Designate which approved baseline governs the Project (attested local operator only). |
| `schedule_scenarios.list` | read | `schedule_analysis_read` | List a Project's (or one Series') Schedule Scenarios, newest first. |
| `schedule_scenarios.read` | read | same | Read one Scenario and a page of its versions, newest first. |
| `schedule_scenario_versions.read` | read | same | Read one scenario version's metadata, settings, calendars, counts and digests. |
| `schedule_scenario_versions.activities` | read | same | List one scenario version's activities in key order. |
| `schedule_scenario_versions.relationships` | read | same | List one scenario version's relationships in predecessor, successor order. |
| `schedule_scenario_versions.changes` | read | same | List the change-set ops that produced one scenario version, in applied order. |
| `schedule_cpm_runs.read` | read | same | Read one server CPM run: status, summary, issues, open ends and critical paths. |
| `schedule_cpm_runs.activities` | read | same | List one CPM run's per-activity dates, floats and criticality in key order. |
| `schedule_scenario_outputs.list` | read | same | List one scenario version's client-asserted outputs, newest first. |
| `schedule_scenario_outputs.read` | read | same | Read one client-asserted output in full. |
| `schedule_series.current` | read | same | Read a Series' derived current standard update and its same-Data-Date ambiguity. |
| `schedule_series.match_decisions` | read | same | List a Project's series auto-match decisions with their candidates and scores, newest first. |
| `schedule_baselines.list` | read | same | List a Project's baselines and proposals with lifecycle status, governing flag and provenance. |
| `schedule_baselines.read` | read | same | Read one baseline or proposal with its full event history and provenance. |
| `schedule_baselines.governing` | read | same | Read the Project's governing baseline now or as of an instant. |
| `schedule_baselines.compare` | read | same | Compare an approved baseline's publication with a later publication of the same Series (the exact per-activity delta). |

| Count | Basis → S6 |
|---|---|
| `Capability` | 240 → 266 (6 client writes, 4 operator-only writes, 16 reads) |
| `Purpose` | 62 → 65 |
| audit capability literals (S6-3 revision) | 251 → 277 (266 + 11 native) |
| audit purpose literals | 62 → 65 |
| `IdKind` | 156 → 164 |
| `_OPERATOR_ONLY` | + 4 |
| `_FEATURE_BY_FAMILY` | `schedule_scenarios`, `schedule_scenario_versions`, `schedule_cpm_runs`, `schedule_scenario_outputs`, `schedule_baselines` → `schedule` (`schedule_series` already is) |
| `facade_kind` | 6 `write`, 4 `operator`, 16 `read` |

### 6.2 Switch

`Settings.schedule_scenarios_enabled: bool = False`, env `MY_PA_SCHEDULE_SCENARIOS_ENABLED`.
The plane is **effective** iff `schedule_enabled and schedule_scenarios_enabled` and the
gateway composed the plane factory (`data_engine is None`). Gate points:
`available_capabilities` subtracts the 26; each handler calls `_schedule_scenario_plane()`
first (`unsupported`); the import's `series_auto` form (section 11.2) is
`invalid_request(SERIES_AUTO)` and its baseline approval fields (section 12.3) are refused
the same way while not effective; lineage family admission (5.1); the ChatLLM prerequisite;
`apps/cli/remote_mcp.py` `_planes_from_settings`. Off → on → off changes no row. Worker
behaviour while off: section 11.2 step 6.

### 6.3 Inputs (strict; unknown key → `invalid_request`)

| Capability | Fields |
|---|---|
| `schedule_scenarios.create` | exactly one of `from_publication_id` / `from_baseline_id` / `from_version_id`; `name`; `description`; `label`; with a publication or baseline: `minutes_per_source_unit`, `calendars`, `default_calendar`, `data_date_time`; `idempotency_key` |
| `schedule_scenario_versions.create` | `scenario_id`; `expected_head_version_no` (else `conflict(EXPECTED_VERSION)`); `label`; `note`; `change_set`; `idempotency_key` |
| `schedule_cpm_runs.create` | `version_id`; `idempotency_key` (the natural key also dedups) |
| `schedule_scenario_outputs.record` | section 4.1 document; `idempotency_key` |
| `schedule_baselines.*` writes | section 12.4 |
| reads | the id; `page_size` 1..100 (default 25); `cursor` ≤ 512; `schedule_scenarios.list`: `project_id`, optional `series_id`; `schedule_cpm_runs.activities`: optional `critical_only`; `schedule_baselines.governing`: `project_id`, optional `as_of` |

Idempotency: `(principal_id, capability, idempotency_key)` in the plane request ledger;
digest `sha256(b"schedule-scenario-request-v1\n" + canonical({principal_id, capability,
request without key}))`; same key and digest replays (`replayed: true`); same key, other
digest `conflict(IDEMPOTENCY_KEY)`.

### 6.4 Outputs, cursors, disclosure, labels

Writes answer ids, numbers, digests, `created`, `replayed` and reports. Reads page stored
immutable documents in canonical order; `ScheduleCursorOrder` gains
`scenarios_created_desc_id_desc`, `versions_no_desc`, `scenario_content_offset`,
`outputs_created_desc_id_desc`, `match_decisions_created_desc_id_desc`,
`baselines_label_asc`. Disclosure: `scope`/`source_references` of the root publication(s);
`trust = MODEL_PROPOSED` with basis `("schedule_scenario", "client_authored")`, plus
`("schedule_cpm", "my-pa-cpm-v1", "server_computed")` for runs,
`("schedule_scenario_output", "client_asserted")` for outputs and
`("schedule_baseline", "operator_approved" | "proposed")` for baselines; classification
`PRIVATE_LOCAL`. Payload labels: `data_class`, `authority` ∈ `client_authored` \|
`server_computed` \| `client_asserted` \| `operator_approved` \| `proposed`,
`authoritative`, `reportable: false`. `authoritative` is `true` only on an approved
baseline (section 12); guidance must not render `MODEL_PROPOSED` as "AI-generated" (R8 R-3).
Hidden = absent.

### 6.5 Provenance of plane rows

Every row stores `authority_class`, `decision_channel`, `asserting_client_id` (remote only),
`acceptance_basis` (`user_confirmed` for the attested local operator, else
`client_identified`) and the unverified `user_directed` claim, derived as S3.1 §6.1. No
request field carries them.

### 6.6 ChatLLM `chatllm-data-v12`

The 22 client-usable names (6 writes, 16 reads) are `CHATLLM_DATA_CONDITIONAL` under new
prerequisite `SCHEDULE_SCENARIOS` (holds iff `planes.schedule and
planes.schedule_scenarios`; new field `ChatLLMCompositionPlanes.schedule_scenarios`); the 4
operator-only names are `CHATLLM_CONTROL_PLANE_EXCLUDED` (rationale "attested operator
baseline approval"). Expected, re-measured by S6-3 (a difference is reported, never forced):
policy 240 → 266; `DATA_CONDITIONAL` 137 → 159; `CONTROL_PLANE_EXCLUDED` 25 → 29; full 164
and default 98 unchanged with the switch off; full + schedule + scenarios 192; full + lineage
+ program + schedule + scenarios 226; default + all 4 switches 158; compositions 512 → 1,024.

### 6.7 Remote, façade, grants

The 6 client writes are `write` kind; they join `_IDEMPOTENT_REMOTE_CAPABILITIES`,
`_CLIENT_BOUND_KEY_CAPABILITIES` (the stamped key binds the OAuth client, so 2 clients with
identical payloads create 2 rows — `test_identical_payloads_from_two_clients_create_two_rows`,
R8-F09) and `is_remote_idempotent`. The 4 operator-only writes are `operator` kind, in
`_OPERATOR_ONLY`, withheld by `remote_tool_names` and the façade, and refused in the handler
unless `attested_lineage_authority` admits the caller (CLI or HTTP gateway), exactly like the
lineage confirms. Reads `read` kind. Every remote call re-checks its own grant. No MCP
database profile changes.

**Façade end to end** (S3.1 Part D shape): `my_pa.describe` lists exactly the eligible
client-usable names; `my_pa.write` creates a Scenario, appends a version, runs CPM, records an
output and proposes a baseline; `my_pa.read` reads each back; an operator name is absent and
`unsupported`; a name not admitted is absent and `unsupported`; lineage
`records.associations.assert` (`concerns`, version → Issue) is `client_identified`. ChatLLM:
the planner desires the 22 exactly when both planes are on and never the 4.

**Operator gates** (written into `ops/runbooks/cpm-workbench.md` by S6-3, never performed by
an agent): apply the S6-2 and S6-3 revisions; set the switches; ChatLLM `profile-apply` to
v12; grant the client-usable names; run the read-only pre-deploy checks.

---

## 7. Reporting and disclosure (OD-08)

| Rule | Enforcement point (S6-3 guard) |
|---|---|
| Plane data never enters a Program total or certified report | no `ProgramFamily` member or `METRIC_CATALOGUE` metric; AST guard: nothing under `src/my_pa/application/program_*.py`, `src/my_pa/domain/program/` or `src/my_pa/contracts/v1/programs.py` imports a plane module or table |
| The manifest lineage section never seeds or counts a schedule family | `src/my_pa/domain/intelligence/source_manifest.py` `_block_seeds`, `lineage_server_counts`, `lineage_section` admit only a pinned frozenset of the 7 pre-S6 families (S6-U04) |
| Program critical path | **UNPROVEN**; a scenario CPM is per version and non-authoritative |
| Baselines | only an **approved** baseline is `authoritative: true`; every output naming a baseline shows its provenance (proposer channel and client id for local readers, approving operator channel, dates); a proposal is labelled `proposed`, is never shown as a baseline or governing, and is refused by `compare`, `set_governing` and `from_baseline_id`; no certified output exists today (OD-08), so "authoritative" means authoritative for scenario derivation and baseline comparison only |
| Publications | stay `SOURCE_BOUND_DERIVED`; no plane path writes an S5 table except the section 11.2 second admission (an ordinary admission through `admit_publication`) and the section 12.3 import-time approval (AST guard over plane persistence) |
| Close gate | a `client_identified` schedule-family link to an Issue holds its close until confirmed (S3.1 §4.6), always confirmable (section 5.1) |

---

## 8. Security and abuse

### 8.1 Complexity and DoS

| Step | Cost |
|---|---|
| change-set application | `O(ops × log V)` + `O(V + E)` re-validation |
| sort, cycle report | `O((V + E) log V)`, `O(V + E)` |
| each pass | `O(V + E)` calls of `O(log days)` |
| path enumeration | ≤ 16 × V steps; count saturates at 1,000,000 |
| calendar tables | ≤ 32 × 36,525 entries |
| operation budget | section 3.11 |
| matcher | ≤ 50 candidates × 25,000 IDs per decision (section 11.2.1) |

Degenerate inputs: cycles (rejected, bounded report), self-loops and duplicates (refused),
dangling references (impossible), all-holiday calendars (refused), extreme lags (bounded;
section 2.6), long chains (bounded by V). Synchronous CPM conditions: section 3.11.

### 8.2 Isolation, integrity

Principal partition and principal-composite foreign keys; hidden = absent; append-only and
TRUNCATE-refusal triggers on every plane table; single `reserved → completed` request-ledger
transition; CAS on version append; digests recomputed from stored bytes on read (mismatch =
`internal_error`).

### 8.3 Rate, refusal and volume bounds (client channels; the attested operator is not limited)

| Bound | Value |
|---|---|
| plane writes per writer bucket | 120 per rolling hour, 1,000 per rolling day (the 6 client writes together; replays consume nothing) |
| plane writes per Principal (client channels) | 2,000 per rolling day |
| **refused** plane writes per writer bucket | 120 per rolling hour, counted after authentication and the switch gate (R8-F06); reaching it answers `rate_limited` before any parse of the payload |
| new stored bytes per writer bucket | 128 MiB per rolling day |
| stored and new bytes per Principal | section 2.10 (2 GiB, 256 MiB per day) |
| CPM compute per Principal | 2,500,000 activity-units per rolling hour; 1 concurrent compute |
| pending baseline proposals per Project | 50 |
| outputs per version | 100 |

### 8.4 AI boundary

A client authors logic, asserts outputs and proposes baselines; the server computes only CPM
and deterministic matching. Nothing a client writes becomes source-bound, accepted-grade,
approved or reportable.

---

## 9. Delivery plan and work split

Serial: S6-1 → S6-2 → S6-3, one worker at a time on this branch.

### 9.1 S6-1 (worker I8): pure domain and engine — no migration, no IO

Owned paths (new): `src/my_pa/domain/schedule/scenario/__init__.py`, `…/model.py`,
`…/calendar.py`, `…/canonical.py`, `…/changeset.py`, `…/snapshot.py`, `…/cpm.py`,
`…/outputs.py`; `src/my_pa/domain/schedule/series_match.py`;
`src/my_pa/domain/schedule/currency.py`; `src/my_pa/domain/schedule/baselines.py`. Tests:
`tests/unit/test_scenario_model.py`, `tests/unit/test_scenario_calendar.py`,
`tests/unit/test_scenario_changeset.py`, `tests/unit/test_scenario_snapshot.py`,
`tests/unit/test_scenario_cpm_goldens.py`, `tests/unit/test_scenario_cpm_oracle.py`,
`tests/unit/test_scenario_cpm_properties.py`, `tests/unit/test_scenario_outputs.py`,
`tests/unit/test_schedule_series_match.py`, `tests/unit/test_schedule_currency.py`,
`tests/unit/test_schedule_baselines.py`, `tests/architecture/test_scenario_engine_scope.py`;
fixtures under `tests/fixtures/schedule_scenario/`. Shard weights and partition proof.

| Public symbol (minimum) | Module |
|---|---|
| content records and enums (`ScenarioContent`, `ScenarioActivity`, `ScenarioRelationship`, `ScenarioCalendar`, `ScenarioSettings`, `ActivityConstraint`, `ActivityProgress`, `DurationDistribution`, `RelationshipType`, `ConstraintType`, `ActivityKind`, `VersionLabel`, `LagCalendar`, `ProgressPolicy`) | `scenario/model.py` |
| `working`, `working_minutes`, `advance`, `retreat`, `next_work`, `prev_end`, `shift` | `scenario/calendar.py` |
| `content_sha256`, `change_set_sha256`, `result_sha256`, `distribution_spec_sha256`, `output_payload_sha256`, `scenario_request_digest` and their documents | `scenario/canonical.py` |
| `ChangeOp`, `apply_change_set`, `ChangeSetRefusal`, `ApplicationReport` | `scenario/changeset.py` |
| `snapshot_from_publication`, `SnapshotReport` | `scenario/snapshot.py` |
| `ENGINE_VERSION`, `CPM_OPERATION_BUDGET`, `run_cpm`, `CpmResult`, `CpmIssueCode` | `scenario/cpm.py` |
| `validate_output`, `OutputKind`, `OutputRefusal` | `scenario/outputs.py` |
| `SERIES_MATCH_VERSION`, `match_series`, `MatchOutcome`, `MatchReason`, `MatchCandidate` | `series_match.py` |
| `current_standard_update`, `PublicationOrderKey` | `currency.py` |
| `BaselineAction`, `BaselineType`, `baseline_status`, `governing_baseline`, `next_baseline_label` | `baselines.py` |

None of these modules names `BASELINE`/`previous`/`current_baseline` in
`application/schedules.py` or `domain/schedule/compare.py` (the T6-25 guard stays green).
The scope guard asserts, for all S6-1 modules: stdlib + `my_pa.domain.schedule` +
`my_pa.domain.common.identifiers` only (inherited); no import of `random`, `time`, `secrets`,
`uuid` or `os`; no `now`/`today`/`utcnow` call; no `float(` call, float literal or `/`
operator (`ast.Div`).

| Prove-red (one break; the named test fails for that reason) | Test |
|---|---|
| P01 drop `snap` on the forward start | `test_golden_network_matches[G02]` |
| P02 lag calendar always predecessor | `test_golden_network_matches[G06b]` |
| P03 FF bound without `retreat` | `test_golden_network_matches[G03]` |
| P04 TF as absolute minutes | `test_golden_network_matches[G02]` |
| P05 Kahn pops insertion order | `test_topological_order_is_key_ordered` |
| P06 cycle not rotated | `test_golden_network_matches[G14]` |
| P07 path enumeration uncapped | `test_critical_path_enumeration_is_bounded` |
| P08 a float in a module | `test_scenario_package_has_no_float_clock_or_randomness` |
| P09 content digest without prefix | `test_content_sha256_vector` |
| P10 ops sorted instead of request order | `test_change_set_applies_in_request_order` |
| P11 snapshot rounds half-up | `test_golden_snapshot[S1]` |
| P12 retained logic ignored | `test_golden_network_matches[G11a]` |
| P13a FNLT violation not reported | `test_golden_network_matches[G08]` |
| P13b SNLT backward bound or violation dropped | `test_golden_network_matches[G18]` |
| P14 MSO not overriding | `test_golden_network_matches[G09]` |
| P15 `must_finish_by` ignored | `test_golden_network_matches[G10]` |
| P16 budget check off by one or removed | `test_operation_budget_is_exact` (G02 with `n` and `n − 1`) |
| P17 horizon check removed | `test_golden_network_matches[G24]` |
| P18 output distribution digest check removed | `test_output_distribution_digest_must_match` |
| P19 histogram sum check removed | `test_output_histogram_counts_sum_to_iterations` |
| P20 `activity.add` admits `sact_` | `test_added_activity_cannot_take_a_source_key` |
| P21 milestone snapped | `test_golden_network_matches[G12]` |
| P22 slack on predecessor calendar | `test_golden_network_matches[G06c]` (R8-F07) |
| P31 FNET forward bound dropped | `test_golden_network_matches[G17]` |
| P32 MFO pin dropped | `test_golden_network_matches[G19]` |
| P33 pin before data date kept | `test_golden_network_matches[G20]` |
| P34 constraint applied to started work | `test_golden_network_matches[G21]` |
| P35 S6-D08 open-end bound dropped | `test_golden_network_matches[G22]` |
| P36 progress_override still considers SS into started work | `test_golden_network_matches[G23]` |
| P37 out-of-range duration clamped | `test_golden_snapshot[S1]` |
| P38 final re-validation token missing | `test_final_revalidation_refuses_with_content_invalid` |

Rows P23–P30 and P39–P46 are in sections 11.5 and 12.7. Acceptance (S6-1): every vector and
frozen digest; oracles; properties; every prove-red row executed; FAST, ruff, ruff format,
mypy strict (default and `--platform linux`, repo and floor-pinned venvs), shard verify and
doc guards green; maximal-network timing reported.

### 9.2 S6-2: schema, migrations, persistence, unit of work, worker hook

Revision A (on `621ef6786c64`): the 8 `IdKind`s' tables
(`knowledge.schedule_scenarios`, `schedule_scenario_versions` with zlib-compressed canonical
content and change set plus digests and sizes and UNIQUE `(principal_id, scenario_id,
version_no)`, `schedule_cpm_runs` with UNIQUE `(principal_id, version_id, engine_version)`,
`schedule_scenario_outputs`, `schedule_scenario_write_requests`, `schedule_intake_series`,
`schedule_series_match_decisions`, `schedule_baselines`, `schedule_baseline_events`,
`schedule_governing_events`); column CHECKs; append-only and TRUNCATE-refusal triggers;
principal-composite FKs `RESTRICT`; the lineage widening (5.4); the role retirement and
baseline-kind restatement of section 12.2; downgrade refused once any plane row or plane
audit name exists. `ScenarioUnitOfWork` / repository with bounded decompression; the
auto-match worker hook (11.2); the import admission changes (11.2, 12.3); read-only
pre-deploy checks. Acceptance: database tier by marker (append-only, TRUNCATE, CAS race,
idempotency, cross-Principal `not_found`, digest recompute, lineage CHECKs, role
retirement and its refusal, match finalization never aborted, baseline lifecycle and
governing transitions), migration tiers, schema parity. No capability.

### 9.3 S6-3: capabilities, policy, ChatLLM, remote, lineage endpoints, guidance

Revision B: audit vocabulary 251 → 277 / 62 → 65. The 26 commands, handlers, `_BUILDERS`,
`_HANDLERS`, purposes, `_SCOPELESS`, `_requested_scope`, `_OPERATOR_ONLY`,
`_WRITE_PURPOSES`, `_IDEMPOTENT_REMOTE_CAPABILITIES`, `_CLIENT_BOUND_KEY_CAPABILITIES`,
`is_remote_idempotent`, `_FEATURE_BY_FAMILY`, ChatLLM v12, switch, cursor orders, the import
command's additive fields, `SafeDetail` members (`SCENARIO_ID`, `SCENARIO_VERSION_ID`,
`CPM_RUN_ID`, `CPM_RUN`, `OUTPUT_ID`, `EXPECTED_VERSION`, `CHANGE_SET`, 14
`change_set_<op_error>`, `CONTENT_SIZE`, `OUTPUT`, `MINUTES_PER_SOURCE_UNIT`, `CALENDAR`,
`ACTIVITY_KEY`, `LABEL`, `SERIES_AUTO`, `BASELINE_ID`, `BASELINE_TYPE`,
`APPROVAL_REFERENCE`, `EFFECTIVE_FROM`, `GOVERNING`, `REASON`, `STORAGE_QUOTA`), lineage
validators and resolvers, OD-08 guards, budgets and quotas, regenerated web fixture,
lockstep count pins, runbook and client guidance.

### 9.4 Crosswalk (requirement → section → first test)

| Requirement | Section | Test (slice) |
|---|---|---|
| new versions of schedule data | 2.2, 2.5, 2.9 | `test_golden_snapshot` (S6-1), `test_version_append_is_cas_guarded` (S6-2) |
| what-if / updating schedules | 2.8, 2.9 | `test_change_set_applies_in_request_order`, `test_golden_network_matches[G11a]` (S6-1) |
| Monte Carlo client-side | 4 | `test_output_histogram_counts_sum_to_iterations` (S6-1), `test_output_record_is_client_asserted` (S6-3) |
| server CPM | 3 | `test_golden_network_matches` (S6-1), `test_cpm_run_replays_by_natural_key` (S6-2) |
| lineage for schedule data | 5 | `test_scenario_lineage_relations_are_admitted`, `test_withheld_family_link_stays_confirmable_and_endable` (S6-3) |
| clients via catalog and façade | 6.6, 6.7 | `test_scenario_facade_end_to_end`, `test_identical_payloads_from_two_clients_create_two_rows` (S6-3) |
| OD-08 kept | 7 | `test_scenario_data_reaches_no_program_surface` (S6-3) |
| auto-matching | 11 | section 11.5 |
| authoritative baselines | 12 | section 12.7 |

---

## 10. Decisions, residuals, open operator decisions

### 10.1 Decisions (S6-D)

| ID | Decision | Why |
|---|---|---|
| S6-D01 | lineage reuses the ADR-015 ledger | one owner of semantic links |
| S6-D02 | structural facts are native virtual edges | ADR-015 decision 2 |
| S6-D03 | version 1 is the exact snapshot or copy; edits from version 2; no blank Scenario | provable baseline provenance |
| S6-D04 | a Scenario is linear; branching is a new Scenario | one CAS head |
| S6-D05 | ≤ 1 relationship per ordered pair | unambiguous slack |
| S6-D06 | integer minutes, horizon 2000–2099 | exactness |
| S6-D07 | no time zones or DST | wall-clock schedules |
| S6-D08 | open-end bound when step 2 yields none | R8 R-2 accepted; reported via `dangling_finish` |
| S6-D09 | CPM runs persisted, computed synchronously under the section 3.11 conditions | R8 R-5 |
| S6-D10 | cycles storable, reported by the run | multi-version edits |
| S6-D11 | trust `MODEL_PROPOSED` everywhere | R8 R-3 |
| S6-D12 | `issue_member` not widened | close-gate semantics |
| S6-D13 | manifest lineage section pinned to 7 families | OD-08 |
| S6-D14 | client writes stamped, client-bound keys | R8-F09 |
| S6-D15 | constraints apply only to not-started activities (default; S6-O16) | R8 R-2 |
| S6-D16..D27 | sections 11 and 12 | — |

### 10.2 Residuals (S6-U)

| ID | Residual | Owner |
|---|---|---|
| S6-U01 | Scenario name/description immutable; no archive | later slice |
| S6-U02 | a removed baseline activity cannot be restored in that Scenario | fork |
| S6-U03 | no correlation, risk events, branching, resources | later version |
| S6-U04 | reports cannot cite schedule-family lineage in a manifest | operator, later |
| S6-U05 | lineage grain is the version | later family |
| S6-U06 | synchronous CPM timing unmeasured until S6-1 | S6-1; worker plane before S6-3 if missed |
| S6-U07 | "retained logic" is this contract's definition, not a P6 equivalence claim | guidance |
| S6-U08 | full content stored per version | bounded by quotas |
| S6-U09 | a refused change set does not disclose the op index | error-contract extension |
| S6-U10..U14 | sections 11 and 12 | — |

### 10.3 Open operator (product) decisions with the default this contract proceeds on

Decided and removed from this list: Monte Carlo location (operator decision; client-side),
baseline scope (per Project), baseline approval and confirm semantics (operator approval
required; clients propose), client-designation guard rails (operator approval; section 8.3
bounds), governing-baseline mechanism (append-only operator events), the first draft's
generic designations (replaced).

| ID | Choice | Default |
|---|---|---|
| S6-O02 | source duration unit | client declares `minutes_per_source_unit`; no default |
| S6-O03 | lag calendar | `predecessor` |
| S6-O04 | out-of-sequence policy | `retained_logic` |
| S6-O05 | critical definition | `TF ≤ 0` |
| S6-O06 | open-end late finish | PF or `must_finish_by` |
| S6-O07 | longest-path definition | not offered |
| S6-O08 | per-iteration server evaluation with duration overrides | not built |
| S6-O09 | rate, refusal, byte and storage bounds | section 8.3 and 2.10 values |
| S6-O10 | ChatLLM exposure | 22 names `DATA_CONDITIONAL`, 4 `CONTROL_PLANE_EXCLUDED`; switches default off |
| S6-O11 | matcher thresholds | consider 300, match 800, margin 500, minimum 20 IDs, name-agreement veto 600 |
| S6-O12 | auto-attach on `matched` | yes, only with the name-agreement veto (operator item A; R8 ruling) |
| S6-O13 | currency excludes approved baselines and considers every other eligible publication | yes |
| S6-O15 | intake publications finalized while the plane is off | match decided and recorded as evidence; no admission (section 11.2 step 6) |
| S6-O16 | constraints on started activities | ignored and reported `constraint_ignored_started`; R8 recommends applying finish-side constraints (FNET forward, FNLT/MFO backward) to in-progress remaining work in a later engine version, because ignoring them drops contractual-deadline negative float exactly when it matters |
| S6-O17 | a Series with updates but no approved baseline | `compare` unavailable for it; reads report `no_baseline_in_series`; the governing baseline is still reported for the Project |
| S6-O18 | governing baseline in Series X while updates arrive in Series Y | the governing baseline compares only within X; reads of Y report `governing_baseline_in_other_series` and list Y's own approved baselines, which the caller may name explicitly; no cross-Series comparison |
| S6-O19 | as-of semantics | by the governing events' recorded time (what the record said on that instant); the baseline's `effective_from` is shown, not used for selection |
| S6-O20 | baseline labels | `BL-<n>` with `n` = the Project's approval ordinal from 0, never reused (a revoked or ineligible baseline keeps its label) |
| S6-O21 | first approved baseline becomes governing automatically | no; governing is always an explicit operator event |
| S6-O22 | revoking the governing baseline | refused (`conflict(GOVERNING)`) until governing moves |

---

## 11. Series auto-matching and the current standard update (operator item A, item B1)

### 11.1 Repository truth

T6-19 to T6-24 (section 1.1): the Series is final at admission; parse products are immutable
and Series-scoped; same-Series re-admission replays only on equal fields; 1 job per
publication; same-Data-Date files are all retained with no stored pointer; `schedule_series`
is append-only.

### 11.2 Auto-matching flow (S6-D16)

1. `schedule_publications.import` gains an additive form: exactly one of `series_id`,
   `series_name` or `series_auto: true` (with optional `series_name_if_new`). The auto form
   requires role `update`, refuses `supersedes_publication_id` and any baseline field
   (`invalid_request(SERIES_AUTO)`; auto-matching never creates a baseline, R8-F12). Requests
   without any S6 field keep the `cpm-schedule-import-v1` digest byte-for-byte; a request with
   any S6 field digests under `b"cpm-schedule-import-v2\n"` with the added keys present
   (null when absent). An explicit `series_id`/`series_name` always wins; the matcher is
   never consulted for it.
2. Each auto import is admitted into its **own** intake Series (R8-F11: no Stable Activity
   identity is shared between unrelated files), named `Schedule intake ` + the first 12 hex
   characters of the request digest and marked by a row in append-only
   `knowledge.schedule_intake_series (principal_id, project_id, series_id,
   publication_id)`. A caller `series_name` whose key starts with the key of `schedule intake
   ` is refused `invalid_request(SERIES_NAME)` (additive). Intake Series and their
   publications and activities are excluded from currency, baselines, scenario seeding, the
   delta (`invalid_request(TO_PUBLICATION_ID)` for an intake pair) and lineage linkability,
   and are labelled `series_kind: intake` in S5 reads (additive field).
3. When the worker finalizes an intake publication, the finalization transaction takes
   `pg_advisory_xact_lock` on `(principal_id, project_id)` (R8-F15), reads at most 50
   non-intake Series of the Project by `(created_at, series_id)` — more than 50 makes the
   outcome `ambiguous`/`candidate_bound` without scoring — computes the match (11.2.1) and
   writes 1 immutable decision (`ssmd_`, `knowledge.schedule_series_match_decisions`):
   publication, outcome, single reason, `threshold_version series-match-v1`, incoming ID
   count, every candidate considered (Series, current publication, Data Date, score,
   `data_date_coherent`, `name_agreement_permille`, `title_equal`), and the resulting or
   existing publication id.
4. The resulting admission (outcomes `matched`, `created`) runs in a **savepoint** inside that
   transaction through `admit_publication` with role `update`, the intake's expected Data
   Date, `admission_basis = auto_match` and the decision id; its idempotency key is
   `sha256("series-match-v1\n" + decision_id)` (first 64 hex). If the target Series already
   holds that source version, no admission is attempted: outcome `already_present` with the
   existing publication. Any admission refusal rolls back only the savepoint and is recorded
   as outcome `admission_refused` with the refusal token; finalization always commits
   (R8-F12). The new publication is parsed by its own job (same parse digest).
5. Outcome set (closed, R8-F14): `matched`, `created` (`no_match` + `series_name_if_new`, the
   name free under the lock), `ambiguous`, `needs_series` (`no_match` without a name),
   `already_present`, `admission_refused`, `not_eligible` (intake publication
   `review_required`/`failed`). `ambiguous` carries exactly 1 reason by precedence:
   `candidate_bound` > `insufficient_evidence` > `multiple_high` > `margin` >
   `data_date_incoherent` > `evidence_conflict` > `name_conflict`.
6. Plane off at finalization (S6-O15, R8): the worker still computes and records the decision
   (evidence only) and performs **no** admission; the decision carries
   `admission_skipped: plane_disabled`. The operator resolves by an explicit import later.
7. The intake publication is never deleted, hidden or moved; the operator resolves
   `ambiguous`/`needs_series` by an explicit import. Provenance: the second admission inherits
   the attested local-operator authority of the import that caused it (a change to ADR-016
   decision 4 recorded in ADR-017); no client can trigger it.

#### 11.2.1 Matcher `series-match-v1` (pure; S6-1)

Inputs: the incoming accepted run's set `A` of exact published Activity IDs with their
normalized names, and its Data Date; per candidate Series the ID→name map `B` of its current
standard update (11.3), else of its newest eligible publication by the order key; Series with
no eligible publication are skipped. Exact string equality only (R2 §16).

| Rule | Value |
|---|---|
| score | `floor(1000 × |A ∩ B| / |A ∪ B|)` |
| considered | score ≥ 300 |
| data-date coherent | incoming Data Date ≥ candidate Data Date |
| name agreement | `floor(1000 × |{id ∈ A ∩ B : name_A(id) = name_B(id)}| / |A ∩ B|)` (exact normalized names); **veto only**: it can demote, never select (R8-F13) |
| `matched` | `|A| ≥ 20`, exactly 1 candidate ≥ 800, coherent, name agreement ≥ 600, every other candidate < 500 |
| `ambiguous` | some candidate considered and `matched` fails |
| `no_match` | none considered |
| candidate order | score desc, Series `created_at` asc, `series_id` asc |
| title | recorded (`title_equal`), never read by the outcome |

| # | Incoming `A` | Candidates | Outcome |
|---|---|---|---|
| M1 | `S1..S100`, names `N1..N100` | X = `S1..S95 ∪ T1..T5`, same names (904, agreement 1000); Y = `S1..S10 ∪ U1..U90` (52) | `matched` X |
| M1c | `S1..S100` | X = `s1..s100` (lower case) (0) | `needs_series` (case is never folded) |
| M2 | M1 | X (904); Y = `S1..S90 ∪ V1..V10`, same names (818) | `ambiguous` `multiple_high` |
| M3 | `S1..S100` | X = `W1..W100` (0) | `needs_series`, or `created` with `series_name_if_new` |
| M4 | `A1000..A1099`, Data Date 2027-01-04 | X same IDs and names, Data Date 2027-02-01 (1000) | `ambiguous` `data_date_incoherent` |
| M5 | `S1..S12` | X = `S1..S12` (1000) | `ambiguous` `insufficient_evidence` |
| M6a | `S1..S100` | X = `S1..S90 ∪ P1..P10` (818); Y = `S1..S69 ∪ Q1..Q31` (526); names agree | `ambiguous` `margin` |
| M6b | `S1..S100` | X as M6a (818); Y = `S1..S66 ∪ Q1..Q34` (492) | `matched` X |
| M7 | `S1..S100`, title equal to Y's | X as M1 (904); Y as M1 (52) | `matched` X (title ignored) |
| M8 | `A1000..A1099` (default P6 numbering), names `GC-1..GC-100` | X = `A1000..A1099`, names `SUB-1..SUB-100`, coherent (1000, agreement 0) | `ambiguous` `evidence_conflict` |
| M9 | `S1..S100` | X `matched`-grade, but X already holds the same source version | `already_present` |

Unless a row says otherwise, every incoming set has a coherent Data Date and every
candidate's names agree with the incoming names on the shared IDs.

### 11.3 Derived current standard update (S6-D17; R8 R-7 accepted)

Per non-intake Series: `E` = publications that are effective `complete`/`partial`, are **not**
the publication of an approved, eligible, non-revoked Baseline at read time (section 12), and
have no effective `complete`/`partial` successor. `current` = max of `E` by the one order key
`(data_date, admitted_at, publication_id)` (the key the S5b-2 reads use; defined once as
`PublicationOrderKey`); null if `E` is empty. `same_data_date_ambiguity` = more than 1 member
of `E` has the maximum Data Date. A `review_required`/`failed` publication is never current;
nothing is hidden. Baseline status never depends on the order and the order never depends on
baseline status beyond membership of `E`. The S5b-2 `latest_update` of `schedule_series.list`
keeps its merged definition (declared role `update`); `schedule_series.current` is the
derived rule (S6-U11).

| # | Series | Current | Ambiguity |
|---|---|---|---|
| C1 | P1, P2 updates, `complete`, Data Date 01-31, P2 admitted later | P2 | true |
| C2 | C1 with P2 superseding P1 | P2 | false |
| C3 | P1 (01-31, complete), P2 (02-28, `review_required`) | P1 | false |
| C4 | P1 (01-31), P2 (02-28, `failed`, supersedes P1) | P1 | false |
| C5 | P1 (01-31) standard update; B1 (02-28) the publication of an approved baseline | P1 | false |
| C6 | only B1 (approved baseline) | null | false |
| C7 | C5 with B1's baseline revoked | B1 | false |
| C8 | P1 (01-31); B1 (02-28) with a pending proposal only | B1 | false |

C5/C6 (R8-F20 a) no longer key on a role: a publication is a baseline iff an approved Baseline
names it; `reference` is retired (section 12.2).

### 11.4 Work split, prove-red, crosswalk, decisions

| Slice | Owns |
|---|---|
| S6-1 | `series_match.py` (M1–M9), `currency.py` (C1–C8) |
| S6-2 | intake table and naming; v2 import digest and auto form; worker hook (lock, bound, savepoint, outcomes, plane-off rule); decisions table |
| S6-3 | import command fields; `schedule_series.current`, `schedule_series.match_decisions`; `series_kind` label |

### 11.5 Prove-red and crosswalk (section 11)

| Prove-red | Test |
|---|---|
| P23 matcher folds case | `test_series_match_vectors[M1c]` (R8-F08) |
| P24 margin rule removed | `test_series_match_vectors[M6a]` |
| P25 data-date coherence removed | `test_series_match_vectors[M4]` |
| P26 title used as a tiebreak | `test_series_match_vectors[M7]` |
| P27 failed successor displaces | `test_current_standard_update_vectors[C4]` |
| P28 ambiguity flag omitted | `test_current_standard_update_vectors[C1]` |
| P29 explicit `series_name` consults the matcher | `test_explicit_series_never_matches` (S6-2) |
| P30 name-agreement veto removed | `test_series_match_vectors[M8]` |
| P39 one shared intake Series | `test_each_auto_import_gets_its_own_intake_series` (S6-2) |
| P40 admission refusal aborts finalization | `test_match_admission_refusal_is_recorded_not_raised` (S6-2) |

| Requirement | Section | First test |
|---|---|---|
| conservative, evidence-recorded auto-matching | 11.2 | `test_series_match_vectors` (S6-1), `test_auto_import_records_a_match_decision` (S6-2) |
| explicit Series always wins | 11.2 step 1 | `test_explicit_series_never_matches` (S6-2) |
| same-Data-Date retention and current version | 11.3 | `test_current_standard_update_vectors` (S6-1), `test_series_current_read_reports_ambiguity` (S6-3) |

| ID | Decision / residual |
|---|---|
| S6-D16 | binding by a second admission after parsing, 1 intake Series per auto import |
| S6-D17 | currency derived over eligible non-baseline publications, never stored |
| S6-U10 | a matched auto import is parsed twice |
| S6-U11 | `latest_update` (S5b-2) and `schedule_series.current` differ when a declared update is an approved baseline; guidance names the derived read as current |
| S6-U12 | matching reads only a candidate's single current (or newest) publication |

---

## 12. Operator-approved Project baselines (operator addendum 2, closed decisions)

### 12.1 Model (S6-D18..D27)

| Item | Rule |
|---|---|
| status of a publication | binary: **baseline** iff an approved, eligible, non-revoked Baseline names it; every other publication is a **standard update** (the `reference` role is retired, 12.2) |
| Baseline (`sbl_`) | `baseline_id`, `principal_id`, `project_id`, `series_id` (its publication's), `publication_id` (exact, immutable; eligible and not intake), `type` ∈ `contract` (prime contract schedule) \| `approved_update` (approved rebaseline, change or time extension), `created_at`; a row is created by a proposal or by a direct operator approval |
| events (`sbev_`) | append-only `propose`, `approve`, `reject`, `withdraw`, `revoke`; each with server-derived provenance (6.5), `reason` (1..2,000) and `recorded_at`; `approve` also carries `label` (`BL-<n>`), `approval_reference` (1..500, required), `effective_from` (date, required), optional `supersedes_baseline_id` (an approved baseline of the same Project) |
| lifecycle | `proposed` → `approved` \| `rejected` \| `withdrawn` (terminal); `approved` → `revoked` (terminal); derived, never updated |
| eligibility | a Baseline is **effective** iff approved, not revoked, and its publication is effective `complete`/`partial`; an import-time approval whose publication finalizes `review_required`/`failed` reads `ineligible` and never counts |
| uniqueness | ≤ 1 pending proposal and ≤ 1 approved non-revoked Baseline per publication; ≤ 50 pending proposals per Project |
| scope | **per Project** (operator decision 1); unlimited count; a Baseline attaches to a publication in any non-intake Series of the Project |
| governing | append-only Project events (`sgov_`): `project_id`, `baseline_id` (effective), `reason`, operator provenance, `recorded_at`; governing now = the latest event's Baseline; as of `t` = the latest event with `recorded_at ≤ t` (S6-O19); the governing Baseline need not be the latest or most recent (BL-0 may stay governing) |
| superseded | a Baseline named by a later approval's `supersedes_baseline_id` is labelled `superseded` (historical); it stays readable and may still be governing if the operator says so |
| comparisons | within one Series only (Stable Activity identity is Series-scoped): `schedule_baselines.compare` pairs an effective Baseline's publication with a later eligible publication of the **same** Series (else `invalid_request(TO_PUBLICATION_ID)`), using `cpm-workbench-full-delta-v1` on demand, and labels the answer with the Baseline's label, type and provenance |
| scenarios | `from_baseline_id` requires an effective Baseline and records both the Baseline id and its exact publication; `from_publication_id` records the publication only (a pending proposal never changes this) |
| auto-matching | never creates, proposes or carries a baseline (11.2 step 1) |

### 12.2 Role retirement and the merged columns (R8-F20 a, b, d)

S6-2 revision A, additive, restates on `knowledge.schedule_publications`:
`publication_role IN ('update', 'baseline')` and `baseline_kind IS NULL OR baseline_kind IN
('contract', 'approved_update')`, by dropping and re-adding the 2 CHECKs by name (the S5b-2
restating precedent); the S5b-1 revision's frozen literals are untouched. The upgrade
**refuses** while any publication row has role `reference` or `baseline` (such rows carry the
old kinds and no Baseline object; production has applied neither S5 revision, so none exists
there; a scratch database with such rows must be rebuilt). `SchedulePublicationRole` loses
`REFERENCE`; `ScheduleBaselineKind` becomes `CONTRACT`, `APPROVED_UPDATE`; every lockstep
test and fixture moves with it. Meaning after S6-2: the column records only the **import-time
declaration**; the Baseline objects are the one source of truth (one mechanism, R8-F20 b).
The delta's "any roles" rule (S5b-2 §3.10) is unchanged; `latest_update` keeps its merged
definition (S6-U11).

### 12.3 Who designates (R8-F20 c)

| Path | Rule |
|---|---|
| operator at import | `schedule_publications.import` with role `baseline` (operator-only, attested-local, ADR-016 decision 4) now **requires** `baseline_type`, `approval_reference`, `effective_from` and a `reason`; the admission transaction writes the publication, its job, the Baseline row and 1 `approve` event attributed to the attested operator ("approved in the same act"); eligibility is decided when the parse finalizes |
| operator after the fact | `schedule_baselines.approve` with `publication_id` (direct) or `baseline_id` (a pending proposal), same approval fields; refused unless the publication is eligible now |
| client | `schedule_baselines.propose` (`publication_id`, `type`, `reason`) only; a client never imports, so a "publishing client" proposes on the publication the operator imported; a proposal is not a baseline, not governing, not authoritative |
| reject / withdraw / revoke / set governing | `reject`, `revoke`, `set_governing`: operator only; `withdraw`: the proposer's writer bucket or the operator |

### 12.4 Capability inputs

| Capability | Fields |
|---|---|
| `schedule_baselines.propose` | `publication_id`, `type`, `reason`, `idempotency_key` |
| `schedule_baselines.withdraw` | `baseline_id`, `reason`, `idempotency_key` |
| `schedule_baselines.approve` | exactly one of `baseline_id` / `publication_id` (+ `type` when direct), `approval_reference`, `effective_from`, optional `supersedes_baseline_id`, `reason`, `idempotency_key` |
| `schedule_baselines.reject` / `.revoke` | `baseline_id`, `reason`, `idempotency_key` |
| `schedule_baselines.set_governing` | `project_id`, `baseline_id` (effective), `expected_governing_baseline_id` (CAS; null for the first), `reason`, `idempotency_key` |
| `schedule_baselines.list` | `project_id`, optional `series_id`, optional `status`, page |
| `schedule_baselines.read` | `baseline_id` |
| `schedule_baselines.governing` | `project_id`, optional `as_of` |
| `schedule_baselines.compare` | `baseline_id`, `to_publication_id`, optional `change_kind`, page |

Errors: an illegal transition (`approve` of a withdrawn proposal, a second approval of one
publication, revoking a revoked Baseline) is `conflict(BASELINE_ID)`; revoking the governing
Baseline `conflict(GOVERNING)`; an ineligible or intake publication `conflict(STATUS)`.

### 12.5 Baseline vectors (S6-1 `baselines.py`, pure over event lists)

| # | Events (Project p) | Result |
|---|---|---|
| B1 | operator import-approves P0 `contract` | BL-0 approved, effective; governing null |
| B2 | B1 + `set_governing` BL-0 | governing BL-0 |
| B3 | B2 + client proposes P5 `approved_update` | P5 `proposed`; not a baseline; governing BL-0; P5 still a standard update for currency |
| B4 | B3 + operator approves the proposal (supersedes BL-0) | BL-1 approved; BL-0 `superseded`; governing still BL-0 |
| B5 | B4 + `set_governing` BL-1 at `t2` | governing BL-1; as of `t1 < t2` BL-0 |
| B6 | B5 + `revoke` BL-1 | `conflict(GOVERNING)` |
| B7 | client proposal + `reject` | `rejected`; no label consumed |
| B8 | import-approve P9 whose parse ends `failed` | `ineligible`; label BL-<n> consumed; never governing |
| B9 | 2 proposals on one publication | the second `conflict(BASELINE_ID)` |
| B10 | `compare` BL-0 with a publication of another Series | `invalid_request(TO_PUBLICATION_ID)` |

### 12.6 Decisions, residuals, open choices (continuing section 10)

| ID | Item |
|---|---|
| S6-D18 | baselines are operator-approved Baseline objects with append-only events; publications stay immutable |
| S6-D19 | scenarios name the exact publication and, when used, the exact Baseline |
| S6-D20 | authority per Project; unlimited baselines (operator decision 1) |
| S6-D21 | governing set only by operator events; any effective Baseline may govern |
| S6-D22 | clients only propose; proposals are never authoritative (operator decision 2) |
| S6-D23 | import-time baseline = operator approval in the same act; one mechanism |
| S6-D24 | `reference` retired, kinds redefined, by a restating revision that refuses old rows |
| S6-D25 | comparisons stay within one Series |
| S6-D26 | as-of by recorded time |
| S6-D27 | currency excludes effective baseline publications |
| S6-U13 | a scratch database holding S5 `baseline`/`reference` rows cannot upgrade; rebuild it |
| S6-U14 | `effective_from` is metadata; contractual effective-date selection is a later read |
| open | S6-O13, S6-O17 to S6-O22 (section 10.3) |

### 12.7 Prove-red and crosswalk

| Prove-red | Test |
|---|---|
| P41 a proposal counted as a baseline | `test_baseline_vectors[B3]` |
| P42 approval of a superseding baseline moves governing | `test_baseline_vectors[B4]` |
| P43 as-of uses effective_from instead of recorded time | `test_baseline_vectors[B5]` |
| P44 governing revocable | `test_baseline_vectors[B6]` |
| P45 ineligible baseline counted | `test_baseline_vectors[B8]` |
| P46 currency ignores baseline exclusion | `test_current_standard_update_vectors[C5]` |
| P47 role `reference` still admitted | `test_reference_role_is_retired` (S6-2) |
| P48 client reaches approve | `test_baseline_approval_is_attested_operator_only` (S6-3) |

| Requirement (operator) | Section | First test |
|---|---|---|
| authoritative baseline, BL-0 prime contract, later approved updates | 12.1, 12.5 | `test_baseline_vectors` (S6-1) |
| every other file a standard update | 12.1, 11.3 | `test_current_standard_update_vectors[C5]` (S6-1) |
| per-Project authority, governing by events | 12.1 | `test_baseline_vectors[B5]` (S6-1), `test_governing_events_are_append_only` (S6-2) |
| operator approval required; clients propose | 12.3 | `test_baseline_approval_is_attested_operator_only` (S6-3) |
| provenance on every output | 7, 12.1 | `test_baseline_outputs_show_provenance` (S6-3) |
| scenarios record the exact baseline | 12.1 | `test_scenario_records_the_exact_baseline` (S6-3) |

---

## 13. R8 findings → fixes (revision R8-1)

| Finding | Fix (section) |
|---|---|
| F01 | ADR-017 written; ADR-016 amendment reduced to a pointer; header; 1.2 |
| F02 | cycle fields in `summary`; subjects of `horizon_exceeded` and `operation_budget_exceeded` (3.2, 3.4, 3.10, 3.11) |
| F03 | properties restricted to FS-only, non-negative lags; `dangling_finish` warning (3.10, 3.13) |
| F04 | keyword-only `operation_budget`, exact counting rule, P16 rewritten (3.11, 9.1) |
| F05 | out-of-range durations null and counted; vector S1 (2.5, 3.12) |
| F06 | refusal metering, byte quotas (2.10, 8.3; S6-O09) |
| F07 | P22 → G06c (9.1) |
| F08 | M1c defined and named alone (11.2.1, 11.5) |
| F09 | client-bound keys; 2-client test (6.7) |
| F10 | withheld-family links stay confirmable and endable (5.1) |
| F11 | 1 intake Series per auto import (safer: no identity is ever shared, so no exclusion rule can be missed), plus exclusion from delta, lineage, currency, baselines and seeding (11.2 step 2) |
| F12 | `already_present`; auto form refuses `supersedes` and baseline fields; savepoint, `admission_refused` (11.2 steps 1, 4) |
| F13 | name-agreement veto (demote only), M8 (11.2.1) |
| F14 | closed outcome set, single reason by precedence (11.2 step 5) |
| F15 | Project advisory lock, 50-candidate bound, name collision under the lock (11.2 step 3) |
| F16 | result bound 64 MiB (3.11) |
| F17 | G17–G24, P13a/P13b and P31–P36 (3.12, 9.1) |
| F18 | `content_invalid`, `op_index = len(ops)` (2.9) |
| F19 | lag text corrected (2.6) |
| F20 | sections 12.2, 12.3, 11.3 (C5–C8), 11.2 step 1 |
| F21 | one count set (6.1) |
