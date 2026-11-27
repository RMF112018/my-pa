# ADR-023: P6 XER and XML schedule import

- **Status:** Proposed — operator decisions of 2026-11-23 (below). Slice S7-0 (the scenario
  engine amendment, no migration) is merged (#384); slice S7-1 (the pure XER parser, catalogue,
  canonical frame and conformance script, no migration) is merged (#386); slice S7-2 (the one
  migration `d8383150cf72` and its table declarations) is merged (#387); slice S7-3 (the
  admission service and the worker's P6 path, no migration, no capability) is merged (#389);
  slice S7-4a (the 7 P6 capabilities, switch, policy, ChatLLM `chatllm-data-v19`, field registry,
  reads and the format-aware S5 reads, no migration) is merged (#391); slice S7-4b (the delta
  `cpm-workbench-p6-delta-v1` and the P6 scenario snapshot, no migration, no new capability) is
  merged (#392); slice S7-5 (the operator runbook, the engine-vs-P6 oracle and the read-only
  evaluation script, no migration, no capability) is implemented in PR #395. Slice S7-7
  (parallel relationships in `schedule-scenario-content-v3`, the second amendment to ADR-017
  below; no migration, no capability) is implemented in PR #396. Nothing else is implemented, and
  nothing is migrated on any shared database, granted, switched on or deployed. The optional
  slice S7-6,
  gate G-1 and every other operator gate in the contract stays open. The operator answered the contract's open
  questions on 2026-11-23 (recorded below and in contract section 17); only S7-6 stays
  undecided.
- **Decision date:** 2026-11-23
- **Repository basis:** `feat/schedule-xer-contract` at `main@5409c5b69b07ef3f3435106b2bd80e199696ca70`
  (tree `cceb6e63d63bdedceb5e894c6f050a46dc6306c7`). Main holds the CPM Workbench S5 slices
  (#344, #345, #347) and the Schedule Scenarios slices S6-1 (#348), S6-2 (#349) and S6-3
  (#354). `ADR-023` was unallocated there: `docs/decisions/` held ADR-001 to ADR-022.
- **Authority:** 2 operator decisions given to the Manager on 2026-11-23, and the operator's
  corrections of the same day: the 2 sample exports the operator holds are evidence of the
  **format only**; schedules of many projects, and many versions of each, will be imported.
- **Scope and contract:** the concrete contract is
  [`schedule-xer-import-contract.md`](../architecture/schedule-xer-import-contract.md). It
  extends the plane of [ADR-016](ADR-016-cpm-workbench-schedule-evidence.md) and
  [ADR-017](ADR-017-schedule-scenarios-and-baselines.md).

## Context

ADR-016 admitted only Full-Schedule PDFs and named XER/XML out of scope because the native
formats were "not available". They now are: the operator exports XER (and P6 API XML) files
from Primavera P6. A PDF carries no relationship, lag, calendar, constraint, duration unit or
actual, so every scenario snapshot of a PDF publication needs client-supplied calendars and a
client-declared `minutes_per_source_unit` and starts with no logic (ADR-017; scenarios
contract T6-02). An XER carries all of them.

ADR-016 decision 4 made import operator-only and attested-local. The operator now wants a
client to trigger an XER import from a file it has placed in the files workspace (ADR-019),
gated by grants. There is no path today from a files-workspace file to an enrolled source
version, and the workspace root may not overlap a source root (contract section 1).

## Decision

1. **XER first, XML later.** The profile `p6_xer_v1` is specified and implemented in full.
   The profile `p6_xml_v1` (P6 API `APIBusinessObjects` XML) is specified at contract level
   only and is used later as a cross-check of the same publication, never as a second
   identity.
2. **An MCP-triggered, grant-gated import for XER (and later XML).** A new client-usable
   write `schedule_publications.import_p6` with its own purpose `schedule_p6_import` imports
   one exact files-workspace file. It is published to a remote client only when the plane's
   switches are on, the client's writes are enabled and the client holds a grant for it. It
   is never available for PDFs.
3. **The admitted bytes are snapshotted.** Admission reads the named workspace file once,
   verifies the caller's expected `version` and SHA-256, and stores the exact bytes in an
   immutable, Principal-partitioned, content-addressed snapshot. The publication rests on
   that snapshot, not on an enrolled source version. The workspace file can change or vanish
   later without affecting the publication. No source provider, enrollment or workspace-root
   rule changes.
4. **The parser is pure, contained and fails closed.** `p6_xer_v1` is a stdlib-only parser
   with no native code. It runs in the existing `schedule` worker plane inside the existing
   contained child process: no network, no environment, rlimits, audit hook, one canonical
   frame. Size, table, record, field and length caps are hard. Decoding is strict (UTF-8,
   else Windows-1252, else a typed failure). XML is parsed with DTDs, entities and external
   references refused.
5. **Profile by catalogue, not by sample.** The profile is a field catalogue for P6 exports
   in general, with tiers: a **required core** (missing → typed fatal issue), **typed
   tolerated** fields (stored in typed columns when present, null when absent), **optional**
   fields (captured into a generic field store when selected), **never-captured** fields
   (executable expressions such as UDF indicator expressions) and **derived** fields (the
   calendar blob). A field or table the catalogue has never seen is recorded with statistics
   only and a typed **non-fatal** issue; its values are not stored unless the operator selects
   it for capture. Nothing is tailored to one project.
6. **Any exported field is recordable without a code change or migration.** A versioned
   in-repo cross-reference catalogue maps every P6 field (XER table.field, XML path, MY-PA
   target, type, unit, tier, seen or documented, engine and delta use). The available-field
   registry for a Series is that catalogue plus an observed-fields record kept per import
   (statistics only). The operator selects captured optional fields **per Series** through a
   grant-gated capability; captured values, including UDFs and activity codes, go to a
   generic, typed, indexed field store keyed by publication, entity, field key and value;
   reads filter and sort on them; the delta reports their changes; a scenario snapshot can
   carry them inert. The engine never interprets them and nothing captured is evaluated.
   Hard caps bound fields per Series, values per entity, value size and filter grammar.
   The raw export bytes are retained, so a later selection can be applied to earlier versions
   by an optional re-capture slice.
7. **Identity is the exact Activity ID (`task_code`) inside a Series.** This keeps ADR-016
   decision 6. P6 internal ids (`task_id`, `proj_id`, `wbs_id`, `clndr_id`, `task_pred_id`)
   are provenance of one publication and are never keys across publications. A P6 GUID is
   stored and may produce a labelled `renumber_candidate` hint in a delta, never a merge of
   histories. For the later XML cross-check, XER `task_id` = XML `Activity/ObjectId`,
   `task_code` = `Activity/Id`, and the 22-character XER GUID is the unpadded base64 of the
   same 16 bytes as the braced XML GUID (verified on the sample, contract section 4).
   Renumbered activities are `removed` + `added`; deleted ones `removed`.
8. **The Series is the operator's explicit choice.** Each import names a Series (or asks for
   ADR-017 auto-matching). The P6 project identity (`proj_short_name`, project GUID) is
   recorded on every publication. A publication whose P6 project identity differs from the
   Series' earlier P6 publications is `review_required` unless the request accepts the change
   explicitly. Nothing is guessed. A Series holds one source format: PDF and XER publications
   are never mixed in one Series, and there is no cross-format delta; a project with PDF
   history starts a new Series for XER (operator decision 2026-11-23). Multi-project exports
   are refused with a typed issue (operator decision 2026-11-23: they are not common).
9. **A conformance check precedes schema and every new project.** A reusable, stats-only
   profile script runs against any XER (later XML) and reports unmapped columns, over-length
   values and unknown enumeration values, never a value. Zero missing required columns, zero
   over-length values in typed columns and zero unknown required-enum values are a hard pass
   condition; unknown optional fields are reported, not fatal. The operator's sample is one
   sample used to confirm the catalogue is complete for P6 26.x (zero unknown fields) before
   the S7-2 migration is opened; it is not the acceptance bar. The operator runs the script on
   each new project's first export before importing it.
10. **Off by default, closed everywhere.** The new switch `MY_PA_SCHEDULE_P6_ENABLED` defaults
   to `false` and is effective only together with `MY_PA_SCHEDULE_ENABLED`. The 7 new
   capabilities (1 import, 1 field-selection write, 5 reads) and 2 new purposes are classified
   on every closed policy surface and in a new ChatLLM data profile.
11. **Retention and limits (operator decisions 2026-11-23).** Every admitted snapshot is
    retained; the placeholder quota and rates are kept; personal fields are captured only on
    explicit selection. Re-capture of earlier versions (S7-6) stays optional and undecided.
12. **Calendars.** A scenario request may choose any imported P6 calendar of the Project. Where
    a source gives none (PDF rows, a missing or unparseable P6 calendar, a project without a
    usable default calendar), the default is the versioned MY-PA standard calendar
    `my-pa-us-40h-v1`: Monday to Friday 08:00–16:00 (an overridable constant), non-working on
    the observed US federal holidays, generated by rule for 2000–2099 (contract section 11.6).
    P6 `rcal_Project` maps to a fixed lag calendar on the project default calendar (the standard
    calendar if none). When neither P6 progress flag is set, the progress policy defaults to
    `retained_logic`, visibly and overridably.
13. **Start and finish milestones are represented faithfully** (the amendment below).

## Amendment to ADR-017: edged milestones and engine `my-pa-cpm-v2`

ADR-017 decision 2 (deterministic server CPM `my-pa-cpm-v1`) is extended, not replaced:

- Scenario activities gain the kinds `start_milestone` and `finish_milestone`; `milestone`
  keeps its v1 meaning (PDF rows do not say which edge). A start milestone's single date is a
  start (the beginning of a working period) and takes only start-side constraints; a finish
  milestone's date is a finish (the end of a working period) and takes only finish-side
  constraints. Settings also accept a fixed lag calendar (`calendar:<key>`).
- These run on a new engine id `my-pa-cpm-v2`. `my-pa-cpm-v1` is frozen: every v1 document and
  output stays byte-identical. The engine is selected by the content schema (v1 → v1, v2 → v2),
  so existing scenarios never change results.
- No migration is needed (the stored engine-version pattern already admits `v2`); the
  capability set and the ChatLLM profile do not change.
- It is delivered as slice S7-0, a separate PR on the merged S6 modules, before the P6
  scenario hand-off (contract section 11.7).

## Amendment to ADR-017: parallel relationships (content v3, S7-7)

ADR-017's scenario content (S6-D05: at most 1 relationship per ordered pair) is extended, not
replaced:

- P6 allows 2 or more relationships between the same ordered pair (an SS + FF or SS + FS
  ladder). With 1 per pair the P6 snapshot kept whichever came first in the file, so the
  export's row order chose the network: a silent correctness defect (proven on 2 real
  exports, stats only). A scenario content now holds at most 1 relationship per
  `(pred, succ, type)`, and the P6 snapshot keeps every relationship between included
  activities.
- A content holding parallel relationships is `schedule-scenario-content-v3` (the v2 shape,
  its own digest prefix), chosen by content only; every v1 and v2 document keeps its bytes
  and digest. It runs on the engine its other content requires (`my-pa-cpm-v2` iff it uses a
  v2 feature, else `my-pa-cpm-v1`): the engine maths was already per relationship, so no
  engine id is added and every v1 and v2 result stays byte-identical.
- Change sets name a parallel relationship by its `type` (additive: every earlier request
  behaves as before); the 100,000-relationship cap counts every relationship.
- No migration (no stored column holds a content schema name); the capability set, the MCP
  tool input schemas and the ChatLLM profile do not change. Contract: import contract
  section 11.7, "Parallel relationships".

## What changes against ADR-016 decision 4, and what does not

| ADR-016 decision 4 says | For XER/XML (this ADR) | For PDF |
|---|---|---|
| import is operator-only | a client-usable write gated by a per-client grant and writes-enabled | unchanged: operator-only |
| admitted only from the CLI and the HTTP gateway (`attested_lineage_authority`) | admitted from any composed transport, including stdio and remote MCP, subject to grant and switch | unchanged |
| scoped to the caller's own enrollment | rests on a files-workspace file snapshotted at admission; Principal-partitioned; the Project must be the caller's | unchanged |
| the only path that feeds a PDF to PDFium | XER/XML never reach PDFium | unchanged |
| each import rests on an operator source-admission decision (OD-06) | the grant and the switch are the operator's admission decision for the format; each project's first export is checked by the conformance script (decision 9) | unchanged |

Every other ADR-016 decision stands for XER: immutable source-bound derived evidence (trust
`SOURCE_BOUND_DERIVED`), contained parsing, exact-ID identity, derived (never stored) deltas,
default-off switch. ADR-016's own Supersession section requires a superseding ADR "to admit a
second profile or engine" and "to admit import from a non-attested surface": this ADR is that
record, for these formats only. ADR-017's decisions (scenarios, auto-matching, derived current
update, operator-approved baselines) apply to XER publications unchanged.

