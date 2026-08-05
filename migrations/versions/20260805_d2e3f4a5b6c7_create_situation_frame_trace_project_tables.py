"""create the R5 continuity surface: situations, frames, traces, projects, pulse

Creates the WP-06 (R5 relationship / project continuity) durable surface on top
of the now principal-partitioned relationship graph:

- `situations` — a purposeful operational context that *references* one or more
  objects (via `object_refs`) but does not own them (canonical model: "Situation:
  purposeful operational context referencing one or more objects; does not own
  them").
- `frames` — the current or saved view *within* a Situation of what matters,
  the evidence, alternatives, obligations, uncertainty, and the next authority
  point ("Frame: current/saved view of what matters, evidence, alternatives,
  obligations, uncertainty, and next authority point").
- `traces` — a derived, source-linked temporal reconstruction for one object over
  a time range, recording the source events it reconstructed and the gaps it
  exposed ("Trace: derived source-linked temporal reconstruction; not source
  evidence"). A trace is a projection, never source evidence.
- `projects` — a durable work context with participants that groups Situations
  ("Project: durable work context with participants, sources, Situations, ...").
- `project_situations` — the link table binding a Project to the Situations it
  contains, unique per (project, situation).
- `relationship_events` — a time/context-aware association event on a Person's
  relationship timeline. `accepted` gates whether Today/Pulse may read it, so an
  unaccepted (proposed) event never surfaces as an accepted timeline fact
  (invariant 5: no timeline entry presents a proposal as accepted).
- `pulse_items` — derived attention recommendations with reason, consequence, and
  next step. `accepted_only` defaults TRUE and encodes the WP-06 acceptance
  criterion "Today/Pulse read only accepted records": a Pulse item is generated
  only from accepted state.

**Every table carries `principal_id` (NOT NULL, opaque-identifier CHECK,
principal-first index).** These surfaces are read by Today/Pulse and by the
relationship/project briefing, all of which must be strictly principal-scoped, so
the partition is present from the first row (invariant 11: `principal_id` is a
mandatory predicate on every read path). Frames and project links inherit their
parent's Principal but still carry `principal_id` explicitly so a query can
enforce the partition without joining back to the parent — the same reasoning the
WP-05 review partition used for span tables.

**Identifier and CHECK literals are frozen in this revision.** Opaque-id CHECKs
(`^{prefix}_[A-Za-z0-9]{8,64}$`) and the principal CHECK
(`^prn_[A-Za-z0-9]{8,64}$`, named `principal_id_is_an_opaque_identifier`)
reproduce the shape `tables.py` emits for id and principal columns, so the applied
schema matches what `to_metadata` builds — the schema-parity invariant. The
literals are inlined so a merged revision keeps meaning the same thing even if the
live declaration is later edited (`D-48`).

The downgrade drops the seven tables in reverse dependency order.

Revision ID: d2e3f4a5b6c7
Revises: c1f2d3e4a5b6
Created: 2026-08-05 20:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1f2d3e4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the situation, frame, trace, project, and pulse continuity surface."""
    op.execute(
        """
        CREATE TABLE knowledge.situations (
          situation_id text PRIMARY KEY
            CHECK (situation_id ~ '^sit_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          title text NOT NULL CHECK (length(trim(title)) > 0),
          description text,
          state text NOT NULL DEFAULT 'open'
            CHECK (state IN ('open', 'active', 'suspended', 'closed')),
          object_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
          opened_at timestamptz NOT NULL,
          closed_at timestamptz,
          outcome text,
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          CONSTRAINT a_closed_situation_records_when_it_closed
            CHECK ((state = 'closed') = (closed_at IS NOT NULL))
        );
        CREATE INDEX situations_by_principal
          ON knowledge.situations (principal_id);
        CREATE INDEX situations_by_principal_state
          ON knowledge.situations (principal_id, state);

        CREATE TABLE knowledge.frames (
          frame_id text PRIMARY KEY
            CHECK (frame_id ~ '^frm_[A-Za-z0-9]{8,64}$'),
          situation_id text NOT NULL
            REFERENCES knowledge.situations(situation_id),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          label text NOT NULL CHECK (length(trim(label)) > 0),
          evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
          alternatives jsonb NOT NULL DEFAULT '[]'::jsonb,
          obligations jsonb NOT NULL DEFAULT '[]'::jsonb,
          uncertainty text,
          next_authority text,
          state text NOT NULL DEFAULT 'current'
            CHECK (state IN ('current', 'saved', 'archived')),
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL
        );
        CREATE INDEX frames_by_principal
          ON knowledge.frames (principal_id);
        CREATE INDEX frames_by_principal_situation
          ON knowledge.frames (principal_id, situation_id);

        CREATE TABLE knowledge.traces (
          trace_id text PRIMARY KEY
            CHECK (trace_id ~ '^trc_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          object_id text NOT NULL,
          object_type text NOT NULL CHECK (length(trim(object_type)) > 0),
          time_range_start timestamptz,
          time_range_end timestamptz,
          source_events jsonb NOT NULL DEFAULT '[]'::jsonb,
          gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
          created_at timestamptz NOT NULL,
          CONSTRAINT a_trace_range_ends_after_it_starts CHECK (
            time_range_end IS NULL OR time_range_start IS NULL
            OR time_range_end >= time_range_start
          )
        );
        CREATE INDEX traces_by_principal
          ON knowledge.traces (principal_id);
        CREATE INDEX traces_by_principal_object
          ON knowledge.traces (principal_id, object_id);

        CREATE TABLE knowledge.projects (
          project_id text PRIMARY KEY
            CHECK (project_id ~ '^prj_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          name text NOT NULL CHECK (length(trim(name)) > 0),
          description text,
          state text NOT NULL DEFAULT 'active'
            CHECK (state IN ('active', 'on_hold', 'closed')),
          participants jsonb NOT NULL DEFAULT '[]'::jsonb,
          opened_at timestamptz NOT NULL,
          closed_at timestamptz,
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          CONSTRAINT a_closed_project_records_when_it_closed
            CHECK ((state = 'closed') = (closed_at IS NOT NULL))
        );
        CREATE INDEX projects_by_principal
          ON knowledge.projects (principal_id);
        CREATE INDEX projects_by_principal_state
          ON knowledge.projects (principal_id, state);

        CREATE TABLE knowledge.project_situations (
          project_situation_id text PRIMARY KEY
            CHECK (project_situation_id ~ '^psit_[A-Za-z0-9]{8,64}$'),
          project_id text NOT NULL
            REFERENCES knowledge.projects(project_id),
          situation_id text NOT NULL
            REFERENCES knowledge.situations(situation_id),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          linked_at timestamptz NOT NULL,
          CONSTRAINT a_situation_links_to_a_project_once
            UNIQUE (project_id, situation_id)
        );
        CREATE INDEX project_situations_by_principal
          ON knowledge.project_situations (principal_id);

        CREATE TABLE knowledge.relationship_events (
          event_id text PRIMARY KEY
            CHECK (event_id ~ '^revt_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          person_id text NOT NULL
            REFERENCES knowledge.relationship_people(person_id),
          event_type text NOT NULL CHECK (event_type IN (
            'interaction', 'meeting', 'commitment', 'observation',
            'affiliation_change', 'project_link'
          )),
          occurred_at timestamptz NOT NULL,
          context text,
          accepted boolean NOT NULL DEFAULT false,
          source_ref text,
          created_at timestamptz NOT NULL
        );
        CREATE INDEX relationship_events_by_principal
          ON knowledge.relationship_events (principal_id);
        CREATE INDEX relationship_events_by_principal_person
          ON knowledge.relationship_events (principal_id, person_id);
        CREATE INDEX relationship_events_by_principal_accepted
          ON knowledge.relationship_events (principal_id, accepted);

        CREATE TABLE knowledge.pulse_items (
          pulse_id text PRIMARY KEY
            CHECK (pulse_id ~ '^puls_[A-Za-z0-9]{8,64}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          item_type text NOT NULL CHECK (item_type IN (
            'commitment', 'decision', 'task', 'observation',
            'relationship_event', 'situation'
          )),
          item_ref text NOT NULL CHECK (length(trim(item_ref)) > 0),
          reason text NOT NULL CHECK (length(trim(reason)) > 0),
          consequence text,
          next_step text,
          priority integer NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
          accepted_only boolean NOT NULL DEFAULT true,
          generated_at timestamptz NOT NULL,
          dismissed_at timestamptz,
          CONSTRAINT pulse_reads_only_accepted_records CHECK (accepted_only IS TRUE)
        );
        CREATE INDEX pulse_items_by_principal
          ON knowledge.pulse_items (principal_id);
        CREATE INDEX pulse_items_by_principal_dismissed
          ON knowledge.pulse_items (principal_id, dismissed_at);
        """
    )


def downgrade() -> None:
    """Drop the continuity surface in reverse dependency order."""
    op.execute(
        """
        DROP TABLE knowledge.pulse_items;
        DROP TABLE knowledge.relationship_events;
        DROP TABLE knowledge.project_situations;
        DROP TABLE knowledge.projects;
        DROP TABLE knowledge.traces;
        DROP TABLE knowledge.frames;
        DROP TABLE knowledge.situations;
        """
    )
