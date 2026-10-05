"""RE-DBH-01: effective Record Event privileges on a disposable database.

Roles are cluster-wide and use the canonical names. The fixture removes them
after the module, once every per-test catalog that could own an object has
been dropped. No credential is created.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.record_event_privilege_gate import (
    verify_record_event_privileges,
)
from my_pa.infrastructure.database.record_event_roles import (
    MIGRATOR_ROLE,
    OWNER_ROLE,
    RUNTIME_ROLE,
    RoleProvisionError,
    provision_record_event_roles,
)

pytestmark = pytest.mark.database

RESTRICT_VIOLATION: Final = "23001"
FEATURE_NOT_SUPPORTED: Final = "0A000"
INSUFFICIENT: Final = "42501"


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


@pytest.fixture
def provisioned(db_engine: Engine) -> Iterator[Engine]:
    with db_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        assert provision_record_event_roles(connection) is True
    try:
        yield db_engine
    finally:
        db_engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _drop_canonical_roles(postgres_admin_engine: Engine) -> Iterator[None]:
    yield
    with postgres_admin_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        present = set(
            connection.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname IN (:runtime, :migrator, :owner)"),
                {"runtime": RUNTIME_ROLE, "migrator": MIGRATOR_ROLE, "owner": OWNER_ROLE},
            ).scalars()
        )
        for member in (RUNTIME_ROLE, MIGRATOR_ROLE):
            if member in present and OWNER_ROLE in present:
                connection.execute(text(f"REVOKE {OWNER_ROLE} FROM {member}"))
        if RUNTIME_ROLE in present and MIGRATOR_ROLE in present:
            connection.execute(text(f"REVOKE {MIGRATOR_ROLE} FROM {RUNTIME_ROLE}"))
        for role in (RUNTIME_ROLE, MIGRATOR_ROLE, OWNER_ROLE):
            if role in present:
                connection.execute(text(f"DROP ROLE {role}"))


def _as_role(engine: Engine, role: str) -> Iterator[object]:
    connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    connection.execute(text(f"SET ROLE {role}"))
    try:
        yield connection
    finally:
        connection.execute(text("RESET ROLE"))
        connection.close()


def test_provision_is_idempotent(provisioned: Engine) -> None:
    with provisioned.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        assert provision_record_event_roles(connection) is True


def test_runtime_membership_in_owner_fails_closed_without_revocation(provisioned: Engine) -> None:
    with provisioned.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"GRANT {OWNER_ROLE} TO {RUNTIME_ROLE}"))
    try:
        with provisioned.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            with pytest.raises(RoleProvisionError, match="already a member"):
                provision_record_event_roles(connection)
            still_member = connection.execute(
                text("SELECT pg_has_role(:member, :role, 'MEMBER')"),
                {"member": RUNTIME_ROLE, "role": OWNER_ROLE},
            ).scalar_one()
        assert still_member is True
    finally:
        with provisioned.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f"REVOKE {OWNER_ROLE} FROM {RUNTIME_ROLE}"))


def test_the_runtime_gate_passes_and_prints_no_url(provisioned: Engine) -> None:
    with provisioned.connect() as connection:
        # Session user, not only current_user: a superuser SET ROLE still has
        # the superuser's SET ROLE rights. Authorization makes runtime the session.
        connection.execute(text(f"SET SESSION AUTHORIZATION {RUNTIME_ROLE}"))
        connection.commit()
        try:
            verify_record_event_privileges(connection)
        finally:
            connection.execute(text("RESET SESSION AUTHORIZATION"))
            connection.commit()


def test_runtime_cannot_truncate_update_delete_or_administer(provisioned: Engine) -> None:
    statements = (
        "TRUNCATE TABLE knowledge.record_events",
        "TRUNCATE TABLE knowledge.record_event_sequences",
        "UPDATE knowledge.record_events SET record_version = record_version",
        "DELETE FROM knowledge.record_events",
        "DROP TRIGGER record_events_are_append_only ON knowledge.record_events",
        "DROP TRIGGER record_events_refuse_truncate ON knowledge.record_events",
        "ALTER TABLE knowledge.record_events DISABLE TRIGGER record_events_refuse_truncate",
        "CREATE TABLE knowledge.record_event_privilege_probe (id integer)",
        f"SET ROLE {OWNER_ROLE}",
        f"SET ROLE {MIGRATOR_ROLE}",
    )
    connection = provisioned.connect().execution_options(isolation_level="AUTOCOMMIT")
    connection.execute(text(f"SET SESSION AUTHORIZATION {RUNTIME_ROLE}"))
    try:
        for statement in statements:
            try:
                connection.execute(text(statement))
            except DBAPIError as exc:
                assert _sqlstate(exc) == INSUFFICIENT, f"{statement}: {exc}"
            else:
                who = connection.execute(text("SELECT current_user, session_user")).one()
                raise AssertionError(f"accepted {statement} as {who}")
    finally:
        connection.execute(text("RESET SESSION AUTHORIZATION"))
        connection.close()


def test_owner_truncate_and_mutation_reach_the_refusal_triggers(provisioned: Engine) -> None:
    admin = provisioned.connect().execution_options(isolation_level="AUTOCOMMIT")
    admin.execute(text(f"SET SESSION AUTHORIZATION {RUNTIME_ROLE}"))
    admin.execute(
        text(
            "INSERT INTO knowledge.record_event_sequences (principal_id, next_sequence) "
            "VALUES ('prn_truncpriv0001aaa', 2)"
        )
    )
    admin.execute(
        text(
            "INSERT INTO knowledge.record_events ("
            "event_id, principal_id, sequence_number, record_family, record_id, "
            "event_kind, record_version, changed_fields, source_capability, "
            "actor_class, classification, occurred_at"
            ") VALUES ("
            "'rcev_truncpriv0001event', 'prn_truncpriv0001aaa', 1, 'task', "
            "'task_truncpriv0001task', 'created', 1, ARRAY['title'], 'tasks.create', "
            "'principal', 'private_local', '2026-10-02T12:00:00Z')"
        )
    )
    admin.execute(text("RESET SESSION AUTHORIZATION"))
    # Test-local, on this disposable clone: the owner owns only the feed, so it is
    # granted TRUNCATE on the one Knowledge table that references it, which lets a
    # combined TRUNCATE get past the foreign-key refusal to the feed's trigger.
    admin.execute(
        text(f"GRANT TRUNCATE ON knowledge.knowledge_submission_trigger_events TO {OWNER_ROLE}")
    )
    admin.execute(text(f"SET SESSION AUTHORIZATION {OWNER_ROLE}"))
    try:
        # KLP-WP-02: `knowledge_submission_trigger_events` now cites the feed by a
        # foreign key, so a bare TRUNCATE of `record_events` is refused one step
        # earlier, by the server (0A000), before its refusal trigger is reached.
        # Truncating the referencing table with it reaches the trigger, as before.
        with pytest.raises(DBAPIError) as referenced:
            admin.execute(text("TRUNCATE TABLE knowledge.record_events"))
        assert _sqlstate(referenced.value) == FEATURE_NOT_SUPPORTED, str(referenced.value)
        for statement in (
            "TRUNCATE TABLE knowledge.record_events, knowledge.knowledge_submission_trigger_events",
            "TRUNCATE TABLE knowledge.record_event_sequences",
            "UPDATE knowledge.record_events SET record_version = 2 "
            "WHERE event_id = 'rcev_truncpriv0001event'",
            "DELETE FROM knowledge.record_events WHERE event_id = 'rcev_truncpriv0001event'",
        ):
            with pytest.raises(DBAPIError) as refused:
                admin.execute(text(statement))
            assert _sqlstate(refused.value) == RESTRICT_VIOLATION, f"{statement}: {refused.value}"
        remaining = admin.execute(text("SELECT count(*) FROM knowledge.record_events")).scalar_one()
    finally:
        admin.execute(text("RESET SESSION AUTHORIZATION"))
        admin.close()
    assert remaining == 1


def test_runtime_role_attributes_are_not_privileged(provisioned: Engine) -> None:
    with provisioned.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolcanlogin, "
                    "rolinherit FROM pg_roles WHERE rolname = :name"
                ),
                {"name": RUNTIME_ROLE},
            )
            .mappings()
            .one()
        )
    assert list(row.values()) == [False, False, False, False, False, False]
    with provisioned.connect() as connection:
        owner = connection.execute(
            text(
                "SELECT pg_get_userbyid(c.relowner) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'knowledge' AND c.relname = 'record_events'"
            )
        ).scalar_one()
    assert owner == OWNER_ROLE


def test_runtime_pages_the_remote_knowledge_family_with_withholding(
    provisioned: Engine, cloned_database_url: str
) -> None:
    """KLP-WP-03 (DEV-13): the restricted runtime role executes the Knowledge feed term.

    A remote page over `knowledge_assertion` plans the Knowledge withholding
    term, which names the Knowledge relations and the capture lifecycle ledger.
    Run as the provisioned runtime session, the page must succeed, carry the
    permitted assertion's event and withhold the restricted one.
    """
    from my_pa.domain.record_events import RecordEventFamily
    from my_pa.infrastructure.persistence.record_events import SqlRecordEventReader
    from tests.database.test_knowledge_assertion_repository import (
        KnowledgeRuntime,
        new_principal,
    )
    from tests.security.test_knowledge_assertion_disclosure import restrict_assertion

    runtime = KnowledgeRuntime(cloned_database_url)
    try:
        principal = new_principal()
        permitted = runtime.create(principal, "klp03-role-permitted", value="Permitted value")
        withheld = runtime.create(principal, "klp03-role-withheld", value="Withheld value")
        restrict_assertion(runtime.engine, principal, withheld["assertion_id"])
    finally:
        runtime.close()
    families = frozenset({RecordEventFamily.KNOWLEDGE_ASSERTION})
    with provisioned.connect() as connection:
        connection.execute(text(f"SET SESSION AUTHORIZATION {RUNTIME_ROLE}"))
        connection.commit()
        try:
            assert connection.execute(text("SELECT session_user")).scalar_one() == RUNTIME_ROLE
            reader = SqlRecordEventReader(connection)
            remote = reader.page(
                principal_id=principal,
                after_sequence=0,
                families=families,
                include_restricted_memory=False,
                limit=10,
            )
            local = reader.page(
                principal_id=principal,
                after_sequence=0,
                families=families,
                include_restricted_memory=True,
                limit=10,
            )
            connection.rollback()
        finally:
            connection.execute(text("RESET SESSION AUTHORIZATION"))
            connection.commit()
    assert {row.record_id for row in remote.rows} == {permitted["assertion_id"]}
    assert {row.record_id for row in local.rows} == {
        permitted["assertion_id"],
        withheld["assertion_id"],
    }
    assert remote.high_watermark_event_id == remote.rows[-1].event_id
