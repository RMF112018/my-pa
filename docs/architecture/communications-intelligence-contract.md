# Communications intelligence — implementation contract

**Status:** proposed implementation contract under [ADR-021](../decisions/ADR-021-communications-intelligence.md) (Proposed — accepted-candidate; not ratified). **WP1 is implemented** on branch `feat/comms-intelligence` (the pure source contract, this spec, the ADR and the corpus evidence); every other section is design for WP2–WP5, which each need their own PR, review and, where marked, operator decision. Nothing is persisted, migrated, exposed, granted or deployed.

**Basis:** contract head measured: branch `feat/comms-intelligence` at `80208caabe92de03be676a93fae8984d31d2b8c1` (tree `057703650c1f7b8976a86ccebc3da0a62f70d1a6`), the WP1 head after fix F2, on `origin/main@092610d36b7d1493fc7fda6e352a4bd06e914f61`; Alembic single head `640aaacc78e8` (129 revision files); 298 `Capability` members and 70 `Purpose` members. PR #368 (ADR-020, meeting prep, migration on `640aaacc78e8`) is open and not on this branch: WP2's migration must chain after whichever head is current when it is written. All counts here are digits on purpose (spelled-count guard). Paths to files that do not exist yet are not written as links (CI relative-link check).

**Corpus evidence:** [`docs/evidence/communications-corpus/`](../evidence/communications-corpus/README.md) (aggregates only, from the sanitized v2 analysis, SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`). Section numbers below are what [`CORPUS-DESIGN-IMPLICATIONS.md`](../evidence/communications-corpus/CORPUS-DESIGN-IMPLICATIONS.md) cites.

## 0. Work packages and implementation state

| WP | Content | State |
| --- | --- | --- |
| WP1 | ADR-021, this spec, 6 corpus deliverables; pure `communications_evidence_v2` contract (parse/validate/normalize both dialects, classification, lane reconciliation, integrity, `comms_search_text_v1`, `comms_identifiers_v1`, corpus coverage summary), aggregate-only CLI, synthetic fixtures, FAST tests | **implemented** (branch, not merged); no migration |
| WP2 | Meeting provider identity and recurrence resolution (section 12): migration, persistence, application, MCP surface, reconciliation, ChatLLM meeting-sync contract | planned |
| WP3 | Shared ingestion lifecycle (section 1) + communications persistence (section 5), ingestion (sections 10–11), coverage (section 9), backfill, scheduled ingestion on the cycles plane, monitoring, runbook | planned |
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

- **Source registry** — `ingest_sources`: one row per admitted source: `source_id`, `principal_id`, `consumer` (closed set: `communications_evidence_v2`, `pulse_csv_export`), `workspace_id`, `path_prefix`, `file_pattern`, `enabled`, `admitted_at`, `admitted_by` (operator channel). Admission is an operator CLI action (ADR-021 decision 15: no client capability).
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
- **Never identity:** producer `dedup_key`, body SHA-256, subject (ADR-021 decision 8).

## 4. Deduplication and observation preservation

### 4.1 Classification (WP1)

`classify_records` assigns, first match wins: `quarantined`; `duplicate_observation` (same provider id, same folder role, same identity and body digest — an exact repeat); `lane_observation_merged` (same provider id in another folder role); `out_of_window` (selected time outside the inclusive window); `accepted_degraded`; `accepted`. Where a rich record declares `in_window` and disagrees, the record degrades (`in_window_disagreement`).

### 4.2 Items and observations (WP1)

`build_items` makes one `MailboxItem` per usable provider id per publication. Its observations are the primary plus every `lane_observation_merged` sibling (an exact repeat adds no evidence). The primary is the sent-lane observation when present, else the lowest ordinal. Participant reconciliation and canonical message time follow ADR-021 decision 7.

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

No raw HTML, body content or display names are stored (ADR-021 decision 10). Display names are deliberately not carried by the WP1 normalized model; resolving a person by name goes through Entities and the address, not through mail text.

### 5.4 Meeting provider bindings (WP2)

Section 12.

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

- **Relation to record lineage (ADR-015).** Communications are not a lineage family in WP3–WP5 (ADR-021 decision 19). No `record_links` row references a message, and no native virtual edge is emitted.
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

## 12. Meeting provider identity and recurrence resolution (designed here; WP2 implements)

Meetings today: `meetings` with nullable `meeting_series_id`, no provider columns; capabilities `meetings.create`, `meetings.list`, `meetings.read`, `meetings.search`, `meetings.update`, `meetings.series.update`, `meetings.notes.versions`, `meetings.notes.read_version`.

### 12.1 Binding table (WP2)

`meeting_provider_bindings`: `binding_id`, `principal_id`, `meeting_id` (FK), `calendar_ref` (neutral calendar reference, like `mailbox_ref`), `ical_uid`, `occurrence_original_start_utc` (null for a single meeting), `provider_event_id` and its format (mutable, attribute only), `series_ical_uid` (the master's UID for an occurrence), `last_seen_snapshot_id`, `provider_state` (`active`, `cancelled`, `not_seen`).

- **Occurrence identity:** `UNIQUE (principal_id, calendar_ref, ical_uid, occurrence_original_start_utc)` — the original start, never the current start, so a moved occurrence keeps its identity.
- **Single meeting:** `UNIQUE (principal_id, calendar_ref, ical_uid)` where `occurrence_original_start_utc IS NULL`.
- **Series:** `meeting_series_provider_bindings (principal_id, meeting_series_id, calendar_ref, series_ical_uid)` unique per Principal; every occurrence binding of that UID resolves to that `meeting_series_id`.

### 12.2 Resolution rules

1. A provider event with a known occurrence key updates the bound Meeting (through the existing `meetings.update` path and its CAS); it never creates a second Meeting.
2. An unknown occurrence of a known series creates a Meeting in that series.
3. An unknown series creates a series binding and a series.
4. An existing unbound Meeting is bound only by an explicit operator or client reconciliation call naming both (`meetings.provider.bind` proposed), never by title or time matching.
5. A cancelled occurrence sets the Meeting status to cancelled; it is never deleted.
6. Provider event ids are mutable attributes; a changed id with the same occurrence key is the same Meeting.

### 12.3 Source

A ChatLLM meeting-sync publication (calendar events with UID, recurrence master UID, original start, attendees with normalized addresses) defined in WP2, ingested on the shared lifecycle as a third consumer, or written by a client through the reconciliation capability — the WP2 decision. **Manager ruling 2026-11-21 (section 21):** this source choice is deferred to WP2's investigation. No calendar data is in the WP1 corpus; WP2 fixtures are synthetic.

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
- **External-model eligibility (operator decision, `AGENTS.md` section 5):** returning mail text to a connected client sends it to that client's model. No grant is issued until the operator records that decision.
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
- Deployment, production migration, grants and source admission stay operator actions.

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

Migration from empty and from the preceding head; binding uniqueness; moved occurrence keeps identity; cancelled occurrence; series resolution; no title/time matching; reconciliation call CAS and idempotency; synthetic calendar fixtures only.

### 20.3 WP3

Lifecycle idempotency (same SHA-256 twice writes once); re-publication and alias paths; stability rule; record totals reconcile per snapshot; cross-publication identity conflict quarantines and does not rewrite; append-only triggers; partition guard; backfill resume; dry run writes nothing; the Manager's isolated-database real-corpus run reproduces section 20.1's figures; the scheduler step's single flight.

### 20.4 WP4

FTS and identifier query correctness (`RFI 17` ≠ `RFI 174`), ranking total order and cursor exactness, collapse, withheld bodies never returned, bounds and refusals, policy closure for the new names and purpose, recall on a labelled synthetic set for each identifier kind.

### 20.5 WP5

Batch context over synthetic Meetings with and without bindings, attendee joins, coverage gaps stated, PULSE absent → `unavailable` with communications intact, response bounds, measured latency for 10 Meetings on the real-corpus-sized isolated database.

## 21. Manager rulings 2026-11-21

The Manager ruled on the open items of this spec and ADR-021 after WP1. These are Manager rulings, not operator ratification: ADR-021 stays **Proposed**, and every operator gate in ADR-021 "Implementation status" and section 17 stands.

| ID | Item | Ruling | Where |
| --- | --- | --- | --- |
| R1 | The worker reads the `mcp` workspace through the files store as an ingestion source | Ratified by the Manager, subject to the ADR-019 decision 7 preflight in WP3 | section 1.1 |
| R2 | The 2 rich publications outside the canonical folder | Admitted to backfill as explicitly registered sources; overlap deduplicates by identity | sections 10, 11 |
| R3 | Text-search configuration | `english` FTS plus the exact-identifier index plus `strpos` confirmation accepted for now; WP4 must measure `english` against `simple` on synthetic and aggregate data and may switch | section 6 |
| R4 | Capability names, the `communications_read` purpose, the default-off switches | Accepted as proposals. Grants, external-model eligibility and ADR-021 acceptance remain operator-gated | sections 16, 17, 19 |
| R5 | `comms_identifiers_v1` recall (change orders 0 against 104, `fpl` 134 against 263, `submittal` 28 against 128 as ruled; `submittal` 31 measured at `184ac6ca`) | Recorded as an **open WP4 defect**, to be fixed with tests; does not block WP1 | sections 7, 20.4 |
| — | WP2 meeting-sync source | Deferred to WP2's investigation | section 12.3 |
| — | The `Disclaimer` and "received this … in error" disclaimer markers are still unanchored | **Open WP4 item**; not fixed in WP1 | section 6 |
