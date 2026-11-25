"""P6 XER import, slice S7-1: the pure parser, catalogue, frame and profile.

Contract `docs/architecture/schedule-xer-import-contract.md` sections 3-7, 12
and 13 under ADR-023. Pure and standard library only (no clock, randomness,
file, network or logging), bound by `tests/architecture/test_cpm_full_parser_scope.py`
and `tests/architecture/test_schedule_p6_parser_scope.py`.
"""

from __future__ import annotations

from my_pa.domain.schedule.p6.catalogue import CATALOGUE, CATALOGUE_VERSION
from my_pa.domain.schedule.p6.frame import FRAME_SCHEMA, frame_bytes, frame_sha256
from my_pa.domain.schedule.p6.model import (
    P6_LIMITS,
    PROFILE_ID,
    P6IssueCode,
    P6Limits,
    P6Outcome,
    P6ParseResult,
)
from my_pa.domain.schedule.p6.parser import parse_xer
from my_pa.domain.schedule.p6.profile import Verdict, export_profile, verdict

__all__ = [
    "CATALOGUE",
    "CATALOGUE_VERSION",
    "FRAME_SCHEMA",
    "P6_LIMITS",
    "PROFILE_ID",
    "P6IssueCode",
    "P6Limits",
    "P6Outcome",
    "P6ParseResult",
    "Verdict",
    "export_profile",
    "frame_bytes",
    "frame_sha256",
    "parse_xer",
    "verdict",
]
