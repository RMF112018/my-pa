"""Migration-authority connection, separate from the application runtime URL.

Online Alembic reads ``MY_PA_MIGRATION_DATABASE_URL`` and nothing else. It does
not fall back to ``MY_PA_DATABASE_URL``. The application settings object does
not store this value. No credential is committed, and the errors raised here
name the variable without echoing the URL.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, SettingsError

__all__ = [
    "MIGRATION_DATABASE_URL_ENV",
    "OFFLINE_RENDER_URL",
    "MigrationAuthority",
    "load_migration_authority",
]

#: Process environment key for the migration principal. Not an application setting.
MIGRATION_DATABASE_URL_ENV: Final = "MY_PA_MIGRATION_DATABASE_URL"

#: Dialect rendering only. No user, no password, and not a reachable host.
OFFLINE_RENDER_URL: Final = "postgresql+psycopg://migration-offline.invalid/migration_offline"


class MigrationAuthority:
    """The one parse of the migration URL, handed to ``create_database_engine``."""

    def __init__(self, parsed: URL) -> None:
        self._parsed_database_url = parsed

    def parsed_database_url(self) -> URL:
        """The stored parse. The name is the connection-provenance contract."""
        return self._parsed_database_url


def _parse(url: str) -> URL:
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError) as exc:
        raise SettingsError(
            f"{MIGRATION_DATABASE_URL_ENV} is not a URL the engine can parse; it "
            f"must use the {DATABASE_URL_SCHEME} scheme and name a host and a database"
        ) from exc
    if parsed.drivername != DATABASE_URL_SCHEME:
        raise SettingsError(
            f"{MIGRATION_DATABASE_URL_ENV} must use the {DATABASE_URL_SCHEME} scheme"
        )
    if not parsed.host:
        raise SettingsError(f"{MIGRATION_DATABASE_URL_ENV} must name a host")
    if not parsed.database:
        raise SettingsError(f"{MIGRATION_DATABASE_URL_ENV} must name a database")
    return parsed


def load_migration_authority(
    environ: Mapping[str, str] | None = None,
) -> MigrationAuthority:
    """Require the migration URL. Never read the application database URL."""
    source = os.environ if environ is None else environ
    raw = source.get(MIGRATION_DATABASE_URL_ENV)
    if raw is None or not raw.strip():
        raise SettingsError(
            f"{MIGRATION_DATABASE_URL_ENV} is required for online migration and "
            "has no fallback to MY_PA_DATABASE_URL"
        )
    return MigrationAuthority(_parse(raw))
