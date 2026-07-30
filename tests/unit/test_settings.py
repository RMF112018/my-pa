"""Settings load safely and fail closed."""

from __future__ import annotations

import pytest

from my_pa.bootstrap.settings import (
    ENV_PREFIX,
    Environment,
    LogLevel,
    Settings,
    SettingsError,
    load_settings,
)


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


@pytest.mark.parametrize("raw", ["0", "-1", "1001"])
def test_out_of_range_page_size_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings({f"{ENV_PREFIX}MAX_PAGE_SIZE": raw})


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings({f"{ENV_PREFIX}ENVIRONMENT": "production"})


def test_settings_hold_no_secret_shaped_field() -> None:
    for name in Settings.model_fields:
        for token in ("password", "secret", "token", "key", "credential", "dsn", "url", "path"):
            assert token not in name, f"settings field {name!r} looks secret-bearing"
