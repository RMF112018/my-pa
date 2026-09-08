"""The Constraint Management authoring vocabulary and its classification (PC-CM-IMP-WP07).

`T07-01`, `T07-02` and `T07-03`. Three separate claims, and they fail in
different ways.

**The names.** The twelve `constraints.` and `constraint_categories.` authoring
members, with exact string values; one `Purpose`; and the two resulting sizes.
A member spelled `constraints.close-follow-up` would be a different wire name on
every transport, so the values are asserted rather than the members.

**The purposes.** Every authoring capability maps to `constraint_authoring` and
to nothing else; every read still maps to `constraint_read` and to nothing else;
no capability holds both. That disjointness is the read/authoring separation
`CM-BE-AC-076` asks for, and it is now a property of two mapped sets rather than
of one absent one.

**The classification.** All twelve are write capabilities; exactly
`constraints.create` and `constraint_categories.create` are additive; none is
operator-only. This is the assertion `N-03` records the need for:
`tests/unit/test_policy.py` walks every capability against `_PERMITTED_PURPOSES`
and nothing walks the two write frozensets, which are hand-curated with a silent
default of `False`. The consequence is not bookkeeping —
`src/my_pa/adapters/mcp/tools.py` publishes `destructive_hint` from
`_WRITE_CAPABILITIES - _ADDITIVE_WRITE_CAPABILITIES`, so a capability wrongly
called additive is a lifecycle transition annotated as a plain insert.

And the negative: no `constraint_sync.*` capability and no sync purpose exists.
That plane is `PC-CM-IMP-WP11`'s, and a name minted here would be one nothing
dispatches.
"""

from __future__ import annotations

from typing import Final

import pytest

from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose

#: The twelve, by member and by the exact value each publishes.
AUTHORING: Final[tuple[tuple[Capability, str], ...]] = (
    (Capability.CONSTRAINTS_CREATE, "constraints.create"),
    (Capability.CONSTRAINTS_PUBLISH, "constraints.publish"),
    (Capability.CONSTRAINTS_UPDATE, "constraints.update"),
    (Capability.CONSTRAINTS_TRANSITION, "constraints.transition"),
    (Capability.CONSTRAINTS_CLOSE, "constraints.close"),
    (Capability.CONSTRAINTS_CLOSE_FOLLOW_UP, "constraints.close_follow_up"),
    (Capability.CONSTRAINTS_VOID, "constraints.void"),
    (Capability.CONSTRAINTS_REOPEN, "constraints.reopen"),
    (Capability.CONSTRAINT_CATEGORIES_CREATE, "constraint_categories.create"),
    (Capability.CONSTRAINT_CATEGORIES_UPDATE, "constraint_categories.update"),
    (Capability.CONSTRAINT_CATEGORIES_DEACTIVATE, "constraint_categories.deactivate"),
    (Capability.CONSTRAINT_CATEGORIES_REORDER, "constraint_categories.reorder"),
)

READS: Final[tuple[Capability, ...]] = (
    Capability.CONSTRAINTS_READ,
    Capability.CONSTRAINTS_LIST,
    Capability.CONSTRAINTS_SEARCH,
    Capability.CONSTRAINTS_HISTORY,
    Capability.CONSTRAINTS_OVERVIEW,
    Capability.CONSTRAINT_CATEGORIES_LIST,
)

#: The only two of the twelve that add a durable record and reach no existing
#: one. Every other one replaces, transitions, supersedes or retires state.
ADDITIVE: Final[frozenset[Capability]] = frozenset(
    {Capability.CONSTRAINTS_CREATE, Capability.CONSTRAINT_CATEGORIES_CREATE}
)


# ---- T07-01: the names exist, with exact values ------------------------------


@pytest.mark.parametrize(("capability", "value"), AUTHORING, ids=lambda item: str(item))
def test_each_authoring_capability_publishes_its_exact_wire_name(
    capability: Capability, value: str
) -> None:
    assert capability.value == value


def test_the_authoring_purpose_exists_and_is_the_only_one_added() -> None:
    assert Purpose.CONSTRAINT_AUTHORING.value == "constraint_authoring"
    assert {purpose for purpose in Purpose if purpose.value.startswith("constraint")} == {
        Purpose.CONSTRAINT_READ,
        Purpose.CONSTRAINT_AUTHORING,
    }


def test_the_two_vocabularies_are_the_sizes_this_package_states() -> None:
    """The counts the census documents and the migration are written against."""
    assert len(Capability) == 154
    assert len(Purpose) == 43


