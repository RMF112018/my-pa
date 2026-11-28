# PULSE-IMPLEMENTATION-PLAN — Project Reporting Intelligence over Procore PULSE CSV exports

**Status:** written as planning only, under scope extension `MYPA-PULSE-INTELLIGENCE-EXTENSION-20261121` of goal `MYPA-COMMS-MEETCTX-P1P3-20261121`, before any PULSE code existed, as the operator required. **As of 2026-11-24, WP3P is implemented on branch `feat/pulse-reports` (not merged) and its decision record is [ADR-024](../decisions/ADR-024-project-report-source-evidence.md). [Section 17](#17-as-built-wp3p-2026-11-24) records what was built and supersedes every passage of sections 2–14 it names; where they disagree, section 17 and the Manager rulings D1–D19 win.** Nothing is migrated, bound, enabled, exposed, granted or deployed. Every work package below needs its own PR, independent review and merge decision; items marked operator-gated need the operator.

**Basis:** branch `feat/comms-intelligence` at `f586b6c97ee480d47503e450980c4768825ac808` (tree `eb1fb5fc4f7488eb3a0abf6ac406fb4bfe6805b6`) on `origin/main@092610d36b7d1493fc7fda6e352a4bd06e914f61`; Alembic single head `640aaacc78e8`. Shared lifecycle: [ADR-022](../decisions/ADR-022-communications-intelligence.md) decision 2 (Accepted under operator delegation 2026-11-22, Manager ruling R-OP-1; effective on merge of WP2) and [`communications-intelligence-contract.md`](../architecture/communications-intelligence-contract.md) ("contract"), sections 1, 9, 11, 18 and 19, with the Manager rulings of 2026-11-21 in its section 21. Evidence: [`docs/evidence/pulse/`](../evidence/pulse/README.md) ("evidence"), aggregates only. All counts are digits on purpose (spelled-count guard). Paths to files that do not exist yet are not written as links (CI relative-link check).

**Committable-data rule.** This plan, its fixtures and its tests name projects by **project number** only and use **synthetic** Project identifiers. The folder-to-Project crosswalk is operator runtime registry data (section 6.4) and is never committed.

## 1. Architecture and rationale

### 1.1 Position

Procore PULSE CSV exports are **read-only original-source evidence** (`AGENTS.md` section 4: original source systems are authoritative and read-only). The operator saves a report in Procore and exports it as CSV into a project folder of the `mcp` file workspace ([ADR-019](../decisions/ADR-019-nas-mcp-file-workspace.md)); my-pa reads those files and never writes, renames or trashes them, and never calls Procore.

### 1.2 One shared lifecycle (reuse, never a second one)

PULSE is the **second consumer** of the lifecycle WP3 builds for communications (contract section 1.2): `ingest_sources`, `ingest_snapshots`, `ingest_runs`, `ingest_run_snapshots`, snapshot rejection, and coverage/freshness bookkeeping. The consumer value `pulse_csv_export` is already in the contract's closed set. PULSE adds nothing to the lifecycle tables except rows; any lifecycle change PULSE needs is listed as a WP3 requirement in section 14.2 so WP3 builds it once.

### 1.3 Domain-specific storage in 2 layers

- **Layer A — source fidelity.** One extension row per PULSE snapshot plus **every raw row** of the export with its row role (`detail`, `group_header(level, key)`, `grand_total`, `spacer`, `grouping_only`, `malformed`, and `unclassified` for a quarantined snapshot), its inherited group context and its raw physical record text, so the export can be reconstructed byte-exact and every sum can be restricted to detail rows.
- **Layer B — typed observations** per validated report family: decimal amounts, dates, statuses, identifiers, each pointing back to its Layer A row.
- Lifecycle tables hold no PULSE content; PULSE tables hold no communications content (ADR-022 decision 2).

### 1.4 Authority class and the Reports feature

- Exports are **not** product-owned user-authored records ([ADR-003](../decisions/ADR-003-product-owned-user-authored-source-records.md)): the operator does not author the rows in my-pa; Procore does. They are not managed documents either.
- They are **not** Intelligence report artifacts ([ADR-010](../decisions/ADR-010-intelligence-artifact-report-plane.md) and the Reports Modernization plane, `reports.*`, `domain/reports/`): those are authored, published, versioned, held and retained by my-pa. Reusing that plane for PULSE would give source evidence a publish/update/archive/delete lifecycle it must not have.
- What is reused: the report plane's integer-rank and keyset-cursor conventions (section 8), the Program reportability vocabulary (`NOT_REPORTABLE`, reasons, no substituted zero; `domain/program/reportability.py`, OD-08), and ADR-018's decimal money semantics (section 7.1).

### 1.5 Rejected alternatives

| Alternative | Reason rejected |
| --- | --- |
| A PULSE-specific ingestion lifecycle | duplicates snapshot, idempotency and quarantine; ADR-022 decision 2 |
| One generic evidence table for communications and PULSE | different identities, units and queries |
| Store PULSE as Intelligence report artifacts | wrong authority class; artifacts are authored and mutable by lifecycle |
| Adapter chosen by filename slug | slugs do not describe content (evidence: historical coverage section 3); 2 slugs share 1 signature |
| Parse only detail rows, drop the rest | loses reconstruction and the stated totals needed to verify sums |
| Sum every numeric row | double and triple counting (evidence: grain section 5) |
| Float arithmetic | inexact cents; the cross-report check is exact only in decimal |
| Project from filename, slug or code prefix | no project in the filename; prefixes are a cross-check only |
| Crosswalk committed in the repository | operator data; committable rule |
| Crosswalk as an environment setting | cannot be validated against the Principal's Projects at load and has no revision audit |
| Infer closure from disappearance | filter semantics are unknown |
| A Procore API connector | live source access is not authorized (`AGENTS.md` section 3); the operator already exports files |
| A PULSE record-lineage family | ADR-015 decision 6 not amended; same position as ADR-022 decision 19 |

## 2. Exact affected modules

New modules (proposed names; each package follows the communications WP1 split: a pure domain, one infrastructure module that names provider vocabulary, application services, persistence, adapters):

| Module | Responsibility | WP |
| --- | --- | --- |
| `src/my_pa/domain/project_reports/model.py` | closed vocabularies (`RowRole`, `CompletenessClass`, `FilterSemantics`, `StatusClass`, `Additivity`, `ReconciliationOutcome`, `RecordFamily`, `IdentityBasis`), frozen records (`ExportSnapshot`, `ExportRow`, `GroupPath`, `StatedTotal`) | WP3P |
| `src/my_pa/domain/project_reports/signature.py` | `pulse_header_signature_v1` (section 4.2) | WP3P |
| `src/my_pa/domain/project_reports/roles.py` | the grouped-export role classifier, parameterized by a family's group-key columns (section 4.3) | WP3P |
| `src/my_pa/domain/project_reports/money.py` | decimal parse of export money and number shapes (section 7.1) | WP3P |
| `src/my_pa/domain/project_reports/reconciliation.py` | stated-total checks, cross-report check (section 7.4) | WP3P |
| `src/my_pa/domain/project_reports/identity.py` | per-family identity keys and match normalizations, versioned (section 6.3) | WP3P |
| `src/my_pa/domain/project_reports/measures.py` | detail-only, status-separated measures with reportability (section 7) | WP3P |
| `src/my_pa/domain/project_reports/bindings.py` | crosswalk file schema and validation, pure (section 6.4) | WP3P |
| `src/my_pa/infrastructure/project_reports/pulse_csv.py` | strict RFC 4180 reader, the signature registry and the family adapters: the only module that names Procore header strings | WP3P |
| `src/my_pa/infrastructure/project_reports/aggregate_cli.py` | aggregate-only validation CLI over real files (Manager only; section 12.3) | WP3P |
| `src/my_pa/infrastructure/persistence/project_reports.py` | Layer A and B repositories through the partition guard | WP3P |
| `src/my_pa/application/project_reports.py` | ingestion step (a lifecycle consumer), binding apply/check, read services | WP3P, WP4P |
| `apps/cli/project_reports.py` | operator commands: `bindings check`, `bindings apply`, `ingest --once`, `backfill`, `dry-run` (as built: `bindings check|apply`, `run-once`, `backfill [--dry-run]`, `rederive`, `coverage`, `aggregate`; section 17) | WP3P |

Changed modules (one line each; exact edits belong to the WP):

| Module | Change | WP |
| --- | --- | --- |
| `src/my_pa/infrastructure/persistence/tables.py` | the section 5 tables | WP3P |
| `migrations/versions/` | 1 additive revision per WP that needs one (section 3) | WP3P, WP4P |
| `src/my_pa/domain/common/identifiers.py` | `IdKind` members for binding revisions and canonical records (proposed prefixes `prbnd`, `prrec`) | WP3P |
| `src/my_pa/domain/identity/operation.py` | the 5 `project_reports.*` names (section 9) | WP4P |
| `src/my_pa/domain/identity/purpose.py` | purpose `project_reports_read` | WP4P |
| `src/my_pa/application/capabilities.py`, `src/my_pa/application/service.py` | manifest entries, handlers, gating set | WP4P |
| `src/my_pa/adapters/mcp/` | tool publication through the existing thin adapter; no PULSE logic | WP4P |
| `src/my_pa/domain/identity/chatllm_capability_policy.py`, `src/my_pa/application/chatllm_data_profile.py` | data-conditional prerequisite `PROJECT_REPORTS` | WP4P |
| `src/my_pa/bootstrap/settings.py` | `MY_PA_PROJECT_REPORTS_ENABLED`, `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` (default off) | WP3P, WP4P |
| `apps/worker.py` | the PULSE consumer joins the lifecycle poll step on the cycles plane (section 11) | WP3P |
| the WP5 meeting-context service | optional PULSE section (section 10) | WP5 |
| `tests/architecture/` | scope guard `test_project_reports_scope.py`, partition and policy closure coverage | WP3P, WP4P |
| `tests/fixtures/project_reports/` | synthetic CSV fixtures only | WP3P |

Not touched: the communications domain and parser, the Reports plane, the financial F-1 slice (section 7.1 chose option B, so it stays untouched), Entities, record lineage.

## 3. Proposed migrations

- **WP3** (not PULSE): the shared lifecycle tables (contract section 1.2), including the section 14.2 requirements.
- **WP3P, 1 additive revision** on whichever head is current: the section 5 tables, their append-only and TRUNCATE-refusal triggers (precedent `7d9a450dfd07`, `c8e4a1b70d35`), composite Principal foreign keys with `ON DELETE RESTRICT`, CHECKs for every closed vocabulary, the 2 new `IdKind` prefixes, and no grant. Downgrade refuses while any PULSE row exists.
- **WP4P, 1 additive revision:** the 5 capability names and the `project_reports_read` purpose admitted to the frozen `audit_events` closed sets (`capability_is_known`, `purpose_is_known` restated, the `640aaacc78e8` precedent); no table.
- No migration rewrites a communications or lifecycle table. Every revision is tested from empty and from its predecessor head (DB tier).

## 4. Adapters and validation

### 4.1 File-level validation (order; the first failure decides)

1. Size at most `MAX_EXPORT_BYTES` (proposed 16 MiB; the largest real export is 147,383 bytes).
2. Strict UTF-8; a byte-order mark is tolerated and recorded (none observed).
3. RFC 4180 parse: comma delimiter, double-quote quoting, CR, LF or CRLF record terminators, line breaks inside quoted fields preserved. An unterminated quote, a quote inside an unquoted field, or a NUL byte → snapshot **rejected** (`malformed_csv` with record number and byte offset only).
4. A non-empty first record (the header) with unique, non-empty cells (`invalid_header`).
5. Header signature lookup (section 4.2). Unknown → **quarantined** (section 4.5).
6. Every further record: width equal to the header's, else that row is `malformed` (stored, counted, never typed). More than `MAX_MALFORMED_RATIO` (proposed 1 %) malformed rows → the snapshot is quarantined.

Rejection and quarantine never delete or modify the file.

### 4.2 Signature registry

- Signature: `pulse_header_signature_v1` = SHA-256 of the compact JSON array of header cells exactly as decoded ([schema catalog](../evidence/pulse/PULSE-REPORT-SCHEMA-CATALOG.md) section 1). The 15 real signatures are listed there.
- The registry maps a signature to `(record_family, view, adapter_version)`. It is code (reviewed, versioned), not configuration. A new Procore column order is a new registry entry in a new PR, with a synthetic fixture.
- Slugs and date prefixes are never consulted to choose an adapter.

### 4.3 Role classification

Each family adapter declares its group-key columns (none, 1 or 2) and its numeric columns. The classifier (pure, `domain/project_reports/roles.py`) walks rows in order:

| Condition | Role |
| --- | --- |
| every cell empty | `spacer` |
| first cell is the literal `Grand Totals` | `grand_total` |
| level-1 key filled | `group_header(1, key)`; `(Blank)` is a real key |
| level-2 key filled, level-1 empty, inside a level-1 group | `group_header(2, key)` |
| no group key, fields of a record present | `detail`, inheriting the current group path |
| group header with no detail row before the next header of the same or higher level, or end of file | re-labelled `grouping_only` (a level-1 header followed directly by its level-2 headers is still `group_header(1, key)`) |
| anything the family rules cannot place | `malformed` |

Inherited context is stored as the ordered group path `[(level, key, header row ordinal), …]`. Every snapshot's role counts must sum to its data-row count.

### 4.4 Typed parse (Layer B)

- Money: section 7.1. Numbers: `Decimal`. Dates: `M/D/YYYY` → date. Booleans: `Yes`/`No`. Statuses: kept verbatim and mapped to a closed `StatusClass` by a versioned per-family table; an unmapped value is `unknown`, never guessed.
- A cell that fails its type makes that Layer B row `degraded` with a reason code; its Layer A row stays intact. Raw text is kept beside every typed value.

### 4.5 Quarantine and reason codes

- **As built (section 17, drift 5, 6):** there is no `oversize` code (an oversized file is the lifecycle's `skipped_too_large`, with no row), `nul_byte` is a rejection code, and quarantine is a derivation state of an `ingested` snapshot, not a snapshot state; `source_unbound` is not a quarantine but a refusal (the command refuses up front; the handler rolls the snapshot back).
- **Snapshot-level:** `rejected` (unparseable: `malformed_csv`, `invalid_header`, `oversize`, `not_utf8`) or `quarantined` (`unknown_header_signature`, `malformed_ratio_exceeded`, `source_unbound`, `binding_project_number_mismatch`). A quarantined snapshot keeps its lifecycle row and **all rows in Layer A with role `unclassified`**, so nothing is lost and a later adapter can re-ingest it from the stored rows.
- **Row-level:** `malformed`, `type_error`, `identity_missing`, `ambiguous_identity`.
- Diagnostics carry codes, ordinals and counts only, never cell content (ADR-022 decision 18 applies equally).

## 5. Tables and indexes

All tables Principal-partitioned (`principal_id` NOT NULL, composite foreign keys, `ON DELETE RESTRICT`), reached through the partition guard, append-only unless a column is named mutable. Schema placement follows WP3's choice for the communications tables. Names are proposals.

### 5.1 Layer A

**`project_report_snapshots`** (1 row per PULSE lifecycle snapshot; PK `snapshot_id` → `ingest_snapshots`):

| Column | Rule |
| --- | --- |
| `principal_id`, `source_id`, `project_id` | `project_id` from the binding revision in force at ingest; FK `knowledge.projects (project_id, principal_id)` |
| `binding_revision_id` | FK to section 5.4 |
| `header` | JSON array of header cells as decoded |
| `header_signature`, `signature_version` | section 4.2 |
| `record_family`, `view`, `adapter_version` | null when quarantined |
| `series_id` | section 6.2 |
| `publication_date_label`, `report_slug_label` | from the filename; labels only |
| `filter_semantics` | `unknown` (default) or `operator_verified` with `filter_definition_id` |
| `completeness_class` | `populated`, `valid_empty`, `grouping_only` |
| `data_row_count`, `role_counts` | role counts JSON; CHECK sum = `data_row_count` |
| `embedded_line_break_count`, `bom_present` | format facts |
| `reconciliation` | JSON of match/mismatch counts per check (section 7.4) |
| `state` | `ingested`, `quarantined` |

**`project_report_rows`** (every data row; PK `(snapshot_id, row_ordinal)`):

`principal_id`, `snapshot_id`, `row_ordinal` (1-based after the header), `raw_record` (the physical record text exactly as in the file, terminator excluded), `terminator` (`lf`, `crlf`, `cr`, `none`), `cells` (JSON array of decoded strings), `row_role`, `group_level` (1, 2 or null), `group_key` (raw cell, for headers), `group_path` (JSON, section 4.3), `parent_header_ordinal`. Invariant tested at ingest: the header record plus every `raw_record` and terminator, concatenated in order, has the snapshot's `file_sha256`.

### 5.2 Layer B (typed observations per family)

Every Layer B row carries `principal_id`, `project_id`, `snapshot_id`, `row_ordinal` (FK to its Layer A row, 1:1), `record_id` (nullable FK to `project_report_records`), `observation_state` (`typed`, `degraded`) and the raw text of every typed column.

| Table | Family / views | Typed columns (beyond identity) |
| --- | --- | --- |
| `project_report_meeting_items` | OAC meeting items | meeting number, meeting date, category, item number, title, description, date updated, minutes |
| `project_report_observations` | observations (all views) | number, status, status class, type, created, closed, assignee vendor, title, description, count |
| `project_report_coordination_issues` | coordination issues | number, status, status class, type, created, updated, due, assignee company, assignee, trade, title, description |
| `project_report_rfis` | RFIs (3 views) | number as exported, prefix, numeric suffix, subject, priority, initiated, due, closed, due-date variance, ball in court, count |
| `project_report_rfi_drawing_links` | RFIs linked to drawings | RFI number, drawing number, link count, tool type, link type |
| `project_report_budget_change_lines` | budget changes (2 views) | change number, change date, title, status, budget code, budget code description, amount, line description |
| `project_report_buyout_lines` | buyout summary | `line_kind` (`budget_line`, `budget_change`, `prime_change_order`, `commitment`, `commitment_change_order`, `vendor_only`), budget code, vendor, commitment number (as exported and match-normalized), amount column name, amount |
| `project_report_change_order_lines` | change-order reconciliation | `line_kind` (`prime_pco_line`, `commitment_co_line`), prime CO number (null for `(Blank)`), PCO number, PCO status, status class, dates, description, amount, commitment CO number and status |
| `project_report_daily_log_entries` | daily log (4 views) | `entry_kind` (`manpower`, `weather`, `delay`, `note`), date, vendor, workers, hours, total hours, weather measures, delay type, start, end, is weather delay, comments |

Explicit within-export relationships ([relationship matrix](../evidence/pulse/PULSE-REPORT-RELATIONSHIP-MATRIX.md)) are these columns; there is no link table.

**`project_report_records`** (canonical identities): `record_id` (`prrec`), `principal_id`, `project_id`, `record_family`, `identity_key` (normalized text, section 6.3), `identity_basis`, `identity_version`, `first_snapshot_id`, `latest_snapshot_id` (mutable projection), `latest_status_class` (mutable projection). `UNIQUE (principal_id, project_id, record_family, identity_key, identity_version)`.

### 5.3 Stated totals

**`project_report_stated_totals`**: `principal_id`, `snapshot_id`, `row_ordinal`, `scope` (`group`, `grand`), `group_level`, `group_key`, `column_index`, `header`, `raw_text`, `value` (`NUMERIC(20,4)` or null), `additivity` (`additive`, `non_additive`, `unknown`; per family column), `computed_value` (Σ detail in that scope), `outcome` (`match`, `mismatch`, `not_checked`). PK `(snapshot_id, row_ordinal, column_index)`. Stated totals are evidence; no read returns them as a measure.

### 5.4 Project binding registry

**`project_report_source_bindings`** (append-only revisions): `binding_revision_id` (`prbnd`), `principal_id`, `source_id` (FK `ingest_sources`), `project_id` (FK `knowledge.projects (project_id, principal_id)`), `declared_project_number`, `state` (`active`, `retired`), `supersedes_revision_id`, `recorded_at`, `recorded_by` (operator channel), `change_set_sha256` (of the applied file, section 6.4), `reason_code`. Partial unique: one `active` revision per `(principal_id, source_id)` and one per `(principal_id, project_id)`.

### 5.5 Indexes

- `project_report_rows (principal_id, snapshot_id, row_role)`.
- `project_report_snapshots (principal_id, project_id, record_family, series_id, first_seen_at DESC)` for latest-per-series and coverage.
- `project_report_records (principal_id, project_id, record_family, identity_key)` (the unique) and `(principal_id, record_family, latest_status_class)`.
- Each Layer B table: `(principal_id, record_id, snapshot_id)` and `(principal_id, project_id, snapshot_id)`; status and date B-trees where section 8 filters on them.
- `project_report_rfis (principal_id, project_id, rfi_numeric_suffix, rfi_prefix)` for exact RFI lookup (section 6.3).
- `pg_trgm` GIN on the title/subject columns of meeting items, observations, coordination issues and RFIs (near-miss lookup); no `pgvector`, no FTS document in v1 (WP4P may propose one after measurement).

## 6. Identity and versioning rules

### 6.1 Snapshot identity

- One lifecycle source per bound project folder. Snapshot identity is `(principal_id, source_id, file_sha256)` (contract section 1.2). The same bytes in 2 project folders are **2 snapshots of 2 sources** (the real byte-identical notes file proves this case).
- A copy of the same bytes inside one source is an alias (contract section 1.3); a new byte content at a known path is a new snapshot and the earlier one becomes `superseded` for that path.
- Stability rule as contract section 11: size and version token unchanged across 2 polls.

### 6.2 Report series and versions

- A **report series** is `(source_id, report_slug_label, header_signature)`: one saved report of one project. Slugs never carry meaning, but 2 saved reports with one signature (evidence: schema catalog section 1) must not be merged, so the label is part of the key.
- A new date prefix with the same slug and signature is a new **version** of the series. Versions are ordered by `publication_date_label`, then `first_seen_at`.
- A changed header under the same slug starts a new series (and a new adapter version, or quarantine).
- `filter_semantics` is per series: `unknown` until the operator records a verified filter definition (an operator CLI action, audited); the definition applies only to versions ingested after it.

### 6.3 Record identity (per family)

| Family | `identity_key` | Basis | Notes |
| --- | --- | --- | --- |
| OAC meeting item | `item:<item number>` | `exported_number` | each row is the item's observation in meeting `<meeting number>`; meeting number is an observation attribute |
| Observation | `observation:<number>` | `exported_number` | |
| Coordination issue | `coordination_issue:<number>` | `exported_number` | |
| RFI | `rfi:<number as exported, whitespace-normalized>` | `exported_number` | prefix and numeric suffix stored separately; repeated rows stay separate observations; no number → `record_id` null, `identity_missing` |
| Budget change | `budget_change:<number>` | `exported_number` | lines have no record: snapshot-scoped |
| Buyout commitment | `commitment:<match-normalized number>@<budget code>` | `exported_number_normalized` | normalization `commitment_number_v1` strips the suffix's leading zeros for matching only |
| Prime change order | `prime_co:<number>` | `exported_number` | |
| PCO | `pco:<number>` | `exported_number` | lines snapshot-scoped |
| Commitment CO line | none | — | `ambiguous_commitment_co`; operator question (section 16) |
| Daily log | `manpower:<date>@<vendor>`, `weather:<date>` | `exported_composite` | |

Rules:

- Identity is never derived from a title, subject, description, amount or date (except the daily-log date, which is the record's own key).
- **Never infer closure from disappearance.** A record absent from the latest version of a series is `not_observed_in_latest`; its status stays as last observed, with that snapshot.
- Status changes are observed only from a status column of a later version.
- An identity or normalization change is a new `identity_version` written beside the old, switched atomically, as contract section 7 does for extractors.
- **RFI matching:** exact numeric suffix (token-bounded: `174` never matches `1740` or `17`); a given prefix must match exactly; no prefix → every prefix with that suffix, flagged `ambiguous_prefix` when more than 1.

### 6.4 Project crosswalk: operator runtime registry data

- **What it is.** For each PULSE source, the folder (relative to the workspace) and the Project it belongs to. It is **never** inferred from a filename, slug or code prefix and **never committed** to this repository.
- **Where it lives.** At runtime, in `project_report_source_bindings` (section 5.4), next to the `ingest_sources` row of each folder. It reaches the database only through an operator CLI command, following the operator-reviewed, append-only mapping revisions of ADR-018 decision 3 and the operator CLI precedent of source admission (contract section 1.2). It is not a `bootstrap/settings.py` value: settings cannot check a Project against the Principal's database at load and keep no revision history.
- **Input format.** An operator-held JSON file outside the repository, `my_pa_project_report_bindings_v1`:

  ```json
  {
    "schema": "my_pa_project_report_bindings_v1",
    "workspace_id": "mcp",
    "bindings": [
      {"folder": "<relative folder path>", "project_id": "prj_<synthetic>", "project_number": "<project number>"}
    ]
  }
  ```

  Only these keys are accepted (unknown keys refuse); duplicate JSON keys refuse.
- **Commands.** `apps/cli/project_reports.py bindings check --file F` (validate and print the diff as counts and project numbers, no write) and `bindings apply --file F --reason CODE` (whole file, one transaction). **As built:** there is no `--reason`; each revision records the reason its change kind names (section 17, drift 7). There is no client capability for bindings.
- **Validation, fail-closed.** `apply` refuses the whole file, writing nothing, when any of these holds:
  1. a `project_id` does not exist for the Principal, or is not a Project identifier;
  2. `project_number` differs from that Project's own `project_number` (or the Project has none);
  3. a folder appears twice, or 2 folders resolve to the same normalized path (mapped twice);
  4. a Project appears under 2 folders (v1 allows 1 folder per Project; widening it is a plan change);
  5. a folder is absolute, contains `..`, or is not inside the workspace's PULSE export area.
- **Unmapped folders.** A folder holding CSV files with no `active` binding is **unbound**: its files are never ingested; each run counts them (`source_unbound`) and `bindings check` lists them by relative path. Retiring a binding stops ingestion of new snapshots and keeps existing rows.
- **Run-time cross-check.** At ingest, if a budget code or commitment number's project-number prefix disagrees with the bound Project's number, the snapshot is quarantined (`binding_project_number_mismatch`).
- **Audit.** Every apply writes 1 revision per changed binding (with `recorded_by`, `reason_code`, the file's SHA-256) and 1 `audit_events` row with codes and counts. **As built:** no `audit_events` row; the revisions are the audit (ruling D6; section 17, drift 7). Revisions are append-only; a correction is a new revision.
- **Tests** use synthetic folders, synthetic project numbers and synthetic `prj_` identifiers only.

### 6.5 Code versions

`pulse_header_signature_v1`, each adapter's version, `commitment_number_v1`, the status-class tables and `identity_version` are recorded on the rows they produced. A version change is a rebuild from Layer A (an operator CLI command), never an in-place edit.

## 7. Financial aggregation safeguards

### 7.1 Money

- Every amount is `Decimal` with `NUMERIC(20,4)` semantics; no `float` in any PULSE module (AST guard). Inputs with more than 4 decimals are refused, never rounded (ADR-018 decision 4).
- Export shapes: currency sign, thousands separators, 2 decimals; negatives in parentheses; plain decimals in daily logs ([financial integrity](../evidence/pulse/PULSE-FINANCIAL-DATA-INTEGRITY-ASSESSMENT.md) section 1). Anything else is a `type_error`.
- **Reuse decision (WP3P preflight, Manager):** option A reuses `domain/project_controls/financial/money.py` (`parse_amount`, `money_sum`), which needs `tests/architecture/test_financial_source_scope.py`'s isolation rule widened to admit `domain/project_reports`; option B keeps a PULSE-local parser with the same context and a parity test against shared cases. **Manager ruling 2026-11-21: option B.** WP3P writes a PULSE-local `Decimal` parser in `domain/project_reports/money.py` with a parity test against the ADR-018 money module (`domain/project_controls/financial/money.py`) over shared cases; the ADR-018 import-isolation guard (`tests/architecture/test_financial_source_scope.py`) stays unchanged.
- Currency is a source attribute: a single currency per source declared in the binding's source admission; no FX.

### 7.2 What a measure may sum

- **Detail rows only.** Every measure reads Layer B rows whose Layer A role is `detail`. Group headers, `grand_total`, `spacer`, `grouping_only`, `malformed`, `unclassified` never contribute (a query-layer guard and a DB-tier test pin it).
- **Levels.** 2-level reports cannot double count because headers of both levels are excluded; the observation 99 vs 198 case is a pinned test.
- **One view per measure.** A measure names one family view; the 2 budget-change views are never added together.
- **One version per series.** A measure reads the latest (or a named) version of one series, never a union of versions.
- **Keyed commitments.** Commitment amounts aggregate by `(commitment, budget code)`.
- **Sides.** A measure names one amount column, hence one side (revenue, cost, budget); no measure adds columns of different sides.

### 7.3 Status separation

Change-order and PCO measures are computed separately per `StatusClass`: `approved`, `pending` (every `Pending - …` value), `void`, `unknown`. There is no all-status measure called "approved", and no measure is taken from a subtotal.

### 7.4 Stated totals and reconciliation

- At ingest every stated subtotal and grand total is recomputed from detail (section 5.3) and recorded as `match`/`mismatch`; per-snapshot counts go into `reconciliation`.
- Additivity is declared per family column. A `non_additive` total (`RFI > Due Date Variance (Days)`, link counts, row counts) is evidence only.
- Cross-report check (evidence: financial integrity section 5): buyout's prime-contract approved grand total = numbered prime CO subtotals + approved `(Blank)` PCO lines, computed when both snapshots of the same project and publication date are present; the outcome is stored on both snapshots.

### 7.5 Reportability

A measure answers `reportable` with a value, or `not_reportable` with closed reasons and no value (OD-08 vocabulary). Reasons: `reconciliation_mismatch`, `source_column_unpopulated` (the unloaded original budget), `status_unknown_present`, `snapshot_quarantined`, `binding_project_number_mismatch`, `filter_semantics_unknown` (attached as a qualifier, not a refusal, for counts of records), `no_snapshot`. No zero is substituted. `reportable` certifies source integrity only, never an approved or certified total (ADR-018 decision 6's position).

## 8. Query/API contracts

All reads are Principal-scoped, bounded, read-only, behind `MY_PA_PROJECT_REPORTS_ENABLED` (default off), purpose `project_reports_read`. Every answer states, per snapshot used: `snapshot_id`, `publication_date_label`, `first_seen_at`, `filter_semantics`, `completeness_class`, adapter and identity versions. Content is inert data.

| Name | Request | Response | Bounds |
| --- | --- | --- | --- |
| `project_reports.catalog` | `project_id?`, `record_family?` | per Project: sources, series (family, view, slug label, signature prefix), versions count, latest version, completeness class, filter semantics, quarantined snapshot count | ≤ 50 Projects; ≤ 200 series |
| `project_reports.query` | `project_id`, `record_family`, `series_id?` (default latest of each series of the family), `version?`, `filters` (status class, statuses, date ranges, identifier terms such as `rfi: 174` with optional prefix, vendor, budget code), `text?` (trigram contains on titles/subjects), `measures?[]` (closed set per family), `limit`, `cursor?` | `rows[]` (typed values, raw text, `record_id`, Layer A pointer), `measures[]` (value or `not_reportable` + reasons), `next_cursor`, snapshot block | `limit` 1–100 (default 25); text ≤ 200 chars; ≤ 20 identifier terms; each text field ≤ 2,000 chars per row |
| `project_reports.record_history` | `record_ids[]` or `(project_id, record_family, identity_key)` | per record: every observation across versions in order (status, dates, changed fields, snapshot block), `not_observed_in_latest` flag | ≤ 25 records; ≤ 200 observations each |
| `project_reports.compare` | `series_id`, `from_version`, `to_version` | `added[]`, `not_observed[]` (never "closed"), `changed[]` (field names, old/new status class), snapshot-scoped lines compared by content and flagged `content_matched`, measures delta per status class | ≤ 500 entries, cursor beyond |
| `project_reports.coverage` | `project_id?`, `record_family?` | per series: versions, date labels, first/last seen, freshness seconds, completeness classes, filter semantics, rejected/quarantined counts, unbound folders count | ≤ 50 Projects |

Cursors are opaque, grant-bound and keyed on a total order (`publication_date_label`, `snapshot_id`, `row_ordinal`), the report plane's and S3's precedent. Unknown or foreign identifiers are `not_found`, indistinguishably. Stated totals are returned only inside a `source_totals` block labelled evidence, never in `measures`.

**As built (WP4P, 2026-11-25).** WP4P was built on branch `feat/pulse-reads` in slices S1–S5 under the Manager's WP4P rulings D1–D10 and the review rulings of 2026-11-25; the design of record is the WP4P-W1 design report. The 5 names, the purpose `project_reports_read`, the switch `MY_PA_PROJECT_REPORTS_ENABLED` (default off) and the bounds of the table stand. The procedure is the runbook's "Reads" section ([`ops/runbooks/project-reports-ingestion.md`](../../ops/runbooks/project-reports-ingestion.md) section 12). Where the build differs from the text above:

- **Series id (ruling D2 (a)).** `series_id` is derived, never stored or issued: `prser_` followed by the first 32 hex characters of SHA-256 over the canonical JSON of the Principal, the ingest source, the slug label, the header signature and `v: 1`. It is stable across a rederive, a binding correction and a restart, is no `IdKind`, and reveals neither the slug nor the signature; a foreign or unknown token is `not_found`. `catalog` returns the slug label and an 8-hex `signature_prefix` (D3 (a)); a filter description is never returned.
- **Snapshot block.** Each version used is `version` (the `isnp_` snapshot id), `series_id`, `publication_date` (the label's ISO date, or null), `first_seen_at`, `filter_semantics` judged per version (a declaration applies to versions first seen at or after it, D8 (i)), `completeness_class`, `derivation_state` with `quarantine_reason`, the adapter, identity and status-map versions (the `pulse_adapter_v1` token reaches clients, accepted), `currency` and `is_latest`. `qualifiers` is once per answer.
- **Unbound folders (D7 (a)).** `coverage` does not count unbound folders: a read never lists the file workspace, and `bindings check` (`unbound_folders`) stays the operator's view. The table's "unbound folders count" is not built.
- **Measure catalogue.** `domain/project_reports/catalogue.py` holds the closed per-view field catalogue by field key only; a FAST parity test holds it equal to the adapters. Measures are generated from it, never listed by hand: every `additive` column of a view plus the record and row counts, 22 names of the forms `<view>.<field_key>`, `<view>.record_count` and `<view>.row_count` (ruling A1), frozen in the MCP enum. A `non_additive` or `unknown` column is never a measure (PULSE-AC-08). The bases are a detail sum, a sum keyed by commitment and budget code, or per status class (the reconciliation and `grouped_by_change` views; no all-status figure); `by_code` carries `status_basis: "not_exported"`. Money is a JSON string in plain fixed point inside `{amount, currency}`, never a float.
- **Reads design deltas.**
  - `catalog` and `coverage` take `project_ids?[]` (at most 50), not one `project_id`.
  - `text` is a contains within one text field, folded in SQL on both sides (`strpos(lower(…), lower(…))`); only ASCII case folding is contractual (F1-4). There is no trigram, FTS or vector index (design 2.11).
  - Measures follow the query's row filters (B1, amended): each measure carries `measure_scope` (`version` with no row filter, `filtered` otherwise). `source_totals` and reconciliation always judge the whole version (`reconciliation_scope: "version"`), as do column population, unknown status and type errors (B2-1, R1-07). A reconciliation mismatch blocks money derivation-wide (D9); a record or row count is never withheld and carries the `reconciliation_mismatch` qualifier instead (A2). A cross-check counts only when both its sides are current derivations (A4).
  - Two answer-only `not_reportable` reasons, no migration: `currency_mixed` (a compare delta across two currencies, R1-09) and `unidentified_key_present` (commitment lines without an identifier are never keyed; the answer reports `unidentified_lines`, R1-10).
  - `record_history`: `changed_fields` compares consecutive readable versions of a series as a multiset, never two lines of one version, sits on the version's first line with `changed_since_version` (the baseline version), and the other lines carry `[]` and null (R1-06, F1-3, R2-07). Per series `presence` is `observed_in_latest`, `not_observed_in_latest` or `latest_unreadable` when the latest version is quarantined (R1-01).
  - `compare`: `from_version` and `to_version` are optional (the latest and the version before it); a quarantined side answers `comparable: false` (B2); count deltas carry the union of both sides' qualifiers (R1-03).
  - Cursors bind the request, the Principal, the grants on the 5 names and the resolved version set (D4 (b)): a new export, rederive or binding correction between pages answers `cursor_state: "scope_changed_restart_required"`. The position is `[series ordinal, version, row_ordinal]` for `query` and `[section, key]` for `compare`, not `publication_date_label` first; every text `ORDER BY` is `COLLATE "C"` (F1-1).
  - Every read selects derivations only through `project_report_current_derivations`: a per-statement static guard (`tests/architecture/test_project_report_reads_use_current_derivations.py`) plus a runtime backstop in the DB read suites (R1-04, R2-02).
  - A request resolves at most 2,000 versions.
  - The client-visible tool text lives in the published field descriptions of the commands' `mcp_payload_properties`: MCP publishes only a command's first docstring line, and `tests/contract/test_project_reports_reads_mcp.py` reads the field descriptions (C-1).
  - For WP5, the read service offers `project_summary`, `match_rfis` and `availability`; they are not MCP tools (design 2.12).
- **Migration.** One vocabulary-only revision, `3b3373d8268e` on `fa18ef3d9bc0`: the audit `capability_is_known` and `purpose_is_known` CHECKs gain the 5 names and `project_reports_read`; no table, index, view or `GRANT`.
- **S6, the Program rollup: deferred to a later WP (ruling D5 (b)).** No `program_entity_id` request field, `program_total` or Program answer-only reason exists; every read is per Project. Residual: R-OP-5 OQ-04's Program rollup (design 2.7) waits for that WP.

## 9. MCP registration plan

- **Names validated against the conventions.** Capability values are `<family>.<verb>` with a snake_case family (`project_controls.*`, `schedule_publications.*`, `native_sources.*`) and lowercase verbs. Verb precedents: `schedule_baselines.compare`, `knowledge.coverage` (and the proposed `communications.coverage`), `entities.identity_history` (a qualified `_history`). `project_reports.catalog / query / record_history / compare / coverage` therefore fits, with 3 justified choices:
  - the family is `project_reports`, not `reports`: `reports.*` is the authored Intelligence report plane and these are source exports (section 1.4); not `pulse` or `procore`: capability names stay neutral (`AGENTS.md` section 4), as `communications.*` does not say Outlook;
  - `query`, not `search`: `*.search` in this repository means ranked text search (`reports.search`, `meetings.search`, the proposed `communications.search`); this read is a structured, filtered, measure-bearing query;
  - `record_history`, not `history`: `history` alone would read as the history of the export, and the qualified form has the `entities.identity_history` precedent.
- **Registration.** `Capability` members, permitted purposes `{project_reports_read}`, manifest entries, handlers in the dispatch table, the thin MCP adapter's publication (no logic in `adapters/mcp/`), the remote read classification (all 5 are reads), the ChatLLM data-conditional prerequisite `PROJECT_REPORTS`, and the WP4P audit-vocabulary migration. Policy-closure tests cover the new names.
- **Not capabilities.** Binding apply/check, filter definitions, ingestion, backfill and rebuild are operator CLI commands (`tests/architecture/test_operator_commands_are_not_capabilities.py`). There is no client write, ingest or delete over PULSE.
- **Gates (operator).** Grants and the external-model eligibility decision for returning PULSE text (titles, descriptions, minutes, names) to a connected client (`AGENTS.md` section 5) precede any grant.

## 10. Integration with communications

- **Shared, not coupled.** The lifecycle is shared (section 1.2); domain code is not. No communications module imports a PULSE module or the reverse; the WP5 meeting-context service composes both through their application read services.
- **Meeting context (WP5, contract section 15).** `meetings.context.read` gains a `pulse` section per Meeting when its Project has an ingested PULSE source: latest-version counts of open observations, coordination issues and RFIs by status class (with filter semantics stated), the RFIs whose numbers match identifiers found in the Meeting's communications and notes (section 6.3 matching; `ambiguous_prefix` returned as candidates), and the PULSE coverage block. Bounded: ≤ 10 RFIs and ≤ 5 measures per Meeting; full detail through `project_reports.query`.
- **No OAC-to-Meeting matching.** An OAC meeting number is not joined to a my-pa Meeting by date or title (contract section 12.2's principle). A later explicit binding may be designed.
- **PULSE absent.** When PULSE is off, unbound, never ingested or failing, the section is `pulse: {state: "unavailable", reason}` and communications are unaffected; a WP5 test pins communications-only answers byte-identical with and without the PULSE tables empty.
- **Identifier vocabulary.** Communications' `rfi:<n>` (contract section 7) and PULSE's `rfi` keys meet only through the section 6.3 matching rule; R5's open WP4 defect (extractor recall) limits WP5's RFI join and is stated in its answers' versions block.
- **As built (WP5, merged in #397).** `meetings.context.read` answers a `pulse` section per Meeting from the batched facade `ProjectReportReads.context_summaries` (WP5 ruling D7): `unavailable` / `reads_disabled` with `MY_PA_PROJECT_REPORTS_ENABLED` off (nothing read), `not_linked` without a Project, `unavailable` with the facade's reason, or `available` with at most 5 latest-version counts (observations, coordination issues, RFIs) and the RFIs of at most 10 numbers, the Meeting's own first, then its messages' (`ambiguous_prefix` as candidates), with the versions and qualifiers read. A PULSE read error fails the request (ruling D-7). The record is [contract section 15](../architecture/communications-intelligence-contract.md#15-meeting-context-assembly-wp5).

## 11. Worker/NAS changes

- **As built (section 17, drift 19):** a separate lifecycle instance and its own cycles step `project_reports_ingest`, with `MY_PA_PROJECT_REPORTS_INGEST_ENABLED`, `MY_PA_PROJECT_REPORTS_INGEST_POLL_SECONDS` and `PROJECT_REPORTS_POLL_LOCK_KEY`; the runbook is [`ops/runbooks/project-reports-ingestion.md`](../../ops/runbooks/project-reports-ingestion.md).
- **No new process, plane, container, mount or cron.** The PULSE consumer runs in the lifecycle poll step on the cycles plane (`apps/worker.py run --plane cycles`, contract section 19), behind its own switch `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` (default off) and its own advisory lock key, interval default 15 minutes.
- **Reads** go through the files workspace store's read path (list, stat, streamed read) under the Manager ruling R1 (contract section 21), subject to the same ADR-019 decision 7 preflight WP3 runs; PULSE adds no source root.
- **Environment.** 2 new settings in the operator's env file at deployment; no compose change is expected (the worker already composes the workspace read for communications after WP3). If WP3's preflight requires a compose change, PULSE inherits it.
- **Crosswalk at deployment.** The operator runs `bindings check` then `bindings apply` with the operator-held file; no file is shipped in the image.
- **Monitoring.** Per run: snapshots by outcome, quarantine reasons, unbound folders, reconciliation mismatches; per series: freshness. Log lines carry codes and counts only. A runbook under `ops/runbooks/` in WP3P, labelled unexecuted until executed.

## 12. Test strategy

### 12.1 FAST (synthetic fixtures under `tests/fixtures/project_reports/`)

Each case is a small synthetic CSV with synthetic project numbers, vendors and amounts:

- every one of the 15 header signatures, plus a reordered-header variant (new signature → quarantine) and an unknown family;
- role classification: flat; 1-level; 2-level with `(Blank)`; `Grand Totals`; spacer rows; grouping-only; a header followed by no detail; in a 2-level export, a level-1 header followed directly by a level-2 header stays `group_header(1, key)` while a level-2 header with no detail before the next level-1 or level-2 header is `grouping_only`; a malformed width; role counts summing to rows;
- the 2-level double-count case (detail-only sum = 99 against a naive 198, synthetic);
- RFC 4180: embedded CRLF in quotes, doubled quotes, a trailing record without terminator, BOM, non-UTF-8, unterminated quote;
- byte-exact reconstruction of every fixture from Layer A records;
- money: currency-sign form, parentheses negatives, more than 4 decimals refused, empty, zero; no float anywhere;
- subtotal reconciliation match and a planted mismatch → `not_reportable`;
- status-class separation and the cross-report check (synthetic numbers reproducing the real shape: approved-only grand total = CO subtotals + approved `(Blank)` PCO lines);
- budget-change cross-view duplicates never summed together; commitment under 2 codes; 2 padding styles;
- identities per family; RFI repeats kept; unnumbered RFI without identity; RFI matching (`174` vs `1740`, `GMP-174` vs `CD 50%-174`, `ambiguous_prefix`);
- `not_observed_in_latest` and compare across 2 synthetic versions; slug sharing a signature as 2 series;
- binding file validation: every section 6.4 refusal, unmapped folder, synthetic `prj_` ids only;
- hostile cell content (formula prefixes, prompt-injection text, markup) kept inert.

### 12.2 Architecture guards

`test_project_reports_scope.py`: the domain imports only the standard library and itself and does no IO; only `infrastructure/project_reports/pulse_csv.py` names Procore header strings; no `float` in PULSE modules; no PULSE module imports a communications module or the reverse; Layer B measure code reads only `detail` rows (an AST-level check on the query builder); fixtures are synthetic (no real project display name, no currency amount from the evidence). Existing partition, principal and policy-closure guards gain the new tables and names.

### 12.3 DB tier and real-data validation

- DB tier: migration from empty and from the predecessor head; append-only and TRUNCATE refusals; partition guard; idempotency (same SHA-256 twice writes once); the byte-identical file in 2 sources = 2 snapshots; binding apply atomicity and every refusal; quarantine keeps Layer A `unclassified` rows; backfill resume; dry run writes nothing; downgrade refuses with rows.
- **Manager-only real-data validation**, aggregate output, in an isolated local database: `PYTHONPATH=src python -m my_pa.infrastructure.project_reports.aggregate_cli FILE [FILE ...]` (from a source checkout; `-I` ignores `PYTHONPATH`, so use `python -I -m …` only where the package is installed) prints counts, roles, signatures, completeness classes and reconciliation outcomes only. It must reproduce the evidence: 20 files, 15 signatures, 2,593 data rows, the per-file role counts, 143/143, 9/9, 3/3, 3/3 matches, the cross-report match.

## 13. Deployment and migration

- Order: WP3 lifecycle deployed (or deployed together) → WP3P migration → operator `bindings apply` → ingestion switch on → dry run, then the first run → aggregate check against section 12.3's figures → WP4P migration and read switch → grants (operator).
- Switches default off; recovery is switch-off with rows retained. No destructive rollback; a downgrade refuses while rows exist.
- Production migration, binding apply, switch changes, grants and the eligibility decision are operator actions; deployment follows the NAS deployment procedure of the time (`ops/runbooks/`).
- The crosswalk file never enters the image, the repository or a log.

## 14. Work-package sequencing

### 14.1 Order

| WP | Content | Depends on |
| --- | --- | --- |
| WP2 | meeting provider identity and recurrence (contract section 12) | WP1 |
| WP3 | shared lifecycle + communications persistence, ingestion, coverage, backfill, scheduled poll (contract sections 1, 5, 9–11, 19) | WP2 |
| **WP3P** | PULSE domain, adapters, Layer A and B, registry and bindings CLI, ingestion consumer, aggregate CLI, runbook (sections 2–7, 11, 12) | WP3 merged |
| WP4 | communications search and its MCP reads | WP3 |
| **WP4P** | PULSE reads and MCP registration (sections 8, 9) | WP3P, WP4 |
| WP5 | batch meeting context with the optional PULSE section (section 10) | WP4, WP4P |

One work package at a time (`AGENTS.md` section 8.3). Communications-only must work at every step: WP4 and WP5 never require WP3P or WP4P to be deployed.

### 14.2 Requirements this plan places on WP3

1. `consumer = pulse_csv_export` in the closed set (already in the contract).
2. Snapshot uniqueness per source, aliasing only within a source (section 6.1).
3. A snapshot state `quarantined` (or a rejection subtype) that keeps the snapshot row and lets the consumer keep its rows; content-free.
4. A consumer hook interface in the poll step: list, stability check, consumer parse, consumer persist, per-snapshot transaction.
5. Coverage bookkeeping that allows a consumer without time windows (PULSE coverage is per series, evidence: historical coverage section 6).

### 14.3 ADR

PULSE needs a decision record before WP3P merges: a new ADR (next free number after ADR-022; ADR-020 is taken by PR #368 and the number between by PR #370) or an ADR-022 amendment, recording sections 1.3, 1.4, 6.4 and 7. **Done:** [ADR-024](../decisions/ADR-024-project-report-source-evidence.md), accepted under operator delegation 2026-11-22, effective on the WP3P merge (ADR-023 was taken by the P6 XER import). Operator ratification is required for it, as it was for ADR-022 (accepted under operator delegation 2026-11-22, R-OP-1).

## 15. Acceptance criteria

| ID | Criterion | Evidence |
| --- | --- | --- |
| PULSE-AC-01 | No PULSE lifecycle table; PULSE uses `ingest_*` rows only | scope guard; DB schema test |
| PULSE-AC-02 | Every data row of every accepted or quarantined snapshot is in Layer A with exactly 1 role; role counts sum to rows | FAST + DB tier |
| PULSE-AC-03 | Every fixture reconstructs byte-exact from Layer A (SHA-256 equal) | FAST |
| PULSE-AC-04 | Adapter selection uses the header signature only; an unknown signature quarantines with rows preserved | FAST + DB tier |
| PULSE-AC-05 | No float in any PULSE module; money is `NUMERIC(20,4)`; >4 decimals refused | AST guard + FAST |
| PULSE-AC-06 | Measures sum detail rows only; the 2-level double-count case returns the detail sum | FAST + DB tier |
| PULSE-AC-07 | Approved, pending, void and unknown measures are separate; none is read from a subtotal | FAST |
| PULSE-AC-08 | Non-additive stated totals are never returned as measures | FAST + contract test of `project_reports.query` |
| PULSE-AC-09 | Reconciliation mismatch → `not_reportable` with reason; unloaded column → `source_column_unpopulated`; no zero substituted | FAST |
| PULSE-AC-10 | `filter_semantics` is `unknown` unless an operator definition exists; no status or recency is derived from a slug | FAST |
| PULSE-AC-11 | No closure is inferred from disappearance; `not_observed_in_latest` is returned instead | FAST (synthetic versions) |
| PULSE-AC-12 | Binding apply fails closed on each section 6.4 refusal and writes nothing; unbound folders are never ingested; every change is an audited revision | DB tier |
| PULSE-AC-13 | The byte-identical file in 2 project folders is 2 snapshots | DB tier |
| PULSE-AC-14 | RFI matching is exact on suffix and prefix; `ambiguous_prefix` flagged | FAST |
| PULSE-AC-15 | The 5 names are registered with purpose `project_reports_read`, default off, read-only, policy-closed; no client write | policy tests |
| PULSE-AC-16 | Meeting context returns communications unchanged when PULSE is absent, with `pulse.state = unavailable` | WP5 tests: **met in #397** -- database `tests/database/test_meeting_context_pulse.py` (communications byte-identical with the switch off, the tables empty and populated) |
| PULSE-AC-17 | The Manager's aggregate run reproduces the evidence figures (section 12.3) | aggregate CLI output |
| PULSE-AC-18 | No committed file holds a project display name, a crosswalk entry, a real `prj_`/`ent_`/`prn_` identifier, or a real amount | leak scan + fixture guard |

## 16. Risks

### 16.1 Open questions for operator ratification

| ID | Question | Default until answered |
| --- | --- | --- |
| PULSE-OQ-01 | **Filter semantics** of each saved report (what does each slug's filter actually select?) | `unknown` everywhere; counts carry the qualifier |
| PULSE-OQ-02 | **RFI duplicate rows** in the status views: revisions or duplicate export rows? | every row kept as an observation; canonical RFI by number; counts of RFIs use distinct numbers and state the row count beside them |
| PULSE-OQ-03 | **Commitment CO ambiguity**: how is a commitment CO line tied to its commitment (a different saved report including the commitment column?) | no canonical identity; amounts reported by status class within the export only |
| PULSE-OQ-04 | **Program membership** of the 3 projects (no verified entity or program relationship yet) | no Program-level PULSE answer; per-Project only |
| PULSE-OQ-05 | External-model eligibility of PULSE text and names returned to connected clients | no grant |
| PULSE-OQ-06 | 1 folder per Project in v1 | refuse a second folder |
| PULSE-OQ-07 | Original budget column unloaded: is a budget export planned? | `not_reportable` |

Manager-level decision (not operator): section 7.1's money reuse. Decided by Manager ruling 2026-11-21: option B (a PULSE-local parser with a parity test; the ADR-018 isolation guard unchanged).

### 16.2 Risks

| Risk | Mitigation |
| --- | --- |
| Procore changes column order or names | signature registry; unknown → quarantine with rows kept; new adapter in a PR |
| The operator renames a saved report | a new series; history continuity is not inferred (could be linked by a later operator action) |
| Filters change silently between versions | `filter_semantics` per series; compare reports `not_observed`, never "closed" |
| Mis-bound folder | fail-closed apply, project-number cross-check at ingest, audited revisions |
| Raw rows hold names, descriptions and minutes | Principal partition, no logging of content, eligibility gate before grants, inert content |
| Double counting by a future query | detail-only guard in code and in tests; measures as a closed set per family |
| Lifecycle built without PULSE needs | section 14.2 requirements reviewed in WP3 |
| Only 1 publication exists | longitudinal behaviour validated synthetically; first real second-generation export is re-checked by the Manager's aggregate run |
| Storage growth from raw rows | about 360 KB for 20 files; append-only rows; retention is a later operator decision |
| Over-broad trigram text search over minutes | bounded text length, per-row text caps, no FTS document in v1 |

## 17. As built (WP3P, 2026-11-24)

WP3P was built on branch `feat/pulse-reports`, stacked on WP3b, in slices S1–S6 under the Manager rulings D1–D19 of 2026-11-24 (made on the WP3P investigation; they override this plan where they differ). The decision record is [ADR-024](../decisions/ADR-024-project-report-source-evidence.md) and the operator procedure is [`ops/runbooks/project-reports-ingestion.md`](../../ops/runbooks/project-reports-ingestion.md). This section supersedes the passages of sections 2–14 named below; the rest of the plan stands as written.

| # | Plan said | As built |
| --- | --- | --- |
| 1 | basis `f586b6c9`, the migration "on whichever head is current" | 1 additive revision `0d4e247d03cb` on `61fafdfd2986` (WP3b); no test spells the Alembic head (the pins accessors); pins are regenerated at the main merge |
| 2 | 14.3: "next free number after ADR-022" | ADR-023 is the P6 XER import; PULSE is ADR-024, which landed with its index row and its first citations in 1 commit |
| 3 | 5.1 `source_id` | `ingest_source_id` everywhere |
| 4 | 5.1 index on `project_report_snapshots (…, first_seen_at DESC)` | `first_seen_at` is the lifecycle's; reads join `ingest_snapshots` (about 20 files) |
| 5 | 4.5 `oversize` rejection | no such code: an oversized file (over 16 MiB) is the lifecycle's `skipped_too_large`, with no row; rejection codes are `not_utf8`, `malformed_csv`, `invalid_header`, `nul_byte` |
| 6 | 4.5 and 14.2 item 3: a lifecycle `quarantined` snapshot | consumer-level quarantine (D3): an `ingested` snapshot whose current derivation is `quarantined` (`unknown_header_signature`, `malformed_ratio_exceeded`, `binding_project_number_mismatch`), every raw row kept |
| 7 | 6.4 1 `audit_events` row per apply; `--reason CODE` | no audit row (D6): the append-only binding revisions are the audit (`recorded_by = operator_cli`); no `--reason` argument, each revision records the reason its change kind names (`initial`, `add`, `correction`, `filter_update`, `retire`) |
| 8 | 6.2 a filter definition is an audited operator CLI action | an optional `reports[{slug, filter}]` declaration in the bindings file (D8, R-OP-5 OQ-01), applying to versions first seen at or after it |
| 9 | OQ-02, OQ-03, OQ-06 defaults | unchanged (R-OP-5) |
| 10 | OQ-04: no Program-level answer | per-Project by default; every typed row carries `project_id`, so a Program rollup is possible on a verified relationship (WP4P) |
| 11 | OQ-05: no grant | `project_reports.*` grants to the operator profile at activation (R-OP-2, R-OP-3); WP4P |
| 12 | OQ-07: `not_reportable`, picked up only by an operator rebuild | an unknown signature quarantines with rows kept and is re-derived automatically by the sweep once its adapter ships (D1, D9); the operator `rederive` remains |
| 13 | 6.4 a run-time cross-check mismatch quarantines the snapshot | a mismatch quarantines the derivation (`binding_project_number_mismatch`, D11); a binding correction re-derives it automatically |
| 14 | 6.4 rule 5 "inside the workspace's PULSE export area" | the bindings file declares `export_root`; each folder must sit strictly inside it (`folder_outside_export_root`) and exist (`folder_not_found`, D19) |
| 15 | 5.2 mutable `latest_snapshot_id`, `latest_status_class` | none (D10): "current" is the derivation nothing supersedes, read through the view `project_report_current_derivations`; derivation and binding-revision chains are append-only, linear and acyclic |
| 16 | 2: modules `domain/project_reports/*` | as planned; the lifecycle neutrality guard was widened to the project-reports modules |
| 17 | 9: `project_reports.*` | no `Capability`, `Purpose`, `IdKind` or table name carries `pulse` or `procore` (guard `tests/architecture/test_project_reports_scope.py`); `continuity.pulse` already exists |
| 18 | 9: `record_history` | built by WP4P as `project_reports.record_history` (WP4P ruling D1 (a)), with `catalog`, `query`, `compare` and `coverage`, all reads under the purpose `project_reports_read`; section 8 "As built (WP4P)" |
| 19 | 2, 11: `MY_PA_PROJECT_REPORTS_ENABLED` and `…_INGEST_ENABLED` in WP3P; the consumer joins the comms poll step | WP3P adds only `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` (default off) and `MY_PA_PROJECT_REPORTS_INGEST_POLL_SECONDS` (900, 60–86,400); the read switch is WP4P's, built in WP4P-S4 as `MY_PA_PROJECT_REPORTS_ENABLED` (default off), independent of the ingest switch. A separate `IngestionLifecycle` instance runs as its own cycles step `project_reports_ingest` under `PROJECT_REPORTS_POLL_LOCK_KEY` (D5), then the re-derivation sweep; the cycles plane has 3 switches, any 1 of which starts it |
| 20 | 12.3: 1 aggregate CLI over files and an isolated database | 2: the file-level `infrastructure/project_reports/aggregate_cli.py` and the operator command's DB `aggregate`, under the same keys, each with `--expect` against `tests/fixtures/project_reports/expected/evidence_aggregate_v1.json` (D14) |
| 21 | 5: "schema placement follows WP3" | `knowledge.project_report_*` |
| 22 | 3: 2 new `IdKind` prefixes | 3: `prbnd`, `prrec`, `prdrv` |
| 23 | 7.1: amounts `NUMERIC(20,4)`, ADR-018 guard unchanged | as planned, and ADR-024 decision 2 records that PULSE money is source evidence, not the ADR-018 controlled financial source; no financial value is written to any product-owned record (D13) |
| 24 | contract section 1.2 bullet list | PULSE follows the contract's "as built" block, which section 1.2 now cites for PULSE |
| 25 | 12.2: no PULSE module imports a communications module or the reverse | as planned; composition is `bootstrap/project_reports.py`, separate from the communications bootstrap |

**Also as built.** `bindings apply` admits, binds and enables in 1 transaction under the poll lock (`IngestionLifecycle.admit_within`, D7); a folder omitted from a later file is retired (source disabled, rows kept). `run-once` and `backfill` refuse `source_unbound` up front, writing nothing, when the source has no active binding (D12 and the Manager ruling on S5); the handler's in-transaction `source_unbound` stays as defence in depth. Row roles include `grouping_only` per level (evidence rule 7), so a level-1 header with no line beneath it is `grouping_only`, not a group header. Buyout's line kinds treat a vendor beside only the never-loaded original-budget cell as `vendor_only`.

**Manager real-data result (counts only, 2026-11-24, scratch database at `013b3bcb1`).** `bindings apply` bound 3 sources; the backfill wrote 20 snapshots, 0 failed, 0 quarantined; the project-number check matched 3 and the cross-report check matched 1; the DB `aggregate --expect evidence_aggregate_v1.json` matched 340 of 340 (exit 0); a rerun was idempotent (20 already known). The earlier file-level run (S2) matched 333 of 340, then 340 of 340 after the 2 corrections noted in the evidence (the vendor-only rule; 96 grouping-only buyout level-1 headers the inventory had counted as headers against its own rule 7). PULSE-AC-17 is met on that run.
