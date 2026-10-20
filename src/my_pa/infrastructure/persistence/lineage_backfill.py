"""The record lineage S3 backfill ledger, behind `contracts.ports.LineageBackfillRepository`.

S3 contract sections 4.2 and 8.3. The dry run's guarded ledger
(`lineage_backfill_runs`, `lineage_backfill_items`): the one-statement
enumeration over `knowledge.lineage_backfill_source_digest`, the batch reads
that rebuild each pending source, the settlements, and the report's counts and
late-source census. Nothing here writes a link, a fact or a commit mark.

**One snapshot.** `enumerate_run` is a single `WITH ... INSERT ... SELECT`: the
population over every source kind, each item's native version and source
digest, the run's census and its `commit_seq_cutoff` (the Principal's committed
`last_seq`, 0 when none) are read by one statement under one snapshot, so the
frozen population, its digests and its census agree.

**The partition is written into every statement.** Each statement is a
`text()` block; every table reference in it constrains that alias's partition
column against the bound `:principal` (the partition guard's raw-SQL claim).

**Reference tokens are the SQL mirror of `domain.lineage.backfill`.** An
origin reference matching the `asrt_` or `cap_` identifier shape is stored as
itself; any other as `prefix:<prefix>:<sha256>` when it has an identifier's
shape, `free_text:<sha256>` otherwise -- the SHA-256 of its exact UTF-8 text
(`origin_reference`). An object ref is stored as itself when identifier-shaped
(`object_reference`). The identifier shape is every `IdKind` prefix with an
8..64 alphanumeric suffix and at most 72 characters, as `validate_identifier`.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    BackfillCountRow,
    BackfillExistingLink,
    BackfillItemRecord,
    BackfillLinkEndpoints,
    BackfillPendingSource,
    BackfillRunRecord,
    BackfillSettlement,
    LineageBackfillRepository,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.lineage.backfill import CaptureVersionPin
from my_pa.domain.lineage.vocabulary import RecordFamily
from my_pa.domain.lineage_backfill.vocabulary import BACKFILL_VALIDATOR_VERSION

__all__ = ["IDENTIFIER_PATTERN", "SqlLineageBackfillRepository"]

#: `validate_identifier`'s shape in PostgreSQL regex terms, compared `COLLATE "C"`
#: (the length bound is a separate `char_length(...) <= 72`).
IDENTIFIER_PATTERN: Final = (
    "^(?:" + "|".join(sorted(kind.value for kind in IdKind)) + ")_[A-Za-z0-9]{8,64}$"
)
_ASSERTION_PATTERN: Final = f"^{IdKind.ASSERTION.value}_[A-Za-z0-9]{{8,64}}$"
_CAPTURE_PATTERN: Final = f"^{IdKind.CAPTURE.value}_[A-Za-z0-9]{{8,64}}$"
_IDENTIFIER_LENGTH: Final = 72

#: The population of section 8.3, one row per source: `(source_kind,
#: source_family, source_id, source_ref, source_version)`. Every row of each
#: listed shape, nothing pre-filtered; `UNION` removes only exact duplicates
#: (a repeated object ref of one Situation is one source).
_POPULATION: Final = """
SELECT 'task_follow_up' AS source_kind, 'task' AS source_family,
       t.task_id AS source_id, t.commitment_id AS source_ref, t.version AS source_version
  FROM knowledge.tasks t
 WHERE t.principal_id = :principal AND t.commitment_id IS NOT NULL
UNION
SELECT 'constraint_follow_up', 'constraint', r.source_constraint_id, r.target_constraint_id,
       NULL::integer
  FROM knowledge.project_constraint_relationships r
 WHERE r.principal_id = :principal AND r.relationship_type = 'follow_up_of'
UNION
SELECT 'meeting_series', 'meeting', m.meeting_id, m.meeting_series_id, m.version
  FROM knowledge.meetings m
 WHERE m.principal_id = :principal AND m.meeting_series_id IS NOT NULL
UNION
SELECT 'project_situation', 'situation', ps.situation_id, ps.project_id, NULL::integer
  FROM knowledge.project_situations ps
 WHERE ps.principal_id = :principal
