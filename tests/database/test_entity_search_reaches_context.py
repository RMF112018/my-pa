"""`entities.search`'s widened matching against real PostgreSQL (RI-ENT-WP-09).

`tests/unit/test_entity_search_reaches_context.py` makes the same claims against
the in-memory `_Entities` fake, which mirrors this matching in Python. This
module makes them against the statement that actually runs: one
partition-guarded, keyset-paged `SELECT` whose `WHERE` carries five correlated
`EXISTS` subqueries beside the two original `ILIKE`s.

Four things only the server can settle, which is why this file exists:

* **The correlated subqueries correlate to the right row.** `entities` appears
  twice in this statement -- once as the outer `FROM` and once inside the
  affiliation subquery as the partition-scoped `affiliated_organization` derived
  table, reached through `organization_entity_id`. A Python double cannot get
  that wrong in the way SQL can, because SQL will silently bind an ambiguous
  reference to the nearest relation in scope.
* **`ESCAPE` is real.** `_contains` escapes `%` and `_` against a stated escape
  character, and only PostgreSQL's `LIKE` engine can show that the escape took.
  The fake's `in` has no metacharacters to escape in the first place, so its
  version of this claim is a statement about agreement, not about escaping.
* **The relationship-type `label` is the seeded one.** `entity_relationship_types`
  is a global taxonomy with no `principal_id`, seeded by migration; the fake
  holds no taxonomy rows at all and matches the type *code* instead. The label
  is read back out of the table here rather than spelled as a literal, so this
  test cannot drift from the seed it is measuring.
* **The partition holds on every child table.** Each subquery carries its own
  `_mine(...)`. A subquery correlated on `entity_id` alone would reach another
  Principal's child rows and let them decide that this Principal's entity
  matches, which is the cross-partition false join this plane exists to avoid.

**Written but not executed.** The WP-09 database gate was closed while this was
authored -- the Manager held the machine-wide serial database tier -- so this
module has never been run. It is committed unrun deliberately, and the handoff
says so. Nothing here may be treated as a passing measurement until it is.

Every identity is synthetic and every address is `example.invalid`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import (
    AffiliationTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    Entity,
    EntityCommunicationMethod,
    EntityName,
    EntityProjectParticipation,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    NameTypeCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    normalize_communication_value,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.tables import entity_relationship_types

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]

#: Distinct from every other database-tier fixture's disposable database, so
#: this suite cannot drop one another suite is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_search_reaches_context_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: Each entity is named for nothing any query below spells, so a hit can only
#: have arrived through one of the five added match paths.
NAMED: Final = "ent_named0001named001"
ADDRESSED: Final = "ent_addr0002addr0002"
EMPLOYED: Final = "ent_empl0003empl0003"
STAFFED: Final = "ent_staf0004staf0004"
CONNECTED: Final = "ent_conn0005conn0005"
EMPLOYER: Final = "ent_orga0006orga0006"
COUNTERPARTY: Final = "ent_ctpy0007ctpy0007"
WITHHELD: Final = "ent_hidn0008hidn0008"
LITERAL: Final = "ent_ltrl0009ltrl0009"
DECOY: Final = "ent_dcoy0010dcoy0010"
PROJECT: Final = "ent_proj0012proj0012"
FOREIGN: Final = "ent_frgn0011frgn0011"
FOREIGN_PEER: Final = "ent_frgp0013frgp0013"

TRADING_NAME: Final = "Harbour Ironworks"
WITHHELD_ALIAS: Final = "Sunset Consulting"
WITHHELD_HISTORICAL: Final = "Sunrise Partners"
MAIL: Final = "rowan@ferrybridge.example.invalid"
JOB_TITLE: Final = "Chief Millwright"
ROLE_TEXT: Final = "Commissioning Lead"
PROJECT_NAME: Final = "Saltmarsh Depot"
WILDCARD_NAME: Final = "50%_off"
DECOY_NAME: Final = "50XYoff"

#: The edge whose seeded label the relationship-type path is measured through.
#: The label itself is read back from `entity_relationship_types` rather than
#: written here, because the seed is the migration's fact and not this test's.
EDGE_TYPE: Final = EntityRelationshipType.SUBCONTRACTOR_TO

WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 9, 1, 13, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
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
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _entity(
    entity_id: str,
    name: str,
    *,
    principal_id: str = PRINCIPAL_A,
    entity_type: EntityType = EntityType.PERSON,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _name(
    entity_name_id: str,
    entity_id: str,
    display_value: str,
    name_type_code: NameTypeCode,
    *,
    principal_id: str = PRINCIPAL_A,
) -> EntityName:
    return EntityName(
        entity_name_id=entity_name_id,
        entity_id=entity_id,
        principal_id=principal_id,
        name_type_code=name_type_code,
        display_value=display_value,
        normalized_value=normalize_name(display_value),
    )


def _method(
    communication_method_id: str,
    entity_id: str,
    value: str,
    *,
    principal_id: str = PRINCIPAL_A,
) -> EntityCommunicationMethod:
    return EntityCommunicationMethod(
        communication_method_id=communication_method_id,
        entity_id=entity_id,
        principal_id=principal_id,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.OFFICE,
        normalized_value=normalize_communication_value(CommunicationMethodTypeCode.EMAIL, value),
        display_value=value,
        verification_status_code=CommunicationVerificationStatusCode.UNRESOLVED,
    )


def _affiliation(
    affiliation_id: str,
    person_entity_id: str,
    organization_entity_id: str | None,
    *,
    job_title: str | None = None,
    principal_id: str = PRINCIPAL_A,
) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=affiliation_id,
        principal_id=principal_id,
        person_entity_id=person_entity_id,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        organization_entity_id=organization_entity_id,
        job_title=job_title,
    )


def _participation(
    participation_id: str,
    participant_entity_id: str,
    *,
    role_text: str | None = None,
    project_display_name: str = PROJECT_NAME,
    principal_id: str = PRINCIPAL_A,
) -> EntityProjectParticipation:
    return EntityProjectParticipation(
        participation_id=participation_id,
        principal_id=principal_id,
        project_entity_id=PROJECT,
        participant_entity_id=participant_entity_id,
        project_display_name=project_display_name,
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        role_text=role_text,
    )


def _edge(
    relationship_id: str,
    from_entity_id: str,
    to_entity_id: str,
    *,
    principal_id: str = PRINCIPAL_A,
) -> EntityRelationship:
    return EntityRelationship(
        relationship_id=relationship_id,
        from_entity_id=from_entity_id,
        relationship_type=EDGE_TYPE,
        to_entity_id=to_entity_id,
        principal_id=principal_id,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """One entity per match path, plus a foreign twin of every child row."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        for entity in (
            _entity(NAMED, "Kalvedge"),
            _entity(ADDRESSED, "Morrowin"),
            _entity(EMPLOYED, "Threndal"),
            _entity(STAFFED, "Oskarven"),
            _entity(CONNECTED, "Piltravon"),
            _entity(EMPLOYER, "Vasqueline", entity_type=EntityType.ORGANIZATION),
            _entity(COUNTERPARTY, "Wendrilo", entity_type=EntityType.ORGANIZATION),
            _entity(WITHHELD, "Zorrandel"),
            _entity(LITERAL, "Quillmara"),
            _entity(DECOY, "Bexforden"),
            _entity(PROJECT, "Undercroft", entity_type=EntityType.PROJECT),
        ):
            repository.create(PRINCIPAL_A, entity)
        for foreign in (
            _entity(FOREIGN, "Yalvenmar", principal_id=PRINCIPAL_B),
            _entity(FOREIGN_PEER, "Xantheria", principal_id=PRINCIPAL_B),
        ):
            repository.create(PRINCIPAL_B, foreign)

    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        for record in (
            _name("enam_trade0001trade01", NAMED, TRADING_NAME, NameTypeCode.DBA),
            _name("enam_alias0002alias0", WITHHELD, WITHHELD_ALIAS, NameTypeCode.ALIAS),
            _name(
                "enam_hist0003histori",
                WITHHELD,
                WITHHELD_HISTORICAL,
                NameTypeCode.HISTORICAL_NAME,
            ),
            _name("enam_liter0006litera", LITERAL, WILDCARD_NAME, NameTypeCode.BRAND),
            _name("enam_decoy0007decoy0", DECOY, DECOY_NAME, NameTypeCode.BRAND),
        ):
            repository.record_entity_name(PRINCIPAL_A, record)
        repository.record_entity_name(
            PRINCIPAL_B,
            _name(
                "enam_forei0005foreig",
                FOREIGN,
                TRADING_NAME,
                NameTypeCode.DBA,
                principal_id=PRINCIPAL_B,
            ),
        )
        repository.record_communication_method(
            PRINCIPAL_A, _method("ecmm_mail0001mail001", ADDRESSED, MAIL)
        )
        repository.record_communication_method(
            PRINCIPAL_B,
            _method("ecmm_forei0003foreig", FOREIGN, MAIL, principal_id=PRINCIPAL_B),
        )
        repository.record_person_organization_affiliation(
            PRINCIPAL_A,
            _affiliation("poaf_empl0001empl001", EMPLOYED, EMPLOYER, job_title=JOB_TITLE),
        )
        repository.record_person_organization_affiliation(
            PRINCIPAL_B,
            _affiliation(
                "poaf_forei0003foreig",
                FOREIGN,
                None,
                job_title=JOB_TITLE,
                principal_id=PRINCIPAL_B,
            ),
        )
        repository.record_project_participation(
            PRINCIPAL_A, _participation("eppt_staf0001staf001", STAFFED, role_text=ROLE_TEXT)
        )
        repository.record_relationship(
            PRINCIPAL_A, _edge("erel_conn0001conn001", CONNECTED, COUNTERPARTY)
        )
        repository.record_relationship(
            PRINCIPAL_B,
            _edge("erel_forei0003foreig", FOREIGN, FOREIGN_PEER, principal_id=PRINCIPAL_B),
        )
    return migrated_engine


