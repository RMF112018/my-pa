# Communications intelligence — implementation contract

**Status:** implementation contract under [ADR-022](../decisions/ADR-022-communications-intelligence.md) (Accepted under operator delegation 2026-11-22, Manager ruling R-OP-1; effective on merge of WP2). **WP1 is implemented** (the pure source contract, this spec, the ADR and the corpus evidence; merged to `main` in #371). **WP2 is implemented on branch `feat/comms-meeting-identity` (not merged)**: section 12 and the [`meeting_sync_v1` producer contract](meeting-sync-v1-contract.md). Every other section is design for WP3–WP5, which each need their own PR, review and, where marked, operator decision. Nothing is granted, activated or deployed: migrations, grants, the ChatLLM profile and schedulers are applied in one consolidated activation at the end of the goal (section 20.6); WP2's migration `6418b57081c3` exists on its branch only and has been applied to disposable databases only.

**Basis:** contract head measured: branch `feat/comms-intelligence` at `80208caabe92de03be676a93fae8984d31d2b8c1` (tree `057703650c1f7b8976a86ccebc3da0a62f70d1a6`), the WP1 head after fix F2, on `origin/main@092610d36b7d1493fc7fda6e352a4bd06e914f61`; Alembic single head `640aaacc78e8` (129 revision files); 298 `Capability` members and 70 `Purpose` members. PR #368 (ADR-020, meeting prep, migration on `640aaacc78e8`) is open and not on this branch: WP2's migration must chain after whichever head is current when it is written. All counts here are digits on purpose (spelled-count guard). Paths to files that do not exist yet are not written as links (CI relative-link check).

**Corpus evidence:** [`docs/evidence/communications-corpus/`](../evidence/communications-corpus/README.md) (aggregates only, from the sanitized v2 analysis, SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`). Section numbers below are what [`CORPUS-DESIGN-IMPLICATIONS.md`](../evidence/communications-corpus/CORPUS-DESIGN-IMPLICATIONS.md) cites.

## 0. Work packages and implementation state

| WP | Content | State |
| --- | --- | --- |
| WP1 | ADR-022, this spec, 6 corpus deliverables; pure `communications_evidence_v2` contract (parse/validate/normalize both dialects, classification, lane reconciliation, integrity, `comms_search_text_v1`, `comms_identifiers_v1`, corpus coverage summary), aggregate-only CLI, synthetic fixtures, FAST tests | **implemented**, merged to `main` (#371); no migration |
| WP2 | Meeting provider identity and recurrence resolution (section 12): migration `6418b57081c3`, persistence, the `meeting_sync_v1` contract and parser, the resolution service, `meetings.provider.bind`, ChatLLM profile `chatllm-data-v15` (activated at the consolidated goal activation, R-OP-4), the [meeting-sync producer contract](meeting-sync-v1-contract.md) | **implemented** on branch `feat/comms-meeting-identity` (not merged); nothing granted, activated or deployed |
| WP3 | Shared ingestion lifecycle (section 1) + communications persistence (section 5), ingestion (sections 10–11), coverage (section 9), backfill, scheduled ingestion on the cycles plane, monitoring, runbook; the batch Meeting bind/review path that gates calendar sync (section 12.7, R-OP-6) | planned |
| WP3P | Procore PULSE persistence and ingestion on the WP3 lifecycle (designed separately by a later docs package) | planned |
| WP4 | Communications search service + MCP reads (sections 6, 7, 13, 14, 16) | planned |
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

## 1. Source acquisition and version control (shared ingestion lifecycle)

### 1.1 Where publications come from

The ChatLLM collector writes `communications_evidence_v2` publications into the `mcp` file workspace (ADR-019), canonical folder `My PA/Daily Intelligence/communications/`, one file per business date (`YYYYMMDD-comms.json`). Two rich-dialect publications sit elsewhere under `My PA/Daily Intelligence/`. my-pa **reads** them through the files workspace store's read path (list, stat with fingerprint version token, streamed read); it never writes, renames or trashes them. No new mount, source root or connector is introduced. Confirming that the worker can compose a read-only view of the `mcp` workspace (ADR-019 decision 7 keeps workspace and source roots disjoint; this is a workspace read, not a source root) is a WP3 preflight item. **Manager ruling 2026-11-21 (R1, section 21):** reading the `mcp` workspace through the files store as an ingestion source is ratified by the Manager, subject to that ADR-019 decision 7 preflight in WP3.

### 1.2 Shared lifecycle (WP3; consumers: communications first, PULSE second)

One lifecycle, content-free, with domain-specific storage behind it:

- **Source registry** — `ingest_sources`: one row per admitted source: `source_id`, `principal_id`, `consumer` (closed set: `communications_evidence_v2`, `pulse_csv_export`), `workspace_id`, `path_prefix`, `file_pattern`, `enabled`, `admitted_at`, `admitted_by` (operator channel). Admission is an operator CLI action (ADR-022 decision 15: no client capability).
- **Snapshots** — `ingest_snapshots`: one row per distinct file content seen: `snapshot_id`, `principal_id`, `source_id`, `relative_path`, `file_sha256`, `byte_count`, `observed_version_token`, `first_seen_at`, `status` (`pending`, `ingested`, `rejected`, `superseded`), `rejection_code`, `parser_version`. `UNIQUE (principal_id, source_id, file_sha256)` is the idempotency key. A snapshot is immutable once `ingested` or `rejected`.
- **Runs** — `ingest_runs`: `run_id`, `principal_id`, `source_id`, `trigger` (`schedule`, `operator`, `backfill`), `started_at`, `finished_at`, `outcome` (`completed`, `partial`, `failed`), and code-count JSON (snapshots seen/new/ingested/rejected/skipped, records per classification). `ingest_run_snapshots` links a run to each snapshot it touched with that snapshot's outcome.
- **Quarantine** — the consumer stores quarantined *records* (section 4.3); the lifecycle stores rejected *snapshots*. Neither stores content.
- **Coverage** — `ingest_coverage_windows`: one row per ingested snapshot with declared `[start_utc, end_utc]` (inclusive end), coverage state and per-lane states; merged intervals are computed at read time (section 9).

### 1.3 Version control

- A file is identified by its SHA-256, not its path or modification time. The same path with new bytes is a new snapshot; the earlier snapshot stays and is marked `superseded` for that path when the new one is ingested.
- The same bytes at another path (a copy) are the same snapshot: the second path is recorded as an alias on the snapshot and nothing is re-ingested.
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

## 5. PostgreSQL schema (design only; WP3 builds; WP2 for section 5.4)

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

### 5.2 Items, observations, participants, identifiers, quarantine

- `communication_mailbox_items`: `item_id`, `principal_id`, `message_id`, `mailbox_ref`, `provider_id`, `provider_id_format`; `UNIQUE (principal_id, mailbox_ref, provider_id)`.
- `communication_observations`: `observation_id`, `principal_id`, `item_id`, `snapshot_id`, `record_ordinal`, `classification`, `folder_role`, `lane_verification`, `selected_field`, `selected_utc`, `received_utc`, `sent_utc` (with states), `body_sha256`, `unique_body_sha256`, `participants` (JSON of normalized address sets per field, no display names); `UNIQUE (snapshot_id, record_ordinal)`.
- `communication_participants`: canonical participants per message: `principal_id`, `message_id`, `field` (`from`, `sender`, `to`, `cc`, `bcc`, `reply_to`), `address`, provenance (`observation_ids`, lanes); PK `(principal_id, message_id, field, address)`; index `(principal_id, address, message_id)` for attendee joins (section 15).
- `communication_identifiers`: `principal_id`, `message_id`, `kind`, `value`, `extractor_version`; PK `(principal_id, message_id, kind, value, extractor_version)`; index `(principal_id, kind, value)`.
- `communication_quarantine`: `principal_id`, `snapshot_id`, `record_ordinal`, `reasons` (closed `ReasonCode` text array); `UNIQUE (snapshot_id, record_ordinal)`.

### 5.3 Indexes

- GIN on `search_document`;
- GIN `gin_trgm_ops` on `subject` (near-miss subject lookup);
- B-tree `(principal_id, message_time DESC, message_id)` (time-ordered keyset pages);
- B-tree `(principal_id, conversation_id, message_time)` (thread collapse and reads);
- the participant and identifier indexes above.

No raw HTML, body content or display names are stored (ADR-022 decision 10). Display names are deliberately not carried by the WP1 normalized model; resolving a person by name goes through Entities and the address, not through mail text.

### 5.4 Meeting provider bindings (WP2, implemented on branch)

Section 12.1.

## 6. Full-text search (WP4; text derivation WP1)

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

**Open WP4 item (Manager ruling 2026-11-21: not fixed in WP1).** Two disclaimer markers are still unanchored: a line starting `Disclaimer` and the "if you have received this … in error" phrase match on any line anywhere in the text, not only on a paragraph-start line in the trailing region as the other markers do, and the "received this … in error" phrase matches anywhere within its line. WP4 must anchor them, with tests; until then they can cut body text that merely mentions a disclaimer.

**Version decision (F1, F2).** The narrowed markers change output for some valid inputs, but the identifier stays `comms_search_text_v1`: nothing has been persisted or published under it, WP1 is unmerged, and the corrected rules are the first `v1` that will be stored. Any change after WP3 persists searchable text is a new version.

## 7. Exact technical-identifier indexing (extractor WP1; index WP3/WP4)

`extract_identifiers(text)` (`comms_identifiers_v1`) returns normalized, distinct `(kind, value)` pairs; the same function normalizes a query, so match is equality.

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

**Indexing.** Extraction runs over `subject + "\n" + search_text` (never over quoted chains), stored in `communication_identifiers` with the extractor version. A new version is written beside the old and switched atomically by a read setting; old rows are removed only after the switch. Result over corpus v2 with extractor `comms_identifiers_v1`, measured at `184ac6ca` (Manager real-corpus run, 2026-11-21) (records): `gmp` 458, `fpl` 134, `rfi` 75, `submittal` 31, `cb` 10, `spec` 5, `co` 0 (at `ac0d06ae`, before fix F1: `rfi` 51, `submittal` 28, `spec` 1). WP4 measures recall on a labelled synthetic set and decides whether `pco`/`cor` kinds are added. **Open WP4 defect (Manager ruling 2026-11-21, R5, section 21):** `comms_identifiers_v1` recall is low against the analysis counts ([search characteristics](../evidence/communications-corpus/COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)): change orders 0 against 104 records, `fpl` 134 against 263, `submittal` 31 against 128 (measured at `184ac6ca`; 28 when the ruling was made at `ac0d06ae`). WP4 must fix it with tests; it does not block WP1.

## 8. Lineage

- **Relation to record lineage (ADR-015).** Communications are not a lineage family in WP3–WP5 (ADR-022 decision 19). No `record_links` row references a message, and no native virtual edge is emitted.
- **Ingestion lineage is provenance, not record lineage.** Every message row names the snapshot and record ordinal it came from; every snapshot names its source and file SHA-256; every run names the snapshots it touched. That chain answers "where did this come from" without the lineage plane.
- **Later amendment (not designed further here).** Admitting a `communication` family would anchor passages as code-point slices of the stored `search_text` with `search_text_sha256` as the source digest (ADR-015 decision 5's shape), and would need an ADR-015 decision 6 amendment, a CHECK widening migration and tests. A search-text version change would then have to preserve the anchored version.

## 9. Coverage and freshness (summary WP1; persistence WP3; read WP4)

- A publication contributes coverage only when accepted and overall coverage is `complete`; it contributes its declared `[start_utc, end_utc]` with the **end inclusive**.
- Intervals are merged when the next start is at most 1 s (`WINDOW_RESOLUTION`) after the previous end; anything wider is a **gap**. A gap is inclusive like a window: it runs from 1 s after the earlier end to 1 s before the next start, and its `seconds` counts both ends (`(end − start) + 1`). Covered through 03:59:59 and again from 04:00:00 the next day is a gap of exactly 86,400 s. Bounds are whole seconds because the parser floors a sub-second bound (section 2, `window_bound_floored`), so a gap's start is never after its end.
- `window.hours` and `business_date` never decide coverage (the Friday window is 33.2 h labelled 24).
- DST: windows are taken as declared in UTC; a 49 h (fall-back) or 47 h (spring-forward) weekend is valid. The declared DST flag is cross-checked (`dst_flag_disagreement`).
- Per-lane coverage: a lane (`inbox`, `sent`, `procore_rfis`) is reported separately; `not_authorized` lanes are reported as such and never as "no messages".
- **Freshness** = now − latest covered instant, per source. A read of a range answers `complete`, `partial` (with gaps) or `none`, plus freshness and the snapshot count, so a client never presents absence of mail in a gap as absence of communication.

Corpus: one interval 2026-10-17T04:00:00Z → 2026-11-20T14:12:05Z, no gaps (`summarize_corpus`).

## 10. Backfill (WP3)

- Backfill is an operator CLI action naming a source and an explicit file list or path glob; it creates one run with trigger `backfill`.
- Files are ingested in ascending `window.start_utc` order, each snapshot in its own transaction, so a stop leaves a consistent prefix and a rerun skips ingested SHA-256 values.
- The 29 canonical publications are the initial backfill. Admitting the 2 rich publications outside the canonical folder was an open decision (they overlap canonical windows and add only verified lanes and privacy classes). **Manager ruling 2026-11-21 (R2, section 21):** both are admitted to backfill as explicitly registered sources; their overlap with canonical windows deduplicates by identity (sections 3 and 11).
- A dry-run mode parses, classifies and reports aggregate counts (the WP1 CLI output) without writing.

## 11. Incremental ingestion (WP3)

- **Trigger.** A poll step on the cycles worker plane (section 19) lists each enabled source; an operator CLI command can run the same step once.
- **Idempotency** by `(principal_id, source_id, file_sha256)`: a known SHA-256 is skipped with no write except the run link. A crash mid-snapshot rolls back that snapshot only.
- **Stability.** A file is ingested only when its size and version token are unchanged across 2 consecutive polls (the collector may still be writing); a file that fails JSON parsing while still changing is retried, a stable one is rejected.
- **Re-publication.** New bytes at a known path → new snapshot; observations of existing messages are added, a newer search-text basis may replace the projection (e.g. a body that was empty), and the earlier snapshot is `superseded` for that path. Coverage keeps both windows; they merge.
- **Overlap.** Overlapping windows (rich vs canonical, weekend vs weekday) produce repeat observations of the same items — counted, never new messages (corpus: 191 provider ids recur, all identical).
- **Ordering.** Within a run, snapshots are processed oldest window first; the message projection always reflects a deterministic rule (latest snapshot with a usable text basis wins), independent of arrival order.
- **Meeting sync (third consumer, section 12).** Scheduled calendar sync must not run before the operator has reconciled existing Meetings in WP3's batch bind/review pass (section 12.7, Manager ruling R-OP-6). Binding stays explicit and is never inferred from title or time. Once that pass is complete, calendar sync enables itself with no further operator switch; until then it stays off.

## 12. Meeting provider identity and recurrence resolution (WP2, implemented on branch)

**State.** Implemented on branch `feat/comms-meeting-identity` (not merged): migration `6418b57081c3` (on `4d1069a7d84f`), persistence, the pure `meeting_sync_v1` contract and parser, the resolution service, and the `meetings.provider.bind` capability. Nothing is ingested: the sync source is registered as a lifecycle consumer in WP3, and the operator applies the ChatLLM collector change once from the producer contract's collector implementation notes (R-OP-8). The producer-facing contract is [`meeting-sync-v1-contract.md`](meeting-sync-v1-contract.md).

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

### 12.3 Source (WP2, implemented as contract; ingestion WP3)

The source is (a) the `meeting_sync_v1` publication contract ([producer contract](meeting-sync-v1-contract.md); parser `my_pa.infrastructure.meeting_sync.parser`, `meeting_sync_v1_parser_v1`) and (b) the resolution service of section 12.2, in a separate `meeting_sync` slice with its own scope guard (`tests/architecture/test_meeting_sync_source_scope.py`; the communications and meeting-sync slices do not import each other). WP3 registers it as the **third** lifecycle consumer (section 1.2). Ruling D1 below. No calendar data is in the WP1 corpus; WP2 fixtures (`tests/fixtures/meeting_sync/`) are synthetic.

Required top-level keys: `schema` (`meeting_sync_v1`), `schema_version` (major `1`), `events`, `generated_at_utc`; optional `cycle_run_id`. A missing `generated_at_utc` rejects the publication with `missing_required_key`, an invalid one with `invalid_top_level_field`. Records carry no body or description (`content_field_ignored`). A record the Meeting plane cannot hold exactly is quarantined under a closed reason code, never truncated (ruling D3): IANA zones only (`timezone_not_iana`), `https` links only (`url_unrepresentable`), all-day events unsupported (`all_day_unsupported`, ruling D4). The full code lists are in the producer contract.

### 12.4 `meetings.provider.bind` (WP2-W3, implemented)

One capability with a closed `action` (`bind` or `unbind`), purpose `meeting_authoring`, arbitrated (`expected_version` CAS and an idempotency key in `meeting_write_requests`), bumping the Meeting version and writing one `meeting_history` `update` receipt and one Record Event naming `provider_binding` (ruling D10). A bind names `meeting_id`, `calendar_ref`, `ical_uid`, and for an occurrence both `occurrence_original_start_utc` and `series_ical_uid`, plus an optional `provider_event_id` and `provider_event_id_format`; an unbind names the Meeting only. Binding an occurrence of an unbound provider series creates the series binding to the Meeting's current series. The answer carries its own `MeetingProviderBindingView`; `meetings.read` and `MeetingView` are unchanged (ruling D11).

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
- **D8 — deviation from section 12.1 as first designed.** `last_seen_snapshot_id` is replaced by `last_seen_source_sha256`, `last_seen_record_ordinal` and `last_seen_at`, all with no foreign key (the lifecycle snapshot table does not exist yet). WP3 may add a snapshot foreign key.
- **D9 — one binding per Meeting.** Single and occurrence bindings for one UID are mutually exclusive in v1.
- **D10 — bind ships in WP2.** `meetings.provider.bind`: purpose `meeting_authoring`, arbitrated, version bump, history receipt, `bind`/`unbind` actions. Rationale: without bind, a future sync would duplicate every hand-made Meeting. WP3 adds the batch bind/review path over it (section 12.7, R-OP-6).
- **D11 — read surface deferred.** `provider_binding` on `meetings.read` / `MeetingView` is deferred to WP5; the bind answer returns its own binding view.
- **D12 — system writes.** Sync writes as actor `system`, under the internal namespace `system.meeting_provider.sync` (also the Record Event `source_capability` of every sync write; never a `Capability` member or audit name), by a direct call inside the caller's unit of work, with a deterministic idempotency key. WP3 decides the audit routing.
- **Rule 7 — publication ordering (F1).** Section 12.2 rule 7; `generated_at_utc` is required.

### 12.6 Open items, limitations and risks

- **C9 — address normalization risk for WP5.** Communications normalizes addresses with `.lower()` (`evidence_v2`); Meetings and meeting sync use `casefold` (the Relationship Intelligence EMAIL rule). The two agree for ASCII but not for every address; WP5's attendee join (section 15) must reconcile them.
- **C10 — `not_seen`.** `provider_state` `not_seen` is defined (and admitted by the CHECK) but never written in WP2. It needs WP3 coverage (an event absent from a complete publication).
- **Known limitation.** Two concurrent binds can surface as `internal_error` rather than a closed refusal token. Accepted for now.
- **Residual risk — producer clock regression (F1).** A producer whose `generated_at_utc` goes backwards makes every record of a known key skip (`stale_record_skipped`) until a publication with a newer stamp arrives. The skips are visible only through diagnostics. The producer contract requires a strictly increasing `generated_at_utc`.

### 12.7 Constraint for WP3: reconcile before scheduled sync

**Scheduled calendar sync must NOT run until the operator has reconciled existing Meetings.** Otherwise every hand-made Meeting that matches a provider event is duplicated by rule 3 or rule 2 (resolution never matches by title or time).

**Batch bind plan (Manager ruling R-OP-6, operator delegation 2026-11-22).** This refines the earlier default-off constraint; the "not before reconciliation" rule stands.

- **One pass.** WP3 adds a batch bind/review path, so the operator reconciles every existing Meeting in one pass instead of one `meetings.provider.bind` call per Meeting. Each binding it writes goes through the same rules as `meetings.provider.bind` (section 12.4: CAS, idempotency, history receipt, Record Event, refusal tokens).
- **Explicit, never inferred.** The operator names each Meeting and its full provider key, or marks it as having no provider event. The path may list candidates for review, but it never binds on title or time similarity, and nothing is bound without the operator's choice.
- **Auto-enable condition.** Calendar sync enables itself once the pass is complete (every existing Meeting is bound or marked unbound by the operator), with no extra operator switch. Before that it does not run. WP3 defines the recorded completion state that the scheduler checks.

## 13. Retrieval (WP4)

- **Search** (`communications.search`): text query (section 6), identifier terms (section 7, exact), participant addresses (any/all), time range (inclusive), folder role, conversation; results are messages, optionally collapsed to one per conversation (`collapse: conversation`, default on).
- **Read** (`communications.read`): a batch of message ids → metadata, canonical participants (addresses), flags, coverage of the message's snapshot, source pointer, and bounded search text. Never raw HTML, never a withheld body.
- **Thread view:** read accepts `conversation_id` to return the conversation's messages in time order (bounded).
- **Coverage** (`communications.coverage`): section 9 for a range.
- Every answer states the search-text and extractor versions and the coverage of the queried range.

## 14. Ranking (WP4)

Deterministic, explainable, no learned weights:

1. **Tier 1** — every requested identifier matched exactly;
2. **Tier 2** — some requested identifier matched;
3. **Tier 3** — text only.

Within a tier: integer `rank = floor(ts_rank_cd(search_document, query) * 1000000)` (subject weighted `A`, body `B`), then participant overlap with requested addresses, then `message_time DESC`, then `message_id` — a total order, so keyset cursors are exact (precedent: the report plane's integer rank). Quoted-chain stripping and conversation collapse are the defences against thread repetition; ranking adds no recency decay beyond the tie-break. Each result carries its tier and matched identifier kinds so a client can explain it.

## 15. Meeting-context assembly (WP5)

`meetings.context.read` takes a batch of Meeting ids and returns, per Meeting:

- the Meeting (id, title, time, series, Project) and its provider binding state;
- **communications**: messages whose canonical participants intersect the attendees' normalized addresses within a lookback window (default 14 days before start, at most 90) plus messages matching identifiers found in the Meeting's title, notes and prep, plus the Project's identifiers; ranked as section 14; bounded per Meeting (default 15, max 50) and per message (snippet only; full text by `communications.read`);
- **coverage** of the lookback window (section 9), so a gap is stated;
- **PULSE evidence** (WP5, from WP4P's reads) when a PULSE source for the Meeting's Project is ingested; otherwise `pulse: {state: "unavailable"}`. The communications part never depends on PULSE.

Attendees with no address and Meetings with no provider binding still work (title, Project and identifier terms only); the answer says which inputs were missing.

## 16. Batch MCP contracts (WP4, WP5)

Proposed names (neutral; not in `Capability` yet; accepted as proposals by Manager ruling 2026-11-21, R4, section 21). All read-only, Principal-scoped, behind `MY_PA_COMMUNICATIONS_ENABLED` (default off), one new purpose `communications_read`, ChatLLM profile data-conditional on a new `COMMUNICATIONS` prerequisite.

| Name | Request | Response | Bounds |
| --- | --- | --- | --- |
| `communications.search` | `query?`, `identifiers?[]`, `participants?[]`, `participant_mode` (`any`/`all`), `from_utc?`, `to_utc?`, `folder_role?`, `conversation_id?`, `collapse` (default `conversation`), `limit`, `cursor?` | `results[]` (`message_id`, `message_time`, `subject`, `sender_address`, `tier`, `rank`, `matched_identifier_kinds`, `snippet`, flags), `next_cursor`, `coverage`, versions | `limit` 1–50 (default 20); query ≤ 512 chars; ≤ 20 identifiers; ≤ 20 participants; snippet ≤ 300 chars |
| `communications.read` | `message_ids[]` or `conversation_id`, `include_text` (default true) | `messages[]` (metadata, participants with provenance, observations summary, source pointer, `search_text` with `truncated`), `not_found[]` | ≤ 25 ids; text ≤ 20,000 chars per message, ≤ 200,000 per answer |
| `communications.coverage` | `from_utc`, `to_utc`, `source?` | `state`, `intervals[]`, `gaps[]`, `freshness_seconds`, `snapshot_count`, lane states | range ≤ 366 days |
| `meetings.context.read` | `meeting_ids[]`, `lookback_days?`, `per_meeting_limit?` | `meetings[]` as section 15 | ≤ 10 meetings; lookback ≤ 90 |

Cursors are opaque, grant-bound and keyed on the section 14 order (precedent: S3 grant-bound cursors). Unknown or foreign ids are `not_found`, indistinguishably. Ingestion, source admission and backfill are operator CLI commands, not capabilities.

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
4. **Rebuild** (new search-text or extractor version): an operator CLI command re-derives from the source pointer; if the publication file is gone or its SHA-256 differs, the stored projection stays and the message is flagged `source_unavailable`.
5. **Identity conflict across publications** → section 3; operator-visible in run counts; resolution is a later operator tool, never automatic.
6. **Collector regression** (a lane `failed`, `partial` coverage, a schema major bump) → coverage reports the gap or the rejection; nothing is inferred.

## 19. Deployment and monitoring (WP3 onward; operator-gated)

- One additive migration per WP that needs one; downgrade refuses while rows exist.
- Switches, all default off: `MY_PA_COMMUNICATIONS_ENABLED` (reads), `MY_PA_COMMUNICATIONS_INGEST_ENABLED` (the poll step).
- **Scheduler:** the poll step runs inside `apps/worker.py run --plane cycles` (#367: `run_cycle_scheduler` loop, `pg_try_advisory_lock` single flight) with its own lock key and interval (default 15 minutes), not a new plane, process or cron.
- **Monitoring:** per run, counts by outcome; per source, freshness seconds, open gaps, rejected snapshots, quarantined records, identity conflicts; log lines carry codes and counts only. A runbook under `ops/runbooks/` is written in WP3.
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

Implemented on branch with these tests (FAST unit, contract and database tiers). Migration from empty and from the preceding head; binding uniqueness; moved occurrence keeps identity; cancelled occurrence; series resolution; no title/time matching; reconciliation call CAS and idempotency; synthetic calendar fixtures only.

### 20.3 WP3

Lifecycle idempotency (same SHA-256 twice writes once); re-publication and alias paths; stability rule; record totals reconcile per snapshot; cross-publication identity conflict quarantines and does not rewrite; append-only triggers; partition guard; backfill resume; dry run writes nothing; the Manager's isolated-database real-corpus run reproduces section 20.1's figures; the scheduler step's single flight.

### 20.4 WP4

FTS and identifier query correctness (`RFI 17` ≠ `RFI 174`), ranking total order and cursor exactness, collapse, withheld bodies never returned, bounds and refusals, policy closure for the new names and purpose, recall on a labelled synthetic set for each identifier kind.

### 20.5 WP5

Batch context over synthetic Meetings with and without bindings, attendee joins, coverage gaps stated, PULSE absent → `unavailable` with communications intact, response bounds, measured latency for 10 Meetings on the real-corpus-sized isolated database.

### 20.6 Consolidated activation (goal acceptance; Manager ruling R-OP-7)

There is **one** consolidated activation, at the end of the goal, not one per WP. One runbook and **one operator command** apply, in order:

1. the migrations of every merged WP (WP2's `6418b57081c3` and the later heads);
2. the grants: every comms and meeting-context capability (`meetings.provider.bind`, `communications.*`, the meetings context batch, `project_reports.*`) to the **operator profile only**, with purpose defaults, so the connected client needs no per-call grant prompts (R-OP-2); nothing goes to a non-operator principal;
3. the ChatLLM profile `chatllm-data-v15` (or the version current at that time; R-OP-4);
4. the schedulers (the cycles-plane poll steps of section 19; calendar sync still waits for the batch reconciliation of section 12.7).

The classifier blocks an agent's compose up, so the operator runs that command (or the Manager, where it is permitted). Goal acceptance includes a successful run of it. WP3 onward writes the runbook under `ops/runbooks/`.

## 21. Manager rulings 2026-11-21

The Manager ruled on the open items of this spec and ADR-022 after WP1. They were Manager rulings, not operator ratification, while ADR-022 was Proposed. ADR-022 is now accepted under operator delegation 2026-11-22 (R-OP-1, effective on merge of WP2); the operator gates in ADR-022 "Implementation status" and section 17 are settled as recorded there and in section 20.6.

| ID | Item | Ruling | Where |
| --- | --- | --- | --- |
| R1 | The worker reads the `mcp` workspace through the files store as an ingestion source | Ratified by the Manager, subject to the ADR-019 decision 7 preflight in WP3 | section 1.1 |
| R2 | The 2 rich publications outside the canonical folder | Admitted to backfill as explicitly registered sources; overlap deduplicates by identity | sections 10, 11 |
| R3 | Text-search configuration | `english` FTS plus the exact-identifier index plus `strpos` confirmation accepted for now; WP4 must measure `english` against `simple` on synthetic and aggregate data and may switch | section 6 |
| R4 | Capability names, the `communications_read` purpose, the default-off switches | Accepted as proposals. Grants, external-model eligibility and ADR-022 acceptance were then settled under operator delegation 2026-11-22 (R-OP-1 to R-OP-3) | sections 16, 17, 19 |
| R5 | `comms_identifiers_v1` recall (change orders 0 against 104, `fpl` 134 against 263, `submittal` 28 against 128 as ruled; `submittal` 31 measured at `184ac6ca`) | Recorded as an **open WP4 defect**, to be fixed with tests; does not block WP1 | sections 7, 20.4 |
| — | WP2 meeting-sync source | Deferred to WP2's investigation; then ruled by the Manager during WP2 as D1 | sections 12.3, 12.5 |
| — | The `Disclaimer` and "received this … in error" disclaimer markers are still unanchored | **Open WP4 item**; not fixed in WP1 | section 6 |

**WP2 rulings.** The Manager's WP2 rulings of 2026-11-21 — D1 to D12 and resolution rule 7 (publication ordering, fix F1) — are recorded in [section 12.5](#125-manager-rulings-2026-11-21-for-wp2-ratified-under-operator-delegation-2026-11-22), with the WP2 open items, limitation and residual risk in section 12.6 and the WP3 reconcile-before-sync constraint in section 12.7. They are ratified under operator delegation 2026-11-22.
