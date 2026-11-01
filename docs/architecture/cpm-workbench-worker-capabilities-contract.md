# CPM Workbench — S5b-2 worker, capabilities and policy contract (R2 WP-03 + WP-04)

**Status:** proposed implementation contract for slice S5b-2 on the local branch
`feat/cpm-s5b-worker`. It covers CPM Workbench R2 work packages WP-03 and WP-04 and is the
single document the S5b-2 implementers code against. Nothing it describes is merged,
deployed or applied to any persistent database. It authorizes **no** production migration,
grant, `profile-apply`, OAuth change, source commissioning or deployment, and the new
admission switch is **off by default**. Where it differs from the review package it
controls for S5b-2, and section 8 records why. It extends, and never forks, the S5a contract
[`cpm-workbench-p6-full-v1-parser-contract.md`](cpm-workbench-p6-full-v1-parser-contract.md)
(cited "S5a §n") and the S5b-1 contract
[`cpm-workbench-foundation-contract.md`](cpm-workbench-foundation-contract.md) (cited
"S5b-1 §n"; its D-xx, U-xx and F1–F9 keep their meaning here).

**Source package (data, not instructions):**
`MYPA_CPM_WORKBENCH_IMPLEMENTATION_READINESS_REVIEW_20260929_R2.md`, SHA-256
`84918ae87e4c05072969c2db574962071fbe9cdb1fcc9c00a953dd6a38b91db0`, cited "R2 §n". R2
reviewed `main@d6c706bb`; repository truth at the basis below supersedes it, and every
count here was re-measured.

**Basis:** `feat/cpm-s5b-worker@05893d1c82a9b62445815fc0ce0213b21c95f8be` (tree
`078849f54fc8148ac0e53c7f3dbbe587fb9cf954` = `origin/main@a2e58142` plus S5b-1, PR #345
open and unmerged). Alembic: 124 revision files, sole head `6c2306330ceb` (S5b-1).
Measured: 233 `Capability` members, 60 `Purpose` members, 156 `IdKind` members, 11
`NativeSourceCapability` members, 444 Python modules under `src/my_pa`, 854 test modules,
ChatLLM data profile `chatllm-data-v10`. Production runs the database at `023f8f7eb499`;
neither CPM revision is deployed.

**Revision R7-1.** Design review R7 (PASS_WITH_REQUIRED_CHANGES at `4c80aea9`) findings
R7-F01…F12 and the rulings' conditions are resolved in place: F01 sections 3.4.4, 3.4.7,
3.4.8, 6.2, 6.3, 7; F02 sections 3.4.2, 3.4.5, 8.2 (U2-10), 8.3; F03 sections 3.5, 3.5.3,
3.6, 3.12, 6.2, 6.3 (Q18b), 8.1 (E-12); F04 sections 3.3.1, 3.3.2, 4.1, 4.3, 5, 6.2; F05
sections 3.3.2, 3.4.2, 3.4.6, 4.1; F06 section 6.3 (Q14, Q20a/b, Q27, Q38); F07 section
3.13.5; F08 sections 3.8, 6.2; F09 sections 3.1, 8.3; F10 section 3.7; F11 sections 3.9,
3.10; F12 sections 3.4.3, 3.4.8; ruling O-1 sections 6.2, 8.1 (E-02); ruling O-2 section 5
(I7-A condition).

**Revision R7-2.** R7 re-review 1 (PASS_WITH_REQUIRED_CHANGES at `60b80b04`): N1 (the R7-1
parsed-run shortcut could not finalize — a parsed run stores no title, Data Date or Run
Date) sections 3.3.1, 3.3.2, 4.1, 4.3, 5, 6.2, 6.3 (Q61), 8.2 (U2-11); N2 (fail-closed
`running`-run rule) sections 3.3.1, 6.2; F01 practicality ruling sections 3.4.4, 3.4.8, 6.2,
6.3, 7, 8.2 (U2-12), 8.3.

**Conventions.** Paths are written in full from the repository root; files that do not
exist yet are written as code spans, never as Markdown links (CI link check); no
`path:line` citation is used (citation guard). Counts are digits (spelled-count guard).
"Schedule reads" means the 6 read capabilities of section 3.5; "import" means
`schedule_publications.import`. Identifiers in examples are synthetic.

---

## 1. Scope

### 1.1 In scope

| R2 | S5b-2 deliverable | Section |
|---|---|---|
| §25, §24 | `schedule` worker plane on all 4 surfaces, handler `process_schedule_publication`, lease-checked transactions over the S5b-1 repository methods, 240 s budget | 3.2, 3.3 |
| S5a U-05, U-12, §35 | parser in an rlimit-bounded child process, bytes by pipe, bounded canonical output | 3.4 |
| §9, §10, §31.1, §32 | 7 Schedule capabilities (1 operator-only write, 6 reads), strict commands, cursor, disclosure | 3.5–3.9 |
| §29, §30 | on-demand delta `cpm-workbench-full-delta-v1`, explicit baseline semantics | 3.10, 3.11 |
| §31.2–§31.5 | policy closure on every closed surface, ChatLLM `chatllm-data-v11`, remote boundary, compact façade | 3.12, 3.13 |
| S5b-1 D-01/D-02/D-03 | migration #2: audit capability/purpose vocabulary, heartbeat plane CHECK | 3.14 |
| brief | default-OFF switch `MY_PA_SCHEDULE_ENABLED` | 3.1 |
| S5b-1 U-03, RR1-I01 | read visibility rules | 3.9 |
| §40 | observability and the never-emit list | 3.15 |
| S5b-1 §9.3 | runbook section and read-only pre-deploy checks (written, never run here) | 3.16 |
| WP-04 | assurance docs, §45 crosswalk, ADR note, runbook, index, shard weights | 5, 6, 7 |

### 1.2 Explicitly out of scope

Deployment or anything in production; live grants, `profile-apply`, OAuth or write-gate
changes; any real schedule PDF; XER/XML (lineage WP-05B stays unimplemented);
supplemental/narrative/adjustment evidence (R2 §§26–28); frontend UI or BFF behaviour
(only the mechanically regenerated web contract fixture of section 3.13.6); AI; any change
to S5a parser behaviour, profile constants or goldens (the parser is only invoked from the
isolated child); cross-domain links (R2 §33); a `context.prepare` schedule plane; any edit
of the S5b-1 revision `6c2306330ceb`.

### 1.3 What "done" means

One additive revision on `6c2306330ceb` that is the sole head; the 7 Schedule
capabilities and 2 purposes are classified on every surface of section 3.12; with the
switch off nothing schedule-related is served, published, planned or runnable; with it on
(tests only) the worker parses synthetic PDFs in the contained child, the reads serve
exactly the rules of section 3.9; every section 6.3 guard is proved red; FAST, database
(by marker), migration tiers, ruff, ruff format, mypy (current and floor-pinned), the
shard partition proof, doc and count guards and the web checks are green.

---

## 2. Repository reauthentication and divergence table

