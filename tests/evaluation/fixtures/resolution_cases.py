"""Frozen, labelled resolution cases over the collision-biased corpus.

Each case states what the resolver *should* answer, and the labels are the point
of the exercise: a metric computed against the resolver's own opinion measures
nothing.

**Both directions are labelled.** A corpus of cases that must resolve would
reward a reckless resolver; a corpus of cases that must not would reward one
that never answers. `MUST_RESOLVE_FAMILIES` and the recall floor in the harness
exist so neither degenerate strategy scores well.

`must_not_include` is the leakage label. It names entities that must never
appear as a candidate at all -- not merely never be chosen -- because a
candidate list is shown to a person, and offering the wrong Alice as a
possibility is a smaller failure than choosing her but it is the same failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from my_pa.domain.relationship.entity import EntityType, ExternalIdentifierNamespace
from my_pa.domain.relationship.resolution import ResolutionOutcome
from tests.evaluation.fixtures.resolution_corpus import (
    ACME,
    ALICE_CHEN_ENGINEER,
    ALICE_CHEN_LAWYER,
    BOB_CHEN_OTHER_PRINCIPAL,
    CHEN_PARTNERS,
    DEPARTED_CONTRACTOR,
    JOSE_ALVAREZ,
    PRINCIPAL_A,
    ROBERT_CHEN,
    ROBERTA_CHEN,
    SURVIVING_CONTRACTOR,
    TOWER_PROJECT,
    WHEN,
)

__all__ = ["MUST_RESOLVE_FAMILIES", "RESOLUTION_CASES", "ResolutionCase"]

#: A moment inside the first holder's tenure of the recycled mailbox.
EARLIER: Final = datetime(2024, 6, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ResolutionCase:
    """One labelled question and the answer the resolver owes it."""

    name: str
    family: str
    reference: str
    expected_outcome: ResolutionOutcome
    #: The entity a *resolved* answer must name. `None` means this case must not
    #: resolve at all -- which is an answer, not an absence of one.
    expected_entity_id: str | None = None
    principal_id: str = PRINCIPAL_A
    namespace: ExternalIdentifierNamespace | None = None
    entity_type: EntityType | None = None
    scope_entity_id: str | None = None
    as_of: datetime | None = None
    #: Entities that must appear among the candidates.
    must_include: frozenset[str] = frozenset()
    #: Entities that must never appear among the candidates.
    must_not_include: frozenset[str] = frozenset()
    note: str = ""

    def __post_init__(self) -> None:
        resolved = {
            ResolutionOutcome.RESOLVED_EXACT,
            ResolutionOutcome.RESOLVED_CONTEXTUAL,
        }
        if (self.expected_outcome in resolved) != (self.expected_entity_id is not None):
            raise ValueError(f"case {self.name} labels an outcome its entity does not match")
        overlap = self.must_include & self.must_not_include
        if overlap:
            raise ValueError(f"case {self.name} both requires and forbids {sorted(overlap)}")


#: The families in which a correct resolver *must* produce an answer. Named so
#: the harness can measure recall over exactly them, and so adding a
#: never-resolve family cannot quietly lower the bar.
MUST_RESOLVE_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "verified_identifier",
        "unverified_identifier",
        "effective_dated_identifier",
        "unique_alias",
        "diacritic_variant",
        "contextual_scope",
        "local_part_collision",
        "former_name",
    }
)


RESOLUTION_CASES: Final[tuple[ResolutionCase, ...]] = (
    # --- must resolve -------------------------------------------------------
    ResolutionCase(
        name="verified_address_names_one_person",
        family="verified_identifier",
        reference="a.chen@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=ALICE_CHEN_ENGINEER,
        must_not_include=frozenset({ALICE_CHEN_LAWYER, CHEN_PARTNERS}),
        note="An identifier separates two people a name cannot.",
    ),
    ResolutionCase(
        name="verified_address_is_case_insensitive",
        family="verified_identifier",
        reference="A.Chen@ACME.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=ALICE_CHEN_ENGINEER,
    ),
    ResolutionCase(
        name="unverified_address_still_resolves",
        family="unverified_identifier",
        reference="dana@northwind.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=SURVIVING_CONTRACTOR,
        note="Resolves, and the answer says the identifier was unverified.",
    ),
    ResolutionCase(
        name="recycled_mailbox_at_the_second_holders_moment",
        family="effective_dated_identifier",
        reference="r.chen@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        as_of=WHEN,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=ROBERTA_CHEN,
        must_not_include=frozenset({ROBERT_CHEN}),
        note="The mailbox was reissued. At this moment it is hers.",
    ),
    ResolutionCase(
        name="recycled_mailbox_at_the_first_holders_moment",
        family="effective_dated_identifier",
        reference="r.chen@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        as_of=EARLIER,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=ROBERT_CHEN,
        must_not_include=frozenset({ROBERTA_CHEN}),
        note="The same address, the same corpus, a different moment, a different person.",
    ),
    ResolutionCase(
        name="a_unique_alias_resolves",
        family="unique_alias",
        reference="Dana O",
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=SURVIVING_CONTRACTOR,
        note="An alias is a recorded fact, so it may resolve where a bare name may not.",
    ),
    ResolutionCase(
        name="a_diacritic_variant_reaches_the_same_person",
        family="diacritic_variant",
        reference="Jose Alvarez",
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=JOSE_ALVAREZ,
        note="Two sources spell one person differently; that is not two people.",
    ),
    ResolutionCase(
        name="the_accented_spelling_reaches_the_same_person",
        family="diacritic_variant",
        reference="José Álvarez",
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=JOSE_ALVAREZ,
    ),
    ResolutionCase(
        name="a_scope_separates_two_people_with_one_name",
        family="contextual_scope",
        reference="Alice Chen",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
        expected_entity_id=ALICE_CHEN_ENGINEER,
        must_not_include=frozenset({ALICE_CHEN_LAWYER}),
        note="Only one of them is on the project, and that is a recorded fact about her.",
    ),
    ResolutionCase(
        name="a_local_part_shared_across_domains_is_not_one_person",
        family="local_part_collision",
        reference="j.alvarez@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=JOSE_ALVAREZ,
        must_not_include=frozenset({ALICE_CHEN_LAWYER}),
        note="The lawyer holds j.alvarez@northwind.test. A local-part match would join them.",
    ),
    ResolutionCase(
        name="a_unique_full_name_alias_resolves",
        family="unique_alias",
        reference="Harbour Tower",
        entity_type=EntityType.PROJECT,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=TOWER_PROJECT,
        note="Resolves on the recorded FULL_NAME alias, not on the bare canonical name.",
    ),
    ResolutionCase(
        name="a_former_name_is_the_same_person",
        family="former_name",
        reference="Alice Nakamura",
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=ALICE_CHEN_ENGINEER,
        note=(
            "The case that catches a merely timid resolver: refusing this one "
            "is as wrong as joining the two Alices."
        ),
    ),
    # --- must not resolve ---------------------------------------------------
    ResolutionCase(
        name="two_people_with_one_name_stay_two",
        family="same_name",
        reference="Alice Chen",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ALICE_CHEN_ENGINEER, ALICE_CHEN_LAWYER}),
        note="The plainest false join available, and the plainest refusal.",
    ),
    ResolutionCase(
        name="a_lone_canonical_name_match_does_not_resolve",
        family="lone_name",
        reference="Acme Construction",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ACME}),
        note=(
            "Exactly one entity carries this name and nothing else matches it, "
            "and that is still not evidence the reference means it. Acme holds "
            "no alias, so the only evidence is the canonical name."
        ),
    ),
    ResolutionCase(
        name="an_organization_named_for_a_person_is_not_that_person",
        family="type_collision",
        reference="Alice Chen",
        entity_type=EntityType.ORGANIZATION,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({CHEN_PARTNERS}),
        must_not_include=frozenset({ALICE_CHEN_ENGINEER, ALICE_CHEN_LAWYER}),
        note="Type filtering removes the people; the org is still only a name match.",
    ),
    ResolutionCase(
        name="a_nickname_two_siblings_answer_to_resolves_to_neither",
        family="shared_nickname",
        reference="Rob",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ROBERT_CHEN, ROBERTA_CHEN}),
        note="An alias resolves only when it is unique. This one is not.",
    ),
    ResolutionCase(
        name="initials_two_siblings_reduce_to_resolve_to_neither",
        family="shared_initials",
        reference="R Chen",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ROBERT_CHEN, ROBERTA_CHEN}),
    ),
    ResolutionCase(
        name="a_scope_true_of_both_siblings_separates_neither",
        family="undiscriminating_scope",
        reference="Rob",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ROBERT_CHEN, ROBERTA_CHEN}),
        note="Both are on the tower. Context that fits everyone has chosen no one.",
    ),
    ResolutionCase(
        name="an_organization_scope_true_of_both_siblings_separates_neither",
        family="undiscriminating_scope",
        reference="Rob",
        scope_entity_id=ACME,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ROBERT_CHEN, ROBERTA_CHEN}),
        note="Both work for Acme, by a typed relationship rather than an assignment.",
    ),
    ResolutionCase(
        name="one_address_on_two_entities_is_a_stop",
        family="conflicted_identifier",
        reference="shared.inbox@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
        must_include=frozenset({ALICE_CHEN_ENGINEER, ROBERT_CHEN, CHEN_PARTNERS}),
        note="A data defect. Choosing any would perform the merge section 15.2 refuses.",
    ),
    ResolutionCase(
        name="a_type_filter_does_not_resolve_a_conflicted_identifier",
        family="conflicted_identifier",
        reference="shared.inbox@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        entity_type=EntityType.ORGANIZATION,
        expected_outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
        must_include=frozenset({CHEN_PARTNERS}),
        note=(
            "The regression case. Exactly one organization claims this address, "
            "so a resolver that filtered by type before counting claimants would "
            "answer resolved_exact here — confidently, and differently for a "
            "caller who asked for a person."
        ),
    ),
    ResolutionCase(
        name="a_recycled_mailbox_without_a_moment_is_a_stop",
        family="conflicted_identifier",
        reference="r.chen@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
        must_include=frozenset({ROBERT_CHEN, ROBERTA_CHEN}),
        note="Both records are true; without a moment, neither is the answer.",
    ),
    ResolutionCase(
        name="a_merged_away_entity_answers_historically",
        family="historical",
        reference="Danny Okonkwo",
        expected_outcome=ResolutionOutcome.HISTORICAL_MATCH,
        must_include=frozenset({DEPARTED_CONTRACTOR}),
        note="Found, and not current. The caller is told which.",
    ),
    ResolutionCase(
        name="nothing_matching_is_not_found",
        family="absent",
        reference="Nobody Whatsoever",
        expected_outcome=ResolutionOutcome.NOT_FOUND,
    ),
    # --- cross-Principal leakage -------------------------------------------
    ResolutionCase(
        name="another_principals_person_is_invisible_by_name",
        family="cross_principal",
        reference="Bob Chen",
        expected_outcome=ResolutionOutcome.NOT_FOUND,
        must_not_include=frozenset({BOB_CHEN_OTHER_PRINCIPAL}),
    ),
    ResolutionCase(
        name="another_principals_person_is_invisible_by_alias",
        family="cross_principal",
        reference="Bobby",
        expected_outcome=ResolutionOutcome.NOT_FOUND,
        must_not_include=frozenset({BOB_CHEN_OTHER_PRINCIPAL}),
    ),
    ResolutionCase(
        name="another_principals_person_is_invisible_by_address",
        family="cross_principal",
        reference="b.chen@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.NOT_FOUND,
        must_not_include=frozenset({BOB_CHEN_OTHER_PRINCIPAL}),
    ),
)
