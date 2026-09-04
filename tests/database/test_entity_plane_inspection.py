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
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from scripts.inspect_entity_plane import report
from sqlalchemy import Engine

from my_pa.application.entity_governance import EntityGovernanceService
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.entity import (
    AliasType,
    Assignment,
    AssignmentType,
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
    EntityProposalMethod,
    EntityProposalState,
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
    "Birgitta",
    "a.chen@acme.test",
    "Bob Chen",
    "bob chen",
    #: One value per remaining free-text column on the eight plane tables. Six
    #: of fourteen were planted before, so the same defect one column over
    #: stayed green: adding `entity_aliases.normalized_value` to the report
    #: printed a person's nickname and every test passed, because the alias
    #: plant was `"Ali"` while the stored value is the normalized `"ali"`, and
    #: the scan is a case-sensitive substring test.
    #:
    #: The nickname is `"Birgitta"` rather than something short for a second
    #: reason: `"ali"` is a substring of the report's own `"aliases"` key, so
    #: planting it made the scan fail on the report's structure rather than on
    #: any personal value. A plant has to be distinctive enough that a hit means
    #: what the test says it means.
    "birgitta",
    "Marguerite Okorie",
    "Priyanka Raval",
    "Theodore Lindqvist",
    "Ingrid Vasquez-Thorne",
    "Cornelius Adeyemi-Blackwood",
    #: Planted into `entity_proposals.proposed_by`, which the inspection script
    #: argues at length must never be selected because it is free text that will
    #: carry "a person's name or address the moment anything records who asked
    #: for the change". The fixture used to plant `"resolver"` there — a value
    #: that is not personal — so re-adding the column would have left this scan
    #: green while an operator pasted a person's name into a ticket. The other
    #: four personal columns were planted and scanned; this was the one gap.
    "Dana Whitfield",
    #: Planted into `entity_observations.mention_display_name`, the fifteenth
    #: free-text column and the one `f3a8c1d7e592` designates as **the only
    #: field `entities.unresolved_mentions` publishes**. It arrived with no
    #: plant, so this scan was one column short of the contract the comment
    #: above states — and short on the highest-disclosure-risk free text on the
    #: plane, which is the same defect that comment records happening at
    #: `entity_aliases.normalized_value`. A hand-maintained canary list is
    #: derived from nothing and cannot notice a new column; only a plant can.
    "Rosalind Achterberg",
)

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def populated(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
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
                    normalized_value=normalize_name("Birgitta"),
                    display_value="Birgitta",
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
                    mention_display_name="Rosalind Achterberg",
                    source_id=SOURCE,
                    source_object_id=OBJECT,
                    source_version_id=VERSION,
                    observed_at=WHEN,
                    recorded_at=WHEN,
                ),
            )
            EntityGovernanceService(repository).propose(
                PRINCIPAL_A,
                kind=EntityProposalKind.MERGE_ENTITIES,
                payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
                observation_ids=(),
                proposed_by="Dana Whitfield",
                method=EntityProposalMethod.DETERMINISTIC,
                method_version="1",
                at=WHEN,
            )
            # An assignment, so `role`, `discipline` and `responsibility_class`
            # are non-empty. Zero rows made three free-text columns unplantable:
            # selecting any of them would have printed nothing and the scan
            # would have stayed green on an empty table.
            repository.record_assignment(
                PRINCIPAL_A,
                Assignment(
                    assignment_id="asn_aaaa0001aaaa0001",
                    entity_id=ALICE,
                    assignment_type=AssignmentType.EMPLOYMENT,
                    principal_id=PRINCIPAL_A,
                    role="Marguerite Okorie's deputy",
                    discipline="Structural, reporting to Priyanka Raval",
                    responsibility_class="Signs for Theodore Lindqvist",
                ),
            )
            # A decided proposal and its merge record, so `decided_by`,
            # `decision_reason` and the merge `reason` carry text. `decided_by`
            # is the same free-text "who made this call" column the script's
            # docstring argues must never be selected, and it was unplanted.
            rejected = EntityGovernanceService(repository).propose(
                PRINCIPAL_A,
                kind=EntityProposalKind.RECORD_ALIAS,
                payload={
                    "entity_id": ALICE,
                    "alias_type": "preferred_name",
                    "display_value": "Birgitta",
                },
                observation_ids=(),
                proposed_by="Ingrid Vasquez-Thorne",
                method=EntityProposalMethod.DETERMINISTIC,
                method_version="1",
                at=WHEN,
            )
            repository.decide_proposal(
                PRINCIPAL_A,
                replace(
                    repository.proposal(PRINCIPAL_A, rejected.proposal_id),
                    state=EntityProposalState.REJECTED,
                    decided_by="Ingrid Vasquez-Thorne",
                    decided_at=WHEN,
                    decision_reason="Refused by Cornelius Adeyemi-Blackwood",
                ),
            )
            # A third proposal makes the open queue contain two independently
            # reviewable producer candidates. Producers cannot self-promote, so
            # even the threshold-eligible alias candidate opens a Review case
            # and is stored `needs_review`.
            EntityGovernanceService(repository).propose(
                PRINCIPAL_A,
                kind=EntityProposalKind.RECORD_ALIAS,
                payload={
                    "entity_id": ALICE,
                    "alias_type": "nickname",
                    "display_value": "Ali",
                },
                observation_ids=(),
                proposed_by="Ingrid Vasquez-Thorne",
                method=EntityProposalMethod.DETERMINISTIC,
                method_version="1",
                at=WHEN,
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
        "assignments": 1,
        "relationships": 0,
        "observations": 1,
        "proposals": 3,
        "merges": 0,
    }
    assert produced["entities_by_status"] == {"active": 2}
    assert produced["entities_by_type"] == {"person": 2}
    assert produced["observations_by_kind"] == {"message_participant": 1}
    assert produced["proposals_by_state"] == {
        "needs_review": 2,
        "rejected": 1,
    }