## Out of scope

Implementing `p6_xml_v1` beyond its contract-level specification; resources, assignments,
costs, expenses, risks, notebooks, steps and baselines carried inside an export; multi-project
XER files (refused, typed); mixing PDF and XER in one Series; computing CPM over a publication
(ADR-017 decision 2 stands: CPM runs only over scenario versions); any write back to P6; any
real project file, identifier, code, calendar or UDF in the repository; production anything.

## Consequences

- An XER publication gives a scenario snapshot real logic, calendars, constraints, durations
  in hours and actuals, with no client-supplied unit or calendar (contract section 9).
- The repository stores the raw export bytes once per Principal per SHA-256. Storage grows
  with publications; the contract (sections 7.6 and 8.4) sizes it and leaves retention and
  partitioning to an operator decision.
- The engine amendment changes merged S6 code (scenario model, canonicalization, change sets,
  snapshot, engine, outputs, run selection) in its own PR; it adds no table or capability.
- Cost: 9 new tables (6 typed, the generic field store, the observed-fields record, the
  capture-selection events), additive columns on 3 existing tables, 1 migration, 7
  capabilities and 2 purposes; the optional re-capture slice adds 2 capabilities, 1 job table
  and 1 worker plane name.
- A client can now cause a parse. The parser is pure Python with hard caps, so the residual
  is bounded CPU and memory per admission, not native-code exposure.
