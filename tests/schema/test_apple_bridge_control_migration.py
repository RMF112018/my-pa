"""NAS-07B schema contract for dedicated credentials and staged grants."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text

from my_pa.domain.native_apple import AppleMachineCredentialError
from my_pa.infrastructure.persistence.apple_bridge_credentials import (
    authenticate_apple_bridge_credential,
    register_apple_bridge_credential,
    revoke_apple_bridge_credential,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.tables import METADATA

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/20260812_a9e4c7b2d610_add_apple_bridge_credentials.py"
)
DATABASE = "my_pa_apple_bridge_test"


def test_migration_declares_separate_credential_and_staged_grant_planes() -> None:
    source = MIGRATION.read_text()
    for statement in (
        "CREATE TABLE knowledge.native_apple_bridge_credentials",
        "secret_sha256 text NOT NULL",
        "apple_bridge_credential_stays_in_principal",
        "CREATE TABLE knowledge.native_apple_read_grants",
        "apple_read_grant_authority_stays_in_principal",
        "apple_read_grant_page_limit_is_bounded",
    ):
        assert statement in source
    assert "secret text" not in source


def test_live_metadata_matches_the_two_new_tables() -> None:
    credential = METADATA.tables["knowledge.native_apple_bridge_credentials"]
    grant = METADATA.tables["knowledge.native_apple_read_grants"]
    assert set(credential.c.keys()) == {
        "credential_id",
        "bridge_id",
        "principal_id",
        "secret_sha256",
        "state",
        "created_at",
        "revoked_at",
    }
    assert grant.c.principal_id.nullable is False
    assert grant.c.cursor_private.nullable is True
    assert grant.c.delivered_at.nullable is True
    assert grant.c.delivery_lease_expires_at.nullable is True
    assert grant.c.delivered_to_credential_id.nullable is True


@pytest.mark.database
def test_database_head_contains_both_new_tables(native_engine: Engine) -> None:
    tables = set(inspect(native_engine).get_table_names(schema="knowledge"))
    assert {"native_apple_bridge_credentials", "native_apple_read_grants"} <= tables


@pytest.mark.database
def test_credentials_are_independently_identified_and_rotatable(native_engine: Engine) -> None:
    principal = "prn_0000000000000001"
    bridge = "nbrg_0000000000000001"
    at = datetime(2026, 8, 13, tzinfo=UTC)
    context = capture_context(principal)
    with native_engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO knowledge.native_bridges
                   (principal_id, bridge_id, protocol_version, label, created_at)
                   VALUES (:principal, :bridge, 'my-pa.native-source.v1', 'Synthetic', :at)"""
            ),
            {"principal": principal, "bridge": bridge, "at": at},
        )
        first = register_apple_bridge_credential(
            connection,
            bridge_id=bridge,
            secret_sha256=sha256(b"first-secret").hexdigest(),
            at=at,
            context=context,
        )
        second = register_apple_bridge_credential(
            connection,
            bridge_id=bridge,
            secret_sha256=sha256(b"second-secret").hexdigest(),
            at=at,
            context=context,
        )
    assert first != second
    identity = authenticate_apple_bridge_credential(
        native_engine, f"AppleBridgeCredential {second}:second-secret"
    )
    assert identity.credential_id == second
    assert identity.bridge_id == bridge
    with native_engine.begin() as connection:
        assert revoke_apple_bridge_credential(
            connection,
            credential_id=first,
            at=at,
            context=context,
        )
        assert not revoke_apple_bridge_credential(
            connection,
            credential_id=first,
            at=at,
            context=context,
        )
    with pytest.raises(AppleMachineCredentialError):
        authenticate_apple_bridge_credential(
            native_engine, f"AppleBridgeCredential {first}:first-secret"
        )


@pytest.fixture
def native_engine(db_engine: Engine) -> Engine:
    return db_engine
