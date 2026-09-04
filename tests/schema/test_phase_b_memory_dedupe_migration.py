"""Legacy Relationship Memory open-equivalent reconciliation at Phase-B head."""

# ruff: noqa: S608 -- every interpolated identifier is a frozen test literal.

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DATABASE: Final = "my_pa_phase_b_memory_dedupe_migration_test"
SCHEMA: Final = "knowledge"
PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
SUBJECT: Final = "ent_aaaa0001aaaa0001"
WINNER: Final = "mprop_aaaa0001aaaa0001"
LOSER: Final = "mprop_bbbb0002bbbb0002"
WINNER_CASE: Final = "rvw_aaaa0001aaaa0001"
LOSER_CASE: Final = "rvw_bbbb0002bbbb0002"
STATEMENT: Final = "Synthetic predecessor claim."
STATEMENT_DIGEST: Final = hashlib.sha256(STATEMENT.encode()).hexdigest()
EARLIER: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
LATER: Final = EARLIER + timedelta(hours=1)
CORRECTED: Final = "C" * 300


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _proposal_values(
    proposal_id: str, case_id: str, at: datetime, version: int
) -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "case_id": case_id,
        "version": version,
        "statement": STATEMENT,
        "statement_digest": STATEMENT_DIGEST,
        "at": at,
    }


PHASE_B_HEAD_OBJECTS: Final = {
    "column:relationship_memory_proposals.context_links",
    "column:relationship_memory_review_decisions.corrected_payload",
    "constraint:a_memory_corrected_payload_matches_its_disposition",
}


