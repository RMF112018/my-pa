# Communications intelligence — implementation contract

**Status:** implementation contract under [ADR-022](../decisions/ADR-022-communications-intelligence.md) (Accepted under operator delegation 2026-11-22, Manager ruling R-OP-1; effective on merge of WP2). **WP1 is implemented** (the pure source contract, this spec, the ADR and the corpus evidence; merged to `main` in #371). **WP2 is implemented and merged** (#373): section 12 and the [`meeting_sync_v1` producer contract](meeting-sync-v1-contract.md). **WP3a is implemented and merged** (#376): the shared ingestion lifecycle, the communications tables, ingestion, backfill, coverage, the cycles-plane poll step, the operator command and the runbook (section 0.2); its migration `52a829ef718a` (on `6418b57081c3`). **WP3b is implemented and merged** (#382): `meeting_sync_v1` as a staging lifecycle consumer, the latch-gated applier, the reconciliation pass, the unbind tombstone, `not_seen` and the snapshot foreign keys (section 0.4); its migration `61fafdfd2986` (on `52a829ef718a`). **WP3P is implemented and merged** (#383): the project-report sources on the shared lifecycle (ADR-024); its migration `0d4e247d03cb`. **WP4 is implemented on branch `feat/comms-search` (not merged)**: search text v2, identifiers v2, the operator `rederive` and `measure-fts`, and the three reads `communications.search`, `communications.read` and `communications.coverage` behind `MY_PA_COMMUNICATIONS_ENABLED` (section 0.5); its migration `fa18ef3d9bc0` (on `0d4e247d03cb`) has been applied to disposable databases only. Every other section is design for WP4P–WP5, which each need their own PR, review and, where marked, operator decision. Nothing is granted, activated or deployed: migrations, grants, the ChatLLM profile and schedulers are applied in one consolidated activation at the end of the goal (section 20.6).

**Basis:** contract head measured: branch `feat/comms-intelligence` at `80208caabe92de03be676a93fae8984d31d2b8c1` (tree `057703650c1f7b8976a86ccebc3da0a62f70d1a6`), the WP1 head after fix F2, on `origin/main@092610d36b7d1493fc7fda6e352a4bd06e914f61`; Alembic single head `640aaacc78e8` (129 revision files); 298 `Capability` members and 70 `Purpose` members. PR #368 (ADR-020, meeting prep, migration on `640aaacc78e8`) is open and not on this branch: WP2's migration must chain after whichever head is current when it is written. WP3a basis: branch `feat/comms-ingestion` on `origin/main@354cdebae60723f2f315578b494d2d6f9f32214c` (the WP2 merge), Alembic single head `52a829ef718a`. All counts here are digits on purpose (spelled-count guard). Paths to files that do not exist yet are not written as links (CI relative-link check).

**Corpus evidence:** [`docs/evidence/communications-corpus/`](../evidence/communications-corpus/README.md) (aggregates only, from the sanitized v2 analysis, SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`). Section numbers below are what [`CORPUS-DESIGN-IMPLICATIONS.md`](../evidence/communications-corpus/CORPUS-DESIGN-IMPLICATIONS.md) cites.

## 0. Work packages and implementation state

| WP | Content | State |
| --- | --- | --- |
| WP1 | ADR-022, this spec, 6 corpus deliverables; pure `communications_evidence_v2` contract (parse/validate/normalize both dialects, classification, lane reconciliation, integrity, `comms_search_text_v1`, `comms_identifiers_v1`, corpus coverage summary), aggregate-only CLI, synthetic fixtures, FAST tests | **implemented**, merged to `main` (#371); no migration |
| WP2 | Meeting provider identity and recurrence resolution (section 12): migration `6418b57081c3`, persistence, the `meeting_sync_v1` contract and parser, the resolution service, `meetings.provider.bind`, ChatLLM profile `chatllm-data-v15` (activated at the consolidated goal activation, R-OP-4), the [meeting-sync producer contract](meeting-sync-v1-contract.md) | **implemented**, merged to `main` (#373); nothing granted, activated or deployed |
| WP3a | Shared ingestion lifecycle (section 1) + communications persistence (section 5), ingestion (sections 10–11), coverage (section 9), backfill, scheduled ingestion on the cycles plane, monitoring, operator command, runbook (section 0.2) | **implemented**, merged to `main` (#376): migration `52a829ef718a`; nothing granted, activated or deployed; the poll switch is off |
| WP3b | `meeting_sync_v1` as a lifecycle consumer (stage-then-apply); the batch Meeting review/reconcile pass that gates calendar sync (section 12.7, R-OP-6) and its one-way latch; the R1-1 unbind tombstone and `adopt_provider_series`; `not_seen` (C10) from the 1.1.0 `coverage`; the deterministic sync apply order and the binding-writer lock; audit routing; snapshot foreign keys on the binding (D8); the runbook. The `provider_id_only` / Message-ID join (section 3, check (e)) is **out of scope** (ruling D11, section 0.4) | **implemented**, merged to `main` (#382): migration `61fafdfd2986`; ChatLLM `chatllm-data-v16`; nothing admitted, granted, activated or deployed (section 0.4) |
| WP3P | Procore PULSE persistence and ingestion on the WP3 lifecycle ([ADR-024](../decisions/ADR-024-project-report-source-evidence.md); runbook [`ops/runbooks/project-reports-ingestion.md`](../../ops/runbooks/project-reports-ingestion.md)) | **implemented**, merged to `main` (#383): migration `0d4e247d03cb`; nothing admitted, granted, activated or deployed |
| WP4 | Search text v2 and identifiers v2 (sections 6, 7), the operator `rederive` and `measure-fts` (section 18), the communications search service and its 3 MCP reads (sections 13, 14, 16) | **implemented** on branch `feat/comms-search` (not merged): migration `fa18ef3d9bc0`; ChatLLM `chatllm-data-v17`; the read switch off; nothing granted, activated or deployed (section 0.5) |
| WP4P | PULSE retrieval MCP | planned |
| WP5 | Batch meeting-context retrieval with PULSE evidence (section 15) + MCP + performance measurements + ChatLLM collector directive + final report; communications-only must work when PULSE is absent | planned |

After each WP the Manager runs the aggregate validation against the real corpus in an isolated local database, then an independent exact-head review, then the merge decision.

### 0.1 What WP1 contains (repository truth)

| Module | Responsibility |
| --- | --- |
| `src/my_pa/domain/communications/model.py` | closed vocabularies and frozen records: `Dialect`, `RecordClassification`, `IdentityState`, `FolderRole`, `LaneVerification`, `BodyState`, `IntegrityOutcome`, `WindowRule`, `Window` (inclusive `contains`), `NormalizedMessage` (with `canonical_key`), `MailboxItem`, `Publication`; `SCHEMA_NAME`, `SUPPORTED_MAJOR = 2`, `WINDOW_RESOLUTION` = 1 s |
| `src/my_pa/domain/communications/diagnostics.py` | `PublicationRejection`, `ReasonCode`, `DiagnosticCode`; `DiagnosticCollector` keeps at most `MAX_DIAGNOSTICS` (200) entries per publication and counts the rest; no entry carries content |
| `src/my_pa/domain/communications/classification.py` | `classify_records`: one classification per record ordinal, with the identity rules of section 3 |
| `src/my_pa/domain/communications/reconciliation.py` | `build_items`, `reconcile_participants`: mailbox items, lane observations, participant union with provenance, canonical message time |
| `src/my_pa/domain/communications/integrity.py` | `check_content`, `check_text_digest`: SHA-256 and UTF-8 byte-count checks |
| `src/my_pa/domain/communications/search_text.py` | `derive_search_text` (`comms_search_text_v1`, cap `MAX_SEARCH_TEXT_CHARS` = 262,144) |
| `src/my_pa/domain/communications/identifiers.py` | `extract_identifiers` (`comms_identifiers_v1`) |
| `src/my_pa/domain/communications/corpus.py` | `merge_intervals`, `summarize_corpus`: merged coverage, gaps, identity counts across publications |
| `src/my_pa/infrastructure/communications/evidence_v2.py` | `parse_publication` (`communications_evidence_v2_parser_v1`, `MAX_PUBLICATION_BYTES` = 64 MiB): the only module naming producer fields and provider vocabulary |
| `src/my_pa/infrastructure/communications/aggregate_cli.py` | the aggregate-only validation CLI (section 20.1) |

`tests/architecture/test_communications_source_scope.py` pins the slice: the domain imports only the standard library and itself and does no IO; the infrastructure package imports only the standard library and the domain; nothing else in `src/` imports either package in WP1; the domain names no provider. Fixtures under `tests/fixtures/communications_evidence/` are synthetic.

### 0.2 What WP3a contains (merged in #376)

| Module or file | Responsibility |
| --- | --- |
| `migrations/versions/20261122_52a829ef718a_communications_ingestion.py` | revision `52a829ef718a` (down `6418b57081c3`): 12 Principal-partitioned tables in `knowledge` — `ingest_sources`, `ingest_snapshots`, `ingest_snapshot_paths`, `ingest_runs`, `ingest_run_snapshots`, `ingest_coverage_windows`, `communication_messages`, `communication_mailbox_items`, `communication_observations`, `communication_participants`, `communication_identifiers`, `communication_quarantine` — with composite `ON DELETE RESTRICT` foreign keys, named-mutable-column, append-only and `TRUNCATE` refusal triggers, the generated English `search_document` with its GIN index, no trigram index; the downgrade refuses while any row exists |
| `src/my_pa/domain/common/identifiers.py` | 8 new identifier kinds: `isrc`, `isnp`, `irun`, `icov` (lifecycle) and `cmsg`, `cmitm`, `cobs`, `cqrn` (communications) |
| `src/my_pa/contracts/ports.py` | the lifecycle and communications ports and closed vocabularies (`IngestConsumer`, `IngestSnapshotStatus`, `IngestRunTrigger`, `IngestRunOutcome`, `IngestRunSnapshotOutcome`, `IngestConsumerHandler`) |
| `src/my_pa/infrastructure/persistence/ingestion.py`, `communications.py` | `SqlIngestionRepository`, `SqlCommunicationsRepository`, the operator aggregate read |
| `src/my_pa/application/ingestion.py` | `IngestionLifecycle`: consumer-neutral admission, enable/disable, scheduled poll, operator run, backfill and dry run (sections 1, 10, 11); closed `IngestRefusalCode` |
| `src/my_pa/application/communications_ingest.py` | `CommunicationsEvidenceHandler` (the `communications_evidence_v2` consumer: identity, dedup, observations, participants, identifiers, quarantine, projection) and `CommunicationsCoverageReader` (range summary and rolling 30 days) |
| `src/my_pa/domain/communications/coverage.py` | pure coverage: merged intervals, gaps, per-lane states, freshness (section 9) |
| `src/my_pa/bootstrap/communications_ingest.py` | the one composition of the lifecycle, the read-only workspace stores and the coverage reader, shared by the operator command and the cycles plane; the injected parser; an audit sink that raises (the lifecycle writes no audit row) |
| `src/my_pa/infrastructure/jobs/cycle_scheduler.py`, `apps/worker.py` | the cycles plane as a tuple of steps, each with its own switch, lock and due rule; the ingestion poll step (section 19) |
| `apps/cli/communications_ingest.py` | the operator command (sections 10, 11): `admit`, `enable`, `disable`, `run-once`, `backfill`, `coverage`, `aggregate` |
| `ops/nas/remote/compose.comms-ingest.remote.example.yml` | the read-only workspace overlay for the cycles service (ruling M8); applying it is part of the consolidated activation (section 20.6) |
| `ops/runbooks/communications-ingestion.md` | admission, backfill, dry run, monitoring, failure recovery and disabling, written for the consolidated activation |

Guards added or amended: `tests/architecture/test_communications_source_scope.py` is an explicit importer allowlist (ruling M5); `tests/architecture/test_ingestion_lifecycle_is_consumer_neutral.py` (the lifecycle imports no consumer slice and calls only `list_directory`, `stat` and `open_download`); `tests/architecture/test_communications_tables_hold_no_content_columns.py` (no body, HTML or display-name column); the partition-guard and operator-command maps register the new tables and the command.

### 0.3 WP3a rulings and deviations from this spec as first designed

The Manager ruled on the WP3a investigation on 2026-11-22 (rulings M1–M8 and m1–m14). Each changes the design where noted; the sections below are amended in place.

| Ruling | Deviation or decision | Section |
| --- | --- | --- |
| M4 | The consumer closed set already admits `communications_evidence_v2`, `meeting_sync_v1` and `pulse_csv_export`, so WP3b and WP3P add no vocabulary migration; admission refuses a consumer with no registered handler (`consumer_not_registered`) | 1.2 |
| M3 | `superseded` is not a snapshot status: snapshots are `pending`, `ingested` or `rejected`; paths and aliases live in `ingest_snapshot_paths`, whose `superseded_by_snapshot_id` and `superseded_at` change once, together, from NULL | 1.2, 1.3 |
| M6 | A later observation of a known provider id is matched by provider id and never rekeys its item; it attaches only when sender and body digest agree, else it is quarantined `identity_conflict` and the message is flagged | 3 |
| M7 | `communication_participants` is append-only with `first_observation_id`; full provenance is derived at read time from `communication_observations.participants` | 5.2 |
| M1 | No trigram subject index in WP3a; it is deferred to WP4, which must amend `tests/architecture/test_no_vector_retrieval_exists.py` (it bans `gin_trgm_ops` today) when it adds one | 5.3 |
| FTS | `search_document` is built now with the `english` configuration (R3); `comms_search_text_v1` is frozen unchanged and is the stored `search_text_version`; identifiers are stored as `comms_identifiers_v1` | 5.1, 6, 7 |
| m6 | Stability exceptions: an operator run and a backfill read on first sight; an unchanged file (same size and version token as this process last finished with) is skipped without a read | 11 |
| — | Path revert: bytes reappearing at a path whose row for them is already superseded write nothing (supersession is one-way) | 1.3 |
| — | A failed snapshot (its transaction rolled back) has no run link; the run counts it | 1.2, 18 |
| — | Backfill is allowed on a disabled source | 10 |
| M2 | The poll is a step of the cycles plane with its own switch, lock and interval; `MY_PA_COMMUNICATIONS_ENABLED` is not added in WP3a (it gates reads, which are WP4) | 19 |
| M8 | The cycles service reads the `mcp` workspace through a read-only overlay | 1.1, 19 |
| m7 | The operator command takes the DSN only from `MY_PA_DATABASE_URL` and asserts `--expected-database` and `--expected-alembic-head` | 10, 19 |
| R1-F1 (a) | A record whose provider id names a stored item of the other identity kind (`provider_id_only` vs `provider_returned`) is quarantined `identity_kind_mismatch` (a new closed reason, admitted by the revision's quarantine `CHECK`) and counted `records_identity_kind_mismatch`; it creates no message or item and the stored item and message are not touched. The key spaces never merge (ADR-022 decision 4) | 3 |
| R1-F4 | `run-once` and `backfill` (not `--dry-run`) hold the poll's advisory lock `COMMS_INGEST_LOCK_KEY` for the run and refuse `lock_held` when another session holds it | 10, 19 |
| R1-F5 | The rolling 30-day read ends at the latest covered instant, `[latest_covered - 30 d, latest_covered]`, and reports holes only; staleness is `freshness_seconds` | 9 |

**Known residuals (WP3a).**

- The poll stops at the first enabled source whose workspace is unavailable; the run is logged failed and retried after the interval.
- Every run (scheduled poll, `run-once` and backfill alike) reads and prepares every fresh file before the first snapshot transaction, holding each file's bytes and its parsed publication together until the run applies them. The bound is the per-file cap (`MAX_PUBLICATION_BYTES`, 64 MiB) times the number of fresh files, plus their parsed form; the first poll (or backfill) over the canonical 29-file folder holds all 29 at once.
- A file whose `prepare` raises is counted `snapshots_failed`, writes nothing and is not remembered as finished, so every later poll reads and prepares it again until its bytes change.
- A rejected snapshot is placed at its path like an ingested one: it supersedes the path's current row. A later re-publication of the earlier good bytes at that path is a path revert (section 1.3) and writes nothing, so the path stays pointing at the rejected snapshot; only new bytes move it.
- A `provider_id_only` message and a Message-ID message of the same provider id stay two messages (section 3, check (e)): a later record of a provider id whose stored message is of the other identity kind is quarantined `identity_kind_mismatch`, in either arrival order, and writes no observation, message or item. **Closed as decided (WP3b ruling D11):** the join is out of scope and the separation stands; attaching such a record to the existing message in one direction (a later Message-ID record of a `provider_id_only` item, "direction A") is a candidate refinement for WP4 if the real counts of `records_identity_kind_mismatch` become non-zero. Each record is quarantined on its own (a provider id in two records of one publication is two quarantine rows).
- The `comms_identifiers_v1` recall gaps (change orders, `fpl`, submittals; section 7, R5) are unchanged and stay WP4's.
- Path revert cannot make an older snapshot current again for its path.

### 0.4 What WP3b contains (merged in #382)

The Manager ruled on the WP3b investigation on 2026-11-23 (rulings D1–D14); the sections below are amended in place. The producer-facing and tool contract is the [`meeting_sync_v1` contract](meeting-sync-v1-contract.md); the operator procedure is the meeting-sync part of [`ops/runbooks/communications-ingestion.md`](../../ops/runbooks/communications-ingestion.md).

| Module or file | Responsibility |
| --- | --- |
| `migrations/versions/20261123_61fafdfd2986_meeting_sync_staging.py` | revision `61fafdfd2986` (down `52a829ef718a`): `meeting_sync_publications`, `meeting_sync_events`, `meeting_provider_review_marks`, `meeting_provider_reconciliation_passes`, `meeting_provider_key_tombstones` (Principal-partitioned, composite `ON DELETE RESTRICT` foreign keys, append-only or change-once guards, `TRUNCATE` refused); `origin_snapshot_id` and `last_seen_snapshot_id` on `meeting_provider_bindings` with composite foreign keys onto `ingest_snapshots` (D10); the audit capability set restated for `meetings.provider.review` and `meetings.provider.reconcile`; the downgrade refuses while any new row exists |
| `src/my_pa/infrastructure/meeting_sync/parser.py` | parser v2 (`meeting_sync_v1_parser_v2`): the optional 1.1.0 `coverage` (D7); a 1.0.x publication has the outcome parser v1 gave it |
| `src/my_pa/application/meeting_sync_ingest.py` | `MeetingSyncHandler`, the `meeting_sync_v1` consumer: **stages only** (D1) |
| `src/my_pa/application/meeting_sync_apply.py` | `MeetingSyncApplier.apply_pending`: applies staged publications once the latch exists, in publication order behind a per-source high-water gate (D8), with `not_seen` (D7) |
| `src/my_pa/application/meeting_provider_reconcile.py`, `src/my_pa/domain/meeting_sync/reconcile.py` | `meetings.provider.review` and `meetings.provider.reconcile` (D2, D3, D4, D6, D12) |
| `src/my_pa/infrastructure/persistence/meeting_sync.py` | the staging and reconciliation repository |

| Ruling | Decision | Section |
| --- | --- | --- |
| D1 | **Stage-then-apply.** The consumer stages accepted events; the applier applies staged publications only once the reconciliation latch exists, from the cycles `comms_ingest` step after each poll and from the operator `run-once` and `backfill`, under `COMMS_INGEST_LOCK_KEY`. Placement: `My PA/Daily Intelligence/meetings/`, `YYYYMMDD-meetings.json` | 1.2, 11, 12.7 |
| D2 | The capabilities `meetings.provider.review` (read) and `meetings.provider.reconcile` (write, 0–50 independent items under SAVEPOINTs); no server-side pairing or similarity anywhere (guard) | 12.7 |
| D3 | The pass reviews the in-scope Meetings only: not cancelled and `start_at >= now − 30 days` (the collector lookback); each is bound or marked `no_provider_event`; no "mark all" | 12.7 |
| D4 | **The latch.** Recorded once, one-way, by the reconcile that leaves nothing in scope unreviewed; sync applies at the next applier run; the review stays usable after it; a Meeting made by hand after it can be duplicated by sync (runbook) | 12.7 |
| D5, D6 | R1-1 closed: an unbind writes a per-key tombstone that suppresses re-creation (`unbound_key_suppressed`), superseded by a later bind, with no release (deferral); `adopt_provider_series` on bind and reconcile items | 12.6, 12.7 |
| D7 | `not_seen` from the 1.1.0 `coverage` claim only; state only, never touches the Meeting; restored on the next sighting; suppressed by any quarantined record in the publication | 12.6 |
| D8 | Publications applied in `(generated_at_utc, file_sha256)` order per source (`skipped_stale`, `skipped_ordering_conflict`); events in key order; every binding writer takes the Principal's binding-writer advisory lock first | 12.6 |
| D9 | **Audit routing.** No `audit_events` row for system sync: the evidence is the Meeting history (actor `system`), the Record Events (`system.meeting_provider.sync`), the ingest run counts and the publication apply ledger; `meetings.provider.review` and `meetings.provider.reconcile` are audited by the ordinary invoke | 12.7, 19 |
| D10 | Binding snapshot foreign keys (`origin_snapshot_id` immutable, `last_seen_snapshot_id`) | 12.1 |
| D11 | The `provider_id_only` / Message-ID join (check (e)) is out of scope; the separation stands (section 0.3 residual) | 0.3, 3 |
| D12 | **Eligibility.** The staged `meeting_sync_v1` event fields answered by `meetings.provider.review` are eligible for the operator's own connected clients (Manager, under the operator's 2026-11-22 delegation; consistent with R-OP-3, section 17) | 12.7, 17 |
| D13 | ChatLLM `chatllm-data-v16` = v15 plus `meetings.provider.review` and `meetings.provider.reconcile` (`DATA_REQUIRED`), activated at the consolidated deploy instead of v15; the R-OP-2 grant list gains both | 20.6 |
| D14 | Counts-only quarantine for meeting sync (no quarantine rows); staged events are retained indefinitely (**deferral**: a retention rule is later work) | 12.3 |

**Known residuals (WP3b).** Post-latch hand-made duplicates (no delete or merge; cancel by hand); `not_seen` is only as good as the producer's completeness claim; no release of a tombstone; staging is never pruned; the `meetings.provider.review` event list is paged (200 per page, with a total, a truncated flag and an `events_after` cursor) and the review is a pass tool, not a calendar browser; a producer clock regression skips whole publications visibly (`publications_skipped_stale`).

### 0.5 What WP4 contains (branch `feat/comms-search`, not merged)

The Manager's pre-design rulings (D1–D11), the rulings on the design report (R1–R18) and on each slice are summarized in section 21; the operator procedure is section 12 of [`ops/runbooks/communications-ingestion.md`](../../ops/runbooks/communications-ingestion.md).

| Module or file | Responsibility |
| --- | --- |
| `migrations/versions/20261125_fa18ef3d9bc0_communications_search.py` | revision `fa18ef3d9bc0` (down `0d4e247d03cb`): `communication_messages.source_unavailable` and `.identifiers_version`, both admitted to the named-mutable trigger; the identifier kind CHECK widened with `pco` and `cor`; the audit capability set restated with the 3 `communications.*` names and the purpose set with `communications_read`; no trigram index; the downgrade refuses while a row holds what the previous revision cannot |
| `src/my_pa/domain/communications/search_text.py` | `comms_search_text_v2` (section 6), v1 kept callable |
| `src/my_pa/domain/communications/identifiers.py` | `comms_identifiers_v2` (section 7), v1 kept callable; `normalize_identifier_query` (one query item, exactly one identifier) |
| `src/my_pa/domain/communications/measurement.py`, `src/my_pa/infrastructure/communications/identifier_measure_cli.py` | the counts-only identifier measurement entry point the Manager runs on the private corpus |
| `src/my_pa/application/communications_rederive.py` | the bounded, resumable rederive to the current versions (section 18) |
| `src/my_pa/application/communications_search.py`, `src/my_pa/domain/communications/cursor.py`, `src/my_pa/domain/communications/search_query.py` | the search, read and coverage reads, the grant-bound cursor codec and the quoted-phrase parse (sections 13, 14, 16) |
| `src/my_pa/infrastructure/persistence/communications.py` | the search, read, thread, provenance, observation, version and rederive statements, every one under the partition guard |
| `apps/cli/communications_ingest.py` | `rederive` and `measure-fts` |
| `src/my_pa/application/service.py`, `commands.py`, the policy and ChatLLM tables | the 3 `communications.*` reads, the `communications_read` purpose, the read switch `MY_PA_COMMUNICATIONS_ENABLED` and `chatllm-data-v17` (section 16) |

## 1. Source acquisition and version control (shared ingestion lifecycle)

### 1.1 Where publications come from

The ChatLLM collector writes `communications_evidence_v2` publications into the `mcp` file workspace (ADR-019), canonical folder `My PA/Daily Intelligence/communications/`, one file per business date (`YYYYMMDD-comms.json`). Two rich-dialect publications sit elsewhere under `My PA/Daily Intelligence/`. my-pa **reads** them through the files workspace store's read path (list, stat with fingerprint version token, streamed read); it never writes, renames or trashes them. No new mount, source root or connector is introduced. Confirming that the worker can compose a read-only view of the `mcp` workspace (ADR-019 decision 7 keeps workspace and source roots disjoint; this is a workspace read, not a source root) is a WP3 preflight item. **Manager ruling 2026-11-21 (R1, section 21):** reading the `mcp` workspace through the files store as an ingestion source is ratified by the Manager, subject to that ADR-019 decision 7 preflight in WP3.

### 1.2 Shared lifecycle (WP3a, merged in #376; consumers: communications, meeting sync (WP3b), then PULSE)

One lifecycle, content-free, with domain-specific storage behind it:

- **Source registry** — `ingest_sources`: one row per admitted source: `source_id`, `principal_id`, `consumer` (closed set: `communications_evidence_v2`, `pulse_csv_export`), `workspace_id`, `path_prefix`, `file_pattern`, `enabled`, `admitted_at`, `admitted_by` (operator channel). Admission is an operator CLI action (ADR-022 decision 15: no client capability).
- **Snapshots** — `ingest_snapshots`: one row per distinct file content seen: `snapshot_id`, `principal_id`, `source_id`, `relative_path`, `file_sha256`, `byte_count`, `observed_version_token`, `first_seen_at`, `status` (`pending`, `ingested`, `rejected`, `superseded`), `rejection_code`, `parser_version`. `UNIQUE (principal_id, source_id, file_sha256)` is the idempotency key. A snapshot is immutable once `ingested` or `rejected`.
- **Runs** — `ingest_runs`: `run_id`, `principal_id`, `source_id`, `trigger` (`schedule`, `operator`, `backfill`), `started_at`, `finished_at`, `outcome` (`completed`, `partial`, `failed`), and code-count JSON (snapshots seen/new/ingested/rejected/skipped, records per classification). `ingest_run_snapshots` links a run to each snapshot it touched with that snapshot's outcome.
- **Quarantine** — the consumer stores quarantined *records* (section 4.3); the lifecycle stores rejected *snapshots*. Neither stores content.
- **Coverage** — `ingest_coverage_windows`: one row per ingested snapshot with declared `[start_utc, end_utc]` (inclusive end), coverage state and per-lane states; merged intervals are computed at read time (section 9).

**As built in WP3a (deviations from the list above).**

- The consumer closed set is `communications_evidence_v2`, `meeting_sync_v1` and `pulse_csv_export` (ruling M4): it already admits WP3b's and WP3P's consumers, so neither needs a vocabulary migration. Admitting a source whose consumer has no registered handler is refused `consumer_not_registered`; in WP3a only `communications_evidence_v2` has a handler. **WP3b registers the `meeting_sync_v1` handler** (`MeetingSyncHandler`, parser `meeting_sync_v1_parser_v2`, 16 MiB per file): it stages each accepted publication in the snapshot's transaction and applies nothing to Meetings (ruling D1); a declared 1.1.0 `coverage` becomes the snapshot's coverage window, state `complete`, with no lane objects. `pulse_csv_export` still has none.
- The source column is `ingest_source_id` everywhere (identifier kind `isrc`); `admitted_by` is always `operator_cli` and no audit row is written (ruling m8); only `enabled` is mutable; one source per `(principal_id, consumer, workspace_id, path_prefix, file_pattern)`.
- `ingest_snapshots.status` is `pending`, `ingested` or `rejected` only (ruling M3): a pending snapshot is finalized once and is then immutable. `superseded` is derived per path from `ingest_snapshot_paths` (section 1.3).
- `ingest_run_snapshots` carries `principal_id` and an outcome from `already_known`, `ingested`, `rejected`, `failed`. A snapshot whose transaction rolled back leaves no row at all, so it has no run link; the run counts it in `snapshots_failed` and its outcome is `partial` or `failed`. The `failed` link outcome is reserved and unused.
- The run `counts` object holds closed count keys only (snapshots seen, new, ingested, rejected, already known, failed, path-reverted, skipped by reason; records per classification).

**PULSE, the second file consumer (WP3P, branch `feat/pulse-reports`, not merged; [ADR-024](../decisions/ADR-024-project-report-source-evidence.md)).** PULSE is bound by the "as built" list above, not by the bullet list before it: the source column is `ingest_source_id`, `ingest_snapshots` has no `relative_path` (paths are `ingest_snapshot_paths` rows) and no `superseded` status, and the consumer set is the three members above. `pulse_csv_export` gets its handler in a **separate** `IngestionLifecycle` instance (`bootstrap/project_reports.py`), never in the communications one, so the communications `admit` keeps refusing it `consumer_not_registered` and a project-report source is admitted only by the operator's `bindings apply` (through `IngestionLifecycle.admit_within`, in the bindings transaction). The lifecycle gains no table, status or vocabulary; PULSE adds the repository read `list_paths_of_snapshot` and quarantines at consumer level (an `ingested` snapshot whose derivation is `quarantined`, every raw row kept). Its poll is its own cycles-plane step (section 19).

### 1.3 Version control

- A file is identified by its SHA-256, not its path or modification time. The same path with new bytes is a new snapshot; the earlier snapshot stays and is marked `superseded` for that path when the new one is ingested.
- The same bytes at another path (a copy) are the same snapshot: the second path is recorded as an alias on the snapshot and nothing is re-ingested.
- **As built (ruling M3).** Every path a snapshot was seen at is a row of `ingest_snapshot_paths` (`principal_id`, `snapshot_id`, `ingest_source_id`, `relative_path`, `first_seen_at`, `superseded_by_snapshot_id`, `superseded_at`); only the two superseded columns are mutable, together and only from NULL (trigger), and at most one row per `(source, relative_path)` is current. New bytes at a path, or known bytes recorded as an alias at a path, supersede that path's current row in the same transaction.
- **Path revert.** Bytes reappearing at a path whose row for them is already superseded write nothing: supersession is one-way, the newer snapshot stays current for that path, and the run counts `snapshots_path_reverted` with an `already_known` link.
- The workspace version token is recorded but never trusted as identity (ADR-019 decision 3: external writers exist).
- A source pointer is `(snapshot file_sha256, record ordinal)`. It is how stored text is rebuilt (section 18.4) and how a client can be told exactly which publication a fact came from.

## 2. Validation and compatibility (WP1, implemented)

`parse_publication(data: bytes)` returns `accepted` with a `Publication`, or `rejected` with one `PublicationRejection`. In order, the first failure decides:

1. size at most `MAX_PUBLICATION_BYTES`; strict UTF-8; JSON with no duplicate object key and no `NaN`/`Infinity` (`malformed_json` carries line, column and offset only);
2. an object whose `schema` is `communications_evidence_v2` (`unknown_schema`);
3. `schema_version` is `MAJOR.MINOR.PATCH` (`invalid_schema_version`); **major 2 only** (`unsupported_major_version`); a newer minor is accepted with diagnostic `schema_minor_newer`;
4. required keys `schema`, `schema_version`, `business_date`, `window`, `coverage`, `mailbox_ref`, `messages` (`missing_required_key`); `id_header`, `cycle_run_id` optional;
5. field types and an aware-UTC window with `end >= start` (`invalid_top_level_field`, `invalid_window`). A timestamp whose UTC instant falls outside the `datetime` range, or within one day of either end of it (year 9999 west of UTC, year 0001 east of it), is unparseable: in the window it is `invalid_window`; in a record it is `unparseable_timestamp` for `selected_utc` (that record only is quarantined) and `raw_timestamp_unparseable` for a raw field (a degradation).

**Dialects.** Lean carries the 9 canonical keys; rich adds `candidates`, `counts`, `provenance`, `threads`, `transport`. None of those 5 markers → lean; any → rich; a partial set → rich with `dialect_markers_incomplete`. Records are parsed field-driven, so rich per-record fields (privacy screen, `unique_body`, `links`, `fetch_state`, `in_window`, `parent_folder_id_returned`) are understood wherever they occur. Unknown top-level and record keys are counted (`unknown_top_level_keys`, `unknown_record_keys`) and never fatal.

**Record level.** A record that cannot be normalized is quarantined with reason codes (`missing_required_field`, `invalid_field_type`, `unparseable_timestamp`, `integrity_mismatch`, `mailbox_ref_mismatch`, …); usable records with a defect are `accepted_degraded` (`subject_empty`, `participant_from_absent`, `body_truncated`, `identity_provider_id_only`, …). One bad record never rejects its publication.

**The aggregate CLI isolates files.** A parse that raises unexpectedly for one file is reported as that file's rejection `internal_error`, which carries no exception type, message or content, and the other files' aggregates are still printed.

**Integrity.** When content is present its SHA-256 and UTF-8 byte count must match the declared values (`verified` / `mismatch`); a withheld body is `not_verifiable_withheld`; an absent digest is `not_declared`.

**Window.** `window.hours` is used only when it is a finite number from 0 to 10,000; anything else (`1e306`, a literal such as `1e400` that parses to infinity, a negative number, a string) raises `window_field_invalid` and is ignored, and the publication is still accepted. A usable `window.hours` is compared with the actual duration and a difference beyond 60 s raises `window_hours_mismatch` (a diagnostic, not a rejection). The DST flag is checked against the computed offset change in the declared time zone (`dst_flag_disagreement`); an unrecognized rule is tolerated as `unrecognized`. Window bounds are whole seconds (`WINDOW_RESOLUTION`): a sub-second `start_utc` or `end_utc` (ISO-8601 allows `.f`) is floored to its second at parse time and reported as `window_bound_floored` (a diagnostic, one per floored bound), so every coverage interval and gap is a whole-second span; flooring keeps `end >= start` (review R2, finding N2). Records are classified against the floored bounds, so a record timestamped inside the floored-off fraction of the end second is `out_of_window`, while flooring the start widens the window (a record at `05:00:00.2` against a start of `05:00:00.5` is in the window); the diagnostic makes both visible (review R3, finding R3-3).

Corpus result: 31 of 31 accepted, 0 quarantined, 0 unknown keys.

## 3. Identity resolution (WP1 rules; WP3 persists them)

- **Canonical key.** `CanonicalKey(mailbox_ref, kind, value)`: `kind = provider_returned` and `value` = Internet Message-ID when present; otherwise `kind = provider_id_only` and `value` = provider id. Persistence prefixes the Principal: `(principal_id, mailbox_ref, identity_kind, identity_value)`. The kinds are separate key spaces and never merge.
- **Provider id conflict** — one provider id whose observations disagree on body digest or carry two different Internet Message-IDs: every observation of it, exact repeats included, is quarantined (`provider_id_conflict`).
- **Lane identity degradation** — one provider id whose observations agree except that some lanes carry the Internet Message-ID and others do not (for example the sent lane lacks it): a missing id is a degradation, not a conflict. The lanes merge as usual, every observation gains `lane_identity_inconsistent`, and the Message-ID the other lane supplied is **lifted**: the item's canonical key and every observation's canonical key become `(mailbox_ref, provider_returned, that Message-ID)`, whichever lane is primary and whichever lane lacked it, and the identity rules use that key. Each record's own `identity_state` and Message-ID stay as reported (evidence; `by_identity_state` counts them). Corpus identity counts are taken under the item's lifted key, never under a lane observation's own provider-id key, so one provider id is one identity within a publication (review R2, finding N1). Lifting works within one publication only: the item has the same key in every publication only when some lane in each publication carries the Internet Message-ID; a publication in which no lane carries it keys the same item `provider_id_only` (review R3, finding R3-2; see the WP3 list below).
- **Identity conflict** — one canonical key whose distinct mailbox items disagree on sender address or body digest: every observation of those items, merged lane siblings and exact repeats included, is quarantined (`identity_conflict`) and never merged, so none of them counts as usable.
- **Two items, one message** — Inbox and Sent (or 2 Inbox) items under one Internet Message-ID are expected; their selected times legitimately differ.
- **Across publications (WP3).** A new snapshot's observation of an existing canonical key is checked against the stored message (sender, body digest). Agreement adds an observation; disagreement quarantines the new observation (`identity_conflict`), sets `identity_conflict = true` on the message, and counts it in the run. The stored message is not rewritten. Corpus: 0 conflicts.
- **As built in WP3a (ruling M6).** A later observation is matched to its mailbox item by provider id first, then by canonical key; an item is never rekeyed. It attaches when sender and body digest agree with the stored message; otherwise it is quarantined `identity_conflict`, the message's `identity_conflict` flag is set, the stored message is not rewritten, and the run counts it. Checks (c) and (d) below are implemented with tests. Check (e) is decided as separation (review R1 of WP3a, finding F1, ruling (a)): the key spaces never merge, in either direction. A record whose provider id already has a stored item whose message is of the other identity kind (stored `provider_id_only`, the record carries a Message-ID, or the reverse) is quarantined `identity_kind_mismatch` with every observation of its item in that snapshot, counted `records_identity_kind_mismatch`; it creates no message and no item, and the stored item and message are not rewritten or flagged. So a Message-ID is never split across two `provider_returned` messages by a provider id that was first seen without it: the other provider ids of that Message-ID (a Sent copy) still key one message. The join by provider id is WP3b.
- **WP3 cross-publication checks (review R1, findings 6c and 6d; not WP1 code).** WP1 checks identity within one publication only. WP3 must add, with tests: (c) one provider id observed with two different Internet Message-IDs across publications is detected and quarantined, never merged (today that fact comes from the Manager's corpus analysis only); (d) the `in_window` disagreement check runs on every observation, `lane_observation_merged` siblings included, not on primaries only; (e) one provider id keyed `provider_id_only` in one publication (no lane carried the Internet Message-ID) and `provider_returned` in another (review R3, finding R3-2: today these are two identities) — WP3 decides whether to join them by provider id, with tests.
- **Mutable provider ids.** A provider id is item identity at collection time only. An item moved between folders may reappear under a new provider id; it becomes a new mailbox item under the same canonical message, which is correct.
- **Never identity:** producer `dedup_key`, body SHA-256, subject (ADR-022 decision 8).

## 4. Deduplication and observation preservation

### 4.1 Classification (WP1)

`classify_records` assigns, first match wins: `quarantined`; `duplicate_observation` (same provider id, same folder role, same identity and body digest — an exact repeat); `lane_observation_merged` (same provider id in another folder role); `out_of_window` (selected time outside the inclusive window); `accepted_degraded`; `accepted`. Where a rich record declares `in_window` and disagrees, the record degrades (`in_window_disagreement`).

### 4.2 Items and observations (WP1)

`build_items` makes one `MailboxItem` per usable provider id per publication. Its observations are the primary plus every `lane_observation_merged` sibling (an exact repeat adds no evidence). The primary is the sent-lane observation when present, else the lowest ordinal. Participant reconciliation and canonical message time follow ADR-022 decision 7.

### 4.3 What is preserved (WP3)

Every record ordinal of every ingested snapshot leaves exactly one row: an observation row (accepted, degraded, merged, out-of-window) or a quarantine row (ordinal + reason codes). A `duplicate_observation` is stored as an observation flagged duplicate so counts reconcile to the record total. Nothing is silently dropped; corpus totals must reconcile (4,141 records = 3,711 + 8 + 421 + 1 + 0 + 0).

`out_of_window` observations are stored but do not contribute to the message's in-coverage claim.

## 5. PostgreSQL schema (WP3a built sections 5.1–5.3 on branch; WP2 for section 5.4)

All tables Principal-partitioned (`principal_id` NOT NULL, composite foreign keys `(…, principal_id)`, `ON DELETE RESTRICT`), reached through the partition guard, with identifier kinds of their own prefixes. Snapshot-derived rows are append-only (refusal triggers for UPDATE/DELETE and TRUNCATE, precedent `7d9a450dfd07` and `c8e4a1b70d35`), except the explicitly mutable projection columns named below. Lifecycle tables: section 1.2.

### 5.1 `communication_messages` (one row per canonical message)

| Column | Rule |
| --- | --- |
| `message_id` | PK, new identifier kind (proposed prefix `cmsg`) |
| `principal_id`, `mailbox_ref` | not null |
| `identity_kind` | `provider_returned` or `provider_id_only` |
| `identity_value` | Internet Message-ID or provider id |
| `conversation_id` | nullable |
| `subject` | nullable text |
| `sender_address` | normalized, nullable |
| `message_time`, `message_time_basis` | canonical time and `sent`/`received`/`selected_fallback` |
| `body_state`, `body_sha256`, `body_utf8_bytes`, `content_type`, `has_attachments` | from the primary observation |
| `search_text`, `search_text_sha256`, `search_text_version`, `search_text_basis`, `search_text_flags` | rebuildable projection (section 6); null when metadata-only |
| `identity_conflict`, `participants_reconciled`, `participants_disagreed` | flags |
| `first_snapshot_id`, `latest_snapshot_id`, `source_ordinal` | source pointer of the observation the text was derived from |
| `search_document` | generated `tsvector` (section 6) |

Constraints: `UNIQUE (principal_id, mailbox_ref, identity_kind, identity_value)`; `body_sha256` lowercase hex; `search_text` length at most 262,144; `search_text IS NULL` when `body_state` is `withheld` or `truncated`. Mutable columns (projection only): the `search_text*` group, `latest_snapshot_id`, the 3 flags; each change is versioned by `search_text_version` or recorded by an ingest run.

**As built (rulings m1, m2).** The source pointer of the text is `(text_snapshot_id, text_record_ordinal)` instead of `source_ordinal`; the `body_*` columns are taken from that same observation, so they move with the text and are mutable with it (`has_attachments` is immutable). The projection key is deterministic: an observation with a usable text basis, then the later declared window end, window start, file SHA-256 and the lowest ordinal. `search_text_version` is `comms_search_text_v1`, frozen unchanged.

**As built in WP4 (rulings R2, R3; revision `fa18ef3d9bc0`).** Two columns, both admitted to the named-mutable trigger: `identifiers_version` (nullable token: the extractor version the message's identifier rows were last written under; NULL on every WP3a row) and `source_unavailable` (boolean, default false: set by the rederive when the message's source file is missing or its SHA-256 differs, cleared when the original bytes return or when ingestion replaces the text pointer with a readable snapshot). New ingestion writes `comms_search_text_v2` and `comms_identifiers_v2` only (ruling R10). `communication_identifiers` stays append-only: the kind CHECK admits `pco` and `cor`, and no DELETE is admitted (prune deferred, ruling R4).

### 5.2 Items, observations, participants, identifiers, quarantine

- `communication_mailbox_items`: `item_id`, `principal_id`, `message_id`, `mailbox_ref`, `provider_id`, `provider_id_format`; `UNIQUE (principal_id, mailbox_ref, provider_id)`.
- `communication_observations`: `observation_id`, `principal_id`, `item_id`, `snapshot_id`, `record_ordinal`, `classification`, `folder_role`, `lane_verification`, `selected_field`, `selected_utc`, `received_utc`, `sent_utc` (with states), `body_sha256`, `unique_body_sha256`, `participants` (JSON of normalized address sets per field, no display names); `UNIQUE (snapshot_id, record_ordinal)`.
- `communication_participants`: canonical participants per message: `principal_id`, `message_id`, `field` (`from`, `sender`, `to`, `cc`, `bcc`, `reply_to`), `address`, provenance (`observation_ids`, lanes; **as built, ruling M7:** the row is append-only and holds only `first_observation_id`, and the full provenance is derived at read time from `communication_observations.participants`); PK `(principal_id, message_id, field, address)`; index `(principal_id, address, message_id)` for attendee joins (section 15).
- `communication_identifiers`: `principal_id`, `message_id`, `kind`, `value`, `extractor_version`; PK `(principal_id, message_id, kind, value, extractor_version)`; index `(principal_id, kind, value)`.
- `communication_quarantine`: `principal_id`, `snapshot_id`, `record_ordinal`, `reasons` (closed `ReasonCode` text array); `UNIQUE (snapshot_id, record_ordinal)`.
- **As built.** Every per-snapshot unique includes `principal_id`; observations carry `reasons` (the closed degradation codes); mailbox items carry `first_snapshot_id`; identifier kinds `cmsg`, `cmitm`, `cobs`, `cqrn`. There is no binding-snapshot foreign key on the meeting bindings (D8 stays; WP3b may add it).

### 5.3 Indexes

- GIN on `search_document`;
- GIN `gin_trgm_ops` on `subject` (near-miss subject lookup) — **not built; M1 closed as not needed in WP4 (rulings D5, R16):** no section 13 or 16 query does a near-miss subject lookup (text is FTS, identifiers are exact, participants are exact addresses), so there is no trigram index, no migration for one and no amendment to `tests/architecture/test_no_vector_retrieval_exists.py`. A later need (for example fuzzy Meeting titles in WP5) is a new proposal;
- B-tree `(principal_id, message_time DESC, message_id)` (time-ordered keyset pages);
- B-tree `(principal_id, conversation_id, message_time)` (thread collapse and reads);
- the participant and identifier indexes above.

No raw HTML, body content or display names are stored (ADR-022 decision 10). Display names are deliberately not carried by the WP1 normalized model; resolving a person by name goes through Entities and the address, not through mail text.

### 5.4 Meeting provider bindings (WP2, implemented)

Section 12.1.

## 6. Full-text search (WP4, implemented on branch; text derivation WP1)

**Indexed text** is `comms_search_text_v1` output, never the raw body: basis `unique_body` (rich), else digest-verified producer text, else the stored body; html reduced to text nodes; quoted chains cut (`-----Original Message-----`, `On … wrote:`, a `From:` header block, `>` lines; a cut that would leave nothing keeps the text and flags `quoted_chain_retained`); signature/disclaimer paragraphs removed (an RFC 3676 `-- ` delimiter near the end, a line starting `Disclaimer` or "if you have received this … in error", and a paragraph that *starts* with "confidentiality notice", "if you are not the intended recipient" or "This email … confidential" only in the trailing region of at most 15 non-blank lines; a line directly under a signature break — exactly `-- ` or a rule of five or more `-`, itself in the trailing region — also starts a paragraph, and the cut is then at the break line, so the body paragraph above the break is kept (review R3, finding R3-1), and a break earlier in the text never lifts the trailing-region limit; so a mid-paragraph sentence never truncates body text); capped at 262,144 characters. Withheld, truncated and empty bodies yield no text (`metadata_only`).

**Document:**

```sql
search_document tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
  setweight(to_tsvector('english', coalesce(search_text, '')), 'B')
) STORED
```

**Configuration.** `english` (stemming) as the report plane uses, because mail queries are topical ("schedule delay", "change orders"). The capture plane's `simple` argument (`D-90`, exact text) is answered here by the exact identifier index (section 7) and an exact-substring confirmation of quoted phrases (`strpos` over the narrowed candidates, as the capture plane does), not by a second tsvector. Query parsing: `websearch_to_tsquery('english', q)`. Participant addresses, identifiers and dates are structured filters, not text. **Manager ruling 2026-11-21 (R3, section 21):** `english` FTS plus the exact-identifier index plus `strpos` confirmation is accepted for now; WP4 must measure `english` against `simple` on synthetic and aggregate data and may switch.

Corpus derivation result, measured at `184ac6ca` (Manager real-corpus run, 2026-11-21) and re-verified unchanged at `80208caa` (Manager real-corpus run, 2026-11-21): 3,563 records body-based, 142 unique-body-based, 436 metadata-only; quoted chain removed in 2,011. `disclaimer_removed` is 108, measured at `80208caa` (Manager real-corpus run, 2026-11-21), after fix F2. History: 684 was measured at `ac0d06ae`, before fix F1 narrowed the disclaimer markers (review R1, finding 4); 125 was measured at `184ac6ca`, before fix F2 (review R2, findings N3 and N4) narrowed them again — breaks count only in the trailing region, and the recipient and confidentiality-notice phrases only at a trailing paragraph start — and made a marker paragraph directly under a trailing dash rule count.

**Closed in WP4: `comms_search_text_v2` (ruling D2).** The two markers v1 honoured on any line — a line starting `Disclaimer`, and a line holding "if you have received this … in error" anywhere in it — now count only as a paragraph start in the trailing region, like the other markers; a mid-body "Disclaimer language for the contract …" line and a mid-body "received this email in error" sentence are kept. Nothing else moved: v2's candidate cut lines are a subset of v1's and the cut placement is the same, so the v1 text of a message is always a prefix of its v2 text (a property test over every fixture and generated variants). Anchoring changes stored output, so the identifier is `comms_search_text_v2`; new ingestion writes v2, and stored messages are brought to it by the operator `rederive` (section 18). `disclaimer_removed`: 108 under v1, 89 under v2 (Manager real-corpus run, 2026-11-25). **Residual (review WP4-R1, finding F3, accepted as design of record):** in a short message (at most 15 non-blank lines, so the whole message is the trailing region) a paragraph that starts with one of the two markers is still cut, with everything after it; the runbook's residuals give the example.

**Built in WP3a.** `search_document` is the generated column above, with the `english` configuration and a GIN index (R3). The read side is WP4 (section 13).

**The D4 measurement and ruling D4-final (WP4).** `measure-fts` (an operator diagnostic, section 18) probes each stored message with the surface form of its identifiers and the alphabetic parts of its participants' address local parts, and counts what `english` and `simple` each find among the probes present in the text. Manager real-corpus run, 2026-11-25 (counts only): identifier class 0 uncovered (the identifier index answers every one); name class 3,887 present, `english` 3,130 and `simple` 3,396; the `english`-only loss is exactly the 267 stop-word names (`english_miss_simple_hit` = `stopword_empty` = 267), and the other misses are shared by both configurations (they come from the substring probe, not the configuration). Ruling D4-final: `english` stays the stored, indexed document, and the query adds a **stop-word fallback** with no schema change. When `websearch_to_tsquery('english', q)` keeps fewer lexemes than `websearch_to_tsquery('simple', q)`, the text condition becomes `search_document @@ q_en OR to_tsvector('simple', coalesce(subject,'') || ' ' || coalesce(search_text,'')) @@ q_simple`, computed on the fly over the candidates the other filters leave; the rank is the greater of the two `ts_rank_cd` values under the same integer formula; and the answer says `text_fallback: "simple_stopwords"`. A query with no searchable term under either configuration drops the text criterion and says `query_state: "no_searchable_terms"` (ruling R8: flagged, not refused). Measured latency of the fallback path at real-corpus size is about 470 ms at p50, accepted for interactive search (ruling C1); a stored `simple` column is reconsidered only if WP5's 10-Meeting context latency exceeds its budget.

**Version decision (F1, F2).** The narrowed markers change output for some valid inputs, but the identifier stays `comms_search_text_v1`: nothing has been persisted or published under it, WP1 is unmerged, and the corrected rules are the first `v1` that will be stored. Any change after WP3 persists searchable text is a new version — WP4's anchoring is therefore `comms_search_text_v2`.

## 7. Exact technical-identifier indexing (extractor WP1, v2 WP4; index WP3/WP4)

`extract_identifiers(text)` (`comms_identifiers_v1`; `comms_identifiers_v2` below is the current version) returns normalized, distinct `(kind, value)` pairs; the same function normalizes a query, so match is equality.

| Kind | Accepted forms | Normalized |
| --- | --- | --- |
| `rfi` | `RFI 174`, `RFI-174`, `RFI #174`, `RFI No. 174`, `RFI174`; case-insensitive | `rfi:174` |
| `cb` | `CB #2`, `CB 2`, `CB-2`, `CB No. 2`; upper case, separator required | `cb:2` |
| `co` | `CO #5`, `CO 5`, `CO-5`, `CO No. 5`; upper case, separator required (`CO2` and `PCO 5` are not) | `co:5` |
| `submittal` | `Submittal 12`, `Submittal #033000-01`; case-insensitive; digits kept verbatim | `submittal:033000-01` |
| `gmp`, `fpl` | bare upper-case tokens; plural normalizes | `gmp`, `fpl` |
| `spec` | **cue required** (`Section`, `Spec`, `Specification`, …) before `03 30 00` or `033000` (optionally `.13`), first pair 00–49 | `spec:033000` |

Every match is token-bounded: `RFI 17` never matches `RFI 174`, `RFI 1740` or `RFI 174.1`, and a number never continues into `.`, `-`, `/` or `,` followed by a digit, so the thousands form `RFI 1,740` yields nothing rather than `rfi:1`. Integer kinds drop leading zeros (`RFI 0174` is `rfi:174`); submittals and spec sections are kept digit-for-digit.

**Six-digit noise policy.** A bare six-digit number is never a spec section by default (1,713 corpus records hold one). `include_uncued_spec_sections=True` admits only the bare *spaced* form and is off in every stored index; turning it on is a new extractor version.

**Indexing.** Extraction runs over `subject + "\n" + search_text` (never over quoted chains), stored in `communication_identifiers` with the extractor version. A new version is written beside the old and switched atomically by a read setting; old rows are removed only after the switch. WP3a stores the rows with extractor version `comms_identifiers_v1`, unchanged; the recall gaps below are not fixed in WP3a and stay WP4's. Result over corpus v2 with extractor `comms_identifiers_v1`, measured at `184ac6ca` (Manager real-corpus run, 2026-11-21) (records): `gmp` 458, `fpl` 134, `rfi` 75, `submittal` 31, `cb` 10, `spec` 5, `co` 0 (at `ac0d06ae`, before fix F1: `rfi` 51, `submittal` 28, `spec` 1). WP4 measures recall on a labelled synthetic set and decides whether `pco`/`cor` kinds are added. **Open WP4 defect (Manager ruling 2026-11-21, R5, section 21):** `comms_identifiers_v1` recall is low against the analysis counts ([search characteristics](../evidence/communications-corpus/COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)): change orders 0 against 104 records, `fpl` 134 against 263, `submittal` 31 against 128 (measured at `184ac6ca`; 28 when the ruling was made at `ac0d06ae`). WP4 must fix it with tests; it does not block WP1. (Closed in WP4: below.)

**`comms_identifiers_v2` (WP4, rulings D3, R5, R5b (a), F6; the current version).** Every v1 form and token boundary is kept, and v2 adds:

| Kind | Forms added in v2 | Normalized |
| --- | --- | --- |
| every numbered kind | `:` as a separator (`RFI: 174`, `CO: 5`, `Submittal: 033000-01`) | as v1 |
| `rfi` | `Request for Information 174` (case-insensitive, separator required) | `rfi:174` |
| `cb` | `Change Bulletin 2` | `cb:2` |
| `co` | `Change Order 5`, `Change Order #5`, `Change Order No. 5` | `co:5` |
| `pco` (new kind) | `PCO 12`, `PCO-12`, `PCO #12`, `PCO: 12`, `PCO12` (upper case); `Potential` or `Proposed Change Order 12` | `pco:12` |
| `cor` (new kind) | `COR 7`, `COR-7`, `COR #7`, `COR: 7`, `COR7` (upper case); `Change Order Request 7` | `cor:7` |
| `submittal` | the plural `Submittals 12`; `Submittal Number 12`; the spaced spec form `Submittal 03 30 00-01` (v1 read it as `submittal:03`, a wrong identifier) | `submittal:033000-01` |
| `fpl` | exactly `FP&L` and `F.P.L.`, token-bounded (`F.P.L.P`, `F.P.L` and `F.P.L.s` yield nothing); lower- or mixed-case `fpl` stays unmatched (URL noise) | `fpl` |

`pco` and `cor` are their own kinds, numbered independently of the executed change order: `PCO 12` is never `co:12`, `COR 7` never `co:7`, and the qualified written forms never also yield a `co`. A number followed by `:` and a digit (`RFI 10:30`) or directly by a letter (`PCO 12a`, `RFI 174A`) yields nothing (F6). The six-digit spec policy and the `RFI 17` ≠ `RFI 174` boundaries are unchanged. A query item normalizes under the configured read version to exactly one identifier, or the request is `invalid_request` `identifiers` (ruling R11); identifiers found in the free-text query are merged into the requested set (R6). A labelled synthetic set (`tests/fixtures/communications_identifiers/labelled_v2.json`) holds v2 at precision and recall 1.0 for every kind, with true negatives expecting nothing; the documented-behaviour cases are a separate table.

**Storage and the read setting (rulings D3, R4, R10).** Ingestion writes the current version only; rederive writes the v2 rows beside the v1 rows of a stored message and records `identifiers_version`. Reads match the version `MY_PA_COMMUNICATIONS_IDENTIFIER_VERSION` names (default `comms_identifiers_v2`; `comms_identifiers_v1` is a rollback lever valid only for messages that still carry v1 rows) and normalize queries with the same version; every answer states it, and a search states `identifier_version_pending`, the messages whose rows are not yet of that version. The v1 rows are never pruned in WP4 (R4: prune deferred).

**Measured, counts only (Manager real-corpus run, 2026-11-25; 31 files, 4,141 records).** Records with at least one identifier of the kind, v1 → v2: change-order family (`co`, `pco`, `cor`) 0 → 91 (`pco` 89, `cor` 2; the analysis counted 104, and the remainder is mostly the keyword without a number, `co` 52); `submittal` 31 → 44 (118 keyword-without-number mentions have no identifier to index); `fpl` 134 → 134 (94 quoted or tail-only, excluded by design; 10 an unsupported shape); `rfi` 75 → 74 (after F6: the 6 dropped values were all v1 false positives, hexadecimal ids and one malformed match, so precision improved); `gmp` 458 → 459; `cb` 10 → 10; `spec` 5 → 5. Over the stored messages after the rederive (Manager real-corpus database run, 2026-11-25): 3,459 messages rederived, 21 with changed text, 817 v2 identifier rows added; v2 adds `pco` in 69 messages (124 rows) and `cor` in 2, and `submittal` goes from 23 to 36 messages. **R5 is closed:** every gap that has a number is covered; what remains are mentions with no number and quoted text excluded by design.

**Residuals (accepted).** `CO: 25 ppm` (a gas reading) reads as `co:25`; the spaced thousands form `RFI 1 740` reads as `rfi:1`; the prefixed RFI number form `RFI CON-132` is recognized by neither version (a candidate for a later extractor version); the `cor` unsupported shape (6 records) and the `fpl` unsupported shape (10 records; R5b stays (a), the expanded utility name is not admitted) are not extracted.

## 8. Lineage

- **Relation to record lineage (ADR-015).** Communications are not a lineage family in WP3–WP5 (ADR-022 decision 19). No `record_links` row references a message, and no native virtual edge is emitted.
- **Ingestion lineage is provenance, not record lineage.** Every message row names the snapshot and record ordinal it came from; every snapshot names its source and file SHA-256; every run names the snapshots it touched. That chain answers "where did this come from" without the lineage plane.
- **Later amendment (not designed further here).** Admitting a `communication` family would anchor passages as code-point slices of the stored `search_text` with `search_text_sha256` as the source digest (ADR-015 decision 5's shape), and would need an ADR-015 decision 6 amendment, a CHECK widening migration and tests. A search-text version change would then have to preserve the anchored version.

## 9. Coverage and freshness (summary WP1; persistence WP3a; read WP4)

- A publication contributes coverage only when accepted and overall coverage is `complete`; it contributes its declared `[start_utc, end_utc]` with the **end inclusive**.
- Intervals are merged when the next start is at most 1 s (`WINDOW_RESOLUTION`) after the previous end; anything wider is a **gap**. A gap is inclusive like a window: it runs from 1 s after the earlier end to 1 s before the next start, and its `seconds` counts both ends (`(end − start) + 1`). Covered through 03:59:59 and again from 04:00:00 the next day is a gap of exactly 86,400 s. Bounds are whole seconds because the parser floors a sub-second bound (section 2, `window_bound_floored`), so a gap's start is never after its end.
- `window.hours` and `business_date` never decide coverage (the Friday window is 33.2 h labelled 24).
- DST: windows are taken as declared in UTC; a 49 h (fall-back) or 47 h (spring-forward) weekend is valid. The declared DST flag is cross-checked (`dst_flag_disagreement`).
- Per-lane coverage: a lane (`inbox`, `sent`, `procore_rfis`) is reported separately; `not_authorized` lanes are reported as such and never as "no messages".
- **Freshness** = now − latest covered instant, per source. A read of a range answers `complete`, `partial` (with gaps) or `none`, plus freshness and the snapshot count, so a client never presents absence of mail in a gap as absence of communication.

Corpus: one interval 2026-10-17T04:00:00Z → 2026-11-20T14:12:05Z, no gaps (`summarize_corpus`).

**As built in WP3a.** One `ingest_coverage_windows` row per ingested snapshot (append-only), with per-lane states as a JSONB array (`key_kind` `inbox`, `sent`, `procore_rfis` or `other`, plus role, lane, authorized and state; ruling m4). `my_pa.domain.communications.coverage` is the pure merge, gap, lane and freshness computation; `CommunicationsCoverageReader` answers a range (`complete`, `partial` or `none`, gaps, freshness seconds, snapshot count) and the rolling 30-day monitoring read. The rolling read is `[latest_covered - 30 d, latest_covered]` (review R1 of WP3a, finding F5): it ends at the latest covered instant, not at the clock, so it reports holes only (`complete` or `partial` with its gaps) and is absent (`state` `none`, `start` and `end` null) when nothing is covered. Staleness is `freshness_seconds`, printed beside it: the operator reads freshness for staleness and the rolling state for holes. The operator command prints both; the client read is WP4.

## 10. Backfill (WP3a, merged in #376)

- Backfill is an operator CLI action naming a source and an explicit file list or path glob; it creates one run with trigger `backfill`.
- Files are ingested in ascending `window.start_utc` order, each snapshot in its own transaction, so a stop leaves a consistent prefix and a rerun skips ingested SHA-256 values.
- The 29 canonical publications are the initial backfill. Admitting the 2 rich publications outside the canonical folder was an open decision (they overlap canonical windows and add only verified lanes and privacy classes). **Manager ruling 2026-11-21 (R2, section 21):** both are admitted to backfill as explicitly registered sources; their overlap with canonical windows deduplicates by identity (sections 3 and 11).
- A dry-run mode parses, classifies and reports aggregate counts (the WP1 CLI output) without writing.
- **As built.** `apps/cli/communications_ingest.py backfill --source ID` with repeated `--file` names, one `--glob` name pattern, or neither for every candidate; `--dry-run` lists, reads, hashes, prepares and counts and writes nothing at all. A backfill reads on first sight (no two-poll wait: the files are at rest) and is allowed on a disabled source, so the operator can backfill before enabling the poll. The lifecycle orders by window start, then window end, then file SHA-256. The operator command builds a bounded engine (`statement_timeout` 60 s), reads the DSN only from `MY_PA_DATABASE_URL` (never argv, never printed) and refuses unless `--expected-database` and `--expected-alembic-head` match the live connection (ruling m7). Exit status is closed: `0` done (a run `completed`), `1` refused with one closed code, `2` usage, `3` a run finished `partial` or `failed`. `run-once` and `backfill` (not `--dry-run`, and not the read commands) take the poll's session advisory lock `COMMS_INGEST_LOCK_KEY` with `pg_try_advisory_lock` on a dedicated connection for the whole run; when another session holds it (the scheduled poll, or a second operator run) the command does not wait and refuses `lock_held` (exit `1`), writing nothing. `coverage` and `aggregate` refuse `source_not_found` (exit `1`) for a source id that names no admitted source. Output is one JSON object of ids, closed codes, counts and UTC timestamps only.

## 11. Incremental ingestion (WP3a, merged in #376)

- **Trigger.** A poll step on the cycles worker plane (section 19) lists each enabled source; an operator CLI command can run the same step once.
- **Idempotency** by `(principal_id, source_id, file_sha256)`: a known SHA-256 is skipped with no write except the run link. A crash mid-snapshot rolls back that snapshot only.
- **Stability.** A file is ingested only when its size and version token are unchanged across 2 consecutive polls (the collector may still be writing); a file that fails JSON parsing while still changing is retried, a stable one is rejected.
  **As built (ruling m6), with two exceptions.** Stability is remembered in the poll's process (one long-lived lifecycle), so a restart waits two polls again. (1) An operator run (`run-once`) and a backfill read on first sight; every read is still bound to the observed version token and size, and a file refused while it moved is `skipped_changing` and retried, never rejected. (2) A path whose size and version token equal those this process last finished with is `skipped_unchanged` without a read; the token is a change detector, never identity.
- **Re-publication.** New bytes at a known path → new snapshot; observations of existing messages are added, a newer search-text basis may replace the projection (e.g. a body that was empty), and the earlier snapshot is `superseded` for that path. Coverage keeps both windows; they merge.
- **Overlap.** Overlapping windows (rich vs canonical, weekend vs weekday) produce repeat observations of the same items — counted, never new messages (corpus: 191 provider ids recur, all identical).
- **Ordering.** Within a run, snapshots are processed oldest window first; the message projection always reflects a deterministic rule (latest snapshot with a usable text basis wins), independent of arrival order.
- **Meeting sync (third consumer, section 12).** Scheduled calendar sync must not run before the operator has reconciled existing Meetings in the batch review/reconcile pass (section 12.7, Manager ruling R-OP-6). Binding stays explicit and is never inferred from title or time. Once that pass is complete, calendar sync enables itself with no further operator switch; until then it stays off.
  **As built (WP3b, rulings D1, D4, D8).** The poll ingests a `meeting_sync_v1` source like any other: the consumer only **stages** (`meeting_sync_publications`, `meeting_sync_events`). After each poll, in the same `comms_ingest` step and under its lock, `MeetingSyncApplier.apply_pending` applies the staged publications, and does nothing until the reconciliation latch exists (`unapplied_awaiting_reconciliation`); the operator `run-once` and `backfill` do the same after their run. It logs one counts-only line, `meeting_sync.apply`. A disabled source's staged publications are held (`publications_held_source_disabled`) until it is enabled again. A publication whose apply transaction fails is counted `publications_failed`, stays unapplied, and blocks the later publications of its source until it applies.

## 12. Meeting provider identity and recurrence resolution (WP2, implemented)

**State.** Implemented and merged to `main` (#373): migration `6418b57081c3` (on `4d1069a7d84f`), persistence, the pure `meeting_sync_v1` contract and parser, the resolution service, and the `meetings.provider.bind` capability. Nothing is ingested: the sync source is registered as a lifecycle consumer in WP3, and the operator applies the ChatLLM collector change once from the producer contract's collector implementation notes (R-OP-8). The producer-facing contract is [`meeting-sync-v1-contract.md`](meeting-sync-v1-contract.md).

Meetings before WP2: `meetings` with nullable `meeting_series_id`, no provider columns; capabilities `meetings.create`, `meetings.list`, `meetings.read`, `meetings.search`, `meetings.update`, `meetings.series.update`, `meetings.notes.versions`, `meetings.notes.read_version`. WP2 adds no column to `meetings`: provider identity lives in two new tables.

### 12.1 Binding tables (WP2, implemented)

Both tables are in schema `knowledge`, Principal-partitioned, with composite foreign keys `(…, principal_id)` `ON DELETE RESTRICT` and `TRUNCATE` refused (the `c8e4a1b70d35` precedent).

`meeting_series_provider_bindings` (identifier prefix `msbnd`, `IdKind.MEETING_SERIES_PROVIDER_BINDING`): `series_binding_id`, `principal_id`, `meeting_series_id` (FK onto `meeting_series`), `calendar_ref`, `series_ical_uid`, `created_at`. Unique per Principal both ways: `(principal_id, calendar_ref, series_ical_uid)` and `(principal_id, meeting_series_id)`. **Append-only**: an update or delete is refused by trigger, so an unbind leaves the series binding in place.

`meeting_provider_bindings` (identifier prefix `mpbnd`, `IdKind.MEETING_PROVIDER_BINDING`): `binding_id`, `principal_id`, `meeting_id` (FK onto `meetings`), `calendar_ref` (neutral calendar reference, like `mailbox_ref`, 1–320 characters), `ical_uid` (1–1024), `occurrence_original_start_utc` (null for a single meeting), `series_ical_uid` (the master's UID for an occurrence; composite FK onto the series bindings, so an occurrence's series must be bound), `provider_event_id` and `provider_event_id_format` (`immutable_verified`, `mutable`, `unknown`; mutable attributes only), `provider_state` (CHECK: `active`, `cancelled`, `not_seen`), `last_seen_source_sha256`, `last_seen_record_ordinal`, `last_seen_at` (all null or all set; ruling D8), `last_applied_generated_at_utc` (nullable, mutable attribute; null after an explicit bind until a sync applies a record; rule 7), `version`, `created_at`, `updated_at`.

- **Occurrence identity:** partial unique index `one_provider_binding_per_occurrence` on `(principal_id, calendar_ref, ical_uid, occurrence_original_start_utc)` where the original start is not null — the original start, never the current start, so a moved occurrence keeps its identity.
- **Single meeting:** partial unique index `one_provider_binding_per_single_meeting` on `(principal_id, calendar_ref, ical_uid)` where `occurrence_original_start_utc IS NULL`.
- **One binding per Meeting:** `UNIQUE (principal_id, meeting_id)` (ruling D9).
- **An occurrence names both its series UID and its original start, a single meeting neither** (CHECK).
- **Guards:** the identity columns are immutable (trigger); one `(principal_id, calendar_ref, ical_uid)` is bound as a single meeting or as occurrences, never both (trigger serialized by a transaction advisory lock; ruling D9). `DELETE` of a binding row is permitted: it is the unbind.
- **Vocabularies:** the migration widens `meeting_write_requests`' capability CHECK to admit `meetings.provider.bind` and the internal namespace `system.meeting_provider.sync`, and restates `audit_events.capability_is_known` to 310 names (309 plus `meetings.provider.bind`). The internal namespace is never an audit name: a sync write writes no audit row.

### 12.2 Resolution rules (WP2, implemented)

`my_pa.domain.meeting_sync.resolution` decides; `my_pa.application.meeting_provider_sync.MeetingProviderSync.apply_event` carries the decision out inside the caller's unit of work.

1. A provider event with a known occurrence key updates the bound Meeting through `MeetingApplication.update_meeting` and its CAS, naming only the provider-owned fields (ruling D2); it never creates a second Meeting. A field that became absent (location, link) is an explicit clear.
2. An unknown occurrence of a known series creates a Meeting in that series.
3. An unknown series creates the series (`series_title` = the event title) with its first occurrence, and both bindings (ruling D7).
4. An existing unbound Meeting is bound only by the explicit `meetings.provider.bind` call naming both the Meeting and the full provider key, never by title or time matching (ruling D10).
5. A cancelled occurrence with a known key sets the Meeting status to cancelled; it is never deleted. A cancelled event with an unknown key creates nothing (`cancelled_unknown_skipped`; ruling D5).
6. Provider event ids are mutable attributes; a changed id with the same occurrence key is the same Meeting.
7. **Publication ordering (WP2-F1).** A known key's record is applied only in publication order: its publication's `generated_at_utc` is compared with the binding's `last_applied_generated_at_utc`. A strictly older stamp is skipped (`stale_record_skipped`); an equal stamp from a different publication (a different `last_seen_source_sha256`) is skipped (`ordering_conflict_skipped`); either skip writes nothing. An equal stamp from the same publication is the idempotent replay; a newer stamp, or a binding with no stamp yet, applies. The stamp is stored even for a record that changed nothing.

A UID already bound as the other kind is skipped (`binding_kind_conflict`; ruling D9). Re-applying an identical event writes no Meeting change and bumps no version. Each applied record has a deterministic idempotency key (`mpsync_` + SHA-256 of the binding key, publication SHA-256 and record ordinal), reserved in `meeting_write_requests` under the namespace `system.meeting_provider.sync`, so a sync key can never collide with a client key.

**Series change refusal (ruling D6).** `meetings.update` refuses a series move or detach of a provider-bound Meeting with `meeting_series_change_refused_provider_bound`; the path is to unbind first (`meetings.provider.bind` with `action` = `unbind`).

### 12.3 Source (WP2, implemented as contract; ingestion WP3b, on branch)

The source is (a) the `meeting_sync_v1` publication contract ([producer contract](meeting-sync-v1-contract.md), schema version 1.1.0; parser `my_pa.infrastructure.meeting_sync.parser`, `meeting_sync_v1_parser_v2` since WP3b, which adds the optional `coverage` claim (ruling D7) and gives every 1.0.x publication the outcome `meeting_sync_v1_parser_v1` gave it) and (b) the resolution service of section 12.2, in a separate `meeting_sync` slice with its own scope guard (`tests/architecture/test_meeting_sync_source_scope.py`; the communications and meeting-sync slices do not import each other). WP3b registers it as the **third** lifecycle consumer (section 1.2; ruling D1 below, and WP3b ruling D1, section 0.4). A quarantined record is counted only (`records_quarantined_<reason>`; WP3b ruling D14): meeting sync writes no quarantine row. No calendar data is in the WP1 corpus; WP2 fixtures (`tests/fixtures/meeting_sync/`) are synthetic.

Required top-level keys: `schema` (`meeting_sync_v1`), `schema_version` (major `1`), `events`, `generated_at_utc`; optional `cycle_run_id`. A missing `generated_at_utc` rejects the publication with `missing_required_key`, an invalid one with `invalid_top_level_field`. Records carry no body or description (`content_field_ignored`). A record the Meeting plane cannot hold exactly is quarantined under a closed reason code, never truncated (ruling D3): IANA zones only (`timezone_not_iana`), `https` links only (`url_unrepresentable`), all-day events unsupported (`all_day_unsupported`, ruling D4). The full code lists are in the producer contract.

### 12.4 `meetings.provider.bind` (WP2-W3, implemented)

One capability with a closed `action` (`bind` or `unbind`) and, since WP3b-S4, an optional occurrence-only `adopt_provider_series` (ruling D6; section 12.7), purpose `meeting_authoring`, arbitrated (`expected_version` CAS and an idempotency key in `meeting_write_requests`), bumping the Meeting version and writing one `meeting_history` `update` receipt and one Record Event naming `provider_binding` (ruling D10). A bind names `meeting_id`, `calendar_ref`, `ical_uid`, and for an occurrence both `occurrence_original_start_utc` and `series_ical_uid`, plus an optional `provider_event_id` and `provider_event_id_format`; an unbind names the Meeting only. Binding an occurrence of an unbound provider series creates the series binding to the Meeting's current series. The answer carries its own `MeetingProviderBindingView`; `meetings.read` and `MeetingView` are unchanged (ruling D11).

Refusal tokens (each names a field or a rule, never a key value or another Meeting): the field tokens `action`, `meeting_id`, `calendar_ref`, `ical_uid`, `occurrence_original_start_utc`, `series_ical_uid`, `provider_event_id`, `provider_event_id_format`; then, in order, `meeting_already_provider_bound`, `provider_key_bound_to_another_meeting`, `provider_binding_kind_conflict`, `provider_binding_requires_series`, `provider_series_binding_conflict`; and for an unbind `meeting_not_provider_bound`.

Counts: `Capability` grows 298 → 299; the audit capability set 309 → 310; `Purpose` is unchanged (70). The ChatLLM profile `chatllm-data-v15` classifies `meetings.provider.bind` `DATA_REQUIRED` (as `meetings.update` is). **v15 is the profile activated at deploy** (Manager ruling R-OP-4, under operator delegation 2026-11-22): it is applied, with the operator-profile grants (R-OP-2), in the consolidated goal activation (section 20.6). Until then no client holds the capability.

### 12.5 Manager rulings 2026-11-21 for WP2 (ratified under operator delegation 2026-11-22)

D1–D12 and rule 7 below were Manager rulings, previously not operator-ratified. They are **ratified under operator delegation 2026-11-22** (with ADR-022's acceptance, Manager ruling R-OP-1; effective on merge of WP2).

- **D1 — source.** The source is (a) the `meeting_sync_v1` contract plus (b) the resolution service, in a separate `meeting_sync` slice with its own scope guard. WP3 registers it as the third lifecycle consumer. The ChatLLM collector change is operator-applied (once, from the [collector implementation notes](meeting-sync-v1-contract.md#8-collector-implementation-notes), R-OP-8). Rejected alternatives: a client-written sync capability as the primary source; the native Apple calendar plane; Graph/Outlook; title/time matching; deferring the contract to WP3.
- **D2 — provider-owned fields.** The provider owns `start_at`, `end_at`, `timezone_name`, `status`, `title`, `location_text` and `virtual_meeting_url`. Sync never touches attendees in WP2 (nor description, notes, prep, Project or attachments). **Deferred attendee merge design:** merge by normalized email; add new attendees; update response status and organizer; retire only email-only rows previously supplied by the provider; **never retire Entity-linked rows**.
- **D3 — no truncation.** A value the Meeting plane cannot hold exactly quarantines the record; IANA zones only.
- **D4 — all-day.** All-day events are quarantined (`all_day_unsupported`).
- **D5 — cancelled unknown.** A cancelled event with an unknown key creates nothing (`cancelled_unknown_skipped`).
- **D6 — series ownership.** A series change on a provider-bound Meeting is refused (`meeting_series_change_refused_provider_bound`); unbind is the "unbind first" path.
- **D7 — series birth.** A series is born with its first occurrence, titled by `series_title` = the event title. A master with no instances creates nothing.
- **D8 — deviation from section 12.1 as first designed.** As WP2 shipped, `last_seen_snapshot_id` was replaced by `last_seen_source_sha256`, `last_seen_record_ordinal` and `last_seen_at`, all with no foreign key (the lifecycle snapshot table did not exist yet). **Superseded in WP3b (Manager ruling D10, revision `61fafdfd2986`):** the binding gained `origin_snapshot_id` (the snapshot whose record created it; NULL after an explicit bind; immutable by trigger) and `last_seen_snapshot_id` (present exactly when `last_seen_source_sha256` is), with composite foreign keys `(last_seen_snapshot_id, principal_id, last_seen_source_sha256)` and `(origin_snapshot_id, principal_id)` onto `ingest_snapshots`, so a recorded digest is the digest of the snapshot it names; `last_seen_record_ordinal` and `last_seen_at` stay.
- **D9 — one binding per Meeting.** Single and occurrence bindings for one UID are mutually exclusive in v1.
- **D10 — bind ships in WP2.** `meetings.provider.bind`: purpose `meeting_authoring`, arbitrated, version bump, history receipt, `bind`/`unbind` actions. Rationale: without bind, a future sync would duplicate every hand-made Meeting. WP3 adds the batch bind/review path over it (section 12.7, R-OP-6).
- **D11 — read surface deferred.** `provider_binding` on `meetings.read` / `MeetingView` is deferred to WP5; the bind answer returns its own binding view.
- **D12 — system writes.** Sync writes as actor `system`, under the internal namespace `system.meeting_provider.sync` (also the Record Event `source_capability` of every sync write; never a `Capability` member or audit name), by a direct call inside the caller's unit of work, with a deterministic idempotency key. WP3 decides the audit routing.
- **Rule 7 — publication ordering (F1).** Section 12.2 rule 7; `generated_at_utc` is required.

### 12.6 Open items, limitations and risks

- **C9 — address normalization risk for WP5.** Communications normalizes addresses with `.lower()` (`evidence_v2`); Meetings and meeting sync use `casefold` (the Relationship Intelligence EMAIL rule). The two agree for ASCII but not for every address; WP5's attendee join (section 15) must reconcile them.
- **C10 — `not_seen` (resolved in WP3b, ruling D7).** `provider_state` `not_seen` was defined but never written in WP2. Since WP3b the applier writes it from the producer's completeness claim only: a 1.1.0 publication's `coverage` (`start_utc`, `end_utc`, `calendar_refs`); a publication without it claims nothing. A binding whose calendar is listed and whose bound Meeting's **current** start lies in the window, but whose key is absent from the publication, is marked `not_seen` (version bumped, the publication's stamp stored, `last_seen_*` kept). It is **state only**: the Meeting is never touched, and the next publication that carries the key restores the state through the ordinary refresh. Any quarantined record in the publication suppresses the whole pass (`not_seen_suppressed_quarantine`). It is only as good as the producer's claim (producer contract section 1.1).
- **Concurrent binds (resolved in WP3b by the binding-writer lock, ruling D8).** As WP2 shipped, two concurrent binds of one unbound key to two Meetings could both pass the key check and meet at the unique index, surfacing as `internal_error`. Since WP3b every binding writer takes the Principal's binding-writer advisory lock first (below), so the second bind waits for the first to commit and then reads its binding: it is refused with the closed token `provider_key_bound_to_another_meeting`. Two concurrent reconciles that both complete the pass serialize the same way, so the latch is written once and both answer cleanly. Guarded by database-tier race tests (`tests/database/test_meeting_provider_bind.py`, `tests/database/test_meeting_provider_reconcile.py`).
- **Lock order (R1-2, fixed).** Every binding writer takes the binding row lock before the Meeting lock, the provider sync's order: sync locks the key's binding `FOR UPDATE`, then its Meeting; an unbind locks the Meeting's own binding `FOR UPDATE`, then the Meeting; a bind locks the requested key's binding `FOR UPDATE` (when one exists), then the Meeting. So a bind or unbind racing sync on one binding waits rather than deadlocks. Guarded by the database-tier lock-order tests in `tests/database/test_meeting_provider_bind.py`. A bind of a key with no binding yet locks no binding row; a concurrent sync insert of that key meets it only at the unique index and holds no lock on the bind's Meeting.
- **Unbind orphans the Meeting (R1-1) — resolved in WP3b (rulings D5, D6).** An unbind deletes the Meeting's binding, but the series binding is append-only and stays. As WP2 shipped: (a) the next sync publication carrying that key no longer resolved to the Meeting and would create a duplicate Meeting (rule 2 or 3); (b) after a series move (D6) of the unbound Meeting, binding it again was refused with `provider_series_binding_conflict`. **(a)** is closed by the unbind tombstone: the unbind writes one append-only `meeting_provider_key_tombstones` row for the deleted binding's key in the same transaction, and a later publication carrying that key while it has no binding is skipped (`unbound_key_suppressed`) and writes nothing; an explicit bind of the key wins (the binding is read first) and the tombstone stays. **(b)** is closed by `adopt_provider_series` (default false) on an occurrence bind or reconcile item: the Meeting is moved into the MeetingSeries its provider series is bound to, or, for a standalone Meeting of an unbound provider series, a MeetingSeries is created for it. **Deferral:** there is no "release tombstone"; a tombstoned key can only be bound explicitly, never re-created by sync.
- **Binding-writer lock (WP3b, ruling D8).** Every binding writer (the sync apply, the `not_seen` pass, `meetings.provider.bind` and the reconcile) first takes the Principal's transaction advisory lock (`MEETING_PROVIDER_BINDING_LOCK_CLASS`), so binding writers of one Principal serialize before the row-lock order above applies.
- **Residual risk — producer clock regression (F1).** A producer whose `generated_at_utc` goes backwards makes every record of a known key skip (`stale_record_skipped`) until a publication with a newer stamp arrives. The skips are visible only through diagnostics. The producer contract requires a strictly increasing `generated_at_utc`.

### 12.7 Constraint for WP3: reconcile before scheduled sync

**Scheduled calendar sync must NOT run until the operator has reconciled existing Meetings.** WP3a did not deliver this pass or register `meeting_sync_v1` as a consumer; WP3b delivers both (section 0.4, and "Implemented" below). Otherwise every hand-made Meeting that matches a provider event is duplicated by rule 3 or rule 2 (resolution never matches by title or time).

**Batch bind plan (Manager ruling R-OP-6, operator delegation 2026-11-22).** This refines the earlier default-off constraint; the "not before reconciliation" rule stands.

- **One pass.** WP3 adds a batch bind/review path, so the operator reconciles every existing Meeting in one pass instead of one `meetings.provider.bind` call per Meeting. Each binding it writes goes through the same rules as `meetings.provider.bind` (section 12.4: CAS, idempotency, history receipt, Record Event, refusal tokens).
- **Explicit, never inferred.** The operator names each Meeting and its full provider key, or marks it as having no provider event. The path may list candidates for review, but it never binds on title or time similarity, and nothing is bound without the operator's choice.
- **Auto-enable condition.** Calendar sync enables itself once the pass is complete (every existing Meeting is bound or marked unbound by the operator), with no extra operator switch. Before that it does not run. WP3 defines the recorded completion state that the scheduler checks.
- **Unbind precondition (R1-1).** Before calendar sync auto-enables, WP3 must deliver a rebind or suppression path for an unbound Meeting (an unbind tombstone recording that the key must not create or re-match a Meeting, or a rebind that re-points the series binding), so that an unbind cannot produce a duplicate Meeting or an unbindable one (section 12.6).

**Implemented (WP3b-S4; Manager rulings D2, D3, D4, D6, D12, D13).** `meetings.provider.review` and `meetings.provider.reconcile` carry the pass; the tool contract (fields, item shape, outcomes, refusal tokens) is the [meeting-sync contract, section 6](meeting-sync-v1-contract.md#6-what-my-pa-does-with-an-event-summary).

- `meetings.provider.review` — a read under `meeting_read`, scopeless: the pass state, one keyset page (≤100) of the in-scope Meetings (not cancelled, `start_at >= now − 30 days`, the collector lookback) with neither a binding nor a `no_provider_event` mark, and the staged provider events whose key is unbound (tombstoned keys listed `suppressed`), each with an opaque `provider_event_ref`: at most 200 events per page, ordered by start then key, with `unbound_provider_events_total` and `unbound_provider_events_truncated` (more remain after this page; Manager ruling on the S4 handoff), and a keyset cursor `unbound_provider_events_next` passed back as `events_after` for the next page (independent of the Meetings' cursor; R1 finding 2), so every event is reachable before the latch (a publication staged mid-sweep can place events before the cursor: restart the event sweep without `events_after`); binding an event's key removes it from the list. Side by side: no pairing, ranking or similarity anywhere (FAST guard). The staged event fields are eligible for the operator's own connected clients (D12, under R-OP-3).
- `meetings.provider.reconcile` — a write under `meeting_authoring`, scopeless, idempotency key required: 0–50 independent items, each an explicit `bind` (exactly `meetings.provider.bind`, by staged reference or full key, optional `adopt_provider_series`) or a `no_provider_event` mark, each under its own SAVEPOINT with an outcome `bound`, `marked`, `replayed` or `refused` and one closed refusal token. There is no "mark all".
- **The latch.** The reconcile that leaves no in-scope Meeting unreviewed records `meeting_provider_reconciliation_passes` once, in the reconcile call's own transaction (with its items, after them); calendar sync applies staged publications from the next applier run (`sync_enabled`). One-way; the review stays usable after it. **Post-latch duplicate risk:** a Meeting made by hand after the latch for an event the calendar also carries is not matched (sync never matches by title or time) and sync creates a second Meeting; there is no delete or merge, so the operator cancels one by hand (runbook).
- **Replay.** Replaying a batch under the same idempotency key is rebuilt item by item, not answered from a stored batch answer: each bind item answers its stored receipt (`replayed`) through its derived key, each mark answers `replayed`, and an item refused before wrote nothing, so it is **evaluated again** against the current state and may now be `bound` or `marked`, or be refused again (possibly with a different token).
- **R1-1 closed.** The unbind tombstone (WP3b-S3, D5) suppresses a re-create; `adopt_provider_series` (D6) lets a rebind after a series move succeed by moving the Meeting into the provider series' MeetingSeries, or creates a series for a standalone Meeting.
- **Counts.** `Capability` 299 → 301 (the audit capability set was restated to 312 by the WP3b revision); `Purpose` unchanged (70); three `SafeDetail` field tokens (`adopt_provider_series`, `items`, `provider_event_ref`); ChatLLM `chatllm-data-v16` = v15 plus both names, `DATA_REQUIRED` (D13), activated at the consolidated deploy instead of v15 with operator-profile grants (R-OP-2).

## 13. Retrieval (WP4, implemented on branch)

- **Search** (`communications.search`): text query (section 6), identifier terms (section 7, exact), participant addresses (any/all), time range (inclusive), folder role, conversation; results are messages, optionally collapsed to one per conversation (`collapse: conversation`, default on).
- **Read** (`communications.read`): a batch of message ids → metadata, canonical participants (addresses), flags, coverage of the message's snapshot, source pointer, and bounded search text. Never raw HTML, never a withheld body.
- **Thread view:** read accepts `conversation_id` to return the conversation's messages in time order (bounded).
- **Coverage** (`communications.coverage`): section 9 for a range.
- Every answer states the search-text and extractor versions and the coverage of the queried range.

**As built in WP4 (`my_pa.application.communications_search`; rulings D8, D9, R6–R13, C2).**

- **Search.** The text criterion is section 6 (with the D4-final fallback); quoted phrases (`"…"`, a negated `-"…"` excluded) are confirmed by exact substring over the narrowed candidates, within the subject or within the text and never across the two (WP4-R2 G5); a negated term or phrase (`-word`, `-"…"`) excludes a message in every tier, an identifier match included: every candidate must also satisfy the negated terms alone, `websearch_to_tsquery('english', …)` over the stored `search_document`, and a negated stop word, which leaves no lexeme there, excludes nothing (WP4-R2 G4); identifiers are exact, merged from the query (R6); participants are lower-cased addresses matched `any` (default) or `all`; `from_utc`/`to_utc` are inclusive whole-second instants; `folder_role` is a **lane claim** (ADR-022 decision 6): it matches a message with an observation in that lane, and each result lists its lanes with their verification, so a claim is never presented as membership (R7). No query and no identifiers is a browse by time (R8). Collapse by conversation is the default and keeps each conversation's best-ranked message, with `conversation_hits`; the keyset is applied after the collapse. A withheld or truncated body yields no snippet.
- **Answer.** `results[]`, `next_cursor`, `cursor_state`, `query_state`, `text_fallback`, `identifiers` (the normalized set matched), `versions` (`search_text_versions` stored, `identifier_version`, `identifier_version_pending`) and `coverage` of the queried range. Without a range the coverage is `[earliest covered, latest covered]`, with `freshness_seconds` beside it (R13).
- **Read.** Up to 25 ids, or one conversation 25 per page in `(message_time, message_id)` order with a cursor (R12). Each message: metadata, flags (including `source_unavailable`), participants with the observations and lanes that carry each (ruling M7), an observations summary, the source pointer, the coverage window of its text snapshot, its current-version identifiers, `search_text_version` and `search_text` (at most 20,000 characters with `truncated`; at most 200,000 per answer, later messages `text_omitted: "answer_cap"`; `include_text: false` gives `not_requested`; a withheld or truncated body gives `no_text`). Unknown and foreign ids are both `not_found`: every statement is scoped to the acting Principal.
- **Coverage.** Section 9 over every communications source of the Principal or one named `source` (unknown and foreign alike `not_found`), at most 366 days.
- **Cursors** (`my_pa.domain.communications.cursor`): opaque, bound to the capability, the Principal, the normalized request (without cursor and limit) and the identifier version, and scoped to the caller's grants on the 3 names. A malformed token is `invalid_request` `cursor`; another Principal's or another request's is `conflict` `cursor`; a cursor whose grant scope changed answers `cursor_state: "scope_changed_restart_required"` with nothing else (C2), not a refusal.
- **Latency** (synthetic set of real-corpus size, `tests/database/test_communications_search_latency.py`): the figures are recorded per read shape; the stop-word fallback is the slowest (about 470 ms at p50), accepted for interactive search (C1).

## 14. Ranking (WP4, implemented on branch)

Deterministic, explainable, no learned weights:

1. **Tier 1** — every requested identifier matched exactly;
2. **Tier 2** — some requested identifier matched;
3. **Tier 3** — text only.

Within a tier: integer `rank = floor(ts_rank_cd(search_document, query) * 1000000)` (subject weighted `A`, body `B`), then participant overlap with requested addresses, then `message_time DESC`, then `message_id` — a total order, so keyset cursors are exact (precedent: the report plane's integer rank). Quoted-chain stripping and conversation collapse are the defences against thread repetition; ranking adds no recency decay beyond the tie-break. Each result carries its tier and matched identifier kinds so a client can explain it.

**As built in WP4 (ruling D9).** Exactly the order above. A browse or an identifier-only search has rank 0 within its tier; with the D4-final fallback the rank is the greater of the `english` and `simple` ranks. Keyset cursors carry `(tier, rank, overlap, message_time, message_id)` and are exact: concatenated pages equal the uncursored order for every limit, with no duplicate or gap (database tier).

## 15. Meeting-context assembly (WP5)

`meetings.context.read` takes a batch of Meeting ids and returns, per Meeting:

- the Meeting (id, title, time, series, Project) and its provider binding state;
- **communications**: messages whose canonical participants intersect the attendees' normalized addresses within a lookback window (default 14 days before start, at most 90) plus messages matching identifiers found in the Meeting's title, notes and prep, plus the Project's identifiers; ranked as section 14; bounded per Meeting (default 15, max 50) and per message (snippet only; full text by `communications.read`);
- **coverage** of the lookback window (section 9), so a gap is stated;
- **PULSE evidence** (WP5, from WP4P's reads) when a PULSE source for the Meeting's Project is ingested; otherwise `pulse: {state: "unavailable"}`. The communications part never depends on PULSE.

Attendees with no address and Meetings with no provider binding still work (title, Project and identifier terms only); the answer says which inputs were missing.

## 16. Batch MCP contracts (WP4 built on branch, WP5)

Neutral names, accepted as proposals by Manager ruling 2026-11-21 (R4, section 21). **The three `communications.*` names are built in WP4** (below); `meetings.context.read` is WP5's and not in `Capability` yet. All read-only, Principal-scoped, behind `MY_PA_COMMUNICATIONS_ENABLED` (default off), one new purpose `communications_read`, ChatLLM profile data-conditional on a new `COMMUNICATIONS` prerequisite.

| Name | Request | Response | Bounds |
| --- | --- | --- | --- |
| `communications.search` | `query?`, `identifiers?[]`, `participants?[]`, `participant_mode` (`any`/`all`), `from_utc?`, `to_utc?`, `folder_role?`, `conversation_id?`, `collapse` (default `conversation`), `limit`, `cursor?` | `results[]` (`message_id`, `message_time`, `subject`, `sender_address`, `tier`, `rank`, `matched_identifier_kinds`, `snippet`, flags), `next_cursor`, `coverage`, versions | `limit` 1–50 (default 20); query ≤ 512 chars; ≤ 20 identifiers; ≤ 20 participants; snippet ≤ 300 chars |
| `communications.read` | `message_ids[]` or `conversation_id`, `include_text` (default true) | `messages[]` (metadata, participants with provenance, observations summary, source pointer, `search_text` with `truncated`), `not_found[]` | ≤ 25 ids; text ≤ 20,000 chars per message, ≤ 200,000 per answer |
| `communications.coverage` | `from_utc`, `to_utc`, `source?` | `state`, `intervals[]`, `gaps[]`, `freshness_seconds`, `snapshot_count`, lane states | range ≤ 366 days |
| `meetings.context.read` | `meeting_ids[]`, `lookback_days?`, `per_meeting_limit?` | `meetings[]` as section 15 | ≤ 10 meetings; lookback ≤ 90 |

Cursors are opaque, grant-bound and keyed on the section 14 order (precedent: S3 grant-bound cursors). Unknown or foreign ids are `not_found`, indistinguishably. Ingestion, source admission and backfill are operator CLI commands, not capabilities.

**As built in WP4 (rulings D7, D8; WP4-S5).** `Capability` gains `communications.search`, `communications.read` and `communications.coverage` (304 members) and `Purpose` gains `communications_read` (71), the only purpose each name permits. All three are reads (MCP `read_only_hint`), scopeless (they name the caller's own rows, never a configured source or enrollment), not operator-only, and `DATA_CONDITIONAL` on the `COMMUNICATIONS` prerequisite in `chatllm-data-v17`. With `MY_PA_COMMUNICATIONS_ENABLED` off (the default) the three are withheld from `capabilities.get`, readiness, the tool list, the remote profile and the ChatLLM composition, and an invocation answers the standard `unsupported`, never an empty result (D8); the switch is never composed in a restricted MCP database role composition, whose roles hold no privilege on the communications tables. The request bounds are the table above, refused as `invalid_request` naming one SafeDetail field token (`query`, `identifiers`, `participants`, `participant_mode`, `from_utc`, `to_utc`, `folder_role`, `conversation_id`, `collapse`, `limit`, `cursor`, `message_ids`, `include_text`, `source`); answers are section 13's, instants RFC 3339 UTC. Derived text only, never a raw body (R-OP-3, section 17).

## 17. Authorization and principal isolation

- Principal is server-derived (authentication only); no request names a Principal or mailbox.
- Every table is Principal-partitioned and reached through the partition guard (`tests/architecture/test_user_owned_tables_are_partitioned.py` and `tests/architecture/test_principal_partition_is_reached_through_the_guard.py` will cover the new tables).
- The remote principal is always the operator (ADR-013), so client separation is per-client grant and profile prerequisite, not Principal.
- **External-model eligibility (operator decision, `AGENTS.md` section 5):** returning mail text to a connected client sends it to that client's model. No grant is issued until the operator records that decision. It was recorded under operator delegation 2026-11-22 (Manager ruling R-OP-3): derived text (excerpts, search text, derived fields) is eligible for the operator's own connected clients; raw bodies stay withheld.
- Withheld bodies are never returned; addresses are returned only to granted clients; logs and audit rows carry capability, purpose, outcome and counts only.

## 18. Error handling and recovery

1. **Publication rejection** → snapshot `rejected` with its code; the run continues with the next file; nothing else is written.
2. **Record quarantine** → quarantine row; the rest of the publication is ingested.
3. **Run failure** (database error, crash) → that snapshot's transaction rolls back; the run is `partial` or `failed`; the next poll retries; idempotency makes retries safe.
4. **Rebuild** (new search-text or extractor version): an operator CLI command re-derives from the source pointer; if the publication file is gone or its SHA-256 differs, the stored projection stays and the message is flagged `source_unavailable`. **As built in WP4 (rulings D2, R2, R3, R4, R9; D-B1, D-B2):** `apps/cli/communications_ingest.py rederive [--dry-run] [--source] [--limit]`. A message is due when its `search_text_version` or `identifiers_version` is not current or it is flagged `source_unavailable`; at most `--limit` per run (default 1,000, at most 20,000), the rest deferred, so the command is bounded and resumable, and a finished rerun writes nothing. Each text-due snapshot is re-read once through the read-only workspace store and accepted only when its SHA-256 matches; the text is derived again from the same record, so the pointer and body columns do not move. A missing or changed file keeps the stored text, flags the message `source_unavailable` and still extracts v2 identifiers from the stored text (R9); the flag clears when the bytes return. A pointer that no longer names its record, and bytes the parser now rejects, write nothing and stay due. One transaction per snapshot, under the poll's lock (`lock_held` while a poll runs). Counts-only output, no audit row, no capability. The v1 identifier rows are never pruned in WP4 (**prune deferred**, R4).
5. **Identity conflict across publications** → section 3; operator-visible in run counts; resolution is a later operator tool, never automatic.
6. **Collector regression** (a lane `failed`, `partial` coverage, a schema major bump) → coverage reports the gap or the rejection; nothing is inferred.

## 19. Deployment and monitoring (WP3 onward; operator-gated)

- One additive migration per WP that needs one; downgrade refuses while rows exist.
- Switches, all default off: `MY_PA_COMMUNICATIONS_ENABLED` (reads), `MY_PA_COMMUNICATIONS_INGEST_ENABLED` (the poll step). **WP3a adds only `MY_PA_COMMUNICATIONS_INGEST_ENABLED`** (setting `communications_ingest_enabled`, default false) and `MY_PA_COMMUNICATIONS_INGEST_POLL_SECONDS` (default 900, bounded 60–86,400); `MY_PA_COMMUNICATIONS_ENABLED` gates the reads and is added by WP4.
- **Scheduler:** the poll step runs inside `apps/worker.py run --plane cycles` (#367: `run_cycle_scheduler` loop, `pg_try_advisory_lock` single flight) with its own lock key and interval (default 15 minutes), not a new plane, process or cron.
- **As built (ruling M2).** The cycles plane runs a tuple of steps, each with its own switch, advisory-lock key and due rule. The daily cycle keeps its date rule and `MY_PA_CYCLE_SCHEDULER_ENABLED`; the ingestion step's lock is `COMMS_INGEST_LOCK_KEY` = `advisory_lock_key(b"my-pa-ingest-poll")` (the first 8 bytes of its SHA-256, signed), it is due at plane start and then one interval after each attempt, and a busy lock skips that step only. The plane runs when either switch is on; with both off it still exits 2 `plane cycles disabled`. Composition stays in `apps/worker.py` (infrastructure does not import application): the workspace stores are composed eagerly, and a misconfigured workspace root exits 2 `plane cycles workspace_misconfigured`. Each poll writes one counts-only JSON log line (`comms_ingest.run`: sources, outcomes, summed counts). The cycles container reads the workspace through the read-only overlay `ops/nas/remote/compose.comms-ingest.remote.example.yml` (ruling M8; the store refuses a mount that is not `ST_RDONLY`).
- **Monitoring:** per run, counts by outcome; per source, freshness seconds, open gaps, rejected snapshots, quarantined records, identity conflicts; log lines carry codes and counts only. A runbook under `ops/runbooks/` is written in WP3: [`ops/runbooks/communications-ingestion.md`](../../ops/runbooks/communications-ingestion.md) (WP3a).
- **Project reports (WP3P, ADR-024).** A third step, `project_reports_ingest`, under `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` (default off) every `MY_PA_PROJECT_REPORTS_INGEST_POLL_SECONDS` (default 900, 60–86,400), with its own lock `PROJECT_REPORTS_POLL_LOCK_KEY` = `advisory_lock_key(b"my-pa-project-reports-poll")`, also taken by `bindings apply`; it polls, then runs the bounded re-derivation sweep, and logs `project_reports_ingest.run` and `project_reports.rederive`. Any one of the three switches starts the plane; with all three off it exits 2. Runbook: [`ops/runbooks/project-reports-ingestion.md`](../../ops/runbooks/project-reports-ingestion.md).
- Deployment, production migration, grants and source admission stay operator actions. They are bundled into the one consolidated activation of section 20.6 (R-OP-7).

## 20. Testing and acceptance

### 20.1 WP1 (implemented)

- FAST unit tests over synthetic fixtures for: both dialects, withheld bodies, null derived text, Inbox+Sent under one Message-ID, lane pairs, within-file repeat, out-of-window and exact-end boundary, the 33 h Friday window, the 48 h and 49 h weekend windows, missing Message-ID, malformed JSON, missing required fields, unknown major version, hostile HTML and prompt-injection text kept inert, identifier boundaries, search-text derivation, coverage merging; the architecture scope guard. Fix F1 (review R1) added regressions for out-of-range timestamps and `window.hours`, a mixed good/bad CLI batch, the content-free `internal_error`, ordinary text that mentions "this message … confidential" or a bare `--`, the lane identity degradation, repeats of a conflicted item, the `RFI 1,740` boundary and inclusive gap seconds.
- **Real-corpus validation (Manager only, aggregate output):**

  ```
  PYTHONPATH=src python -m my_pa.infrastructure.communications.aggregate_cli FILE [FILE ...]
  ```

  This is the source-checkout form. `-I` would ignore `PYTHONPATH` (and, with an editable install, import a stale tree); use `python -I -m …` only where the package is installed.

  It prints counts, closed-vocabulary values, validated timestamps and basenames only; exit 0 when every file is accepted, 1 otherwise, 2 on usage error. Result measured at `184ac6ca` (Manager real-corpus run, 2026-11-21): 31/31 accepted, 4,141 observations, 3,461 identities, 3,527 provider ids, 421 multi-lane items, 0 conflicts, 197 verified vs 3,944 unverified lanes, one coverage interval. The identity, lane, quarantine and coverage results were re-verified unchanged at `184ac6ca` against the `ac0d06ae` run; only `disclaimer_removed` and the `rfi`, `submittal` and `spec` identifier counts moved (sections 6 and 7). At `80208caa` (Manager real-corpus run, 2026-11-21), after fix F2, the summary was re-verified unchanged again (31/31 accepted; identities, provider ids, lanes, quarantines and coverage identical), 0 window bounds were floored, and only `disclaimer_removed` moved (125 → 108, section 6).

### 20.2 WP2

Implemented (merged in #373) with these tests (FAST unit, contract and database tiers). Migration from empty and from the preceding head; binding uniqueness; moved occurrence keeps identity; cancelled occurrence; series resolution; no title/time matching; reconciliation call CAS and idempotency; synthetic calendar fixtures only.

### 20.3 WP3

Lifecycle idempotency (same SHA-256 twice writes once); re-publication and alias paths; stability rule; record totals reconcile per snapshot; cross-publication identity conflict quarantines and does not rewrite; append-only triggers; partition guard; backfill resume; dry run writes nothing; the Manager's isolated-database real-corpus run reproduces section 20.1's figures; the scheduler step's single flight.

**WP3a (implemented; merged in #376).** Migration tier `tests/schema/test_communications_ingestion_migration.py` (tables, foreign keys, CHECKs, named-mutable, append-only and `TRUNCATE` triggers, downgrade refusal while rows exist); database tier `tests/database/test_communications_ingestion_persistence.py`, `test_communications_ingestion_application.py`, `test_communications_ingest_cli.py` (admit, dry-run backfill, backfill, idempotent rerun, coverage, aggregate over the synthetic fixtures) and `test_cycle_plane_steps.py` (two-process single flight on the new lock key); FAST `tests/unit/test_ingestion_lifecycle.py`, `test_communications_ingest.py`, `test_communications_coverage.py`, `test_communications_ingest_cli.py` (refusal on missing or mismatched expectations, DSN never echoed, dry run writes nothing, output holds no fixture subject or address) and `test_cycle_plane_steps.py` (per-step lock, due rule and interval, the switch matrix, the read-only overlay); the architecture guards of section 0.2. The real-corpus run is the Manager's, through the operator command against an isolated database; the WP1 figures it should reproduce are in section 20.1, deduplicated across sources (the WP1 aggregate counts each publication separately).

**WP3b (implemented on branch `feat/comms-meeting-sync`).** Migration tier `tests/schema/test_meeting_sync_staging_migration.py` (the five tables, the binding snapshot foreign keys and their CHECK pairing, the origin-immutable trigger, append-only and change-once guards, the upgrade refusal while a binding records `last_seen_*`, the downgrade refusals); database tier `tests/database/test_meeting_sync_persistence.py`, `test_meeting_sync_ingestion_application.py` (stage through the lifecycle, oldest stamp first), `test_meeting_sync_apply_application.py` (nothing before the latch, everything after; a stale publication skipped; a disabled source held; `not_seen` through the window query; tombstone suppression; the binding-writer lock serializing concurrent writers without a deadlock; the cycles step and `run-once` applying under the poll lock) and `test_meeting_provider_reconcile.py` (review scope and paging, the bounded event list, SAVEPOINT item isolation, the latch written once, adopt, replay, end to end); FAST `tests/unit/test_meeting_sync_parser_v2.py`, `test_meeting_sync_ingest.py`, `test_meeting_sync_apply.py` (apply order, the high-water gate, tombstone then rebind, `not_seen` mark, restore and suppression), `test_meeting_sync_staging_types.py`, `test_meeting_provider_reconcile.py`; contract `tests/contract/test_meeting_provider_reconcile_mcp.py`; architecture guards `test_meeting_sync_ingest_stages_only.py`, `test_meeting_sync_tables_hold_no_attendee_or_body_columns.py` and `test_meeting_provider_review_no_pairing.py` (no pairing, ranking or similarity in the pass). The WP3a nits closed with it: the CLI prints the `none` rolling shape for an admitted source with no snapshot, and a provider id in two records of one publication is quarantined `identity_kind_mismatch` once per record, in either arrival order.

### 20.4 WP4

FTS and identifier query correctness (`RFI 17` ≠ `RFI 174`), ranking total order and cursor exactness, collapse, withheld bodies never returned, bounds and refusals, policy closure for the new names and purpose, recall on a labelled synthetic set for each identifier kind.

**WP4 (implemented on branch `feat/comms-search`).** Each criterion and where it is proved:

| Criterion | Evidence |
| --- | --- |
| Search text v2 anchoring; the v1 text a prefix of the v2 text | FAST `tests/unit/test_communications_search_text.py` |
| Identifier recall and precision per kind on the labelled synthetic set; `RFI 17` ≠ `RFI 174`; the cross-kind traps; the six-digit policy | FAST `tests/unit/test_communications_identifiers_v2.py`, `test_communications_identifier_measure_cli.py` |
| Migration `fa18ef3d9bc0`: columns, named-mutable admission, kind CHECK, audit restatement, downgrade refusals and round trip | schema `tests/schema/test_communications_search_migration.py` |
| Rederive: due rule, bound, SHA-256 check, `source_unavailable` set and cleared, pointer and digest guards, dry run, lock, idempotent rerun; the FTS measurement | FAST `tests/unit/test_communications_rederive.py`; database `tests/database/test_communications_rederive.py`, `test_communications_fts_config_measurement.py` |
| FTS and identifier query correctness end to end; tiers; total order; cursor exactness for every limit; collapse; the `strpos` phrase; participants `any`/`all`; the lane claim; withheld bodies never returned; foreign ids `not_found`; the stop-word fallback; coverage `complete`/`partial`/`none`; versions | FAST `tests/unit/test_communications_search.py`; database `tests/database/test_communications_search.py` |
| Latency at real-corpus size | database `tests/database/test_communications_search_latency.py` |
| Policy closure for the 3 names and the purpose; bounds and refusals naming SafeDetail tokens only; switch off withholds and answers `unsupported`; answers carry versions and coverage; cross-Principal and cross-request cursors refused; grant change restarts | contract `tests/contract/test_communications_reads_mcp.py`, the transport-parity, negative-evidence, policy-closure and ChatLLM suites; FAST `tests/unit/test_remote_mcp_chatllm_profile.py` (v17 with the switch off desires exactly v16) |

The real-corpus measurements are the Manager's (sections 6 and 7).

### 20.5 WP5

Batch context over synthetic Meetings with and without bindings, attendee joins, coverage gaps stated, PULSE absent → `unavailable` with communications intact, response bounds, measured latency for 10 Meetings on the real-corpus-sized isolated database.

### 20.6 Consolidated activation (goal acceptance; Manager ruling R-OP-7)

There is **one** consolidated activation, at the end of the goal, not one per WP. One runbook and **one operator command** apply, in order:

1. the migrations of every merged WP (WP2's `6418b57081c3` and the later heads);
2. the grants: every comms and meeting-context capability (`meetings.provider.bind`, `meetings.provider.review`, `meetings.provider.reconcile`, `communications.*`, the meetings context batch, `project_reports.*`) to the **operator profile only**, with purpose defaults, so the connected client needs no per-call grant prompts (R-OP-2); nothing goes to a non-operator principal. The WP4 grants are exactly three, each with purpose `communications_read`: `communications.search`, `communications.read` and `communications.coverage`, written only after the read switch is on (the communications activation order: the migration, the rederive, the switch, then the grants; the runbook section 12.3). No slice writes a grant;
3. the ChatLLM profile `chatllm-data-v17` (v16 plus the 3 `communications.*` reads, `DATA_CONDITIONAL` on `MY_PA_COMMUNICATIONS_ENABLED`; v16 is v15 plus `meetings.provider.review` and `meetings.provider.reconcile`, both `DATA_REQUIRED`; activated instead of v15, Manager rulings D13 and D7; or the version current at that time; R-OP-4);
4. the schedulers (the cycles-plane poll steps of section 19; calendar sync still waits for the batch reconciliation of section 12.7).

**Project reports (WP3P, ADR-024), within the same activation.** After the migrations (which include `0d4e247d03cb`, applied with the cycles worker stopped): the operator's bindings file is placed (mode `0600`, outside the repository and the image), then `bindings check`, `bindings apply`, a dry-run backfill and a backfill per source, the stored `aggregate --expect` against the evidence figures, and only then `MY_PA_PROJECT_REPORTS_INGEST_ENABLED`. The `project_reports.*` grants arrive with WP4P. The steps are in [`ops/runbooks/project-reports-ingestion.md`](../../ops/runbooks/project-reports-ingestion.md) section 10.

The classifier blocks an agent's compose up, so the operator runs that command (or the Manager, where it is permitted). Goal acceptance includes a successful run of it. WP3 onward writes the runbook under `ops/runbooks/`.

## 21. Manager rulings 2026-11-21

The Manager ruled on the open items of this spec and ADR-022 after WP1. They were Manager rulings, not operator ratification, while ADR-022 was Proposed. ADR-022 is now accepted under operator delegation 2026-11-22 (R-OP-1, effective on merge of WP2); the operator gates in ADR-022 "Implementation status" and section 17 are settled as recorded there and in section 20.6.

| ID | Item | Ruling | Where |
| --- | --- | --- | --- |
| R1 | The worker reads the `mcp` workspace through the files store as an ingestion source | Ratified by the Manager, subject to the ADR-019 decision 7 preflight in WP3 | section 1.1 |
| R2 | The 2 rich publications outside the canonical folder | Admitted to backfill as explicitly registered sources; overlap deduplicates by identity | sections 10, 11 |
| R3 | Text-search configuration | `english` FTS plus the exact-identifier index plus `strpos` confirmation accepted for now; WP4 must measure `english` against `simple` on synthetic and aggregate data and may switch | section 6 |
| R4 | Capability names, the `communications_read` purpose, the default-off switches | Accepted as proposals. Grants, external-model eligibility and ADR-022 acceptance were then settled under operator delegation 2026-11-22 (R-OP-1 to R-OP-3) | sections 16, 17, 19 |
| R5 | `comms_identifiers_v1` recall (change orders 0 against 104, `fpl` 134 against 263, `submittal` 28 against 128 as ruled; `submittal` 31 measured at `184ac6ca`) | Recorded as an **open WP4 defect**, to be fixed with tests; does not block WP1. **Closed in WP4** by `comms_identifiers_v2` | sections 7, 20.4 |
| — | WP2 meeting-sync source | Deferred to WP2's investigation; then ruled by the Manager during WP2 as D1 | sections 12.3, 12.5 |
| — | The `Disclaimer` and "received this … in error" disclaimer markers are still unanchored | **Open WP4 item**; not fixed in WP1. **Closed in WP4** by `comms_search_text_v2` | section 6 |

**WP2 rulings.** The Manager's WP2 rulings of 2026-11-21 — D1 to D12 and resolution rule 7 (publication ordering, fix F1) — are recorded in [section 12.5](#125-manager-rulings-2026-11-21-for-wp2-ratified-under-operator-delegation-2026-11-22), with the WP2 open items, limitation and residual risk in section 12.6 and the WP3 reconcile-before-sync constraint in section 12.7. They are ratified under operator delegation 2026-11-22.

**WP3a rulings.** The Manager's WP3a rulings of 2026-11-22 (M1–M8, m1–m14 and the FTS ruling) and the deviations they make from this spec as first designed are recorded in [section 0.3](#03-wp3a-rulings-and-deviations-from-this-spec-as-first-designed), and amended in place in sections 1.2, 1.3, 3, 5, 6, 7, 9, 10, 11 and 19.

**WP4 rulings.** The Manager's WP4 rulings of 2026-11-25 are summarized here; the full record is the Manager's. Pre-design: D1 scope; D2 search text v2 and the operator rederive; D3 identifiers v2 with a read setting; D4 measure `english` against `simple` (then **D4-final**: keep `english`, add the stop-word fallback, section 6); D5 no trigram index (M1 closed); D6 at most one additive migration; D7 the 3 `communications.*` reads, `communications_read`, the read switch, `chatllm-data-v17`; D8 answers state versions and coverage, and the switch off is the standard refusal; D9 ranking exactly section 14; D10 pins. On the design report: R1 schema first; R2 the `identifiers_version` marker; R3 the `source_unavailable` column; R4 **no prune in WP4** (amends D3); R5 the `pco` and `cor` kinds and the v2 forms; R5b (a) `FP&L` and `F.P.L.` only; R6 query identifiers merged; R7 `folder_role` as a lane claim; R8 browse allowed, stop-word-only queries flagged; R9 identifiers from the stored text when the source is unavailable; R10 ingestion writes the current version only; R11 one identifier per query item; R12 25 per thread page with a cursor; R13 the covered range by default; R14 stale same-version identifier rows a residual; R15, R16 confirm D4 and D5; R17 `PURPOSE_ADMISSIONS`. On the slices: A1–A7 (WP4-S1/S2), D-B1–D-B6 (WP4-S3: an unparseable or pointer-mismatched snapshot writes nothing and stays due; a 1% materiality share), the review WP4-R1 findings F1–F7 (F3 and the F6 shapes accepted as residuals, sections 6 and 7), and C1–C5 (WP4-S4: the fallback latency accepted, `scope_changed_restart_required` an answer field). Where each is applied: sections 0.5, 5, 6, 7, 13, 14, 16, 18 and 20.
