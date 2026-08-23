"""GSQS remote-eval Settings: defaults, enable fail-closed, no live secrets."""

from __future__ import annotations

from pathlib import Path

import pytest

from my_pa.bootstrap.settings import ENV_PREFIX, Settings, SettingsError, load_settings
from my_pa.contracts.oauth import valid_operator_secret

DATABASE_URL = f"{ENV_PREFIX}DATABASE_URL"
_A_URL = "postgresql+psycopg://someone@db.invalid:5432/somewhere"
PUBLIC_ORIGIN = "https://my-pa-gsqs.bobby-fetting.me"
AUDIENCE = f"{PUBLIC_ORIGIN}/mcp"
EVAL_OPERATOR_SECRET = "s" * 43


def _environment(**overrides: str) -> dict[str, str]:
    return {DATABASE_URL: _A_URL, **overrides}


def _enabled(**overrides: str) -> dict[str, str]:
    values = {
        DATABASE_URL: _A_URL,
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_ENABLED": "true",
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_PUBLIC_ORIGIN": PUBLIC_ORIGIN,
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": "gsqs-eval-state-root-synthetic",
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_OAUTH_OPERATOR_SECRET": EVAL_OPERATOR_SECRET,
    }
    values.update(overrides)
    return values


def test_gsqs_remote_eval_defaults_are_disabled_and_empty_state_root() -> None:
    settings = load_settings(_environment())
    assert settings.gsqs_remote_eval_enabled is False
    assert settings.gsqs_remote_eval_public_origin == ""
    assert settings.gsqs_remote_eval_port == 8767
    assert settings.gsqs_remote_eval_state_root == ""
    assert settings.gsqs_remote_eval_session_ttl_seconds == 259200
    assert settings.gsqs_remote_eval_retention_seconds == 1_209_600
    assert settings.gsqs_remote_eval_max_image_bytes == 8_388_608
    assert settings.gsqs_remote_eval_max_result_bytes == 1_048_576
    assert settings.gsqs_remote_eval_max_concurrency == 1
    assert settings.gsqs_remote_eval_oauth_scope == "my-pa.gsqs.evaluate"
    assert settings.gsqs_remote_eval_allowed_origins == ""
    assert settings.gsqs_remote_eval_oauth_audience == AUDIENCE
    assert settings.gsqs_remote_eval_oauth_operator_secret == ""
    assert "/srv" not in settings.gsqs_remote_eval_state_root
    assert Settings(database_url=_A_URL).gsqs_remote_eval_enabled is False


def test_disabled_eval_does_not_require_oauth_operator_secret() -> None:
    settings = load_settings(_environment())
    assert settings.oauth_operator_secret == ""
    assert settings.gsqs_remote_eval_oauth_operator_secret == ""
    assert settings.remote_mcp_enabled is False


def test_enabled_eval_does_not_require_production_oauth_operator_secret(tmp_path: Path) -> None:
    settings = load_settings(
        _enabled(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": str(tmp_path)})
    )
    assert settings.gsqs_remote_eval_enabled is True
    assert settings.oauth_operator_secret == ""
    assert valid_operator_secret(settings.gsqs_remote_eval_oauth_operator_secret)
    assert settings.remote_mcp_enabled is False
    assert EVAL_OPERATOR_SECRET not in repr(settings)
    assert Settings.model_fields["gsqs_remote_eval_oauth_operator_secret"].repr is False


def test_enabled_without_eval_oauth_operator_secret_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="GSQS_REMOTE_EVAL_OAUTH_OPERATOR_SECRET"):
        load_settings(
            _enabled(
                **{
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": str(tmp_path),
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_OAUTH_OPERATOR_SECRET": "",
                }
            )
        )


def test_eval_operator_secret_must_not_equal_production_secret(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="must not equal"):
        load_settings(
            _enabled(
                **{
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": str(tmp_path),
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_OAUTH_OPERATOR_SECRET": EVAL_OPERATOR_SECRET,
                    f"{ENV_PREFIX}OAUTH_OPERATOR_SECRET": EVAL_OPERATOR_SECRET,
                }
            )
        )