def _found(
    engine: Engine, query: str, principal_id: str = PRINCIPAL_A, **kwargs: object
) -> set[str]:
    with engine.begin() as connection:
        summaries = SqlEntityRepository(connection).search(principal_id, query, **kwargs)  # type: ignore[arg-type]
    return {summary.entity_id for summary in summaries}


def _seeded_label(engine: Engine) -> str:
    """The label the migration seeded for `EDGE_TYPE`, read rather than assumed."""
    with engine.begin() as connection:
        label = connection.execute(
            select(entity_relationship_types.c.label).where(
                entity_relationship_types.c.relationship_type_code == EDGE_TYPE.value
            )
        ).scalar_one()
    return str(label)


# --- the five added paths ----------------------------------------------------


def test_a_typed_name_reaches_an_entity_its_canonical_name_does_not(staged: Engine) -> None:
    assert _found(staged, "Ironworks") == {NAMED}


def test_a_communication_value_and_its_domain_both_reach_the_entity(staged: Engine) -> None:
    """Domain matching is the substring match, not a parser and not a column."""
    assert _found(staged, MAIL) == {ADDRESSED}
    assert _found(staged, "ferrybridge.example.invalid") == {ADDRESSED}


def test_an_affiliation_reaches_a_person_by_title_and_by_employer_name(staged: Engine) -> None:
    """The employer's name lives on a *second* `entities` row.

    This is the assertion the `affiliated_organization` derived table exists for,
    and the one a mis-correlated subquery fails: bound to the outer `entities`
    instead, the predicate would read the person's own name and match nothing.
    """
    assert _found(staged, "Millwright") == {EMPLOYED}
    assert _found(staged, "Vasqueline") == {EMPLOYED, EMPLOYER}


