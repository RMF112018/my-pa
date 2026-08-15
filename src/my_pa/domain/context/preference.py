"""Explicit, reversible retrieval preferences.

These records do not change canonical facts, authority, source scope, or
lifecycle. They exist so ranking can pin, filter, alias, or prefer a source
inside the already-authorized evidence set. Reversal appends an opposing event;
events are never deleted.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "MAX_CONTEXT_ALIAS_CHARACTERS",
    "ContextPreferenceAction",
    "ContextPreferenceAdmission",
    "ContextPreferenceClass",
    "ContextPreferenceCurrent",
    "ContextPreferenceError",
    "ContextPreferenceEvent",
    "preference_class_for",
    "validate_context_alias",
]

MAX_CONTEXT_ALIAS_CHARACTERS: Final = 64
_FORBIDDEN_CATEGORIES: Final[frozenset[str]] = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


class ContextPreferenceError(ValueError):
    """A preference value is malformed. Messages name the rule, never the value."""


class ContextPreferenceAction(StrEnum):
    """Closed retrieval-preference acts. Ranking reads only the current fold."""

    MARK_RELEVANT = "mark_relevant"
    MARK_IRRELEVANT = "mark_irrelevant"
    PIN = "pin"
    UNPIN = "unpin"
    CONFIRM_ALIAS = "confirm_alias"
    REMOVE_ALIAS = "remove_alias"
    PREFER_SOURCE = "prefer_source"
    DEPREFER_SOURCE = "deprefer_source"
    CLEAR = "clear"


class ContextPreferenceClass(StrEnum):
    """Independent projection slots so a pin and an alias can coexist."""

    FOCUS = "focus"
    RELEVANCE = "relevance"
    ALIAS = "alias"
    SOURCE = "source"


_FOCUS_ACTIONS: Final[frozenset[ContextPreferenceAction]] = frozenset(
    {ContextPreferenceAction.PIN, ContextPreferenceAction.UNPIN}
)
_RELEVANCE_ACTIONS: Final[frozenset[ContextPreferenceAction]] = frozenset(
    {ContextPreferenceAction.MARK_RELEVANT, ContextPreferenceAction.MARK_IRRELEVANT}
)
_ALIAS_ACTIONS: Final[frozenset[ContextPreferenceAction]] = frozenset(
    {ContextPreferenceAction.CONFIRM_ALIAS, ContextPreferenceAction.REMOVE_ALIAS}
)
_SOURCE_ACTIONS: Final[frozenset[ContextPreferenceAction]] = frozenset(
    {ContextPreferenceAction.PREFER_SOURCE, ContextPreferenceAction.DEPREFER_SOURCE}
)


def preference_class_for(action: ContextPreferenceAction) -> ContextPreferenceClass | None:
    """The projection slot `action` writes, or `None` for `clear` (all slots)."""
    if action in _FOCUS_ACTIONS:
        return ContextPreferenceClass.FOCUS
    if action in _RELEVANCE_ACTIONS:
        return ContextPreferenceClass.RELEVANCE
    if action in _ALIAS_ACTIONS:
        return ContextPreferenceClass.ALIAS
    if action in _SOURCE_ACTIONS:
        return ContextPreferenceClass.SOURCE
    return None


def validate_context_alias(value: str) -> str:
    """Return `value` unchanged, or refuse it without echoing it."""
    if not isinstance(value, str):
        raise ContextPreferenceError(f"alias must be a string, got {type(value).__name__}")
    if not value or len(value) > MAX_CONTEXT_ALIAS_CHARACTERS:
        raise ContextPreferenceError(
            f"alias is required and at most {MAX_CONTEXT_ALIAS_CHARACTERS} characters"
        )
    if "\x00" in value:
        raise ContextPreferenceError("alias cannot contain a null byte")
    for character in value:
        if unicodedata.category(character) in _FORBIDDEN_CATEGORIES:
            raise ContextPreferenceError(
                "alias cannot contain control, formatting, surrogate, "
                "private-use, or unassigned characters"
            )
    return value


def _required_id(value: str, kind: IdKind, name: str) -> None:
    try:
        validate_identifier(value, kind)
    except InvalidIdentifierError as exc:
        raise ContextPreferenceError(f"{name} is not a well-formed identifier") from exc


@dataclass(frozen=True, slots=True)
class ContextPreferenceEvent:
    """One append-only preference event. Alias is omitted from repr."""

    event_id: str
    principal_id: str
    action: ContextPreferenceAction
    target_id: str
    idempotency_key: str
    event_number: int
    created_at: datetime
    correlation_id: str
    request_id: str
    alias: str | None = field(default=None, repr=False)
    source_id: str | None = None
    superseded_at: datetime | None = None
    audit_id: str | None = None

    def __post_init__(self) -> None:
        _required_id(self.event_id, IdKind.CONTEXT_PREFERENCE_EVENT, "event_id")
        _required_id(self.principal_id, IdKind.PRINCIPAL, "principal_id")
        if not isinstance(self.action, ContextPreferenceAction):
            raise ContextPreferenceError("action is required")
        try:
            validate_identifier(self.target_id)
        except InvalidIdentifierError as exc:
            raise ContextPreferenceError("target_id is not a well-formed identifier") from exc
        if not self.idempotency_key:
            raise ContextPreferenceError("idempotency_key is required")
        if isinstance(self.event_number, bool) or self.event_number < 1:
            raise ContextPreferenceError("event_number must be a positive integer")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        if self.superseded_at is not None:
            object.__setattr__(self, "superseded_at", ensure_utc(self.superseded_at))
        _required_id(self.correlation_id, IdKind.CORRELATION, "correlation_id")
        if not self.request_id:
            raise ContextPreferenceError("request_id is required")
        if self.alias is not None:
            validate_context_alias(self.alias)
        if self.source_id is not None:
            _required_id(self.source_id, IdKind.SOURCE, "source_id")
        if self.audit_id is not None:
            _required_id(self.audit_id, IdKind.AUDIT, "audit_id")


@dataclass(frozen=True, slots=True)
class ContextPreferenceCurrent:
    """The folded preference for one principal, target, and action class."""

    principal_id: str
    target_id: str
    preference_class: ContextPreferenceClass
    action: ContextPreferenceAction
    event_id: str
    alias: str | None = field(default=None, repr=False)
    source_id: str | None = None

    def __post_init__(self) -> None:
        _required_id(self.principal_id, IdKind.PRINCIPAL, "principal_id")
        try:
            validate_identifier(self.target_id)
        except InvalidIdentifierError as exc:
            raise ContextPreferenceError("target_id is not a well-formed identifier") from exc
        if not isinstance(self.preference_class, ContextPreferenceClass):
            raise ContextPreferenceError("preference_class is required")
        if not isinstance(self.action, ContextPreferenceAction):
            raise ContextPreferenceError("action is required")
        _required_id(self.event_id, IdKind.CONTEXT_PREFERENCE_EVENT, "event_id")
        if self.alias is not None:
            validate_context_alias(self.alias)
        if self.source_id is not None:
            _required_id(self.source_id, IdKind.SOURCE, "source_id")


@dataclass(frozen=True, slots=True)
class ContextPreferenceAdmission:
    """What recording one preference event produced, including idempotent replay."""

    event: ContextPreferenceEvent
    current: tuple[ContextPreferenceCurrent, ...]
    created: bool