def _phase_b_head_objects(connection: Connection) -> set[str]:
    """The two typed JSON columns and their dependent IFF constraint."""
    return set(
        connection.execute(
            text(
                "SELECT 'column:' || table_name || '.' || column_name "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND ("
                "(table_name = 'relationship_memory_proposals' "
                " AND column_name = 'context_links') OR "
                "(table_name = 'relationship_memory_review_decisions' "
                " AND column_name = 'corrected_payload')) "
                "UNION ALL "
                "SELECT 'constraint:' || conname FROM pg_constraint "
                "WHERE conrelid = 'knowledge.relationship_memory_review_decisions'::regclass "
                "AND conname = 'a_memory_corrected_payload_matches_its_disposition'"
            ),
            {"schema": SCHEMA},
        ).scalars()
    )


def test_upgrade_backfills_context_and_typed_memory_correction_payload(
    predecessor: Engine,
) -> None:
    """A current predecessor reaches the new proposal/review shape without loss."""
    with predecessor.begin() as connection:
        assert _phase_b_head_objects(connection) == set()
        SqlEntityRepository(connection).create(
            PRINCIPAL,
            Entity(
                entity_id=SUBJECT,
                principal_id=PRINCIPAL,
                entity_type=EntityType.PERSON,
                canonical_name=normalize_name("Synthetic Person"),
                display_name="Synthetic Person",
                status=EntityStatus.ACTIVE,
                created_at=EARLIER,
                updated_at=EARLIER,
                version=1,
            ),
        )
        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.relationship_memory_proposals (
                  memory_proposal_id, principal_id, subject_entity_id,
                  proposed_kind, proposed_statement, proposed_statement_sha256,
                  structured_value, state, method, method_version, classification,
                  proposed_at, review_case_id
                ) VALUES (
                  'mprop_cccc0003cccc0003', :principal, :subject,
                  'general_note', :statement, :statement_digest, NULL,
                  'needs_review', 'rule', 'legacy-rule-v1', 'private_local', :at,
                  'rvw_cccc0003cccc0003'
                )
                """
            ),
            {
                "principal": PRINCIPAL,
                "subject": SUBJECT,
                "statement": STATEMENT,
                "statement_digest": STATEMENT_DIGEST,
                "at": EARLIER,
            },
        )
        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.relationship_memory_review_decisions (
                  decision_id, memory_proposal_id, review_case_id, principal_id,
                  sequence, disposition, corrected_statement, correlation_id,
                  audit_id, decided_at
                ) VALUES (
                  'rdec_cccc0003cccc0003', 'mprop_cccc0003cccc0003',
                  'rvw_cccc0003cccc0003', :principal, 1, 'correct_and_accept',
                  :corrected, 'corr_cccc0003cccc0003',
                  'audit_cccc0003cccc0003', :at
                )
                """
            ),
            {"principal": PRINCIPAL, "corrected": CORRECTED, "at": LATER},
        )

    command.upgrade(_config(), "head")

    with predecessor.begin() as connection:
        assert _phase_b_head_objects(connection) == PHASE_B_HEAD_OBJECTS
        proposal_context = connection.execute(
            text(
                f"SELECT context_links FROM {SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = 'mprop_cccc0003cccc0003'"
            )
        ).scalar_one()
        corrected_payload = connection.execute(
            text(
                f"SELECT corrected_payload FROM "
                f"{SCHEMA}.relationship_memory_review_decisions "
                "WHERE decision_id = 'rdec_cccc0003cccc0003'"
            )
        ).scalar_one()
        assert proposal_context == []
        assert corrected_payload == {
            "statement": CORRECTED,
            "kind": "general_note",
            "structured_value": None,
            "context_links": [],
        }
        with (
            pytest.raises(
                IntegrityError,
                match="append only",
            ),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.relationship_memory_review_decisions "
                    "SET corrected_payload = corrected_payload "
                    "WHERE decision_id = 'rdec_cccc0003cccc0003'"
                )
            )
        with (
            pytest.raises(
                IntegrityError,
                match="a_memory_corrected_payload_matches_its_disposition",
            ),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.relationship_memory_review_decisions (
                      decision_id, memory_proposal_id, review_case_id, principal_id,
                      sequence, disposition, corrected_payload, correlation_id,
                      audit_id, decided_at
                    ) VALUES (
                      'rdec_dddd0004dddd0004', 'mprop_cccc0003cccc0003',
                      'rvw_cccc0003cccc0003', :principal, 2, 'defer',
                      '{{}}'::jsonb, 'corr_dddd0004dddd0004',
                      'audit_dddd0004dddd0004', :at
                    )
                    """
                ),
                {"principal": PRINCIPAL, "at": LATER},
            )

    command.downgrade(_config(), "b64e29a0f7c1")
    with predecessor.connect() as connection:
        assert _phase_b_head_objects(connection) == set()


def test_upgrade_reconciles_version_drift_duplicates_without_deleting_history(
    predecessor: Engine,
) -> None:
    with predecessor.begin() as connection:
        SqlEntityRepository(connection).create(
            PRINCIPAL,
            Entity(
                entity_id=SUBJECT,
                principal_id=PRINCIPAL,
                entity_type=EntityType.PERSON,
                canonical_name=normalize_name("Synthetic Person"),
                display_name="Synthetic Person",
                status=EntityStatus.ACTIVE,
                created_at=EARLIER,
                updated_at=LATER,
                version=2,
            ),
        )
        # Phase B briefly shipped these two additive columns through the live
        # table declaration before this dedicated child migration froze them.
        # Reproduce that legal predecessor shape explicitly; a pristine
        # predecessor without them is exercised by the ordinary upgrade tests.
        connection.execute(
            text(
                f"ALTER TABLE {SCHEMA}.relationship_memory_proposals "
                "ADD COLUMN IF NOT EXISTS expected_subject_version integer, "
                "ADD COLUMN IF NOT EXISTS dedupe_sha256 text"
            )
        )
        connection.execute(
            text(f"DROP INDEX IF EXISTS {SCHEMA}.an_open_equivalent_memory_proposal_is_raised_once")
        )
        connection.execute(
            text(
                f"ALTER TABLE {SCHEMA}.relationship_memory_proposals "
                "ALTER COLUMN dedupe_sha256 DROP NOT NULL"
            )
        )
        insert_proposal = text(
            f"""
            INSERT INTO {SCHEMA}.relationship_memory_proposals (
              memory_proposal_id, principal_id, subject_entity_id,
              expected_subject_version, proposed_kind, proposed_statement,
              proposed_statement_sha256, dedupe_sha256, structured_value, state,
              method, method_version, classification, proposed_at, review_case_id
            ) VALUES (
              :proposal_id, :principal, :subject, :version, 'working_preference',
              :statement, :statement_digest, NULL, NULL, 'needs_review',
              'rule', 'legacy-rule-v1', 'private_local', :at, :case_id
            )
            """
        )
        for values in (
            _proposal_values(WINNER, WINNER_CASE, EARLIER, 1),
            _proposal_values(LOSER, LOSER_CASE, LATER, 2),
        ):
            connection.execute(
                insert_proposal, {**values, "principal": PRINCIPAL, "subject": SUBJECT}
            )
        insert_evidence = text(
            f"""
            INSERT INTO {SCHEMA}.relationship_memory_proposal_evidence (
              proposal_evidence_id, memory_proposal_id, principal_id, role,
              knowledge_id, created_at
            ) VALUES (:evidence_id, :proposal_id, :principal, :role, :source_id, :at)
            """
        )
        for seeded_evidence in (
            ("mpev_aaaa0001aaaa0001", WINNER, "direct", "knw_aaaa0001aaaa0001", EARLIER),
            ("mpev_bbbb0002bbbb0002", LOSER, "direct", "knw_aaaa0001aaaa0001", LATER),
            ("mpev_cccc0003cccc0003", LOSER, "supporting", "knw_bbbb0002bbbb0002", LATER),
        ):
            connection.execute(
                insert_evidence,
                dict(
                    zip(
                        ("evidence_id", "proposal_id", "role", "source_id", "at"),
                        seeded_evidence,
                        strict=True,
                    ),
                    principal=PRINCIPAL,
                ),
            )
        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.relationship_memory_review_decisions (
                  decision_id, memory_proposal_id, review_case_id, principal_id,
                  sequence, disposition, correlation_id, audit_id, decided_at
                ) VALUES (
                  'rdec_bbbb0002bbbb0002', :loser, :case_id, :principal, 1, 'defer',
                  'corr_bbbb0002bbbb0002', 'audit_bbbb0002bbbb0002', :at
                )
                """
            ),
            {"loser": LOSER, "case_id": LOSER_CASE, "principal": PRINCIPAL, "at": LATER},
        )

    command.upgrade(_config(), "head")

    with predecessor.begin() as connection:
        proposals = (
            connection.execute(
                text(
                    f"SELECT memory_proposal_id, state, superseded_by_memory_proposal_id, "
                    f"dedupe_sha256 FROM {SCHEMA}.relationship_memory_proposals "
                    "ORDER BY memory_proposal_id"
                )
            )
            .mappings()
            .all()
        )
        evidence_rows = [
            dict(row)
            for row in connection.execute(
                text(
                    f"SELECT memory_proposal_id, role, knowledge_id FROM "
                    f"{SCHEMA}.relationship_memory_proposal_evidence "
                    "ORDER BY memory_proposal_id, role, knowledge_id"
                )
            ).mappings()
        ]
        decisions = (
            connection.execute(
                text(
                    f"SELECT memory_proposal_id FROM {SCHEMA}.relationship_memory_review_decisions"
                )
            )
            .scalars()
            .all()
        )

        assert len(proposals) == 2
        assert proposals[0]["memory_proposal_id"] == WINNER
        assert proposals[0]["state"] == "needs_review"
        assert proposals[1]["memory_proposal_id"] == LOSER
        assert proposals[1]["state"] == "superseded"
        assert proposals[1]["superseded_by_memory_proposal_id"] == WINNER
        assert proposals[0]["dedupe_sha256"] == proposals[1]["dedupe_sha256"]
        assert evidence_rows == [
            {
                "memory_proposal_id": WINNER,
                "role": "direct",
                "knowledge_id": "knw_aaaa0001aaaa0001",
            },
            {
                "memory_proposal_id": WINNER,
                "role": "supporting",
                "knowledge_id": "knw_bbbb0002bbbb0002",
            },
            {
                "memory_proposal_id": LOSER,
                "role": "direct",
                "knowledge_id": "knw_aaaa0001aaaa0001",
            },
        ]
        assert decisions == [LOSER]

        with (
            pytest.raises(IntegrityError, match="an_open_equivalent_memory_proposal"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA}.relationship_memory_proposals (
                      memory_proposal_id, principal_id, subject_entity_id,
                      origin_subject_entity_id,
                      expected_subject_version, proposed_kind, proposed_statement,
                      proposed_statement_sha256, dedupe_sha256, state, method,
                      method_version, classification, proposed_at, review_case_id
                    ) VALUES (
                      'mprop_cccc0003cccc0003', :principal, :subject, :subject, 2,
                      'working_preference', :statement, :statement_digest, :dedupe,
                      'needs_review', 'rule', 'legacy-rule-v1', 'private_local', :at,
                      'rvw_cccc0003cccc0003'
                    )
                    """
                ),
                {
                    "principal": PRINCIPAL,
                    "subject": SUBJECT,
                    "statement": STATEMENT,
                    "statement_digest": STATEMENT_DIGEST,
                    "dedupe": proposals[0]["dedupe_sha256"],
                    "at": LATER,
                },
            )


@pytest.fixture
def predecessor(empty_database_url: str) -> Iterator[Engine]:
    engine = create_database_engine(empty_database_url)
    try:
        command.upgrade(_config(), "b64e29a0f7c1")
        yield engine
    finally:
        engine.dispose()