def test_a_project_role_reaches_a_participant_by_role_and_by_project(staged: Engine) -> None:
    assert _found(staged, "Commissioning") == {STAFFED}
    assert _found(staged, "Saltmarsh") == {STAFFED}


def test_a_relationship_type_label_reaches_both_ends_of_the_edge(staged: Engine) -> None:
    """The seeded label, read from the taxonomy rather than spelled here.

    `entity_relationship_types` carries no `principal_id`, so the partition is
    imposed on `entity_relationships`; the label is the only column of the
    taxonomy this match reads.
    """
    label = _seeded_label(staged)
    assert _found(staged, label) == {CONNECTED, COUNTERPARTY}


# --- WP09-DECISION-1's boundary ----------------------------------------------


def test_an_alias_typed_name_is_unreachable_through_search(staged: Engine) -> None:
    assert _found(staged, WITHHELD_ALIAS) == set()


def test_a_historical_typed_name_is_unreachable_through_search(staged: Engine) -> None:
    assert _found(staged, WITHHELD_HISTORICAL) == set()


def test_the_withheld_entity_is_reachable_by_its_own_display_name(staged: Engine) -> None:
    """Anti-vacuity: the two claims above would hold for an absent row too."""
    assert _found(staged, "Zorrandel") == {WITHHELD}


