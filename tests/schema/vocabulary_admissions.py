"""The one home of the vocabulary families admitted after the files workspace revision.

Why this exists (SCOPE "pins and counts", row B4, phase P3). A migration test
at an older revision asserts that revision's spelled audit vocabulary equals
the domain's `Capability` set **minus** every name a later revision admitted.
Before this module each such test spelled the later names itself
(`declared -= {"meetings.provider.bind"}`), so every new capability family cost
one edit in each of them. Now a family is recorded here once, with the revision
that admits it, and each test subtracts `capabilities_admitted_after(<its own
revision>)`. Purposes follow the same rule through `PURPOSE_ADMISSIONS` and
`purposes_admitted_after` (communications WP4, ruling R17): before them, each
old-revision test asserted its purpose set equal to the live `Purpose` enum and
broke on every new purpose.

Scope: families admitted by revisions after `SINCE` (the files workspace
revision, `640aaacc78e8`). Earlier families keep their own frozen homes (for
example `files_workspace_vocabulary_contract.FILES_CAPABILITIES`,
`schedule_scenarios_vocabulary_contract.S63_CAPABILITIES`), which their tests
already import; they never change again.

`tests/schema/test_vocabulary_admissions.py` holds the table complete: the
newest revision's spelled capability set minus the `SINCE` revision's is
exactly the union of the rows, and each row's names are spelled in its own
revision; the same holds for the purpose rows. A new vocabulary revision
therefore adds one row here, in the same change. This is a helper module, not
a test module: pytest does not collect it.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from tests import pins

#: The files workspace revision. Every row below is admitted after it.
SINCE: Final = "640aaacc78e8"

#: Family -> (the revision that admits it, its capability names). Frozen
#: literals copied from each revision, never derived from the enums they are
#: checked against.
CAPABILITY_ADMISSIONS: Final[Mapping[str, tuple[str, frozenset[str]]]] = MappingProxyType(
    {
        # Communications intelligence WP2-W3 (ADR-022): the provider-binding revision.
        "meetings_provider_bind": ("6418b57081c3", frozenset({"meetings.provider.bind"})),
        # Communications intelligence WP3b (ADR-022): the meeting sync staging revision.
        "meetings_provider_review_reconcile": (
            "61fafdfd2986",
            frozenset({"meetings.provider.reconcile", "meetings.provider.review"}),
        ),
        # Communications intelligence WP4 (ADR-022): the communications search revision.
        "communications_reads": (
            "fa18ef3d9bc0",
            frozenset({"communications.coverage", "communications.read", "communications.search"}),
        ),
    }
)

#: Purpose family -> (the revision that admits it, its purposes), the purpose
#: analogue of `CAPABILITY_ADMISSIONS` (WP4 ruling R17). Same scope (after
#: `SINCE`) and the same frozen-literal rule.
PURPOSE_ADMISSIONS: Final[Mapping[str, tuple[str, frozenset[str]]]] = MappingProxyType(
    {
        # Communications intelligence WP4 (ADR-022): the communications search revision.
        "communications_read": ("fa18ef3d9bc0", frozenset({"communications_read"})),
    }
)


def capabilities_admitted_after(revision: str) -> frozenset[str]:
    """Every recorded capability name a revision later than `revision` admits."""
    position = pins.ALEMBIC_CHAIN.index(revision)
    return frozenset().union(
        *(
            names
            for admitting, names in CAPABILITY_ADMISSIONS.values()
            if pins.ALEMBIC_CHAIN.index(admitting) > position
        )
    )


def purposes_admitted_after(revision: str) -> frozenset[str]:
    """Every recorded purpose a revision later than `revision` admits."""
    position = pins.ALEMBIC_CHAIN.index(revision)
    return frozenset().union(
        *(
            names
            for admitting, names in PURPOSE_ADMISSIONS.values()
            if pins.ALEMBIC_CHAIN.index(admitting) > position
        )
    )
