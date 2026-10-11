"""Typed public errors.

An error states a stable code, a safe message, a correlation ID, and retry
guidance. It carries no path, provider detail, query text, stack trace, database
detail, or credential, and it does not reveal whether a denied object exists
(`docs/specs`, section 10).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from my_pa.contracts.v1.base import StrictModel
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "MAX_ALLOWED_VALUES",
    "MAX_ALLOWED_VALUE_ENTRIES",
    "AllowedValues",
    "ErrorCode",
    "ProblemDetail",
    "RetryGuidance",
    "is_allowed_value_token",
    "retry_guidance_for",
]


class ErrorCode(StrEnum):
    """The eleven public error codes."""

    INVALID_REQUEST = "invalid_request"
    AMBIGUOUS_REQUEST = "ambiguous_request"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    QUARANTINED = "quarantined"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class RetryGuidance(StrEnum):
    """Whether and when a caller may retry."""

    AFTER_CORRECTION = "after_correction"
    AFTER_EXPLICIT_CHOICE = "after_explicit_choice"
    AFTER_AUTHORITY_CHANGE = "after_authority_change"
    AFTER_REFRESH = "after_refresh"
    CONDITIONAL = "conditional"
    BOUNDED_RETRY = "bounded_retry"
    OPERATOR_REVIEW = "operator_review"
    NEW_REQUEST = "new_request"
    NO = "no"


_RETRY_GUIDANCE: Mapping[ErrorCode, RetryGuidance] = MappingProxyType(
    {
        ErrorCode.INVALID_REQUEST: RetryGuidance.AFTER_CORRECTION,
        ErrorCode.AMBIGUOUS_REQUEST: RetryGuidance.AFTER_EXPLICIT_CHOICE,
        ErrorCode.DENIED: RetryGuidance.AFTER_AUTHORITY_CHANGE,
        ErrorCode.UNAVAILABLE: RetryGuidance.CONDITIONAL,
        ErrorCode.UNSUPPORTED: RetryGuidance.NO,
        ErrorCode.NOT_FOUND: RetryGuidance.CONDITIONAL,
        ErrorCode.CONFLICT: RetryGuidance.AFTER_REFRESH,
        ErrorCode.RATE_LIMITED: RetryGuidance.BOUNDED_RETRY,
        ErrorCode.QUARANTINED: RetryGuidance.OPERATOR_REVIEW,
        ErrorCode.CANCELLED: RetryGuidance.NEW_REQUEST,
        ErrorCode.INTERNAL_ERROR: RetryGuidance.CONDITIONAL,
    }
)


def retry_guidance_for(code: ErrorCode) -> RetryGuidance:
    """Return the guidance the contract fixes for `code`."""
    return _RETRY_GUIDANCE[code]


#: Shape a `safe_details` entry must take: a short, pre-categorised token such as
#: a rejected field name. Bounded so the field cannot become the free-text
#: channel that `AuditEvent` is structurally denied.
_SAFE_DETAIL_PATTERN: Final = re.compile(r"\A[a-z][a-z0-9_.]{0,63}\Z")

#: Most rejected fields a single request can usefully report.
_MAX_SAFE_DETAILS: Final = 16


#: Shape one listed vocabulary value must take: a short code token such as an
#: enum member's value. Case is free because some vocabularies spell their
#: members in capitals; whitespace, `/`, `@`, `:` and quoting are not, so the
#: list cannot carry a path, an address, a sentence or a credential.
_ALLOWED_VALUE_PATTERN: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}\Z")

#: Most values one `AllowedValues` entry lists. A longer vocabulary is cut to its
#: first `MAX_ALLOWED_VALUES` members in declaration order and marked
#: `truncated`.
MAX_ALLOWED_VALUES: Final = 64

#: Most `AllowedValues` entries one problem carries: one per rejected field at
#: most, so it is the same bound as `safe_details`.
MAX_ALLOWED_VALUE_ENTRIES: Final = _MAX_SAFE_DETAILS


def is_allowed_value_token(value: object) -> bool:
    """Whether `value` may be listed as one acceptable vocabulary value."""
    return isinstance(value, str) and _ALLOWED_VALUE_PATTERN.fullmatch(value) is not None


class AllowedValues(StrictModel):
    """The closed vocabulary one rejected field accepts.

    `detail` is the `safe_details` token naming the field; `values` are the
    vocabulary's members in declaration order. The values come from the
    service's own closed vocabularies, never from the request, and never from
    tenant data: a list of identifiers, names or free text is not a vocabulary.

    Bounded twice: at most `MAX_ALLOWED_VALUES` values, each a short code token.
    A vocabulary longer than the bound is listed as its first
    `MAX_ALLOWED_VALUES` members with `truncated` set, so a caller can tell a
    complete list from a prefix.
    """

    detail: str
    values: tuple[str, ...] = Field(min_length=1, max_length=MAX_ALLOWED_VALUES)
    truncated: bool = False

    @model_validator(mode="after")
    def _check(self) -> AllowedValues:
        if not _SAFE_DETAIL_PATTERN.fullmatch(self.detail):
            raise ValueError("allowed_values detail must be a safe_details token")
        for value in self.values:
            if not is_allowed_value_token(value):
                raise ValueError("allowed values must be short vocabulary tokens")
        if len(set(self.values)) != len(self.values):
            raise ValueError("allowed values must not repeat")
        return self

    @classmethod
    def bounded(cls, detail: str, values: Iterable[str]) -> AllowedValues:
        """List `values` for `detail`, cut to the bound and marked if cut."""
        listed = tuple(dict.fromkeys(values))
        return cls(
            detail=detail,
            values=listed[:MAX_ALLOWED_VALUES],
            truncated=len(listed) > MAX_ALLOWED_VALUES,
        )


class ProblemDetail(StrictModel):
    """One typed public error.

    `message` is a fixed, human-readable summary of the code. It is deliberately
    not a place to interpolate request state; `safe_details` carries only
    pre-categorised tokens a caller may act on, such as a rejected field name.

    Both fields are bounded in shape as well as length. An unbounded string here
    would be the same payload channel that was removed from `AuditEvent`: a
    caller interpolating "rejected value {x}" would leak a query, path, or
    credential into a public error.

    `allowed_values` is additive and optional. For an `invalid_request` that
    rejected a closed-vocabulary field it lists the values that field accepts,
    one entry per rejected field named in `safe_details`, at most
    `MAX_ALLOWED_VALUE_ENTRIES` entries of at most `MAX_ALLOWED_VALUES` values
    each (a longer vocabulary is a prefix marked `truncated`). It is never set
    on any other code. When empty it is omitted from the serialized form, so a
    problem without it encodes exactly as it did before the field existed, and
    a problem received without it validates unchanged.
    """

    code: ErrorCode
    message: str = Field(min_length=1, max_length=200)
    correlation_id: str
    retry: RetryGuidance
    safe_details: tuple[str, ...] = Field(default=(), max_length=_MAX_SAFE_DETAILS)
    allowed_values: tuple[AllowedValues, ...] = Field(
        default=(), max_length=MAX_ALLOWED_VALUE_ENTRIES
    )

    @model_validator(mode="after")
    def _check(self) -> ProblemDetail:
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        expected = retry_guidance_for(self.code)
        if self.retry is not expected:
            raise ValueError(f"{self.code} requires retry guidance {expected}, got {self.retry}")
        for detail in self.safe_details:
            if not _SAFE_DETAIL_PATTERN.fullmatch(detail):
                raise ValueError(
                    "safe_details entries must be short lowercase tokens such as a field name"
                )
        if self.allowed_values:
            if self.code is not ErrorCode.INVALID_REQUEST:
                raise ValueError("only invalid_request may list allowed values")
            listed = [entry.detail for entry in self.allowed_values]
            if len(set(listed)) != len(listed):
                raise ValueError("allowed_values lists each detail at most once")
            if not set(listed) <= set(self.safe_details):
                raise ValueError("allowed_values may only describe a detail in safe_details")
        return self

    @model_serializer(mode="wrap")
    def _omit_empty_allowed_values(self, handler: SerializerFunctionWrapHandler) -> Any:  # noqa: ANN401 - pydantic's serialized form
        serialized = handler(self)
        if not self.allowed_values and isinstance(serialized, dict):
            serialized.pop("allowed_values", None)
        return serialized
