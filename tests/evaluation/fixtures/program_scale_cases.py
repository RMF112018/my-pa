"""Labelled resolution cases over the program-scale corpus (`RI-AC-032`).

Every case states what the resolver *should* answer, and the label is derived
from the fixture's own construction rather than from a run: a metric computed
against the resolver's own opinion measures nothing, and a label copied out of a
failing run measures less than nothing.

**Both directions are labelled, in bulk.** Five hundred and forty cases must
resolve and four hundred and twenty-five must not. A corpus of only the first
kind rewards a reckless resolver; a corpus of only the second rewards one that
never answers. The acceptance record floors recall over `MUST_RESOLVE_FAMILIES`
*and* requires zero false resolutions, so neither degenerate strategy scores.

**The acceptance bias is stated here rather than implied.** WP-RI-12 says the
bias favours no false join over resolution coverage, so `false_resolution_count`
is the release-blocking number and coverage is the number that keeps the
refusals honest. Where the two conflict, this file labels the refusal.

`must_not_include` is the leakage label, and it carries the cross-Principal
claim: a candidate list is shown to a person, and offering another Principal's
person as a *possibility* is the same failure as choosing them.

Case identifiers are stable across runs because the corpus is. A reviewer who
wants to know why a particular case exists can read its family and its `note`;
the families are the unit the record reports.
"""

from __future__ import annotations

from typing import Final

from my_pa.domain.relationship.entity import EntityType, ExternalIdentifierNamespace
from my_pa.domain.relationship.resolution import ResolutionOutcome
from tests.evaluation.fixtures.program_scale_corpus import (
    EARLY,
    LATE,
    PRINCIPAL_A,
    PRINCIPAL_B,
    PROGRAM_SCALE_CORPUS,
    absent_name,
)
from tests.evaluation.fixtures.resolution_cases import ResolutionCase

__all__ = [
    "CONTEXTUAL_FAMILIES",
    "MUST_RESOLVE_FAMILIES",
    "PROGRAM_SCALE_CASES",
]

#: How many verified primary mailboxes are asked about. Not all five hundred:
#: the case set is a *sample* whose size is stated, because a benchmark that
#: asks every possible question of one family and none of another reports a
#: precision figure dominated by whichever family happened to be exhaustive.
VERIFIED_IDENTIFIER_CASES: Final = 120
UNIQUE_ALIAS_CASES: Final = 120
ORGANIZATION_IDENTIFIER_CASES: Final = 30
LONE_NAME_CASES: Final = 40
ABSENT_CASES: Final = 40
CROSS_PRINCIPAL_NAME_CASES: Final = 25

#: An address with more claimants than this spans two entity types in the
#: fixture, which is the shape the type-filter regression case is built from.
_TWO_CLAIMANTS: Final = 2

#: The families in which a correct resolver *must* produce an answer. Named so
#: the harness measures recall over exactly them, and so adding a never-resolve
#: family cannot quietly lower the bar.
MUST_RESOLVE_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "verified_identifier",
        "unverified_identifier",
        "vendor_identifier",
        "organization_identifier",
        "unique_document_alias",
        "former_name",
        "effective_dated_identifier",
        "contextual_project_scope",
        "contextual_organization_scope",
        "cross_principal_identifier",
    }
)

#: The families whose answer must come from the surrounding context rather than
#: from the reference. `contextual_coverage` is measured over exactly these, and
#: they are the only families where a bare canonical name is allowed to end in a
#: resolution at all.
CONTEXTUAL_FAMILIES: Final[frozenset[str]] = frozenset(
    {"contextual_project_scope", "contextual_organization_scope"}
)


