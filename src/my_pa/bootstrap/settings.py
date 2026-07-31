"""Process configuration.

Settings fail closed. An unknown `MY_PA_` variable, an unparseable value, or an
out-of-range value raises rather than falling back to a default, so a typo in a
security-relevant name cannot silently leave the safe setting in place.

No setting here holds a secret. Credentials, connection strings, and source roots
are not part of Phase 01 and must never be added to the committed example.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from pydantic import Field, ValidationError, model_validator

from my_pa.contracts.v1.base import StrictModel

__all__ = ["ENV_PREFIX", "Environment", "LogLevel", "Settings", "SettingsError", "load_settings"]

ENV_PREFIX: Final = "MY_PA_"


class Environment(StrEnum):
    """Deployment environment. There is no production value in Phase 01."""

    LOCAL = "local"
    TEST = "test"


class LogLevel(StrEnum):
    """Log verbosity."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SettingsError(ValueError):
    """Raised by `load_settings` when configuration is missing, unknown, or invalid.

    Constructing `Settings` directly raises Pydantic's `ValidationError` instead,
    because Pydantic wraps whatever a validator raises. `load_settings` is the
    supported entry point and normalises both cases to this type.
    """


class Settings(StrictModel):
    """Validated, non-secret process settings."""

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = LogLevel.INFO
    redaction_enabled: bool = True
    contract_strict_mode: bool = True
    max_page_size: int = Field(default=200, gt=0, le=1000)

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if not self.redaction_enabled:
            raise SettingsError(
                "redaction cannot be disabled; debug mode does not bypass redaction"
            )
        if not self.contract_strict_mode:
            raise SettingsError("strict contract parsing cannot be disabled")
        return self


_FIELD_NAMES: Final = frozenset(Settings.model_fields)

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _coerce(name: str, raw: str) -> object:
    """Convert one environment string to the type its field expects."""
    # Typed as `object` so identity checks below are plain comparisons rather
    # than type narrowing, which would make the second branch look unreachable.
    annotation: object = Settings.model_fields[name].annotation
    if annotation is bool:
        lowered = raw.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        # Name the setting and the expected type, never the supplied value.
        # Settings are non-secret today; echoing input would make this a
        # disclosure channel the moment one is not.
        raise SettingsError(f"{ENV_PREFIX}{name.upper()} must be a boolean")
    if annotation is int:
        try:
            return int(raw)
        except ValueError as exc:
            raise SettingsError(f"{ENV_PREFIX}{name.upper()} must be an integer") from exc
    return raw


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build `Settings` from `environ`, defaulting to the process environment.

    Any `MY_PA_`-prefixed variable that does not name a field is an error.
    Ignoring it would let `MY_PA_REDACTION_ENABLE=false` look accepted while
    redaction stayed on under a different name — or, worse, the reverse.
    """
    source = os.environ if environ is None else environ
    values: dict[str, object] = {}
    unknown: list[str] = []

    for key, raw in source.items():
        if not key.startswith(ENV_PREFIX):
            continue
        name = key[len(ENV_PREFIX) :].lower()
        if name not in _FIELD_NAMES:
            unknown.append(key)
            continue
        values[name] = _coerce(name, raw)

    if unknown:
        raise SettingsError(f"unknown {ENV_PREFIX} settings: {sorted(unknown)}")

    try:
        return Settings(**values)  # type: ignore[arg-type]
    except ValidationError as exc:
        # Report which setting failed and why, but not the offending value.
        # Settings are non-secret today; echoing inputs would turn this into a
        # disclosure channel the moment one is not.
        problems = "; ".join(
            f"{ENV_PREFIX}{'.'.join(str(part) for part in error['loc']).upper()}: {error['msg']}"
            for error in exc.errors()
        )
        raise SettingsError(f"invalid configuration: {problems}") from exc
