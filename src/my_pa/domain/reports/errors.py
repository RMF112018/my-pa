"""Typed refusals the general report domain raises.

Each names the field and the rule it enforced and never the value it refused,
the discipline `domain.capture.errors` applies: a refusal can be classified
into a public code without stripping anything out of its message first.
"""

from __future__ import annotations

__all__ = [
    "ReportDomainError",
    "ReportLifecycleRefusal",
    "ReportRetentionOverflowError",
    "ReportValidationError",
]


class ReportDomainError(Exception):
    """A general report value or transition refused to exist."""


class ReportValidationError(ReportDomainError):
    """A caller-supplied field broke a frozen bound.

    `field` names the input (`title`, `metadata`, `topics`, ...) and `code` the
    rule (`type`, `too_short`, `too_long`, `control_character`, ...). Both are
    stable strings chosen by this module, so the message built from them can
    never echo the offending value.
    """

    def __init__(self, field: str, code: str) -> None:
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


class ReportRetentionOverflowError(ReportValidationError):
    """A retention period added to a clock start lands past `datetime.max` (year 9999).

    Reports Modernization WP08 (WP05b review #8). A subclass of
    `ReportValidationError`, so every handler that maps an invalid retention
    computation maps this one the same way (`reports.retention.get`:
    `internal_error`), never an unmapped `OverflowError`. Unreachable with
    server-clock timestamps; the field and code name the rule, not the value.
    """

    def __init__(self) -> None:
        super().__init__("eligible_at", "out_of_range")


class ReportLifecycleRefusal(ReportDomainError):  # noqa: N818 - contract section 2 name
    """The requested operation is not legal from the report's current state.

    Carries the state and the operation, both closed enumerations, so the
    message is a fact about the transition table and not about any caller text.
    """

    code = "illegal_transition"

    def __init__(self, state: str, operation: str) -> None:
        super().__init__(f"lifecycle: {operation} is not legal from {state}")
        self.state = state
        self.operation = operation
