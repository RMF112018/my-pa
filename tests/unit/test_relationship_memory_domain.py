"""What `domain.relationship.memory` refuses, and why each refusal is load-bearing.

Beside `tests/unit/test_entity_domain.py`, which makes the same kind of claim
about the plane that owns a memory's subject. This one is about the record class
itself: the ten semantic kinds, the partial dates the product must be able to
hold without inventing the missing half, the classification floor that keeps a
`sensitivity` out of a broad read, and the four fields no caller and no writer on
this path may set.

Every assertion here is about a rule that has somewhere else to fail. The schema
carries a CHECK for most of them and the repository proves ownership for the
rest, so a rule that held only in SQL would be a rule the in-memory fake, the
proposal plane and any future writer do not inherit. This file is the layer
where a bad value is refused before a connection is opened.

Nothing here touches a database, a file, or a network. Every identifier and every
statement is synthetic: no real person, no real date, no live data.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from my_pa.domain.common.classification import Classification
from my_pa.domain.relationship.entity import EntityType
from my_pa.domain.relationship.memory import (
    MEMORY_STRUCTURED_SCHEMAS,
    PERSON_ONLY_KINDS,
    STRUCTURED_VALUE_KINDS,
    MemoryActorClass,
    MemoryAuthority,
    MemoryKind,
    MemoryKindNotPermittedError,
    MemoryLifecycle,
    MemoryProposalMethod,
    MemoryProposalState,
    MemoryStructuredValueError,
    RelationshipMemory,
    RelationshipMemoryError,
    RelationshipMemoryProposal,
    RelationshipMemoryVersion,
    check_kind_permits_subject,
    classification_floor_for,
    statement_digest,
    validate_structured_value,
)

#: Synthetic identifiers. None of these names anything that exists.
PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
MEMORY: Final = "mem_aaaa0001aaaa0001"
VERSION: Final = "memver_aaaa0001aaaa0001"
PRIOR_VERSION: Final = "memver_bbbb0002bbbb0002"
SUBJECT: Final = "ent_aaaa0001aaaa0001"
CORRELATION: Final = "corr_aaaa0001aaaa0001"
PROPOSAL: Final = "mprop_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 22, 12, tzinfo=UTC)

#: One synthetic note. Distinctive enough that finding it in a `repr` is
#: evidence rather than coincidence.
STATEMENT: Final = "Synthetic subject prefers Teams messages (qzvbnr-marker)."


def a_version(**overrides: object) -> RelationshipMemoryVersion:
    """One valid version, with `overrides` applied. Every test starts from valid.

    The digest follows the statement unless a test overrides it explicitly, so a
    test about some other field cannot pass by accident on a digest mismatch.
    """
    statement = str(overrides.pop("statement", STATEMENT))
    kind = overrides.pop("memory_kind", MemoryKind.GENERAL_NOTE)
    assert isinstance(kind, MemoryKind)
    fields: dict[str, object] = {
        "memory_version_id": VERSION,
        "memory_id": MEMORY,
        "principal_id": PRINCIPAL,
        "version_number": 1,
        "statement": statement,
        "statement_sha256": statement_digest(statement),
        "memory_kind": kind,
        "authority": MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
        "classification": classification_floor_for(kind),
        "created_by_actor": MemoryActorClass.USER,
        "recorded_at": WHEN,
        "idempotency_key": "synthetic-memory-0001",
        "correlation_id": CORRELATION,
    }
    return RelationshipMemoryVersion(**{**fields, **overrides})  # type: ignore[arg-type]


def a_proposal(**overrides: object) -> RelationshipMemoryProposal:
    """One valid proposal, with `overrides` applied."""
    statement = str(overrides.pop("proposed_statement", STATEMENT))
    fields: dict[str, object] = {
        "memory_proposal_id": PROPOSAL,
        "principal_id": PRINCIPAL,
        "subject_entity_id": SUBJECT,
        "proposed_kind": MemoryKind.GENERAL_NOTE,
        "proposed_statement": statement,
        "proposed_statement_sha256": statement_digest(statement),
        "state": MemoryProposalState.PROPOSED,
        "method": MemoryProposalMethod.DETERMINISTIC,
        "method_version": "v1",
        "classification": Classification.PRIVATE_LOCAL,
        "proposed_at": WHEN,
    }
    return RelationshipMemoryProposal(**{**fields, **overrides})  # type: ignore[arg-type]


# --- the closed vocabulary of meaning ----------------------------------------


@pytest.mark.parametrize("kind", sorted(MemoryKind, key=lambda member: member.value))
def test_every_semantic_kind_constructs_a_version(kind: MemoryKind) -> None:
    """All ten, not the three a happy path happens to use.

    A kind that could not construct at its own floor would be a member of the
    published vocabulary — the MCP schema names all ten — that no caller could
    ever write, which is a tool description that lies about what it accepts.
    """
    version = a_version(memory_kind=kind)
    assert version.memory_kind is kind
    assert version.classification is classification_floor_for(kind)


def test_the_kind_vocabulary_has_exactly_the_ten_members_the_schema_checks() -> None:
    """A widening without a forward migration would break the database CHECK."""
    assert len(MemoryKind) == 10


@pytest.mark.parametrize("kind", sorted(PERSON_ONLY_KINDS, key=lambda member: member.value))
@pytest.mark.parametrize(
    "entity_type",
    [member for member in EntityType if member is not EntityType.PERSON],
    ids=lambda member: member.value,
)
def test_a_person_only_kind_is_refused_for_a_subject_that_is_not_a_person(
    kind: MemoryKind, entity_type: EntityType
) -> None:
    """A birthday, a personal detail or an interest about an organization.

    Without this, `important_date` on a vendor row would be stored and later
    rendered as a person's birthday on a profile that has no person.
    """
    with pytest.raises(MemoryKindNotPermittedError):
        check_kind_permits_subject(kind, entity_type)


@pytest.mark.parametrize("kind", sorted(PERSON_ONLY_KINDS, key=lambda member: member.value))
def test_a_person_only_kind_is_permitted_for_a_person(kind: MemoryKind) -> None:
    """The other half, so the guard above is not passing by refusing everything."""
    check_kind_permits_subject(kind, EntityType.PERSON)


def test_sensitivity_is_deliberately_not_a_person_only_kind() -> None:
    """A caution about a topic, and a topic need not belong to a human being.

    If `SENSITIVITY` were Person-only, the same caution about a vendor would be
    pushed into `general_note`, which floors at `private_local` and therefore
    reaches a broad search — the exact downgrade the restricted floor exists to
    prevent. Asserted from both ends: absent from the set, and accepted for a
    subject that is not a Person.
    """
    assert MemoryKind.SENSITIVITY not in PERSON_ONLY_KINDS
    check_kind_permits_subject(MemoryKind.SENSITIVITY, EntityType.ORGANIZATION)


# --- partial dates, held rather than completed -------------------------------


def test_a_month_and_day_with_no_year_is_accepted() -> None:
    """A birthday given as a month and a day is the ordinary case, and it has no year."""
    envelope = validate_structured_value(
        MemoryKind.IMPORTANT_DATE,
        {"month": 4, "day": 17, "precision": "month_day"},
    )
    assert envelope is not None
    assert envelope["value"] == {"month": 4, "day": 17, "precision": "month_day"}


def test_a_year_on_a_month_day_precision_is_refused() -> None:
    """A record whose precision says the year is unknown while carrying one.

    A reader has no way to tell which half to believe, so the contradiction is
    refused rather than resolved by preferring one of them.
    """
    with pytest.raises(MemoryStructuredValueError):
        validate_structured_value(
            MemoryKind.IMPORTANT_DATE,
            {"month": 4, "day": 17, "year": 1980, "precision": "month_day"},
        )


def test_the_twenty_ninth_of_february_with_no_year_is_accepted() -> None:
    """A real birthday. There is no year to check it against, and refusing it
    would lose a date the user actually has."""
    envelope = validate_structured_value(
        MemoryKind.IMPORTANT_DATE,
        {"month": 2, "day": 29, "precision": "month_day"},
    )
    assert envelope is not None
    assert envelope["value"]["day"] == 29


def test_a_thirteenth_month_is_refused() -> None:
    """A transposed digit is refused at the edge rather than stored and rendered."""
    with pytest.raises(MemoryStructuredValueError):
        validate_structured_value(
            MemoryKind.IMPORTANT_DATE,
            {"month": 13, "day": 1, "precision": "month_day"},
        )


def test_the_thirty_first_of_april_is_refused() -> None:
    """The day bound is per month, not a flat thirty-one."""
    with pytest.raises(MemoryStructuredValueError):
        validate_structured_value(
            MemoryKind.IMPORTANT_DATE,
            {"month": 4, "day": 31, "precision": "month_day"},
        )


def test_a_date_with_no_year_gains_no_inferred_year() -> None:
    """The stored envelope holds exactly what the user supplied.

    A default year, a "current year", or a year copied from `recorded_at` would
    all turn "I do not know when they were born" into a claim about it — and the
    claim would then be rendered as though the user had made it.
    """
    envelope = validate_structured_value(
        MemoryKind.IMPORTANT_DATE,
        {"month": 4, "day": 17, "precision": "month_day"},
    )
    assert envelope is not None
    assert "year" not in envelope["value"]


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (
            MemoryKind.IMPORTANT_DATE,
            {"month": 4, "day": 17, "precision": "month_day", "age": 46},
        ),
        (
            MemoryKind.COMMUNICATION_PREFERENCE,
            {"channel": "teams", "preference": "preferred", "age": 46},
        ),
        (MemoryKind.INTEREST, {"label": "sailing", "age": 46}),
    ],
    ids=lambda value: value.value if isinstance(value, MemoryKind) else "value",
)
def test_no_schema_admits_an_age_field(kind: MemoryKind, value: dict[str, Any]) -> None:
    """An age is a derived claim about a person, and none of the three take one.

    Asserted against every kind that has a schema rather than against
    `important_date` alone: a derived-attribute field could be added to any of
    them, and a test that only watched the date schema would not notice.
    """
    with pytest.raises(MemoryStructuredValueError):
        validate_structured_value(kind, value)


# --- structured values are validated or refused, never stored unvalidated ----


@pytest.mark.parametrize(
    "kind",
    sorted(set(MemoryKind) - STRUCTURED_VALUE_KINDS, key=lambda member: member.value),
)
def test_a_kind_with_no_schema_refuses_a_structured_value(kind: MemoryKind) -> None:
    """Refusal is what "arbitrary JSON is prohibited" has to mean to be enforceable.

    Seven of the ten kinds are narrative. A value accepted for one of them would
    be stored against no schema and validated by nothing, ever again.
    """
    with pytest.raises(MemoryStructuredValueError):
        validate_structured_value(kind, {"whatever": "the caller sent"})


def test_an_arbitrary_key_is_refused_by_a_kind_that_does_have_a_schema() -> None:
    """A schema that ignored unknown keys would store them unvalidated."""
    with pytest.raises(MemoryStructuredValueError):
        validate_structured_value(MemoryKind.INTEREST, {"label": "sailing", "rating": 9})


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (MemoryKind.IMPORTANT_DATE, {"month": 4, "day": 17, "precision": "month_day"}),
        (MemoryKind.COMMUNICATION_PREFERENCE, {"channel": "teams", "preference": "preferred"}),
        (MemoryKind.INTEREST, {"label": "sailing"}),
    ],
    ids=lambda value: value.value if isinstance(value, MemoryKind) else "value",
)
def test_the_envelope_names_the_versioned_schema_the_value_was_checked_against(
    kind: MemoryKind, value: dict[str, Any]
) -> None:
    """A row written under `v1` is never reinterpreted under a later schema."""
    envelope = validate_structured_value(kind, value)
    assert envelope is not None
    assert envelope["schema"] == MEMORY_STRUCTURED_SCHEMAS[kind]
    assert envelope["schema"].endswith(".v1")
    assert set(envelope) == {"schema", "value"}


def test_no_structured_value_is_the_ordinary_case_and_stays_absent() -> None:
    """A memory whose whole meaning is its sentence carries no envelope."""
    assert validate_structured_value(MemoryKind.GENERAL_NOTE, None) is None


# --- classification: a floor, and only ever tightened ------------------------


def test_a_sensitivity_floors_at_restricted_local() -> None:
    assert classification_floor_for(MemoryKind.SENSITIVITY) is Classification.RESTRICTED_LOCAL


@pytest.mark.parametrize(
    "kind",
    sorted(set(MemoryKind) - {MemoryKind.SENSITIVITY}, key=lambda member: member.value),
)
def test_every_other_kind_floors_at_private_local(kind: MemoryKind) -> None:
    assert classification_floor_for(kind) is Classification.PRIVATE_LOCAL


def test_a_sensitivity_stored_at_private_local_is_refused() -> None:
    """The floor is enforced on the record, not only computed for it.

    A `sensitivity` at `private_local` would be selected by the broad search,
    which excludes `restricted_local` and nothing else — so this refusal is what
    keeps the search exclusion from being bypassable by writing the row at the
    wrong classification.
    """
    with pytest.raises(RelationshipMemoryError):
        a_version(
            memory_kind=MemoryKind.SENSITIVITY,
            classification=Classification.PRIVATE_LOCAL,
        )


def test_an_ordinary_note_may_be_recorded_more_restrictively() -> None:
    """A floor tightens monotonically; it is not an assignment."""
    version = a_version(
        memory_kind=MemoryKind.GENERAL_NOTE,
        classification=Classification.RESTRICTED_LOCAL,
    )
    assert version.classification is Classification.RESTRICTED_LOCAL


# --- the postures no writer on this path may take ----------------------------


def test_a_cloud_eligible_version_is_refused() -> None:
    """No path sets this true, and the refusal is what keeps that true.

    The column exists so the posture is auditable in the database rather than
    absent. Without this check, "defaults false" is a default a later writer can
    change without anyone deciding to.
    """
    with pytest.raises(RelationshipMemoryError):
        a_version(cloud_eligible=True)


@pytest.mark.parametrize(
    "authority",
    sorted(
        set(MemoryAuthority) - {MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE},
        key=lambda member: member.value,
    ),
)
def test_a_user_written_version_cannot_claim_a_non_user_authority(
    authority: MemoryAuthority,
) -> None:
    """A note the user typed is not a source-backed, confirmed or public finding.

    Without this, a direct write could self-assert `source_backed_assertion` and
    manufacture a finding out of a private note.
    """
    with pytest.raises(RelationshipMemoryError):
        a_version(created_by_actor=MemoryActorClass.USER, authority=authority)


def test_the_authority_vocabulary_names_no_model_inference_and_no_unresolved_claim() -> None:
    """The two absences are the decision, so they are asserted rather than assumed.

    A vocabulary that named either would give a promotion path a value to write,
    and a model-authored memory would then be a stored authority rather than a
    proposal a human has not decided yet.
    """
    values = {member.value for member in MemoryAuthority}
    assert "model_inference" not in values
    assert "unresolved_claim" not in values
    assert values == {
        "user_authored_private_note",
        "user_confirmed_assertion",
        "source_backed_assertion",
        "public_assertion",
    }


def test_the_lifecycle_vocabulary_names_no_deleted_state() -> None:
    """Withdrawal is `archived` and reversible. There is no member meaning gone."""
    assert {member.value for member in MemoryLifecycle} == {"active", "archived"}


# --- the digest identifies the bytes this product committed ------------------


def test_the_statement_digest_is_the_sha256_of_the_exact_utf8_statement() -> None:
    """No normalization, no trimming, no case folding.

    Any transformation between the text and the hash would make the stored
    digest a digest of something the user did not write, and the receipt would
    then acknowledge bytes that were never committed.
    """
    statement = "  Synthetic Subject prefers TEAMS.  "
    assert statement_digest(statement) == hashlib.sha256(statement.encode("utf-8")).hexdigest()
    assert statement_digest(statement) != statement_digest(statement.strip())
    assert statement_digest(statement) != statement_digest(statement.casefold())


def test_a_version_whose_digest_is_not_its_own_statements_is_refused() -> None:
    """Otherwise the two fields could disagree and nothing would ever notice."""
    with pytest.raises(RelationshipMemoryError):
        a_version(statement_sha256=statement_digest("a different synthetic note"))


# --- the note does not reach a traceback, a log, or an assertion message -----


def test_the_repr_of_a_version_does_not_contain_the_statement() -> None:
    """A dataclass `repr` reaches a traceback and a pytest failure message.

    This is the field carrying what the user wrote about another person, so its
    absence from the default rendering is a property of the record rather than
    of the code paths that happen to log today.
    """
    rendered = repr(a_version())
    assert STATEMENT not in rendered
    assert "qzvbnr-marker" not in rendered
    assert VERSION in rendered


def test_the_repr_of_a_proposal_does_not_contain_the_statement() -> None:
    """The same claim on the plane a model may actually write into."""
    rendered = repr(a_proposal())
    assert STATEMENT not in rendered
    assert "qzvbnr-marker" not in rendered
    assert PROPOSAL in rendered


# --- the aggregate holds no narrative ----------------------------------------


def test_the_aggregate_carries_no_statement_field() -> None:
    """Every listing would otherwise be a read of private note text.

    And the current statement would have two places to disagree with itself.
    """
    memory = RelationshipMemory(
        memory_id=MEMORY,
        principal_id=PRINCIPAL,
        subject_entity_id=SUBJECT,
        memory_kind=MemoryKind.GENERAL_NOTE,
        lifecycle_state=MemoryLifecycle.ACTIVE,
        current_version_id=VERSION,
        current_version_number=1,
        version=1,
        pinned=False,
        created_at=WHEN,
        updated_at=WHEN,
    )
    assert not hasattr(memory, "statement")
    assert STATEMENT not in repr(memory)


def test_only_the_first_version_supersedes_nothing() -> None:
    """A chain with a hole in it would make history unreadable in both directions."""
    with pytest.raises(RelationshipMemoryError):
        a_version(version_number=2, prior_version_id=None)
    with pytest.raises(RelationshipMemoryError):
        a_version(version_number=1, prior_version_id=PRIOR_VERSION)
    successor = a_version(version_number=2, prior_version_id=PRIOR_VERSION)
    assert successor.prior_version_id == PRIOR_VERSION
