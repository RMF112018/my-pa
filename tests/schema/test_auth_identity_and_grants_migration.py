"""Normalize account identity and add digest-only auth grants."""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.auth_grants import auth_grants
from my_pa.infrastructure.persistence.user_accounts import user_accounts
from my_pa.infrastructure.persistence.webauthn_auth import (
    _CHALLENGE_PURPOSE_CHECK,
    webauthn_challenges,
)

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "4e9a1c7b2d60"
PREVIOUS: Final = "c5b71e0a8d43"
#: The revision that landed on this one, making it the chain head instead.
SUCCESSOR: Final = "f7a2c9d51e64"
CONSTRAINT_SYNC: Final = "b8e4d6f20a11"
HEAD: Final = "c1a8e4d70b29"
MIGRATION: Final = (
    ROOT / "migrations/versions/20260907_4e9a1c7b2d60_normalize_auth_identity_and_add_grants.py"
)
LOCAL_OPERATOR: Final = UUID("24abf5d2-d0c2-5e1c-82f6-e72425e9ed37")
SYNTHETIC_TID: Final = "11111111-2222-3333-4444-555555555555"
WHEN: Final = datetime(2026, 9, 7, 12, tzinfo=UTC)
NEW_CHALLENGE_PURPOSES: Final = (
    "bootstrap_registration",
    "credential_registration",
    "operator_recovery_registration",
)
ACCOUNT_CONSTRAINTS: Final = (
    "user_account_identity_provider_is_known",
    "user_account_identity_subject_is_present",
    "user_account_provider_claim_shape",
    "user_account_local_binding_is_fixed",
    "one_user_account_per_provider_subject",
)
GRANT_CONSTRAINTS: Final = (
    "auth_grant_digest_is_sha256_hex",
    "auth_grant_purpose_is_known",
    "auth_grant_target_is_local_operator",
    "auth_grant_expiry_is_bounded",
    "auth_grant_terminal_state_is_exclusive",
    "auth_grant_session_matches_purpose",
    "auth_grant_exchanged_at_is_ordered",
    "auth_grant_consumed_at_is_ordered",
    "auth_grant_revoke_reason_matches_revocation",
)


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    return empty_database_url


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        yield engine
    finally:
        engine.dispose()


def _constraint_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = 'identity' AND t.relname = :table"
                ),
                {"table": table},
            ).scalars()
        )


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'identity' AND table_name = :table"
                ),
                {"table": table},
            ).scalars()
        )


def _purpose_check(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = 'identity' AND t.relname = 'webauthn_challenges' "
                    "AND c.conname = 'webauthn_challenge_purpose_is_known'"
                )
            ).scalar_one()
        )


def test_the_chain_has_exactly_one_head_and_this_revision_is_beneath_it() -> None:
    """`f7a2c9d51e64` (PC-CM-IMP-WP07) landed on this revision, so it is no longer
    the head. The claim worth keeping is that the chain still holds exactly one
    head and that this revision sits on it at a known position, asserted link by
    link rather than loosened to reachability.
    """
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [HEAD]
    assert script.get_revision(HEAD).down_revision == CONSTRAINT_SYNC
    assert script.get_revision(CONSTRAINT_SYNC).down_revision == SUCCESSOR
    assert script.get_revision(SUCCESSOR).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 101


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__"}
    assert "24abf5d2-d0c2-5e1c-82f6-e72425e9ed37" in source
    assert "'bootstrap'" in source
    assert "'operator_recovery'" in source
    assert "'credential_administration'" in source
    assert "exchanged_at" in source
    assert "my_pa.domain" not in source
    assert "infrastructure.persistence" not in source
    assert "AccountIdentityProvider" not in source
    assert "AuthGrantPurpose" not in source


def test_runtime_metadata_columns_and_checks_match_ddl() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "exchanged_at" in auth_grants.c
    assert auth_grants.c.exchanged_at.name in source
    assert "auth_grant_id" in webauthn_challenges.c
    assert "identity_provider" in user_accounts.c
    assert "identity_subject" in user_accounts.c
    for column in auth_grants.c:
        assert column.name in source
    assert "auth_grant_id" in source
    for name in (*ACCOUNT_CONSTRAINTS, *GRANT_CONSTRAINTS, "webauthn_challenge_purpose_is_known"):
        assert name in source
        if name.startswith("auth_grant_"):
            assert any(constraint.name == name for constraint in auth_grants.constraints)
    for purpose in NEW_CHALLENGE_PURPOSES:
        assert f"'{purpose}'" in source
        assert f"'{purpose}'" in _CHALLENGE_PURPOSE_CHECK
    assert "exchanged_at" in {column.name for column in auth_grants.c}


