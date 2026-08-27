"""The three identity-correction tables against a real server.

`tests/unit/test_identity_correction.py` drives the domain records and proves the
contract. This drives the SQL and proves the contract holds where it has to:
against the append-only trigger that makes the effect ledger evidence rather than
a mutable note, the `UNIQUE (identity_operation_id, sequence)` that orders one
operation's effects, the composite foreign keys that make same-Principal
structural, the idempotency unique that makes a replay find its own earlier row,
and the CHECK that stops a writer choosing how long an operator's approval lasts.

**What this file proves and what it does not.** Nothing here goes through
`ApplicationService`, so nothing here writes an audit row: `entities.merge` and
`entities.merge.preview` are not admitted to `knowledge.audit_events`'
`capability_is_known` at this head, because Phase B takes one vocabulary revision
and several branches restating one frozen CHECK would produce several heads. The
merge that drives these tables end to end is `WP-RI-06`'s application half and is
somebody else's file. What is measured here is the schema.

Every identity is synthetic, and every recorded state holds identifiers, closed
vocabulary members and versions -- the rule the effect ledger's own declaration
states about what may go in `before_state` and `after_state`.
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
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.identity_correction import (
    IDENTITY_PREVIEW_LIFETIME,
    IdentityEffectFamily,
    IdentityEffectKind,
    state_digest,
)
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable database,
#: so this suite can run alongside them without one dropping the database another
#: is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_identity_correction_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"
FOREIGN: Final = "ent_ffff0009ffff0009"

PREVIEW: Final = "eipv_aaaa0001aaaa01"
OPERATION: Final = "eiop_aaaa0001aaaa01"

CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
DIGEST: Final = "0" * 64
OTHER_DIGEST: Final = "1" * 64


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
        with engine.begin() as connection:
            for entity_id, principal_id in (
                (SURVIVOR, PRINCIPAL_A),
                (MERGED, PRINCIPAL_A),
                (FOREIGN, PRINCIPAL_B),
            ):
                connection.execute(
                    text(
                        f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                        "(entity_id, principal_id, entity_type, canonical_name, display_name, "
                        " status, created_at, updated_at, version) "
                        "VALUES (:entity_id, :principal_id, 'person', :name, :name, "
                        " 'active', :when, :when, 1)"
                    ),
                    {
                        "entity_id": entity_id,
                        "principal_id": principal_id,
                        "name": f"synthetic {entity_id}",
                        "when": WHEN,
                    },
                )
        yield engine
    finally:
        engine.dispose()


def _insert_preview(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "preview_id": PREVIEW,
        "principal_id": PRINCIPAL_A,
        "operation_type": "merge",
        "survivor_entity_id": SURVIVOR,
        "expected_survivor_version": 1,
        "merged_away": '[{"entity_id": "' + MERGED + '", "expected_version": 1}]',
        "preview_digest": DIGEST,
        "conflict_digest": OTHER_DIGEST,
        "plan_digest": OTHER_DIGEST,
        "created_by": "operator",
        "actor_class": "user",
        "created_at": WHEN,
        "expires_at": WHEN + IDENTITY_PREVIEW_LIFETIME,
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_identity_previews "  # noqa: S608
                "(preview_id, principal_id, operation_type, survivor_entity_id, "
                " expected_survivor_version, merged_away, preview_digest, conflict_digest, "
                " plan_digest, "
                " created_by, actor_class, created_at, expires_at) "
                "VALUES (:preview_id, :principal_id, :operation_type, :survivor_entity_id, "
                " :expected_survivor_version, CAST(:merged_away AS jsonb), :preview_digest, "
                " :conflict_digest, :plan_digest, :created_by, :actor_class, :created_at, "
                " :expires_at)"
            ),
            values,
        )


def _insert_operation(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "identity_operation_id": OPERATION,
        "principal_id": PRINCIPAL_A,
        "operation_type": "merge",
        "survivor_entity_id": SURVIVOR,
        "merged_entity_ids": '["' + MERGED + '"]',
        "preview_id": PREVIEW,
        "preview_digest": DIGEST,
        "idempotency_key": "merge-0001",
        "request_digest": OTHER_DIGEST,
        "performed_by": "operator",
        "actor_class": "user",
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "receipt_id": "rcpt_aaaa0001aaaa01",
        "state": "completed",
        "started_at": WHEN,
        "completed_at": WHEN + timedelta(seconds=2),
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_identity_operations "  # noqa: S608
                "(identity_operation_id, principal_id, operation_type, survivor_entity_id, "
                " merged_entity_ids, preview_id, preview_digest, idempotency_key, "
                " request_digest, performed_by, actor_class, correlation_id, audit_id, receipt_id, "
                " state, started_at, completed_at) "
                "VALUES (:identity_operation_id, :principal_id, :operation_type, "
                " :survivor_entity_id, CAST(:merged_entity_ids AS jsonb), :preview_id, "
                " :preview_digest, :idempotency_key, :request_digest, :performed_by, "
                " :actor_class, :correlation_id, :audit_id, :receipt_id, :state, "
                " :started_at, :completed_at)"
            ),
            values,
        )


def _insert_effect(engine: Engine, **overrides: object) -> None:
    before = {"entity_id": MERGED}
    after = {"entity_id": SURVIVOR}
    values: dict[str, object] = {
        "effect_id": "eief_aaaa0001aaaa01",
        "identity_operation_id": OPERATION,
        "principal_id": PRINCIPAL_A,
        "sequence": 1,
        "record_family": IdentityEffectFamily.ALIAS.value,
        "record_id": "eals_aaaa0001aaaa01",
        "effect_kind": IdentityEffectKind.OWNER_REPARENTED.value,
        "before_state": '{"entity_id": "' + MERGED + '"}',
        "after_state": '{"entity_id": "' + SURVIVOR + '"}',
        "before_sha256": state_digest(before),
        "after_sha256": state_digest(after),
        "recorded_at": WHEN,
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_identity_effects "  # noqa: S608
                "(effect_id, identity_operation_id, principal_id, sequence, record_family, "
                " record_id, effect_kind, before_state, after_state, before_sha256, "
                " after_sha256, recorded_at) "
                "VALUES (:effect_id, :identity_operation_id, :principal_id, :sequence, "
                " :record_family, :record_id, :effect_kind, CAST(:before_state AS jsonb), "
                " CAST(:after_state AS jsonb), :before_sha256, :after_sha256, :recorded_at)"
            ),
            values,
        )


# --- the preview control row -------------------------------------------------


def test_a_preview_is_stored_and_read_back(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT expires_at - created_at AS lifetime, consumed_at "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_previews WHERE preview_id = :preview_id"
            ),
            {"preview_id": PREVIEW},
        ).one()
    assert stored.lifetime == IDENTITY_PREVIEW_LIFETIME
    assert stored.consumed_at is None


def test_the_server_refuses_a_preview_lifetime_a_writer_chose(migrated_engine: Engine) -> None:
    """The domain refuses it too; a row written around the repository is refused here."""
    with pytest.raises(IntegrityError) as refused:
        _insert_preview(migrated_engine, expires_at=WHEN + timedelta(hours=8))
    assert "a_preview_expires_fifteen_minutes_after_it_was_created" in str(refused.value)


def test_the_server_refuses_a_preview_over_another_principals_entity(
    migrated_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError) as refused:
        _insert_preview(migrated_engine, survivor_entity_id=FOREIGN)
    assert "a_preview_retains_an_entity_of_its_principal" in str(refused.value)


def test_the_server_bounds_the_merged_away_set(migrated_engine: Engine) -> None:
    entries = ", ".join(f'{{"entity_id": "ent_merged{index:08d}"}}' for index in range(11))
    eleven = f"[{entries}]"
    with pytest.raises(IntegrityError) as refused:
        _insert_preview(migrated_engine, merged_away=eleven)
    assert "a_preview_merges_away_a_bounded_set_of_entities" in str(refused.value)
    with pytest.raises(IntegrityError):
        _insert_preview(migrated_engine, merged_away="[]")


# --- the operation ledger ----------------------------------------------------


def test_an_operation_consumes_a_preview_of_its_own_principal(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_identity_operations")  # noqa: S608
            ).scalar_one()
            == 1
        )


def test_the_server_refuses_an_operation_against_another_principals_preview(
    migrated_engine: Engine,
) -> None:
    """The composite reference, not a predicate the writer has to remember."""
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(migrated_engine, principal_id=PRINCIPAL_B)
    assert "an_identity_operation" in str(refused.value)


def test_one_idempotency_key_holds_one_operation_per_principal(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(
            migrated_engine,
            identity_operation_id="eiop_bbbb0002bbbb02",
            request_digest=DIGEST,
        )
    assert "one_identity_operation_per_principal_and_key" in str(refused.value)


def test_an_operation_requires_one_unique_server_receipt(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError):
        _insert_operation(migrated_engine, receipt_id=None)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(
            migrated_engine,
            identity_operation_id="eiop_bbbb0002bbbb02",
            idempotency_key="merge-0002",
            request_digest=DIGEST,
        )
    assert "one_receipt_per_identity_operation" in str(refused.value)


def test_an_operation_in_progress_may_not_name_an_end(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(migrated_engine, state="in_progress")
    assert "an_identity_operation_is_finished_exactly_when_it_names_an_end" in str(refused.value)


def test_an_operation_is_updated_from_in_progress_to_completed(migrated_engine: Engine) -> None:
    """The asymmetry with the effects: status is revised, evidence is not."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine, state="in_progress", completed_at=None)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_operations "  # noqa: S608
                "SET state = 'completed', completed_at = :when "
                "WHERE identity_operation_id = :identity_operation_id"
            ),
            {"when": WHEN + timedelta(seconds=1), "identity_operation_id": OPERATION},
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    f"SELECT state FROM {SCHEMA}.entity_identity_operations "  # noqa: S608
                    "WHERE identity_operation_id = :identity_operation_id"
                ),
                {"identity_operation_id": OPERATION},
            ).scalar_one()
            == "completed"
        )