UNION
SELECT o.source_kind, o.source_family, o.source_id,
       CASE WHEN o.source_kind = 'work_origin_other' THEN
         CASE WHEN char_length(o.ref) <= :identifier_length
                   AND o.ref COLLATE "C" ~ :identifier_pattern
              THEN 'prefix:' || split_part(o.ref, '_', 1) || ':'
              ELSE 'free_text:' END
         || encode(sha256(convert_to(o.ref, 'UTF8')), 'hex')
       ELSE o.ref END,
       o.source_version
  FROM (
    SELECT CASE WHEN w.ref COLLATE "C" ~ :assertion_pattern THEN 'work_origin_assertion'
                WHEN w.ref COLLATE "C" ~ :capture_pattern THEN 'work_origin_capture_root'
                ELSE 'work_origin_other' END AS source_kind,
           w.source_family, w.source_id, w.ref, w.source_version
      FROM (
        SELECT 'task' AS source_family, wt.task_id AS source_id,
               wt.origin_evidence_ref AS ref, wt.version AS source_version
          FROM knowledge.tasks wt
         WHERE wt.principal_id = :principal AND wt.origin_evidence_ref IS NOT NULL
        UNION ALL
        SELECT 'commitment', wc.commitment_id, wc.origin_evidence_ref, wc.version
          FROM knowledge.commitments wc
         WHERE wc.principal_id = :principal AND wc.origin_evidence_ref IS NOT NULL
      ) w
  ) o
UNION
SELECT 'situation_object_ref', 'situation', e.situation_id,
       CASE WHEN char_length(e.ref) <= :identifier_length
                 AND e.ref COLLATE "C" ~ :identifier_pattern
            THEN e.ref
            ELSE 'free_text:' || encode(sha256(convert_to(e.ref, 'UTF8')), 'hex') END,
       e.version
  FROM (
    SELECT s.situation_id, s.version,
           CASE WHEN jsonb_typeof(element.value) = 'string' THEN element.value #>> '{}'
                ELSE element.value::text END AS ref
      FROM knowledge.situations s
     CROSS JOIN LATERAL jsonb_array_elements(
           CASE WHEN jsonb_typeof(s.object_refs) = 'array' THEN s.object_refs
                ELSE '[]'::jsonb END) AS element(value)
     WHERE s.principal_id = :principal AND s.kind = 'context'
  ) e