@pytest.mark.database
@pytest.mark.migration_empty_to_head
def test_empty_schema_reaches_the_new_head(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == HEAD
            )
        assert "auth_grants" in inspect(engine).get_table_names(schema="identity")
        assert {"identity_provider", "identity_subject", "exchanged_at"} <= (
            _columns(engine, "user_accounts") | _columns(engine, "auth_grants")
        )
        names = _constraint_names(engine, "auth_grants")
        assert set(GRANT_CONSTRAINTS) <= names
        assert "auth_grant_id" in _columns(engine, "webauthn_challenges")
        account_constraints = _constraint_names(engine, "user_accounts")
        assert set(ACCOUNT_CONSTRAINTS) <= account_constraints
        assert "one_user_account_per_entra_identity" not in account_constraints
    finally:
        engine.dispose()


@pytest.mark.database
@pytest.mark.migration_edge
def test_predecessor_backfills_identity_preserves_ids_and_adds_empty_grants(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), PREVIOUS)
    engine = create_database_engine(disposable_database)
    entra_id = uuid4()
    entra_principal = uuid4()
    synthetic_id = uuid4()
    synthetic_principal = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO identity.user_accounts "
                    "(id, principal_id, tid, oid, first_seen_at) "
                    "VALUES (:id, :principal_id, :tid, :oid, :now)"
                ),
                [
                    {
                        "id": entra_id,
                        "principal_id": entra_principal,
                        "tid": "tenant-entra",
                        "oid": "object-entra",
                        "now": WHEN,
                    },
                    {
                        "id": synthetic_id,
                        "principal_id": synthetic_principal,
                        "tid": SYNTHETIC_TID,
                        "oid": "object-synthetic",
                        "now": WHEN,
                    },
                ],
            )
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            rows = {
                row.id: row
                for row in connection.execute(
                    text(
                        "SELECT id, principal_id, identity_provider, identity_subject, tid, oid "
                        "FROM identity.user_accounts"
                    )
                )
            }
            entra = rows[entra_id]
            synthetic = rows[synthetic_id]
            assert entra.principal_id == entra_principal
            assert entra.identity_provider == "entra"
            assert entra.identity_subject == "tenant-entra:object-entra"
            assert entra.tid == "tenant-entra" and entra.oid == "object-entra"
            assert synthetic.principal_id == synthetic_principal
            assert synthetic.identity_provider == "synthetic"
            assert synthetic.identity_subject == f"{SYNTHETIC_TID}:object-synthetic"
            grants = connection.execute(
                text("SELECT count(*) FROM identity.auth_grants")
            ).scalar_one()
            assert grants == 0
        account_constraints = _constraint_names(engine, "user_accounts")
        assert set(ACCOUNT_CONSTRAINTS) <= account_constraints
        # `(identity_provider, identity_subject)` is the sole account unique after
        # the upgrade: a surviving `(tid, oid)` unique is the one a concurrent
        # first sign-in would violate, since `ON CONFLICT` names only the other.
        assert "one_user_account_per_entra_identity" not in account_constraints
        definition = _purpose_check(engine)
        for purpose in NEW_CHALLENGE_PURPOSES:
            assert purpose in definition
        for retained in (
            "registration",
            "authentication",
            "credential_administration",
            "recovery",
            "step_up",
        ):
            assert retained in definition
    finally:
        engine.dispose()


@pytest.mark.database
def test_local_insert_succeeds_only_for_the_fixed_binding(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError) as wrong_uuid, migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.user_accounts "
                "(id, principal_id, identity_provider, identity_subject, tid, oid, "
                " first_seen_at, consent_state, lifecycle_state) "
                "VALUES (:id, :principal_id, 'local', 'local-operator', NULL, NULL, "
                " :now, 'pending', 'active')"
            ),
            {"id": uuid4(), "principal_id": uuid4(), "now": WHEN},
        )
    assert "user_account_local_binding_is_fixed" in str(wrong_uuid.value)
    with pytest.raises(IntegrityError) as wrong_subject, migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.user_accounts "
                "(id, principal_id, identity_provider, identity_subject, tid, oid, "
                " first_seen_at, consent_state, lifecycle_state) "
                "VALUES (:id, :principal_id, 'local', 'other-operator', NULL, NULL, "
                " :now, 'pending', 'active')"
            ),
            {"id": uuid4(), "principal_id": LOCAL_OPERATOR, "now": WHEN},
        )
    assert "user_account_local_binding_is_fixed" in str(wrong_subject.value)
    with pytest.raises(IntegrityError) as tid_present, migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.user_accounts "
                "(id, principal_id, identity_provider, identity_subject, tid, oid, "
                " first_seen_at, consent_state, lifecycle_state) "
                "VALUES (:id, :principal_id, 'local', 'local-operator', 'tid', NULL, "
                " :now, 'pending', 'active')"
            ),
            {"id": uuid4(), "principal_id": LOCAL_OPERATOR, "now": WHEN},
        )
    assert "user_account_provider_claim_shape" in str(tid_present.value)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.user_accounts "
                "(id, principal_id, identity_provider, identity_subject, tid, oid, "
                " first_seen_at, consent_state, lifecycle_state) "
                "VALUES (:id, :principal_id, 'local', 'local-operator', NULL, NULL, "
                " :now, 'pending', 'active')"
            ),
            {"id": uuid4(), "principal_id": LOCAL_OPERATOR, "now": WHEN},
        )


