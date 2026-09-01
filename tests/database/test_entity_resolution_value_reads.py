"""The two normalized-value resolution reads against real PostgreSQL (RI-ENT-WP-09).

`entities_by_typed_name` and `entities_by_communication_value` answer the
question resolution asks -- "who, if anyone, is called this" / "who, if anyone,
is reachable here" -- and this module proves the four properties that answer's
safety rests on, against real statements, a real partition predicate and the
real partial unique indexes over `state = 'active'`:

* **Every claimant comes back.** A value two entities both claim returns both
  rows. This is the property a page could break: resolution decides whether a
  value is contested by counting claimants, so a read that could drop one turns
  a genuinely contested name into a clean match.
* **A superseded row and a retired row are not matched.** Both families carry an
  explicit `active`/`retired`/`superseded` lifecycle that WP-08's correction
  path drives. A superseded row holds a value the Principal has already
  corrected away; a retired row holds one they withdrew. Matching either would
  hand back, as evidence of identity today, exactly the value the Principal
  said to stop using. **This is a deliberate divergence from
  `entities_by_alias`, which applies no lifecycle filter**, and it is asserted
  here rather than left to a reader to infer from the SQL.
* **Another Principal's row is unreachable.** Asserted in both directions each
  time, on `test_entity_repository`'s terms: a foreign row must be answered
  exactly as an absent one, and the other Principal must be able to see its own
  row through the same read, so the assertion cannot pass by reading an empty
  table.
* **The matched child row comes back beside the entity, carrying its own
  lifecycle.** `entities`, `entity_names` and `entity_communication_methods` all
  declare `version` and `updated_at`, and a `Row` read by attribute answers with
  the *first* column of that name in the statement. So the fixtures give the
  entity and the child deliberately different values, exactly as
  `test_entity_repository`'s joined identifier and alias tests do, and a read
  that answered with the entity's version cannot pass here by coincidence.

Effective dating is deliberately absent from these assertions: it is not this
repository's to apply. `effective_from`/`effective_to` are judged by the service
against the caller's `as_of`, and the reads return the rows the service judges.

Every identity here is synthetic and every address is `example.invalid`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import (
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    Entity,
    EntityCommunicationMethod,
    EntityCommunicationMethodState,
    EntityName,
    EntityNameState,
    EntityStatus,
    EntityType,
    NameTypeCode,
    normalize_communication_value,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]

#: A name distinct from every other database-tier fixture's disposable
#: database, so this suite can run alongside them without one dropping the
#: database another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_resolution_value_reads_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: Two organizations of A that both claim the contested value, and one of B
#: that claims it too. `ORG_ONE` sorts before `ORG_TWO`, which is the order
#: both reads promise.
ORG_ONE: Final = "ent_aaaa0001aaaa0001"
ORG_TWO: Final = "ent_bbbb0002bbbb0002"
FOREIGN_ORG: Final = "ent_cccc0003cccc0003"

CONTESTED_NAME: Final = "Harbour Consulting Group"
CONTESTED_ADDRESS: Final = "shared@example.invalid"
WITHDRAWN_NAME: Final = "Withdrawn Trading Name"
WITHDRAWN_ADDRESS: Final = "withdrawn@example.invalid"
STALE_NAME: Final = "Superseded Brand Name"
STALE_ADDRESS: Final = "stale@example.invalid"
CORRECTED_NAME: Final = "Corrected Brand Name"
CORRECTED_ADDRESS: Final = "corrected@example.invalid"

NAME_ONE: Final = "enam_aaaa0001aaaa0001"
NAME_TWO: Final = "enam_bbbb0002bbbb0002"
NAME_THREE: Final = "enam_cccc0003cccc0003"
NAME_FOUR: Final = "enam_dddd0004dddd0004"
NAME_FIVE: Final = "enam_eeee0005eeee0005"
NAME_SIX: Final = "enam_ffff0006ffff0006"

METHOD_ONE: Final = "ecmm_aaaa0001aaaa0001"
METHOD_TWO: Final = "ecmm_bbbb0002bbbb0002"
METHOD_THREE: Final = "ecmm_cccc0003cccc0003"
METHOD_FOUR: Final = "ecmm_dddd0004dddd0004"
METHOD_FIVE: Final = "ecmm_eeee0005eeee0005"
METHOD_SIX: Final = "ecmm_ffff0006ffff0006"

WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

#: The entity and the child are revised at different moments and to different
#: versions, so a joined read that answered with the *entity's* column cannot
#: pass by coincidence. `test_entity_repository` states the collision this
#: guards against in full, over the same `_ChildRow` machinery.
ENTITY_REVISED: Final = datetime(2026, 9, 2, 12, tzinfo=UTC)
CHILD_REVISED: Final = datetime(2026, 9, 3, 12, tzinfo=UTC)
ENTITY_VERSION: Final = 7
CHILD_VERSION: Final = 3


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


def _entity(entity_id: str, name: str, principal_id: str) -> Entity:
    """An entity that has been revised, so its version and moment are its own."""
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=ENTITY_REVISED,
        version=ENTITY_VERSION,
    )


def _name(
    entity_name_id: str,
    *,
    entity_id: str,
    display_value: str,
    principal_id: str = PRINCIPAL_A,
    name_type_code: NameTypeCode = NameTypeCode.LEGAL,
    version: int = 1,
    updated_at: datetime | None = WHEN,
) -> EntityName:
    return EntityName(
        entity_name_id=entity_name_id,
        entity_id=entity_id,
        principal_id=principal_id,
        name_type_code=name_type_code,
        display_value=display_value,
        normalized_value=normalize_name(display_value),
        version=version,
        updated_at=updated_at,
    )


def _method(
    communication_method_id: str,
    *,
    entity_id: str,
    value: str,
    principal_id: str = PRINCIPAL_A,
    version: int = 1,
    updated_at: datetime | None = WHEN,
) -> EntityCommunicationMethod:
    return EntityCommunicationMethod(
        communication_method_id=communication_method_id,
        entity_id=entity_id,
        principal_id=principal_id,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.CORPORATE,
        normalized_value=normalize_communication_value(CommunicationMethodTypeCode.EMAIL, value),
        display_value=value,
        verification_status_code=CommunicationVerificationStatusCode.UNRESOLVED,
        version=version,
        updated_at=updated_at,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """Three organizations, and for each family: two claimants, a retired row,
    a superseded row with its successor, and one row in B's partition."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(ORG_ONE, "Harbour One Synthetic", PRINCIPAL_A))
        repository.create(PRINCIPAL_A, _entity(ORG_TWO, "Harbour Two Synthetic", PRINCIPAL_A))
        repository.create(PRINCIPAL_B, _entity(FOREIGN_ORG, "Harbour B Synthetic", PRINCIPAL_B))

    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        # The contested value, claimed by both of A's organizations, and by B's.
        for record in (
            _name(
                NAME_ONE,
                entity_id=ORG_ONE,
                display_value=CONTESTED_NAME,
                version=CHILD_VERSION,
                updated_at=CHILD_REVISED,
            ),
            _name(
                NAME_TWO,
                entity_id=ORG_TWO,
                display_value=CONTESTED_NAME,
                version=CHILD_VERSION,
                updated_at=CHILD_REVISED,
            ),
            # A withdrawn name and a name about to be corrected away. Different
            # `name_type_code`s, so neither collides with the contested LEGAL
            # row under `an_active_entity_name_is_unique_per_entity_and_type`.
            _name(
                NAME_THREE,
                entity_id=ORG_ONE,
                display_value=WITHDRAWN_NAME,
                name_type_code=NameTypeCode.TRADING,
            ),
            _name(
                NAME_FOUR,
                entity_id=ORG_ONE,
                display_value=STALE_NAME,
                name_type_code=NameTypeCode.BRAND,
            ),
        ):
            repository.record_entity_name(PRINCIPAL_A, record)
        for method in (
            _method(
                METHOD_ONE,
                entity_id=ORG_ONE,
                value=CONTESTED_ADDRESS,
                version=CHILD_VERSION,
                updated_at=CHILD_REVISED,
            ),
            _method(
                METHOD_TWO,
                entity_id=ORG_TWO,
                value=CONTESTED_ADDRESS,
                version=CHILD_VERSION,
                updated_at=CHILD_REVISED,
            ),
            _method(METHOD_THREE, entity_id=ORG_ONE, value=WITHDRAWN_ADDRESS),
            _method(METHOD_FOUR, entity_id=ORG_ONE, value=STALE_ADDRESS),
        ):
            repository.record_communication_method(PRINCIPAL_A, method)

    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_entity_name(
            PRINCIPAL_B,
            _name(
                NAME_SIX,
                entity_id=FOREIGN_ORG,
                display_value=CONTESTED_NAME,
                principal_id=PRINCIPAL_B,
            ),
        )
        repository.record_communication_method(
            PRINCIPAL_B,
            _method(
                METHOD_SIX,
                entity_id=FOREIGN_ORG,
                value=CONTESTED_ADDRESS,
                principal_id=PRINCIPAL_B,
            ),
        )

    # The lifecycle is driven through the write path rather than inserted in a
    # non-active state, so what these reads decline to match is what a real
    # correction and a real withdrawal actually leave behind.
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.retire_entity_name(
            PRINCIPAL_A, entity_name_id=NAME_THREE, expected_version=1, at=LATER
        )
        repository.retire_communication_method(
            PRINCIPAL_A, communication_method_id=METHOD_THREE, expected_version=1, at=LATER
        )
        repository.supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_FOUR,
            successor=_name(
                NAME_FIVE,
                entity_id=ORG_ONE,
                display_value=CORRECTED_NAME,
                name_type_code=NameTypeCode.BRAND,
            ),
            expected_version=1,
            at=LATER,
        )
        repository.supersede_communication_method(
            PRINCIPAL_A,
            communication_method_id=METHOD_FOUR,
            successor=_method(METHOD_FIVE, entity_id=ORG_ONE, value=CORRECTED_ADDRESS),
            expected_version=1,
            at=LATER,
        )
    return migrated_engine


