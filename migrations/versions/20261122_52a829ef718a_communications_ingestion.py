"""Communications ingestion: the shared lifecycle and the communications tables (WP3a).

Revision ID: 52a829ef718a
Revises: 6418b57081c3
Create Date: 2026-11-22

The one additive revision of communications intelligence WP3a, on the sole head
`6418b57081c3`. It creates twelve Principal-partitioned tables in `knowledge`
and touches nothing that existed before it. In order it:

1. sets `lock_timeout` to 10 s for this revision's transaction only
   (`SET LOCAL`), so a lock that cannot be taken aborts the whole revision with
   `55P03` and leaves the database at `6418b57081c3`;
2. creates the consumer-neutral ingestion lifecycle (contract sections 1.2 and
   1.3, Manager rulings M3, M4, m3, m8, m9):
   * `ingest_sources` -- one admitted source; the consumer is one of the three
     closed names (M4), `admitted_by` is always `operator_cli` (m8, no audit
     row), and only `enabled` is mutable;
   * `ingest_snapshots` -- one distinct file content per source, keyed by
     `(principal_id, ingest_source_id, file_sha256)`; `status` is `pending`,
     `ingested` or `rejected`, and a pending snapshot is finalized exactly once
     to a terminal status (with its `rejection_code` and `parser_version`), after
     which the row is immutable. "Superseded" is not a snapshot status: it is
     derived per path (M3);
   * `ingest_snapshot_paths` -- every relative path a snapshot was seen at (the
     alias of contract section 1.3); only `superseded_by_snapshot_id` and
     `superseded_at` may change, together, and only from NULL (M3). At most one
     path row per `(source, relative_path)` is not superseded;
   * `ingest_runs` -- one run of one source; `finished_at`, `outcome` and the
     `counts` object are set together, once, from NULL;
   * `ingest_run_snapshots` -- the snapshots a run touched, each with its
     per-snapshot outcome (append-only, m9);
   * `ingest_coverage_windows` -- one declared window per ingested snapshot, the
     end inclusive, with the coverage state and the per-lane states as a JSONB
     array (m4; append-only);
3. creates the communications tables (contract sections 5.1 and 5.2 as amended
   by rulings m1, m2, M6, M7):
   * `communication_messages` -- one canonical message per `(principal_id,
     mailbox_ref, identity_kind, identity_value)`. The source pointer of its
     text is `(text_snapshot_id, text_record_ordinal)` (m1); the `body_*`
     projection is taken from that same observation (m2). Only the projection
     columns (the `search_text` group, the text pointer, the four `body_*`
     columns), `latest_snapshot_id` and the three flags are mutable;
     `search_document` is the generated English document (FTS ruling);
   * `communication_mailbox_items` -- one provider id per mailbox, attached to
     its message, never rekeyed (M6; append-only);
   * `communication_observations` -- one row per usable record ordinal of a
     snapshot, its classification (an exact repeat is `duplicate_observation`),
     lane, times, digests and the normalized participant addresses as JSONB
     (append-only);
   * `communication_participants` -- canonical participants per message with
     the observation that first contributed each (M7; append-only);
   * `communication_identifiers` -- technical identifiers per message and
     extractor version (append-only);
   * `communication_quarantine` -- one row per quarantined record ordinal with
     its closed reason codes (append-only);
4. creates the indexes: GIN over `search_document`, the time-ordered keyset and
   conversation indexes, the participant-address and identifier indexes, and
   the foreign-key lookups. There is no trigram index (ruling M1);
5. creates the guards: one named-mutable-column trigger per table that has
   mutable columns, one shared append-only refusal, and `TRUNCATE` refusal on
   all twelve tables (the `c8e4a1b70d35` precedent).

Every foreign key is composite with `principal_id` and `ON DELETE RESTRICT`. A
row keyed by a source also carries `ingest_source_id`, so a path, a run link and
a coverage window can only name a snapshot (and a run) of their own source. No
column holds a raw body, raw HTML or a display name (ADR-022 decision 10):
`search_text` is the derived, bounded projection of contract section 6.

Every bound is a frozen literal and this revision imports nothing from the live
domain. No `GRANT`, no `REVOKE`, no backfill.

`downgrade` locks all twelve tables `ACCESS EXCLUSIVE` and refuses with
`restrict_violation`, deleting nothing, while any of them holds a row; otherwise
it drops exactly what `upgrade` created, in reverse order.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "52a829ef718a"
down_revision: str | None = "6418b57081c3"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_LOCK_TIMEOUT: Final = "SET LOCAL lock_timeout = '10s'"

# ---- step 2: the ingestion lifecycle -------------------------------------------

_SOURCES_DDL: Final = """
    CREATE TABLE knowledge.ingest_sources (
      ingest_source_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      consumer TEXT NOT NULL,
      workspace_id TEXT NOT NULL,
      path_prefix TEXT NOT NULL,
      file_pattern TEXT NOT NULL,
      enabled BOOLEAN NOT NULL,
      admitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
      admitted_by TEXT NOT NULL,
      PRIMARY KEY (ingest_source_id),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT an_ingest_source_consumer_is_known CHECK (consumer IN
          ('communications_evidence_v2', 'meeting_sync_v1', 'pulse_csv_export')),
      CONSTRAINT an_ingest_source_workspace_is_an_alias CHECK (workspace_id ~
          '^[a-z][a-z0-9_]{0,63}$'),
      CONSTRAINT an_ingest_source_path_prefix_is_relative_and_bounded CHECK
          (length(path_prefix) <= 1024 AND path_prefix NOT LIKE '/%' AND path_prefix !~
          '(^|/)\\.\\.(/|$)'),
      CONSTRAINT an_ingest_source_file_pattern_is_one_bounded_name CHECK
          (length(file_pattern) BETWEEN 1 AND 256 AND strpos(file_pattern, '/') = 0),
      CONSTRAINT an_ingest_source_is_admitted_by_the_operator_cli CHECK (admitted_by =
          'operator_cli'),
      CONSTRAINT one_ingest_source_per_location UNIQUE (principal_id, consumer,
          workspace_id, path_prefix, file_pattern),
      CONSTRAINT an_ingest_source_is_identified_within_its_principal UNIQUE
          (ingest_source_id, principal_id)
    )
    """

_SNAPSHOTS_DDL: Final = """
    CREATE TABLE knowledge.ingest_snapshots (
      snapshot_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      file_sha256 TEXT NOT NULL,
      byte_count BIGINT NOT NULL,
      observed_version_token TEXT,
      first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
      status TEXT NOT NULL,
      rejection_code TEXT,
      parser_version TEXT,
      PRIMARY KEY (snapshot_id),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT an_ingest_snapshot_digest_is_sha256 CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT an_ingest_snapshot_byte_count_is_non_negative CHECK (byte_count >= 0),
      CONSTRAINT an_ingest_snapshot_version_token_is_bounded CHECK (observed_version_token
          IS NULL OR length(observed_version_token) BETWEEN 1 AND 256),
      CONSTRAINT an_ingest_snapshot_status_is_known CHECK (status IN ('ingested',
          'pending', 'rejected')),
      CONSTRAINT an_ingest_snapshot_rejection_code_is_a_token CHECK (rejection_code IS
          NULL OR rejection_code ~ '^[a-z][a-z0-9_]{0,63}$'),
      CONSTRAINT an_ingest_snapshot_parser_version_is_a_token CHECK (parser_version IS NULL
          OR parser_version ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
      CONSTRAINT a_rejected_ingest_snapshot_names_its_code CHECK ((status = 'rejected') =
          (rejection_code IS NOT NULL)),
      CONSTRAINT a_pending_ingest_snapshot_names_no_parser CHECK (status <> 'pending' OR
          parser_version IS NULL),
      CONSTRAINT an_ingested_snapshot_names_its_parser CHECK (status <> 'ingested' OR
          parser_version IS NOT NULL),
      CONSTRAINT one_ingest_snapshot_per_source_content UNIQUE (principal_id,
          ingest_source_id, file_sha256),
      CONSTRAINT an_ingest_snapshot_is_identified_within_its_principal UNIQUE
          (snapshot_id, principal_id),
      CONSTRAINT an_ingest_snapshot_is_identified_within_its_source UNIQUE (snapshot_id,
          principal_id, ingest_source_id),
      CONSTRAINT an_ingest_snapshot_names_a_source_of_its_principal FOREIGN
          KEY(ingest_source_id, principal_id) REFERENCES knowledge.ingest_sources
          (ingest_source_id, principal_id) ON DELETE RESTRICT
    )
    """

_PATHS_DDL: Final = """
    CREATE TABLE knowledge.ingest_snapshot_paths (
      principal_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      relative_path TEXT NOT NULL,
      first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
      superseded_by_snapshot_id TEXT,
      superseded_at TIMESTAMP WITH TIME ZONE,
      CONSTRAINT ingest_snapshot_paths_pkey PRIMARY KEY (principal_id, snapshot_id,
          relative_path),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT superseded_by_snapshot_id_is_an_opaque_identifier CHECK
          (superseded_by_snapshot_id ~ '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT an_ingest_snapshot_path_is_relative_and_bounded CHECK
          (length(relative_path) BETWEEN 1 AND 1024 AND relative_path NOT LIKE '/%' AND
          relative_path !~ '(^|/)\\.\\.(/|$)'),
      CONSTRAINT an_ingest_snapshot_path_supersession_is_whole CHECK
          ((superseded_by_snapshot_id IS NULL) = (superseded_at IS NULL)),
      CONSTRAINT an_ingest_snapshot_path_is_not_superseded_by_itself CHECK
          (superseded_by_snapshot_id IS NULL OR superseded_by_snapshot_id <> snapshot_id),
      CONSTRAINT an_ingest_snapshot_path_names_a_snapshot_of_its_source FOREIGN
          KEY(snapshot_id, principal_id, ingest_source_id) REFERENCES
          knowledge.ingest_snapshots (snapshot_id, principal_id, ingest_source_id) ON
          DELETE RESTRICT,
      CONSTRAINT an_ingest_snapshot_path_is_superseded_by_its_sources_snapshot FOREIGN
          KEY(superseded_by_snapshot_id, principal_id, ingest_source_id) REFERENCES
          knowledge.ingest_snapshots (snapshot_id, principal_id, ingest_source_id) ON
          DELETE RESTRICT
    )
    """

_RUNS_DDL: Final = """
    CREATE TABLE knowledge.ingest_runs (
      run_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      trigger TEXT NOT NULL,
      started_at TIMESTAMP WITH TIME ZONE NOT NULL,
      finished_at TIMESTAMP WITH TIME ZONE,
      outcome TEXT,
      counts JSONB,
      PRIMARY KEY (run_id),
      CONSTRAINT run_id_is_an_opaque_identifier CHECK (run_id ~ '^irun_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT an_ingest_run_trigger_is_known CHECK (trigger IN ('backfill', 'operator',
          'schedule')),
      CONSTRAINT an_ingest_run_outcome_is_known CHECK (outcome IS NULL OR outcome IN
          ('completed', 'failed', 'partial')),
      CONSTRAINT an_ingest_run_finish_is_whole CHECK ((finished_at IS NULL) = (outcome IS
          NULL) AND (outcome IS NULL) = (counts IS NULL)),
      CONSTRAINT an_ingest_run_finishes_after_it_starts CHECK (finished_at IS NULL OR
          finished_at >= started_at),
      CONSTRAINT an_ingest_run_counts_is_an_object CHECK (counts IS NULL OR
          jsonb_typeof(counts) = 'object'),
      CONSTRAINT an_ingest_run_is_identified_within_its_source UNIQUE (run_id,
          principal_id, ingest_source_id),
      CONSTRAINT an_ingest_run_names_a_source_of_its_principal FOREIGN
          KEY(ingest_source_id, principal_id) REFERENCES knowledge.ingest_sources
          (ingest_source_id, principal_id) ON DELETE RESTRICT
    )
    """

_RUN_SNAPSHOTS_DDL: Final = """
    CREATE TABLE knowledge.ingest_run_snapshots (
      principal_id TEXT NOT NULL,
      run_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      outcome TEXT NOT NULL,
      recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
      CONSTRAINT ingest_run_snapshots_pkey PRIMARY KEY (principal_id, run_id, snapshot_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT run_id_is_an_opaque_identifier CHECK (run_id ~ '^irun_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT an_ingest_run_snapshot_outcome_is_known CHECK (outcome IN
          ('already_known', 'failed', 'ingested', 'rejected')),
      CONSTRAINT an_ingest_run_snapshot_names_a_run_of_its_source FOREIGN KEY(run_id,
          principal_id, ingest_source_id) REFERENCES knowledge.ingest_runs (run_id,
          principal_id, ingest_source_id) ON DELETE RESTRICT,
      CONSTRAINT an_ingest_run_snapshot_names_a_snapshot_of_its_source FOREIGN
          KEY(snapshot_id, principal_id, ingest_source_id) REFERENCES
          knowledge.ingest_snapshots (snapshot_id, principal_id, ingest_source_id) ON
          DELETE RESTRICT
    )
    """

_COVERAGE_DDL: Final = """
    CREATE TABLE knowledge.ingest_coverage_windows (
      coverage_window_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      start_utc TIMESTAMP WITH TIME ZONE NOT NULL,
      end_utc TIMESTAMP WITH TIME ZONE NOT NULL,
      coverage_state TEXT NOT NULL,
      lane_states JSONB NOT NULL,
      recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
      PRIMARY KEY (coverage_window_id),
      CONSTRAINT coverage_window_id_is_an_opaque_identifier CHECK (coverage_window_id ~
          '^icov_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT an_ingest_coverage_window_ends_at_or_after_its_start CHECK (end_utc >=
          start_utc),
      CONSTRAINT an_ingest_coverage_state_is_known CHECK (coverage_state IN ('complete',
          'failed', 'not_authorized', 'partial', 'unknown')),
      CONSTRAINT an_ingest_coverage_lane_states_is_an_array CHECK (jsonb_typeof(lane_states)
          = 'array'),
      CONSTRAINT one_ingest_coverage_window_per_snapshot UNIQUE (principal_id, snapshot_id),
      CONSTRAINT an_ingest_coverage_window_names_a_snapshot_of_its_source FOREIGN
          KEY(snapshot_id, principal_id, ingest_source_id) REFERENCES
          knowledge.ingest_snapshots (snapshot_id, principal_id, ingest_source_id) ON
          DELETE RESTRICT
    )
    """

# ---- step 3: the communications tables -----------------------------------------

#: The generated English search document (FTS ruling): the subject weighted `A`,
#: the derived search text `B`. Both configurations are constant `regconfig`
#: literals, so the expression is immutable and can be stored.
_SEARCH_DOCUMENT: Final = (
    "setweight(to_tsvector('english'::regconfig, coalesce(subject, '')), 'A') || "
    "setweight(to_tsvector('english'::regconfig, coalesce(search_text, '')), 'B')"
)

#: Not an f-string: the regex quantifiers `{8,64}` must reach the server verbatim.
_MESSAGES_DDL: Final = """
    CREATE TABLE knowledge.communication_messages (
      message_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      mailbox_ref TEXT NOT NULL,
      identity_kind TEXT NOT NULL,
      identity_value TEXT NOT NULL,
      conversation_id TEXT,
      subject TEXT,
      sender_address TEXT,
      message_time TIMESTAMP WITH TIME ZONE NOT NULL,
      message_time_basis TEXT NOT NULL,
      has_attachments BOOLEAN,
      body_state TEXT NOT NULL,
      body_sha256 TEXT NOT NULL,
      body_utf8_bytes BIGINT NOT NULL,
      content_type TEXT NOT NULL,
      search_text TEXT,
      search_text_sha256 TEXT,
      search_text_version TEXT NOT NULL,
      search_text_basis TEXT NOT NULL,
      search_text_flags TEXT[] NOT NULL,
      text_snapshot_id TEXT NOT NULL,
      text_record_ordinal INTEGER NOT NULL,
      first_snapshot_id TEXT NOT NULL,
      latest_snapshot_id TEXT NOT NULL,
      identity_conflict BOOLEAN DEFAULT false NOT NULL,
      participants_reconciled BOOLEAN DEFAULT false NOT NULL,
      participants_disagreed BOOLEAN DEFAULT false NOT NULL,
      search_document TSVECTOR GENERATED ALWAYS AS (__SEARCH_DOCUMENT__) STORED,
      PRIMARY KEY (message_id),
      CONSTRAINT message_id_is_an_opaque_identifier CHECK (message_id ~
          '^cmsg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT text_snapshot_id_is_an_opaque_identifier CHECK (text_snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT first_snapshot_id_is_an_opaque_identifier CHECK (first_snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT latest_snapshot_id_is_an_opaque_identifier CHECK (latest_snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_communication_mailbox_ref_is_bounded CHECK (length(mailbox_ref) BETWEEN
          1 AND 320),
      CONSTRAINT a_communication_identity_kind_is_known CHECK (identity_kind IN
          ('provider_id_only', 'provider_returned')),
      CONSTRAINT a_communication_identity_value_is_bounded CHECK (length(identity_value)
          BETWEEN 1 AND 2048),
      CONSTRAINT a_communication_conversation_id_is_bounded CHECK (conversation_id IS NULL
          OR length(conversation_id) BETWEEN 1 AND 2048),
      CONSTRAINT a_communication_subject_is_bounded CHECK (subject IS NULL OR
          length(subject) <= 16384),
      CONSTRAINT a_communication_sender_is_a_normalized_address CHECK (sender_address IS
          NULL OR (length(sender_address) BETWEEN 1 AND 320 AND sender_address =
          lower(sender_address))),
      CONSTRAINT a_communication_message_time_basis_is_known CHECK (message_time_basis IN
          ('received', 'selected_fallback', 'sent')),
      CONSTRAINT a_communication_body_state_is_known CHECK (body_state IN ('empty',
          'present', 'truncated', 'withheld')),
      CONSTRAINT a_communication_body_digest_is_sha256 CHECK (body_sha256 ~
          '^[0-9a-f]{64}$'),
      CONSTRAINT a_communication_body_byte_count_is_non_negative CHECK (body_utf8_bytes >=
          0),
      CONSTRAINT a_communication_content_type_is_known CHECK (content_type IN ('html',
          'text')),
      CONSTRAINT a_communication_search_text_is_bounded CHECK (search_text IS NULL OR
          length(search_text) <= 262144),
      CONSTRAINT a_communication_search_text_digest_is_sha256 CHECK (search_text_sha256 IS
          NULL OR search_text_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT a_communication_search_text_has_its_digest CHECK ((search_text IS NULL) =
          (search_text_sha256 IS NULL)),
      CONSTRAINT a_communication_search_text_version_is_a_token CHECK (search_text_version
          ~ '^[a-z][a-z0-9_]{0,63}$'),
      CONSTRAINT a_communication_search_text_basis_is_known CHECK (search_text_basis IN
          ('body_content', 'none', 'producer_derived_text', 'unique_body')),
      CONSTRAINT a_communication_search_text_without_basis_is_null CHECK
          ((search_text_basis = 'none') = (search_text IS NULL)),
      CONSTRAINT a_communication_search_text_flag_is_known CHECK (search_text_flags <@
          ARRAY['disclaimer_removed', 'empty', 'markup_dropped', 'metadata_only',
          'quoted_chain_removed', 'quoted_chain_retained', 'text_capped', 'truncated',
          'withheld']),
      CONSTRAINT a_withheld_or_truncated_body_has_no_search_text CHECK (search_text IS NULL
          OR body_state NOT IN ('truncated', 'withheld')),
      CONSTRAINT a_communication_text_ordinal_is_non_negative CHECK (text_record_ordinal >=
          0),
      CONSTRAINT one_communication_message_per_identity UNIQUE (principal_id, mailbox_ref,
          identity_kind, identity_value),
      CONSTRAINT a_communication_message_is_identified_within_its_principal UNIQUE
          (message_id, principal_id),
      CONSTRAINT a_communication_message_is_identified_within_its_mailbox UNIQUE
          (message_id, principal_id, mailbox_ref),
      CONSTRAINT a_communication_text_names_a_snapshot_of_its_principal FOREIGN
          KEY(text_snapshot_id, principal_id) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id) ON DELETE RESTRICT,
      CONSTRAINT a_communication_first_snapshot_is_of_its_principal FOREIGN
          KEY(first_snapshot_id, principal_id) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id) ON DELETE RESTRICT,
      CONSTRAINT a_communication_latest_snapshot_is_of_its_principal FOREIGN
          KEY(latest_snapshot_id, principal_id) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id) ON DELETE RESTRICT
    )
    """.replace("__SEARCH_DOCUMENT__", _SEARCH_DOCUMENT)

_ITEMS_DDL: Final = """
    CREATE TABLE knowledge.communication_mailbox_items (
      item_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      message_id TEXT NOT NULL,
      mailbox_ref TEXT NOT NULL,
      provider_id TEXT NOT NULL,
      provider_id_format TEXT NOT NULL,
      first_snapshot_id TEXT NOT NULL,
      PRIMARY KEY (item_id),
      CONSTRAINT item_id_is_an_opaque_identifier CHECK (item_id ~
          '^cmitm_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT message_id_is_an_opaque_identifier CHECK (message_id ~
          '^cmsg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT first_snapshot_id_is_an_opaque_identifier CHECK (first_snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_mailbox_item_mailbox_ref_is_bounded CHECK (length(mailbox_ref) BETWEEN 1
          AND 320),
      CONSTRAINT a_mailbox_item_provider_id_is_bounded CHECK (length(provider_id) BETWEEN 1
          AND 2048),
      CONSTRAINT a_mailbox_item_provider_id_format_is_known CHECK (provider_id_format IN
          ('immutable_verified', 'mutable', 'unknown')),
      CONSTRAINT one_mailbox_item_per_provider_id UNIQUE (principal_id, mailbox_ref,
          provider_id),
      CONSTRAINT a_mailbox_item_is_identified_within_its_principal UNIQUE (item_id,
          principal_id),
      CONSTRAINT a_mailbox_item_names_a_message_of_its_mailbox FOREIGN KEY(message_id,
          principal_id, mailbox_ref) REFERENCES knowledge.communication_messages
          (message_id, principal_id, mailbox_ref) ON DELETE RESTRICT,
      CONSTRAINT a_mailbox_item_first_snapshot_is_of_its_principal FOREIGN
          KEY(first_snapshot_id, principal_id) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id) ON DELETE RESTRICT
    )
    """

_OBSERVATIONS_DDL: Final = """
    CREATE TABLE knowledge.communication_observations (
      observation_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      record_ordinal INTEGER NOT NULL,
      classification TEXT NOT NULL,
      reasons TEXT[] NOT NULL,
      folder_role TEXT NOT NULL,
      lane_verification TEXT NOT NULL,
      selected_field TEXT NOT NULL,
      selected_utc TIMESTAMP WITH TIME ZONE NOT NULL,
      received_utc TIMESTAMP WITH TIME ZONE,
      received_state TEXT NOT NULL,
      sent_utc TIMESTAMP WITH TIME ZONE,
      sent_state TEXT NOT NULL,
      body_sha256 TEXT NOT NULL,
      unique_body_sha256 TEXT,
      participants JSONB NOT NULL,
      PRIMARY KEY (observation_id),
      CONSTRAINT observation_id_is_an_opaque_identifier CHECK (observation_id ~
          '^cobs_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT item_id_is_an_opaque_identifier CHECK (item_id ~
          '^cmitm_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_communication_observation_ordinal_is_non_negative CHECK (record_ordinal
          >= 0),
      CONSTRAINT a_communication_observation_classification_is_known CHECK (classification
          IN ('accepted', 'accepted_degraded', 'duplicate_observation',
          'lane_observation_merged', 'out_of_window')),
      CONSTRAINT a_communication_observation_reason_is_a_degradation CHECK (reasons <@
          ARRAY['body_truncated', 'conversation_id_absent', 'derived_text_invalid',
          'fetch_error_reported', 'identity_provider_id_only', 'identity_state_inconsistent',
          'in_window_disagreement', 'lane_identity_inconsistent', 'participant_entry_invalid',
          'participant_from_absent', 'privacy_withheld_content_present',
          'raw_timestamp_unparseable', 'selected_timestamp_inconsistent', 'subject_empty',
          'unknown_body_completeness', 'unknown_folder_role', 'unknown_id_format',
          'unknown_participant_state']),
      CONSTRAINT a_communication_observation_folder_role_is_known CHECK (folder_role IN
          ('inbox', 'other', 'sent')),
      CONSTRAINT a_communication_observation_lane_verification_is_known CHECK
          (lane_verification IN ('unverified_lane_claim', 'verified')),
      CONSTRAINT a_communication_observation_selected_field_is_known CHECK (selected_field
          IN ('received', 'sent')),
      CONSTRAINT a_communication_observation_received_state_is_known CHECK (received_state
          IN ('absent', 'present', 'unparseable')),
      CONSTRAINT a_communication_observation_sent_state_is_known CHECK (sent_state IN
          ('absent', 'present', 'unparseable')),
      CONSTRAINT a_communication_observation_received_time_matches_its_state CHECK
          ((received_state = 'present') = (received_utc IS NOT NULL)),
      CONSTRAINT a_communication_observation_sent_time_matches_its_state CHECK
          ((sent_state = 'present') = (sent_utc IS NOT NULL)),
      CONSTRAINT a_communication_observation_body_digest_is_sha256 CHECK (body_sha256 ~
          '^[0-9a-f]{64}$'),
      CONSTRAINT a_communication_observation_unique_body_digest_is_sha256 CHECK
          (unique_body_sha256 IS NULL OR unique_body_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT a_communication_observation_participants_is_an_object CHECK
          (jsonb_typeof(participants) = 'object'),
      CONSTRAINT one_communication_observation_per_record UNIQUE (principal_id,
          snapshot_id, record_ordinal),
      CONSTRAINT a_communication_observation_is_identified_within_its_principal UNIQUE
          (observation_id, principal_id),
      CONSTRAINT a_communication_observation_names_an_item_of_its_principal FOREIGN
          KEY(item_id, principal_id) REFERENCES knowledge.communication_mailbox_items
          (item_id, principal_id) ON DELETE RESTRICT,
      CONSTRAINT a_communication_observation_names_a_snapshot_of_its_principal FOREIGN
          KEY(snapshot_id, principal_id) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id) ON DELETE RESTRICT
    )
    """

_PARTICIPANTS_DDL: Final = """
    CREATE TABLE knowledge.communication_participants (
      principal_id TEXT NOT NULL,
      message_id TEXT NOT NULL,
      field TEXT NOT NULL,
      address TEXT NOT NULL,
      first_observation_id TEXT NOT NULL,
      CONSTRAINT communication_participants_pkey PRIMARY KEY (principal_id, message_id,
          field, address),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT message_id_is_an_opaque_identifier CHECK (message_id ~
          '^cmsg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT first_observation_id_is_an_opaque_identifier CHECK (first_observation_id
          ~ '^cobs_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_communication_participant_field_is_known CHECK (field IN ('bcc', 'cc',
          'from', 'reply_to', 'sender', 'to')),
      CONSTRAINT a_communication_participant_is_a_normalized_address CHECK (length(address)
          BETWEEN 1 AND 320 AND address = lower(address)),
      CONSTRAINT a_communication_participant_names_a_message_of_its_principal FOREIGN
          KEY(message_id, principal_id) REFERENCES knowledge.communication_messages
          (message_id, principal_id) ON DELETE RESTRICT,
      CONSTRAINT a_communication_participant_names_an_observation_of_its_owner FOREIGN
          KEY(first_observation_id, principal_id) REFERENCES
          knowledge.communication_observations (observation_id, principal_id) ON DELETE
          RESTRICT
    )
    """

_IDENTIFIERS_DDL: Final = """
    CREATE TABLE knowledge.communication_identifiers (
      principal_id TEXT NOT NULL,
      message_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      value TEXT NOT NULL,
      extractor_version TEXT NOT NULL,
      CONSTRAINT communication_identifiers_pkey PRIMARY KEY (principal_id, message_id,
          kind, value, extractor_version),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT message_id_is_an_opaque_identifier CHECK (message_id ~
          '^cmsg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_communication_identifier_kind_is_known CHECK (kind IN ('cb', 'co',
          'fpl', 'gmp', 'rfi', 'spec', 'submittal')),
      CONSTRAINT a_communication_identifier_value_is_bounded CHECK (length(value) BETWEEN 1
          AND 256),
      CONSTRAINT a_communication_identifier_extractor_version_is_a_token CHECK
          (extractor_version ~ '^[a-z][a-z0-9_]{0,63}$'),
      CONSTRAINT a_communication_identifier_names_a_message_of_its_principal FOREIGN
          KEY(message_id, principal_id) REFERENCES knowledge.communication_messages
          (message_id, principal_id) ON DELETE RESTRICT
    )
    """

_QUARANTINE_DDL: Final = """
    CREATE TABLE knowledge.communication_quarantine (
      quarantine_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      record_ordinal INTEGER NOT NULL,
      reasons TEXT[] NOT NULL,
      PRIMARY KEY (quarantine_id),
      CONSTRAINT quarantine_id_is_an_opaque_identifier CHECK (quarantine_id ~
          '^cqrn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_communication_quarantine_ordinal_is_non_negative CHECK (record_ordinal
          >= 0),
      CONSTRAINT a_communication_quarantine_names_a_reason CHECK (cardinality(reasons) >=
          1),
      CONSTRAINT a_communication_quarantine_reason_is_known CHECK (reasons <@
          ARRAY['body_content_missing', 'body_truncated', 'conversation_id_absent',
          'derived_text_invalid', 'fetch_error_reported', 'identity_conflict',
          'identity_kind_mismatch', 'identity_provider_id_only', 'identity_state_inconsistent',
          'in_window_disagreement', 'integrity_mismatch', 'invalid_field_type',
          'invalid_field_value', 'lane_identity_inconsistent', 'mailbox_ref_mismatch',
          'missing_required_field', 'participant_entry_invalid', 'participant_from_absent',
          'privacy_withheld_content_present', 'provider_id_conflict',
          'provider_id_fields_disagree', 'raw_timestamp_unparseable',
          'record_not_an_object', 'selected_timestamp_inconsistent', 'subject_empty',
          'unknown_body_completeness', 'unknown_folder_role', 'unknown_id_format',
          'unknown_participant_state', 'unparseable_timestamp']),
      CONSTRAINT one_communication_quarantine_per_record UNIQUE (principal_id, snapshot_id,
          record_ordinal),
      CONSTRAINT a_communication_quarantine_names_a_snapshot_of_its_principal FOREIGN
          KEY(snapshot_id, principal_id) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id) ON DELETE RESTRICT
    )
    """

#: Parent before child: `upgrade` creates in this order, `downgrade` drops in reverse.
_TABLES: Final = (
    ("ingest_sources", _SOURCES_DDL),
    ("ingest_snapshots", _SNAPSHOTS_DDL),
    ("ingest_snapshot_paths", _PATHS_DDL),
    ("ingest_runs", _RUNS_DDL),
    ("ingest_run_snapshots", _RUN_SNAPSHOTS_DDL),
    ("ingest_coverage_windows", _COVERAGE_DDL),
    ("communication_messages", _MESSAGES_DDL),
    ("communication_mailbox_items", _ITEMS_DDL),
    ("communication_observations", _OBSERVATIONS_DDL),
    ("communication_participants", _PARTICIPANTS_DDL),
    ("communication_identifiers", _IDENTIFIERS_DDL),
    ("communication_quarantine", _QUARANTINE_DDL),
)

# ---- step 4: the indexes -------------------------------------------------------

_INDEXES: Final = (
    (
        "one_current_ingest_snapshot_per_path",
        """
        CREATE UNIQUE INDEX one_current_ingest_snapshot_per_path ON
          knowledge.ingest_snapshot_paths (principal_id, ingest_source_id, relative_path)
          WHERE superseded_by_snapshot_id IS NULL
        """,
    ),
    (
        "ingest_snapshot_paths_by_source",
        """
        CREATE INDEX ingest_snapshot_paths_by_source ON knowledge.ingest_snapshot_paths
          (principal_id, ingest_source_id, relative_path)
        """,
    ),
    (
        "ingest_runs_by_source",
        """
        CREATE INDEX ingest_runs_by_source ON knowledge.ingest_runs (principal_id,
          ingest_source_id, started_at DESC)
        """,
    ),
    (
        "ingest_run_snapshots_by_snapshot",
        """
        CREATE INDEX ingest_run_snapshots_by_snapshot ON knowledge.ingest_run_snapshots
          (principal_id, snapshot_id)
        """,
    ),
    (
        "ingest_coverage_windows_by_source",
        """
        CREATE INDEX ingest_coverage_windows_by_source ON knowledge.ingest_coverage_windows
          (principal_id, ingest_source_id, start_utc)
        """,
    ),
    (
        "communication_messages_search_document",
        """
        CREATE INDEX communication_messages_search_document ON
          knowledge.communication_messages USING gin (search_document)
        """,
    ),
    (
        "communication_messages_by_time",
        """
        CREATE INDEX communication_messages_by_time ON knowledge.communication_messages
          (principal_id, message_time DESC, message_id)
        """,
    ),
    (
        "communication_messages_by_conversation",
        """
        CREATE INDEX communication_messages_by_conversation ON
          knowledge.communication_messages (principal_id, conversation_id, message_time)
        """,
    ),
    (
        "communication_mailbox_items_by_message",
        """
        CREATE INDEX communication_mailbox_items_by_message ON
          knowledge.communication_mailbox_items (principal_id, message_id)
        """,
    ),
    (
        "communication_observations_by_item",
        """
        CREATE INDEX communication_observations_by_item ON
          knowledge.communication_observations (principal_id, item_id)
        """,
    ),
    (
        "communication_participants_by_address",
        """
        CREATE INDEX communication_participants_by_address ON
          knowledge.communication_participants (principal_id, address, message_id)
        """,
    ),
    (
        "communication_identifiers_by_value",
        """
        CREATE INDEX communication_identifiers_by_value ON
          knowledge.communication_identifiers (principal_id, kind, value)
        """,
    ),
)

# ---- step 5: the guards --------------------------------------------------------


def _named_mutable(table: str, function: str, trigger: str, rule: str) -> str:
    """One BEFORE UPDATE OR DELETE guard: DELETE is refused, `rule` judges UPDATE."""
    return f"""
    CREATE FUNCTION {SCHEMA}.{function}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '{table} rows are never deleted'
          USING ERRCODE = 'restrict_violation';
      END IF;
{rule}
      RETURN NEW;
    END; $$;
    CREATE TRIGGER {trigger}
      BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
      FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{function}()
    """


def _only(table: str, mutable: tuple[str, ...]) -> str:
    """Refuse an UPDATE that changes any column outside `mutable`.

    The row is compared as JSONB minus the mutable keys, so a column added to the
    table later is immutable without editing this guard.
    """
    keys = ", ".join(f"'{name}'" for name in mutable)
    return f"""      IF (to_jsonb(NEW) - ARRAY[{keys}]::text[])
         IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[{keys}]::text[]) THEN
        RAISE EXCEPTION '{table} changes only its named mutable columns'
          USING ERRCODE = 'restrict_violation';
      END IF;"""


_SOURCE_RULE: Final = _only("ingest_sources", ("enabled",))

#: Pending to a terminal status, exactly once; then the row is frozen.
_SNAPSHOT_RULE: Final = """      IF OLD.status <> 'pending' THEN
        RAISE EXCEPTION 'ingest_snapshots row is terminal and immutable'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF NEW.status NOT IN ('ingested', 'rejected') THEN
        RAISE EXCEPTION 'ingest_snapshots row is finalized to a terminal status'
          USING ERRCODE = 'restrict_violation';
      END IF;