- `tests/security/test_cpm_workbench_security.py::test_no_xer_or_xml_runtime_in_the_schedule_plane`
  must be narrowed, not removed, by the slice that implements each format (contract
  section 11.2).

## Supersession

A superseding ADR is required to use XER/XML ids or GUIDs as identity across publications, to
store an unselected field's values, to let the engine interpret a captured field, to admit a
multi-project export, to mix formats in one Series, to change `my-pa-cpm-v1` results, to
let a client trigger a PDF import, or to make the plane on by default.

## Implementation status

S7-0 merged (#384; no migration): contract sections 11.5
(PDF snapshot `calendars` and `default_calendar` optional together), 11.6 (the MY-PA standard
calendar `my-pa-us-40h-v1`, generated by rule in
`src/my_pa/domain/schedule/scenario/standard_calendar.py`) and 11.7 (the kinds
`start_milestone` and `finish_milestone`, the fixed lag calendar `calendar:<key>`, optional
inert `published_reference.fields`, content schema `schedule-scenario-content-v2` chosen by the
content, engine `my-pa-cpm-v2` chosen by the content schema; `my-pa-cpm-v1` and every v1
content, change-set and output hash byte-identical).

S7-1 merged (#386; no migration, no capability, no
table): the pure package `src/my_pa/domain/schedule/p6/` (catalogue `p6-field-catalogue-v1`
rendered row for row from contract section 6, the reader and calendar-blob parser, the typed
mapping and issue model of profile `p6_xer_v1`, the section 5.4 caps, and the canonical frame
`cpm-workbench-p6-frame-v1`), the synthetic fixture generator
`tests/fixtures/schedule_p6_xer.py` with pinned golden frame digests, and the read-only
stats-only conformance script `ops/schedule/p6_export_profile.py` (contract section 12).
S7-2 merged (#387; no capability, no repository, no
worker): the one additive revision `d8383150cf72` of contract section 8.3 (the snapshot and
capture-event tables, the seven per-run P6 tables, the additive `schedule_publications`,
`schedule_parser_runs` and `schedule_import_issues` columns and CHECKs, the guards, F3/F6/F9
restated for P6 rows with every PDF path unchanged, and the S7-4 audit names admitted ahead of
the domain), its `tables.py` declarations and the identifier kinds `sp6n` and `sp6e`.
S7-3 merged (#389; no migration, no capability, no MCP
tool): the admission service `ScheduleP6Application.import_p6` (switch, strict inputs, the
files-workspace contained read with version, size, SHA-256 and fingerprint re-check, the byte
sniff, replay, Series resolution, PDF-Series refusal, content idempotency, the snapshot once per
Principal), the switch `MY_PA_SCHEDULE_P6_ENABLED`, and the `schedule` worker's P6 path H1-H8 in
the existing contained child (the parent never imports the parser; the frame is decoded by the
catalogue, re-rendered and bound to the bytes).
S7-4a merged (#391; no migration): the 7 P6 capabilities
of contract section 10.1 behind `MY_PA_SCHEDULE_P6_ENABLED` (on every closed surface; the 2
writes idempotent and client-bound remotely), ChatLLM `chatllm-data-v19`, the field registry and
the compare-and-swap capture chain, the P6 reads with the section 7.7 filter grammar, the S5
reads format-aware for P6 publications, and the snapshot quota and import budgets. S7-4b
merged (#392; no migration, no new capability): the
P6 delta `cpm-workbench-p6-delta-v1` (`schedule_changes.list` and `schedule_baselines.compare`
choose the algorithm by the Series' format) and the P6 scenario snapshot of contract section
11.5 (`schedule_scenarios.create` with its `p6` options); the S6 engine, content schemas and
stored version columns are unchanged.
S7-5 is implemented in PR #395 (no migration, no capability). It adds the runbook section
(`ops/runbooks/cpm-workbench.md` section 10), the engine-vs-P6 oracle
`src/my_pa/domain/schedule/p6/oracle.py` (a check, never a claim of equivalence) and the
read-only, stats-only `ops/schedule/p6_evaluate.py`. The operator runs the real-corpus acceptance
at gate G-7.
S7-7 is implemented in PR #396 (no migration, no capability). It adds content
`schedule-scenario-content-v3` for parallel
relationships (model, canonical form and digest, decoder, change sets, the engine's
critical-path edges and typed result rows, the P6 snapshot keeping every relationship, and
the oracle's `parallel_relationships` cause narrowed to a repeated type).
Gate G-1 (the script on the operator's sample) is not run. The optional S7-6 is not
implemented; the contract defines its acceptance tests and the operator gates.
