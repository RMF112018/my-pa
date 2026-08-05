"""Internal application-port records for the native baseline worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from my_pa.contracts.v1.native_sources import NativeSourceKind

__all__ = [
    "AdmittedNativePage",
    "BaselineResumePoint",
    "FrozenBaseline",
    "NativeBaselineJob",
]


class NativeAdmissionCounts(Protocol):
    @property
    def admitted_count(self) -> int: ...

    @property
    def duplicate_count(self) -> int: ...


class AdmittedNativePage(Protocol):
    @property
    def admission(self) -> NativeAdmissionCounts: ...

    @property
    def authority_id(self) -> str: ...

    @property
    def next_cursor(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class FrozenBaseline:
    run_id: str
    configuration_id: str
    configuration_revision: int
    cutoff_at: datetime


@dataclass(frozen=True, slots=True)
class NativeBaselineJob:
    job_id: str
    run_id: str
    configuration_id: str
    configuration_revision: int
    bucket_id: str
    kind: NativeSourceKind
    range_start: datetime
    range_end: datetime
    current_inventory: bool
    lease_owner: str


@dataclass(frozen=True, slots=True)
class BaselineResumePoint:
    cursor: str | None
    terminal: bool
    page_count: int
