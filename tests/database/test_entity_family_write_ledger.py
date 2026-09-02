"""`EntityFamilyWriteService` against real PostgreSQL (RI-ENT-WP-11, ledger tier).

`RI-ENT-WP-08`'s own database module already covers what
`EntityRecordFamilyService` writes into the five record families, and the
contract tier covers what this service does over the in-memory double. This one
holds only what neither of those can decide -- the properties that exist because
`knowledge.entity_mutation_events` is really underneath the write:

* **The ledger row carries the new `record_family`.** `MutationRecordFamily` was
  closed at six families and `RI-ENT-WP-11` widened it to eleven. The value in
  the enum is a Python fact; the value the column accepts is a CHECK
  (`a_mutated_record_family_is_known`), and only a real server can say whether
  the two agree.
* **`UNIQUE (principal_id, capability, idempotency_key)` is what makes the write
  idempotent.** The replay pre-read through `directed_replay` is an
  optimisation; the index is the decision. A retry with the same key and the
  same payload has to return the first receipt and write no second row of
  anything, and a retry with the same key and a *different* payload has to be
  refused rather than absorbed.
* **`expected_version` is honoured by the guarded `UPDATE`'s own `rowcount`**,
  not by a version this service re-read for itself -- and a refused write has to
  leave no ledger row behind, because a ledger row for a change that did not
  happen is worse than no ledger at all.

**THESE TESTS ARE WRITTEN AND HAVE NEVER BEEN EXECUTED.** `RI-ENT-WP-11` ran
under an absolute prohibition on running anything marked `database`, because
another work package's database measurement was in flight machine-wide. They are
committed as written-and-unexecuted and are reported that way, by filename and
test name, rather than described as passing.

**AND THEY ARE EXPECTED TO FAIL UNTIL THE PHASE'S MIGRATION LANDS.** No revision
in this branch widens `a_mutated_record_family_is_known` to admit `name`,
`address`, `communication_method`, `project_participation` or
`person_organization_affiliation`, and none widens
`knowledge.audit_events.capability_is_known` to admit the capability values these
tests invoke. A single dedicated owner writes one revision for the whole phase.
Until it does, every test below is expected to fail on its first INSERT with a
CHECK violation, and that failure is the migration being absent rather than this
module being wrong. In this campaign eleven database tests were committed
statically verified and errored on first execution against an enum member that
never existed; nothing here claims to have escaped that class.

Every identity is synthetic and every value is `example.invalid`-shaped.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.engine import make_url

from my_pa.application.commands import (
    AddEntityAddress,
    AddEntityName,
    RetireEntityAddress,
    RetireEntityName,
    ReviseEntityAddress,
    SupersedeEntityName,
)
from my_pa.application.entity_family_writes import EntityFamilyWriteService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    Entity,
    EntityAddressState,
    EntityNameState,
    EntityStatus,
    EntityType,
    NameTypeCode,
    StaleDirectedVersionError,
)
from my_pa.domain.relationship.governance import (
    EntityMutationConflictError,
    MutationRecordFamily,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.tables import (
    entity_addresses,
    entity_mutation_events,
    entity_names,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_entity_family_write_ledger_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PERSON: Final = "ent_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

AUDIT: Final = "aud_aaaa0001aaaa0001"
AUDIT_TWO: Final = "aud_bbbb0002bbbb0002"


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
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """One person, and nothing else.

    Every record-family row these tests read back was written by the service
    under test, which is the property that makes reading one evidence rather
    than a restatement of the fixture.
    """
    with migrated_engine.begin() as connection:
        SqlEntityRepository(connection).create(
            PRINCIPAL_A,
            Entity(
                entity_id=PERSON,
                principal_id=PRINCIPAL_A,
                entity_type=EntityType.PERSON,
                canonical_name=normalize_name("Alice Synthetic"),
                display_name="Alice Synthetic",
                status=EntityStatus.ACTIVE,
                created_at=WHEN,
                updated_at=WHEN,
                version=1,
            ),
        )
    return migrated_engine


def _ledger(connection: Connection) -> list[dict[str, object]]:
    """Every mutation-ledger row this Principal holds, oldest first."""
    rows = connection.execute(
        select(entity_mutation_events)
        .where(entity_mutation_events.c.principal_id == PRINCIPAL_A)
        .order_by(entity_mutation_events.c.recorded_at, entity_mutation_events.c.event_id)
    ).all()
    return [dict(row._mapping) for row in rows]


def _names(connection: Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        select(entity_names).where(entity_names.c.principal_id == PRINCIPAL_A)
    ).all()
    return [dict(row._mapping) for row in rows]


def _add(key: str = "wp11-names-add-0001", value: str = "Alice Synthetic") -> AddEntityName:
    return AddEntityName(
        entity_id=PERSON,
        name_type_code=NameTypeCode.LEGAL,
        display_value=value,
        idempotency_key=key,
    )


# --- entity_names -----------------------------------------------------------


def test_an_added_name_writes_one_ledger_row_naming_the_new_record_family(
    staged: Engine,
) -> None:
    """The property the phase's migration has to admit, stated as a read.

    `record_family` is `name`, which `a_mutated_record_family_is_known` did not
    accept before `RI-ENT-WP-11` and which no revision in this branch widens it
    to accept. That is why this is the first assertion in the module.
    """
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        receipt = service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    assert receipt.record_family is MutationRecordFamily.NAME
    assert receipt.replayed is False
    assert receipt.prior_version is None
    assert receipt.version == 1
    assert receipt.state == EntityNameState.ACTIVE.value
    assert receipt.superseded_id is None
    with staged.connect() as connection:
        ledger = _ledger(connection)
        written = _names(connection)
    assert len(ledger) == 1
    assert ledger[0]["record_family"] == MutationRecordFamily.NAME.value
    assert ledger[0]["capability"] == "entities.names.add"
    assert ledger[0]["record_id"] == receipt.record_id
    assert ledger[0]["prior_version"] is None
    assert ledger[0]["new_version"] == 1
    assert ledger[0]["audit_id"] == AUDIT
    assert ledger[0]["idempotency_key"] == "wp11-names-add-0001"
    # The photograph carries a lifecycle state and no recorded value. A display
    # value in `after_state` is exactly the disclosure `EntityMutationEvent`'s
    # own docstring forbids, and this is where it would land.
    assert ledger[0]["after_state"] == {"state": EntityNameState.ACTIVE.value}
    assert ledger[0]["before_state"] is None
    assert len(written) == 1
    assert written[0]["entity_name_id"] == receipt.record_id


def test_a_retry_with_the_same_key_and_payload_replays_and_writes_nothing(
    staged: Engine,
) -> None:
    """Both calls succeed, one row exists, and the second says it did no work."""
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        first = service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.begin() as connection:
        second = service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    assert first.replayed is False
    assert second.replayed is True
    # The replayed receipt is the *first* answer, audit identifier included: a
    # retry that reported the second attempt's audit row would tell a caller the
    # write happened at a moment it did not.
    assert second.record_id == first.record_id
    assert second.mutation_event_id == first.mutation_event_id
    assert second.audit_id == AUDIT
    with staged.connect() as connection:
        assert len(_ledger(connection)) == 1
        assert len(_names(connection)) == 1


def test_a_retry_with_the_same_key_and_a_different_payload_is_refused(
    staged: Engine,
) -> None:
    """The one case that must be refused rather than absorbed.

    The refusal comes from `directed_replay`'s digest comparison, which is the
    same mechanism the directed plane uses, and it leaves no second row of
    either kind behind.
    """
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    from my_pa.domain.relationship.entity import DirectedWriteError

    with pytest.raises(DirectedWriteError), staged.begin() as connection:
        service.add_name(
            SqlEntityRepository(connection),
            _add(value="Alice Synthetic Two"),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    with staged.connect() as connection:
        assert len(_ledger(connection)) == 1
        assert len(_names(connection)) == 1


def test_a_supersession_names_its_predecessor_and_the_version_it_asserted(
    staged: Engine,
) -> None:
    """The successor is a new row at version one, and `before_state` says which
    predecessor at which version the write actually succeeded against."""
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        added = service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.begin() as connection:
        corrected = service.supersede_name(
            SqlEntityRepository(connection),
            SupersedeEntityName(
                entity_name_id=added.record_id,
                expected_version=1,
                entity_id=PERSON,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Alice Synthetic Corrected",
                idempotency_key="wp11-names-supersede-0001",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    assert corrected.superseded_id == added.record_id
    assert corrected.record_id != added.record_id
    # `prior_version` is null and `new_version` is one, because the successor is
    # a brand-new row: `a_mutation_advances_the_version_it_names` requires
    # `new_version > prior_version`, and the successor never stood at the
    # predecessor's version.
    assert corrected.prior_version is None
    assert corrected.version == 1
    with staged.connect() as connection:
        ledger = _ledger(connection)
        written = {row["entity_name_id"]: row for row in _names(connection)}
    assert len(ledger) == 2
    assert ledger[1]["capability"] == "entities.names.supersede"
    assert ledger[1]["record_family"] == MutationRecordFamily.NAME.value
    assert ledger[1]["record_id"] == corrected.record_id
    assert ledger[1]["before_state"] == {"record_id": added.record_id, "version": 1}
    assert written[added.record_id]["state"] == EntityNameState.SUPERSEDED.value
    assert written[added.record_id]["superseded_by_entity_name_id"] == corrected.record_id
    assert written[corrected.record_id]["state"] == EntityNameState.ACTIVE.value


def test_a_retirement_advances_the_version_it_names(staged: Engine) -> None:
    """The one verb that moves a version in place, read back off both rows.

    `retire_entity_name` sets `version = version + 1` under
    `WHERE version = expected_version`, so the receipt's `prior_version` is what
    the caller asserted and `new_version` is one more -- and the row itself has
    to agree, which is what makes this a measurement rather than a restatement.
    """
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        added = service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.begin() as connection:
        retired = service.retire_name(
            SqlEntityRepository(connection),
            RetireEntityName(
                entity_name_id=added.record_id,
                expected_version=1,
                idempotency_key="wp11-names-retire-0001",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    assert retired.record_id == added.record_id
    assert retired.prior_version == 1
    assert retired.version == 2
    assert retired.state == EntityNameState.RETIRED.value
    with staged.connect() as connection:
        ledger = _ledger(connection)
        written = _names(connection)
    assert ledger[1]["prior_version"] == 1
    assert ledger[1]["new_version"] == 2
    assert ledger[1]["capability"] == "entities.names.retire"
    assert len(written) == 1
    assert written[0]["state"] == EntityNameState.RETIRED.value
    assert written[0]["version"] == 2
    assert written[0]["is_preferred"] is False


def test_a_stale_expected_version_is_refused_and_leaves_no_ledger_row(
    staged: Engine,
) -> None:
    """The guarded `UPDATE`'s own `rowcount` decides, and the ledger follows it.

    A refusal that had already appended its ledger row would record a change
    that did not happen, which is worse than recording nothing -- so the write
    comes first and the ledger second, and this is the test that says so.
    """
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        added = service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with pytest.raises(StaleDirectedVersionError), staged.begin() as connection:
        service.retire_name(
            SqlEntityRepository(connection),
            RetireEntityName(
                entity_name_id=added.record_id,
                expected_version=2,
                idempotency_key="wp11-names-retire-stale",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    with staged.connect() as connection:
        ledger = _ledger(connection)
        written = _names(connection)
    assert len(ledger) == 1
    assert ledger[0]["capability"] == "entities.names.add"
    assert written[0]["state"] == EntityNameState.ACTIVE.value
    assert written[0]["version"] == 1


def test_one_key_under_two_capabilities_is_two_writes_and_not_one(
    staged: Engine,
) -> None:
    """`capability` is part of the unique, so reusing a key across verbs is honest.

    Two different acts on different state, so two ledger rows -- which is what
    `EntityMutationEvent`'s own docstring says the composite key means, read
    back off a server rather than asserted about it.
    """
    service = EntityFamilyWriteService()
    shared = "wp11-names-shared-key"
    with staged.begin() as connection:
        added = service.add_name(
            SqlEntityRepository(connection),
            _add(key=shared),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.begin() as connection:
        retired = service.retire_name(
            SqlEntityRepository(connection),
            RetireEntityName(
                entity_name_id=added.record_id,
                expected_version=1,
                idempotency_key=shared,
            ),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    assert retired.replayed is False
    with staged.connect() as connection:
        ledger = _ledger(connection)
    assert [row["capability"] for row in ledger] == [
        "entities.names.add",
        "entities.names.retire",
    ]
    assert {row["idempotency_key"] for row in ledger} == {shared}


def test_a_second_ledger_row_for_one_key_and_capability_is_refused(
    staged: Engine,
) -> None:
    """The pre-read `record_mutation_event` performs, against a real unique.

    Reached directly rather than through the service, because the service's own
    `directed_replay` answers first: this is the second line of defence, and a
    test that could only reach the first would prove nothing about it.
    """
    from my_pa.domain.relationship.governance import (
        DEFAULT_MUTATION_ACTOR_CLASS,
        DEFAULT_MUTATION_AUTHORITY,
        EntityMutationEvent,
    )

    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        added = service.add_name(
            SqlEntityRepository(connection),
            _add(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.connect() as connection:
        held = _ledger(connection)[0]
    conflicting = EntityMutationEvent(
        event_id="emev_cccc0003cccc0003",
        principal_id=PRINCIPAL_A,
        capability="entities.names.add",
        record_family=MutationRecordFamily.NAME,
        record_id=added.record_id,
        new_version=1,
        authority=DEFAULT_MUTATION_AUTHORITY,
        actor_class=DEFAULT_MUTATION_ACTOR_CLASS,
        idempotency_key=str(held["idempotency_key"]),
        request_digest="0" * 64,
        correlation_id="corr_cccc0003cccc0003",
        audit_id=AUDIT_TWO,
        recorded_at=LATER,
    )
    with pytest.raises(EntityMutationConflictError), staged.begin() as connection:
        SqlEntityRepository(connection).record_mutation_event(PRINCIPAL_A, conflicting)
    with staged.connect() as connection:
        assert len(_ledger(connection)) == 1


# --- entity_addresses -------------------------------------------------------


def _addresses(connection: Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        select(entity_addresses).where(entity_addresses.c.principal_id == PRINCIPAL_A)
    ).all()
    return [dict(row._mapping) for row in rows]


def _add_address(
    key: str = "wp11-addresses-add-0001", raw_value: str = "1 Synthetic Way"
) -> AddEntityAddress:
    return AddEntityAddress(
        entity_id=PERSON,
        address_type_code=AddressTypeCode.BUSINESS,
        raw_value=raw_value,
        idempotency_key=key,
    )


def test_an_added_address_writes_a_ledger_row_naming_the_address_family(
    staged: Engine,
) -> None:
    """`record_family` is `address`, which the phase's migration has to admit."""
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        receipt = service.add_address(
            SqlEntityRepository(connection),
            _add_address(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    assert receipt.record_family is MutationRecordFamily.ADDRESS
    assert receipt.version == 1
    assert receipt.state == EntityAddressState.ACTIVE.value
    with staged.connect() as connection:
        ledger = _ledger(connection)
        written = _addresses(connection)
    assert len(ledger) == 1
    assert ledger[0]["record_family"] == MutationRecordFamily.ADDRESS.value
    assert ledger[0]["capability"] == "entities.addresses.add"
    assert ledger[0]["record_id"] == receipt.record_id
    # No address text anywhere in the photograph. A raw address value in
    # `after_state` is the disclosure this ledger's own docstring forbids, and
    # this is exactly where it would land.
    assert ledger[0]["after_state"] == {"state": EntityAddressState.ACTIVE.value}
    assert len(written) == 1
    assert written[0]["entity_address_id"] == receipt.record_id


def test_an_address_retry_with_the_same_key_and_payload_replays(staged: Engine) -> None:
    """One row, and the second call says it did no work."""
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        first = service.add_address(
            SqlEntityRepository(connection),
            _add_address(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.begin() as connection:
        second = service.add_address(
            SqlEntityRepository(connection),
            _add_address(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    assert first.replayed is False
    assert second.replayed is True
    assert second.record_id == first.record_id
    with staged.connect() as connection:
        assert len(_ledger(connection)) == 1
        assert len(_addresses(connection)) == 1


def test_an_address_retry_with_a_different_payload_is_refused(staged: Engine) -> None:
    """Same key, different address: a conflict rather than a silent second write."""
    from my_pa.domain.relationship.entity import DirectedWriteError

    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        service.add_address(
            SqlEntityRepository(connection),
            _add_address(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with pytest.raises(DirectedWriteError), staged.begin() as connection:
        service.add_address(
            SqlEntityRepository(connection),
            _add_address(raw_value="2 Synthetic Way"),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    with staged.connect() as connection:
        assert len(_ledger(connection)) == 1
        assert len(_addresses(connection)) == 1


def test_an_address_revision_is_a_supersession_and_not_an_edit(staged: Engine) -> None:
    """`revise` is this family's spelling of what names call `supersede`.

    The predecessor is marked SUPERSEDED pointing at a brand-new successor row,
    so both remain readable and neither was edited in place.
    """
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        added = service.add_address(
            SqlEntityRepository(connection),
            _add_address(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.begin() as connection:
        revised = service.revise_address(
            SqlEntityRepository(connection),
            ReviseEntityAddress(
                entity_address_id=added.record_id,
                expected_version=1,
                entity_id=PERSON,
                address_type_code=AddressTypeCode.BUSINESS,
                raw_value="2 Synthetic Way",
                idempotency_key="wp11-addresses-revise-0001",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    assert revised.superseded_id == added.record_id
    assert revised.record_id != added.record_id
    assert revised.prior_version is None
    assert revised.version == 1
    with staged.connect() as connection:
        ledger = _ledger(connection)
        written = {row["entity_address_id"]: row for row in _addresses(connection)}
    assert ledger[1]["record_family"] == MutationRecordFamily.ADDRESS.value
    assert ledger[1]["before_state"] == {"record_id": added.record_id, "version": 1}
    assert written[added.record_id]["state"] == EntityAddressState.SUPERSEDED.value
    assert written[added.record_id]["superseded_by_entity_address_id"] == revised.record_id
    assert written[revised.record_id]["state"] == EntityAddressState.ACTIVE.value


def test_an_address_retirement_advances_its_version_and_releases_its_slot(
    staged: Engine,
) -> None:
    """`version + 1` under the guarded `UPDATE`, read back off the row itself."""
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        added = service.add_address(
            SqlEntityRepository(connection),
            _add_address(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with staged.begin() as connection:
        retired = service.retire_address(
            SqlEntityRepository(connection),
            RetireEntityAddress(
                entity_address_id=added.record_id,
                expected_version=1,
                idempotency_key="wp11-addresses-retire-0001",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    assert retired.prior_version == 1
    assert retired.version == 2
    assert retired.state == EntityAddressState.RETIRED.value
    with staged.connect() as connection:
        ledger = _ledger(connection)
        written = _addresses(connection)
    assert ledger[1]["prior_version"] == 1
    assert ledger[1]["new_version"] == 2
    assert written[0]["state"] == EntityAddressState.RETIRED.value
    assert written[0]["version"] == 2
    assert written[0]["is_preferred"] is False


def test_a_stale_address_version_is_refused_and_leaves_no_ledger_row(
    staged: Engine,
) -> None:
    """The write comes first and the ledger second, so a refusal records nothing."""
    service = EntityFamilyWriteService()
    with staged.begin() as connection:
        added = service.add_address(
            SqlEntityRepository(connection),
            _add_address(),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT,
            at=WHEN,
        )
    with pytest.raises(StaleDirectedVersionError), staged.begin() as connection:
        service.retire_address(
            SqlEntityRepository(connection),
            RetireEntityAddress(
                entity_address_id=added.record_id,
                expected_version=2,
                idempotency_key="wp11-addresses-retire-stale",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=AUDIT_TWO,
            at=LATER,
        )
    with staged.connect() as connection:
        assert len(_ledger(connection)) == 1
        assert _addresses(connection)[0]["version"] == 1
