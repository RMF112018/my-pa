"""Meeting provider bindings (communications intelligence WP2, contract section 12.1).

Revision ID: 6418b57081c3
Revises: 4d1069a7d84f
Create Date: 2026-11-21

The one additive revision of WP2, on the sole head `4d1069a7d84f`. In order it:

1. sets `lock_timeout` to 10 s for this revision's transaction only
   (`SET LOCAL`), so a lock that cannot be taken aborts the whole revision with
   `55P03` and leaves the database at `4d1069a7d84f`;
2. creates `knowledge.meeting_series_provider_bindings`: one row binds one
   MeetingSeries to one provider series `(calendar_ref, series_ical_uid)`,
   unique both ways per Principal, partitioned by a composite foreign key onto
   `meeting_series`, `ON DELETE RESTRICT`;
3. creates `knowledge.meeting_provider_bindings`: one row binds one Meeting to
   one provider identity `(calendar_ref, ical_uid, occurrence_original_start_utc)`
   -- the original start, never the current one -- with the provider event id,
   its format, the provider state and the last observation
   (`last_seen_source_sha256`, `last_seen_record_ordinal`, `last_seen_at`, Manager
   ruling D8) and the ordering stamp of the last applied publication
   (`last_applied_generated_at_utc`, NULL until a sync applies one; WP2-F1) as
   mutable attributes. An occurrence names its series UID exactly
   when it names its original start, and the series UID must be bound
   (composite foreign key onto the series bindings). One binding per Meeting
   (D9). Two partial unique indexes key occurrences and single meetings;
4. creates the guards: the occurrence binding identity columns are immutable;
   one `(principal_id, calendar_ref, ical_uid)` is bound as a single meeting or
   as occurrences, never both (D9, serialized by a transaction advisory lock);
   the series bindings are append-only; `TRUNCATE` is refused on both tables
   (the `c8e4a1b70d35` precedent);
5. widens two existing vocabularies, the only statements that name a table
   that existed before this revision (a widening cannot fail on an existing
   row):
   * `meeting_write_requests.a_meeting_write_request_capability_is_known`
     admits the 3 `7d9a450dfd07` names plus exactly the public
     `meetings.provider.bind` (contract section 12.2 rule 4, Manager ruling D10)
     and the internal arbitration namespace `system.meeting_provider.sync` of
     every provider sync write (never a `Capability` member, never invocable),
     each with its own completed-shape CHECK;
   * `audit_events.capability_is_known` is restated (the `_restate_audit`
     precedent: `DROP CONSTRAINT` then `ADD CONSTRAINT ... CHECK`, `ACCESS
     EXCLUSIVE` on the live `audit_events`, held to commit) with the frozen
     sorted set of 310 names: the 309 `640aaacc78e8` left plus exactly
     `meetings.provider.bind`. `purpose_is_known` is unchanged: the capability
     maps to the existing `meeting_authoring`. A sync write writes no audit
     row, so the internal namespace is not an audit name.

`DELETE` of a `meeting_provider_bindings` row stays permitted: the unbind of
`meetings.provider.bind` deletes the occurrence binding and records a
`meeting_history` receipt. A series binding is never deleted while an occurrence
binding names its UID (`ON DELETE RESTRICT`), and never at all (append-only).

Every bound is a frozen literal: the `mpbnd_` and `msbnd_` prefixes, the
calendar reference bound 320, the UID and provider event id bound 1024, the
SHA-256 shape and the closed vocabularies. This revision imports nothing from
the live domain. No `GRANT`, no `REVOKE`, no backfill.

`downgrade` locks both tables, `meeting_write_requests` and `audit_events`
`ACCESS EXCLUSIVE`, refuses with `restrict_violation`, deleting nothing, while
any binding row exists, any write request names either step-5 name, or any
audit event names `meetings.provider.bind`; otherwise it restores the frozen
prior texts (the `7d9a450dfd07` write-request CHECK and a byte copy of the
`640aaacc78e8` AT audit set), drops the two completed-shape CHECKs, and drops
exactly what `upgrade` created, in reverse order.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "6418b57081c3"
down_revision: str | None = "4d1069a7d84f"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_LOCK_TIMEOUT: Final = "SET LOCAL lock_timeout = '10s'"

_SERIES_TABLE: Final = "meeting_series_provider_bindings"
_TABLE: Final = "meeting_provider_bindings"

_SERIES_DDL: Final = """
    CREATE TABLE knowledge.meeting_series_provider_bindings (
      series_binding_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      meeting_series_id TEXT NOT NULL,
      calendar_ref TEXT NOT NULL,
      series_ical_uid TEXT NOT NULL,
      created_at TIMESTAMP WITH TIME ZONE NOT NULL,
      PRIMARY KEY (series_binding_id),
      CONSTRAINT series_binding_id_is_an_opaque_identifier CHECK (series_binding_id ~
          '^msbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT meeting_series_id_is_an_opaque_identifier CHECK (meeting_series_id ~
          '^mser_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_series_provider_binding_calendar_ref_is_bounded CHECK
          (length(calendar_ref) BETWEEN 1 AND 320),
      CONSTRAINT a_series_provider_binding_uid_is_bounded CHECK (length(series_ical_uid)
          BETWEEN 1 AND 1024),
      CONSTRAINT one_series_provider_binding_per_provider_series UNIQUE (principal_id,
          calendar_ref, series_ical_uid),
      CONSTRAINT one_provider_binding_per_meeting_series UNIQUE (principal_id,
          meeting_series_id),
      CONSTRAINT a_series_provider_binding_is_identified_within_its_principal UNIQUE
          (series_binding_id, principal_id),
      CONSTRAINT a_series_provider_binding_names_a_series_of_its_principal FOREIGN
          KEY(meeting_series_id, principal_id) REFERENCES knowledge.meeting_series
          (meeting_series_id, principal_id) ON DELETE RESTRICT
    )
    """

_DDL: Final = """
    CREATE TABLE knowledge.meeting_provider_bindings (
      binding_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      meeting_id TEXT NOT NULL,
      calendar_ref TEXT NOT NULL,
      ical_uid TEXT NOT NULL,
      occurrence_original_start_utc TIMESTAMP WITH TIME ZONE,
      series_ical_uid TEXT,
      provider_event_id TEXT,
      provider_event_id_format TEXT NOT NULL,
      provider_state TEXT DEFAULT 'active' NOT NULL,
      last_seen_source_sha256 TEXT,
      last_seen_record_ordinal INTEGER,
      last_seen_at TIMESTAMP WITH TIME ZONE,
      last_applied_generated_at_utc TIMESTAMP WITH TIME ZONE,
      version INTEGER DEFAULT 1 NOT NULL,
      created_at TIMESTAMP WITH TIME ZONE NOT NULL,
      updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
      PRIMARY KEY (binding_id),
      CONSTRAINT binding_id_is_an_opaque_identifier CHECK (binding_id ~
          '^mpbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT meeting_id_is_an_opaque_identifier CHECK (meeting_id ~
          '^mtg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_provider_binding_calendar_ref_is_bounded CHECK (length(calendar_ref)
          BETWEEN 1 AND 320),
      CONSTRAINT a_provider_binding_uid_is_bounded CHECK (length(ical_uid) BETWEEN 1 AND
          1024),
      CONSTRAINT a_provider_binding_series_uid_is_bounded CHECK (series_ical_uid IS NULL OR
          length(series_ical_uid) BETWEEN 1 AND 1024),
      CONSTRAINT a_provider_event_id_is_bounded CHECK (provider_event_id IS NULL OR
          length(provider_event_id) BETWEEN 1 AND 1024),
      CONSTRAINT a_provider_event_id_format_is_known CHECK (provider_event_id_format IN
          ('immutable_verified', 'mutable', 'unknown')),
      CONSTRAINT a_provider_binding_state_is_known CHECK (provider_state IN ('active',
          'cancelled', 'not_seen')),
      CONSTRAINT an_occurrence_binding_names_its_series_and_original_start CHECK
          ((series_ical_uid IS NULL) = (occurrence_original_start_utc IS NULL)),
      CONSTRAINT a_provider_binding_last_seen_is_whole CHECK ((last_seen_source_sha256 IS
          NULL) = (last_seen_record_ordinal IS NULL) AND (last_seen_source_sha256 IS NULL) =
          (last_seen_at IS NULL)),
      CONSTRAINT a_provider_binding_last_seen_digest_is_sha256 CHECK
          (last_seen_source_sha256 IS NULL OR last_seen_source_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT a_provider_binding_last_seen_ordinal_is_non_negative CHECK
          (last_seen_record_ordinal IS NULL OR last_seen_record_ordinal >= 0),
      CONSTRAINT a_provider_binding_version_is_positive CHECK (version >= 1),
      CONSTRAINT one_provider_binding_per_meeting UNIQUE (principal_id, meeting_id),
      CONSTRAINT a_provider_binding_names_a_meeting_of_its_principal FOREIGN KEY(meeting_id,
          principal_id) REFERENCES knowledge.meetings (meeting_id, principal_id) ON DELETE
          RESTRICT,
      CONSTRAINT an_occurrence_binding_names_a_bound_series FOREIGN KEY(principal_id,
          calendar_ref, series_ical_uid) REFERENCES knowledge.meeting_series_provider_bindings
          (principal_id, calendar_ref, series_ical_uid) ON DELETE RESTRICT
    )
    """

_INDEXES: Final = (
    (
        "one_provider_binding_per_occurrence",
        """
        CREATE UNIQUE INDEX one_provider_binding_per_occurrence ON
          knowledge.meeting_provider_bindings (principal_id, calendar_ref, ical_uid,
          occurrence_original_start_utc) WHERE occurrence_original_start_utc IS NOT NULL
        """,
    ),
    (
        "one_provider_binding_per_single_meeting",
        """
        CREATE UNIQUE INDEX one_provider_binding_per_single_meeting ON
          knowledge.meeting_provider_bindings (principal_id, calendar_ref, ical_uid)
          WHERE occurrence_original_start_utc IS NULL
        """,
    ),
)

_IDENTITY_FUNCTION: Final = "meeting_provider_bindings_keep_their_identity"
_IDENTITY_TRIGGER: Final = "meeting_provider_binding_identity_is_immutable"
_KIND_FUNCTION: Final = "meeting_provider_bindings_bind_one_kind_per_uid"
_KIND_TRIGGER: Final = "meeting_provider_binding_kind_is_exclusive"
_SERIES_FUNCTION: Final = "meeting_series_provider_bindings_stay_append_only"
_SERIES_TRIGGER: Final = "meeting_series_provider_bindings_are_append_only"
_TRUNCATE_FUNCTION: Final = "meeting_provider_bindings_refuse_truncate"
_TRUNCATE_TRIGGERS: Final = (
    ("meeting_series_provider_bindings_refuse_truncate", _SERIES_TABLE),
    ("meeting_provider_bindings_refuse_truncate", _TABLE),
)

_IDENTITY: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_IDENTITY_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.binding_id IS DISTINCT FROM OLD.binding_id
         OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
         OR NEW.meeting_id IS DISTINCT FROM OLD.meeting_id
         OR NEW.calendar_ref IS DISTINCT FROM OLD.calendar_ref
         OR NEW.ical_uid IS DISTINCT FROM OLD.ical_uid
         OR NEW.occurrence_original_start_utc IS DISTINCT FROM OLD.occurrence_original_start_utc
         OR NEW.series_ical_uid IS DISTINCT FROM OLD.series_ical_uid
         OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION '{_TABLE} identity is immutable'
          USING ERRCODE = 'restrict_violation';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER {_IDENTITY_TRIGGER}
      BEFORE UPDATE ON {SCHEMA}.{_TABLE}
      FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IDENTITY_FUNCTION}()
    """

#: D9: a UID is bound as a single meeting or as occurrences, never both. The
#: transaction advisory lock (two-key form, its own class id) serializes two
#: inserts for one `(principal_id, calendar_ref, ical_uid)`, so the second sees
#: the first's committed row (each statement of a READ COMMITTED function takes
#: a fresh snapshot).
_KIND: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_KIND_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM pg_advisory_xact_lock(
        20261121,
        hashtext(NEW.principal_id || chr(31) || NEW.calendar_ref || chr(31) || NEW.ical_uid)
      );
      IF EXISTS (
        SELECT 1 FROM {SCHEMA}.{_TABLE} b
        WHERE b.principal_id = NEW.principal_id
          AND b.calendar_ref = NEW.calendar_ref
          AND b.ical_uid = NEW.ical_uid
          AND (b.occurrence_original_start_utc IS NULL)
              <> (NEW.occurrence_original_start_utc IS NULL)
      ) THEN
        RAISE EXCEPTION '{_TABLE} binds one kind per uid'
          USING ERRCODE = 'exclusion_violation';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER {_KIND_TRIGGER}
      BEFORE INSERT ON {SCHEMA}.{_TABLE}
      FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_KIND_FUNCTION}()
    """  # noqa: S608 -- frozen module constants only, no input

_SERIES_APPEND_ONLY: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_SERIES_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '{_SERIES_TABLE} is append-only'
        USING ERRCODE = 'restrict_violation';
    END; $$;
    CREATE TRIGGER {_SERIES_TRIGGER}
      BEFORE UPDATE OR DELETE ON {SCHEMA}.{_SERIES_TABLE}
      FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_SERIES_FUNCTION}()
    """

_TRUNCATE: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% refuses %', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
      RETURN NULL;
    END; $$
    """

# ---- step 5: the widened vocabularies, frozen ----------------------------------

_WRITE_REQUESTS: Final = "meeting_write_requests"
_WRITE_REQUEST_CAPABILITY_CHECK: Final = "a_meeting_write_request_capability_is_known"

#: Byte copy of `7d9a450dfd07`'s write-request capability CHECK (3 names).
_WRITE_REQUEST_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('meetings.create', 'meetings.series.update', 'meetings.update')"
)

#: The same 3 plus the public `meetings.provider.bind` and the internal sync
#: namespace `system.meeting_provider.sync` -- 5 names, sorted.
_WRITE_REQUEST_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('meetings.create', 'meetings.provider.bind', 'meetings.series.update', "
    "'meetings.update', 'system.meeting_provider.sync')"
)

#: The completed shape of each new name: a bind or unbind names its Meeting, its
#: one receipt and the version it left, and never a series receipt; a sync write
#: (a create or an update) names its Meeting, its receipt and its version, and
#: carries a series receipt exactly when it created the series.
_COMPLETED_SHAPES: Final = (
    (
        "a_completed_meeting_provider_bind_names_its_result",
        "completed_at IS NULL OR capability <> 'meetings.provider.bind' OR (meeting_id IS NOT "
        "NULL AND meeting_history_id IS NOT NULL AND result_version IS NOT NULL AND "
        "meeting_series_history_id IS NULL)",
    ),
    (
        "a_completed_meeting_provider_sync_names_its_result",
        "completed_at IS NULL OR capability <> 'system.meeting_provider.sync' OR (meeting_id IS "
        "NOT NULL AND meeting_history_id IS NOT NULL AND result_version IS NOT NULL)",
    ),
)

#: Byte copy of `640aaacc78e8`'s AT set (309 names), the latest prior
#: restatement of `capability_is_known`.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.archive', 'capture.create', 'capture.list', 'capture.read', 'capture.restore', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.v2.list', 'commitments.v2.read', "
    "'commitments.v2.search', 'commitments.v2.waiting_on', 'commitments.waiting_on', "
    "'constraint_categories.create', 'constraint_categories.deactivate', "
    "'constraint_categories.list', 'constraint_categories.reorder', "
    "'constraint_categories.update', 'constraint_sync.acknowledge', 'constraint_sync.apply', "
    "'constraint_sync.conflicts', 'constraint_sync.delta', 'constraint_sync.preview', "
    "'constraint_sync.resolve', 'constraint_sync.state', 'constraints.close', "
    "'constraints.close_follow_up', 'constraints.create', 'constraints.create_published', "
    "'constraints.history', 'constraints.list', 'constraints.overview', "
    "'constraints.portfolio_list', 'constraints.portfolio_overview', "
    "'constraints.portfolio_search', 'constraints.publish', 'constraints.read', "
    "'constraints.reopen', 'constraints.search', 'constraints.transition', "
    "'constraints.update', 'constraints.void', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.close', 'continuity.projects.create', "
    "'continuity.projects.read', 'continuity.projects.update', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'files.copy', 'files.download.begin', 'files.history', 'files.list', "
    "'files.mkdir', 'files.move', 'files.preview', 'files.rename', 'files.restore', "
    "'files.search', 'files.stat', 'files.trash', 'files.upload.abort', "
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
    "'knowledge.assertions.submit', 'knowledge.coverage', 'knowledge.discovery.checkpoint', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'meetings.create', "
    "'meetings.list', 'meetings.notes.read_version', 'meetings.notes.versions', "
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
    "'records.lineage.related', 'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', 'relationship_memory.list', "
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
    "'schedule_activities.list', 'schedule_baselines.approve', 'schedule_baselines.compare', "
    "'schedule_baselines.governing', 'schedule_baselines.list', "
    "'schedule_baselines.propose', 'schedule_baselines.read', 'schedule_baselines.reject', "
    "'schedule_baselines.revoke', 'schedule_baselines.set_governing', "
    "'schedule_baselines.withdraw', 'schedule_changes.list', 'schedule_cpm_runs.activities', "
    "'schedule_cpm_runs.create', 'schedule_cpm_runs.read', 'schedule_publications.import', "
    "'schedule_publications.list', 'schedule_publications.read', "
    "'schedule_scenario_outputs.list', 'schedule_scenario_outputs.read', "
    "'schedule_scenario_outputs.record', 'schedule_scenario_versions.activities', "
    "'schedule_scenario_versions.changes', 'schedule_scenario_versions.create', "
    "'schedule_scenario_versions.read', 'schedule_scenario_versions.relationships', "
    "'schedule_scenarios.create', 'schedule_scenarios.list', 'schedule_scenarios.read', "
    "'schedule_series.current', 'schedule_series.list', 'schedule_series.match_decisions', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.comments.create', "
    "'tasks.comments.list', 'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)

#: The same set plus exactly `meetings.provider.bind` -- 310 names, sorted.
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

#: `downgrade` locks both tables, the write requests and the audit table before
#: it checks them, so no binding, bind request or audit event can commit
#: between the refusal check and the drops.
_LOCK_TABLES: Final = (
    "LOCK TABLE knowledge.meeting_provider_bindings, knowledge.meeting_series_provider_bindings, "
    "knowledge.meeting_write_requests, knowledge.audit_events IN ACCESS EXCLUSIVE MODE"
)

#: `downgrade` refuses while any binding exists, any write request names a
#: step-5 name or any audit event names `meetings.provider.bind`, rather than
#: deleting user data or audit history to make the downgrade pass (the
#: `7d9a450dfd07` precedent). Each clause alone suffices.
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM knowledge.meeting_provider_bindings)
         OR EXISTS (SELECT 1 FROM knowledge.meeting_series_provider_bindings) THEN
        RAISE EXCEPTION 'meeting provider bindings exist; refusing to downgrade 6418b57081c3'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF EXISTS (
           SELECT 1 FROM knowledge.meeting_write_requests
            WHERE capability IN ('meetings.provider.bind', 'system.meeting_provider.sync')) THEN
        RAISE EXCEPTION 'meeting provider write requests exist; refusing to downgrade 6418b57081c3'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF EXISTS (
           SELECT 1 FROM knowledge.audit_events
            WHERE capability = 'meetings.provider.bind') THEN
        RAISE EXCEPTION 'meeting provider audit history exists; refusing to downgrade 6418b57081c3'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """


def _restate(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, schema=SCHEMA, type_="check")
    op.create_check_constraint(name, table, expression, schema=SCHEMA)


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_SERIES_DDL)
    op.execute(_DDL)
    for _name, ddl in _INDEXES:
        op.execute(ddl)
    op.execute(_IDENTITY)
    op.execute(_KIND)
    op.execute(_SERIES_APPEND_ONLY)
    op.execute(_TRUNCATE)
    for trigger, table in _TRUNCATE_TRIGGERS:
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
              BEFORE TRUNCATE ON {SCHEMA}.{table}
              FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}()
            """
        )
    _restate(
        _WRITE_REQUESTS,
        _WRITE_REQUEST_CAPABILITY_CHECK,
        _WRITE_REQUEST_CAPABILITIES_AT_THIS_REVISION,
    )
    for name, expression in _COMPLETED_SHAPES:
        op.create_check_constraint(name, _WRITE_REQUESTS, expression, schema=SCHEMA)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_AT_THIS_REVISION)


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLES)
    op.execute(_REFUSE_DOWNGRADE)
    _restate("audit_events", "capability_is_known", _CAPABILITIES_BEFORE_THIS_REVISION)
    for name, _expression in reversed(_COMPLETED_SHAPES):
        op.drop_constraint(name, _WRITE_REQUESTS, schema=SCHEMA, type_="check")
    _restate(
        _WRITE_REQUESTS,
        _WRITE_REQUEST_CAPABILITY_CHECK,
        _WRITE_REQUEST_CAPABILITIES_BEFORE_THIS_REVISION,
    )
    for trigger, table in reversed(_TRUNCATE_TRIGGERS):
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}()")
    op.execute(f"DROP TRIGGER {_SERIES_TRIGGER} ON {SCHEMA}.{_SERIES_TABLE}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_SERIES_FUNCTION}()")
    op.execute(f"DROP TRIGGER {_KIND_TRIGGER} ON {SCHEMA}.{_TABLE}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_KIND_FUNCTION}()")
    op.execute(f"DROP TRIGGER {_IDENTITY_TRIGGER} ON {SCHEMA}.{_TABLE}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_IDENTITY_FUNCTION}()")
    for name, _ddl in reversed(_INDEXES):
        op.execute(f"DROP INDEX {SCHEMA}.{name}")
    op.execute(f"DROP TABLE {SCHEMA}.{_TABLE} RESTRICT")
    op.execute(f"DROP TABLE {SCHEMA}.{_SERIES_TABLE} RESTRICT")