"""

#: The census of section 8.3 over the frozen `numbered` population: per source
#: kind the native rows examined (counted from the native tables) and the
#: number enumerated; per work family the origin-reference shapes; and the
#: `project_situation` consistency counts. Counts and tokens only.
_CENSUS: Final = """
jsonb_build_object(
  'schema_version', 1,
  'kinds', jsonb_build_object(
    'task_follow_up', jsonb_build_object(
      'examined', (SELECT count(*) FROM knowledge.tasks ct
                    WHERE ct.principal_id = :principal AND ct.commitment_id IS NOT NULL),
      'enumerated', (SELECT count(*) FROM numbered WHERE source_kind = 'task_follow_up')),
    'constraint_follow_up', jsonb_build_object(
      'examined', (SELECT count(DISTINCT (cr.source_constraint_id, cr.target_constraint_id))
                     FROM knowledge.project_constraint_relationships cr
                    WHERE cr.principal_id = :principal
                      AND cr.relationship_type = 'follow_up_of'),
      'enumerated', (SELECT count(*) FROM numbered WHERE source_kind = 'constraint_follow_up')),
    'meeting_series', jsonb_build_object(
      'examined', (SELECT count(*) FROM knowledge.meetings cm
                    WHERE cm.principal_id = :principal AND cm.meeting_series_id IS NOT NULL),
      'enumerated', (SELECT count(*) FROM numbered WHERE source_kind = 'meeting_series')),
    'project_situation', jsonb_build_object(
      'examined', (SELECT count(*) FROM knowledge.project_situations cps
                    WHERE cps.principal_id = :principal),
      'enumerated', (SELECT count(*) FROM numbered WHERE source_kind = 'project_situation')),
    'work_origin_assertion', jsonb_build_object(
      'examined', (SELECT count(*) FROM origin_shapes WHERE shape = 'asrt_'),
      'enumerated', (SELECT count(*) FROM numbered
                      WHERE source_kind = 'work_origin_assertion')),
    'work_origin_capture_root', jsonb_build_object(
      'examined', (SELECT count(*) FROM origin_shapes WHERE shape = 'cap_'),
      'enumerated', (SELECT count(*) FROM numbered
                      WHERE source_kind = 'work_origin_capture_root')),
    'work_origin_other', jsonb_build_object(
      'examined', (SELECT count(*) FROM origin_shapes
                    WHERE shape IN ('other_prefix', 'not_an_identifier')),
      'enumerated', (SELECT count(*) FROM numbered WHERE source_kind = 'work_origin_other')),
    'situation_object_ref', jsonb_build_object(
      'examined', (SELECT count(DISTINCT (cs.situation_id, element.value))
                     FROM knowledge.situations cs
                    CROSS JOIN LATERAL jsonb_array_elements(
                          CASE WHEN jsonb_typeof(cs.object_refs) = 'array' THEN cs.object_refs
                               ELSE '[]'::jsonb END) AS element(value)
                    WHERE cs.principal_id = :principal AND cs.kind = 'context'),
      'enumerated', (SELECT count(*) FROM numbered WHERE source_kind = 'situation_object_ref'))),
  'origin_reference_shapes', jsonb_build_object(
    'task', jsonb_build_object(
      'asrt_', (SELECT count(*) FROM origin_shapes WHERE family = 'task' AND shape = 'asrt_'),
      'cap_', (SELECT count(*) FROM origin_shapes WHERE family = 'task' AND shape = 'cap_'),
      'other_prefix', (SELECT count(*) FROM origin_shapes
                        WHERE family = 'task' AND shape = 'other_prefix'),
      'not_an_identifier', (SELECT count(*) FROM origin_shapes
                             WHERE family = 'task' AND shape = 'not_an_identifier')),
    'commitment', jsonb_build_object(
      'asrt_', (SELECT count(*) FROM origin_shapes
                 WHERE family = 'commitment' AND shape = 'asrt_'),
      'cap_', (SELECT count(*) FROM origin_shapes
                WHERE family = 'commitment' AND shape = 'cap_'),
      'other_prefix', (SELECT count(*) FROM origin_shapes
                        WHERE family = 'commitment' AND shape = 'other_prefix'),
      'not_an_identifier', (SELECT count(*) FROM origin_shapes
                             WHERE family = 'commitment' AND shape = 'not_an_identifier'))),
  'project_situation', jsonb_build_object(
    'consistent', (SELECT count(*) FROM situation_links WHERE consistent),
    'inconsistent', (SELECT count(*) FROM situation_links WHERE NOT consistent)))
"""

#: Section 8.3's enumeration, one statement. `origin_shapes` reads the origin
#: references by shape (counted, not interpreted); `situation_links` the
#: `project_situation` consistency the classification will state; `numbered`
#: the population in its deterministic `item_no` order.
_ENUMERATE: Final = (
    "WITH population AS (" + _POPULATION + "),\n"  # noqa: S608 - this module's constant SQL only
    """