# --- The active-state filter on the widened search ------------------------
#
# `SqlEntityRepository.search`'s typed-name subquery restricts to
# `EntityNameState.ACTIVE`, and its own comment states why: "a retired or
# superseded name form is a name this entity no longer carries, and serving it
# to a browse query is the disclosure the alias decision refuses." That filter
# was untested until these two tests. Removing it failed nothing in this
# module -- proven by mutation, deleting the line and watching all nineteen
# tests stay green -- which is the same shape of gap that let a broken
# `correct_affiliation` reach independent review in RI-ENT-WP-08: a documented
# invariant with nothing holding it.
#
# Each test asserts reachability BEFORE the lifecycle transition as well as
# after, so neither can pass because the row was never findable in the first
# place.

RETIRED_NAME: Final = "Quenthivar"
SUPERSEDED_NAME: Final = "Brellowyn"
SUCCESSOR_NAME: Final = "Kaddrimore"
"""Deliberately not a superstring of `SUPERSEDED_NAME`: `search` is a
substring match, so a successor named "Brellowyn Reborn" would be found by
a query for "Brellowyn" and the supersession assertion would fail for a
reason that has nothing to do with the active-state filter under test."""


def test_a_retired_typed_name_is_unreachable_through_search(staged: Engine) -> None:
    name_id = "enam_retir0008retire"
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(
            PRINCIPAL_A, _name(name_id, NAMED, RETIRED_NAME, NameTypeCode.OPERATING)
        )
    assert _found(staged, RETIRED_NAME) == {NAMED}

    with staged.begin() as connection:
        SqlEntityRepository(connection).retire_entity_name(
            PRINCIPAL_A, entity_name_id=name_id, expected_version=1, at=LATER
        )
    assert _found(staged, RETIRED_NAME) == set()
    assert _found(staged, TRADING_NAME) == {NAMED}


def test_a_superseded_typed_name_is_unreachable_and_its_successor_is(staged: Engine) -> None:
    name_id = "enam_super0009supers"
    successor_id = "enam_succe0010succes"
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(
            PRINCIPAL_A, _name(name_id, NAMED, SUPERSEDED_NAME, NameTypeCode.ACRONYM)
        )
    assert _found(staged, SUPERSEDED_NAME) == {NAMED}

    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=name_id,
            successor=_name(successor_id, NAMED, SUCCESSOR_NAME, NameTypeCode.ACRONYM),
            expected_version=1,
            at=LATER,
        )
    assert _found(staged, SUPERSEDED_NAME) == set()
    assert _found(staged, SUCCESSOR_NAME) == {NAMED}


# --- the partition, asserted in both directions ------------------------------


@pytest.mark.parametrize("query", [TRADING_NAME, MAIL, JOB_TITLE, ROLE_TEXT])
def test_a_foreign_child_row_decides_nothing_in_this_partition(staged: Engine, query: str) -> None:
    """Each subquery is scoped as well as correlated.

    Asserted from both sides, on `test_entity_repository`'s terms: A cannot see
    B's row, and B can see its own through the same read -- so the claim cannot
    pass by reading an empty table.
    """
    assert FOREIGN not in _found(staged, query)
    assert _found(staged, query, PRINCIPAL_B) <= {FOREIGN, FOREIGN_PEER}


