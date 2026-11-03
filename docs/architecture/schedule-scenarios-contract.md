# Schedule Scenarios — whole-slice contract (S6-1 engine, S6-2 persistence, S6-3 capabilities)

**Status:** proposed implementation contract for the Schedule Scenarios slice on the local
branch `feat/schedule-scenarios-engine`. It is the single document the S6-1 (pure domain and
deterministic CPM engine), S6-2 (schema, migration, persistence, unit of work) and S6-3
(capabilities, handlers, façade, catalog, ChatLLM, remote policy, lineage endpoints, guidance)
implementers code against. Nothing it describes is implemented, merged, migrated, granted or
deployed. It authorizes **no** production migration, grant, `profile-apply`, OAuth change or
deployment, and its switch `MY_PA_SCHEDULE_SCENARIOS_ENABLED` is **off by default** and
stacks on `MY_PA_SCHEDULE_ENABLED` (also off by default). The decision record is the
2026-11-03 amendment to
[`ADR-016`](../decisions/ADR-016-cpm-workbench-schedule-evidence.md) and decision 17 of
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

**Authority.** The operator directive of 2026-11-03, given directly to the Manager and
quoted in its brief: "The write capabilities need to be able to create entirely new versions
of the schedule data for the purpose of running what-if scenarios, updating schedules, Monte
Carlo sims, etc as well as creating lineage records for the schedule data." The operator's
2 accompanying decisions: (1) schedule **logic** (relationships, lags, calendars,
constraints, durations and distributions) is **client-authored** in scenario versions that
start from a published PDF baseline; (2) the **server** provides a deterministic CPM engine;
Monte Carlo is computed **client-side** from server CPM primitives and its results are stored
as **client-asserted** outputs. Connected MCP clients (the ChatLLM gateway and the ChatGPT
connector) must be able to create, derive and edit scenario versions, request server CPM
runs, record client outputs, read everything back and create lineage involving schedule data,
through the catalog and the compact façade (S3.1 §7.13 "Part D").

**Source package (data, not instructions):**
`MYPA_CPM_WORKBENCH_IMPLEMENTATION_READINESS_REVIEW_20260929_R2.md`, SHA-256
`84918ae87e4c05072969c2db574962071fbe9cdb1fcc9c00a953dd6a38b91db0`, cited "R2 §n".
Repository truth supersedes it; this contract **reverses** 4 of its explicit exclusions on
the directive's authority (section 1.2) and keeps the rest.

