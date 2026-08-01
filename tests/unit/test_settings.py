"""Settings load safely and fail closed."""

from __future__ import annotations

import pytest

from my_pa.bootstrap.settings import (
    DATABASE_URL_SCHEME,
    DEFAULT_DATABASE_URL,
    ENV_PREFIX,
    Environment,
    LogLevel,
    Settings,
    SettingsError,
    load_settings,
)

DATABASE_URL = f"{ENV_PREFIX}DATABASE_URL"


def test_defaults_are_safe() -> None:
    settings = load_settings({})
    assert settings.environment is Environment.LOCAL
    assert settings.log_level is LogLevel.INFO
    assert settings.redaction_enabled is True
    assert settings.contract_strict_mode is True


def test_unrelated_environment_variables_are_ignored() -> None:
    assert load_settings({"PATH": "/usr/bin", "HOME": "/root"}) == Settings()


def test_known_values_are_parsed() -> None:
    settings = load_settings(
        {
            f"{ENV_PREFIX}ENVIRONMENT": "test",
            f"{ENV_PREFIX}LOG_LEVEL": "debug",
            f"{ENV_PREFIX}MAX_PAGE_SIZE": "10",
        }
    )
    assert settings.environment is Environment.TEST
    assert settings.log_level is LogLevel.DEBUG
    assert settings.max_page_size == 10


def test_unknown_prefixed_variable_fails_closed() -> None:
    # A typo must not look accepted while the real setting keeps its default.
    with pytest.raises(SettingsError, match="unknown MY_PA_ settings"):
        load_settings({f"{ENV_PREFIX}REDACTION_ENABLE": "false"})


def test_redaction_cannot_be_disabled() -> None:
    with pytest.raises(SettingsError, match="redaction cannot be disabled"):
        load_settings({f"{ENV_PREFIX}REDACTION_ENABLED": "false"})


def test_strict_contract_parsing_cannot_be_disabled() -> None:
    with pytest.raises(SettingsError, match="strict contract parsing"):
        load_settings({f"{ENV_PREFIX}CONTRACT_STRICT_MODE": "0"})


def test_debug_log_level_does_not_disable_redaction() -> None:
    assert load_settings({f"{ENV_PREFIX}LOG_LEVEL": "debug"}).redaction_enabled is True


@pytest.mark.parametrize("raw", ["maybe", "", "2", "yes please"])
def test_unparseable_boolean_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must be a boolean"):
        load_settings({f"{ENV_PREFIX}REDACTION_ENABLED": raw})


@pytest.mark.parametrize("raw", ["ten", "", "1.5"])
def test_unparseable_integer_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must be an integer"):
        load_settings({f"{ENV_PREFIX}MAX_PAGE_SIZE": raw})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (f"{ENV_PREFIX}REDACTION_ENABLED", "SUPERSECRETVALUE"),
        (f"{ENV_PREFIX}CONTRACT_STRICT_MODE", "SUPERSECRETVALUE"),
        (f"{ENV_PREFIX}MAX_PAGE_SIZE", "SUPERSECRETVALUE"),
        (f"{ENV_PREFIX}MAX_PAGE_SIZE", "99999"),
        (f"{ENV_PREFIX}ENVIRONMENT", "SUPERSECRETVALUE"),
    ],
)
def test_error_messages_never_echo_the_supplied_value(key: str, value: str) -> None:
    """Settings are non-secret today; echoing input would make this a leak later.

    Both the coercion path and the validation path must stay quiet about values,
    so re-introducing an echo in either fails here.
    """
    with pytest.raises(SettingsError) as caught:
        load_settings({key: value})
    assert value not in str(caught.value)
    assert key in str(caught.value)


@pytest.mark.parametrize("raw", ["0", "-1", "1001"])
def test_out_of_range_page_size_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings({f"{ENV_PREFIX}MAX_PAGE_SIZE": raw})


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings({f"{ENV_PREFIX}ENVIRONMENT": "production"})


def test_only_the_database_url_may_be_credential_bearing() -> None:
    """One setting can carry a credential; a second one arriving is a decision.

    `database_url` is exempt because a PostgreSQL URL is where a password
    belongs when the environment supplies one. Every other field must stay
    plainly non-secret, so a `MY_PA_API_TOKEN` cannot appear as an ordinary
    setting and inherit this module's handling by accident.
    """
    tokens = ("password", "secret", "token", "key", "credential", "dsn", "url", "path")
    for name in Settings.model_fields:
        if name == "database_url":
            continue
        for token in tokens:
            assert token not in name, f"settings field {name!r} looks secret-bearing"


def test_the_default_database_url_carries_no_credential() -> None:
    # The committed default must be usable without being a secret. The password
    # comes from PGPASSWORD or ~/.pgpass, never from the repository.
    assert "@" in DEFAULT_DATABASE_URL  # a user is named
    authority = DEFAULT_DATABASE_URL.split("://", 1)[1].split("@", 1)[0]
    assert ":" not in authority, "the default database URL embeds a password"
    assert ":5433/" in DEFAULT_DATABASE_URL


def test_the_database_url_defaults_to_the_local_instance() -> None:
    assert load_settings({}).database_url == DEFAULT_DATABASE_URL


def test_a_supplied_database_url_is_used() -> None:
    supplied = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/other"
    assert load_settings({DATABASE_URL: supplied}).database_url == supplied


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not a url",
        "postgresql://my_pa@localhost:5433/my_pa",  # unpinned driver
        "postgresql+psycopg2://my_pa@localhost:5433/my_pa",  # wrong driver
        "postgresql+asyncpg://my_pa@localhost:5433/my_pa",  # wrong driver
        "sqlite:///my_pa.sqlite",  # not the canonical store
    ],
)
def test_a_database_url_with_the_wrong_scheme_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must use the postgresql\\+psycopg scheme"):
        load_settings({DATABASE_URL: raw})


def test_a_database_url_without_a_host_is_rejected() -> None:
    with pytest.raises(SettingsError, match="must name a host"):
        load_settings({DATABASE_URL: f"{DATABASE_URL_SCHEME}:///my_pa"})


@pytest.mark.parametrize("raw", ["://localhost:5433", "://localhost:5433/"])
def test_a_database_url_without_a_database_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must name a database"):
        load_settings({DATABASE_URL: DATABASE_URL_SCHEME + raw})


def test_an_invalid_database_url_error_never_echoes_the_url() -> None:
    """A rejected URL is the one setting value most likely to hold a password."""
    url = "postgresql+psycopg2://my_pa:SUPERSECRETVALUE@localhost:5433/my_pa"
    with pytest.raises(SettingsError) as caught:
        load_settings({DATABASE_URL: url})
    assert "SUPERSECRETVALUE" not in str(caught.value)
    assert url not in str(caught.value)