def _build() -> tuple[ResolutionCase, ...]:
    """Derive every labelled case from the corpus's recorded structure."""
    corpus = PROGRAM_SCALE_CORPUS
    cases: list[ResolutionCase] = []

    # --- identifiers that name exactly one entity ---------------------------

    for person in corpus.persons[:VERIFIED_IDENTIFIER_CASES]:
        cases.append(
            ResolutionCase(
                name=f"verified_address_names_{person.entity_id}",
                family="verified_identifier",
                reference=person.primary_address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=person.entity_id,
                note="A verified mailbox separates people a shared name cannot.",
            )
        )

    for entity_id, address in corpus.unverified_addresses:
        cases.append(
            ResolutionCase(
                name=f"unverified_address_still_names_{entity_id}",
                family="unverified_identifier",
                reference=address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=entity_id,
                note="Resolves, and the answer discloses that the identifier is unverified.",
            )
        )

    for entity_id, value in corpus.vendor_identifiers[:VERIFIED_IDENTIFIER_CASES]:
        cases.append(
            ResolutionCase(
                name=f"vendor_identifier_names_{entity_id}",
                family="vendor_identifier",
                reference=value,
                namespace=ExternalIdentifierNamespace.VENDOR_SYSTEM_ID,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=entity_id,
                note="A namespace whose values are opaque and case-sensitive.",
            )
        )

    for entity_id, address in corpus.organization_addresses[:ORGANIZATION_IDENTIFIER_CASES]:
        cases.append(
            ResolutionCase(
                name=f"organization_address_names_{entity_id}",
                family="organization_identifier",
                reference=address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=entity_id,
                note="An organization is an entity too, and resolves on the same terms.",
            )
        )

    # --- aliases: the recorded name forms ------------------------------------

    for entity_id, display in corpus.document_reference_aliases[:UNIQUE_ALIAS_CASES]:
        cases.append(
            ResolutionCase(
                name=f"unique_document_reference_names_{entity_id}",
                family="unique_document_alias",
                reference=display,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=entity_id,
                note="An alias is a recorded fact, so it may resolve where a bare name may not.",
            )
        )

    for entity_id, display in corpus.former_name_aliases:
        cases.append(
            ResolutionCase(
                name=f"former_name_is_still_{entity_id}",
                family="former_name",
                reference=display,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=entity_id,
                note=(
                    "The family that catches a merely timid resolver: refusing this is "
                    "as wrong as joining two people who share a name."
                ),
            )
        )

    # --- temporal truth ------------------------------------------------------

    for mailbox in corpus.recycled_mailboxes:
        cases.append(
            ResolutionCase(
                name=f"recycled_mailbox_at_the_first_moment_{mailbox.first_holder_id}",
                family="effective_dated_identifier",
                reference=mailbox.address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                as_of=EARLY,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=mailbox.first_holder_id,
                must_not_include=frozenset({mailbox.second_holder_id}),
                note="The same address, the same corpus, a different moment, a different person.",
            )
        )
        cases.append(
            ResolutionCase(
                name=f"recycled_mailbox_at_the_second_moment_{mailbox.second_holder_id}",
                family="effective_dated_identifier",
                reference=mailbox.address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                as_of=LATE,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=mailbox.second_holder_id,
                must_not_include=frozenset({mailbox.first_holder_id}),
                note="The mailbox was reissued. At this moment it is theirs.",
            )
        )
        cases.append(
            ResolutionCase(
                name=f"recycled_mailbox_without_a_moment_{mailbox.address}",
                family="recycled_without_moment",
                reference=mailbox.address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
                must_include=frozenset({mailbox.first_holder_id, mailbox.second_holder_id}),
                note="Both records are true; without a moment, neither is the answer.",
            )
        )

    # --- context that does and does not decide -------------------------------

    for group in corpus.collision_groups:
        cases.append(
            ResolutionCase(
                name=f"same_name_stays_several_{group.member_ids[0]}",
                family="same_name",
                reference=group.display_name,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.AMBIGUOUS,
                must_include=frozenset(group.member_ids),
                note="The plainest false join available, and the plainest refusal.",
            )
        )
        if group.discriminating_project_id is not None:
            assert group.discriminating_member_id is not None
            assert group.discriminating_organization_id is not None
            excluded = frozenset(set(group.member_ids) - {group.discriminating_member_id})
            cases.append(
                ResolutionCase(
                    name=f"a_project_scope_separates_{group.discriminating_member_id}",
                    family="contextual_project_scope",
                    reference=group.display_name,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=group.discriminating_project_id,
                    expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
                    expected_entity_id=group.discriminating_member_id,
                    must_not_include=excluded,
                    note="Only one of them is assigned to this project, and that is recorded.",
                )
            )
            cases.append(
                ResolutionCase(
                    name=f"an_employer_scope_separates_{group.discriminating_member_id}",
                    family="contextual_organization_scope",
                    reference=group.display_name,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=group.discriminating_organization_id,
                    expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
                    expected_entity_id=group.discriminating_member_id,
                    must_not_include=excluded,
                    note=(
                        "The same separation reached through a typed relationship and an "
                        "employment assignment rather than a project assignment."
                    ),
                )
            )
        else:
            assert group.shared_project_id is not None
            cases.append(
                ResolutionCase(
                    name=f"a_scope_true_of_everyone_separates_nobody_{group.member_ids[0]}",
                    family="undiscriminating_project_scope",
                    reference=group.display_name,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=group.shared_project_id,
                    expected_outcome=ResolutionOutcome.AMBIGUOUS,
                    must_include=frozenset(group.member_ids),
                    note="Context that fits everyone has chosen no one.",
                )
            )

    for entity_id, project_id in corpus.stale_assignment_scopes:
        cases.append(
            ResolutionCase(
                name=f"an_assignment_that_expired_does_not_resolve_{entity_id}",
                family="stale_assignment_scope",
                reference=_display_name_of(entity_id),
                principal_id=PRINCIPAL_A,
                scope_entity_id=project_id,
                expected_outcome=ResolutionOutcome.AMBIGUOUS,
                must_include=frozenset({entity_id}),
                note=(
                    "The row still says active and its dates say it ended. Corroborating "
                    "on it would claim the person *is* on the project."
                ),
            )
        )

    for entity_id, project_id in corpus.stale_relationship_scopes:
        cases.append(
            ResolutionCase(
                name=f"an_edge_that_ended_does_not_resolve_{entity_id}",
                family="stale_relationship_scope",
                reference=_display_name_of(entity_id),
                principal_id=PRINCIPAL_A,
                scope_entity_id=project_id,
                expected_outcome=ResolutionOutcome.AMBIGUOUS,
                must_include=frozenset({entity_id}),
                note=(
                    "The same refusal written to the other table. An ended edge must not "
                    "corroborate more strongly than an ended assignment."
                ),
            )
        )

    # --- names that are only names -------------------------------------------

    for nickname, members in corpus.shared_nickname_groups:
        cases.append(
            ResolutionCase(
                name=f"a_shared_nickname_resolves_to_nobody_{members[0]}",
                family="shared_nickname",
                reference=nickname,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.AMBIGUOUS,
                must_include=frozenset(members),
                note="An alias resolves only when it is unique. This one is not.",
            )
        )

    for given, members in corpus.first_name_groups:
        cases.append(
            ResolutionCase(
                name=f"a_bare_first_name_resolves_to_nobody_{members[0]}",
                family="shared_first_name",
                reference=given,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.AMBIGUOUS,
                must_include=frozenset(members),
                note="`RI-AC-004`: a first-name-only reference is ambiguous, not a guess.",
            )
        )

    for entity_id in corpus.lone_name_person_ids[:LONE_NAME_CASES]:
        cases.append(
            ResolutionCase(
                name=f"a_lone_canonical_name_does_not_resolve_{entity_id}",
                family="lone_canonical_name",
                reference=_display_name_of(entity_id),
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.AMBIGUOUS,
                must_include=frozenset({entity_id}),
                note=(
                    "Exactly one entity carries this name and that is still not evidence "
                    "the reference means it. Uniqueness is a fact about the database."
                ),
            )
        )

    # --- conflicts, redirects, and absence -----------------------------------

    for conflict in corpus.conflicted_addresses:
        cases.append(
            ResolutionCase(
                name=f"one_address_on_several_entities_is_a_stop_{conflict.address}",
                family="conflicted_identifier",
                reference=conflict.address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
                must_include=frozenset(conflict.claimant_ids),
                note="A data defect. Choosing any claimant would perform a merge.",
            )
        )
        if len(conflict.claimant_ids) > _TWO_CLAIMANTS:
            cases.append(
                ResolutionCase(
                    name=f"a_type_filter_does_not_unconflict_{conflict.address}",
                    family="conflicted_identifier",
                    reference=conflict.address,
                    namespace=ExternalIdentifierNamespace.EMAIL,
                    entity_type=EntityType.ORGANIZATION,
                    principal_id=PRINCIPAL_A,
                    expected_outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
                    note=(
                        "Exactly one organization claims this address, so a resolver that "
                        "filtered by type before counting claimants would answer exactly "
                        "here — and differently for a caller who asked for a person."
                    ),
                )
            )

    for redirect in corpus.merged_redirects:
        cases.append(
            ResolutionCase(
                name=f"a_merged_entity_answers_historically_{redirect.merged_entity_id}",
                family="historical_merge_redirect",
                reference=redirect.alias_display_value,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.HISTORICAL_MATCH,
                must_include=frozenset({redirect.merged_entity_id}),
                note="Found, and not current. The caller is told which, and where it went.",
            )
        )

    for redirect in corpus.merged_redirects[: LONE_NAME_CASES // 2]:
        cases.append(
            ResolutionCase(
                name=f"a_merged_entitys_bare_name_does_not_resolve_{redirect.merged_entity_id}",
                family="merged_bare_name",
                reference=redirect.display_name,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.AMBIGUOUS,
                must_include=frozenset({redirect.merged_entity_id}),
                note=(
                    "The weaker question about the same row. A redirect is reachable by "
                    "the alias somebody recorded, not by a name nobody did."
                ),
            )
        )

    for offset in range(ABSENT_CASES):
        cases.append(
            ResolutionCase(
                name=f"nothing_matching_is_not_found_{offset:02d}",
                family="absent",
                reference=absent_name(offset),
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.NOT_FOUND,
                note="Drawn from the name band no entity was built from.",
            )
        )

    # --- the partition -------------------------------------------------------

    for offset in range(CROSS_PRINCIPAL_NAME_CASES):
        other_id = corpus.other_principal_person_ids[offset]
        cases.append(
            ResolutionCase(
                name=f"another_principals_person_is_invisible_by_name_{other_id}",
                family="cross_principal_name",
                reference=corpus.other_principal_names[offset],
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.NOT_FOUND,
                must_not_include=frozenset({other_id}),
                note="Answered as absent rather than as filtered out.",
            )
        )
        mine = corpus.lone_name_person_ids[offset]
        cases.append(
            ResolutionCase(
                name=f"the_first_principals_person_is_invisible_to_the_second_{mine}",
                family="cross_principal_name",
                reference=_display_name_of(mine),
                principal_id=PRINCIPAL_B,
                expected_outcome=ResolutionOutcome.NOT_FOUND,
                must_not_include=frozenset({mine}),
                note="The same claim asserted in the other direction.",
            )
        )

    for address, mine, theirs in corpus.shared_addresses:
        cases.append(
            ResolutionCase(
                name=f"a_shared_mailbox_string_names_only_my_person_{mine}",
                family="cross_principal_identifier",
                reference=address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_A,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=mine,
                must_not_include=frozenset({theirs}),
                note=(
                    "Two records in two partitions, not a conflict. A partition predicate "
                    "left out of one WHERE clause turns this into a stop for both."
                ),
            )
        )
        cases.append(
            ResolutionCase(
                name=f"a_shared_mailbox_string_names_only_their_person_{theirs}",
                family="cross_principal_identifier",
                reference=address,
                namespace=ExternalIdentifierNamespace.EMAIL,
                principal_id=PRINCIPAL_B,
                expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
                expected_entity_id=theirs,
                must_not_include=frozenset({mine}),
                note="The same address, the other partition, the other person.",
            )
        )

    return tuple(cases)


_DISPLAY_NAMES: Final[dict[str, str]] = {
    person.entity_id: person.display_name for person in PROGRAM_SCALE_CORPUS.persons
}


def _display_name_of(entity_id: str) -> str:
    """The display name of one generated person, by identifier."""
    return _DISPLAY_NAMES[entity_id]


PROGRAM_SCALE_CASES: Final[tuple[ResolutionCase, ...]] = _build()