| # | R2 claim | Repository truth at the basis | Decision |
|---|---|---|---|
| T2-01 | 178 `Capability`, 47 `Purpose` → 185/49 (§31.1) | `src/my_pa/domain/identity/operation.py`: 233 members (enum `Capability`); `src/my_pa/domain/identity/purpose.py`: 60 | 233 → 240, 60 → 62; members appended last in declaration order (section 4.1) |
| T2-02 | `operation.py` maps/sets (§31.2) | 4 closed structures: `_OPERATOR_ONLY` (also holds 9 `NativeSourceCapability`), `_PERMITTED_PURPOSES` (unmapped = empty = denied), `_WRITE_CAPABILITIES`, `_ADDITIVE_WRITE_CAPABILITIES`; `is_destructive_capability` = write minus additive | import: operator-only, write, additive, `{schedule_import}`; 6 reads: `{schedule_read}` only |
| T2-03 | `decision.py` `_SCOPELESS` (§31.2) | `src/my_pa/domain/policy/decision.py`: `evaluate` checks authenticated → may hold authority → operator-only → purpose → scope; `_SCOPELESS` requires an **empty** requested scope; an unlisted capability with an empty scope is silently `scope_not_authorized`; the S4 Program reads are in `_SCOPELESS` | 6 reads join `_SCOPELESS`; import does not (it names an enrollment) |
| T2-04 | authorization requested scope (§31.2) | `src/my_pa/application/authorization.py` `_requested_scope` is a `match` with **no default arm** (an omitted command returns `None` and `authorize` fails `internal_error`); `SearchKnowledge`/`ReadKnowledge` use `_scope_of_enrollment(enrollment_id, enrollments)` (only the Principal's own enrollments; foreign = empty = denied) | 6 read commands join the empty-scope arm; `ImportSchedulePublication` gets its own arm `_scope_of_enrollment(command.enrollment_id, enrollments)` |
| T2-05 | remote `_WRITE_PURPOSES` (§31.2) | `src/my_pa/adapters/mcp/remote.py`: `is_remote_write = bool(permitted_purposes & _WRITE_PURPOSES)`; `remote_tool_names` skips every operator-only name unless `compact_operator_publication` and the name is in `_REMOTE_OPERATOR_IDENTITY_CAPABILITIES ∪ {sources.enroll}`, or the `remote.operator` profile and the name is one of the 4 identity-correction names | `Purpose.SCHEDULE_IMPORT` joins `_WRITE_PURPOSES`; neither operator exception set changes |
| T2-06 | `_IDEMPOTENT_REMOTE_CAPABILITIES` (§31.4) | `src/my_pa/adapters/remote_request.py` (not `remote.py`): writes whose key the server stamps; `REMOTE_OWNED_PAYLOAD_FIELDS` refuses a caller key | import is **not** added; no remote caller can stamp or send its key |
| T2-07 | ChatLLM policy, `chatllm-data-v3` → v4, targets 159/93 → 165/99 (§31.3) | `src/my_pa/domain/identity/chatllm_capability_policy.py`: `CHATLLM_DATA_PROFILE_VERSION = "chatllm-data-v10"`; 6 classes; `_build_policy` raises on an unclassified member; switch-gated planes are `DATA_CONDITIONAL` with an explicit name set and a `ChatLLMCompositionPrerequisite` (`LINEAGE`, `PROGRAM_REPORTING`); `DATA_REQUIRED` means always composed (comment on `record_events.list`) | next version `chatllm-data-v11`; 6 reads `DATA_CONDITIONAL` under new prerequisite `SCHEDULE` (E-02); import `CONTROL_PLANE_EXCLUDED` |
| T2-08 | desired targets | `tests/contract/test_chatllm_data_profile_diff.py`: full planes 164, default planes 98; `tests/contract/test_lineage_client_exposure_policy.py`: full+lineage 191, full+lineage+program 198, default+both 130, 256 compositions (8 plane flags) | re-measured section 3.13.1: 164/98 unchanged with the switch off; 170 (full+schedule), 204 (full+all 3 switches), 136 (default+all 3), 512 compositions |
| T2-09 | gateway family → feature (§31.2) | `src/my_pa/adapters/mcp/chatllm_gateway.py` `_FEATURE_BY_FAMILY` keys on the text before the first dot; unknown → `other`; `facade_kind`: operator-only → `operator`, remote write → `write`, else `read` | 4 families → `schedule` |
| T2-10 | catalog (§31.5) | `src/my_pa/adapters/mcp/tools.py` `TOOLS` derives name, summary (first docstring line), schema and annotations from the `Command` union; `idempotent_hint = is_remote_idempotent` (server-replay set or lineage writes) | summaries in section 3.5; annotations follow derivation (import: `read_only=false`, `destructive=false`, `idempotent=false`) |
| T2-11 | façade e2e tests | S3.1 Part D: `tests/contract/test_lineage_s31_facade_catalog.py` (FAST), `tests/integration/test_lineage_s31_compact_facade.py` (database) | same pair for schedule (section 6) |
| T2-12 | generic adapters (§31.5) | `src/my_pa/adapters/normalization.py` `_BUILDERS` (unknown key = `TypeError` = `invalid_request`); HTTP routes into `_HANDLERS`; CLI and stdio MCP derive from the same | 7 builders, 7 handlers, no schedule route/server/program |
| T2-13 | web fixtures "if guard requires" | `tests/contract/test_bff_success_decoder_parity.py::test_committed_python_fixtures_match_live_model_dumps` compares the committed `web/src/lib/api/decode/fixtures/python/success.json` (its `capabilities.get` manifest is built from **all** `_HANDLERS`) with a live dump | **mechanically required**: regenerated in I7-B (7 manifest rows; worker planes unchanged, section 3.2) |
| T2-14 | audit vocabulary (§18.8.4) | `knowledge.audit_events.capability_is_known` last restated by `023f8f7eb499` (244 literals = 233 + 11 native); `purpose_is_known` last restated by `c5260943d933` (60); `tables.py` `_CURRENT_AUDIT_CAPABILITIES` derives from both enums | migration #2 restates both from byte-copied BEFORE texts: 244 → 251, 60 → 62 |
| T2-15 | worker surfaces (§25) | `worker_heartbeats.worker_plane_is_known` = `plane IN ('capture', 'enrollment', 'reenrichment')` (last frozen by `b727e870d45e`, literal in `tables.py`); `src/my_pa/infrastructure/persistence/worker_health.py` admits those 3 for heartbeats and `{capture, enrollment}` for health; `apps/worker.py` `_JOB_PLANES` = enrollment, capture, `_PLANES` adds `reenrichment`; `ApplicationService._capabilities_get` fallback and `SqlAlchemyUnitOfWork` worker-health read enumerate `("capture", "enrollment")`; FAST guard `tests/architecture/test_cpm_workbench_foundation_scope.py::test_schedule_plane_is_not_runnable_before_its_handler` asserts `schedule` is absent from each | all 4 move together in I7-B; the guard is converted honestly (section 3.2) |
| T2-16 | `run_worker`, lease 300 s (§25) | `src/my_pa/infrastructure/jobs/worker.py`: `DEFAULT_LEASE_SECONDS = 300`, `MAX_LEASE_SECONDS = 3600`; `JobHandler = (Engine, LeasedJob, owner) -> None`; `JobExecutionError(code)` → `release_job` (retry `min(300, 2^(n-1))` s, `failed` + dead-letter at `max_attempts` = 3); `LeaseLostError` → `lost`; any other exception → `internal_error`; `complete_job` only after the handler returns. `hold_lease` = `FOR UPDATE` and `lease_expires_at > now()`; no lease extension exists | reused unchanged; `--lease-seconds < 300` refused for the schedule plane (section 3.2) |
| T2-17 | provider read (§9.4) | `src/my_pa/infrastructure/jobs/extraction.py`: `RegisteredSourceProviders(connection).for_source(source_id)` on an `AUTOCOMMIT` connection; `None` or constructor `ValueError` → `JobExecutionError(UNAVAILABLE)`; `metadata()` then `fetch(max_bytes=…)`; `VersionChangedError`, `TraversalDeniedError` (absent and refused are indistinguishable), `ProviderError`; `SourceObjectContent.version_id` is the version observed at read time; `is_truncated` reported | same pattern; pinned version rechecked after both calls (section 3.3) |
| T2-18 | switch convention | `src/my_pa/bootstrap/settings.py`: `lineage_enabled`, `program_reporting_enabled` (env `MY_PA_<FIELD>`), default `False`; `ApplicationService.available_capabilities` subtracts the switch set; every handler asks `_lineage_plane()` first (`unsupported`), because `invoke` routes into `_HANDLERS` without consulting `available_capabilities`; the gateway builds the Program read factory only when the switch is on **and** no restricted `data_engine` is injected | same shape: `schedule_enabled`, capability absent **and** handler `unsupported` (section 3.1) |
| T2-19 | `TrustLevel`, disclosure (§32.8) | `src/my_pa/domain/common/provenance.py` `TrustLevel.SOURCE_BOUND_DERIVED`; `src/my_pa/contracts/v1/disclosure.py`: `Scope`, `Coverage` (state + eligible/processed/quarantined/unsupported), `SourceReference(source_id, source_object_id, version_id)`, `Truncation(is_truncated, reason, next_cursor)`; partial coverage states and truncation require `partial_result=True`; list handlers use reason `page_size_reached` | new builder `schedule_disclosure` (section 3.8) |
| T2-20 | search cursor (§32.1) | `src/my_pa/domain/search/query.py`: base64url compact JSON `{b,k,r,t}`, `MAX_CURSOR_CHARACTERS = 512`, `CURSOR_TTL_SECONDS = 300`, `RESULT_ORDER` bound into the digest; unreadable, expired and rebound are one `SearchCursorError` → `conflict(cursor)` | `ScheduleCursor` on the same rules (section 3.7) |
| T2-21 | `MAX_PAGE_SIZE=100` | `MAX_PAGE_SIZE = 100` in `src/my_pa/domain/search/query.py`; per-plane copies elsewhere | `MAX_SCHEDULE_PAGE_SIZE = 100`, default 25 |
| T2-22 | PDFium usage, isolation | `pypdfium2` imported only by `infrastructure/goodnotes` and `infrastructure/schedule/pdf.py` (`tests/architecture/test_scope_and_hygiene.py`); precedent child process: `src/my_pa/adapters/mcp_interaction_capture.py` `ProcessRowBuilder` (`subprocess` of `sys.executable -c`, child lowers `RLIMIT_AS`; "macOS does not support lowering `RLIMIT_AS`" — measured here too: `ValueError`); `infrastructure/schedule` may not log, print, or touch files/env (`tests/architecture/test_cpm_full_parser_scope.py`) | child entry lives in `infrastructure/jobs` (section 3.4); the parser packages stay untouched |
| T2-23 | safe error codes | `ErrorCode` 11 public codes (`schedule_jobs.last_error_code` CHECK); `ScheduleIssueCode` 23 codes; `SafeDetail` closed (`src/my_pa/application/errors.py`): `PROJECT_ID`, `ENROLLMENT_ID`, `SOURCE_OBJECT_ID`, `SOURCE_VERSION_ID`, `IDEMPOTENCY_KEY`, `PAGE_SIZE`, `CURSOR`, `STATUS`, `MAX_BYTES` exist; no series/publication/activity/row-type/date-range tokens | 14 SafeDetail members added (section 4.5) |
| T2-24 | generic remote read re-check | `invoke` does not consult the grant set (G1-RD-008); lineage reads call `require_read_grant(authorization.capability_grants, capability)` (`src/my_pa/application/lineage_visibility.py`) | every schedule read calls it after the switch gate |
| T2-25 | MCP database profiles | `src/my_pa/contracts/mcp_database_profiles.py`: closed read/write ceilings and opt-in sets; no grant on CPM tables to `my_pa_mcp_ro`/`rw` (S5b-1 §4.11) | schedule names join **no** ceiling and **no** opt-in set; a restricted composition never composes the Schedule factory |
| T2-26 | `ApplicationService` composition (§8.5) | R2 "no new feature flag"; brief requires one | E-01 |
| T2-27 | complete/partial Data Date | S5a V11/V13: page 1 must carry a valid Data Date and every page must agree, else `UNSUPPORTED_LAYOUT`/`PAGE_METADATA_MISMATCH` (failed/review_required) | every `complete`/`partial` publication has a non-NULL `data_date`; reads may rely on it (asserted, section 3.9) |

---

## 3. Decisions

### 3.1 Admission switch

| Item | Decision |
|---|---|
| Name | `Settings.schedule_enabled: bool = False`, env `MY_PA_SCHEDULE_ENABLED` (field docstring in the lineage style: default off, what it gates, operator gate to enable) |
| Dependency | none (no other switch required); refused by nothing |
| Gateway | `src/my_pa/bootstrap/gateway.py` builds `schedule_unit_of_work = lambda: SqlAlchemyScheduleUnitOfWork(work_engine)` **only when** `settings.schedule_enabled and data_engine is None` (a restricted MCP-profile composition never composes it: its role holds no CPM privilege, T2-25); passes `schedule_enabled=settings.schedule_enabled`, `schedule_unit_of_work=…` to `ApplicationService`, and `schedule_enabled=<same conjunction>` to `SqlAlchemyUnitOfWork` (worker-health read, section 3.2) |
| Capability admission | `ApplicationService.available_capabilities`: `if not (self._schedule_enabled and self._schedule_unit_of_work is not None): served -= _SCHEDULE_CAPABILITIES` (7) → absent from `capabilities.get`, readiness, MCP tool list, remote profile, façade and ChatLLM composition |
| Handler refusal | each of the 7 handlers first calls `self._schedule_plane()` → `UnsupportedError()` when off (before any read, write or replay; precedent `_lineage_plane`) |
| Worker plane | `apps/worker.py run --plane schedule` with the switch off: prints `plane schedule disabled` and returns exit code 2 before building an engine, claiming, or writing a heartbeat |
| ChatLLM | prerequisite `SCHEDULE` holds iff `ChatLLMCompositionPlanes.schedule` (new field, default `False`); `apps/cli/remote_mcp.py` `_planes_from_settings` sets `schedule=settings.schedule_enabled` |
| Remote | nothing schedule-related exists remotely while off (derived from `available_capabilities`) |
| Off → on / on → off | changes no row; `schedule_jobs` queued while off are not claimed until a schedule worker runs with the switch on |
| Tests | FAST `test_schedule_switch_defaults_off`; database `test_switch_off_withholds_and_refuses_every_schedule_capability` (parametrized over 7: absent from `available_capabilities` and `capabilities.get`, handler `unsupported`, no schedule row written — the authorization audit row `invoke` writes before any handler is expected and asserted, R7-F09 — MCP tool list lacks it); FAST `test_worker_refuses_the_schedule_plane_while_disabled`; FAST planner tests of section 3.13.1 |

### 3.2 Worker plane — the 4 surfaces move together (I7-B)

| # | Surface | Change |
|---|---|---|
| 1 | `apps/worker.py` | `_JOB_PLANES["schedule"] = (SCHEDULE_JOBS, process_schedule_publication)`; `_PLANES` follows; docstring gains the schedule bullet (PDF parsed only by the isolated child; generic PDF extraction stays `unsupported`); `_run` refuses (exit 2, message only) the schedule plane when the switch is off or `--lease-seconds < 300` |
| 2 | heartbeat CHECK | migration #2 restates `worker_plane_is_known` to `plane IN ('capture', 'enrollment', 'reenrichment', 'schedule')`; `tables.py` literal identical; `TABLES_SHA256` re-pinned |
| 3 | `worker_health.py` | heartbeat allowlist `{capture, enrollment, reenrichment, schedule}`; health map adds `"schedule": SCHEDULE_JOBS` |
| 4 | application/UoW | `SqlAlchemyUnitOfWork(…, schedule_enabled: bool = False)`; its worker-health read enumerates `("capture", "enrollment")` plus `"schedule"` iff `schedule_enabled`; `ApplicationService._capabilities_get` fallback enumerates the same plus `"schedule"` iff the Schedule factory is composed and the switch is on |

Consequence: with the switch off, `capabilities.get` reports exactly the 2 planes it reports
today (the committed web fixture's `worker_planes` is unchanged) and never reads
`schedule_jobs` (a profile role could not); with it on, the schedule plane's backlog,
dead-letter count and heartbeat are reported and degrade readiness exactly as the other
planes do.

**Guard conversion (honest, I7-B).** `test_schedule_plane_is_not_runnable_before_its_handler`
is replaced in place by `test_schedule_plane_is_runnable_on_all_four_surfaces`, asserting each
surface separately with a message naming it: (1) `_JOB_PLANES["schedule"]` is
`(SCHEDULE_JOBS, process_schedule_publication)` and `"schedule" in _PLANES`; (2) the head
CHECK text names `'schedule'`; (3) `record_worker_heartbeat(…, plane="schedule")` issues
exactly one statement on a `MagicMock` connection and `worker_plane_health(…,
plane_name="schedule")` no longer raises `ValueError` before its first statement; (4) the UoW
read and the service fallback name `schedule` iff enabled (both polarities).
`test_schedule_jobs_is_a_plane_constant_only` becomes
`test_schedule_jobs_is_the_schedule_plane` (`SCHEDULE_JOBS` in `_JOB_PLANES` values). The
converted assertions are listed old → new in the I7-B handoff.

### 3.3 Handler `process_schedule_publication` (`src/my_pa/infrastructure/jobs/schedule.py`)

Signature `process_schedule_publication(engine: Engine, job: LeasedJob, owner: str) -> None`
(the `JobHandler` type). `principal_id = job.principal_id`, `publication_id =
job.subject_id`, `lease = ScheduleLease(job.operation_id, owner, job.attempt)`. Budget:
`ScheduleBudget(start=time.monotonic(), seconds=240)`; `budget.remaining()` is read at every
checkpoint `C`. The module imports neither `pypdfium2` nor `my_pa.infrastructure.schedule.pdf`
(the parent never loads PDFium — S5a U-12 resolved by construction).

#### 3.3.1 Phases (R2 §24 → S5b-1 methods)

| # | R2 §24 | Code | S5b-1 method / call | Notes |
|---|---|---|---|---|
| H1 | worker plan transaction | `with SqlAlchemyScheduleUnitOfWork(engine) as uow:` | `begin_processing` | `plan.terminal` → return (job completes, R6-F05); `SchedulePlan` gains `source_id: str \| None` (None iff terminal; E-03) |
| C1 | budget | | | |
| H2 | provider read phase | `engine.connect().execution_options(isolation_level="AUTOCOMMIT")` | module seam `_provider_for(connection, source_id)` = `RegisteredSourceProviders(connection).for_source(source_id)` (tests replace the seam with a fake `SourceProvider` serving synthetic bytes; extraction precedent `_provider`), then `metadata(source_object_id)`, `fetch(source_object_id, max_bytes=plan.max_fetch_bytes)` | no DB transaction around bytes; checks in 3.3.2 |
| C2 | budget | | | |
| H3 | (pin) | UoW | `pin_document(sha256(bytes), len(bytes))` | `ScheduleIntegrityError("document_changed")` → deterministic `source_version_changed` |
| C3 | budget, then `wall = min(150, remaining − 60)`; `wall < 15` → deterministic `processing_budget_exceeded` without spawning | | | |
| H4 | parser phase | `run_isolated_parse(bytes, expected_data_date, wall)` (3.4) | — | no DB transaction |
| C4 | budget | | | |
| H5 | parser-run batch | UoW | `start_parser_run(ScheduleParserIdentity(<result parser/profile fields>, <result.engine versions>))` | result `FAILED` → `fail_publication(<its single failed-ladder code>, run_id)`, return |
| H6 | row/issue batches | one UoW per batch, `C` before each | `insert_rows` ×⌈rows/1000⌉ in ordinal order, then `insert_issues` ×⌈issues/1000⌉, then `finish_parser_run(parsed=result.counts, parse_result_sha256=…)` | skipped only when the returned run has `status == parsed` (R7-N1); then `parse_result_sha256(result)` must equal the reused run's stored `parse_result_sha256`, a mismatch being an invariant breach → transient `internal_error`, nothing written (a re-claim is a determinism check, not blind trust). A `running` run returned here (this attempt's own run, reachable only by a second call within one attempt) with **zero** stored rows and issues is treated as fresh and gets the full H6; **any** stored row or issue on it is an invariant breach → transient `internal_error`, no write (`insert_issues` has no idempotency guard, so no resumption is attempted; R7-N2); `ScheduleRowBoundsError` → `fail_publication(BOUNDS_EXCEEDED, run_id)` |
| H7 | stable canonicalization | one UoW per batch, `C` before each | `canonicalize_batch(limit=1000)` until `remaining == 0` | only when the run outcome (= `result.outcome`) is `complete`/`partial` |
| H8 | finalization | UoW | `finalize_publication(ScheduleFinalization(run_id, title, data_date, run_date))` | status derived by F9/F3 |
| HF | deterministic terminal failure | UoW | `fail_publication(code, run_id or None)` then **return** | `run_id` only while that run is `running`; otherwise `None` (run-less issue, still `failed`) |
| HT | transient | `raise JobExecutionError(code)` | `release_job` in the loop | no write after |

Every UoW above is a separate short transaction whose first statement is `hold_lease` (inside
the S5b-1 method). `ScheduleLeaseLostError` anywhere → `raise LeaseLostError(job.operation_id)`
(loop counts `lost`; nothing further is written). Every write passes through a S5b-1 method;
the handler issues no SQL of its own except the provider read connection.

Budget exceeded at any checkpoint after H1 → `fail_publication(PROCESSING_BUDGET_EXCEEDED,
<running run or None>)` and return (R2 §22: failed while the lease is held). The lease (300 s
minimum, enforced by `apps/worker.py`) exceeds the budget (240 s) by 60 s; a provider call
cannot be pre-empted, so a call returning after lease expiry is caught by the next
`hold_lease` (R2 §25).

#### 3.3.2 Failure classification (every source → class → persisted state / safe code)

| Source | Class | Effect |
|---|---|---|
| `plan.terminal` (re-claim after a committed terminal) | done | return; job `succeeded` |
| provider lookup `None` or adapter `ValueError` | transient | `JobExecutionError(UNAVAILABLE)` |
| `ProviderError` (incl. `TraversalDeniedError`: absent and refused are one answer) | transient | `JobExecutionError(UNAVAILABLE)`; exhaustion → effective `failed` (R2 §22 "source read unavailable before bytes are proven") |
| `VersionChangedError`; `metadata().version_id` or `fetch().version_id` ≠ pinned | deterministic | `failed` / `source_version_changed` (run-less) |
| `metadata().media_type` is a string other than `"application/pdf"` | deterministic | `failed` / `unsupported_media_type` (run-less) |
| `metadata().media_type is None` (provider reports no type) | accepted | admission already proved the stored version's type is PDF; the `%PDF-` check below still applies (R7-F05) |
| `metadata().size_bytes > max_fetch_bytes`; `fetch().is_truncated`; `len(bytes) > 16 MiB` | deterministic | `failed` / `source_too_large` (run-less) |
| bytes do not start with `%PDF-` (checked before spawning) | deterministic | `failed` / `unsupported_media_type` (run-less) |
| `pin_document` → `ScheduleIntegrityError("document_changed")` (same version id, different bytes on a retry) | deterministic | `failed` / `source_version_changed` (run-less) |
| child result `FAILED` (corrupt, encrypted, image-only, layout, bounds, parser exception, in-child budget) | deterministic | run started, `failed` / the result's code (run-scoped) |
| child outcomes of section 3.4.6 marked deterministic | deterministic | `failed` / mapped code (run-less) |
| child outcomes marked transient (spawn failure, unexpected exit, malformed frame) | transient | `JobExecutionError(INTERNAL_ERROR)` |
| `ScheduleRowBoundsError` from `insert_rows` | deterministic | `failed` / `bounds_exceeded` (run-scoped; S5b-1 ruling (c)) |
| budget exceeded (any checkpoint after H1) | deterministic | `failed` / `processing_budget_exceeded` |
| `ScheduleLeaseLostError`, `complete_job` false | lost | `LeaseLostError`; no further write; another worker continues |
| `ScheduleIntegrityError` other than `document_changed` (`identity_gate`, `status_mismatch`, `incomplete_canonicalization`, `run_less_issue`, `row_ordinal_gap`) | transient (invariant breach) | `JobExecutionError(INTERNAL_ERROR)`; attempts bound the damage |
| SQLAlchemy/driver errors, deadlock `40P01`, anything else | transient | loop records `internal_error`; retry |

Attempt accounting: one `schedule_jobs` row per publication (`UNIQUE (publication_id)`, S5b-1 §4.4); `job.attempt`
is the claim's `attempt_count`; each attempt starts at most one parser run
(`attempt_number = lease.attempt`); `max_attempts = 3`; a deterministic outcome completes the
job (`succeeded`) while the publication is `failed`/`review_required` — the job's success
means "processing finished", not "publication succeeded" (R2 §22). Exhausted transient
attempts leave the publication `queued`/`processing` and reads derive effective `failed`
(S5b-1 `effective_publication_status`); no read writes. A re-claimed attempt re-reads,
re-pins (equal digest = no-op) and re-parses in the child; `start_parser_run` then either
reuses the `parsed` run for the S5b-1 reuse key (H6 skipped after the `parse_result_sha256`
equality check) or closes the earlier `running` run and starts a new one. A parsed run stores
no title, Data Date or Run Date, so finalization always needs the re-parse's result (R7-N1);
the cost is residual U2-11.

### 3.4 PDF isolation (S5a U-05, U-12)

#### 3.4.1 Mechanism

`subprocess.Popen` of the running interpreter, **not** `multiprocessing` (spawn would re-import
the worker's `__main__`; fork would copy a process holding database connections — the
`ProcessRowBuilder` precedent, T2-22):

```text
argv  = [sys.executable, "-I", "-B", "-c", CHILD_BOOTSTRAP, <src root>, <expected date or "-">, <wall ms>]
CHILD_BOOTSTRAP = "import sys; sys.path.insert(0, sys.argv[1]); "
                  "from my_pa.infrastructure.jobs.schedule_parser_child import main; "
                  "raise SystemExit(main(sys.argv[2:]))"
env   = {}                         # nothing inherited
cwd   = "/"
stdin = PIPE, stdout = PIPE, stderr = DEVNULL
close_fds = True, start_new_session = True
```

`-I` ignores every `PYTHON*` variable, the user site and the script directory; `-B`
writes no bytecode (required: `RLIMIT_FSIZE = 0` would kill a `.pyc` write with `SIGXFSZ`); `<src root>`
is the parent's own `Path(my_pa.__file__).parents[1]`, so the child imports exactly the
parent's code (the stale-import hazard cannot pick another tree). The parent process is
single-threaded around the call and never loads PDFium, so `fork`+`exec` copies no PDFium
state; the child processes exactly one document and exits (PDFium is never shared by
threads or reused across documents).

#### 3.4.2 Child (`src/my_pa/infrastructure/jobs/schedule_parser_child.py`)

`main(args) -> int`, in this order:

1. `apply_containment(ChildLimits.from_args(wall))` part 1: `RLIMIT_CORE = (0, 0)`,
   `RLIMIT_FSIZE = (0, 0)` (no write may grow a regular file past 0 bytes, native code
   included; pipes are unaffected). It does **not** stop native code from truncating
   (`O_TRUNC`), unlinking, renaming, changing permissions of, or creating empty files the
   worker UID may modify (U2-10).
2. import `my_pa.infrastructure.schedule` (loads PDFium) — before the descriptor cap.
3. part 2: on Linux `RLIMIT_AS = RLIMIT_DATA = (1 GiB, 1 GiB)` — failure to set → exit 5; on
   macOS the call raises `ValueError` (measured) and the cap is recorded as not in force;
   `RLIMIT_NOFILE = (32, 32)`; `RLIMIT_CPU = (ceil(wall_s) + 1, ceil(wall_s) + 2)`.
4. `sys.addaudithook(_refuse)`: raises `RuntimeError("contained")` on events `socket.*`
   (`__new__`, `connect`, `bind`, `getaddrinfo`, …), `subprocess.Popen`, `os.system`,
   `os.exec`, `os.posix_spawn`, `os.fork`, `os.forkpty`, `os.spawn`, `ctypes.dlopen`, and
   `open` with any write/append/create/update mode. Read-only `open` stays allowed (lazy
   stdlib imports).
5. argv is validated first (bad argv → exit 6); read `stdin.buffer.read(16_777_217)`; more than 16 MiB → exit 4.
6. `parse_full_schedule(data, expected_data_date=…, deadline=monotonic_start + wall_s − 1.0)`
   (production limits; S5a code unchanged). `MemoryError` → exit 3 (nothing written).
7. write `FRAME_MAGIC + canonical_json_bytes({"schema": "cpm-workbench-parse-frame-v1",
   "engine": {"pdfium_version": …, "pypdfium2_version": …}, "result":
   parse_result_object(result)})` to stdout; exit 0. `FRAME_MAGIC = b"CPMWB-PARSE-1\n"`.

   *Implementation note I7-A (orchestrator-ratified):* the frame object carries a 4th exact
   key, `"page_dimensions": [[page, width_mpt, height_mpt], …]`, strictly increasing by page
   and equal to the set of pages that carry rows (the canonical result object does not hold
   page dimensions, which the row rebuild needs); the parent refuses any other key set.

The child imports only the standard library, `my_pa.domain.schedule`,
`my_pa.domain.common.identifiers` and `my_pa.infrastructure.schedule` (measured closure: no
`sqlalchemy`, `psycopg`, `socket`, `ssl`, `http`; `urllib.parse` only), prints nothing and
writes nothing but the frame.

#### 3.4.3 Parent (`src/my_pa/infrastructure/jobs/schedule_parser_process.py`)

`run_isolated_parse(data: bytes, *, expected_data_date: date | None, wall_seconds: float,
limits: ChildLimits = PRODUCTION_CHILD_LIMITS, command: Sequence[str] = CHILD_COMMAND) ->
IsolatedParse` where `IsolatedParse` is exactly one of `ParsedResult(result)`,
`DeterministicFailure(code)`, `TransientFailure(error_code)`. One `selectors` loop, no
threads: non-blocking writes of `data` to stdin (then close), reads of stdout into a buffer
capped at `MAX_CHILD_OUTPUT_BYTES + 1 = 134_217_729` bytes, against `deadline =
monotonic() + wall_seconds + 2.0`. `finally`: if the child is alive, `os.killpg(pid,
SIGKILL)`; always `process.wait(timeout=5)` (no zombie). `command` and `limits` are
injectable for tests only (tightened, never widened: `ChildLimits` refuses values above
production, as `ScheduleParseLimits` does, and a test wall below `MIN_TEST_WALL_SECONDS = 1.0`;
the in-child cooperative deadline is `start + max(wall − 1.0, 0)`, never negative — R7-F12).

#### 3.4.4 Bounds

| Bound | Value | Enforced by |
|---|---|---|
| input | ≤ 16,777,216 bytes | handler before spawn; child exit 4 |
| address space | 1,073,741,824 bytes (Linux only), **provisional** (labelled so in its code comment; U2-12): no number is presented as measured unless measured on Linux (macOS has no `VmPeak`, and macOS VSZ includes the shared cache, so it is neither a proxy nor cited). Verification is the Linux-only `test_child_address_space_has_headroom` (3.4.8), enforced by the PR's ubuntu CI | `RLIMIT_AS`/`RLIMIT_DATA` |
| CPU | `ceil(wall)+1` s soft (`SIGXCPU`), +1 hard | `RLIMIT_CPU` |
| wall | `min(150, remaining − 60)` s, ≥ 15 s; parent kill at wall + 2 s | parent loop; in-child cooperative deadline at wall − 1 s |
| open descriptors | 32 | `RLIMIT_NOFILE` |
| core files / file writes | 0 / 0 bytes | `RLIMIT_CORE`, `RLIMIT_FSIZE` |
| output | 134,217,728 bytes incl. magic | parent read cap (measured: 1,858 bytes/row canonical on the 86-page fixture ⇒ ≈ 46 MB at 25,000 rows; 2.9× headroom) |

#### 3.4.5 Network denial — what is and is not enforced

Enforced: no credentials or database URL can reach the child (empty environment, `-I`, no
inherited descriptors besides 0/1/2, `stderr` discarded); the child's import closure contains
no networking or database module (FAST guard); every Python-level socket, process-spawn,
exec, `ctypes.dlopen` and file-write attempt raises (audit hook); no code, native included,
can grow a regular file (`RLIMIT_FSIZE = 0`); descriptor count is capped.
**Not enforced:** native PDFium code issuing raw `socket(2)`/`connect(2)` system calls after
memory corruption. Neither macOS (no supported sandbox API) nor the Linux container (no
seccomp profile or network namespace is configured, and creating one needs privileges the
worker does not hold) prevents it. Residual U2-01; an operator-level mitigation is a
network-less container for the schedule worker (section 8.3). **Also not enforced (U2-10):**
native file-system effects that do not grow a file (truncate, unlink, rename, chmod, mkdir,
empty-file creation) under the worker's UID, and **result forgery** — a compromised child can
return a well-formed frame for the right digest with fabricated rows; the parent's checks
prove the frame's shape and its binding to the bytes sent, not the truth of its rows, and
forged rows would be served as `SOURCE_BOUND_DERIVED`. Mitigations are operator-level
(section 8.3): a dedicated UID with a read-only root filesystem and no write access to any
source root, and the network-less runtime.

#### 3.4.6 Deterministic mapping of child outcomes

| Child outcome | Class | Code |
|---|---|---|
| exit 0, valid frame, decoded result, `document_sha256`/size equal the bytes sent | parsed | the result (any outcome) |
| exit 0, frame missing/garbled, schema/key mismatch, decode or canonical round-trip mismatch, digest mismatch | transient | `internal_error` |
| output exceeds `MAX_CHILD_OUTPUT_BYTES` | deterministic | `bounds_exceeded` |
| parent wall deadline reached (child killed by the parent) | deterministic | `processing_budget_exceeded` |
| killed by `SIGXCPU` | deterministic | `processing_budget_exceeded` |
| exit 3 (`MemoryError`) | deterministic | `bounds_exceeded` |
| exit 4 (oversized stdin) | deterministic | `source_too_large` |
| exit 6 (bad argv — a parent programming error, R7-F05) | transient | `internal_error` |
| killed by `SIGSEGV`, `SIGBUS`, `SIGILL`, `SIGTRAP`, `SIGABRT`, `SIGFPE` (native crash, incl. PDFium's own allocation-failure crash under `RLIMIT_AS`) | deterministic | `parser_exception` |
| killed by `SIGKILL` not sent by the parent (external OOM killer, operator) | transient | `internal_error` |
| exit 5 (Linux memory cap could not be set), any other exit code or signal, `OSError` at spawn | transient | `internal_error` |

Decoding: `parse_result_from_object(obj, engine, page_dimensions)` (new,
`src/my_pa/domain/schedule/canonical.py`; *implementation note I7-A*: it takes the frame's
`page_dimensions` as `{page: (width_mpt, height_mpt)}`) rebuilds a `ScheduleParseResult` with exact key sets and closed values, then requires
`canonical_json_bytes(parse_result_object(rebuilt)) == canonical_json_bytes(obj)`; JSON is
parsed with `parse_constant` refusing `NaN`/`Infinity`. JSON (not `pickle`) because the child
handles hostile data and a compromised child must not gain code execution in the parent.

#### 3.4.7 Platform differences (stated, tested)

| Platform | `RLIMIT_AS` | Consequence |
|---|---|---|
| Linux (CI `ubuntu-latest`, production container) | enforced | memory tests run **in CI only** unless a Linux host is used; each is reported "CI-only, not executed on the implementation host" until a CI run shows it (R7-F01); a bomb ends `bounds_exceeded` or `parser_exception` (pinned per test, measured) |
| macOS (dev) | cannot be lowered (`ValueError`, measured on the basis host) | memory tests skip with reason `RLIMIT_AS is enforced only on Linux`; `test_containment_reports_the_memory_cap_per_platform` asserts the report on both |

#### 3.4.8 Hostile-PDF tests (generated in-test, small, deterministic, stdlib `zlib` only)

| Case | Construction | Expected |
|---|---|---|
| positive control (production limits) | the largest synthetic golden (`full_multi_page_86_equivalent`) and the bounds-maximal synthetic within production caps, under `PRODUCTION_CHILD_LIMITS` | each parses to its golden outcome with a digest equal to the in-process parse — the cap does not break benign documents (Linux) |
| address-space headroom (R7 F01 ruling) | `test_child_address_space_has_headroom`, skipped exactly when `sys.platform != "linux"` (reason `Linux-only: RLIMIT_AS/VmPeak`; never "if the cap cannot be set", so an unsettable cap on Linux fails as exit 5 → transient instead of skipping): a test-only probe child, reachable **only** through the injectable test `command`, applies every production containment step **except** `RLIMIT_AS`/`RLIMIT_DATA` (so the peak is not censored), imports the parser, parses the largest synthetic golden and the bounds-maximal synthetic, and reports `VmPeak` from `/proc/self/status` | asserts `2 × VmPeak ≤ PRODUCTION_CHILD_LIMITS.address_space` and prints the measured value; fails in CI below 2× headroom. `ChildLimits` still refuses widening and the production path cannot omit the cap; FAST `test_child_command_applies_the_address_space_cap_on_linux` asserts `CHILD_COMMAND` always applies `RLIMIT_AS` on Linux |
| positive control (bomb cap) | the 86-page fixture under the bomb test's `address_space = 268,435,456` | parses to its golden outcome — the bomb below fails because of the bomb (Linux) |
| decompression bomb | 1 page, `FlateDecode` content stream of 536,870,912 zero bytes (≈ 0.5 MiB compressed), test limit `address_space = 268,435,456` | Linux: `failed`, code pinned to the measured member of {`bounds_exceeded`, `parser_exception`}, identical on 2 runs; parent RSS growth < 64 MiB |
| page count | 251 minimal valid pages | `failed` / `bounds_exceeded` (S5a V-cap through the child) |
| deep nesting | page `/Resources` holding 100,000 nested arrays | `failed` / code pinned (measured; `corrupt_pdf` or `parser_exception`), parent survives |
| timeout (in-child path) | the 86-page fixture with `wall_seconds = MIN_TEST_WALL_SECONDS = 1.0` (in-child deadline `start + 0`) | the child returns a run-scoped `FAILED` result with `processing_budget_exceeded` (the parent kill at 3 s is not reached); the parent-kill path is the hang row |
| hang | probe child `time.sleep(60)` | parent kills at wall + 2 s; `processing_budget_exceeded`; no zombie (`waitpid` reaped) |
| crash | probe `os.kill(os.getpid(), SIGSEGV)` | `parser_exception` |
| external kill | probe `os.kill(os.getpid(), SIGKILL)` | transient `internal_error` |
| oversize output | probe writes `MAX + 1` bytes | `bounds_exceeded`; parent buffer never exceeds the cap |
| malformed frame | probe writes valid magic + `{}` | transient `internal_error` |
| environment | probe prints `sorted(os.environ)` | ⊆ {`LC_CTYPE`, `__CF_USER_TEXT_ENCODING`} (interpreter/OS-added, measured); parent's planted `MY_PA_DATABASE_URL` and a sentinel secret absent |
| containment | probe calls `apply_containment` then tries `socket.socket()`, `open(path, "w")`, `subprocess.run`, and prints `getrlimit` values | each refused; rlimits equal section 3.4.4 |
| parity | every S5a golden case through the child | `parse_result_sha256` equal to the in-process parse (no behaviour change) |
| text flood (FR7-F04) | 1 page, 2,610 bytes, Flate content `BT /F1 1 Tf` then `(x) Tj` 200,000 times with no `Td` (in PDFium, an early call boundary, then one long native call); wall 5 s | a budget answer either way, host-speed dependent: a run-less `DeterministicFailure(processing_budget_exceeded)` when the child is still inside the long native call at the wall and is ended from outside (`SIGXCPU` at ceil(wall) + 1 s CPU, about 6.05–6.21 s on the implementation host, or the parent kill at wall + 2 s; then elapsed ≥ wall), or a run-scoped `FAILED` result coded `processing_budget_exceeded` when the in-child deadline had already passed at the early call boundary (seen on efficiency cores, 4.40 s); elapsed ≤ wall + 3 s in both. On Linux `bounds_exceeded` or `parser_exception` are also admitted, if the address-space cap ends it first (U2-13) |

*Implementation note I7-D (FR7-F01):* the **bounds-maximal synthetic** is generated at test time
by `_bounds_maximal()` in `tests/unit/test_schedule_parser_isolation.py` from the S5a generator's
`Plan` (no committed binary, neutral synthetic text only): 250 pages (the page cap) of 93 rows
each — the most 7-point rows the `p6_full_v1` data zone holds without overlapping glyph boxes
— so 23,250 rows (93 % of the 25,000-row cap, which 250 pages of this geometry cannot reach),
a PDFium character count of 1,928,357 (96 % of 2,000,000), 142,749 text objects (57 %) and
about 12.4 MB (74 %); outcome `complete`. The FAST test
`test_bounds_maximal_synthetic_is_at_or_near_every_production_cap` pins those properties on every
platform. Both Linux memory rows are parametrized over `largest_golden` and `bounds_maximal`
(`test_largest_golden_parses_under_production_limits[…]`, `test_child_address_space_has_headroom[…]`);
the bomb-cap positive control stays on the 86-page golden.

### 3.5 Capabilities

| Capability (enum member) | Command | Handler | Kind | Purpose | Operator-only | Scope | Additive | ChatLLM |
|---|---|---|---|---|---|---|---|---|
| `schedule_publications.import` (`SCHEDULE_PUBLICATIONS_IMPORT`) | `ImportSchedulePublication` | `_schedule_publications_import` | write | `schedule_import` | yes | enrollment source scope | yes | `CONTROL_PLANE_EXCLUDED` |
| `schedule_series.list` (`SCHEDULE_SERIES_LIST`) | `ListScheduleSeries` | `_schedule_series_list` | read | `schedule_read` | no | scopeless | — | `DATA_CONDITIONAL` / `SCHEDULE` |
| `schedule_publications.list` (`SCHEDULE_PUBLICATIONS_LIST`) | `ListSchedulePublications` | `_schedule_publications_list` | read | `schedule_read` | no | scopeless | — | same |
| `schedule_publications.read` (`SCHEDULE_PUBLICATIONS_READ`) | `ReadSchedulePublication` | `_schedule_publications_read` | read | `schedule_read` | no | scopeless | — | same |
| `schedule_activities.list` (`SCHEDULE_ACTIVITIES_LIST`) | `ListScheduleActivities` | `_schedule_activities_list` | read | `schedule_read` | no | scopeless | — | same |
| `schedule_activities.history` (`SCHEDULE_ACTIVITIES_HISTORY`) | `ReadScheduleActivityHistory` | `_schedule_activities_history` | read | `schedule_read` | no | scopeless | — | same |
| `schedule_changes.list` (`SCHEDULE_CHANGES_LIST`) | `ListScheduleChanges` | `_schedule_changes_list` | read | `schedule_read` | no | scopeless | — | same |

Command summaries (first docstring line = `TOOLS` description):

| Command | Summary |
|---|---|
| `ImportSchedulePublication` | Admit one enrolled schedule PDF version as a publication of a Schedule Series and queue its parse (attested local operator: CLI or HTTP gateway only). |
| `ListScheduleSeries` | List a Project's Schedule Series, newest first, with each one's latest comparison-eligible update. |
| `ListSchedulePublications` | List one Schedule Series' publications, newest admission first, with effective status and counts. |
| `ReadSchedulePublication` | Read one schedule publication: source identity, document digest, published metadata, status, job, parser runs and issue counts by code. |
| `ListScheduleActivities` | List one complete or partial publication's activities and milestones in published schedule order. |
| `ReadScheduleActivityHistory` | Read one Stable Activity's observations in its Series' complete and partial publications, oldest Data Date first. |
| `ListScheduleChanges` | Compare two publications of one Series and list the exact per-activity changes from the first to the second. |

#### 3.5.1 Inputs (frozen dataclasses; unknown key → `invalid_request`; every field validated in `__post_init__`)

| Command | Fields (type; bound; error detail) |
|---|---|
| `ImportSchedulePublication` | `project_id` (`prj`; `PROJECT_ID`); `series_id: str \| None` (`sser`; `SERIES_ID`); `series_name: str \| None` (raw ≤ 1,000 characters, then `normalize_series_name`; `SERIES_NAME`) — exactly one of the two (`SERIES_ID`); `enrollment_id` (`enr`; `ENROLLMENT_ID`); `source_object_id` (`obj`; `SOURCE_OBJECT_ID`); `source_version_id` (`ver`, required; `SOURCE_VERSION_ID`); `publication_role` ∈ `update\|baseline\|reference` (required; `PUBLICATION_ROLE`); `baseline_kind` ∈ `working\|contract`, present iff role `baseline` (`BASELINE_KIND`); `expected_data_date: str \| None` (`YYYY-MM-DD`; `EXPECTED_DATA_DATE`); `supersedes_publication_id: str \| None` (`spub`; `SUPERSEDES_PUBLICATION_ID`); `idempotency_key` (`^[A-Za-z0-9_-]{8,128}$`; `IDEMPOTENCY_KEY`). No path, locator, filename, URL, bytes, Principal or scope field exists. |
| `ListScheduleSeries` | `project_id`; `page_size: int \| None` (1..100, default 25; `PAGE_SIZE`); `cursor: str \| None` (≤ 512; `CURSOR`) |
| `ListSchedulePublications` | `series_id`; `publication_role: str \| None`; `status: str \| None` (∈ the 6 publication statuses, matched against **effective** status; `STATUS`); `page_size`; `cursor` |
| `ReadSchedulePublication` | `publication_id` |
| `ListScheduleActivities` | `publication_id`; `row_type: str \| None` ∈ `activity\|milestone` (`ROW_TYPE`); `hierarchy_prefix: list[str] \| None` (1..32 labels, each 1..2,000 characters, exact match on the leading path entries; `HIERARCHY_PREFIX`); `start_from`, `start_to`, `finish_from`, `finish_to: str \| None` (`YYYY-MM-DD`, inclusive, `from ≤ to`; `DATE_RANGE`); `page_size`; `cursor` |
| `ReadScheduleActivityHistory` | `schedule_activity_id` (`sact`; `SCHEDULE_ACTIVITY_ID`); `page_size`; `cursor` |
| `ListScheduleChanges` | `from_publication_id`, `to_publication_id` (both required, `spub`; `FROM_PUBLICATION_ID`/`TO_PUBLICATION_ID`); `change_kind: str \| None` (∈ the 11 kinds; `CHANGE_KIND`); `page_size`; `cursor` |

#### 3.5.2 Outputs (payload keys; every success carries the section 3.8 disclosure)

| Capability | Payload |
|---|---|
| import | `{series_id, publication_id, operation_id, status: "queued"\|"replayed", created: bool}` (`created` = admission outcome `CREATED`) |
| `schedule_series.list` | `{project_id, series: [{series_id, name, publication_count, latest_update: {publication_id, data_date} \| null}], page_size}` |
| `schedule_publications.list` | `{series_id, publications: [{publication_id, publication_role, baseline_kind, supersedes_publication_id, status (effective), persisted_status, published_schedule_title, data_date, run_date, admitted_at, completed_at, page_count, row_count, activity_count, ambiguous_row_count, issue_count, parser_name, parser_version, profile_id, profile_version, operation_id}], page_size}` |
| `schedule_publications.read` | `{publication_id, series_id, project_id, enrollment_id, source_object_id, source_version_id, publication_role, baseline_kind, expected_data_date, supersedes_publication_id, status, persisted_status, document_sha256, document_size_bytes, published_schedule_title, data_date, run_date, counts {page, row, activity, ambiguous_row, issue}, admitted_at, processing_started_at, completed_at, job {operation_id, state, attempt_count, max_attempts, last_error_code}, accepted_parser_run_id, parser_runs [{parser_run_id, attempt_number, status, parser_name, parser_version, profile_id, profile_version, pypdfium2_version, pdfium_version, failure_code, started_at, completed_at}], issue_counts {<code>: n}}` |
| `schedule_activities.list` | `{publication_id, activities: [{schedule_activity_id, published_activity_id, activity_name, row_type, row_ordinal, page_number, hierarchy_path, original_duration, remaining_duration, start, finish, warning_codes, provenance {page_number, physical_line_ordinal, bbox_normalized}}], page_size}`; a duration is `{state, value: "<decimal, 3 places>" \| null}`, a date `{state, value: "YYYY-MM-DD" \| null, marker: "*" \| null}` |
| `schedule_activities.history` | `{schedule_activity_id, series_id, published_activity_id, observations: [{publication_id, publication_role, baseline_kind, data_date, admitted_at, activity_name, row_type, hierarchy_path, original_duration, remaining_duration, start, finish}], page_size}` — no `created_at`, no "first seen" |
| `schedule_changes.list` | `{algorithm_version: "cpm-workbench-full-delta-v1", from: {publication_id, publication_role, baseline_kind, data_date}, to: {…}, counts_by_kind: {<all 11 kinds>: n}, changes: [{schedule_activity_id, published_activity_id, change_kind, field, before, after, delta_calendar_days, delta_source_units}], page_size}` |

No payload carries a filename, locator, path, raw PDF/page text, raw cell fragments,
exception text or a `schedule_activities.created_at`.

#### 3.5.3 Error mapping

| Condition | Error |
|---|---|
| switch off / factory absent | `unsupported` (no detail) |
| import from a remote composition (`transport is REMOTE_CLIENT` or `capability_grants is not None` or `authenticated_client_id is not None`) | `unsupported` (defence in depth; it is never published remotely) |
| import from any local caller without an attested operator surface (stdio MCP, which runs `LOCAL` with no `operator_surface`; any unattested composition) | `denied` — `attested_lineage_authority(authorization)` (`src/my_pa/application/lineage_authority.py`, the S3.1 D-16 mechanism the backfill report and confirm handlers already call) admits only `operator_surface ∈ {CLI, HTTP_GATEWAY}`, stamped only by `adapters/cli/app.py` and `adapters/http/app.py`; fail-closed (E-12, R7-F03) |
| remote read without a grant on that capability for `schedule_read` | `unsupported` (`require_read_grant`) |
| foreign or absent enrollment (import) | `denied` from authorization (empty requested scope), audited; the admission refusal `ENROLLMENT_NOT_FOUND` is the backstop → `not_found(ENROLLMENT_ID)` |
| `PROJECT_NOT_FOUND` / `SERIES_NOT_FOUND` / `SOURCE_OBJECT_NOT_ENROLLED` / `SOURCE_VERSION_NOT_FOUND` / `SUPERSEDED_PUBLICATION_NOT_FOUND` | `not_found(PROJECT_ID / SERIES_ID / SOURCE_OBJECT_ID / SOURCE_VERSION_ID / SUPERSEDES_PUBLICATION_ID)` |
| `UNSUPPORTED_MEDIA_TYPE` | `unsupported(SOURCE_VERSION_ID)` |
| `MEDIA_TYPE_NOT_ENROLLED` | `denied` (the enrollment does not admit PDF) |
| `SOURCE_TOO_LARGE` | `unsupported(MAX_BYTES)` |
| `SUPERSEDED_PUBLICATION_NOT_TERMINAL` / `…_HAS_SUCCESSOR` | `conflict(SUPERSEDES_PUBLICATION_ID)` |
| `SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION` | `invalid_request(SUPERSEDES_PUBLICATION_ID)` |
| `IDEMPOTENCY_KEY_CONFLICT` / `SOURCE_VERSION_CONFLICT` | `conflict(IDEMPOTENCY_KEY)` / `conflict(SOURCE_VERSION_ID)` (U-09 surfaced) |
| read root absent, another Principal's, or an orphan Stable Activity (U-03) | `not_found(<root detail>)`, byte-identical answer |
| activities/changes on a publication not effective `complete`/`partial` | `conflict(STATUS)` |
| changes pair in different Series, equal, or reversed order | `invalid_request(TO_PUBLICATION_ID)` |
| cursor unreadable, expired, rebound | `conflict(CURSOR)` |

Every not-found is raised before any other read of the root's children, so timing and shape
do not distinguish "another Principal's" from "absent" beyond the one partitioned lookup.

### 3.6 Import admission

1. `_schedule_plane()`; remote-composition refusal; `attested_lineage_authority(authorization)` (result discarded; `denied` unless CLI or HTTP gateway) — all before any read or write (3.5.3, E-12).
2. `command.import_request()` builds the S5b-1 `ScheduleImportRequest` (series name normalized
   by `normalize_series_name`, R2 §10.1; role/baseline enums; date parsed).
3. `digest = schedule_import_request_digest(principal_id, request)` (S5b-1 D-14).
4. `with schedule_uow() as suow: admission = suow.schedules.admit_publication(principal_id,
   request, digest)` — the S5b-1 one-transaction method: idempotency replay/conflict, owned
   Project, owned accepted enrollment, enrolled object, version→object binding, PDF media
   type, enrollment allowlist, known size ≤ 16 MiB, Series resolve-or-create on `name_key`,
   source-version replay/conflict, supersession rules, then publication insert and exactly
   one `enqueue_job(…, plane=SCHEDULE_JOBS)`. No bytes are fetched.
5. `ScheduleAdmissionRejectedError(reason)` → section 3.5.3 (the UoW rolled back, including
   any Series row).
6. Payload of 3.5.2; disclosure `schedule_import_disclosure` (3.8).

Authority: `ApplicationService.invoke` → `authorize` (operator-only, purpose
`schedule_import`, requested scope = the source of the caller's **own** enrollment named by
`enrollment_id`) → durable audit → handler. Cross-binding to another Principal's
enrollment, object or version is refused twice: by authorization (empty scope) and by the
S5b-1 composite FKs/partitioned reads.

### 3.7 Schedule cursor (`src/my_pa/domain/schedule/cursor.py`)

| Item | Rule |
|---|---|
| Encoding | unpadded base64url of canonical JSON (sorted keys, compact, ASCII) `{"b": <64 hex>, "p": [<position>], "t": <int epoch seconds>, "v": 1}` |
| Length | `MAX_SCHEDULE_CURSOR_CHARACTERS = 512`; a longer input is refused before decoding; every position below encodes far under the bound (largest: history, 3 short scalars), and an encoder result over 512 is a programming error (`ValueError`) |
| TTL | `SCHEDULE_CURSOR_TTL_SECONDS = 300`, compared with `authorization.at` |
| Binding `b` | SHA-256 of canonical JSON `{"capability", "cursor_version": 1, "principal_id", "purpose", "request": <normalized command fields without cursor>, "page_size": <effective>, "order": <order id>}` plus, for changes, `"algorithm_version": "cpm-workbench-full-delta-v1"` (offset semantics depend on it; R7-F10). `t` is **not** covered by `b`, so the TTL is advisory against a caller who edits `t` (the search precedent has the same property); a `t` later than `authorization.at` + 5 s is refused |
| Order ids | `series_created_desc_id_desc`, `publications_admitted_desc_id_desc`, `activities_row_ordinal_asc_row_id_asc`, `history_data_date_asc_admitted_asc_id_asc`, `changes_offset_in_published_id_kind_field_order` |
| Positions `p` | series `[created_at, series_id]`; publications `[admitted_at, publication_id]`; activities `[row_ordinal, row_id]`; history `[data_date, admitted_at, publication_id]`; changes `[offset]` — the number of entries of the (filtered) sorted change list already returned, stable because both inputs are terminal and immutable and the algorithm is versioned; an offset beyond the list is `conflict(CURSOR)`; instants as `YYYY-MM-DDTHH:MM:SS.ffffffZ`, dates ISO; each element shape-checked |
| Refusals | malformed, expired, future-issued, binding mismatch: one `ScheduleCursorError` → `conflict(CURSOR)` (search precedent, R2 §32.1) |
| Order of checks | decode, binding and TTL (pure) **before** the root lookup, so a bad cursor never reaches the database and never distinguishes a present root from an absent one (R7-F10) |
| Authority | none; every page is re-authorized by `invoke`, re-partitioned, re-checked for visibility; not a MAC — a forged position can only skip to rows the same query could read |
| Next cursor | issued only when a `page_size + 1`-th row exists (`Truncation(is_truncated=True, reason="page_size_reached", next_cursor=…)`) |

No position carries a published Activity ID, a name or any other source text (a Unicode ID
of 256 characters could not fit 512 characters of base64, and the cursor would echo source
text); the changes position is a bare offset for that reason.

### 3.8 Disclosure (`src/my_pa/application/schedules.py`)

`schedule_disclosure(*, publications: Sequence[ScheduleSourceBinding], observed_at, truncation)`
for reads; the referenced publications are those whose rows/metadata the answer contains
(series list: each row's latest update; publications list/read: the listed ones; activities:
the one; history: the observed ones on the page; changes: the pair).

| Field | Rule |
|---|---|
| `scope` | sorted unique `source_ids` (from the publication's enrollment, partitioned join) and `enrollment_ids` |
| `coverage` | over the referenced set P: `eligible = |P|`, `processed` = effective complete+partial, `quarantined` = review_required, `unsupported` = failed (persisted or effective); state: `eligible` with every count 0 if P is empty (an ordinary case — a Series with no eligible update, an empty filtered page — never `not_enrolled`, which would claim nothing is enrolled; R7-F08; scope and references empty, `partial_result` false unless truncated), `processed` if all complete, `queued` if all queued/processing, `quarantined` if all review_required, `unsupported` if all failed, else `partially_processed` |
| `freshness` | `observed_at = authorization.at`, `CURRENT_FOR_OBSERVED_VERSION` |
| `trust` | `TrustLevel.SOURCE_BOUND_DERIVED`, basis `("cpm-workbench-full-parser", "p6_full_v1")`, plus `"cpm-workbench-full-delta-v1"` for changes |
| `source_references` | one `SourceReference(source_id, source_object_id, source_version_id)` per referenced publication, sorted |
| `truncation` | section 3.7 |
| `partial_result` | true iff the coverage state is partial-class or truncated (existing validator) |
| `classification` | `PRIVATE_LOCAL`, `cloud_eligible = False` |

Import: scope = the enrollment's source and the enrollment, coverage `queued` (eligible 1)
for `CREATED`, the publication's effective state for `REPLAYED`; trust basis
`("schedule_admission",)`; one source reference. The disclosure states coverage of the
selected publications only, never of the enrolled corpus (R2 §32.8).

### 3.9 Reads — queries and visibility rules

New `ScheduleRepository` read methods (section 4.3) build every statement with `_mine` /
`principal_scoped`; no `text()`; every row read is joined to its publication under the same
Principal.

| Read | Query | Eligibility / visibility |
|---|---|---|
| series list | series of the owned Project ordered `(created_at DESC, series_id DESC)`; `publication_count` = all publications; `latest_update` = max `(data_date, admitted_at, publication_id)` among `publication_role='update'` and status `complete\|partial` | Project not owned → `not_found(PROJECT_ID)`; baselines and references never become "latest update" |
| publications list | `(admitted_at DESC, publication_id DESC)`; effective status = `failed` when persisted `queued\|processing` and the job is `failed` or abandoned at its last attempt (new public `job_is_effectively_failed(plane)` in `jobs.py`, the same predicate `job_for` uses) | Series not owned → `not_found(SERIES_ID)` |
| publication read | publication + job + runs; `issue_counts`: **RR1-I01** — persisted `complete\|partial\|review_required` count only the accepted run's issues (`parser_run_id = accepted_parser_run_id`); `failed` counts every issue of the publication (= its stored `issue_count`); queued/processing count every issue so far | not owned → `not_found(PUBLICATION_ID)` |
| activities list | rows with `parser_run_id = accepted_parser_run_id` and `row_type IN ('activity','milestone')`, ordered `(row_ordinal, row_id)`; date filters match only `published_value` cells; prefix matches `hierarchy_path[1:n] = :prefix` | publication must be effective `complete\|partial` (else `conflict(STATUS)`); summaries are carried by `hierarchy_path`, never listed |
| history | rows `r` with `r.schedule_activity_id = :id`, joined to publications `p` with `r.parser_run_id = p.accepted_parser_run_id` and `p.status IN ('complete','partial')`, ordered `(p.data_date, p.admitted_at, p.publication_id)` | **U-03**: the Stable Activity is visible iff at least 1 such row exists; otherwise `not_found(SCHEDULE_ACTIVITY_ID)`, identical to absent or foreign; `created_at` never returned |
| changes | section 3.10 | section 3.10 |

History may list a superseded predecessor and its successor with the same Data Date; both
are actual observations ordered by `(data_date, admitted_at, publication_id)` (R7-F11).

Invariant check: an eligible publication with `data_date IS NULL` contradicts T2-27 →
`InternalError` (never a guessed order).

### 3.10 Delta `cpm-workbench-full-delta-v1` (`src/my_pa/domain/schedule/compare.py`)

**Eligibility (R2 §29.1).** Both publications owned (else `not_found`), same Project and
Series (else `invalid_request(TO_PUBLICATION_ID)`), effective `complete|partial` (else
`conflict(STATUS)`), and `key(from) < key(to)` with `key = (data_date, admitted_at,
publication_id)` (equal or reversed → `invalid_request(TO_PUBLICATION_ID)`). Any roles may
be paired; the caller chooses (R2 §30).

**Data flow.** The repository streams each side's accepted-run `activity|milestone` rows
ordered `published_activity_id COLLATE "C"` (byte order = code-point order for UTF-8) in
chunks of 1,000 (`yield_per`) as `ScheduleComparisonRow(schedule_activity_id,
published_activity_id, activity_name, row_type, hierarchy_path, original_duration,
remaining_duration, start, finish)`. `prior_observations(principal_id, series_id,
before=key(from), schedule_activity_ids)` returns the ids among the given set that have a
linked accepted-run row in an eligible publication of the Series with key `< key(from)` (one
statement, `= ANY(:ids)`). "Eligible" here is any role — update, baseline, reference — and
includes superseded predecessors (R2 §29.3 and §10.4: supersession never hides the
predecessor; R7-F11). The application merges the 2 sorted streams once (O(N), exact
`published_activity_id` equality = same Stable Activity inside one Series), calls
`prior_observations` once with the B-only ids, and builds the full change list.

**Change kinds and rules** (`ScheduleChangeKind`, declaration order = `kind_rank` 1..11).
For a matched pair, rules are evaluated independently; one pair may emit several changes.

| Kind | Rule | `field` | `before` / `after` | Delta |
|---|---|---|---|---|
| `added` | in B only and **not** in `prior_observations` | null | null / `{activity_name, row_type}` | null |
| `removed` | in A only | null | `{activity_name, row_type}` / null | null |
| `reintroduced` | in B only and in `prior_observations` (replaces `added`) | null | null / `{activity_name, row_type}` | null |
| `renamed` | stored names differ (both are the parser's NFC + space-normalized display text, compared exactly) | `activity_name` | names | null |
| `row_type_changed` | `activity` ↔ `milestone` | null | row types | null |
| `original_duration_changed` | both `published_value`, values differ | `original_duration` | cell objects | `delta_source_units = to − from` (decimal string, 3 places) |
| `remaining_duration_changed` | same for RD | `remaining_duration` | cell objects | same |
| `start_changed` | both `published_value`, dates differ | `start` | cell objects (incl. marker) | `delta_calendar_days = (to − from).days` (int) |
| `finish_changed` | same for Finish | `finish` | cell objects | same |
| `hierarchy_changed` | both paths non-NULL and differ | `hierarchy` | paths | null |
| `field_state_changed` | for OD/RD/Start/Finish: states differ (at least 1 side not `published_value`); for hierarchy: exactly 1 side NULL (`before_state`/`after_state` = `published_value` for a path, `ambiguous` for NULL) | the field code | `{state, …}` per side | null — never fabricated |

OD/RD values are compared as `Decimal`, never as strings (R7-F11). Not changes: equal values; both sides the same non-value state; a marker-only difference on
an equal date (residual U2-07); bbox/style/page/ordinal differences (provenance, R2 §29.5).

**Ordering and pagination.** Sort `(published_activity_id, kind_rank, field_rank)` where
`field_rank` = `ScheduleFieldCode` declaration order (null = 0). `counts_by_kind` is computed
over the full unfiltered list (all 11 keys present). `change_kind` filters after counting.
A page is the next `page_size` entries after the cursor offset; every page
recomputes the delta (deterministic inputs: terminal, immutable rows; no persistence, R2
§29.6).

**Bounds.** ≤ 25,000 rows per side (S5a cap); memory O(N) for the change list; target
25,000-row A→B scan < 5 s on the isolated CI database (`test_change_scan_of_25000_rows_meets_the_target`,
`database`+`slow`; a miss is reported, never hidden by widening the bound).

### 3.11 Baseline (R2 §30)

| Rule | Enforcement |
|---|---|
| role explicit, no default | `publication_role` is a required command field; a missing role is `invalid_request` |
| baseline kind iff baseline | command `__post_init__` + S5b-1 CHECK `a_schedule_baseline_has_its_kind` |
| update ≠ baseline; "previous update" and "first publication" are not baselines | no code path derives a baseline; `latest_update` considers role `update` only; FAST guard greps `application/schedules.py` and `domain/schedule/compare.py` for no `"baseline"` default literal and no `current_baseline`/`previous` symbol |
| no baseline Start/Finish columns | none exist (S5b-1 schema) |
| caller selects the pair | `schedule_changes.list` requires both ids |
| multiple baselines allowed | no uniqueness on role |

### 3.12 Policy closure — exhaustive surface table (one owner: I7-B)

Measured by enumerating every `src`/`apps` module that names `Capability.` or `Purpose.`
members and classifying each as closed (must change) or feature-local (must not).

| File | Symbol | Change |
|---|---|---|
| `src/my_pa/domain/identity/operation.py` | `Capability` | +7 members (appended) |
| same | `_OPERATOR_ONLY` | + import (comment: attested-local, S3.1 D-16; the handler reuses `attested_lineage_authority`; never satisfiable remotely or over stdio MCP) |
| same | `_PERMITTED_PURPOSES` | import → `{SCHEDULE_IMPORT}`; 6 reads → `{SCHEDULE_READ}` |
| same | `_WRITE_CAPABILITIES`, `_ADDITIVE_WRITE_CAPABILITIES` | + import (both) |
| `src/my_pa/domain/identity/purpose.py` | `Purpose` | `SCHEDULE_IMPORT = "schedule_import"`, `SCHEDULE_READ = "schedule_read"` (appended; D-91 comments) |
| `src/my_pa/domain/policy/decision.py` | `_SCOPELESS` | + 6 reads |
| `src/my_pa/application/authorization.py` | `_requested_scope` | 6 read commands in the empty-scope arm; `case ImportSchedulePublication(): return _scope_of_enrollment(command.enrollment_id, enrollments)` |
| `src/my_pa/application/commands.py` | 7 command classes; `Command` union | +7 |
| `src/my_pa/application/errors.py` | `SafeDetail` | +14 (section 4.5) |
| `src/my_pa/adapters/normalization.py` | `_BUILDERS` | +7 |
| `src/my_pa/application/service.py` | `_HANDLERS`, `_SCHEDULE_CAPABILITIES`, `_SCHEDULE_READ_CAPABILITIES`, `available_capabilities`, ctor, `_schedule_plane`, `_capabilities_get` fallback | section 3.1/3.2; 7 handler methods (stubs answering `unsupported` after the switch gate in I7-B, real in I7-C) |
| `src/my_pa/adapters/mcp/remote.py` | `_WRITE_PURPOSES` | + `SCHEDULE_IMPORT`; `_REMOTE_OPERATOR_IDENTITY_CAPABILITIES` and the `sources.enroll` exception **unchanged** |
| `src/my_pa/adapters/remote_request.py` | `_IDEMPOTENT_REMOTE_CAPABILITIES`, `_SERVER_REPLAY_REMOTE_CAPABILITIES`, `CANONICAL_REMOTE_PURPOSES` | **unchanged** (import excluded; reads have 1 purpose) |
| `src/my_pa/domain/identity/chatllm_capability_policy.py` | `CHATLLM_DATA_PROFILE_VERSION`, `ChatLLMCompositionPrerequisite`, `_DATA_CONDITIONAL`, `_CONTROL_PLANE_EXCLUDED`, `_EXCLUSION_RATIONALE`, `SCHEDULE_DATA_NAMES`, `_prerequisite_of` | `chatllm-data-v11`; `SCHEDULE = "SCHEDULE"`; 6 reads conditional; import excluded with rationale `"operator-only schedule source admission (local operator surface; source designation OD-06)"`; explicit-name rule before prefix rules |
| `src/my_pa/application/chatllm_data_profile.py` | `ChatLLMCompositionPlanes.schedule`, `_prerequisite_holds` | `schedule: bool = False`; `SCHEDULE → planes.schedule` |
| `apps/cli/remote_mcp.py` | `_planes_from_settings` | `schedule=settings.schedule_enabled` |
| `src/my_pa/adapters/mcp/chatllm_gateway.py` | `_FEATURE_BY_FAMILY` | `schedule_series`, `schedule_publications`, `schedule_activities`, `schedule_changes` → `schedule` |
| `src/my_pa/adapters/mcp/tools.py` | `TOOLS` | derived (no edit) |
| `src/my_pa/contracts/mcp_database_profiles.py` | ceilings, opt-ins | **unchanged** (asserted) |
| `src/my_pa/infrastructure/persistence/tables.py` | `_CURRENT_AUDIT_CAPABILITIES` (derived), `worker_plane_is_known` literal | literal widened (3.2) |
| migration #2 | audit + heartbeat CHECKs | section 3.14 |
| `src/my_pa/bootstrap/settings.py`, `bootstrap/gateway.py`, `infrastructure/persistence/unit_of_work.py`, `worker_health.py`, `apps/worker.py` | switch/plane | sections 3.1/3.2 |
| feature-local, unchanged (verified) | `domain/record_events.py` (no Schedule Record Event family; schedule rows emit none), `bootstrap/relationship_intelligence_profiles.py`, `bootstrap/knowledge_discovery_profiles.py`, `application/context/providers.py` (no schedule context plane), `contracts/mcp_database_witness.py`, `application/capabilities.py` (behaviour unchanged; I7-D adds the generic-PDF clarification comment, R2 §8.4), remote grant store `identity.remote_capability_grants` (no closed vocabulary) | — |

### 3.13 ChatLLM, remote, façade, fixtures

#### 3.13.1 ChatLLM (re-measured targets, all derived by the planner)

| Composition (planes) | v10 | v11 |
|---|---|---|
| full (5 flags, no switch) | 164 | 164 |
| default (constraints only) | 98 | 98 |
| full + schedule | — | 170 |
| full + lineage + program + schedule | 198 (without schedule) | 204 |
| default + lineage + program + schedule | 130 (without schedule) | 136 |
| compositions enumerated by `_every_composition` | 256 | 512 |
| `CHATLLM_CAPABILITY_POLICY` size | 233 | 240 |

The planner desires a schedule read exactly when `planes.schedule` (no other plane needed);
never desires import in any composition (`CONTROL_PLANE_EXCLUDED`); an active grant on import
is `UNEXPECTED_CONTROL_PLANE_GRANT` (diff unhealthy). No live `profile-apply`.

#### 3.13.2 Remote

Reads: `read` kind, purpose `schedule_read` not in `_WRITE_PURPOSES`; published to a remote
client only when the switch is on, the process composes the Schedule factory, and the
client holds a grant (existing grant path; nothing granted here). Import: withheld by
`remote_tool_names` (operator-only, in neither exception set), by the façade
(`operator` kind; the compact operator publication admits only the identity-correction names
and `sources.enroll`), by `_IDEMPOTENT_REMOTE_CAPABILITIES` (no remote key path), and by the
handler's local-transport check. Note: every remote OAuth client authenticates as
`PrincipalKind.OPERATOR`, so the operator-only policy check alone would **not** stop a remote
call — the publication and handler layers are the load-bearing guards (tested separately,
section 6.3).

#### 3.13.3 Façade/catalog

`feature_label` → `schedule` for the 7; kinds: 6 `read`, import `operator`; non-null summaries
(3.5); describe lists only eligible names.

#### 3.13.4 MCP database profiles

No schedule name in any ceiling or opt-in; a restricted composition never composes the
factory; asserted by `test_schedule_names_join_no_profile_ceiling_or_opt_in`.

#### 3.13.5 Count pins moved by I7-B (re-measured, lockstep, each with its reason)

`len(Capability)` 233 → 240 in `tests/contract/test_capabilities_and_readiness.py`,
`test_chatllm_capability_policy.py`, `test_cli_transport.py` (`_BUILDERS`),
`test_lineage_s31_capability_admission.py`, `test_lineage_s4_capability_admission.py`,
`test_mcp_transport.py` (`TOOLS`), `test_transport_parity.py`,
`tests/unit/test_constraint_authoring_vocabulary.py`,
`tests/security/test_no_capability_accepts_a_server_owned_field.py`; the ChatLLM class counts in
`tests/contract/test_chatllm_capability_policy.py` (`DATA_CONDITIONAL` 131 → 137,
`CONTROL_PLANE_EXCLUDED` 24 → 25); **not** `tests/schema/test_record_lineage_s3_migration.py`'s
frozen historical literal, which must not move;
`tests/schema/test_project_controls_run01_integrity_migration.py`; `len(Purpose)` 60 → 62 and
the published purpose tail in `test_lineage_s31_capability_admission.py`,
`test_lineage_s4_capability_admission.py`, `test_commitment_v1_strict_client.py`;
`tests/architecture/test_readme_state_claims.py` (implemented 240, withheld families 127,
default 113, with the schedule set as a seventh withheld family); every `chatllm-data-v10`
current-state assertion → v11 (only where it states the current version; P1 history stays);
revision count 124 → 125 and the head literal in every module pinning `6c2306330ceb` as head
(52 test files measured) and in the current-state docs bound by the spelled-count and
readme guards (`README.md`, `docs/architecture/00_ARCHITECTURE_INDEX.md`,
`docs/architecture/system-context.md`, `docs/architecture/module-boundaries.md`,
`docs/plans/mcv-completion-plan.md`, `docs/plans/relationship-intelligence-implementation-plan.md`,
`ops/runbooks/gateway-operations.md`, `ops/runbooks/mcp-and-cli-operations.md`,
`ops/runbooks/managed-knowledge-context.md`, `ops/runbooks/remote-mcp-cloudflare.md`);
any payload/view schema digest the new commands move. The implementer runs the full FAST
tier and every guard, and lists each moved pin old → new.

#### 3.13.6 Web fixture

`web/src/lib/api/decode/fixtures/python/success.json` regenerated from the live dump (7 new
manifest rows); `worker_planes` unchanged (switch off in the fixture composition);
`web/contracts/gateway.json` unchanged (no web route); `npm run lint`, `typecheck`, `test`,
`contract`, `build` in `web/`.

### 3.14 Migration #2

File `migrations/versions/<YYYYMMDD>_<rev>_cpm_workbench_vocabulary.py`, `down_revision =
"6c2306330ceb"`, sole head, imports `alembic.op` and `typing.Final` only.

| Step | upgrade | downgrade |
|---|---|---|
| 1 | `SET LOCAL lock_timeout = '10s'` | same |
| 2 | — | refusal `DO` block: `IF EXISTS (SELECT 1 FROM knowledge.audit_events WHERE capability IN (<7 names>) OR purpose IN ('schedule_import','schedule_read')) OR EXISTS (SELECT 1 FROM knowledge.worker_heartbeats WHERE plane = 'schedule') THEN RAISE EXCEPTION 'cpm workbench vocabulary is in use; refusing to downgrade <rev>' USING ERRCODE = 'restrict_violation'` |
| 3 | restate `capability_is_known` AT (251 literals, sorted) | restate BEFORE (byte copy of `023f8f7eb499`'s AT, 244) |
| 4 | restate `purpose_is_known` AT (62, sorted) | BEFORE (byte copy of `c5260943d933`'s AT, 60) |
| 5 | restate `worker_plane_is_known` AT `plane IN ('capture', 'enrollment', 'reenrichment', 'schedule')` | BEFORE byte copy |

Restating = `DROP CONSTRAINT` + `ADD CONSTRAINT … CHECK` (S3.1/S4 precedent): `ACCESS
EXCLUSIVE` on `audit_events` and `worker_heartbeats` and a validating scan of each, held to
commit; a widening cannot fail on existing rows. No table, column, index, trigger, function,
`GRANT` or `REVOKE`; no row written; no `my_pa` import; literals frozen (not derived). The 7
capability literals (sorted): `schedule_activities.history`, `schedule_activities.list`,
`schedule_changes.list`, `schedule_publications.import`, `schedule_publications.list`,
`schedule_publications.read`, `schedule_series.list`.

Tests (`tests/schema/test_cpm_workbench_vocabulary_migration.py`; `_migration.py` suffix →
`migration_edge` default; `migration_empty_to_head` explicit): static
`test_the_revision_is_the_single_head_on_6c2306330ceb`, `test_the_revision_imports_no_package_module`,
`test_the_revision_writes_no_row_and_grants_nothing`, `test_before_texts_are_byte_copies`,
`test_at_sets_equal_the_live_enums` (251 = 240 + 11; 62); database
`test_empty_to_head_admits_every_schedule_name_and_plane`,
`test_downgrade_refuses_while_schedule_vocabulary_is_used` (3 cases: capability audit row,
purpose audit row, heartbeat), `test_clean_downgrade_restores_the_before_checks_and_reupgrades`,
`test_lock_timeout_is_transaction_local`.

### 3.15 Observability (R2 §40)

No logging or metrics framework exists in the job plane (measured: no `logging` in
`infrastructure/jobs`; the worker prints counts only). v1 therefore adds **no** emitter
(E-05). What is observable, all content-free: publication status/counts and issue counts by
safe code (`schedule_publications.read`); job `state`, `attempt_count`, `last_error_code`
(one of 11 public codes); schedule worker-plane backlog, dead-lettered count and heartbeat
(`capabilities.get`); the worker's existing per-run counts on stdout (claimed, completed,
released, lost). Never emitted anywhere outside the read payloads: Activity IDs/names,
schedule title, raw cells, filenames, locators, paths, PDF bytes, exception text, stack
traces (child `stderr` is `DEVNULL`; `JobExecutionError` carries a code only; issues carry
codes only). FAST guard: no `print`, `logging`, `warnings`, `sys.stderr`/`sys.stdout` write
(except the child's frame write) and no f-string interpolation of a row value into an
exception in the 5 new modules.

### 3.16 Pre-deploy gates (written here, never run in this slice)

`ops/runbooks/cpm-workbench.md` gains "Pre-deploy gates" (S5b-1 §9.3 plus migration #2) and
`ops/postgres/cpm_workbench_predeploy_check.py --phase before|after` (thin runner, connects
with `MY_PA_DATABASE_URL`, `SET TRANSACTION READ ONLY`, prints one status line per check
and no connection string) over `src/my_pa/infrastructure/database/cpm_workbench_predeploy.py`
(every statement a `SELECT` on catalogs or catalog functions):

| Check | Phase | Query (catalog only) | Stop when |
|---|---|---|---|
| P1 default privileges | before | `pg_default_acl` (role, namespace, objtype, acl) | an entry for tables (`r`) in `knowledge` or global names `PUBLIC`, `my_pa_mcp_ro` or `my_pa_mcp_rw` |
| P2 PK premise | before | `pg_constraint` `contype='p'` `conkey` on `knowledge.enrollments`, `knowledge.source_object_versions` | either PK absent or not single-column |
| P3 lock sizing | before | `pg_class.reltuples`, `pg_relation_size` for `enrollments`, `source_object_versions`, `audit_events`, `worker_heartbeats` | — (reported for the operator's quiet-window decision) |
| P4 runtime-role reach | before | `current_user`, `session_user`; owner and `relacl` of `knowledge.record_links` | runtime role neither owner nor default-privileged (stop for enablement, not for schema deploy) |
| P5 ACL snapshot | before/after | SHA-256 of `relacl::text` for `enrollments`, `source_object_versions` | after ≠ before |
| P6 no extra grant | after | `has_table_privilege(<role>, 'knowledge.<t>', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')` for `public`, existing `my_pa_mcp_ro`/`rw` over the 7 tables | any true |
| P7 vocabulary at head | after | `pg_get_constraintdef` of `capability_is_known`, `purpose_is_known`, `worker_plane_is_known` | a schedule name missing |
| P8 runtime reach | after | `has_table_privilege(current_user, …)` on the 7 tables | runtime cannot read/write them |

Tests: FAST `test_predeploy_sql_is_select_only` (parses every statement: `SELECT` only,
no `pg_catalog` write function, `SET TRANSACTION READ ONLY` first); database
`test_predeploy_checks_pass_on_a_clean_scratch_database` and
`test_predeploy_check_reports_a_planted_default_privilege` (scratch cluster only).

*Implementation note I7-D (trivial resolutions):* the module adds a check P0 that reads
`transaction_read_only` and stops unless it is `on`; P5 is one SHA-256 over both tables'
`relacl` text (the `after` phase stops without the `before` digest, passed as
`--before-acl-sha256`); P6 and P8 stop when a CPM table is absent; P8 requires `SELECT` and
`INSERT` on all 7 tables and `UPDATE` on publications, jobs, parser runs and rows (the tables
the worker and import update or lock `FOR UPDATE`); P4's stop is labelled a stop for
enablement in the runbook. Results are `pass`/`stop`/`report` (`CheckStatus.HOLDS`, `STOP`,
`REPORT`); the runner exits 1 on any stop. The database module holds 10 tests (the 2 named
above plus a global and an other-schema default privilege, a planted grant, an ACL change, a
narrowed CHECK, the after-phase stop without a digest, the open-transaction refusal and the
ops runner's output), all on per-test scratch clones.

---

## 4. Symbol inventory

### 4.1 Enums and constants

| Symbol | Module | Value |
|---|---|---|
| `Capability.SCHEDULE_PUBLICATIONS_IMPORT` … `SCHEDULE_CHANGES_LIST` (7) | `domain/identity/operation.py` | section 3.5, appended in table order |
| `Purpose.SCHEDULE_IMPORT`, `Purpose.SCHEDULE_READ` | `domain/identity/purpose.py` | appended |
| `ChatLLMCompositionPrerequisite.SCHEDULE`, `SCHEDULE_DATA_NAMES`, `CHATLLM_DATA_PROFILE_VERSION = "chatllm-data-v11"` | `domain/identity/chatllm_capability_policy.py` | |
| `ScheduleChangeKind` (11, R2 §43.2 order), `DELTA_ALGORITHM_VERSION = "cpm-workbench-full-delta-v1"` | `domain/schedule/compare.py` | |
| `MAX_SCHEDULE_PAGE_SIZE = 100`, `DEFAULT_SCHEDULE_PAGE_SIZE = 25`, `MAX_SCHEDULE_CURSOR_CHARACTERS = 512`, `SCHEDULE_CURSOR_TTL_SECONDS = 300`, `SCHEDULE_CURSOR_VERSION = 1` | `domain/schedule/cursor.py` | |
| `SCHEDULE_HANDLER_BUDGET_SECONDS = 240`, `SCHEDULE_PARSE_RESERVE_SECONDS = 60`, `SCHEDULE_PARSE_MAX_WALL_SECONDS = 150`, `SCHEDULE_PARSE_MIN_WALL_SECONDS = 15`, `SCHEDULE_MIN_LEASE_SECONDS = 300` | `infrastructure/jobs/schedule.py` | |
| `ChildLimits`, `PRODUCTION_CHILD_LIMITS` (address space 1,073,741,824; open files 32; output 134,217,728), `FRAME_MAGIC`, `FRAME_SCHEMA = "cpm-workbench-parse-frame-v1"`, `CHILD_COMMAND`, exit codes `EXIT_MEMORY = 3`, `EXIT_INPUT = 4`, `EXIT_CONTAINMENT = 5`, `EXIT_USAGE = 6` | `infrastructure/jobs/schedule_parser_process.py` (exit codes shared with the child module) | |

### 4.2 Records (frozen slots dataclasses, `__post_init__` invariants)

`domain/schedule/model.py`: `SchedulePlan.source_id` (added, E-03); `ScheduleSourceBinding`
(`source_id, enrollment_id, source_object_id, source_version_id`); `ScheduleSeriesSummary`;
`SchedulePublicationSummary` (publication + effective status + operation id + source
binding); `SchedulePublicationDetail` (publication, effective status, job view, runs,
issue counts, source binding); `ScheduleJobView`; `ScheduleActivityRowView` (row id, stable
id, `ParsedScheduleRow` content); `ScheduleActivityObservation`. `domain/schedule/compare.py`:
`ScheduleComparisonRow`, `ScheduleChange`, `ScheduleChangeSet` (changes, counts).
`domain/schedule/cursor.py`: `ScheduleCursor`, `ScheduleCursorError`. Parent:
`ParsedResult`, `DeterministicFailure`, `TransientFailure` (`IsolatedParse` union),
`ScheduleBudget`.

### 4.3 Ports (`contracts/ports.py`, on `ScheduleRepository`)

```text
owns_project(principal_id, project_id) -> bool
list_series(principal_id, project_id, *, after: tuple[datetime, str] | None, limit) -> tuple[ScheduleSeriesSummary, ...]
list_publications(principal_id, series_id, *, role, status, after: tuple[datetime, str] | None, limit) -> tuple[SchedulePublicationSummary, ...]
get_publication_detail(principal_id, publication_id) -> SchedulePublicationDetail | None
list_activity_rows(principal_id, publication_id, *, row_type, hierarchy_prefix, start_range, finish_range, after: tuple[int, str] | None, limit) -> tuple[ScheduleActivityRowView, ...]
activity_is_visible(principal_id, schedule_activity_id) -> StableScheduleActivity | None
activity_history(principal_id, schedule_activity_id, *, after: tuple[date, datetime, str] | None, limit) -> tuple[ScheduleActivityObservation, ...]
comparison_rows(principal_id, publication_id) -> Iterator[ScheduleComparisonRow]
prior_observations(principal_id, series_id, *, before: tuple[date, datetime, str], schedule_activity_ids: frozenset[str]) -> frozenset[str]
```

`limit` is `page_size + 1`. All on `SqlScheduleRepository` (partitioned, registered module).

### 4.4 Functions and services

`domain/schedule/canonical.py` `parse_result_from_object`; `domain/schedule/compare.py`
`compare_publications(from_rows, to_rows, prior: frozenset[str]) -> ScheduleChangeSet`,
`change_sort_key`; `domain/schedule/cursor.py` `schedule_cursor_binding`, `encode_schedule_cursor`,
`decode_schedule_cursor`; `application/schedules.py` `ScheduleApplication` (`import_publication`,
`list_series`, `list_publications`, `read_publication`, `list_activities`, `activity_history`,
`list_changes`), `schedule_disclosure`, `schedule_import_disclosure`;
`infrastructure/jobs/schedule.py` `process_schedule_publication`;
`infrastructure/jobs/schedule_parser_process.py` `run_isolated_parse`;
`infrastructure/jobs/schedule_parser_child.py` `apply_containment`, `main`;
`infrastructure/persistence/jobs.py` `job_is_effectively_failed`;
`infrastructure/database/cpm_workbench_predeploy.py` `run_predeploy_checks`.

### 4.5 SafeDetail additions (14)

`SERIES_ID = "series_id"`, `SERIES_NAME = "series_name"`, `PUBLICATION_ID = "publication_id"`,
`PUBLICATION_ROLE = "publication_role"`, `BASELINE_KIND = "baseline_kind"`,
`EXPECTED_DATA_DATE = "expected_data_date"`, `SUPERSEDES_PUBLICATION_ID =
"supersedes_publication_id"`, `SCHEDULE_ACTIVITY_ID = "schedule_activity_id"`,
`FROM_PUBLICATION_ID = "from_publication_id"`, `TO_PUBLICATION_ID = "to_publication_id"`,
`CHANGE_KIND = "change_kind"`, `HIERARCHY_PREFIX = "hierarchy_prefix"`, `ROW_TYPE =
"row_type"`, `DATE_RANGE = "date_range"` (none of the 14 values exists at the basis). Reused: `PROJECT_ID`, `ENROLLMENT_ID`,
`SOURCE_OBJECT_ID`, `SOURCE_VERSION_ID`, `IDEMPOTENCY_KEY`, `PAGE_SIZE`, `CURSOR`, `STATUS`,
`MAX_BYTES`.

---

## 5. Work split (4 serial packages)

The orchestrator's recommended order put migration #2 first; it cannot stay green there:
the restated audit CHECK must equal the live enums (`_CURRENT_AUDIT_CAPABILITIES` derives from
them; S5b-1 D-01), and adding the enum members forces handlers (`set(Capability) -
set(_HANDLERS) == set()`), the exhaustive ChatLLM policy and every count pin in the same
commit. So the revision moves with the registrations (E-06).

| Package | Owns (writes only these) | Exit |
|---|---|---|
| **I7-A** worker + isolation | NEW `src/my_pa/infrastructure/jobs/schedule.py`, `schedule_parser_process.py`, `schedule_parser_child.py`; `src/my_pa/domain/schedule/canonical.py` (`parse_result_from_object`), `model.py` (`SchedulePlan.source_id`), `__init__.py`; `src/my_pa/infrastructure/persistence/schedule.py` (`begin_processing` fills `source_id`); `src/my_pa/bootstrap/settings.py` (`schedule_enabled`); `src/my_pa/bootstrap/gateway.py` (factory composition); `src/my_pa/application/service.py` (ctor params only); NEW `tests/unit/test_schedule_parser_isolation.py`, `tests/database/test_cpm_workbench_worker.py`, `tests/architecture/test_cpm_workbench_worker_scope.py` (child import closure, no logging, parent never imports PDFium); `tests/unit/test_settings.py` (switch default); `tests/architecture/test_principal_partition_is_reached_through_the_guard.py` only if registration moves | handler runs end-to-end under `run_worker(…, plane=SCHEDULE_JOBS)` in database tests (no heartbeat); **ruling O-2 condition: I7-A leaves `apps/worker.py`, the heartbeat CHECK (and its `tables.py` literal) and `worker_health.py` untouched**, so the S5b-1 not-runnable guard stays green until I7-B converts it |
| **I7-B** registration + policy closure + migration #2 | every row of section 3.12 except the real handler bodies; NEW migration; `tables.py` (heartbeat literal); `worker_health.py`; `unit_of_work.py`; `apps/worker.py`; `apps/cli/remote_mcp.py`; handler **stubs** (switch gate → `unsupported`, S3 D-37 precedent); converted `tests/architecture/test_cpm_workbench_foundation_scope.py`; NEW `tests/schema/test_cpm_workbench_vocabulary_migration.py`, `tests/contract/test_schedule_policy_closure.py`, `tests/contract/test_schedule_facade_catalog.py`; every pin of 3.13.5; `web/src/lib/api/decode/fixtures/python/success.json` (`git add -f` not needed for a tracked file; verify `git ls-tree`) | full FAST + doc guards + web checks green; 7 names closed on every surface; reads answer `unsupported` |
| **I7-C** behaviour | `src/my_pa/application/schedules.py` (NEW), `src/my_pa/domain/schedule/compare.py` (NEW), `cursor.py` (NEW), `model.py` (read records), `src/my_pa/contracts/ports.py` (read methods), `src/my_pa/infrastructure/persistence/schedule.py` (read methods), `jobs.py` (`job_is_effectively_failed`), `src/my_pa/application/service.py` (7 handler bodies), `src/my_pa/application/disclosure.py` only if the builder lives there; NEW `tests/unit/test_schedule_compare.py`, `tests/unit/test_schedule_cursor.py`, `tests/unit/test_schedule_commands.py`, `tests/database/test_schedule_capabilities.py`, `tests/integration/test_schedule_compact_facade.py`, `tests/database/test_cpm_workbench_change_performance.py` | section 6 rows marked I7-C green |
| **I7-D** WP-04 assurance | NEW `docs/architecture/cpm-workbench.md`, `ops/runbooks/cpm-workbench.md`, `docs/decisions/ADR-016-cpm-workbench-schedule-evidence.md` (+ index row), `src/my_pa/infrastructure/database/cpm_workbench_predeploy.py`, `ops/postgres/cpm_workbench_predeploy_check.py`, `tests/security/test_cpm_workbench_security.py`, `tests/database/test_cpm_workbench_predeploy.py`; `src/my_pa/application/capabilities.py` and `src/my_pa/domain/extraction/text.py` (comments only, R2 §8.4); `docs/architecture/00_ARCHITECTURE_INDEX.md`, `system-context.md`, `module-boundaries.md`, `docs/00_REPOSITORY_SOURCE_INDEX.md`, `ops/runbooks/README.md`, `ops/postgres/README.md`; this contract's section 7 table filled with executed results; `tests/ci_shard_weights.json` (`python -m tests.ci_shard weigh` from JUnit XML of the fast and migration lanes; S5a, S5b-1, S5b-2 modules; keep `verify` green and shard 1 no heavier than today); a FAST guard `test_the_s5b2_contract_crosswalk_names_tests_that_exist` | doc/count/link guards green; §45 table honest |

Order: I7-A → I7-B → I7-C → I7-D, each from the previous head. Only I7-B writes migrations,
registries, count pins and the web fixture. No package edits the S5b-1 revision or S5a parser
modules.

---

## 6. Test plan and crosswalk

### 6.1 Modules

| Module | Tier | Package |
|---|---|---|
| `tests/unit/test_schedule_parser_isolation.py` | FAST (Linux-only cases skip on macOS with reason) | I7-A |
| `tests/database/test_cpm_workbench_worker.py` | `database` | I7-A |
| `tests/architecture/test_cpm_workbench_worker_scope.py` | FAST | I7-A (+ I7-D crosswalk test) |
| `tests/architecture/test_cpm_workbench_foundation_scope.py` (converted) | FAST | I7-B |
| `tests/schema/test_cpm_workbench_vocabulary_migration.py` | static FAST + `migration_edge` / `migration_empty_to_head` | I7-B |
| `tests/contract/test_schedule_policy_closure.py`, `test_schedule_facade_catalog.py` | FAST | I7-B |
| `tests/unit/test_schedule_compare.py`, `test_schedule_cursor.py`, `test_schedule_commands.py` | FAST | I7-C |
| `tests/database/test_schedule_capabilities.py` | `database` | I7-C |
| `tests/integration/test_schedule_compact_facade.py` | `database` | I7-C |
| `tests/database/test_cpm_workbench_change_performance.py` | `database`, `slow` | I7-C |
| `tests/security/test_cpm_workbench_security.py` | FAST | I7-D |
| `tests/database/test_cpm_workbench_predeploy.py` | `database` | I7-D |

### 6.2 R2 clause → tests

| R2 | Tests (module: function) |
|---|---|
| §9.1, AC-003 | commands: `test_import_accepts_exactly_the_contract_fields`, `test_import_refuses_path_locator_filename_and_body_fields` (parametrized unknown keys), `test_import_requires_exactly_one_of_series_id_and_name`, `test_import_requires_a_source_version` |
| §9.2–§9.3, AC-004 | policy closure: `test_import_is_operator_only_write_additive_with_one_purpose`, `test_import_scope_is_its_own_enrollment_source`; capabilities: `test_import_with_another_principals_enrollment_is_denied_and_writes_nothing`, `test_import_admission_refusals_map_to_safe_errors` (parametrized over the 14 refusals), `test_import_over_stdio_mcp_is_denied_and_writes_nothing` (through `adapters/mcp/server.py`'s local composition), `test_import_without_an_attested_surface_is_denied` (service invoked with `LOCAL`, no `operator_surface`), `test_import_from_cli_and_http_gateway_is_admitted` |
| §9.4, AC-006 | worker: `test_version_change_at_metadata_fails_before_parsing`, `test_version_change_at_fetch_fails_before_parsing`, `test_truncated_fetch_is_source_too_large`, `test_provider_unavailable_is_transient_and_exhausts_to_effective_failed`, `test_provider_read_holds_no_transaction` (asserts no open transaction on the schedule UoW connection during the fake provider call) |
| §10.1–§10.4, §23, AC-025 | capabilities: `test_import_replays_and_conflicts_per_section_23` (S5b-1 table through the capability), `test_import_creates_one_job` |
| §10.6, §22, AC-026 | worker: `test_deterministic_failure_completes_the_job_and_fails_the_publication` (parametrized over every deterministic row of 3.3.2), `test_transient_failure_releases_and_retries`; capabilities: `test_exhausted_job_reads_effective_failed_without_writing` |
| §24, AC-030 | worker: `test_every_phase_refuses_after_lease_loss` (lease expired before each of H1/H3/H5/H6/H7/H8), `test_no_write_after_lease_loss`, `test_lease_loss_is_counted_lost_not_released`, `test_reclaimed_attempt_reuses_the_parsed_run`, `test_reclaimed_reparse_digest_must_equal_the_reused_run`, `test_running_run_of_this_attempt_with_stored_rows_is_an_invariant_breach`, `test_reclaimed_attempt_after_terminal_completes_without_writing` |
| §25 budget | worker: `test_budget_checkpoints_fail_with_processing_budget_exceeded` (fake clock at each checkpoint), `test_parse_is_not_spawned_with_less_than_the_minimum_wall` |
| §25, AC-029 | foundation scope: `test_schedule_plane_is_runnable_on_all_four_surfaces`; worker scope: `test_worker_refuses_the_schedule_plane_while_disabled`, `test_worker_refuses_a_lease_shorter_than_three_hundred_seconds`; capabilities: `test_capabilities_get_reports_the_schedule_plane_only_when_enabled`; façade e2e (through `build_gateway_runtime`, FR7-F02): `test_gateway_composition_discloses_the_schedule_plane_only_with_the_switch` |
| U-05, §35 | isolation: every row of 3.4.8 (`test_decompression_bomb_fails_closed_on_linux`, `test_page_count_bound_through_the_child`, `test_deep_nesting_fails_closed`, `test_wall_timeout_is_processing_budget_exceeded`, `test_hung_child_is_killed_and_reaped`, `test_native_crash_is_parser_exception`, `test_external_kill_is_transient`, `test_oversized_output_is_bounds_exceeded`, `test_malformed_frame_is_transient`, `test_frame_for_other_bytes_is_transient`, `test_child_environment_is_scrubbed`, `test_containment_refuses_network_spawn_and_write`, `test_child_rlimits_are_set`, `test_containment_reports_the_memory_cap_per_platform`, `test_child_parse_equals_in_process_parse` (under `PRODUCTION_CHILD_LIMITS`), `test_largest_golden_parses_under_production_limits`, `test_benign_document_parses_under_the_bomb_cap`, `test_child_address_space_has_headroom` (Linux-only), `test_child_command_applies_the_address_space_cap_on_linux`, `test_bounds_maximal_synthetic_is_at_or_near_every_production_cap`, `test_page_dimensions_are_strictly_increasing` (FR7-F03), `test_text_flood_outlasts_the_wall_and_ends_processing_budget_exceeded` (FR7-F04)); worker scope: `test_child_import_closure_has_no_network_or_database_module`, `test_the_worker_parent_never_imports_pdfium` |
| §29, AC-028 | compare: `test_each_change_kind` (11 cases), `test_reintroduced_replaces_added`, `test_sign_convention`, `test_no_number_is_fabricated_for_non_value_states`, `test_marker_and_provenance_only_differences_emit_nothing`, `test_merge_is_single_pass` (counts comparisons ≤ 2N), `test_ordering_and_counts_by_kind`; capabilities: `test_changes_pagination_is_stable_across_pages`, `test_changes_eligibility_refusals`; performance: `test_change_scan_of_25000_rows_meets_the_target` |
| §30, AC-027 | commands: `test_role_is_required_and_baseline_kind_follows_it`; capabilities: `test_series_latest_update_ignores_baselines_and_references`, `test_first_publication_is_not_a_baseline`; worker scope: `test_no_baseline_is_derived` |
| §31, AC-031 | policy closure: `test_every_closed_surface_classifies_the_seven` (one assertion per surface of 3.12), `test_reads_are_scopeless_and_import_is_not`, `test_unchanged_surfaces_are_unchanged` |
| §31.3–§31.4, AC-032 | policy closure: `test_every_data_required_policy_is_always_composed` (every `DATA_REQUIRED` policy has prerequisite `ALWAYS`; ruling O-1), `test_v11_reads_are_data_conditional_under_schedule`, `test_import_is_control_plane_excluded`, `test_v11_targets`, `test_planner_desires_schedule_reads_only_with_the_switch`, `test_active_import_grant_is_unexpected_control_plane`, `test_import_is_never_remote_published` (default, `remote.operator`, compact operator), `test_import_is_not_remote_idempotent`, `test_schedule_names_join_no_profile_ceiling_or_opt_in`; capabilities: `test_remote_import_is_unsupported_even_for_an_operator_principal`, `test_remote_read_without_grant_is_unsupported` |
| §32, AC-033 | cursor: `test_round_trip`, `test_length_bound`, `test_ttl`, `test_binding_covers_every_field` (parametrized: capability, principal, purpose, each filter, pair ids, page size, order), `test_forged_position_reads_nothing_unauthorized`; capabilities: `test_page_of_100_and_101_rows`, `test_cursor_conflicts` |
| §32.8 | capabilities: `test_disclosure_per_read` (scope, coverage, trust, references, truncation, and the empty-P `eligible`/0 case for each read) |
| U-03 | capabilities: `test_orphan_stable_activity_is_not_found_like_absent`, `test_history_never_reports_created_at` |
| RR1-I01 | capabilities: `test_issue_counts_are_limited_to_the_accepted_run` |
| §35 cross-Principal | capabilities: `test_cross_principal_roots_are_not_found_identically` (every read, every root) |
| §36 | performance module; isolation `test_child_parse_equals_in_process_parse` timing recorded |
| §40, AC-034 | security: `test_errors_carry_no_content`, `test_job_error_is_a_public_code`, `test_new_modules_neither_log_nor_print`, `test_child_stderr_is_discarded` |
| §31.5 catalog | catalog: `test_every_schedule_capability_has_a_catalog_entry` (non-null summary, feature `schedule`), `test_schedule_facade_kinds_are_deliberate` |
| §31.5 façade | façade e2e: `test_describe_lists_exactly_the_eligible_schedule_reads`, `test_read_wrapper_invokes_schedule_reads_strictly`, `test_import_is_absent_from_every_publication`, `test_switch_off_hides_every_schedule_name`, `test_profile_service_composes_no_schedule_capability`, `test_manifest_and_web_fixture_agree_for_schedule`, `test_a_chatllm_client_with_v11_grants_reaches_the_reads` |
| §19, AC-036 | migration module (3.14) |
| §16.15/U-09 surfaced | capabilities: `test_failed_version_reimport_is_a_source_version_conflict` |
| §20, AC-024 | worker: `test_served_facts_trace_to_source_job_parser_and_cell` |
| §3.16 gates | predeploy tests (3.16) |

### 6.3 Prove-red (break exactly one guard; the named test must fail for that reason; revert)

| # | Mutation | Must fail |
|---|---|---|
| Q01 | `available_capabilities`: drop the schedule subtraction | `test_switch_off_withholds_and_refuses_every_schedule_capability` |
| Q02 | one handler: drop `_schedule_plane()` (7 runs) | same, `[<capability>]` |
| Q03 | `Settings.schedule_enabled` default `True` | `test_schedule_switch_defaults_off` |
| Q04 | `apps/worker.py`: drop the disabled-plane refusal | `test_worker_refuses_the_schedule_plane_while_disabled` |
| Q05 | `apps/worker.py`: drop the lease minimum | `test_worker_refuses_a_lease_shorter_than_three_hundred_seconds` |
| Q06 | remove `schedule` from each of the 4 surfaces (4 runs) | `test_schedule_plane_is_runnable_on_all_four_surfaces` (message names the surface) |
| Q07 | service fallback names `schedule` unconditionally | same test, surface 4 polarity |
| Q08 | `_OPERATOR_ONLY`: drop import | `test_import_is_operator_only_write_additive_with_one_purpose`, `test_import_is_never_remote_published` |
| Q09 | `_PERMITTED_PURPOSES`: add `schedule_read` to import | `test_import_is_operator_only_write_additive_with_one_purpose` |
| Q10 | `_WRITE_CAPABILITIES` / `_ADDITIVE_WRITE_CAPABILITIES`: drop import (2 runs) | same |
| Q11 | `_SCOPELESS`: drop one read (6 runs) | `test_reads_are_scopeless_and_import_is_not` and the matching capability test (`scope_not_authorized`) |
| Q12 | `_SCOPELESS`: add import | `test_reads_are_scopeless_and_import_is_not` |
| Q13 | `_requested_scope`: import returns `frozenset()` | `test_import_scope_is_its_own_enrollment_source` |
| Q14 | `_requested_scope`: import reads the enrollment row directly (any Principal) | `test_import_with_another_principals_enrollment_is_denied_and_writes_nothing` — its fixture gives both Principals enrollments on the **same** `source_id`, so the held-scope rule (`requested ⊆ authorized`) cannot mask the break; the test asserts the audited `denied` from authorization (R7-F06) |
| Q15 | `_WRITE_PURPOSES`: drop `SCHEDULE_IMPORT` | `test_every_closed_surface_classifies_the_seven[remote_write]` |
| Q16 | add import to `_REMOTE_OPERATOR_IDENTITY_CAPABILITIES` (then, separately, to the compact operator exception) — 2 runs | `test_import_is_never_remote_published[<profile>]` |
| Q17 | add import to `_IDEMPOTENT_REMOTE_CAPABILITIES` | `test_import_is_not_remote_idempotent` |
| Q18b | import handler: drop the `attested_lineage_authority` call | `test_import_over_stdio_mcp_is_denied_and_writes_nothing`, `test_import_without_an_attested_surface_is_denied` |
| Q18 | import handler: drop the remote-composition check | `test_remote_import_is_unsupported_even_for_an_operator_principal` (invoked on the service directly; the publication layer would mask it) |
| Q19 | one read handler: drop `require_read_grant` (6 runs) | `test_remote_read_without_grant_is_unsupported[<capability>]` |
| Q20a | ChatLLM: move one read to `_DATA_REQUIRED` (class only; it stays in `SCHEDULE_DATA_NAMES`) | `test_v11_reads_are_data_conditional_under_schedule`, `test_every_data_required_policy_is_always_composed` |
| Q20b | ChatLLM: drop one read from `SCHEDULE_DATA_NAMES` (prerequisite becomes `ALWAYS`) | `test_planner_desires_schedule_reads_only_with_the_switch` |
| Q21 | ChatLLM: import moved to `DATA_CONDITIONAL` | `test_import_is_control_plane_excluded`, `test_active_import_grant_is_unexpected_control_plane` |
| Q22 | `_prerequisite_holds`: `SCHEDULE` returns `True` | `test_planner_desires_schedule_reads_only_with_the_switch` |
| Q23 | `CHATLLM_DATA_PROFILE_VERSION` left at v10 | `test_v11_targets` |
| Q24 | `_FEATURE_BY_FAMILY`: drop one family (4 runs) | `test_every_schedule_capability_has_a_catalog_entry` |
| Q25 | add a schedule read to `MCP_PROFILE_OPT_IN_READ_CAPABILITIES` | `test_schedule_names_join_no_profile_ceiling_or_opt_in` |
| Q26 | gateway composes the factory also with an injected `data_engine` | `test_profile_service_composes_no_schedule_capability` |
| Q27 | handler: drop the `ScheduleLeaseLostError → LeaseLostError` translation | `test_lease_loss_is_counted_lost_not_released` (asserts the `run_worker` outcome `lost`, not `released`/`internal_error`; R7-F06) |
| Q28 | handler skips the budget check before H6 | `test_budget_checkpoints_fail_with_processing_budget_exceeded[H6]` |
| Q29 | 3.3.2: classify `VersionChangedError` transient | `test_version_change_at_fetch_fails_before_parsing` |
| Q30 | 3.3.2: classify `ProviderError` deterministic | `test_provider_unavailable_is_transient_and_exhausts_to_effective_failed` |
| Q31 | 3.4.6: map native crash to transient | `test_native_crash_is_parser_exception` |
| Q32 | 3.4.6: map external `SIGKILL` deterministic | `test_external_kill_is_transient` |
| Q33 | drop the output cap | `test_oversized_output_is_bounds_exceeded` |
| Q34 | drop the parent wall kill | `test_hung_child_is_killed_and_reaped` (bounded by its own test timeout) |
| Q35 | `env = os.environ.copy()` | `test_child_environment_is_scrubbed` |
| Q36 | drop each rlimit (CORE, FSIZE, NOFILE, CPU, AS) — 5 runs | `test_child_rlimits_are_set[<limit>]` (AS: Linux only — "CI-only, not executed on the implementation host" unless a Linux host is used, R7-F01) |
| Q37 | drop the audit hook | `test_containment_refuses_network_spawn_and_write` |
| Q38 | decoder skips the canonical round-trip check | `test_non_canonical_frame_is_transient` — concrete frame: a row whose derived `bbox_normalized` is tampered (*implementation note I7-A*: the originally named `original_duration.value` of `"1.50"` is refused by the domain constructor itself, so it cannot isolate the round trip; `bbox_normalized` is read by nothing but the round trip) |
| Q39 | decoder skips the digest/size equality | `test_frame_for_other_bytes_is_transient` |
| Q40 | child imports `sqlalchemy` (planted) | `test_child_import_closure_has_no_network_or_database_module` |
| Q41 | handler imports `my_pa.infrastructure.schedule.pdf` | `test_the_worker_parent_never_imports_pdfium` |
| Q42 | cursor binding omits one field (one run per field) | `test_binding_covers_every_field[<field>]` |
| Q42b | changes cursor accepts an offset beyond the list | `test_cursor_conflicts[offset_out_of_range]` |
| Q43 | cursor TTL check removed | `test_ttl` |
| Q44 | cursor length bound removed | `test_length_bound` |
| Q45 | one read drops `_mine` on its root lookup (6 runs) | `test_cross_principal_roots_are_not_found_identically[<read>]` |
| Q46 | history ignores the accepted-run/complete-partial join | `test_orphan_stable_activity_is_not_found_like_absent` |
| Q47 | publication read counts every issue for a complete publication | `test_issue_counts_are_limited_to_the_accepted_run` |
| Q48 | compare: `added` instead of `reintroduced` | `test_reintroduced_replaces_added` |
| Q49 | compare: `from − to` | `test_sign_convention` |
| Q50 | compare: delta computed when a side is not `published_value` | `test_no_number_is_fabricated_for_non_value_states` |
| Q51 | compare: drop each kind's rule (11 runs) | `test_each_change_kind[<kind>]` |
| Q52 | `latest_update` admits role `baseline` | `test_series_latest_update_ignores_baselines_and_references` |
| Q53 | import role defaults to `update` | `test_role_is_required_and_baseline_kind_follows_it` |
| Q54 | migration: drop each downgrade refusal clause (3 runs) | `test_downgrade_refuses_while_schedule_vocabulary_is_used[<case>]` |
| Q55 | migration: AT capability set missing one name (7 runs) | `test_at_sets_equal_the_live_enums` |
| Q56 | migration: BEFORE text edited by one character | `test_before_texts_are_byte_copies` |
| Q57 | migration: add `GRANT SELECT … TO PUBLIC` | `test_the_revision_writes_no_row_and_grants_nothing` |
| Q58 | heartbeat CHECK at head lacks `schedule` | `test_empty_to_head_admits_every_schedule_name_and_plane` |
| Q59 | predeploy: add an `UPDATE` statement | `test_predeploy_sql_is_select_only` |
| Q60 | `print(row.activity_name)` planted in the handler | `test_new_modules_neither_log_nor_print` |
| Q61 | handler: skip the `parse_result_sha256` equality check on a reused `parsed` run | `test_reclaimed_reparse_digest_must_equal_the_reused_run` (R7-N1) |

A prove-red that stays green is reported as redundancy, a masked test or an unreachable
hazard, never as "covered" (for example Q08's second test is expected to be layered behind
the first). A row whose test skips on the implementation host (Linux-only memory rows: the
bomb, its positive controls, Q36[AS]) is reported "CI-only, not executed on the
implementation host", never as a red proof, unless a Linux host is actually used. Per the
R7 F01 practicality ruling, the implementer on macOS runs every non-Linux-gated isolation test
and its prove-red locally (parity under production limits with AS not in force, CPU, wall,
`FSIZE`, `NOFILE`, environment, audit hook, frame and kill cases) and reports the Linux-only
rows (the headroom test, both positive controls, the bomb, Q36[AS]) in this table, in section
7 (AC-007 memory) and in the handoff as "CI-only, not executed on the implementation host —
pending the PR's ubuntu CI run", with no red proof and no pass claimed.

### 6.4 Commands (foreground, chunked, `PYTHONPATH=src`, `~/my-pa/.venv/bin/python`)

FAST over new and touched modules then the full FAST selection in chunks; `-m "database and
not migration_edge and not migration_empty_to_head and not migration"` over the new database
modules; `-m migration_empty_to_head` and `-m migration_edge` over the migration modules; the
full `tests/architecture`; `ruff check .`; `ruff format --check .` (formats Markdown Python
fences too); `mypy` (current and the floor venv); `python -m tests.ci_shard verify --lane
fast --shards 3 -m "<FAST expression>"` and the migration lane; web checks in I7-B. Homebrew
`postgres@15` scratch cluster (`initdb --auth=trust`, loopback, `PGTZ=UTC`, no inline
password), removed at the end.

---

## 7. R2 §45 acceptance criteria (executed results, I7-D)

Executed by worker I7-D on 2026-10-31 on the implementation host (macOS, Python 3.12.13,
Homebrew PostgreSQL 15.15 scratch cluster on loopback, `PGTZ=UTC`, synthetic data only), over
the code of the final S5b-2 head (the commits after the run change documents, count pins and
`tests/ci_shard_weights.json` only). Whole-tier results of that run: FAST 38,400 collected —
38,257 passed, 136 skipped (macOS-only and Linux-only skips; CI states 74), 7 failed, all 7
count/prose pins this package then re-measured (5) or rephrased (1) and a head-pin list the
security module's migration path tripped (1), each re-run green after the fix; the full FAST
selection re-run at the I7-D head (after those fixes): 38,400 collected — 38,264 passed, 136
skipped, 0 failed; and at the FR7-corrective head: 38,407 collected — 38,269 passed, 138
skipped (the 2 new bounds-maximal Linux-only nodes), 0 failed, with the façade end-to-end
database module 11 passed (the 2 new gateway-composition cases included); database tier
(`database or recovery or e2e`) 5,312 collected — 5,294 passed, 15 skipped, 2 failed, 1 failed
then fixed and re-run green (table note b); migration lanes (`migration_edge or migration`,
1,683, and `migration_empty_to_head`, 20) 1,703 passed. A count is the executed node count of
the named tests (parametrized cases counted). "CI-only" means skipped on this host and
**not** executed here; it is never counted as a pass.

| AC | Criterion (R2 §45, abridged) | Tests | Executed result |
|---|---|---|---|
| 001 | neutral naming | `test_schedule_files_carry_no_denylisted_token`, `test_generated_fixtures_carry_no_denylisted_token` (S5a), `test_s5b2_files_carry_no_denylisted_token` (S5b-2 sources, tests, docs) | met — 3 passed |
| 002 | no XER/XML/P6 runtime | `test_no_prohibited_dependency_is_imported` (every `src/my_pa` module, the 7 S5b-2 modules included), `test_no_xer_or_xml_runtime_in_the_schedule_plane` | met — 451 + 1 passed |
| 003 | one PDF object + exact version only | 6.2 §9.1 row | met — 23 passed |
| 004 | own-enrollment scope, operator-only, structural admission | 6.2 §9.2 row; S5b-1 composite-FK tests in `tests/database/test_cpm_workbench_schema_guards.py` | met — 20 passed (+ the S5b-1 module, 199 passed). Note: 2 admission refusals (`ENROLLMENT_NOT_FOUND`, `SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION`) are unreachable through the capability (earlier checks refuse first) and are proved at the repository layer only (I7-C) |
| 005 | generic extraction unchanged | `test_generic_extraction_still_excludes_pdf`; comment-only clarification in `src/my_pa/application/capabilities.py` and `src/my_pa/domain/extraction/text.py` | met — 1 passed |
| 006 | provider read outside a transaction, version recheck | 6.2 §9.4 row | met — 10 passed |
| 007 | bounds and corrupt/encrypted/image-only fail closed | S5a `test_corrupt_encrypted_and_image_only_fail_closed`, `test_production_limits_are_the_r2_bounds`, `test_bounds_variants_only_tighten_production_limits`, goldens; through the child: `test_page_count_bound_through_the_child`, `test_wall_timeout_is_processing_budget_exceeded`, `test_hung_child_is_killed_and_reaped`, `test_oversized_output_is_bounds_exceeded`, `test_deep_nesting_fails_closed`, `test_child_rlimits_are_set` | **partially met.** CPU/time/page/output/descriptor/file-write bounds met — all passed (`test_child_rlimits_are_set` 4 of 5 cases). The **memory** sub-criterion is **CI-only, not executed on the implementation host — pending the PR's ubuntu CI run**: `test_child_address_space_has_headroom[largest_golden]`, `[bounds_maximal]`, `test_largest_golden_parses_under_production_limits[largest_golden]`, `[bounds_maximal]`, `test_benign_document_parses_under_the_bomb_cap`, `test_decompression_bomb_fails_closed_on_linux`, `test_child_rlimits_are_set[RLIMIT_AS-expected4]` (7 skipped here; operator gate 6). The bounds-maximal case (23,250 rows, FR7-F01) was added after FR7 found the rows ran on the 86-page golden only (about 5× headroom). **Risk, disclosed:** FR7 extrapolated linearly from macOS child RSS (33 MiB at 10 rows, 105 MiB at 3,408 rows) to about 560 MiB RSS at 25,000 rows, above the 512 MiB the 2× rule allows; that is an extrapolation, not a measurement. **Non-Linux observation only (macOS, no address-space cap, `ru_maxrss` of the probe child, not `VmPeak`):** the bounds-maximal parse peaked at 440 MiB RSS (frame 42,876,908 bytes, 11.4 s); the positive-control body took 29.1 s and parsed `complete` with parity. Linux `VmPeak` is virtual and higher than RSS, so the 2× rule may fail in CI. If it does, the cap is re-derived (≥ 2 × `VmPeak`, ≤ any container memory limit) or the admitted bound is reduced (R2 §36) **before merge**; the cap value is not changed on extrapolation alone. The bomb's Linux failure code stays unmeasured until CI reports it. The flood row (U2-13) is met: 1 passed |
| 008 | PDFium sole engine, confined | `test_a_confined_dependency_is_imported_only_where_it_belongs`, `test_every_confined_dependency_is_actually_used_there`, `test_the_worker_parent_never_imports_pdfium` | met — 451 + 1 + 1 passed |
| 009–019 | profile geometry, chart clip, watermark, grouping, wrap, header, page coherence, missing ID, durations, row type, hierarchy | S5a suites `tests/unit/test_schedule_full_goldens.py` (`test_every_case_matches_its_golden` and 24 more), `tests/unit/test_schedule_full_profile.py`, `tests/unit/test_schedule_full_pdf.py`, `tests/unit/test_schedule_model.py` (unchanged parser); child parity `test_child_parse_equals_in_process_parse` | met — 329 + 56 + 103 + 100 passed; parity 65 passed |
| 020–023 | exact-ID identity, identity gate, immutability, cell states | S5b-1 `tests/database/test_cpm_workbench_schema_guards.py`, `tests/database/test_cpm_workbench_persistence.py`, `tests/unit/test_schedule_foundation_domain.py`; through the worker: 6.2 §24 and §20 rows | met — 199 + 81 + 30 passed |
| 024 | every served fact traces to source, job, parser and cell | `test_served_facts_trace_to_source_job_parser_and_cell` | met — 1 passed |
| 025 | idempotency/supersession/source-version reuse | 6.2 §10/§23 row; `test_failed_version_reimport_is_a_source_version_conflict`; S5b-1 `test_failed_version_cannot_be_reimported_into_its_series` | met — 2 + 1 + 3 passed |
| 026 | truthful persisted/effective status, no repair on read | 6.2 §10.6 row | met — 17 passed |
| 027 | explicit baselines | 6.2 §30 row | met — 4 passed |
| 028 | on-demand O(N) delta, 11 kinds, `to − from` | 6.2 §29 row (with `test_change_scan_of_25000_rows_meets_the_target`: 0.709 s for 25,000 rows per side against 5 s, I7-C) | met — 23 passed |
| 029 | JobPlane reused, plane on every surface | 6.2 §25 row | met — 5 passed |
| 030 | §24 boundaries, lease recheck on every write | 6.2 §24 row; budget row | met — 13 + 8 passed |
| 031 | 7 capabilities and 2 purposes closed on every surface | 6.2 §31 row; catalog and façade rows | met — 19 + 8 + 9 passed |
| 032 | ChatLLM classification, import excluded, remote not widened | 6.2 §31.3 row | **met with deviation E-02** (R7 ruling O-1): reads are `DATA_CONDITIONAL` under `SCHEDULE` in `chatllm-data-v11`, not R2's `DATA_REQUIRED` in v4 — 18 passed. "No live grant/profile apply" holds because nothing in the repository applies one |
| 033 | bounded pages, 512-character 300 s request-bound cursors | 6.2 §32 row | met — 20 passed |
| 034 | no content in errors/logs/metrics | 6.2 §40 row (`test_errors_carry_no_content`, `test_job_error_is_a_public_code`, `test_new_modules_neither_log_nor_print`, `test_child_stderr_is_discarded`); `test_new_worker_modules_neither_log_nor_print` | met — 4 + 1 passed. No metrics emitter exists (E-05) |
| 035 | no cross-domain link, frontend, legacy write or generic-PDF widening | `test_no_cross_domain_link_frontend_or_legacy_write`, `test_generic_extraction_still_excludes_pdf` | met — 1 + 1 passed |
| 036 | migration | S5b-1 `tests/schema/test_cpm_workbench_migration.py` and section 3.14's `tests/schema/test_cpm_workbench_vocabulary_migration.py` (static, `migration_edge`, `migration_empty_to_head`) | **met with deviation** S5b-1 D-03 (CPM spans 2 revisions) — 33 + 20 passed; whole migration lanes 1,703 passed |
| 037 | synthetic goldens, quality and performance gates; real corpus | `test_quality_gates_hold_over_every_case`, `test_every_case_matches_its_golden`, performance `test_change_scan_of_25000_rows_meets_the_target` | **synthetic part met** — 1 + 77 + 1 passed; the authorized real-corpus evaluation (R2 §39, S5a U-01) is **operator-gated, not executed**: no real PDF exists here |
| 038 | current-state docs re-derived, no deployment claim | `docs/architecture/cpm-workbench.md`, `ops/runbooks/cpm-workbench.md`, ADR-016, the indexes; guards `test_claimed_test_counts_match_collection.py`, `test_spelled_counts_match_the_sets_they_name.py`, `test_entity_plane_prose_matches_the_capability_sets.py`, `test_readme_state_claims.py`, `test_the_s5b2_contract_crosswalk_names_tests_that_exist` | met — each guard green after the I7-D re-measurement (the 7 FAST failures above). ChatLLM state is v11 (E-02), not R2's v4 |
| pre-deploy | section 3.16 gates | `test_predeploy_sql_is_select_only`, `tests/database/test_cpm_workbench_predeploy.py` (10, scratch clones only) | written and tested — 1 + 10 passed; **never run against any real database** (operator gate 2) |

Table notes. (a) The 2 database failures are `tests/contract/test_health_probe.py::test_a_database_at_head_reports_ready_and_exits_zero` and `::test_a_database_one_revision_behind_names_what_it_is_and_what_head_is`, which assert a PostgreSQL 17 server (`server_version` starts with `17.`); the host cluster is 15.15, so they are environmental and pass only on the CI image `postgres:17`; the 15 skips are `tests/database/test_mcp_database_profiles.py` cases that run only in CI's dedicated MCP-profile step. Neither is CPM code. (b) `tests/database/test_knowledge_remote_grants.py::test_profile_apply_installs_the_create_grant_with_its_purpose` failed (`SimpleNamespace` settings stub lacked `schedule_enabled`, which I7-B's `_planes_from_settings` now reads); I7-D added the field to the stub and the module re-ran 34 passed.

---

## 8. Deviations, residuals, operator gates, open questions

### 8.1 Deviations from R2 (E-xx; S5b-1 keeps D-xx)

| ID | R2 | S5b-2 | Reason |
|---|---|---|---|
| E-01 | §8.5: Schedule factory composed unconditionally, no feature flag | default-off `MY_PA_SCHEDULE_ENABLED`; factory only with the switch and without a restricted `data_engine` | brief; lineage/program precedent; profile roles hold no CPM privilege |
| E-02 | §31.2/§31.3 reads `DATA_REQUIRED`, `chatllm-data-v4`; the S5b-2 brief: "six reads DATA_REQUIRED behind a new composition prerequisite/switch following the lineage/program precedent" | `DATA_CONDITIONAL` under prerequisite `SCHEDULE`, `chatllm-data-v11` | a switch-gated name is conditional in this repo (all 74 `DATA_REQUIRED` names are `ALWAYS`; every gated plane, including the cited lineage/program precedent, is `DATA_CONDITIONAL`); v10 is current. **R7 ruling O-1: UPHELD** — the brief's substantive instruction (a new prerequisite, a default-off switch, the lineage/program precedent) is met in full; the literal `DATA_REQUIRED` contradicts that precedent. Guarded by the FAST invariant `test_every_data_required_policy_is_always_composed` |
| E-03 | §43.3 `SchedulePlan` (S5b-1 §5.2 fields) | adds `source_id` | the provider is selected by source; read in the same plan transaction |
| E-04 | §8.1 parser runs inside the worker | parser runs in a contained child process | S5a U-05/U-12 |
| E-05 | §40 events/metrics vocabulary | no emitter; persisted counters, job state and plane health only | no logging/metrics sink exists in the job plane; adding one is a separate design |
| E-06 | §44 WP-03 order, orchestrator plan (migration first) | migration #2 lands with the registrations (I7-B) | audit CHECK must equal the live enums (S5b-1 D-01) |
| E-07 | §32.5 activities list "rows" | only `activity`/`milestone` rows; summaries appear in `hierarchy_path` | the output names a Stable Activity per row; complete/partial runs hold no ambiguous rows |
| E-08 | §32.1 changes keyset `(published_activity_id, change_kind_rank)` | changes cursor position is an offset into the deterministic sorted list | a published ID (≤ 256 Unicode characters) cannot fit the 512-character cursor and would put source text in a token; immutable terminal inputs make the offset stable |
| E-09 | §29.3 hierarchy `field_state_changed` unspecified for NULL paths | NULL ↔ path is `field_state_changed(hierarchy)` with states `ambiguous`/`published_value` | deterministic, no fabricated path |
| E-10 | §31.4 import boundary by policy | plus a handler remote-composition check (`unsupported`) | remote clients are `PrincipalKind.OPERATOR`; policy alone would not refuse |
| E-12 | §31.4 "Local HTTP/local MCP/CLI use the canonical import command" | import is **attested-local only** (CLI, HTTP gateway) through the existing S3.1 D-16 check `attested_lineage_authority`; local stdio MCP and any unattested local caller are `denied`, fail-closed, until an operator decision admits them | orchestrator decision on R7-F03 (option (a)): import is the only path feeding hostile PDFs to PDFium and is tied to an operator source-admission decision; a local AI agent over stdio MCP must not queue imports |
| E-11 | §22 "source read unavailable" only | `TraversalDeniedError` treated as unavailable (transient) | absent and refused are one provider answer; exhaustion still ends effective `failed` |

### 8.2 Residuals and unknowns

| ID | Item | Owner |
|---|---|---|
| U2-01 | Native code in the child can still issue socket syscalls (no seccomp/netns on Linux, no sandbox on macOS) | operator: network-less container for the schedule worker |
| U2-02 | macOS cannot lower `RLIMIT_AS`: on dev hosts a bomb is bounded only by CPU/wall | accepted (prod and CI are Linux) |
| U2-03 | A worker killed by `SIGKILL` leaves its child running until `RLIMIT_CPU` or a broken pipe ends it (≤ ~152 s CPU); no parent-death signal from the standard library | accepted, bounded |
| U2-04 | Parent decode of a maximal frame (≈ 46 MB nominal, cap 128 MiB) can raise worker RSS by several hundred MiB | WP-04 measure — **not measured** in S5b-2 (no maximal frame was decoded under an RSS probe); the runbook asks the operator to size the worker container for it |
| U2-05 | Persistence time for 25,000 rows plus canonicalization inside the 60 s reserve | measured by I7-C on the implementation host: 25,000-row import plus persistence 18.6 s, inside the reserve; production unmeasured — on a miss reduce the admitted bound (R2 §36) |
| U2-06 | `audit_events` validating scan under `ACCESS EXCLUSIVE` in migration #2; production row count unknown | operator gate 1 |
| U2-07 | A Start/Finish marker change on an equal date (planned → actual) is not a v1 change kind | future delta version |
| U2-08 | Parser and persistence durations are not recorded (E-05) | future observability design |
| U2-09 | `budget` failure after a legitimate slow persistence permanently blocks that version in that Series (S5b-1 U-09) | operator documentation (I7-D runbook) |
| U2-10 | A compromised child can (a) truncate, unlink, rename, chmod or create empty files the worker UID may modify (`RLIMIT_FSIZE` only stops growth; the audit hook covers Python calls only), and (b) return a well-formed frame with fabricated rows for the right digest, which would be persisted and served as `SOURCE_BOUND_DERIVED` | operator: dedicated UID, read-only root filesystem, no write access to source roots, network-less runtime (section 8.3) |
| U2-11 | A timing-dependent child failure (wall/CPU budget) on a re-claim fails a publication whose parse is already persisted as a `parsed` run: the re-parse is required because a parsed run stores no title, Data Date or Run Date (R7-N1). R2 §22 makes budget failures terminal; R2 §36's admitted bound is the lever | WP-04 measurement; bound reduction if observed |
| U2-12 | `RLIMIT_AS` 1 GiB is provisional and unverified on Linux until the PR's CI shows the 7 Linux-only nodes of section 8.3 gate 6 — the headroom test and the production-limit positive control **for both the largest golden and the bounds-maximal synthetic** (FR7-F01), the bomb-cap control, the bomb and `RLIMIT_AS` — **executed and passed** (not skipped). FR7's linear extrapolation (about 560 MiB RSS at 25,000 rows; macOS observation 440 MiB RSS at 23,250 rows) puts the bounds-maximal case near the 512 MiB the 2× rule allows, and `VmPeak` exceeds RSS. If the headroom test fails, the cap is re-derived as ≥ 2× the reported `VmPeak` (and ≤ any container memory limit), or the admitted bound is reduced (R2 §36), before merge; the cap is not changed on an extrapolation. The STOP rule applies only when a real Linux measurement is in hand (for example a CI run the operator relays back) showing < 2× headroom: the implementer then stops and reports rather than re-tuning silently | operator pre-merge gate (section 8.3); the I7-D runbook names the 7 nodes to look for in the CI log |
| U2-13 | (FR7-F04) The in-child cooperative deadline is checked only between PDFium calls: one native call is not interrupted. A 2,610-byte page (`BT /F1 1 Tf` and 200,000 `(x) Tj` with no `Td`) reaches an early call boundary, then one long native call (FR7 measured over 20 s in total), so CPU and memory spent per admitted document are bounded only by `RLIMIT_CPU` (ceil(wall) + 1 s), the parent kill at wall + 2 s (wall ≤ 150 s) and, on Linux, the address-space cap. Such a document ends `processing_budget_exceeded` (run-less when ended from outside, run-scoped when the deadline had already passed at the early boundary), terminal on its first attempt (no retry storm); pinned at a 5 s wall by `test_text_flood_outlasts_the_wall_and_ends_processing_budget_exceeded` | accepted; operator-only import limits exposure (runbook) |
| U2-14 | (FR7-F05) `tests/ci_shard_weights.json` was re-weighed from macOS JUnit, where the Linux-only memory tests skip, so CI cost (above all `tests/unit/test_schedule_parser_isolation.py`, now also parsing the bounds-maximal case on Linux) is under-weighted; balance only, never coverage | re-weigh both lanes with `python -m tests.ci_shard weigh` from the first ubuntu CI JUnit of the PR |
| carried | S5b-1 U-06 (owner can disable triggers), U-09 (failed version blocks the Series), U-10 (RESTRICT FKs) — documented in the I7-D runbook; S5a U-01 (no real corpus) | operator / WP-04 |

### 8.3 Operator gates (nothing here is performed by an agent)

1. **Deploy order (R7-F09).** Migration #2 must be applied **before** any code carrying the 7
   Schedule names serves a request: `invoke` audits every call before any handler, switch on
   or off, so a call naming a schedule capability against the old `capability_is_known` CHECK
   fails (closed, as `internal_error`). **Once migration #2 is applied, any audited call naming
   a schedule capability or purpose — including a denied or `unsupported` probe — writes an
   audit row that makes migration #2's downgrade refusal permanent** (by design; audit rows
   are never deleted). The I7-D runbook states both.
   Deploying migration #2: `ACCESS EXCLUSIVE` + validating scan on `knowledge.audit_events`
   and `worker_heartbeats` held to commit; read P3 first, choose a quiet window; a `55P03`
   abort is clean and retryable.
2. The S5b-1 §9.3 gates (P1–P8 of section 3.16) before and after both CPM revisions.
3. Enabling `MY_PA_SCHEDULE_ENABLED` anywhere but a test; running a schedule worker; source
   designation for schedule PDFs (OD-06) and the enrollment that admits `application/pdf`.
4. Any ChatLLM profile apply to `chatllm-data-v11`, any remote grant on a schedule read.
5. A runtime for the schedule worker that is network-less, runs under a dedicated UID with a
   read-only root filesystem and has no write access to any source root (U2-01, U2-10).
6. **Pre-merge (U2-12):** the PR's ubuntu CI log shows `test_child_address_space_has_headroom[largest_golden]`,
   `test_child_address_space_has_headroom[bounds_maximal]`,
   `test_largest_golden_parses_under_production_limits[largest_golden]`,
   `test_largest_golden_parses_under_production_limits[bounds_maximal]`,
   `test_benign_document_parses_under_the_bomb_cap`,
   `test_decompression_bomb_fails_closed_on_linux` and
   `test_child_rlimits_are_set[RLIMIT_AS-expected4]` executed and passed (not skipped). If the headroom
   test shows < 2× headroom (FR7's extrapolation makes the bounds-maximal case the likely one),
   the cap is re-derived or the admitted bound reduced (R2 §36) before merge; never on an
   extrapolation alone.
7. The authorized real-corpus evaluation (R2 §39, S5a U-01) and XER/XML (WP-05B, unimplemented).

### 8.4 Open questions for review R7

| ID | Question | Contract's position |
|---|---|---|
| O-1 | Brief text says the 6 reads are `DATA_REQUIRED` behind a prerequisite; repo semantics make switch-gated names `DATA_CONDITIONAL` | E-02 (`DATA_CONDITIONAL`); reviewer to rule |
| O-2 | Package order differs from the orchestrator plan (registrations + migration before behaviour) | E-06; reviewer to rule |
| O-3 | Native-crash signals map to deterministic `parser_exception` (a PDFium OOM crash under `RLIMIT_AS` is indistinguishable from a segfault) | accepted mapping; reviewer to rule |
| O-4 | `TraversalDeniedError` transient (E-11) vs deterministic | transient |
| O-5 | Activities list excludes summary rows (E-07) | exclude |

**R7 rulings (recorded).** O-1 UPHELD (condition: E-02 quotes the brief and the ruling; FAST
`test_every_data_required_policy_is_always_composed`). O-2 UPHELD (condition: I7-A leaves
`apps/worker.py`, the heartbeat CHECK and `worker_health.py` untouched, section 5). O-3 UPHELD,
conditional on the R7-F01 positive controls (section 3.4.8). O-4 UPHELD. O-5 UPHELD. R7-F03:
the orchestrator chose attested-local only (E-12).
