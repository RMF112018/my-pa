"""Read-only normalized personal-source fixture port.

The port has one read and no mutation method. Real contacts, email, and calendar
adapters remain unauthorized; WP-9's only implementation reads synthetic JSON
fixtures through the already-conformant filesystem boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.relationship.identity import IdentityObservation

__all__ = ["PersonalSourceBatch", "PersonalSourceProvider"]


@dataclass(frozen=True, slots=True)
class PersonalSourceBatch:
    domain: str
    state: CoverageState
    observations: tuple[IdentityObservation, ...]
    limitation: str | None = None

    def __post_init__(self) -> None:
        if not self.domain.strip():
            raise ValueError("a personal-source domain is not blank")
        if self.state not in {CoverageState.PROCESSED, CoverageState.UNAVAILABLE}:
            raise ValueError("a personal-source fixture is processed or unavailable")
        if self.state is CoverageState.PROCESSED and (
            not self.observations or self.limitation is not None
        ):
            raise ValueError("processed personal-source coverage contains observations only")
        if self.state is CoverageState.UNAVAILABLE and (
            self.observations or not (self.limitation and self.limitation.strip())
        ):
            raise ValueError("unavailable personal-source coverage states why and contains no rows")


class PersonalSourceProvider(ABC):
    @abstractmethod
    def observations(self) -> tuple[PersonalSourceBatch, ...]:
        """Return normalized observations and explicit unavailable domains."""