def test_the_other_principal_reaches_its_own_typed_name(staged: Engine) -> None:
    assert _found(staged, TRADING_NAME, PRINCIPAL_B) == {FOREIGN}


# --- ESCAPE, which only the server's LIKE engine can settle -------------------


def test_a_like_metacharacter_in_the_query_is_escaped(staged: Engine) -> None:
    """`_contains`' `ESCAPE '\\\\'` convention, on every one of the seven matches.

    Under `LIKE` semantics `5_%off` matches both stored names; escaped, it
    matches neither. A bare `%` unescaped would select the whole partition.
    """
    assert _found(staged, DECOY_NAME) == {DECOY}
    assert _found(staged, WILDCARD_NAME) == {LITERAL}
    assert _found(staged, "%") == {LITERAL}
    assert _found(staged, "5_%off") == set()


# --- the keyset and the cursor survive the widening ---------------------------


def test_the_widened_match_still_pages_by_its_own_keyset(staged: Engine) -> None:
    """The `(canonical_name, entity_id)` walk, over rows reached five ways."""
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        first = repository.search(PRINCIPAL_A, "e", limit=3)
        assert len(first) == 3
        following = repository.search(
            PRINCIPAL_A, "e", limit=3, after_entity_id=first[-1].entity_id
        )
        whole = repository.search(PRINCIPAL_A, "e", limit=50)
    walked = [summary.entity_id for summary in (*first, *following)]
    assert len(walked) == len(set(walked))
    assert walked == [summary.entity_id for summary in whole][: len(walked)]


def test_a_cursor_naming_another_principals_entity_is_refused(staged: Engine) -> None:
    from my_pa.contracts.ports import UnknownScopeError

    with staged.begin() as connection, pytest.raises(UnknownScopeError):
        SqlEntityRepository(connection).search(PRINCIPAL_A, "e", after_entity_id=FOREIGN)


def test_an_entity_type_filter_still_narrows_a_context_match(staged: Engine) -> None:
    assert _found(staged, "Vasqueline", entity_type=EntityType.ORGANIZATION) == {EMPLOYER}


# --- RI-AC-038: the disambiguators the page carries back ----------------------


def test_a_summary_carries_the_current_employer_and_the_current_project(
    staged: Engine,
) -> None:
    """The two bounded reads that follow the page, against real rows.

    `tests/unit/test_entity_search_disambiguators.py` proves there are exactly
    two of them however large the page is, by counting statements against a
    recording connection. What it cannot show is that the `row_number()` window
    and the joined `current_organization` derived table produce the right
    values on a real server, which is what this asserts.
    """
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        (employed,) = repository.search(PRINCIPAL_A, "Threndal")
        (staffed,) = repository.search(PRINCIPAL_A, "Oskarven")
        (unattached,) = repository.search(PRINCIPAL_A, "Kalvedge")
    assert employed.affiliated_organizations == ("Vasqueline",)
    assert staffed.project_roles == (f"{ROLE_TEXT} on {PROJECT_NAME}",)
    # Empty rather than absent: an entity with neither family is an ordinary
    # row, and a caller reading the field does not have to tell "none" from
    # "not carried".
    assert unattached.affiliated_organizations == ()
    assert unattached.project_roles == ()


def test_the_disambiguator_reads_stay_inside_the_partition(staged: Engine) -> None:
    """B's affiliation names no organization, and A's rows are not reachable from B.

    The disambiguator reads are keyed by the page's identifiers, so the leak
    they could carry is not another Principal's *entity* but another
    Principal's *organization name* joined onto one of these rows. Asserted by
    reading the same families as B and getting only B's own answer.
    """
    with staged.begin() as connection:
        theirs = SqlEntityRepository(connection).search(PRINCIPAL_B, "Yalvenmar")
    assert [summary.entity_id for summary in theirs] == [FOREIGN]
    assert theirs[0].affiliated_organizations == ()