# --- every claimant of a contested value comes back --------------------------


def test_a_name_claimed_by_two_entities_returns_both(staged: Engine) -> None:
    """Both rows, in `(entity_id, entity_name_id)` order, with the name that matched.

    The read that decides whether a value is contested must see the whole of
    the contest; one claimant returned here would read as a clean match.
    """
    with staged.connect() as connection:
        found = SqlEntityRepository(connection).entities_by_typed_name(
            PRINCIPAL_A, normalize_name(CONTESTED_NAME)
        )
    assert [(entity.entity_id, name.entity_name_id) for entity, name in found] == [
        (ORG_ONE, NAME_ONE),
        (ORG_TWO, NAME_TWO),
    ]


def test_an_address_claimed_by_two_entities_returns_both(staged: Engine) -> None:
    """A shared address is a fact the caller must be able to see, not an error."""
    with staged.connect() as connection:
        found = SqlEntityRepository(connection).entities_by_communication_value(
            PRINCIPAL_A,
            normalize_communication_value(CommunicationMethodTypeCode.EMAIL, CONTESTED_ADDRESS),
        )
    assert [(entity.entity_id, method.communication_method_id) for entity, method in found] == [
        (ORG_ONE, METHOD_ONE),
        (ORG_TWO, METHOD_TWO),
    ]


