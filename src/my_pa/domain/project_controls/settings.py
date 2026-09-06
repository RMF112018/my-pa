"""The per-Project Constraint settings: which calendar the Project's dates mean.

PC-CM-IMP-WP02. `ConstraintProjectSettings` is the domain half of
`knowledge.constraint_project_settings`, whose primary key `(principal_id,
project_id)` *is* its uniqueness: one Principal, one Project, one row.

`timezone_name` is the IANA zone name `business_time.project_today` resolves
through `ZoneInfo`. This class deliberately declares **no default**: a Project
whose calendar nobody has stated is a Project whose Due dates nobody can
compute, and inventing `UTC` here would silently move every Due Soon and
Overdue boundary for a construction project that never said so. What is checked
here is only what a name must look like to be a name at all — non-blank,
bounded, and free of whitespace — because whether a well-formed name is a real
zone is `ZoneInfo`'s answer, not a second, drifting copy of the tz database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "MAX_PROJECT_TIMEZONE_NAME_CHARACTERS",
    "ConstraintProjectSettings",
    "ConstraintProjectSettingsError",
]

#: The stored bound on `constraint_project_settings.timezone_name`.
MAX_PROJECT_TIMEZONE_NAME_CHARACTERS: Final = 64


class ConstraintProjectSettingsError(ValueError):
    """Project constraint settings were not well-formed. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConstraintProjectSettings:
    """One Project's Constraint settings, owned by one Principal."""

    principal_id: str
    project_id: str
    timezone_name: str
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        if not self.timezone_name.strip():
            raise ConstraintProjectSettingsError(
                "project_timezone_blank", "a project timezone name is non-blank"
            )
        if len(self.timezone_name) > MAX_PROJECT_TIMEZONE_NAME_CHARACTERS:
            raise ConstraintProjectSettingsError(
                "project_timezone_too_long", "a project timezone name exceeds the stored bound"
            )
        if any(character.isspace() for character in self.timezone_name):
            raise ConstraintProjectSettingsError(
                "project_timezone_has_whitespace",
                "a project timezone name carries no whitespace",
            )
        if self.version < 1:
            raise ConstraintProjectSettingsError(
                "project_settings_version_not_positive", "version is a positive integer"
            )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
