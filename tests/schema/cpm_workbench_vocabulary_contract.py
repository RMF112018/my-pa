"""The one home of the CPM Workbench S5b-2 audit vocabulary (contract section 3.14).

The single S5b-2 revision `621ef6786c64` restates `capability_is_known` and
`purpose_is_known` with the 7 Schedule capability names and the 2 Schedule
purposes, and the S5b-2 registration declares every one of them in the same
change, so there is no schema-ahead gap. Earlier revisions' vocabulary tests
set these names aside as admitted later, exactly as they set aside each lineage
slice's names. Frozen literals, never derived from the enums they are checked
against. This is a helper module, not a test module: pytest does not collect it.
"""

from __future__ import annotations

from typing import Final

S5B2_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "schedule_publications.import",
        "schedule_series.list",
        "schedule_publications.list",
        "schedule_publications.read",
        "schedule_activities.list",
        "schedule_activities.history",
        "schedule_changes.list",
    }
)
S5B2_PURPOSES: Final[frozenset[str]] = frozenset({"schedule_import", "schedule_read"})