# --- the matched child row arrives beside the entity, carrying its own facts --


def test_a_joined_name_lookup_hydrates_both_records(staged: Engine) -> None:
    """Each record carries its *own* lifecycle, not the other one's."""
    with staged.connect() as connection:
        found = SqlEntityRepository(connection).entities_by_typed_name(
            PRINCIPAL_A, normalize_name(CONTESTED_NAME)
        )
    entity, name = found[0]
    assert entity.entity_id == ORG_ONE
    assert entity.display_name == "Harbour One Synthetic"
    assert entity.version == ENTITY_VERSION
    assert entity.updated_at == ENTITY_REVISED
    assert name.entity_name_id == NAME_ONE
    assert name.entity_id == ORG_ONE
    assert name.display_value == CONTESTED_NAME
    assert name.normalized_value == normalize_name(CONTESTED_NAME)
    assert name.name_type_code is NameTypeCode.LEGAL
    assert name.state is EntityNameState.ACTIVE
    assert name.version == CHILD_VERSION
    assert name.updated_at == CHILD_REVISED


def test_a_joined_communication_lookup_hydrates_both_records(staged: Engine) -> None:
    """The same collision on the communication side, and the same two columns."""
    with staged.connect() as connection:
        found = SqlEntityRepository(connection).entities_by_communication_value(
            PRINCIPAL_A,
            normalize_communication_value(CommunicationMethodTypeCode.EMAIL, CONTESTED_ADDRESS),
        )
    entity, method = found[0]
    assert entity.entity_id == ORG_ONE
    assert entity.version == ENTITY_VERSION
    assert entity.updated_at == ENTITY_REVISED
    assert method.communication_method_id == METHOD_ONE
    assert method.entity_id == ORG_ONE
    assert method.display_value == CONTESTED_ADDRESS
    assert method.method_type_code is CommunicationMethodTypeCode.EMAIL
    assert method.usage_context_code is CommunicationUsageContextCode.CORPORATE
    assert method.state is EntityCommunicationMethodState.ACTIVE
    assert method.version == CHILD_VERSION
    assert method.updated_at == CHILD_REVISED


# --- a retired and a superseded row are not matched ---------------------------


def test_a_retired_name_is_not_matched(staged: Engine) -> None:
    """A value the Principal withdrew is not evidence of who they are today.

    Not vacuous: the row is still there, still readable through `names`, and
    still carries the value asked for -- what has changed is only its state.
    """
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        found = repository.entities_by_typed_name(PRINCIPAL_A, normalize_name(WITHDRAWN_NAME))
        stored = [
            row
            for row in repository.names(PRINCIPAL_A, ORG_ONE)
            if row.entity_name_id == NAME_THREE
        ]
    assert found == []
    assert [row.state for row in stored] == [EntityNameState.RETIRED]
    assert [row.normalized_value for row in stored] == [normalize_name(WITHDRAWN_NAME)]


