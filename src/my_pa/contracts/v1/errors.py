"""Typed public errors.

An error states a stable code, a safe message, a correlation ID, and retry
guidance. It carries no path, provider detail, query text, stack trace, database
detail, or credential, and it does not reveal whether a denied object exists
(`docs/specs`, section 10).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = ["ErrorCode", "ProblemDetail", "RetryGuidance", "retry_guidance_for"]


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


class ProblemDetail(StrictModel):
    """One typed public error.

    `message` is a fixed, human-readable summary of the code. It is deliberately
    not a place to interpolate request state; `safe_details` carries only
    pre-categorised strings a caller may act on, such as a rejected field name.
    """

    code: ErrorCode
    message: str = Field(min_length=1, max_length=200)
    correlation_id: str
    retry: RetryGuidance
    safe_details: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ProblemDetail:
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        expected = retry_guidance_for(self.code)
        if self.retry is not expected:
            raise ValueError(f"{self.code} requires retry guidance {expected}, got {self.retry}")
        return self
