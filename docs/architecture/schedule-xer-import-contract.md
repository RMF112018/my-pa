# P6 XER/XML schedule import — whole-slice contract (S7-0 to S7-6)

**Status:** proposed implementation contract. S7-0 is merged (#384), S7-1 is merged (#386),
S7-2 (revision `d8383150cf72`) is merged (#387), S7-3 (the admission service `import_p6`
and the `schedule` worker's P6 path, no migration, no capability) is merged (#389); its bounds-maximal synthetic measurement (25,000
activities, 100,000 relationships, 25,000 WBS rows, 8,526,632 bytes) ran the handler in 50.7 s
(the contained parse 6.1 s) against the 240 s budget on a local PostgreSQL 15 scratch cluster.
S7-4a (the 7 P6 capabilities, the switch composition, policy, ChatLLM `chatllm-data-v19`, the field registry and selection chain, the P6 reads, the format-aware S5 reads and the section 7.7 quota and import budgets; no migration) is merged (#391); S7-4b (the delta `cpm-workbench-p6-delta-v1` and the P6 scenario snapshot, acceptance D5 and D6; no migration, no new capability) is implemented on `feat/schedule-xer-handoff`, not merged (its corrections are the "As built in S7-4b" block after section 11.5).
Nothing else in it is implemented, and nothing is migrated on a shared database, granted,
switched on or deployed. The decision record is
[`ADR-023`](../decisions/ADR-023-p6-xer-xml-schedule-import.md), which loosens
[`ADR-016`](../decisions/ADR-016-cpm-workbench-schedule-evidence.md) decision 4 for the P6
XER and XML formats only and leaves
[`ADR-017`](../decisions/ADR-017-schedule-scenarios-and-baselines.md) unchanged. It extends,
and never forks, the CPM Workbench contracts
([`cpm-workbench-p6-full-v1-parser-contract.md`](cpm-workbench-p6-full-v1-parser-contract.md),
[`cpm-workbench-foundation-contract.md`](cpm-workbench-foundation-contract.md),
[`cpm-workbench-worker-capabilities-contract.md`](cpm-workbench-worker-capabilities-contract.md);
cited "S5a §n", "S5b-1 §n", "S5b-2 §n"), the
[`schedule-scenarios-contract.md`](schedule-scenarios-contract.md) (cited "S6 §n") and the
[`files-workspace-contract.md`](files-workspace-contract.md) (cited "FW §n").

**Basis:** `main@5409c5b69b07ef3f3435106b2bd80e199696ca70` (tree
`cceb6e63d63bdedceb5e894c6f050a46dc6306c7`), branch `feat/schedule-xer-contract`. Counts
below (capabilities 299, purposes 70, ChatLLM `chatllm-data-v15`, Alembic chain ending at
`6418b57081c3`) are measured there and **move** with main; each slice re-measures them.

**Evidence rule.** The operator supplied 2 sample exports of 1 project (an XER from P6 26.4
and the companion P6 API XML, namespace version V26.7). They were profiled read-only on the
operator's NAS; no byte, name, identifier, code, calendar or UDF of them is in the repository.
They show the **format** only. Schedules of many projects, and many versions of each, will be
imported, so nothing here is tailored to them. Every statement is marked:

- **[S]** verified on the sample (counts, field names, types, lengths, enumerations);
- **[D]** from the generic P6 file-format documentation as the author knows it, not verified
  here;
- **[A]** a design assumption about other P6 versions or exports, to be confirmed by the
  conformance script (section 12) on further exports.

---

## 0. Scope

### 0.1 In scope

| Item | Slice | Section |
|---|---|---|
| XER format, generic structure and the sample's statistics | S7-1 | 3 |
| XER ↔ XML identity and the discrepancies found | S7-1 (XER), XML later | 4 |
| Profile `p6_xer_v1`: required core, typed tolerated, optional (generic), never-captured | S7-1 | 5 |
| P6 field cross-reference catalogue (XER table.field ↔ XML path ↔ MY-PA target) | S7-1 | 6 |
| Optional-field registry, capture selection, observed-fields record | S7-2, S7-4 | 7 |
| Storage, provenance, migration shape, scale | S7-2 | 8 |
| Admission from a files-workspace file; snapshot; worker | S7-3 | 9 |
| Capabilities, switch, policy, ChatLLM, remote, audit, errors, read shapes | S7-4 | 10 |
| Many versions: Series identity, matching, delta, scenario hand-off | S7-2..S7-4 | 11 |
| Trust boundary and limits | all | 13 |
| Conformance script | S7-1 (script), S7-5 (real-corpus runs) | 12 |
| Slices, acceptance tests, prove-red plan, operator gates | — | 14, 15 |
| Re-capture of an imported publication from its retained snapshot | S7-6 (optional, undecided) | 7.6 |
| Scenario engine amendment: start and finish milestones, `my-pa-cpm-v2`, MY-PA standard calendar, fixed-calendar lag | S7-0 | 11.6, 11.7 |
| `p6_xml_v1` at contract level | later slice | 16 |

### 0.2 Out of scope

Resources, roles, costs, expenses, risks, notebooks, steps and baselines **as typed
schedule logic** (their fields can still be captured generically, section 7); multi-project
exports (refused, typed; **decided** 2026-11-23: not common); mixing PDF and P6 formats in one
Series or a cross-format delta (**decided** 2026-11-23: a project with PDF history starts a new
Series for XER); CPM over a publication (ADR-017
decision 2); any write to P6; real project data in the repository; production anything.

---

## 1. Repository truth at the basis (the key questions)

| # | Question | Repository truth | Consequence |
|---|---|---|---|
| T7-01 | How is `schedule_publications.import` authorized? | `ScheduleApplication.import_publication` (`src/my_pa/application/schedules.py`) refuses a remote transport, any capability grant or an authenticated client (`unsupported`), then `attested_lineage_authority` (`src/my_pa/application/lineage_authority.py`) admits only the CLI and the HTTP gateway's stamped operator surface; the name is in `_OPERATOR_ONLY` with purpose `schedule_import`; `remote_tool_names` never publishes it | PDF stays exactly so; the P6 import is a **new** capability (section 10) |
| T7-02 | How does admission pin a source? | `SqlScheduleRepository.admit_publication` (`src/my_pa/infrastructure/persistence/schedule.py`) checks `enrollments` (Principal-partitioned), `enrollment_objects`, `source_object_versions`, `SCHEDULE_MEDIA_TYPE = "application/pdf"` and `MAX_SCHEDULE_SOURCE_BYTES = 16777216` (`src/my_pa/domain/schedule/model.py`), then inserts the publication and 1 `schedule_jobs` row; the **document SHA-256 is pinned only by the worker** (phase H3). A source version carries no content hash (the fixture fingerprint is a stat tuple) | a P6 publication pins its SHA-256 at admission (section 9) |
| T7-03 | How does a file reach the files workspace? | `files.upload.begin` → byte routes → `files.upload.finalize` (SHA-256 and length verified), or `files.upload.begin` with `source_file`, or `files.write_text` (FW §6, §17.2). Entries are addressed by `workspace_id` + relative `path`; a `fv1_` version token is a stat fingerprint; SHA-256 on request (`files.stat include_sha256`) (FW §4). No MIME allowlist | the import names `workspace_id`, `path`, `expected_version` and `expected_sha256` |
| T7-04 | **How does a workspace file become an enrolled source version?** | **It cannot today.** No `files.*` code references enrollment or sources. The only live provider is `FixtureSourceProvider`; sources are registered only by the operator CLI (`apps/cli/sources.py register`), enrollment is the operator-only `sources.enroll`. And the files-workspace store **refuses** a root that is, contains or lies inside a configured source root (`src/my_pa/infrastructure/file_workspace/store.py`), so the workspace cannot be registered as a source | the smallest new surface is **not** a bridge into enrollment but an admission-time **snapshot** of the workspace file (section 9.1; options compared in 9.1.1) |
| T7-05 | Worker plane | `apps/worker.py run --plane schedule`, `SCHEDULE_JOBS` (`src/my_pa/infrastructure/persistence/jobs.py`), handler `process_schedule_publication` (`src/my_pa/infrastructure/jobs/schedule.py`) phases H1–H8, contained child (`schedule_parser_process.py`/`schedule_parser_child.py`), budgets 240 s handler, 150 s parse wall | reused; the handler dispatches on the publication's source format (section 9.3) |
| T7-06 | Storage model | 7 S5 tables; cells are JSONB `schedule_rows.cell_evidence` (no separate cells table); provenance `page_number`, `physical_line_ordinal`, `row_ordinal`, bbox; issues in `schedule_import_issues` | P6 rows need their own tables (no page/bbox; record line instead) |
| T7-07 | Engine inputs | `run_cpm(ScenarioContent)` (`src/my_pa/domain/schedule/scenario/cpm.py`); content holds data date, settings (default calendar, lag calendar, progress policy, must-finish-by, critical threshold), calendars (week + exceptions), activities (kind, remaining/original minutes, calendar, constraints, progress), relationships (type, lag minutes) | see T7-08 |
| T7-08 | **What does a PDF publication give the engine?** | Per row only Activity ID, name, row type, hierarchy path, 2 durations **without a unit**, 2 dates with an inert marker, and the publication data date. **No relationship, lag, calendar, constraint, float or actual** (S6 T6-02). `snapshot_from_publication` takes client calendars and `minutes_per_source_unit` and invents no logic | **What XER adds:** relationships with type and lag in hours; calendars (week intervals and dated exceptions); primary and secondary constraints; durations with a unit (hours); actual start/finish; the data date with a time; lag-calendar and progress-policy settings; and P6's own early/late dates and floats on the publication (read by Activity ID; the scenario content carries none of them, section 11.5 as built in S7-4b). A snapshot needs no client unit or calendar (section 11.5) |
| T7-09 | Closed policy surfaces | `Capability` (`src/my_pa/domain/identity/operation.py`), `_OPERATOR_ONLY`, permitted purposes, `_SCOPELESS` (`src/my_pa/domain/policy/decision.py`), command builders, `ApplicationService._HANDLERS`, `CHATLLM_CAPABILITY_POLICY`, remote `_WRITE_PURPOSES`, `_IDEMPOTENT_REMOTE_CAPABILITIES`, `_CLIENT_BOUND_KEY_CAPABILITIES`, audit `capability_is_known`/`purpose_is_known` CHECKs; pins in `tests/pins.json` | every new name lands on all of them (section 10.7) |
| T7-10 | Switches | `MY_PA_SCHEDULE_ENABLED` and `MY_PA_SCHEDULE_SCENARIOS_ENABLED` (`src/my_pa/bootstrap/settings.py`), both default false; scenarios effective only with schedule; the restricted MCP DB-profile composition disables both | `MY_PA_SCHEDULE_P6_ENABLED` stacks the same way |
| T7-11 | Partitioning | application-level only (`principal_bound_values`, `partition_criterion`); no RLS; `principal_id NOT NULL` on every schedule table; guards `tests/architecture/test_user_owned_tables_are_partitioned.py`, `test_principal_partition_is_reached_through_the_guard.py` | every new table is Principal-partitioned |
| T7-12 | XER/XML runtime guard | `tests/security/test_cpm_workbench_security.py::test_no_xer_or_xml_runtime_in_the_schedule_plane` forbids `xml`, `lxml`, `defusedxml`, `xmltodict`, `openpyxl`, `xlrd`, `sqlite3`, `jpype`, `py4j` in the schedule sources | the XER parser needs none of them; the XML slice narrows the guard to admit only the hardened stdlib path (section 13.3) |

---

## 2. Operator decisions (2026-11-23) and their effect

1. XER first (`p6_xer_v1`), specified in full; XML (`p6_xml_v1`) later as a cross-check of
   the same publication, specified at contract level (section 16).
2. An MCP-triggered import for XER/XML, gated by grants; PDF stays operator-only and
   attested-local. The change table against ADR-016 decision 4 is in ADR-023.
3. (Correction) The samples show the format only; design for many projects and many
   versions, nothing project-specific.
4. (Correction) Any data the operator finds worth exporting must be recordable and usable
   without a code change or migration per field: a cross-reference catalogue, an
   optional-field registry with grant-gated selection, a generic typed field store, an
   observed-fields record, reads that filter and sort on captured fields, and named limits
   (section 7).
5. (Answers, 2026-11-23) The operator decided the open questions: section 17. They add the
   MY-PA standard calendar (11.6), faithful start and finish milestones on a new engine id
   (11.7, slice S7-0), full snapshot retention (7.6) and the decided defaults of 11.5.

---

## 3. The XER format

### 3.1 Structure (generic) [S][D]

An XER is a tab-separated text export. Records, one per line:

| Line | Meaning |
|---|---|
| `ERMHDR` `\t` version `\t` export date `\t` … | header, first line; field 2 is the export version (`26.4` in the sample, [S]); 9 fields in the sample [S]; later fields are export metadata (user, database, currency) and are never stored |
| `%T` `\t` table | starts a table |
| `%F` `\t` field … | the table's field names, once, right after `%T` |
| `%R` `\t` value … | one record; exactly as many values as `%F` fields ([S]: 0 width mismatches in 9,186 records) |
| `%E` | end of file, last line |

There is no quoting or escaping: a value cannot contain a tab or a line break [D]. Tables
appear in a dependency order that varies by export [A]; the parser never relies on order
beyond `%T`/`%F`/`%R` adjacency.

### 3.2 Bytes, encoding, line endings [S]

- The sample is **not valid UTF-8**: it is Windows-1252 (bytes such as `0x80`, `0xA3`, `0xA5`
  in currency symbols) and decodes strictly as cp1252. There is no encoding declaration.
- Lines end in CRLF (every line; no bare CR or LF inside a line).
- The `CALENDAR.clndr_data` blob uses byte `0x7F` pairs as its internal line separator
  (238 to 524 per calendar). `SCHEDOPTIONS.LevelPriorityList` also carries non-ASCII
  separators.
- Rule: decode strictly as UTF-8 if valid, else strictly as Windows-1252, else fail
  `p6_encoding_invalid`. The chosen encoding is recorded. Accept CRLF or LF line ends; a bare
  CR, NUL, or a C0 control other than tab (and `0x7F` inside `clndr_data`) in a value is
  `p6_value_invalid` for that field.
- A byte-order mark is not stripped: the first line then does not start with `ERMHDR`, and
  the file fails `p6_header_invalid`.

Admission (9.1 step 3) requires the bytes to start with `ERMHDR\t`, so a file with a BOM in front is refused there as `unsupported(SOURCE_FORMAT)` before the parser's `p6_header_invalid` could apply.

### 3.3 Identifiers and value forms [S]

| Item | Form in the sample |
|---|---|
| `task_id`, `wbs_id`, `proj_id`, `clndr_id`, `task_pred_id`, `actv_code_id`, `udf_type_id` | positive integers of 3 to 9 digits; **database-internal object ids** (XML `ObjectId`) |
| `task_code` | the user-visible **Activity ID**, text of 5..12 characters, unique in the file (3,035 distinct of 3,035) |
| `proj_short_name` | the user-visible Project ID (XML `Project/Id`); the project's long name is **not** in `PROJECT`: it is the `wbs_name` of the `PROJWBS` row with `proj_node_flag = Y` (XML `Project/Name`) |
| `guid` | 22 characters: the unpadded standard base64 of the 16 GUID bytes in RFC 4122 (big-endian) order; equal to the braced 38-character XML `GUID` for 3,035 of 3,035 activities |
| dates | `YYYY-MM-DD HH:MM`, naive, minute resolution, never midnight-only in the sample (all early/late dates carry a working time) |
| durations, floats, lags | hours (`*_hr_cnt`), integers in the sample (no fractional values, no negative floats); P6 allows decimals [D] |
| flags | `Y`/`N` |
| enumerations | P6 tokens `PREFIX_Name` (`TT_Task`, `PR_FS`, `CS_MEOB`, `rcal_Predecessor`, …) |
| empty value | the empty string; there is no null marker |

### 3.4 Calendars (`clndr_data`) [S]

A bracketed tree: `(0||CalendarData()( (0||DaysOfWeek()( (0||1()( (0||0(s|08:00|f|12:00)()) … ))
… )) (0||VIEW(…)…) (0||Exceptions()( (0||0(d|NNNNN)( … )) … )) ))`, with `0x7F` pairs between
nodes.

- `DaysOfWeek` children are numbered **1 = Sunday … 7 = Saturday** (verified: days 1 and 7
  carry no intervals on the 5-day calendars, matching XML `Sunday`/`Saturday` without work
  time, and Monday–Friday carry them).
- An interval is `s|HH:MM|f|HH:MM`; 2 per working day in the sample; no `f|00:00` (midnight
  end) seen. P6 may write `00:00` as a day's end [D]: it is read as minute 1,440.
- `Exceptions` children carry `d|N`, **N = days since 1899-12-30** (verified: the converted
  dates equal XML `HolidayOrException/Date` exactly, 242 and 96 per calendar); an exception
  with no interval is a non-working day; all sample exceptions are non-working.
- `VIEW` is display state and is ignored.
- A project calendar (`CA_Project`) names a base calendar but carries its own complete data
  in the sample [S]; inheritance is not resolved by the parser ([A]: an export may rely on the
  base; if a calendar has no `DaysOfWeek`, its base's week is used and the substitution is
  recorded as an issue).

### 3.5 Sample statistics [S] (counts only)

16 tables, 9,186 records, 305 fields:

| Table | Records | Fields | Note |
|---|---|---|---|
| CURRTYPE | 17 | 11 | currencies |
| FINTMPL | 1 | 3 | financial period template |
| LOCATION | 9 | 15 | addresses |
| NONWORK | 7 | 4 | non-work types |
| OBS | 2 | 6 | responsibility structure (personal names) |
| UDFTYPE | 2 | 9 | 1 TASK, 1 PROJECT, both `FT_TEXT` |
| PROJECT | 1 | 88 | exactly 1 project |
| CALENDAR | 4 | 13 | 2 `CA_Base`, 2 `CA_Project`; all 3,035 activities use 1 project calendar |
| SCHEDOPTIONS | 1 | 25 | |
| PROJWBS | 472 | 26 | depth ≤ 7 below the project node; 1 project node |
| ACTVTYPE | 1 | 8 | `AS_Global` |
| TASK | 3,035 | 67 | 3,028 `TT_Task`, 6 `TT_FinMile`, 1 `TT_Mile`; all `TK_NotStart`; 2 constraints |
| ACTVCODE | 1 | 8 | |
| TASKPRED | 4,722 | 11 | 4,112 FS, 499 FF, 111 SS, 0 SF; 256 positive lags, 0 negative; 0 cross-project |
| TASKACTV | 350 | 4 | |
| UDFVALUE | 561 | 7 | 560 on activities, 1 on the project; text only |

Not present in the sample but common in exports [D]: `RSRC`, `TASKRSRC`, `ROLES`, `ACCOUNT`,
`PROJCOST`, `TASKMEMO`, `MEMOTYPE`, `TASKPROC`, `UDFCODE`, `PCATTYPE`, `PCATVAL`, `PROJPCAT`,
`RCATTYPE`, `RCATVAL`, `RSRCRCAT`, `UMEASURE`, `SHIFT`, `SHIFTPER`, `COSTTYPE`, `EXPTYPE`.
Their presence depends on the export options [A].

---

## 4. XER ↔ XML identity and discrepancies (sample) [S]

| XER | XML (`APIBusinessObjects`) | Agreement |
|---|---|---|
| `TASK.task_id` | `Project/Activity/ObjectId` | 3,035 = 3,035 |
| `TASK.task_code` | `Project/Activity/Id` | 3,035 = 3,035 |
| `TASK.guid` (22, base64) | `Project/Activity/GUID` (38, braced) | same 16 bytes, 3,035 |
| `TASKPRED.task_pred_id` | `Project/Relationship/ObjectId` | 4,722 = 4,722 |
| `TASKPRED.task_id` / `pred_task_id` | `SuccessorActivityObjectId` / `PredecessorActivityObjectId` | 0 mismatches |
| `TASKPRED.lag_hr_cnt` | `Relationship/Lag` (hours) | 0 mismatches |
| `PROJWBS.wbs_id` | `Project/WBS/ObjectId` | 471 of 472 (below) |
| `CALENDAR.clndr_id` | `Calendar/ObjectId`, `Project/Calendar/ObjectId` | 3 of 4 (below) |
| `PROJECT.proj_id` / `proj_short_name` | `Project/ObjectId` / `Project/Id` | equal |
| `PROJECT.last_recalc_date` | `Project/DataDate` | equal |
| dates `YYYY-MM-DD HH:MM` | `YYYY-MM-DDTHH:MM:SS` (seconds always `00`) | 0 mismatches across 9 activity date fields (early, late, planned, remaining-early, constraint) |
| durations (hours) | `PlannedDuration`, `RemainingDuration` (hours) | 0 mismatches |
| `TASK` start/finish | `StartDate` = `act_start_date` if set else `early_start_date`; `FinishDate` = `act_end_date` if set else `early_end_date` | 0 mismatches |
| `TASK.task_name`, `PROJWBS.wbs_name` | `Name`, wrapped in `<![CDATA[…]]>` when it contains `&` (474 such names) | equal after CDATA unwrapping |

Enumeration labels: `TT_Task` = `Task Dependent`, `TT_Mile` = `Start Milestone`, `TT_FinMile`
= `Finish Milestone`, `TK_NotStart` = `Not Started`, `PR_FS`/`PR_FF`/`PR_SS` = `Finish to
Start`/`Finish to Finish`/`Start to Start`, `CS_MEOB` = `Finish On or Before`, `CS_MEOA` =
`Finish On or After`, `DT_FixedDUR2` = `Fixed Duration and Units`, **`DT_FixedRate` = `Fixed
Units/Time`**, **`DT_FixedDrtn` = `Fixed Duration and Units/Time`** (the token names do not
match the labels), `CP_Drtn` = `Duration`, `CA_Base` = `Global`, `CA_Project` = `Project`.
XML flags are `0`/`1`.

**Discrepancies:**

1. **Version labels differ:** `ERMHDR` says `26.4`; the XML namespace says `V26.7`. A
   publication records both; they are not compared.
2. **WBS:** XML omits the project node row (472 vs 471); its 5 top-level WBS elements have a
   nil `ParentObjectId` where XER points at the project node.
3. **Calendars:** XER holds 4, XML 3; the XER-only calendar is an unused `CA_Base` calendar.
   XML nests project calendars under `Project` and global ones at the top level.
4. **OBS:** XER 2 rows, XML 4.
5. **Floats:** XER carries `total_float_hr_cnt` and `free_float_hr_cnt`; the XML carries
   neither (and no critical or driving flag).
6. **GUID text form** differs (section 3.3).
7. **Size:** the XML is about 8.3 times the XER (16.3 MB vs 1.9 MB); it is UTF-8, LF, with
   no DTD or entity declaration, tab-indented, one element per line.

The later cross-check (section 16) matches by `ObjectId` and compares the mapped fields;
items 2–5 are expected differences, not errors.

---

## 5. Profile `p6_xer_v1`

### 5.1 Tiers

Every catalogued field has exactly 1 tier:

| Tier | Meaning | Missing field (no `%F` column) | Empty value |
|---|---|---|---|
| **R** required core | the engine or the delta needs it | fatal `p6_required_field_missing` | allowed only where the catalogue says so (for example `act_start_date`), else fatal `p6_value_invalid` |
| **T** typed tolerated | stored in a typed column when present | stored null, info issue once | null |
| **O** optional | captured into the generic field store when selected (section 7); catalogue sets the default | nothing | nothing stored |
| **N** never captured | executable or meaningless outside P6 (for example `UDFTYPE.indicator_expression`) | nothing | nothing |
| **V** derived | not stored as such; consumed to build typed data (for example `clndr_data`) | per the field it feeds | per the field it feeds |

Required tables: `PROJECT`, `CALENDAR`, `PROJWBS`, `TASK`, `TASKPRED` (a file with no
relationships still has the table header in P6 exports [A]; an absent `TASKPRED` is fatal
`p6_required_table_missing`, because silently importing a logic-free network would mislead the
engine). Tolerated tables: `SCHEDOPTIONS`, `UDFTYPE`, `UDFVALUE`, `ACTVTYPE`, `ACTVCODE`,
`TASKACTV`, `UDFCODE`, `RSRC`, `TASKRSRC`. Every other catalogued table is optional (its
fields are O). A table the catalogue does not know is recorded as observed (section 7.4) with
a non-fatal `p6_unknown_table`.

### 5.2 Unknown-field policy

A field the catalogue has never seen (name not in the table's catalogue) is: (a) recorded
in the observed-fields record with stats only (present, non-empty count, min/max length, a
value-shape histogram: integer, decimal, date, flag, text); (b) reported once per field as
the non-fatal issue `p6_unknown_field` (table and field name only, if the name matches
`[A-Za-z][A-Za-z0-9_]{0,63}`, else as `p6_unknown_field_unnamed`); (c) **not stored** unless
the operator has selected it for capture, in which case it is captured as bounded text
(section 7.2).

Why this rather than preserving every unknown value: storing unseen fields by default would
store data no one reviewed (unknown size, possibly personal), break the rule that every stored
value has a documented source, and grow storage with fields nobody reads. Why not fail:
different P6 versions and export options add fields routinely; failing would block every
newer export. The observed-fields record plus selection gives the operator every field
without a code change, and the snapshot retention (section 7.6) lets a later selection be
applied to versions already imported.

### 5.3 Version variation [A]

- `ERMHDR` version: any `\d{1,2}\.\d{1,2}(\.\d{1,4}){0,2}` is accepted and recorded. A
  version outside the catalogue's tested range (`26.x`, the sample) adds the non-fatal
  `p6_export_version_untested`; the required-core check alone decides acceptance.
- A field present in the catalogue for some versions and absent in a file is handled by its
  tier (R fatal, T null, O nothing).
- An enumeration value not in the catalogue: in an **R** field (`task_type`, `status_code`,
  `pred_type`, `cstr_type`, `clndr_type`) it is fatal `p6_unknown_enum_value`; R value sets
  are closed. In a T or O field a token (≤ 64 characters, pattern `[A-Za-z0-9_]{1,64}`) is
  stored as its raw token with the non-fatal `p6_unknown_enum_value`; a value that is not a
  token is `p6_value_invalid` and stored null.
- Multiple `PROJECT` rows: fatal `p6_multiple_projects` (single-project exports only;
  operator decision 2026-11-23: multi-project exports are not common, keep refusing them).

### 5.4 Caps (hard; exceeding any is fatal `p6_bound_exceeded` naming the bound)

| Bound | Value |
|---|---|
| file | ≤ 16,777,216 bytes (16 MiB; the sample is 1.9 MB) |
| line | ≤ 4,194,304 bytes |
| tables / fields per table | ≤ 128 / ≤ 512 |
| total records | ≤ 2,000,000 |
| `TASK` / `TASKPRED` / `PROJWBS` | ≤ 25,000 / ≤ 100,000 / ≤ 25,000 (the engine's bounds, S6 §2.10) |
| `CALENDAR` / exceptions per calendar | ≤ 1,000 / ≤ 20,000 |
| `UDFTYPE` / `ACTVTYPE` / `ACTVCODE` | ≤ 2,000 / ≤ 2,000 / ≤ 100,000 |
| `UDFVALUE` / `TASKACTV` / `TASKRSRC` | ≤ 1,000,000 / ≤ 500,000 / ≤ 500,000 |
| value length | ≤ 65,536 characters; `clndr_data` ≤ 1,048,576 |
| calendar tree | depth ≤ 16, nodes ≤ 100,000 (200,000 could not be reached under the 1,048,576-character `clndr_data` cap) |
| WBS depth | ≤ 64 |
| numbers | `-?\d{1,15}(\.\d{1,6})?`: up to 15 integer digits and 6 decimals are kept (section 6.2 widths) |
| dates | `YYYY-MM-DD HH:MM`; seconds are accepted only when zero (`HH:MM:SS` with `SS` = `00`) [D] (any other seconds value is `p6_value_invalid`); years 1900–2199 |

### 5.5 Structural validation (fatal, in order)

`p6_encoding_invalid`, `p6_header_invalid` (first line not `ERMHDR`), `p6_structure_invalid`
(record before `%T`, `%R` before `%F`, duplicate table, duplicate field, missing `%E`, content
after `%E` other than blank lines, which are tolerated), `p6_record_width_mismatch`,
`p6_bound_exceeded`, `p6_required_table_missing`, `p6_required_field_missing`,
`p6_multiple_projects`, `p6_value_invalid` (R field), `p6_unknown_enum_value` (R field),
`p6_duplicate_activity_id` (`task_code` repeated or empty), `p6_structure_invalid` (the number
of `PROJWBS` rows with `proj_node_flag = Y` is not exactly 1; the issue names the table and
field, not a value), `p6_reference_dangling` (a `TASK.wbs_id` or same-project `TASKPRED` end
that names no row; a non-project `PROJWBS` row whose `parent_wbs_id` names no row; a `TASK` or
`PROJWBS` `proj_id` that differs from the `PROJECT` row's), `p6_wbs_cycle`. A missing or
unparseable activity calendar is **not** fatal (operator decision 2026-11-23): it is
`p6_calendar_missing` below.

Order details. The parse stops at the first fatal issue, and within one check at the first
by line. The calendar-tree bounds of 5.4 are checked (every `clndr_data` blob is parsed)
before the required-table check. Duplicate P6 ids (`task_id`, `wbs_id`, `clndr_id`,
`task_pred_id`) are `p6_structure_invalid`, raised with `p6_duplicate_activity_id` after the
value checks; the WBS depth bound (`p6_bound_exceeded`) is raised with `p6_wbs_cycle`, after
the reference checks. The returned issue list is capped at 10,000 issues; the counts by code
are always complete.

Non-fatal: `p6_tolerated_field_missing` (info: a T field with no `%F` column, once per table
and field, section 5.1), `p6_unknown_table`, `p6_unknown_field`, `p6_unknown_field_unnamed`,
`p6_unknown_enum_value` (T/O), `p6_export_version_untested`, `p6_value_invalid` (T/O field:
stored null), `p6_external_relationship` (`pred_proj_id ≠ proj_id`: stored, flagged),
`p6_calendar_invalid` (unused calendar), `p6_calendar_base_substituted`,
`p6_calendar_missing` (a `TASK.clndr_id` that names no row, or a used calendar whose data is
unparseable: the activity is stored with its P6 calendar id and the scenario snapshot gives it
the MY-PA standard calendar, section 11.6),
`p6_capture_cap_reached` (section 7.7), `p6_project_identity_changed` (section 11.1: makes the
publication `review_required`).

Implementation notes (no rule of their own): an empty file is `p6_structure_invalid`; with
several `SCHEDOPTIONS` rows the first (of the project) is taken; a "used" calendar is one named
by a `TASK.clndr_id` (the project default calendar does not make a calendar used).

---

## 6. P6 field cross-reference catalogue

### 6.1 Form

The machine-readable catalogue is a Python literal module
`src/my_pa/domain/schedule/p6/catalogue.py` (S7-1), versioned `p6-field-catalogue-v1`, with 1
record per field: `field_key`, XER table and field, XML path, entity kind, value type, unit,
tier, default capture, sample status (`seen` / `documented`), P6 versions seen, engine use,
delta use, storage target, sensitivity (`personal` for user and person names and addresses).
A Python module (not JSON) because the domain package may not read files
(`tests/architecture/test_cpm_full_parser_scope.py`). S7-1 adds a test that renders the module
and compares it row for row with the tables below, so the contract and the catalogue cannot
drift. Adding a catalogued field later is a data edit to that module plus a catalogue version
bump — no migration, no handler or schema change — and until then the field is still
capturable as text through the observed-fields path (section 7).

Type rule for fields listed by name only (6.7 and 6.8 optional lists, 6.9 and 6.10 field
lists): a name ending `_flag` is `flag`, `_date` is `ts`, `_id`, `_id1` or `_id2` is `id`;
every other field is `text(4000)`.

`field_key` grammar: `xer:<TABLE>.<field>` for a fixed field; `udf:<owner>:<label>` for a
UDF (owner `TASK`, `PROJWBS`, `PROJECT`, `TASKRSRC`, `RSRC`; label normalized NFC, ≤ 120
characters); `code:<type label>` for an activity-code type. UDF and code keys use the
**label**, not the P6 id, because type ids are database-internal and differ between databases
and re-exports [A]; a label change therefore appears as a new field (documented, never
guessed).

### 6.2 Columns of the tables below

- **XML**: the `APIBusinessObjects` path; `—` when no 1:1 element was identified; seen in the
  sample unless marked [D].
- **Type**: `id` (bigint), `text(n)`, `name` (normalized display text ≤ 2,000), `enum`,
  `flag`, `ts` (naive minute timestamp), `hours` (numeric(21,6)), `num` (numeric(21,6)), `int`,
  `blob`. The numeric widths hold the 15 integer digits and 6 decimals of 5.4; S7-2 uses them.
- **Tier**: R, T, O (`O+` captured by default, `O−` not by default), N, V (section 5.1).
- **Use**: `E` scenario snapshot / engine, `Δ` delta, `—` neither.
- **Target**: the MY-PA storage target (section 8): a typed column `table.column`, `FS` (the
  generic field store), `derived → …`, or `none`.
- **Seen**: `S` in the sample, `D` documented only.

### 6.3 `TASK` (entity `activity`) — typed table `schedule_p6_activities`

| XER field | XML | Type | Unit | Tier | Use | Target | Seen |
|---|---|---|---|---|---|---|---|
| task_id | Activity/ObjectId | id | — | R | — | `p6_task_id` (provenance; never a cross-version key) | S |
| proj_id | Activity/ProjectObjectId | id | — | R | — | derived → must equal `PROJECT.proj_id` | S |
| wbs_id | Activity/WBSObjectId | id | — | R | E | `p6_wbs_id`; derived → `wbs_path` | S |
| clndr_id | Activity/CalendarObjectId | id | — | R | E | `p6_calendar_id` | S |
| phys_complete_pct | Activity/PhysicalPercentComplete | num | % | T | Δ | `physical_pct` | S |
| rev_fdbk_flag | Activity/IsNewFeedback | flag | — | O− | — | FS | S |
| est_wt | Activity/EstimatedWeight | num | — | O− | — | FS | S |
| lock_plan_flag | — | flag | — | O− | — | FS | S |
| auto_compute_act_flag | Activity/AutoComputeActuals | flag | — | O− | — | FS | S |
| complete_pct_type | Activity/PercentCompleteType | enum | — | T | — | `percent_complete_type` | S |
| task_type | Activity/Type | enum | — | R | E Δ | `task_type` | S |
| duration_type | Activity/DurationType | enum | — | T | Δ | `duration_type` | S |
| status_code | Activity/Status | enum | — | R | E Δ | `status_code` | S |
| task_code | Activity/Id | text(40) | — | R | E Δ | `activity_id`; Stable Activity key | S |
| task_name | Activity/Name | name | — | R | E Δ | `activity_name` | S |
| rsrc_id | Activity/PrimaryResourceObjectId | id | — | O− | — | FS | S |
| total_float_hr_cnt | — (absent in XML [S]; `TotalFloat` [D]) | hours | h | T | Δ | `total_float_hours` | S |
| free_float_hr_cnt | — (`FreeFloat` [D]) | hours | h | T | Δ | `free_float_hours` | S |
| remain_drtn_hr_cnt | Activity/RemainingDuration | hours | h | R | E Δ | `remaining_hours` | S |
| act_work_qty | Activity/ActualLaborUnits | num | h | O− | — | FS | S |
| remain_work_qty | Activity/RemainingLaborUnits | num | h | O− | — | FS | S |
| target_work_qty | Activity/PlannedLaborUnits | num | h | O− | — | FS | S |
| target_drtn_hr_cnt | Activity/PlannedDuration | hours | h | R | E Δ | `original_hours` | S |
| target_equip_qty | Activity/PlannedNonLaborUnits | num | h | O− | — | FS | S |
| act_equip_qty | Activity/ActualNonLaborUnits | num | h | O− | — | FS | S |
| remain_equip_qty | Activity/RemainingNonLaborUnits | num | h | O− | — | FS | S |
| cstr_date | Activity/PrimaryConstraintDate | ts | — | R (empty allowed) | E Δ | `constraint_date` | S |
| act_start_date | Activity/ActualStartDate | ts | — | R (empty allowed) | E Δ | `actual_start` | S |
| act_end_date | Activity/ActualFinishDate | ts | — | R (empty allowed) | E Δ | `actual_finish` | S |
| late_start_date | Activity/LateStartDate | ts | — | T | Δ | `late_start` | S |
| late_end_date | Activity/LateFinishDate | ts | — | T | Δ | `late_finish` | S |
| expect_end_date | Activity/ExpectedFinishDate | ts | — | O+ | — | FS | S |
| early_start_date | Activity/EarlyStartDate | ts | — | R | Δ | `early_start`; derived → `start_at` | S |
| early_end_date | Activity/EarlyFinishDate | ts | — | R | Δ | `early_finish`; derived → `finish_at` | S |
| restart_date | Activity/RemainingEarlyStartDate | ts | — | T | — | `remaining_early_start` | S |
| reend_date | Activity/RemainingEarlyFinishDate | ts | — | T | — | `remaining_early_finish` | S |
| target_start_date | Activity/PlannedStartDate | ts | — | T | Δ | `planned_start` | S |
| target_end_date | Activity/PlannedFinishDate | ts | — | T | Δ | `planned_finish` | S |
| rem_late_start_date | Activity/RemainingLateStartDate | ts | — | O+ | — | FS | S |
| rem_late_end_date | Activity/RemainingLateFinishDate | ts | — | O+ | — | FS | S |
| cstr_type | Activity/PrimaryConstraintType | enum | — | R (empty allowed) | E Δ | `constraint_type` | S |
| priority_type | Activity/LevelingPriority | enum | — | O− | — | FS | S |
| suspend_date | Activity/SuspendDate | ts | — | O+ | — | FS | S |
| resume_date | Activity/ResumeDate | ts | — | O+ | — | FS | S |
| float_path | — | int | — | O− | — | FS | S |
| float_path_order | — | int | — | O− | — | FS | S |
| guid | Activity/GUID | text(22) | — | T | — | `p6_guid` (renumber hint, section 11.3) | S |
| tmpl_guid | — | text(22) | — | O− | — | FS | S |
| cstr_date2 | Activity/SecondaryConstraintDate | ts | — | T | E Δ | `constraint2_date` | S |
| cstr_type2 | Activity/SecondaryConstraintType | enum | — | T | E Δ | `constraint2_type` | S |
| driving_path_flag | — | flag | — | O+ | — | FS | S |
| act_this_per_work_qty | Activity/ActualThisPeriodLaborUnits | num | h | O− | — | FS | S |
| act_this_per_equip_qty | Activity/ActualThisPeriodNonLaborUnits | num | h | O− | — | FS | S |
| external_early_start_date | Activity/ExternalEarlyStartDate | ts | — | O+ | — | FS | S |
| external_late_end_date | Activity/ExternalLateFinishDate | ts | — | O+ | — | FS | S |
| cbs_id | Activity/CBSCode | id | — | O− | — | FS | S |
| pre_pess_start_date | — | ts | — | O− | — | FS | S |
| pre_pess_finish_date | — | ts | — | O− | — | FS | S |
| post_pess_start_date | — | ts | — | O− | — | FS | S |
| post_pess_finish_date | — | ts | — | O− | — | FS | S |
| create_date | — | ts | — | O− | — | FS | S |
| update_date | — | ts | — | O− | — | FS | S |
| create_user | — | text(255) | — | O− (personal) | — | FS | S |
| update_user | — | text(255) | — | O− (personal) | — | FS | S |
| location_id | Activity/LocationObjectId | id | — | O− | — | FS | S |
| control_updates_flag | — | flag | — | O− | — | FS | S |
| crt_path_num | — | int | — | O− | — | FS | S |

Derived activity columns: `start_at` = `actual_start` if set else `early_start`, `finish_at` =
`actual_finish` if set else `early_finish` (equal to XML `StartDate`/`FinishDate`, section 4);
`wbs_path` (the `wbs_short_name` labels below the project node, from its children down; the
depth, ≤ 64, counts those levels and not the project node); `kind` (`task` for
`TT_Task` and the other non-milestone types, `start_milestone` for `TT_Mile`,
`finish_milestone` for `TT_FinMile`; mapped faithfully, never collapsed, section 11.7).

Enumerations: `task_type` {`TT_Task`, `TT_Mile`, `TT_FinMile`} [S], {`TT_LOE`, `TT_WBS`,
`TT_Rsrc`} [D]; `status_code` {`TK_NotStart`} [S], {`TK_Active`, `TK_Complete`} [D];
`duration_type` {`DT_FixedDUR2`, `DT_FixedRate`, `DT_FixedDrtn`} [S], {`DT_FixedQty`} [D];
`complete_pct_type` {`CP_Drtn`} [S], {`CP_Units`, `CP_Phys`} [D]; `cstr_type`/`cstr_type2`
{`CS_MEOA`, `CS_MEOB`} [S], {`CS_MSO`, `CS_MSOA`, `CS_MSOB`, `CS_MEO`, `CS_MANDSTART`,
`CS_MANDFIN`, `CS_ALAP`} [D]; `priority_type` {`PT_Normal`} [S].

### 6.4 `TASKPRED` (entity `relationship`) — typed table `schedule_p6_relationships`

| XER field | XML | Type | Unit | Tier | Use | Target | Seen |
|---|---|---|---|---|---|---|---|
| task_pred_id | Relationship/ObjectId | id | — | R | — | `p6_relationship_id` | S |
| task_id | Relationship/SuccessorActivityObjectId | id | — | R | E Δ | `succ_p6_task_id` → successor row | S |
| pred_task_id | Relationship/PredecessorActivityObjectId | id | — | R | E Δ | `pred_p6_task_id` → predecessor row | S |
| proj_id | Relationship/SuccessorProjectObjectId | id | — | R | — | derived → `is_external` | S |
| pred_proj_id | Relationship/PredecessorProjectObjectId | id | — | R | — | derived → `is_external` | S |
| pred_type | Relationship/Type | enum | — | R | E Δ | `relationship_type` | S |
| lag_hr_cnt | Relationship/Lag | hours | h | R | E Δ | `lag_hours` | S |
| comments | Relationship/Comments | text(4000) | — | O− | — | FS | S |
| float_path | — | int | — | O− | — | FS | S |
| aref | — | ts | — | O− | — | FS | S |
| arls | — | ts | — | O− | — | FS | S |

`is_external` is true when `pred_proj_id` differs from `proj_id` or `proj_id` differs from
the `PROJECT` row's `proj_id`.

`pred_type` {`PR_FS`, `PR_SS`, `PR_FF`} [S], {`PR_SF`} [D]. Relationships are matched across
publications by the (predecessor, successor) Activity-ID pair, never by `task_pred_id`.

### 6.5 `PROJWBS` (entity `wbs`) — typed table `schedule_p6_wbs`

| XER field | XML | Type | Tier | Use | Target | Seen |
|---|---|---|---|---|---|---|
| wbs_id | WBS/ObjectId | id | R | E | `p6_wbs_id` | S |
| proj_id | WBS/ProjectObjectId | id | R | — | derived check | S |
| obs_id | WBS/OBSObjectId | id | O− | — | FS | S |
| seq_num | WBS/SequenceNumber | int | T | — | `sequence` | S |
| est_wt | WBS/EstimatedWeight | num | O− | — | FS | S |
| proj_node_flag | — (row absent in XML) | flag | R | E | `is_project_node` | S |
| sum_data_flag | — | flag | O− | — | FS | S |
| status_code | WBS/Status | enum | T | — | `status_code` | S |
| wbs_short_name | WBS/Code | text(40) | R | E Δ | `short_name` | S |
| wbs_name | WBS/Name | name | R | E Δ | `name` | S |
| phase_id | — | id | O− | — | FS | S |
| parent_wbs_id | WBS/ParentObjectId | id | R | E | `parent_p6_wbs_id` | S |
| ev_user_pct | WBS/EarnedValueUserPercent | num | O− | — | FS | S |
| ev_etc_user_value | WBS/EarnedValueETCUserValue | num | O− | — | FS | S |
| orig_cost | WBS/OriginalBudget | num | O− | — | FS | S |
| indep_remain_total_cost | WBS/IndependentETCTotalCost | num | O− | — | FS | S |
| ann_dscnt_rate_pct | — | num | O− | — | FS | S |
| dscnt_period_type | — | enum | O− | — | FS | S |
| indep_remain_work_qty | WBS/IndependentETCLaborUnits | num | O− | — | FS | S |
| anticip_start_date | WBS/AnticipatedStartDate | ts | O− | — | FS | S |
| anticip_end_date | WBS/AnticipatedFinishDate | ts | O− | — | FS | S |
| ev_compute_type | WBS/EarnedValueComputeType | enum | O− | — | FS | S |
| ev_etc_compute_type | WBS/EarnedValueETCComputeType | enum | O− | — | FS | S |
| guid | WBS/GUID | text(22) | T | — | `p6_guid` | S |
| tmpl_guid | — | text(22) | O− | — | FS | S |
| plan_open_state | — | text(255) | O− | — | FS | S |

`status_code` {`WS_Closed`} [S] (all 472 rows, XML `Inactive`), {`WS_Open`, `WS_Whatif`,
`WS_Planned`} [D].

### 6.6 `CALENDAR` (entity `calendar`) — typed table `schedule_p6_calendars`

| XER field | XML | Type | Tier | Use | Target | Seen |
|---|---|---|---|---|---|---|
| clndr_id | Calendar/ObjectId | id | R | E | `p6_calendar_id` | S |
| default_flag | Calendar/IsDefault | flag | T | — | `is_default` | S |
| clndr_name | Calendar/Name | name | T | — | `name` | S |
| proj_id | Calendar/ProjectObjectId | id | T | — | `p6_project_id` | S |
| base_clndr_id | Calendar/BaseCalendarObjectId | id | T | E | `base_p6_calendar_id` | S |
| last_chng_date | — | ts | O− | — | FS | S |
| clndr_type | Calendar/Type | enum | R | — | `calendar_type` | S |
| day_hr_cnt | Calendar/HoursPerDay | hours | T | — | `hours_per_day` | S |
| week_hr_cnt | Calendar/HoursPerWeek | hours | T | — | `hours_per_week` | S |
| month_hr_cnt | Calendar/HoursPerMonth | hours | T | — | `hours_per_month` | S |
| year_hr_cnt | Calendar/HoursPerYear | hours | T | — | `hours_per_year` | S |
| rsrc_private | Calendar/IsPersonal | flag | O− | — | FS | S |
| clndr_data | Calendar/StandardWorkWeek, Calendar/HolidayOrExceptions | blob | V + R | E | derived → `week`, `exceptions`, `data_sha256` | S |

`clndr_type` {`CA_Base`, `CA_Project`} [S], {`CA_Rsrc`} [D].

### 6.7 `PROJECT` (entity `project`) — typed table `schedule_p6_projects`

Typed (R/T):

| XER field | XML | Type | Tier | Use | Target | Seen |
|---|---|---|---|---|---|---|
| proj_id | Project/ObjectId | id | R | — | `p6_project_id` | S |
| proj_short_name | Project/Id | text(40) | R | — | `project_short_name` (Series identity check) | S |
| guid | Project/GUID | text(22) | T | — | `project_guid` | S |
| clndr_id | Project/ActivityDefaultCalendarObjectId | id | T | E | `default_p6_calendar_id` | S |
| last_recalc_date | Project/DataDate | ts | R | E Δ | `data_date` | S |
| plan_start_date | Project/PlannedStartDate | ts | T | — | `planned_start` | S |
| plan_end_date | Project/MustFinishByDate | ts | T | E | `must_finish_by` | S |
| scd_end_date | Project/ScheduledFinishDate | ts | T | Δ | `scheduled_finish` | S |
| critical_drtn_hr_cnt | Project/CriticalActivityFloatLimit | hours | T | E | `critical_float_hours` | S |
| critical_path_type | Project/CriticalActivityPathType | enum | T | — | `critical_path_type` | S |
| next_data_date | — | ts | T | — | `next_data_date` | S |
| (proj node `wbs_name`) | Project/Name | name | V | — | derived → `project_name` | S |

Optional, generic field store (O−, all [S]): `fy_start_month_num`, `rsrc_self_add_flag`,
`allow_complete_flag`, `rsrc_multi_assign_flag`, `checkout_flag`, `project_flag`,
`step_complete_flag`, `cost_qty_recalc_flag`, `batch_sum_flag`, `name_sep_char`,
`def_complete_pct_type`, `acct_id`, `orig_proj_id`, `source_proj_id`, `base_type_id`,
`sum_base_proj_id`, `task_code_base`, `task_code_step`, `priority_num`, `wbs_max_sum_level`,
`strgy_priority_num`, `last_checksum`, `def_cost_per_qty`, `add_date`, `last_tasksum_date`,
`fcst_start_date`, `def_duration_type`, `task_code_prefix`, `def_qty_type`, `add_by_name`
(personal), `web_local_root_path`, `proj_url`, `def_rate_type`, `add_act_remain_flag`,
`act_this_per_link_flag`, `def_task_type`, `act_pct_link_flag`, `task_code_prefix_flag`,
`def_rollup_dates_flag`, `use_project_baseline_flag`, `rem_target_link_flag`,
`reset_planned_flag`, `allow_neg_act_flag`, `sum_assign_level`, `last_fin_dates_id`,
`last_baseline_update_date`, `cr_external_key`, `apply_actuals_date`, `fintmpl_id`,
`last_schedule_date`, `matrix_id`, `last_level_date`, `hist_interval`, `hist_level`,
`control_updates_flag`, `rsrc_role_match_flag`, `px_enable_publication_flag`,
`publish_spread_assign_level`, `px_last_update_date`, `px_priority`, `schedule_type`,
`location_id`, `loaded_scope_level`, `export_flag`, `new_fin_dates_id`,
`baselines_to_export`, `baseline_names_to_export`, `sync_wbs_heir_flag`,
`sched_wbs_heir_type`, `wbs_heir_levels`, `base_proj_id`, `base_proj_id1`, `base_proj_id2`,
`close_period_flag`, `sum_refresh_date`, `trsrcsum_loaded`, `sumtask_loaded`. Their XML
elements, where 1:1, are listed in the catalogue module (for example `fy_start_month_num` =
`Project/FiscalYearStartMonth`, `add_date` = `Project/DateAdded`, `add_by_name` =
`Project/AddedBy`); the remaining rows carry `—` and are resolved by the XML slice.

### 6.8 `SCHEDOPTIONS` (entity `project`) — typed columns on `schedule_p6_projects`

| XER field | XML | Type | Tier | Use | Target | Seen |
|---|---|---|---|---|---|---|
| sched_calendar_on_relationship_lag | ScheduleOptions/RelationshipLagCalendar | enum | T | E | `lag_calendar` | S |
| sched_retained_logic | ScheduleOptions/OutOfSequenceScheduleType | flag | T | E | `retained_logic` | S |
| sched_progress_override | ScheduleOptions/OutOfSequenceScheduleType | flag | T | E | `progress_override` | S |
| sched_float_type | ScheduleOptions/ComputeTotalFloatType | enum | T | — | `float_type` | S |
| sched_open_critical_flag | ScheduleOptions/MakeOpenEndedActivitiesCritical | flag | T | — | `open_ends_critical` | S |
| sched_outer_depend_type | ScheduleOptions/IgnoreOtherProjectRelationships | enum | T | — | `external_dependencies` | S |
| sched_use_expect_end_flag | ScheduleOptions/UseExpectedFinishDates | flag | T | — | `use_expected_finish` | S |
| sched_lag_early_start_flag | ScheduleOptions/StartToStartLagCalculationType | flag | T | — | `ss_lag_from_early_start` | S |
| sched_use_project_end_date_for_float | ScheduleOptions/CalculateFloatBasedOnFinishDate | flag | T | — | `float_from_project_finish` | S |

Optional (O−, [S]): `schedoptions_id`, `proj_id` (derived check), `sched_setplantoforecast`,
`level_float_thrs_cnt`, `level_outer_assign_flag`, `level_outer_assign_priority`,
`level_over_alloc_pct`, `level_within_float_flag`, `level_keep_sched_date_flag`,
`level_all_rsrc_flag`, `enable_multiple_longest_path_calc`,
`limit_multiple_longest_path_calc`, `max_multiple_longest_path`,
`use_total_float_multiple_longest_paths`, `key_activity_for_multiple_longest_paths`,
`LevelPriorityList`.

Enumerations: `sched_calendar_on_relationship_lag` {`rcal_Predecessor`} [S],
{`rcal_Successor`, `rcal_24Hour`, `rcal_Project`} [D]; `sched_float_type` {`FT_FF`} [S];
`sched_outer_depend_type` {`SD_Both`} [S].

### 6.9 UDFs and activity codes (generic, entity of their owner)

| XER table.field | XML | Tier | Target | Seen |
|---|---|---|---|---|
| UDFTYPE.udf_type_id | UDFType/ObjectId | V | field definition (observed) | S |
| UDFTYPE.table_name | UDFType/SubjectArea | V | owner entity of `udf:<owner>:<label>` | S |
| UDFTYPE.udf_type_name | — | V | stored in observed record only | S |
| UDFTYPE.udf_type_label | UDFType/Title | V | `<label>` of the field key | S |
| UDFTYPE.logical_data_type | UDFType/DataType | V | value type: `FT_TEXT` [S]; `FT_INT`, `FT_FLOAT_2_DECIMALS`, `FT_MONEY`, `FT_START_DATE`, `FT_END_DATE`, `FT_STATICTYPE` [D] | S |
| UDFTYPE.super_flag | — | O− | FS (project entity) | S |
| UDFTYPE.indicator_expression | — | N | none (an executable expression; never evaluated or stored) | S |
| UDFTYPE.summary_indicator_expression | — | N | none (same) | S |
| UDFTYPE.export_flag | — | O− | FS (project entity) | S |
| UDFVALUE.udf_type_id | Activity/UDF/TypeObjectId | V | resolves the field key | S |
| UDFVALUE.fk_id | (parent element) | V | owner entity id | S |
| UDFVALUE.proj_id | — | V | check | S |
| UDFVALUE.udf_text / udf_number / udf_date / udf_code_id | Activity/UDF/TextValue (`DoubleValue`, `StartDateValue`, `CodeValue` [D]) | O+ | FS typed value | S (text) / D |
| ACTVTYPE.actv_code_type_id | ActivityCodeType/ObjectId | V | resolves `code:<label>` | S |
| ACTVTYPE.actv_code_type | ActivityCodeType/Name | V | `<label>` | S |
| ACTVTYPE.actv_code_type_scope | ActivityCodeType/Scope | O− | FS (project entity) | S |
| ACTVTYPE.actv_short_len, seq_num, proj_id, wbs_id, export_flag | ActivityCodeType/Length, SequenceNumber, ProjectObjectId | O− | FS | S |
| ACTVCODE.actv_code_id | ActivityCode/ObjectId | V | code value id | S |
| ACTVCODE.short_name | ActivityCode/CodeValue | O+ | FS value (text) | S |
| ACTVCODE.actv_code_name | ActivityCode/Description | O+ | FS value description | S |
| ACTVCODE.parent_actv_code_id | ActivityCode/ParentObjectId | O+ | FS value parent path | S |
| ACTVCODE.actv_code_type_id, seq_num, color, total_assignments | CodeTypeObjectId, SequenceNumber, Color | O− | FS | S |
| TASKACTV.task_id, actv_code_type_id, actv_code_id, proj_id | Activity/Code/TypeObjectId, ValueObjectId | V | FS row (activity, `code:<label>`) | S |
| UDFCODE.* | — | V | value labels for `FT_STATICTYPE` | D |

UDF and activity-code values are **captured by default** (they are what each project defines
for itself), subject to the caps of section 7.7.

### 6.10 Tables optional as a whole (every field O−)

| Table | Fields (all [S] unless stated) | Note |
|---|---|---|
| CURRTYPE | curr_id, decimal_digit_cnt, curr_symbol, decimal_symbol, digit_group_symbol, pos_curr_fmt_type, neg_curr_fmt_type, curr_type, curr_short_name, group_digit_cnt, base_exch_rate | XML `DisplayCurrency/Currency/*` (1 of 17) |
| FINTMPL | fintmpl_id, fintmpl_name, default_flag | XML `FinancialPeriodTemplate/*` |
| LOCATION | location_id, location_name, location_type, address_line1, address_line2, address_line3, city_name, municipality_name, state_name, state_code, country_name, country_code, postal_code, longitude, latitude | personal/address data; not in XML sample |
| NONWORK | nonwork_type_id, seq_num, nonwork_code, nonwork_type | not in XML sample |
| OBS | obs_id, parent_obs_id, guid, seq_num, obs_name, obs_descr | personal names; XML `OBS/*` |
| ROLES, ACCOUNT, PROJCOST, TASKMEMO, MEMOTYPE, TASKPROC, PCATTYPE, PCATVAL, PROJPCAT, RCATTYPE, RCATVAL, RSRCRCAT, UMEASURE, SHIFT, SHIFTPER, COSTTYPE, EXPTYPE | none listed [D] | entity `project`; catalogued in S7-1 from documentation without fields |

`RSRC` and `TASKRSRC` are tolerated tables (5.1), not rows of this table: their fields are
all O− and belong to entity `resource` and `assignment`. Documentation-only tables (the last
row above, and `RSRC` and `TASKRSRC` while v1 lists none of their fields) are catalogued
without fields: their fields are observed as unknown (`p6_unknown_field`, section 5.2) until a
documented field list is added with a catalogue version bump.

`ERMHDR` fields 2 (version) and 3 (export date) are stored on the project row
(`export_version`, `export_date`); its remaining fields (user, database, currency labels) are
**N**: never stored.

---

## 7. Optional-field registry, capture and the generic field store

### 7.1 Registry: a versioned in-repo catalogue plus a database observation record

The **available-field registry** is the union, served per Series, of:

1. the versioned catalogue (section 6): every typed, enumerated and unit-bearing field with
   its tier and default; and
2. the **observed-fields record** (section 7.4): every field actually seen in the Series'
   imports, including fields no catalogue knows.

Decision: the catalogue is **versioned code-data, not a database table**. Types, units,
enumerations and engine meanings must be reviewed, tested against synthetic fixtures and be
identical on every host; a database-held catalogue would let a write define how bytes are
interpreted, which is the free-form surface this design refuses (section 7.7). Fields the
catalogue lacks are still capturable — as bounded text — through the observation record, so
no field waits for a code change; a catalogue bump only upgrades such a field to a typed
interpretation (old values stay as captured; the type change applies from the next import or
re-capture).

### 7.2 Capture selection: per Series

The operator's choice of captured optional fields is a **per-Series** set, recorded as an
append-only chain of events in `schedule_p6_capture_events`; the current set is the last
event's set (default: the catalogue defaults, O+). With no selection the default is the O+
fields plus every UDF and activity-code key the file defines; more than 300 default keys are
sorted, truncated to the first 300 and raise `p6_capture_cap_reached`. Per Series, because each project defines
its own UDFs, codes and export options and a Series is one project's schedule over time: a
per-Principal set would apply one project's labels to another's, and a per-publication set
would make versions of one project incomparable. A selection applies from the **next** import
into that Series (and, with S7-6, to earlier imports by re-capture).

Selectable: every O field (catalogued) and every observed uncatalogued field. Not selectable:
N fields; R/T/V fields (always captured as typed columns). Selecting a field marked
`personal` requires the request flag `include_personal=true` and is audited as such.

### 7.3 Generic field store

`schedule_p6_field_values` (section 8.2): 1 row per captured value, keyed by
`(parser_run_id, entity_kind, entity_p6_id, field_key, ordinal)` with `principal_id`,
`publication_id`, `series_id`, `schedule_activity_id` (activities only, for cross-version
reads), and exactly 1 typed value column set: `value_text` (≤ 4,000), `value_number`
(numeric(28,6)), `value_ts`, `value_flag`, plus `code_path` (activity code parent chain from
the root value down to the value, ≤ 8 labels) and `record_line`. A static-type
(`FT_STATICTYPE`) UDF value is resolved through `UDFCODE.short_name`. Optional fields of a
table that is not an entity table attach to the `project` entity, with the row index (from 0)
as `ordinal`. `ordinal` > 0 only for multi-valued keys (several codes of one
type are not allowed by P6 [D]; ordinal stays for `TASKRSRC`-style repetition). Entity kinds:
`project`, `wbs`, `activity`, `relationship`, `calendar`, `resource`, `assignment`.

Indexes: `(parser_run_id, field_key, left(value_text, 256))`,
`(parser_run_id, field_key, value_number)`, `(parser_run_id, field_key, value_ts)` (filter and
sort within a publication; led by `parser_run_id`, section 8.4); `(principal_id, series_id,
schedule_activity_id, field_key)` (history across versions). Corrected in S7-2: the text index
keys the first 256 characters, because a whole 4,000-character value can exceed PostgreSQL's
B-tree entry limit (about 2,704 bytes) and the index would refuse a legal value (proven in
`tests/schema/test_schedule_p6_storage_migration.py`); a text filter rechecks the full value.

### 7.4 Observed-fields record

`schedule_p6_observed_fields`: per parser run, per (table, field): `field_key`, catalogued
or not, tier, present, records, non-empty count, min and max length, shape counts (integer,
decimal, date, flag, token, text), unknown-enum count, over-length count, captured or not.
**Stats only; never a value.** It lets `schedule_p6_fields.available` show, for a Series,
fields present in its exports but not captured.

### 7.5 Reads over captured fields

See section 10.5: `schedule_p6_activities.list` and `schedule_p6_field_values.list` filter
and sort on captured fields; the delta reports captured-field changes; a scenario snapshot
can carry selected captured fields inert (section 11.5).

### 7.6 Raw-source retention (**decided: retain every snapshot**) and re-capture (optional, undecided)

The admitted bytes are stored anyway (section 9.1), so re-parsing an already imported version
is possible. **Operator decision 2026-11-23: every snapshot is retained** (no retention rule
deletes one). Reasons: it is the only way a field selected later reaches earlier versions, and
the conformance script and the XML cross-check need the exact bytes. Cost: about the export
size per distinct file per Principal (the sample: 1.9 MB; PostgreSQL TOAST compresses text,
ratio not measured). At 50 projects × 52 weekly exports a year that is about 4.9 GB a year
uncompressed [A]. The placeholder quota (section 7.7, kept by the same decision) bounds it.

**Re-capture in plain words.** When a schedule is imported, MY-PA keeps an exact copy of the
file and saves only the fields you have chosen to capture. If you later decide a field matters
(say, a custom code your scheduler added), new imports will capture it, but the versions
imported before your choice will not have it. Re-capture is an optional extra that would go
back to those kept copies and read the newly chosen field out of them, so older versions gain
the field too, without changing anything already recorded. It is not needed for anything else
in this design, and whether to build it is still open.

**S7-6 (optional, undecided):** `schedule_p6_captures.request` (write) enqueues a re-capture of 1
publication under the Series' current selection: it re-parses the retained snapshot in the
contained child and **appends** field values under a new `capture_run_id`; typed rows and
earlier values are never changed; reads use the latest capture run per publication.
`schedule_p6_captures.list` (read). It needs 1 job table and 1 worker plane name
(`schedule_p6_capture`) — specified here, built only if the operator asks.

### 7.7 Limits that keep it safe

| Limit | Value |
|---|---|
| captured optional fields per Series | ≤ 300 (UDF and code keys included) |
| captured values per entity per publication | ≤ 300 |
| captured values per publication | ≤ 3,000,000 |
| `value_text` | ≤ 4,000 characters after NFC normalization; longer values are truncated **never**: the value is skipped with `p6_value_invalid` and counted |
| numbers / dates / flags | validated by the catalogue type; an uncatalogued field is always text |
| field key | `^(xer:[A-Z][A-Z0-9_]{0,31}\.[A-Za-z][A-Za-z0-9_]{0,63}|udf:[A-Z]{1,16}:.{1,120}|code:.{1,120})$` |
| filters per read | ≤ 3 field predicates, operators `eq`, `in` (≤ 50 values), `lt`, `le`, `gt`, `ge`, `prefix` (text, ≤ 100 characters); 1 sort key; no `OR`, no regular expression, no expression language, no SQL fragment |
| execution | nothing captured is evaluated: UDF indicator expressions are **N**; values are data only |
| snapshot bytes per Principal | ≤ 8 GiB (`rate_limited(STORAGE_QUOTA)`), operator-adjustable by setting; placeholder kept by operator decision 2026-11-23 |
| imports per Principal | ≤ 60 per hour, ≤ 500 per day (`rate_limited`); placeholders kept by the same decision |
| selection events per Series | ≤ 1,000 |

Reaching any capture cap stops all further capture for that publication's optional values
with the non-fatal `p6_capture_cap_reached` (typed data is unaffected).

---

## 8. Storage design and migration shape (S7-2)

### 8.1 Identifiers

New `IdKind` members (prefix-freeness to be checked against the head's set by
`tests/unit/test_identifiers.py`): `SCHEDULE_P6_SNAPSHOT` (`sp6n`), `SCHEDULE_P6_CAPTURE_EVENT`
(`sp6e`), and with S7-6 `SCHEDULE_P6_CAPTURE_RUN` (`sp6r`). Rows of the per-run tables are keyed
by `(parser_run_id, …)` and mint no identifier.

### 8.2 Tables (all `knowledge.`, all `principal_id NOT NULL`, all append-only/immutable after insert, foreign keys `RESTRICT`)

| Table | Key | Content |
|---|---|---|
| `schedule_p6_snapshots` | `snapshot_id`; unique `(principal_id, sha256)` | `format` (`p6_xer`, `p6_xml`), `size_bytes`, `sha256`, `content` (bytea), `created_at` |
| `schedule_p6_projects` | `parser_run_id` | the PROJECT and SCHEDOPTIONS typed columns (6.7, 6.8), `export_version`, `export_date`, `encoding`, `project_name`, `record_line` |
| `schedule_p6_wbs` | `(parser_run_id, p6_wbs_id)` | 6.5 typed columns, `depth`, `record_line` |
| `schedule_p6_activities` | `(parser_run_id, p6_task_id)`; unique `(parser_run_id, activity_id)` | 6.3 typed and derived columns, `schedule_activity_id` (Stable Activity, `sact_`), `record_line` |
| `schedule_p6_relationships` | `(parser_run_id, p6_relationship_id)` | 6.4 columns, `pred_activity_id`, `succ_activity_id` (Activity IDs; null predecessor when external), `is_external`, `record_line` |
| `schedule_p6_calendars` | `(parser_run_id, p6_calendar_id)` | 6.6 columns, `week` (canonical JSON: 7 lists Monday first of `[start, end]` minutes), `exceptions` (canonical JSON, sorted), `exception_count`, `data_sha256` (the SHA-256 over the canonical parsed week and exceptions, so `VIEW` display state does not change it), `record_line` |
| `schedule_p6_field_values` | section 7.3 | generic captured values |
| `schedule_p6_observed_fields` | `(parser_run_id, source_table, field_name)` | section 7.4 |
| `schedule_p6_capture_events` | `event_id`; unique `(series_id, sequence)` | `principal_id`, `series_id`, `sequence`, `field_keys` (sorted array ≤ 300), `include_personal`, `catalogue_version`, `provenance`, `created_at` |

Changes to existing tables (additive): `schedule_publications` gains `source_format`
(`pdf` default, `p6_xer`, `p6_xml`), `p6_snapshot_id`, `p6_workspace_id`,
`p6_workspace_path` (≤ 4,096 bytes, **never served**), `p6_workspace_version`,
`p6_capture_event_id` (the selection in force at admission), `accept_project_identity_change`;
`enrollment_id`, `source_object_id`, `source_version_id` become nullable under a CHECK
(`pdf` ⇒ all 3 set and no snapshot; `p6_*` ⇒ none of them and a snapshot). `schedule_parser_runs`
gains nothing but, where `pypdfium2_version`/`pdfium_version` are NOT NULL at the head, they
become nullable under a CHECK keyed on `profile_id` (`p6_full_v1` ⇒ set). `schedule_import_issues`
gains nullable `source_table` and `record_line`. The existing F1–F9 and G10 guards stay; the new
tables get the same set-once/append-only/terminal-immutability triggers.

Provenance: every stored P6 row carries `parser_run_id` (→ publication, snapshot SHA-256,
parser and profile and catalogue version), its source `record_line` (1-based physical line)
and, through the catalogue, its source table and field. Issues carry table, line and field.

### 8.3 Migration shape

One additive revision for S7-2 (tables, the column and CHECK changes, the triggers, the
audit-vocabulary restatement for the S7-4 names and purposes as frozen literals, the new
`IdKind` prefixes where the schema names them). Its `down_revision` is **the Alembic head of
main when S7-2 is opened**: at the basis that is `6418b57081c3`; the revision is rebased onto
whatever head main has then, and nothing here pins it. Lock windows: `ACCESS EXCLUSIVE` on
`schedule_publications`, `schedule_parser_runs`, `schedule_import_issues` and, for the
vocabulary restatement, `knowledge.audit_events` (the gateway pauses; S6-3 revision B
precedent); `lock_timeout = '10s'`. Downgrade refuses once any new table holds a row, any
publication is not `pdf`, or any audit row names a new capability or purpose. The S7-6 job
table and plane name, if built, are a separate later revision.

### 8.4 Scale [A]

Per publication (sample-sized): about 3,000 activities, 4,700 relationships, 470 WBS rows, 4
calendars, 900 code/UDF values, 300 observed-field rows: about 9,400 rows and one 2 MB
snapshot. At 50 projects × 52 versions a year: about 24 million rows and 5 GB of snapshots
a year, all retained (section 7.6). Every per-run table leads its primary key and indexes with `parser_run_id`, so a
publication's reads touch only its own index range, and history reads use
`(principal_id, series_id, schedule_activity_id)`. No declarative partitioning in this
version: the per-run keys keep lookups bounded and the row counts are well inside one
PostgreSQL table's comfortable range; partitioning by `series_id` hash is the documented next step if
the measured size calls for it (gate G-9); snapshots are never deleted (section 7.6). The S5
`RESTRICT` foreign keys apply: deleting a publication requires a retention design first.

---

## 9. Admission and worker (S7-3)

### 9.1 Admission

`schedule_publications.import_p6` (section 10):

1. Switches (section 10.2), then strict input validation (unknown key → `invalid_request`).
2. Outside any transaction, through the files-workspace store's contained read path (FW §3,
   §4: no symlink, no special file, no multiply-linked file): resolve `workspace_id` + `path`;
   the current `version` must equal `expected_version` (`conflict(EXPECTED_VERSION)`, the SafeDetail naming the request field); `size` must be
   ≤ 16 MiB before any byte is read (`unsupported(MAX_BYTES)`); read the bytes; their SHA-256
   must equal `expected_sha256` (`conflict(EXPECTED_SHA256)`); re-read the fingerprint after
   reading (`conflict(EXPECTED_VERSION)` if it moved). A key replay made after the file has changed therefore answers this conflict, not the stored result, because this step runs before step 4.
3. **Sniff** (the extension is ignored): `p6_xer` iff the bytes start with `ERMHDR\t` and the
   last non-empty line is `%E`; else `unsupported(SOURCE_FORMAT)`. (`p6_xml`, later: an
   `<?xml` declaration or none, then the root `APIBusinessObjects` in a namespace beginning
   `http://xmlns.oracle.com/Primavera/P6/`.) The recorded media type is the internal token
   `application/vnd.my-pa.p6-xer` (there is no registered type for XER [D]).
4. One transaction: idempotency-key replay (same key + same request digest → stored result;
   different digest → `conflict(IDEMPOTENCY_KEY)`); the Project is the caller's
   (`not_found(PROJECT_ID)`); the Series resolves exactly as S5/S6 (`series_id`,
   `series_name` resolve-or-create, or `series_auto` into an intake Series; until S7-4 extends the ADR-017 hook to read `schedule_p6_activities`, a P6 `series_auto` import always gets its own intake Series with decision `needs_series`); the request digest covers every input but the idempotency key (including `expected_version` and the workspace path); a Series holding
   any `pdf` publication refuses (`conflict(SERIES_FORMAT)`); **content idempotency** (which also answers for a failed publication of the same bytes: a retry needs a re-export or another Series): a
   publication of the same `sha256` already in that Series returns it with
   `already_present: true` (nothing new is written); the snapshot is inserted unless the
   Principal already holds that SHA-256; the publication is inserted (`source_format`,
   snapshot, workspace provenance, the Series' current capture event, role `update`); 1
   `schedule_jobs` row is enqueued.

#### 9.1.1 Why a snapshot (options compared)

| Option | New surface | Problem |
|---|---|---|
| A. Snapshot the workspace bytes at admission **(chosen)** | 1 table, 4 columns on publications | storage (section 7.6), which retention also needs |
| B. A new `SourceProviderKind` over the workspace | a provider kind (closed enum, migration), enrollment of workspace objects, worker fetch from a mutable path | the workspace root may not overlap a source root (T7-04); a workspace file is mutable, so the worker could read different bytes than the client named |
| C. Operator copies the file into a registered fixture source and enrolls it | none in code, but `.xer` media-type mapping in the fixture provider | operator-only, not MCP-triggered: contradicts decision 2 |

### 9.2 Roles and baselines

Every P6 import is role `update`. A baseline is created afterwards through the existing
ADR-017 operator capabilities (`schedule_baselines.approve` …); this import never carries
approval fields.

### 9.3 Worker

The `schedule` plane handler dispatches on `source_format`. For `p6_xer`: H1 plan; H2 load
the snapshot from the database (no provider call) and verify its SHA-256 and size; H3 pin
`document_sha256`/`document_size_bytes` (already known, re-asserted); H4 parse in the existing
contained child (stdin bytes, the profile and the capture selection; stdout one canonical
frame `cpm-workbench-p6-frame-v1`, capped at the existing 134,217,728 bytes); H5 parser run
(`profile_id = p6_xer_v1`, `profile_version`, catalogue version); H6 typed rows, field values,
observed fields and issues in batches of ≤ 1,000; H7 Stable Activities by exact `task_code`
in the Series; H8 finalize and the ADR-017 series-match hook. Status: `failed` on any fatal
issue; `review_required` on `p6_project_identity_changed`; else `complete` (non-fatal issues
listed, at most 10,000, with counts by code over the listed issues; the complete counts by code are in the frame and are re-derivable from the retained snapshot, and are not stored separately, section 5.5). `partial` is not used by `p6_xer_v1`. Budgets: the S5 handler budget and parse wall;
a measurement on a bounds-maximal synthetic file is an S7-3 acceptance item.

---

## 10. Capabilities, switch, policy (S7-4)

### 10.1 Names (appended to `Capability` after the head's last member)

| Name | Kind | Purpose | Notes |
|---|---|---|---|
| `schedule_publications.import_p6` | write, additive, client-usable | `schedule_p6_import` (new) | section 9 |
| `schedule_p6_fields.available` | read | `schedule_read` | registry for a Series (catalogue ∪ observed, with capture status) |
| `schedule_p6_fields.set_captured` | write, additive (appends an event) | `schedule_p6_configuration` (new) | set the Series' captured field set |
| `schedule_p6_activities.list` | read | `schedule_read` | typed activities + selected captured fields; filter/sort |
| `schedule_p6_relationships.list` | read | `schedule_read` | |
| `schedule_p6_calendars.list` | read | `schedule_read` | week and exceptions |
| `schedule_p6_field_values.list` | read | `schedule_read` | captured values of any entity kind |

7 capabilities and 2 purposes (at the basis: 299 → 306 capabilities, 70 → 72 purposes; S7-6
would add 2 more capabilities and no purpose). All join `_SCOPELESS` (they take no
`source_id`; ownership is the Principal partition plus the Project/Series/publication checks,
as the S6-3 plane). None is operator-only. The existing reads (`schedule_publications.read`,
`schedule_activities.list`, `schedule_activities.history`, `schedule_changes.list`) serve P6
publications too: `schedule_publications.read` gains an additive `p6` block (project identity,
export version, data date, settings, counts) for a P6 publication.

### 10.2 Switch

`MY_PA_SCHEDULE_P6_ENABLED` (`Settings.schedule_p6_enabled`, default `false`), effective only
with `MY_PA_SCHEDULE_ENABLED`; the restricted MCP DB-profile composition disables it. With it
off: the 7 names are absent from `capabilities.get`, the MCP tool list, remote profiles, the
façade and ChatLLM composition, each handler answers `unsupported` first, and the `schedule`
worker fails a `p6_*` publication's job closed as a transient `unavailable` (it never parses).
Scenario capabilities over P6 publications additionally need `MY_PA_SCHEDULE_SCENARIOS_ENABLED`
(unchanged).

### 10.3 Inputs (strict)

- `import_p6`: `project_id`; exactly one of `series_id`, `series_name`, `series_auto`;
  `workspace_id`; `path`; `expected_version` (`fv1_…`, required); `expected_sha256`
  (64 lowercase hex, required); `format` (`p6_xer`; `p6_xml` refused `unsupported(FORMAT)`
  until the XML slice); `accept_project_identity_change` (default false);
  `supersedes_publication_id?`; `idempotency_key`.
- `set_captured`: `series_id`; `field_keys` (≤ 300, each section 7.7 grammar, each available
  for the Series or in the catalogue); `include_personal` (default false);
  `expected_sequence` (compare-and-swap on the event chain, `conflict(SEQUENCE)`);
  `idempotency_key`.
- reads: `publication_id` (or `series_id` for `fields.available`), `page_size` 1–100,
  `cursor`, `fields?` (≤ 50 captured keys to include), `filter?` and `sort?` (section 7.7).

### 10.4 Outputs and disclosure

Every answer carries the S5 disclosure (scope, coverage, freshness, trust
`SOURCE_BOUND_DERIVED` with basis `p6_xer_v1` + catalogue version, truncation, classification
`PRIVATE_LOCAL`). Never served: the workspace path, raw bytes, `clndr_data`, ERMHDR user
fields, exception text. Captured `personal` fields are served only to a client holding a grant
on `schedule_p6_field_values.list` and only when selected with `include_personal`.

### 10.5 Read shapes

- **activity**: `{schedule_activity_id, activity_id, name, kind (task | start_milestone |
  finish_milestone), task_type,
  status, wbs_path, calendar_id, original_hours, remaining_hours, start, finish,
  early_start, early_finish, late_start, late_finish, planned_start, planned_finish,
  actual_start, actual_finish, total_float_hours, free_float_hours, constraint: {type, date},
  constraint2: {type, date}, physical_pct, duration_type, fields: {<key>: value}}`.
- **relationship**: `{pred_activity_id, succ_activity_id, type (FS|SS|FF|SF), lag_hours,
  is_external, fields}`.
- **calendar**: `{calendar_id, name, type, is_default, base_calendar_id, hours_per_day,
  week: [7 × intervals as HH:MM], exceptions: [{date, intervals}] (paged), fields}`.
- **field value**: `{entity_kind, entity_ref (Activity ID for activities, P6 id otherwise),
  field_key, value_type, value}`.
- **available field**: `{field_key, entity_kind, value_type, unit, tier, catalogued,
  default_capture, captured, personal, observed: {imports_seen, last_seen_publication_id,
  nonempty_ratio}}`.

### 10.6 Errors

Public codes only (`invalid_request`, `not_found`, `conflict`, `unsupported`, `denied`,
`rate_limited`, …) with new `SafeDetail` tokens: `WORKSPACE_ID`, `WORKSPACE_PATH`,
`EXPECTED_VERSION`, `EXPECTED_SHA256`, `SOURCE_FORMAT`, `FORMAT`, `SERIES_FORMAT`,
`FIELD_KEY`, `FIELD_FILTER`, `SEQUENCE`, `STORAGE_QUOTA` (if absent at the head). Worker
issue codes are the `p6_*` codes of section 5.5 (new `ScheduleIssueCode` members);
`last_error_code` stays one of the 11 public codes.

### 10.7 Policy, ChatLLM, remote, audit

- Every name is classified on every closed surface of T7-09; `schedule_p6_import` and
  `schedule_p6_configuration` join `_WRITE_PURPOSES`; both writes join
  `_IDEMPOTENT_REMOTE_CAPABILITIES` and `_CLIENT_BOUND_KEY_CAPABILITIES`.
- ChatLLM: a new data profile (the next free version at S7-4; `chatllm-data-v16` at the
  basis), all 7 `DATA_CONDITIONAL` under a new prerequisite `SCHEDULE_P6`; the 2 writes need
  `--write`. With the switch off the new profile desires exactly the previous profile's set.
- Remote: published only with the switches on, `writes_enabled` for the 2 writes, and a grant
  per name. The remote principal is the operator (single-Principal deployment), so the grant
  is the operator's admission decision for a client.
- Audit: every call is audited by `ApplicationService` as today; the import's audit carries
  publication id, SHA-256 and size (no path); `set_captured` carries the field-key count and
  `include_personal`.
- No restricted MCP database role gains a privilege.

**As built in S7-4a (corrections to this section and to 10.3/10.6, proven while implementing):**
(1) the audit event (`domain.audit.events.AuditEvent`) is closed by design: identifiers,
closed enums and bounded counts, no free-form field, and `audit_events` has no column for a
publication id, a digest or a size, so carrying them would need a migration this slice may
not make. Every P6 call is audited exactly as every other call (capability, purpose, outcome,
policy version; never the path). The publication id, SHA-256 and size are in the import's
answer and on the publication row; the selection's key count and `include_personal` are in
its answer and on the capture-event row, with its provenance pair. (2) `set_captured`'s
`idempotency_key` is required (and stamped client-bound remotely) but arbitrated by the
capture chain itself, since no request ledger admits the P6 names without a migration: a
retry of the same request by the same writer finds the event it appended at
`expected_sequence + 1` and replays it (`created: false`); any other request meets the
compare-and-swap (`conflict(sequence)`). A different request reusing a key whose request
already succeeded is therefore a new selection, not `conflict(idempotency_key)` (residual).
(3) The request field is `path`, so its `SafeDetail` is the existing `PATH`; there is no
`WORKSPACE_PATH`. (4) `schedule_changes.list` between P6 publications is the delta of section
11.4 (S7-4b) and answers `unsupported(source_format)` until then; a P6 origin of
`schedule_scenarios.create` likewise (section 11.5, S7-4b). (5) `series_auto` for P6 keeps the
S7-3 rule (its own intake Series, decision `needs_series`): extending the ADR-017 hook to
`schedule_p6_activities` is not a cheap correct extension in this slice.
(6) The S5 reads serve stored P6 publications under the Schedule switch alone (such data exists
only if the P6 switch was on at import); the seven P6 names need the P6 switch (10.2). (7) Read
shapes (10.5) carry these additive fields: calendar `exception_count` and
`exceptions_truncated`; field value `publication_id`, `ordinal` and `code_path`; the `p6`
block `source_format`, `capture_event_id`, `encoding` and `catalogue_version`. The default
page size of the P6 reads is 25. (8) Residuals: the import budget and storage quota are
checked then inserted without a lock, so concurrent imports of one Principal can overshoot by
about the number in flight (single operator Principal: accepted); an import-only remote grant
can tell whether a workspace path exists (`not_found` against `conflict(expected_version)`),
inherent to the snapshot design (9.1.1 option A). (9) A P6 scenario origin and a P6 delta are
untested at the plane level until S7-4b adds the scenario plane tests.

---

## 11. Many projects, many versions

### 11.1 Series identity

The Series is always the caller's explicit choice (or ADR-017 auto-matching, which matches by
exact Activity IDs and is recorded). The P6 identity (`project_short_name`, `project_guid`,
`p6_project_id`) is stored per publication and compared with the Series' earlier P6
complete publications (a `review_required` one never becomes the reference): if none shares the short name **or** the GUID, the publication becomes
`review_required` with `p6_project_identity_changed` unless the request set
`accept_project_identity_change`. A project renamed in P6 keeps its GUID; a project copied
into another database keeps its short name [A]; either keeps the Series.

### 11.2 Re-exports

- **Identical bytes** → content idempotency returns the existing publication (9.1 step 4).
- **Same schedule re-exported** (new export date, different `ERMHDR` user or version) →
  different bytes, a new publication; the delta to its predecessor is empty of activity
  changes and reports the header differences only.
- **Changed internal ids** (the project re-imported into another P6 database: new `task_id`,
  `wbs_id`, `clndr_id`, `task_pred_id`, possibly new GUIDs) → no effect on identity, which
  is `task_code` per Series; relationships match by Activity-ID pairs; calendars are compared
  by content (`data_sha256`), WBS by path.
- **Changed `ERMHDR` version** → recorded; the catalogue tiers decide (5.3).

### 11.3 Activity matching across versions

Exact `task_code` inside the Series, as ADR-016 decision 6: same code = same Stable Activity.
A code that disappears is `removed`; one that appears is `added`, or `reintroduced` if seen in
an earlier publication of the Series (existing S5 rule). **Renumbering** (an activity whose
code changed) is not merged: it is `removed` + `added`, and when the old and new rows share a
P6 GUID the delta adds an informational `renumber_candidate {from_activity_id,
to_activity_id}` — a hint, never a link, never a merged history. A duplicate code fails the
publication.

### 11.4 Delta `cpm-workbench-p6-delta-v1`

On demand between 2 caller-named publications of one Series (`to − from`), single pass,
never stored, algorithm version in every answer and cursor:

- activity kinds: `added`, `removed`, `reintroduced`, `renamed`, `wbs_moved`,
  `type_changed`, `status_changed`, `duration_changed` (original/remaining hours, numeric
  delta), `dates_changed` (start, finish, early, late, planned, actual: each with signed delta
  in calendar minutes), `float_changed` (total, free), `constraint_changed`, `calendar_changed`,
  `progress_changed`, `field_changed` (a captured field present in both publications' capture
  sets), plus `renumber_candidate`;
- relationship kinds: `relationship_added`, `relationship_removed`, `relationship_changed`
  (type or lag);
- calendar kinds: `calendar_week_changed`, `calendar_exceptions_changed` (count of dates
  added/removed);
- project: `data_date_changed`, `settings_changed`;
- a captured field present in only one publication's capture set is counted
  `fields_not_comparable`, never reported as a change.

**Memory.** The delta runs in the gateway request path and loads both accepted runs whole.
Each capture set comes from the selection in force or the run's distinct captured keys, never
from values, and only the values of keys in both capture sets that are not personal are read
(`field_key = ANY(:keys)` in the statement, partitioned by Principal and run): a personal key
(`fields_withheld`) or a key in 1 capture set only (`fields_not_comparable`) reads no value.
At the bounds (25,000 activities and 100,000 relationships per side, every field changed) the
measured peak RSS is about 0.6 GiB with no values and about 0.6 GiB with 3,000,000 values per
side whose capture sets share 1 key, against about 3.4 GiB before. Residual: a pair whose
capture sets share every comparable key still reads those values (about 3.4 GiB at the
3,000,000-per-publication cap), and every page recomputes the whole delta.

**N versions.** The delta stays pairwise; history across N publications is
`schedule_activities.history` (per Stable Activity, indexed by Series and activity) plus the
new captured-field history via `schedule_p6_field_values.list` with `schedule_activity_id`.
The ADR-017 derived current standard update and baselines apply unchanged; "latest vs
governing baseline" is the delta between the 2 publications they name.

The S5 delta `cpm-workbench-full-delta-v1` keeps serving PDF Series; `schedule_changes.list`
selects the algorithm by the Series' format.

### 11.5 Scenario hand-off

`schedule_scenarios.create` from a P6 publication (or an approved baseline naming one) builds
version 1 **without** client calendars or `minutes_per_source_unit`. The request may name
calendars (below); everything else is mapped:

| Content | From |
|---|---|
| `data_date` | `data_date` (minute exact) |
| calendars | by default every calendar an activity uses (≤ 32, else `invalid_request(CALENDARS)`), key `p6-<id>`; week intervals in minutes (Monday first); exceptions 2000-01-01..2099-12-31 only (others counted `exceptions_out_of_range`); ≤ 4 intervals per day else refused `invalid_request(CALENDAR)`. The request may add or substitute **any imported P6 calendar of the same Project** (named by `(publication_id, p6_calendar_id)` of any P6 publication of that Project the caller owns, including a project's own unique calendar), and the MY-PA standard calendar `my-pa-us-40h-v1` (section 11.6) is always available |
| `settings.default_calendar` | the request's `default_calendar` if given; else `p6-<default_p6_calendar_id>` when that calendar exists and parses; else **`my-pa-us-40h-v1`** (counted `default_calendar_standard`) |
| activity `calendar` | `p6-<clndr_id>`; when the activity's calendar is missing or unparseable (`p6_calendar_missing`), **`my-pa-us-40h-v1`** (counted `calendars_defaulted`); the request may remap any activity calendar to another available one |
| `settings.lag_calendar` | `rcal_Predecessor` → `predecessor`, `rcal_Successor` → `successor`, `rcal_24Hour` → `twenty_four_hour`, **`rcal_Project` → `calendar:p6-<default_p6_calendar_id>`** (the project default calendar, a fixed lag calendar: section 11.7), or `calendar:my-pa-us-40h-v1` when the project has no usable default calendar (counted `lag_calendar_standard`); the request may override |
| `settings.progress_policy` | `progress_override` Y → `progress_override`; `retained_logic` Y → `retained_logic`; **neither (P6 "actual dates") → `retained_logic` by default** (counted `progress_policy_defaulted`); the request may override. Why this default: retained logic is P6's own default, it never schedules remaining work of an out-of-sequence activity earlier than its logic allows (so it cannot understate a forecast), and P6 "actual dates" mode differs from it only for out-of-sequence progressed activities, which the engine already reports; the default is visible in the snapshot report and changeable by `settings.set` |
| `settings.must_finish_by`, threshold | `must_finish_by`; `critical_float_hours × 60` |
| activities | every activity; `kind`: `TT_Task` → `task`, `TT_Mile` → `start_milestone`, `TT_FinMile` → `finish_milestone` (faithful; section 11.7); `TT_LOE`/`TT_WBS` excluded with their relationships, counted |
| durations | `remaining_minutes = remaining_hours × 60`, `original_minutes = original_hours × 60`; a non-integral product is rounded half-even and counted `durations_quantized`; milestones 0 and 0 |
| constraints | `CS_MSOA` → SNET, `CS_MEOA` → FNET, `CS_MSOB` → SNLT, `CS_MEOB` → FNLT, `CS_MANDSTART` → MSO, `CS_MANDFIN` → MFO; `CS_MSO`, `CS_MEO`, `CS_ALAP` not representable: dropped and counted `constraints_unsupported`; a primary + secondary pair the engine's slot rule refuses keeps the primary and counts `constraints_dropped`. On a milestone the constraint is put on the milestone's own side (section 11.7): a finish-side constraint on a start milestone becomes its start-side twin (FNET → SNET, FNLT → SNLT, MFO → MSO) and vice versa, counted `milestone_constraints_converted`; the date is unchanged, so nothing is lost (a milestone has one date) |
| progress | `actual_start`/`actual_finish`; a start milestone takes `actual_start` (its actual finish is the same instant), a finish milestone `actual_finish`; `TK_Complete` without the needed actual date is refused `invalid_request(ROWS)` |
| relationships | every same-project relationship between included activities; `lag_minutes = lag_hours × 60`; external ones counted `external_relationships_dropped` |
| `published_reference` | publication id, Activity ID, the published hours (original, remaining) and the derived start/finish dates, and the request's `include_fields` (≤ 50 captured keys) as `fields`; P6's own early/late dates and floats stay on the publication (`schedule_p6_activities.list`, by Activity ID): the S7-0 content schema has no field for them (corrected in S7-4b, below) |

S7-4 obligations for this mapping: `published_reference.fields` is emitted as null (never
`{}`) when the request captures nothing, and a non-integral P6 number in a captured field
travels as text (the content admits no `float`).

Content schema: a document that uses none of the S7-0 additions (edged milestones, a
`calendar:` lag calendar, `published_reference.fields`) is a byte-identical
`schedule-scenario-content-v1` document; one that uses any of them is
`schedule-scenario-content-v2` (section 11.7). A P6 snapshot with any milestone or with
`rcal_Project` is therefore v2. The engine never reads captured fields: they are inert data.
The snapshot report lists every count above.

**PDF snapshots (S7-0 change):** the S6 snapshot input's `calendars` and `default_calendar`
become optional; when omitted, the MY-PA standard calendar is the only calendar and the
default (counted `default_calendar_standard`). A request that supplies calendars, as every
existing caller does, produces exactly the same content and hash as today. PDF rows keep kind
`milestone` (the PDF does not say which edge), so a PDF snapshot stays v1.

Because the P6 early/late dates and floats stay on the publication (`schedule_p6_activities.list`,
joined by the Activity ID each scenario activity's `published_reference` names; corrected in
S7-4b, below), the engine's result on a version 1
of an unmodified P6 publication can be compared with P6's own numbers: that comparison is the
S7-5 oracle (section 14), never a claim of equivalence (P6 options the engine lacks —
`sched_lag_early_start_flag`, expected finish, multiple float paths — are listed per
publication as `unmodelled_settings`).

**As built in S7-4b (decisions and corrections, proven while implementing; no migration, no new
capability, purpose or `SafeDetail`):**
(1) *Spec error, corrected in the table above:* the S7-0 content schema (v1 and v2, section 11.7)
fixes `published_reference` to the publication id, the Activity ID, 2 duration cells, 2 date cells
and (v2) `fields`; it has no early/late date or float, and adding them would be a third content
schema. A P6 snapshot carries the published hours (a value not exact at 3 decimals is an
`ambiguous` cell) and the derived start/finish dates; the oracle (S7-5) reads P6's dates and
floats from the publication by Activity ID.
(2) The P6 options travel in one additive object `p6` of `schedule_scenarios.create`
(`calendars` as `{publication_id, calendar_id}` references, `default_calendar`, `calendar_map`,
`include_fields`); a P6 origin requires it (`{}` for every default) and refuses the PDF fields,
and a PDF origin refuses it, each `invalid_request(source_format)`. The lag calendar and progress
policy are not create inputs: the client overrides them with `settings.set` on version 2. The
tool's payload digest moves (accepted under ADR-023).
(3) `invalid_request(CALENDARS)` is built as `invalid_request(calendar)` and `invalid_request(ROWS)`
as the S6 rows refusal `conflict(from_publication_id)` (no new `SafeDetail`); an include key not in
the origin's capture set, or personal, is `invalid_request(field_key)`.
(4) A referenced calendar keyed `p6-<id>` substitutes the origin's calendar of that id, any other
is added; both are in the content even when no activity uses them. `calendar_map` remaps an
activity's calendar key after the missing-calendar default.
(5) Persistence: the stored version keeps the six S6 snapshot columns (activities, milestones,
durations quantized and out of range, original and remaining missing). Every 11.5 count, the
`unmodelled_settings` (`ss_lag_from_early_start`, `use_expected_finish`) and
`standard_calendar_horizon_exceeded` are the create answer's `p6_snapshot_report`, recomputed for
a replay (immutable rows, same request). `default_calendar_standard` is not a column: it is that
report's count for P6, the boolean `default_calendar_standard` of a PDF snapshot's create answer,
and visible in the stored content (the default calendar is `my-pa-us-40h-v1`).
(6) `standard_calendar_horizon_exceeded` is in the snapshot report (the latest of the published
finish and late finish dates and `must_finish_by`) and in `schedule_cpm_runs.read` (the latest of
the run's project finish and `must_finish_by`).
(7) Mapping details the table leaves open: `TT_Rsrc` is a task (counted
`resource_dependent_tasks`); an absent or unknown lag-calendar token is `predecessor` (P6's
default); a constraint without a date or off the engine's axis is `constraints_unsupported`; a
complete activity with remaining hours is given 0 (`complete_remaining_zeroed`); a WBS path over 32
labels is null (`wbs_paths_dropped`); seconds are truncated (`instants_truncated`); a relationship
to an excluded activity is `relationships_excluded`; a repeated (code) value travels by its first
ordinal; a non-integral lag is rounded half-even (`lags_quantized`).
(8) Delta: a publication's capture set is its admission's selection, or under the defaults the
default-captured keys plus the UDF and code keys the run captured; a personal key is never
compared (`fields_withheld`); relationships match by their Activity-ID pair and an external one is
counted, not compared; calendars match by P6 id, else by a name unique among the unmatched
(`calendars_unmatched`), and an activity's `calendar_changed` follows the calendar's content
digest; `settings_changed` covers the settings of the `p6` block plus the ERMHDR
`export_version`/`export_date` (11.2). The change-kind enum lists both algorithms' kinds; a kind
the Series' algorithm does not report is `invalid_request(change_kind)` (the payload digests of
`schedule_changes.list` and `schedule_baselines.compare` move, accepted under ADR-023). The cursor
binds the algorithm, so one algorithm's cursor never continues the other's; a cross-format pair
stays `unsupported(source_format)`.

### 11.6 MY-PA standard calendar `my-pa-us-40h-v1`

The default calendar wherever a source gives none (PDF rows, a missing or unparseable P6
calendar, a P6 project without a usable default calendar, `rcal_Project` without one). It is a
versioned constant of the scenario domain (S7-0), generated by rule, never by a year list:

| Item | Value |
|---|---|
| key | `my-pa-us-40h-v1` (a change of any rule below is a new key, `-v2`; existing content keeps the old calendar's materialized data) |
| week | Monday to Friday, 1 interval `[480, 960]` (08:00–16:00, 8 hours, 40 a week); Saturday and Sunday non-working |
| interval override | the constant `STANDARD_WORKDAY = (480, 960)`; a snapshot request may pass `standard_workday` (`HH:MM`–`HH:MM`, 1..1,440 minutes, at most 2 intervals) to materialize a variant, keyed `my-pa-us-40h-v1-<start><end>` (for example `my-pa-us-40h-v1-07001530`) so 2 variants never share a key; each interval adds 8 characters to the key and a calendar key is at most 32 characters, so a variant has at most 2 intervals (3 or 4 intervals pass the engine's per-day limit of 4 but are refused with a `ValueError` when the variant key is formed) |
| holidays | the US federal holidays: New Year's Day (1 Jan), Martin Luther King Jr. Day (3rd Monday of January), Presidents Day (3rd Monday of February), Memorial Day (last Monday of May), Juneteenth (19 June, **from 2021**, the year it became a federal holiday), Independence Day (4 July), Labor Day (1st Monday of September), Columbus / Indigenous Peoples' Day (2nd Monday of October), Veterans Day (11 November), Thanksgiving (4th Thursday of November), Christmas Day (25 December) |
| observed rule | a fixed-date holiday on a Saturday is observed the Friday before, on a Sunday the Monday after; the observed day is the non-working exception (the weekend day is non-working anyway). New Year's Day on a Saturday is observed on 31 December of the previous year (for example 1 Jan 2022 → Fri 31 Dec 2021) |
| window | the rules are defined for every year the engine supports; an observed date outside 2000-01-01..2099-12-31 is dropped (1 Jan 2000 is a Saturday: its observed day, 31 Dec 1999, is outside the window) |
| materialization | the engine limits a calendar to 1,000 exceptions and a version to 2,000 (S6 §2.10), and 100 years of 11 holidays exceed that, so a snapshot materializes the holidays of the years `data_date.year − 2` to `data_date.year + 20` (clipped to the window; ≤ 253 dates); a scenario that runs past that horizon reports `standard_calendar_horizon_exceeded` and the client may extend it with `calendar.exception.put`. **S7-0 provides the domain function only** (`standard_calendar_horizon_exceeded`, tested); surfacing it in a run or snapshot report is deferred to S7-4 |
| holidays as exceptions | each observed date is an exception with no interval (non-working) |

Planned tests (S7-0): each fixed-date holiday on a Saturday, a Sunday and a weekday (for
example Independence Day 2099 is a Saturday → Fri 3 Jul; Christmas 2021 is a Saturday → Fri
24 Dec; Veterans Day 2000 is a Saturday → Fri 10 Nov); New Year on a Saturday crossing into the
previous year (2022 → 31 Dec 2021) and at the window edge (2000 → dropped); each nth-weekday
rule including "last Monday of May" in a May with 5 Mondays and with 4; leap years (2000, a
century leap year; 2024; 2096) for every February and nth-weekday rule; Juneteenth absent in
2020 and present (observed Fri 18 Jun) in 2021; the 2099 year complete; the count per year (10
before 2021, 11 from 2021, less any observed day pushed outside the window); the horizon
clipping; the generator is pure and deterministic (same input, same canonical bytes).

### 11.7 Scenario engine amendment (S7-0): start and finish milestones, `my-pa-cpm-v2`

This amends ADR-017 (recorded in ADR-023, "Amendment to ADR-017") and the S6 contract
sections 2.3, 2.4, 2.8, 3.3, 3.5 and 3.6.

**Kinds.** `kind` ∈ `task` | `milestone` | `start_milestone` | `finish_milestone`. `milestone`
keeps its v1 meaning exactly (used by PDF snapshots, whose rows do not say which edge). Both
edged kinds have `original_minutes = remaining_minutes = 0` and 1 date (start = finish).

**Scheduling semantics (`my-pa-cpm-v2`, additions to S6 §3 only).**

| | start milestone | finish milestone |
|---|---|---|
| its date is | the start: the beginning of a working period | the finish: the end of a working period |
| forward | `x` as S6 §3.5 step 3, then `ES = EF = next_work(C_j, x)` | `x` as S6 §3.5 step 3, then `ES = EF = max(D, prev_end(C_j, x))` |
| backward | `y` as S6 §3.6 step 5, then `LS = LF = next_work(C_j, y)` | `y` as S6 §3.6 step 5, then `LS = LF = prev_end(C_j, y)` |
| relationships | every type is allowed; because start = finish, FS/SS from it use its one date, and FS/SS/FF/SF bounds onto it bound that date (`retreat(C_j, t, 0) = t`), exactly as today | same |
| constraints | start side only: SNET, SNLT, MSO (a finish-side one is refused `constraint_conflict` in a change set; the snapshot converts it, section 11.5) | finish side only: FNET, FNLT, MFO |
| mandatory pin | applied at `at`, unsnapped (as v1) | same |
| progress | `actual_start` = its date (`actual_finish` must be null or equal) | `actual_finish` = its date (`actual_start` must be null or equal) |

Snapping moves a milestone only across non-working time (`W(C_j, x, next_work(C_j, x)) = 0`
and `W(C_j, prev_end(C_j, x), x) = 0`), so floats in working minutes are unchanged; what changes
is the wall-clock date, which matters for the dates shown and for a `twenty_four_hour` or fixed
lag calendar. Example: a task finishing Monday 16:00 drives, by FS 0, a start milestone at
Tuesday 08:00 and a finish milestone at Monday 16:00 (under v1 both would read Monday 16:00).

**Gap-end rule (backward pass through a finish milestone).** A finish milestone `k` that is
not complete and not a kept mandatory pin stands for the whole non-working gap it was snapped
back across. So in S6 §3.6 a predecessor's bound through `k` uses `next_work(C_k, LF_k)` (the
end of that gap) in place of `LS_k`/`LF_k`; `k`'s own reported dates are unchanged. Without it
a lag on another calendar could give the predecessor negative float. Example (lag calendar
`twenty_four_hour`, `std` Monday–Friday 08:00–16:00, data date Monday 00:00): task A (8 h)
finishes Monday 16:00 and drives finish milestone F by FS +120; the lag ends Monday 18:00, so F
is at Monday 16:00 (forward and backward). Through `LF_F` A's bound would be Monday 14:00 (A
late 01-01 14:00 / 01-04 14:00, TF −120); with the rule it is `next_work(Monday 16:00)` =
Tuesday 08:00 less 120 clock minutes = Tuesday 06:00, whose previous working end is Monday
16:00: A late 01-04 08:00 / 01-04 16:00, TF 0, FF 0, critical path [A, F]. The rule is 1
counted calendar call per such milestone that has a predecessor (S6 §3.11). A start milestone
needs no such rule: it only snaps later, so its late date is never before the anchor its
predecessor drives. The rule does not touch bounds onto tasks: an FF or SF lag (or a lead)
ending in non-working time before a task's finish behaves as in v1, which can show negative
float there on either engine.

**Finish milestone late date and the data date.** The backward pass has no data-date floor
(literal formula `LS = LF = prev_end(C_j, y)`), so a finish milestone whose early date is
floored to a non-working data date can have a late date before both its early date and the
data date: in the E3 golden `data_date_only` (data date Monday 00:00) F reads early Monday
00:00 and late Friday 01-01 16:00, with TF 0 (no working minute lies between).

**Fixed lag calendar.** `settings.lag_calendar` also accepts `calendar:<key>` (an existing
calendar of the version): every relationship's lag is measured on that calendar. It carries
P6 `rcal_Project`. It cannot be removed while named (`calendar_in_use`).

**Versioning and compatibility.**

- A new engine id **`my-pa-cpm-v2`** is needed: v2 output differs from v1 on edged milestones
  and fixed lag calendars, and a run is stored and replayed by `(version, engine version)`.
- `my-pa-cpm-v1` is frozen: its code path, outputs and output hashes stay **byte-identical**
  for every existing and future v1 document.
- The engine is chosen by the content schema: a `schedule-scenario-content-v1` document runs
  on v1, a v2 document on v2. `schedule_cpm_runs.create` takes no new input. A v1 document can
  never be run on v2 and vice versa, so existing scenarios never change results.
- Content: v2 = v1 + the 2 kinds + `calendar:<key>` lag calendars + optional
  `published_reference.fields`; hash `sha256(b"schedule-scenario-content-v2\n" + canonical)`.
  A change set that introduces a v2 feature into a v1 parent produces a v2 child; a change
  set that removes every v2 feature produces a v1 child again (the schema follows the content,
  so the v1 hash is reproducible).
- Change set grammar: `activity.add`/`activity.edit` accept the 2 kinds; `settings.set`
  accepts `calendar:<key>`; `op_error` gains no member (wrong-side constraints use
  `constraint_conflict`).
- Client-asserted outputs: `OutputEngine` gains `my-pa-cpm-v2`.

**Effect on existing S6 pieces.**

| Piece | Effect |
|---|---|
| persistence | **no migration**: content is stored as validated JSON; `schedule_cpm_runs.engine_version` is already checked by the pattern `^my-pa-cpm-v[1-9][0-9]{0,3}$` (`a_cpm_run_engine_version_is_known`, `src/my_pa/infrastructure/persistence/tables.py`), which admits `my-pa-cpm-v2`; `OutputEngine` values carry no database CHECK at the basis (S7-0 re-verifies both) |
| stored versions, runs, outputs | unchanged; nothing is rewritten |
| snapshots | PDF snapshots unchanged (kind `milestone`, v1) unless calendars are omitted, which only adds the standard calendar; P6 snapshots are new |
| change sets | additive grammar; existing change sets replay identically |
| contract hashes | v1 content, change-set and output hashes unchanged; v2 has its own prefix |
| read shapes | `kind` gains 2 values; run reads carry `engine_version` already |
| ChatLLM profile | the capability set does not change, so no profile bump; tool input schemas that enumerate `kind` or `lag_calendar` widen additively (if a pinned tool-schema snapshot exists at the head, it moves in the same PR) |
| modules touched | `src/my_pa/domain/schedule/scenario/` (`model.py`, `canonical.py`, `changeset.py`, `snapshot.py`, `cpm.py`, `outputs.py`), `src/my_pa/application/schedule_scenarios.py` (engine selection, `_RUN_BASIS`), `src/my_pa/infrastructure/persistence/schedule_cpm_lease.py` (run lookup by the chosen engine), the S6 command docstrings and tool descriptions |

**Recommendation: a separate slice S7-0, its own PR, first.** It changes merged S6 modules
(above), not the new `p6` package, and its key proof — every v1 golden byte-identical — is
cleanest reviewed alone. It needs **no migration**, so it does not enter the migration lane
(the repository's one-at-a-time migration lane) and can merge before, after or between
migration PRs; only S7-2 takes a place in that lane.

**S7-0 tests and acceptance.**

- E1 every S6 golden network (G1…, S1…) and every recorded v1 output hash is unchanged
  (byte-for-byte), run on the v1 path after the change.
- E2 the v2 code path on every v1 golden with `milestone` and no fixed lag calendar yields the
  same activity results as v1 (differential test; only `engine_version` differs).
- E3 new goldens: start milestone after FS from a 16:00 finish → next working start; finish
  milestone → 16:00; both under a `twenty_four_hour` and a fixed lag calendar (dates differ as
  specified); a finish milestone whose only bound is the data date at a non-working instant →
  the data date; backward-pass late dates of both kinds; floats equal to the unsnapped working
  minutes; a pinned milestone unsnapped.
- E4 change-set refusals: finish-side constraint on a start milestone and the reverse
  (`constraint_conflict`); removal of a calendar named as fixed lag calendar
  (`calendar_in_use`).
- E5 content schema: a v1 document hashes as before; adding then removing an edged milestone
  returns to the identical v1 hash; v2 canonical form and hash golden.
- E6 standard calendar tests of section 11.6.
- E7 PDF snapshot without calendars → standard calendar; with calendars → identical bytes and
  hash to the pre-S7-0 golden.
- E8 a run on a v1 version is stored and replayed as `my-pa-cpm-v1`, a run on a v2 version as
  `my-pa-cpm-v2`; `schedule_cpm_runs.read` reports each.

Prove-red for S7-0: make the v2 start-milestone snap a no-op (E3 must fail); route a v1
document to the v2 path with a deliberately different tie-break (E1/E2 must fail); drop the
observed-day Saturday rule (E6 must fail); include Juneteenth before 2021 (E6 must fail).

---

## 12. Conformance script

`ops/schedule/p6_export_profile.py` (S7-1): a read-only, **stats-only** profiler for any XER
(and, from the XML slice, XML) file, driven by the same catalogue module and parser front end
as the worker (one definition, no drift). It never writes to the database, the network or the
file it reads, and its output never contains a value: only table and field names (names that
fail the field-name pattern are reported by position), counts, lengths, shape histograms and,
for enumerated fields, unknown tokens matching `[A-Za-z]{1,8}_[A-Za-z0-9_]{1,40}` (P6
vocabulary; anything else is counted, not printed). It prints no version string: the export
version appears only as `export_version_tested` (true or false). An unexpected error prints
the error's type name only and exits 1.

Report: per table (catalogued or unknown; records), per field (tier, present, non-empty, min
and max length, shapes, over-length against the catalogue bound, unknown enum tokens), and a
verdict:

| Verdict | Condition | Exit |
|---|---|---|
| **fail** | encoding or structure invalid; a required table or required field missing; any over-length value in a typed (R/T) column; any unknown enum value in an R field; a cap of 5.4 exceeded | 1 |
| **pass with findings** | unknown tables or fields; unknown enum values in T/O fields; untested export version | 0 |
| **pass** | none of the above | 0 |
| usage error | | 2 |

Uses:

1. **Catalogue completeness gate (before S7-2 opens).** Run by the operator, or by a worker
   the operator authorizes, against the operator's sample XER on the NAS. Required: verdict
   not `fail`, **and** zero unknown fields and tables (the sample defines what P6 26.x writes
   by default; an unknown one means the catalogue is incomplete and S7-1 is reopened). Only
   the stats report leaves the NAS.
2. **Each new project's first export**, before its first import: the operator runs it; `fail`
   stops the import; findings are reviewed (the worker records the same findings in the
   observed-fields record anyway).
3. **S7-5 real-corpus run**: every export the operator nominates, as the evaluation.

Synthetic fixtures (S7-1) cover: a minimal valid XER; a file with no optional tables; an extra
unknown table; an extra unknown field in `TASK`; a missing tolerated field; a missing required
field; a different `ERMHDR` version (`8.4`, `19.12`, `26.4`); UDFs present (text, number,
date, code) and absent; activity codes with a parent chain; a cross-project relationship;
Windows-1252 bytes; UTF-8 bytes; invalid bytes; CRLF and LF; a width mismatch; each cap at
its bound and one past it; a calendar with a `00:00` day end; a calendar without
`DaysOfWeek`; an activity naming a missing calendar (non-fatal `p6_calendar_missing`); start
and finish milestones with constraints on either side; `rcal_Project` and neither progress flag
set; a duplicate Activity ID; a multi-project file. Every fixture is generated by a
committed script from synthetic names (no real project, person, code, calendar or UDF label).

---

## 13. Trust boundary

1. **Input is hostile.** The bytes come from a client-named file. Caps (5.4) apply before and
   during parsing; every count is checked before allocation; the parser is a single pass over
   lines with bounded state.
2. **Pure, stdlib-only parser, no native code**, in `src/my_pa/domain/schedule/p6/` (bound by
   `test_cpm_full_parser_scope.py`: no logging, printing or file access). It runs in the
   existing contained child: no network (audit hook refuses sockets), no environment, no
   inherited descriptors, rlimits, wall clock, one canonical JSON frame re-rendered and bound
   to the digest by the parent.
3. **XML (later):** stdlib `xml.parsers.expat` with a handler that refuses any DOCTYPE,
   entity declaration, external entity or processing instruction other than the XML
   declaration (`SetParamEntityParsing(XML_PARAM_ENTITY_PARSING_NEVER)`, `StartDoctypeDeclHandler`
   raising), element depth ≤ 32, attribute count ≤ 16, text node ≤ 65,536 characters, file ≤
   64 MiB. CDATA is accepted as text. The security guard of T7-12 is narrowed to admit exactly
   `xml.parsers.expat` in that 1 module.
4. **Fail closed** on every fatal code of 5.5; nothing is guessed (no fuzzy matching, no
   repaired references, no inferred units).
5. **Encoding**: strict decoding only (3.2).
6. **No evaluation**: indicator expressions and any expression-like field are never evaluated
   or stored (N).
7. **Disclosure**: section 10.4.

Residuals: CPU and memory per admission are bounded by caps and the child's rlimits (the
Linux address-space cap remains CI-verified, S5 U2-12); a client with the grant can fill its
Principal's quota (section 7.7 bounds it); a crafted file can make a schedule look plausible
but false — the trust label says what it is: what that file published. The P6 delta (11.4)
reads only its comparable keys' values, so a pair whose capture sets overlap at the value cap
still holds about 3.4 GiB in the gateway while it computes.

---

## 14. Slices, acceptance tests, prove-red plan

Order: S7-0 → S7-1 → (gate G-1) → S7-2 → S7-3 → S7-4 → S7-5; S7-6 optional (undecided)
after S7-4. One work package at a time. S7-0 and S7-1 need no migration; S7-2 is the only
slice that enters the migration lane. S7-0 is a separate PR on merged S6 modules (section
11.7); it comes first because S7-4's scenario hand-off depends on it, but S7-1 does not, so
S7-1 may start once S7-0 has merged or in parallel with it if the operator allows 2 PRs.

### S7-0 — scenario engine amendment (no migration)

Deliverables, acceptance E1–E8 and its prove-red plan: section 11.7; the standard calendar
and its tests: section 11.6. S7-4's scenario hand-off (D6) depends on it.

### S7-1 — pure parser, catalogue and conformance script (no migration, no IO in the domain)

Deliverables: `src/my_pa/domain/schedule/p6/` (catalogue module, ERMHDR/table reader,
calendar-blob parser, typed mapping, issue model, canonical frame), the synthetic fixture
generator and fixtures, `ops/schedule/p6_export_profile.py`, tests.

Acceptance:
- A1 every fixture of section 12 produces its expected verdict, issues (code, table, line,
  field) and canonical frame hash (goldens).
- A2 the catalogue module renders row-for-row equal to section 6 (contract ↔ code lockstep).
- A3 calendar: week 1 = Sunday; `d|N` from 1899-12-30; `00:00` end = 1,440; exceptions without
  intervals are holidays; property test: render → parse → equal.
- A4 encoding: cp1252, UTF-8, invalid → expected outcome; CRLF/LF equivalent frames.
- A5 caps: each bound passes at the limit and fails one past it.
- A6 determinism: same bytes → identical frame bytes across runs and hosts.
- A7 the profiler emits no value: a test plants unique marker strings in every field of a
  fixture and asserts none appears in its output.
- A8 domain guards (`test_cpm_full_parser_scope.py`) cover the new package.

### Gate G-1 — catalogue completeness on the sample (operator or authorized worker)

The script from S7-1 runs read-only against the sample XER on the NAS; the stats report shows
verdict not `fail` and zero unknown tables or fields. Its output (stats only) is attached to
the S7-2 PR. S7-2 is not opened before this.

### S7-2 — schema and persistence

Deliverables: the revision of 8.3, tables, triggers, repository methods (Principal-bound),
unit of work, `IdKind` members.

Acceptance:
- B1 upgrade on an empty and on a populated S6 scratch database; downgrade refusals of 8.3.
- B2 immutability triggers refuse update/delete on every new table.
- B3 the publications CHECK refuses a `p6_*` row with enrollment columns and a `pdf` row
  without them.
- B4 a round trip of every fixture's frame into the tables and back equals the frame.
- B5 partition guards cover every new table; a cross-Principal read returns `not_found`.
- B6 a 25,000-activity / 100,000-relationship synthetic publication persists within the S5
  handler budget on the scratch cluster (measured, recorded).

### S7-3 — admission and worker

Acceptance:
- C1 admission refusals: version moved, SHA-256 mismatch, too large, not XER, PDF Series,
  foreign Project, idempotency conflict; replay; `already_present` for identical bytes.
- C2 the snapshot is deduplicated per Principal; the workspace path is stored and never
  served.
- C3 worker: fixture → `complete` / `failed` / `review_required` as specified; Stable
  Activities by `task_code`; a renumbered fixture yields `removed` + `added` +
  `renumber_candidate`.
- C4 the contained child is used (the parent never imports the parser module); a frame
  forged for another digest is refused.
- C5 switch off: the job fails closed transient and nothing parses.

### S7-4 — capabilities, switch, policy, ChatLLM, field registry and reads

Acceptance:
- D1 every closure test (policy, pins, ChatLLM coverage, remote publication, audit
  vocabulary) passes with the 7 names; the switch-off composition equals the previous
  profile's set.
- D2 `set_captured` CAS, caps, `include_personal`; a selection applies from the next import.
- D3 an uncatalogued field observed in import 1, selected, is captured as text in import 2
  (no code change).
- D4 filters/sorts: each operator; caps; refusal of anything else.
- D5 delta: every change kind on synthetic pairs; N-version history; `fields_not_comparable`.
- D6 scenario snapshot from a P6 publication: every mapping row of 11.5 (including calendar
  choice across the Project's P6 publications, the standard-calendar defaults, `rcal_Project`
  → fixed lag calendar, the progress-policy default, faithful start/finish milestones and the
  milestone constraint conversion), counts, v1/v2 content.
- D7 remote: published only with switch, writes-enabled and grant; the PDF import is still
  never published.
- D8 the S5 reads (`get_publication`, `get_publication_detail`, `list_publications`) serve P6
  publications (they have no enrollment): format-aware reads, tested on a complete P6
  publication; the 7.7 storage quota and rate limits; the gateway composition; the `series_auto`
  decision for P6 (refuse, or extend the ADR-017 hook to read `schedule_p6_activities` and
  exclude PDF Series); the publication mapping: `data_date` is the project's data date,
  `run_date` the ERMHDR export date, the title the project name when at most 300 characters,
  else null.

### S7-5 — operator procedure and real-corpus evaluation

Deliverables: runbook section, pre-deploy checks for the revision, the evaluation procedure.
Acceptance (operator-run, stats only): the conformance script and a scratch-database import
of every nominated export; per export: verdict, issue counts by code, activity/relationship
counts equal to the file's, delta counts between consecutive versions, and the engine-vs-P6
oracle (early dates and total float of an unmodified version 1: share of activities equal, the
distribution of differences in minutes, and `unmodelled_settings`).

### S7-6 — re-capture (optional)

Section 7.6; acceptance: a field selected after import 1 appears for import 1 after
re-capture; earlier values and typed rows unchanged.

### Prove-red plan

Each guard is proven red by **one** isolated mutation (a green run means redundancy or a
masked test, never "covered"), recorded in the PR:

| Guard | Mutation that must turn it red |
|---|---|
| required-field check | delete `remain_drtn_hr_cnt` from a fixture's `%F` |
| width check | drop one value from a `%R` line |
| encoding | insert byte `0x81` (undefined in cp1252) into a non-UTF-8 fixture |
| caps | raise one cap constant by 1 in the test only and feed the limit+1 fixture |
| duplicate Activity ID | duplicate a `task_code` |
| unknown field non-fatal | make the unknown-field branch raise |
| profiler emits no value | print one value in the profiler |
| snapshot SHA-256 check | skip the comparison in admission |
| content idempotency | remove the `(series, sha256)` lookup |
| immutability trigger | drop the trigger in a test database |
| partition | remove `principal_id` from one repository query |
| switch | serve one name with the switch off |
| remote publication | add the PDF import to the client-usable set |
| filter grammar | admit an unknown operator |
| catalogue lockstep | change one tier in the module |

---

## 15. Operator gates (no agent performs these)

| Gate | What |
|---|---|
| G-1 | run the conformance script on the sample (or authorize a worker to), before S7-2 |
| G-2 | approve each PR merge per AGENTS.md |
| G-3 | apply the S7-2 revision (after its pre-deploy checks), in a quiet window |
| G-4 | deploy the build with `MY_PA_SCHEDULE_P6_ENABLED` absent |
| G-5 | set `MY_PA_SCHEDULE_P6_ENABLED=true` (with `MY_PA_SCHEDULE_ENABLED`) on the gateway and the schedule worker |
| G-6 | grants per client for the 7 names, `set-client-writes`, ChatLLM `profile-apply` at the new profile |
| G-7 | the S7-5 real-corpus run and its acceptance |
| G-8 | personal-field capture (`include_personal`) for any Series |
| G-9 | partitioning, if measured size calls for it; and any later change to the placeholder quota or rates (retention itself is decided: every snapshot is kept) |
| G-10 | build S7-6 or not (undecided) |

---

## 16. `p6_xml_v1` (contract level)

Purpose: cross-check an XER publication against the XML export of the same project and time.
Input: a second import with `format = p6_xml` naming `cross_check_of_publication_id`; parsed
under 13.3; stored only as a cross-check result (counts and mismatching field keys per entity,
no second set of typed rows), matched by `ObjectId` per section 4 with the expected
differences (project WBS node, unused calendars, OBS, floats absent, CDATA, `0`/`1` flags,
seconds in dates, braced GUIDs) excluded. File ≤ 64 MiB (the sample XML is 16.3 MB).
Optional fields present only in XML (for example `Activity/AtCompletionDuration`,
`Project/ActivityDefaultDurationType`) enter the same registry with `xml:` keys in a later
catalogue version. Detailed in its own slice.

---

## 17. Operator decisions on the open questions (2026-11-23) and what remains open

| # | Question | Decision |
|---|---|---|
| 1 | Multi-project exports | **Decided:** not common; refused with the typed fatal issue `p6_multiple_projects` |
| 2 | Mixed formats | **Decided:** a project with PDF history starts a new Series for XER; no cross-format delta (`conflict(SERIES_FORMAT)`) |
| 3 | Quota and rate | **Decided:** keep the placeholders (8 GiB of snapshots; 60 imports an hour, 500 a day, per Principal) |
| 4 | Retention | **Decided:** retain every snapshot (section 7.6) |
| 5 | Personal fields | **Decided:** captured only on explicit selection with `include_personal` (gate G-8), as designed |
| 6 | Calendars, `rcal_Project`, progress policy | **Decided:** a request may choose any imported P6 calendar of the Project; the default where a source has none is the MY-PA standard calendar `my-pa-us-40h-v1` (section 11.6); `rcal_Project` maps to a fixed lag calendar on the project default calendar (standard calendar if none, section 11.7); progress policy defaults to `retained_logic` when neither P6 flag is set (recommended and justified in 11.5), overridable |
| 7 | Start/finish milestones | **Decided:** represented faithfully; engine amendment S7-0, `my-pa-cpm-v2` (section 11.7); the earlier collapse design is withdrawn |
| 8 | S7-6 re-capture | **Open:** optional and undecided; explained in plain words in section 7.6 |

## 18. What could not be determined

- How other P6 versions and export options differ from the sample (every [A]); the generic P6
  documentation was not available to this design beyond the author's knowledge ([D]).
- The XML for UDF types other than text, for resources and for activity codes with parents.
- TOAST compression of XER snapshots; parse time and memory on the NAS for a bounds-maximal
  file.
- Whether the base calendar of a project calendar ever carries data the project calendar
  lacks (all sample project calendars are self-contained).
- The process that composes the files-workspace store for a remote call (the gateway composes
  it at the basis; the remote MCP process serves byte routes): S7-3 confirms the read path.