def test_a_superseded_name_is_not_matched_and_its_successor_is(staged: Engine) -> None:
    """The correction's own subject cannot be resurrected by a resolution read."""
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        stale = repository.entities_by_typed_name(PRINCIPAL_A, normalize_name(STALE_NAME))
        corrected = repository.entities_by_typed_name(PRINCIPAL_A, normalize_name(CORRECTED_NAME))
        stored = [
            row for row in repository.names(PRINCIPAL_A, ORG_ONE) if row.entity_name_id == NAME_FOUR
        ]
    assert stale == []
    assert [name.entity_name_id for _, name in corrected] == [NAME_FIVE]
    assert [row.state for row in stored] == [EntityNameState.SUPERSEDED]
    assert [row.superseded_by_entity_name_id for row in stored] == [NAME_FIVE]


def test_a_retired_communication_method_is_not_matched(staged: Engine) -> None:
    """An address the Principal stopped using is not a way to reach them."""
    value = normalize_communication_value(CommunicationMethodTypeCode.EMAIL, WITHDRAWN_ADDRESS)
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        found = repository.entities_by_communication_value(PRINCIPAL_A, value)
        stored = [
            row
            for row in repository.communication_methods(PRINCIPAL_A, ORG_ONE)
            if row.communication_method_id == METHOD_THREE
        ]
    assert found == []
    assert [row.state for row in stored] == [EntityCommunicationMethodState.RETIRED]
    assert [row.normalized_value for row in stored] == [value]


def test_a_superseded_communication_method_is_not_matched_and_its_successor_is(
    staged: Engine,
) -> None:
    stale = normalize_communication_value(CommunicationMethodTypeCode.EMAIL, STALE_ADDRESS)
    corrected_value = normalize_communication_value(
        CommunicationMethodTypeCode.EMAIL, CORRECTED_ADDRESS
    )
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        superseded = repository.entities_by_communication_value(PRINCIPAL_A, stale)
        corrected = repository.entities_by_communication_value(PRINCIPAL_A, corrected_value)
        stored = [
            row
            for row in repository.communication_methods(PRINCIPAL_A, ORG_ONE)
            if row.communication_method_id == METHOD_FOUR
        ]
    assert superseded == []
    assert [method.communication_method_id for _, method in corrected] == [METHOD_FIVE]
    assert [row.state for row in stored] == [EntityCommunicationMethodState.SUPERSEDED]
    assert [row.superseded_by_communication_method_id for row in stored] == [METHOD_FIVE]


# --- another Principal's row is unreachable, in both directions ---------------


def test_a_name_in_another_partition_is_unreachable(staged: Engine) -> None:
    """B's claim on the contested name is invisible to A, and visible to B.

    Both halves are asserted, because an emptiness assertion over a partition
    nobody populated asserts nothing about the partition.
    """
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.entities_by_typed_name(PRINCIPAL_A, normalize_name(CONTESTED_NAME))
        theirs = repository.entities_by_typed_name(PRINCIPAL_B, normalize_name(CONTESTED_NAME))
    assert [name.entity_name_id for _, name in mine] == [NAME_ONE, NAME_TWO]
    assert [name.entity_name_id for _, name in theirs] == [NAME_SIX]
    assert [entity.entity_id for entity, _ in theirs] == [FOREIGN_ORG]


def test_a_communication_value_in_another_partition_is_unreachable(staged: Engine) -> None:
    value = normalize_communication_value(CommunicationMethodTypeCode.EMAIL, CONTESTED_ADDRESS)
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.entities_by_communication_value(PRINCIPAL_A, value)
        theirs = repository.entities_by_communication_value(PRINCIPAL_B, value)
    assert [method.communication_method_id for _, method in mine] == [METHOD_ONE, METHOD_TWO]
    assert [method.communication_method_id for _, method in theirs] == [METHOD_SIX]
    assert [entity.entity_id for entity, _ in theirs] == [FOREIGN_ORG]


# --- equality, never a pattern ------------------------------------------------


def test_a_partial_value_matches_nothing_on_either_read(staged: Engine) -> None:
    """`search` is the substring surface; resolution asks who *is* this.

    A prefix of a stored value is evidence of nothing here, and a wildcard is a
    literal character rather than a pattern -- the same rule `search` states for
    a caller who typed `%`.
    """
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.entities_by_typed_name(PRINCIPAL_A, "harbour") == []
        assert repository.entities_by_typed_name(PRINCIPAL_A, "harbour%") == []
        assert repository.entities_by_communication_value(PRINCIPAL_A, "shared@") == []
        assert repository.entities_by_communication_value(PRINCIPAL_A, "%@example.invalid") == []
