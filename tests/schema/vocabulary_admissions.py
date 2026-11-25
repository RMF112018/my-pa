"""The one home of the capability and purpose families admitted after the files workspace revision.

Why this exists (SCOPE "pins and counts", row B4, phase P3). A migration test
at an older revision asserts that revision's spelled audit vocabulary equals
the domain's `Capability` set **minus** every name a later revision admitted.
Before this module each such test spelled the later names itself
(`declared -= {"meetings.provider.bind"}`), so every new capability family cost
one edit in each of them. Now a family is recorded here once, with the revision
that admits it, and each test subtracts `capabilities_admitted_after(<its own
revision>)`.

Scope: families admitted by revisions after `SINCE` (the files workspace
revision, `640aaacc78e8`). Earlier families keep their own frozen homes (for
example `files_workspace_vocabulary_contract.FILES_CAPABILITIES`,
`schedule_scenarios_vocabulary_contract.S63_CAPABILITIES`), which their tests
already import; they never change again.

`tests/schema/test_vocabulary_admissions.py` holds the table complete: the
newest revision's spelled capability set minus the `SINCE` revision's is
exactly the union of the rows, and each row's names are spelled in its own
revision. A new vocabulary revision therefore adds one row here, in the same
change. This is a helper module, not a test module: pytest does not collect it.

`PURPOSE_ADMISSIONS` is the purpose analogue (communications WP4 ruling R17):
an older revision's purpose test subtracts `purposes_admitted_after(<its own
revision>)` the same way, under the same scope and frozen-literal rules.
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
        # P6 XER import S7-2: the schedule P6 revision admits the seven S7-4
        # names of contract section 10.1, ahead of the domain (see below).
        "schedule_p6": (
            "d8383150cf72",
            frozenset(
                {
                    "schedule_publications.import_p6",
                    "schedule_p6_fields.available",
                    "schedule_p6_fields.set_captured",
                    "schedule_p6_activities.list",
                    "schedule_p6_relationships.list",
                    "schedule_p6_calendars.list",
                    "schedule_p6_field_values.list",
                }
            ),
        ),
        # Communications intelligence WP4 (ADR-022): the communications search revision.
        "communications_reads": (
            "fa18ef3d9bc0",
            frozenset({"communications.coverage", "communications.read", "communications.search"}),
        ),
    }
)

#: Family -> (the revision that admits it, its purpose names), for the purpose
#: families admitted after `SINCE` (which is also the latest purpose revision
#: before them). Same rules as `CAPABILITY_ADMISSIONS`.
PURPOSE_ADMISSIONS: Final[Mapping[str, tuple[str, frozenset[str]]]] = MappingProxyType(
    {
        # P6 XER import S7-2: the new purpose names of contract section 10.1.
        "schedule_p6": (
            "d8383150cf72",
            frozenset({"schedule_p6_import", "schedule_p6_configuration"}),
        ),
        # Communications intelligence WP4 (ADR-022): the communications search revision.
        "communications_read": ("fa18ef3d9bc0", frozenset({"communications_read"})),
    }
)

#: The families whose names the schema admits ahead of the domain: the audit
#: vocabulary holds them while `Capability` and `Purpose` do not declare them
#: yet. A test comparing the newest frozen audit vocabulary with the domain
#: adds `admitted_ahead_of_the_domain(...)` instead of spelling the names.
#: `schedule_p6` leaves this set in the S7-4 change that declares its names.
AHEAD_OF_THE_DOMAIN: Final[frozenset[str]] = frozenset({"schedule_p6"})


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
    """Every recorded purpose name a revision later than `revision` admits."""
    position = pins.ALEMBIC_CHAIN.index(revision)
    return frozenset().union(
        *(
            names
            for admitting, names in PURPOSE_ADMISSIONS.values()
            if pins.ALEMBIC_CHAIN.index(admitting) > position
        )
    )


def admitted_ahead_of_the_domain(kind: str) -> frozenset[str]:
    """The `capability` or `purpose` names the schema admits and the domain does not yet."""
    table = {"capability": CAPABILITY_ADMISSIONS, "purpose": PURPOSE_ADMISSIONS}[kind]
    return frozenset().union(
        *(names for family, (_revision, names) in table.items() if family in AHEAD_OF_THE_DOMAIN)
    )