@pytest.mark.database
def test_grant_target_check_refuses_other_principals(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError) as refused, migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.auth_grants "
                "(id, grant_digest, purpose, target_principal_id, created_at, expires_at) "
                "VALUES (:id, :digest, 'bootstrap', :principal, :created, :expires)"
            ),
            {
                "id": uuid4(),
                "digest": "ab" * 32,
                "principal": uuid4(),
                "created": WHEN,
                "expires": WHEN + timedelta(minutes=10),
            },
        )
    assert "auth_grant_target_is_local_operator" in str(refused.value)


@pytest.mark.database
@pytest.mark.migration_empty_to_head
def test_downgrade_empty_and_entra_only_succeeds_and_data_bearing_refuses(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    command.downgrade(_config(), PREVIOUS)
    engine = create_database_engine(disposable_database)
    try:
        assert "auth_grants" not in inspect(engine).get_table_names(schema="identity")
        assert "identity_provider" not in _columns(engine, "user_accounts")
        restored_constraints = _constraint_names(engine, "user_accounts")
        assert "one_user_account_per_entra_identity" in restored_constraints
        assert "one_user_account_per_provider_subject" not in restored_constraints
        with engine.connect() as connection:
            tid_nullable = connection.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'identity' AND table_name = 'user_accounts' "
                    "AND column_name = 'tid'"
                )
            ).scalar_one()
            assert tid_nullable == "NO"
        entra_id = uuid4()
        entra_principal = uuid4()
        synthetic_id = uuid4()
        synthetic_principal = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO identity.user_accounts "
                    "(id, principal_id, tid, oid, first_seen_at) "
                    "VALUES (:id, :principal_id, :tid, :oid, :now)"
                ),
                [
                    {
                        "id": entra_id,
                        "principal_id": entra_principal,
                        "tid": "tenant-entra",
                        "oid": "object-entra",
                        "now": WHEN,
                    },
                    {
                        "id": synthetic_id,
                        "principal_id": synthetic_principal,
                        "tid": SYNTHETIC_TID,
                        "oid": "object-synthetic",
                        "now": WHEN,
                    },
                ],
            )
        command.upgrade(_config(), REVISION)
        command.downgrade(_config(), PREVIOUS)
        with engine.connect() as connection:
            restored = {
                row.id: row
                for row in connection.execute(
                    text("SELECT id, principal_id, tid, oid FROM identity.user_accounts")
                )
            }
            assert restored[entra_id].principal_id == entra_principal
            assert restored[synthetic_id].tid == SYNTHETIC_TID
            assert "identity_provider" not in _columns(engine, "user_accounts")
            assert "auth_grants" not in inspect(engine).get_table_names(schema="identity")
        command.upgrade(_config(), REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO identity.auth_grants "
                    "(id, grant_digest, purpose, target_principal_id, created_at, expires_at) "
                    "VALUES (:id, :digest, 'bootstrap', :principal, :created, :expires)"
                ),
                {
                    "id": uuid4(),
                    "digest": "cd" * 32,
                    "principal": LOCAL_OPERATOR,
                    "created": WHEN,
                    "expires": WHEN + timedelta(minutes=10),
                },
            )
        with pytest.raises(Exception, match="auth remediation history cannot be represented"):
            command.downgrade(_config(), PREVIOUS)
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == REVISION
            )
            assert (
                connection.execute(text("SELECT count(*) FROM identity.auth_grants")).scalar_one()
                == 1
            )
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM identity.auth_grants"))
            connection.execute(
                text(
                    "INSERT INTO identity.user_accounts "
                    "(id, principal_id, identity_provider, identity_subject, tid, oid, "
                    " first_seen_at, consent_state, lifecycle_state) "
                    "VALUES (:id, :principal_id, 'local', 'local-operator', NULL, NULL, "
                    " :now, 'pending', 'active')"
                ),
                {"id": uuid4(), "principal_id": LOCAL_OPERATOR, "now": WHEN},
            )
        with pytest.raises(Exception, match="auth remediation history cannot be represented"):
            command.downgrade(_config(), PREVIOUS)
    finally:
        engine.dispose()
