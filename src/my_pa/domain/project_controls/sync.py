"""Pure, provider-neutral Constraint synchronization contracts and comparison.

WP11 receives normalized logical rows from an external orchestrator.  It never
opens a workbook, calls Microsoft, or treats layout metadata as domain state.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, fields
from datetime import date, datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.project_controls.constraint import (
    ACTIVE_CONSTRAINT_LIFECYCLE_STATES,
    ConstraintLifecycleState,
)
from my_pa.domain.project_controls.party import PartyRef
from my_pa.domain.project_controls.read_models import PersistedConstraintRecord

MAX_SYNC_ROWS: Final = 100
MAX_SYNC_PAGE: Final = 100
MAX_SYNC_CURSOR: Final = 512
MAX_ROW_IDENTITY: Final = 256
MAX_PROVIDER_VERSION: Final = 256
MAX_TARGET_IDENTITY: Final = 1024
MAX_NORMALIZATION_VERSION: Final = 64
MAX_PARTIES_PER_ROLE: Final = 32
MAX_PARTY_LABEL: Final = 512
MAX_NARRATIVE: Final = 4096
MAX_REFERENCE: Final = 1024
MAX_CANDIDATE_BYTES: Final = 8192
DIGEST_LENGTH: Final = 64

SYNC_LOGICAL_FIELDS: Final = (
    "constraint_code",
    "category",
    "description",
    "date_identified",
    "status",
    "bic",
    "responsible",
    "due_date",
    "reference",
    "current_update",
    "completion_date",
)
MANUAL_PATCH_FIELDS: Final = (
    "description",
    "date_identified",
    "due_date",
    "reference",
    "current_update",
    "bic",
    "responsible",
    "project_id",
    "category_id",
)


class ConstraintSyncState(StrEnum):
    NEVER_SYNCED = "never_synced"
    IN_SYNC = "in_sync"
    DB_EXPORT_PENDING = "db_export_pending"
    EXTERNAL_IMPORT_PENDING = "external_import_pending"
    CONFLICT = "conflict"
    WORKBOOK_UNAVAILABLE = "workbook_unavailable"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    PARTIAL = "partial"
    VERIFICATION_PENDING = "verification_pending"
    VERIFICATION_FAILED = "verification_failed"


class ConstraintSyncRunState(StrEnum):
    STARTED = "started"
    PREVIEWED = "previewed"
    APPLIED = "applied"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"


class ConstraintSyncAction(StrEnum):
    NO_OP = "no_op"
    IMPORT_EXTERNAL = "import_external"
    EXPORT_CANONICAL = "export_canonical"
    MERGE = "merge"
    CONFLICT = "conflict"


class ConstraintSyncConflictKind(StrEnum):
    BOTH_CHANGED = "both_changed"
    DELETED_IN_CANONICAL = "deleted_in_canonical"
    DELETED_IN_EXTERNAL = "deleted_in_external"
    NEW_IN_EXTERNAL = "new_in_external"
    IDENTITY = "identity"
    LIFECYCLE = "lifecycle"


class ConstraintSyncResolution(StrEnum):
    KEEP_CANONICAL = "keep_canonical"
    ACCEPT_EXTERNAL = "accept_external"
    MANUAL_PATCH = "manual_patch"
    REOPEN = "reopen"


class ConstraintSyncError(ValueError):
    """A safe synchronization-domain refusal."""


def _text(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConstraintSyncError("a text value is required")
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    if not normalized or len(normalized) > maximum:
        raise ConstraintSyncError("a text value is outside its accepted bound")
    return normalized


def _row_identity(value: object) -> str:
    if not isinstance(value, str) or any(character.isspace() for character in value):
        raise ConstraintSyncError("an external row key must not contain whitespace")
    normalized = _text(value, maximum=MAX_ROW_IDENTITY)
    if normalized is None:  # unreachable after the non-optional validation above
        raise ConstraintSyncError("an external row key is required")
    return normalized


def validate_digest(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) != DIGEST_LENGTH or any(ch not in "0123456789abcdef" for ch in value):
        raise ConstraintSyncError("a digest must be 64 lowercase hexadecimal characters")
    return value


def _party(party: PartyRef) -> PartyRef:
    if not isinstance(party, PartyRef):
        raise ConstraintSyncError("an external party must be a PartyRef")
    if party.label is not None and len(party.label) > MAX_PARTY_LABEL:
        raise ConstraintSyncError("a party label exceeds 512 characters")
    return party


@dataclass(frozen=True, slots=True)
class NormalizedExternalConstraintRow:
    """One logical external row; no coordinates, formulas, or formatting."""

    external_row_key: str
    constraint_id: str | None = None
    constraint_code: str | None = None
    category: str | None = None
    description: str | None = None
    date_identified: date | None = None
    status: ConstraintLifecycleState | None = None
    bic: tuple[PartyRef, ...] = ()
    responsible: tuple[PartyRef, ...] = ()
    due_date: date | None = None
    reference: str | None = None
    current_update: str | None = None
    completion_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_row_key", _row_identity(self.external_row_key))
        object.__setattr__(self, "constraint_code", _text(self.constraint_code, maximum=32))
        object.__setattr__(self, "category", _text(self.category, maximum=256))
        for name in ("description", "current_update"):
            object.__setattr__(self, name, _text(getattr(self, name), maximum=MAX_NARRATIVE))
        object.__setattr__(self, "reference", _text(self.reference, maximum=MAX_REFERENCE))
        for name in ("date_identified", "due_date", "completion_date"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, date):
                raise ConstraintSyncError("an external date must be an ISO calendar date")
        if len(self.bic) > MAX_PARTIES_PER_ROLE or len(self.responsible) > MAX_PARTIES_PER_ROLE:
            raise ConstraintSyncError("a party collection exceeds 32 entries")
        object.__setattr__(self, "bic", tuple(_party(item) for item in self.bic))
        object.__setattr__(self, "responsible", tuple(_party(item) for item in self.responsible))
        if self.status is not None and not isinstance(self.status, ConstraintLifecycleState):
            raise ConstraintSyncError("an external lifecycle state is unknown")

    def logical_values(self) -> dict[str, object]:
        def parties(value: tuple[PartyRef, ...]) -> list[dict[str, str | None]]:
            return [
                {"kind": item.kind.value, "entity_id": item.entity_id, "label": item.label}
                for item in value
            ]

        return {
            "constraint_code": self.constraint_code,
            "category": self.category,
            "description": self.description,
            "date_identified": None
            if self.date_identified is None
            else self.date_identified.isoformat(),
            "status": None if self.status is None else self.status.value,
            "bic": parties(self.bic),
            "responsible": parties(self.responsible),
            "due_date": None if self.due_date is None else self.due_date.isoformat(),
            "reference": self.reference,
            "current_update": self.current_update,
            "completion_date": None
            if self.completion_date is None
            else self.completion_date.isoformat(),
        }

    def field_digests(self) -> dict[str, str]:
        return {name: _digest(value) for name, value in self.logical_values().items()}

    def record_digest(self) -> str:
        return _digest(self.logical_values())


@dataclass(frozen=True, slots=True)
class ConstraintSyncBaseline:
    constraint_id: str
    revision_id: str
    constraint_version: int
    field_digests: dict[str, str]
    record_digest: str
    external_row_key: str
    verified_provider_version: str | None
    verified_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_row_key", _row_identity(self.external_row_key))
        if set(self.field_digests) != set(SYNC_LOGICAL_FIELDS):
            raise ConstraintSyncError("a baseline must bind all logical fields")
        for digest in self.field_digests.values():
            validate_digest(digest)
        validate_digest(self.record_digest)
        object.__setattr__(self, "verified_at", ensure_utc(self.verified_at))


@dataclass(frozen=True, slots=True)
class ConstraintSyncDecision:
    external_row_key: str
    constraint_id: str | None
    action: ConstraintSyncAction
    changed_in_db: tuple[str, ...] = ()
    changed_external: tuple[str, ...] = ()
    conflict_fields: tuple[str, ...] = ()
    conflict_kind: ConstraintSyncConflictKind | None = None

    def __post_init__(self) -> None:
        for value in (self.changed_in_db, self.changed_external, self.conflict_fields):
            if len(value) > len(SYNC_LOGICAL_FIELDS) or not set(value) <= set(SYNC_LOGICAL_FIELDS):
                raise ConstraintSyncError("a comparison named an unknown logical field")


def compare_three_way(
    baseline: ConstraintSyncBaseline | None,
    canonical: PersistedConstraintRecord | None,
    external: NormalizedExternalConstraintRow | None,
) -> ConstraintSyncDecision:
    """Compare verified A, current canonical B, and normalized external C."""
    if external is None:
        if canonical is None:
            raise ConstraintSyncError("a comparison requires a canonical or external row")
        return ConstraintSyncDecision(
            external_row_key=baseline.external_row_key
            if baseline is not None
            else canonical.constraint_id,
            constraint_id=canonical.constraint_id,
            action=ConstraintSyncAction.EXPORT_CANONICAL,
            conflict_kind=ConstraintSyncConflictKind.DELETED_IN_EXTERNAL,
        )
    if canonical is None:
        return ConstraintSyncDecision(
            external_row_key=external.external_row_key,
            constraint_id=None,
            action=ConstraintSyncAction.CONFLICT,
            conflict_fields=SYNC_LOGICAL_FIELDS,
            conflict_kind=ConstraintSyncConflictKind.NEW_IN_EXTERNAL,
        )
    if baseline is not None and baseline.external_row_key != external.external_row_key:
        return _conflict(external, canonical, (), ConstraintSyncConflictKind.IDENTITY)
    current = canonical_logical_values(canonical)
    current_digests = {name: _digest(value) for name, value in current.items()}
    external_values = external.logical_values()
    external_digests = external.field_digests()
    if external.constraint_code != canonical.constraint_code:
        return _conflict(
            external, canonical, ("constraint_code",), ConstraintSyncConflictKind.IDENTITY
        )
    category = canonical.category_id
    if external.category != category:
        return _conflict(external, canonical, ("category",), ConstraintSyncConflictKind.IDENTITY)
    if external.status is None:
        return _conflict(external, canonical, ("status",), ConstraintSyncConflictKind.LIFECYCLE)
    if external.status is ConstraintLifecycleState.CLOSED and external.completion_date is None:
        return _conflict(
            external,
            canonical,
            ("status", "completion_date"),
            ConstraintSyncConflictKind.LIFECYCLE,
        )
    if (
        external.status is not ConstraintLifecycleState.CLOSED
        and external.completion_date is not None
    ):
        return _conflict(
            external,
            canonical,
            ("completion_date",),
            ConstraintSyncConflictKind.LIFECYCLE,
        )
    if external.status != canonical.lifecycle_state and not (
        canonical.lifecycle_state in ACTIVE_CONSTRAINT_LIFECYCLE_STATES
        and (
            external.status in ACTIVE_CONSTRAINT_LIFECYCLE_STATES
            or external.status is ConstraintLifecycleState.CLOSED
        )
    ):
        return _conflict(external, canonical, ("status",), ConstraintSyncConflictKind.LIFECYCLE)
    if (
        canonical.lifecycle_state is ConstraintLifecycleState.CLOSED
        and external.completion_date != canonical.completion_date
    ):
        return _conflict(
            external,
            canonical,
            ("completion_date",),
            ConstraintSyncConflictKind.LIFECYCLE,
        )
    if canonical.lifecycle_state is not ConstraintLifecycleState.DRAFT:
        required_clears = tuple(
            name
            for name in ("description", "date_identified", "due_date")
            if current[name] is not None and external_values[name] is None
        )
        if required_clears:
            return _conflict(
                external,
                canonical,
                required_clears,
                ConstraintSyncConflictKind.BOTH_CHANGED,
            )
    if baseline is None:
        return ConstraintSyncDecision(
            external_row_key=external.external_row_key,
            constraint_id=canonical.constraint_id,
            action=(
                ConstraintSyncAction.NO_OP
                if current == external_values
                else ConstraintSyncAction.CONFLICT
            ),
            conflict_fields=()
            if current == external_values
            else tuple(
                name
                for name in SYNC_LOGICAL_FIELDS
                if current_digests[name] != external_digests[name]
            ),
            conflict_kind=None
            if current == external_values
            else ConstraintSyncConflictKind.BOTH_CHANGED,
        )
    db_changed = tuple(
        name
        for name in SYNC_LOGICAL_FIELDS
        if current_digests[name] != baseline.field_digests[name]
    )
    external_changed = tuple(
        name
        for name in SYNC_LOGICAL_FIELDS
        if external_digests[name] != baseline.field_digests[name]
    )
    divergent = tuple(
        name
        for name in set(db_changed) & set(external_changed)
        if current_digests[name] != external_digests[name]
    )
    if divergent:
        return _conflict(
            external, canonical, tuple(sorted(divergent)), ConstraintSyncConflictKind.BOTH_CHANGED
        )
    # A field can have changed on both sides since the baseline and nevertheless
    # have converged to the same value.  Such a field needs verification, not an
    # apply mutation.  Persist only differences that still exist between the
    # current canonical row and the workbook; otherwise apply would replay a
    # value canonical already holds (and terminal lifecycle operations cannot be
    # safely repeated).
    canonical_export_fields = tuple(
        name for name in db_changed if current_digests[name] != external_digests[name]
    )
    external_apply_fields = tuple(
        name for name in external_changed if current_digests[name] != external_digests[name]
    )
    if not canonical_export_fields and not external_apply_fields:
        action = ConstraintSyncAction.NO_OP
    elif external_apply_fields and not canonical_export_fields:
        action = ConstraintSyncAction.IMPORT_EXTERNAL
    elif canonical_export_fields and not external_apply_fields:
        action = ConstraintSyncAction.EXPORT_CANONICAL
    else:
        action = ConstraintSyncAction.MERGE
    return ConstraintSyncDecision(
        external.external_row_key,
        canonical.constraint_id,
        action,
        canonical_export_fields,
        external_apply_fields,
    )


def canonical_logical_values(record: PersistedConstraintRecord) -> dict[str, object]:
    def parties(value: tuple[PartyRef, ...]) -> list[dict[str, str | None]]:
        return [
            {"kind": item.kind.value, "entity_id": item.entity_id, "label": item.label}
            for item in value
        ]

    return {
        "constraint_code": record.constraint_code,
        "category": record.category_id,
        "description": record.description,
        "date_identified": None
        if record.date_identified is None
        else record.date_identified.isoformat(),
        "status": record.lifecycle_state.value,
        "bic": parties(record.bic),
        "responsible": parties(record.responsible),
        "due_date": None if record.due_date is None else record.due_date.isoformat(),
        "reference": record.reference,
        "current_update": record.current_update,
        "completion_date": None
        if record.completion_date is None
        else record.completion_date.isoformat(),
    }


def _conflict(
    external: NormalizedExternalConstraintRow,
    canonical: PersistedConstraintRecord,
    names: tuple[str, ...],
    kind: ConstraintSyncConflictKind,
) -> ConstraintSyncDecision:
    return ConstraintSyncDecision(
        external.external_row_key,
        canonical.constraint_id,
        ConstraintSyncAction.CONFLICT,
        conflict_fields=names,
        conflict_kind=kind,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def candidate_json(row: NormalizedExternalConstraintRow) -> dict[str, object]:
    value = {field.name: getattr(row, field.name) for field in fields(row)}
    value["date_identified"] = (
        None if row.date_identified is None else row.date_identified.isoformat()
    )
    value["due_date"] = None if row.due_date is None else row.due_date.isoformat()
    value["completion_date"] = (
        None if row.completion_date is None else row.completion_date.isoformat()
    )
    value["status"] = None if row.status is None else row.status.value
    value["bic"] = row.logical_values()["bic"]
    value["responsible"] = row.logical_values()["responsible"]
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > MAX_CANDIDATE_BYTES:
        raise ConstraintSyncError("an external candidate exceeds 8 KiB")
    return value