def test_no_public_migration_capability_exists() -> None:
    """`CM-BE-AC-080`, as a negative over the whole set.

    Legacy import and migration tooling is an operator program that composes its
    own unit of work; admitting it to `Capability` would put it on three public
    transports at once.
    """
    named = [
        capability
        for capability in Capability
        if "migrat" in capability.value or "import" in capability.value
    ]
    assert named == []


# ---- T07-02: the purpose mapping --------------------------------------------


@pytest.mark.parametrize("capability", [pair[0] for pair in AUTHORING], ids=lambda c: c.value)
def test_every_authoring_capability_is_granted_only_the_authoring_purpose(
    capability: Capability,
) -> None:
    assert permitted_purposes(capability) == frozenset({Purpose.CONSTRAINT_AUTHORING})


@pytest.mark.parametrize("capability", READS, ids=lambda c: c.value)
def test_every_constraint_read_is_still_granted_only_the_read_purpose(
    capability: Capability,
) -> None:
    """The regression half of `CM-BE-AC-076`, and it is not implied by the row above.

    A read that acquired the authoring purpose would still satisfy every
    assertion about the authoring names; only reading the mapping from the read
    side catches it.
    """
    assert permitted_purposes(capability) == frozenset({Purpose.CONSTRAINT_READ})


def test_the_authoring_purpose_reaches_the_twelve_and_nothing_else() -> None:
    """Read from the purpose's end, which is where a quiet widening would show."""
    reached = {
        capability
        for capability in Capability
        if Purpose.CONSTRAINT_AUTHORING in permitted_purposes(capability)
    }
    assert reached == {pair[0] for pair in AUTHORING}


def test_no_capability_holds_both_constraint_purposes() -> None:
    both = [
        capability
        for capability in Capability
        if {Purpose.CONSTRAINT_READ, Purpose.CONSTRAINT_AUTHORING} <= permitted_purposes(capability)
    ]
    assert both == []


def test_every_capability_still_has_a_mapping() -> None:
    """`_PERMITTED_PURPOSES` is exhaustive, so no name is permanently denied."""
    for capability in Capability:
        assert permitted_purposes(capability), f"{capability} would be permanently denied"


# ---- T07-03: write, destructive and operator-only classification -------------


@pytest.mark.parametrize("capability", [pair[0] for pair in AUTHORING], ids=lambda c: c.value)
def test_every_authoring_capability_is_a_write(capability: Capability) -> None:
    assert is_write_capability(capability)


@pytest.mark.parametrize("capability", [pair[0] for pair in AUTHORING], ids=lambda c: c.value)
def test_exactly_the_two_creations_are_additive(capability: Capability) -> None:
    """Additive means "adds a record and changes no existing state", not "does not delete".

    Publish consumes the Category's allocator sequence and moves a Draft;
    `constraints.close_follow_up` marks the predecessor *and* mints the
    successor; `constraint_categories.deactivate` retires a live row. Each of
    those is a change to state that already existed, and calling any of them
    additive would publish `destructive_hint=False` on a lifecycle transition.
    """
    assert is_destructive_capability(capability) is (capability not in ADDITIVE)


@pytest.mark.parametrize("capability", [pair[0] for pair in AUTHORING], ids=lambda c: c.value)
def test_no_authoring_capability_is_operator_only(capability: Capability) -> None:
    """Constraint authoring is ordinary Principal work over the Principal's own partition.

    The operator set exists for capabilities that widen the scope a later
    request is evaluated against — `sources.enroll`, the identity-correction
    pair. None of these does.
    """
    assert not is_operator_only(capability)


def test_exactly_ten_of_the_twelve_are_destructive() -> None:
    destructive = {pair[0] for pair in AUTHORING if is_destructive_capability(pair[0])}
    assert len(destructive) == 10
    assert destructive == {pair[0] for pair in AUTHORING} - ADDITIVE


def test_no_constraint_read_became_a_write() -> None:
    for capability in READS:
        assert not is_write_capability(capability)
        assert not is_destructive_capability(capability)
        assert not is_operator_only(capability)


def test_no_synchronisation_capability_or_purpose_exists() -> None:
    """`PC-CM-IMP-WP11`'s vocabulary, deliberately absent at this head."""
    assert [c for c in Capability if c.value.startswith("constraint_sync")] == []
    assert [p for p in Purpose if "sync" in p.value] == []