origin_shapes AS (
  SELECT os.family,
         CASE WHEN os.ref COLLATE "C" ~ :assertion_pattern THEN 'asrt_'
              WHEN os.ref COLLATE "C" ~ :capture_pattern THEN 'cap_'
              WHEN char_length(os.ref) <= :identifier_length
                   AND os.ref COLLATE "C" ~ :identifier_pattern THEN 'other_prefix'
              ELSE 'not_an_identifier' END AS shape
    FROM (
      SELECT 'task' AS family, st.origin_evidence_ref AS ref
        FROM knowledge.tasks st
       WHERE st.principal_id = :principal AND st.origin_evidence_ref IS NOT NULL
      UNION ALL
      SELECT 'commitment', sc.origin_evidence_ref
        FROM knowledge.commitments sc
       WHERE sc.principal_id = :principal AND sc.origin_evidence_ref IS NOT NULL
    ) os
),
situation_links AS (
  SELECT (ls.kind IS NOT NULL AND lp.project_id IS NOT NULL
          AND (ls.kind <> 'issue_workstream' OR EXISTS (
                SELECT 1 FROM knowledge.issue_project_membership_events le
                 WHERE le.principal_id = :principal
                   AND le.issue_id = lps.situation_id
                   AND le.project_id = lps.project_id))) AS consistent
    FROM knowledge.project_situations lps
    LEFT JOIN knowledge.situations ls
      ON ls.principal_id = :principal AND ls.situation_id = lps.situation_id
    LEFT JOIN knowledge.projects lp
      ON lp.principal_id = :principal AND lp.project_id = lps.project_id
   WHERE lps.principal_id = :principal
),
numbered AS (
  SELECT row_number() OVER (
           ORDER BY p.source_kind COLLATE "C", p.source_id COLLATE "C",
                    p.source_ref COLLATE "C") AS item_no,
         p.source_kind, p.source_family, p.source_id, p.source_ref, p.source_version
    FROM population p
),
census AS (
  SELECT """
    + _CENSUS
    + """ AS value
),
run AS (
  INSERT INTO knowledge.lineage_backfill_runs (
    principal_id, run_id, state, validator_version, commit_seq_cutoff, source_cutoff_at,
    population_count, classified_count, plan_digest, census, created_at, classified_at,
    authority_class, decision_channel)
  SELECT :principal, :run_id, 'enumerated', :validator_version,
         coalesce((SELECT q.last_seq FROM knowledge.lineage_commit_sequences q
                    WHERE q.principal_id = :principal), 0),
         statement_timestamp(), (SELECT count(*) FROM numbered), 0, NULL,
         (SELECT census.value FROM census), :created_at, NULL, :authority_class,
         :decision_channel
   WHERE NOT EXISTS (
         SELECT 1 FROM knowledge.lineage_backfill_runs
          WHERE lineage_backfill_runs.principal_id = :principal
            AND lineage_backfill_runs.run_id = :run_id)
  RETURNING run_id
)
INSERT INTO knowledge.lineage_backfill_items (
  principal_id, run_id, item_no, source_kind, source_family, source_id, source_ref,
  source_version, source_digest)
SELECT :principal, run.run_id, n.item_no, n.source_kind, n.source_family, n.source_id,
       n.source_ref, n.source_version,
       knowledge.lineage_backfill_source_digest(
         :principal, n.source_kind, n.source_family, n.source_id, n.source_ref)
  FROM numbered n CROSS JOIN run
 WHERE NOT EXISTS (
       SELECT 1 FROM knowledge.lineage_backfill_items
        WHERE lineage_backfill_items.principal_id = :principal
          AND lineage_backfill_items.run_id = :run_id)
"""
)

_RUN_COLUMNS: Final = """
SELECT r.run_id, r.state, r.validator_version, r.commit_seq_cutoff, r.source_cutoff_at,
       r.population_count, r.classified_count, r.plan_digest, r.census, r.created_at,
       r.classified_at
  FROM knowledge.lineage_backfill_runs r
 WHERE r.principal_id = :principal AND r.run_id = :run_id
"""

_ITEM_COLUMNS: Final = """
SELECT i.item_no, i.source_kind, i.source_family, i.source_id, i.source_ref,
       i.source_version, i.source_digest, i.classification, i.reason, i.candidate_identity,
       i.candidate, i.existing_link_id, i.existing_link_state, i.quarantined, i.classified_at
"""

_PENDING: Final = (
    _ITEM_COLUMNS
    + """,
       knowledge.lineage_backfill_source_digest(
         :principal, i.source_kind, i.source_family, i.source_id, i.source_ref)
         AS current_digest,
       knowledge.lineage_backfill_source_document(
         :principal, i.source_kind, i.source_family, i.source_id, i.source_ref)
         AS current_document
  FROM knowledge.lineage_backfill_items i
 WHERE i.principal_id = :principal AND i.run_id = :run_id
   AND i.item_no > :after AND i.classification IS NULL
 ORDER BY i.item_no
 LIMIT :limit
"""
)

_ITEMS: Final = (
    _ITEM_COLUMNS
    + """
  FROM knowledge.lineage_backfill_items i
 WHERE i.principal_id = :principal AND i.run_id = :run_id
   AND i.item_no > :after
   AND (CAST(:through AS integer) IS NULL OR i.item_no <= CAST(:through AS integer))
   AND (CAST(:classification AS text) IS NULL
        OR i.classification = CAST(:classification AS text))
 ORDER BY i.item_no
 LIMIT :limit
"""
)

_PINS: Final = """
SELECT v.version_id, v.capture_id, v.version_number, v.content_sha256
  FROM knowledge.capture_versions v
 WHERE v.owner_principal_id = :principal AND v.version_id = ANY(CAST(:ids AS text[]))