def test_enabled_without_public_origin_fails_closed() -> None:
    with pytest.raises(SettingsError, match="GSQS_REMOTE_EVAL_PUBLIC_ORIGIN"):
        load_settings(_enabled(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_PUBLIC_ORIGIN": ""}))


def test_enabled_without_state_root_fails_closed() -> None:
    with pytest.raises(SettingsError, match="GSQS_REMOTE_EVAL_STATE_ROOT"):
        load_settings(_enabled(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": ""}))


def test_enabled_http_origin_fails_closed() -> None:
    with pytest.raises(SettingsError, match="HTTPS origin"):
        load_settings(
            _enabled(
                **{
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_PUBLIC_ORIGIN": (
                        "http://my-pa-gsqs.bobby-fetting.me"
                    )
                }
            )
        )


def test_enabled_origin_with_path_fails_closed() -> None:
    with pytest.raises(SettingsError, match="HTTPS origin"):
        load_settings(
            _enabled(
                **{
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_PUBLIC_ORIGIN": (
                        "https://my-pa-gsqs.bobby-fetting.me/mcp"
                    )
                }
            )
        )


def test_enabled_with_tmp_state_root_and_https_origin_loads(tmp_path: Path) -> None:
    settings = load_settings(
        _enabled(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": str(tmp_path)})
    )
    assert settings.gsqs_remote_eval_enabled is True
    assert settings.gsqs_remote_eval_state_root == str(tmp_path)
    assert "/srv" not in settings.gsqs_remote_eval_state_root
    assert settings.gsqs_remote_eval_transport_hosts(bind_host="127.0.0.1", port=8767) == (
        "127.0.0.1",
        "127.0.0.1:8767",
        "my-pa-gsqs.bobby-fetting.me",
        "my-pa-gsqs.bobby-fetting.me:8767",
    )


def test_max_concurrency_must_equal_one() -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings(_environment(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_MAX_CONCURRENCY": "2"}))


def test_wildcard_allowed_origin_fails_closed() -> None:
    with pytest.raises(SettingsError, match="wildcard"):
        load_settings(_environment(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_ALLOWED_ORIGINS": "*"}))
    with pytest.raises(SettingsError, match="wildcard"):
        load_settings(
            _enabled(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_ALLOWED_ORIGINS": "https://chat.example, *"})
        )


def test_session_ttl_is_bounded() -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings(_environment(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_SESSION_TTL_SECONDS": "60"}))
    settings = load_settings(
        _environment(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_SESSION_TTL_SECONDS": "3600"})
    )
    assert settings.gsqs_remote_eval_session_ttl_seconds == 3600


def test_allowed_origins_split_on_comma_or_space(tmp_path: Path) -> None:
    settings = load_settings(
        _enabled(
            **{
                f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": str(tmp_path),
                f"{ENV_PREFIX}GSQS_REMOTE_EVAL_ALLOWED_ORIGINS": (
                    "https://a.example.invalid, https://b.example.invalid"
                ),
            }
        )
    )
    assert settings.gsqs_remote_eval_origin_allowlist() == (
        "https://a.example.invalid",
        "https://b.example.invalid",
    )


def test_empty_oauth_scope_fails_closed() -> None:
    with pytest.raises(SettingsError, match="scope"):
        load_settings(_environment(**{f"{ENV_PREFIX}GSQS_REMOTE_EVAL_OAUTH_SCOPE": ""}))


def test_enabled_audience_must_match_public_origin_host(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="audience"):
        load_settings(
            _enabled(
                **{
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": str(tmp_path),
                    f"{ENV_PREFIX}GSQS_REMOTE_EVAL_OAUTH_AUDIENCE": (
                        "https://other.example.invalid/mcp"
                    ),
                }
            )
        )


def test_remote_mcp_validation_is_unchanged_when_eval_fields_are_present() -> None:
    values = {
        DATABASE_URL: _A_URL,
        f"{ENV_PREFIX}REMOTE_MCP_ENABLED": "true",
        f"{ENV_PREFIX}REMOTE_MCP_PUBLIC_HOST": "mcp.example.invalid",
        f"{ENV_PREFIX}OAUTH_AUTHORIZATION_SERVER": "https://mcp.example.invalid",
        f"{ENV_PREFIX}OAUTH_AUDIENCE": "https://mcp.example.invalid/mcp",
        f"{ENV_PREFIX}OAUTH_SCOPES": "my-pa.read",
        f"{ENV_PREFIX}OAUTH_OPERATOR_SECRET": "s" * 43,
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_ENABLED": "false",
    }
    assert load_settings(values).remote_mcp_enabled is True
    with pytest.raises(SettingsError, match="exact HTTPS public origin"):
        load_settings(
            {**values, f"{ENV_PREFIX}OAUTH_AUTHORIZATION_SERVER": "http://mcp.example.invalid"}
        )
