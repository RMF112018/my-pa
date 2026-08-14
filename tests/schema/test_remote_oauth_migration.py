from __future__ import annotations

from pathlib import Path

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    oauth_access_tokens,
    oauth_authorization_codes,
    remote_capability_grants,
    remote_clients,
    remote_security_controls,
)
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT / "migrations/versions/20260813_e3b7a1d5c942_add_remote_oauth_identity_and_grants.py"
)
ORIGIN_MIGRATION = (
    ROOT
    / "migrations/versions/20260814_4f6a9c2d8e17_replace_entra_remote_identity_with_origin_oauth.py"
)


def test_runtime_remote_identity_tables_match_the_frozen_migration() -> None:
    text = MIGRATION.read_text() + ORIGIN_MIGRATION.read_text()
    assert {
        table.name for table in (remote_clients, remote_capability_grants, remote_security_controls)
    } == {"remote_clients", "remote_capability_grants", "remote_security_controls"}
    for table in (remote_clients, remote_capability_grants, remote_security_controls):
        assert f"CREATE TABLE identity.{table.name}" in text
        for column in table.c:
            assert column.name in text


def test_remote_controls_are_created_fail_closed() -> None:
    text = MIGRATION.read_text()
    assert "remote_enabled, writes_enabled" in text
    assert "VALUES (true, false, false, now())" in text
    assert "capability_version" in text
    assert "external_scope" in text
    assert "revoked_at" in text
    assert "expires_at" in text


def test_remote_tables_share_the_canonical_identity_metadata() -> None:
    assert REMOTE_IDENTITY_METADATA is IDENTITY_METADATA
    assert {
        "user_accounts",
        "principal_scope_grants",
        "remote_clients",
        "remote_capability_grants",
        "remote_security_controls",
        "oauth_authorization_codes",
        "oauth_access_tokens",
    }.issubset({table.name for table in IDENTITY_METADATA.tables.values()})


def test_origin_oauth_migration_removes_entra_identity_and_hashes_credentials() -> None:
    text = ORIGIN_MIGRATION.read_text()
    assert "DROP CONSTRAINT remote_clients_principal_id_fkey" in text
    assert "migration refused: legacy remote clients require explicit operator resolution" in text
    assert "remote_client_is_local_operator" in text
    assert str(LOCAL_OPERATOR_UUID) in text
    assert "code_hash varchar(64) PRIMARY KEY" in text
    assert "token_hash varchar(64) PRIMARY KEY" in text
    for table in (oauth_authorization_codes, oauth_access_tokens):
        assert f"CREATE TABLE identity.{table.name}" in text
