"""WP-11 reviewer NOTE 2, discharged with evidence rather than with an assertion.

`SqlContinuityRepository.accept` verifies that a review decision exists, belongs
to the Principal, and carries an accepting disposition — and does **not** verify
that the decision decided *this object*. One accepting decision can therefore
promote unrelated continuity objects. NOTE 2 records that the defect must close
before the continuity write plane is wired to any capability.

WP-12 had to determine whether the relationship identity aggregate reaches it.
It does not, and the four facts below are why. They are asserted rather than
described, so the determination expires the moment it stops being true:

1. `accept` dispatches through `_OBJECT_TABLE`, which maps the five
   `ContinuityObjectKind` members to five continuity tables. No relationship
   table appears in it, so there is no `object_kind` that names a person, an
   identity observation, or an identity resolution — the gate has no way to
   address the relationship plane even if it were called with one.
2. `ContinuityObjectKind` has five members and none is relational.
3. `accept` reads `capture_review_decisions`. The relationship plane's
   decisions live in `relationship_identity_review_decisions`, a different
   table, so the two governance records do not even share a namespace.
4. Nothing in `src/` or `apps/` calls it at all, and in particular
   `persistence/relationships.py` — the whole relationship write plane — neither
   imports nor names `situation_repository`.

**This is a reachability finding, not a repair.** The defect is untouched and
still open on the continuity plane; what is established here is that WP-12's
work does not depend on it and does not widen it. If a future change wires the
relationship plane into that gate, these fail and the defect has to close first,
which is the outcome NOTE 2 asked for.

The relationship plane's own equivalent binding — that a decision authorizes the
exact review case, action, people and observations it decided — is asserted
behaviourally in
`tests/schema/test_relationship_schema_migration.py::test_an_accepting_decision_from_another_review_case_cannot_authorize_a_merge`.

The last test here records a **second** surface with NOTE 2's posture, found
while making that determination: `RelationshipEventRepository.record_event`
takes `accepted` as an argument all the way from
`RecordRelationshipEventCommand`, so whoever calls it decides whether a
relationship-timeline event is an accepted fact — no review decision is
consulted and none is recorded on the row. It defaults false, and no capability
reaches it, so it is latent rather than live. Wiring it without binding
`accepted` to a review decision would put a derivation's own output on the
accepted timeline, which is exactly what invariant 5 forbids; the test below
makes that wiring redden rather than land quietly.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path
from typing import Final

from my_pa.application.commands import RecordRelationshipEventCommand
from my_pa.domain.situation.continuity import ContinuityObjectKind
from my_pa.infrastructure.persistence.situation_repository import _OBJECT_TABLE
from my_pa.infrastructure.persistence.tables import relationship_events

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
APPS: Final = ROOT / "apps"
PERSISTENCE: Final = PACKAGE / "infrastructure" / "persistence"
CONTINUITY_REPOSITORY: Final = PERSISTENCE / "situation_repository.py"
RELATIONSHIP_REPOSITORY: Final = PERSISTENCE / "relationships.py"

#: The five continuity kinds `accept` can address. None is relational.
EXPECTED_KINDS: Final = frozenset({"commitment", "decision", "task", "situation", "project"})


def _python_sources() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE.rglob("*.py"))) + tuple(sorted(APPS.rglob("*.py")))


def test_the_acceptance_gate_can_address_only_the_five_continuity_kinds() -> None:
    """Fact 1 and 2: the dispatch table, and the vocabulary that indexes it."""
    assert {kind.value for kind in ContinuityObjectKind} == EXPECTED_KINDS
    assert {kind.value for kind in _OBJECT_TABLE} == EXPECTED_KINDS
    addressable = {table.name for table, _column in _OBJECT_TABLE.values()}
    relational = sorted(name for name in addressable if name.startswith("relationship_"))
    assert relational == [], (
        f"{relational} became addressable through the continuity acceptance gate. "
        "That gate does not verify the decision decided *this* object (WP-11 "
        "reviewer NOTE 2), so a relationship record reachable through it is "
        "promotable by an unrelated accepting decision. Close NOTE 2 first"
    )


def test_the_acceptance_gate_reads_a_different_decision_table_entirely() -> None:
    """Fact 3: the two governance records do not share a table."""
    source = CONTINUITY_REPOSITORY.read_text(encoding="utf-8")
    accept = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "accept"
    )
    named = {node.id for node in ast.walk(accept) if isinstance(node, ast.Name)}
    assert "capture_review_decisions" in named, (
        "`accept` no longer reads `capture_review_decisions`; the determination "
        "below is measuring a function that has changed shape"
    )
    relational = sorted(name for name in named if name.startswith("relationship_"))
    assert relational == [], (
        f"`accept` now names {relational}. The relationship plane's decisions are "
        "governed by `relationship_identity_review_decisions` and its own exact "
        "case/action/subject binding; routing them through this gate would "
        "replace that binding with a weaker one"
    )


def test_nothing_calls_the_acceptance_gate_and_the_relationship_plane_cannot() -> None:
    """Fact 4: it is unreachable today, and unreachable *from here* specifically."""
    callers = sorted(
        str(path.relative_to(ROOT))
        for path in _python_sources()
        if re.search(r"\.accept\(", path.read_text(encoding="utf-8"))
    )
    # The two live `.accept(` call sites are an enrollment admission and a
    # migration key guard; neither is the continuity gate. Named, so the claim
    # "nothing calls it" is a measurement rather than a grep that found nothing.
    assert callers == [
        "src/my_pa/application/service.py",
        "src/my_pa/infrastructure/migration/loader.py",
    ], f"a new `.accept(` call site appeared in {callers}; confirm it is not the continuity gate"

    relationship_source = RELATIONSHIP_REPOSITORY.read_text(encoding="utf-8")
    for forbidden in ("situation_repository", "SqlContinuityRepository", "ContinuityObjectKind"):
        assert forbidden not in relationship_source, (
            f"the relationship write plane now names {forbidden}. NOTE 2's defect "
            "is open on that gate; reaching it from here makes the relationship "
            "identity aggregate depend on an unclosed one"
        )


def test_the_relationship_event_accepted_flag_is_caller_supplied_and_unwired() -> None:
    """The second unwired acceptance surface, registered so it cannot go live quietly.

    `record_event(..., accepted=...)` writes the flag Today/Pulse and the
    briefing filter on, and consults no review decision to do it. The row keeps
    no `accepted_by_review_decision_id` either, so an accepted relationship
    event carries no trace of what accepted it — unlike a continuity object,
    which at least records the decision it was promoted by.

    Two things make that latent rather than live, and both are asserted so that
    changing either forces the governance question first:

    * `accepted` defaults to false on the command, so an omission proposes
      rather than asserts;
    * nothing in `src/` or `apps/` calls `record_relationship_event` — the
      relationship-event write plane is reached only from tests.

    **Not a repair.** Binding `accepted` to a review decision is a design change
    with no consumer today; WP-12 records the residual instead of inventing a
    governance path nothing asks for.
    """
    accepted = next(
        field
        for field in dataclasses.fields(RecordRelationshipEventCommand)
        if field.name == "accepted"
    )
    assert accepted.default is False, (
        "the relationship-event `accepted` flag no longer defaults to proposed; "
        "an omitted flag now asserts a timeline fact (invariant 5)"
    )
    assert "accepted_by_review_decision_id" not in relationship_events.c, (
        "`relationship_events` gained a review-decision column. That is how this "
        "residual closes — bind `accepted` to it and remove this test rather "
        "than leaving a registry that describes the old shape"
    )

    callers = sorted(
        str(path.relative_to(ROOT))
        for path in _python_sources()
        if "record_relationship_event" in path.read_text(encoding="utf-8")
    )
    assert callers == [
        "src/my_pa/application/situation_service.py",
    ], (
        f"{callers} now reach the relationship-event write plane. Its `accepted` "
        "flag is caller-supplied and bound to no review decision, so wiring it to "
        "a capability lets a derivation promote its own output onto the accepted "
        "timeline. Bind acceptance to a review decision before wiring it"
    )
