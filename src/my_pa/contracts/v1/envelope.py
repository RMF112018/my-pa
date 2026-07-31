"""Common request metadata and the response envelope.

Every response, including an error, carries the contract version, the caller's
request ID, and a correlation ID (`docs/specs`, section 7).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from my_pa.contracts.v1.base import (
    CONTRACT_VERSION,
    StrictModel,
    UtcDatetime,
    ensure_deterministic,
)
from my_pa.contracts.v1.disclosure import Disclosure, Scope
from my_pa.contracts.v1.errors import ProblemDetail
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

__all__ = ["RequestMetadata", "ResponseEnvelope"]


class RequestMetadata(StrictModel):
    """Common metadata on every public request.

    `principal_id` is correlation input only. Authenticated context determines
    the acting principal; a caller-supplied identity is never trusted alone
    (`docs/specs`, section 8.2).
    """

    contract_version: str = CONTRACT_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    capability: Capability
    purpose: Purpose
    principal_id: str
    scope: Scope = Scope()
    requested_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> RequestMetadata:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract_version: {self.contract_version!r}")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        return self


class ResponseEnvelope(StrictModel):
    """The envelope wrapping every public result.

    Exactly one of `disclosure` or `error` is populated. A success without a
    disclosure would be a result with no stated scope, coverage, or trust, which
    the contract forbids.
    """

    contract_version: str = CONTRACT_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    correlation_id: str
    completed_at: UtcDatetime
    # Deliberately not a recursive PEP 695 alias: that form is not reliably
    # supported by the declared Pydantic floor, and CI would never surface the
    # problem because it resolves to the newest release. The validator below is
    # the enforcement, so the annotation does not need to carry the shape.
    result: dict[str, Any] | None = None
    disclosure: Disclosure | None = None
    error: ProblemDetail | None = None

    @field_validator("result", mode="before")
    @classmethod
    def _result_must_encode_deterministically(cls, value: Any) -> Any:  # noqa: ANN401
        """Reject a payload that would serialise differently across processes.

        `result` is the one field carrying capability-specific content, so it is
        the one place the envelope's canonical-encoding guarantee could be lost
        silently. Checking here means it fails at construction instead.

        Note that `model_copy(update=...)` and `model_construct` skip validation
        entirely, which is standard Pydantic behaviour. Since the model is
        frozen, `model_copy` is the natural way to derive a modified envelope,
        so a caller taking that route can still place a non-deterministic value
        in `result`. Build a new envelope rather than copying when the payload
        changes.
        """
        return value if value is None else ensure_deterministic(value)

    @model_validator(mode="after")
    def _check(self) -> ResponseEnvelope:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract_version: {self.contract_version!r}")
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        if (self.error is None) == (self.disclosure is None):
            raise ValueError("exactly one of disclosure or error must be set")
        if self.error is not None and self.result is not None:
            raise ValueError("an error response cannot carry a result")
        if self.error is not None and self.error.correlation_id != self.correlation_id:
            raise ValueError("error correlation_id must match the envelope")
        return self
