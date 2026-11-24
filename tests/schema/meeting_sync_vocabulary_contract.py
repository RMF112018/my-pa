"""The one home of the WP3b meeting sync audit vocabulary (Manager rulings D2, D9).

Revision `61fafdfd2986` (WP3b-S1) restates `capability_is_known` with
`meetings.provider.reconcile` and `meetings.provider.review`. The domain's
`Capability` enum gains the same names in WP3b-S4, so between the two the head
audit vocabulary is the domain's **union** this set; a head-equality test spells
that as `declared | MEETING_SYNC_CAPABILITIES`, which holds both before and
after S4. Frozen literals copied from the rulings, never derived from the enum
they are checked against. This is a helper module, not a test module: pytest
does not collect it.
"""

from __future__ import annotations

from typing import Final

MEETING_SYNC_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"meetings.provider.reconcile", "meetings.provider.review"}
)
