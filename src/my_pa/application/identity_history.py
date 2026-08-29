"""Bound and paginate the authoritative identity-history projection."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import ensure_utc, format_rfc3339
from my_pa.domain.relationship.identity_history import (
    IdentityHistoryCursorError,
    IdentityHistoryEntry,
    IdentityHistoryPage,
    IdentityHistoryPosition,
)

__all__ = ["IdentityHistoryCursorError", "IdentityHistoryQuery", "IdentityHistoryService"]

_CURSOR_ORDER: Final = "occurred_at_asc_source_order_asc_history_id_asc_v1"
_MAX_CURSOR_CHARACTERS: Final = 512
_MAX_PAGE_SIZE: Final = 100


class IdentityHistoryQuery(Protocol):
    """The narrow read port required by identity history."""

    def entries(
        self,
        principal_id: str,
        entity_id: str,
        *,
        limit: int,
        after: IdentityHistoryPosition | None = None,
    ) -> tuple[tuple[IdentityHistoryEntry, int], ...]:
        """Return entries paired with their stable source order."""


@dataclass(frozen=True, slots=True)
class IdentityHistoryService:
    """Issue opaque request-bound continuations over one entity's history."""

    def history(
        self,
        repository: IdentityHistoryQuery,
        *,
        principal_id: str,
        entity_id: str,
        page_size: int,
        after: str | None = None,
    ) -> IdentityHistoryPage:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        if not 1 <= page_size <= _MAX_PAGE_SIZE:
            raise ValueError(f"an identity history page contains 1..{_MAX_PAGE_SIZE} entries")
        binding = _binding(principal_id, entity_id, page_size)
        position = None if after is None else _decode(after, expected_binding=binding)
        if after is not None and position is None:
            raise IdentityHistoryCursorError("an identity history cursor is invalid")
        found = repository.entries(
            principal_id,
            entity_id,
            limit=page_size + 1,
            after=position,
        )
        truncated = len(found) > page_size
        selected = found[:page_size]
        cursor = None
        if truncated and selected:
            entry, source_order = selected[-1]
            cursor = _encode(
                binding,
                IdentityHistoryPosition(entry.occurred_at, source_order, entry.history_id),
            )
        return IdentityHistoryPage(
            entity_id=entity_id,
            entries=tuple(entry for entry, _source_order in selected),
            is_truncated=truncated,
            next_cursor=cursor,
        )


def _binding(principal_id: str, entity_id: str, page_size: int) -> str:
    payload = json.dumps(
        {
            "entity_id": entity_id,
            "order": _CURSOR_ORDER,
            "page_size": page_size,
            "principal_id": principal_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _encode(binding: str, position: IdentityHistoryPosition) -> str:
    payload = json.dumps(
        {
            "b": binding,
            "i": position.history_id,
            "r": position.source_order,
            "t": format_rfc3339(position.occurred_at),
            "v": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii").rstrip("=")


def _decode(token: str, *, expected_binding: str) -> IdentityHistoryPosition | None:
    if not token or len(token) > _MAX_CURSOR_CHARACTERS:
        return None
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = json.loads(
            base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        )
    except (binascii.Error, UnicodeEncodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(decoded, dict) or set(decoded) != {"b", "i", "r", "t", "v"}:
        return None
    if decoded["b"] != expected_binding or decoded["v"] != 1:
        return None
    if not isinstance(decoded["i"], str) or not isinstance(decoded["r"], int):
        return None
    if not isinstance(decoded["t"], str):
        return None
    try:
        occurred_at = ensure_utc(datetime.fromisoformat(decoded["t"]))
        validate_identifier(decoded["i"])
        return IdentityHistoryPosition(occurred_at, decoded["r"], decoded["i"])
    except (InvalidIdentifierError, TypeError, ValueError, OverflowError):
        return None
