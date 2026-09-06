"""Unit tests for the PC-CM-IMP-WP02 per-Project Constraint settings."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.project_controls.settings import (
    MAX_PROJECT_TIMEZONE_NAME_CHARACTERS,
    ConstraintProjectSettings,
    ConstraintProjectSettingsError,
)

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
PROJECT_ID = "prj_aaaa0001aaaa0001aaaa"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _settings(**overrides: object) -> ConstraintProjectSettings:
    values: dict[str, object] = {
        "principal_id": PRINCIPAL_ID,
        "project_id": PROJECT_ID,
        "timezone_name": "America/New_York",
        "version": 1,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return ConstraintProjectSettings(**values)  # type: ignore[arg-type]


def test_settings_are_keyed_by_one_principal_and_one_project() -> None:
    settings = _settings()
    assert settings.principal_id == PRINCIPAL_ID
    assert settings.project_id == PROJECT_ID
    assert settings.timezone_name == "America/New_York"


def test_there_is_no_default_timezone_to_fall_back_on() -> None:
    """Inventing one would silently move every Due Soon and Overdue boundary."""
    required = {
        field.name
        for field in fields(ConstraintProjectSettings)
        if field.default is field.default_factory is not None or field.name == "timezone_name"
    }
    assert "timezone_name" in required
    with pytest.raises(TypeError):
        ConstraintProjectSettings(  # type: ignore[call-arg]
            principal_id=PRINCIPAL_ID,
            project_id=PROJECT_ID,
            version=1,
            created_at=T0,
            updated_at=T0,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("principal_id", "prj_aaaa0001aaaa0001aaaa"),
        ("project_id", "prn_aaaa0001aaaa0001aaaa0001"),
    ],
)
def test_every_identifier_is_checked_for_its_own_kind(field: str, value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        _settings(**{field: value})


@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_a_blank_timezone_name_is_refused(name: str) -> None:
    with pytest.raises(ConstraintProjectSettingsError) as refusal:
        _settings(timezone_name=name)
    assert refusal.value.code in {"project_timezone_blank", "project_timezone_has_whitespace"}


@pytest.mark.parametrize("name", ["America/New York", "America/New_York ", " UTC"])
def test_a_timezone_name_carries_no_whitespace(name: str) -> None:
    with pytest.raises(ConstraintProjectSettingsError) as refusal:
        _settings(timezone_name=name)
    assert refusal.value.code == "project_timezone_has_whitespace"


def test_a_timezone_name_is_bounded_by_the_stored_column() -> None:
    with pytest.raises(ConstraintProjectSettingsError) as refusal:
        _settings(timezone_name="A/" + "b" * MAX_PROJECT_TIMEZONE_NAME_CHARACTERS)
    assert refusal.value.code == "project_timezone_too_long"


def test_zone_validity_is_left_to_zoneinfo_rather_than_a_second_tz_database() -> None:
    """A well-formed name this class accepts is one `ZoneInfo` can be asked about."""
    accepted = _settings(timezone_name="Not/AZone")
    assert accepted.timezone_name == "Not/AZone"
    with pytest.raises(Exception):  # noqa: B017 - ZoneInfo owns the answer, not this class
        ZoneInfo(accepted.timezone_name)
    assert ZoneInfo(_settings().timezone_name).key == "America/New_York"


def test_a_version_is_a_positive_integer() -> None:
    with pytest.raises(ConstraintProjectSettingsError) as refusal:
        _settings(version=0)
    assert refusal.value.code == "project_settings_version_not_positive"
    assert _settings(version=7).version == 7


def test_timestamps_are_normalised_to_utc_and_a_naive_one_is_refused() -> None:
    eastern = datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    settings = _settings(created_at=eastern)
    assert settings.created_at.tzinfo is UTC
    assert settings.created_at == eastern
    with pytest.raises(ValueError):
        _settings(updated_at=datetime(2026, 9, 1, 12, 0))


def test_settings_carry_no_credential_or_free_text_column() -> None:
    stored = {field.name for field in fields(ConstraintProjectSettings)}
    assert stored == {
        "principal_id",
        "project_id",
        "timezone_name",
        "version",
        "created_at",
        "updated_at",
    }