"""

#: Which named records the Principal owns, one family per branch.
_OWNED: Final = {
    RecordFamily.SITUATION: """
SELECT s.situation_id FROM knowledge.situations s
 WHERE s.principal_id = :principal AND s.situation_id = ANY(CAST(:ids AS text[]))
""",
    RecordFamily.MEETING: """
SELECT m.meeting_id FROM knowledge.meetings m
 WHERE m.principal_id = :principal AND m.meeting_id = ANY(CAST(:ids AS text[]))
""",
    RecordFamily.MEETING_NOTE_VERSION: """
SELECT n.note_version_id FROM knowledge.meeting_note_versions n
 WHERE n.principal_id = :principal AND n.note_version_id = ANY(CAST(:ids AS text[]))
""",
    RecordFamily.TASK: """
SELECT t.task_id FROM knowledge.tasks t
 WHERE t.principal_id = :principal AND t.task_id = ANY(CAST(:ids AS text[]))
""",
    RecordFamily.COMMITMENT: """
SELECT c.commitment_id FROM knowledge.commitments c
 WHERE c.principal_id = :principal AND c.commitment_id = ANY(CAST(:ids AS text[]))
""",
    RecordFamily.CONSTRAINT: """
SELECT k.constraint_id FROM knowledge.project_constraints k
 WHERE k.principal_id = :principal AND k.constraint_id = ANY(CAST(:ids AS text[]))
""",
    RecordFamily.CAPTURE_VERSION: """
SELECT v.version_id FROM knowledge.capture_versions v
 WHERE v.owner_principal_id = :principal AND v.version_id = ANY(CAST(:ids AS text[]))
""",
}

#: Section 4.2's existing-link column: any link between the endpoints, in any
#: context, known at the cutoff, with its state there -- the lowest `link_id`.
_EXISTING_LINKS: Final = """
SELECT DISTINCT ON (l.from_family, l.from_id, l.relation_type, l.to_family, l.to_id)
       l.from_family, l.from_id, l.relation_type, l.to_family, l.to_id, l.link_id,
       known.lifecycle_state
  FROM knowledge.record_links l
  JOIN unnest(CAST(:from_families AS text[]), CAST(:from_ids AS text[]),
              CAST(:relations AS text[]), CAST(:to_families AS text[]),
              CAST(:to_ids AS text[])) AS wanted(ff, fi, rt, tf, ti)
    ON l.from_family = wanted.ff AND l.from_id = wanted.fi AND l.relation_type = wanted.rt
   AND l.to_family = wanted.tf AND l.to_id = wanted.ti
  JOIN LATERAL (
       SELECT rv.lifecycle_state
         FROM knowledge.record_link_revisions rv
        WHERE rv.principal_id = :principal AND rv.link_id = l.link_id
          AND (rv.commit_seq IS NULL OR rv.commit_seq <= :cutoff)
        ORDER BY rv.revision_no DESC
        LIMIT 1) AS known ON true
 WHERE l.principal_id = :principal
 ORDER BY l.from_family, l.from_id, l.relation_type, l.to_family, l.to_id,
          l.link_id COLLATE "C"
"""

_SETTLE: Final = """
UPDATE knowledge.lineage_backfill_items
   SET classification = :classification, reason = :reason,
       candidate_identity = :candidate_identity, candidate = :candidate,
       existing_link_id = :existing_link_id, existing_link_state = :existing_link_state,
       quarantined = :quarantined, classified_at = :classified_at
 WHERE lineage_backfill_items.principal_id = :principal
   AND lineage_backfill_items.run_id = :run_id
   AND lineage_backfill_items.item_no = :item_no
   AND lineage_backfill_items.classification IS NULL
"""

_ADVANCE: Final = """
UPDATE knowledge.lineage_backfill_runs
   SET classified_count = :classified_count,
       state = CASE WHEN CAST(:plan_digest AS text) IS NULL THEN state ELSE 'classified' END,
       plan_digest = :plan_digest, classified_at = :classified_at
 WHERE lineage_backfill_runs.principal_id = :principal
   AND lineage_backfill_runs.run_id = :run_id
"""

_COUNT_ROWS: Final = """
SELECT i.classification, i.reason, i.existing_link_state, i.quarantined, count(*) AS total
  FROM knowledge.lineage_backfill_items i
 WHERE i.principal_id = :principal AND i.run_id = :run_id AND i.classification IS NOT NULL
 GROUP BY i.classification, i.reason, i.existing_link_state, i.quarantined
