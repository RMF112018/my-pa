# Schedule Scenarios — whole-slice contract (S6-1 engine, S6-2 persistence, S6-3 capabilities)

**Status:** proposed implementation contract for the Schedule Scenarios slice. It is the
single document the S6-1 (pure domain and
deterministic CPM engine), S6-2 (schema, migrations, persistence, unit of work, worker hook)
and S6-3 (capabilities, handlers, façade, catalog, ChatLLM, remote policy, lineage endpoints,
guidance) implementers code against. S6-1 (the pure domain and engine) is implemented and
merged (#348, section 9.1.1); S6-2 (schema, revision A `2a90f91dd786`, persistence, worker
hook; section 14) is implemented and merged (#349); S6-3 (section 15) is implemented on
`feat/schedule-scenarios-capabilities` by packages I10-A, I10-B and I10-C (section 15.19) and
not merged. No plane capability, grant or switch exists in any deployment. It authorizes
**no** production migration, grant, `profile-apply`, OAuth change or deployment, and its
switch `MY_PA_SCHEDULE_SCENARIOS_ENABLED` (added by S6-3) is **off by default** and stacks on
`MY_PA_SCHEDULE_ENABLED` (off by default). The governing
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

**Revision R8-2.** R8 re-review 1 (PASS_WITH_REQUIRED_CHANGES at `3dc96413`) findings
RR1-F01…F10 are resolved in place; section 13.1 maps each to its fix.

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
| 26 capabilities, 3 purposes, switch, ChatLLM `chatllm-data-v13` (amended by section 15, S6-3-D03), remote and façade | S6-3 | 6, 15 |
| OD-08 labelling and exclusion from Program reporting | S6-3 guards | 7 |
| Bounds, quotas, DoS analysis, isolation | all | 8 |
| Series auto-matching on import; derived current standard update | S6-1 (pure), S6-2, S6-3 | 11 |
| Operator-approved Project baselines, governing-baseline events, `reference` role retirement | S6-1 (pure), S6-2, S6-3 | 12 |

### 0.2 Status (honest)

Directive-selected design, not ratified for production. S6-1 (the pure domain and the
CPM engine, section 9.1) is implemented and merged (#348); S6-2 is implemented and merged
(#349, section 14); S6-3 is designed in section 15 and not implemented. No plane capability is
granted or served, and the plane's switch does not exist yet (S6-3 adds it, default off). The server verifies
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
| `key`, `name`, `wbs_path` | `schedule_activity_id`, `activity_name`, `hierarchy_path`; each label (and the name) through `normalize_display_text`. A null or empty `hierarchy_path` gives `wbs_path = null`, and so does a path in which any label normalizes to nothing (S5 stores an unnamed parent as `""`): a path with a hole would misstate the hierarchy, and `wbs_path` is inert, so nulling it changes no result, whereas a refusal would make the whole publication unusable for an inert field (FR8-F02). A row a scenario activity still cannot hold (for example an unnamed row) refuses the snapshot `invalid_request(ROWS)`, never an unclassified error |
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
  plus a session-level `pg_try_advisory_lock` on the Principal, taken on a **dedicated**
  connection that is never returned to the pool while it holds the lock and released by an
  unconditional `pg_advisory_unlock` in a `try/finally`, with the connection closed after; a
  second caller gets `conflict(CPM_RUN)` without computing; RR1-F10). S6-1 measures the maximal network (target ≤ 10 s on the CI host); a
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
| S1 | snapshot, `minutes_per_source_unit = 500`, 4 rows: X1 activity OD `1.500`, RD `0.001`; X2 activity OD `0.003`, RD `0.005`; X3 activity OD `999999999.000`, RD `published_blank`; X4 milestone OD `0.000`, RD `0.000` | X1 original 750, remaining 0 (0.5 → 0 half-even; half-up gives 1); X2 original 2 (1.5 → 2), remaining 2 (2.5 → 2 half-even; half-up gives 3); X3 original null (out of range), remaining null (missing); X4 0, 0 | — | `snapshot_report` = `{activities: 4, milestones: 1, durations_quantized: 3, durations_out_of_range: 1, original_missing: 0, remaining_missing: 1}` (`activities` counts every copied row, milestones included; an out-of-range cell counts only as out of range) |

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
| `originated_from` (widened) | semantic | + `scenario_version`, `schedule_baseline` | `meeting_note_version`, `capture_version` | unchanged (exact `origin` anchor) | a version's change set, or a baseline's approval, came from that note or capture; from a `schedule_baseline` it is admitted only while the Baseline is **approved** at assert time (else `invalid_request(RELATION_TYPE)`), and reads and guidance call it approval evidence only then — a `client_identified` link is shown as a client claim, never as the approval (RR1-F08) |

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
`(family token, identifier)` order (**amended by section 15.11.2**, S6-3-D21: the 6
schedule families are read without `FOR SHARE`). S3.1 provenance, budgets, idempotency, replay and the
"clients never remove accepted lineage" rule are unchanged. No link is ever created from
similarity, shared names, dates or WBS.

### 5.4 Schema and ADR process

S6-2's first revision widens, with the Python vocabulary, the `record_links` family CHECKs,
the family → identifier CHECKs, the relation-type CHECK and `a_record_link_pair_is_admitted`;
`LINEAGE_READ_GENERATION` 1 → 2. ADR-015 decision 17 is the amendment decision 6 requires.
**Amended by section 14** (S6-2-D01, S6-2-D02): revision A widens the CHECKs from a storage
vocabulary in lockstep with `tables.py`; the public enums, the read grant map and the
generation bump move to S6-3 with the validators.

---

## 6. Capabilities (S6-3)

**Amended by section 15** (re-measured at `59f333d7`, after Reports Modernization #351): the
counts of 6.1, the cursor order `baselines_label_asc` (6.4), the profile version and targets of
6.6 (`chatllm-data-v13`), the `SafeDetail` list of 9.3 and the operator's `propose` (S6-3-O01)
are restated there (S6-3-D01…D25); section 15 controls for S6-3.

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

**Amended by section 15.2** (S6-3-D01, D02): `Capability` 255 → 281, `Purpose` 65 → 68, audit
literals 266 → 292 / 65 → 68 (revision B on `4c37731671fc`), `IdKind` 174 unchanged.

### 6.2 Switch

`Settings.schedule_scenarios_enabled: bool = False`, env `MY_PA_SCHEDULE_SCENARIOS_ENABLED`.
The plane is **effective** iff `schedule_enabled and schedule_scenarios_enabled` and the
gateway composed the plane factory (`data_engine is None`). Gate points:
`available_capabilities` subtracts the 26; each handler calls `_schedule_scenario_plane()`
first (`unsupported`); the import's `series_auto` form (section 11.2) is
`invalid_request(SERIES_AUTO)` while not effective. **Behaviour change of the merged S5
import (RR1-F04):** after S6-2/S6-3, while the plane is not effective, the import admits role
`update` only — role `baseline` is refused `invalid_request(BASELINE_TYPE)`, because a baseline
now needs the section 12.3 approval fields and those exist only with the plane on — and the
retired values (`reference`, kind `working`) are refused whatever the switch
(`test_baseline_import_refused_while_plane_off`, S6-3); lineage family admission (5.1); the ChatLLM prerequisite;
`apps/cli/remote_mcp.py` `_planes_from_settings`. Off → on → off changes no row. Worker
behaviour while off: section 11.2 step 6. **Amended by section 15.9 (S6-3-D14, R10-F07):** the
plane-off answer to a role-`baseline` import is `invalid_request(PUBLICATION_ROLE)`, not
`BASELINE_TYPE`, given after the import's E-10/E-12 refusals.

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

**Amended by section 15.12.1** (S6-3-D03, D04): the version is `chatllm-data-v13` (Reports #351
took v12) and the targets below are restated in section 15.2.

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
| pending baseline proposals | 50 per Project and 10 per writer bucket per Project (RR1-F06), counted under the Project lock; the operator's direct approval is never blocked by a pending proposal (section 12.4) |
| outputs per version | 100 |

**Amended by section 15.10** (S6-3-D13, R10-F11; S6-3-D20 replaced, R10-F04): only refusals
answered after the decode step are counted (an `unsupported`, a grant or authority `denied` and
normalization refusals are not); the attested operator is exempt from the hourly CPM-units
bound, while the per-run operation budget and the 1-compute lease bind every caller.

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
| P11 snapshot rounds half-up | `test_golden_snapshot[S1]` (X1 remaining becomes 1, X2 remaining 3; RR1-F01) |
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

#### 9.1.1 S6-1 executed results (worker I8, 2026-11-03)

Measured on the branch, not claimed: the tests named below ran green and each
prove-red row recorded here went red for the stated reason. Nothing here was run
against a database, CI or production. The 12 S6-1 test modules collect 441 tests
(431 at the first handoff; FR8 corrective round 1 added 10).

| Item | Result |
|---|---|
| G02 exact operation count `n` | 70 (sort 8, forward 20, backward 20, slack 16, critical paths 6; hand-derived and pinned in `tests/unit/test_scenario_cpm_goldens.py`; budget 70 computes, 69 rejects) |
| Frozen digests | a `result_sha256` per vector G01-G24 and the G02 `content_sha256`, pinned in `tests/unit/test_scenario_cpm_goldens.py` |
| Maximal network (R8 ruling R-5) | 25,000 activities with 66-character keys, 100,000 relationships (24,999 FS plus 75,001 FF/SF), 32 calendars with 62 holidays each, 2 constraints on every not-started activity: computed in 1,077,389 operations (budget 4,000,000; section 3.11 bound 2,100,000) in about 1.1 s on the local developer host (Apple M4 Pro, CPython 3.12.13); canonical content 27,270,007 bytes, result document 30,501,253 bytes. The CI-host figure is not yet measured (S6-U06) |
| Oracles and properties | calendar functions against a minute-by-minute oracle (24 seeded calendars); ES/EF/LS/LF/TF and the critical set against path enumeration on 2,000 seeded DAGs; the section 3.13 properties on 60 seeded networks each |

Prove-red rows whose named test cannot prove the rule alone (FR8-F04, FR8 ruling c):

| Row | Proving mutation and test |
|---|---|
| P35 | as written ("open-end bound dropped") it fails `G22` only by a crash (`min()` of no bound), and the coherent variant (a skipped-only activity takes its own EF) is masked on `G22` because A ends the project there. The proof is that coherent variant (P35b) on `test_open_end_bound_applies_when_every_outgoing_bound_is_skipped` (`tests/unit/test_scenario_cpm_goldens.py`) |
| P36 | as written it fails `G23` only by a crash (no anchor for the newly considered relationship). The proof is P36c (the same change with anchors always computed) on `G23` (`[['A', 'B']]` instead of `[['A'], ['B']]`); the anchors-alone control stays green |
| P43 | the literal hazard (as-of resolved by `effective_from`) cannot be expressed in S6-1, because `governing_baseline` never receives `effective_from` (a structural guard). The substitute mutation (the as-of filter dropped) goes red on `B5`. **S6-2/S6-3 obligation:** the read that resolves `as_of` (`schedule_baselines.governing`) is tested with B5's `effective_from` values, so a read path that selects by `effective_from` goes red |

Rules the vectors alone did not pin (FR8-F01); each test went red against FR8's named mutant:

| FR8 mutant | Rule | Test |
|---|---|---|
| M02 | SS `out_of_sequence` only when the predecessor has not started (3.10) | `test_ss_out_of_sequence_needs_an_unstarted_predecessor` |
| M06 | `dangling_finish` only for incomplete activities (3.10) | `test_dangling_finish_is_only_for_incomplete_activities` |
| M08 | `must_finish_by` is a bound only when step 2 produced none (3.6, S6-D08) | `test_must_finish_by_bounds_only_activities_without_a_successor_bound` |
| M19 | the cycle walk steps to the smallest-key predecessor (3.4) | `test_cycle_walk_steps_to_the_smallest_key_predecessor` |
| M21 | emission stops before the 50,000-key total (3.8) | `test_critical_path_emission_stops_before_the_key_cap` |
| M22 | `critical_path_count` saturates at 1,000,000 across start nodes (3.8) | `test_critical_path_count_saturates_across_start_nodes` |
| M15 | a second candidate at exactly 500 fails `matched` (11.2.1) | `test_a_second_candidate_at_exactly_the_margin_is_ambiguous` |
| M17 | `progress.set` with a finish after the working data date is refused at that op (2.9) | `test_progress_finish_after_the_data_date_is_refused_at_its_op` |

Change outside the section 9.1 owned paths (FR8-F05, accepted by FR8 ruling a):
`tests/architecture/test_user_owned_tables_are_partitioned.py` scans for string literals
beginning with a migration-target schema name (`calendar.` among them). The 4 section 2.9 op
names `calendar.put`, `calendar.remove`, `calendar.exception.put` and
`calendar.exception.remove` are exempt there only as exact whole literals, and only in
`src/my_pa/domain/schedule/scenario/changeset.py`. `test_the_non_schema_literal_exemption_is_exact`
pins this. The target revision's 11 `calendar.*` tables are all named `calendar_*`, so the
exempt literals cannot name one.

Obligations carried to S6-2 (FR8-F07): `run_cpm` computes the `ScenarioContent` it is given.
That record admits duplicate activity keys, which only `content_problem` refuses, so S6-2 runs
the engine only on stored content that passed `content_problem` (decoded from bytes whose
digest is rechecked). A change set that is not JSON-encodable is refused
`(0, invalid_field)`; a JSON transport cannot produce one.

Resolutions this contract left open, taken by I8 (each pinned by a test):

| Point | Resolution |
|---|---|
| vector keys `A`, `B`, ... | written `x:A`, `x:B`, ... (a key is `sact_` or `x:<token>`, section 2.4; key order unchanged) |
| `remaining_start` of a complete activity | null |
| a rejected run's summary | `activity_count` and `relationship_count` from the content; every other count 0, `critical_paths_truncated` false |
| a self-loop reaching the engine | a 1-element cycle (`cycle_detected`), never `dangling_relationship` |
| `ambiguous` with a considered candidate but none at 800 | reason `insufficient_evidence` |
| `series_name_if_new` taken under the lock | `ambiguous` `name_conflict` (the reason the closed set already holds) |
| change set outside 1..5,000 ops or 4,194,304 bytes | `ChangeSetRefusal(0, bound_exceeded)` before any op |
| `constraint.clear`, `distribution.clear`, `progress.clear`, `calendar.exception.remove` of something absent | an empty effective change (the grammar has no `*_absent` token for them) |
| `constraint.set` | replaces the constraint in its slot (early, late or mandatory); mixing a mandatory with any other is `constraint_conflict` |
| symbol names | `SnapshotRefusalError` (ruff N818), `ChangeSetApplied`, `ChangeOp` as the op-name enum, `OutputRefusal` with `OutputRefusalReason`, `SeriesCandidate` (input) beside `MatchCandidate` (recorded), `decide_baseline_write` and `compare_refusal` for the section 12 transition and comparison rules |

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

**Implementation note.** Section 14 is the exact S6-2 design (repository reauthentication at
`a66a6e32`, schema, triggers, revision A, persistence, worker hook, pre-deploy checks, work
split, tests) and controls this paragraph where they differ; its amendments S6-2-D01 (lineage
widening from a storage vocabulary), S6-2-D02 (the generation bump moves to S6-3), S6-2-D03
(an 11th table, the refusal ledger) and S6-2-D09 (revision A's downgrade checks plane rows,
not audit names) are stated there with their reasons.

### 9.3 S6-3: capabilities, policy, ChatLLM, remote, lineage endpoints, guidance

**Amended by section 15** (the S6-3 implementation note): revision B restates 266 → 292 / 65 →
68; the `SafeDetail` list is section 15.7.1 (S6-3-D07); the work split is section 15.15.

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
| S6-U06 | synchronous CPM timing: measured by S6-1 on the local developer host only (section 9.1.1: about 1.1 s for the maximal network); the CI-host figure comes from the first CI run of the FAST test that asserts the 10 s target | S6-1 (local, done); CI host on the first PR run; worker plane before S6-3 if missed |
| S6-U07 | "retained logic" is this contract's definition, not a P6 equivalence claim | guidance |
| S6-U08 | full content stored per version | bounded by quotas |
| S6-U09 | a refused change set does not disclose the op index | error-contract extension |
| S6-U16 | a compiled calendar covers the whole 2000-2099 axis, not only the span reached (section 3.2): about 0.31 MB each after FR8-F06 (measured: 32 calendars retain 10,042,704 bytes; it was 57 MB before the tables were compacted), memoized by value in a process cache bounded at 40 (about 12.6 MB) | S6-3 sizing on the server host; a span-limited table in a later engine version if needed |
| S6-U10..U15 | sections 11 and 12 | — |

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
| S6-O19 | as-of semantics | by the recorded order of the per-Project event chains (section 12.1: `seq`, with `recorded_at` from `clock_timestamp()` after the Project lock and non-decreasing); reads are labelled **"as recorded"**; the baseline's `effective_from` is shown, never used for selection (RR1-F02) |
| S6-O20 | baseline labels | `BL-<n>` with `n` = the Project's approval ordinal from 0, assigned under the Project lock, UNIQUE `(principal_id, project_id, label)`, never reused (a revoked or ineligible baseline keeps its label) (RR1-F03) |
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
| Baseline (`sbl_`) | `baseline_id`, `principal_id`, `project_id`, `series_id` (its publication's), `publication_id` (exact, immutable; eligible and not intake), `type` ∈ `contract` (prime contract schedule) \| `approved_update` (approved rebaseline, change or time extension) — the **proposed** type, shown as such; the Baseline's **effective** type is the `type` of its `approve` event, which may differ after a direct approval adopts a proposal (RR2-F01) — `created_at`; a row is created by a proposal or by a direct operator approval |
| events (`sbev_`) | append-only `propose`, `approve`, `reject`, `withdraw`, `revoke`; each with `baseline_id`, `publication_id`, server-derived provenance (6.5), `reason` (1..2,000), and the Project chain fields: `seq` (1, 2, … per Project), `previous_event_id` (null iff `seq = 1`), `recorded_at`; `approve` also carries `type` (the effective type), `label` (`BL-<n>`), `approval_reference` (1..500, required), `effective_from` (date, required), optional `supersedes_baseline_id` (an approved baseline of the same Project); `propose` carries `proposal_ordinal` (section 12.1 "enforcement") |
| lifecycle | `proposed` → `approved` \| `rejected` \| `withdrawn` (terminal); `approved` → `revoked` (terminal); derived, never updated |
| eligibility | a Baseline is **effective** iff approved, not revoked, and its publication is effective `complete`/`partial`; an import-time approval whose publication finalizes `review_required`/`failed` reads `ineligible` and never counts |
| uniqueness | ≤ 1 pending proposal per publication; a publication is approved **at most once ever** (a revoked Baseline's publication is not re-approvable; S6-D28); ≤ 50 pending proposals per Project and ≤ 10 per writer bucket per Project |
| enforcement (RR1-F03) | every baseline and governing write — including the import-time approval written inside the S5 admission transaction (it consumes a `seq` and a label; RR2-F04) — first takes `pg_advisory_xact_lock` on `(principal_id, project_id)` and validates under it. These writes run at READ COMMITTED (the repository default) and read the chain head, counts and pending state in statements issued **after** the lock, so each read sees every write committed before the lock was granted (RR2-F03). Database backstops on `schedule_baseline_events`: UNIQUE `(principal_id, project_id, seq)`; partial UNIQUE `(principal_id, baseline_id) WHERE action IN ('approve', 'reject', 'withdraw')` (one decision per proposal); partial UNIQUE `(principal_id, baseline_id) WHERE action = 'revoke'`; partial UNIQUE `(principal_id, publication_id) WHERE action = 'approve'` (one approval per publication); partial UNIQUE `(principal_id, project_id, label) WHERE action = 'approve'` (labels never reused); partial UNIQUE `(principal_id, publication_id, proposal_ordinal) WHERE action = 'propose'`, where `proposal_ordinal` = the number of earlier proposals of that publication that already have a decision, computed under the lock — a second pending proposal computes the same ordinal and collides. The pending caps are lock-enforced (counted under the lock), not constraint-enforced. Each invariant has a database-tier race test (section 12.7) |
| scope | **per Project** (operator decision 1); unlimited count; a Baseline attaches to a publication in any non-intake Series of the Project |
| governing | append-only Project chain (`sgov_`): `project_id`, `baseline_id` (effective), `reason`, operator provenance, `seq` (1, 2, …), `previous_governing_event_id` (null iff `seq = 1`; equal to the event named by the CAS `expected_governing_baseline_id`), `recorded_at`; UNIQUE `(principal_id, project_id, seq)` and a principal-composite FK to the predecessor. **Order (RR1-F02):** under the Project lock the writer reads the head, takes `recorded_at = clock_timestamp()` **after** acquiring the lock, and a CHECK-by-trigger refuses a `recorded_at` earlier than the predecessor's, so recorded time is non-decreasing along the chain. Governing now = the event with the maximum `seq`; as of `t` = the event with the maximum `seq` among those with `recorded_at ≤ t` (equal timestamps resolve by `seq`); reads say "as recorded". The baseline event chain follows the same rules. The governing Baseline need not be the latest or most recent (BL-0 may stay governing) |
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
definition (S6-U11). **Merged-S5 behaviour change (RR1-F04):** from S6-2 on, `reference` and
kind `working` are refused at import whatever the switches; from S6-3 on, a role-`baseline`
import needs the section 12.3 fields and is therefore refused `invalid_request(BASELINE_TYPE)`
while the plane is not effective, so with only `MY_PA_SCHEDULE_ENABLED` on the import admits
role `update` only (**amended by section 15.9**, S6-3-D14, R10-F07: the answer is
`invalid_request(PUBLICATION_ROLE)`; P56 and `test_baseline_import_refused_while_plane_off`
follow it). ADR-017 "Consequences" states it; `test_baseline_import_refused_while_plane_off`
(S6-3) and `test_reference_role_is_retired` (S6-2) pin it. **Amendment (section 14,
S6-2-D04; R9-F05):** in the interval from S6-2 to S6-3 every role-`baseline` import is refused
`invalid_request(PUBLICATION_ROLE)` whatever the switches (the approval fields do not exist
yet), and `schedule_publications.list` refuses the filter `publication_role=reference` with
`invalid_request(PUBLICATION_ROLE)` (an S5 read-behaviour change of the enum lockstep).

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
| `schedule_baselines.approve` | exactly one of `baseline_id` / `publication_id` (+ `type` when direct), `approval_reference`, `effective_from`, optional `supersedes_baseline_id`, `reason`, `idempotency_key` A direct approval by `publication_id` of a publication that has a pending proposal **adopts that proposal**: it writes the `approve` event on the proposal's `baseline_id` (the operator's `type` and fields win and are recorded), creates no second Baseline row and is never blocked by the proposal (RR1-F05/F06) |
| `schedule_baselines.reject` / `.revoke` | `baseline_id`, `reason`, `idempotency_key` |
| `schedule_baselines.set_governing` | `project_id`, `baseline_id` (effective), `expected_governing_baseline_id` (CAS; null for the first), `reason`, `idempotency_key` |
| `schedule_baselines.list` | `project_id`, optional `series_id`, optional `status`, page |
| `schedule_baselines.read` | `baseline_id` |
| `schedule_baselines.governing` | `project_id`, optional `as_of` |
| `schedule_baselines.compare` | `baseline_id`, `to_publication_id`, optional `change_kind`, page |

Errors: an illegal transition (`approve` of a withdrawn proposal, a second approval of one
publication, revoking a revoked Baseline, a lost race on any section 12.1 backstop) is
`conflict(BASELINE_ID)`; a pending cap reached is `rate_limited(BASELINE_ID)`; on a governing write, a lost `seq` race or an `expected_governing_baseline_id` mismatch is `conflict(GOVERNING)` (RR2-F04); revoking the governing
Baseline `conflict(GOVERNING)`; an ineligible or intake publication `conflict(STATUS)`.

### 12.5 Baseline vectors (S6-1 `baselines.py`, pure over event lists)

| # | Events (Project p) | Result |
|---|---|---|
| B1 | operator import-approves P0 `contract` | BL-0 approved, effective; governing null |
| B2 | B1 + `set_governing` BL-0 | governing BL-0 |
| B3 | B2 + client proposes P5 `approved_update` | P5 `proposed`; not a baseline; governing BL-0; P5 still a standard update for currency |
| B4 | B3 + operator approves the proposal (supersedes BL-0) | BL-1 approved; BL-0 `superseded`; governing still BL-0 |
| B5 | B4 with BL-0 `effective_from` 2027-01-01 and BL-1 `effective_from` 2026-12-01; governing chain: `seq 1` BL-0 recorded 2027-02-01T10:00, `seq 2` BL-1 recorded 2027-03-01T10:00 | governing now BL-1; as recorded at 2027-01-15 null, at 2027-02-15 BL-0, at 2027-03-15 BL-1 (an `effective_from` rule would answer BL-0 on 2027-01-15 and 2027-03-15; RR1-F07) |
| B6 | B5 + `revoke` BL-1 | `conflict(GOVERNING)` |
| B7 | client proposal + `reject` | `rejected`; no label consumed |
| B8 | import-approve P9 whose parse ends `failed` | `ineligible`; label BL-<n> consumed; never governing |
| B9 | 2 proposals on one publication | the second `conflict(BASELINE_ID)` |
| B10 | `compare` BL-0 with a publication of another Series | `invalid_request(TO_PUBLICATION_ID)` |
| B11 | client proposes P7 (`approved_update`, its bucket's 1st pending); operator `approve` with `publication_id` P7, `type contract` | the proposal's Baseline is approved as BL-<next> with type `contract`; no second Baseline row; the proposal is no longer pending; a later client `withdraw` of it is `conflict(BASELINE_ID)` (RR1-F05) |

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
| S6-D28 | a publication is approved at most once ever; revocation is final for it |
| S6-D29 | baseline and governing events are per-Project `seq` chains written under the Project lock with `clock_timestamp()` after the lock; reads are "as recorded" |
| S6-U13 | a scratch database holding S5 `baseline`/`reference` rows cannot upgrade; rebuild it |
| S6-U14 | `effective_from` is metadata; contractual effective-date selection is a later read |
| S6-U15 | revoking a Baseline is final for its publication (S6-D28); recovery means approving a different publication. The `schedule_baselines.revoke` docstring (hence its catalog summary or description) and the runbook section S6-3 writes must state this warning (RR2-F02) |
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
| P49 `recorded_at` from transaction start (`now()`) or no predecessor check | `test_governing_chain_is_monotonic_under_contention` (S6-2) |
| P50 Project lock removed from baseline writes | `test_concurrent_approve_and_withdraw_write_one_decision` (S6-2) |
| P51 one-approval-per-publication index dropped | `test_concurrent_approvals_of_one_publication` (S6-2) |
| P52 label index dropped | `test_concurrent_approvals_never_reuse_a_label` (S6-2) |
| P53 `proposal_ordinal` index dropped | `test_concurrent_proposals_on_one_publication` (S6-2) |
| P54 pending caps unchecked | `test_pending_caps_hold_under_concurrency` (S6-2) |
| P55 direct approval creates a second Baseline | `test_baseline_vectors[B11]` |
| P56 role `baseline` admitted with the plane off | `test_baseline_import_refused_while_plane_off` (S6-3) |

**Amended by section 14.11 (R9-F03).** P50 and P54 go red by the class of the loser's answer
(a decide-time `conflict(BASELINE_ID)` / `rate_limited(BASELINE_ID)`, never a lost race on the
`seq` UNIQUE). P51–P53's race tests are layered behind the per-Project `seq` UNIQUE and are
expected green when only their partial unique is dropped; each partial unique is proved alone
by `test_baseline_backstop_index_refuses_alone[<index>]`. Every race test synchronizes by
barriers and seams, never sleeps.

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

### 13.1 R8 re-review 1 findings → fixes (revision R8-2)

| Finding | Fix (section) |
|---|---|
| RR1-F01 | S1 rebuilt with `minutes_per_source_unit = 500` and 2 tie cases (0.5 → 0, 2.5 → 2) where half-up differs, every cell and the full `snapshot_report` stated; P11 names what goes red (3.12, 9.1) |
| RR1-F02 | baseline and governing events are per-Project `seq` chains with UNIQUE `(principal_id, project_id, seq)`, `previous_…_id`, `recorded_at = clock_timestamp()` after the Project lock, a non-decreasing trigger CHECK, `seq` as tie rule, reads labelled "as recorded" (12.1; S6-O19; P49) |
| RR1-F03 | Project advisory lock on every baseline and governing write; partial UNIQUE backstops for 1 decision and 1 revoke per Baseline, 1 approval per publication, labels, and pending proposals per publication (`proposal_ordinal`); lock-enforced caps; a race test per invariant (12.1, 12.7; S6-O20; P50–P54) |
| RR1-F04 | the merged-S5 import change disclosed in 6.2, 12.2 and ADR-017 Consequences, with `test_baseline_import_refused_while_plane_off` (P56) |
| RR1-F05 | a direct approval adopts a pending proposal; vector B11 (12.4, 12.5; P55) |
| RR1-F06 | 10 pending per writer bucket per Project; the operator's direct approval never blocked (8.3, 12.1, 12.4) |
| RR1-F07 | B5 gives `effective_from` values that disagree with recording order and states the as-of answers (12.5) |
| RR1-F08 | `originated_from` from a Baseline admitted only while it is approved; never presented as approval evidence otherwise (5.2) |
| RR1-F09 | ADR-017 wording: "baselines are never derived (now operator-approved objects)" |
| RR1-F10 | dedicated connection and unconditional `try/finally` unlock for the CPM advisory lock (3.11) |

### 13.2 R8 re-review 2 findings → fixes (non-blocking; PASS at `c8a899ab`)

| Finding | Fix (section) |
|---|---|
| RR2-F01 | the effective Baseline type is the `approve` event's `type`; the row's `type` is the proposed type (12.1) |
| RR2-F02 | residual S6-U15 (revocation is final for its publication) with the docstring and runbook warning required of S6-3 (12.6) |
| RR2-F03 | READ COMMITTED and head reads in statements after the lock (12.1) |
| RR2-F04 | the import-time approval takes the Project lock inside the admission transaction; a lost governing `seq` race is `conflict(GOVERNING)` (12.1, 12.4) |

---

## 14. S6-2 implementation note (design D9; implemented on this branch by I9-A and I9-B, not merged)

**Status.** Implemented on `feat/schedule-scenarios-persistence` by I9-A (schema) and I9-B
(persistence), not merged, migrated, granted or deployed anywhere; section 14.14 records what
was executed. The design text below is unchanged. Written by D9 on `feat/schedule-scenarios-persistence` at base
`a66a6e32668f4707d49563f8eda7d9cfefecf333`, tree `108dd79054e361bcde580df57a41d153e1181536`
(= `origin/main` with S6-1 #348 merged); as written, nothing in it was implemented, migrated,
granted or deployed. Once design review R9 passes it, this section and the sections it cites
are the single specification the S6-2 implementers (I9-A, I9-B) code against: a point that
is wrong or incomplete against the code is a stop with a proposed amendment, never a silent
redesign; trivial naming resolutions are allowed and listed in the handoff. Where this
section and an earlier section of this contract disagree, the earlier text is amended here
explicitly (each marked **amendment**, with its reason, section 14.12) and this section
controls for S6-2. Operator decisions (sections 10.3, 12) and S6-1 engine semantics are not
reopened.

**Revision R9-1.** Design review R9 (PASS_WITH_REQUIRED_CHANGES at `a444e21b`) findings
R9-F01…F13 are resolved in place; section 14.13 maps each finding to its fix. **Revision R9-2:** re-review RR1
(PASS_WITH_REQUIRED_CHANGES at `b612db98`) findings RR1-F01…F05 are resolved in place; the
end of section 14.13 maps them.

### 14.1 Repository reauthentication at `a66a6e32`

| # | Claim (this contract or the brief) | Repository truth at `a66a6e32` | Decision |
|---|---|---|---|
| R2-01 | Sole Alembic head `621ef6786c64`; 125 revision files | `migrations/versions/20261028_621ef6786c64_cpm_workbench_vocabulary.py` is the sole head; 125 revision files (+ `README.md`); `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py::test_the_chain_is_readable_and_non_empty` pins 125; 53 test modules name `621ef6786c64` (`git grep -l 621ef6786c64 -- tests`) | 1 new revision (revision A, `down_revision = "621ef6786c64"`), 126 files; head literal and count move in lockstep (I9-A) |
| R2-02 | 156 `IdKind`; the 8 prefixes are free | 156 members, last `SCHEDULE_IMPORT_ISSUE = "siss"`; measured: none of `sscn sscv scpm ssco ssmd sbl sbev sgov` equals a member, is a `str.startswith` prefix of one or is prefixed by one, and no two of the 8 prefix each other (nearest: `sact sevd siss sit smem sobs span sprun spub src srow sser stage sub`). `git grep` of `<prefix>_` finds only S6-1 docstrings/literals: `src/my_pa/domain/schedule/scenario/outputs.py` (`_VERSION_ID` = `\Asscv_…\Z`, `_RUN_ID` = `\Ascpm_…\Z`), `src/my_pa/domain/schedule/baselines.py` (docstrings), and synthetic test identifiers | adopt the 8 unchanged, appended in section 2.1 order; the 2 S6-1 regexes stay (S6-1 is not reopened) and a FAST test pins them equal to the `IdKind` prefixes |
| R2-03 | `tables.py` layout and guards | `src/my_pa/infrastructure/persistence/tables.py` (19,010 lines) derives closed sets from live enums (`_one_of`, `_literals`, `_is_identifier`, `_IDENTIFIER_SUFFIX` = `[A-Za-z0-9]{8,64}`); the S5 tables sit at its end; `tests/architecture/test_capture_project_binding.py` pins `TABLES_SHA256`; per-revision parity is `tests/schema/test_cpm_workbench_migration.py::test_runtime_metadata_matches_the_revision` (a scratch schema built from `tables.py` compared to the migrated catalog) | 11 new tables appended after the S5 tables; `TABLES_SHA256` re-pinned; a revision-A parity test of the same shape |
| R2-04 | Principal-partition guard registry | `tests/architecture/test_principal_partition_is_reached_through_the_guard.py`: exact sets `REACHED_THROUGH_THE_GUARD` (holds `infrastructure/persistence/schedule.py`), `PER_MODULE_ONLY` (with a reason per module), `STATEMENT_LEVEL`, `HAND_WRITTEN_COMPARISONS`, `UNPARTITIONED_JOB_STATEMENTS`; raw `text()` must carry the partition | the 2 new SQL modules (14.8) join `REACHED_THROUGH_THE_GUARD` and `PER_MODULE_ONLY` (the `schedule.py` shape: module-local `_mine`/`_bound`, no `text()`); advisory locks are written with `func.pg_advisory_xact_lock`/`func.hashtext`, never `text()` |
| R2-05 | S5b-1/S5b-2 schedule tables and triggers | 7 tables (`schedule_series`, `schedule_publications`, `schedule_activities`, `schedule_jobs`, `schedule_parser_runs`, `schedule_rows`, `schedule_import_issues`), functions F1–F9 under CPM-owned names (S5b-1 §4.10); `schedule_publications` U3 `a_schedule_publication_is_identified_within_its_series (publication_id, principal_id, project_id, series_id)`; `schedule_series` `a_schedule_series_is_identified_within_its_project (series_id, principal_id, project_id)`; CHECKs `a_schedule_publication_role_is_known` = `publication_role IN ('baseline', 'reference', 'update')` and `a_schedule_baseline_kind_is_known` = `baseline_kind IS NULL OR baseline_kind IN ('contract', 'working')`, frozen in `6c2306330ceb` inside `CREATE TABLE` | revision A references U3 and the Series composite; restates the 2 CHECKs by name; adds 1 trigger on `schedule_publications` (G10); edits no merged revision |
| R2-06 | Restating precedent | `621ef6786c64` `_restate(table, name, expression)` = `op.drop_constraint` then `op.create_check_constraint`, with byte-copied BEFORE texts and a `DO` refusal before any downgrade restore; `SET LOCAL lock_timeout = '10s'` first in both directions | the same order; the restatements of one table are batched into one multi-clause `ALTER TABLE` (one validating pass, R9-F10) |
| R2-07 | Downgrade refusal convention | `DO $$ … RAISE EXCEPTION '…' USING ERRCODE = 'restrict_violation'` before any drop; reverse-order drops, `RESTRICT` | the same; refusal set in 14.6 |
| R2-08 | `record_links` CHECKs and the lineage vocabulary | `src/my_pa/domain/lineage/vocabulary.py`: `RecordFamily` 7, `RelationType` 8, `RELATION_MATRIX`, `RECORD_FAMILY_ID_KINDS`, `LINEAGE_FAMILY_READS`, `LINEAGE_READ_GENERATION: Final = 1` (consumed by `src/my_pa/domain/lineage/cursor.py` `scope_digest`). Only `record_links` carries `RecordFamily` CHECKs: `a_record_link_from_family_is_known`, `a_record_link_to_family_is_known`, `from_id_is_an_opaque_identifier`, `to_id_is_an_opaque_identifier` (all frozen by `264310e0416a` inside `CREATE TABLE`, never restated), `a_record_link_relation_type_is_known` and `a_record_link_pair_is_admitted` (last restated by `6f1476b8da52`, its `_WIDENED_CHECKS` AT texts). `tables.py` builds them with `_one_of(…, RecordFamily)`, `_family_identifier` and `_relation_matrix` over the live enums | widened by revision A (14.6) from a **storage vocabulary**, not from the public enums (amendment S6-2-D01) |
| R2-09 | Widening the public lineage enums is harmless before S6-3 | it is not: `RecordFamily` feeds the `records.associations.assert` input schema enum (`src/my_pa/application/commands.py`, `"enum": [member.value for member in RecordFamily]`), `parse_record_ref` admits any member (`src/my_pa/application/lineage_endpoints.py`), `lineage_visibility.py` iterates every member against `LINEAGE_FAMILY_READS`, and `record_lineage.py` `_NATIVE` maps only the 7 families (a new member would reach a `KeyError`). `RelationType` likewise feeds `CONTESTABLE_RELATIONS` and the assert schema | the public enums, `RELATION_MATRIX`, `RECORD_FAMILY_ID_KINDS`, `LINEAGE_FAMILY_READS` and the generation move in S6-3 with the validators (S6-2-D01, S6-2-D02) |
| R2-10 | `record_links` is live in production | production runs the database at `023f8f7eb499` (S3.1), which includes S1's `record_links`; the S5 tables do not exist there | every `record_links` touch is a production live-table lock (14.6.3); the S5 tables are live only if the S5 revisions were applied and used before revision A |
| R2-11 | S5b-2 import admission | `SqlScheduleRepository.admit_publication(principal_id, request, request_digest)` in `src/my_pa/infrastructure/persistence/schedule.py`: (1) replay by key, (2–3) bindings, (4) Series by id or `name_key`, (5) replay by source version, (6) predecessor `FOR UPDATE`, (7) series `ON CONFLICT DO NOTHING`, publication `ON CONFLICT DO NOTHING`, `enqueue_job`; rejections raise `ScheduleAdmissionRejectedError`; digest `schedule_import_request_digest` (`b"cpm-schedule-import-v1\n"`, `src/my_pa/domain/schedule/canonical.py`); `ScheduleImportRequest` (`src/my_pa/domain/schedule/model.py`) requires exactly one of `series_id`/`series_name`; `_REFUSALS` in `src/my_pa/application/schedules.py` maps every `ScheduleAdmissionRefusal` | S6-2 extends the record, the digest and this method (14.7, 14.8.6); no `ScheduleAdmissionRefusal` member is added (the FAST guard `tests/architecture/test_cpm_workbench_worker_scope.py::test_no_baseline_is_derived` forbids a `BASELINE` symbol in `application/schedules.py`) |
| R2-12 | Worker finalization | `src/my_pa/infrastructure/jobs/schedule.py`: `process_schedule_publication(engine, job, owner)` (registered in `apps/worker.py` `"schedule": (SCHEDULE_JOBS, process_schedule_publication)`); phases H1–H8, each phase one `SqlAlchemyScheduleUnitOfWork` transaction through `_Job.transaction`; H8 = `finalize_publication`; every deterministic failure = `_Job.fail` → `fail_publication`, one transaction | the hook runs inside the H8 and `fail` transactions (14.8.7) |
| R2-13 | Dedicated UoW precedent | `ScheduleUnitOfWork` / `SqlAlchemyScheduleUnitOfWork(engine)` (`engine.begin()`, refuses re-entry, repository on that connection, never commits inside it), not on `UnitOfWork` | `ScenarioUnitOfWork` of the same shape, exposing both repositories on one connection |
| R2-14 | Advisory-lock precedent | single-bigint keys (`hashtextextended`, `sha256`-derived, literal `7420196`, `87421002`) everywhere except lineage, which uses the two-int form `pg_advisory_xact_lock(CAST(:namespace AS integer), hashtext(…))` with `LINEAGE_ADVISORY_NAMESPACE = 0x4C494E45` ("LINE"); the two-int and one-bigint forms are separate key spaces in PostgreSQL. No session-level advisory lock is held by request-path code (only `record_event_roles.py`, operator tooling) | 2 plane namespaces in the two-int space (14.8.4) |
| R2-15 | App-role grant pattern | S1–S3.1 and both S5 revisions execute no `GRANT`/`REVOKE`; tables are owned by the migrating role; tests assert `relacl IS NULL` and `has_table_privilege` false for `PUBLIC`, `my_pa_mcp_ro`, `my_pa_mcp_rw` | revision A is grant-free (14.6.5) |
| R2-16 | Migration test tiers | `tests/db/fixtures.py`: a `*_migration.py` module's database tests default to `migration_edge`; `migration_empty_to_head` is explicit; other `database` tests default to `database_clone`; no-marker tests are FAST; database tests build schemas through `upgrade_head`, never `METADATA.create_all` | section 14.11 assigns tiers |
| R2-17 | Audit vocabulary names exist for a revision-A downgrade check ("plane audit name", section 9.2) | no plane capability or purpose exists until S6-3; `capability_is_known`/`purpose_is_known` were last restated by `621ef6786c64` | revision A's downgrade checks plane rows (and S6 lineage rows) only; revision B (S6-3) refuses its own downgrade on plane audit names (amendment S6-2-D09) |
| R2-18 | Pre-deploy check precedent | `src/my_pa/infrastructure/database/cpm_workbench_predeploy.py` (P0–P8, one read-only transaction, always rolled back), `ops/postgres/cpm_workbench_predeploy_check.py`, `tests/database/test_cpm_workbench_predeploy.py`, runbook `ops/runbooks/cpm-workbench.md` | the same shape for Q0–Q9 (14.9) |
| R2-19 | The S5 command layer validates role and kind through the enums | `ImportSchedulePublication.import_request` uses `_schedule_choice(…, tuple(SchedulePublicationRole), SafeDetail.PUBLICATION_ROLE)` and `tuple(ScheduleBaselineKind)` / `SafeDetail.BASELINE_KIND`; `ListSchedulePublications` filters by role the same way | the enum lockstep alone refuses `reference` and `working` at the boundary; one owned command edit refuses role `baseline` until S6-3 (S6-2-D04) |
| R2-20 | Remote idempotency keys | the remote boundary stamps a 64-hex SHA-256 key (`src/my_pa/adapters/remote_request.py`) | the plane ledger key reuses the S5 pattern `^[A-Za-z0-9_-]{8,128}$`, which a stamped key satisfies |

### 14.2 Identifiers

`src/my_pa/domain/common/identifiers.py` appends after `SCHEDULE_IMPORT_ISSUE`, with a comment
block in the file's style ("Checked against all 156 prior members before use …"):
`SCHEDULE_SCENARIO = "sscn"`, `SCHEDULE_SCENARIO_VERSION = "sscv"`, `SCHEDULE_CPM_RUN = "scpm"`,
`SCHEDULE_SCENARIO_OUTPUT = "ssco"`, `SCHEDULE_SERIES_MATCH = "ssmd"`, `SCHEDULE_BASELINE = "sbl"`,
`SCHEDULE_BASELINE_EVENT = "sbev"`, `SCHEDULE_GOVERNING_EVENT = "sgov"` (156 → 164).
`tests/unit/test_identifiers.py::test_contract_prefixes_are_stable` gains the 8 (exact set).
The idempotency ledger and the refusal ledger mint no identifier kind.

### 14.3 Exact schema (schema `knowledge`, revision A)

**Conventions** (the S5b-1 §4 conventions, restated where they bind): identifiers `text` with
`<column>_is_an_opaque_identifier` CHECK `<column> ~ '^<prefix>_[A-Za-z0-9]{8,64}$'`; every
FK `ON DELETE RESTRICT`, `MATCH SIMPLE`, naming the referenced unique's columns in its order;
closed sets are **frozen sorted literals** in the revision and `_one_of`/`_literals` over the
domain symbol in `tables.py`, identical text; "SHA" = CHECK `<col> ~ '^[0-9a-f]{64}$'`;
`created_at timestamptz NOT NULL DEFAULT now()`; constraint names ≤ 63 bytes. Every table
holds `principal_id text NOT NULL` (`prn`). Compressed columns are `bytea` (`LargeBinary` in
`tables.py`) holding one zlib stream of the canonical bytes (section 14.8.3).

**Provenance columns** (section 6.5), on `schedule_scenarios`, `schedule_scenario_versions`,
`schedule_cpm_runs`, `schedule_scenario_outputs`, `schedule_baseline_events`,
`schedule_governing_events`: `authority_class text NOT NULL`, `decision_channel text NOT NULL`,
`asserting_client_id text NULL`, `acceptance_basis text NOT NULL`, `user_directed_claim boolean
NOT NULL DEFAULT false`, with 2 CHECKs per table (`<t>` = the table's short name below):

- `a_<t>_creator_is_known`: `(authority_class = 'local_operator' AND decision_channel IN ('local_cli', 'local_web') AND acceptance_basis = 'user_confirmed' AND asserting_client_id IS NULL) OR (authority_class = 'ordinary_reviewer' AND decision_channel IN ('local_unattested', 'remote_interactive') AND acceptance_basis = 'client_identified' AND (asserting_client_id IS NOT NULL) = (decision_channel = 'remote_interactive'))` (the S3.1 sets `ATTESTED_DECISION_CHANNELS`, `CLIENT_DECISION_CHANNELS`, `AcceptanceBasis`; frozen);
- `a_<t>_client_is_bounded`: `asserting_client_id IS NULL OR char_length(asserting_client_id) BETWEEN 1 AND 256`.

Short names: `scenario`, `scenario_version`, `cpm_run`, `scenario_output`, `baseline_event`,
`governing_event` (for example `a_scenario_version_creator_is_known`).

**Name CHECK text** (`N(col)`): `char_length(col) BETWEEN 1 AND 200 AND col = btrim(col, ' ')
AND position('  ' in col) = 0 AND col !~ '[[:cntrl:]]'` (the `a_schedule_series_name_is_normalized` body).

#### 14.3.1 `schedule_intake_series` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `principal_id`, `project_id`, `series_id`, `publication_id` | text | no | `prn`/`prj`/`sser`/`spub` |
| `series_name_if_new` | text | yes | `an_intake_new_series_name_is_normalized`: `series_name_if_new IS NULL OR (N(series_name_if_new))` |
| `series_name_if_new_key` | text | yes | `an_intake_new_series_key_is_bounded`: `series_name_if_new_key IS NULL OR char_length(series_name_if_new_key) BETWEEN 1 AND 800`; `an_intake_new_series_name_is_whole`: `(series_name_if_new IS NULL) = (series_name_if_new_key IS NULL)` |
| `created_at` | timestamptz | no | `now()` |

- PK `schedule_intake_series_pkey (principal_id, series_id)`; UNIQUE `an_intake_publication_is_marked_once (principal_id, publication_id)`; UNIQUE `an_intake_series_is_identified_with_its_publication (principal_id, series_id, publication_id)`.
- FK `an_intake_series_is_a_series_of_its_project (series_id, principal_id, project_id) → schedule_series`; FK `an_intake_series_marks_its_publication (publication_id, principal_id, project_id, series_id) → schedule_publications` U3.
- Triggers G1 (append-only), G2 (TRUNCATE), G9 `an_intake_series_holds_only_its_publication`.

#### 14.3.2 `schedule_series_match_decisions` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `decision_id` | text | no | PK; `ssmd` |
| `principal_id`, `project_id`, `intake_series_id`, `intake_publication_id` | text | no | `prn`/`prj`/`sser`/`spub` |
| `outcome` | text | no | `a_series_match_outcome_is_known`: `IN ('admission_refused', 'already_present', 'ambiguous', 'created', 'matched', 'needs_series', 'not_eligible')` |
| `reason` | text | yes | `a_series_match_reason_is_known`: `IS NULL OR IN ('candidate_bound', 'data_date_incoherent', 'evidence_conflict', 'insufficient_evidence', 'margin', 'multiple_high', 'name_conflict')`; `an_ambiguous_match_states_one_reason`: `(outcome = 'ambiguous') = (reason IS NOT NULL)` |
| `threshold_version` | text | no | `a_series_match_threshold_version_is_known`: `threshold_version ~ '^series-match-v[1-9][0-9]{0,3}$'` |
| `incoming_id_count` | integer | no | `>= 0` (`a_series_match_count_is_not_negative`) |
| `candidates` | jsonb | no | `a_series_match_candidates_are_bounded`: `jsonb_typeof(candidates) = 'array' AND jsonb_array_length(candidates) <= 50 AND octet_length(candidates::text) <= 65536` |
| `target_series_id` | text | yes | `sser` |
| `resulting_publication_id` | text | yes | `spub` |
| `admission_refusal` | text | yes | `a_series_match_refusal_is_known`: `IS NULL OR IN (<the 14 ScheduleAdmissionRefusal values, sorted>, 'integrity_violation')` |
| `admission_skipped` | text | yes | `a_series_match_skip_is_known`: `IS NULL OR admission_skipped = 'plane_disabled'` |
| `created_at` | timestamptz | no | `now()` |

`a_series_match_records_its_result` (one CHECK, the outcome shapes):
`(outcome IN ('matched', 'created') AND admission_refusal IS NULL AND ((admission_skipped IS NULL AND target_series_id IS NOT NULL AND resulting_publication_id IS NOT NULL) OR (admission_skipped IS NOT NULL AND resulting_publication_id IS NULL AND (outcome = 'matched') = (target_series_id IS NOT NULL)))) OR (outcome = 'already_present' AND target_series_id IS NOT NULL AND resulting_publication_id IS NOT NULL AND admission_refusal IS NULL AND admission_skipped IS NULL) OR (outcome = 'admission_refused' AND resulting_publication_id IS NULL AND admission_refusal IS NOT NULL AND admission_skipped IS NULL) OR (outcome IN ('ambiguous', 'needs_series', 'not_eligible') AND target_series_id IS NULL AND resulting_publication_id IS NULL AND admission_refusal IS NULL AND admission_skipped IS NULL)`.
A skipped `created` names no Series (none is created while the plane is off); an
`admission_refused` names its target when the refused admission was a `matched` one and none
when it was a `created` one, so that branch leaves `target_series_id` free.

- UNIQUE `an_intake_publication_is_decided_once (principal_id, intake_publication_id)`.
- FK `a_series_match_decides_an_intake_publication (principal_id, intake_series_id, intake_publication_id) → schedule_intake_series (principal_id, series_id, publication_id)`.
- FK `a_series_match_names_its_intake_publication (intake_publication_id, principal_id, project_id, intake_series_id) → schedule_publications` U3.
- FK `a_series_match_targets_a_series_of_its_project (target_series_id, principal_id, project_id) → schedule_series`.
- FK `a_series_match_names_a_publication_of_its_target (resulting_publication_id, principal_id, project_id, target_series_id) → schedule_publications` U3.
- Index `schedule_series_match_decisions_by_project (principal_id, project_id, created_at, decision_id)`.
- Triggers G1, G2, G11 `a_series_match_decision_follows_its_intake`.

#### 14.3.3 `schedule_baselines` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `baseline_id` | text | no | PK; `sbl` |
| `principal_id`, `project_id`, `series_id`, `publication_id` | text | no | `prn`/`prj`/`sser`/`spub` |
| `type` | text | no | `a_schedule_baseline_type_is_known`: `IN ('approved_update', 'contract')` (the proposed type, or the direct approval's; RR2-F01) |
| `created_at` | timestamptz | no | `now()` |

- UNIQUE `a_schedule_baseline_is_identified_within_its_project (baseline_id, principal_id, project_id)` (supersedes and governing target).
- UNIQUE `a_schedule_baseline_is_identified_with_its_publication (baseline_id, principal_id, project_id, publication_id)` (event target).
- UNIQUE `a_schedule_baseline_names_its_publication (baseline_id, principal_id, publication_id)` (scenario target).
- FK `a_schedule_baseline_names_a_publication_of_its_series (publication_id, principal_id, project_id, series_id) → schedule_publications` U3.
- Index `schedule_baselines_by_project (principal_id, project_id, created_at, baseline_id)`; index `schedule_baselines_by_publication (principal_id, publication_id)`.
- Triggers G1, G2, G12 `a_schedule_baseline_names_an_admissible_publication`, G13 `a_schedule_baseline_has_its_first_event` (deferred).

#### 14.3.4 `schedule_baseline_events` (append-only, per-Project chain)

| Column | Type | Null | Rule |
|---|---|---|---|
| `event_id` | text | no | PK; `sbev` |
| `principal_id`, `project_id`, `baseline_id`, `publication_id` | text | no | `prn`/`prj`/`sbl`/`spub` |
| `action` | text | no | `a_schedule_baseline_action_is_known`: `IN ('approve', 'propose', 'reject', 'revoke', 'withdraw')` |
| `seq` | integer | no | `a_schedule_baseline_event_seq_is_positive`: `seq >= 1` |
| `previous_event_id` | text | yes | `sbev`; `a_schedule_baseline_event_chain_starts_once`: `(seq = 1) = (previous_event_id IS NULL)` |
| `recorded_at` | timestamptz | no | no default: the writer inserts `clock_timestamp()` after the Project lock (section 12.1) |
| `reason` | text | no | `a_schedule_baseline_reason_is_bounded`: `char_length(reason) BETWEEN 1 AND 2000` |
| `type` | text | yes | `a_schedule_baseline_event_type_is_known`: `IS NULL OR IN ('approved_update', 'contract')` |
| `label` | text | yes | `a_schedule_baseline_label_is_well_formed`: `IS NULL OR label ~ '^BL-(0|[1-9][0-9]{0,8})$'` |
| `approval_reference` | text | yes | `a_schedule_approval_reference_is_bounded`: `IS NULL OR char_length BETWEEN 1 AND 500` |
| `effective_from` | date | yes | |
| `supersedes_baseline_id` | text | yes | `sbl`; `a_schedule_baseline_does_not_supersede_itself`: `IS NULL OR supersedes_baseline_id <> baseline_id` |
| `proposal_ordinal` | integer | yes | `a_schedule_proposal_ordinal_is_not_negative`: `IS NULL OR >= 0` |
| `approved_at_import` | boolean | yes | |
| provenance (5) | | | `a_baseline_event_creator_is_known`, `a_baseline_event_client_is_bounded` |
| `created_at` | timestamptz | no | `now()` |

`a_schedule_baseline_event_carries_its_fields`:
`(action = 'propose' AND type IS NOT NULL AND proposal_ordinal IS NOT NULL AND label IS NULL AND approval_reference IS NULL AND effective_from IS NULL AND supersedes_baseline_id IS NULL AND approved_at_import IS NULL) OR (action = 'approve' AND type IS NOT NULL AND label IS NOT NULL AND approval_reference IS NOT NULL AND effective_from IS NOT NULL AND approved_at_import IS NOT NULL AND proposal_ordinal IS NULL) OR (action IN ('reject', 'withdraw', 'revoke') AND type IS NULL AND label IS NULL AND approval_reference IS NULL AND effective_from IS NULL AND supersedes_baseline_id IS NULL AND proposal_ordinal IS NULL AND approved_at_import IS NULL)`.

`a_schedule_baseline_decision_is_operator_attested`: `action NOT IN ('approve', 'reject', 'revoke') OR authority_class = 'local_operator'` (section 12.3; `withdraw` and `propose` are open to either authority, the proposer-bucket rule is `decide_baseline_write`'s).

Uniques (section 12.1 backstops, exactly):

- UNIQUE `a_schedule_baseline_event_seq_is_used_once (principal_id, project_id, seq)`.
- UNIQUE `a_schedule_baseline_event_is_identified_within_its_project (event_id, principal_id, project_id)` (predecessor target).
- partial UNIQUE index `a_schedule_baseline_is_decided_once ON (principal_id, baseline_id) WHERE action IN ('approve', 'reject', 'withdraw')`.
- partial UNIQUE index `a_schedule_baseline_is_revoked_once ON (principal_id, baseline_id) WHERE action = 'revoke'`.
- partial UNIQUE index `a_schedule_publication_is_approved_once ON (principal_id, publication_id) WHERE action = 'approve'`.
- partial UNIQUE index `a_schedule_baseline_label_is_used_once ON (principal_id, project_id, label) WHERE action = 'approve'`.
- partial UNIQUE index `a_schedule_proposal_ordinal_is_used_once ON (principal_id, publication_id, proposal_ordinal) WHERE action = 'propose'`.

FKs: `a_schedule_baseline_event_names_its_baseline (baseline_id, principal_id, project_id, publication_id) → schedule_baselines`;
`a_schedule_baseline_event_follows_its_predecessor (previous_event_id, principal_id, project_id) → schedule_baseline_events (event_id, principal_id, project_id)`;
`a_schedule_baseline_event_supersedes_a_baseline_of_its_project (supersedes_baseline_id, principal_id, project_id) → schedule_baselines (baseline_id, principal_id, project_id)`.
Index `schedule_baseline_events_by_baseline (principal_id, baseline_id, seq)`.
Triggers G1, G2, G14 `a_schedule_baseline_event_extends_its_chain`.

#### 14.3.5 `schedule_governing_events` (append-only, per-Project chain)

| Column | Type | Null | Rule |
|---|---|---|---|
| `governing_event_id` | text | no | PK; `sgov` |
| `principal_id`, `project_id`, `baseline_id` | text | no | `prn`/`prj`/`sbl` |
| `seq` | integer | no | `a_governing_event_seq_is_positive`: `>= 1` |
| `previous_governing_event_id` | text | yes | `sgov`; `a_governing_event_chain_starts_once`: `(seq = 1) = (previous_governing_event_id IS NULL)` |
| `recorded_at` | timestamptz | no | writer-supplied `clock_timestamp()` |
| `reason` | text | no | `a_governing_reason_is_bounded`: `char_length BETWEEN 1 AND 2000` |
| provenance (5) | | | `a_governing_event_creator_is_known`, `a_governing_event_client_is_bounded`, and `a_governing_event_is_operator_attested`: `authority_class = 'local_operator'` |
| `created_at` | timestamptz | no | `now()` |

- UNIQUE `a_governing_event_seq_is_used_once (principal_id, project_id, seq)`; UNIQUE `a_governing_event_is_identified_within_its_project (governing_event_id, principal_id, project_id)`.
- FK `a_governing_event_follows_its_predecessor (previous_governing_event_id, principal_id, project_id) → schedule_governing_events (governing_event_id, principal_id, project_id)`; FK `a_governing_event_names_a_baseline_of_its_project (baseline_id, principal_id, project_id) → schedule_baselines`.
- Triggers G1, G2, G15 `a_schedule_governing_event_extends_its_chain`.

#### 14.3.6 `schedule_scenarios` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `scenario_id` | text | no | PK; `sscn` |
| `principal_id`, `project_id`, `series_id` | text | no | `prn`/`prj`/`sser` |
| `name` | text | no | `a_schedule_scenario_name_is_normalized`: `N(name)` |
| `description` | text | yes | `a_schedule_scenario_description_is_bounded`: `IS NULL OR char_length(description) <= 2000` |
| `origin_kind` | text | no | `a_schedule_scenario_origin_kind_is_known`: `IN ('publication', 'version')` |
| `origin_publication_id` | text | yes | `spub` |
| `origin_baseline_id` | text | yes | `sbl` |
| `origin_version_id` | text | yes | `sscv` |
| provenance (5) | | | `a_scenario_creator_is_known`, `a_scenario_client_is_bounded` |
| `created_at` | timestamptz | no | `now()` |

`a_schedule_scenario_origin_is_whole`: `(origin_kind = 'publication' AND origin_publication_id IS NOT NULL AND origin_version_id IS NULL) OR (origin_kind = 'version' AND origin_version_id IS NOT NULL AND origin_publication_id IS NULL AND origin_baseline_id IS NULL)`.

- UNIQUE `a_schedule_scenario_is_identified_within_its_series (scenario_id, principal_id, project_id, series_id)`.
- FK `a_schedule_scenario_names_a_series_of_its_project (series_id, principal_id, project_id) → schedule_series`.
- FK `a_schedule_scenario_starts_from_a_publication_of_its_series (origin_publication_id, principal_id, project_id, series_id) → schedule_publications` U3.
- FK `a_schedule_scenario_starts_from_a_baseline_of_its_publication (origin_baseline_id, principal_id, origin_publication_id) → schedule_baselines (baseline_id, principal_id, publication_id)` (applies only when both are set; the origin CHECK forbids a baseline without its publication).
- FK `a_schedule_scenario_forks_a_version_of_its_series (origin_version_id, principal_id, project_id, series_id) → schedule_scenario_versions (version_id, principal_id, project_id, series_id)` — circular, added by `ALTER TABLE` after the versions table (`use_alter=True` in `tables.py`, the S5b-1 accepted-run precedent).
- Indexes `schedule_scenarios_by_project (principal_id, project_id, created_at, scenario_id)`, `schedule_scenarios_by_series (principal_id, series_id, created_at, scenario_id)`.
- Triggers G1, G2, G3 `a_schedule_scenario_starts_from_an_admissible_origin`, G4 `a_schedule_scenario_has_its_first_version` (deferred).

#### 14.3.7 `schedule_scenario_versions` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `version_id` | text | no | PK; `sscv` |
| `principal_id`, `project_id`, `series_id`, `scenario_id` | text | no | `prn`/`prj`/`sser`/`sscn` |
| `version_no` | integer | no | `a_scenario_version_number_is_bounded`: `BETWEEN 1 AND 500` |
| `parent_version_id` | text | yes | `sscv`; `a_scenario_version_has_a_parent_after_the_first`: `(version_no = 1) = (parent_version_id IS NULL)` |
| `label` | text | no | `a_scenario_version_label_is_known`: `IN ('simulation_input', 'update', 'what_if')` |
| `note` | text | yes | `a_scenario_version_note_is_bounded`: `IS NULL OR char_length(note) <= 2000` |
| `content_zlib` | bytea | no | `a_scenario_content_is_stored_bounded`: `octet_length(content_zlib) BETWEEN 1 AND 33619968` |
| `content_sha256` | text | no | SHA (`a_scenario_content_digest_is_sha256`) |
| `content_size_bytes` | integer | no | `a_scenario_content_size_is_bounded`: `BETWEEN 1 AND 33554432` |
| `change_set_zlib` | bytea | yes | `a_scenario_change_set_is_stored_bounded`: `IS NULL OR octet_length BETWEEN 1 AND 4259840` |
| `change_set_sha256` | text | yes | SHA when set |
| `change_set_size_bytes` | integer | yes | `IS NULL OR BETWEEN 1 AND 4194304` |
| `change_set_op_count`, `ops_applied`, `relationships_removed` | integer | yes | `a_scenario_change_counts_are_bounded`: `change_set_op_count IS NULL OR change_set_op_count BETWEEN 1 AND 5000`, `ops_applied IS NULL OR ops_applied BETWEEN 0 AND change_set_op_count`, `relationships_removed IS NULL OR relationships_removed >= 0` |
| `content_changed` | boolean | yes | |
| `snapshot_activities`, `snapshot_milestones`, `snapshot_durations_quantized`, `snapshot_durations_out_of_range`, `snapshot_original_missing`, `snapshot_remaining_missing` | integer | yes | `a_scenario_snapshot_counts_are_not_negative`: each `IS NULL OR >= 0` |
| `activity_count` | integer | no | `BETWEEN 0 AND 25000` |
| `relationship_count` | integer | no | `BETWEEN 0 AND 100000` |
| `calendar_count` | integer | no | `BETWEEN 1 AND 32` (the 3 in `a_scenario_version_counts_are_bounded`) |
| `distribution_spec_sha256` | text | no | SHA |
| provenance (5) | | | `a_scenario_version_creator_is_known`, `a_scenario_version_client_is_bounded` |
| `created_at` | timestamptz | no | `now()` |

`a_scenario_change_set_is_whole`: `(version_no = 1) = (change_set_zlib IS NULL) AND (change_set_zlib IS NULL) = (change_set_sha256 IS NULL) AND (change_set_zlib IS NULL) = (change_set_size_bytes IS NULL) AND (change_set_zlib IS NULL) = (change_set_op_count IS NULL) AND (change_set_zlib IS NULL) = (ops_applied IS NULL) AND (change_set_zlib IS NULL) = (relationships_removed IS NULL) AND (change_set_zlib IS NULL) = (content_changed IS NULL)`.
`a_scenario_snapshot_report_is_whole`: the 6 snapshot columns are all NULL or all NOT NULL, and all NULL when `version_no > 1` (that they are set exactly on version 1 of a publication-origin Scenario is G5's).
(Every stored `*_zlib` bound is the canonical bound plus 65,536 bytes, above zlib's
worst-case expansion of 5 bytes per 16 KiB block plus its header at 64 MiB.)

- UNIQUE `a_scenario_version_number_is_used_once (principal_id, scenario_id, version_no)` (section 9.2).
- UNIQUE `a_scenario_version_is_identified_within_its_scenario (version_id, principal_id, scenario_id)` (parent target).
- UNIQUE `a_scenario_version_is_identified_within_its_series (version_id, principal_id, project_id, series_id)` (fork target).
- UNIQUE `a_scenario_version_is_identified_with_its_content (version_id, principal_id, content_sha256)` (run and output binding).
- FK `a_scenario_version_belongs_to_its_scenario (scenario_id, principal_id, project_id, series_id) → schedule_scenarios`.
- FK `a_scenario_version_follows_its_parent (parent_version_id, principal_id, scenario_id) → schedule_scenario_versions (version_id, principal_id, scenario_id)`.
- Index `schedule_scenario_versions_by_principal_time (principal_id, created_at)` (quota sums).
- Triggers G1, G2, G5 `a_scenario_version_extends_its_chain`.

#### 14.3.8 `schedule_cpm_runs` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `cpm_run_id` | text | no | PK; `scpm` |
| `principal_id`, `version_id` | text | no | `prn`/`sscv` |
| `engine_version` | text | no | `a_cpm_run_engine_version_is_known`: `engine_version ~ '^my-pa-cpm-v[1-9][0-9]{0,3}$'` (a bump needs no restatement) |
| `input_content_sha256` | text | no | SHA |
| `status` | text | no | `a_cpm_run_status_is_known`: `IN ('computed', 'rejected')` |
| `result_zlib` | bytea | no | `a_cpm_result_is_stored_bounded`: `octet_length BETWEEN 1 AND 67174400` |
| `result_sha256` | text | no | SHA |
| `result_size_bytes` | integer | no | `a_cpm_result_size_is_bounded`: `BETWEEN 1 AND 67108864` |
| `activity_count`, `relationship_count` | integer | no | `a_cpm_run_counts_are_bounded`: `BETWEEN 0 AND 25000`, `BETWEEN 0 AND 100000` (the CPM-unit sum reads `activity_count`) |
| `project_finish` | text | yes | `a_cpm_run_finish_is_an_instant`: `project_finish IS NULL OR project_finish ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$'`; `a_rejected_cpm_run_has_no_finish`: `status = 'computed' OR project_finish IS NULL` |
| provenance (5) | | | `a_cpm_run_creator_is_known`, `a_cpm_run_client_is_bounded` (who requested the computation) |
| `created_at` | timestamptz | no | `now()` |

- UNIQUE `a_cpm_run_is_computed_once (principal_id, version_id, engine_version)` (the natural key, section 3.11).
- UNIQUE `a_cpm_run_is_identified_with_its_version (cpm_run_id, principal_id, version_id)` (output target).
- FK `a_cpm_run_computes_its_version_content (version_id, principal_id, input_content_sha256) → schedule_scenario_versions (version_id, principal_id, content_sha256)`.
- Index `schedule_cpm_runs_by_principal_time (principal_id, created_at)`.
- Triggers G1, G2. No `server_computed` column: only the server inserts a run, so the label is a read-time constant (S6-2-D10).

#### 14.3.9 `schedule_scenario_outputs` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `output_id` | text | no | PK; `ssco` |
| `principal_id`, `version_id` | text | no | `prn`/`sscv` |
| `content_sha256` | text | no | SHA (binding, section 4.1) |
| `base_cpm_run_id` | text | yes | `scpm` |
| `kind` | text | no | `a_scenario_output_kind_is_known`: `IN ('criticality', 'monte_carlo', 'sensitivity')` |
| `iterations` | integer | no | `a_scenario_output_iterations_are_bounded`: `BETWEEN 1 AND 1000000` |
| `distribution_spec_sha256` | text | no | SHA |
| `payload_zlib` | bytea | no | `a_scenario_output_is_stored_bounded`: `octet_length BETWEEN 1 AND 1114112` |
| `payload_sha256` | text | no | SHA |
| `payload_size_bytes` | integer | no | `a_scenario_output_size_is_bounded`: `BETWEEN 1 AND 1048576` |
| provenance (5) | | | `a_scenario_output_creator_is_known`, `a_scenario_output_client_is_bounded` |
| `created_at` | timestamptz | no | `now()` |

- FK `a_scenario_output_binds_its_version_content (version_id, principal_id, content_sha256) → schedule_scenario_versions (version_id, principal_id, content_sha256)`.
- FK `a_scenario_output_names_a_run_of_its_version (base_cpm_run_id, principal_id, version_id) → schedule_cpm_runs (cpm_run_id, principal_id, version_id)`.
- Index `schedule_scenario_outputs_by_version (principal_id, version_id, created_at, output_id)`; index `schedule_scenario_outputs_by_principal_time (principal_id, created_at)`.
- Triggers G1, G2, G6 `a_scenario_output_binds_a_computed_run`.

#### 14.3.10 `schedule_scenario_write_requests` (idempotency ledger; one legal transition)

| Column | Type | Null | Rule |
|---|---|---|---|
| `principal_id` | text | no | `prn` |
| `capability` | text | no | `a_plane_write_request_capability_is_known`: `IN ('schedule_baselines.approve', 'schedule_baselines.propose', 'schedule_baselines.reject', 'schedule_baselines.revoke', 'schedule_baselines.set_governing', 'schedule_baselines.withdraw', 'schedule_cpm_runs.create', 'schedule_scenario_outputs.record', 'schedule_scenario_versions.create', 'schedule_scenarios.create')` (from `PLANE_WRITE_CAPABILITIES`, section 14.7) |
| `idempotency_key` | text | no | `a_plane_write_request_key_is_bounded`: `idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'` |
| `request_digest` | text | no | SHA (`scenario_request_digest`, section 6.3) |
| `decision_channel` | text | no | `a_plane_write_request_channel_is_known`: `IN ('local_cli', 'local_unattested', 'local_web', 'remote_interactive')` |
| `asserting_client_id` | text | yes | `a_plane_write_request_client_is_whole`: `(asserting_client_id IS NOT NULL) = (decision_channel = 'remote_interactive') AND (asserting_client_id IS NULL OR char_length(asserting_client_id) BETWEEN 1 AND 256)` |
| `result_kind` | text | yes | `a_plane_write_request_result_kind_is_known`: `IS NULL OR IN ('baseline_event', 'cpm_run', 'governing_event', 'output', 'scenario', 'version')` |
| `result_id` | text | yes | `a_plane_write_request_result_is_typed`: `result_id IS NULL OR (result_kind = 'scenario' AND result_id ~ '^sscn_…$') OR (… 'version' sscv) OR (… 'cpm_run' scpm) OR (… 'output' ssco) OR (… 'baseline_event' sbev) OR (… 'governing_event' sgov)` (each pattern `^<prefix>_[A-Za-z0-9]{8,64}$`) |
| `result_created` | boolean | yes | false only for a natural-key CPM hit (an existing run returned) |
| `result_bytes` | bigint | yes | `>= 0` (new canonical bytes stored by this write; 0 for events and a natural-key hit) |
| `created_at` | timestamptz | no | `now()` |
| `completed_at` | timestamptz | yes | |

- PK `schedule_scenario_write_requests_pkey (principal_id, capability, idempotency_key)` (section 6.3).
- `an_incomplete_plane_write_request_names_no_result`: `completed_at IS NOT NULL OR (result_kind IS NULL AND result_id IS NULL AND result_created IS NULL AND result_bytes IS NULL)`.
- `a_complete_plane_write_request_names_its_result`: `completed_at IS NULL OR (result_id IS NOT NULL AND result_created IS NOT NULL AND result_bytes IS NOT NULL AND result_kind = CASE capability WHEN 'schedule_scenarios.create' THEN 'scenario' WHEN 'schedule_scenario_versions.create' THEN 'version' WHEN 'schedule_cpm_runs.create' THEN 'cpm_run' WHEN 'schedule_scenario_outputs.record' THEN 'output' WHEN 'schedule_baselines.set_governing' THEN 'governing_event' ELSE 'baseline_event' END)`.
- Indexes `schedule_scenario_write_requests_by_bucket (principal_id, decision_channel, asserting_client_id, completed_at)`, `schedule_scenario_write_requests_by_principal (principal_id, completed_at)`.
- Triggers G7 `a_plane_write_request_completes_once`, G8 `a_plane_write_request_is_never_left_reserved` (deferred), G2.

#### 14.3.11 `schedule_scenario_write_refusals` (append-only; amendment S6-2-D03)

| Column | Type | Null | Rule |
|---|---|---|---|
| `refusal_no` | bigint | no | PK; `GENERATED BY DEFAULT AS IDENTITY` (`Identity()` in `tables.py`, the `resolution_sequence` precedent) |
| `principal_id` | text | no | `prn` |
| `capability` | text | no | `a_plane_refusal_capability_is_known`: the 10-name set above |
| `decision_channel`, `asserting_client_id` | text | no / yes | the 2 ledger CHECKs, named `a_plane_refusal_channel_is_known`, `a_plane_refusal_client_is_whole` |
| `error_code` | text | no | `a_plane_refusal_code_is_public`: `IN ('ambiguous_request', 'cancelled', 'conflict', 'denied', 'internal_error', 'invalid_request', 'not_found', 'quarantined', 'rate_limited', 'unavailable', 'unsupported')` (the `schedule_jobs` literal set) |
| `refused_at` | timestamptz | no | `now()` |

- Index `schedule_scenario_write_refusals_by_bucket (principal_id, decision_channel, asserting_client_id, refused_at)`.
- Triggers G1, G2. Written in its own short transaction after the refused one rolled back (14.8.5); never written for an attested operator or for a refusal answered by the refusal bound itself, so it holds about 120 rows per writer bucket per hour at most (a soft bound: the count is read outside P before a separate insert transaction, R9-F13) (retention: S6-2-U05).

#### 14.3.12 Changes to existing tables

| Table | Change |
|---|---|
| `schedule_publications` | restate `a_schedule_publication_role_is_known` → `publication_role IN ('baseline', 'update')`; restate `a_schedule_baseline_kind_is_known` → `baseline_kind IS NULL OR baseline_kind IN ('approved_update', 'contract')` (section 12.2); new trigger G10 `a_schedule_intake_series_admits_no_other_publication` (`BEFORE INSERT FOR EACH ROW`) |
| `record_links` | restate 6 CHECKs from the storage vocabulary (section 14.7.4): `a_record_link_from_family_is_known`, `a_record_link_to_family_is_known`, `from_id_is_an_opaque_identifier`, `to_id_is_an_opaque_identifier`, `a_record_link_relation_type_is_known`, `a_record_link_pair_is_admitted` |
| every other existing table, column, CHECK, trigger, index, function and vocabulary | unchanged; `a_linked_record_is_not_deleted` is **not** attached to a plane table (every plane table and every S5 table it names already refuses `DELETE`) |

### 14.4 Functions and triggers

All plane functions are `LANGUAGE plpgsql` in `knowledge`, take no argument, name every
table schema-qualified (`knowledge.<table>`), carry no identifier or content in a message,
and are created in the default `ENABLE` mode (the S5b-1 §4.10 rules). None reuses an S1 or
S5 function (D-13 precedent: plane-local downgrade). SQLSTATE: `restrict_violation`
(`23001`) for immutability, transition, chain and lifecycle legality; `check_violation`
(`23514`) for deferred completeness and the `recorded_at` order (section 12.1 "CHECK-by-trigger").

**Principal-qualified lookups (R9-F06).** Every row a plane trigger reads is selected by
`principal_id = NEW.principal_id` **and** the composite columns its FK names (for example the
origin publication by `(publication_id, principal_id, project_id, series_id)`), never by a
bare identifier. A BEFORE trigger runs before the AFTER FK check, so a trigger that finds no
row under those columns returns `NEW` without deciding, and the FK then refuses with
`foreign_key_violation` (`23503`): another Principal's row can neither decide a refusal class
nor serve as an existence oracle (the S5 precedent qualifies by `principal_id` the same way).
This "absent ⇒ defer" rule applies only to the **subject** lookup the FK also names. It does
**not** apply to aggregates where absence is meaningful — G14 (a)/G15 (a) chain start (no
event ⇒ `seq` must be 1), G5 "no version of the Scenario exists", G12 "no `approve` exists",
G9's publication set, G4/G8/G13 completeness — which are evaluated on the (Principal-qualified)
empty read and decide (RR1-F05).

| # | Function | Attached | Rule |
|---|---|---|---|
| G1 | `schedule_plane_rows_are_append_only()` | `BEFORE UPDATE OR DELETE FOR EACH ROW` on the 10 append-only plane tables (all but the ledger) | `'% is append-only', TG_TABLE_NAME` |
| G2 | `schedule_plane_relations_refuse_truncate()` | `BEFORE TRUNCATE FOR EACH STATEMENT` on all 11 | refuses only when the table holds a row (the S1 body) |
| G3 | `a_schedule_scenario_starts_from_an_admissible_origin()` | `BEFORE INSERT` on scenarios | `publication`: the origin publication's stored `status IN ('complete', 'partial')` (terminal, so equal to the effective status) and `NOT EXISTS` an intake row for `NEW.series_id`; with `origin_baseline_id`: that Baseline has an `approve` event and no `revoke` event (its publication is the origin publication by FK; eligibility is the status rule just checked); `version`: the source version's Scenario is in `NEW.series_id` (FK) — nothing else |
| G4 | `a_schedule_scenario_has_its_first_version()` | constraint trigger `AFTER INSERT`, `DEFERRABLE INITIALLY DEFERRED`, on scenarios | at commit a version with `version_no = 1` of the Scenario exists, else `check_violation` (S6-D03: no blank Scenario) |
| G5 | `a_scenario_version_extends_its_chain()` | `BEFORE INSERT` on versions | `version_no = 1`: no version of the Scenario exists; the 6 snapshot columns are set iff the Scenario's `origin_kind = 'publication'`; for `origin_kind = 'version'`, `content_sha256`, `content_size_bytes` and `distribution_spec_sha256` equal the source version's (byte-for-byte copy, section 2.2). `version_no > 1`: the parent's `version_no = NEW.version_no - 1` and it is the Scenario's current maximum (linear chain) |
| G6 | `a_scenario_output_binds_a_computed_run()` | `BEFORE INSERT` on outputs | `distribution_spec_sha256` equals the version's; a set `base_cpm_run_id` names a run with `status = 'computed'` |
| G7 | `a_plane_write_request_completes_once()` | `BEFORE INSERT OR UPDATE OR DELETE FOR EACH ROW` on the ledger | INSERT: `completed_at IS NULL`; DELETE refused; UPDATE: only `OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL`, and only `completed_at`, `result_kind`, `result_id`, `result_created`, `result_bytes` change (`to_jsonb(NEW) - <those 5> = to_jsonb(OLD) - <those 5>`) |
| G8 | `a_plane_write_request_is_never_left_reserved()` | constraint trigger `AFTER INSERT OR UPDATE`, deferred, on the ledger | at commit the row (re-read) has `completed_at IS NOT NULL`, else `check_violation` (the `a_lineage_write_request_is_never_left_reserved` precedent) |
| G9 | `an_intake_series_holds_only_its_publication()` | `BEFORE INSERT` on intake | the Series' publications are exactly `{NEW.publication_id}`; that publication has `publication_role = 'update'`, `baseline_kind IS NULL`, `supersedes_publication_id IS NULL`; the Series' `name = 'Schedule intake ' || substr(<publication>.request_digest, 1, 12)` |
| G10 | `a_schedule_intake_series_admits_no_other_publication()` | `BEFORE INSERT` on `schedule_publications` | refuses when an intake row names `NEW.series_id` (with G9: an intake Series holds exactly 1 publication; R8-F11) |
| G11 | `a_series_match_decision_follows_its_intake()` | `BEFORE INSERT` on decisions | the intake publication's stored status is terminal; `outcome = 'not_eligible'` iff that status `NOT IN ('complete', 'partial')`; a set `target_series_id` is not an intake Series |
| G12 | `a_schedule_baseline_names_an_admissible_publication()` | `BEFORE INSERT` on baselines | the publication's Series is not intake; no other Baseline row names the publication with an `approve` event (a revoked publication is not re-approvable, S6-D28; the partial unique is the race backstop) |
| G13 | `a_schedule_baseline_has_its_first_event()` | constraint trigger `AFTER INSERT`, deferred, on baselines | at commit an event of the Baseline with action `propose` or `approve` exists, else `check_violation` |
| G14 | `a_schedule_baseline_event_extends_its_chain()` | `BEFORE INSERT` on baseline events | (a) **chain:** `NEW.seq = 1 + coalesce(max(seq), 0)` over the Project's events and `NEW.previous_event_id` is the event at that maximum; (b) **order:** `NEW.recorded_at >= predecessor.recorded_at` else `check_violation`; (c) **lifecycle** over the Baseline's prior events: `propose` and a direct `approve` need none; an adopting `approve`, `reject` and `withdraw` need the latest to be `propose` with no decision; `revoke` needs an `approve` and no `revoke`, and refuses when the Project's governing head names this Baseline (S6-O22); (d) **eligibility:** `propose` and an `approve` with `approved_at_import = false` need the publication's stored `status IN ('complete', 'partial')`; `approved_at_import = true` needs `status = 'queued'` **and** the publication's `admitted_at = now()` (transaction-start time, the default the admission used: it was admitted in this transaction; R9-F13); (e) **label:** an `approve`'s `label = 'BL-' || <count of the Project's approve events>`; (f) **ordinal:** a `propose`'s `proposal_ordinal` = the count of earlier `propose` events of that publication whose Baseline has a decision; (g) **supersedes:** a set `supersedes_baseline_id` has an `approve` and no `revoke` |
| G15 | `a_schedule_governing_event_extends_its_chain()` | `BEFORE INSERT` on governing events | (a) chain and (b) order as G14 over the governing chain; (c) the Baseline has an `approve`, no `revoke`, and its publication's stored status is `complete`/`partial` |

G14 (a)–(f) and G15 (a)–(c) read under READ COMMITTED inside the writer's transaction; they
are exact under the Project lock and are the database backstop without it (2 concurrent
writers both compute `seq = n + 1`; the UNIQUE refuses one, section 12.1).

### 14.5 Native virtual edges

The 8 section 5.2 virtual edges are columns: `scenario_version_of` (`versions.scenario_id`),
`scenario_version_parent` (`parent_version_id`), `scenario_based_on_publication`
(`origin_publication_id`), `scenario_based_on_baseline` (`origin_baseline_id`),
`scenario_forked_from_version` (`origin_version_id`), `scenario_output_of`
(`outputs.version_id`), `schedule_baseline_designates` (`baselines.publication_id`),
`schedule_baseline_supersedes` (`baseline_events.supersedes_baseline_id` on the `approve`).
Their read-side exposure is S6-3.

### 14.6 Migration plan (revision A)

#### 14.6.1 File and form

`migrations/versions/<YYYYMMDD>_<rev>_schedule_scenarios_persistence.py`, generated by
`alembic revision` against the re-authenticated sole head; `down_revision = "621ef6786c64"`;
1 revision (the section 9.2 "revision A"; no second S6-2 revision is justified: every object
is additive and one transaction gives one rollback unit). Imports `from alembic import op` and
`typing.Final` only. Docstring in the `621ef6786c64` style (its `_restate` helper is replaced by a per-table multi-clause
`ALTER TABLE` builder, section 14.6.2 steps 7 and 9): the ordered steps, "No role grant
changes", "No backfill", the upgrade and downgrade refusals, operator authority. Frozen
literals (written out, sorted, never derived): the 7 match outcomes, 7 reasons, 14 + 1
refusal tokens, 5 baseline actions, 2 baseline types, 2 origin kinds, 3 labels, 2 run
statuses, 3 output kinds, 10 plane capabilities, 4 channels, 6 result kinds, 11 error codes,
the provenance sets, the 2 + 2 publication CHECK texts (BEFORE and AT), and the 6 + 6
`record_links` CHECK texts (BEFORE and AT).

`record_links` BEFORE texts: the 4 family/identifier CHECKs are the texts `264310e0416a`
created inline; `a_record_link_relation_type_is_known` and `a_record_link_pair_is_admitted`
are byte copies of `6f1476b8da52`'s `_WIDENED_CHECKS` AT texts. AT texts: exactly what
`tables.py` builds from the storage vocabulary (section 14.7.4) — the families sorted
(`capture_version`, `commitment`, `constraint`, `meeting`, `meeting_note_version`, `scenario`,
`scenario_output`, `scenario_version`, `schedule_activity`, `schedule_baseline`,
`schedule_publication`, `situation`, `task`), the identifier disjunction in that order, the
11 relation types sorted, and the pair disjunction per relation in sorted order; a FAST test
asserts each AT literal equals `str(CheckConstraint.sqltext)` of the `tables.py` declaration
(`test_frozen_lineage_texts_equal_the_storage_vocabulary`).

#### 14.6.2 `upgrade()` in order

1. `SET LOCAL lock_timeout = '10s'`.
2. **Early refusal** (fail fast, non-authoritative): `DO` block raising `restrict_violation`
   `'schedule scenarios: publications with a retired role exist; refusing to upgrade to <rev>'`
   when `EXISTS (SELECT 1 FROM knowledge.schedule_publications WHERE publication_role IN
   ('baseline', 'reference'))` (section 12.2; S6-U13).
3. `CREATE TABLE` in order: `schedule_intake_series`, `schedule_series_match_decisions`,
   `schedule_baselines`, `schedule_baseline_events`, `schedule_governing_events`,
   `schedule_scenarios`, `schedule_scenario_versions`, `schedule_cpm_runs`,
   `schedule_scenario_outputs`, `schedule_scenario_write_requests`,
   `schedule_scenario_write_refusals`, each with its inline CHECKs, uniques and FKs **among new
   tables only**, followed by its `CREATE [UNIQUE] INDEX` statements. No `CREATE TABLE` names
   an existing table.
4. `ALTER TABLE knowledge.schedule_scenarios ADD CONSTRAINT
   a_schedule_scenario_forks_a_version_of_its_series FOREIGN KEY …` (circular).
5. `CREATE FUNCTION` G1–G15.
6. `CREATE TRIGGER` / `CREATE CONSTRAINT TRIGGER` on the new tables (a `_triggers()` tuple).
7. **Live phase A — `schedule_publications`** (S5; live if the S5 revisions were applied and
   used): `LOCK TABLE knowledge.schedule_publications IN ACCESS EXCLUSIVE MODE` (held to
   commit); the **authoritative** refusal `DO` block of step 2 (no row can be inserted from
   here to commit); **one** `ALTER TABLE knowledge.schedule_publications DROP CONSTRAINT
   a_schedule_publication_role_is_known, ADD CONSTRAINT a_schedule_publication_role_is_known
   CHECK (…), DROP CONSTRAINT a_schedule_baseline_kind_is_known, ADD CONSTRAINT
   a_schedule_baseline_kind_is_known CHECK (…)` (PostgreSQL validates every new CHECK of one
   `ALTER TABLE` in a single table pass); `CREATE TRIGGER
   a_schedule_intake_series_admits_no_other_publication`.
8. **Live phase B — FKs into S5 tables**, by `ALTER TABLE <new table> ADD CONSTRAINT …
   FOREIGN KEY`: the 2 intake FKs, the 3 decision FKs into `schedule_series` /
   `schedule_publications`, `a_schedule_baseline_names_a_publication_of_its_series`,
   `a_schedule_scenario_names_a_series_of_its_project`,
   `a_schedule_scenario_starts_from_a_publication_of_its_series` (8 FKs; each takes `SHARE
   ROW EXCLUSIVE` on the referenced S5 table, held to commit; validation scans the empty new
   table).
9. **Live phase C — `record_links`** (production-live): the 6 restatements as **one**
   `ALTER TABLE knowledge.record_links DROP CONSTRAINT <n1>, ADD CONSTRAINT <n1> CHECK (…), …`
   statement (6 drop/add pairs, one validating pass; R9-F10), last, so `record_links` is
   locked only from here to commit. This varies the `_restate` precedent (one `ALTER TABLE`
   per CHECK) deliberately: the result in the catalog is identical and the `ACCESS
   EXCLUSIVE` window holds 1 scan instead of 6.

`tables.py` declares every FK on its table as usual (`use_alter=True` only for the circular
fork FK); the order above is the revision's, and a name-parity test
(`test_frozen_ddl_names_every_declared_constraint`) still holds.

#### 14.6.3 Live-table lock and runtime analysis

| Table | Live where | Statement | Lock (held to commit) | Scan | Who waits |
|---|---|---|---|---|---|
| `record_links` | production (`023f8f7eb499`) | 1 `ALTER TABLE` with 6 `DROP CONSTRAINT` + `ADD CONSTRAINT … CHECK` pairs | `ACCESS EXCLUSIVE` | 1 validating pass checking the 6 CHECKs (a widening cannot fail on an existing row) | every lineage read and write: `records.lineage*`, `records.associations.*`, `issues.*` close gate and timeline, the ChatLLM and remote lineage reads |
| `schedule_publications` | only after the S5 revisions are applied | `LOCK TABLE`, 1 `ALTER TABLE` with 2 restatements, `CREATE TRIGGER` | `ACCESS EXCLUSIVE` | 1 validating pass (it can fail only on a retired-role row, which step 7's refusal excludes first) | the schedule import, the schedule worker, the 6 schedule reads |
| `schedule_publications`, `schedule_series` | as above | 8 FKs from new (empty) tables | `SHARE ROW EXCLUSIVE` | none on the referenced table; each new table scanned (empty) | writers of those 2 tables (import, worker) |

`lock_timeout = '10s'` bounds each acquisition: a lock not obtained aborts the whole revision
with `55P03` and leaves the database at `621ef6786c64` (tested). No `statement_timeout` is set
(the migration engine is built with `statement_timeout_ms=None`). `NOT VALID` + `VALIDATE` is
not adopted: inside one revision transaction the `ADD` already holds `ACCESS EXCLUSIVE` to
commit, so it would save nothing and would leave `pg_get_constraintdef` differing from
`tables.py`. Runtime: the validating passes are linear in `record_links` and
`schedule_publications` row counts, which are operator-scale and unknown here (S6-2-U01; Q3
reports them).

**Scratch-cluster measurement (R9-F10; I9-A performs it, nothing real is touched).** On the
Homebrew `postgres@15` scratch cluster at `621ef6786c64`, I9-A seeds synthetic `record_links`
rows (the `tests/database/test_lineage_benchmark.py` harness shape: synthetic Principals and
identifiers, inserted after `SET LOCAL session_replication_role = replica` so no endpoint row is needed,
then `ANALYZE`) at 10^5 and at 10^6 rows, runs revision A's upgrade, and records for each size:
the wall time of the live phase C statement (from just before the `ALTER TABLE` to its return,
measured by `clock_timestamp()` around it in a measurement-only copy of the statement, not in
the revision), the wall time of the whole upgrade, and the table size (`pg_relation_size`).
Same for live phase A at 10^4 `schedule_publications` rows. The figures, the host (CPU,
PostgreSQL minor version) and the commands go into the executed-results subsection of section
14, and the runbook turns Q3's `reltuples` into an expected window by linear scaling, with the
go/no-go rule "the expected phase C time is well under the 10 s `lock_timeout` budget the
quiet window allows; otherwise stop and review". The measurement is a script under the test
module's helpers, run once by hand in the foreground; it is not a CI test.

#### 14.6.4 `downgrade()` in order

1. `SET LOCAL lock_timeout = '10s'`.
2. **Amended (FR9-F06):** `LOCK TABLE` the 11 plane tables `IN ACCESS EXCLUSIVE MODE`
   first, so no plane row can commit between the refusal and the drops; then the refusal
   `DO` block, `restrict_violation`, `'schedule scenarios rows exist; refusing to
   downgrade <rev>'`, when **any** of: a row in any of the 11 plane tables; a `record_links` row
   whose `from_family` or `to_family` is one of the 6 S6 families or whose `relation_type` is
   `concerns`, `delays` or `mitigates`; a `schedule_publications` row with `baseline_kind =
   'approved_update'` (each clause alone refuses; parametrized test).
3. `DROP TRIGGER` in reverse of upgrade step 6 and G10; `DROP FUNCTION knowledge.<name>()`
   G15…G1.
4. Drop `a_schedule_scenario_forks_a_version_of_its_series`; `DROP TABLE … RESTRICT` in
   reverse creation order (removes the 8 FKs into S5 tables with their tables).
5. Restore the 2 `schedule_publications` CHECKs to their BEFORE texts (one `ALTER TABLE`).
6. Restore the 6 `record_links` CHECKs to their BEFORE texts (one `ALTER TABLE`) — last.

`tests/schema/test_every_revision_denotes_one_schema.py` (chain-agnostic) then proves the
downgraded catalog equals a fresh build at `621ef6786c64`.

#### 14.6.5 Grants

Grant-free: the revision executes no `GRANT`/`REVOKE`, does not import or call
`src/my_pa/infrastructure/database/mcp_object_grants.py`, and references no role; tables (and
the refusal table's identity sequence) are owned by the migrating role exactly as every
S1–S5 table. Tested statically and in the catalog (`relacl IS NULL` for the 11 tables and the
sequence; `has_table_privilege` false for `PUBLIC`, `my_pa_mcp_ro`, `my_pa_mcp_rw`; `relacl`
of `record_links`, `schedule_publications` and `schedule_series` byte-identical before
upgrade, after upgrade and after downgrade).

### 14.7 Domain and vocabulary changes

#### 14.7.1 Enum lockstep (`src/my_pa/domain/schedule/model.py`)

`SchedulePublicationRole` = `UPDATE`, `BASELINE` (loses `REFERENCE`). `ScheduleBaselineKind` =
`CONTRACT`, `APPROVED_UPDATE` (loses `WORKING`), value-equal to S6-1 `BaselineType` (FAST
test). Every lockstep test and fixture that names `reference` or `working` moves (14.10).

#### 14.7.2 `ScheduleImportRequest` and `ScheduleImportApproval`

New frozen record `ScheduleImportApproval(approval_reference: str, effective_from: date,
reason: str)` (`approval_reference` 1..500 and `reason` 1..2,000 characters after
`normalize_display_text`; fixed `ValueError` messages). `ScheduleImportRequest` gains, all
defaulted so every S5 call site is unchanged: `series_auto: bool = False`,
`series_name_if_new: ScheduleSeriesName | None = None`, `approval: ScheduleImportApproval |
None = None`, `match_decision_id: str | None = None` (`ssmd`). Invariants added to
`__post_init__`:

| Rule | Refusal |
|---|---|
| exactly one of `series_id`, `series_name`, `series_auto` | `ValueError` |
| `series_name_if_new` only with `series_auto` | `ValueError` |
| `series_auto` ⇒ role `UPDATE`, no `baseline_kind`, no `supersedes_publication_id`, no `approval`, no `match_decision_id` | `ValueError` |
| `approval` set ⇔ role `BASELINE` | `ValueError` |
| `match_decision_id` ⇒ `series_id` or `series_name` set (the matched or the created Series), role `UPDATE`, no `supersedes_publication_id`, no `approval` | `ValueError` |

#### 14.7.3 Import digest v2 and intake naming

`schedule_import_request_digest` keeps `cpm-schedule-import-v1` byte-for-byte for a request
with no S6 field (`series_auto` false and the 3 others `None`). Otherwise it digests
`sha256(b"cpm-schedule-import-v2\n" + canonical_json_bytes(body))` with `body` = the v1 body
whose `request` adds exactly `series_auto` (bool), `series_name_if_new_key`,
`approval_reference`, `effective_from` (ISO date), `reason`, `match_decision_id` (absent =
`null`). Golden vectors: one v1 request unchanged, one auto, one approval, one second
admission.

New pure module `src/my_pa/domain/schedule/plane.py` (bound by the `domain/schedule` import
allowlist: stdlib, `my_pa.domain.schedule`, `my_pa.domain.common.identifiers`):

| Symbol | Value |
|---|---|
| `INTAKE_SERIES_PREFIX` | `"Schedule intake "` |
| `intake_series_name(request_digest) -> ScheduleSeriesName` | `normalize_series_name(INTAKE_SERIES_PREFIX + request_digest[:12])` |
| `is_intake_name_key(key) -> bool` | `key.startswith("schedule intake ")` (S6-3's command refusal uses it) |
| `second_admission_key(decision_id) -> str` | `hashlib.sha256(b"series-match-v1\n" + decision_id.encode("ascii")).hexdigest()` (64 hex; matches the S5 key pattern) |
| `PLANE_CLIENT_WRITE_CAPABILITIES`, `PLANE_OPERATOR_WRITE_CAPABILITIES`, `PLANE_WRITE_CAPABILITIES` | the 6, 4 and 10 names of section 6.1 as strings (S6-3 pins them equal to its `Capability` members) |
| `PlaneResultKind` | `SCENARIO`, `VERSION`, `CPM_RUN`, `OUTPUT`, `BASELINE_EVENT`, `GOVERNING_EVENT`; `RESULT_KIND_BY_CAPABILITY` |
| `MatchAdmissionSkip` | `PLANE_DISABLED = "plane_disabled"` |
| `MATCH_INTEGRITY_REFUSAL` | `"integrity_violation"` |
| `PlaneProvenance` | frozen record `authority_class`, `decision_channel`, `asserting_client_id`, `acceptance_basis`, `user_directed_claim`, validating the section 14.3 creator rule (frozen literal sets; a FAST test pins them equal to the lineage vocabulary sets) |
| `writer_bucket(decision_channel, asserting_client_id) -> str \| None` | `None` for an attested channel (`local_cli`, `local_web`); otherwise `decision_channel + "\x1f" + (asserting_client_id or "")` — the string S6-1 `ProposeRequest.writer_bucket` / `BaselineEvent.writer_bucket` carry (R9-F13) |
| `MAX_CPM_RESULT_BYTES` | 67,108,864 (section 3.11) |

#### 14.7.4 Lineage storage vocabulary (`src/my_pa/domain/lineage/vocabulary.py`; amendment S6-2-D01)

| Symbol (new, string-keyed) | Value |
|---|---|
| `SCHEDULE_LINEAGE_FAMILY_ID_KINDS` | `schedule_publication → SCHEDULE_PUBLICATION`, `schedule_activity → SCHEDULE_ACTIVITY`, `schedule_baseline → SCHEDULE_BASELINE`, `scenario → SCHEDULE_SCENARIO`, `scenario_version → SCHEDULE_SCENARIO_VERSION`, `scenario_output → SCHEDULE_SCENARIO_OUTPUT` |
| `STORED_RECORD_FAMILY_ID_KINDS` | `{family.value: kind for RECORD_FAMILY_ID_KINDS} ∪ SCHEDULE_LINEAGE_FAMILY_ID_KINDS` (13) |
| `SCHEDULE_LINEAGE_RELATIONS` | `concerns`, `delays`, `mitigates` |
| `STORED_RELATION_MATRIX` | `RELATION_MATRIX` with string tokens, then: `discusses` to-families + `schedule_publication`, `schedule_activity`, `schedule_baseline`, `scenario`, `scenario_output`; `originated_from` from-families + `scenario_version`, `schedule_baseline`; new `concerns` (semantic; `scenario`, `scenario_version`, `scenario_output` → `situation`, `constraint`, `task`, `commitment`, `schedule_activity`, `schedule_baseline`), `delays` (semantic; `constraint`, `situation` → `schedule_activity`), `mitigates` (semantic; `task`, `commitment`, `scenario_version` → `constraint`, `situation`) — section 5.2 exactly |

`tables.py` builds the 6 `record_links` CHECKs from these (`_one_of` over
`frozenset(STORED_RECORD_FAMILY_ID_KINDS)`, `_family_identifier` and `_relation_matrix`
iterating the stored maps sorted by token). `RecordFamily`, `RelationType`, `RELATION_MATRIX`,
`RECORD_FAMILY_ID_KINDS`, `LINEAGE_FAMILY_READS` and `LINEAGE_READ_GENERATION` are **unchanged**
in S6-2. FAST `test_storage_vocabulary_is_the_public_vocabulary_plus_the_pending_s6_additions`
pins: stored ⊇ public, stored − public = exactly the S6 additions above (S6-3 replaces it by
equality when it widens the public enums and bumps the generation to 2).

### 14.8 Persistence design

#### 14.8.1 Modules and ports

| New module | Holds |
|---|---|
| `src/my_pa/infrastructure/persistence/schedule_scenarios.py` | `SqlScenarioRepository` (scenarios, versions, CPM runs, outputs, ledger, refusals, budget reads, baselines, governing, intake finalization), `SqlAlchemyScenarioUnitOfWork`, the advisory-lock helpers of 14.8.4 |
| `src/my_pa/infrastructure/persistence/schedule_plane_codec.py` | `compress_canonical`, `decompress_bounded`, `verified_document` (no SQL) |
| `src/my_pa/infrastructure/persistence/schedule_cpm_lease.py` | the per-Principal compute lease and `compute_and_store_cpm_run` (14.8.4) |

Ports in `src/my_pa/contracts/ports.py` after the Schedule ports. Records are frozen slots
dataclasses; errors carry a fixed code and no content.

```python
class ScenarioIntegrityError(Exception):  # a stored digest, size or decode check failed
    code: str  # "content_digest", "content_decode", "result_digest", ...


class CpmComputeBusyError(
    Exception
): ...  # the Principal's compute lease is held -> conflict(CPM_RUN)


class ScheduleBaselineRaceError(Exception):  # a section 12.1 backstop refused a lost race
    code: str  # the constraint or trigger name


# R9-F08: every non-success after `reserve_request` is raised, so the UoW rolls back the
# reservation and G8 never turns a refusal into `internal_error`.
class ScenarioHeadMovedError(Exception):  # CAS lost -> conflict(EXPECTED_VERSION)
    head_version_no: int


class BaselineWriteRefusedError(Exception):  # decide_baseline_write refused
    refusal: BaselineRefusal


class PlaneSubjectAbsentError(
    Exception
): ...  # a named subject is absent or another Principal's -> not_found


class PlaneReservationOutcome(StrEnum):
    RESERVED = "reserved"
    REPLAYED = "replayed"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class PlaneReservation:
    outcome: PlaneReservationOutcome
    result_kind: PlaneResultKind | None = None  # set on REPLAYED
    result_id: str | None = None
    result_created: bool | None = None


@dataclass(frozen=True, slots=True)
class PlaneWriteCounts:  # completed client-channel ledger rows (replays never add a row)
    bucket_hour: int
    bucket_day: int
    principal_day: int


@dataclass(frozen=True, slots=True)
class PlaneByteCounts:  # canonical bytes: content + results + outputs (section 2.10)
    principal_total: int
    principal_day: int
    bucket_day: int


class ScenarioRepository(ABC):
    # prologue of every plane write transaction
    def lock_principal(self, principal_id: str) -> None: ...
    def reserve_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        request_digest: str,
        writer: PlaneProvenance,
    ) -> PlaneReservation: ...
    def complete_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        result_id: str,
        *,
        created: bool,
        stored_bytes: int,
    ) -> None: ...
    # bound reads (S6-3 applies the limits)
    def client_write_counts(
        self, principal_id: str, writer: PlaneProvenance, at: datetime
    ) -> PlaneWriteCounts: ...
    def plane_byte_counts(
        self, principal_id: str, writer: PlaneProvenance, at: datetime
    ) -> PlaneByteCounts: ...
    def scenario_and_version_counts(self, principal_id: str) -> tuple[int, int]: ...
    def output_count(self, principal_id: str, version_id: str) -> int: ...
    def cpm_units_since(self, principal_id: str, since: datetime) -> int: ...
    def refusal_count(self, principal_id: str, writer: PlaneProvenance, since: datetime) -> int: ...
    def record_refusal(
        self, principal_id: str, writer: PlaneProvenance, capability: str, error_code: str
    ) -> None: ...
    # scenarios and versions
    def snapshot_source(
        self, principal_id: str, publication_id: str
    ) -> ScenarioSnapshotSource | None: ...
    def insert_scenario(
        self,
        principal_id: str,
        scenario: NewScenario,
        first_version: NewScenarioVersion,
        writer: PlaneProvenance,
    ) -> StoredScenarioVersion: ...
    def fork_scenario(
        self,
        principal_id: str,
        scenario: NewScenario,
        source_version_id: str,
        label: VersionLabel,
        note: str | None,
        writer: PlaneProvenance,
    ) -> StoredScenarioVersion: ...  # raises PlaneSubjectAbsentError
    def head_version(self, principal_id: str, scenario_id: str) -> StoredScenarioVersion | None: ...
    def append_version(
        self,
        principal_id: str,
        scenario_id: str,
        expected_head_version_no: int,
        version: NewScenarioVersion,
        writer: PlaneProvenance,
    ) -> StoredScenarioVersion: ...  # raises ScenarioHeadMovedError
    def get_scenario(self, principal_id: str, scenario_id: str) -> StoredScenario | None: ...
    def get_version(self, principal_id: str, version_id: str) -> StoredScenarioVersion | None: ...
    def load_content(
        self, principal_id: str, version_id: str
    ) -> VerifiedScenarioContent | None: ...
    def load_change_set(self, principal_id: str, version_id: str) -> VerifiedDocument | None: ...
    # CPM runs
    def get_cpm_run(
        self, principal_id: str, version_id: str, engine_version: str
    ) -> StoredCpmRun | None: ...
    def insert_cpm_run(
        self, principal_id: str, run: NewCpmRun, writer: PlaneProvenance
    ) -> tuple[StoredCpmRun, bool]: ...
    def load_cpm_result(self, principal_id: str, cpm_run_id: str) -> VerifiedDocument | None: ...
    # outputs
    def insert_output(
        self, principal_id: str, output: NewScenarioOutput, writer: PlaneProvenance
    ) -> StoredScenarioOutput: ...
    def get_output(self, principal_id: str, output_id: str) -> StoredScenarioOutput | None: ...
    def load_output(self, principal_id: str, output_id: str) -> VerifiedDocument | None: ...
    # baselines and governing (each takes the Project lock itself)
    def write_baseline(
        self,
        principal_id: str,
        request: BaselineRequest,
        *,
        reason: str,
        approval: ScheduleImportApproval | None,
        writer: PlaneProvenance,
        project_id: str | None = None,  # required for SetGoverningRequest
    ) -> BaselineWritten: ...  # raises BaselineWriteRefusedError, PlaneSubjectAbsentError
    def baseline_chain(self, principal_id: str, project_id: str) -> BaselineChain: ...
    def governing_as_of(
        self, principal_id: str, project_id: str, as_of: datetime | None
    ) -> str | None: ...
    # worker hook (inside the S5 finalization transaction)
    def finalize_intake(
        self, principal_id: str, publication_id: str, *, plane_effective: bool
    ) -> SeriesMatchRecord | SeriesMatchUndecided | None: ...


class ScenarioUnitOfWork(ABC):
    def __enter__(self) -> ScenarioUnitOfWork: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
    @property
    def scenarios(self) -> ScenarioRepository: ...
    @property
    def schedules(self) -> ScheduleRepository: ...  # the S5 repository on the same connection
```

`ScenarioUnitOfWork` is not on `UnitOfWork`, has no `record_events` or `projects` member and
is not composed into `ApplicationService` or the gateway in S6-2 (S6-3 composes the plane
factory). Record fields (`NewScenario`, `NewScenarioVersion`, `StoredScenario`,
`StoredScenarioVersion`, `NewCpmRun`, `StoredCpmRun`,
`NewScenarioOutput`, `StoredScenarioOutput`, `ScenarioSnapshotSource`,
`VerifiedScenarioContent(content, canonical, size)`, `VerifiedDocument(document, canonical)`,
`BaselineWritten(baseline_id, event_id | governing_event_id, label, seq)`,
`BaselineChain(events, governing)`, `SeriesMatchRecord`, `SeriesMatchUndecided(code)`) are the section 14.3 columns, typed
with the S6-1 enums; I9-B names any helper record not listed here and reports it.
`SqlAlchemyScenarioUnitOfWork(engine)` is the `SqlAlchemyScheduleUnitOfWork` shape; both
properties raise `RuntimeError` outside a transaction. Isolation: the engine default, READ
COMMITTED (RR2-F03).

#### 14.8.2 Write-transaction prologue, idempotency and CAS

Every plane write transaction issues, first: `lock_principal` (14.8.4 key P), then
`reserve_request`: `INSERT … ON CONFLICT (principal_id, capability, idempotency_key) DO
NOTHING RETURNING`; inserted ⇒ `RESERVED`; else the existing row (it is committed and
completed, G8): equal digest ⇒ `REPLAYED` with its result; other digest ⇒ `CONFLICT`
(`conflict(IDEMPOTENCY_KEY)`). The key is client-bound because the stamped remote key is
(section 6.7); the ledger stores the bucket. Reads of counts and heads follow in statements
**after** the lock (RR2-F03). The write ends with `complete_request` (G7 permits only that
transition; G8 refuses a commit that leaves it reserved). A refusal raised after
`reserve_request` rolls the whole transaction back, so no reservation survives.

| Write | Inside the one write transaction, after the prologue |
|---|---|
| Scenario from a publication or Baseline | read is done before (14.8.3); with `from_baseline_id`, take J and re-read that the Baseline is effective (approved, not revoked, publication `complete`/`partial`). Not effective ⇒ raise `BaselineWriteRefusedError` (RR1-F04; S6-2-D20): revoked or never approved ⇒ `CONFLICT_BASELINE_ID` (`conflict(BASELINE_ID)`), publication not `complete`/`partial` ⇒ `CONFLICT_STATUS` (`conflict(STATUS)`), section 12.4/7; absent or another Principal's ⇒ `PlaneSubjectAbsentError` (`not_found`). Otherwise insert the Scenario and version 1 (snapshot columns set); G3, G5, G4 at commit |
| Scenario from a version (fork) | `INSERT … SELECT` copying `content_zlib`, `content_sha256`, `content_size_bytes`, the 3 counts and `distribution_spec_sha256` from the source version (partitioned), so the copy is byte-for-byte without decompression; G5 re-checks; source absent ⇒ raise `PlaneSubjectAbsentError`. The copy is stored again physically, so its `content_size_bytes` counts as new stored bytes toward the 2 GiB, 256 MiB and 128 MiB quotas (`stored_bytes` = `content_size_bytes`; S6-U08, R9-F13) |
| Version append (CAS) | `head_version` (max `version_no`) read after the lock; `head ≠ expected_head_version_no` ⇒ raise `ScenarioHeadMovedError(head_version_no)` (`conflict(EXPECTED_VERSION)`; the transaction rolls back, R9-F08); else insert `version_no = expected + 1`, `parent_version_id = head`; the UNIQUE and G5 are the backstop when the lock is absent |
| CPM run | 14.8.4 |
| Output | `output_count < 100` is S6-3's limit read here; insert; G6 |
| Baseline / governing | `write_baseline` (14.8.5) |

#### 14.8.3 Content storage, verification and bounded decompression

- **Compute outside the write transaction.** Snapshot (`snapshot_from_publication`) and
  change-set application (`apply_change_set`) run on data read in a short read transaction
  (`snapshot_source` reads the eligible, non-intake publication and its accepted run's
  `activity`/`milestone` rows — terminal and immutable, so a stale read is impossible;
  for an append, the read transaction reads the head and, when `head ≠
  expected_head_version_no`, raises `ScenarioHeadMovedError` **before computing**; otherwise
  `load_content` reads exactly the version with `version_no = expected_head_version_no`, which
  is the parent the write re-checks under P (R9-F13)), then the canonical bytes are compressed outside any
  transaction; the write transaction re-validates only what can change (CAS head, Baseline
  effectiveness under the Project lock).
- **Compression:** `zlib.compress(canonical, 6)`; the compressed bytes need not be
  deterministic (digests are over canonical bytes).
- **`decompress_bounded(blob, limit)`:** `d = zlib.decompressobj()`; `out = d.decompress(blob,
  limit + 1)`; refuse (`ScenarioIntegrityError("decompress_bound")`) if `len(out) > limit`,
  `d.unconsumed_tail`, `d.unused_data` or `not d.eof`. Limits: content 33,554,432; change set
  4,194,304; result 67,108,864; output 1,048,576 — and never more than the row's stored
  `*_size_bytes`, which `out` must equal exactly.
- **Verify on read:** `sha256(<schema>\n + out)` equals the stored digest (else
  `ScenarioIntegrityError("<kind>_digest")` → `internal_error`, section 8.2); content is then
  decoded with S6-1 `content_from_object(json.loads(out))` and must pass `content_problem` (else
  `content_decode`). `run_cpm` is called only on content returned by `load_content` (FR8-F07,
  section 9.1.1).

#### 14.8.4 Advisory locks and the CPM compute lease

| Lock | Form | Key | Held by |
|---|---|---|---|
| P — Principal plane lock | `pg_advisory_xact_lock(int4, int4)` | namespace `SCHEDULE_PLANE_ADVISORY_NAMESPACE = 0x53534350` ("SSCP"), key `hashtext('principal:' \|\| principal_id)` | every plane write transaction (prologue) |
| J — Project lock | same form | namespace `0x53534350`, key `hashtext('project:' \|\| principal_id \|\| ':' \|\| project_id)` | baseline and governing writes, Scenario-from-Baseline, the import-time approval, the intake finalization hook (section 12.1, R8-F15) |
| C — compute lease | `pg_try_advisory_lock(int4, int4)` (session) | namespace `SCHEDULE_CPM_ADVISORY_NAMESPACE = 0x5343504D` ("SCPM"), key `hashtext('cpm:' \|\| principal_id)` | the dedicated lease connection, during one compute |

Collision avoidance: both namespaces differ from `LINEAGE_ADVISORY_NAMESPACE` (`0x4C494E45`)
and live in the two-int key space, which no single-bigint key in `src/` can reach. C has its
own namespace so a 32-bit `hashtext` collision can never make a held compute lease block a P
or J lock of the same request (which would wait on its own session's lease, a hang PostgreSQL
cannot detect). A `hashtext` collision between 2 P or J keys only serializes 2 unrelated
writers; P and J colliding in one transaction is re-entrant; a collision between one writer's
P and another's J can at worst produce a `deadlock_detected` (`40P01`), which PostgreSQL
detects and which is a transient refusal (`internal_error`, retried), never a silent hang. A
`hashtext('cpm:' …)` collision between 2 Principals makes one of them answer a spurious
`conflict(CPM_RUN)` while the other computes; accepted (S6-2-U11).

**Lock order (R9-F11).** There is no single global order; the partial order and the argument
that no cycle exists are:

| Holder | Takes, in order |
|---|---|
| plane client write (scenario, version, run, output) | P → FK `KEY SHARE` on referenced plane rows and on terminal S5 rows (origin publication, Series) |
| baseline / governing write, Scenario-from-Baseline | P → J → FK `KEY SHARE` on the Baseline's terminal publication and Series; no other row lock |
| S5 import with approval | J → (role `baseline` has no auto form) the non-intake predecessor's `FOR UPDATE` when superseding → FK `KEY SHARE` on its Series |
| S5 import without approval, second admission | no P or J of its own; row and FK locks as today |
| worker finalization (H8, `fail`) | job row (`hold_lease`, `FOR UPDATE`) → its publication `FOR UPDATE` → (intake only) J → the second admission's inserts (FK `KEY SHARE` on the target Series) |
| CPM compute (14.8.4) | C: a session `pg_try_advisory_lock` on the dedicated lease connection, which **never waits** (a miss answers busy) and is held across steps 3–5; meanwhile steps 3 and 5 take P and row locks on other connections as a plane client write does (RR1-F05) |

No path takes P after J. Every J holder other than the hook touches no intake publication,
intake job row or intake Series (G3, G9–G12), and the hook's row locks are exactly those intake
rows, so a J holder never waits on a lock the hook holds while the hook waits on J. The
finalizing worker updates no `schedule_series` row, so its FK `KEY SHARE` locks conflict with no
J holder's. Baseline writers read eligibility from immutable terminal status and take no row
lock beyond FK `KEY SHARE` on terminal rows, which no worker updates.

`compute_and_store_cpm_run(engine, principal_id, version_id, *, capability_key, writer,
admit_compute)` (section 3.11, R8 ruling R-5, RR1-F10):

1. Read transaction: ledger probe by key (replay or conflict ⇒ return); natural-key probe
   `get_cpm_run(…, ENGINE_VERSION)` (found ⇒ go to step 5 with that run, computing nothing);
   `load_content` (verified).
2. Lease: a module-level `dict[str, threading.Lock]` (guarded) — non-blocking acquire, lost ⇒
   `CpmComputeBusyError`; then a lease connection opened **outside the application pool**
   (R9-F12). `schedule_cpm_lease.py` owns a small factory `lease_engine(url: URL) -> Engine`
   that takes the parsed `URL` object (never `str(engine.url)`, which masks the password) and
   builds `create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT",
   connect_args={})` with its connect arguments stated explicitly — no `statement_timeout`,
   because the lease connection runs only `pg_try_advisory_lock`/`pg_advisory_unlock` — cached
   per `URL` in the process and `dispose()`d at shutdown (RR1-F03). The cache is safe under
   concurrent first use: it is created and read under a module lock (the process-lock dict's
   guard or a lock of its own), and test fixtures that create per-test scratch databases
   dispose the cached lease engines at teardown, so neither engines nor connections leak
   across tests (RR2-F02). `create_database_engine`
   is not reused: it has no pool-class parameter and its connect arguments cannot be read back
   from an `Engine`. A held lease thus never consumes one of the request pool's connections
   while steps 3 and 5 take theirs. Lease connections sit **outside** the gateway's pool of 5
   (`src/my_pa/bootstrap/gateway.py`): at most 1 extra connection per concurrently computing
   Principal per process, to be counted against `max_connections` (runbook, S6-2-U12);
   `SELECT pg_try_advisory_lock(C)`; false ⇒ release the process lock,
   `connection.invalidate()`, `CpmComputeBusyError`. `run_cpm` is injected through a
   keyword (`compute=run_cpm`) so tests block it on a barrier.
3. `admit_compute(units)` (S6-3's activity-units-per-hour check, given
   `cpm_units_since` read in a short read transaction while the lease is held).
4. `run_cpm(content)` outside any transaction, with no database lock other than C;
   `result_document`, canonical bytes, `result_sha256`, bound check (> 64 MiB ⇒
   `ScenarioIntegrityError("result_bound")`, section 3.11), compress.
5. Write transaction: prologue (P, `reserve_request`: a racing replay or conflict wins and the
   computed result is discarded); `insert_cpm_run` = `INSERT … ON CONFLICT (principal_id,
   version_id, engine_version) DO NOTHING RETURNING`; no row ⇒ read the existing run
   (`created = false`); `complete_request`.
6. `finally` (always, whatever happened): `SELECT pg_advisory_unlock(C)` on the dedicated
   connection (an error or a `false` answer is swallowed: the lease was already lost), then
   `connection.invalidate()` and `close()` — the connection never belongs to the request pool
   and is never reused, so no pooled connection can carry a session lock — then release the
   process lock.

Lease loss (the dedicated connection dies mid-compute): PostgreSQL releases C; the result is
still a deterministic function of `(content, engine_version)` and the insert is idempotent by
the natural key, so the only effect is that a second compute may overlap — a bound breach, not
an integrity one (S6-2-U04).

#### 14.8.5 Baseline and governing writes

`write_baseline(principal_id, request, *, reason, approval, writer)`, inside a plane write
transaction (prologue done):

1. Resolve the Project from the immutable subject, partitioned: the publication
   (`ProposeRequest`, direct `ApproveRequest`) or the Baseline row (the rest); `SetGoverningRequest`
   takes the `project_id` keyword (S6-3's command field), checked owned; absent ⇒ `None`
   (`not_found`).
2. Take J.
3. Statements after the lock: read the Project's whole baseline chain and governing chain
   (ordered by `seq`) as S6-1 `BaselineEvent` (with `writer_bucket` derived from the stored
   channel and client) and `GoverningEvent`; read the eligible publication ids among those the
   chain and the request name (stored `status IN ('complete', 'partial')` and not intake).
4. `decide_baseline_write(events, governing, request, eligible_publication_ids=…)` (S6-1; it
   carries the pending caps, the adoption rule of RR1-F05 and the transitions). A refusal is
   **raised** as `BaselineWriteRefusedError(refusal)` so the transaction rolls back with the
   reservation (R9-F08); S6-3 maps the carried `BaselineRefusal`. An absent subject (step 1)
   raises `PlaneSubjectAbsentError` (`not_found`).
5. On a plan: a new Baseline row when `plan.baseline_id is None` (propose, or a direct approval
   with no pending proposal; the row's `type` is the request's); the event with `seq =
   len(events) + 1`, `previous_event_id` = the head, `recorded_at = clock_timestamp()`,
   `label`/`proposal_ordinal` from the plan, `approved_at_import = false`; for
   `set_governing`, a governing event likewise. G14/G15 re-verify.

Lost races on a backstop (`unique_violation` on any section 12.1 index, or G14/G15
`restrict_violation`) surface as `ScheduleBaselineRaceError(code)` with the constraint name, and
S6-3 maps them to `conflict(BASELINE_ID)` or, on the governing chain, `conflict(GOVERNING)`
(RR2-F04). A G14 (b)/G15 (b) `check_violation` (a wall-clock regression between 2 writes) is
not a race: it maps to `internal_error` and the client retries (R9-F13). `governing_as_of(project, as_of)` = the governing event with the maximum `seq` among
those with `recorded_at <= as_of` (ties by `seq`), never `effective_from` (section 9.1.1, P43
obligation).

**Import-time approval (section 12.3, RR2-F04).** `SqlScheduleRepository.admit_publication`
gains the keyword `operator_channel: str | None = None`, required (an attested channel) iff
`request.approval` is set. After step (1) (replay by key) and before step (2), it takes J on
`(principal_id, request.project_id)`. After the publication insert and `enqueue_job`, in the
same transaction, it calls the plane helper (`schedule_scenarios.py`,
`record_import_approval(connection, …)`, the only plane function the S5 module imports) which
reads the chain after the lock, decides `ApproveRequest(type = request.baseline_kind,
publication_id = new, effective_from, at_import=True)`, inserts the Baseline row and the
`approve` event (`approved_at_import = true`, label `BL-<n>`, provenance `local_operator` /
`operator_channel` / `user_confirmed`). A refusal there is impossible by construction (an
at-import approval of a publication just admitted always yields a plan: it cannot be approved
already, eligibility is skipped at import, and it never carries `supersedes_baseline_id`:
section 12.3 defines the import-time fields as `baseline_type`, `approval_reference`,
`effective_from` and `reason` only. Should S6-3 ever add a supersedes field there, the decision
must be made under J inside the admission (validating it outside J would race a concurrent
`revoke`), with a typed refusal that rolls the admission back; RR2-F02); any other refusal or backstop error there is an integrity
error (`ScheduleIntegrityError("import_approval")`), never mapped to an admission refusal
(RR1-F04). Replay by source version for role `baseline` also
compares the stored `approve` event's `type`, `approval_reference`, `effective_from` and
`reason` (any difference ⇒ `SOURCE_VERSION_CONFLICT`).

#### 14.8.6 Intake admission (section 11.2 steps 1–2)

`admit_publication` with `series_auto`:

- step (4): the Series is `intake_series_name(request_digest)` looked up by `name_key`; absent
  ⇒ created in step (7) as now;
- after the publication insert: insert the intake row (`series_name_if_new` and its key from
  the request); G9 verifies;
- a `series_id` (or a `series_name` whose Series) naming an intake Series is refused
  `SERIES_NOT_FOUND` (hidden as absent; no new refusal member, R2-11); G10 is the backstop;
- the caller-name prefix refusal (`invalid_request(SERIES_NAME)`) is the import command's,
  owned by S6-3 (section 11.4); the repository relies on the intake row, never the name, to
  decide intake-ness.

The auto form and approvals are reachable in S6-2 only from tests: no command carries them
until S6-3.

#### 14.8.7 Worker finalization hook (section 11.2 steps 3–7)

`process_schedule_publication(engine, job, owner, *, scenario_plane_effective: bool = False)`.
H8 (`finalize_publication`) and `_Job.fail` (`fail_publication`) run in a
`SqlAlchemyScenarioUnitOfWork` transaction and call, **after** the terminal update,
`uow.scenarios.finalize_intake(principal, publication_id, plane_effective=…)`, which returns
`SeriesMatchRecord | SeriesMatchUndecided | None`:

1. Not an intake publication (no intake row) ⇒ return `None` with no lock and no further read.
2. **Outer savepoint** (R9-F01): `outer = connection.begin_nested()`. Steps 3–10 run inside it.
   Both savepoints are used as `begin_nested()` context managers, so rolling back the outer
   one also closes an open inner one; if the rollback to the outer savepoint itself raises
   (for example a broken connection), that error propagates as transient (RR2-F02).
3. J on `(principal_id, project_id)`; a decision for this intake publication already exists ⇒
   return it (UNIQUE backstop; re-entry cannot normally occur because the terminal update
   commits with the decision).
4. Stored status not `complete`/`partial` ⇒ decision `not_eligible`.
5. **Candidate bound on the raw count** (R9-F07): read up to 51 non-intake Series of the
   Project ordered by `(created_at, series_id)` (identifiers and `created_at` only). 51 rows ⇒
   the decision is `ambiguous`/`candidate_bound` with an empty `candidates` array and the
   incoming ID count, decided **before** any eligibility skip or activity-row read
   (`match_series` is not called, because skipping ineligible Series first would let it score
   a truncated set; section 11.2 step 3 bounds the Project's non-intake Series).
6. Per Series (≤ 50): its publications as S6-1 `CurrencyPublication` with their effective
   status (only a terminal `complete`/`partial` one is eligible, and for it stored and
   effective status are equal), the effective Baseline publications of the Project (approved,
   not revoked, eligible), then `current_standard_update`, else the newest eligible by
   `PublicationOrderKey`; Series with neither are skipped. Its ID → normalized name map from
   the accepted run's `activity`/`milestone` rows (≤ 25,000 rows each), and the Series'
   publication holding the intake's `source_version_id`, if any.
7. `NewSeriesName`: `ABSENT` without `series_name_if_new`, else `TAKEN`/`FREE` by a
   `name_key` read under J (I8's resolution: taken ⇒ `ambiguous`/`name_conflict`).
8. `match_series(incoming, candidates, new_series_name=…)` (S6-1).
9. Outcome `matched`/`created` and `plane_effective` false ⇒ record with `admission_skipped =
   'plane_disabled'`, no admission (S6-O15). Otherwise mint the decision id, open an **inner
   savepoint**, call `uow.schedules.admit_publication` with `ScheduleImportRequest(project,
   series_id = target` (matched) or `series_name = series_name_if_new` (created), the intake's
   enrollment, object and version, role `update`, `expected_data_date` = the intake
   publication's stored `expected_data_date`, `idempotency_key =
   second_admission_key(decision_id)`, `match_decision_id = decision_id)`:
   - success for `matched` ⇒ release the inner savepoint; `resulting_publication_id` = the
     admitted (or replayed) publication, `target_series_id` = its Series;
   - success for `created` **requires `admission.series_created is True`** (R9-F02): the S5
     explicit import takes no J, so a Series of that name may have been committed between the
     `FREE` read and the admission, and `_find_series` / `_create_series` would then return
     that existing, never-scored Series. Otherwise roll back to the inner savepoint and record
     `ambiguous`/`name_conflict` (no target, no resulting publication) — I8's taken-name
     resolution, so no identity is shared (R8-F11);
   - `ScheduleAdmissionRejectedError` ⇒ roll back to the inner savepoint, outcome
     `admission_refused`, `admission_refusal = reason.value`; a `sqlalchemy.exc.IntegrityError`
     (SQLSTATE class `23`) inside it ⇒ the same with `integrity_violation`.
10. Insert the decision (outcome, reason, `threshold_version`, `incoming_id_count`, the ranked
    candidates as a JSON array of `{series_id, publication_id, data_date, score,
    data_date_coherent, name_agreement_permille, title_equal}` in matcher order); release the
    outer savepoint.

**Failure semantics (R9-F01, RR1-F01; R8-F12 stands unamended).** The classification is
by **transience**, not by a list of defects. Only these propagate out of steps 3–10, as a
transient attempt failure (the whole finalization rolls back and the attempt bound applies):
`sqlalchemy.exc.OperationalError` and `sqlalchemy.exc.InterfaceError` (with psycopg these carry
`40001`, `40P01`, `55P03`, `57014`, the `08` connection class and the `53` resource class);
`ScheduleLeaseLostError` (should any hook path ever hold the lease); and any `BaseException`
that is not an `Exception` (`KeyboardInterrupt`, `SystemExit`, cancellation). **Every other
`Exception`** raised in steps 3–10 — among them `sqlalchemy.exc.IntegrityError`, `DataError`
(class `22`), `ProgrammingError` (class `42`) and `InternalError` (a plpgsql `RAISE` with the
default `P0001`), `ScenarioIntegrityError`, `ScheduleIntegrityError`, and Python `ValueError`
(the section 14.7.2 request invariants, the admission's digest check, S6-1 record
constructors fed stored data), `TypeError` and `KeyError` (building the candidates JSON) —
rolls back to the **outer** savepoint and returns `SeriesMatchUndecided(code)` (the exception
class name, or the constraint name when the driver reports one); the finalization then
commits with the terminal status and **no decision**, so an evidence defect never fails a
parsed publication. Recording *why* durably is not feasible in S6-2: the decision row is what
failed, the closed outcome set (R8-F14) has no "undecided" member, and the worker may not log
(`test_new_worker_modules_neither_log_nor_print`); the returned code is discarded by the S6-2
worker and S6-3 reads present an intake publication with no decision as **undecided**
(S6-2-U10). An intake publication whose job exhausts its attempts or is abandoned never
reaches H8 or `_Job.fail`, so it also has no decision (S6-2-U09); in both cases the operator
resolves it by an explicit import.

**"Plane off" in S6-2** (decided): the switch is S6-3's, so S6-2 takes the effective-plane bit
as the keyword above, **default `False`**, and `apps/worker.py` passes nothing (a FAST scope
test pins both). Justification: off is the S6-O15 behaviour (evidence only, no admission), and
in S6-2 no intake publication can exist outside tests because the auto form has no command;
S6-3 passes `settings.schedule_enabled and settings.schedule_scenarios_enabled` from the worker
composition.

#### 14.8.8 Bounds: database CHECK, repository read or S6-3 policy

| Bound (section) | Where |
|---|---|
| version_no 1..500, sizes (32 MiB, 4 MiB and 1..5,000 ops, 64 MiB, 1 MiB), iterations, counts, closed sets, reason/reference lengths, label shape, ≤ 50 candidates | DB CHECK (14.3) |
| linear chain, byte-copy fork, snapshot-iff-publication, origin eligibility and intake exclusion, base run computed, distribution digest binding, baseline lifecycle, seq/previous/recorded_at, label and ordinal arithmetic, revoke-not-governing, approve-at-most-once | DB trigger (G3–G15) + partial uniques |
| 200 Scenarios / 20,000 versions per Principal, 100 outputs per version, 2 GiB stored, 256 MiB/day per Principal, 128 MiB/day per bucket, 120/hour + 1,000/day per bucket, 2,000/day per Principal, 120 refusals/hour per bucket, 2,500,000 CPM units/hour | S6-2 repository read under P (`scenario_and_version_counts`, `output_count`, `plane_byte_counts`, `client_write_counts`, `refusal_count`, `cpm_units_since`); the limit and its error are S6-3 policy |
| pending proposals 50 per Project, 10 per bucket per Project | S6-1 `decide_baseline_write` under J (lock-enforced, section 12.1) |
| 1 concurrent compute per Principal | lease C + process lock (14.8.4) |

### 14.9 Pre-deploy checks and runbook

New `src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py` (the
`cpm_workbench_predeploy.py` shape: `STATEMENTS` all `SELECT`, one transaction starting `SET
TRANSACTION READ ONLY`, always rolled back; no connection string, application row or
exception text in a result). Every statement reads catalogs or catalog functions **except
Q2's** retired-role probe, a deliberate operator-wide, cross-Principal boolean (R9-F09). It is
**not** a raw string: `test_raw_sql_carries_the_partition_on_every_table_reference` scans every
string constant of every module under `src/my_pa` and has no exemption registry (RR1-F02).
Q2 is therefore built with the expression language over the declaration,
`RETIRED_ROLE_PROBE = select(exists().where(schedule_publications.c.publication_role.in_(("baseline",
"reference"))))`, kept beside (not inside) the string `STATEMENTS` map, and the module —
which then imports a partitioned declaration — is registered in `QUARANTINED` of
`tests/architecture/test_principal_partition_is_reached_through_the_guard.py` with the reason
"read-only operator pre-deploy aggregate: one cross-Principal `EXISTS` boolean over
`schedule_publications` that returns no row and no identifier; it builds no other SQL over a
partitioned table". This is the mechanism the guard has (option (a) of RR1-F02, verified
against `test_every_module_naming_a_partitioned_table_is_guarded_or_registered`, which accounts
modules by their imports from `tables.py`). The select-only security test compiles the probe
with the PostgreSQL dialect and asserts it is a single `SELECT`.

**Quarantine pin (RR2-F01).** `QUARANTINED` exempts the whole module from import accounting,
so an exact pin keeps the registration from widening: I9-B adds the FAST test
`test_predeploy_module_touches_only_the_retired_role_probe` (in
`tests/architecture/test_schedule_scenarios_persistence_scope.py`), an AST check that
`src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py` imports exactly
`{"schedule_publications"}` from `my_pa.infrastructure.persistence.tables` and references that
name only inside the `RETIRED_ROLE_PROBE` assignment. An ad-hoc declaration such as
`sqlalchemy.table("schedule_publications", column(…), schema="knowledge")` or a `text()`
statement must not be used instead: the first would evade both the import accounting and the
raw-SQL scan, the second the raw-SQL scan's purpose.
The script runs, as the S5 precedent does, **as the runtime role the gateway and worker
connect as** (stated in the runbook): Q4 and Q8 evaluate that role as `current_user`, and Q4
also reports the owner of `knowledge.record_links` (the migrating role) for comparison, thin runner
`ops/postgres/schedule_scenarios_predeploy_check.py`, test
`tests/database/test_schedule_scenarios_predeploy.py`. **Scripted, never run against a
persistent database by S6-2.**

| # | Phase | Check | Stop when |
|---|---|---|---|
| Q0 | both | `transaction_read_only = on` | not read-only |
| Q1 | before | `pg_default_acl` entries for tables and sequences (`defaclobjtype IN ('r', 'S')`, R9-F09: the refusal table's identity sequence) naming `PUBLIC`, `my_pa_mcp_ro`, `my_pa_mcp_rw` | any entry |
| Q2 | before | the 7 S5 tables exist (revision A requires `621ef6786c64`) and the `EXISTS` above is false | a table absent or `true` |
| Q3 | before | `reltuples` and `pg_relation_size` of `record_links`, `schedule_publications`, `schedule_series` (reported; the quiet-window input) | never (report) |
| Q4 | before | the connecting runtime role (`current_user`) reaches `record_links` the way it will reach the plane tables (owner or default privilege; the P4 query), with the table owner reported | no reach |
| Q5 | both | one SHA-256 over the `relacl` text of `record_links`, `schedule_publications`, `schedule_series`; `after` must equal `before` | differs or missing |
| Q6 | after | `has_table_privilege` false for `PUBLIC`, `my_pa_mcp_ro`, `my_pa_mcp_rw` on the 11 plane tables, and the refusal sequence's `relacl IS NULL` | any privilege |
| Q7 | after | `pg_get_constraintdef` of `a_record_link_pair_is_admitted` names `concerns`, `delays`, `mitigates`; `a_record_link_from_family_is_known` names the 6 S6 families; `a_schedule_publication_role_is_known` does not name `reference` | any missing |
| Q8 | after | the connecting runtime role (`current_user`) holds `SELECT, INSERT` on the 11 tables and `UPDATE` on the ledger (the runtime reach the plane needs) | lacking |
| Q9 | after | the 11 plane tables, the 15 plane functions and trigger G10 exist | any absent |

Runbook (R9-F05): I9-A edits the `ops/runbooks/cpm-workbench.md` import procedure with the
S6-2-D04 behaviour ("from S6-2 until S6-3, `schedule_publications.import` refuses role
`baseline` with `invalid_request(PUBLICATION_ROLE)` whatever the switches; `reference` and kind
`working` are refused; `schedule_publications.list` refuses the filter
`publication_role=reference` with `invalid_request(PUBLICATION_ROLE)`"), and I9-B adds a
section "Schedule Scenarios revision A (S6-2, schema only)" in the same file: prerequisites (the S5 revisions applied first; the plane is
inert until S6-3), the quiet window (pause lineage writes and reads — the `record_links`
`ACCESS EXCLUSIVE` blocks them — the schedule import and worker), backup, Q0–Q5 before, the
upgrade, Q0, Q5–Q9 after, the expected `record_links` window from the section 14.6.3
measurement scaled by Q3, `55P03` as a clean retryable abort (never raise the 10 s timeout
without review), the downgrade refusal set, and "no grant, revoke, switch or capability is
part of this step". The ChatLLM/switch/grant gates stay in S6-3's runbook section (section 6.7).

### 14.10 Work split (2 serial packages; I9-B starts from I9-A's head)

| Package | Owns (writes only these) |
|---|---|
| **I9-A** schema | `src/my_pa/domain/common/identifiers.py` (8 kinds); `src/my_pa/domain/schedule/model.py` (enum lockstep, `ScheduleImportApproval`, request fields and invariants), `src/my_pa/domain/schedule/canonical.py` (v2 digest), NEW `src/my_pa/domain/schedule/plane.py`, `src/my_pa/domain/schedule/__init__.py` (exports); `src/my_pa/domain/lineage/vocabulary.py` (storage vocabulary only); `src/my_pa/application/commands.py` (the one S6-2-D04 edit, which must land with the request invariant "`approval` set ⇔ role `BASELINE`", R9-F04); `ops/runbooks/cpm-workbench.md` (the S6-2-D04 import note, section 14.9); `src/my_pa/infrastructure/persistence/tables.py` (11 tables, the 2 restated publication CHECKs by enum, the 6 `record_links` CHECKs from the storage vocabulary, G10's table comment); NEW revision A; NEW `tests/schema/test_schedule_scenarios_migration.py`; NEW `tests/database/test_schedule_scenarios_schema_guards.py`; NEW `tests/unit/test_schedule_plane_domain.py`; lockstep: `tests/unit/test_identifiers.py`, `tests/architecture/test_capture_project_binding.py` (`TABLES_SHA256`), `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` (125 → 126), the 53 head-pinning modules (`git grep -l 621ef6786c64 -- tests`; S5's own suites keep their revision and move only `HEAD`), `tests/schema/test_cpm_workbench_migration.py` (its frozen-literal test compares with the frozen pre-S6 sets, which are no longer the enums), `tests/unit/test_schedule_foundation_domain.py`, `tests/unit/test_schedule_commands.py` (also the new `test_baseline_import_is_refused_until_the_approval_fields_exist`), `tests/database/test_cpm_workbench_schema_guards.py`, `tests/database/test_cpm_workbench_persistence.py`, `tests/database/test_schedule_capabilities.py` and any other fixture naming `reference`/`working`, the lineage migration suites whose head assertions read the widened `record_links` texts, `TABLES_ABOVE`-style table lists, and the revision-count/head claims the readme-state and spelled-count guards bind (`README.md`, `docs/architecture/00_ARCHITECTURE_INDEX.md`, `docs/architecture/system-context.md`, `docs/architecture/cpm-workbench.md`, `ops/runbooks/README.md`, `ops/runbooks/gateway-operations.md`, `ops/runbooks/mcp-and-cli-operations.md`, re-measured, each file's own style), the module/test-count pins of the 2 contended plan documents `docs/plans/mcv-completion-plan.md` and `docs/plans/relationship-intelligence-implementation-plan.md` re-measured at I9-A's own head (its new source module and test modules move them), the section 14.6.3 scratch-cluster measurement recorded in the executed-results subsection, and `tests/ci_shard_weights.json` as `verify` requires |
| **I9-B** persistence | `src/my_pa/contracts/ports.py` (14.8.1); NEW `src/my_pa/infrastructure/persistence/schedule_scenarios.py`, `…/schedule_plane_codec.py`, `…/schedule_cpm_lease.py`; `src/my_pa/infrastructure/persistence/schedule.py` (14.8.5 approval, 14.8.6 intake); `src/my_pa/infrastructure/jobs/schedule.py` (14.8.7); NEW `src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py`, `ops/postgres/schedule_scenarios_predeploy_check.py`; `ops/runbooks/cpm-workbench.md` (the revision A section, 14.9); NEW tests `tests/database/test_schedule_scenarios_persistence.py`, `tests/database/test_schedule_baselines_persistence.py`, `tests/database/test_schedule_baseline_races.py`, `tests/database/test_schedule_series_matching.py`, `tests/database/test_schedule_scenarios_predeploy.py`, `tests/unit/test_schedule_plane_codec.py`, `tests/unit/test_schedule_cpm_lease.py`, `tests/architecture/test_schedule_scenarios_persistence_scope.py`; lockstep: `tests/architecture/test_principal_partition_is_reached_through_the_guard.py` (registry), `tests/architecture/test_cpm_workbench_worker_scope.py` only if its closure lists move, the module/test-count and mypy-file pins in `docs/plans/mcv-completion-plan.md` and `docs/plans/relationship-intelligence-implementation-plan.md` (re-measured again at I9-B's own head; the 2 contended pinned plan docs), `docs/architecture/cpm-workbench.md` and this contract's section 14 "executed results" subsection, `tests/ci_shard_weights.json` (heavy new database modules weighed; `python -m tests.ci_shard verify` green; validate-fast stays within its limit) |

**Each package's head is green on its own** (R9-F04): FAST, the full `tests/architecture`
directory and the database tiers it touches (`database` by marker, `migration_edge`,
`migration_empty_to_head`), ruff, both mypy runs and `python -m tests.ci_shard verify`, with
the 2 contended plan documents re-measured at that head.

Neither package edits `src/my_pa/application/schedules.py`, `src/my_pa/domain/schedule/compare.py`,
`src/my_pa/application/service.py`, `src/my_pa/bootstrap/*`, `apps/worker.py`, the S6-1
modules, any capability/purpose/policy/catalog/ChatLLM/remote/SafeDetail/web file, or a merged
revision.

### 14.11 Test plan, crosswalk and prove-red

#### 14.11.1 Modules and tiers

| Module | Tier | Content |
|---|---|---|
| `tests/unit/test_schedule_plane_domain.py` | FAST | IdKind prefixes vs S6-1 regexes; enum lockstep; request invariants; v1/v2 digest vectors; intake name; `second_admission_key`; `writer_bucket`; provenance sets equal the lineage sets; storage vocabulary ⊇ public |
| `tests/unit/test_schedule_plane_codec.py` | FAST | bounded decompression (bomb, truncation, trailing data, exact size), digest verification |
| `tests/unit/test_schedule_cpm_lease.py` | FAST | process lock, unlock-in-finally and invalidate on every path (mocked connection) |
| `tests/schema/test_schedule_scenarios_migration.py` | static: FAST + `migration_edge`; database: `migration_edge` default, `migration_empty_to_head` explicit | graph, freeze, offline SQL order, empty→head, predecessor→head with S5 and lineage rows, upgrade refusal, downgrade refusal and restore, lock timeout, grants, parity |
| `tests/database/test_schedule_scenarios_schema_guards.py` | `database_clone` | every CHECK, FK, unique, partial unique and trigger G1–G15 at head |
| `tests/database/test_schedule_scenarios_persistence.py` | `database_clone` | repository/UoW: ledger, CAS, scenarios, versions, CPM, outputs, digest recompute, cross-Principal |
| `tests/database/test_schedule_baselines_persistence.py` | `database_clone` | baseline lifecycle, governing, import-time approval, as-of |
| `tests/database/test_schedule_baseline_races.py` | `database_clone` | the section 12.7 race tests (threads, separate connections, a barrier) |
| `tests/database/test_schedule_series_matching.py` | `database_clone` | intake admission, worker hook, savepoint, plane-off |
| `tests/database/test_schedule_scenarios_predeploy.py` | `database_clone` | Q0–Q9 on the scratch cluster |
| `tests/architecture/test_schedule_scenarios_persistence_scope.py` | FAST | scope guard |

#### 14.11.2 Crosswalk (every S6-2 test this contract names)

| Requirement (section) | Test |
|---|---|
| CAS version append (9.4, 8.2) | persistence `test_version_append_is_cas_guarded` |
| CPM natural-key replay (9.4, 3.11) | persistence `test_cpm_run_replays_by_natural_key` |
| one compute per Principal; lease released on every path (3.11) | persistence `test_concurrent_cpm_runs_answer_busy_without_computing` (layered: both lease layers), `test_a_held_session_lease_answers_busy` (session lock alone), `test_cpm_lease_connection_is_never_returned_to_the_pool`, `test_compute_lease_never_blocks_the_write_transaction`; unit `test_the_process_lock_answers_busy_alone`, `test_lease_unlocks_and_invalidates_on_every_path` |
| engine runs only verified stored content (9.1.1 FR8-F07) | persistence `test_cpm_runs_only_on_verified_stored_content` |
| digest recompute on read (8.2) | persistence `test_tampered_content_reads_as_an_integrity_error` (parametrized: content, change set, result, output) |
| bounded decompression (8.1) | unit `test_decompression_is_bounded` |
| idempotency (6.3) | persistence `test_same_key_same_request_replays`, `test_same_key_other_request_conflicts`, `test_a_refused_write_leaves_no_reservation` (parametrized: a refusal before the insert, `ScenarioHeadMovedError`, a `BaselineWriteRefusedError`, `PlaneSubjectAbsentError`, `baseline_not_effective` for Scenario-from-Baseline; R9-F08, RR1-F04) |
| cross-Principal `not_found` (8.2) | persistence `test_other_principal_reads_none_and_writes_nothing` |
| append-only and TRUNCATE (8.2) | guards `test_plane_table_is_append_only[<table>]` (10), `test_plane_table_refuses_truncate_when_it_holds_rows[<table>]` (11) |
| ledger transition (8.2) | guards `test_write_request_completes_once`, `test_write_request_is_never_left_reserved` |
| lineage CHECKs (5.4) | migration `test_lineage_checks_admit_the_s6_pairs_and_refuse_others`, `test_frozen_lineage_texts_equal_the_storage_vocabulary`; unit `test_storage_vocabulary_is_the_public_vocabulary_plus_the_pending_s6_additions` |
| role retirement (12.2) | guards `test_reference_role_is_retired` (P47); migration `test_upgrade_refuses_while_a_retired_role_row_exists`; unit `tests/unit/test_schedule_commands.py::test_baseline_import_is_refused_until_the_approval_fields_exist` (S6-2-D04, I9-A) |
| explicit Series never matches (11.2 step 1, P29) | matching `test_explicit_series_never_matches` |
| own intake Series (11.2 step 2, P39) | matching `test_each_auto_import_gets_its_own_intake_series` |
| decision recorded (11.2) | matching `test_auto_import_records_a_match_decision` |
| refusal recorded, finalization commits (11.2 step 4, P40) | matching `test_match_admission_refusal_is_recorded_not_raised` |
| plane off (11.2 step 6) | matching `test_plane_off_records_the_decision_without_admitting` |
| candidate bound under the lock (11.2 step 3) | matching `test_more_than_fifty_series_is_candidate_bound` (parametrized: 51 eligible Series; 51 Series of which 3 have no eligible publication — still `candidate_bound` with an empty `candidates` array; R9-F07) |
| finalization never fails on a hook defect (11.2 step 4, R8-F12) | matching `test_hook_defect_commits_finalization_without_a_decision` (parametrized through a test seam: a decision-insert `IntegrityError`, a `ScenarioIntegrityError`, a `ValueError`, a `DataError`; each case: the intake publication is terminal `complete`, no decision row, the job succeeds), and `test_transient_hook_error_still_propagates` (a seam raises `OperationalError`: the finalization rolls back, the publication stays `processing`, the attempt is released for retry; RR1-F01) |
| exhausted intake job (S6-2-U09) | matching `test_exhausted_intake_job_has_no_decision_and_breaks_nothing` (the job dead-letters; the publication reads effective `failed`; no decision; a later explicit import admits) |
| `created` never joins an unscored Series (R9-F02) | matching `test_created_never_joins_a_series_created_after_the_free_read` (a barrier seam between the `FREE` read and the admission; an explicit import of that name commits in between; expected `ambiguous`/`name_conflict`, no publication added to the operator's Series) |
| trigger lookups are Principal-qualified (R9-F06) | guards `test_a_foreign_principal_subject_is_a_foreign_key_violation` (parametrized: another Principal's publication as a Scenario origin, as a Baseline publication and as a baseline-event subject; SQLSTATE `23503`, never `23001`) |
| import-time approval only in its own admission (G14 (d)) | guards `test_import_approval_needs_a_publication_of_this_transaction` |
| each section 12.1 index refuses on its own | guards `test_baseline_backstop_index_refuses_alone[<index>]` (7: the 5 partial uniques and the 2 `seq` uniques; rows inserted after `SET LOCAL session_replication_role = replica` (transaction-scoped, so no pooled connection keeps it; RR1-F05), so G12–G15 and the FK triggers do not fire, with distinct `seq` values except in the `seq` cases; `unique_violation` naming exactly that index) |
| intake Series holds 1 publication (G9, G10) | guards `test_intake_series_admits_no_other_publication` |
| baseline lifecycle (12.1) | baselines `test_baseline_lifecycle_transitions`, `test_direct_approval_adopts_a_pending_proposal` (B11), `test_import_time_approval_is_written_in_the_admission` |
| governing transitions (12.1) | baselines `test_governing_events_are_append_only`, `test_revoking_the_governing_baseline_is_refused`, `test_governing_as_of_reads_recorded_order_not_effective_from` (B5 values; P43 obligation) |
| races (12.7 P49–P54) | races `test_governing_chain_is_monotonic_under_contention`, `test_concurrent_approve_and_withdraw_write_one_decision`, `test_concurrent_approvals_of_one_publication`, `test_concurrent_approvals_never_reuse_a_label`, `test_concurrent_proposals_on_one_publication`, `test_pending_caps_hold_under_concurrency`; every race test synchronizes by barriers and seams, never by sleeps (R9-F03): a seam after the chain read makes the first writer wait until the second writer either reaches the same seam (no J) or is observed waiting on an advisory lock in `pg_locks` (`granted = false`, J present), so both interleavings are forced deterministically. P50 and P54 assert the **class** of the loser's answer: `BaselineWriteRefusedError` carrying `CONFLICT_BASELINE_ID` (P50) or `RATE_LIMITED_BASELINE_ID` (P54), never `ScheduleBaselineRaceError` |
| migration tiers, refusals, grants, parity (9.2) | migration `test_the_revision_is_the_single_head_on_621ef6786c64`, `test_the_revision_imports_no_package_module`, `test_the_revision_writes_no_row_and_grants_nothing`, `test_empty_to_head_creates_exactly_the_eleven_tables`, `test_predecessor_with_rows_upgrades`, `test_live_table_work_is_last_in_the_upgrade`, `test_lock_timeout_is_transaction_local`, `test_a_held_lock_aborts_the_upgrade_cleanly` (another connection holds `ROW EXCLUSIVE` on `knowledge.record_links`; `55P03`; still at `621ef6786c64`), `test_downgrade_refuses_while_any_plane_row_exists[<clause>]`, `test_clean_downgrade_restores_every_before_text`, `test_no_grant_beyond_the_owner`, `test_live_table_acls_are_unchanged`, `test_runtime_metadata_matches_the_revision` |
| nothing public; scope (9.2 "No capability") | scope `test_no_plane_name_is_public_before_s63`, `test_scenario_unit_of_work_is_not_on_the_general_unit_of_work`, `test_worker_passes_no_effective_plane`, `test_plane_persistence_writes_no_s5_table_except_through_admission` |
| pre-deploy (14.9) | predeploy `test_checks_are_read_only_and_always_roll_back`, `test_each_check_reports_its_stop` |

#### 14.11.3 Prove-red (break exactly one guard; the named test fails for that reason; revert)

| # | Mutation | Must fail |
|---|---|---|
| P2-01 | drop one of the 8 prefixes from the exact set (8 runs) | `test_contract_prefixes_are_stable` |
| P2-02 | G1 removed from each append-only table (10 runs) | `test_plane_table_is_append_only[<table>]` |
| P2-03 | G2 removed from each table (11 runs) | `test_plane_table_refuses_truncate_when_it_holds_rows[<table>]` |
| P2-04 | each CHECK family dropped in turn: provenance creator, origin whole, change set whole, snapshot whole, outcome shape, event fields, operator-attested decision, operator-attested governing, ledger result shapes, size bounds (one run each) | the matching `test_<check>_refuses` in the guards module |
| P2-05 | each composite FK changed to omit its project/series column or `RESTRICT` → `CASCADE` (one run each) | the matching `test_<fk>_refuses_a_cross_binding` |
| P2-06 | drop `a_scenario_version_number_is_used_once` with the P lock and G5 also removed | `test_version_append_is_cas_guarded` (with only the unique dropped the test must stay green: report as layered, not covered) |
| P2-07 | drop `a_cpm_run_is_computed_once` | `test_cpm_run_replays_by_natural_key` |
| P2-08 | ledger: compare key without digest | `test_same_key_other_request_conflicts` |
| P2-09 | G7 admits `completed → reserved` | `test_write_request_completes_once` |
| P2-10 | G8 removed | `test_write_request_is_never_left_reserved` |
| P2-11 | G3 drops the intake exclusion; then the status rule (2 runs) | `test_scenario_origin_must_be_eligible_and_not_intake[<case>]` |
| P2-12 | G4 removed | `test_a_scenario_without_a_first_version_fails_at_commit` |
| P2-13 | G5 drops the byte-copy rule; the linear rule; the snapshot rule (3 runs) | `test_scenario_version_chain_rules[<rule>]` |
| P2-14 | G6 drops the computed-run rule; the digest rule (2 runs) | `test_output_binds_a_computed_run_and_its_distributions[<rule>]` |
| P2-15 | G9 removed; G10 removed (2 runs) | `test_intake_series_admits_no_other_publication` |
| P2-16 | G11 accepts `matched` for a `failed` intake | `test_match_decision_follows_its_intake` |
| P2-17 | G12 removed | `test_a_revoked_publication_is_not_reapproved` |
| P2-18 | G14 (a) chain, (b) order, (c) lifecycle, (d) eligibility, (e) label, (f) ordinal, (g) supersedes — one run each | `test_baseline_event_chain_rules[<rule>]` |
| P2-19 | G15 (a)/(b)/(c) (3 runs) | `test_governing_event_chain_rules[<rule>]` |
| P2-20 | each of the 5 section 12.1 partial uniques and the 2 `seq` uniques dropped (7 runs) | `test_baseline_backstop_index_refuses_alone[<index>]`. **Declared layered in advance (R9-F03):** the race tests P51–P53 (`test_concurrent_approvals_of_one_publication`, `test_concurrent_approvals_never_reuse_a_label`, `test_concurrent_proposals_on_one_publication`) stay green when only a partial unique is dropped, because 2 concurrent writers of one Project always collide on `a_schedule_baseline_event_seq_is_used_once` and a sequential second write is refused by G12/G14 (c); they are expected green under this mutation and are reported as layered, never as covering the partial unique |
| P2-21 | `recorded_at = now()` instead of `clock_timestamp()` (P49) | `test_governing_chain_is_monotonic_under_contention` |
| P2-22 | J lock removed from `write_baseline` (P50) | `test_concurrent_approve_and_withdraw_write_one_decision`, which fails because the loser answers `ScheduleBaselineRaceError` (the `seq` UNIQUE) instead of `BaselineWriteRefusedError(CONFLICT_BASELINE_ID)` |
| P2-23 | pending caps read before the lock (P54) | `test_pending_caps_hold_under_concurrency`, which fails because a loser beyond the cap answers `ScheduleBaselineRaceError` (or a G14 (a) refusal) instead of `BaselineWriteRefusedError(RATE_LIMITED_BASELINE_ID)` |
| P2-24a | lease: the session lock removed | `test_a_held_session_lease_answers_busy` (a separate raw connection holds C, the process lock is free; expected `CpmComputeBusyError` and no compute) |
| P2-24b | lease: the process lock removed | `test_the_process_lock_answers_busy_alone` (`pg_try_advisory_lock` stubbed always true; 2 threads; the injected `compute` blocks on a barrier; the second answers busy) |
| P2-24c | lease: unlock not in `finally`; the lease connection taken from the request pool (2 runs) | `test_lease_unlocks_and_invalidates_on_every_path`, `test_cpm_lease_connection_is_never_returned_to_the_pool` |
| P2-24d | — | `test_concurrent_cpm_runs_answer_busy_without_computing` is **declared layered**: it stays green when either single layer is removed (the other answers busy); it proves the combined behaviour only, with an injected `compute` blocking on a barrier |
| P2-25 | C and P share one namespace | `test_compute_lease_never_blocks_the_write_transaction` (forced `hashtext` collision through a test seam) |
| P2-26 | `load_content` skips the digest check; skips `content_problem` (2 runs) | `test_tampered_content_reads_as_an_integrity_error[content]`, `test_cpm_runs_only_on_verified_stored_content` |
| P2-27 | `decompress_bounded` without `max_length` | `test_decompression_is_bounded` |
| P2-28 | savepoint removed from the hook | `test_match_admission_refusal_is_recorded_not_raised` |
| P2-29 | hook admits while `plane_effective` is false | `test_plane_off_records_the_decision_without_admitting` |
| P2-30 | all auto imports share one intake Series name | `test_each_auto_import_gets_its_own_intake_series` |
| P2-31 | explicit `series_id` consults the matcher (P29) | `test_explicit_series_never_matches` |
| P2-32 | candidate read without `LIMIT 51`; the bound decided after the eligibility skip (2 runs) | `test_more_than_fifty_series_is_candidate_bound[<case>]` |
| P2-33 | upgrade: authoritative refusal removed (the early one kept) | `test_upgrade_refuses_while_a_retired_role_row_exists` (the case inserts the row after step 2 through a test seam, else report masked) |
| P2-34 | restated role CHECK still admits `reference` (P47) | `test_reference_role_is_retired` |
| P2-35 | downgrade refusal: drop one clause (13 runs: 11 tables, the lineage clause, the kind clause) | `test_downgrade_refuses_while_any_plane_row_exists[<clause>]` |
| P2-36 | downgrade restores one BEFORE text wrongly (one run per restored CHECK, 8) | `test_clean_downgrade_restores_every_before_text`, `tests/schema/test_every_revision_denotes_one_schema.py` |
| P2-37 | move a live phase before `CREATE TRIGGER` | `test_live_table_work_is_last_in_the_upgrade` |
| P2-38 | `SET` instead of `SET LOCAL`; `lock_timeout` removed (2 runs) | `test_lock_timeout_is_transaction_local`, `test_a_held_lock_aborts_the_upgrade_cleanly` |
| P2-39 | add a `GRANT SELECT … TO PUBLIC` to the revision; grant on one table in the scratch database (2 runs) | `test_the_revision_writes_no_row_and_grants_nothing`, `test_no_grant_beyond_the_owner` |
| P2-40 | remove each new module from the partition registry (2 runs) | `test_every_module_naming_a_partitioned_table_is_guarded_or_registered` |
| P2-41 | drop `_mine` from `get_version` | `test_other_principal_reads_none_and_writes_nothing` |
| P2-42 | widen the public `RecordFamily` in S6-2 | `test_storage_vocabulary_is_the_public_vocabulary_plus_the_pending_s6_additions`, `test_no_plane_name_is_public_before_s63` |
| P2-43 | add a plane capability name to `Capability` | `test_no_plane_name_is_public_before_s63` |
| P2-44 | `apps/worker.py` passes `scenario_plane_effective=True` | `test_worker_passes_no_effective_plane` |
| P2-45 | v2 digest applied to a request with no S6 field | `test_v1_requests_keep_their_digest` |
| P2-46 | role-`baseline` replay by version ignores the approval fields | `test_baseline_reimport_with_other_approval_fields_conflicts` |
| P2-47 | `governing_as_of` selects by `effective_from` (P43 obligation) | `test_governing_as_of_reads_recorded_order_not_effective_from` |
| P2-48 | `ScenarioUnitOfWork` added to `UnitOfWork` | `test_scenario_unit_of_work_is_not_on_the_general_unit_of_work` |
| P2-49 | a plane module writes `schedule_publications` directly | `test_plane_persistence_writes_no_s5_table_except_through_admission` |
| P2-50 | the hook's outer savepoint removed (R9-F01) | `test_hook_defect_commits_finalization_without_a_decision` |
| P2-51 | the `series_created` check dropped (R9-F02) | `test_created_never_joins_a_series_created_after_the_free_read` |
| P2-52 | one trigger (G3, G12 or G14) looks its subject up by bare identifier and refuses when absent (3 runs) | `test_a_foreign_principal_subject_is_a_foreign_key_violation[<case>]` |
| P2-53 | `append_version` returns instead of raising on a moved head; `write_baseline` returns its refusal (2 runs) | `test_a_refused_write_leaves_no_reservation[<case>]` (the commit fails with G8's `check_violation`) |
| P2-54 | G14 (d) drops the `admitted_at = now()` condition | `test_import_approval_needs_a_publication_of_this_transaction` |
| P2-55 | remove the predeploy module's `QUARANTINED` entry; then (separately) write Q2 as a raw string (2 runs) | `test_every_module_naming_a_partitioned_table_is_guarded_or_registered`; `test_raw_sql_carries_the_partition_on_every_table_reference[<module>]` (RR1-F02) |
| P2-56 | the hook classifies by the old defect list (a `ValueError` propagates) | `test_hook_defect_commits_finalization_without_a_decision[value_error]` (RR1-F01) |
| P2-57 | Scenario-from-Baseline returns instead of raising when the Baseline is no longer effective | `test_a_refused_write_leaves_no_reservation[baseline_not_effective]` (RR1-F04) |
| P2-58 | import a second partitioned declaration into the predeploy module; then (separately) reference `schedule_publications` outside `RETIRED_ROLE_PROBE` (2 runs) | `test_predeploy_module_touches_only_the_retired_role_probe` (RR2-F01) |

A prove-red that stays green is reported as redundancy, a masked test or an unreachable
hazard, never "covered" (P2-06, P2-20's race tests, P2-24d and P2-33 name their expected
layering in advance, each with a sibling test that isolates the guard).

#### 14.11.4 Commands (foreground, chunked, explicit timeouts, `PYTHONPATH=src`, `~/my-pa/.venv/bin/python`)

FAST over new and touched modules; `-m "database and not migration_edge and not
migration_empty_to_head and not migration"` over the new database modules (by marker, never
by path alone); `-m migration_empty_to_head` and `-m migration_edge` over the migration
module; the full `tests/architecture` directory (the memory-row guard alone); `ruff check`,
`ruff format --check`; `mypy` strict default and `--platform linux`, in the repo venv and the
floor-pinned venv (the SQLAlchemy-floor `JSONB(...)` untyped-call trap applies to the
`candidates` column); `python -m tests.ci_shard verify` and `weigh`. Homebrew `postgres@15`
scratch cluster (`initdb --auth=trust`, free loopback port, `PGTZ=UTC`, no inline password),
stopped and removed at the end.

### 14.12 Decisions, amendments, residuals and operator gates

#### 14.12.1 Decisions and amendments (S6-2-D)

| ID | Decision | Reason |
|---|---|---|
| S6-2-D01 | **Amendment of section 5.4 and ADR-015 decision 17's "together with the vocabulary":** revision A widens the `record_links` CHECKs from a string-keyed **storage vocabulary**; the public enums and maps move in S6-3 | widening `RecordFamily`/`RelationType` in S6-2 would change the public `records.associations.assert` schema and admit families no resolver can read (R2-09) while S6-2 may expose nothing; the database and the Python declaration stay in lockstep through `tables.py` |
| S6-2-D02 | **Amendment of section 5.4:** `LINEAGE_READ_GENERATION` 1 → 2 moves to S6-3 | the generation tracks read rules (S3 §3); S6-2 changes none; one bump when the families become visible |
| S6-2-D03 | **Amendment of section 9.2's table list:** an 11th table, `schedule_scenario_write_refusals` | section 8.3's refused-write bound must survive the refused transaction's rollback; no other plane table can hold it, and adding it in S6-3 would turn revision B into a schema revision |
| S6-2-D04 | **Owned exception to "commands are S6-3":** `ImportSchedulePublication.import_request` refuses role `baseline` with `invalid_request(PUBLICATION_ROLE)` from S6-2 until S6-3 adds the section 12.3 fields and the `BASELINE_TYPE` plane gate (amended by S6-3-D14: the gate answers `PUBLICATION_ROLE`) | from S6-2 on a baseline import must carry an approval (one mechanism, R8-F20 b); without this edit the S5 command would build a request the record refuses (an unclassified error), or admit a baseline declaration with no Baseline object |
| S6-2-D05 | a per-Principal plane transaction lock P serializes every plane write | race-free budget, quota and CAS reads under READ COMMITTED (the lineage allocator-lock precedent) |
| S6-2-D06 | plane advisory namespaces `0x53534350` (P, J) and `0x5343504D` (C) | collision-free against every existing key; C separate so a lease can never block its own request |
| S6-2-D07 | no `admission_basis` column on `schedule_publications`; the auto-match basis is the decision row's `resulting_publication_id` (and the v2 digest's `match_decision_id`) | F3 freezes the publication's admission columns by an explicit list; a new column would need F3 replaced; the decision row is the evidence (section 11.2 step 3) |
| S6-2-D08 | an explicit `series_id`/`series_name` naming an intake Series is refused `SERIES_NOT_FOUND`; G9/G10 keep 1 publication per intake Series | R8-F11 (no shared identity); no new refusal member (R2-11) |
| S6-2-D09 | **Amendment of section 9.2 "or plane audit name":** revision A's downgrade checks plane rows, S6 lineage rows and `approved_update` publications; revision B refuses its own downgrade on plane audit names | no plane audit name exists before revision B (R2-17) |
| S6-2-D10 | no `server_computed` column; the label is a read-time constant of `schedule_cpm_runs` | only the server inserts runs; a constant column would be redundant |
| S6-2-D11 | content, change sets, results and outputs stored as zlib `bytea`; digests over canonical bytes | section 9.2 compression; bounded decompression on read |
| S6-2-D12 | the worker hook's effective-plane bit is a keyword defaulting to `False` | the switch is S6-3's; off is S6-O15's evidence-only behaviour (14.8.7) |
| S6-2-D13 | match decisions carry no provenance columns | the worker acts on the import's attested authority (section 11.2 step 7); the intake publication's admission is that act |
| S6-2-D14 | snapshot and change-set computation run outside the write transaction; the write re-checks the CAS head and Baseline effectiveness | short lock holds; the inputs are immutable |
| S6-2-D15 | `engine_version` and `threshold_version` CHECKs are patterns, not closed sets | a version bump needs no restating revision |
| S6-2-D16 | the intake hook runs inside an outer savepoint; a deterministic hook defect commits the finalization with no decision (R9-F01, Orchestrator option (a)) | R8-F12 "finalization always commits" stands unamended: an evidence defect never fails a parsed publication |
| S6-2-D17 | a `created` outcome requires `admission.series_created`, else `ambiguous`/`name_conflict` (R9-F02) | the explicit import takes no J, so a same-named Series can appear after the `FREE` read; joining it would share identity with an unscored Series (R8-F11) |
| S6-2-D18 | the compute-lease connection comes from a process-cached `NullPool` lease engine, outside the request pool (R9-F12) | a held lease never starves the pool of the connections its own steps need |
| S6-2-D19 | the restatements of one live table run as one multi-clause `ALTER TABLE` after an explicit `LOCK TABLE` (R9-F10) | one validating pass instead of 6 on `record_links`; the authoritative refusal still runs under `ACCESS EXCLUSIVE` |
| S6-2-D20 | every non-success after `reserve_request` is raised as a typed exception (R9-F08) | the UoW rolls the reservation back; G8 can never turn a refusal into `internal_error` |
| S6-2-D21 | the S6-2-D04 command edit lands in I9-A with the request invariant, and each package's head is green on its own (R9-F04) | no intermediate head exposes an unclassified error or a stale count pin |

#### 14.12.2 Residuals (S6-2-U)

| ID | Residual | Owner |
|---|---|---|
| S6-2-U01 | production row counts of `record_links` (and of the S5 tables if applied) are unknown here; the `ACCESS EXCLUSIVE` window scales with them (the scratch-cluster rate of section 14.6.3 gives the scale factor) | operator, Q3 before deploy |
| S6-2-U02 | production default privileges and runtime-role reach are unknown | operator, Q1/Q4 |
| S6-2-U03 | `write_baseline` reads the Project's whole chain under the lock (unlimited baselines) | later slice if a Project's chain grows large |
| S6-2-U04 | a lost compute lease can let 2 computes of one Principal overlap; integrity holds by the natural key | accepted |
| S6-2-U05 | `schedule_scenario_write_refusals` has no retention (≤ 120 rows per bucket per hour) | later retention design |
| S6-2-U06 | a 48-bit intake-name prefix collision between 2 different auto requests would put the second into the first's intake Series' name; G10 refuses it (an attempt failure, not a shared identity) | accepted (probability about 2^-48 per pair) |
| S6-2-U07 | the matcher reads up to 50 × 25,000 rows inside the finalization transaction under J. The worker engine's 30 s `statement_timeout` (`src/my_pa/infrastructure/database/engine.py`) means a matcher read, or a J wait, that deterministically exceeds 30 s raises `57014`, which is classed transient (RR1-F01): it is retried to the attempt bound and the intake publication then reads effectively `failed`. Accepted only because the bounded read is expected to be far below 30 s | bounded (section 8.1); S6-3 measures the maximal read on the server host |
| S6-2-U08 | owner/superuser can disable the plane triggers (S5b-1 U-06) | operator-gated role separation |
| S6-2-U09 | an intake publication whose job exhausts its attempts or is abandoned never reaches H8 or `_Job.fail`, so it has no decision (its effective status is `failed`, nothing is written); the operator resolves it by an explicit import (R9-F01) | operator; S6-3 reads show it as undecided |
| S6-2-U10 | a deterministic hook defect leaves an intake publication terminal with no decision; the reason is not recorded durably (no outcome member, no worker logging) | operator (explicit import); S6-3 reads show it as undecided |
| S6-2-U12 | CPM lease connections are outside the gateway's pool bound: up to 1 extra server connection per concurrently computing Principal per process (RR1-F03) | operator: count against `max_connections` (runbook, S6-3 enablement) |
| S6-2-U11 | a 32-bit `hashtext('cpm:' …)` collision between 2 Principals makes one answer a spurious `conflict(CPM_RUN)`; a P/J collision between 2 writers can surface a detected `40P01` (transient `internal_error`) | accepted (R9-F11, R9-F12) |

#### 14.12.3 Open S6-3 item recorded by R9 (ruling 4)

| ID | Item | Options |
|---|---|---|
| S6-3-O01 | whether an attested operator may call `schedule_baselines.propose`, and with which writer bucket. S6-1 `ProposeRequest.writer_bucket` is typed `str`, so an operator proposal is not representable today without a synthetic bucket; S6-2's schema does not pre-decide it (`a_schedule_baseline_decision_is_operator_attested` admits `propose` from either authority, and `writer_bucket` derives `None` for an operator row) | (a) the operator does not propose: section 12.3 lists `propose` as the client path, the operator approves directly, and the handler refuses (R9's recommendation: one mechanism); (b) the operator proposes with bucket `None`, counted against the 50-per-Project cap only and withdrawable only by the operator. S6-3 decides; no S6-2 change |

#### 14.12.4 Operator gates (never performed by an agent)

1. Apply revision A only after `6c2306330ceb` and `621ef6786c64`, in a quiet window for lineage
   (its `record_links` `ACCESS EXCLUSIVE` blocks every lineage read and write), the schedule
   import and worker; backup first; Q0–Q5 before and Q0, Q5–Q9 after; a `55P03` abort is
   clean and retryable.
2. A database holding S5 `baseline`/`reference` publications cannot upgrade (S6-U13); rebuild it.
3. No grant, revoke, switch, capability, ChatLLM profile or deployment is part of S6-2.

### 14.13 R9 findings → fixes (revision R9-1)

Design review R9 (PASS_WITH_REQUIRED_CHANGES at `a444e21b`) findings R9-F01…F13 and its rulings
are resolved in place; the Orchestrator chose option (a) for R9-F01.

| Finding | Fix (section) |
|---|---|
| R9-F01 | the hook runs in an outer savepoint; a deterministic hook defect commits the finalization with no decision, R8-F12 unamended; residuals S6-2-U09 (exhausted or abandoned job) and S6-2-U10; tests `test_hook_defect_commits_finalization_without_a_decision`, `test_exhausted_intake_job_has_no_decision_and_breaks_nothing`; P2-50 (14.8.7, 14.11, 14.12; S6-2-D16) |
| R9-F02 | `created` requires `admission.series_created`, else `ambiguous`/`name_conflict`; barrier race test `test_created_never_joins_a_series_created_after_the_free_read`; P2-51 (14.8.7; S6-2-D17) |
| R9-F03 | P50/P54 assert the class of the loser's answer; P51–P53 declared layered with `test_baseline_backstop_index_refuses_alone[<index>]` isolating each index; P2-24 split into P2-24a–d; barriers and seams only; section 12.7 amended (14.11.2, 14.11.3, 12.7) |
| R9-F04 | the S6-2-D04 command edit and `test_baseline_import_is_refused_until_the_approval_fields_exist` move to I9-A; both packages re-measure the 2 contended plan documents; each head green on its own (14.10; S6-2-D21) |
| R9-F05 | marked amendments in section 12.2, ADR-017 Consequences, ADR-015 decision 17 (pointer to S6-2-D01/D02) and `docs/architecture/cpm-workbench.md`; the runbook import note is specified for I9-A (14.9) |
| R9-F06 | Principal-qualified trigger lookups that defer to the FK when nothing is found; `test_a_foreign_principal_subject_is_a_foreign_key_violation`; P2-52 (14.4) |
| R9-F07 | the candidate bound is decided on the raw 51-row count before any skip, with an empty `candidates` array; P2-32 extended (14.8.7) |
| R9-F08 | `ScenarioHeadMovedError`, `BaselineWriteRefusedError`, `PlaneSubjectAbsentError` raised after the reservation; `test_a_refused_write_leaves_no_reservation` parametrized; P2-53 (14.8.1, 14.8.2, 14.8.5; S6-2-D20) |
| R9-F09 | Q2 is a stated cross-Principal `EXISTS` registered in the partition guard; Q1 covers sequences; Q4/Q8 run as the runtime role (14.9) |
| R9-F10 | one multi-clause `ALTER TABLE` per live table; I9-A's scratch-cluster measurement at 10^5 and 10^6 `record_links` rows recorded for the runbook (14.6.2, 14.6.3; S6-2-D19) |
| R9-F11 | the lock-order statement replaced by the partial order and the no-cycle argument, with FK `KEY SHARE` and job-row locks; `40P01` is transient (14.8.4; S6-2-U11) |
| R9-F12 | the lease connection comes from a `NullPool` lease engine; the spurious `conflict(CPM_RUN)` on a key collision is accepted (14.8.4; S6-2-D18, S6-2-U11) |
| R9-F13 | G14 (d) requires `admitted_at = now()` (P2-54); G14 (b)/G15 (b) `check_violation` maps to `internal_error`; "about 120"; `writer_bucket -> str \| None`; the append reads the parent by `expected_head_version_no` and refuses before computing; fork bytes count toward the quotas; `test_compute_lease_never_blocks_the_write_transaction` in the crosswalk (14.3.11, 14.4, 14.7.3, 14.8.2, 14.8.3, 14.11.2) |
| Ruling 4 | recorded as open S6-3 item S6-3-O01 (14.12.3) |

**Re-review RR1 (PASS_WITH_REQUIRED_CHANGES at `b612db98`) → fixes (revision R9-2).**

| Finding | Fix (section) |
|---|---|
| RR1-F01 | the hook classifies by transience: only `OperationalError`, `InterfaceError`, `ScheduleLeaseLostError` and non-`Exception` `BaseException` propagate; every other `Exception` rolls back to the outer savepoint and returns `SeriesMatchUndecided`; the hook-defect test gains `ValueError` and `DataError` cases plus `test_transient_hook_error_still_propagates`; the 30 s `statement_timeout` (`57014`) case is disclosed in S6-2-U07; P2-56 (14.8.7, 14.11, 14.12.2) |
| RR1-F02 | option (a): Q2 is an expression-language `EXISTS` over the `schedule_publications` declaration, never a raw string, and the predeploy module is registered in `QUARANTINED` (verified: the raw-SQL scan has no exemption registry; module accounting is by imports); P2-55 (14.9) |
| RR1-F03 | `lease_engine(url: URL)` factory with explicit connect arguments, cached per URL and disposed at shutdown; lease connections are outside the pool of 5 (S6-2-U12) (14.8.4) |
| RR1-F04 | Scenario-from-Baseline raises `BaselineWriteRefusedError` (`conflict(BASELINE_ID)` / `conflict(STATUS)`) or `PlaneSubjectAbsentError`; an import-time approval refusal is an integrity error by construction; P2-57 and a new no-reservation case (14.8.2, 14.8.5) |
| RR1-F05 | `SET LOCAL session_replication_role = replica`; a C row in the lock inventory; the "absent ⇒ defer" rule limited to subject lookups (14.4, 14.6.3, 14.8.4, 14.11.2) |

**Re-review RR2 (PASS_WITH_REQUIRED_CHANGES at `638d9b90`) → fixes (revision R9-3).**

| Finding | Fix (section) |
|---|---|
| RR2-F01 | FAST AST pin `test_predeploy_module_touches_only_the_retired_role_probe` (I9-B): the predeploy module imports exactly `{"schedule_publications"}` from `tables.py` and uses it only inside `RETIRED_ROLE_PROBE`; ad-hoc `sqlalchemy.table()` or `text()` alternatives are forbidden; P2-58 (14.9) |
| RR2-F02 | the import-time approval never carries `supersedes_baseline_id` (a future field would be decided under J with a typed refusal); the lease-engine cache is lock-guarded and disposed by test fixtures; both hook savepoints are `begin_nested()` context managers and a failed outer rollback propagates as transient (14.8.4, 14.8.5, 14.8.7) |

### 14.14 Executed results (S6-2)

**I9-A scratch-cluster lock measurement (section 14.6.3, R9-F10).** Run once by hand on
2026-11-03 with `tests/schema/schedule_scenarios_lock_measurement.py` (not a CI test) against a
disposable catalog of a Homebrew PostgreSQL 15.15 (aarch64, Apple M4 Pro) scratch cluster
(`initdb --auth=trust`, loopback, `PGTZ=UTC`); nothing persistent was touched. Synthetic
`record_links` rows were inserted under `session_replication_role = replica` and `ANALYZE`d;
10^4 synthetic `schedule_publications` rows were present in both runs. Each live `ALTER TABLE`
was timed by `clock_timestamp()` immediately around it through a measurement-only wrapper of
`op`; the revision text was unchanged.

| `record_links` rows | `record_links` size | Phase C (`record_links`, 6 CHECKs, 1 pass) | Phase A (`schedule_publications` at 10^4 rows, 2.9 MB) | Whole upgrade |
|---|---|---|---|---|
| 100,000 | 24.8 MB | 0.84 s | 0.003 s | 0.88 s |
| 1,000,000 | 248.3 MB | 8.40 s | 0.002 s | 8.45 s |

Scale factor: phase C is linear at about 34 ms per MB of `record_links` heap (about 8.4 µs
per row) on this host, a freshly loaded and cached table on NVMe. **Go/no-go (amended by
FR9-F01):** the input is Q3's `bytes=` (exact; `rows~` is an estimate, and `rows~-1` means
never analyzed); `T = bytes / 1,048,576 × 34 ms × 10`, with 10 the stated host factor for the
unmeasured server host (S6-2-U01). Go when `T ≤ 2 s` (`bytes=` at most about 6,000,000);
otherwise the operator first runs the upgrade once, timed, on a restored copy on the server
host, and goes only when that measured upgrade takes at most 2 s. The window is unrelated to
the 10 s `lock_timeout`, which bounds only lock acquisition; an unpaused lineage call waits
for the whole pass, bounded by its own 30 s `statement_timeout` (`57014`, retried).
Runbook `ops/runbooks/cpm-workbench.md` section 8 step 3.

Command: `PYTHONPATH=src python -m tests.schema.schedule_scenarios_lock_measurement
postgresql+psycopg://<user>@127.0.0.1:<port>/postgres` (scratch cluster admin URL).

**I9-B executed results (persistence, sections 14.8-14.11).** Implemented on this branch
(I9-B, 2026-11-03) on I9-A's head `8adee5d9`: the section 14.8.1 ports, the plane repository
and unit of work (`src/my_pa/infrastructure/persistence/schedule_scenarios.py`), the bounded
codec (`schedule_plane_codec.py`), the two-layer compute lease (`schedule_cpm_lease.py`), the
admission's import-time approval and intake Series (`schedule.py`), the worker hook
(`src/my_pa/infrastructure/jobs/schedule.py`), the read-only checks Q0-Q9
(`src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py`,
`ops/postgres/schedule_scenarios_predeploy_check.py`) and section 8 of
`ops/runbooks/cpm-workbench.md` (the lock-measurement scaling and its go/no-go rule above).
Nothing was run against a persistent database; every database tier ran on a disposable
Homebrew PostgreSQL 15.15 scratch cluster. Every I9-B prove-red row (P2-06 to P2-08, P2-21 to
P2-32, P2-40 to P2-44, P2-46 to P2-58) went red with the guard restored after each run, all but
two through the named test's own assertion: P2-30 and P2-31 went red through the G9 backstop
(a shared or explicit Series name fails `an_intake_series_holds_only_its_publication` at the
admission). FR9 isolated both with G9's name clause off: P2-31 then reddens by its own
assertion, while P2-30 reddens through G10, so `test_each_auto_import_gets_its_own_intake_series`
is layered behind G9/G10 (proven by P2-15), not covering. P2-06 (the unique alone), P2-20 (the
partial uniques under P51-P53) and P2-24d (either lease layer alone) stayed green as declared
in advance; their isolating siblings are red: `test_plane_uniques_refuse_a_second_row` with
`a_scenario_version_number_is_used_once` dropped alone (FR9 M1, re-run by I9-B: `DID NOT
RAISE`), `test_baseline_backstop_index_refuses_alone[...]` (I9-A) and P2-24a/P2-24b.
**FR9 corrective rows (I9-B, red):** FR9-F02, the early J removed from `admit_publication` ->
`test_import_approval_takes_the_project_lock_before_the_predecessor` fails with `40P01`
(deadlock detected); FR9-F03, `InterfaceError` or `ScheduleLeaseLostError` removed from the
hook's transient set, or `BaseException` caught as a defect ->
`test_transient_hook_error_still_propagates[interface_error|lease_lost|keyboard_interrupt]`;
FR9-F06, the downgrade's plane `LOCK TABLE` removed -> `test_offline_downgrade_refuses_first`.
**Residual (FR9-F05, pre-existing):** `tests/database/test_mcp_database_profiles.py` and
`tests/schema/test_cpm_workbench_migration.py::test_no_grant_beyond_the_owner` create the
cluster-global roles `my_pa_mcp_ro`/`my_pa_mcp_rw` and never drop them, so on a reused cluster
`tests/database/test_cpm_workbench_predeploy.py::test_a_grant_on_a_cpm_table_stops_the_after_phase`
(exact `detail` match) fails by test order; not exposed in CI's fresh container. The S6-2
role-creating tests drop the roles they create. Trivial naming resolutions, none changing a
decision: the helper records `NewScenarioChangeSet` and `CpmRunWritten`; the helper port
methods `find_request` (the read-only ledger probe of section 14.8.4 step 1),
`version_by_number`, `get_cpm_run_by_id` and `get_match_decision`; `NewScenario` holds the
name, description and origin publication/Baseline, and the Project and Series are the origin's;
`BaselineWritten.event_id` names either chain's event, with `governing`;
`compute_and_store_cpm_run` takes `request_digest` (the ledger needs it) and the test seams
`compute` and `clock`, and calls `admit_compute(units_used_last_hour, units_requested)`; the S5
module reaches the plane through 3 functions (`lock_project`, `record_import_approval`,
`stored_import_approval`) by a module import, which is safe in either import order; the lease
module names no table, so only `schedule_scenarios.py` joins `REACHED_THROUGH_THE_GUARD` and
`PER_MODULE_ONLY`, and P2-40's second run removes the pre-deploy module's `QUARANTINED` entry;
`record_refusal` keeps nothing for an attested operator; Q2 and Q6 stop
(`retired_role_rows=unreadable`, the sequence found through `pg_depend`) rather than abort when
the connecting role cannot read; `tests/security/test_cpm_workbench_security.py` admits the
plane module in its import list (the admission and the handler now import it); the shared test
helper is `tests/database/schedule_plane_world.py`.

---

## 15. S6-3 implementation note (design D10; implemented on this branch by I10-A, I10-B and I10-C, not merged)

**Status.** Implemented on `feat/schedule-scenarios-capabilities` by packages I10-A, I10-B and
I10-C (section 15.19); not merged, migrated, granted or deployed. Written by D10 on
`feat/schedule-scenarios-capabilities` at base `59f333d72c10b1eaebd6ee988e7ec9f31735c6b3`, tree
`93e82197887b9758cc3a10c8b70f5d232ed0c271` (= `origin/main` with S6-2 #349 merged as `3a1bdea7`
and then Reports Modernization #351). Once design review R10 passes it, this section and the
sections it cites are the single specification the S6-3 implementers (I10-A, I10-B, I10-C) code
against: a point that is wrong or incomplete against the code is a stop with a proposed
amendment, never a silent redesign; trivial naming resolutions are allowed and listed in the
handoff. Where this section and an earlier section disagree, the earlier text is amended here
explicitly (each marked **amendment** with its reason, section 15.18) and this section controls
for S6-3. Operator decisions (sections 10.3, 12), S6-1 engine semantics and S6-2 persistence
semantics are not reopened; S6-3-O01 is closed by the operator (section 15.4).

**Revision R10-1.** Design review R10 (PASS_WITH_REQUIRED_CHANGES at `de81d3d8`) findings
R10-F01…F13 and its rulings on S6-3-D01…D20 and the open questions are resolved in place;
section 15.20 maps each finding to its fix (D20 is replaced, D14 amended, D21–D25 added).

### 15.1 Repository reauthentication at `59f333d7`

Every count of sections 6 and 9.3 was measured before Reports Modernization #351, which added
15 `reports.*` names, 3 report purposes, 10 `IdKind`s, 11 `DATA_REQUIRED` ChatLLM names, 4
`CONTROL_PLANE_EXCLUDED` names, profile `chatllm-data-v12` and the audit restatement
`4c37731671fc`. Each delta is an S6-3-D row.

| # | Claim (contract or brief) | Repository truth at `59f333d7` | Decision |
|---|---|---|---|
| R3-01 | 240 `Capability` (section 6.1) | 255 (`src/my_pa/domain/identity/operation.py`); the last 7 members are the S5b-2 Schedule names, the 15 Reports names sit inside the class beside `reports.*` | the 26 are appended after `SCHEDULE_CHANGES_LIST` in section 6.1 order: 255 → 281 (S6-3-D01) |
| R3-02 | 62 `Purpose` | 65 (`src/my_pa/domain/identity/purpose.py`); last 3 `report_lifecycle`, `report_hold`, `report_retention` | 3 appended after `REPORT_RETENTION`: 65 → 68 (S6-3-D01) |
| R3-03 | 156 → 164 `IdKind` | 174 in `src/my_pa/domain/common/identifiers.py` (S6-2's 8 plus Reports' 10) | S6-3 adds no `IdKind`; 174 stays |
| R3-04 | audit vocabulary 251 → 277 / 62 → 65 | the audit CHECKs `capability_is_known` / `purpose_is_known` on `knowledge.audit_events` are DB CHECKs; last restated by `4c37731671fc` (`_CAPABILITIES_AT_THIS_REVISION` 266 = 255 + 11 `NativeSourceCapability`, `_PURPOSES_AT_THIS_REVISION` 65); `tables.py` derives both from the live enums (`_CURRENT_AUDIT_CAPABILITIES`, `_one_of("purpose", Purpose)`) | **revision B is required** (a new `Capability` without it leaves the head catalog differing from `tables.py`): 266 → 292, 65 → 68, `down_revision = "4c37731671fc"` (S6-3-D02, section 15.13) |
| R3-05 | Alembic sole head | `4c37731671fc` (`migrations/versions/20261104_4c37731671fc_general_report_plane.py`), chaining from S6-2 `2a90f91dd786`; 127 revision files; 57 test modules name `4c37731671fc`; 34 test functions pin 127 | revision B: 128 files; head literal and counts move in lockstep |
| R3-06 | `CHATLLM_DATA_PROFILE_VERSION` becomes `chatllm-data-v12` | already `chatllm-data-v12` (Reports #351, `src/my_pa/domain/identity/chatllm_capability_policy.py`) | **S6-3 bumps to `chatllm-data-v13`** (S6-3-D03) |
| R3-07 | ChatLLM policy counts (section 6.6) | policy 255; `DATA_REQUIRED` 85; `DATA_CONDITIONAL` 137; `CONTROL_PLANE_EXCLUDED` 29; `COMPATIBILITY_ONLY` 2; `OPERATOR_DECISION_REQUIRED` 2; `RETIRED` 0; `SCHEDULE_DATA_NAMES` 6; prerequisite enum has `SCHEDULE` and no scenario member; `ChatLLMCompositionPlanes` (`src/my_pa/application/chatllm_data_profile.py`) has 9 flags (`schedule` last); planner targets: full 175, default 109, full + schedule 181, full + lineage 202, full + lineage + program 209, full + lineage + program + schedule 215, default + lineage + program 141, default + all 3 switches 147; 512 compositions | section 15.2 targets (S6-3-D04) |
| R3-08 | `_FEATURE_BY_FAMILY` "in remote" | `src/my_pa/adapters/mcp/chatllm_gateway.py`, a `family → feature` map of 26 entries keyed by the token before the first `.`; `schedule_series`/`_publications`/`_activities`/`_changes` → `schedule` | + 5 entries (section 6.1 list) → `schedule`; shape unchanged |
| R3-09 | remote ceilings | restricted MCP database profiles (`src/my_pa/contracts/mcp_database_profiles.py`) hold no CPM privilege; remote publication is `remote_tool_names` (`src/my_pa/adapters/mcp/remote.py`): operator-only names are withheld except `_REMOTE_OPERATOR_IDENTITY_CAPABILITIES` under the `remote.operator` profile or compact operator publication; writes need `writes_enabled` | unchanged; the 4 operator writes never join `_REMOTE_OPERATOR_IDENTITY_CAPABILITIES` |
| R3-10 | façade `describe/read/write/operator` and catalog `TOOLS` | `facade_kind` (chatllm gateway) = `operator` if `is_operator_only`, else `write` if `is_remote_write` (`permitted_purposes & _WRITE_PURPOSES`, minus `_REMOTE_READS_UNDER_WRITE_PURPOSES`), else `read`; `TOOLS` (`src/my_pa/adapters/mcp/tools.py`) is built from every `Command` union member: name, description = the command docstring's first line, input schema from the dataclass, annotations `read_only_hint = not is_write_capability`, `destructive_hint = is_destructive_capability`, `idempotent_hint = is_remote_idempotent`; 255 tools | the 26 commands join the `Command` union; `facade_kind` follows from the registries below (6 `write`, 4 `operator`, 16 `read`) |
| R3-11 | `_OPERATOR_ONLY`, `_WRITE_PURPOSES` | `_OPERATOR_ONLY` (26 members) is in `operation.py`; `_WRITE_PURPOSES` (33) is in `src/my_pa/adapters/mcp/remote.py`; `operation.py` also holds `_WRITE_CAPABILITIES` (137) and `_ADDITIVE_WRITE_CAPABILITIES` (50), which the contract did not name | + 4 operator-only; + `schedule_analysis_authoring`, `schedule_baseline_approval`; + 10 writes; + 5 additive (S6-3-D05) |
| R3-12 | `_SCOPELESS`, `_requested_scope` | `_SCOPELESS` (246) in `src/my_pa/domain/policy/decision.py`; `_requested_scope` is a `match` over command classes in `src/my_pa/application/authorization.py` (the S5b-2 reads share one case arm) | + 26 to `_SCOPELESS`; the 26 command classes join the scopeless arm |
| R3-13 | remote keys | `src/my_pa/adapters/remote_request.py`: `_IDEMPOTENT_REMOTE_CAPABILITIES` (107) stamps `idempotency_key = "idk_" + sha256(json{capability, principal_id, payload[, client]})[:32]` (36 characters, **not 64-hex**: R2-20 of section 14.1 was wrong, harmless because `^[A-Za-z0-9_-]{8,128}$` admits it); `_CLIENT_BOUND_KEY_CAPABILITIES` (20) is derived: idempotent ∩ (`OPEN_LINEAGE_WRITE_CAPABILITIES` ∪ `_CLIENT_BOUND_REPORT_WRITES`); `is_remote_idempotent` is a function: server-replay set ∪ `LINEAGE_WRITE_CAPABILITIES` | a third source set `_CLIENT_BOUND_SCENARIO_WRITES` (the 6) feeds both sets, and `is_remote_idempotent` gains `or capability in _CLIENT_BOUND_SCENARIO_WRITES` (S6-3-D06) |
| R3-14 | `attested_lineage_authority` | `src/my_pa/application/lineage_authority.py`: returns the derived pair, raises `DeniedError()` unless the authority class is attested and the channel is `local_cli`/`local_web`; `lineage_write_provenance(authorization, user_directed=…)` derives the S3.1 row provenance and refuses `user_directed=True` for the operator | the 4 operator handlers call `attested_lineage_authority`; every plane write derives `PlaneProvenance` from `lineage_write_provenance` |
| R3-15 | `SafeDetail` names of section 9.3 | 359 members (`src/my_pa/application/errors.py`); **already present:** `EXPECTED_VERSION`, `LABEL`, `EFFECTIVE_FROM`, `REASON`, `VERSION_ID`, `STATUS`, `TO_PUBLICATION_ID`, `SERIES_NAME`, `PUBLICATION_ROLE`, `BASELINE_KIND`, `PROJECT_ID`, `SERIES_ID`, `PUBLICATION_ID`, `FROM_PUBLICATION_ID`, `PAGE_SIZE`, `CURSOR`, `NAME`, `DESCRIPTION`, `AS_OF`, `CHANGE_KIND`, `IDEMPOTENCY_KEY`, `CLIENT_INTENT_ID`, `USER_DIRECTED`, `ENDPOINT`, `RELATION_TYPE`; absent: the rest | reuse the present ones; add 37 (section 15.7.1), none colliding with an existing value (measured); `SCENARIO_VERSION_ID` and `ACTIVITY_KEY` are not added (S6-3-D07) |
| R3-16 | `ScheduleCursorOrder` | 5 orders (`src/my_pa/domain/schedule/cursor.py`); `tests/unit/test_schedule_cursor.py::test_round_trip` parametrizes over all | + 6 (section 15.6.2); `baselines_label_asc` is replaced (S6-3-D08) |
| R3-17 | lineage vocabulary | `RecordFamily` 7, `RelationType` 8, `NativeVirtualEdge` 1, `LINEAGE_FAMILY_READS` 7 keys, `LINEAGE_READ_GENERATION = 1` (consumed by `src/my_pa/domain/lineage/cursor.py` `scope_digest`), `CONTESTABLE_RELATIONS` 7; S6-2's `SCHEDULE_LINEAGE_FAMILY_ID_KINDS`, `STORED_RECORD_FAMILY_ID_KINDS` (13), `SCHEDULE_LINEAGE_RELATIONS`, `STORED_RELATION_MATRIX` exist; `tables.py` builds the `record_links` CHECKs from the stored maps | section 15.11 |
| R3-18 | lineage endpoint resolution | `lock_lineage_sources` (`src/my_pa/application/lineage_endpoints.py`) shares endpoints through `RecordLineageRepository.share_endpoint(principal_id, family, identifier) -> LineageEndpoint \| None` (SQL in `src/my_pa/infrastructure/persistence/record_lineage.py`) on the **general** `UnitOfWork`; `require_linkable(issues, principal_id, endpoint)` decides linkability per family; `LineageEndpoint` (`src/my_pa/contracts/ports.py`) carries per-family facts | the 6 families are shared by `share_endpoint` on the general unit of work (FOR SHARE, Principal-partitioned) with new `LineageEndpoint` fields; `ScenarioUnitOfWork` stays off `UnitOfWork` (S6-3-D09) |
| R3-19 | S6-2 repository API the handlers call | `ScenarioRepository` / `ScenarioUnitOfWork` in `src/my_pa/contracts/ports.py` as section 14.8.1 plus the I9-B helpers `find_request`, `version_by_number`, `get_cpm_run_by_id`, `get_match_decision`; `compute_and_store_cpm_run(engine, principal_id, version_id, *, capability_key, request_digest, writer, admit_compute, compute=run_cpm, clock=_now) -> CpmRunWritten` (`src/my_pa/infrastructure/persistence/schedule_cpm_lease.py`); **no paged list read exists** (scenarios, versions, outputs, decisions, baselines), no eligible-publication read, no currency read and no intake probe | 9 read methods and 1 keyword are added to the S6-2 module (S6-3-D10, section 15.14); the application layer reaches the plane only through ports composed in `src/my_pa/bootstrap/gateway.py` |
| R3-20 | worker hook | `process_schedule_publication(engine, job, owner, *, scenario_plane_effective: bool = False)` (`src/my_pa/infrastructure/jobs/schedule.py`); `apps/worker.py` `_JOB_PLANES["schedule"] = (SCHEDULE_JOBS, process_schedule_publication)` passes nothing; FAST `test_worker_passes_no_effective_plane` pins that | `apps/worker.py` `_run` binds `functools.partial(process_schedule_publication, scenario_plane_effective=settings.schedule_enabled and settings.schedule_scenarios_enabled)` for the schedule plane; the S6-2 pin is replaced (section 15.8) |
| R3-21 | S5 import command | `ImportSchedulePublication` (`src/my_pa/application/commands.py`), a frozen dataclass (fields `series_id`, `series_name`, `publication_role`, `baseline_kind`, `expected_data_date`, `supersedes_publication_id`, `idempotency_key`, …) whose `import_request()` refuses role `baseline` with `invalid_request(PUBLICATION_ROLE)` (S6-2-D04); the record `ScheduleImportRequest` already carries `series_auto`, `series_name_if_new`, `approval`, `match_decision_id`; `SqlScheduleRepository.admit_publication` takes `operator_channel` | section 15.9 lifts D04 for role `baseline` only |
| R3-22 | commands are "strict pydantic models" (brief) | every command is a `@dataclass(frozen=True, slots=True)` built by `_BUILDERS` (`src/my_pa/adapters/normalization.py`) as `Command(**payload)`; an unknown key is a `TypeError` that `normalize` answers `invalid_request` (no detail); `__post_init__` validates; the published schema is `additionalProperties: false` | the repository idiom is kept: no pydantic (S6-3-D11) |
| R3-23 | transport size | `MAX_REQUEST_BYTES` = 762,288 (`src/my_pa/adapters/normalization.py`) bounds every CLI, HTTP and remote MCP request | a change set (bound 4,194,304) or output document (1,048,576) larger than about 740 KiB is unreachable over every transport; bounds unchanged, disclosed (S6-3-D12, S6-3-U01) |
| R3-24 | refused-write bound "before any parse of the payload" (section 8.3) | normalization (`Command(**payload)` and `__post_init__`) runs in the adapter **before** authentication and the handler | plane commands keep their heavy documents opaque until the handler; normalization refusals are pre-authentication and never counted (S6-3-D13, section 15.10) |
| R3-25 | web fixture | `web/src/lib/api/decode/fixtures/python/success.json`, compared with a live dump by `tests/contract/test_bff_success_decoder_parity.py::test_committed_python_fixtures_match_live_model_dumps` (its `capabilities.get` manifest lists every handler-backed capability); `web/src/contracts/gateway.json` declares web routes; every `Capability` must have a `_HANDLERS` entry (`assert set(Capability) - set(_HANDLERS) == set()`) | regenerated (26 manifest rows); `gateway.json` unchanged; all 26 handlers land in one package (I10-A) |
| R3-26 | client guidance | no server-instructions text; client guidance is `docs/operations/record-lineage-client-guidance.md` (pinned by `tests/contract/test_lineage_s31_guidance.py`) plus each command's docstring | a new guidance section there (section 15.12.5) |
| R3-27 | OD-08 | `ProgramFamily` (`src/my_pa/domain/program/vocabulary.py`) and `METRIC_CATALOGUE` (`src/my_pa/domain/program/reportability.py`) name no schedule member; `_block_seeds`, `lineage_server_counts`, `lineage_section` (`src/my_pa/domain/intelligence/source_manifest.py`) iterate `RecordFamily` | pinned 7-family frozenset (section 15.11.6) |
| R3-29 | runtime reach of the tables a lineage endpoint names (R10-F12) | S5b-1 (`6c2306330ceb`), revision A (`2a90f91dd786`) and Reports are **grant-free**: tables are owned by the migrating role and the runtime role reaches them as owner or by default privilege (Q4/P4 report which). The pre-deploy checks assert only: P-checks `SELECT, INSERT` on the 7 S5 tables plus `UPDATE` on `schedule_publications`, `schedule_jobs`, `schedule_parser_runs`, `schedule_rows` (`_UPDATED_TABLES`, `src/my_pa/infrastructure/database/cpm_workbench_predeploy.py`); Q8 `SELECT, INSERT` on the 11 plane tables plus `UPDATE` on the ledger only (`src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py`). So `UPDATE` (which `SELECT … FOR SHARE` requires) is **not** guaranteed on `schedule_activities`, `schedule_baselines`, `schedule_scenarios`, `schedule_scenario_versions`, `schedule_scenario_outputs` when the runtime role is not the owner | the 6 families are read without a row lock (S6-3-D21, 15.11.2); no grant is added; I10-B proves it under a role holding exactly the Q8/P-check privileges and stops if anything needs more |
| R3-28 | S6-2 scope pins S6-3 replaces | `tests/architecture/test_schedule_scenarios_persistence_scope.py::test_no_plane_name_is_public_before_s63` (no plane name, purpose, family, relation; generation 1; no application/adapters/bootstrap/apps module imports the plane persistence), `::test_worker_passes_no_effective_plane`; `tests/unit/test_schedule_plane_domain.py` pins generation 1 and stored ⊇ public | replaced in lockstep by the S6-3 pins of section 15.16 |

### 15.2 Re-measured pins (base → S6-3)

Values are measured at `59f333d7`; "S6-3" is the value the implementing package's head must
show. A test function listed moves in lockstep with its own comment updated; implementers
re-measure and report any difference, never force it. **Planner targets (R10 limits, verified
by D10 in revision R10-1):** every base target in this table was produced by **executing** the
planner (`desired_effective_capabilities(composed_capabilities(IMPLEMENTED, planes))`, through
the `tests/contract/test_schedule_policy_closure.py` helpers) at the base: full 175, default 109,
full + schedule 181, full + lineage 202, full + lineage + program 209, full + lineage + program +
schedule 215, default + lineage + program 141, default + lineage + program + schedule 147, 512
compositions. The S6-3 values add the 22 under the rule "desired iff `schedule and
schedule_scenarios`"; the same execution verified, over all 512 base compositions, that the 6
`DATA_CONDITIONAL` S5b-2 reads (the same class, one purpose, a plane prerequisite) are desired
exactly when their prerequisite holds, which is the rule the 22 follow. The S6-3 numbers are
therefore executed base + that verified rule, not a run of the S6-3 planner (which does not
exist yet); I10-C's `test_v13_targets` executes them.

**I10-A interim values (R10-F08).** I10-A's head holds ChatLLM at v12 (S6-3-D17): policy 281,
`DATA_REQUIRED` 85, `DATA_CONDITIONAL` 137, `CONTROL_PLANE_EXCLUDED` 55 (29 + the 26 under the
holding rationale `_SCHEDULE_SCENARIOS_PENDING_EXPOSURE = "Schedule Scenarios S6-3 pending
exposure (I10-C)"`), version `chatllm-data-v12`, every planner target and 512 compositions
unchanged, `_CURRENT` unchanged; `tests/contract/test_chatllm_capability_policy.py::test_classification_counts_match_the_approved_plan`
and `test_schedule_policy_closure.py::test_v11_targets` (`len(policy) == 281`) take those
values at I10-A, and `tests/contract/test_schedule_scenarios_policy_closure.py` asserts the
holding at I10-A and the final classes (159 / 33, v13) at I10-C. The S6-3 column below is
I10-C's head.

| Pin | Contract said | Base | S6-3 | Pinned by (file::test) |
|---|---|---|---|---|
| `Capability` | 240 → 266 | 255 | 281 | `tests/unit/test_constraint_authoring_vocabulary.py::test_the_two_vocabularies_are_the_sizes_this_package_states`, `tests/contract/test_capabilities_and_readiness.py::test_manifest_lists_every_capability_exactly_once`, `tests/contract/test_chatllm_capability_policy.py::test_policy_covers_every_public_capability_exactly_once`, `tests/contract/test_cli_transport.py::test_the_cli_publishes_no_command_for_handler_unwired_capabilities` (`_BUILDERS`), `tests/contract/test_mcp_transport.py::test_handler_unwired_capabilities_publish_no_mcp_tools` (`TOOLS`), `tests/contract/test_transport_parity.py::test_declared_unwired_capabilities_stay_separate_from_positive_parity`, `tests/contract/test_lineage_s31_capability_admission.py::test_s31_capabilities_are_operator_decision_required`, `tests/contract/test_lineage_s4_capability_admission.py::test_s4_capabilities_are_operator_decision_required_reads`, `tests/contract/test_schedule_policy_closure.py::_capability_enum` (also its `members[-7:]` slice → `members[-33:-26]`) and `::test_v11_targets`, `tests/schema/test_project_controls_run01_integrity_migration.py::test_revision_identity_and_frozen_vocabulary_are_exact`, `tests/security/test_no_capability_accepts_a_server_owned_field.py::test_the_population_is_the_handler_backed_remote_tool_set` |
| `Purpose` | 62 → 65 | 65 | 68 | `test_constraint_authoring_vocabulary.py` (as above), `tests/contract/test_lineage_s31_capability_admission.py::test_existing_non_lineage_v1_shapes_are_unchanged_by_s31`, `tests/contract/test_commitment_v1_strict_client.py::test_v1_tool_schemas_are_unchanged_by_s4`, `tests/contract/test_lineage_s4_capability_admission.py::test_the_program_purpose_admits_exactly_the_program_reads`, `tests/contract/test_schedule_policy_closure.py::_purpose_enum` (slices move by 3), `tests/schema/test_project_controls_run01_integrity_migration.py` (as above) |
| head audit vocabulary | 251 → 277 / 62 → 65 | 266 / 65 | 292 / 68 | `tests/schema/test_cpm_workbench_vocabulary_migration.py::test_at_sets_equal_the_live_enums` (head = live enums); `tests/schema/test_reports_general_migration.py::test_the_audit_before_texts_are_byte_copies_and_at_adds_exactly_the_report_vocabulary` stays 266/65 (its own frozen AT set) |
| Alembic files / head | — | 127 / `4c37731671fc` | 128 / revision B | `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py::test_the_chain_is_readable_and_non_empty` and the 33 `tests/schema/*` chain tests pinning 127; the 57 modules naming `4c37731671fc` as head (`git grep -l 4c37731671fc -- tests`; each revision's own suite keeps its revision and moves only `HEAD`) |
| `IdKind` | 156 → 164 | 174 | 174 | unchanged |
| ChatLLM version | `chatllm-data-v12` | v12 | v13 | 33 test functions (`git grep -n chatllm-data-v12 -- tests`), among them `tests/unit/test_remote_mcp_chatllm_profile.py::test_v12_profile_commands_refuse_v11_and_the_nonexistent_next_version` (`_NONEXISTENT_NEXT_VERSION` 13 → 14, refused set v12 and v14) |
| runbook current version `_CURRENT` (R10-F03) | — | `chatllm-data-v12` | `chatllm-data-v13` | `tests/contract/test_lineage_client_exposure_runbook.py::test_the_runbooks_state_the_current_profile_version` (and the 6 files it reads) |
| ChatLLM policy size | 240 → 266 | 255 | 281 | `test_chatllm_capability_policy.py`, `test_schedule_policy_closure.py::test_v11_targets` |
| `DATA_REQUIRED` | 74 | 85 | 85 | `test_chatllm_capability_policy.py::test_classification_counts_match_the_approved_plan` |
| `DATA_CONDITIONAL` | 137 → 159 | 137 | 159 | same |
| `CONTROL_PLANE_EXCLUDED` | 25 → 29 | 29 | 33 | same |
| `COMPATIBILITY_ONLY` / `OPERATOR_DECISION_REQUIRED` | 2 / 2 | 2 / 2 | 2 / 2 | same |
| planner full / default (switch off) | 164 / 98 | 175 / 109 | 175 / 109 | `tests/contract/test_chatllm_data_profile_diff.py::test_full_plane_effective_target_is_one_hundred_forty_nine`, `::test_default_plane_effective_target_is_eighty_three`, `test_schedule_policy_closure.py::test_v11_targets`, `tests/contract/test_lineage_client_exposure_policy.py::test_v10_full_plane_targets_with_lineage_and_program_reporting` |
| full + schedule | 170 | 181 | 181 | `test_v11_targets` |
| full + schedule + scenarios | 192 | — | 203 | new `test_v13_targets` |
| full + lineage + program + schedule (+ scenarios) | 204 (226) | 215 | 215 (237) | `test_v11_targets`, `test_v13_targets` |
| default + lineage + program + schedule (+ scenarios) | 136 (158) | 147 | 147 (169) | same |
| full + lineage / + program; default + lineage + program | — | 202 / 209; 141 | unchanged | `test_v10_full_plane_targets_with_lineage_and_program_reporting` |
| compositions | 512 → 1,024 | 512 | 1,024 | `test_lineage_client_exposure_policy.py::test_v10_never_desires_a_withheld_lineage_name_in_any_composition`, `test_schedule_policy_closure.py::test_v11_targets` (`_every_composition` gains the `schedule_scenarios` bit) |
| README default split | — | default 124, total 255, withheld 131 | 124, 281, 157 | `tests/architecture/test_readme_state_claims.py::test_current_state_docs_derive_the_default_capability_split` (and the docs it reads) |
| `SafeDetail` | — | 359 | 396 | no count pin; `tests/contract/test_meeting_mcp.py` reads the live enum |
| `ScheduleCursorOrder` | 5 + 6 | 5 | 11 | `tests/unit/test_schedule_cursor.py::test_round_trip` (parametrized) |
| `RecordFamily` / `RelationType` / `NativeVirtualEdge` / `LINEAGE_FAMILY_READS` | 13 / 11 / 9 / 13 | 7 / 8 / 1 / 7 | 13 / 11 / 9 / 13 | `tests/unit/test_schedule_plane_domain.py` (stored ⊇ public → equality), lineage vocabulary unit tests |
| `LINEAGE_READ_GENERATION` | 1 → 2 | 1 | 2 | `tests/unit/test_schedule_plane_domain.py`, `test_schedule_scenarios_persistence_scope.py::test_no_plane_name_is_public_before_s63` (replaced) |
| `_OPERATOR_ONLY` / `_SCOPELESS` / `_WRITE_CAPABILITIES` / `_ADDITIVE_WRITE_CAPABILITIES` | + 4 / + 26 / — / — | 26 / 246 / 137 / 50 | 30 / 272 / 147 / 55 | policy and annotation tests that enumerate them |
| `_WRITE_PURPOSES` / `_IDEMPOTENT_REMOTE_CAPABILITIES` / `_CLIENT_BOUND_KEY_CAPABILITIES` | + 2 / + 6 / + 6 | 33 / 107 / 20 | 35 / 113 / 26 | remote annotation tests |
| `_FEATURE_BY_FAMILY` | + 5 | 26 | 31 | chatllm gateway tests |
| doc and plan pins | — | module, test-module, revision and head claims in `README.md`, `docs/architecture/00_ARCHITECTURE_INDEX.md`, `docs/architecture/system-context.md`, `docs/architecture/cpm-workbench.md`, `ops/runbooks/README.md`, `ops/runbooks/gateway-operations.md`, `ops/runbooks/mcp-and-cli-operations.md`, `ops/runbooks/managed-document-operations.md`, and the 2 contended plan documents `docs/plans/mcv-completion-plan.md`, `docs/plans/relationship-intelligence-implementation-plan.md` | re-measured at each package's own head | `test_readme_state_claims.py`, `test_spelled_counts_match_the_sets_they_name.py`, `test_claimed_test_counts_match_collection.py` and the plan guards |

### 15.3 Capability inventory (final)

Common to all 26: scopeless (`_SCOPELESS`, the `_requested_scope` scopeless arm); purpose
exactly one (the column); audit literal = the name (revision B); `feature_label` →
`schedule`; served only while the plane is effective (section 15.8). "Client write" = the 6
names of `PLANE_CLIENT_WRITE_CAPABILITIES`; "operator write" = the 4 of
`PLANE_OPERATOR_WRITE_CAPABILITIES` (`src/my_pa/domain/schedule/plane.py`; S6-3 pins both equal
to their `Capability` members). Rate bucket: **plane** = the section 8.3 client-channel write
budgets, refusal bound and byte quotas of the caller's writer bucket (none for the attested
operator); **—** = a read, unbounded beyond paging.

| # | Capability | Kind | Purpose | `facade_kind` | Additive | `idempotent_hint` / client-bound key | ChatLLM | Rate |
|---|---|---|---|---|---|---|---|---|
| 1 | `schedule_scenarios.create` | client write | `schedule_analysis_authoring` | `write` | yes | yes / yes | `DATA_CONDITIONAL` | plane |
| 2 | `schedule_scenario_versions.create` | client write | same | `write` | yes | yes / yes | `DATA_CONDITIONAL` | plane |
| 3 | `schedule_cpm_runs.create` | client write | same | `write` | yes | yes / yes | `DATA_CONDITIONAL` | plane + CPM units |
| 4 | `schedule_scenario_outputs.record` | client write | same | `write` | yes | yes / yes | `DATA_CONDITIONAL` | plane + 100 per version |
| 5 | `schedule_baselines.propose` | client write (operator may call, 15.4) | same | `write` | yes | yes / yes | `DATA_CONDITIONAL` | plane + pending caps |
| 6 | `schedule_baselines.withdraw` | client write (operator may call) | same | `write` | no | yes / yes | `DATA_CONDITIONAL` | plane |
| 7 | `schedule_baselines.approve` | operator write | `schedule_baseline_approval` | `operator` | no | no / no | `CONTROL_PLANE_EXCLUDED` | — (operator) |
| 8 | `schedule_baselines.reject` | operator write | same | `operator` | no | no / no | `CONTROL_PLANE_EXCLUDED` | — |
| 9 | `schedule_baselines.revoke` | operator write | same | `operator` | no | no / no | `CONTROL_PLANE_EXCLUDED` | — |
| 10 | `schedule_baselines.set_governing` | operator write | same | `operator` | no | no / no | `CONTROL_PLANE_EXCLUDED` | — |
| 11–26 | `schedule_scenarios.list`, `schedule_scenarios.read`, `schedule_scenario_versions.read`, `schedule_scenario_versions.activities`, `schedule_scenario_versions.relationships`, `schedule_scenario_versions.changes`, `schedule_cpm_runs.read`, `schedule_cpm_runs.activities`, `schedule_scenario_outputs.list`, `schedule_scenario_outputs.read`, `schedule_series.current`, `schedule_series.match_decisions`, `schedule_baselines.list`, `schedule_baselines.read`, `schedule_baselines.governing`, `schedule_baselines.compare` | read | `schedule_analysis_read` | `read` | — | no / no | `DATA_CONDITIONAL` | — |

The ChatLLM rationale for rows 7–10 is `_SCHEDULE_BASELINE_APPROVAL_EXCLUSION = "attested
operator baseline approval; the attested local operator only (operator decision
2026-11-03)"`. The `schedule_baselines.revoke` docstring's first line (its catalog
description) is "Revoke an approved, non-governing baseline; final for its publication, which
can never be approved again (attested local operator only)." (S6-U15, RR2-F02). The other 25
first lines are section 6.1's summaries verbatim.

### 15.4 S6-3-O01 resolved: operator proposals

The operator ruled that the attested operator **may** call `schedule_baselines.propose` (the
operator may always do what a client can). Representation, with no S6-1 or S6-2 change:

| Item | Rule |
|---|---|
| stored row | the `propose` event's provenance is the operator's (`local_operator`, `local_cli`/`local_web`, `user_confirmed`, no client id); `writer_bucket(...)` derives `None` for it, so S6-1 `BaselineEvent.writer_bucket` and `BaselineView.proposer_bucket` read `None` |
| bucket derivation (R10-F06) | **only** from server provenance: `bucket = writer_bucket(provenance.decision_channel, provenance.asserting_client_id)` with `provenance` the `PlaneProvenance` from `lineage_write_provenance` (step 3 of 15.10); `bucket` is `None` exactly for `PLANE_ATTESTED_DECISION_CHANNELS` (`local_cli`, `local_web`) and otherwise a string containing `"\x1f"` (a `local_unattested` stdio caller with no client id is `"local_unattested\x1f"`, a bucket of its own). No request field is consulted |
| request bucket | propose passes `bucket if bucket is not None else OPERATOR_PROPOSAL_BUCKET`, where `OPERATOR_PROPOSAL_BUCKET: Final = "operator"` (added to `src/my_pa/domain/schedule/plane.py`) is a string no client bucket can equal; S6-1 `ProposeRequest.writer_bucket` stays `str` |
| caps | the 50-per-Project cap counts and **binds** operator proposals (it counts every pending view; a Project invariant, not a client rate); the 10-per-bucket cap never binds the operator (`proposer_bucket == "operator"` matches no stored view). A refusal there is `rate_limited(BASELINE_ID)`; the operator's direct `approve` is never blocked (section 12.4) |
| withdraw | S6-1 `WithdrawRequest.writer_bucket` is `str \| None`: withdraw passes `bucket` unchanged, so `None` arises only for the attested operator, who may withdraw any pending proposal; a client passes its bucket and may withdraw only its own bucket's (`DENIED` → `denied(BASELINE_ID)`), so an operator proposal is withdrawable only by the operator |
| reads and labels | `authority: "proposed"`, `authoritative: false`, `proposer: {"kind": "operator", "channel": <channel>}` versus `{"kind": "client", "channel", "client_id"}` for a client (client id withheld from remote readers, section 15.6.4); never shown as a baseline or governing |
| budgets | none (attested operator, section 8.3); no refusal row |
| test | `test_operator_may_propose_and_only_the_operator_withdraws_it` (parametrized: `operator_proposes`, `operator_withdraws_client_proposal`, `client_withdraws_other_bucket`, `local_unattested`, `client_withdraws_operator_proposal`; section 15.16) |

### 15.5 Commands (inputs)

Each capability has one frozen-slots dataclass command in `src/my_pa/application/commands.py`
(class names: `CreateScheduleScenario`, `CreateScheduleScenarioVersion`, `CreateScheduleCpmRun`,
`RecordScheduleScenarioOutput`, `ProposeScheduleBaseline`, `WithdrawScheduleBaseline`,
`ApproveScheduleBaseline`, `RejectScheduleBaseline`, `RevokeScheduleBaseline`,
`SetGoverningScheduleBaseline`, `ListScheduleScenarios`, `ReadScheduleScenario`,
`ReadScheduleScenarioVersion`, `ListScheduleScenarioActivities`,
`ListScheduleScenarioRelationships`, `ListScheduleScenarioChanges`, `ReadScheduleCpmRun`,
`ListScheduleCpmRunActivities`, `ListScheduleScenarioOutputs`, `ReadScheduleScenarioOutput`,
`ReadScheduleSeriesCurrent`, `ListScheduleSeriesMatchDecisions`, `ListScheduleBaselines`,
`ReadScheduleBaseline`, `ReadGoverningScheduleBaseline`, `CompareScheduleBaseline`), built by
`_BUILDERS` as `Command(**payload)`; an unknown or missing key is `invalid_request` (no detail).
`__post_init__` checks types, identifier kinds, lengths and closed sets only; the 3 heavy
documents (`calendars`, `change_set`, `document`) are typed `object`, checked there only for
JSON type (`list`/`object`), and decoded in the handler after the refusal bound (section
15.10). Identifiers: `_schedule_id(value, IdKind.<kind>, SafeDetail.<field>)`. Text fields:
`normalize_display_text`, then the bound.

**Common to the 6 client writes:** `idempotency_key: str` (`^[A-Za-z0-9_-]{8,128}$`; required on
the command; remote callers never send it — it is server-stamped and client-bound),
`client_intent_id: str | None = None` (`CLIENT_INTENT_ID_PATTERN` of
`src/my_pa/domain/reports/publication.py`; it changes the stamped key so a deliberate repeat of
an identical request is a new write — the Reports precedent; it is part of the request digest
and stored nowhere else), `user_directed: bool = False` (the unverified S3.1 claim stored in
`user_directed_claim`; `True` from the attested operator is `invalid_request(USER_DIRECTED)`,
`lineage_write_provenance`). The 4 operator writes take `idempotency_key` only.

| Capability | Fields (type, bound, default) | Field refusals (`invalid_request(<detail>)` unless stated) |
|---|---|---|
| `schedule_scenarios.create` | exactly one of `from_publication_id` (`spub`), `from_baseline_id` (`sbl`), `from_version_id` (`sscv`); `name` (`N` rule, 1..200); `description` (≤ 2,000, default `None`); `label` (`VersionLabel`: `what_if`, `update`, `simulation_input`); with a publication or baseline, required: `minutes_per_source_unit` (int 1..`MAX_MINUTES_PER_SOURCE_UNIT`), `calendars` (list, 1..32 S6-1 calendar objects), `default_calendar` (a calendar id among them), `data_date_time` (`HH:MM`, default `"00:00"`); with `from_version_id` all 4 must be absent (the content is copied); `note` (≤ 2,000) for a fork | none or 2 origins: `FROM_PUBLICATION_ID`; bad id: `FROM_PUBLICATION_ID` / `FROM_BASELINE_ID` / `FROM_VERSION_ID`; `NAME`, `DESCRIPTION`, `LABEL`, `NOTE`; snapshot fields with a fork, or missing without: `MINUTES_PER_SOURCE_UNIT` / `CALENDAR` |
| `schedule_scenario_versions.create` | `scenario_id` (`sscn`); `expected_head_version_no` (int 1..499); `label`; `note` (≤ 2,000, default `None`); `change_set` (list of op objects, 1..5,000 ops, decoded by S6-1 `apply_change_set`) | `SCENARIO_ID`, `EXPECTED_VERSION`, `LABEL`, `NOTE`, `CHANGE_SET` (not a list) |
| `schedule_cpm_runs.create` | `version_id` (`sscv`) | `VERSION_ID` |
| `schedule_scenario_outputs.record` | `document` (the section 4.1 object, validated by S6-1 `validate_output` against the version binding; it names `version_id` and the optional `base_cpm_run_id`) | `OUTPUT` (not an object) |
| `schedule_baselines.propose` | `publication_id` (`spub`), `type` (`contract` \| `approved_update`), `reason` (1..2,000) | `PUBLICATION_ID`, `BASELINE_TYPE`, `REASON` |
| `schedule_baselines.withdraw` | `baseline_id` (`sbl`), `reason` | `BASELINE_ID`, `REASON` |
| `schedule_baselines.approve` | exactly one of `baseline_id` / `publication_id`; `type` (required with `publication_id`; optional with `baseline_id`, default the proposed type); `approval_reference` (1..500); `effective_from` (ISO date); `supersedes_baseline_id` (`sbl`, default `None`); `reason` | neither or both ids: `BASELINE_ID`; `BASELINE_TYPE`, `APPROVAL_REFERENCE`, `EFFECTIVE_FROM`, `SUPERSEDES_BASELINE_ID`, `REASON` |
| `schedule_baselines.reject` / `.revoke` | `baseline_id`, `reason` | `BASELINE_ID`, `REASON` |
| `schedule_baselines.set_governing` | `project_id` (`prj`), `baseline_id`, `expected_governing_baseline_id` (`sbl` or `null`, **required key**), `reason` | `PROJECT_ID`, `BASELINE_ID`, `GOVERNING`, `REASON` |
| `schedule_scenarios.list` | `project_id`; `series_id` (default `None`); `page_size` (1..100, 25); `cursor` (≤ 512) | `PROJECT_ID`, `SERIES_ID`, `PAGE_SIZE`, `CURSOR` |
| `schedule_scenarios.read` | `scenario_id`; page | `SCENARIO_ID`, page |
| `schedule_scenario_versions.read` | `version_id` | `VERSION_ID` |
| `schedule_scenario_versions.activities` / `.relationships` / `.changes` | `version_id`; page | `VERSION_ID`, page |
| `schedule_cpm_runs.read` | `cpm_run_id` (`scpm`) | `CPM_RUN_ID` |
| `schedule_cpm_runs.activities` | `cpm_run_id`; `critical_only` (bool, `False`); page | `CPM_RUN_ID`, `CRITICAL_ONLY`, page |
| `schedule_scenario_outputs.list` | `version_id`; page | `VERSION_ID`, page |
| `schedule_scenario_outputs.read` | `output_id` (`ssco`) | `OUTPUT_ID` |
| `schedule_series.current` | `series_id` | `SERIES_ID` |
| `schedule_series.match_decisions` | `project_id`; page | `PROJECT_ID`, page |
| `schedule_baselines.list` | `project_id`; `series_id` (default `None`); `status` (`BaselineStatus` value, default `None`); page | `PROJECT_ID`, `SERIES_ID`, `STATUS`, page |
| `schedule_baselines.read` | `baseline_id` | `BASELINE_ID` |
| `schedule_baselines.governing` | `project_id`; `as_of` (RFC 3339 instant, default `None`) | `PROJECT_ID`, `AS_OF` |
| `schedule_baselines.compare` | `baseline_id`; `to_publication_id`; `change_kind` (`ScheduleChangeKind`, default `None`); page | `BASELINE_ID`, `TO_PUBLICATION_ID`, `CHANGE_KIND`, page |

**Request digest and idempotency** (section 6.3, unchanged): `scenario_request_digest =
sha256(b"schedule-scenario-request-v1\n" + canonical({principal_id, capability, request without
idempotency_key}))`, with `request` the command's fields after normalization (identifiers as
given, text normalized, dates ISO, absent optionals `null`); the ledger key is
`(principal_id, capability, idempotency_key)`.

### 15.6 Outputs, cursors, disclosure, labels

#### 15.6.1 Write answers

Every write answers `replayed` (bool) and `labels` (15.6.3). A replay answers the stored
result read back by its ledger `result_id`, byte-identical in every field but `replayed`.

| Capability | Fields |
|---|---|
| `schedule_scenarios.create` | `scenario_id`, `version_id`, `version_no` (1), `origin` `{kind, publication_id, baseline_id, version_id}`, `content_sha256`, `content_size_bytes`, `activity_count`, `relationship_count`, `calendar_count`, `distribution_spec_sha256`, `snapshot_report` (the 6 counts, `null` for a fork) |
| `schedule_scenario_versions.create` | `scenario_id`, `version_id`, `version_no`, `parent_version_id`, the content fields, `change_report` `{op_count, ops_applied, relationships_removed, content_changed}` |
| `schedule_cpm_runs.create` | `cpm_run_id`, `version_id`, `engine_version`, `status`, `project_finish`, `result_sha256`, `created` (`false` for a natural-key hit) |
| `schedule_scenario_outputs.record` | `output_id`, `version_id`, `kind`, `iterations`, `payload_sha256`, `base_cpm_run_id` |
| baseline writes | `baseline_id`, `event_id` (or `governing_event_id`), `action`, `seq`, `label` (`approve` only), `status` (derived after the write) |

#### 15.6.2 Reads, orders, cursors

Reads page stored immutable rows or verified stored documents (hidden = absent: another
Principal's or a withheld row is `not_found`, never counted). Cursors are S5 `ScheduleCursor`s
(`src/my_pa/domain/schedule/cursor.py`): ≤ 512 characters, TTL 300 s, bound by
`schedule_cursor_binding(capability, principal_id, …filters)`; a cursor of another binding,
order or an expired one is `invalid_request(CURSOR)`. New orders (amendment S6-3-D08):

| Order (value) | Position | Used by |
|---|---|---|
| `scenarios_created_desc_id_desc` | `(created_at, scenario_id)` | `schedule_scenarios.list` |
| `versions_no_desc` | `(version_no,)` | `schedule_scenarios.read` (its version page) |
| `scenario_content_offset` | `(offset,)` into the canonical sorted array | `.activities` (key order), `.relationships` (predecessor, successor), `.changes` (applied order), `schedule_cpm_runs.activities` (key order; `critical_only` filters before paging and is bound) |
| `outputs_created_desc_id_desc` | `(created_at, output_id)` | `schedule_scenario_outputs.list` |
| `match_decisions_created_desc_id_desc` | `(created_at, decision_id)` | `schedule_series.match_decisions` |
| `baselines_created_desc_id_desc` | `(created_at, baseline_id)` | `schedule_baselines.list` (replaces `baselines_label_asc`: a proposal has no label) |

`schedule_baselines.compare` reuses the S5 `CHANGES` order. Read answers: `schedule_scenarios.read`
= the Scenario (name, description, origin, Project, Series, provenance) and a version page
(number, id, label, note, counts, digests, provenance); `schedule_scenario_versions.read` = the
version's metadata, settings, calendars, counts and digests (not activities); `schedule_cpm_runs.read`
= status, summary, issues, open ends and critical paths from the verified result;
`schedule_scenario_outputs.read` = the verified document; `schedule_series.current` = `{series_id,
current_publication_id | null, same_data_date_ambiguity, data_date, order_key}` by S6-1
`current_standard_update` over `currency_publications` and the effective Baseline publications;
`schedule_series.match_decisions` = decisions with outcome, reason, candidates, target and
resulting publication, `admission_skipped`; `schedule_baselines.list/read` = S6-1 `BaselineView`
fields (status, proposed and effective type, label, `effective_from`, `superseded`, governing
flag) plus provenance; `.read` adds the full event history; `schedule_baselines.governing` =
`{baseline_id | null, as_of, basis: "as_recorded"}` plus that Baseline's view;
`schedule_baselines.compare` = the S5 delta page labelled with the Baseline's label, effective
type and provenance, refused by S6-1 `compare_refusal`.

S5 read changes (section 11.2 step 2, 11.4): `schedule_series.list` and
`schedule_publications.list`/`.read` gain `series_kind: "standard" | "intake"` (additive);
`schedule_publications.read` of an intake publication gains `match_state: "pending" |
"decided" | "undecided"` (`pending` while non-terminal; `undecided` = terminal with no
decision, S6-2-U09/U10) and `match_decision_id`; `schedule_changes.list` naming an intake
publication on either side is `invalid_request(TO_PUBLICATION_ID)` (or `FROM_PUBLICATION_ID`).
These are served whatever the scenario switch (they describe S5 rows), read through 1 new S5
repository read (`intake_publication_ids`, 15.14).

#### 15.6.3 Labels and trust

| Answer | `labels` | Trust basis (`TrustLevel.MODEL_PROPOSED`) |
|---|---|---|
| scenario, version, change set | `{data_class: "schedule_scenario", authority: "client_authored", authoritative: false, reportable: false}` | `("schedule_scenario", "client_authored")` |
| CPM run | `{data_class: "schedule_cpm_run", authority: "server_computed", authoritative: false, reportable: false}` | `("schedule_scenario", "client_authored", "schedule_cpm", "my-pa-cpm-v1", "server_computed")` |
| output | `{data_class: "schedule_scenario_output", authority: "client_asserted", authoritative: false, reportable: false}` | `("schedule_scenario", "client_authored", "schedule_scenario_output", "client_asserted")` |
| baseline | `{data_class: "schedule_baseline", authority: "operator_approved" \| "proposed", authoritative: <effective>, reportable: false}`; `authoritative` is `true` only on an effective (approved, not revoked, eligible) Baseline | `("schedule_baseline", "operator_approved" \| "proposed")` |
| lineage node only (15.11.3a): publication, activity | `{data_class: "schedule_publication" \| "schedule_activity", authority: "source_bound_derived", authoritative: false, reportable: false}` | `trust: "source_bound_derived"` on the node |
| current, match decision | `{data_class: "schedule_series_current" \| "schedule_match_decision", authority: "server_computed", authoritative: false, reportable: false}` | `("schedule_series", "series-match-v1" \| "currency-v1", "server_computed")` |

Classification `PRIVATE_LOCAL`. Disclosure `scope`/`source_references`: the enrollment and source
of the root publication (the origin publication, the Baseline's publication or, for a fork, the
source Scenario's origin), built by the S5 disclosure helper; a list answer discloses the union
of its rows' roots.

#### 15.6.4 Provenance and client ids

Every plane row read shows `provenance {authority_class, decision_channel, acceptance_basis,
user_directed_claim, asserting_client_id}`; `asserting_client_id` is withheld (`null`) for a
remote reader by the S3.1 `withhold_client_ids` rule, shown to a local reader.

### 15.7 Refusal mapping (exhaustive)

#### 15.7.1 New `SafeDetail` members (359 → 396)

`SCENARIO_ID`, `FROM_VERSION_ID`, `FROM_BASELINE_ID`, `CPM_RUN_ID`, `CPM_RUN`, `OUTPUT_ID`,
`OUTPUT`, `CHANGE_SET`, the 14 `CHANGE_SET_<OP_ERROR>` (values `change_set_` + each S6-1
`ChangeOpError` value), `CONTENT_SIZE`, `MINUTES_PER_SOURCE_UNIT`, `CALENDAR`, `DATA_DATE_TIME`,
`NOTE`, `SERIES_AUTO`, `BASELINE_ID`, `BASELINE_TYPE`, `APPROVAL_REFERENCE`,
`SUPERSEDES_BASELINE_ID`, `GOVERNING`, `STORAGE_QUOTA`, `SCENARIO_WRITE_BUDGET`,
`SCENARIO_REFUSAL_BUDGET`, `CRITICAL_ONLY` (value = the lower-case name). Verified by D10 at the
base (revision R10-1): none of the 37 names or values, the 14 `change_set_*` values included,
equals an existing `SafeDetail` name or value.

#### 15.7.2 Mapping

| Source (S6-1 / S6-2 / handler) | Public answer |
|---|---|
| plane not effective (any of the 26) | `unsupported` (no detail), before any read; not counted |
| operator write by a non-attested caller (`attested_lineage_authority` raises) | `denied` (no detail); remote never sees the name (`unsupported`) |
| missing grant (`require_read_grant` / `require_write_grant`) | as today (`denied`) |
| refusal bound reached (15.10 step 4) | `rate_limited(SCENARIO_REFUSAL_BUDGET)`; not recorded |
| `client_write_counts` over 120/hour or 1,000/day per bucket, or 2,000/day per Principal | `rate_limited(SCENARIO_WRITE_BUDGET)` |
| `plane_byte_counts` + new bytes over 2 GiB total, 256 MiB/day per Principal, or 128 MiB/day per bucket; `scenario_and_version_counts` at 200 / 20,000; `output_count` at 100 | `rate_limited(STORAGE_QUOTA)` |
| client channel: `cpm_units_since(now − 1 h) + activity_count` over 2,500,000 (`admit_compute`; the attested operator is exempt, R10-F04) | `rate_limited(CPM_RUN)` |
| `CpmComputeBusyError` | `conflict(CPM_RUN)` |
| `PlaneReservation.REPLAYED` | the stored result, `replayed: true` |
| `PlaneReservation.CONFLICT` | `conflict(IDEMPOTENCY_KEY)` |
| `ScenarioHeadMovedError` (read or write transaction) | `conflict(EXPECTED_VERSION)` |
| `BaselineWriteRefusedError(CONFLICT_BASELINE_ID)` | `conflict(BASELINE_ID)` |
| `… (CONFLICT_GOVERNING)` | `conflict(GOVERNING)` |
| `… (CONFLICT_STATUS)` | `conflict(STATUS)` |
| `… (RATE_LIMITED_BASELINE_ID)` | `rate_limited(BASELINE_ID)` |
| `… (INVALID_TO_PUBLICATION_ID)` | `invalid_request(TO_PUBLICATION_ID)` |
| `… (DENIED)` | `denied(BASELINE_ID)` |
| `PlaneSubjectAbsentError` | `not_found(<subject>)`: `FROM_BASELINE_ID` / `FROM_VERSION_ID` (create), `PUBLICATION_ID` (propose, direct approve), `BASELINE_ID` (approve by id, reject, withdraw, revoke), `PROJECT_ID` (set_governing) |
| `ScheduleBaselineRaceError(code)` | `conflict(GOVERNING)` when `code` names the governing chain (`a_governing_event_seq_is_used_once`, `a_schedule_governing_event_extends_its_chain`), else `conflict(BASELINE_ID)` |
| G14 (b) / G15 (b) `check_violation` (wall-clock regression) | `internal_error` (retry) |
| `ScenarioIntegrityError`, any other `IntegrityError`/`DataError` on a plane write | `internal_error` |
| `snapshot_source` absent or another Principal's publication | `not_found(FROM_PUBLICATION_ID)`; an intake publication reads as absent (S6-2-D08) |
| publication present, not effective `complete`/`partial` | `conflict(STATUS)` |
| `SnapshotRefusalError(MINUTES_PER_SOURCE_UNIT \| CALENDAR \| DATA_DATE)` | `invalid_request(MINUTES_PER_SOURCE_UNIT \| CALENDAR \| DATA_DATE_TIME)` |
| `SnapshotRefusalError(ROWS)` | `conflict(FROM_PUBLICATION_ID)` (the stored publication cannot be snapshotted) |
| `ChangeSetRefusal(op_index, op_error)` | `invalid_request(change_set_<op_error>)`; `op_index` not disclosed (S6-U09) |
| new canonical content over 33,554,432 bytes | `invalid_request(CONTENT_SIZE)` |
| `OutputRefusal(<any reason>)` | `invalid_request(OUTPUT)` |
| output binding names another version, or a run not of that version | `invalid_request(OUTPUT)` (`binding`) |
| `get_*` / `load_*` / `version_by_number` → `None` on a read | `not_found(<the request's id field>)` |
| `ScheduleCursorError` | `invalid_request(CURSOR)` (the plane reads); **amended (FR10-F04, I10-A D-4):** `schedule_baselines.compare` delegates its delta page to the S5 `schedule_changes.list` order and command (section 15.6.2), so a bad compare cursor inherits S5's `conflict(CURSOR)`; its binding still differs by purpose (`schedule_analysis_read`), so S5 and compare cursors are not interchangeable |
| `compare_refusal(...)` | the `BaselineRefusal` rows above |
| `schedule_baselines.governing` with no governing event | not an error: `baseline_id: null` |
| `from_baseline_id` or `compare` naming a Baseline that is not effective (R10-F13): a proposal, or a rejected, withdrawn or revoked Baseline | `conflict(BASELINE_ID)` (section 7 "refused"); the handler pre-check answers exactly as the S6-2 write-side `_require_effective_baseline` does |
| the same, approved but its publication not effective `complete`/`partial` (`ineligible`) | `conflict(STATUS)` |

Refusals raised after step 4 of section 15.10 by a client channel are recorded with
`record_refusal(principal, writer, capability, error_code)` in their own transaction after the
refused one rolled back (S6-2-D03); `unsupported`, `denied` before step 4, and the refusal bound
itself are not.

### 15.8 Switch `MY_PA_SCHEDULE_SCENARIOS_ENABLED`

| Point | Rule |
|---|---|
| Settings | `src/my_pa/bootstrap/settings.py`: `schedule_scenarios_enabled: bool = False` after `schedule_enabled`, env `MY_PA_SCHEDULE_SCENARIOS_ENABLED`, comment in the `schedule_enabled` style; no `_check` refusal (effective is a conjunction, as program reporting with lineage) |
| effective | `schedule_enabled and schedule_scenarios_enabled and data_engine is None` |
| composition | `src/my_pa/bootstrap/gateway.py` builds `scenario_unit_of_work: Callable[[], ScenarioUnitOfWork] \| None` and `cpm_runner: ScenarioCpmRunner \| None` (`functools.partial(compute_and_store_cpm_run, work_engine)`) only when effective, and passes them to `ApplicationService` (`schedule_scenarios_enabled=`, `scenario_unit_of_work=`, `scenario_cpm_runner=`); `dispose_lease_engines` joins the gateway shutdown |
| `available_capabilities` | subtracts `_SCHEDULE_SCENARIO_CAPABILITIES` (the 26) unless `_scenario_plane_is_composed()` |
| handlers | each of the 26 calls `self._scenario_plane()` first (`unsupported`), the `_schedule_plane()` precedent |
| import | while not effective, after the E-10/E-12 refusals: `series_auto: true` → `invalid_request(SERIES_AUTO)`; a role-`baseline` request (with its 4 approval fields) → `invalid_request(PUBLICATION_ROLE)` (R10-F07; section 15.9) |
| lineage | the 6 schedule families are withheld (15.11.4) while not effective or while `MY_PA_LINEAGE_ENABLED` is off |
| ChatLLM | prerequisite `SCHEDULE_SCENARIOS` holds iff `planes.schedule and planes.schedule_scenarios` |
| remote planner | `apps/cli/remote_mcp.py` `_planes_from_settings` passes `schedule_scenarios=settings.schedule_enabled and settings.schedule_scenarios_enabled` |
| worker | `apps/worker.py` `_run`: for `--plane schedule`, the handler is `functools.partial(process_schedule_publication, scenario_plane_effective=settings.schedule_enabled and settings.schedule_scenarios_enabled)` (S6-2-D12); the plane refusal `plane schedule disabled` is unchanged (the scenario switch alone never starts a worker) |
| off → on → off | changes no row: every gate is a read-time filter or a refusal before any write (`test_scenario_switch_changes_no_row`) |

### 15.9 Import additive fields (sections 11.2, 12.3; lifting S6-2-D04 for role `baseline`)

`ImportSchedulePublication` gains, all defaulted: `series_auto: bool = False`,
`series_name_if_new: str | None = None`, `approval_reference: str | None = None` (1..500),
`effective_from: str | None = None` (ISO date), `reason: str | None = None` (1..2,000). The
baseline type is the existing `baseline_kind` field (values `contract`, `approved_update`); no
second `baseline_type` field is added (S6-3-D14). `import_request()` builds:

| Case | Rule (in order) |
|---|---|
| Series form | exactly one of `series_id`, `series_name`, `series_auto` (else `invalid_request(SERIES_ID)`, today's detail); `series_name_if_new` only with `series_auto` (`SERIES_AUTO`) |
| intake names | a `series_name` or `series_name_if_new` whose key `is_intake_name_key` → `invalid_request(SERIES_NAME)` |
| auto form | `series_auto` with role ≠ `update`, any of `baseline_kind`, `approval_reference`, `effective_from`, `reason`, or `supersedes_publication_id` → `invalid_request(SERIES_AUTO)` |
| role `reference`, kind `working` | refused by the enum lockstep (`PUBLICATION_ROLE`, `BASELINE_KIND`) whatever the switches |
| role `baseline` | requires `baseline_kind`, `approval_reference`, `effective_from`, `reason` (missing → that field's detail: `BASELINE_KIND`, `APPROVAL_REFERENCE`, `EFFECTIVE_FROM`, `REASON`); builds `ScheduleImportApproval` |
| role `update` | any of the approval fields → that field's detail; `baseline_kind` → `BASELINE_KIND` (today) |

**Where the gates run (amended by R10-F01).** The command cannot see the switch, so the plane
gates run in `ScheduleApplication.import_publication` (`src/my_pa/application/schedules.py`),
which gains the keyword `scenario_plane_effective: bool` (the service passes
`self._scenario_plane_is_composed()` from `_schedule_publications_import`, which stays a thin
call). In order: (1) the E-10 remote refusal (`unsupported`) and (2) the E-12 attestation,
keeping its value: `authority = attested_lineage_authority(authorization)` (`denied`), both
unchanged and first, so a remote or unattested caller never learns about the plane; (3)
`request = command.import_request()`; (4) not effective and `request.series_auto` →
`invalid_request(SERIES_AUTO)`; (5) not effective and `request.approval is not None` →
`invalid_request(PUBLICATION_ROLE)` (R10-F07, S6-3-D14: the refused value is the role, the S6-2-D04
answer callers already see, unchanged across the S6-2 → S6-3 deploy while the plane stays off;
`import_request()` has already refused, whatever the switch, a role-`baseline` request lacking
any approval field with that field's detail, so this gate only ever sees fully specified
requests); (6) `admit_publication(principal_id, request, digest, operator_channel=
authority.decision_channel.value if request.approval is not None else None)`. Keying on
`request.approval` keeps `test_no_baseline_is_derived` green: no `"baseline"` literal, no
`BASELINE` identifier and no `previous`/`current_baseline` name enters
`src/my_pa/application/schedules.py` or `src/my_pa/domain/schedule/compare.py`; the role and
field checks live in `commands.py`. `schedules.py` is owned by I10-A (15.15), which also renders
the 15.6.2 S5 read fields there. Retirement stays one-way: `reference` and
`working` never return; switching the plane off again refuses new role-`baseline` imports but
changes no Baseline already approved.

### 15.10 Policy, authorization and bounds

**Order of one plane write** (handler code in the new module
`src/my_pa/application/schedule_scenarios.py`, class `ScheduleScenarioApplication`, called from
thin `ApplicationService._schedule_scenarios_create`, … handlers):

1. `_scenario_plane()` (`unsupported`). Policy (`evaluate`: operator-only, purpose, scope) has
   already run in `authorize`.
2. Grant: `require_write_grant` (writes) / `require_read_grant` (reads), as S5b-2.
3. Authority: operator writes `attested_lineage_authority(authorization)` (`denied`); every write
   then `lineage_write_provenance(authorization, user_directed=command.user_directed)` →
   `PlaneProvenance` (no request field carries the class, channel, client or basis).
4. Refusal bound (client channels only): a short read transaction, `refusal_count(principal,
   writer, now − 1 h) ≥ 120` → `rate_limited(SCENARIO_REFUSAL_BUDGET)`, before any heavy
   document is decoded — for every write, `schedule_cpm_runs.create` included (it runs before
   `compute_and_store_cpm_run`, R10-F02). **Counting scope (amendment of section 8.3, S6-3-D13,
   R10-F11):** refusals answered in steps 1–4 (`unsupported`, a missing grant `denied`, an
   authority `denied`, the bound itself) and normalization refusals are never counted; every
   refusal from step 5 on is.
5. Decode and compute outside any write transaction (S6-2-D14): `calendars` → S6-1 calendars,
   `snapshot_source` + `snapshot_from_publication`; or the head read (CAS pre-check) +
   `load_content` + `apply_change_set`; or `validate_output` against the stored binding;
   canonical bytes, size check, `compress_canonical`.
6. Write transaction (`ScenarioUnitOfWork`): `lock_principal`; `reserve_request` (replay /
   conflict return here, consuming nothing); **client channels:** `client_write_counts`,
   `plane_byte_counts` (+ this write's new canonical bytes), `scenario_and_version_counts`
   (Scenario create, version append), `output_count` (outputs) — each over its bound raises;
   then the insert (`insert_scenario` / `fork_scenario` / `append_version` / `insert_output` /
   `write_baseline`); `complete_request(…, stored_bytes=<new canonical bytes>)`.
7. Any refusal raised in steps 5–6 rolls the transaction back (S6-2-D20) and, for a client
   channel, is recorded by `record_refusal` in its own transaction.

**CPM runs (amended by R10-F02, R10-F04).** The handler runs steps 1–4, then
`compute_and_store_cpm_run`, whose `admit_write(repository, principal_id)` keyword (S6-3-D10) is
called **twice**: (a) **only on the compute path** (amended by R10-N01): after step 1's ledger
probe and natural-key probe have **both** found nothing, and immediately before the leased
compute, inside a short transaction under P (`lock_principal`, then the read-only
`client_write_counts` and `plane_byte_counts` with **0 new bytes**), so it refuses only a client
that is already at or over a write budget or a byte quota, and is never reached by a replay
(which returns the stored run, consuming nothing) or a natural-key hit (which consumes a write but
no bytes and is admitted under its step-5 check); a client over its write budget or byte quota is
thus refused without computing (`test_over_budget_cpm_run_never_computes`, P3-41); and (b) authoritatively in its step 5 after a
`RESERVED` reservation and before the insert, with the result's actual canonical size (the
step-6 rules). A natural-key hit completes a ledger row with `stored_bytes = 0`, so it consumes a
write but no bytes. `admit_compute(used, requested)` refuses a client channel when `used +
requested > 2,500,000` (`rate_limited(CPM_RUN)`) and **admits the attested operator whatever
`used` is** (R10-F04, replacing D20); the operator's runs still count in `cpm_units_since`, so
heavy operator use reduces client headroom (the operator's own choice). The per-run operation
budget (`CPM_OPERATION_BUDGET`, section 3.11) and the 1-concurrent-compute lease apply to every
caller. A compute refused only by the step-5 re-check (a race with a concurrent write of the same
bucket) is computed and not stored, so it is not counted in `cpm_units_since` (S6-3-U06).

| Bound (section 8.3 / 2.10) | Counted where | Applies to |
|---|---|---|
| 120/hour, 1,000/day per bucket; 2,000/day per Principal | S6-2 read under P, S6-3 limit (step 6) | the 6 client writes together; replays consume nothing |
| 120 refusals/hour per bucket | S6-2 refusal ledger read before decode (step 4); a soft bound (R9-F13) | client channels |
| 128 MiB/day per bucket; 2 GiB total and 256 MiB/day per Principal | S6-2 read under P (step 6) | client channels; forks count their copied bytes (S6-U08) |
| 200 Scenarios, 20,000 versions per Principal; 100 outputs per version | S6-2 read under P | client channels |
| 2,500,000 CPM activity-units/hour | `admit_compute` under the lease (counts every stored run of the Principal) | client channels; the attested operator is admitted whatever the count (R10-F04) |
| per-run operation budget; 1 concurrent compute per Principal | S6-1 `run_cpm` budget; lease C + process lock | every caller |
| 50 pending per Project, 10 per bucket per Project | S6-1 `decide_baseline_write` under J | 15.4 |

The attested operator is never budgeted, never quota-limited and never held to the hourly
CPM-units bound (section 8.3; it still meets the DB CHECK bounds, the per-run operation budget and
the compute lease) and is never recorded as refused.

### 15.11 Lineage (section 5; ADR-015 decision 17)

#### 15.11.1 Public vocabulary (`src/my_pa/domain/lineage/vocabulary.py`)

`RecordFamily` appends `SCHEDULE_PUBLICATION`, `SCHEDULE_ACTIVITY`, `SCHEDULE_BASELINE`,
`SCENARIO`, `SCENARIO_VERSION`, `SCENARIO_OUTPUT` (7 → 13); `RelationType` appends `CONCERNS`,
`DELAYS`, `MITIGATES` (8 → 11); `RELATION_MATRIX` and `RECORD_FAMILY_ID_KINDS` gain exactly the
section 5.2 / 14.7.4 entries; `CONTESTABLE_RELATIONS` gains the 3 (7 → 10); `NativeVirtualEdge`
appends the 8 section 5.2 edges (1 → 9); `LINEAGE_FAMILY_READS` gains the section 5.1 read sets
(7 → 13 keys); `LINEAGE_READ_GENERATION = 2` (S6-2-D02). The stored maps stay the source of the
DB CHECKs; FAST `test_storage_vocabulary_equals_the_public_vocabulary` replaces the S6-2
superset pin with equality (string-keyed, both directions), so no revision is needed (the
CHECK texts already admit them). The `records.associations.assert` input enums widen with the
enums (a published-schema change; any schema digest pin moves).

#### 15.11.2 Endpoint sharing and linkability

`RecordLineageRepository.share_endpoint` (SQL, `src/my_pa/infrastructure/persistence/record_lineage.py`,
Principal-partitioned, in the S1 `(family token, identifier)` order) handles the 6 families on
the **general** unit of work's connection (reads only; no plane or S5 row is written;
`ScenarioUnitOfWork` stays off `UnitOfWork`). **No row lock for the 6 families (amendment of
section 5.3, S6-3-D21, R10-F12):** they are read with a plain `SELECT`, not `FOR SHARE`. Each
named row is immutable for linkability: the 5 plane/S5 tables other than
`schedule_publications` are append-only (G1/F-triggers refuse `UPDATE`/`DELETE`), and a
publication is linkable only in a terminal `complete`/`partial` status, which never changes.
Every fact either is fixed once linkable (terminal publication status — the S5b-1 trigger
`a_schedule_publication_follows_its_lifecycle` refuses any update of a terminal row; the frozen
accepted run; set-once row links — `a_schedule_row_changes_only_by_linking`; an intake mark written
only in the admitting transaction — `_mark_intake` from `admit_publication` — and refused on a
Series holding another publication — `an_intake_series_holds_only_its_publication`) or moves only
toward linkable. The one change away from linkable is a `revoke` event append, which takes no row
lock on `schedule_baselines`, so `FOR SHARE` never serialized against it, and a link read before
the revoke commits is the serial order link-then-revoke (RR1-F08 "at assert time"; R10-N03,
verified by R10 re-review 1). `FOR SHARE` would need `UPDATE` privilege, which repository truth does not guarantee to
the runtime role on these tables (R3-29). **I10-B precondition:** the database-tier test
`test_share_endpoint_needs_only_select_on_the_schedule_tables` runs `share_endpoint` for **every**
family, the publication family included, as a role holding exactly P-check ∪ Q8 privileges (no
`UPDATE` on the 5 tables other than `schedule_publications`); if
any implementation path needs more (a lock, an `UPDATE`), I10-B stops and reports: a grant is a
schema/operator change, never added silently. `LineageEndpoint` gains
`schedule_linkable: bool = False` and `baseline_approved: bool = False`:

| Family | Row shared | `schedule_linkable` | Other |
|---|---|---|---|
| `schedule_publication` | `schedule_publications` | effective `complete`/`partial` and not intake | — |
| `schedule_activity` | `schedule_activities` (Stable Activity) | visible (S5b-1 U-03: a row of an accepted run of a `complete`/`partial` publication) and its Series is not intake | — |
| `schedule_baseline` | `schedule_baselines` | exists | `baseline_approved` = an `approve` and no `revoke` event (read in the same statement) |
| `scenario` / `scenario_version` / `scenario_output` | the plane row | exists | — |

`require_linkable` refuses `invalid_request(ENDPOINT)` when `schedule_linkable` is false; and
a new relation-level check refuses `originated_from` from a `schedule_baseline` whose
`baseline_approved` is false with `invalid_request(RELATION_TYPE)` (RR1-F08). Evidence rules:
`_EXACT_ROLE_RULES` gains `DELAYS → CORROBORATES` and `MITIGATES → CORROBORATES` (≥ 1
exact-version anchor); `concerns` none. Provenance, budgets (the S3.1 120/hour, 1,000/day
per bucket, 2,000/day per Principal lineage budgets — not the plane's), idempotency, replay and
"clients never remove accepted lineage" are unchanged; lineage writes need no operator
attestation (ADR-015 amendment, S3.1).

#### 15.11.3 Read-side resolvers and native virtual edges

`src/my_pa/infrastructure/persistence/record_lineage.py` `_NATIVE` (family → table, identifier
column; read by `share_endpoint`, `native_members` and `resolve_records`) gains the 6 families'
tables (`schedule_publications`, `schedule_activities`, `schedule_baselines`,
`schedule_scenarios`, `schedule_scenario_versions`, `schedule_scenario_outputs`), and the
application resolvers in `src/my_pa/application/record_lineage.py` render one summary per family
(fields: publication `series_id`, `data_date`, effective status, `series_kind`; activity
`published_activity_id`, `activity_name`, `series_id`; baseline `label`, status, effective type;
Scenario `name`, `series_id`; version `scenario_id`, `version_no`, `label`; output `kind`,
`iterations`, `version_id`), each labelled per 15.6.3 and with `MODEL_PROPOSED` for the plane
families. The 8 native virtual edges are emitted by the related/lineage reads from the section
14.5 columns and are never accepted in an assertion (`invalid_request(RELATION_TYPE)`).
**Superseded by section 15.11.3a** (S6-3-B01): the summary fields above are replaced by the
minimal wire shape there; `_NATIVE` and the assertion refusal stand (implemented by I10-B).

#### 15.11.3a Read shapes of schedule nodes and virtual edges (addendum for S6-3-B01; owner I10-C)

Written at `bb6bbe8d` (I10-A, its corrective IA-C1 and I10-B implemented), after I10-B stopped because
`LineageNodeView`, `VirtualEdgeView` and `LineagePathEdgeView`
(`src/my_pa/contracts/v1/record_lineage.py`) admit no schedule shape. Today a schedule node is
emitted bare (`family`, `record_id`, `depth`, `reached_from`, `reached_via`) and no schedule
virtual edge is emitted. This addendum is the only change to those shapes; everything else in
`records.lineage` and `records.lineage.related` is unchanged.

**1. Node key.** `LineageNodeView` (and so `RelatedRecordView`) gains one optional key,
`schedule`, present **iff** the node's family is one of the 6 schedule families and absent (not
serialized) otherwise. Its value is an object with exactly these keys (no other key, no payload
content, no name, no client-authored text, no identifier of another record, no provenance):

| Family | `schedule` keys (all always present) |
|---|---|
| all 6 | `data_class`, `authority`, `authoritative` (bool), `reportable` (always `false`), `trust` (`TrustLevel` value) |
| `schedule_publication` | + `data_date` (ISO date), `status` (effective `SchedulePublicationStatus`), `series_kind` (`standard` \| `intake`) |
| `schedule_activity` | + `published_activity_id` (the exact published Activity ID, the activity's identity key) |
| `schedule_baseline` | + `status` (`BaselineStatus` as of N, item 6), `label` (`BL-<n>` or `null`), `effective_type` (`contract` \| `approved_update` or `null`), both the `BaselineView` fields as of N (`null` only while never approved) |
| `scenario` | + `origin_kind` (`publication` \| `version`) |
| `scenario_version` | + `version_no`, `version_label` (`VersionLabel`) |
| `scenario_output` | + `kind` (`OutputKind`), `iterations` |

Label values: `schedule_publication` and `schedule_activity` → `data_class` = the family token,
`authority: "source_bound_derived"`, `authoritative: false`, `trust: "source_bound_derived"`;
`schedule_baseline` → exactly the implemented plane read `_baseline_labels`
(`src/my_pa/application/schedule_scenarios.py`; amended by R10-S02): `data_class:
"schedule_baseline"`, `authority: "operator_approved"` iff the S6-1 `BaselineView.effective_type`
as of N is not `null` (approved, ineligible or revoked), else `"proposed"` (proposed, rejected,
withdrawn), `authoritative` = `BaselineView.effective` (status `approved`), `trust:
"model_proposed"`; `effective_type` and `label` are the `BaselineView` fields as of N, so a
revoked or ineligible Baseline keeps its type and `BL-<n>`; `scenario`, `scenario_version` → `data_class:
"schedule_scenario"`, `authority: "client_authored"`; `scenario_output` → `data_class:
"schedule_scenario_output"`, `authority: "client_asserted"`; these 3 `authoritative: false`,
`trust: "model_proposed"`. `reportable` is `false` everywhere (OD-08). Labels sit **on the node**
(inside `schedule`); the answer-level `Trust` and disclosure of the lineage reads are unchanged.
Client ids: none is carried (no provenance on a node), so the I10-A D-9 remote withholding has
nothing to withhold here; provenance stays on the plane reads. Names are not carried: a client
reads them with the family's own read grant (`LINEAGE_FAMILY_READS`).
**Serialization (R10-S03):** `schedule` is a union of 6 strict per-family models
(`StrictModel`, `extra="forbid"`, one per family, validated against the node's family); the base
node dump keeps `exclude_none=True` but excludes `schedule`, and `to_canonical_dict` inserts
`schedule` from its own dump with `exclude_none=False` (as `reached_from`/`reached_via` are
inserted), so every key in the table is always present, `null` included (for example a proposed
Baseline's `label: null`, `effective_type: null`).

**2. Virtual edge endpoints.** New `NATIVE_VIRTUAL_EDGE_ENDPOINTS: Final[Mapping[NativeVirtualEdge,
tuple[RecordFamily, RecordFamily]]]` in `src/my_pa/domain/lineage/vocabulary.py` (9 entries,
exact), read by `VirtualEdgeView._check` (which today admits only note → Meeting):

| Edge | From → to | Source (section 14.5) |
|---|---|---|
| `meeting_note_version_of` | `meeting_note_version` → `meeting` | unchanged |
| `scenario_version_of` | `scenario_version` → `scenario` | `schedule_scenario_versions.scenario_id` |
| `scenario_version_parent` | `scenario_version` → `scenario_version` | `.parent_version_id` |
| `scenario_based_on_publication` | `scenario` → `schedule_publication` | `schedule_scenarios.origin_publication_id` |
| `scenario_based_on_baseline` | `scenario` → `schedule_baseline` | `.origin_baseline_id` |
| `scenario_forked_from_version` | `scenario` → `scenario_version` | `.origin_version_id` |
| `scenario_output_of` | `scenario_output` → `scenario_version` | `schedule_scenario_outputs.version_id` |
| `schedule_baseline_designates` | `schedule_baseline` → `schedule_publication` | `schedule_baselines.publication_id` |
| `schedule_baseline_supersedes` | `schedule_baseline` → `schedule_baseline` | the `approve` event's `supersedes_baseline_id`, as of the read (item 6) |

**3. Emission, not traversal.** A schedule virtual edge is emitted **only when both endpoints are
nodes of the same answer** (already reached through typed links, visible, not withheld); it is
never followed, so it reaches no new node, adds no depth and is never a path step:
`LineagePathEdgeView` with `edge: "virtual"` keeps admitting only `meeting_note_version_of`
(validator made explicit). This keeps hidden = absent (no unreached or withheld record is named),
adds no expansion cost and leaves every existing traversal, cursor and path unchanged. Proposed
deferral (S6-3-U08): traversal through schedule virtual edges is not built.

**4. Order (extends the S1 order).** `virtual_native_edges` (lineage) and `virtual_edges`
(related) list the `meeting_note_version_of` edges first, in their existing order, then the
schedule edges sorted by `(edge_type value, from.family value, from.record_id, to.family value,
to.record_id)`.

**5. Budgets and paging.** Each schedule edge is admitted through the same whole-query budget as
a note edge (`budget.admit(edges=1, size=256)`, counted in `MAX_LINEAGE_EDGES` and the 400-edge
answer cap); when the budget refuses, emission stops and the answer carries the existing
budget-exhausted completeness qualifier. A node's `schedule` object is admitted with its node, its
size measured as `_size(<the schedule document>)` (`src/my_pa/application/record_lineage.py`),
within `MAX_LINEAGE_BYTES` (R10-S06: a `published_activity_id` may be 256 characters); it never
adds a node. **Paging key (R10-S01):** `_item_key` keys a schedule virtual edge
`v:<edge_type>:<from.family>:<from.record_id>:<to.family>:<to.record_id>` (about 120 characters,
within the cursor bound), because a schedule edge's source is not unique (a version has
`scenario_version_of` and `scenario_version_parent`; a Baseline-seeded Scenario has both
`scenario_based_on_*`; a Baseline may designate and supersede); the `meeting_note_version_of` key
stays `v:<from.record_id>`, so every existing cursor is byte-identical. **Position grammar
(amendment of S3 section 5, R10-T01):** `_lineage_position` (`src/my_pa/application/record_lineage.py`)
accepts after `v:` either `<note_version_id>` (validated as a meeting note version, unchanged) or
`<edge_type>:<from.family>:<from.record_id>:<to.family>:<to.record_id>`, where `edge_type` is a
schedule `NativeVirtualEdge` (never `meeting_note_version_of`), the 2 families equal
`NATIVE_VIRTUAL_EDGE_ENDPOINTS[edge_type]`, and each id validates for its family
(`RECORD_FAMILY_ID_KINDS`); anything else is `invalid_request(CURSOR)`.
`test_schedule_virtual_edges_page_without_repeat` (a page-size-1 walk) decodes such a cursor. In `records.lineage` and
`records.lineage.related` the edges join the bounded item sequence after the note edges and page
with it under that key.

**6. As of (amended by R10-S04).** Schedule nodes are cut exactly like the other native families:
no creation-time filter applies to a node (a schedule node is reached only through a typed link
asserted while its endpoint was linkable; `schedule_publications` has no `created_at`). A
Baseline's `status`, `label`, `effective_type` and its `schedule_baseline_supersedes` edge are
derived by S6-1 `baseline_status` over the Project's events with `recorded_at ≤ N` (section 12.1
"as recorded"), with `eligible_publication_ids` as of N: a publication counts as eligible iff its
status is `complete`/`partial` **and** its `completed_at ≤ N`, so a fixed `known_at` reproduces
the same answer and `related_sha256`; a `scenario_based_on_baseline` edge is a fixed column. A
publication node's `status` is its effective status at read time, equal to its status at N
(S6-3-U09).

**7. `related_sha256`.** The digest covers the new key and edges (it is computed over the whole
bounded result; the prefix stays `lineage-related-v1`). Consequence (I10-B B-06 extended): a
related claim stored before this change whose result holds a schedule node or edge reads
`changed_since_read`; since no S6-3 build is deployed, no real stored claim is affected (S6-3-U10).

**8. Compatibility.** Additive only: one optional node key that appears only on the 6 new families
(which no pre-S6-3 client has seen) and 8 new `edge_type` values on edges between them. Every
existing node, edge, key and order is byte-identical, so an old JSON client and the remote/ChatLLM
façade are unaffected. The web decoders are closed, so they move in lockstep (I10-C):
`web/src/lib/api/decode/capabilities/records.lineage.ts` (the only closed lineage decoder; no
web decoder exists for `records.lineage.related`) accepts `schedule` with exactly the 15.11.3a keys
per family and the 9-entry endpoint table; the UI label maps gain the 8 edge types and the label
enumeration gains `source_bound_derived`, `schedule_publication` and `schedule_activity`
(R10-S06); `web/src/lib/api/decode/fixtures/python/success.json` and the decoder
tests are regenerated; vitest and `tsc` run.

**9. Tests (I10-C).** Database tier (`tests/database/test_schedule_scenario_lineage.py`):
`test_schedule_nodes_carry_exactly_their_summary[<family>]` (6), `test_schedule_virtual_edges_are_emitted_between_reached_nodes[<edge>]` (8),
`test_schedule_virtual_edge_to_an_unreached_node_is_not_emitted`,
`test_schedule_virtual_edges_page_without_repeat` (page size 1 over a version with 2 edges and a
Baseline-seeded Scenario: every item exactly once), the `[schedule_baseline]` summary case
parametrized over `proposed`, `approved`, `ineligible`, `rejected`, `withdrawn`, `revoked`
(asserting the null keys of a proposal are present),
`test_schedule_virtual_edges_are_never_traversed`,
`test_schedule_baseline_node_is_as_of_the_native_cut` (including an import-time approval whose
publication completes after N: `ineligible` at N),
`test_withheld_schedule_family_emits_no_node_or_edge`,
`test_related_sha256_covers_schedule_summaries_and_edges`; FAST
(`tests/unit/test_schedule_lineage_vocabulary.py`, contract model tests):
`test_virtual_edge_endpoint_table_is_exact`, `test_node_schedule_key_is_present_iff_schedule_family`,
`test_virtual_path_step_admits_only_the_note_edge`; web: the decoder tests above.

**10. Ownership.** I10-C (15.15) owns `src/my_pa/contracts/v1/record_lineage.py`, the read paths of
`src/my_pa/application/record_lineage.py` (node rendering, `_virtual_edges`, `_item_key`, `_lineage_position`, related
digest inputs), the summary columns read in `src/my_pa/infrastructure/persistence/record_lineage.py`
(read-only, Principal-partitioned, plain `SELECT` per S6-3-D21), the endpoint table in
`src/my_pa/domain/lineage/vocabulary.py`, the web decoders, labels and fixture, and these tests.

#### 15.11.4 Withheld families

`lineage_visibility(grants, capability, *, withheld_families=frozenset())`: the service passes
the 6 schedule families while the plane is not effective (and the lineage plane itself is off
as today). A withheld family behaves as an unreadable one (S3 section 6.4): a new assertion
naming one answers as absent (`not_found` with the endpoint's detail), reads drop its endpoints
with no hidden count. `confirm`, `end`, `contest` of an existing link and Issue close/reopen act
on the link identity and head, re-validate only visible endpoints and record a withheld endpoint
by its stored identifier (section 5.1, R8-F10).

#### 15.11.5 Issue close gate

A `client_identified` schedule-family link to an Issue holds its close until confirmed (S3.1
section 4.6) and is always confirmable (15.11.4); Issue close/reopen/backfill stay
operator-gated.

#### 15.11.6 OD-08 guards

- AST guard (FAST, `tests/architecture/test_schedule_scenarios_capability_scope.py::test_scenario_data_reaches_no_program_surface`):
  nothing under `src/my_pa/application/program_*.py`, `src/my_pa/domain/program/` or
  `src/my_pa/contracts/v1/programs.py` imports `src/my_pa/application/schedule_scenarios.py`,
  `src/my_pa/domain/schedule/`, the S6-2 persistence modules or names a plane table; no
  `ProgramFamily` member or `METRIC_CATALOGUE` metric names a schedule or scenario token.
- Manifest pin: `src/my_pa/domain/intelligence/source_manifest.py` gains
  `MANIFEST_LINEAGE_FAMILIES: Final = frozenset({<the 7 pre-S6 families>})`; `_block_seeds`,
  `lineage_server_counts` and `lineage_section` admit only it (S6-D13, S6-U04);
  `test_manifest_lineage_section_is_pinned_to_seven_families`.

### 15.12 Surfaces

#### 15.12.1 ChatLLM `chatllm-data-v13`

`CHATLLM_DATA_PROFILE_VERSION = "chatllm-data-v13"`; new `SCHEDULE_SCENARIO_DATA_NAMES` (the 22
client-usable names) in `_DATA_CONDITIONAL`; prerequisite member `SCHEDULE_SCENARIOS` (comment
"Schedule Scenarios S6-3 (chatllm-data-v13): `MY_PA_SCHEDULE_SCENARIOS_ENABLED`, which stacks on
the Schedule switch"); `_prerequisite_of` returns it for those names (after `SCHEDULE`);
`_prerequisite_holds` returns `planes.schedule and planes.schedule_scenarios` (exhaustive rule
KLP-AC-105 kept); `ChatLLMCompositionPlanes.schedule_scenarios: bool = False`; the 4 operator
names in `_CONTROL_PLANE_EXCLUDED` with `_SCHEDULE_BASELINE_APPROVAL_EXCLUSION`. Targets: 15.2.
**Old clients and DV-01:** the version is checked only as the `profile-*` CLI argument
(`apps/cli/remote_mcp.py` `_run_profile_command`), never stamped on a grant: a client
provisioned at v10, v11 or v12 keeps every grant and stays healthy while the scenario plane is
off (its desired set is unchanged); with the plane on, `profile-diff` reports as missing the 22
plus whichever of the 6 S5b-2 reads and the 11 v12 Reports names the client does not hold yet
(22, 28, 33 or 39; the set rule of 15.17 step 2, R10-F05, R10-N02) until the operator runs `profile-apply --profile-version chatllm-data-v13`; calls to an
ungranted name are denied. `profile-*` with `chatllm-data-v12` is refused after the bump. No
MCP database profile, role or opt-in changes (DV-01; T6-18).

#### 15.12.2 Remote

`_WRITE_PURPOSES` + `SCHEDULE_ANALYSIS_AUTHORING`, `SCHEDULE_BASELINE_APPROVAL` (comment in the
file's style); `_CLIENT_BOUND_SCENARIO_WRITES` (the 6) joins `_IDEMPOTENT_REMOTE_CAPABILITIES`
and the `_CLIENT_BOUND_KEY_CAPABILITIES` derivation, and `is_remote_idempotent`; the 4 operator
names are withheld by `remote_tool_names` (never in `_REMOTE_OPERATOR_IDENTITY_CAPABILITIES`).
Remote client writes still need the remote writes switch and the client's writes flag.

#### 15.12.3 Façade and catalog

`_FEATURE_BY_FAMILY` + `schedule_scenarios`, `schedule_scenario_versions`, `schedule_cpm_runs`,
`schedule_scenario_outputs`, `schedule_baselines` → `schedule`. The catalog `TOOLS` gains the
26 automatically from the `Command` union; `my_pa.describe` lists the eligible client-usable
names (feature `schedule`, kinds `write`/`read`); `my_pa.write` / `my_pa.read` dispatch them;
an operator name is absent from `describe` and `unsupported` through `my_pa.write` and
`my_pa.operator` for a remote client.

#### 15.12.4 Web fixture

`web/src/lib/api/decode/fixtures/python/success.json` regenerated from the live dump (26 new
`capabilities.get` manifest rows; `worker_planes` unchanged: the fixture composition has the
switches off); `web/src/contracts/gateway.json` unchanged (no web route). Frontend checks in
`web/`: `npm ci` if needed, `npm run lint`, `typecheck`, `test`, `contract`, `build` (the S5b-2
section 3.13.6 precedent). The regenerated file is tracked already (no `git add -f` needed;
verify with `git ls-tree`).

#### 15.12.5 Client guidance

A section "Schedule scenarios and schedule lineage" in `docs/operations/record-lineage-client-guidance.md`
(and the 26 docstrings) says: create a scenario version for a what-if, an updated forecast or a
simulation input; run the server CPM; record a Monte Carlo or sensitivity result you computed as
a client-asserted output; **commit scenario and schedule lineage records when you identify a
relationship (a scenario concerns an Issue, a Constraint delays an activity, a Task mitigates a
Constraint) or when the user instructs you**, citing exact evidence for `delays`/`mitigates`;
use those records when you search, report and suggest; lineage needs no operator attestation,
but a `client_identified` link holds an Issue's close until confirmed; never present
`MODEL_PROPOSED` as "AI-generated" (it means the server did not verify the logic); scenario,
CPM and output data are non-authoritative and never reportable (`reportable: false`); a baseline
proposal is not a baseline; only the operator approves, rejects, revokes or sets governing;
revocation is final for its publication; use `schedule_series.current` (not `latest_update`)
for the current standard update (S6-U11); a lineage or related read never expands through a schedule
virtual edge (they are emitted only between records already in the answer), unlike
`meeting_note_version_of`, which is traversed and emitted when either endpoint is reached — reach
a Scenario's versions or a Baseline's publication through the plane reads (S6-3-U08, R10 ruling); a request is limited to 762,288 bytes in all
(`MAX_REQUEST_BYTES`), so a change set is split across versions and an output document must stay
under about 740 KiB (a criticality or Monte Carlo output of a network above roughly 10,000
activities may not fit; S6-3-U01). The `schedule_scenario_versions.create` and
`schedule_scenario_outputs.record` docstrings state the same limit (R10-F09).

### 15.13 Revision B (audit vocabulary)

File `migrations/versions/<YYYYMMDD>_<rev>_schedule_scenarios_vocabulary.py`, generated by
`alembic revision` against the re-authenticated sole head; `down_revision = "4c37731671fc"`;
imports `from alembic import op` and `typing.Final` only; docstring in the `4c37731671fc` step-6
style ("No role grant changes", "No backfill", the refusal, operator authority).

| Step | upgrade | downgrade |
|---|---|---|
| 1 | `SET LOCAL lock_timeout = '10s'` | the same |
| 2 | restate `capability_is_known` (`op.drop_constraint` then `op.create_check_constraint`, the `_restate_audit` precedent) with `_CAPABILITIES_AT_THIS_REVISION`: the frozen sorted 292 = the byte-copied 266 of `4c37731671fc`'s AT text + the 26 | `LOCK TABLE knowledge.audit_events IN ACCESS EXCLUSIVE MODE`, then a `DO` block refusing (`restrict_violation`, `'schedule scenarios audit history exists; refusing to downgrade <rev>'`) while any `audit_events` row names one of the 26 plane names or the 3 plane purposes (S6-2-D09) |
| 3 | restate `purpose_is_known` with the frozen sorted 68 = the 65 + `schedule_analysis_authoring`, `schedule_analysis_read`, `schedule_baseline_approval` | restore both BEFORE texts (byte copies of `4c37731671fc`'s AT texts) |

Only `knowledge.audit_events` is touched: it is live in production (`ACCESS EXCLUSIVE` held to
commit, one validating scan per CHECK, linear in its rows; a widening cannot fail on an existing
row). No table, row, grant, function or other CHECK. The window is measured like section 14.6.3:
I10-A times the 2 restatements on the scratch cluster at 10^5 and 10^6 synthetic `audit_events`
rows (`session_replication_role = replica`, `ANALYZE`) and records the figures in section 15.19;
the pre-deploy checks gain Q10 (before: `reltuples` and `pg_relation_size` of
`knowledge.audit_events`, report) and Q11 (after: `pg_get_constraintdef` of `capability_is_known`
names the 26 and of `purpose_is_known` the 3). Migration tests (`tests/schema/test_schedule_scenarios_vocabulary_migration.py`):
`test_the_revision_is_the_single_head_on_4c37731671fc`, `test_the_revision_imports_no_package_module`,
`test_before_texts_are_byte_copies_and_at_adds_exactly_the_plane_vocabulary`,
`test_at_sets_equal_the_live_enums`, `test_the_revision_writes_no_row_and_grants_nothing`,
`test_downgrade_refuses_while_plane_audit_history_exists[capability|purpose]`,
`test_clean_downgrade_restores_the_before_texts`, `test_a_held_lock_aborts_the_upgrade_cleanly`,
`test_runtime_metadata_matches_the_revision`.

### 15.14 Repository additions and composition

Additive to `src/my_pa/contracts/ports.py` and `src/my_pa/infrastructure/persistence/schedule_scenarios.py`
(reads only, Principal-partitioned through the module's `_mine`/`_bound`; no schema change;
amendment S6-3-D10):

| Method | Returns |
|---|---|
| `list_scenarios(principal_id, project_id, series_id, *, after, limit)` | `tuple[StoredScenario, ...]` by `(created_at, scenario_id)` desc |
| `list_versions(principal_id, scenario_id, *, before_version_no, limit)` | `tuple[StoredScenarioVersion, ...]` by `version_no` desc |
| `list_outputs(principal_id, version_id, *, after, limit)` | `tuple[StoredScenarioOutput, ...]` |
| `list_match_decisions(principal_id, project_id, *, after, limit)` | `tuple[SeriesMatchRecord, ...]` |
| `list_baselines(principal_id, project_id, series_id, *, after, limit)` | `tuple[StoredBaseline, ...]` (new record: the section 14.3.3 columns) |
| `get_baseline(principal_id, baseline_id)` | `StoredBaseline \| None` |
| `eligible_publication_ids(principal_id, project_id)` | `frozenset[str]`: the Project's non-intake publications with stored status `complete`/`partial` |
| `currency_publications(principal_id, series_id)` | `tuple[CurrencyPublication, ...] \| None` (`None` for absent, foreign or intake) |
| `publication_state(principal_id, publication_id)` | `(status, is_intake) \| None`, to tell `not_found` from `conflict(STATUS)` (15.7.2) |

`SqlScheduleRepository` gains `intake_publication_ids(principal_id, ids)` for the S5
`series_kind` and `match_state` fields. `compute_and_store_cpm_run` gains the keyword
`admit_write: Callable[[ScenarioRepository, str], None] = _admit_nothing` (15.10). Application
code imports none of these modules: `ScenarioUnitOfWork` and the port
`ScenarioCpmRunner` (a `Protocol` with `compute_and_store_cpm_run`'s keyword signature minus
`engine`, in `src/my_pa/contracts/ports.py`) are injected by `src/my_pa/bootstrap/gateway.py`,
the only module (with `apps/worker.py` reaching the jobs module) allowed to import the plane
persistence (`test_only_the_composition_root_imports_the_plane`).

### 15.15 Work split (3 serial packages; each head green on its own)

| Package | Owns |
|---|---|
| **I10-A** capabilities | `operation.py` (26 names, purposes map, `_OPERATOR_ONLY`, `_WRITE_CAPABILITIES`, `_ADDITIVE_WRITE_CAPABILITIES`), `purpose.py` (3), `decision.py` (`_SCOPELESS`), `authorization.py` (`_requested_scope`), `errors.py` (37 `SafeDetail`), `commands.py` (26 commands; import fields 15.9), `normalization.py` (`_BUILDERS`), `service.py` (switch, composition parameters, 26 thin handlers, the `scenario_plane_effective` hand-off), `src/my_pa/application/schedules.py` (the import gates and `operator_channel` hand-off of 15.9; the 15.6.2 S5 read fields and the intake delta refusal; R10-F01), `src/my_pa/domain/schedule/compare.py` only if the intake refusal cannot live in `schedules.py`, the `MAX_REQUEST_BYTES` docstring sentence of `src/my_pa/adapters/normalization.py` (R10-F09), NEW `src/my_pa/application/schedule_scenarios.py`, `src/my_pa/domain/schedule/cursor.py` (6 orders), `src/my_pa/domain/schedule/plane.py` (`OPERATOR_PROPOSAL_BUCKET`), `settings.py`, `gateway.py`, `apps/worker.py`, `ports.py` + `schedule_scenarios.py` + `schedule.py` + `schedule_cpm_lease.py` (15.14), `src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py` (Q10, Q11), revision B, `src/my_pa/adapters/mcp/remote.py` (`_WRITE_PURPOSES`), `src/my_pa/adapters/remote_request.py` (keys), `src/my_pa/domain/identity/chatllm_capability_policy.py` with a **v12 holding classification** — the 26 as `CONTROL_PLANE_EXCLUDED` with rationale "Schedule Scenarios S6-3 pending exposure (I10-C)" and no version bump, so I10-A's head is green with ChatLLM unchanged (the Reports WP03 → `OPERATOR_DECISION_REQUIRED` holding precedent, but excluded so no planner change) — `src/my_pa/adapters/mcp/chatllm_gateway.py` (`_FEATURE_BY_FAMILY`), the web fixture, the tests of section 15.16 for these, every lockstep pin of 15.2 except ChatLLM |
| **I10-B** lineage | `vocabulary.py` (public enums, maps, generation 2, `CONTESTABLE_RELATIONS`, `NativeVirtualEdge`), `lineage_endpoints.py`, `lineage_visibility.py`, `src/my_pa/application/record_lineage.py` (summaries, virtual edges), `src/my_pa/infrastructure/persistence/record_lineage.py` (`_NATIVE`, `share_endpoint`), `ports.py` (`LineageEndpoint` fields), `source_manifest.py` (pin), `service.py` (withheld families wiring only), the lineage and OD-08 tests, the partition-guard registry if its accounting moves, lineage lockstep pins |
| **I10-C** exposure | the section 15.11.3a lineage read shapes (S6-3-B01): `src/my_pa/contracts/v1/record_lineage.py`, the read paths of `src/my_pa/application/record_lineage.py`, the summary reads of `src/my_pa/infrastructure/persistence/record_lineage.py`, `NATIVE_VIRTUAL_EDGE_ENDPOINTS` in `src/my_pa/domain/lineage/vocabulary.py`, `web/src/lib/api/decode/capabilities/records.lineage.ts` (with the label maps and fixture; no related-read web decoder exists), and the 15.11.3a tests; `chatllm_capability_policy.py` (v13, `SCHEDULE_SCENARIOS`, the 22 `DATA_CONDITIONAL`, the 4 excluded with their final rationale), `chatllm_data_profile.py` (`schedule_scenarios` flag, prerequisite), `apps/cli/remote_mcp.py` (`_planes_from_settings`), the ChatLLM/remote/façade tests and pins, the v12 → v13 sweep (R10-F03): every live `--profile-version chatllm-data-v12` command moved to v13, keeping v12 as history, in `ops/runbooks/managed-knowledge-context.md`, `ops/runbooks/mcp-and-cli-operations.md`, `ops/runbooks/remote-mcp-cloudflare.md`, `ops/runbooks/managed-document-operations.md`, and the current-version statements in `ops/runbooks/gateway-operations.md`, `docs/operations/mcv-limitations.md`, `docs/operations/record-lineage-client-guidance.md`, `docs/decisions/ADR-017-schedule-scenarios-and-baselines.md` and `docs/plans/relationship-intelligence-implementation-plan.md`, with `_CURRENT` in `tests/contract/test_lineage_client_exposure_runbook.py` → v13 and the sentence "v13 with `MY_PA_SCHEDULE_SCENARIOS_ENABLED` off desires exactly the v12 set, so a pending Reports commissioning uses v13 after this build" in each runbook that carries a profile command, `docs/operations/record-lineage-client-guidance.md`, `ops/runbooks/cpm-workbench.md` section 9, `docs/decisions/ADR-017-schedule-scenarios-and-baselines.md` and ADR-015 decision 17 status notes, this contract's executed-results subsection, `docs/architecture/cpm-workbench.md`, the index rows, the doc and plan pins, `tests/ci_shard_weights.json` |

Every package runs FAST, the full `tests/architecture` directory (the memory-row guard alone),
the database tiers it touches by marker (`database`, `migration_edge`,
`migration_empty_to_head`), ruff, both mypy runs in both venvs, `python -m tests.ci_shard verify`
(and `weigh` for heavy new modules), and re-measures the 2 contended plan documents at its own
head. I10-A's head serves the 26 with the switch on but exposes nothing to ChatLLM (its interim
pins: section 15.2); I10-B's
head admits the lineage families; I10-C's head is the whole slice.

### 15.16 Test plan, crosswalk and prove-red

#### 15.16.1 Modules

| Module | Tier | Content |
|---|---|---|
| `tests/unit/test_schedule_scenario_commands.py` | FAST | every 15.5 field refusal; unknown key; heavy documents opaque until the handler; import fields 15.9 |
| `tests/contract/test_schedule_scenarios_policy_closure.py` | FAST | 15.3 inventory row by row against every registry; 15.2 pins; v12 holding (I10-A) then v13 (I10-C) |
| `tests/database/test_schedule_scenario_capabilities.py` | `database_clone` | handlers end to end through `ApplicationService` with the gateway composition: writes, reads, replays, refusal mapping 15.7.2, budgets, quotas, operator-only, switch |
| `tests/database/test_schedule_scenario_lineage.py` | `database_clone` | lineage families, relations, evidence, withheld families, close gate |
| `tests/integration/test_scenario_compact_facade.py` | `database_clone` (the S5b-2 façade module's tier) | façade end to end, 2 clients, ChatLLM planner |
| `tests/schema/test_schedule_scenarios_vocabulary_migration.py` | static FAST + `migration_edge`; DB `migration_edge` / `migration_empty_to_head` | revision B (15.13) |
| `tests/architecture/test_schedule_scenarios_capability_scope.py` | FAST | OD-08 AST, manifest pin, composition-root import rule, no `BASELINE` in the S5 files, worker wiring, S6-1 `PLANE_*_WRITE_CAPABILITIES` equal the members |

#### 15.16.2 Crosswalk (every S6-3 test this contract names)

| Requirement (section) | Test |
|---|---|
| Monte Carlo client-side, client-asserted (9.4) | capabilities `test_output_record_is_client_asserted` |
| lineage for schedule data (5, 9.4) | lineage `test_scenario_lineage_relations_are_admitted` (parametrized over the 5 relations and every admitted pair, and one refused pair each) |
| withheld family (5.1, R8-F10) | lineage `test_withheld_family_link_stays_confirmable_and_endable` |
| catalog and façade (6.7, 9.4) | façade `test_scenario_facade_end_to_end` (describe lists exactly the eligible client-usable names; write creates, appends, runs CPM, records an output, proposes; read reads each back; an operator name and an unadmitted name are absent and `unsupported`; `records.associations.assert` `concerns` version → Issue is `client_identified`) |
| client-bound keys (6.7, R8-F09) | façade `test_identical_payloads_from_two_clients_create_two_rows`; and `test_identical_retry_from_one_client_replays` |
| OD-08 (7) | scope `test_scenario_data_reaches_no_program_surface`; `test_manifest_lineage_section_is_pinned_to_seven_families` |
| import refused while off (6.2, 12.2, P56; amended by R10-F07) | capabilities `test_baseline_import_refused_while_plane_off` (role `baseline` with all 4 approval fields → `invalid_request(PUBLICATION_ROLE)` with only `MY_PA_SCHEDULE_ENABLED`; the same from a remote or unattested caller → `unsupported`/`denied` first; `reference`/`working` refused whatever the switches) |
| CPM budget before compute (8.3, R10-F02, R10-N01) | capabilities `test_over_budget_cpm_run_never_computes` (parametrized: `write_budget`, `byte_quota`, `refusal_bound` — the injected `compute` seam is never called; `replay_over_budget` — returns the stored run with `replayed: true`; `natural_key_over_byte_quota` — the existing run is returned, `created: false`, admitted; `byte_headroom_below_content_size` — the client's remaining byte headroom is greater than 0 but less than the version's `content_size_bytes`, and the injected `compute` seam **is** reached (R10-N06)) |
| operator approval required (12.3, P48) | capabilities `test_baseline_approval_is_attested_operator_only` (each of the 4 by a remote client, stdio MCP and `local_unattested`: `denied`/`unsupported`; by the CLI operator: admitted) |
| provenance on every output (7, 12.1) | capabilities `test_baseline_outputs_show_provenance` |
| scenarios record the exact baseline (12.1) | capabilities `test_scenario_records_the_exact_baseline` |
| current standard update (11.3) | capabilities `test_series_current_read_reports_ambiguity` |
| S6-3-O01 (15.4) | capabilities `test_operator_may_propose_and_only_the_operator_withdraws_it` |
| switch (6.2) | capabilities `test_every_scenario_name_is_unsupported_while_the_plane_is_off` (each of the 26, each switch combination), `test_scenario_switch_changes_no_row`; scope `test_worker_passes_the_effective_plane` |
| auto form gate (11.2) | capabilities `test_series_auto_refused_while_plane_off`, `test_intake_series_name_is_refused` |
| refusal mapping (15.7.2) | capabilities `test_every_repository_outcome_maps_to_its_public_answer` (parametrized over the 15.7.2 rows reachable through a handler) |
| budgets and refusal bound (8.3) | capabilities `test_client_write_budget_is_enforced_per_bucket_and_principal`, `test_refusal_bound_answers_before_decoding`, `test_refusal_counting_scope` (step 1–4 refusals uncounted, R10-F11), `test_storage_quota_is_enforced`, `test_cpm_units_bound_is_enforced` (cases `client`, `operator_exempt`: a client fills the Principal's hourly units and the operator still computes, R10-F04), `test_attested_operator_is_never_budgeted` (cases `writes`, `bytes`, `cpm_units`) |
| compare names an effective Baseline only (15.7.2, R10-F13; FR10-F01) | capabilities `test_compare_refuses_a_non_effective_baseline` (`proposed`, `rejected`, `withdrawn`, `revoked`: `conflict(baseline_id)`) |
| approved but ineligible (15.7.2; FR10-F02) | capabilities `test_an_ineligible_baseline_answers_conflict_status` (`schedule_scenarios.create` from the Baseline and `compare`: `conflict(status)`) |
| lineage endpoints need only SELECT (R10-F12) | lineage `test_share_endpoint_needs_only_select_on_the_schedule_tables` |
| ChatLLM (6.6) | policy `test_v13_targets`, `test_planner_desires_the_22_only_with_both_switches`, `test_planner_never_desires_the_4`, `test_old_client_stays_healthy_while_the_plane_is_off` |
| revision B (15.13) | the 9 migration tests named there |

#### 15.16.3 Prove-red (break exactly one guard; the named test fails for that reason; revert)

| # | Mutation | Must fail |
|---|---|---|
| P3-01 | drop one operator name from `_OPERATOR_ONLY` (4 runs) | `test_baseline_approval_is_attested_operator_only[<name>]` (the remote call is admitted) |
| P3-02 | remove `attested_lineage_authority` from one operator handler (4 runs) | the same test, `local_unattested` case |
| P3-03 | `_scenario_plane()` removed from one handler (sampled: 1 write, 1 read, 1 operator) | `test_every_scenario_name_is_unsupported_while_the_plane_is_off[<name>]` |
| P3-04 | `available_capabilities` stops subtracting the 26 | `test_every_scenario_name_is_unsupported_while_the_plane_is_off` (manifest half) |
| P3-05 | the import gate admits role `baseline` while off | `test_baseline_import_refused_while_plane_off` (P56) |
| P3-06 | the import gate admits `series_auto` while off | `test_series_auto_refused_while_plane_off` |
| P3-07 | a command accepts an unknown key (`**extra`) | `test_unknown_key_is_invalid_request[<capability>]` |
| P3-08 | one of the 6 dropped from `_CLIENT_BOUND_SCENARIO_WRITES` | `test_identical_payloads_from_two_clients_create_two_rows` |
| P3-09 | one of the 6 dropped from `_IDEMPOTENT_REMOTE_CAPABILITIES` | `test_identical_retry_from_one_client_replays` |
| P3-10 | `is_remote_idempotent` ignores the plane set | `test_scenario_tools_carry_the_idempotent_hint` |
| P3-11 | the version handler skips the CAS pre-check (the S6-2 write check kept) | `test_version_append_conflict_is_reported_before_computing` (the injected `apply_change_set` seam must not be called) |
| P3-12 | refusal bound checked after decoding | `test_refusal_bound_answers_before_decoding` (the decode seam is reached) |
| P3-13 | bucket budget check removed | `test_client_write_budget_is_enforced_per_bucket_and_principal[bucket_hour]` (and `[bucket_day]`, `[principal_day]` one run each) |
| P3-14 | byte quota removed | `test_storage_quota_is_enforced[bucket_day]` (and `[principal_day]`, `[principal_total]`) |
| P3-15 | `admit_compute` admits everything | `test_cpm_units_bound_is_enforced` |
| P3-16 | the operator is budgeted (3 runs: writes, bytes, CPM units in `admit_compute`) | `test_attested_operator_is_never_budgeted[<case>]`; the CPM-units run also reddens `test_cpm_units_bound_is_enforced[operator_exempt]` |
| P3-17 | a remote reader sees `asserting_client_id` | `test_baseline_outputs_show_provenance[remote_reader]` |
| P3-18 | another Principal's Scenario readable (drop `_mine` in `list_scenarios`) | `test_hidden_is_absent_for_every_read[schedule_scenarios.list]` |
| P3-19 | a proposal labelled `authoritative: true` | `test_baseline_outputs_show_provenance[proposal]` |
| P3-20 | `from_baseline_id` admits a proposal | `test_scenario_records_the_exact_baseline[proposal]` |
| P3-21 | propose passes `None`, or a client-reachable bucket (for example `"local_unattested\x1f"`), for the operator instead of `OPERATOR_PROPOSAL_BUCKET` (R10-F06) | `test_operator_may_propose_and_only_the_operator_withdraws_it[operator_proposes]` (the 11th operator proposal is refused by the 10-per-bucket cap, or a `local_unattested` caller withdraws it) |
| P3-22 | OD-08: a planted import of `schedule_scenarios` in `program_work.py` | `test_scenario_data_reaches_no_program_surface` |
| P3-23 | manifest admits `RecordFamily` wholesale | `test_manifest_lineage_section_is_pinned_to_seven_families` |
| P3-24 | `require_linkable` admits an intake publication | `test_scenario_lineage_relations_are_admitted[intake_publication_refused]` |
| P3-25 | `originated_from` from a non-approved Baseline admitted | `test_scenario_lineage_relations_are_admitted[originated_from_proposal_refused]` |
| P3-26 | `delays` without the `corroborates` rule | `test_scenario_lineage_relations_are_admitted[delays_without_anchor_refused]` |
| P3-27 | `confirm` re-validates a withheld endpoint | `test_withheld_family_link_stays_confirmable_and_endable` |
| P3-28 | `LINEAGE_READ_GENERATION` left at 1 | `test_lineage_generation_is_two` (and an S3 cursor from generation 1 is refused) |
| P3-29 | public and stored lineage vocabularies differ by one pair | `test_storage_vocabulary_equals_the_public_vocabulary` |
| P3-30 | ChatLLM: one of the 22 not `DATA_CONDITIONAL`; prerequisite ignores `schedule` (2 runs) | `test_planner_desires_the_22_only_with_both_switches` |
| P3-31 | ChatLLM: one operator name `DATA_CONDITIONAL` | `test_planner_never_desires_the_4` |
| P3-32 | `_FEATURE_BY_FAMILY` misses one family | `test_scenario_facade_end_to_end` (feature `other`) |
| P3-33 | façade publishes an operator name | `test_scenario_facade_end_to_end` |
| P3-34 | `_planes_from_settings` ignores the scenario switch | `test_remote_planner_reads_the_scenario_switch` |
| P3-35 | worker passes `scenario_plane_effective=True` unconditionally; passes nothing (2 runs) | `test_worker_passes_the_effective_plane` |
| P3-36 | revision B: one capability missing from the AT text; downgrade clause dropped (2 runs) | `test_at_sets_equal_the_live_enums`; `test_downgrade_refuses_while_plane_audit_history_exists[capability]` |
| P3-37 | `SET` instead of `SET LOCAL` in revision B | `test_a_held_lock_aborts_the_upgrade_cleanly` |
| P3-38 | a count pin (`len(Capability)`) left at 255 | the named pin tests of 15.2 (expected red; it proves the pin is live) |
| P3-39 | the composition root rule: application imports `schedule_scenarios` persistence | `test_only_the_composition_root_imports_the_plane` |
| P3-40 | a refused client write not recorded | `test_refusal_bound_answers_before_decoding[recorded]` |
| P3-41 | the step-1 `admit_write` pre-check removed from the CPM path (R10-F02) | `test_over_budget_cpm_run_never_computes[write_budget]` (the compute seam is reached) |
| P3-46 | the pre-check moved before the replay probe (R10-N01) | `test_over_budget_cpm_run_never_computes[replay_over_budget]` (refused instead of replayed) |
| P3-47 | 2 runs (R10-N01, R10-N06): run 1, the pre-check uses the version's content size instead of 0 new bytes; run 2, the pre-check runs before the natural-key probe | run 1: `test_over_budget_cpm_run_never_computes[byte_headroom_below_content_size]` (refused before the compute seam instead of computing); run 2: `test_over_budget_cpm_run_never_computes[natural_key_over_byte_quota]` (refused instead of admitted) |
| P3-48 | one schedule edge type not emitted (8 runs) | `test_schedule_virtual_edges_are_emitted_between_reached_nodes[<edge>]` |
| P3-49 | emission admits an edge whose far endpoint is not a node of the answer | `test_schedule_virtual_edge_to_an_unreached_node_is_not_emitted` |
| P3-50 | a schedule virtual edge is followed by the traversal | `test_schedule_virtual_edges_are_never_traversed` |
| P3-51 | a summary carries one extra key (for example the Scenario name) | `test_schedule_nodes_carry_exactly_their_summary[scenario]` |
| P3-52 | baseline status read from the whole chain instead of `recorded_at ≤ N` | `test_schedule_baseline_node_is_as_of_the_native_cut` |
| P3-53 | the service passes no `withheld_families` to the lineage reads (R10-S05; layered on I10-B's own withheld-family prove-red, declared in advance) | `test_withheld_schedule_family_emits_no_node_or_edge` |
| P3-54 | the digest input filters the schedule edges out (`related_digest` itself is generic) | `test_related_sha256_covers_schedule_summaries_and_edges` |
| P3-55 | `VirtualEdgeView` admits a wrong endpoint pair; a virtual path step admits a schedule edge type (2 runs) | `test_virtual_edge_endpoint_table_is_exact`; `test_virtual_path_step_admits_only_the_note_edge` |
| P3-56 | the schedule edge key left as `v:<from.record_id>` (R10-S01) | `test_schedule_virtual_edges_page_without_repeat` |
| P3-57 | the node derives `authority` from `effective` instead of `effective_type` (R10-S02) | `test_schedule_nodes_carry_exactly_their_summary[schedule_baseline-revoked]` (and `[ineligible]`) |
| P3-58 | `_lineage_position` left unchanged (it validates everything after `v:` as a note version id) (R10-T01) | `test_schedule_virtual_edges_page_without_repeat` (the next page is refused `invalid_request(CURSOR)`) |
| P3-42 | withdraw passes `None` for a client channel (bucket taken from anything but `PlaneProvenance`) (R10-F06) | `test_operator_may_propose_and_only_the_operator_withdraws_it[client_withdraws_other_bucket]` and `[local_unattested]` |
| P3-43 | the import plane gate placed before E-10/E-12 (R10-F01) | `test_baseline_import_refused_while_plane_off` (the remote case answers `invalid_request`) |
| P3-44 | `share_endpoint` takes `FOR SHARE` on the `schedule_activity` family (a table without `UPDATE` under the test role; R10-F12, R10-N04) | `test_share_endpoint_needs_only_select_on_the_schedule_tables[schedule_activity]` (`insufficient_privilege`, SQLSTATE `42501`, under the role holding exactly P-check ∪ Q8); a mutation on the publication family would stay green (the role holds `UPDATE` there) and is not a valid prove-red |
| P3-45 | a step-2 grant `denied` recorded as a refusal (R10-F11) | `test_refusal_counting_scope` |
| P3-59 | FR10 M13: `compare` reads the Baseline without the effectiveness check (FR10-F01) | `test_compare_refuses_a_non_effective_baseline[proposed\|rejected\|withdrawn\|revoked]` |
| P3-60 | FR10 M3: the `INELIGIBLE → conflict(STATUS)` branch of `_eligible_baseline` deleted (FR10-F02) | `test_an_ineligible_baseline_answers_conflict_status[schedule_scenarios.create\|schedule_baselines.compare]` (`conflict(baseline_id)` instead) |
| P3-61 | FR10 M4: `_counted` stops recording `ConflictError` (FR10-F03) | `test_refusal_counting_scope` (the `conflict(expected_version)` is not counted) |

A prove-red that stays green is reported as redundancy, a masked test or an unreachable hazard,
never "covered". Declared layered in advance: P3-11's S6-2 write-side CAS (S6-2 P2-06) still
refuses, so the test asserts the seam, not the answer.

### 15.17 Runbook plan (`ops/runbooks/cpm-workbench.md` section 9, written by I10-C; nothing run)

1. **Order.** S6-2 revision A applied (section 8; the operator reports production at
   `4c37731671fc`, which includes it — this note did not verify it), revision B applied (backup; quiet window for
   audit writes — every authorized request writes `audit_events`, so the gateway pauses; Q0,
   Q10 before; Q0, Q11 after; `55P03` is a clean retryable abort; go/no-go from the 15.19
   measurement scaled by Q10 as section 14.14's rule); deploy the S6-3 build with
   `MY_PA_SCHEDULE_SCENARIOS_ENABLED` absent; then `MY_PA_SCHEDULE_ENABLED=true` (if not already)
   and `MY_PA_SCHEDULE_SCENARIOS_ENABLED=true` on the gateway **and** on the schedule worker;
   restart both.
2. **Commissioning (operator-run, not run):** for each ChatLLM client, `profile-diff`,
   `profile-plan`, then `profile-apply --profile-version chatllm-data-v13` (the
   `ops/runbooks/managed-knowledge-context.md` form). **Go/no-go is a set rule, not a count**
(R10-F05, R10-N02): (i) the diff shows **no removal**; (ii) every add is in {the 22 below} ∪ {the
6 S5b-2 reads `schedule_series.list`, `schedule_publications.list`, `schedule_publications.read`, `schedule_activities.list`, `schedule_activities.history`, `schedule_changes.list` (purpose `schedule_read`)} ∪ {the 11 `chatllm-data-v12` Reports names `reports.publish`, `reports.update`, `reports.history`, `reports.archive`, `reports.delete`, `reports.restore`, `reports.transfer.begin`, `reports.transfer.append`, `reports.transfer.finalize`, `reports.transfer.abort`, `reports.transfer.read_chunk`}; (iii) all 22 are
present. Anything else is a stop. Expected cases: **22** adds (the client holds the 6 S5b-2 reads
and was applied at v12), **28** (never profiled with `MY_PA_SCHEDULE_ENABLED` on; production
today: that switch is absent), **33** (holds the 6 reads, never applied at v12: the Reports
commissioning still pending in production), **39** (neither). v13 with
`MY_PA_SCHEDULE_SCENARIOS_ENABLED` off desires exactly the v12 set, so a still-pending Reports
commissioning simply uses v13 after this build (R10-F03). The 22:
   writes `schedule_scenarios.create`, `schedule_scenario_versions.create`,
   `schedule_cpm_runs.create`, `schedule_scenario_outputs.record`, `schedule_baselines.propose`,
   `schedule_baselines.withdraw` (purpose `schedule_analysis_authoring`, `--write`); reads
   `schedule_scenarios.list`, `schedule_scenarios.read`, `schedule_scenario_versions.read`,
   `schedule_scenario_versions.activities`, `schedule_scenario_versions.relationships`,
   `schedule_scenario_versions.changes`, `schedule_cpm_runs.read`, `schedule_cpm_runs.activities`,
   `schedule_scenario_outputs.list`, `schedule_scenario_outputs.read`, `schedule_series.current`,
   `schedule_series.match_decisions`, `schedule_baselines.list`, `schedule_baselines.read`,
   `schedule_baselines.governing`, `schedule_baselines.compare` (purpose
   `schedule_analysis_read`). For a non-ChatLLM remote client (the ChatGPT connector), the same 22
   by `apps/cli/remote_mcp.py grant` (one per name, `--write` for the 6), and its writes flag;
   the S5b-2 Schedule reads too if the client lacks them; the schedule-family lineage reads need
   the lineage grants the client already holds. **Never** grant the 4 operator names (an active
   grant on one is `UNEXPECTED_CONTROL_PLANE_GRANT`).
3. **Read-only checks:** Q0–Q11 (`ops/postgres/schedule_scenarios_predeploy_check.py`) as the
   runtime role; after enablement `capabilities.get` lists the 26 (operator) and remote
   `tools/list` the 22 for a granted client.
4. **Measurements the operator owns:** S6-2-U07 (the maximal matcher read under J on the server
   host, by an intake import against a Project with 50 Series; stop if it approaches the 30 s
   `statement_timeout`), S6-2-U12 (count 1 extra connection per concurrently computing
   Principal per process against `max_connections`), S6-U06/U16 (CPM timing and calendar cache
   memory on the server host).
5. **Rollback:** switches off (no row changes; reads and writes `unsupported`, lineage families
   withheld, links stay confirmable); revision B downgrade only while no audit row names a plane
   capability or purpose (it refuses otherwise; never delete audit history).
6. **Warnings:** revoking a Baseline is final for its publication (S6-U15); large change sets are
   split across versions (S6-3-U01).
7. Operator-gated and not performed by an agent: both revisions, the switches, every
   `profile-apply`/grant, the measurements, deployment.

### 15.18 Decisions, amendments, residuals, open questions

#### 15.18.1 Decisions and amendments (S6-3-D)

| ID | Decision / amendment | Reason |
|---|---|---|
| S6-3-D01 | **Amendment of 6.1 counts:** `Capability` 255 → 281, `Purpose` 65 → 68, `IdKind` 174 unchanged | Reports #351 landed first (R3-01–R3-03) |
| S6-3-D02 | **Amendment of 6.1 / 9.3 audit counts:** revision B restates 266 → 292 and 65 → 68 on `4c37731671fc` | R3-04; the audit vocabulary is a DB CHECK |
| S6-3-D03 | **Amendment of 6.6 / 0.1 / 6.7:** the profile is `chatllm-data-v13` | v12 is Reports' (R3-06) |
| S6-3-D04 | **Amendment of 6.6 targets:** policy 281; `DATA_CONDITIONAL` 159; `CONTROL_PLANE_EXCLUDED` 33; full 175 and default 109 unchanged while off; full + schedule + scenarios 203; full + lineage + program + schedule + scenarios 237; default + all 4 169; 1,024 compositions | Reports' 11 `DATA_REQUIRED` names moved every target by 11 (R3-07) |
| S6-3-D05 | the 10 plane writes join `_WRITE_CAPABILITIES`; the 5 that only insert (create, append, CPM run, output, propose) join `_ADDITIVE_WRITE_CAPABILITIES`; withdraw, approve, reject, revoke, set_governing are destructive-hinted | registries the contract did not name (R3-11) |
| S6-3-D06 | `_CLIENT_BOUND_SCENARIO_WRITES` feeds the idempotent and client-bound sets and `is_remote_idempotent`; the stamped key is `idk_` + 32 hex | the derived-set shape (R3-13) |
| S6-3-D07 | **Amendment of 9.3 `SafeDetail` list:** reuse `EXPECTED_VERSION`, `LABEL`, `EFFECTIVE_FROM`, `REASON`, `VERSION_ID`; drop `SCENARIO_VERSION_ID` (the field is `version_id`) and `ACTIVITY_KEY` (no input names an activity key); add `FROM_VERSION_ID`, `FROM_BASELINE_ID`, `DATA_DATE_TIME`, `NOTE`, `SUPERSEDES_BASELINE_ID`, `SCENARIO_WRITE_BUDGET`, `SCENARIO_REFUSAL_BUDGET`, `CRITICAL_ONLY` | collisions and fields the list missed (R3-15) |
| S6-3-D08 | **Amendment of 6.4 cursor orders:** `baselines_label_asc` → `baselines_created_desc_id_desc` | a proposal has no label |
| S6-3-D09 | schedule-family endpoints are shared by `share_endpoint` on the general unit of work | one lineage transaction locks every endpoint (S1 order); `ScenarioUnitOfWork` stays off `UnitOfWork` (R3-18) |
| S6-3-D10 | **Amendment of section 14.8.1 (S6-2 API, additive):** 9 `ScenarioRepository` reads, 1 `SqlScheduleRepository` read, `compute_and_store_cpm_run(…, admit_write=…)` | the handlers need paged reads, eligibility, currency and the write budget inside the CPM write transaction (R3-19) |
| S6-3-D11 | commands are frozen dataclasses, not pydantic | repository idiom (R3-22) |
| S6-3-D12 | the 4 MiB change-set and 1 MiB output bounds stay; `MAX_REQUEST_BYTES` is not raised, and the plane requests are deliberately not part of its derivation: I10-A updates the `src/my_pa/adapters/normalization.py` docstring sentence that calls it "derived from the largest request the contract can express" (R10-F09) | a transport-wide bound; raising it is a separate decision (R3-23); R10 accepted U01 |
| S6-3-D13 | **Amendment of 8.3 refusal counting (R10-F11):** only refusals from step 5 of 15.10 on are counted; `unsupported`, a missing-grant or authority `denied`, the refusal bound itself and normalization refusals (pre-authentication) are never counted; heavy documents decode after the bound | R3-24; steps 1–4 are cheap and precede any decode |
| S6-3-D14 | **Amendment of 12.3 field name, and of 6.2, 12.2 and P56 (R10-F07):** the import's type is the existing `baseline_kind`; no `baseline_type` field; the plane-off answer to a fully specified role-`baseline` import is `invalid_request(PUBLICATION_ROLE)` (not `BASELINE_TYPE`); `BASELINE_TYPE` is only the `type` field's detail on propose/approve | a `SafeDetail` names the offending field; unchanged from S6-2-D04 for callers while the plane is off |
| S6-3-D15 | S6-3-O01: the operator may propose with `OPERATOR_PROPOSAL_BUCKET`; bound by the 50 cap, never the 10 cap; withdrawable only by the operator | operator ruling (15.4) |
| S6-3-D16 | the 6 client writes take `client_intent_id` and `user_directed`; **clarification of 6.5** "no request field carries them" means class, channel, client and basis | the Reports deliberate-repeat precedent; S3.1's claim field |
| S6-3-D17 | I10-A holds the 26 `CONTROL_PLANE_EXCLUDED` (no version bump) until I10-C | each package's head green on its own with no premature ChatLLM exposure |
| S6-3-D18 | S5 reads gain `series_kind`, `match_state`, `match_decision_id`; the delta refuses an intake publication | sections 11.2 step 2, 11.4; S6-2-U09/U10 "S6-3 reads show it as undecided" |
| S6-3-D19 | a snapshot of a non-eligible publication is `conflict(STATUS)`, of an absent/foreign/intake one `not_found`; `SnapshotRefusalReason.ROWS` is `conflict(FROM_PUBLICATION_ID)` | consistent with section 12.4's eligibility answer and S6-2-D08 |
| S6-3-D20 | **Replaced (R10-F04):** the attested operator is exempt from the hourly CPM-units bound; the per-run operation budget and the 1-compute lease apply to everyone; operator runs still count toward the Principal's units | a client within its budgets could otherwise lock the operator out for up to an hour (120 × 25,000 > 2,500,000); host protection is the operation budget and the lease |
| S6-3-D21 | **Amendment of 5.3 (R10-F12):** the 6 schedule families are read by `share_endpoint` without `FOR SHARE` | immutable or terminal rows; `FOR SHARE` needs `UPDATE`, not guaranteed to the runtime role (R3-29) |
| S6-3-D22 | the import's plane gates run in `ScheduleApplication.import_publication` after E-10/E-12, keyed on `request.approval` (R10-F01) | the admission and the attested authority live there; a non-operator never learns of the plane |
| S6-3-D23 | `admit_write` runs before the leased compute (read-only, under P) and again in the write (R10-F02) | an over-budget client cannot force uncounted computes |
| S6-3-D24 | the propose/withdraw bucket derives only from `PlaneProvenance` (R10-F06) | no request field or channel guess can make a client the operator |
| S6-3-D25 | a client's withdraw of another bucket's proposal stays `denied(BASELINE_ID)` (R10-F10) | proposals are readable by the caller, so hidden = absent does not apply; a counted refusal |

#### 15.18.2 Residuals (S6-3-U)

| ID | Residual | Owner |
|---|---|---|
| S6-3-U01 | change sets or output documents above about 740 KiB cannot be sent (`MAX_REQUEST_BYTES` 762,288 bytes); clients split change sets across versions, but an output cannot be split: a `criticality`/`monte_carlo` output whose `activity_criticality` holds more than roughly 10,000–12,000 entries (about 60 bytes each) has no route, so client-asserted criticality is unrecordable for large networks (R10-F09) | later transport decision (accepted by R10) |
| S6-3-U02 | revision B takes `ACCESS EXCLUSIVE` on live `audit_events`; production row count unknown | operator, Q10 |
| S6-3-U03 | `write_baseline` and the baseline reads read the whole Project chain (S6-2-U03) | later slice |
| S6-3-U04 | a refused client write is recorded in a separate transaction; a crash between the 2 loses one count (soft bound) | accepted (R9-F13) |
| S6-3-U05 | an operator proposal can fill the 50-per-Project cap and block client proposals | operator |
| S6-3-U06 | a CPM compute refused only by the step-5 re-check (a race with a concurrent write of the same bucket after the step-1 pre-check) is computed but never stored, so it is not counted in `cpm_units_since` (R10-F02) | accepted: bounded by the lease and the race window |
| S6-3-U08 | schedule virtual edges are emitted between reached nodes only and never traversed (15.11.3a item 3); a client reaches a Scenario's versions or a Baseline's publication by the plane reads, not by lineage expansion — **accepted by R10 re-review 3** on condition that the 15.12.5 guidance states the difference from the note edge (done) | later slice |
| S6-3-U09 | a schedule publication node's `status` is read at read time, not as of the native cut; it equals the status at N for every reachable publication, because a publication becomes a node only through a typed link admitted while it was terminal, and terminal statuses never change (no other path exists: U08 forbids traversal) — reason corrected by R10 re-review 3 | accepted (R10 re-review 3) |
| S6-3-U10 | `related_sha256` now covers schedule summaries and edges, and a default-filter related read's digest changes because the default relation set grew (B-06); a claim is verified only at report commit, so only a claim read on a pre-S6-3 build and committed on the S6-3 build reads `changed_since_read` — transient at deploy and failing closed (none exists: nothing of S6-3 is deployed) | accepted (R10 re-review 3; B-06 folded in by FR10) |
| S6-3-U07 | heavy attested-operator CPM use counts toward the Principal's hourly units and can exhaust client headroom (R10-F04) | operator's own choice |
| S6-3-U11 | CI headroom of validate-fast shard 1 (FR10-F05): the memory-row guard (`tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py`), alone in shard 1, ran 734–792 s locally at this head (about 563 s at an earlier base; 281 against 255 capabilities). Scaled by about 1.3 the worst complete shard-1 leg projects to about 2,400–2,600 s against `timeout-minutes: 55` (3,300 s), about 75–80 %: an erosion, not a breach. The weights are left unchanged (the table is CI-derived; the 5 new light FAST files are hash-placed) | make the guard cheaper, or re-weigh the fast lane from the first CI run of this head |

#### 15.18.2a I10-B divergences (as reported by I10-B at `bb6bbe8d`; ruled by the final review FR10, all accepted)

| ID | Divergence (I10-B's words, condensed) |
|---|---|
| S6-3-B01 | stopped: section 15.11.3 designed no public shape for schedule node summaries and virtual edges — resolved by the 15.11.3a addendum (owner I10-C) |
| B-02 | the hard-coded `AssertRecordAssociation` relation enum in `commands.py` (an I10-A file) was widened, as 15.11.1 asks; treated as a trivial ownership point. **FR10: accepted** (trivial ownership) |
| B-03 | the web decoder and 3 UI label maps were widened (outside the listed paths); without the decoder the S2/S3/S3.1 decoder guards fail, without the labels `tsc` fails. **FR10: accepted** |
| B-04 | the report recompute withholds the 6 families unconditionally (OD-08), and the manifest functions raise `ValueError` outside the 7 families — I10-B's concrete reading of "admit only it". **FR10: accepted** (OD-08 stricter than required; `ValueError` only on an internal defect) |
| B-05 | the P1 companion-table test excludes the Schedule families' reads (the Schedule plane's own grants, not P1 companions). **FR10: accepted** |
| B-06 | `related_sha256` of a default-filter related read changes (the default filter is all relations, which grew); a client claim stored before would show `changed_since_read`. **FR10: accepted as a residual, folded into S6-3-U10** |
| B-07 | the local cursor scope does not include withheld families (the local grant digest is `None`); a local cursor spanning a plane switch flip (which needs a restart) would not be told to restart — left as a residual. **FR10: accepted as a residual** (a switch flip needs a restart; the exposure is a local in-flight cursor across it) |
| B-08 | `concerns` has no evidence rule, but every assertion still needs at least 1 anchor (the S1 parse minimum), so the tests cite a `corroborates` anchor. **FR10: accepted** (the S1 parse minimum) |

#### 15.18.2b I10-A and I10-C divergences (as reported by the packages; ruled by the final review FR10)

| ID | Divergence | FR10 ruling |
|---|---|---|
| I10-A D-1 | `admit_write` is `Callable[[ScenarioRepository, str, int \| None], None]` (15.14 named `Callable[[ScenarioRepository, str], None]`): `None` refuses at or over the byte quota (the CPM pre-check), `0` skips bytes, `n > 0` refuses `used + n > quota` — one `0` cannot express both the pre-check and the natural-key admission over quota (section 15.10) | accepted |
| I10-A D-2 | a third plane port, `ScenarioRecordBuilders` (`new_version`, `new_output`), composed in `src/my_pa/bootstrap/gateway.py` beside `ScenarioUnitOfWork` and `ScenarioCpmRunner` (15.8 and 15.14 named 2): the builders live in the plane persistence, which the application may not import | accepted |
| I10-A D-3 | `available_capabilities` restates the plane conjunction on the attributes instead of calling `_scenario_plane_is_composed()` (the S5 precedent; P3-04 guards it) | accepted (minor maintenance risk) |
| I10-A D-4 | plane reads refuse a bad cursor `invalid_request(CURSOR)`; compare delegates to S5 and inherits `conflict(CURSOR)` | accepted; 15.7.2 amended |
| I10-A D-5 | `StoredBaseline` carries its events; `SeriesMatchRecord` gains `created_at` (additive, for `.read` history and keyset paging) | accepted |
| I10-A D-6 | repository reads beyond the 9 of 15.14 (read-only, Principal-partitioned, no schema change) | accepted |
| I10-A D-7 | one shared `_operator_writer` (grant, `attested_lineage_authority`, provenance) for the 4 operator writes | accepted |
| I10-A D-8 | a CPM replay answers the ledger's original `created` (15.6.1 byte-identical replays) | accepted |
| I10-A D-9 | proposer and approver `client_id` withheld from remote readers (15.4, 15.6.4) | accepted |
| I10-A D-10 | the S6-2 scope test relaxed: `service.py` and `bootstrap` may name `ScenarioUnitOfWork` (15.8 requires the parameter and the factory); the dropped "nothing public" pins replaced in lockstep by `test_only_the_composition_root_imports_the_plane`, `test_worker_passes_the_effective_plane` and the lineage vocabulary tests (R3-28) | accepted, not a weakening |
| I10-A D-11 | the remote-key tests live in the database module (they need the real ledger) | accepted |
| I10-A D-12 | 6 names added to the transport's mutating-name exemption (the 3 `.create` names append the Principal's own immutable plane rows; the 3 `schedule_scenario_outputs.*` names trip only on "put" in "outputs"); explicit and enumerated | accepted |
| I10-A D-13 | the Reports suite upgrades to its own revision; only `HEAD` moves (15.2) | accepted |
| I10-A D-14 | test naming | accepted (trivial) |
| I10-A P3-18 | green: unreachable at the handler (Project ids are Principal-partitioned and `owns_project` refuses first); the persistence `_mine` in `list_scenarios` is defence in depth | accepted as unreachable, not "covered" |
| I10-A P3-20 | green: layered on the S6-2 write-side `_require_effective_baseline` (S6-2's own prove-red isolates it); the ineligible half is guarded by FR10-F02's test | accepted as layered |
| I10-C C-1 | the port record `LineageScheduleFacts` and a non-abstract `RecordLineageRepository.schedule_node_facts` (default `{}`, so in-memory fakes keep working) in `src/my_pa/contracts/ports.py`; the SQL repository overrides it with Principal-partitioned plain `SELECT`s | accepted (the default fails closed: nodes are dropped, never mislabelled) |
| I10-C C-2 | a Schedule node with no facts (for example a Baseline with no event recorded by `N`) is dropped as `partial_native_history`; a summary the byte budget refuses drops its node with `truncated_budget` | accepted (hidden = absent) |
| I10-C C-3 | an extra validator on `ScheduleBaselineNodeSummary` (`operator_approved` iff an effective type; `authoritative` iff `approved`), so P3-57 is layered | accepted (defence in depth for 15.11.3a item 1) |
| I10-C C-4 | the publication summary's `data_date` is nullable (key always present); `status` is the stored status, equal to the effective status for every terminal (linkable) publication | not separately ruled (S6-3-U09) |
| I10-C C-5 | the page-size-1 walk lowers `MIN_LINEAGE_PAGE_SIZE` (public minimum 10) in the test and still runs the service and the real cursor; no web component renders virtual edges or summaries, so the edge and label enumerations live in the decoder | not separately ruled (trivial) |
| I10-C C-6 | `ops/runbooks/remote-mcp-cloudflare.md` inventory restated 37 (21 + 7 + 1 + 4 Reports custody + 4 baseline decisions = v13 `CONTROL_PLANE_EXCLUDED` 33 + 2 + 2); the base text (29) was stale after Reports | accepted |
| I10-C C-7 | `tests/ci_shard_weights.json` unchanged | accepted with residual S6-3-U11 |

#### 15.18.3 Open questions

R10 ruled on the 5 questions of revision 1: D20 rejected (operator exempt, F04); the I10-A
holding classification accepted (F08); U01 accepted with disclosure (F09); `denied(BASELINE_ID)`
kept (F10); the plane-off import answer is `PUBLICATION_ROLE` (F07). One question remains for
the R10 re-review:

1. (Answered by R10 re-review 1: D21 accepted.) S6-3-D21 removes `FOR SHARE` for the 6 schedule families instead of requiring `UPDATE` on
   them (R10-F12's stop rule). Is the immutability argument of 15.11.2 accepted, or should I10-B
   keep `FOR SHARE` and stop if the runtime role lacks `UPDATE`?
2. (Answered by R10 re-review 3: U08 accepted, with the guidance condition.) S6-3-U08 (15.11.3a item 3): is emitting schedule virtual edges only between nodes already
   reached, never traversing them, acceptable for S6-3, or must lineage expansion follow them?

### 15.19 Executed results (S6-3)

The implementing packages record their commands, counts, the revision B scratch-cluster
measurement and the prove-red outcomes here.

**Package I10-A (capabilities; branch `feat/schedule-scenarios-capabilities`, 2026-11-11, not
merged, migrated, granted or deployed).** Revision B is `b77334135653` (`down_revision =
"4c37731671fc"`; 128 revision files). Its window, measured on a Homebrew PostgreSQL 15.15
scratch cluster (`initdb --auth=trust`, loopback, `PGTZ=UTC`; synthetic `audit_events` rows
inserted under `session_replication_role = replica`, then `ANALYZE`), as the wall clock of
`alembic upgrade b77334135653` and of `alembic downgrade 4c37731671fc` from a fresh interpreter
(about 0.5 s of each is interpreter and Alembic start-up, not lock time):

| `audit_events` rows (`reltuples`) | `pg_relation_size` | upgrade (2 restatements) | clean downgrade (refusal scan + 2 restatements) |
|---|---|---|---|
| 100,000 | 16,719,872 bytes | 0.68 s | 0.68 s |
| 1,000,000 | 167,190,528 bytes | 1.54 s | 1.87 s |

Scale by Q10's `reltuples` and `pg_relation_size` on the production host (section 14.14's
rule); the lock is `ACCESS EXCLUSIVE` on `audit_events` for the whole window, so every
authorized request pauses for it. Package I10-A's commands, counts and prove-red outcomes are in
its handoff report; packages I10-B and I10-C add theirs here.

**Package I10-B (lineage; same branch, 2026-11-11, not merged, migrated, granted or deployed).**
The public lineage vocabulary is widened by exactly the S6-2 storage vocabulary (`RecordFamily`
13, `RelationType` 11, `NativeVirtualEdge` 9, `LINEAGE_FAMILY_READS` 13 keys,
`CONTESTABLE_RELATIONS` 10, `LINEAGE_READ_GENERATION` 2); the stored maps are now derived from the
public ones and are byte-for-byte the S6-2 values, so the `record_links` CHECK texts and revision
B are unchanged. **The 15.11.2 precondition holds:** `test_share_endpoint_needs_only_select_on_the_schedule_tables`
shares each of the 6 families (and a proposal and an intake publication) as a role holding exactly
the P-check ∪ Q8 privileges and schema usage (no `UPDATE` on the 5 tables other than
`schedule_publications`, asserted by `test_the_probe_role_holds_no_update_on_the_five_tables`);
no grant was added. Not implemented, stopped with a proposed amendment (S6-3-B01 in the I10-B
handoff): the 15.11.3 per-family summaries, their labels and the emission of the 8 native virtual
edges, whose public shapes (`LineageNodeView`, `VirtualEdgeView`, `LineagePathEdgeView` in
`src/my_pa/contracts/v1/record_lineage.py`) this note does not design; Schedule nodes are read,
emitted and paged as bare `{family, record_id}` nodes. Commands, counts and prove-red outcomes
are in the I10-B handoff report.

**Package I10-C (exposure; same branch, 2026-11-11, not merged, migrated, granted or deployed).**
ChatLLM is `chatllm-data-v13`: policy 281, `DATA_REQUIRED` 85, `DATA_CONDITIONAL` 159 (the 22
client-usable names on the new `SCHEDULE_SCENARIOS` prerequisite, desired iff `schedule and
schedule_scenarios`), `CONTROL_PLANE_EXCLUDED` 33 (the 4 operator decisions with
`_SCHEDULE_BASELINE_APPROVAL_EXCLUSION`), `COMPATIBILITY_ONLY` 2, `OPERATOR_DECISION_REQUIRED`
2. `test_v13_targets` **executed** the planner: full 175, default 109, full + schedule 181, full
+ schedule + scenarios 203, full + lineage + program + schedule 215 (+ scenarios 237), default +
lineage + program + schedule 147 (+ scenarios 169), the scenario switch alone composing nothing,
1,024 compositions. A client provisioned at v10, v11 or v12 stays healthy while the plane is off;
with it on `profile-diff` adds exactly 22, 28, 33 or 39 names from the section 15.17 set, never
a removal (`test_old_client_stays_healthy_while_the_plane_is_off`); no MCP database profile
ceiling or opt-in names a plane capability (DV-01). The section 15.11.3a read shapes are
implemented: the strict per-family `schedule` node key (Baseline labels as of `N` exactly as
`_baseline_labels`), `NATIVE_VIRTUAL_EDGE_ENDPOINTS`, emission of the 8 Schedule edges between
nodes of an answer only and never traversed, the schedule edge item key and cursor position,
and `related_sha256` over both. The web `records.lineage` decoder, its tests, the committed
Python fixture (now carrying 3 Schedule nodes and a `scenario_version_of` edge) and the lineage
table test move in lockstep. The compact facade end to end, the client guidance section (with
the U08 sentence), runbook section 9 and the v12 → v13 sweep are in place. Local tiers at the
package head (scratch Homebrew PostgreSQL 15.15, `initdb --auth=trust`, `PGTZ=UTC`): FAST
45,837 passed, 138 skipped (the memory-row guard, 115, run alone in 792 s); database tier
(`(database_clone or database_transactional)` minus the recovery, e2e and migration markers)
4,983 passed, 15 skipped and the 2 `tests/contract/test_health_probe.py` failures that fail
identically at `59f333d7` on this server (they require PostgreSQL 17); recovery 86 passed;
`migration_empty_to_head` 22 passed; `migration_edge or migration` 2,178 passed; the frontend
typecheck, lint, 5,004 vitest cases, the 1,171 contract cases and the build pass. Prove-red
P3-30 to P3-34 and P3-48 to P3-58 each reddened its named test; P3-56 with the key alone
reddens through the position validator (P3-58's guard, layered), and P3-51 and P3-57 are also
held by the strict summary models; commands and outcomes are in the I10-C handoff report.

**Corrective FC-C1 (final review FR10, PASS_WITH_REQUIRED_CHANGES at `d6a035c5`; same branch,
2026-11-11).** Tests only, no behaviour change: `test_compare_refuses_a_non_effective_baseline`
(4), `test_an_ineligible_baseline_answers_conflict_status` (2; an import-time approval whose
publication ends `review_required`) and a counted `conflict(expected_version)` and
`rate_limited(storage_quota)` in `test_refusal_counting_scope`. Prove-red P3-59 (FR10 M13) reddens
the 4 compare cases; its 2 ineligible cases stay green under M13 because the S5 delta then
refuses the `review_required` publication with `conflict(status)` (layered; P3-60 isolates the
branch). P3-60 (M3) reddens both ineligible cases (`conflict(baseline_id)`); P3-61 (M4) reddens
`test_refusal_counting_scope` (1 counted refusal instead of 2). The database selection
`database or recovery or e2e` collects 6,785 (+6). Divergences D-1…D-14 and C-1…C-7 are in
section 15.18.2b; the CI headroom residual is S6-3-U11.

### 15.20 R10 findings → fixes (revision R10-1)

Design review R10 (PASS_WITH_REQUIRED_CHANGES at `de81d3d8`); Orchestrator dispositions applied.

| Finding | Fix (section) |
|---|---|
| R10-F01 | import gates and `operator_channel` hand-off in `ScheduleApplication.import_publication` after E-10/E-12, keyed on `request.approval`, with a `scenario_plane_effective` keyword; `schedules.py` (and `compare.py` if needed) owned by I10-A; P3-43 (15.8, 15.9, 15.15; S6-3-D22) |
| R10-F02 | refusal bound before `compute_and_store_cpm_run`; read-only `admit_write` pre-check under P before the leased compute, authoritative again in step 5; `test_over_budget_cpm_run_never_computes`, P3-41; residual S6-3-U06 (15.10, 15.16; S6-3-D23) |
| R10-F03 | v12 → v13 sweep of every live profile command and current-version statement, `_CURRENT` pin, the "v13 with the switch off desires exactly v12" sentence, owned by I10-C (15.2, 15.15, 15.17) |
| R10-F04 | D20 replaced: operator exempt from the hourly CPM-units bound; operation budget and lease universal; bounds table, 15.7.2 row, P3-16, `test_cpm_units_bound_is_enforced[operator_exempt]`, `test_attested_operator_is_never_budgeted[cpm_units]`; S6-3-U07 (15.10, 15.16, 15.18) |
| R10-F05 | expected diff 22 or 28 (the 6 S5b-2 reads listed) (15.12.1, 15.17) |
| R10-F06 | bucket only from `PlaneProvenance`; propose/withdraw rules stated; P3-21 restated, P3-42 added; test parametrized (15.4, 15.16; S6-3-D24) |
| R10-F07 | plane-off role-`baseline` answer `invalid_request(PUBLICATION_ROLE)`; amendments of 6.2, 12.2 and P56; the test sends all 4 approval fields (6.2, 12.2, 15.8, 15.9, 15.16; S6-3-D14) |
| R10-F08 | I10-A interim pins stated (policy 281, `CONTROL_PLANE_EXCLUDED` 55, `DATA_CONDITIONAL` 137, v12, targets and `_CURRENT` unchanged; the holding rationale constant) (15.2, 15.15) |
| R10-F09 | U01 states the unrecordable large criticality outputs; the `MAX_REQUEST_BYTES` docstring update is I10-A's; guidance and docstrings state the limit (15.12.5, 15.15, 15.18) |
| R10-F10 | `denied(BASELINE_ID)` kept (S6-3-D25) |
| R10-F11 | D13 extended to steps 1–4 as an amendment of 8.3; `test_refusal_counting_scope`, P3-45 (8.3, 15.10, 15.18) |
| R10-F12 | repository truth R3-29 (grant-free revisions; P/Q checks assert no `UPDATE` on 5 of the 6 tables); no `FOR SHARE` for the 6 families (S6-3-D21); I10-B precondition test and stop rule; P3-44; open question 1 (15.1, 15.11.2, 15.18.3) |
| R10-F13 | `IdKind` module path; the non-effective `from_baseline_id`/`compare` cases mapped (15.1, 15.7.2) |
| R10 limits | D10 verified: the 14 `change_set_*` values collide with nothing (15.7.1); the base planner targets were executed and the S6-3 rule verified over 512 compositions (15.2) |

**Re-review R10-RR1 (PASS_WITH_REQUIRED_CHANGES at `a0eaca31`; S6-3-D21 accepted) → fixes
(revision R10-2).**

| Finding | Fix (section) |
|---|---|
| R10-N01 | the CPM `admit_write` pre-check runs only on the compute path, after both the replay and the natural-key probe miss, with 0 new bytes; step 5 stays authoritative with the actual size; test cases `[replay_over_budget]`, `[natural_key_over_byte_quota]`; P3-46, P3-47 (15.10, 15.16) |
| R10-N02 | commissioning go/no-go as a set rule (no removals; every add in the 22 ∪ the 6 S5b-2 reads ∪ the 11 v12 Reports names, listed; all 22 present), with 22/28/33/39 as the expected cases; 15.12.1 aligned (15.12.1, 15.17) |
| R10-N03 | D21 justification reworded: facts are fixed once linkable or move only toward linkable; the evidence (lifecycle, row-link and intake triggers; `_mark_intake`); revoke takes no row lock (15.11.2) |
| R10-N04 | P3-44 targets `schedule_activity` (no `UPDATE`), expects `42501` under the P-check ∪ Q8 role; the precondition test runs every family, the publication family included (15.11.2, 15.16.3) |
| R10-N05 | the S6-2-D04 row points to the S6-3-D14 amendment (14.12.1) |
| R10-N06 (re-review 2) | P3-47 run 1 could not fail (a natural-key hit never reaches the pre-check): new case `byte_headroom_below_content_size` (headroom > 0 and < `content_size_bytes`; the compute seam is reached) carries run 1; `natural_key_over_byte_quota` keeps run 2 (15.16.2, 15.16.3) |

**S6-3-B01 → design addendum (revision R10-3, at `bb6bbe8d`).**

| Item | Fix (section) |
|---|---|
| S6-3-B01 (I10-B stop) | section 15.11.3a: the `schedule` node key and its exact per-family keys and labels; the 9-entry endpoint table; emission between reached nodes only, never traversed; order, budgets, paging, as-of, `related_sha256` coverage, additive compatibility and web lockstep; tests and P3-48–P3-55; ownership to I10-C (15.15); residuals S6-3-U08 (deferral of traversal, for the reviewer), U09, U10; I10-B divergences B-02–B-08 recorded unruled (15.18.2a) |

**R10 re-review 3 (PASS_WITH_REQUIRED_CHANGES at `d61a7290`) → fixes (revision R10-4).**

| Finding | Fix (section) |
|---|---|
| R10-S01 | schedule virtual-edge paging key `v:<edge_type>:<from.family>:<from.record_id>:<to.family>:<to.record_id>` in `_item_key` (note-edge key unchanged); `test_schedule_virtual_edges_page_without_repeat`; P3-56; `_item_key` in the ownership (15.11.3a items 5, 9, 10) |
| R10-S02 | Baseline node labels mirror `_baseline_labels` exactly (`authority` by `effective_type`, `authoritative` = effective; `effective_type` and `label` as of N); summary test over all 6 statuses; P3-57 (15.11.3a items 1, 9) |
| R10-S03 | `schedule` is a union of strict per-family models, inserted from its own `exclude_none=False` dump; null keys asserted (15.11.3a item 1) |
| R10-S04 | no node creation-time filter; eligibility as of N = `complete`/`partial` with `completed_at ≤ N`; as-of test case added (15.11.3a items 6, 9) |
| R10-S05 | P3-53 restated as "the service passes no `withheld_families`", declared layered on I10-B (15.16.3) |
| R10-S06 | node-only label row (`source_bound_derived`, `schedule_publication`, `schedule_activity`) in 15.6.3 and the web label enumeration; measured `_size` instead of + 192 (15.6.3, 15.11.3a items 5, 8) |
| R10-S07 | "the related decoder" dropped: no related-read web decoder exists (15.11.3a item 8, 15.15) |
| Rulings | U08 accepted with the guidance condition (15.12.5 states it); U09 accepted, reason corrected; U10 accepted; P3-54 mutation clarified (15.12.5, 15.16.3, 15.18.2) |

**R10 re-review 4 (at `5fcebff5`) → fix (revision R10-5).**

| Finding | Fix (section) |
|---|---|
| R10-T01 | `_lineage_position` accepts the schedule edge key form (schedule edge type, families from `NATIVE_VIRTUAL_EDGE_ENDPOINTS`, ids validated per family) besides `v:<note_version_id>`, amending S3 section 5; owned by I10-C; the page-size-1 test decodes it; P3-58 (15.11.3a items 5, 10; 15.16.3) |

**Final review FR10 (PASS_WITH_REQUIRED_CHANGES at `d6a035c5`) → corrective FC-C1.**

| Finding | Fix (section) |
|---|---|
| FR10-F01 | `test_compare_refuses_a_non_effective_baseline`; P3-59 (15.16.2, 15.16.3, 15.19) |
| FR10-F02 | `test_an_ineligible_baseline_answers_conflict_status`; P3-60 (15.16.2, 15.16.3, 15.19) |
| FR10-F03 | `test_refusal_counting_scope` counts a conflict and a quota refusal; P3-61 (15.16.3, 15.19) |
| FR10-F04 | 15.18.2b (I10-A D-1…D-14, I10-C C-1…C-7 with FR10's rulings); the compare-cursor note in 15.7.2; B-02…B-08 marked ruled, B-06 folded into S6-3-U10 (15.7.2, 15.18) |
| FR10-F05 | residual S6-3-U11 (15.18.2) |