def test_the_report_shows_the_unresolved_queue(populated: Engine) -> None:
    assert report(populated, PRINCIPAL_A)["unresolved_mentions"] == 1


def test_the_report_lists_the_open_proposals_without_their_payloads(
    populated: Engine,
) -> None:
    """An operator sees that a decision is waiting, not what it would join."""
    open_proposals = report(populated, PRINCIPAL_A)["open_proposals"]
    assert isinstance(open_proposals, list)
    assert len(open_proposals) == 2
    # The identifiers are checked for shape rather than against literals: the
    # server mints them now, so a literal here would be this test naming a value
    # only the server may choose. `validate_identifier` is the same check the
    # record applies, so a mint of the wrong kind still reddens.
    for listed in open_proposals:
        validate_identifier(str(listed["proposal_id"]), IdKind.ENTITY_PROPOSAL)
        assert "payload" not in listed
    assert {listed["kind"] for listed in open_proposals} == {"merge_entities", "record_alias"}
    assert ALICE not in json.dumps(open_proposals)


def test_the_open_queue_contains_every_undecided_producer_candidate(populated: Engine) -> None:
    """The queue is the *population*, not one state literal that used to name it.

    This is the regression `WP-RI-B-05` shipped and the corrective cycle caught.
    Producer-originated candidates all require review now. This still asserts
    the stored state rather than only a count so a future queue predicate cannot
    silently omit the state every producer writes.
    """
    listed = report(populated, PRINCIPAL_A)["open_proposals"]
    with populated.connect() as connection:
        repository = SqlEntityRepository(connection)
        held = [repository.proposal(PRINCIPAL_A, str(row["proposal_id"])) for row in listed]
    assert all(proposal is not None for proposal in held)
    states = {proposal.state for proposal in held if proposal is not None}
    assert states == {EntityProposalState.NEEDS_REVIEW}
    # And every listed proposal is genuinely undecided, so the report cannot
    # start listing decided rows and pass on the set assertion alone.
    assert all(proposal.is_open for proposal in held if proposal is not None)


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