"""

_LATE_SOURCES: Final = (
    "WITH population AS (" + _POPULATION + ")\n"  # noqa: S608 - this module's constant SQL only
    """
SELECT count(*)
  FROM population p
 WHERE NOT EXISTS (
       SELECT 1 FROM knowledge.lineage_backfill_items li
        WHERE li.principal_id = :principal AND li.run_id = :run_id
          AND li.source_kind = p.source_kind AND li.source_id = p.source_id
          AND li.source_ref = p.source_ref)
"""
)


def _shape_parameters(principal_id: str) -> dict[str, object]:
    return {
        "principal": principal_id,
        "identifier_pattern": IDENTIFIER_PATTERN,
        "identifier_length": _IDENTIFIER_LENGTH,
        "assertion_pattern": _ASSERTION_PATTERN,
        "capture_pattern": _CAPTURE_PATTERN,
    }


def _run(row: Row[Any]) -> BackfillRunRecord:
    census = row.census if isinstance(row.census, dict) else json.loads(row.census)
    return BackfillRunRecord(
        run_id=row.run_id,
        state=row.state,
        validator_version=row.validator_version,
        commit_seq_cutoff=row.commit_seq_cutoff,
        source_cutoff_at=row.source_cutoff_at,
        population_count=row.population_count,
        classified_count=row.classified_count,
        plan_digest=row.plan_digest,
        census=census,
        created_at=row.created_at,
        classified_at=row.classified_at,
    )


def _item(row: Row[Any]) -> BackfillItemRecord:
    return BackfillItemRecord(
        item_no=row.item_no,
        source_kind=row.source_kind,
        source_family=row.source_family,
        source_id=row.source_id,
        source_ref=row.source_ref,
        source_version=row.source_version,
        source_digest=row.source_digest,
        classification=row.classification,
        reason=row.reason,
        candidate_identity=row.candidate_identity,
        candidate=row.candidate,
        existing_link_id=row.existing_link_id,
        existing_link_state=row.existing_link_state,
        quarantined=row.quarantined,
        classified_at=row.classified_at,
    )


class SqlLineageBackfillRepository(LineageBackfillRepository):
    """`LineageBackfillRepository`, over the general unit of work's `Connection`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def enumerate_run(
        self,
        principal_id: str,
        run_id: str,
        *,
        created_at: datetime,
        authority_class: str,
        decision_channel: str,
    ) -> BackfillRunRecord:
        self._connection.execute(
            text(_ENUMERATE),
            {
                **_shape_parameters(principal_id),
                "run_id": run_id,
                "validator_version": BACKFILL_VALIDATOR_VERSION,
                "created_at": created_at,
                "authority_class": authority_class,
                "decision_channel": decision_channel,
            },
        )
        run = self.read_run(principal_id, run_id)
        if run is None:  # pragma: no cover - the statement above inserted it
            raise RuntimeError("the enumerated backfill run is not readable")
        return run

    def read_run(
        self, principal_id: str, run_id: str, *, for_update: bool = False
    ) -> BackfillRunRecord | None:
        statement = _RUN_COLUMNS + (" FOR UPDATE" if for_update else "")
        row = self._connection.execute(
            text(statement), {"principal": principal_id, "run_id": run_id}
        ).one_or_none()
        return None if row is None else _run(row)

    def pending_sources(
        self, principal_id: str, run_id: str, *, after: int, limit: int
    ) -> tuple[BackfillPendingSource, ...]:
        rows = self._connection.execute(
            text(_PENDING),
            {"principal": principal_id, "run_id": run_id, "after": after, "limit": limit},
        ).all()
        return tuple(
            BackfillPendingSource(
                item=_item(row),
                current_digest=row.current_digest,
                current_document=row.current_document,
            )
            for row in rows
        )

    def capture_version_pins(
        self, principal_id: str, version_ids: Collection[str]
    ) -> Mapping[str, CaptureVersionPin]:
        if not version_ids:
            return {}
        rows = self._connection.execute(
            text(_PINS), {"principal": principal_id, "ids": sorted(set(version_ids))}
        ).all()
        return {
            row.version_id: CaptureVersionPin(
                version_id=row.version_id,
                capture_id=row.capture_id,
                version_number=row.version_number,
                content_sha256=row.content_sha256,
            )
            for row in rows
        }

    def owned_references(
        self, principal_id: str, references: Collection[tuple[RecordFamily, str]]
    ) -> frozenset[tuple[RecordFamily, str]]:
        owned: set[tuple[RecordFamily, str]] = set()
        for family, statement in _OWNED.items():
            wanted = sorted({record_id for named, record_id in references if named is family})
            if not wanted:
                continue
            rows = self._connection.execute(
                text(statement), {"principal": principal_id, "ids": wanted}
            ).scalars()
            owned.update((family, str(record_id)) for record_id in rows)
        return frozenset(owned)

    def existing_links(
        self, principal_id: str, endpoints: Collection[BackfillLinkEndpoints], *, cutoff: int
    ) -> Mapping[BackfillLinkEndpoints, BackfillExistingLink]:
        wanted = sorted(
            set(endpoints),
            key=lambda e: (e.from_family, e.from_id, e.relation_type, e.to_family, e.to_id),
        )
        if not wanted:
            return {}
        rows = self._connection.execute(
            text(_EXISTING_LINKS),
            {
                "principal": principal_id,
                "cutoff": cutoff,
                "from_families": [e.from_family for e in wanted],
                "from_ids": [e.from_id for e in wanted],
                "relations": [e.relation_type for e in wanted],
                "to_families": [e.to_family for e in wanted],
                "to_ids": [e.to_id for e in wanted],
            },
        ).all()
        return {
            BackfillLinkEndpoints(
                from_family=row.from_family,
                from_id=row.from_id,
                relation_type=row.relation_type,
                to_family=row.to_family,
                to_id=row.to_id,
            ): BackfillExistingLink(link_id=row.link_id, lifecycle_state=row.lifecycle_state)
            for row in rows
        }

    def settle_items(
        self,
        principal_id: str,
        run_id: str,
        settlements: Sequence[BackfillSettlement],
        *,
        classified_at: datetime,
    ) -> None:
        if not settlements:
            return
        self._connection.execute(
            text(_SETTLE),
            [
                {
                    "principal": principal_id,
                    "run_id": run_id,
                    "item_no": settled.item_no,
                    "classification": settled.classification,
                    "reason": settled.reason,
                    "candidate_identity": settled.candidate_identity,
                    "candidate": settled.candidate,
                    "existing_link_id": settled.existing_link_id,
                    "existing_link_state": settled.existing_link_state,
                    "quarantined": settled.quarantined,
                    "classified_at": classified_at,
                }
                for settled in settlements
            ],
        )

    def advance_run(
        self,
        principal_id: str,
        run_id: str,
        *,
        classified_count: int,
        plan_digest: str | None,
        classified_at: datetime | None,
    ) -> None:
        self._connection.execute(
            text(_ADVANCE),
            {
                "principal": principal_id,
                "run_id": run_id,
                "classified_count": classified_count,
                "plan_digest": plan_digest,
                "classified_at": classified_at,
            },
        )

    def items(
        self,
        principal_id: str,
        run_id: str,
        *,
        after: int,
        through: int | None = None,
        limit: int | None = None,
        classification: str | None = None,
    ) -> tuple[BackfillItemRecord, ...]:
        rows = self._connection.execute(
            text(_ITEMS),
            {
                "principal": principal_id,
                "run_id": run_id,
                "after": after,
                "through": through,
                "limit": limit,
                "classification": classification,
            },
        ).all()
        return tuple(_item(row) for row in rows)

    def count_rows(self, principal_id: str, run_id: str) -> tuple[BackfillCountRow, ...]:
        rows = self._connection.execute(
            text(_COUNT_ROWS), {"principal": principal_id, "run_id": run_id}
        ).all()
        return tuple(
            BackfillCountRow(
                classification=row.classification,
                reason=row.reason,
                existing_link_state=row.existing_link_state,
                quarantined=row.quarantined,
                count=int(row.total),
            )
            for row in rows
        )

    def late_source_count(self, principal_id: str, run_id: str) -> int:
        return int(
            self._connection.execute(
                text(_LATE_SOURCES), {**_shape_parameters(principal_id), "run_id": run_id}
            ).scalar_one()
        )
