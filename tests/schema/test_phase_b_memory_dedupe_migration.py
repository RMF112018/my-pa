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
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
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


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def predecessor(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')

    def administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[call-overload]

    engine: Engine | None = None
    try:
        administer(drop, text(f'CREATE DATABASE "{DATABASE}"'))
        url = configured.set(database=DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        engine = create_database_engine(url)
        command.upgrade(_config(), "b64e29a0f7c1")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        administer(drop)
        maintenance.dispose()


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
                      expected_subject_version, proposed_kind, proposed_statement,
                      proposed_statement_sha256, dedupe_sha256, state, method,
                      method_version, classification, proposed_at, review_case_id
                    ) VALUES (
                      'mprop_cccc0003cccc0003', :principal, :subject, 2,
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
