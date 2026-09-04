"""FAST tests for disposable-database naming and protection rules."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import make_url

from tests.db.provisioning import (
    DISPOSABLE_NAME_PREFIX,
    LEGACY_IMPORT_VARIABLES,
    POSTGRESQL_IDENTIFIER_LIMIT,
    PROTECTED_CATALOGS,
    ProvisioningError,
    disposable_database_name,
    maintenance_url_from,
    require_disposable_name,
    restored_environ,
    sanitize_worker_id,
    sanitized_migration_environ,
)


def test_worker_ids_collapse_to_postgres_safe_tokens() -> None:
    assert sanitize_worker_id("gw0") == "gw0"
    assert sanitize_worker_id("master") == "master"
    assert sanitize_worker_id("GW-1") == "gw1"


def test_template_and_clone_names_stay_under_the_identifier_limit() -> None:
    template = disposable_database_name("t", "deadbeef", "gw12")
    clone = disposable_database_name("c", "deadbeef", "gw12", 999999)
    assert template.startswith(DISPOSABLE_NAME_PREFIX)
    assert clone.startswith(DISPOSABLE_NAME_PREFIX)
    assert len(template.encode()) <= POSTGRESQL_IDENTIFIER_LIMIT
    assert len(clone.encode()) <= POSTGRESQL_IDENTIFIER_LIMIT
    assert template != clone


def test_canonical_and_configured_names_are_refused() -> None:
    for name in (*PROTECTED_CATALOGS, "my_pa_ci", "someone_elses_db"):
        with pytest.raises(ProvisioningError):
            require_disposable_name(name)


def test_maintenance_url_never_targets_the_application_catalog() -> None:
    configured = make_url("postgresql+psycopg://my_pa@localhost:5432/my_pa_ci")
    maintenance = maintenance_url_from(configured)
    assert maintenance.database == "postgres"
    assert configured.database == "my_pa_ci"


def test_restored_environ_returns_an_unset_variable_to_absent() -> None:
    key = "MY_PA_TEST_PROVISIONING_ENV_RESTORE"
    os.environ.pop(key, None)
    with restored_environ({key: "temporary"}):
        assert os.environ[key] == "temporary"
    assert key not in os.environ


def test_sanitized_migration_environ_clears_legacy_import_variables() -> None:
    updates = sanitized_migration_environ(
        "postgresql+psycopg://my_pa@localhost:5432/my_pa_p_t_deadbeef_master"
    )
    assert updates["MY_PA_DATABASE_URL"].endswith("my_pa_p_t_deadbeef_master")
    for name in LEGACY_IMPORT_VARIABLES:
        assert updates[name] is None
