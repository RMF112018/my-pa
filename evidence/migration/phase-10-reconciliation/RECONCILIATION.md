# Phase 10 — Cross-Domain Reconciliation and Acceptance

Generated 2026-08-01T16:05:34+00:00. Every number below was recomputed from the legacy
SQLite file and from PostgreSQL directly; the control plane's own counters are
checked, not trusted.

**Phase 10 PASSES WITH WAIVERS against OD-012.** Every criterion holds except ones a named decision authorises in advance.

- WAIVED `P10-02` under OD-029 — every MIGRATE_DATA table's target count equals its source count (2 of 197 differ; 0 without an adjudicating decision).

## Bound identity

The campaign migrates the schema-128 source under OD-001, not the schema-135
snapshot the plan named; that file does not exist on this machine. The deviation
is recorded here rather than reconciled away.

| fact | value |
|---|---|
| source file | hb-personal-assistant.sqlite |
| source sha256 | `9b8c8d8b151735af3773a1c9a3843166a6c1b542f90c6f9823e3821a90a37f6f` |
| source bytes | 4,368,125,952 |
| source schema_migrations version | 128 |
| target Alembic revision | `6c4d3ea82f10` |
| journal siblings beside the source | none |
| runs agreeing with the measured digest | 2/2 |

### Runs

| run | status | dry run | schema | revision | bytes | sha256 (first 16) |
|---|---|---|---|---|---|---|
| `9c36cf05-b5f1-4382-94b0-0328679a3373` | COMPLETED | False | 128 | `4b9f0d27ac31` | 4,368,125,952 | `9b8c8d8b151735af` |
| `ed06aadf-c1de-42f4-bc32-a2ce33c5975a` | COMPLETED | False | 128 | `3a8e2cb16d59` | 4,368,125,952 | `9b8c8d8b151735af` |

No `-wal`, `-shm`, or `-journal` sibling exists beside the live source file.
Every read used `immutable=1`, which is what makes that true rather than lucky.

## Headline numbers

| measure | value |
|---|---|
| tables loaded | 398 |
| source rows in loaded tables | 3,263,878 |
| rows in the target | 3,263,870 |
| rows quarantined | 8 |
| objects deliberately not created | 109 |
| source rows deliberately excluded | 51,744 |
| source rows withheld from the target in total | 59,572 (1.79%) |
| tables asserted empty | 90 |
| tables created in the target | 484 |
| plan objects absent from the source | 15 |
| foreign keys validated | 277 of 277 |
| identifier renames recorded | 764 |
| identity sequences checked | 49 |

The first two rows overlap by 4: a `PROVENANCE_ONLY` table
is loaded *and* asserted empty, so it appears in both. That is why
398 + 90 exceeds the
484 tables actually created. Both figures are correct and no
total below double-counts a row; the arithmetic just needs the note.

## Acceptance criteria (OD-012)

`WAIVED` means a decision in the register adjudicated the shortfall before it
happened and the waiver names that decision. It is not a pass and it is not
discretion exercised here; a shortfall no decision has looked at is a `FAIL`.

| id | criterion | result | waiver | measured |
|---|---|---|---|---|
| P10-01 | every loaded table's source rows are either in the target or in quarantine | PASS | — | 398 tables; 0 unaccounted |
| P10-02 | every MIGRATE_DATA table's target count equals its source count | WAIVED | OD-029 | 2 of 197 differ; 0 without an adjudicating decision |
| P10-03 | no row was lost silently: every shortfall is a named quarantine record | PASS | — | 8 quarantined rows in 2 groups |
| P10-04 | identity coverage: one source_key_map entry per loaded row of a keyed table | PASS | — | 0 tables with incomplete coverage |
| P10-05 | keyless tables reconcile by source_row_hash multiset equality (OD-014) | PASS | — | 1 keyless tables; 0 unequal |
| P10-06 | no orphan on a required foreign key | PASS | — | 277/277 validated; 0 orphan rows |
| P10-07 | no duplicate on a required unique key | PASS | — | 0 DUPLICATE_NATURAL_KEY records |
| P10-08 | deliberately empty classes are asserted empty | PASS | — | 90 tables asserted; 0 not empty |
| P10-09 | every excluded object is named, priced, and absent from the target | PASS | — | 109 excluded objects, 51744 source rows |
| P10-10 | the ABSENT_FROM_SOURCE_AT_SCHEMA_128 list matches OD-001 exactly | PASS | — | 15 objects |
| P10-11 | every loaded row carries a complete provenance stamp | PASS | — | 3263870 rows over 286 tables |
| P10-12 | every identity sequence is at max(key) + 1, or at 1 for an empty table | PASS | — | 49 sequences; 0 misplaced |
| P10-13 | the source file is byte-identical to what every run bound itself to, and no journal sibling was created | PASS | — | 2/2 runs agree; 0 journal siblings |
| P10-14 | the evidence tree passes the personal-data redaction scan (OD-004) | PASS | — | 0 findings over 94 files |
| P10-15 | every source object has a disposition and every source row is in one bucket | PASS | — | 593 source tables, 3323450 rows; 0 in no bucket |
| P10-16 | each SQLite read model is ported as a target view whose row count equals the source view's (OD-018) | PASS | — | 2 source views; 0 unreconciled |
| P10-17 | every departure from the plan's dispositions is declared with its decision | PASS | — | 4 departures; 0 without a governing decision |

## 0a. Departures from the plan's dispositions

OD-008 assigned every legacy table a treatment. Four planning classes did **not**
get the treatment the plan named: each was reversed by a later decision, and each
reversal loaded data the plan would have left out of the target. They are listed
here together so the fact is discoverable without cross-tabulating the appendix.

Nothing here is a defect. All four reversals are governed, and the point of this
section is disclosure, not correction.

| planning class | OD-008 said | decision | tables loaded | rows loaded | tables withheld | rows withheld |
|---|---|---|---|---|---|---|
| `ARCHIVE_LEGACY_SOURCE_ONLY` | not created in the target | OD-025 | 46 | 221,536 | 0 | 0 |
| `DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION` | not created in the target | OD-025 | 14 | 3,558 | 2 | 4 |
| `REBUILD_AND_VALIDATE` | schema created, left deliberately unpopulated | OD-025 | 132 | 1,330,813 | 12 | 32,203 |
| `REINITIALIZE_OPERATIONAL_STATE` | schema only, empty by design | OD-028 | 5 | 5,388 | 85 | 7,828 |

A class with a non-zero figure in both loaded and withheld was **split**, not
reversed wholesale. Reading either column alone misstates what happened to it.

`DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION` withheld: `construction_email_intelligence_deferred_state`, `raw_content_model_context_packets`.
`REBUILD_AND_VALIDATE` withheld: `obsidian_note_fts`, `obsidian_note_fts_config`, `obsidian_note_fts_content`, `obsidian_note_fts_data`, `obsidian_note_fts_docsize`, `obsidian_note_fts_idx`, `source_intelligence_fts`, `source_intelligence_fts_config`, `source_intelligence_fts_content`, `source_intelligence_fts_data`, `source_intelligence_fts_docsize`, `source_intelligence_fts_idx`.
`REINITIALIZE_OPERATIONAL_STATE` withheld 85 tables; they are listed in sections 6 and 7.

## 0. Global row accounting

The sweep starts at the source's own `sqlite_master`, not at the disposition
registry: a registry that omitted an object would otherwise reconcile perfectly
against itself while a table went missing. Every source table is placed in exactly
one bucket and the row counts have to add up.

| bucket | rows |
|---|---|
| loaded | 3,263,878 |
| deliberately not created | 51,744 |
| created and asserted empty | 7,828 |
| **total bucketed** | **3,323,450** |
| **source rows, all tables** | **3,323,450** |

593 tables exist in the source catalogue and
593 carry a disposition.

**59,572 source rows (1.79%) reach no
target table**, by either route; 3,263,878 (98.21%) do.

OD-025 puts the withheld figure at 64,960 with operational state at 13,216. That
number is stale: it was derived before OD-028 moved five `*_runs` tables (5,388
rows) into scope, and 64,960 - 5,388 = 59,572. The figure above is computed from
the registry and the source rather than restated, and it is the one to use.

The buckets balance exactly against the source. No row is unaccounted for and
no source object is missing a disposition.

## 1. Row-count parity

Every one of the 398 tables whose treatment carries data was counted
on both sides. The full per-table listing is the appendix; this section names only
the tables where the two numbers differ, and no difference is aggregated away.

2 tables differ:

| legacy table | source | target | quarantined | unexplained |
|---|---|---|---|---|
| `source_intelligence_chunks` | 2,926 | 2,920 | 6 | 0 |
| `source_intelligence_text` | 5,738 | 5,736 | 2 | 0 |

Every difference is accounted for row-for-row by a quarantine record naming
the table, the column, and the reason. No row went missing without a name.

## 2. Quarantine

8 rows were refused and named. Each is recorded by table,
column, error code, and a hash of its key -- never by value.

| error code | legacy table | column | rows |
|---|---|---|---|
| UNSUPPORTED_TEXT_NUL | `source_intelligence_chunks` | `chunk_text` | 6 |
| UNSUPPORTED_TEXT_NUL | `source_intelligence_text` | `text_excerpt` | 2 |

The columns above are read from `migration_control.quarantine_records`, not
from OD-029, which names `text_content` on both tables. That column does not
exist on either; the measured names are the ones in this table and they are
what a reader should search for. The decision's substance is unaffected: the
rows are refused and named rather than stripped of a byte of the owner's
content, and the legacy source retains the originals unchanged.

## 3. Identity coverage

`migration_control.source_key_map` holds one entry per loaded row of a keyed
table. 397 loaded tables have a source-side key; 1 do not.

| class | tables | map entries | target rows |
|---|---|---|---|
| keyed | 397 | 3,228,581 | 3,228,581 |
| keyless (OD-014) | 1 | 0 | 35,289 |

The keyless tables are legitimately absent from `source_key_map`: `schedule_cpm_relationship_results`.
OD-014 refuses to invent a business key the source never had, so identity for
these is content equality, checked in section 4.

Every keyed table's coverage equals its loaded row count.

## 4. OD-014 — the keyless table

`schedule_cpm_relationship_results` has neither a primary key nor a unique index in
the source, so a row count is not the guarantee. The check recomputes the SHA-256 of
every source tuple and compares the two multisets against the stored
`migration_source_row_hash`, which catches reordering, duplication, and truncation.

| legacy table | source | target | distinct surrogate ids | distinct hashes | only in source | only in target | multisets equal |
|---|---|---|---|---|---|---|---|
| `schedule_cpm_relationship_results` | 35,289 | 35,289 | 35,289 | 35,289 | 0 | 0 | yes |

## 5. Foreign keys

SQLite never enforced its declared constraints, so the migration adds every foreign
key `NOT VALID` and then validates it (OD-017). This check counts the result and
prices anything still unvalidated. It never validates a constraint itself: doing so
would change the database the report describes.

| schema | foreign keys | validated | NOT VALID |
|---|---|---|---|
| calendar | 5 | 5 | 0 |
| construction | 10 | 10 | 0 |
| core | 41 | 41 | 0 |
| email | 10 | 10 | 0 |
| financial | 40 | 40 | 0 |
| migration_control | 7 | 7 | 0 |
| procore | 150 | 150 | 0 |
| schedule | 14 | 14 | 0 |

Total 277, validated 277, left `NOT VALID` 0, orphan rows 0.

## 6. Deliberately empty classes, asserted empty

Each of these tables exists in the target and is required to hold no rows. Every one
was queried; none is assumed.

| treatment | tables | source rows withheld | target rows |
|---|---|---|---|
| PROVENANCE_ONLY | 4 | 0 | 0 |
| SCHEMA_ONLY_ASSERT_EMPTY | 1 | 0 | 0 |
| SCHEMA_ONLY_EMPTY_BY_DESIGN | 85 | 7,828 | 0 |

The operational-state class has 85 members rather than 90:
OD-028 loads five provenance tables out of it, because withholding the rows that
record which computation produced the derived data would have manufactured orphans
rather than preserved a clean slate. Those five are `forecast_runs`, `procore_live_sync_runs`, `schedule_cost_mapping_runs`, `schedule_cpm_runs`, `schedule_quality_evaluation_runs`, and they appear in the parity appendix as loaded tables.

Every asserted-empty table holds exactly zero rows.

## 7. The excluded objects

109 source objects carrying 51,744 rows are
deliberately not created in the target. Every one is named below with its planning
disposition, its reason, and its source row count, so the exclusion is auditable
rather than assumed.

| treatment | objects | source rows |
|---|---|---|
| NOT_CREATED | 68 | 24 |
| NOT_CREATED_FTS_REBUILT_IN_POSTGRES | 12 | 32,203 |
| NOT_CREATED_PRIVACY_GATED | 2 | 4 |
| NOT_CREATED_SUPERSEDED | 27 | 19,513 |

None of them exists in the target database.

### The deferred class was split, not withheld

`DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION` has 16 tables in the source.
**14 were loaded** (3,558 rows) and **2 were withheld** (4 rows). The `NOT_CREATED_PRIVACY_GATED` count of 2 in the table above is the
withheld part only and must not be read as the whole class.

Withheld, and the only two the privacy gate meant (OD-025): `construction_email_intelligence_deferred_state`, `raw_content_model_context_packets`.

The rest are `NONSENSITIVE_OR_OPERATIONAL_METADATA` and were loaded as
ordinary owner-owned data. Migrating data is not activating a product
feature -- the distinction OP-PROD-001 drew and OD-025 applied here.

### Every excluded object

| legacy object | kind | planning disposition | reason | source rows |
|---|---|---|---|---|
| `assistant_claims` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_decision_records` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_feedback_recommendations` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_feedback_records` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_feedback_targets` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_memory_mentions` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_memory_nodes` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_open_loop_records` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_output_file_manifest_entries` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_output_file_versions` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_output_files` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_preference_records` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_quality_findings` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_quality_targets` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_review_dispositions` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `assistant_review_items` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `calendar_events` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `construction_document_projection_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `construction_email_intelligence_deferred_state` | table | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | withheld by the privacy gate (OD-025, OP-PROD-001) | 0 |
| `emails` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `obsidian_note_fts` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 5,000 |
| `obsidian_note_fts_config` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 1 |
| `obsidian_note_fts_content` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 5,000 |
| `obsidian_note_fts_data` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 2,097 |
| `obsidian_note_fts_docsize` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 5,000 |
| `obsidian_note_fts_idx` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 1,851 |
| `pa_artifact_links` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_artifact_promotion_bundles` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_artifact_proposal_bundles` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_artifact_proposal_versions` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_artifact_proposals` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_artifact_repair_tasks` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_artifact_review_decisions` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_canonical_artifacts` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_client_tool_manifests` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_prompt_workflow_recipes` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_session_captures` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_tool_families` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_tool_manifest_entries` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_tool_manifest_refresh_proposals` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_tool_routing_entries` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `pa_workflow_route_recipes` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `phase_07d_validation_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `phase_08a_validation_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `procore_endpoint_contracts` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_ep_projects_custom_fields_custom_field_163305_value` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_financial_payment_applications` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_raw_billing_periods` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 67 |
| `procore_raw_budget_change_line_items` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_raw_budget_modifications` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 805 |
| `procore_raw_budget_views` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 35 |
| `procore_raw_change_events` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 1,106 |
| `procore_raw_company_dimensions` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_raw_inspection_items` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 8,856 |
| `procore_raw_inspection_sections` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 288 |
| `procore_raw_inspections` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 208 |
| `procore_raw_location_dimensions` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_raw_meetings` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 576 |
| `procore_raw_observations` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 1,492 |
| `procore_raw_payment_applications` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_raw_person_dimensions` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_raw_punch_items` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 89 |
| `procore_raw_rfis` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 2,027 |
| `procore_raw_rfqs` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 291 |
| `procore_raw_schedule_activities` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 1,609 |
| `procore_raw_schedules` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 4 |
| `procore_raw_submittal_responses` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 0 |
| `procore_raw_submittals` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 1,864 |
| `raw_content_model_context_packets` | table | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | withheld by the privacy gate (OD-025, OP-PROD-001) | 4 |
| `schedule_quality_metric_results_v66` | table | REPLACED_BY_NEWER_AUTHORITATIVE_TABLE | a newer table holds these facts authoritatively (OD-025) | 196 |
| `second_brain_agent_performance_feedback_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_mcp_denial_receipts` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_mcp_policy_gate_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_memory_consolidation_candidates` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_memory_consolidation_review_items` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_memory_quality_review_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_operator_feedback` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_operator_preference_profiles` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_phase_08c_validation_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_phase_08d_validation_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_phase_09_validation_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_benchmark_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_context_budget_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_embedding_model_evals` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_eval_cases` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_eval_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_eval_sets` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_hybrid_query_results` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_hybrid_query_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_llamaindex_config_snapshots` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_source_linked_proof_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retrieval_unsupported_claim_checks` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_retry_receipts` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_review_burden_clusters` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_review_burden_policy_evals` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_review_burden_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_run_registry` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `second_brain_run_steps` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `source_intelligence_fts` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 4,126 |
| `source_intelligence_fts_config` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 1 |
| `source_intelligence_fts_content` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 4,126 |
| `source_intelligence_fts_data` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 471 |
| `source_intelligence_fts_docsize` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 4,126 |
| `source_intelligence_fts_idx` | table | REBUILD_AND_VALIDATE | SQLite full-text index internals, rebuilt as PostgreSQL indexes (OD-010) | 404 |
| `source_structure_findings` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `source_structure_hints` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `source_structure_runs` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `source_structure_summaries` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 0 |
| `sqlite_sequence` | table | DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE | obsolete or empty in the source (OD-025) | 24 |

## 8. ABSENT_FROM_SOURCE_AT_SCHEMA_128

15 plan objects, all of them schema v129-v135 additions, do not
exist in the schema-128 source. They are an expected, named gap under OD-001, not a
shortfall, and no target table is created for any of them.

| legacy object | planning disposition |
|---|---|
| `apple_contact_raw_content` | MIGRATE_DATA |
| `apple_contact_structured` | REBUILD_AND_VALIDATE |
| `calendar_event_current_selection` | MIGRATE_DATA |
| `calendar_event_revisions` | MIGRATE_DATA |
| `calendar_event_source_observations` | MIGRATE_DATA |
| `contact_current_selection` | MIGRATE_DATA |
| `contact_email_hashes` | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION |
| `contact_entities` | MIGRATE_DATA |
| `contact_linkage_candidates` | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION |
| `contact_phone_hashes` | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION |
| `contact_revisions` | MIGRATE_DATA |
| `contact_source_observations` | MIGRATE_DATA |
| `email_message_current_selection` | MIGRATE_DATA |
| `email_message_revisions` | MIGRATE_DATA |
| `email_message_source_observations` | MIGRATE_DATA |

The list matches OD-001 exactly: the decision register's 15 names were compared
against the registry's, in both directions.

## 9. Identifier renames

764 identifiers were renamed and recorded in
`migration_control.identifier_map`. PostgreSQL's 63-byte budget is the only reason
a name was shortened; a shortened name keeps its first 55 bytes and gains 7 hex
characters of the SHA-256 of the full original, so two names that differ only after
byte 63 do not collide (OD-013).

| object kind | renames |
|---|---|
| check constraint | 656 |
| column | 17 |
| foreign key | 12 |
| index | 67 |
| primary key | 12 |

### The one rename that is a policy decision, not a length problem

`construction_project_identity.hb_project_number` -> `construction_project_identity.project_number`

This is OD-024. It is the single source identifier carrying former-employer
branding, and the repository's neutral-naming rule wins for a newly created
identifier. **The column was not lost.** A reader searching the legacy name
`hb_project_number` will find it here and in `identifier_map`, mapped to the target
column `project_number` on `construction_project_identity`. The scope of the rename is the column name
only: the column's values are data and were migrated unchanged.

### The longest originals

| object kind | owning table | original bytes | target |
|---|---|---|---|
| check constraint | `second_brain_financial_currency_completeness_snapshots` | 99 | `second_brain_financial_currency_completeness_snapshots__b87c07b` |
| check constraint | `procore_ep_change_events_change_items_budget_code_seg_2dff22` | 98 | `procore_ep_change_events_change_items_budget_code_seg_2_8873091` |
| check constraint | `procore_ep_change_events_markup_items_wbs_code_segment_items` | 98 | `procore_ep_change_events_markup_items_wbs_code_segment__a34a1ae` |
| check constraint | `procore_ep_commitment_compliance_insurance_documents__52b7bf` | 98 | `procore_ep_commitment_compliance_insurance_documents__5_2f83d30` |
| check constraint | `procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65` | 98 | `procore_ep_purchase_order_contracts_custom_fields_cus_a_aeb10e6` |

The full mapping is in `reconciliation.json` and queryable from
`migration_control.identifier_map`.

## 10. Provenance completeness

OD-011 requires every migrated row to carry `migration_run_id`, `migration_source_table`, `migration_source_schema_version`, `migration_natural_key_hash`. Every non-empty loaded table
was queried for a NULL in any of the four.

Tables checked: 286. Rows covered: 3,263,870.

No loaded row has a NULL in any provenance column.

## 11. Identity sequences

The load inserts the source's own keys into `GENERATED BY DEFAULT AS IDENTITY`
columns, which leaves each sequence behind its data until it is reset (OD-016,
OD-022). Without the reset, the first ordinary application insert would collide.

49 identity sequences were checked. 22 belong to an
empty table and are legitimately at 1. 27 are at
`max(key) + 1`.

Every sequence is at its expected next value.

## 12. Redaction scan (OD-004)

The scan covers `evidence`, `docs/migration`, `migrations/data`, `migrations/sql`, `migrations/versions`, `apps`, `scripts`, including this
report itself. A finding names a file, a line, and a pattern, and never quotes what
it matched -- printing the match would put the disclosure in the artefact that is
supposed to be clean.

`src` and `tests` are deliberately outside that scope -- they are ordinary source
code, covered by review and the repository's own checks -- so this scan does not
claim coverage of them.

Files scanned: 94. Non-text files skipped: 0.
Patterns: EMAIL_ADDRESS, PHONE_NUMBER, HOME_DIRECTORY_PATH, LOCAL_ACCOUNT_NAME.

No finding.

The patterns are mechanical: mail addresses, telephone numbers, absolute
home-directory paths, and the local account name discovered at runtime. Free-text
personal names are **not** detected by pattern, because a regular expression
cannot make that judgement and claiming otherwise would report a clean scan that
means less than it appears to. What supports the personal-name claim instead is
construction: every artefact this phase writes is built from table names, column
names, type names, error codes, counts, and digests, and no query in the harness
reads a row value into its output.

## 13. The two SQLite read models (OD-018)

`v_procore_inspection_unanswered_items` and `v_procore_open_action_signals` are
SQLite-dialect views over base tables that are now loaded. OD-018 requires them
hand-ported to PostgreSQL and each verified by comparing its row count against the
source view's.

| legacy view | target | source rows | present | target rows |
|---|---|---|---|---|
| `v_procore_inspection_unanswered_items` | `procore.v_procore_inspection_unanswered_items` | 1,774 | yes | 1,774 |
| `v_procore_open_action_signals` | `procore.v_procore_open_action_signals` | 20,788 | yes | 20,788 |

## 14. Single-copy retention risk (OD-030)

**This is a recorded risk, not an acceptance criterion.** It does not gate the
verdict above, and it is not mitigated.

59,580 source rows exist nowhere but inside the one
4,368,125,952-byte legacy file: the 59,572 rows withheld from the target by decision, plus
the 8 rows PostgreSQL could not represent. For those rows the
source file is the sole custodian, and OD-003 keeps it retained indefinitely --
retention is not redundancy.

Files beside it, by size. A byte-identical copy would have to match the
source's size, so only a same-sized file was digested. Any `-wal` or `-shm`
name in this list belongs to one of those earlier snapshots, not to the live
source: the live file's own journal siblings are checked by exact name under
*Bound identity* above.

| file | bytes | byte-identical copy of the source |
|---|---|---|
| `hb-personal-assistant.sqlite.bak-20260625T143637Z` | 3,640,639,488 | no |
| `hb-personal-assistant.sqlite.bak-20260625T205219Z` | 3,640,639,488 | no |
| `hb-personal-assistant.sqlite.bak-20260625T205219Z-shm` | 32,768 | no |
| `hb-personal-assistant.sqlite.bak-20260625T205219Z-wal` | 0 | no |
| `hb-personal-assistant.sqlite.before-gma-hard-purge-20260628T163432.bak` | 4,025,368,576 | no |
| `hb-personal-assistant.sqlite.pre-v122-20260711T113404Z.bak` | 4,212,047,872 | no |
| `hb-personal-assistant.sqlite.pre-v79-20260627T065543.bak` | 3,758,014,464 | no |
| `hb-personal-assistant.sqlite.zip` | 71,393,219 | no |

Verified copies of the source: **0**. The siblings are
earlier snapshots taken at earlier schema versions, not backups of this file.

Nothing was copied anywhere to close this. Moving personal data off this machine
is the owner's disclosure decision under `AGENTS.md` section 5 and OD-004, and a
reconciliation harness may not take it unilaterally. The risk is stated so the
owner can decide, which is the only correct action available here.

## Appendix — per-table row-count parity

Every loaded table, both counts, in name order. `planning class` is what OD-008
assigned and `treatment` is what the table actually got; where they disagree, the
governing decision is in section 0a.

| legacy table | schema | planning class | treatment | source | target | quarantined |
|---|---|---|---|---|---|---|
| `accepted_commitments` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `accepted_tasks` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `action_items` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `aging_exposure_report_items` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 1,780 | 1,780 | 0 |
| `assistant_answer_draft_citations` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_answer_draft_events` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_answer_draft_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_answer_draft_sections` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_answer_drafts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_context_pack_events` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_context_pack_items` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_context_pack_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_context_packs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_intelligence_projection_events` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_intelligence_projection_items` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_intelligence_projection_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_intelligence_projections` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_memory_compilations` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_research_packet_citations` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_research_packet_events` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_research_packet_items` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_research_packet_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_research_packets` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `assistant_runs` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 106 | 106 | 0 |
| `attachments` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `brief_effectiveness_rollups` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `calendar_event_attendees` | calendar | MIGRATE_DATA | SCHEMA_AND_DATA | 22,170 | 22,170 | 0 |
| `calendar_event_index` | calendar | MIGRATE_DATA | SCHEMA_AND_DATA | 1,711 | 1,711 | 0 |
| `calendar_event_raw_content` | calendar | MIGRATE_DATA | SCHEMA_AND_DATA | 1,709 | 1,709 | 0 |
| `calendar_project_match_candidates` | calendar | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 21 | 21 | 0 |
| `calendar_raw_event_attendees_structured` | calendar | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 22,137 | 22,137 | 0 |
| `calendar_raw_event_locations_structured` | calendar | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1,416 | 1,416 | 0 |
| `calendar_raw_event_structured` | calendar | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1,709 | 1,709 | 0 |
| `calendar_source_locations` | calendar | MIGRATE_DATA | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `candidate_merge_links` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `candidate_source_refs` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `claude_context_packet_items` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `claude_context_packets` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `commitment_candidates` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `construction_document_cards` | construction | MIGRATE_DATA | SCHEMA_AND_DATA | 283 | 283 | 0 |
| `construction_document_classification_candidates` | construction | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 283 | 283 | 0 |
| `construction_document_intelligence_previews` | construction | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1 | 1 | 0 |
| `construction_document_project_match_candidates` | construction | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 283 | 283 | 0 |
| `construction_document_relationship_candidates` | construction | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 23 | 23 | 0 |
| `construction_drive_item_inventory` | construction | MIGRATE_DATA | SCHEMA_AND_DATA | 401 | 401 | 0 |
| `construction_drive_items` | construction | MIGRATE_DATA | SCHEMA_AND_DATA | 1,000 | 1,000 | 0 |
| `construction_file_extraction_runs` | construction | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `construction_project_identity` | construction | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `construction_project_keyword_registry` | construction | MIGRATE_PROVENANCE_ONLY | PROVENANCE_ONLY | 0 | 0 | 0 |
| `construction_project_source_matches` | construction | MIGRATE_PROVENANCE_ONLY | PROVENANCE_ONLY | 0 | 0 | 0 |
| `construction_source_locations` | construction | MIGRATE_DATA | SCHEMA_AND_DATA | 15 | 15 | 0 |
| `construction_source_resolutions` | construction | MIGRATE_PROVENANCE_ONLY | PROVENANCE_ONLY | 0 | 0 | 0 |
| `content_embeddings` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `cross_domain_context_readiness_mart` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `cross_source_intelligence_obsidian_runs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1 | 1 | 0 |
| `cross_source_relationship_candidates` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 1,880 | 1,880 | 0 |
| `cross_source_relationships` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 1,671 | 1,671 | 0 |
| `daily_brief_action_candidates` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_assembly_runs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_assembly_sections` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_change_event_refs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_change_events` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_delivery_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_exposure_events` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_handoff_lines` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 6,107 | 6,107 | 0 |
| `daily_brief_html_render_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_item_outcome_events` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_notification_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_open_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_ranked_candidates` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_ranking_runs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `daily_brief_runs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 15 | 15 | 0 |
| `daily_brief_source_refs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 6,120 | 6,120 | 0 |
| `data_quality_gate_results` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 1,320 | 1,320 | 0 |
| `email_calendar_projection_coverage` | email | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 120 | 120 | 0 |
| `email_followup_enrichments` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `email_intelligence_active_policy` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `email_message_attachments` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 16,352 | 16,352 | 0 |
| `email_message_body_vault_refs` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 5 | 5 | 0 |
| `email_message_raw_content` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 23,729 | 23,729 | 0 |
| `email_message_recipients` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 129,616 | 129,616 | 0 |
| `email_messages` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 23,733 | 23,733 | 0 |
| `email_model_classifications` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 40 | 40 | 0 |
| `email_project_matches` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 453 | 453 | 0 |
| `email_raw_message_attachments_structured` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 4,676 | 4,676 | 0 |
| `email_raw_message_recipients_structured` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 129,625 | 129,625 | 0 |
| `email_raw_message_structured` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 23,729 | 23,729 | 0 |
| `email_raw_thread_messages_structured` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 14,640 | 14,640 | 0 |
| `email_raw_thread_structured` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 8,929 | 8,929 | 0 |
| `email_relationship_candidates` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 6,569 | 6,569 | 0 |
| `email_source_locations` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 6 | 6 | 0 |
| `email_thread_raw_context` | email | MIGRATE_DATA | SCHEMA_AND_DATA | 8,929 | 8,929 | 0 |
| `email_thread_summaries` | email | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 281 | 281 | 0 |
| `files` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `follow_up_status_events` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `follow_up_watch_items` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_accuracy_results` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `forecast_anomaly_findings` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `forecast_budget_details` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 127 | 127 | 0 |
| `forecast_calibration_weights` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_comparison_results` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `forecast_confidence_factors` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 131 | 131 | 0 |
| `forecast_confidence_scorecards` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 128 | 128 | 0 |
| `forecast_config_items` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 195 | 195 | 0 |
| `forecast_config_snapshot_items` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 388 | 388 | 0 |
| `forecast_config_snapshots` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 2 | 2 | 0 |
| `forecast_config_sources` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 7 | 7 | 0 |
| `forecast_cost_entries` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 6,324 | 6,324 | 0 |
| `forecast_cost_entry_staffing_actuals` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_data_availability_profiles` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 7 | 7 | 0 |
| `forecast_evidence_packages` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_external_forecast_mappings` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_external_forecast_rows` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_external_forecasts` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_method_eligibility` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_model_selection_decisions` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `forecast_model_versions` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_monthly_actuals_by_budget_code` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 1,081 | 1,081 | 0 |
| `forecast_operator_assumptions` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `forecast_output_budget_codes` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 254 | 254 | 0 |
| `forecast_output_changes` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 49 | 49 | 0 |
| `forecast_output_commitment_exposure` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 127 | 127 | 0 |
| `forecast_output_monthly` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 2,932 | 2,932 | 0 |
| `forecast_output_monthly_table_rows` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 127 | 127 | 0 |
| `forecast_output_monthly_table_totals` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1 | 1 | 0 |
| `forecast_output_narratives` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 127 | 127 | 0 |
| `forecast_output_probability` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 127 | 127 | 0 |
| `forecast_output_risks` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 155 | 155 | 0 |
| `forecast_output_schedule_phasing` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 58 | 58 | 0 |
| `forecast_output_staffing` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `forecast_outputs` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 2 | 2 | 0 |
| `forecast_package_manifests` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_project_maturity_snapshots` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `forecast_project_staffing_absence_overrides` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_project_staffing_assumptions` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_project_staffing_attribution_review_items` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_project_staffing_attribution_rules` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_project_staffing_config` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_project_staffing_snapshot_rows` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_project_staffing_snapshots` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_projects` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_required_assumptions` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_review_items` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `forecast_runs` | financial | REINITIALIZE_OPERATIONAL_STATE | SCHEMA_AND_DATA | 10 | 10 | 0 |
| `forecast_staffing_cost_codes` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_staffing_template_versions` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `forecast_staffing_templates` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `long_term_memory_items` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `long_term_memory_quality_signals` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 2 | 2 | 0 |
| `long_term_memory_source_refs` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `meeting_email_relationship_candidates` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1,059 | 1,059 | 0 |
| `meeting_prep_brief_runs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1 | 1 | 0 |
| `meeting_prep_brief_sections` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 8 | 8 | 0 |
| `memory_update_candidates` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 2 | 2 | 0 |
| `memory_update_reviews` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `obsidian_index_entries` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 5 | 5 | 0 |
| `obsidian_index_manifests` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 7 | 7 | 0 |
| `obsidian_managed_section_registry` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `obsidian_note_index` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `obsidian_note_tag_index` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `obsidian_note_update_receipts` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `parser_outputs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `phase10_relationship_candidates` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `procore_action_signals` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 20,788 | 20,788 | 0 |
| `procore_attachment_refs` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 9,329 | 9,329 | 0 |
| `procore_company_entities` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 241 | 241 | 0 |
| `procore_custom_field_values` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 9,320 | 9,320 | 0 |
| `procore_endpoint_raw_payloads` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 145,193 | 145,193 | 0 |
| `procore_ep_billing_periods` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 66 | 66 | 0 |
| `procore_ep_budget_change_history` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 420 | 420 | 0 |
| `procore_ep_budget_detail_columns` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 399 | 399 | 0 |
| `procore_ep_budget_detail_row_cells` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 273,951 | 273,951 | 0 |
| `procore_ep_budget_detail_rows` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 3,044 | 3,044 | 0 |
| `procore_ep_budget_modifications` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 805 | 805 | 0 |
| `procore_ep_budget_views` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 35 | 35 | 0 |
| `procore_ep_change_events` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,104 | 1,104 | 0 |
| `procore_ep_change_events_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,453 | 2,453 | 0 |
| `procore_ep_change_events_change_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,966 | 2,966 | 0 |
| `procore_ep_change_events_change_items_budget_code_seg_2dff22` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 8,898 | 8,898 | 0 |
| `procore_ep_change_events_markup_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,232 | 2,232 | 0 |
| `procore_ep_change_events_markup_items_wbs_code_segment_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 6,696 | 6,696 | 0 |
| `procore_ep_commitment_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 153 | 153 | 0 |
| `procore_ep_commitment_change_orders` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 288 | 288 | 0 |
| `procore_ep_commitment_compliance` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 118 | 118 | 0 |
| `procore_ep_commitment_compliance_insurance_documents` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,085 | 1,085 | 0 |
| `procore_ep_commitment_compliance_insurance_documents__52b7bf` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,844 | 2,844 | 0 |
| `procore_ep_commitment_contracts` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 248 | 248 | 0 |
| `procore_ep_commitment_line_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,308 | 1,308 | 0 |
| `procore_ep_daily_log_dcrs` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,976 | 2,976 | 0 |
| `procore_ep_daily_log_dcrs_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,456 | 1,456 | 0 |
| `procore_ep_daily_log_deliveries` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 60 | 60 | 0 |
| `procore_ep_daily_log_deliveries_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 18 | 18 | 0 |
| `procore_ep_daily_log_inspections` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 116 | 116 | 0 |
| `procore_ep_daily_log_inspections_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 14 | 14 | 0 |
| `procore_ep_daily_log_manpower` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 980 | 980 | 0 |
| `procore_ep_daily_log_manpower_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 841 | 841 | 0 |
| `procore_ep_daily_log_notes` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 93 | 93 | 0 |
| `procore_ep_daily_log_notes_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,188 | 1,188 | 0 |
| `procore_ep_daily_log_visitor` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 3 | 3 | 0 |
| `procore_ep_daily_log_weather` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 208 | 208 | 0 |
| `procore_ep_inspection_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 5,139 | 5,139 | 0 |
| `procore_ep_inspection_items_response_set_responses` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 15,378 | 15,378 | 0 |
| `procore_ep_inspection_sections` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 288 | 288 | 0 |
| `procore_ep_inspections` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 208 | 208 | 0 |
| `procore_ep_inspections_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,184 | 1,184 | 0 |
| `procore_ep_inspections_distribution_members` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 827 | 827 | 0 |
| `procore_ep_inspections_inspectors` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 237 | 237 | 0 |
| `procore_ep_inspections_signature_requests` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 9 | 9 | 0 |
| `procore_ep_meetings` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 576 | 576 | 0 |
| `procore_ep_observations` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,491 | 1,491 | 0 |
| `procore_ep_observations_assignees` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 368 | 368 | 0 |
| `procore_ep_prime_change_order_line_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 249 | 249 | 0 |
| `procore_ep_prime_change_orders` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 219 | 219 | 0 |
| `procore_ep_prime_contract_line_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 499 | 499 | 0 |
| `procore_ep_prime_contracts` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 7 | 7 | 0 |
| `procore_ep_projects` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 6 | 6 | 0 |
| `procore_ep_projects_custom_fields_custom_field_163287_value` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `procore_ep_projects_custom_fields_custom_field_163290_value` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `procore_ep_projects_custom_fields_custom_field_163293_value` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `procore_ep_projects_custom_fields_custom_field_163296_value` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `procore_ep_projects_custom_fields_custom_field_163299_value` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `procore_ep_projects_custom_fields_custom_field_163302_value` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `procore_ep_punch_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 36 | 36 | 0 |
| `procore_ep_punch_items_assignees` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 48 | 48 | 0 |
| `procore_ep_punch_items_assignments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 48 | 48 | 0 |
| `procore_ep_punch_items_ball_in_court` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 23 | 23 | 0 |
| `procore_ep_purchase_order_contracts` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 11 | 11 | 0 |
| `procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `procore_ep_purchase_order_line_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 28 | 28 | 0 |
| `procore_ep_purchase_order_line_items_cost_code_line_i_779dbd` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 49 | 49 | 0 |
| `procore_ep_rfis` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,027 | 2,027 | 0 |
| `procore_ep_rfis_assignees` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 3,500 | 3,500 | 0 |
| `procore_ep_rfis_ball_in_courts` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 132 | 132 | 0 |
| `procore_ep_rfis_questions` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,027 | 2,027 | 0 |
| `procore_ep_rfqs` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 12 | 12 | 0 |
| `procore_ep_rfqs_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 72 | 72 | 0 |
| `procore_ep_rfqs_change_event_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 94 | 94 | 0 |
| `procore_ep_rfqs_change_event_change_event_line_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 63 | 63 | 0 |
| `procore_ep_rfqs_change_event_change_event_line_items__0a3e8d` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 69 | 69 | 0 |
| `procore_ep_schedule_activities` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 18,909 | 18,909 | 0 |
| `procore_ep_schedule_activity_code_assignments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 63,970 | 63,970 | 0 |
| `procore_ep_schedule_calendars` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 35 | 35 | 0 |
| `procore_ep_schedule_relationships` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 44,570 | 44,570 | 0 |
| `procore_ep_schedule_udf_values` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 39,407 | 39,407 | 0 |
| `procore_ep_schedule_wbs_nodes` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,513 | 2,513 | 0 |
| `procore_ep_schedules` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 30 | 30 | 0 |
| `procore_ep_subcontractor_invoice_change_order_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,403 | 2,403 | 0 |
| `procore_ep_subcontractor_invoice_contract_detail_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 51,428 | 51,428 | 0 |
| `procore_ep_subcontractor_invoices` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,002 | 1,002 | 0 |
| `procore_ep_subcontractor_invoices_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,000 | 1,000 | 0 |
| `procore_ep_submittals` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,852 | 1,852 | 0 |
| `procore_ep_submittals_approvers` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 7,601 | 7,601 | 0 |
| `procore_ep_submittals_approvers_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 6,848 | 6,848 | 0 |
| `procore_ep_submittals_ball_in_court` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 196 | 196 | 0 |
| `procore_financial_amount_facts` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 447,398 | 447,398 | 0 |
| `procore_financial_billing_periods` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 67 | 67 | 0 |
| `procore_financial_budget_changes` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1,225 | 1,225 | 0 |
| `procore_financial_budget_rows` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 3,044 | 3,044 | 0 |
| `procore_financial_budget_views` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 35 | 35 | 0 |
| `procore_financial_change_events` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1,106 | 1,106 | 0 |
| `procore_financial_change_order_line_items` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 944 | 944 | 0 |
| `procore_financial_change_orders` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 507 | 507 | 0 |
| `procore_financial_compliance_documents` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1,588 | 1,588 | 0 |
| `procore_financial_contracts` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 271 | 271 | 0 |
| `procore_financial_invoice_items` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 71,113 | 71,113 | 0 |
| `procore_financial_line_items` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 2,110 | 2,110 | 0 |
| `procore_financial_rfqs` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 291 | 291 | 0 |
| `procore_financial_subcontractor_invoices` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 1,085 | 1,085 | 0 |
| `procore_inspection_evidence_rules` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 8,856 | 8,856 | 0 |
| `procore_inspection_items` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 8,856 | 8,856 | 0 |
| `procore_inspection_records` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 208 | 208 | 0 |
| `procore_inspection_response_options` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 33 | 33 | 0 |
| `procore_inspection_response_sets` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 11 | 11 | 0 |
| `procore_inspection_sections` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 288 | 288 | 0 |
| `procore_live_record_change_events` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 111,663 | 111,663 | 0 |
| `procore_live_record_snapshots` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 107,905 | 107,905 | 0 |
| `procore_live_record_state_index` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 105,264 | 105,264 | 0 |
| `procore_live_records` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 113,557 | 113,557 | 0 |
| `procore_live_sync_runs` | procore | REINITIALIZE_OPERATIONAL_STATE | SCHEMA_AND_DATA | 5,315 | 5,315 | 0 |
| `procore_location_entities` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 165 | 165 | 0 |
| `procore_people_entities` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 626 | 626 | 0 |
| `procore_raw_attachments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 240 | 240 | 0 |
| `procore_raw_budget_changes` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 420 | 420 | 0 |
| `procore_raw_budget_columns` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 399 | 399 | 0 |
| `procore_raw_budget_rows` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 3,044 | 3,044 | 0 |
| `procore_raw_change_event_comments` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 4 | 4 | 0 |
| `procore_raw_change_order_line_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 944 | 944 | 0 |
| `procore_raw_change_orders` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 507 | 507 | 0 |
| `procore_raw_contract_line_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 2,110 | 2,110 | 0 |
| `procore_raw_contracts` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 271 | 271 | 0 |
| `procore_raw_cost_code_dimensions` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 679 | 679 | 0 |
| `procore_raw_daily_logs` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 4,639 | 4,639 | 0 |
| `procore_raw_date_dimensions` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 13,733 | 13,733 | 0 |
| `procore_raw_invoice_items` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 71,113 | 71,113 | 0 |
| `procore_raw_invoices` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,085 | 1,085 | 0 |
| `procore_raw_meeting_details` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 576 | 576 | 0 |
| `procore_raw_meeting_topics` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 8,169 | 8,169 | 0 |
| `procore_raw_project_dimensions` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 48 | 48 | 0 |
| `procore_raw_rfi_responses` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 123 | 123 | 0 |
| `procore_raw_rfq_responses` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 315 | 315 | 0 |
| `procore_raw_status_dimensions` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 227 | 227 | 0 |
| `procore_raw_submittal_packages` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 11 | 11 | 0 |
| `procore_record_edges` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 101,479 | 101,479 | 0 |
| `procore_record_timeline_events` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 105,952 | 105,952 | 0 |
| `procore_synced_entities` | procore | MIGRATE_DATA | SCHEMA_AND_DATA | 1,185 | 1,185 | 0 |
| `procore_text_intelligence` | procore | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 12,895 | 12,895 | 0 |
| `project_issue_history_items` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 598 | 598 | 0 |
| `project_risk_digest_items` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 44 | 44 | 0 |
| `project_schedule_baseline_selections` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `project_schedule_named_baseline_slots` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 3 | 3 | 0 |
| `project_schedule_series_membership` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `project_source_coverage_mart` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `ranking_policy_eval_items` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `ranking_policy_eval_runs` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `raw_content_access_events` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 39,839 | 39,839 | 0 |
| `relationship_quality_mart` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `retrieval_context_refs` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 6,528 | 6,528 | 0 |
| `retrieval_query_receipts` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 16 | 16 | 0 |
| `schedule_baseline_activities` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 15,818 | 15,818 | 0 |
| `schedule_baseline_activity_codes` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 31,250 | 31,250 | 0 |
| `schedule_baseline_activity_crosswalk` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 15,486 | 15,486 | 0 |
| `schedule_baseline_health_facts` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 99 | 99 | 0 |
| `schedule_baseline_projects` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 11 | 11 | 0 |
| `schedule_baseline_relationships` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 37,044 | 37,044 | 0 |
| `schedule_baseline_udfs` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 17,693 | 17,693 | 0 |
| `schedule_baseline_wbs` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 1,862 | 1,862 | 0 |
| `schedule_cost_distributions` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `schedule_cost_mapping_candidates` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 2,607 | 2,607 | 0 |
| `schedule_cost_mapping_runs` | schedule | REINITIALIZE_OPERATIONAL_STATE | SCHEMA_AND_DATA | 3 | 3 | 0 |
| `schedule_cost_weighting_results` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 37 | 37 | 0 |
| `schedule_cpm_activity_results` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 18,084 | 18,084 | 0 |
| `schedule_cpm_diagnostics` | schedule | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 24,462 | 24,462 | 0 |
| `schedule_cpm_path_activities` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 91 | 91 | 0 |
| `schedule_cpm_paths` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 3 | 3 | 0 |
| `schedule_cpm_relationship_results` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 35,289 | 35,289 | 0 |
| `schedule_cpm_runs` | schedule | REINITIALIZE_OPERATIONAL_STATE | SCHEMA_AND_DATA | 18 | 18 | 0 |
| `schedule_file_imports` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 25 | 25 | 0 |
| `schedule_identities` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 4 | 4 | 0 |
| `schedule_identity_manual_actions` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `schedule_import_package_files` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 21 | 21 | 0 |
| `schedule_import_packages` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 12 | 12 | 0 |
| `schedule_package_equivalence_facts` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 8 | 8 | 0 |
| `schedule_package_field_lineage` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 144 | 144 | 0 |
| `schedule_quality_evaluation_runs` | schedule | REINITIALIZE_OPERATIONAL_STATE | SCHEMA_AND_DATA | 42 | 42 | 0 |
| `schedule_quality_findings` | schedule | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 9,502 | 9,502 | 0 |
| `schedule_quality_metric_results` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 450 | 450 | 0 |
| `schedule_quality_scorecards` | schedule | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 42 | 42 | 0 |
| `schedule_source_capabilities` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 163 | 163 | 0 |
| `schedule_version_diff_detail_facts` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 209,437 | 209,437 | 0 |
| `schedule_version_diff_facts` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 160 | 160 | 0 |
| `schedule_version_diff_impact_rollups` | schedule | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 32,728 | 32,728 | 0 |
| `schedule_version_identity_matches` | schedule | MIGRATE_DATA | SCHEMA_AND_DATA | 10 | 10 | 0 |
| `schema_migrations` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 128 | 128 | 0 |
| `second_brain_agent_model_receipts` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 15 | 15 | 0 |
| `second_brain_agent_run_receipts` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 15 | 15 | 0 |
| `second_brain_evaluation_runs` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 15 | 15 | 0 |
| `second_brain_financial_amount_facts_normalized` | financial | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `second_brain_financial_currency_completeness_snapshots` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 291 | 291 | 0 |
| `second_brain_financial_exposure_summary_items` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `second_brain_financial_review_required_items` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 128,769 | 128,769 | 0 |
| `second_brain_financial_source_coverage_snapshots` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 980 | 980 | 0 |
| `second_brain_financial_wbs_cost_code_snapshots` | financial | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 97 | 97 | 0 |
| `second_brain_mcp_claude_desktop_config_previews` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 2 | 2 | 0 |
| `second_brain_mcp_permission_audit_runs` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 3 | 3 | 0 |
| `second_brain_mcp_prompt_registry_snapshots` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 3 | 3 | 0 |
| `second_brain_mcp_resource_registry_snapshots` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 3 | 3 | 0 |
| `second_brain_mcp_server_config_snapshots` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 15 | 15 | 0 |
| `second_brain_mcp_tool_call_receipts` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 14 | 14 | 0 |
| `second_brain_mcp_tool_registry_snapshots` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 3 | 3 | 0 |
| `second_brain_research_packets` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 2 | 2 | 0 |
| `second_brain_retrieval_approved_source_manifests` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `second_brain_retrieval_vector_index_items` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 6,805 | 6,805 | 0 |
| `second_brain_retrieval_vector_index_runs` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 5 | 5 | 0 |
| `second_brain_runtime_config_receipts` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 14 | 14 | 0 |
| `source_evidence_trails` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 1,880 | 1,880 | 0 |
| `source_index_entities` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 9,128 | 9,128 | 0 |
| `source_index_locators` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 9,128 | 9,128 | 0 |
| `source_index_move_signals` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `source_intelligence_chunks` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 2,926 | 2,920 | 6 |
| `source_intelligence_generated_notes` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 195 | 195 | 0 |
| `source_intelligence_metadata` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 9,128 | 9,128 | 0 |
| `source_intelligence_relationships` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 285 | 285 | 0 |
| `source_intelligence_sources` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 9,128 | 9,128 | 0 |
| `source_intelligence_summaries` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 7 | 7 | 0 |
| `source_intelligence_text` | core | MIGRATE_DATA | SCHEMA_AND_DATA | 5,738 | 5,736 | 2 |
| `source_links` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `source_record_summary_mart` | core | REBUILD_AND_VALIDATE | SCHEMA_AND_DATA_REBUILDABLE | 0 | 0 | 0 |
| `source_records` | core | MIGRATE_PROVENANCE_ONLY | PROVENANCE_ONLY | 0 | 0 | 0 |
| `source_structure_entities` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `source_structure_entity_folders` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `source_structure_folders` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `source_structure_overrides` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `source_structure_roots` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `source_system_record_map` | core | DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `staffing_holiday_calendar_dates` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 150 | 150 | 0 |
| `staffing_holiday_calendars` | financial | MIGRATE_DATA | SCHEMA_AND_DATA | 1 | 1 | 0 |
| `sync_state` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
| `task_candidates` | core | ARCHIVE_LEGACY_SOURCE_ONLY | SCHEMA_AND_DATA | 0 | 0 | 0 |
