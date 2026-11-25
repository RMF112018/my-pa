"""P6 XER import, slice S7-1: the pure parser, catalogue, frame and profile.

Contract `docs/architecture/schedule-xer-import-contract.md` sections 3-7, 12
and 13 under ADR-023. Pure and standard library only (no clock, randomness,
file, network or logging), bound by `tests/architecture/test_cpm_full_parser_scope.py`
and `tests/architecture/test_schedule_p6_parser_scope.py`.

S7-3 (section 9.3, acceptance C4): the parser front end (`parser`, `reader`,
`values`, `calendar`, `profile`) is loaded only on first use of `parse_xer`,
`export_profile`, `verdict` or `Verdict`, so a process that imports only the
catalogue, the model or the frame -- the worker parent, the persistence
tables -- never loads the parser. Only the contained child parses.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Final

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

if TYPE_CHECKING:
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

#: The parser front end's public names and the submodule each lives in.
_LAZY: Final = {
    "parse_xer": "parser",
    "Verdict": "profile",
    "export_profile": "profile",
    "verdict": "profile",
}


def __getattr__(name: str) -> object:
    """Load the parser front end on first use of one of its names (PEP 562)."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(name)
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
