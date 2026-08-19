"""The operator inspection report, against a real database.

Two claims, and the second is the one worth a test.

**It reports the plane accurately** — counts, statuses, the unresolved queue,
the open proposals.

**It prints no personal data.** Names, addresses, alias text and observed values
are in the tables it reads and must not be in what it writes: `AGENTS.md`
section 5 keeps contact details out of logs, and an operator report is a log
somebody will paste into a ticket. So the report is scanned for every piece of
personal data the fixture planted, and every one must be absent.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from scripts.inspect_entity_plane import report
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.entity_governance import EntityGovernanceService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import (
    AliasType,
    Entity,
    EntityAlias,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.governance import (
    EntityObservation,
    EntityProposalKind,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_entity_inspection_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
ALICE_TWO: Final = "ent_bbbb0002bbbb0002"
BOB: Final = "ent_cccc0003cccc0003"

#: Every piece of personal data the fixture plants. The report must contain none
#: of it — listed here so the scan is exhaustive by construction rather than by
#: whichever string a test author happened to remember.
PLANTED_PERSONAL_DATA: Final[tuple[str, ...]] = (
    "Alice Chen",
    "alice chen",
    "Ali",
    "a.chen@acme.test",
    "Bob Chen",
    "bob chen",
    #: Planted into `entity_proposals.proposed_by`, which the inspection script
    #: argues at length must never be selected because it is free text that will
    #: carry "a person's name or address the moment anything records who asked
    #: for the change". The fixture used to plant `"resolver"` there — a value
    #: that is not personal — so re-adding the column would have left this scan
    #: green while an operator pasted a person's name into a ticket. The other
    #: four personal columns were planted and scanned; this was the one gap.
    "Dana Whitfield",
)

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def populated(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            repository = SqlEntityRepository(connection)
            for entity_id, principal_id, name, kind in (
                (ALICE, PRINCIPAL_A, "Alice Chen", EntityType.PERSON),
                (ALICE_TWO, PRINCIPAL_A, "Alice Chen", EntityType.PERSON),
                (BOB, PRINCIPAL_B, "Bob Chen", EntityType.PERSON),
            ):
                repository.create(
                    principal_id,
                    Entity(
                        entity_id=entity_id,
                        principal_id=principal_id,
                        entity_type=kind,
                        canonical_name=normalize_name(name),
                        display_name=name,
                        status=EntityStatus.ACTIVE,
                        created_at=WHEN,
                        updated_at=WHEN,
                        version=1,
                    ),
                )
            repository.record_alias(
                PRINCIPAL_A,
                EntityAlias(
                    alias_id="eals_aaaa0001aaaa0001",
                    entity_id=ALICE,
                    alias_type=AliasType.NICKNAME,
                    normalized_value=normalize_name("Ali"),
                    display_value="Ali",
                    principal_id=PRINCIPAL_A,
                ),
            )
            repository.bind_identifier(
                PRINCIPAL_A,
                ALICE,
                ExternalIdentifier(
                    identifier_id="xid_aaaa0001aaaa0001",
                    entity_id=ALICE,
                    namespace=ExternalIdentifierNamespace.EMAIL,
                    normalized_value=normalize_identifier(
                        ExternalIdentifierNamespace.EMAIL, "a.chen@acme.test"
                    ),
                    display_value="a.chen@acme.test",
                    principal_id=PRINCIPAL_A,
                    verified=True,
                ),
            )
            repository.record_observation(
                PRINCIPAL_A,
                EntityObservation(
                    observation_id="eobs_aaaa0001aaaa0001",
                    principal_id=PRINCIPAL_A,
                    kind=ObservationKind.MESSAGE_PARTICIPANT,
                    observed_value="Alice Chen <a.chen@acme.test>",
                    normalized_value=normalize_name("Alice Chen"),
                    source_id=SOURCE,
                    source_object_id=OBJECT,
                    source_version_id=VERSION,
                    observed_at=WHEN,
                    recorded_at=WHEN,
                ),
            )
            EntityGovernanceService(repository).propose(
                PRINCIPAL_A,
                proposal_id="eprp_aaaa0001aaaa0001",
                kind=EntityProposalKind.MERGE_ENTITIES,
                payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
                observation_ids=(),
                proposed_by="Dana Whitfield",
                proposed_at=WHEN,
            )
        yield engine
    finally:
        engine.dispose()


def test_the_report_counts_the_plane(populated: Engine) -> None:
    produced = report(populated, PRINCIPAL_A)
    assert produced["counts"] == {
        "entities": 2,
        "aliases": 1,
        "external_identifiers": 1,
        "assignments": 0,
        "relationships": 0,
        "observations": 1,
        "proposals": 1,
        "merges": 0,
    }
    assert produced["entities_by_status"] == {"active": 2}
    assert produced["entities_by_type"] == {"person": 2}
    assert produced["observations_by_kind"] == {"message_participant": 1}
    assert produced["proposals_by_state"] == {"proposed": 1}


def test_the_report_shows_the_unresolved_queue(populated: Engine) -> None:
    assert report(populated, PRINCIPAL_A)["unresolved_mentions"] == 1


def test_the_report_lists_the_open_proposal_without_its_payload(populated: Engine) -> None:
    """An operator sees that a decision is waiting, not what it would join."""
    open_proposals = report(populated, PRINCIPAL_A)["open_proposals"]
    assert isinstance(open_proposals, list)
    assert [entry["proposal_id"] for entry in open_proposals] == ["eprp_aaaa0001aaaa0001"]
    assert open_proposals[0]["kind"] == "merge_entities"
    assert "payload" not in open_proposals[0]
    assert ALICE not in json.dumps(open_proposals)


def test_the_report_prints_no_personal_data(populated: Engine) -> None:
    """The claim the module docstring makes, checked against what it planted."""
    rendered = json.dumps(report(populated, PRINCIPAL_A))
    leaked = [planted for planted in PLANTED_PERSONAL_DATA if planted in rendered]
    assert leaked == []


def test_the_report_cannot_see_another_principals_plane(populated: Engine) -> None:
    produced = report(populated, PRINCIPAL_B)
    assert produced["counts"]["entities"] == 1
    assert BOB not in json.dumps(produced)


def test_the_report_of_an_unknown_principal_is_empty_rather_than_an_error(
    populated: Engine,
) -> None:
    """A Principal with no plane has a plane with nothing in it."""
    produced = report(populated, "prn_cccc0003cccc0003cccc0003")
    assert produced["counts"]["entities"] == 0
    assert produced["unresolved_mentions"] == 0
    assert produced["open_proposals"] == []


def test_producing_the_report_changes_nothing(populated: Engine) -> None:
    """READ-ONLY, asserted rather than asserted-in-a-docstring."""
    before = report(populated, PRINCIPAL_A)
    for _ in range(3):
        report(populated, PRINCIPAL_A)
    assert report(populated, PRINCIPAL_A) == before
