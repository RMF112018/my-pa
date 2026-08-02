"""Reading and writing the source registry.

Every function here takes a `Connection` and returns a domain value or an opaque
identifier. The caller owns the transaction: these are the statements, not the
unit of work, so a provider that observes ten objects commits them together
rather than ten times.

The asymmetry with `tables.py` is the point. The table stores `native_root` and
`native_locator`; nothing returned from this module carries either, except
`resolve_native_locator`, which exists because a provider holding an `obj_…` has
to be able to open something. That one function is the whole exposed surface of
the physical layer, it returns a bare string rather than a domain type so it
cannot be passed onward by accident, and its result must not reach a response, a
log, or an error message.

Identity is issued, then looked up. `register_source` and `record_object` insert
a freshly issued identifier and fall back to selecting the existing row when the
natural key is already present, so re-observing the same object returns the
identifier issued the first time. That is what makes an opaque identifier stable
without making it a function of the thing it names.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.source.provider import ObjectKind, SourceObject
from my_pa.domain.source.registry import (
    ConfiguredSource,
    SourceProviderKind,
    issue_identifier,
    validate_source_label,
)
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.tables import (
    source_object_versions,
    source_objects,
    sources,
)

__all__ = [
    "UnknownSourceError",
    "get_source",
    "observe_object",
    "register_source",
    "resolve_native_locator",
    "source_of_object",
]


class UnknownSourceError(LookupError):
    """Raised when an opaque identifier names no row.

    Carries the identifier, which is opaque by construction, and nothing else.
    """


def _to_source(row: Row[tuple[str, str, str, str, datetime]]) -> ConfiguredSource:
    return ConfiguredSource(
        source_id=row[0],
        provider_kind=SourceProviderKind(row[1]),
        label=row[2],
        classification=Classification(row[3]),
        configured_at=row[4],
    )


_SOURCE_COLUMNS = (
    sources.c.source_id,
    sources.c.provider_kind,
    sources.c.label,
    sources.c.classification,
    sources.c.configured_at,
)


def register_source(
    connection: Connection,
    *,
    provider_kind: SourceProviderKind,
    label: str,
    classification: Classification,
    native_root: str,
) -> ConfiguredSource:
    """Configure `native_root` as a source, or return the one already configured.

    Idempotent on `(provider_kind, native_root)`: configuring the same root
    twice is one source with one identity, not two identities for one
    collection. The insert is attempted first and the select is the fallback, so
    two concurrent callers cannot both conclude the row is absent.
    """
    validate_source_label(label)
    if not native_root:
        raise ValueError("native_root is required")

    statement = (
        pg_insert(sources)
        .values(
            source_id=issue_identifier(IdKind.SOURCE),
            provider_kind=provider_kind.value,
            label=label,
            classification=classification.value,
            native_root=native_root,
        )
        .on_conflict_do_nothing(constraint="sources_native_root_is_configured_once")
        .returning(*_SOURCE_COLUMNS)
    )
    inserted = connection.execute(statement).one_or_none()
    if inserted is not None:
        return _to_source(inserted)

    # The insert conflicted, so the row exists and was committed by someone
    # else. Reading it here depends on READ COMMITTED taking a fresh snapshot
    # per statement; the package docstring records what a higher isolation level
    # does instead. `conflicting_row` keeps the remaining case — the row deleted
    # between the two statements — from looking like an absent row.
    existing = connection.execute(
        select(*_SOURCE_COLUMNS).where(
            sources.c.provider_kind == provider_kind.value,
            sources.c.native_root == native_root,
        )
    ).one_or_none()
    return _to_source(conflicting_row(existing, "knowledge.sources"))


def get_source(connection: Connection, source_id: str) -> ConfiguredSource:
    """Return the configured source `source_id` names, or raise."""
    validate_identifier(source_id, IdKind.SOURCE)
    row = connection.execute(
        select(*_SOURCE_COLUMNS).where(sources.c.source_id == source_id)
    ).one_or_none()
    if row is None:
        raise UnknownSourceError(f"no configured source {source_id}")
    return _to_source(row)


def source_of_object(connection: Connection, source_object_id: str) -> str | None:
    """Return the `src_…` an object belongs to, or `None` when it names no row.

    Deliberately the *opaque* source identity and never the locator beside it in
    the same table. A status request may name an object, and the scope such a
    request has to be authorized against is the object's source; nothing about
    where the object physically is takes part in that decision, so nothing about
    it leaves this function.

    `None` rather than `UnknownSourceError`, because the caller's next act is to
    report `not_found`, and an exception here would tempt a caller into
    distinguishing "no such object" from "not yours" — which section 10 forbids.
    """
    validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)
    source_id = connection.execute(
        select(source_objects.c.source_id).where(
            source_objects.c.source_object_id == source_object_id
        )
    ).scalar_one_or_none()
    return None if source_id is None else str(source_id)


def resolve_native_locator(connection: Connection, source_object_id: str) -> str:
    """Return the provider-native locator behind `source_object_id`.

    The one place a physical locator leaves persistence. A provider needs it to
    open the object; nothing else does, and the value must not appear in a
    response, a log, or an error message.
    """
    validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)
    locator = connection.execute(
        select(source_objects.c.native_locator).where(
            source_objects.c.source_object_id == source_object_id
        )
    ).scalar_one_or_none()
    if locator is None:
        raise UnknownSourceError(f"no source object {source_object_id}")
    return str(locator)


def _object_id_for(
    connection: Connection,
    *,
    source_id: str,
    native_locator: str,
    kind: ObjectKind,
) -> str:
    statement = (
        pg_insert(source_objects)
        .values(
            source_object_id=issue_identifier(IdKind.SOURCE_OBJECT),
            source_id=source_id,
            kind=kind.value,
            native_locator=native_locator,
        )
        .on_conflict_do_nothing(constraint="source_objects_locator_is_issued_once")
        .returning(source_objects.c.source_object_id)
    )
    issued = connection.execute(statement).scalar_one_or_none()
    if issued is not None:
        return str(issued)
    # Insert-then-select fallback: requires READ COMMITTED. See the package
    # docstring and `register_source`.
    existing = connection.execute(
        select(source_objects.c.source_object_id).where(
            source_objects.c.source_id == source_id,
            source_objects.c.native_locator == native_locator,
        )
    ).scalar_one_or_none()
    return str(conflicting_row(existing, "knowledge.source_objects"))


def observe_object(
    connection: Connection,
    *,
    source_id: str,
    native_locator: str,
    kind: ObjectKind,
    fingerprint: str,
    modified_at: datetime,
    media_type: str | None = None,
    size_bytes: int | None = None,
) -> SourceObject:
    """Record one observation and return it as the normalised domain value.

    Re-observing an unchanged object returns the identifiers already issued for
    it: the object identity is keyed on the locator and the version identity on
    the fingerprint, so an unchanged object keeps its `obj_…` and its `ver_…`
    and a changed one keeps its `obj_…` and gets a new `ver_…`. A caller
    comparing the returned `version_id` against the one it last saw is how a
    change is detected.
    """
    validate_identifier(source_id, IdKind.SOURCE)
    if not native_locator:
        raise ValueError("native_locator is required")
    if not fingerprint:
        raise ValueError("fingerprint is required")
    observed_at = ensure_utc(modified_at)

    source_object_id = _object_id_for(
        connection, source_id=source_id, native_locator=native_locator, kind=kind
    )

    statement = (
        pg_insert(source_object_versions)
        .values(
            version_id=issue_identifier(IdKind.VERSION),
            source_object_id=source_object_id,
            fingerprint=fingerprint,
            media_type=media_type,
            size_bytes=size_bytes,
            modified_at=observed_at,
        )
        .on_conflict_do_nothing(constraint="source_object_versions_are_one_per_fingerprint")
        .returning(source_object_versions.c.version_id)
    )
    version_id = connection.execute(statement).scalar_one_or_none()
    if version_id is None:
        # Insert-then-select fallback: requires READ COMMITTED. See the package
        # docstring and `register_source`.
        found = connection.execute(
            select(source_object_versions.c.version_id).where(
                source_object_versions.c.source_object_id == source_object_id,
                source_object_versions.c.fingerprint == fingerprint,
            )
        ).scalar_one_or_none()
        version_id = conflicting_row(found, "knowledge.source_object_versions")

    return SourceObject(
        source_id=source_id,
        source_object_id=source_object_id,
        version_id=str(version_id),
        kind=kind,
        media_type=media_type,
        size_bytes=size_bytes,
        modified_at=observed_at,
    )
