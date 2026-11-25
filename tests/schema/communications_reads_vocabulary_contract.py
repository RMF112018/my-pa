"""The communications read names the WP4 revision admits ahead of the domain.

Revision `fa18ef3d9bc0` (communications intelligence WP4-S1, ruling D7)
restates `capability_is_known` with the three `communications.*` read names and
`purpose_is_known` with `communications_read`. The domain declares them in
WP4-S5, so until then the head audit vocabulary is the domain's **union** these
sets; every head-equality test that sets aside the files names sets these aside
too, which holds both before and after S5 (the WP3b
`meeting_sync_vocabulary_contract.py` precedent; S5 removes this module).
Frozen literals, never derived from the enums they are checked against. This is
a helper module, not a test module: pytest does not collect it.
"""

from __future__ import annotations

from typing import Final

COMMUNICATIONS_READ_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"communications.coverage", "communications.read", "communications.search"}
)
COMMUNICATIONS_READ_PURPOSES: Final[frozenset[str]] = frozenset({"communications_read"})
