"""The migration URL is required, separate, and never echoed."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from my_pa.bootstrap.migration_authority import (
    MIGRATION_DATABASE_URL_ENV,
    OFFLINE_RENDER_URL,
    load_migration_authority,
)
from my_pa.bootstrap.settings import SettingsError, load_settings

_RUNTIME = "postgresql+psycopg://runtime.invalid/runtime_db"
_MIGRATION = "postgresql+psycopg://migrator:super-secret-value@db.invalid/migration_db"


def test_online_migration_refuses_to_fall_back_to_the_runtime_url() -> None:
    with pytest.raises(SettingsError, match="no fallback to MY_PA_DATABASE_URL") as refused:
        load_migration_authority({"MY_PA_DATABASE_URL": _RUNTIME})
    assert "runtime.invalid" not in str(refused.value)


def test_a_migration_url_is_parsed_without_echoing_its_secret() -> None:
    authority = load_migration_authority({MIGRATION_DATABASE_URL_ENV: _MIGRATION})
    parsed = authority.parsed_database_url()
    assert parsed.database == "migration_db"
    assert parsed.password == make_url(_MIGRATION).password
    with pytest.raises(SettingsError, match="must name a host") as refused:
        load_migration_authority({MIGRATION_DATABASE_URL_ENV: "postgresql+psycopg:///missing"})
    assert "super-secret-value" not in str(refused.value)


def test_offline_render_url_has_no_password() -> None:
    assert "secret" not in OFFLINE_RENDER_URL
    assert "@" not in OFFLINE_RENDER_URL.split("://", 1)[1]


def test_application_settings_ignore_the_migration_url() -> None:
    loaded = load_settings({"MY_PA_DATABASE_URL": _RUNTIME, MIGRATION_DATABASE_URL_ENV: _MIGRATION})
    assert not hasattr(loaded, "migration_database_url")
    assert "super-secret-value" not in repr(loaded)
    with pytest.raises(SettingsError, match="unknown MY_PA_ settings"):
        load_settings({"MY_PA_MIGRATION_DATABASE_URLS": _MIGRATION, "MY_PA_DATABASE_URL": _RUNTIME})