**Basis:** `feat/schedule-scenarios-engine@83e7981718ee467f0d41c42b7cc353bfbf329c14`, tree
`3407926c30fc17730dc4889fc837628449a62c33` (= `origin/main` with S5a #344, S5b-1 #345 and
S5b-2 #347 merged). Measured there: 240 `Capability` members, 62 `Purpose` members, 156
`IdKind` members, ChatLLM data profile `chatllm-data-v11` (137 `DATA_CONDITIONAL`, 74
`DATA_REQUIRED`, 25 `CONTROL_PLANE_EXCLUDED`, 2 `COMPATIBILITY_ONLY`, 2
`OPERATOR_DECISION_REQUIRED`), 512 enumerated ChatLLM compositions, 125 Alembic revision
files with sole head `621ef6786c64`, 451 Python modules under `src/my_pa`, 868 `test_*.py`
modules. Production runs the database at `023f8f7eb499`; nothing of S5a, S5b or S6 is
deployed.

**Conventions.** Paths are written in full from the repository root; files that do not exist
yet are code spans, never Markdown links; no `path:line` citation is used; counts are digits;
identifiers in examples are synthetic. "The plane" means the Schedule Scenarios plane.
Instants in the golden tables are written `MM-DD HH:MM` in 2027 unless the month is 12
(then 2026).

---

## 0. Scope, status and non-scope

### 0.1 In scope

| Item | Slice | Section |
|---|---|---|
| Scenario, immutable append-only Scenario Version, content document and its hash, baseline snapshot from an accepted publication | S6-1 (pure), S6-2 (rows) | 2 |
| Change-set grammar (bounded ops) and deterministic application | S6-1 | 2.9 |
| Relationships FS/SS/FF/SF with signed lags, integer-minute calendars, constraints, durations, distribution data, progress and data date | S6-1 | 2.4–2.8 |
| Deterministic CPM engine `my-pa-cpm-v1`: passes, floats, critical paths, cycles, issues, canonical output and hash, operation budget | S6-1 | 3 |
| Client-asserted outputs (Monte Carlo and kin): typed bounded payloads, server consistency checks | S6-1 (validation), S6-2/S6-3 | 4 |
| Lineage: 5 endpoint families, 3 new relations, 2 widened relations, native virtual edges | S6-2 (vocabulary + CHECK), S6-3 (validators, reads) | 5 |
| 14 capabilities, 2 purposes, switch, ChatLLM `chatllm-data-v12`, remote and façade | S6-3 | 6 |
| Addendum: series auto-matching on import; derived current published version; append-only authority designations; 4 more capabilities | S6-1 (pure), S6-2, S6-3 | 11 |
| OD-08 labelling and exclusion from Program reporting | S6-3 guards | 7 |
| Bounds, DoS analysis, isolation | all | 8 |

### 0.2 Status (honest)

Directive-selected design, not ratified for production. Nothing is implemented, merged,
migrated, granted or deployed. Every switch is default off in code. The server verifies
shapes, bounds, ownership, references and its own computation; it cannot verify that any
client-authored logic, duration, distribution or Monte Carlo result is true, and never says
so (section 7).

### 0.3 Out of scope (all slices)

Production anything; real schedule files; XER/XML; server-side Monte Carlo sampling or any
server randomness; resource loading/levelling; probabilistic branching, risk events and
duration correlation (S6-U03); a Program-level critical path (stays **UNPROVEN**, section
7); converting scenario data into a publication, a Stable Activity or any source-bound row;
web UI; editing S5a/S5b behaviour, profile constants or goldens; a scenario Record Event
family; persisted lineage of scenario activities below the version grain (S6-U05).

---

## 1. Repository reauthentication and divergence table

### 1.1 Repository truth (re-measured at the basis)

| # | Directive / R2 claim | Repository truth at `83e79817` | Decision |
|---|---|---|---|
| T6-01 | Activities have stable identity across publications | `StableScheduleActivity` (`sact_`) = exact published Activity ID inside one Series (`src/my_pa/domain/schedule/model.py`); visible only through a row of the accepted parser run of a `complete`/`partial` publication (S5b-1 U-03, S5b-2 §3.9) | a baseline-derived scenario activity is keyed by its `sact_` id; client-added activities get a scenario-local key `x:<token>` (section 2.4); a client can never mint an `sact_` key |
| T6-02 | The PDF yields schedule logic | The parser yields per row only: `published_activity_id`, `activity_name`, `row_type` (`activity`/`milestone`; summaries and `ambiguous` rows are never activities), `hierarchy_path` (≤ 32 labels), `original_duration`/`remaining_duration` (`ScheduleDurationCell`: `Decimal` with exponent −3, **no unit** — S5a §4.8 "No unit conversion"), `start`/`finish` (`ScheduleDateCell`: a `date`, no time, and a raw `*` marker that S5a §4.7 says has **no meaning**), plus the publication `data_date` (always set for `complete`/`partial`, S5b-2 T2-27). No relationship, lag, calendar, constraint, float, actual or critical flag exists | logic is client-authored (operator decision 1); the snapshot copies durations through a client-declared `minutes_per_source_unit` (section 2.5) and keeps the published dates and marker only as an inert `published_reference` |
| T6-03 | Publication states | `SchedulePublicationStatus`: `queued`, `processing`, `complete`, `partial`, `review_required`, `failed`; effective status (`effective_publication_status`) reads `failed` for an exhausted job | a snapshot source must be **effective** `complete` or `partial` (as `schedule_activities.list`), any role |
| T6-04 | Schedule tables | S5b-1 (`6c2306330ceb`): 7 `knowledge.schedule_*` tables, Principal-partitioned, F1–F9 guards; S5b-2 (`621ef6786c64`) admitted the vocabulary | S6-2 adds new `knowledge.schedule_scenario*` / `schedule_cpm_runs` tables only; no S5 table or revision is edited |
| T6-05 | S5b-2 surface | 7 capabilities (`schedule_publications.import` operator-only attested-local; 6 scopeless reads, purpose `schedule_read`), switch `MY_PA_SCHEDULE_ENABLED` (`Settings.schedule_enabled`), ChatLLM `chatllm-data-v11` with prerequisite `SCHEDULE`, feature label `schedule` via `_FEATURE_BY_FAMILY`, targets 164/98 (full/default, switch off), 170 (full + schedule), 204 (full + lineage + program + schedule), 136 (default + all 3), 512 compositions | the plane stacks on the schedule switch; ChatLLM `chatllm-data-v12` with prerequisite `SCHEDULE_SCENARIOS` (section 6.6) |
| T6-06 | Lineage families/relations | `src/my_pa/domain/lineage/vocabulary.py`: `RecordFamily` 7 members; `RelationType` 8 (`issue_member` + 7 semantic); `RELATION_MATRIX`; `RECORD_FAMILY_ID_KINDS`; `LINEAGE_FAMILY_READS`; `NativeVirtualEdge` 1 member; DB CHECKs `a_record_link_from_family_is_known`, `…_to_family_is_known`, `from_id_is_an_opaque_identifier`, `a_record_link_relation_type_is_known`, `a_record_link_pair_is_admitted` derived from these in `tables.py`; evidence rules in `src/my_pa/application/lineage_endpoints.py` `require_relation_evidence` | widened together in S6-2 (enum + CHECK in one revision) per ADR-015 decision 6 and the S1 "widen both together" rule; ADR-015 decision 17 records the amendment (section 5) |
| T6-07 | Lineage provenance and rate | S3.1: acceptance basis `client_identified` vs `user_confirmed`, decision channels, `asserting_client_id` (≤ 256), `user_directed` claim; budgets 120/hour and 1,000/day per writer bucket, 2,000/day per Principal (`src/my_pa/application/lineage_rate.py`); write-path disclosure: a subject in a family the caller may not read answers as absent | reused unchanged for schedule-family links; the plane's own writes reuse the provenance derivation and get their own budget (section 8.3) |
| T6-08 | Program reporting / OD-08 | `src/my_pa/domain/program/vocabulary.py` `ProgramFamily` (6 members, no schedule); `src/my_pa/domain/program/reportability.py` `METRIC_CATALOGUE` (no schedule metric); S4 §12: `programs.schedule.milestones` not built; manifest lineage section `src/my_pa/domain/intelligence/source_manifest.py` (`_block_seeds`, `lineage_server_counts`, `lineage_section`) reads every `RecordFamily` member | scenario data joins no Program family or metric; the manifest lineage section is pinned to the 7 pre-S6 families (section 7) |
| T6-09 | Counts | 240 capabilities, 62 purposes, 156 `IdKind` | +14 → 254, +2 → 64, +4 → 160 (sections 2.1, 6) |
| T6-10 | `IdKind` prefixes | 156 members; prefix-free rule (no member a prefix of another) asserted by `tests/unit/test_identifiers.py` | `sscn`, `sscv`, `scpm`, `ssco` collide with none and are prefix-free against all 156 (measured by enumeration; a grep of `sscn_`, `sscv_`, `scpm_`, `ssco_` over `src`, `tests`, `web/src`, `migrations` finds nothing) |
| T6-11 | Decimal/time conventions | durations `Decimal` quantized to 3 places (`DURATION_EXPONENT = -3`); dates `datetime.date`; no `float` in canonical objects (S5a §6) | the plane uses **integer minutes** only (section 3.1); `Decimal` appears only in the snapshot conversion |
| T6-12 | Canonical JSON / hash helpers | `src/my_pa/domain/schedule/canonical.py` `canonical_json_bytes` (sorted keys, compact, `ensure_ascii=True`, `allow_nan=False`); digests are `sha256(domain_prefix + canonical)` lowercase hex (`schedule_import_request_digest`, prefix `b"cpm-schedule-import-v1\n"`) | every plane digest reuses `canonical_json_bytes` with its own `\n`-terminated domain prefix (section 2.3) |
| T6-13 | Cursor | `src/my_pa/domain/schedule/cursor.py`: base64url canonical JSON, 512 characters, TTL 300 s, binding = SHA-256 of capability/Principal/purpose/request/page size/order, `ScheduleCursorOrder` (5 orders) | S6-3 appends orders to `ScheduleCursorOrder` (section 6.4); no second cursor module |
| T6-14 | Domain package guards | `tests/architecture/test_cpm_full_parser_scope.py`: everything under `src/my_pa/domain/schedule` is stdlib-only plus `my_pa.domain.schedule` and `my_pa.domain.common.identifiers`, neither logs nor prints nor opens files, and carries no denylisted token | the S6-1 package lives at `src/my_pa/domain/schedule/scenario/` so those guards bind it automatically; S6-1 adds a no-float/no-clock/no-randomness guard (section 9.1) |
| T6-15 | Disclosure trust levels | `TrustLevel`: `SOURCE_ORIGINAL`, `SOURCE_BOUND_DERIVED`, `MODEL_PROPOSED` (the last unused in `src`) | every plane answer is `MODEL_PROPOSED` with basis tokens; no new member (S6-D11, ruling R-3) |
| T6-16 | Remote idempotency | `src/my_pa/adapters/remote_request.py`: `_IDEMPOTENT_REMOTE_CAPABILITIES` = keyed writes whose key the server stamps from the payload (a remote caller may not send `idempotency_key`); `is_remote_idempotent` = server-replay set or `LINEAGE_WRITE_CAPABILITIES` | the 4 plane writes join `_IDEMPOTENT_REMOTE_CAPABILITIES`, and `is_remote_idempotent` gains them (section 6.7) |
| T6-17 | Scopeless policy | `src/my_pa/domain/policy/decision.py` `_SCOPELESS` holds the lineage writes and the 6 schedule reads | all 14 plane names join `_SCOPELESS`; `_requested_scope` empty-scope arm |
| T6-18 | Restricted MCP profiles | `src/my_pa/contracts/mcp_database_profiles.py`: no CPM privilege in any ceiling or opt-in | no plane name joins any ceiling or opt-in; a restricted composition never composes the plane factory |

### 1.2 R2 exclusions: reversed and kept

| R2 | Exclusion | Decision |
|---|---|---|
| §6 | "application-computed CPM, calendars, relationships, critical path, float" | **Reversed** for scenario versions only: the server computes CPM over client-authored logic, labelled `server_computed` over `client_authored` input, never over a publication |
| §6 / §29.6 | persisted comparison data (and by implication persisted derived schedule data) | **Reversed** for scenarios: versions, CPM results and client outputs are persisted, immutable rows. The publication delta stays on-demand and unpersisted |
| §6 / §33 | "schedule-specific Task/Commitment/Entity/Constraint links" | **Reversed** only as lineage associations (ADR-015 ledger) between the 5 families of section 5 and existing families, `client_identified` unless the human channel writes them; no native record is mutated, coerced or linked by a column |
| §6 | (no scenario data) | **Reversed**: scenario data is a new, explicitly non-authoritative data class |
| §6, §34 | fuzzy ID matching; AI-resolved canonical facts; XER/XML; frontend; production | **Kept** |
| §10, §29 | publications immutable source facts; baselines explicit | **Kept**: nothing in this plane writes a `schedule_*` S5 table |
| ADR-016 decision 4 | import operator-only attested-local | **Kept**: the plane reads accepted publications; it imports nothing |
| OD-08 | uncertified totals never reported | **Kept**: section 7 |

---

## 2. Domain model

### 2.1 Identifiers (S6-2 adds them; S6-1 code does not need them)

| `IdKind` member | Prefix | Row |
|---|---|---|
| `SCHEDULE_SCENARIO` | `sscn` | one Scenario |
| `SCHEDULE_SCENARIO_VERSION` | `sscv` | one immutable Scenario Version |
| `SCHEDULE_CPM_RUN` | `scpm` | one server CPM run of one version under one engine version |
| `SCHEDULE_SCENARIO_OUTPUT` | `ssco` | one client-asserted output |

Appended after `SCHEDULE_IMPORT_ISSUE` with the S5b-1 comment form (156 → 160). The plane's
idempotency ledger is keyed by `(principal_id, capability, idempotency_key)` (section 6.3)
and mints no identifier kind of its own.

### 2.2 Scenario and Scenario Version

| Record | Fields | Rules |
|---|---|---|
| Scenario | `scenario_id`, `principal_id`, `project_id`, `series_id`, `name` (`normalize_display_text`, 1..200 characters, the Series-name refusal set), `description` (0..2,000 characters or null), `origin_kind` ∈ `publication`\|`version`, `origin_publication_id` (`spub`, iff `publication`), `origin_version_id` (`sscv`, iff `version`, of the same Principal, any Scenario of the same Series), provenance (section 6.5), `created_at` | immutable after insert (no update capability exists; S6-U01). `project_id`/`series_id` are the origin's |
| Scenario Version | `version_id`, `principal_id`, `scenario_id`, `version_no` (1..500), `parent_version_id` (null iff `version_no = 1`, else the version `version_no − 1` of the same Scenario), `label` ∈ `what_if`\|`update`\|`simulation_input`, `note` (0..2,000 characters or null), `content_sha256`, `content_size_bytes`, content (section 2.3), `change_set_sha256` and change set (null iff `version_no = 1`), `snapshot_report` (iff `version_no = 1`), counts (`activity_count`, `relationship_count`, `calendar_count`), `distribution_spec_sha256` (section 4.3), provenance, `created_at` | immutable, append-only. A Scenario is a **linear** chain; a branch is a new Scenario whose version 1 copies another version (`origin_kind = version`). Version 1 is the exact snapshot (publication origin) or the byte-identical copy of the origin version's content (version origin); edits start at version 2 (S6-D03) |

The label is metadata, never semantics: the engine never reads it. `update` means "the client
updated this schedule (progress, re-forecast)"; `simulation_input` means "prepared for a
client Monte Carlo"; `what_if` is everything else. None makes the version authoritative.

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
| Fixed keys | every key above is present on every object; absent values are explicit `null` (`wbs_path`, `calendar`, `original_minutes`, `remaining_minutes`, `progress`, `distribution`, `published_reference`, `must_finish_by`); `constraints` is a list (possibly empty) |
| Ordering | `calendars` by `key`; `exceptions` by `date`; `activities` by `key`; `constraints` by `type` in the order `SNET, FNET, SNLT, FNLT, MSO, MFO`; `relationships` by `(pred, succ)`; all string comparison is Python `str` order (code points) |
| Strings | NFC (`normalize_display_text` for `name` and each `wbs_path` label; keys are ASCII by grammar) |
| Numbers | Python `int` only; a `bool` is never an `int`; no `float`, no `Decimal` (durations in `published_reference` are the S5b-2 decimal **strings**) |
| Instants | `YYYY-MM-DDTHH:MM`, minute resolution, naive (the schedule's own wall clock; no time zone is modelled, S6-D07) |
| Bytes | `canonical_json_bytes(document)` (T6-12) |
| Hash | `content_sha256 = sha256(b"schedule-scenario-content-v1\n" + bytes)` lowercase hex |
| Excluded | every identifier of the version, Scenario, parent, label, note, provenance and time, so equal logic hashes equal across versions and Scenarios |
| Bound | `content_size_bytes ≤ 33,554,432` (32 MiB) or the write is `invalid_request(CONTENT_SIZE)` |

The change set (section 2.9) is stored as `schedule-scenario-change-set-v1`
(`{"schema": ..., "ops": [...]}`, ops in request order) with
`change_set_sha256 = sha256(b"schedule-scenario-change-set-v1\n" + canonical)`.

### 2.4 Activities and keys

| Field | Rule |
|---|---|
| `key` | baseline: the `sact_` identifier (validated `IdKind.SCHEDULE_ACTIVITY`); added: `x:` + `[A-Za-z0-9_.-]{1,64}`. Unique within a version. `activity.add` refuses an `sact_` key (`invalid_request(ACTIVITY_KEY)`), so a client never fabricates source identity. A key removed in a version may be re-added later only if it is an `x:` key; a removed baseline activity cannot be restored in that Scenario (fork an earlier version instead; S6-U02) |
| `name` | 1..2,000 characters after `normalize_display_text` |
| `kind` | `task` or `milestone`; a `milestone` has `original_minutes = remaining_minutes = 0` |
| `wbs_path` | null or 1..32 labels, each 1..2,000 characters (S5b constants); inert to the engine |
| `calendar` | null (= `settings.default_calendar`) or an existing calendar key |
| `original_minutes` | null or 0..5,256,000; informational to the engine |
| `remaining_minutes` | null or 0..5,256,000; the duration the engine schedules (section 3.5); null makes the CPM run `rejected` with `missing_duration` |
| `published_reference` | set only by the snapshot, never by an op; null for added activities |

### 2.5 Baseline snapshot (version 1 from a publication)

Input: an owned publication whose **effective** status is `complete` or `partial` (else
`conflict(STATUS)`), `minutes_per_source_unit` (integer 1..1,440, required — the PDF carries
no unit, T6-02; S6-O02), 1..32 calendars, `default_calendar`, and an optional
`data_date_time` (`HH:MM`, default `00:00`).

| Content field | Snapshot value |
|---|---|
| `data_date` | the publication's `data_date` at `data_date_time` |
| `settings` | `default_calendar` as given; `lag_calendar = predecessor`, `progress_policy = retained_logic`, `must_finish_by = null`, `critical_float_threshold_minutes = 0` (S6-O03..O06 defaults) |
| activities | exactly the accepted parser run's `activity` and `milestone` rows (the `schedule_activities.list` set, bounded 25,000), one per Stable Activity; `ambiguous` and summary rows are never copied |
| `key` | the row's `schedule_activity_id` |
| `name`, `wbs_path` | `activity_name`, `hierarchy_path` |
| `kind` | `activity → task`, `milestone → milestone` |
| `calendar` | null |
| `original_minutes` / `remaining_minutes` | for a `published_value` cell: `int((value * minutes_per_source_unit).quantize(Decimal(1), ROUND_HALF_EVEN))`; any other state: null. A `milestone` gets 0 and 0 whatever its cells say. A non-integral product is counted in `snapshot_report.durations_quantized` |
| `constraints`, `progress`, `distribution` | empty, null, null — the `*` marker is **not** read as an actual or a constraint (S5a §4.7) |
| `published_reference` | the publication id, the published Activity ID and the 4 cells as S5b-2 §3.5.2 serializes them |
| relationships | none |

`snapshot_report` = `{activities, milestones, durations_quantized, original_missing,
remaining_missing}` (non-negative integers). A snapshot whose content exceeds 32 MiB is
`invalid_request(CONTENT_SIZE)`.

### 2.6 Relationships

`{pred, succ, type ∈ FS|SS|FF|SF, lag_minutes}`; both keys exist in the version (else the op
is refused, so a stored version has no dangling reference); `pred ≠ succ`; at most one
relationship per ordered `(pred, succ)` (a second type between the same pair is refused,
S6-D05); `lag_minutes` is a signed integer in `[−1,051,200, 1,051,200]`; a negative lag is a
lead and is allowed. Cycles are **storable** (a client may be mid-edit) and are reported by
the CPM run (section 3.4).

### 2.7 Calendars

| Item | Rule |
|---|---|
| `key` | `[a-z0-9_-]{1,32}`, unique; 1..32 calendars per version |
| `week` | exactly 7 day patterns, Monday first (`date.weekday()` order) |
| day pattern / exception intervals | 0..4 intervals `[s, e)`, integers, `0 ≤ s < e ≤ 1,440`, sorted, strictly separated (`e_k < s_{k+1}`, so the representation is canonical — touching intervals must be merged by the client) |
| working week | the 7 patterns together hold ≥ 1 working minute, else `invalid_request(CALENDAR)` |
| `exceptions` | dates `2000-01-01..2099-12-31`, unique; intervals replace that date's pattern; an empty list is a holiday; ≤ 1,000 per calendar and ≤ 2,000 per version |
| default | `settings.default_calendar` must exist; `calendar.remove` of the default or of a referenced calendar is refused |

### 2.8 Constraints, progress, durations and distributions

**Constraints** (closed set; at most 1 "early" ∈ {`SNET`, `FNET`} and at most 1 "late" ∈
{`SNLT`, `FNLT`}, or exactly 1 "mandatory" ∈ {`MSO`, `MFO`} and nothing else; `at` within the
horizon of section 3.1). Semantics are in section 3.5/3.6; they apply only to `not_started`
activities, and a constraint on a started activity is kept in content and reported
`constraint_ignored_started`.

| Type | Kind | Forward | Backward |
|---|---|---|---|
| `SNET` | hard early | start bound `at` | — |
| `FNET` | hard early | start bound `retreat(C, at, d)` | — |
| `SNLT` | soft late | — (violation reported) | finish bound `advance(C, at, d)` |
| `FNLT` | soft late | — (violation reported) | finish bound `at` |
| `MSO` | mandatory | start := `at` (overrides logic, reported) | finish := `advance(C, at, d)` |
| `MFO` | mandatory | start := `retreat(C, at, d)` | finish := `at` |

**Progress.** `progress` null = `not_started`; `{actual_start, null}` = `in_progress`;
`{actual_start, actual_finish}` = `complete`. `actual_start ≤ data_date`;
`actual_start ≤ actual_finish ≤ data_date`; `actual_finish` without `actual_start` is
refused; a `complete` activity has `remaining_minutes = 0` (the op sets it); an
`in_progress` activity keeps its `remaining_minutes` (≥ 0). Out-of-sequence progress is
**stored** and reported (section 3.10), never refused.

**Durations.** Integer working minutes on the activity's calendar. The engine reads only
`remaining_minutes` (section 3.5).

**Distributions** (data only; the server never samples, ever). Each applies to the
activity's remaining duration, in integer minutes in `[0, 5,256,000]`:

| `kind` | Fields | Validation |
|---|---|---|
| `triangular` | `min`, `mode`, `max` | `min ≤ mode ≤ max`, `min < max` |
| `pert` | `min`, `mode`, `max` | same (the client's PERT shape parameter is its own; not stored) |
| `uniform` | `min`, `max` | `min < max` |
| `bounded_normal` | `mean`, `sd`, `min`, `max` | `sd > 0`, `min ≤ mean ≤ max`, `min < max` |

### 2.9 Change-set grammar and application

A change set is 1..5,000 ops, canonical size ≤ 4,194,304 bytes. Ops apply **in request
order** to a working copy of the parent content; each op is validated against the state left
by the ops before it; the first failing op refuses the whole change set and nothing is
written. The pure function returns `ChangeSetRefusal(op_index, op_error)`; the public error
is `invalid_request` with the safe details `CHANGE_SET` and the one `SafeDetail` member
named for its `op_error` (for example `change_set_key_absent`). The repository's error
contract carries only closed tokens, so the 0-based `op_index` is **not** disclosed in this
slice (S6-U09). No content is echoed. After the last op the whole
content is re-validated (sections 2.4–2.8) and canonicalized; an empty effective change
(content hash equal to the parent's) is allowed and recorded.

| Op | Fields | Effect / refusal |
|---|---|---|
| `activity.add` | `key` (`x:`), `name`, `kind`, `calendar`, `original_minutes`, `remaining_minutes`, `wbs_path` | adds; refuses an existing key or an `sact_` key |
| `activity.edit` | `key`, any of `name`, `kind`, `calendar`, `wbs_path` | sets the given fields; `kind → milestone` requires both durations 0 |
| `activity.remove` | `key` | removes it **and** every relationship naming it; the cascade count is in `application_report.relationships_removed` |
| `duration.set` | `key`, `original_minutes` and/or `remaining_minutes` (null clears) | — |
| `distribution.set` / `distribution.clear` | `key`, `distribution` | — |
| `relationship.add` | `pred`, `succ`, `type`, `lag_minutes` | refuses an existing pair, a self-loop, a missing key |
| `relationship.edit` | `pred`, `succ`, `type` and/or `lag_minutes` | refuses an absent pair |
| `relationship.remove` | `pred`, `succ` | refuses an absent pair |
| `calendar.put` | a whole calendar | creates or replaces |
| `calendar.remove` | `key` | refuses the default or a referenced calendar |
| `calendar.exception.put` / `calendar.exception.remove` | `key`, `date`, `intervals` | — |
| `constraint.set` / `constraint.clear` | `key`, `type`, `at` | `set` replaces the same slot; mixing mandatory with others is refused |
| `progress.set` | `key`, `actual_start`, `actual_finish`, `remaining_minutes` | the section 2.8 rules, against the data date **after** this op's predecessors |
| `progress.clear` | `key` | back to `not_started` |
| `data_date.set` | `at` | re-validated at the end (progress must stay ≤ the new data date) |
| `settings.set` | any of `default_calendar`, `lag_calendar`, `progress_policy`, `must_finish_by`, `critical_float_threshold_minutes` (0..525,600) | — |

`op_error` codes (closed): `unknown_op`, `invalid_field`, `key_exists`, `key_absent`,
`source_key_refused`, `relationship_exists`, `relationship_absent`, `self_loop`,
`calendar_absent`, `calendar_in_use`, `constraint_conflict`, `progress_invalid`,
`bound_exceeded`. `application_report` = `{ops_applied, relationships_removed,
content_changed: bool}`.

### 2.10 Version bounds

| Bound | Value |
|---|---|
| activities | 25,000 (the S5a row cap) |
| relationships | 100,000 |
| calendars | 32; exceptions 1,000 per calendar, 2,000 per version |
| versions per Scenario | 500 |
| Scenarios per Principal | 200 |
| versions per Principal | 20,000 |
| content | 32 MiB canonical |

---

## 3. CPM engine `my-pa-cpm-v1`

### 3.1 Time model

Integer minutes on one naive axis: minute `0` = `2000-01-01T00:00`, horizon `H = 52,596,000`
= `2100-01-01T00:00`; valid instants are `0 ≤ t ≤ H`. Minute `m` is the half-open interval
`[m, m+1)`. Integers make every operation exact and platform-independent; `Decimal` would
add nothing (all inputs are whole minutes) and `float` is forbidden (S6-D06). Day index
`k = m // 1440`, minute-of-day `m % 1440`, date `2000-01-01 + k days`, weekday from
`date.weekday()`.

### 3.2 Calendar functions (calendar `C`)

| Function | Definition |
|---|---|
| `working(C, m)` | the day's pattern is the exception's intervals if the date has an exception, else `week[weekday]`; `m` works iff its minute-of-day lies in some `[s, e)` |
| `W(C, a, b)` | `a ≤ b`: the number of working minutes `m` with `a ≤ m < b`; `a > b`: `−W(C, b, a)` (signed, additive: `W(a,c) = W(a,b) + W(b,c)`) |
| `advance(C, t, d)`, `d ≥ 0` | `d = 0`: `t`. Else the smallest `t′ > t` with `W(C, t, t′) = d` (the end of the `d`-th working minute at or after `t`) |
| `retreat(C, t, d)`, `d ≥ 0` | `d = 0`: `t`. Else the largest `t′ < t` with `W(C, t′, t) = d` (the start of the `d`-th working minute before `t`) |
| `next_work(C, t)` | the smallest `m ≥ t` with `working(C, m)` |
| `prev_end(C, t)` | the largest `m ≤ t` with `working(C, m − 1)` |
| `shift(C, t, L)` | `advance(C, t, L)` if `L ≥ 0`, else `retreat(C, t, −L)` |
| `twenty_four_hour` | the implicit calendar in which every minute works (`W = b − a`, `advance = t + d`, …) |

Any result outside `[0, H]` rejects the run with `horizon_exceeded`. Implementation
requirement (not semantics): a per-calendar cumulative working-minute table by day over the
span reached, so each function is `O(log days)`; a minute-by-minute loop is forbidden outside
tests.

### 3.3 States, durations, lag calendar

`state(j)` from progress (section 2.8). `C_j` = the activity's calendar or the default.
`d_j = remaining_minutes` (for `not_started` and `in_progress`). `snap(j, t) = next_work(C_j,
t)` if `d_j > 0`, else `t`; `snap_back(j, t) = prev_end(C_j, t)` if `d_j > 0`, else `t`.
The lag calendar `Lc(i, k)` of relationship `i → k` is `C_i` (`predecessor`, default), `C_k`
(`successor`) or `twenty_four_hour`, from `settings.lag_calendar`. `D` = the data date.

### 3.4 Validation, topological order and cycles

Checked in this order; the first failing check rejects the run (status `rejected`, no
dates) and emits 1 issue per offending element: `empty_network` (0 activities),
`unknown_calendar` (per activity naming an absent calendar), `dangling_relationship` (per
relationship naming an absent key; both impossible for a stored version, checked
defensively), `missing_duration` (per incomplete activity with `remaining_minutes = null`),
then the topological sort.

**Order.** Kahn's algorithm with a min-heap on `key`: start with every activity of in-degree
0; pop the smallest key; append it; for each outgoing relationship in `succ` order decrement
the successor's in-degree and push it at 0. The pop sequence is the **topological order**
and `topo_index` (0-based). It depends only on content, never on input order.

**Cycle.** If fewer than all activities are popped, let `R` be the residual set. From
`s = min(R)`, repeatedly step to the smallest-key predecessor of the current node that lies
in `R` (every node of `R` has one) until a node repeats; the repeated segment, reversed into
successor order and rotated to start at its smallest key, is **the** reported cycle. The run
is `rejected` with one issue `cycle_detected` carrying `cycle` (the first 100 keys) and
`cycle_length`, and the summary carries `residual_count = |R|`. Cost `O(V + E)`.

### 3.5 Forward pass (topological order)

For each activity `j`:

1. `complete`: `ES = actual_start`, `EF = actual_finish`; nothing else.
2. Relationship bounds of an incoming `i → j` (type, lag `L`, `Lc = Lc(i, j)`), using `i`'s
   already computed `ES_i`, `EF_i`:

   | Type | Bound on `j`'s start |
   |---|---|
   | FS | `shift(Lc, EF_i, L)` |
   | SS | `shift(Lc, ES_i, L)` |
   | FF | `retreat(C_j, shift(Lc, EF_i, L), d_j)` |
   | SF | `retreat(C_j, shift(Lc, ES_i, L), d_j)` |

3. `not_started`: `x = snap(j, max({D} ∪ relationship bounds ∪ {SNET at} ∪ {retreat(C_j,
   FNET at, d_j)}))`. Mandatory pin `p` (`MSO`: `at`; `MFO`: `retreat(C_j, at, d_j)`): if
   `p < D`, report `mandatory_constraint_before_data_date` and drop the pin (both passes);
   else if `x > p` report `mandatory_constraint_overrides_logic`; then `x = p` (no snap).
   `ES = x`, `EF = advance(C_j, x, d_j)`.
4. `in_progress`: `ES = actual_start` (reported). The remaining work starts at
   `RS = snap(j, max({D} ∪ bounds))`, where the bounds are those of step 2 under
   `retained_logic` and none under `progress_override`; `EF = advance(C_j, RS, d_j)`.
   Constraints are ignored (section 2.8).

`RS_j = ES_j` for a `not_started` activity. Project finish `PF = max EF` over **all**
activities.

### 3.6 Backward pass (reverse topological order)

A relationship `j → k` is **considered** unless `k` is `complete`, or `k` is `in_progress`
under `progress_override`. For each activity `j`:

1. `complete`: `LS = ES`, `LF = EF`; total and free float are `null`; never critical.
2. Bounds on `j`'s finish from each considered `j → k` (`Lc = Lc(j, k)`; `LS_k`, `LF_k`
   already computed; for an `in_progress` `k`, `LS_k` is its late remaining start):

   | Type | Bound on `j`'s finish | When `j` is `in_progress` |
   |---|---|---|
   | FS | `shift(Lc, LS_k, −L)` | applies |
   | FF | `shift(Lc, LF_k, −L)` | applies |
   | SS | `advance(C_j, shift(Lc, LS_k, −L), d_j)` | skipped (its start has happened) |
   | SF | `advance(C_j, shift(Lc, LF_k, −L), d_j)` | skipped |

3. If step 2 produced **no** bound — `j` has no considered outgoing relationship, or `j` is
   `in_progress` and every considered one is SS/SF — add the open-end bound
   `must_finish_by` if set, else `PF` (S6-D08).
4. `not_started` only: add `FNLT at` and `advance(C_j, SNLT at, d_j)`.
5. `y = snap_back(j, min(bounds))`; a kept mandatory pin overrides: `MFO`: `y = at`; `MSO`:
   `y = advance(C_j, at, d_j)`. `LF = y`, `LS = retreat(C_j, y, d_j)` (for an
   `in_progress` activity `LS` is its late **remaining** start).

### 3.7 Floats

| Quantity | Definition |
|---|---|
| total float `TF_j` (incomplete) | `W(C_j, EF_j, LF_j)` in minutes, signed (= `W(C_j, RS_j, LS_j)` by additivity) |
| relationship slack `rff_r` (considered `i → k`) | `B_r` = `shift(Lc, EF_i, L)` for FS/FF, `shift(Lc, ES_i, L)` for SS/SF; `Q_r` = `RS_k` for FS/SS, `EF_k` for FF/SF; `rff_r = W(C_k, B_r, Q_r)` (successor calendar) |
| free float `FF_j` (incomplete) | `min({TF_j} ∪ {rff_r : r considered outgoing from j})` — so `FF ≤ TF`; an open finish has `FF = TF` |
| driving | `rff_r = 0` |
| violated | `rff_r < 0` (only a mandatory pin produces it) |

### 3.8 Critical activities and paths

- **Critical:** incomplete and `TF ≤ critical_float_threshold_minutes` (default 0; the
  longest-path definition is not offered, S6-O07).
- **Critical graph:** critical activities and the driving relationships between 2 critical
  activities.
- **Paths:** start nodes = critical activities with no incoming critical-graph edge, in key
  order; from each, depth-first, successors in key order, emitting the path at every node
  with no outgoing critical-graph edge. Every descent ends in an emitted path, so the work is
  at most `MAX_CRITICAL_PATHS × V` steps. Emission stops at `MAX_CRITICAL_PATHS = 16` paths
  or before a path that would take the emitted key total past
  `MAX_CRITICAL_PATH_KEYS = 50,000`.
- **Count:** `critical_path_count` = the number of maximal paths by dynamic programming over
  the critical graph (`O(V + E)`), saturating at 1,000,000; `critical_paths_truncated =
  count > emitted`.

### 3.9 Open ends

`open_starts` = activities with no incoming relationship; `open_finishes` = no outgoing
relationship (structural, any state); each listed by key, first 1,000, with full counts.

### 3.10 Issues

| Code | Severity | Emitted when |
|---|---|---|
| `empty_network`, `unknown_calendar`, `dangling_relationship`, `missing_duration`, `cycle_detected`, `horizon_exceeded`, `operation_budget_exceeded` | error (run `rejected`) | section 3.4 / 3.2 / 3.11 |
| `out_of_sequence` | warning | a relationship `i → k` with `k` started and: FS with `i` not complete; SS with `i` not started; FF with `k` complete and `i` not complete; SF with `k` complete and `i` not started |
| `constraint_ignored_started` | warning | a started activity carries a constraint |
| `mandatory_constraint_overrides_logic` | warning | section 3.5 step 3 |
| `mandatory_constraint_before_data_date` | warning | section 3.5 step 3 |
| `start_no_later_than_violated` | warning | `ES_j > SNLT at` |
| `finish_no_later_than_violated` | warning | `EF_j > FNLT at` |
| `must_finish_by_violated` | warning (project) | `PF > must_finish_by` |
| `relationship_violated` | warning | `rff_r < 0` |

An issue is `{code, severity, activity_key | null, pred | null, succ | null}`; sorted by
`(severity rank error→warning, code declaration order, activity_key, pred, succ)` with null
first; the first 1,000 are listed and `issue_counts` holds every code's full count.

### 3.11 Output document, hash, determinism, budget

`schedule-cpm-result-v1`:

```json
{
  "schema": "schedule-cpm-result-v1",
  "engine_version": "my-pa-cpm-v1",
  "input_content_sha256": "<64 hex>",
  "status": "computed | rejected",
  "summary": {"data_date": "...", "project_finish": "... | null", "must_finish_by": "... | null", "activity_count": 0, "relationship_count": 0, "critical_count": 0, "negative_float_count": 0, "open_start_count": 0, "open_finish_count": 0, "critical_path_count": 0, "critical_paths_truncated": false, "residual_count": 0},
  "issue_counts": {"<code>": 0},
  "issues": [],
  "open_starts": [], "open_finishes": [],
  "critical_paths": [["<key>"]],
  "activities": [{"key": "...", "state": "not_started | in_progress | complete", "topo_index": 0, "early_start": "...", "remaining_start": "...", "early_finish": "...", "late_start": "...", "late_finish": "...", "total_float_minutes": 0, "free_float_minutes": 0, "critical": false}],
  "relationships": [{"pred": "...", "succ": "...", "considered": true, "slack_minutes": 0, "driving": true}]
}
```

`issue_counts` holds all 15 codes of section 3.10. `activities` by key, `relationships` by `(pred, succ)`
(a not-considered relationship has `slack_minutes = null`, `driving = false`). A `rejected`
run has `project_finish = null` and empty `activities`, `relationships`, `critical_paths`
and open-end lists. `result_sha256 = sha256(b"schedule-cpm-result-v1\n" +
canonical_json_bytes(result))`; result ≤ 32 MiB.

- **Determinism.** The output is a pure function of `(content bytes, engine_version)`: no
  clock, randomness, environment, locale, hash-seed-dependent iteration (no iteration over a
  `set` or `dict` whose order reaches the output without a sort), no `float`. Identical input
  gives byte-identical output on every platform.
- **Engine version.** `my-pa-cpm-v1`; any change that could alter a result for identical
  content bumps it (the S5a parser-version rule). A run is keyed by `(version_id,
  engine_version)`.
- **Operation budget.** The engine counts 1 unit per activity visit, per relationship visit
  and per calendar-function call in every phase; at 4,000,000 units it stops and the run is
  `rejected` with `operation_budget_exceeded`. At the section 2.10 maxima (V = 25,000,
  E = 100,000) the work is ≤ 2,100,000 units — sort 125,000; forward ≤ 4 per relationship
  and 5 per activity (525,000); backward the same (525,000); slack 3 per relationship
  (300,000); total float 1 per activity (25,000); critical count 125,000; paths ≤ 16 ×
  25,000 (400,000) — so the budget is a defence in depth and a wall clock is never
  consulted.

### 3.12 Golden vectors (S6-1 commits each as a fixture with these exact expectations)

Common: calendar `std` = Monday–Friday `[[480, 960]]` (08:00–16:00, 480 minutes per day),
Saturday and Sunday `[]`; default `std`; `D = 2027-01-04T00:00` (a Monday) unless stated;
`lag_calendar = predecessor`, `progress_policy = retained_logic`, threshold 0; "1d" = 480
minutes. Every network was computed by hand and cross-checked with a minute-by-minute
throwaway implementation of sections 3.2–3.8 (not committed).

| # | Network | Activity: ES – EF / LS – LF / TF / FF | Critical paths | Issues / other |
|---|---|---|---|---|
| G01 | A 3d | A 01-04 08:00 – 01-06 16:00 / same / 0 / 0 | [A] | PF 01-06 16:00 |
| G02 | A 1d →FS B 2d →FS D 1d; A →FS C 1d →FS D | A 01-04 08:00 – 01-04 16:00 / same / 0 / 0; B 01-05 08:00 – 01-06 16:00 / same / 0 / 0; C 01-05 08:00 – 01-05 16:00 / 01-06 08:00 – 01-06 16:00 / 480 / 480; D 01-07 08:00 – 01-07 16:00 / same / 0 / 0 | [A, B, D] | slack A→B 0, A→C 0, B→D 0, C→D 480 |
| G03 | A 3d; A →SS+480 B 2d; A →FF+480 C 1d | A 01-04 08:00 – 01-06 16:00 / same / 0 / 0; B 01-05 08:00 – 01-06 16:00 / 01-06 08:00 – 01-07 16:00 / 480 / 480; C 01-07 08:00 – 01-07 16:00 / same / 0 / 0 | [A, C] | PF 01-07 16:00 |
| G04 | A 2d →FS−240 B 1d | A 01-04 08:00 – 01-05 16:00 / same / 0 / 0; B 01-05 12:00 – 01-06 12:00 / same / 0 / 0 | [A, B] | lead crosses no non-working time |
| G05 | A 1d →SF+1440 B 1d | A 01-04 08:00 – 01-04 16:00 / same / 0 / 0; B 01-06 08:00 – 01-06 16:00 / same / 0 / 0 | [A, B] | B's finish bound = `advance(01-04 08:00, 1440)` = 01-06 16:00 |
| G06a | calendar `c6` = Monday–Saturday 08:00–16:00; A 1d on `c6`, `SNET 01-08T00:00`; A →FS+960 B 1d (`std`); `lag_calendar = predecessor` | A 01-08 08:00 – 01-08 16:00 / same / 0 / 0; B 01-12 08:00 – 01-12 16:00 / same / 0 / 0 | [A, B] | lag on `c6`: Sat 01-09 + Mon 01-11 → 01-11 16:00 |
| G06b | G06a with `lag_calendar = successor` | A 01-08 08:00 – 01-08 16:00 / 01-09 08:00 – 01-09 16:00 / 480 / 0; B 01-13 08:00 – 01-13 16:00 / same / 0 / 0 | [B] | lag on `std` → 01-12 16:00; A may finish Saturday on `c6` without delaying B |
| G06c | G06a with `lag_calendar = twenty_four_hour` | A as G06b (TF 480, FF 0); B 01-11 08:00 – 01-11 16:00 / same / 0 / 0 | [B] | 01-08 16:00 + 960 = 01-09 08:00 → B snaps to Monday |
| G07 | `std` with exception `2027-01-05: []`; A 3d | A 01-04 08:00 – 01-07 16:00 / same / 0 / 0 | [A] | the holiday is skipped |
| G08 | A 2d →FS B 2d `FNLT 01-05T16:00`; C 1d `SNET 01-06T12:00` | A 01-04 08:00 – 01-05 16:00 / 12-31 08:00 – 01-01 16:00 / −960 / −960; B 01-06 08:00 – 01-07 16:00 / 01-04 08:00 – 01-05 16:00 / −960 / −960; C 01-06 12:00 – 01-07 12:00 / 01-07 08:00 – 01-07 16:00 / 240 / 240 | [A, B] | `finish_no_later_than_violated` (B); negative-float count 2; PF 01-07 16:00 |
| G09 | A 2d →FS B 1d `MSO 01-05T08:00` | A 01-04 08:00 – 01-05 16:00 / 01-01 08:00 – 01-04 16:00 / −480 / −480; B 01-05 08:00 – 01-05 16:00 / same / 0 / 0 | [A], [B] | `mandatory_constraint_overrides_logic` (B), `relationship_violated` (A→B, slack −480) |
| G10 | A 5d; `must_finish_by 01-07T16:00` | A 01-04 08:00 – 01-08 16:00 / 01-01 08:00 – 01-07 16:00 / −480 / −480 | [A] | `must_finish_by_violated` |
| G11a | `D = 01-06T00:00`; A complete (01-04 08:00 – 01-04 16:00); B in progress (start 01-05 08:00, remaining 2d); C 1d; E in progress (start 01-05 08:00, remaining 1d); A→B, B→C, C→E all FS | A actuals, TF/FF null; B ES 01-05 08:00, RS 01-06 08:00, EF 01-07 16:00 / LS 01-06 08:00 – 01-07 16:00 / 0 / 0; C 01-08 08:00 – 01-08 16:00 / same / 0 / 0; E ES 01-05 08:00, RS 01-11 08:00, EF 01-11 16:00 / 01-11 08:00 – 01-11 16:00 / 0 / 0 | [B, C, E] | `out_of_sequence` (C→E); A→B slack 480 (not in the critical graph: A is complete) |
| G11b | G11a with `progress_override` | B as G11a; C 01-08 08:00 – 01-08 16:00 / same / 0 / 0; E ES 01-05 08:00, RS 01-06 08:00, EF 01-06 16:00 / 01-08 08:00 – 01-08 16:00 / 960 / 960 | [B, C] | `out_of_sequence` (C→E); C→E not considered; PF 01-08 16:00 |
| G12 | M0 milestone →FS A 1d →FS M1 milestone | M0 01-04 00:00 – 01-04 00:00 / 01-04 08:00 – 01-04 08:00 / 0 / 0; A 01-04 08:00 – 01-04 16:00 / same / 0 / 0; M1 01-04 16:00 – 01-04 16:00 / same / 0 / 0 | [M0, A, M1] | a milestone is never snapped; M0's 8 non-working hours are 0 working minutes of float |
| G13 | A 1d → B 2d → E 1d; A → C 2d → E (FS) | A 01-04 08:00 – 16:00, B and C 01-05 08:00 – 01-06 16:00, E 01-07 08:00 – 16:00, all late = early, TF 0 | [A, B, E], [A, C, E] | `critical_path_count` 2 |
| G14 | A→B, B→C, C→A, D→A, C→Z (FS, 1d each) | rejected | — | `cycle_detected`, `cycle = [A, B, C]`, `cycle_length` 3, `residual_count` 4 |
| G15 | A 1d → B 3d → E 1d; A → C 1d → X 1d → E (FS) | A, B, E TF 0; C 01-05 08:00 – 16:00 / 01-06 08:00 – 16:00 / 480 / 0; X 01-06 08:00 – 16:00 / 01-07 08:00 – 16:00 / 480 / 480 | [A, B, E] | free float < total float (shared float) |
| G16 | A with `remaining_minutes = null` | rejected | — | `missing_duration` (A) |

S6-1 also commits a byte-exact `result_sha256` for each vector (computed by the
implementation, then frozen and reviewed; a change needs an engine-version bump) and a
`content_sha256` vector for G02.

### 3.13 Oracle approach (independent of the engine)

1. **Calendar oracle.** A test-only minute-by-minute implementation of section 3.2 over
   seeded random calendars (`random.Random(seed)` in the test, fixed seed list) and windows
   of ≤ 21 days, compared with the engine's `W`, `advance`, `retreat`, `next_work`,
   `prev_end` on every probed instant.
2. **Longest-path oracle.** On `twenty_four_hour` calendars (so the passes reduce to
   difference constraints), seeded random DAGs of 2..7 activities with all 4 types, lags in
   `[−480, 480]`, durations in `[0, 960]`, no constraints, no progress: `ES_j` must equal the
   maximum, over every path from the data-date source, of the summed edge weights (FS:
   `d_i + L`, SS: `L`, FF: `d_i + L − d_j`, SF: `L − d_j`), found by **enumerating every
   path** (not by relaxation); `LF_j` likewise by enumerating paths to the sink; TF and the
   critical set follow. At least 2,000 random DAGs.
3. **Properties** (seeded random networks on `std`): byte-identical output across 2 runs and
   across input permutations of activities, relationships, calendars and exceptions;
   `FF ≤ TF`; `TF = W(C, RS, LS) = W(C, EF, LF)`; with no constraint, progress or
   `must_finish_by` at least 1 activity has `TF = 0` and every critical path starts at an
   open start and ends at an activity whose `EF = PF`; increasing one remaining duration never
   decreases `PF` (no constraint, no progress).

---

## 4. Client-asserted outputs

### 4.1 Document `schedule-scenario-output-v1` (canonical ≤ 1,048,576 bytes)

| Part | Fields and bounds |
|---|---|
| binding | `version_id` (owned), `content_sha256` (must equal the version's), `base_cpm_run_id` (optional; an owned `computed` run of the same version) |
| `kind` | `monte_carlo` \| `criticality` \| `sensitivity` (closed) |
| `run_config` | `tool_name` and `tool_version` (`[A-Za-z0-9._-]{1,64}`), `seed` (`[A-Za-z0-9_-]{1,128}`), `iterations` 1..1,000,000, `sampling = independent` (closed), `engine` ∈ `my-pa-cpm-v1` (the client reimplemented this contract) \| `server_runs` (it called the server per iteration) \| `other`, `distribution_spec_sha256` |
| `finish_percentiles` | ≤ 99 entries `{p: 1..99, finish: instant}`, `p` strictly increasing, `finish` non-decreasing |
| `finish_histogram` | ≤ 200 bins `{start, end, count}`, contiguous (`end_k = start_{k+1}`), `start < end`, counts sum to `iterations` |
| `deterministic_finish` | instant; must equal `base_cpm_run_id`'s `project_finish` when that is given |
| `activity_criticality` | ≤ 25,000 `{activity_key, critical_iterations: 0..iterations}`, keys unique and present in the version |
| `activity_finish_percentiles` | ≤ 2,000 activities × ≤ 9 `{p, finish}` (same monotonic rules) |
| `sensitivity` | ≤ 2,000 `{activity_key, metric ∈ spearman_rank_milli \| duration_cruciality_milli, value: −1,000..1,000}` |

Every number is an integer (fractions in milli-units); an unknown key is
`invalid_request(OUTPUT)`. `payload_sha256 = sha256(b"schedule-scenario-output-v1\n" +
canonical)`.

### 4.2 Server checks (schema, bounds, consistency — nothing else)

Shape and bounds above; binding equalities; percentile and histogram monotonicity and sums;
activity keys exist; `distribution_spec_sha256` equals the server's recomputation (section
4.3), so an output always names the distributions it claims to have sampled; `kind`-specific
presence (`monte_carlo` needs `finish_percentiles` or `finish_histogram`; `criticality`
needs `activity_criticality`; `sensitivity` needs `sensitivity`). The server **never**
re-samples, re-runs or judges plausibility. Stored and served with `authority =
client_asserted`, `authoritative = false`, the writer's provenance and the client id (local
readers only, S3.1 §4.1).

### 4.3 Distribution digest

`distribution_spec_sha256 = sha256(b"schedule-scenario-distributions-v1\n" +
canonical_json_bytes([{"key": k, "distribution": dist} for each activity with a
distribution, by key]))`; stored on every version; the empty list has its own fixed digest.

---

## 5. Scenario lineage (ADR-015 decision 17)

### 5.1 New endpoint families (`RecordFamily`, appended)

| Family | Id kind | Linkable when | Read grant set (`LINEAGE_FAMILY_READS`) |
|---|---|---|---|
| `schedule_publication` | `spub` | effective `complete`/`partial` | `schedule_publications.read`, `schedule_publications.list` |
| `schedule_activity` | `sact` | visible under S5b-1 U-03 | `schedule_activities.history`, `schedule_activities.list` |
| `scenario` | `sscn` | exists | `schedule_scenarios.read`, `schedule_scenarios.list` |
| `scenario_version` | `sscv` | exists | `schedule_scenario_versions.read` |
| `scenario_output` | `ssco` | exists | `schedule_scenario_outputs.read`, `schedule_scenario_outputs.list` |

The 5 families exist for lineage only while the plane is effective (section 6.2) **and**
`MY_PA_LINEAGE_ENABLED` is on; otherwise naming one is answered exactly as an absent record
(`not_found`), and lineage reads withhold such endpoints as they withhold a family the caller
may not read (S3 §6.4), with no hidden count.

### 5.2 Relations (closed; the minimal set the use cases need)

| Relation | Kind | From | To | Evidence rule | Use case |
|---|---|---|---|---|---|
| `concerns` (new) | semantic | `scenario`, `scenario_version`, `scenario_output` | `situation`, `constraint`, `task`, `commitment`, `schedule_activity` | none | "this what-if / this simulation is about Issue X, Constraint Y, activity Z" |
| `delays` (new) | semantic | `constraint`, `situation` | `schedule_activity` | ≥ 1 exact-version `corroborates` anchor (the `blocks` rule) | "this constraint / Issue delays this activity" — a causal claim, so it needs cited evidence |
| `mitigates` (new) | semantic | `task`, `commitment`, `scenario_version` | `constraint`, `situation` | ≥ 1 exact-version `corroborates` anchor | "this work / this recovery version mitigates the constraint" |
| `discusses` (widened) | semantic | `meeting`, `meeting_note_version` (unchanged) | + `schedule_publication`, `schedule_activity`, `scenario`, `scenario_output` | unchanged (a `discussion` note anchor) | a meeting reviewed an update, an activity, a scenario or a simulation |
| `originated_from` (widened) | semantic | + `scenario_version` | `meeting_note_version`, `capture_version` (unchanged) | unchanged (exact `origin` anchor on the `to` version) | the version's change set came from a decision in that note or capture |

`issue_member`, `blocks`, `related_context`, `delegated_from`, `escalated_from` and
`created_to_resolve` are **not** widened (the close gate's mandatory-member semantics are
untouched; S6-D12). `concerns`, `delays`, `mitigates` are contestable (`CONTESTABLE_RELATIONS`
= every semantic relation) and not composite-only. Directions are as tabled; none is
symmetric.

**Structural edges are native, never ledger rows** (ADR-015 decision 2). New
`NativeVirtualEdge` members, read-only, derived from the plane's own columns:
`scenario_version_of` (version → Scenario), `scenario_version_parent` (version → its
parent), `scenario_based_on_publication` (Scenario → origin publication),
`scenario_forked_from_version` (Scenario → origin version) and `scenario_output_of` (output
→ version). No CPM-run edge exists (a run is not an endpoint family; it is reached from its
version). A client cannot assert `derived_from`, `based_on` or `used_in` — those facts are
columns.

### 5.3 Validators (S1 style, in the S1 order)

Strict `IdKind` per family → Principal ownership (another Principal's row is `not_found`,
byte-identical to absent) → family linkability (table 5.1) → relation matrix → evidence rule
→ lock: the 5 new families' rows are append-only, so the writer takes `FOR SHARE` on each
named row in the S1 `(family token, identifier)` order (decision 9; the family tokens sort as
strings, so `scenario…` and `schedule_…` interleave deterministically with the existing
tokens). Provenance (`client_identified` / `user_confirmed`), `user_directed`, the client
budgets, idempotency, replay and the "clients never remove accepted lineage" rule are S3.1's,
unchanged. The server never creates a lineage fact from similarity, shared names, shared
dates or shared WBS (no similarity → causation); every link is a writer's explicit assertion.

### 5.4 Schema (S6-2) and the ADR process

S6-2's revision widens, in one change with the Python vocabulary: the `record_links`
family CHECKs, `from_id_is_an_opaque_identifier`/`to_id_…` (family → id kind),
`a_record_link_relation_type_is_known`, `a_record_link_pair_is_admitted` (regenerated from
`RELATION_MATRIX`), `RECORD_FAMILY_ID_KINDS`, `LINEAGE_FAMILY_READS` and the read-side
endpoint resolvers. `LINEAGE_READ_GENERATION` is bumped 1 → 2 (traversal now reaches new
families; every old lineage cursor is refused once). ADR-015 decision 17 is the amendment
decision 6 requires; the migration and tests are S6-2's.

---

## 6. Capabilities (S6-3)

### 6.1 Names, kinds, purposes

Section 11.4 adds 4 more names (designations, currency, match decisions) and supersedes the
counts below. 2 new purposes, appended: `schedule_scenario_authoring` (joins `_WRITE_PURPOSES`) and
`schedule_scenario_read`. All 14 names are scopeless (`_SCOPELESS`), not operator-only, and
classified on every closed surface S5b-2 §3.12 lists.

| Capability | Kind | Purpose | Additive | Summary (first docstring line) |
|---|---|---|---|---|
| `schedule_scenarios.create` | write | `schedule_scenario_authoring` | yes | Create a Schedule Scenario whose version 1 is a snapshot of one complete or partial publication, or a copy of an existing scenario version. |
| `schedule_scenario_versions.create` | write | same | yes | Append one immutable version to a Scenario by applying a bounded change set to its current head version. |
| `schedule_cpm_runs.create` | write | same | yes | Run the deterministic server CPM engine over one scenario version and store its result (replays the existing run for the same version and engine). |
| `schedule_scenario_outputs.record` | write | same | yes | Record a client-computed (client-asserted) analysis output such as Monte Carlo percentiles, bound to one scenario version. |
| `schedule_scenarios.list` | read | `schedule_scenario_read` | — | List a Project's (or one Series') Schedule Scenarios, newest first. |
| `schedule_scenarios.read` | read | same | — | Read one Scenario and a page of its versions, newest first. |
| `schedule_scenario_versions.read` | read | same | — | Read one scenario version's metadata, settings, calendars, counts and digests. |
| `schedule_scenario_versions.activities` | read | same | — | List one scenario version's activities in key order. |
| `schedule_scenario_versions.relationships` | read | same | — | List one scenario version's relationships in predecessor, successor order. |
| `schedule_scenario_versions.changes` | read | same | — | List the change-set ops that produced one scenario version, in applied order. |
| `schedule_cpm_runs.read` | read | same | — | Read one server CPM run: status, summary, issues, open ends and critical paths. |
| `schedule_cpm_runs.activities` | read | same | — | List one CPM run's per-activity dates, floats and criticality in key order. |
| `schedule_scenario_outputs.list` | read | same | — | List one scenario version's client-asserted outputs, newest first. |
| `schedule_scenario_outputs.read` | read | same | — | Read one client-asserted output in full. |

Counts: `Capability` 240 → 254, `Purpose` 62 → 64; the audit vocabulary CHECK restated by
S6-3's revision 251 → 265 capability literals (254 + 11 native) and 62 → 64 purposes.
`_FEATURE_BY_FAMILY`: `schedule_scenarios`, `schedule_scenario_versions`,
`schedule_cpm_runs`, `schedule_scenario_outputs` → `schedule`. `facade_kind`: 4 `write`, 10
`read`.

### 6.2 Switch

`Settings.schedule_scenarios_enabled: bool = False`, env `MY_PA_SCHEDULE_SCENARIOS_ENABLED`.
The plane is **effective** iff `schedule_enabled and schedule_scenarios_enabled` and the
gateway composed the plane factory (`data_engine is None`; a restricted MCP-profile
composition never composes it). The scenario switch alone is refused by nothing and does
nothing. Gate points: `ApplicationService.available_capabilities` subtracts the 14 when not
effective (absent from `capabilities.get`, readiness, MCP tool list, remote profile, façade,
ChatLLM composition); each handler first calls `_schedule_scenario_plane()` → `unsupported`
before any read, write or replay; the lineage family admission of section 5.1; the ChatLLM
prerequisite; `apps/cli/remote_mcp.py` `_planes_from_settings`. Off → on → off changes no row.

### 6.3 Inputs (strict; unknown key → `invalid_request`)

| Capability | Fields |
|---|---|
| `schedule_scenarios.create` | exactly one of `from_publication_id` (`spub`) / `from_version_id` (`sscv`); `name`; `description`; `label`; with a publication: `minutes_per_source_unit`, `calendars` (1..32), `default_calendar`, `data_date_time`; `idempotency_key` (`^[A-Za-z0-9_-]{8,128}$`) |
| `schedule_scenario_versions.create` | `scenario_id`; `expected_head_version_no` (CAS: must equal the current head, else `conflict(EXPECTED_VERSION)`); `label`; `note`; `change_set`; `idempotency_key` |
| `schedule_cpm_runs.create` | `version_id`; `idempotency_key`. The natural key `(version_id, my-pa-cpm-v1)` also dedups: an existing run is returned with `created: false` and nothing is computed |
| `schedule_scenario_outputs.record` | section 4.1 document; `idempotency_key` |
| reads | the id; `page_size` 1..100 (default 25); `cursor` ≤ 512; `schedule_scenarios.list`: `project_id`, optional `series_id`; `schedule_cpm_runs.activities`: optional `critical_only` |

Idempotency: `(principal_id, capability, idempotency_key)` in one plane request ledger
(S6-2), request digest `sha256(b"schedule-scenario-request-v1\n" + canonical({principal_id,
capability, request without key}))`; same key and digest → the recorded outcome with
`replayed: true`; same key, other digest → `conflict(IDEMPOTENCY_KEY)`. The remote boundary
stamps the key (T6-16).

### 6.4 Outputs, cursors, disclosure

Every write answers ids, `version_no`, digests, `created`, `replayed` and (create/versions)
the `snapshot_report` / `application_report`. Reads page from the stored immutable documents
in their canonical order; `ScheduleCursorOrder` gains `scenarios_created_desc_id_desc`,
`versions_no_desc`, `scenario_content_offset` (activities, relationships, changes, CPM
activities: a bare offset bound to the version or run id, as the delta's) and
`outputs_created_desc_id_desc`. Disclosure: `scope` = the source and enrollment of the
Scenario's root publication; `source_references` = that publication's source version;
`trust = MODEL_PROPOSED` with basis `("schedule_scenario", "client_authored")`, plus
`("schedule_cpm", "my-pa-cpm-v1", "server_computed")` for runs and
`("schedule_scenario_output", "client_asserted")` for outputs; `classification
PRIVATE_LOCAL`. Every payload object carries the labels `data_class: "schedule_scenario"`,
`authority` ∈ `client_authored` \| `server_computed` \| `client_asserted`,
`authoritative: false`, `reportable: false`. Hidden = absent: another Principal's id, an id
while the plane is off, and an absent id answer identically.

### 6.5 Provenance of plane rows

Every Scenario, version, run and output row stores `authority_class`, `decision_channel` and
`asserting_client_id` (remote only) derived exactly as S3.1 §6.1 derives lineage provenance,
and `user_directed` as an unverified claim. No request field carries a Principal, actor,
channel or time. There is no `confirm`: scenario data is never accepted-grade whoever wrote
it.

### 6.6 ChatLLM `chatllm-data-v12`

All 14 names `CHATLLM_DATA_CONDITIONAL` under new prerequisite `SCHEDULE_SCENARIOS`, which
holds iff `planes.schedule and planes.schedule_scenarios` (new field
`ChatLLMCompositionPlanes.schedule_scenarios: bool = False`). Expected (re-measured by the
implementer; a difference is reported, never forced): policy size 240 → 254;
`DATA_CONDITIONAL` 137 → 151; full and default targets unchanged with the switch off (164,
98); full + schedule + scenarios 184; full + lineage + program + schedule + scenarios 218;
default + all 4 switches 150; compositions 512 → 1,024. The import stays
`CONTROL_PLANE_EXCLUDED`.

### 6.7 Remote, façade, grants

Writes are `write` kind (purpose in `_WRITE_PURPOSES`): published only with remote writes
enabled and a grant; reads `read` kind. The 4 writes join `_IDEMPOTENT_REMOTE_CAPABILITIES`
and `is_remote_idempotent` (MCP `idempotentHint` true); `schedule_scenarios.create` with an
identical payload therefore replays rather than creating a second Scenario (S6-D14).
`_SERVER_REPLAY_REMOTE_CAPABILITIES` and `REMOTE_OWNED_PAYLOAD_FIELDS` are unchanged. Every
remote read and write re-checks its own grant (`require_read_grant` precedent) after the
switch gate. No MCP database profile ceiling or opt-in changes.

**Façade end to end** (S6-3, S3.1 Part D shape, default remote path): `my_pa.describe` lists
exactly the eligible plane names with summary, kind, feature `schedule` and `idempotent`;
`my_pa.write` creates a Scenario from a synthetic publication, appends a version, runs CPM
and records an output; `my_pa.read` reads each back; a write via `my_pa.read` (or the
reverse) is `invalid_request`; a name not admitted (no grant, switch off, plane not
effective) is absent from describe and `unsupported` at call; the interaction log records
the canonical capability; lineage `records.associations.assert` with `concerns` from the
version to an Issue succeeds and is `client_identified`. ChatLLM path: the planner desires
the 14 exactly when both planes are on.

**Operator grant table and pre-deploy gates** (written by S6-3 into
`ops/runbooks/cpm-workbench.md`, never performed by an agent): apply S6-2 and S6-3
revisions; set `MY_PA_SCHEDULE_ENABLED`, `MY_PA_SCHEDULE_SCENARIOS_ENABLED` (and
`MY_PA_LINEAGE_ENABLED` for lineage); ChatLLM `profile-apply` to `chatllm-data-v12`; grant
the 14 names to the ChatGPT connector's client; run the read-only pre-deploy checks S6-2
adds (tables, triggers, CHECKs, no grant to profile roles).

---

## 7. Reporting and disclosure (OD-08)

| Rule | Enforcement point (guarded by S6-3) |
|---|---|
| Scenario data never enters a Program total or certified report | `ProgramFamily` gains no member; `METRIC_CATALOGUE` gains no metric; no module under `src/my_pa/application/program_*.py`, `src/my_pa/domain/program/` or `src/my_pa/contracts/v1/programs.py` imports a plane module or table (AST guard) |
| The report-manifest lineage section never counts or seeds a schedule family | `src/my_pa/domain/intelligence/source_manifest.py` `_block_seeds`, `lineage_server_counts` and `lineage_section` admit only the 7 pre-S6 families (a pinned frozenset, not `RecordFamily`); a guard fails if a new family reaches them (S6-U04 if the operator wants scenario lineage in reports later) |
| Program critical path | **UNPROVEN**: no Program-level schedule read exists; a scenario CPM is per version and labelled non-authoritative; no capability aggregates runs across Projects |
| Labels everywhere | section 6.4; the TOOLS summaries say "client-asserted" / "scenario" |
| Baseline vs scenario | publications stay `SOURCE_BOUND_DERIVED` and immutable; nothing writes an S5 table (AST guard over plane persistence: no insert/update/delete on a `schedule_` S5 table) |
| Lineage close gate | a `client_identified` `concerns`/`delays`/`mitigates` link to an Issue is in its review scope (S3.1 §4.6), holding the close gate until confirmed — unchanged behaviour |

---

## 8. Security and abuse

### 8.1 Complexity and DoS

| Step | Cost |
|---|---|
| change-set application | `O(ops × log V)` plus one `O(V + E)` re-validation; ≤ 5,000 ops |
| topological sort, cycle report | `O((V + E) log V)` (heap), `O(V + E)` |
| each pass | `O(V + E)` calendar calls, each `O(log days)`; ≤ 4 calls per element |
| slack, critical count | `O(E)`, `O(V + E)` |
| path enumeration | ≤ 16 × V steps (every descent emits); no exponential blow-up; the count saturates at 1,000,000 |
| calendar tables | ≤ 32 × 36,525 day entries |
| operation budget | 4,000,000 units, pure counting (section 3.11) |

Degenerate inputs: cycles (rejected with a bounded report), self-loops and duplicates
(refused at the op), dangling references (impossible in a stored version), all-holiday
calendars (refused: ≥ 1 working minute per week; exceptions bounded, so `advance` always
terminates inside the horizon or rejects), extreme lags (bounded ±2 years), long chains
(bounded by V). Target: a maximal network (25,000 activities, 100,000 relationships, 32
calendars) computes in ≤ 10 s on the CI host, measured by S6-1 (`slow`) and S6-3
(`database`+`slow`); a miss is reported, never hidden, and moves the compute to a worker
plane by a contract revision (S6-U06).

### 8.2 Isolation, integrity

Principal partition on every row and principal-composite foreign keys (S6-2); hidden =
absent; append-only `BEFORE UPDATE OR DELETE` and `BEFORE TRUNCATE` refusals on every plane
table (S5b-1 F-guard precedent), the request ledger's single `reserved → completed`
transition; CAS on version append; idempotent writes; content and result digests recomputed
from the stored bytes on every read (a mismatch is `internal_error`, never served).

### 8.3 Rate and volume bounds (non-attested writers; the human channel is not limited)

| Bound | Value |
|---|---|
| plane writes per writer bucket | 120 per rolling hour, 1,000 per rolling day (the 4 writes together; replays and refusals consume nothing) |
| plane writes per Principal (client channels) | 2,000 per rolling day |
| CPM compute per Principal | 2,500,000 activity-units per rolling hour (a run costs its activity count; a natural-key replay costs 0) |
| storage | section 2.10; outputs ≤ 100 per version |

Reaching one answers `rate_limited` with a plane detail and writes nothing (S3.1 §4.8
precedent).

### 8.4 AI boundary

A client (human or model) authors logic and asserts outputs; the server computes only CPM.
Nothing a client writes becomes source-bound, accepted-grade or reportable; no
model-confidence field exists; the server never infers a relationship, duration, calendar or
lineage link.

---

## 9. Delivery plan and work split

Serial: S6-1 → S6-2 → S6-3, one worker at a time, each on this branch.

### 9.1 S6-1 (worker I8): pure domain and engine — no migration, no IO

Owned paths (new): `src/my_pa/domain/schedule/scenario/__init__.py` (re-exports, no
logic), `src/my_pa/domain/schedule/scenario/model.py` (enums, bounds, content records with
`__post_init__` invariants, distributions, constraints, progress), `…/calendar.py`
(calendar records and the section 3.2 functions), `…/canonical.py` (content, change-set,
result, output and distribution documents and digests; decoders for stored documents),
`…/changeset.py` (op grammar and application, `ChangeSetRefusal(op_index, op_error)`),
`…/snapshot.py` (section 2.5 over `ScheduleActivityRowView` values), `…/cpm.py`
(`ENGINE_VERSION`, `run_cpm(content) -> CpmResult`), `…/outputs.py` (section 4 validation).
Tests (new): `tests/unit/test_scenario_model.py`, `tests/unit/test_scenario_calendar.py`,
`tests/unit/test_scenario_changeset.py`, `tests/unit/test_scenario_snapshot.py`,
`tests/unit/test_scenario_cpm_goldens.py`, `tests/unit/test_scenario_cpm_oracle.py`,
`tests/unit/test_scenario_cpm_properties.py`, `tests/unit/test_scenario_outputs.py`,
`tests/architecture/test_scenario_engine_scope.py`; fixtures under
`tests/fixtures/schedule_scenario/`. Shard weights for heavy modules (`python -m
tests.ci_shard weigh`), partition proof green.

| Public symbol (minimum) | Module |
|---|---|
| `ScenarioContent`, `ScenarioActivity`, `ScenarioRelationship`, `ScenarioCalendar`, `ScenarioSettings`, `ActivityConstraint`, `ActivityProgress`, `DurationDistribution`, `RelationshipType`, `ConstraintType`, `ActivityKind`, `VersionLabel`, `LagCalendar`, `ProgressPolicy` | `model.py` |
| `working`, `working_minutes`, `advance`, `retreat`, `next_work`, `prev_end`, `shift` | `calendar.py` |
| `content_document`, `content_sha256`, `change_set_sha256`, `result_document`, `result_sha256`, `distribution_spec_sha256`, `output_payload_sha256`, `scenario_request_digest` | `canonical.py` |
| `ChangeOp` (closed op union), `apply_change_set`, `ChangeSetRefusal`, `ApplicationReport` | `changeset.py` |
| `snapshot_from_publication`, `SnapshotReport` | `snapshot.py` |
| `ENGINE_VERSION = "my-pa-cpm-v1"`, `run_cpm`, `CpmResult`, `CpmIssueCode`, `CpmActivityResult` | `cpm.py` |
| `validate_output`, `OutputKind`, `OutputRefusal` | `outputs.py` |

The scope guard asserts: stdlib + `my_pa.domain.schedule` + `my_pa.domain.common.identifiers`
only (inherited); no import of `random`, `time`, `secrets`, `uuid` or `os`; no call of
`now`, `today` or `utcnow`; no `float(` call, no float literal and no `/` operator (`ast.Div`;
integer `//` only) anywhere in the package; no `print`/`open`/logging (inherited).

| Prove-red (break exactly one thing; the named test fails for that reason) | Test |
|---|---|
| P01 drop `snap` on the forward start | `test_golden_network_matches[G02]` |
| P02 lag calendar always predecessor | `test_golden_network_matches[G06b]` |
| P03 FF bound without `retreat` | `test_golden_network_matches[G03]` |
| P04 TF as absolute minutes instead of `W` | `test_golden_network_matches[G02]` (C: 1,440 ≠ 480) |
| P05 Kahn pops insertion order, not min key | `test_topological_order_is_key_ordered` |
| P06 cycle not rotated to its smallest key | `test_golden_network_matches[G14]` |
| P07 path enumeration uncapped | `test_critical_path_enumeration_is_bounded` |
| P08 a float in the engine | `test_scenario_package_has_no_float_clock_or_randomness` |
| P09 content digest without its domain prefix | `test_content_sha256_vector` |
| P10 ops sorted instead of applied in request order | `test_change_set_applies_in_request_order` |
| P11 snapshot rounds half-up | `test_snapshot_quantizes_half_even` |
| P12 retained logic ignored for in-progress work | `test_golden_network_matches[G11a]` |
| P13 SNLT/FNLT violation not reported | `test_golden_network_matches[G08]` |
| P14 MSO not overriding logic | `test_golden_network_matches[G09]` |
| P15 `must_finish_by` ignored | `test_golden_network_matches[G10]` |
| P16 operation budget not enforced | `test_operation_budget_rejects_deterministically` |
| P17 horizon check removed | `test_horizon_exceeded_is_rejected` |
| P18 distribution digest check removed | `test_output_distribution_digest_must_match` |
| P19 histogram sum check removed | `test_output_histogram_counts_sum_to_iterations` |
| P20 `activity.add` admits an `sact_` key | `test_added_activity_cannot_take_a_source_key` |
| P21 milestone snapped | `test_golden_network_matches[G12]` |
| P22 slack on predecessor calendar | `test_golden_network_matches[G06b]` (FF of A) |

Acceptance (S6-1): every golden vector and frozen digest; oracle ≥ 2,000 DAGs and the calendar
oracle; properties; prove-red table executed; FAST, ruff, ruff format, mypy strict (default
and `--platform linux`, repo venv and floor-pinned venv), shard verify and doc guards green;
the maximal-network timing measured and reported.

### 9.2 S6-2: schema, migration, persistence, unit of work

One additive revision on `621ef6786c64` (sole head after): 4 `IdKind`s; tables
`knowledge.schedule_scenarios`, `knowledge.schedule_scenario_versions` (content and change
set as zlib-compressed canonical bytes plus `*_sha256` and `*_size_bytes`; UNIQUE
`(principal_id, scenario_id, version_no)`; parent and origin principal-composite FKs
`RESTRICT`), `knowledge.schedule_cpm_runs` (UNIQUE `(principal_id, version_id,
engine_version)`; result compressed, summary columns), `knowledge.schedule_scenario_outputs`,
`knowledge.schedule_scenario_write_requests` (idempotency ledger); every CHECK of sections
2–4 that is a column property (bounds, closed vocabularies, digest shape, label, version
numbering); append-only and TRUNCATE-refusal triggers; downgrade refused once any plane row
or plane audit name exists. The lineage widening of section 5.4 in the same revision. A
`ScenarioUnitOfWork` / `SqlScenarioRepository` (own factory; principal-scoped statements;
bounded zlib decompression that refuses a size mismatch). Acceptance: database tier by
marker (append-only, TRUNCATE, CAS race, idempotency, cross-Principal `not_found`,
digest-recompute, lineage CHECK widening, downgrade refusal), migration tiers, schema parity,
pre-deploy read-only checks. No capability.

### 9.3 S6-3: capabilities, policy, ChatLLM, remote, lineage endpoints, guidance

Second additive revision (audit capability/purpose vocabulary 251 → 265 / 62 → 64); the 14
commands, handlers, `_BUILDERS`, `_HANDLERS`, purposes, `_SCOPELESS`, `_requested_scope`,
`_WRITE_PURPOSES`, `_IDEMPOTENT_REMOTE_CAPABILITIES`, `is_remote_idempotent`,
`_FEATURE_BY_FAMILY`, ChatLLM v12, switch, cursor orders, `SafeDetail` members
(`SCENARIO_ID`, `SCENARIO_VERSION_ID`, `CPM_RUN_ID`, `OUTPUT_ID`, `EXPECTED_VERSION`,
`CHANGE_SET`, `CONTENT_SIZE`, `OUTPUT`, `MINUTES_PER_SOURCE_UNIT`, `CALENDAR`,
`ACTIVITY_KEY`, `LABEL`, and 1 `change_set_<op_error>` member per section 2.9 `op_error`
code), lineage endpoint validators and resolvers, OD-08 guards, rate
budgets, regenerated web fixture, count pins in lockstep, runbook and client guidance.
Acceptance: switch-off withholding parametrized over 14; façade e2e (FAST catalog test +
database façade test); ChatLLM planner targets; remote grant re-check; lineage `concerns`,
`delays`, `mitigates`, widened `discusses`/`originated_from` admitted and every other pair
refused; OD-08 guards; rate budgets; prove-red of every new guard.

### 9.4 Crosswalk (directive → section → first test)

| Directive requirement | Section | Test (slice) |
|---|---|---|
| create entirely new versions of schedule data | 2.2, 2.5, 2.9 | `test_snapshot_copies_exactly_the_accepted_run` (S6-1), `test_version_append_is_cas_guarded` (S6-2) |
| what-if scenarios / updating schedules | 2.9, 2.8 | `test_change_set_applies_in_request_order`, `test_golden_network_matches[G11a]` (S6-1) |
| Monte Carlo sims (client-side) | 4 | `test_output_histogram_counts_sum_to_iterations` (S6-1), `test_output_record_is_client_asserted` (S6-3) |
| server CPM | 3 | `test_golden_network_matches` (S6-1), `test_cpm_run_replays_by_natural_key` (S6-2/3) |
| lineage records for schedule data | 5 | `test_scenario_lineage_relations_are_admitted` (S6-3) |
| connected clients through catalog and façade | 6.6, 6.7 | `test_scenario_facade_end_to_end` (S6-3) |
| OD-08 kept | 7 | `test_scenario_data_reaches_no_program_surface` (S6-3) |

---

## 10. Deviations, residuals, open operator decisions, questions for R8

### 10.1 Decisions (S6-D)

| ID | Decision | Why |
|---|---|---|
| S6-D01 | Scenario lineage reuses the ADR-015 ledger (new families and relations) rather than a schedule-only link table | one owner of semantic links; S3.1 provenance, budgets and disclosure apply unchanged |
| S6-D02 | Structural facts (parent, origin, output-of) are native columns exposed as native virtual edges, never client-assertable relations | ADR-015 decision 2 |
| S6-D03 | Version 1 is the exact snapshot or exact copy; edits begin at version 2; no blank Scenario | provenance of the baseline stays provable by digest; operator decision 1 |
| S6-D04 | A Scenario is a linear chain; branching is a new Scenario | CAS on one head; no merge semantics |
| S6-D05 | ≤ 1 relationship per ordered pair | P6 parity; unambiguous slack |
| S6-D06 | Integer minutes, naive wall clock, horizon 2000–2099 | exactness; matches the S5a date window |
| S6-D07 | No time zones or DST | schedules are wall-clock; a zone-aware model is a later engine version |
| S6-D08 | Open-end bound applies whenever the step-2 bound set is empty | keeps `min` defined for an in-progress activity whose only successors are SS/SF |
| S6-D09 | CPM runs are persisted (immutable, keyed by version and engine) and computed synchronously inside the request | cheap re-reads and stable lineage targets; budgeted; S6-U06 if too slow |
| S6-D10 | Cycles are storable; the run reports them | a client may edit across several versions |
| S6-D11 | Disclosure trust `MODEL_PROPOSED` for all plane answers (no new `TrustLevel`) | the lowest existing level; never upgraded by who wrote it |
| S6-D12 | `issue_member` not widened | the close gate's mandatory-member semantics stay as reviewed |
| S6-D13 | Manifest lineage section pinned to the 7 pre-S6 families | OD-08 conservatism |
| S6-D14 | All 4 writes are remote-stamped idempotent; an identical `schedule_scenarios.create` replays | the remote key is a payload digest; a client wanting 2 identical Scenarios changes the name |
| S6-D15 | Constraints apply only to not-started activities | simple, P6-like; reported when ignored |

### 10.2 Residuals (S6-U)

| ID | Residual | Owner |
|---|---|---|
| S6-U01 | Scenario name/description immutable; no archive | later slice |
| S6-U02 | A removed baseline activity cannot be restored in the same Scenario | fork an earlier version |
| S6-U03 | No correlation, risk events, probabilistic branching, resources | later engine/output version |
| S6-U04 | Reports cannot cite scenario lineage in a manifest | operator decision, later slice |
| S6-U05 | Lineage grain is the version, not the scenario activity | later family if needed |
| S6-U06 | Synchronous CPM timing at maxima unmeasured until S6-1 | S6-1 measures; contract revision if missed |
| S6-U07 | The engine's "retained logic" is this contract's definition (section 3.5/3.6), not a claim of P6 equivalence | stated in guidance |
| S6-U08 | Content is stored per version in full (no delta storage) | bounded by section 2.10 |
| S6-U09 | A refused change set names the `op_error` class but not the op's index (closed-token error contract) | an error-contract extension, later slice |

### 10.3 Open operator (product) decisions, each with the default this contract proceeds on

| ID | Decision | Default chosen |
|---|---|---|
| S6-O01 | Monte Carlo location | client-side only (operator decision 2); no server sampling |
| S6-O02 | Source duration unit | client must declare `minutes_per_source_unit`; no default |
| S6-O03 | Lag calendar | `predecessor` (settable per version) |
| S6-O04 | Out-of-sequence policy | `retained_logic` (settable per version) |
| S6-O05 | Critical definition | `TF ≤ 0` (threshold settable 0..525,600 minutes) |
| S6-O06 | Open-end late finish | project finish, or `must_finish_by` when set |
| S6-O07 | Longest-path critical definition | not offered |
| S6-O08 | Server evaluation with client duration overrides (per-iteration server CPM) | not built; a client may call `schedule_cpm_runs.create` on `simulation_input` versions within the rate bounds |
| S6-O09 | Rate and storage bounds (section 8.3, 2.10) | as tabled |
| S6-O10 | Exposure | ChatLLM `DATA_CONDITIONAL` (writes included) and remote grants by the operator; switches default off |

### 10.4 Items the contract asks review R8 to rule on

- R-1: whether ADR-016's Supersession clause ("a superseding ADR is required … to persist
  deltas, to link schedule evidence to another domain") is satisfied by the in-place
  2026-11-03 amendment (this contract's choice, matching ADR-015 decisions 15–16) or needs a
  separate ADR-017.
- R-2: S6-D08 (the empty-bound-set rule) and S6-D15.
- R-3: S6-D11 (`MODEL_PROPOSED` for operator-authored scenario data).
- R-4: the writes as ChatLLM `DATA_CONDITIONAL` (S6-O10), mirroring P1's open lineage writes.
- R-5: synchronous CPM (S6-D09) versus a worker plane.
- R-6: the auto-match flow of section 11.2 (intake Series and a second admission) and
  S6-O12 (automatic attach without confirmation).
- R-7: currency and designation semantics of section 11.3 (S6-D17, S6-D18, S6-O13, S6-O14).

---

## 11. Addendum (operator, 2026-11-03): series auto-matching and publication currency and authority

Operator additions relayed by the Manager on 2026-11-03: "add auto-matching to the S6
contract", and "if two schedule files with the same Data Date are uploaded, are both
retained, and which is the latest/authoritative version?". Both are in scope of S6 and of
review R8; sections 0–10 are unchanged except where this section says so.

### 11.1 Repository truth (re-measured at the basis)

| # | Fact at `83e79817` | Consequence |
|---|---|---|
| T6-19 | `ScheduleImportRequest` needs exactly one of `series_id` / `series_name`; `admit_publication` resolves or creates the Series **in the admission transaction**, before any byte is fetched (S5b-1 `admit_publication` steps 4 and 7); `schedule_publications.series_id` is not null | the Series is final at admission; matching needs parsed Activity IDs, which exist only after the worker parses — so matching cannot bind the admitted publication itself |
| T6-20 | Stable Activities are created per Series during the worker's canonicalization; rows, runs and activities are immutable (F-guards) | a publication cannot be moved between Series after parsing |
| T6-21 | UNIQUE `(principal_id, series_id, source_version_id)` behaviour: the same source version re-admitted to the same Series replays or conflicts (S5b-1 step 5); across Series it is admissible | a matched source version can be admitted a second time into the matched Series |
| T6-22 | One job per publication (`a_schedule_publication_has_one_job`); a job is enqueued only on insert | a second admission gets its own job; nothing reuses a job |
| T6-23 | Both same-Data-Date publications are retained (immutable; a different source version is a new publication); there is no stored latest/current pointer; reads order by `(data_date, admitted_at, publication_id)`; `schedule_series.list`'s `latest_update` = max of that key among role `update`, status `complete`/`partial`; the only explicit relation is `supersedes_publication_id` (at most 1 successor per predecessor; supersession never hides the predecessor) | currency is derived, never stored; authority is a separate, append-only, attributed claim |
| T6-24 | `schedule_series` is append-only (F1/F2); the Series name refusal set is `normalize_series_name` | no column is added to S5 tables; an intake marker lives in a new table |

### 11.2 A — auto-matching (deterministic, conservative, evidence-recorded)

**Flow (S6-D16).**

1. `schedule_publications.import` gains an **additive** request form: exactly one of
   `series_id`, `series_name`, or `series_auto: true` (with optional `series_name_if_new`).
   The 2 existing forms are byte-for-byte unchanged, including their request digest
   (`cpm-schedule-import-v1`); the auto form digests under
   `b"cpm-schedule-import-v2\n"` with the added keys `series_auto` and
   `series_name_if_new_key`. An explicit `series_id` or `series_name` **always** wins: the
   matcher is never consulted for it.
2. An auto import is admitted, in the same S5b-1 transaction, into the Project's **intake
   Series** — an ordinary `schedule_series` row named `Schedule intake (unmatched)`, created
   on first use and marked by a row in the new append-only table
   `knowledge.schedule_intake_series (principal_id, project_id, series_id)`, UNIQUE per
   `(principal_id, project_id)`. A caller `series_name` whose key equals the intake name's
   key is refused `invalid_request(SERIES_NAME)` (additive refusal). The publication is
   parsed by its one job exactly like any other.
3. When the worker finalizes an intake publication as `complete` or `partial`, the same
   finalization transaction computes the match (11.2.1) over the Project's non-intake
   Series and writes one immutable **match decision** (`ssmd_`, table
   `knowledge.schedule_series_match_decisions`): publication id, outcome, `threshold_version`
   `series-match-v1`, incoming ID count, every candidate considered with its score, current
   publication id, Data Date and `data_date_coherent`, title equality (evidence only), and
   the resulting publication id if any. A `review_required` or `failed` intake publication
   gets a decision with outcome `not_eligible` and no candidates.
4. Outcome `matched`: in that transaction, a second publication of the **same source
   version** is admitted into the matched Series (new `spub_`, its own job, the original
   role, baseline kind and expected Data Date, `admission_basis = auto_match`, the decision
   id; idempotency key derived as `sha256("series-match-v1\n" + decision_id)` truncated to 64
   hex). It is parsed again by its own job (deterministic: same parse result digest).
   Outcome `no_match` with `series_name_if_new`: the same, into a Series created with that
   name — unless a non-intake Series already has that name key, which makes the outcome
   `ambiguous` (`name_conflict`) and creates nothing. `no_match` without a name: outcome
   `needs_series`. `ambiguous`: nothing is admitted.
5. The intake publication is never deleted, hidden or moved; it stays readable, labelled
   `series_kind: intake`, can never be current (11.3), and cannot seed a Scenario
   (`schedule_scenarios.create` refuses it with `conflict(STATUS)`). The operator resolves
   `ambiguous`/`needs_series` by an explicit import (`series_id` or `series_name`) of the
   same source version — an ordinary admission.

Provenance: the auto admission inherits the attested local-operator authority of the import
that caused it (import is operator-only, ADR-016 decision 4) and records
`admission_basis = auto_match` plus the decision id; no client can trigger it.

#### 11.2.1 Matcher `series-match-v1` (pure; S6-1)

Inputs: the incoming accepted run's set `A` of exact published Activity IDs (activity and
milestone rows), its Data Date; per candidate Series (non-intake, same Project) the set `B`
of its **current published version** (11.3), or, when it has none, of its newest eligible
publication of any role by `(data_date, admitted_at, publication_id)`; candidates with no
eligible publication are skipped. Exact string equality only (R2 §16; no fuzzy, case or
whitespace folding beyond the parser's own normalization).

| Rule | Value |
|---|---|
| score | `floor(1000 × |A ∩ B| / |A ∪ B|)` (Jaccard, per-mille, integers) |
| considered | score ≥ 300 |
| data-date coherent | incoming Data Date ≥ the candidate's Data Date |
| `matched` | `|A| ≥ 20`, exactly 1 candidate with score ≥ 800, it is data-date coherent, and every other candidate scores < 500 |
| `ambiguous` | some candidate is considered but `matched` fails (reasons, closed: `multiple_high`, `margin`, `data_date_incoherent`, `insufficient_evidence`, `name_conflict`) |
| `no_match` | no candidate considered |
| candidate order | score desc, then Series `created_at` asc, then `series_id` asc |
| title | recorded (`title_equal: bool`), never read by the outcome |

Vectors (S6-1 commits each; IDs synthetic):

| # | Incoming `A` | Candidates | Outcome |
|---|---|---|---|
| M1 | `S1..S100` | X = `S1..S95 ∪ T1..T5` (904); Y = `S1..S10 ∪ U1..U90` (52) | `matched` X |
| M2 | `S1..S100` | X as M1 (904); Y = `S1..S90 ∪ V1..V10` (818) | `ambiguous` `multiple_high` [X, Y] |
| M3 | `S1..S100` | X = `W1..W100` (0) | `no_match` → `needs_series`, or a new Series when `series_name_if_new` is given |
| M4 (ID reuse) | `A1000..A1099`, Data Date 2027-01-04 | X = `A1000..A1099` with Data Date 2027-02-01 (1000) | `ambiguous` `data_date_incoherent` |
| M5 (small set) | `S1..S12` | X = `S1..S12` (1000) | `ambiguous` `insufficient_evidence` |
| M6a | `S1..S100` | X 850, Y 520 | `ambiguous` `margin` |
| M6b | `S1..S100` | X 850, Y 499 | `matched` X |
| M7 (title trap) | `S1..S100`, title equal to Y's | X 904, Y 52 | `matched` X (title ignored) |

### 11.3 B — currency and authority

**Derived current published version (S6-D17).** Per non-intake Series: the eligible set
`E` = publications with role `update`, effective status `complete` or `partial`, and no
successor whose effective status is `complete` or `partial` (a `failed`/`review_required`
successor does not displace its predecessor). `current` = max of `E` by `(data_date,
admitted_at, publication_id)`; null if `E` is empty. `same_data_date_ambiguity` = more than
1 member of `E` has the maximum Data Date. A `review_required` or `failed` publication can
never be current; nothing is deleted or hidden. Baselines and references are never current
(R2 §30: baselines are explicit).

| # | Series | Current | Ambiguity |
|---|---|---|---|
| C1 | P1, P2 both `update`, `complete`, Data Date 2027-01-31, P2 admitted later | P2 | true |
| C2 | C1 with P2 `supersedes` P1 | P2 | false |
| C3 | P1 (01-31, complete), P2 (02-28, `review_required`) | P1 | false |
| C4 | P1 (01-31, complete), P2 (02-28, `failed`, supersedes P1) | P1 | false |
| C5 | P1 `update` (01-31), B1 `baseline` (02-28) | P1 | false |
| C6 | only a `baseline` | null | false |

**Authority designation events (S6-D18).** Append-only table
`knowledge.schedule_authority_designations` (`sdsg_`): `designation_id`, `principal_id`,
`series_id`, `publication_id` (must be in that Series, non-intake, effective `complete` or
`partial`; else `conflict(STATUS)`), `scope` ∈ `series_current` (authoritative for the Series)
\| `data_date` (authoritative among publications sharing its Data Date), `action` ∈
`designate` \| `revoke` (`revoke` names the `designation_id` it revokes, same Principal,
Series and scope, not already revoked), `reason` (1..2,000 characters, required), provenance
derived as section 6.5 (`acceptance_basis` `user_confirmed` for the attested local operator,
`client_identified` otherwise), `recorded_at`. Never updated or deleted; a reversal is a later
event. Effective designation per `(series, scope[, data_date])` and per basis = the latest
non-revoked `designate` event. Reads report the derived current, the effective
`user_confirmed` designation and the effective `client_identified` designation separately;
**only a `user_confirmed` designation is ever treated as authoritative in anything
certified**, and nothing certified reads currency at all today (OD-08, section 7); a client
designation is shown labelled `client_identified`. A designation whose publication is later
superseded or whose Data Date is overtaken is still shown, flagged `designation_stale`.

**Scenarios (S6-D19).** `schedule_scenarios.create` takes an explicit `from_publication_id`
only; there is no "current" pointer argument. A client wanting the current version reads
`schedule_series.current` first and passes the id; the Scenario records that exact id.

### 11.4 Capabilities (added to section 6)

| Capability | Kind | Purpose | Summary |
|---|---|---|---|
| `schedule_designations.record` | write (additive) | `schedule_scenario_authoring` | Record an append-only authority designation (or its revocation) of one publication within its Series, with a reason. |
| `schedule_designations.list` | read | `schedule_scenario_read` | List a Series' authority designation events, newest first. |
| `schedule_series.current` | read | `schedule_scenario_read` | Read a Series' derived current published version, its same-Data-Date ambiguity, and its effective operator and client designations. |
| `schedule_series.match_decisions` | read | `schedule_scenario_read` | List a Project's series auto-match decisions with their candidates and scores, newest first. |

Same switch, gates, scopelessness, labels, rate budget (the designation write counts in the
section 8.3 write budget), remote and façade rules as section 6; `schedule_designations` →
feature `schedule`; `schedule_designations.record` joins `_IDEMPOTENT_REMOTE_CAPABILITIES`.
`schedule_publications.import` stays operator-only, attested-local and
`CONTROL_PLANE_EXCLUDED`; only its request grows. **Counts change accordingly** (supersede
the section 6.1/6.6/9.3 figures): 18 plane capabilities (5 writes, 13 reads); `Capability`
240 → 258; audit capability literals 251 → 269; `Purpose` 62 → 64 (unchanged by the
addendum); `IdKind` 156 → 162 (`sdsg`, `ssmd` added; both prefix-free against all 156 and
absent from `src`, `tests`, `web/src`, `migrations`); ChatLLM `DATA_CONDITIONAL` 137 → 155,
policy 258, full + schedule + scenarios 188, full + lineage + program + schedule +
scenarios 222, default + all 4 switches 154 (re-measured by S6-3). `SafeDetail` gains
`DESIGNATION_ID`, `SCOPE`, `REASON`, `SERIES_AUTO`.

### 11.5 Work split, prove-red and crosswalk

| Slice | Owns |
|---|---|
| S6-1 | pure `src/my_pa/domain/schedule/series_match.py` (`SERIES_MATCH_VERSION`, `match_series`, `MatchOutcome`, `MatchReason`, `MatchCandidate`) and `src/my_pa/domain/schedule/currency.py` (`current_publication`, `effective_designations`); tests `tests/unit/test_schedule_series_match.py` (M1–M7), `tests/unit/test_schedule_currency.py` (C1–C6 and designation revoke/stale vectors). Both modules sit under the S5a package guards (stdlib only) and the S6-1 no-float guard is extended to them |
| S6-2 | `schedule_intake_series`, `schedule_series_match_decisions`, `schedule_authority_designations` tables (append-only, TRUNCATE refusal, principal-composite FKs `RESTRICT`); the 2 `IdKind`s; the import request v2 digest and admission of the auto form; the worker finalization hook (match + auto admission in the finalization transaction, lease-checked); repository reads |
| S6-3 | the import command's additive fields; the 4 capabilities; reads; labels; guidance; the S5b-2 contract gains a forward note, never a rewrite |

| Prove-red | Test |
|---|---|
| P23 matcher folds case | `test_series_match_vectors[M1]` plus a case-variant vector `M1c` (must not match) |
| P24 margin rule removed | `test_series_match_vectors[M6a]` |
| P25 data-date coherence removed | `test_series_match_vectors[M4]` |
| P26 title used as a tiebreak | `test_series_match_vectors[M7]` |
| P27 failed successor displaces | `test_current_publication_vectors[C4]` |
| P28 ambiguity flag omitted | `test_current_publication_vectors[C1]` |
| P29 explicit `series_name` consults the matcher | `test_explicit_series_never_matches` (S6-2) |
| P30 client designation treated as authoritative | `test_only_operator_designations_are_authoritative` (S6-3) |

| Requirement | Section | First test |
|---|---|---|
| auto-matching, conservative, evidence recorded | 11.2 | `test_series_match_vectors` (S6-1), `test_auto_import_records_a_match_decision` (S6-2) |
| explicit Series always wins | 11.2 step 1 | `test_explicit_series_never_matches` (S6-2) |
| same-Data-Date retention and current version | 11.3 | `test_current_publication_vectors` (S6-1), `test_series_current_read_reports_ambiguity` (S6-3) |
| attributed authority designation | 11.3 | `test_designations_are_append_only_and_revocable` (S6-2) |
| scenarios name the exact publication | 11.3 | `test_scenario_records_the_exact_publication` (S6-3) |

### 11.6 Decisions, residuals and open product choices (continuing section 10)

| ID | Decision / residual / choice | Default or owner |
|---|---|---|
| S6-D16 | Auto-matching binds by a **second admission** after parsing; the intake publication stays as evidence | the Series is final at admission in the merged contract (T6-19/20) |
| S6-D17 | Currency is derived (role `update`, eligible, not displaced by an eligible successor), never stored | R2 §10.4 and §30 |
| S6-D18 | Authority is an append-only attributed claim; only `user_confirmed` counts for anything certified | OD-08, S3.1 provenance |
| S6-D19 | Scenarios always name the exact publication | no implicit pointer |
| S6-U10 | A matched auto import is parsed twice (intake and matched Series) | accepted cost; deterministic |
| S6-U11 | Matching uses only the candidate's single current (or newest) publication's ID set, not its history | later matcher version |
| S6-O11 | Matcher thresholds (consider 300, match 800, margin 500, minimum 20 IDs) | as tabled (`series-match-v1`) |
| S6-O12 | `matched` attaches automatically (no confirmation step) | yes, per the addendum; R8 to rule whether an operator confirmation is safer |
| S6-O13 | Currency considers role `update` only | yes |
| S6-O14 | Client designations are accepted (labelled `client_identified`) rather than refused | accepted, labelled, never authoritative |
| S6-O15 | The 4 addendum capabilities sit behind `MY_PA_SCHEDULE_SCENARIOS_ENABLED`; the import's auto form behind the same switch | yes (off: the auto form is `invalid_request(SERIES_AUTO)`) |