""" + _only("ingest_snapshots", ("status", "rejection_code", "parser_version"))

#: Superseded once, from NULL, and never again (M3).
_PATH_RULE: Final = """      IF OLD.superseded_by_snapshot_id IS NOT NULL
         OR OLD.superseded_at IS NOT NULL THEN
        RAISE EXCEPTION 'ingest_snapshot_paths row is already superseded'
          USING ERRCODE = 'restrict_violation';
      END IF;
""" + _only("ingest_snapshot_paths", ("superseded_by_snapshot_id", "superseded_at"))

#: Finished once, from NULL; the CHECK makes the three columns move together.
_RUN_RULE: Final = """      IF OLD.finished_at IS NOT NULL
         OR OLD.outcome IS NOT NULL
         OR OLD.counts IS NOT NULL THEN
        RAISE EXCEPTION 'ingest_runs row is already finished'
          USING ERRCODE = 'restrict_violation';
      END IF;
""" + _only("ingest_runs", ("finished_at", "outcome", "counts"))

#: The projection columns (contract section 5.1 as amended by m1 and m2). The
#: generated `search_document` is listed because a BEFORE trigger sees it before
#: it is recomputed; it follows `subject` and `search_text` and cannot be written.
_MESSAGE_MUTABLE: Final = (
    "search_text",
    "search_text_sha256",
    "search_text_version",
    "search_text_basis",
    "search_text_flags",
    "text_snapshot_id",
    "text_record_ordinal",
    "body_state",
    "body_sha256",
    "body_utf8_bytes",
    "content_type",
    "latest_snapshot_id",
    "identity_conflict",
    "participants_reconciled",
    "participants_disagreed",
    "search_document",
)
_MESSAGE_RULE: Final = _only("communication_messages", _MESSAGE_MUTABLE)

#: `(table, function, trigger, rule)` for every table with named mutable columns.
_MUTABLE_GUARDS: Final = (
    (
        "ingest_sources",
        "ingest_sources_change_only_enabled",
        "ingest_sources_change_only_enabled",
        _SOURCE_RULE,
    ),
    (
        "ingest_snapshots",
        "ingest_snapshots_finalize_once",
        "ingest_snapshots_finalize_once",
        _SNAPSHOT_RULE,
    ),
    (
        "ingest_snapshot_paths",
        "ingest_snapshot_paths_supersede_once",
        "ingest_snapshot_paths_supersede_once",
        _PATH_RULE,
    ),
    (
        "ingest_runs",
        "ingest_runs_finish_once",
        "ingest_runs_finish_once",
        _RUN_RULE,
    ),
    (
        "communication_messages",
        "communication_messages_change_only_their_projection",
        "communication_messages_change_only_their_projection",
        _MESSAGE_RULE,
    ),
)

_APPEND_ONLY_FUNCTION: Final = "communications_ingestion_rows_are_append_only"
_APPEND_ONLY_TABLES: Final = (
    "ingest_run_snapshots",
    "ingest_coverage_windows",
    "communication_mailbox_items",
    "communication_observations",
    "communication_participants",
    "communication_identifiers",
    "communication_quarantine",
)

_APPEND_ONLY: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
    END; $$
    """