def test_the_server_refuses_an_unknown_operation_type(migrated_engine: Engine) -> None:
    """`split` is not admitted at this revision; `WP-07` widens the CHECK."""
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(migrated_engine, operation_type="split")
    assert "an_identity_operation_type_is_known" in str(refused.value)


# --- the append-only effect ledger -------------------------------------------


def test_an_effect_is_stored_with_both_states_and_both_digests(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT before_state, after_state, before_sha256, after_sha256 "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_effects"
            )
        ).one()
    assert stored.before_state == {"entity_id": MERGED}
    assert stored.after_state == {"entity_id": SURVIVOR}
    assert stored.before_sha256 == state_digest({"entity_id": MERGED})
    assert stored.after_sha256 == state_digest({"entity_id": SURVIVOR})


def test_an_effect_row_cannot_be_updated(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_effects "  # noqa: S608
                'SET after_state = \'{"entity_id": "ent_rewritten00001"}\'::jsonb'
            )
        )
    assert "append only" in str(refused.value)


def test_an_effect_row_cannot_be_deleted(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {SCHEMA}.entity_identity_effects"))  # noqa: S608
    assert "append only" in str(refused.value)
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_identity_effects")  # noqa: S608
            ).scalar_one()
            == 1
        )


def test_one_effect_per_operation_and_sequence(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(
            migrated_engine,
            effect_id="eief_bbbb0002bbbb02",
            record_id="eals_bbbb0002bbbb02",
        )
    assert "one_identity_effect_per_operation_and_sequence" in str(refused.value)


def test_one_effect_per_operation_and_record(migrated_engine: Engine) -> None:
    """Two rows about one record would leave a split unable to say what to restore."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(
            migrated_engine,
            effect_id="eief_bbbb0002bbbb02",
            sequence=2,
            effect_kind=IdentityEffectKind.ROW_COALESCED.value,
        )
    assert "one_identity_effect_per_operation_and_record" in str(refused.value)


def test_the_server_refuses_an_effect_that_records_no_change(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    same = '{"entity_id": "' + MERGED + '"}'
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(
            migrated_engine,
            after_state=same,
            after_sha256=state_digest({"entity_id": MERGED}),
        )
    assert "an_identity_effect_records_a_change" in str(refused.value)


def test_the_server_refuses_an_effect_state_that_says_nothing(migrated_engine: Engine) -> None:
    """A `{}` state is the redirect-only ledger, written one row at a time."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(migrated_engine, before_state="{}", before_sha256=state_digest({}))
    assert "an_identity_effect_before_state_says_something" in str(refused.value)


def test_the_server_refuses_an_effect_of_another_principals_operation(
    migrated_engine: Engine,
) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(migrated_engine, principal_id=PRINCIPAL_B)
    assert "an_identity_effect_records_an_operation_of_its_principal" in str(refused.value)


def test_the_server_refuses_a_record_id_that_is_not_an_opaque_identifier(
    migrated_engine: Engine,
) -> None:
    """`record_id` names nine families and carries no foreign key; shape is what is left."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(migrated_engine, record_id="/etc/passwd")
    assert "an_identity_effect_record_id_is_an_opaque_identifier" in str(refused.value)


def test_the_ledger_reads_back_in_sequence_order(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(
        migrated_engine,
        effect_id="eief_cccc0003cccc03",
        sequence=3,
        record_family=IdentityEffectFamily.IDENTIFIER.value,
        record_id="xid_cccc0003cccc0003",
    )
    _insert_effect(
        migrated_engine,
        effect_id="eief_bbbb0002bbbb02",
        sequence=2,
        record_id="eals_bbbb0002bbbb02",
    )
    _insert_effect(migrated_engine)
    with migrated_engine.connect() as connection:
        sequences = [
            row.sequence
            for row in connection.execute(
                text(
                    f"SELECT sequence FROM {SCHEMA}.entity_identity_effects "  # noqa: S608
                    "WHERE identity_operation_id = :identity_operation_id "
                    "ORDER BY sequence"
                ),
                {"identity_operation_id": OPERATION},
            )
        ]
    assert sequences == [1, 2, 3]
