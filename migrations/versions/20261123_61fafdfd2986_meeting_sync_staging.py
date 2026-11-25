"""Meeting sync staging and reconciliation (communications intelligence WP3b-S1).

Revision ID: 61fafdfd2986
Revises: 52a829ef718a
Create Date: 2026-11-23

The one additive revision of communications intelligence WP3b, on the sole head
`52a829ef718a` (Manager rulings D1, D3, D4, D5, D8, D9 and D10). In order it:

1. sets `lock_timeout` to 10 s for this revision's transaction only
   (`SET LOCAL`), so a lock that cannot be taken aborts the whole revision with
   `55P03` and leaves the database at `52a829ef718a`; then takes every lock
   the revision needs up front, in one fixed order (the downgrade's order for
   the tables both lock): `ACCESS EXCLUSIVE` on `meeting_provider_bindings`,
   `ingest_snapshots` and `audit_events` (each is altered), then `SHARE ROW
   EXCLUSIVE` on `meetings` and `meeting_history` (the new tables' foreign keys
   reference them), so no lock is upgraded or added mid-revision;
2. refuses, with `restrict_violation` and before changing anything, while any
   `meeting_provider_bindings` row records a `last_seen_*` observation: such a
   row could not name the snapshot it came from (D10). No sync has run before
   this revision, so on every database it is meant for the check passes;
3. creates five Principal-partitioned tables in `knowledge`:
   * `meeting_sync_publications` -- one staged `meeting_sync_v1` snapshot
     (D1, stage-then-apply), keyed by `(principal_id, snapshot_id)`, naming its
     snapshot through `(snapshot_id, principal_id, ingest_source_id)`; its
     declared coverage is all-or-none (D7); `applied_at`, `apply_outcome`
     (`applied`, `skipped_stale`, `skipped_ordering_conflict`, D8) and
     `apply_counts` change together, once, from NULL;
   * `meeting_sync_events` -- one staged accepted event record (`msevt_`), its
     provider key and the provider-owned fields of ruling D2, never an attendee
     or a body; append-only;
   * `meeting_provider_review_marks` -- a Meeting explicitly marked as having
     no provider event (D3); append-only;
   * `meeting_provider_reconciliation_passes` -- the one-way reconciliation
     latch, one row per Principal (D4); append-only;
   * `meeting_provider_key_tombstones` -- the provider key of a binding the
     unbind deleted (D5), keyed by that binding's id, naming its Meeting and
     the unbind's history receipt; append-only;
4. adds `an_ingest_snapshot_is_identified_with_its_digest`, UNIQUE
   `(snapshot_id, principal_id, file_sha256)`, on `ingest_snapshots`;
5. alters `meeting_provider_bindings` (D10): `origin_snapshot_id` (the snapshot
   whose record created the binding; NULL after an explicit bind; immutable,
   by its own trigger) and `last_seen_snapshot_id` (present exactly when
   `last_seen_source_sha256` is), each an `isnp_` identifier, with composite
   foreign keys `(last_seen_snapshot_id, principal_id, last_seen_source_sha256)`
   and `(origin_snapshot_id, principal_id)` onto `ingest_snapshots`, so a
   binding's recorded digest is the digest of the snapshot it names;
6. creates the guards: the publication's apply-once trigger, one shared
   append-only refusal on the other four tables, `TRUNCATE` refusal on all
   five (the `c8e4a1b70d35` precedent) and the binding origin trigger;
7. restates `audit_events.capability_is_known` (the `_restate` precedent: `DROP
   CONSTRAINT` then `ADD CONSTRAINT ... CHECK`, `ACCESS EXCLUSIVE` on the live
   `audit_events`, held to commit) with the frozen sorted set of 312 names: the
   310 `6418b57081c3` left plus exactly `meetings.provider.reconcile` and
   `meetings.provider.review` (D9: both capabilities are audited by the normal
   invoke). `purpose_is_known` is unchanged: they map to the existing
   `meeting_read` and `meeting_authoring`. The two names are admitted ahead of
   the domain, which declares them in WP3b-S4. A system sync writes no audit
   row (D9). `meeting_write_requests` is unchanged.

Every bound is a frozen literal and this revision imports nothing from the live
domain. No `GRANT`, no `REVOKE`, no backfill.

`downgrade` locks the five tables, `meeting_provider_bindings`,
`ingest_snapshots` and `audit_events` `ACCESS EXCLUSIVE` and refuses with
`restrict_violation`, deleting nothing, while any of the five tables holds a
row, any binding names a snapshot, or any audit event names either new
capability; otherwise it restores the byte copy of the `6418b57081c3` audit set
and drops exactly what `upgrade` created, in reverse order.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "61fafdfd2986"
down_revision: str | None = "52a829ef718a"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_LOCK_TIMEOUT: Final = "SET LOCAL lock_timeout = '10s'"

# ---- step 2: the legacy-observation refusal -------------------------------------

_BINDINGS: Final = "meeting_provider_bindings"

#: Every lock the upgrade needs, taken first and in one fixed order -- the
#: downgrade's order for the tables both lock -- so the revision never upgrades
#: or adds a lock after it began changing things (a deadlock or a long wait
#: mid-DDL). The altered tables take the `ACCESS EXCLUSIVE` their ALTERs take
#: anyway (`meeting_provider_bindings`: columns, checks, foreign keys and the
#: origin trigger; `ingest_snapshots`: the digest key, then the referenced side
#: of the new foreign keys; `audit_events`: the restated CHECK); taking the
#: bindings lock before the legacy-observation check also means no observation
#: can commit between the check and the ALTER. The new tables' foreign keys
#: reference `meetings` and `meeting_history`, which need `SHARE ROW EXCLUSIVE`.
_LOCK_ALTERED: Final = (
    "LOCK TABLE knowledge.meeting_provider_bindings, knowledge.ingest_snapshots, "
    "knowledge.audit_events IN ACCESS EXCLUSIVE MODE"
)
_LOCK_REFERENCED: Final = (
    "LOCK TABLE knowledge.meetings, knowledge.meeting_history IN SHARE ROW EXCLUSIVE MODE"
)

_REFUSE_LEGACY_OBSERVATIONS: Final = """
    DO $$
    BEGIN
      IF EXISTS (
           SELECT 1 FROM knowledge.meeting_provider_bindings
            WHERE last_seen_source_sha256 IS NOT NULL) THEN
        RAISE EXCEPTION 'legacy binding observations exist; refusing to upgrade to 61fafdfd2986'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """

# ---- step 3: the tables ---------------------------------------------------------

#: Not f-strings: the regex quantifiers `{8,64}` must reach the server verbatim.
_PUBLICATIONS_DDL: Final = """
    CREATE TABLE knowledge.meeting_sync_publications (
      principal_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      generated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL,
      coverage_start_utc TIMESTAMP WITH TIME ZONE,
      coverage_end_utc TIMESTAMP WITH TIME ZONE,
      coverage_calendar_refs TEXT[],
      record_count INTEGER NOT NULL,
      accepted_count INTEGER NOT NULL,
      quarantined_count INTEGER NOT NULL,
      staged_at TIMESTAMP WITH TIME ZONE NOT NULL,
      applied_at TIMESTAMP WITH TIME ZONE,
      apply_outcome TEXT,
      apply_counts JSONB,
      CONSTRAINT meeting_sync_publications_pkey PRIMARY KEY (principal_id, snapshot_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_meeting_sync_publication_coverage_is_whole CHECK ((coverage_start_utc IS
          NULL) = (coverage_end_utc IS NULL) AND (coverage_start_utc IS NULL) =
          (coverage_calendar_refs IS NULL)),
      CONSTRAINT a_meeting_sync_publication_coverage_ends_after_it_starts CHECK
          (coverage_end_utc IS NULL OR coverage_end_utc >= coverage_start_utc),
      CONSTRAINT a_meeting_sync_publication_coverage_names_its_calendars CHECK
          (coverage_calendar_refs IS NULL OR (cardinality(coverage_calendar_refs) BETWEEN 1
          AND 100 AND array_position(coverage_calendar_refs, NULL) IS NULL)),
      CONSTRAINT a_meeting_sync_publication_count_is_non_negative CHECK (record_count >= 0
          AND accepted_count >= 0 AND quarantined_count >= 0),
      CONSTRAINT a_meeting_sync_publication_counts_reconcile CHECK (accepted_count +
          quarantined_count = record_count),
      CONSTRAINT a_meeting_sync_publication_apply_is_whole CHECK ((applied_at IS NULL) =
          (apply_outcome IS NULL) AND (apply_outcome IS NULL) = (apply_counts IS NULL)),
      CONSTRAINT a_meeting_sync_publication_apply_outcome_is_known CHECK (apply_outcome IS
          NULL OR apply_outcome IN ('applied', 'skipped_ordering_conflict', 'skipped_stale')),
      CONSTRAINT a_meeting_sync_publication_apply_counts_is_an_object CHECK (apply_counts IS
          NULL OR jsonb_typeof(apply_counts) = 'object'),
      CONSTRAINT a_meeting_sync_publication_names_a_snapshot_of_its_source FOREIGN
          KEY(snapshot_id, principal_id, ingest_source_id) REFERENCES
          knowledge.ingest_snapshots (snapshot_id, principal_id, ingest_source_id) ON
          DELETE RESTRICT
    )
    """

_EVENTS_DDL: Final = """
    CREATE TABLE knowledge.meeting_sync_events (
      event_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      record_ordinal INTEGER NOT NULL,
      calendar_ref TEXT NOT NULL,
      ical_uid TEXT NOT NULL,
      series_ical_uid TEXT,
      occurrence_original_start_utc TIMESTAMP WITH TIME ZONE,
      start_utc TIMESTAMP WITH TIME ZONE NOT NULL,
      end_utc TIMESTAMP WITH TIME ZONE NOT NULL,
      timezone_name TEXT NOT NULL,
      status TEXT NOT NULL,
      title TEXT NOT NULL,
      location_text TEXT,
      virtual_meeting_url TEXT,
      provider_event_id TEXT,
      provider_event_id_format TEXT NOT NULL,
      staged_at TIMESTAMP WITH TIME ZONE NOT NULL,
      PRIMARY KEY (event_id),
      CONSTRAINT event_id_is_an_opaque_identifier CHECK (event_id ~
          '^msevt_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_meeting_sync_event_ordinal_is_non_negative CHECK (record_ordinal >= 0),
      CONSTRAINT a_meeting_sync_event_calendar_ref_is_bounded CHECK (length(calendar_ref)
          BETWEEN 1 AND 320),
      CONSTRAINT a_meeting_sync_event_uid_is_bounded CHECK (length(ical_uid) BETWEEN 1 AND
          1024),
      CONSTRAINT a_meeting_sync_event_series_uid_is_bounded CHECK (series_ical_uid IS NULL OR
          length(series_ical_uid) BETWEEN 1 AND 1024),
      CONSTRAINT a_meeting_sync_event_names_its_series_and_original_start CHECK
          ((series_ical_uid IS NULL) = (occurrence_original_start_utc IS NULL)),
      CONSTRAINT a_meeting_sync_event_does_not_end_before_it_starts CHECK (end_utc >=
          start_utc),
      CONSTRAINT a_meeting_sync_event_timezone_name_is_bounded CHECK (length(timezone_name)
          BETWEEN 1 AND 64 AND length(trim(timezone_name)) > 0),
      CONSTRAINT a_meeting_sync_event_status_is_known CHECK (status IN ('cancelled',
          'confirmed', 'tentative')),
      CONSTRAINT a_meeting_sync_event_title_is_bounded CHECK (length(title) BETWEEN 1 AND
          200 AND length(trim(title)) > 0),
      CONSTRAINT a_meeting_sync_event_location_is_bounded CHECK (location_text IS NULL OR
          length(location_text) <= 500),
      CONSTRAINT a_meeting_sync_event_virtual_url_is_bounded CHECK (virtual_meeting_url IS
          NULL OR length(virtual_meeting_url) BETWEEN 1 AND 2048),
      CONSTRAINT a_meeting_sync_event_provider_event_id_is_bounded CHECK (provider_event_id
          IS NULL OR length(provider_event_id) BETWEEN 1 AND 1024),
      CONSTRAINT a_meeting_sync_event_provider_event_id_format_is_known CHECK
          (provider_event_id_format IN ('immutable_verified', 'mutable', 'unknown')),
      CONSTRAINT one_meeting_sync_event_per_record UNIQUE (principal_id, snapshot_id,
          record_ordinal),
      CONSTRAINT a_meeting_sync_event_names_a_publication_of_its_principal FOREIGN
          KEY(principal_id, snapshot_id) REFERENCES knowledge.meeting_sync_publications
          (principal_id, snapshot_id) ON DELETE RESTRICT
    )
    """

_MARKS_DDL: Final = """
    CREATE TABLE knowledge.meeting_provider_review_marks (
      principal_id TEXT NOT NULL,
      meeting_id TEXT NOT NULL,
      marked_at TIMESTAMP WITH TIME ZONE NOT NULL,
      CONSTRAINT meeting_provider_review_marks_pkey PRIMARY KEY (principal_id, meeting_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT meeting_id_is_an_opaque_identifier CHECK (meeting_id ~
          '^mtg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_review_mark_names_a_meeting_of_its_principal FOREIGN KEY(meeting_id,
          principal_id) REFERENCES knowledge.meetings (meeting_id, principal_id) ON DELETE
          RESTRICT
    )
    """

_PASSES_DDL: Final = """
    CREATE TABLE knowledge.meeting_provider_reconciliation_passes (
      principal_id TEXT NOT NULL,
      completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
      reviewed_meetings INTEGER NOT NULL,
      reconcile_correlation_id TEXT NOT NULL,
      PRIMARY KEY (principal_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT reconcile_correlation_id_is_an_opaque_identifier CHECK
          (reconcile_correlation_id ~ '^corr_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_reconciliation_pass_count_is_non_negative CHECK (reviewed_meetings >= 0)
    )
    """

_TOMBSTONES_DDL: Final = """
    CREATE TABLE knowledge.meeting_provider_key_tombstones (
      principal_id TEXT NOT NULL,
      binding_id TEXT NOT NULL,
      meeting_id TEXT NOT NULL,
      calendar_ref TEXT NOT NULL,
      ical_uid TEXT NOT NULL,
      occurrence_original_start_utc TIMESTAMP WITH TIME ZONE,
      series_ical_uid TEXT,
      unbound_at TIMESTAMP WITH TIME ZONE NOT NULL,
      meeting_history_id TEXT NOT NULL,
      CONSTRAINT meeting_provider_key_tombstones_pkey PRIMARY KEY (principal_id, binding_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT binding_id_is_an_opaque_identifier CHECK (binding_id ~
          '^mpbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT meeting_id_is_an_opaque_identifier CHECK (meeting_id ~
          '^mtg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT meeting_history_id_is_an_opaque_identifier CHECK (meeting_history_id ~
          '^mhst_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_key_tombstone_calendar_ref_is_bounded CHECK (length(calendar_ref) BETWEEN
          1 AND 320),
      CONSTRAINT a_key_tombstone_uid_is_bounded CHECK (length(ical_uid) BETWEEN 1 AND 1024),
      CONSTRAINT a_key_tombstone_series_uid_is_bounded CHECK (series_ical_uid IS NULL OR
          length(series_ical_uid) BETWEEN 1 AND 1024),
      CONSTRAINT a_key_tombstone_names_its_series_and_original_start CHECK ((series_ical_uid
          IS NULL) = (occurrence_original_start_utc IS NULL)),
      CONSTRAINT a_key_tombstone_names_a_meeting_of_its_principal FOREIGN KEY(meeting_id,
          principal_id) REFERENCES knowledge.meetings (meeting_id, principal_id) ON DELETE
          RESTRICT,
      CONSTRAINT a_key_tombstone_names_a_receipt_of_its_meeting FOREIGN
          KEY(meeting_history_id, meeting_id, principal_id) REFERENCES
          knowledge.meeting_history (history_id, meeting_id, principal_id) ON DELETE
          RESTRICT
    )
    """

#: `(table, DDL)` in creation order, parent before child.
_TABLES: Final = (
    ("meeting_sync_publications", _PUBLICATIONS_DDL),
    ("meeting_sync_events", _EVENTS_DDL),
    ("meeting_provider_review_marks", _MARKS_DDL),
    ("meeting_provider_reconciliation_passes", _PASSES_DDL),
    ("meeting_provider_key_tombstones", _TOMBSTONES_DDL),
)

_INDEXES: Final = (
    (
        "meeting_sync_publications_by_source",
        """
        CREATE INDEX meeting_sync_publications_by_source ON
          knowledge.meeting_sync_publications (principal_id, ingest_source_id,
          generated_at_utc)
        """,
    ),
    (
        "meeting_sync_events_by_key",
        """
        CREATE INDEX meeting_sync_events_by_key ON knowledge.meeting_sync_events
          (principal_id, calendar_ref, ical_uid, occurrence_original_start_utc)
        """,
    ),
    (
        "meeting_provider_key_tombstones_by_key",
        """
        CREATE INDEX meeting_provider_key_tombstones_by_key ON
          knowledge.meeting_provider_key_tombstones (principal_id, calendar_ref, ical_uid,
          occurrence_original_start_utc)
        """,
    ),
)

# ---- steps 4 and 5: the snapshot digest key and the binding snapshot columns ----

_SNAPSHOT_DIGEST_UNIQUE: Final = "an_ingest_snapshot_is_identified_with_its_digest"

_BINDING_COLUMNS: Final = ("origin_snapshot_id", "last_seen_snapshot_id")

#: `(name, expression)` of the binding CHECKs, in creation order.
_BINDING_CHECKS: Final = (
    (
        "origin_snapshot_id_is_an_opaque_identifier",
        "origin_snapshot_id ~ '^isnp_[A-Za-z0-9]{8,64}$'",
    ),
    (
        "last_seen_snapshot_id_is_an_opaque_identifier",
        "last_seen_snapshot_id ~ '^isnp_[A-Za-z0-9]{8,64}$'",
    ),
    (
        "a_provider_binding_last_seen_names_its_snapshot",
        "(last_seen_snapshot_id IS NULL) = (last_seen_source_sha256 IS NULL)",
    ),
)

#: `(name, local columns, remote columns)` of the binding foreign keys onto
#: `ingest_snapshots`, `ON DELETE RESTRICT`, in creation order.
_BINDING_FOREIGN_KEYS: Final = (
    (
        "a_provider_binding_last_seen_names_a_snapshot_of_its_digest",
        ["last_seen_snapshot_id", "principal_id", "last_seen_source_sha256"],
        ["snapshot_id", "principal_id", "file_sha256"],
    ),
    (
        "a_provider_binding_origin_names_a_snapshot_of_its_principal",
        ["origin_snapshot_id", "principal_id"],
        ["snapshot_id", "principal_id"],
    ),
)

# ---- step 6: the guards ---------------------------------------------------------

_PUBLICATION_FUNCTION: Final = "meeting_sync_publications_apply_once"
_PUBLICATION_TRIGGER: Final = "meeting_sync_publications_apply_once"

#: DELETE is refused; an UPDATE only sets the three apply columns, once, from
#: NULL (the CHECK makes them move together). The row is compared as JSONB minus
#: those keys, so a column added later is immutable without editing this guard.
_PUBLICATION_GUARD: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_PUBLICATION_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'meeting_sync_publications rows are never deleted'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF OLD.applied_at IS NOT NULL
         OR OLD.apply_outcome IS NOT NULL
         OR OLD.apply_counts IS NOT NULL THEN
        RAISE EXCEPTION 'meeting_sync_publications row is already applied'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF (to_jsonb(NEW) - ARRAY['applied_at', 'apply_outcome', 'apply_counts']::text[])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['applied_at', 'apply_outcome', 'apply_counts']::text[]) THEN
        RAISE EXCEPTION 'meeting_sync_publications changes only its apply columns'
          USING ERRCODE = 'restrict_violation';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER {_PUBLICATION_TRIGGER}
      BEFORE UPDATE OR DELETE ON {SCHEMA}.meeting_sync_publications
      FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_PUBLICATION_FUNCTION}()
    """

_APPEND_ONLY_FUNCTION: Final = "meeting_sync_rows_are_append_only"
_APPEND_ONLY_TABLES: Final = (
    "meeting_sync_events",
    "meeting_provider_review_marks",
    "meeting_provider_reconciliation_passes",
    "meeting_provider_key_tombstones",
)

_APPEND_ONLY: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
    END; $$
    """

_TRUNCATE_FUNCTION: Final = "meeting_sync_refuses_truncate"

_TRUNCATE: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% refuses %', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
      RETURN NULL;
    END; $$
    """

_ORIGIN_FUNCTION: Final = "meeting_provider_bindings_keep_their_origin"
_ORIGIN_TRIGGER: Final = "meeting_provider_binding_origin_is_immutable"

#: A separate trigger rather than an edit of `6418b57081c3`'s identity function,
#: so no historical revision changes.
_ORIGIN: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_ORIGIN_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.origin_snapshot_id IS DISTINCT FROM OLD.origin_snapshot_id THEN
        RAISE EXCEPTION '{_BINDINGS} origin is immutable'
          USING ERRCODE = 'restrict_violation';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER {_ORIGIN_TRIGGER}
      BEFORE UPDATE ON {SCHEMA}.{_BINDINGS}
      FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_ORIGIN_FUNCTION}()
    """

# ---- step 7: the audit vocabulary, frozen ---------------------------------------

#: Byte copy of `6418b57081c3`'s AT set (310 names), the latest prior
#: restatement of `capability_is_known`.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.archive', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.restore', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', 'commitments.read', "
    "'commitments.search', 'commitments.update', 'commitments.v2.list', "
    "'commitments.v2.read', 'commitments.v2.search', 'commitments.v2.waiting_on', "
    "'commitments.waiting_on', 'constraint_categories.create', "
    "'constraint_categories.deactivate', 'constraint_categories.list', "
    "'constraint_categories.reorder', 'constraint_categories.update', "
    "'constraint_sync.acknowledge', 'constraint_sync.apply', 'constraint_sync.conflicts', "
    "'constraint_sync.delta', 'constraint_sync.preview', 'constraint_sync.resolve', "
    "'constraint_sync.state', 'constraints.close', 'constraints.close_follow_up', "
    "'constraints.create', 'constraints.create_published', 'constraints.history', "
    "'constraints.list', 'constraints.overview', 'constraints.portfolio_list', "
    "'constraints.portfolio_overview', 'constraints.portfolio_search', "
    "'constraints.publish', 'constraints.read', 'constraints.reopen', "
    "'constraints.search', 'constraints.transition', 'constraints.update', "
    "'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', "
    "'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', "
    "'entities.assignments.list', 'entities.assignments.revise', "
    "'entities.communication.add', 'entities.communication.list', "
    "'entities.communication.retire', 'entities.communication.revise', 'entities.context', "
    "'entities.create', 'entities.get', 'entities.graph', 'entities.identifiers.bind', "
    "'entities.identifiers.list', 'entities.identifiers.retire', "
    "'entities.identifiers.supersede', 'entities.identity_history', 'entities.merge', "
    "'entities.merge.preview', 'entities.names.add', 'entities.names.list', "
    "'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', "
    "'entities.observe', 'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'files.copy', 'files.download.begin', 'files.history', "
    "'files.list', 'files.mkdir', 'files.move', 'files.preview', 'files.rename', "
    "'files.restore', 'files.search', 'files.stat', 'files.trash', 'files.upload.abort', "
    "'files.upload.begin', 'files.upload.finalize', 'files.workspaces.list', "
    "'files.write_text', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', "
    "'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'issues.close', "
    "'issues.closure_readiness', 'issues.create', 'issues.handoffs.correct', "
    "'issues.handoffs.list', 'issues.handoffs.record', 'issues.history', 'issues.list', "
    "'issues.memberships.add', 'issues.memberships.confirm', 'issues.memberships.correct', "
    "'issues.memberships.end', 'issues.project_links.add', 'issues.project_links.confirm', "
    "'issues.project_links.end', 'issues.read', 'issues.reopen', 'issues.timeline', "
    "'issues.update', 'issues.work.create_commitment', 'issues.work.create_task', "
    "'knowledge.assertions.create', 'knowledge.assertions.history', "
    "'knowledge.assertions.list', 'knowledge.assertions.read', "
    "'knowledge.assertions.reveal', 'knowledge.assertions.search', "
    "'knowledge.assertions.submit', 'knowledge.coverage', "
    "'knowledge.discovery.checkpoint', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'meetings.create', 'meetings.list', "
    "'meetings.notes.read_version', 'meetings.notes.versions', 'meetings.provider.bind', "
    "'meetings.read', 'meetings.search', 'meetings.series.update', 'meetings.update', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'programs.members.resolve', "
    "'programs.overview', 'project_controls.configure', 'project_controls.status', "
    "'record_events.list', 'record_events.provenance', 'records.associations.assert', "
    "'records.associations.confirm', 'records.associations.contest', "
    "'records.associations.correct', 'records.associations.end', "
    "'records.associations.history', 'records.associations.reinstate', "
    "'records.backfill.plan', 'records.backfill.report', 'records.lineage', "
    "'records.lineage.related', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.archive', "
    "'reports.begin_cycle', 'reports.commit', 'reports.delete', 'reports.history', "
    "'reports.hold.place', 'reports.hold.release', 'reports.latest', 'reports.list', "
    "'reports.manifest', 'reports.publish', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.restore', 'reports.retention.get', "
    "'reports.retention.set', 'reports.search', 'reports.transfer.abort', "
    "'reports.transfer.append', 'reports.transfer.begin', 'reports.transfer.finalize', "
    "'reports.transfer.read_chunk', 'reports.types.create', 'reports.types.list', "
    "'reports.update', 'review.decide', 'review.list', 'schedule_activities.history', "
    "'schedule_activities.list', 'schedule_baselines.approve', "
    "'schedule_baselines.compare', 'schedule_baselines.governing', "
    "'schedule_baselines.list', 'schedule_baselines.propose', 'schedule_baselines.read', "
    "'schedule_baselines.reject', 'schedule_baselines.revoke', "
    "'schedule_baselines.set_governing', 'schedule_baselines.withdraw', "
    "'schedule_changes.list', 'schedule_cpm_runs.activities', 'schedule_cpm_runs.create', "
    "'schedule_cpm_runs.read', 'schedule_publications.import', "
    "'schedule_publications.list', 'schedule_publications.read', "
    "'schedule_scenario_outputs.list', 'schedule_scenario_outputs.read', "
    "'schedule_scenario_outputs.record', 'schedule_scenario_versions.activities', "
    "'schedule_scenario_versions.changes', 'schedule_scenario_versions.create', "
    "'schedule_scenario_versions.read', 'schedule_scenario_versions.relationships', "
    "'schedule_scenarios.create', 'schedule_scenarios.list', 'schedule_scenarios.read', "
    "'schedule_series.current', 'schedule_series.list', 'schedule_series.match_decisions', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', "
    "'tasks.comments.create', 'tasks.comments.list', 'tasks.create', 'tasks.history', "
    "'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
)

#: The same set plus exactly `meetings.provider.reconcile` and
#: `meetings.provider.review` -- 312 names, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.archive', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.restore', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', 'commitments.read', "
    "'commitments.search', 'commitments.update', 'commitments.v2.list', "
    "'commitments.v2.read', 'commitments.v2.search', 'commitments.v2.waiting_on', "
    "'commitments.waiting_on', 'constraint_categories.create', "
    "'constraint_categories.deactivate', 'constraint_categories.list', "
    "'constraint_categories.reorder', 'constraint_categories.update', "
    "'constraint_sync.acknowledge', 'constraint_sync.apply', 'constraint_sync.conflicts', "
    "'constraint_sync.delta', 'constraint_sync.preview', 'constraint_sync.resolve', "
    "'constraint_sync.state', 'constraints.close', 'constraints.close_follow_up', "
    "'constraints.create', 'constraints.create_published', 'constraints.history', "
    "'constraints.list', 'constraints.overview', 'constraints.portfolio_list', "
    "'constraints.portfolio_overview', 'constraints.portfolio_search', "
    "'constraints.publish', 'constraints.read', 'constraints.reopen', "
    "'constraints.search', 'constraints.transition', 'constraints.update', "
    "'constraints.void', 'context.feedback', 'context.prepare', 'continuity.projects', "
    "'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', "
    "'entities.assignments.list', 'entities.assignments.revise', "
    "'entities.communication.add', 'entities.communication.list', "
    "'entities.communication.retire', 'entities.communication.revise', "
    "'entities.context', 'entities.create', 'entities.get', 'entities.graph', "
    "'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', "
    "'entities.profile', 'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'files.copy', 'files.download.begin', 'files.history', "
    "'files.list', 'files.mkdir', 'files.move', 'files.preview', 'files.rename', "
    "'files.restore', 'files.search', 'files.stat', 'files.trash', 'files.upload.abort', "
    "'files.upload.begin', 'files.upload.finalize', 'files.workspaces.list', "
    "'files.write_text', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', "
    "'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'issues.close', "
    "'issues.closure_readiness', 'issues.create', 'issues.handoffs.correct', "
    "'issues.handoffs.list', 'issues.handoffs.record', 'issues.history', 'issues.list', "
    "'issues.memberships.add', 'issues.memberships.confirm', "
    "'issues.memberships.correct', 'issues.memberships.end', 'issues.project_links.add', "
    "'issues.project_links.confirm', 'issues.project_links.end', 'issues.read', "
    "'issues.reopen', 'issues.timeline', 'issues.update', "
    "'issues.work.create_commitment', 'issues.work.create_task', "
    "'knowledge.assertions.create', 'knowledge.assertions.history', "
    "'knowledge.assertions.list', 'knowledge.assertions.read', "
    "'knowledge.assertions.reveal', 'knowledge.assertions.search', "
    "'knowledge.assertions.submit', 'knowledge.coverage', "
    "'knowledge.discovery.checkpoint', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'meetings.create', 'meetings.list', "
    "'meetings.notes.read_version', 'meetings.notes.versions', 'meetings.provider.bind', "
    "'meetings.provider.reconcile', 'meetings.provider.review', 'meetings.read', "
    "'meetings.search', 'meetings.series.update', 'meetings.update', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'programs.members.resolve', "
    "'programs.overview', 'project_controls.configure', 'project_controls.status', "
    "'record_events.list', 'record_events.provenance', 'records.associations.assert', "
    "'records.associations.confirm', 'records.associations.contest', "
    "'records.associations.correct', 'records.associations.end', "
    "'records.associations.history', 'records.associations.reinstate', "
    "'records.backfill.plan', 'records.backfill.report', 'records.lineage', "
    "'records.lineage.related', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.archive', "
    "'reports.begin_cycle', 'reports.commit', 'reports.delete', 'reports.history', "
    "'reports.hold.place', 'reports.hold.release', 'reports.latest', 'reports.list', "
    "'reports.manifest', 'reports.publish', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.restore', 'reports.retention.get', "
    "'reports.retention.set', 'reports.search', 'reports.transfer.abort', "
    "'reports.transfer.append', 'reports.transfer.begin', 'reports.transfer.finalize', "
    "'reports.transfer.read_chunk', 'reports.types.create', 'reports.types.list', "
    "'reports.update', 'review.decide', 'review.list', 'schedule_activities.history', "
    "'schedule_activities.list', 'schedule_baselines.approve', "
    "'schedule_baselines.compare', 'schedule_baselines.governing', "
    "'schedule_baselines.list', 'schedule_baselines.propose', 'schedule_baselines.read', "
    "'schedule_baselines.reject', 'schedule_baselines.revoke', "
    "'schedule_baselines.set_governing', 'schedule_baselines.withdraw', "
    "'schedule_changes.list', 'schedule_cpm_runs.activities', 'schedule_cpm_runs.create', "
    "'schedule_cpm_runs.read', 'schedule_publications.import', "
    "'schedule_publications.list', 'schedule_publications.read', "
    "'schedule_scenario_outputs.list', 'schedule_scenario_outputs.read', "
    "'schedule_scenario_outputs.record', 'schedule_scenario_versions.activities', "
    "'schedule_scenario_versions.changes', 'schedule_scenario_versions.create', "
    "'schedule_scenario_versions.read', 'schedule_scenario_versions.relationships', "
    "'schedule_scenarios.create', 'schedule_scenarios.list', 'schedule_scenarios.read', "
    "'schedule_series.current', 'schedule_series.list', "
    "'schedule_series.match_decisions', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', 'tasks.bulk_confirm', "
    "'tasks.bulk_preview', 'tasks.comments.create', 'tasks.comments.list', "
    "'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

#: The two names this revision admits to the audit vocabulary.
_NEW_CAPABILITIES: Final = ("meetings.provider.reconcile", "meetings.provider.review")

# ---- downgrade -------------------------------------------------------------------

#: `downgrade` locks every table it checks or changes before it checks them, so
#: no row can commit between the refusal check and the drops.
_LOCK_TABLES: Final = (
    "LOCK TABLE knowledge.meeting_sync_publications, knowledge.meeting_sync_events, "
    "knowledge.meeting_provider_review_marks, knowledge.meeting_provider_reconciliation_passes, "
    "knowledge.meeting_provider_key_tombstones, knowledge.meeting_provider_bindings, "
    "knowledge.ingest_snapshots, knowledge.audit_events IN ACCESS EXCLUSIVE MODE"
)

#: `downgrade` refuses while any staged or reconciliation row exists, any
#: binding names a snapshot, or any audit event names a new capability, rather
#: than deleting evidence or audit history to make the downgrade pass (the
#: `7d9a450dfd07` precedent). Each clause alone suffices.
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM knowledge.meeting_sync_publications)
         OR EXISTS (SELECT 1 FROM knowledge.meeting_sync_events)
         OR EXISTS (SELECT 1 FROM knowledge.meeting_provider_review_marks)
         OR EXISTS (SELECT 1 FROM knowledge.meeting_provider_reconciliation_passes)
         OR EXISTS (SELECT 1 FROM knowledge.meeting_provider_key_tombstones) THEN
        RAISE EXCEPTION 'meeting sync rows exist; refusing to downgrade 61fafdfd2986'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF EXISTS (
           SELECT 1 FROM knowledge.meeting_provider_bindings
            WHERE origin_snapshot_id IS NOT NULL OR last_seen_snapshot_id IS NOT NULL) THEN
        RAISE EXCEPTION 'provider bindings name a snapshot; refusing to downgrade 61fafdfd2986'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF EXISTS (
           SELECT 1 FROM knowledge.audit_events
            WHERE capability IN ('meetings.provider.reconcile', 'meetings.provider.review')) THEN
        RAISE EXCEPTION 'provider review audit history exists; refusing to downgrade 61fafdfd2986'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """


def _restate(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, schema=SCHEMA, type_="check")
    op.create_check_constraint(name, table, expression, schema=SCHEMA)


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_ALTERED)
    op.execute(_LOCK_REFERENCED)
    op.execute(_REFUSE_LEGACY_OBSERVATIONS)
    for _table, ddl in _TABLES:
        op.execute(ddl)
    for _name, ddl in _INDEXES:
        op.execute(ddl)
    op.create_unique_constraint(
        _SNAPSHOT_DIGEST_UNIQUE,
        "ingest_snapshots",
        ["snapshot_id", "principal_id", "file_sha256"],
        schema=SCHEMA,
    )
    for column in _BINDING_COLUMNS:
        op.execute(f"ALTER TABLE {SCHEMA}.{_BINDINGS} ADD COLUMN {column} TEXT")
    for name, expression in _BINDING_CHECKS:
        op.create_check_constraint(name, _BINDINGS, expression, schema=SCHEMA)
    for name, local, remote in _BINDING_FOREIGN_KEYS:
        op.create_foreign_key(
            name,
            _BINDINGS,
            "ingest_snapshots",
            local,
            remote,
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="RESTRICT",
        )
    op.execute(_PUBLICATION_GUARD)
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
    op.execute(_ORIGIN)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_AT_THIS_REVISION)


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLES)
    op.execute(_REFUSE_DOWNGRADE)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_BEFORE_THIS_REVISION)
    op.execute(f"DROP TRIGGER {_ORIGIN_TRIGGER} ON {SCHEMA}.{_BINDINGS}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_ORIGIN_FUNCTION}()")
    for table, _ddl in reversed(_TABLES):
        op.execute(f"DROP TRIGGER {table}_refuse_truncate ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}()")
    for table in reversed(_APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER {table}_are_append_only ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}()")
    op.execute(f"DROP TRIGGER {_PUBLICATION_TRIGGER} ON {SCHEMA}.meeting_sync_publications")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_PUBLICATION_FUNCTION}()")
    for name, _local, _remote in reversed(_BINDING_FOREIGN_KEYS):
        op.drop_constraint(name, _BINDINGS, schema=SCHEMA, type_="foreignkey")
    for name, _expression in reversed(_BINDING_CHECKS):
        op.drop_constraint(name, _BINDINGS, schema=SCHEMA, type_="check")
    for column in reversed(_BINDING_COLUMNS):
        op.execute(f"ALTER TABLE {SCHEMA}.{_BINDINGS} DROP COLUMN {column} RESTRICT")
    op.drop_constraint(_SNAPSHOT_DIGEST_UNIQUE, "ingest_snapshots", schema=SCHEMA, type_="unique")
    for name, _ddl in reversed(_INDEXES):
        op.execute(f"DROP INDEX {SCHEMA}.{name}")
    for table, _ddl in reversed(_TABLES):
        op.execute(f"DROP TABLE {SCHEMA}.{table} RESTRICT")
