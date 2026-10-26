"""The Program overview digest (record lineage S4 contract section 5.1).

`overview_sha256 = sha256(b"program-overview-v1\\n" + canonical_json(D))` where
`D` is the `programs.overview` answer **as served** without its 3 read-time
stamps (`overview_sha256`, `source_cutoff_at`, `lineage_known_at`). The
canonical JSON is ADR-014 decision 6 (`domain.lineage.canonical`: NFC, sorted
keys, compact separators, no floats). `project_today` and
`constraint_sync.last_verified_at` stay in `D`: the first decides overdue, the
second is stored data. Two overviews of an unchanged state on one Project
calendar day are equal; any change of membership, a metric value, a reason, a
source state or a calendar day changes it. A withheld field is `null` in the
answer, so the digest never encodes a withheld value.

Pure: no I/O.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Final

from my_pa.domain.lineage.canonical import canonical_json
from my_pa.domain.program.vocabulary import PROGRAM_CALCULATION_VERSION

__all__ = ["OVERVIEW_DIGEST_PREFIX", "OVERVIEW_READ_TIME_STAMPS", "overview_digest"]

#: Section 5.1: the domain prefix of the overview digest.
OVERVIEW_DIGEST_PREFIX: Final = f"{PROGRAM_CALCULATION_VERSION}\n".encode("ascii")
#: Section 5.1: the 3 top-level keys `D` leaves out.
OVERVIEW_READ_TIME_STAMPS: Final[frozenset[str]] = frozenset(
    {"overview_sha256", "source_cutoff_at", "lineage_known_at"}
)


def overview_digest(answer: Mapping[str, object]) -> str:
    """The section 5.1 digest of one overview answer (JSON-mode, as served)."""
    body = {key: value for key, value in answer.items() if key not in OVERVIEW_READ_TIME_STAMPS}
    encoded = canonical_json(body).encode("utf-8")
    return hashlib.sha256(OVERVIEW_DIGEST_PREFIX + encoded).hexdigest()