_TRUNCATE_FUNCTION: Final = "communications_ingestion_refuses_truncate"

_TRUNCATE: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% refuses %', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
      RETURN NULL;
    END; $$
    """

#: `downgrade` locks every table before it checks them, so no row can commit
#: between the refusal check and the drops.
_LOCK_TABLES: Final = (
    "LOCK TABLE knowledge.ingest_sources, knowledge.ingest_snapshots, "
    "knowledge.ingest_snapshot_paths, knowledge.ingest_runs, knowledge.ingest_run_snapshots, "
    "knowledge.ingest_coverage_windows, knowledge.communication_messages, "
    "knowledge.communication_mailbox_items, knowledge.communication_observations, "
    "knowledge.communication_participants, knowledge.communication_identifiers, "
    "knowledge.communication_quarantine IN ACCESS EXCLUSIVE MODE"
)

#: `downgrade` refuses while any table holds a row rather than deleting
#: ingested evidence to make the downgrade pass (the `7d9a450dfd07` precedent).
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM knowledge.ingest_sources)
         OR EXISTS (SELECT 1 FROM knowledge.ingest_snapshots)
         OR EXISTS (SELECT 1 FROM knowledge.ingest_snapshot_paths)
         OR EXISTS (SELECT 1 FROM knowledge.ingest_runs)
         OR EXISTS (SELECT 1 FROM knowledge.ingest_run_snapshots)
         OR EXISTS (SELECT 1 FROM knowledge.ingest_coverage_windows)
         OR EXISTS (SELECT 1 FROM knowledge.communication_messages)
         OR EXISTS (SELECT 1 FROM knowledge.communication_mailbox_items)
         OR EXISTS (SELECT 1 FROM knowledge.communication_observations)
         OR EXISTS (SELECT 1 FROM knowledge.communication_participants)
         OR EXISTS (SELECT 1 FROM knowledge.communication_identifiers)
         OR EXISTS (SELECT 1 FROM knowledge.communication_quarantine) THEN
        RAISE EXCEPTION 'communications ingestion rows exist; refusing to downgrade 52a829ef718a'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    for _table, ddl in _TABLES:
        op.execute(ddl)
    for _name, ddl in _INDEXES:
        op.execute(ddl)
    for table, function, trigger, rule in _MUTABLE_GUARDS:
        op.execute(_named_mutable(table, function, trigger, rule))
    op.execute(_APPEND_ONLY)
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_are_append_only
              BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
              FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}()
            """
        )
    op.execute(_TRUNCATE)
    for table, _ddl in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_refuse_truncate
              BEFORE TRUNCATE ON {SCHEMA}.{table}
              FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}()
            """
        )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLES)
    op.execute(_REFUSE_DOWNGRADE)
    for table, _ddl in reversed(_TABLES):
        op.execute(f"DROP TRIGGER {table}_refuse_truncate ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}()")
    for table in reversed(_APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER {table}_are_append_only ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}()")
    for table, function, trigger, _rule in reversed(_MUTABLE_GUARDS):
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}")
        op.execute(f"DROP FUNCTION {SCHEMA}.{function}()")
    for name, _ddl in reversed(_INDEXES):
        op.execute(f"DROP INDEX {SCHEMA}.{name}")
    for table, _ddl in reversed(_TABLES):
        op.execute(f"DROP TABLE {SCHEMA}.{table} RESTRICT")
