# ADR-023: P6 XER and XML schedule import

- **Status:** Proposed — operator decisions of 2026-11-23 (below); design only. Nothing is
  implemented, migrated, granted, switched on or deployed. Every slice (S7-1 to S7-6) and every
  operator gate in the contract stays open.
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
   are never mixed in one Series in this version.
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
multi-project export, to mix formats in one Series, to
let a client trigger a PDF import, or to make the plane on by default.

## Implementation status

Not implemented. The contract defines slices S7-1 to S7-5 (and the optional S7-6), their
acceptance tests, the prove-red plan and the operator gates.
