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
    HALVARD_BRAND,
    HALVARD_HOLDINGS,
    HALVARD_STUDIO,
    IRIS_BELL_CANCELLED,
    IRIS_BELL_OTHER,
    JOSE_ALVAREZ,
    LEO_MARCHETTI,
    MAYA_OSEI,
    MERIDEL_LEGAL,
    NADIA_OKONKWO_INCOMING,
    NADIA_OKONKWO_OTHER,
    NORTHWIND,
    OMAR_DIALLO_ENDED,
    OMAR_DIALLO_OTHER,
    PRINCIPAL_A,
    PRIYA_RAO,
    ROBERT_CHEN,
    ROBERTA_CHEN,
    SURVIVING_CONTRACTOR,
    TOMAS_HALL_CURRENT,
    TOMAS_HALL_OTHER,
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
    #: The moment the question is asked, defaulted to the corpus clock so every
    #: case is answered the way the capability answers one. A case that wants the
    #: no-moment fallback sets it to `None` explicitly and says why.
    at: datetime | None = WHEN
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
        # The two corroboration families `RI-ENT-WP-09` put on the resolution
        # path. Each is a *must-resolve* family rather than a refusal one on
        # purpose: an affiliation and a participation are the two signals the
        # work package added, and a corpus that only ever asked them to refuse
        # would score identically against a resolver that never read them.
        "affiliated_scope",
        "participating_scope",
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
        name="a_scope_resolves_a_lone_name_nobody_shares",
        family="contextual_scope",
        reference="Maya Osei",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
        expected_entity_id=MAYA_OSEI,
        note=(
            "Corroboration resolving without a rival to exclude. The corpus's other "
            "contextual case has one, so this path -- where the caller's own scope is "
            "the whole difference between a refusal and a confident answer -- was "
            "unmeasured, and so was every rule about whether the tie is still current."
        ),
    ),
    ResolutionCase(
        name="a_tie_that_has_since_ended_still_resolves_at_a_moment_it_covered",
        family="contextual_scope",
        reference="Priya Rao",
        scope_entity_id=TOWER_PROJECT,
        as_of=EARLIER,
        expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
        expected_entity_id=PRIYA_RAO,
        note=(
            "A caller who names a moment gets that moment's answer. Refusing here would "
            "be the other failure: a currency rule strict enough to answer nothing."
        ),
    ),
    ResolutionCase(
        name="a_tie_cancelled_by_its_status_does_not_resolve_a_shared_name",
        family="signal_currency",
        reference="Iris Bell",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({IRIS_BELL_CANCELLED, IRIS_BELL_OTHER}),
        note=(
            "Her assignment's window is open and began in the past, so every date rule "
            "admits it; only `status` says it is over. The corpus's other stale assignment "
            "is expired *and* active, so the date rule excluded it first and the status "
            "flag could be deleted with this gate green — a corpus hostile on one axis "
            "and blind on the other."
        ),
    ),
    ResolutionCase(
        name="an_edge_ended_by_its_state_does_not_resolve_a_shared_name",
        family="signal_currency",
        reference="Omar Diallo",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({OMAR_DIALLO_ENDED, OMAR_DIALLO_OTHER}),
        note=(
            "The edge equivalent, and the pair of the case above. Leo's ended edge carries "
            "expired dates too, so it never reached the state filter; this one is in force "
            "by every date and ended only by its state."
        ),
    ),
    ResolutionCase(
        name="a_tie_that_has_not_begun_does_not_resolve_a_shared_name",
        family="signal_currency",
        reference="Nadia Okonkwo",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({NADIA_OKONKWO_INCOMING, NADIA_OKONKWO_OTHER}),
        note=(
            "Her assignment starts in 2030 and nobody has ended it. The rule that read "
            "currency off 'nobody wrote an end date' called that in force, so a person "
            "was named as being somewhere she has not arrived. Both Nadias stay on the "
            "answer, which is what refusing looks like here."
        ),
    ),
    ResolutionCase(
        name="a_tie_running_to_a_future_end_date_still_resolves",
        family="signal_currency",
        reference="Tomas Hall",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
        expected_entity_id=TOMAS_HALL_CURRENT,
        must_not_include=frozenset({TOMAS_HALL_OTHER}),
        note=(
            "The pair of the case above, and the half that made the old rule wrong for "
            "ordinary data: a contract with a recorded end date in 2030 is live now. A "
            "currency rule that refuses this refuses every dated employment, which is a "
            "resolver that answers nothing and passes for safe."
        ),
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
    ResolutionCase(
        name="a_typed_name_beside_an_alias_still_resolves_on_the_alias",
        family="former_name",
        reference="Alice Nakamura",
        entity_type=EntityType.PERSON,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=ALICE_CHEN_ENGINEER,
        must_not_include=frozenset({ALICE_CHEN_LAWYER, CHEN_PARTNERS}),
        note=(
            "The regression guard on `_BASIS_ORDER`. Her married name is recorded twice "
            "-- as a `FORMER_NAME` alias and again as a `HISTORICAL_NAME` typed name on "
            "the same entity -- so this reference is the corpus's one candidate carrying "
            "both an old basis and a new one. `TYPED_NAME` was appended below `ALIAS`, so "
            "`strongest_basis` is still `ALIAS` and this answer is bit-identical to the "
            "one it gave before resolution read `entity_names` at all. An insertion above "
            "`ALIAS` would move it, and nothing else in the corpus would notice. The "
            "`entity_type` filter is here too, because `_admits` inside the typed-name "
            "read had no case exercising it."
        ),
    ),
    ResolutionCase(
        name="an_identifier_that_matches_never_reaches_the_channel_plane",
        family="verified_identifier",
        reference="a.chen@acme.test",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.RESOLVED_EXACT,
        expected_entity_id=ALICE_CHEN_ENGINEER,
        must_not_include=frozenset({ROBERTA_CHEN}),
        note=(
            "The regression guard on the most delicate edit in this work package. This "
            "address is an `entity_external_identifiers` row of the engineer's *and* an "
            "active `entity_communication_methods` row of Roberta's, because a mail "
            "connector copied it onto the wrong contact card. The communication read is "
            "reached only where no identifier row matched at all; one did, so Roberta can "
            "never be offered here. Widen that fall-through and she appears beside the "
            "engineer, and an exact resolution becomes an ambiguous one."
        ),
    ),
    ResolutionCase(
        name="an_affiliation_naming_the_scope_resolves_a_lone_name",
        family="affiliated_scope",
        reference="Leo Marchetti",
        scope_entity_id=NORTHWIND,
        expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
        expected_entity_id=LEO_MARCHETTI,
        note=(
            "`AFFILIATED_WITH_THE_NAMED_SCOPE`, and the whole reason this case exists: "
            "until it, no case supplied a scope any affiliation row's "
            "`organization_entity_id` was equal to, so the signal was computed on every "
            "contextual case and fired on none. Leo's corrected employer is Northwind, "
            "open-ended and active; his Acme row names a different organization and his "
            "project rows name a different scope, so an affiliation is the only thing "
            "lifting a bare canonical name here."
        ),
    ),
    ResolutionCase(
        name="a_participation_separates_two_juristic_entities_sharing_a_name",
        family="participating_scope",
        reference="Halvard Studio",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
        expected_entity_id=HALVARD_STUDIO,
        must_not_include=frozenset({HALVARD_HOLDINGS, MERIDEL_LEGAL, HALVARD_BRAND}),
        note=(
            "`PARTICIPATES_IN_THE_NAMED_SCOPE`, isolated: the operating studio carries no "
            "assignment, no edge and no affiliation, so a project participation is the "
            "only signal available. It is also the constructive half of audit section M's "
            "rule -- the family must not be collapsed, and it must not be left "
            "permanently unresolvable either. Exactly one of the four is on this project, "
            "and a caller who names it gets that one. The answer rests on `TYPED_NAME`, "
            "which is why it is `RESOLVED_CONTEXTUAL` and can never be `RESOLVED_EXACT`."
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
        name="a_relationship_to_the_scope_that_has_ended_does_not_resolve",
        family="stale_scope",
        reference="Leo Marchetti",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({LEO_MARCHETTI}),
        note=(
            "Leo is the only Leo, and his one tie to the project is recorded as over. "
            "This used to answer RESOLVED_CONTEXTUAL naming him, with no warning: an "
            "ended assignment stopped corroborating and an ended relationship did not, "
            "so the answer depended on which table the fact had been written to."
        ),
    ),
    ResolutionCase(
        name="an_assignment_to_the_scope_that_expired_does_not_resolve",
        family="stale_scope",
        reference="Priya Rao",
        scope_entity_id=TOWER_PROJECT,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({PRIYA_RAO}),
        note=(
            "The same refusal reached the other way. Priya's row still says active and "
            "its dates say it ended, and the request names no moment -- the default. "
            "Not filtering by time without an `as_of` is right for the evidence the "
            "reference matched and wrong for a signal, which claims she *is* on it."
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
    ResolutionCase(
        name="a_typed_legal_name_alone_does_not_resolve",
        family="typed_name_alone",
        reference="Acme Construction Group, LLC",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ACME}),
        note=(
            "The typed-name half of `a_lone_canonical_name_match_does_not_resolve`. "
            "Exactly one entity carries this registered name, no other row matches it, "
            "and it is still not evidence that the reference means it -- a name is a "
            "name whichever table it was written to. `TYPED_NAME` is absent from "
            "`_BASES_THAT_NAME_AN_ENTITY` precisely so this answers `AMBIGUOUS`, and "
            "Acme is named among the candidates because a retrieval candidate is exactly "
            "what audit section M allows a name to produce."
        ),
    ),
    ResolutionCase(
        name="an_operating_name_two_juristic_entities_share_is_ambiguous",
        family="juristic_family",
        reference="Halvard Studio",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({HALVARD_STUDIO, HALVARD_HOLDINGS}),
        must_not_include=frozenset({MERIDEL_LEGAL, HALVARD_BRAND}),
        note=(
            "Audit section M's rule, measured on the fast tier: four similarly-named "
            "organizations 'must not silently mint four unrelated organizations or "
            "automatically collapse distinct juristic entities solely because names "
            "resemble each other'. The operating company and its holding company both "
            "trade under this name, which is what a corporate family is and not a data "
            "defect. Both are offered, neither is chosen, and the two that do not claim "
            "this name are not swept in with them."
        ),
    ),
    ResolutionCase(
        name="a_brand_two_juristic_entities_share_is_ambiguous",
        family="juristic_family",
        reference="Halvard Four",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({MERIDEL_LEGAL, HALVARD_BRAND}),
        must_not_include=frozenset({HALVARD_STUDIO, HALVARD_HOLDINGS}),
        note=(
            "The same refusal on the brand axis, and the case that proves a typed name "
            "reaches an entity no canonical name could: `MERIDEL_LEGAL` is canonically "
            "'meridel design works' and shares not one token with the brand it signs "
            "under. Reading `entity_names` is what finds it; refusing to choose between "
            "it and the brand-holding company is what keeps that reach safe."
        ),
    ),
    ResolutionCase(
        name="a_legal_name_naming_one_juristic_entity_offers_no_other",
        family="juristic_family",
        reference="Halvard Studio Holdings, LLC",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({HALVARD_HOLDINGS}),
        must_not_include=frozenset({HALVARD_STUDIO, MERIDEL_LEGAL, HALVARD_BRAND}),
        note=(
            "The other half of the same rule, and the half a timid resolver fails. A "
            "reference naming one specific juristic person must not hand back its three "
            "lookalikes as though the family were interchangeable -- 'must not silently "
            "mint four unrelated organizations' and 'must not collapse them' are one "
            "requirement read from two sides. The answer is still `AMBIGUOUS`, because "
            "a legal name is a name."
        ),
    ),
    ResolutionCase(
        name="a_type_filter_removes_every_juristic_entity_sharing_a_name",
        family="type_collision",
        reference="Halvard Studio",
        entity_type=EntityType.PERSON,
        expected_outcome=ResolutionOutcome.NOT_FOUND,
        must_not_include=frozenset({HALVARD_STUDIO, HALVARD_HOLDINGS}),
        note=(
            "`_admits` applied inside the typed-name read rather than after it. A caller "
            "asking for a person is not offered an organization whose operating name "
            "happens to be spelled this way, and with both claimants removed there is no "
            "candidate left to be ambiguous between."
        ),
    ),
    ResolutionCase(
        name="a_superseded_typed_name_matches_nothing",
        family="withdrawn_name",
        reference="Halvard Studio Three",
        expected_outcome=ResolutionOutcome.NOT_FOUND,
        must_not_include=frozenset({HALVARD_STUDIO}),
        note=(
            "The row exists, and it is not evidence. The studio traded under this name "
            "until the correction that replaced it, so matching it would hand back the "
            "very spelling the Principal has already corrected away. The read filters on "
            "`EntityNameState`, and this is the case that makes that filter measurable."
        ),
    ),
    ResolutionCase(
        name="a_retired_typed_name_matches_nothing",
        family="withdrawn_name",
        reference="Halvard Signage",
        expected_outcome=ResolutionOutcome.NOT_FOUND,
        must_not_include=frozenset({HALVARD_BRAND}),
        note=(
            "Withdrawn rather than corrected: the Principal said to stop using this brand "
            "and named no successor. The pair of the case above, on the other state a "
            "name row can be left in -- because a filter written for one of them and not "
            "the other passes half this rule and reads as though it passed all of it."
        ),
    ),
    ResolutionCase(
        name="a_communication_value_one_entity_claims_still_does_not_resolve",
        family="communication_value",
        reference="studio@halvard.example.invalid",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({MERIDEL_LEGAL}),
        must_not_include=frozenset({HALVARD_STUDIO, HALVARD_HOLDINGS, HALVARD_BRAND}),
        note=(
            "`COMMUNICATION_VALUE`, which nothing measured until now. The namespace is "
            "set and no `entity_external_identifiers` row carries this address, so "
            "`_by_identifier` falls through to the channel plane, where exactly one "
            "entity records it. One claimant and it still does not resolve: a recorded "
            "way to reach somebody is not a verified identity binding, and a mailbox with "
            "a single recorded owner is a mailbox, not a person."
        ),
    ),
    ResolutionCase(
        name="an_ended_affiliation_to_the_scope_does_not_resolve",
        family="stale_scope",
        reference="Priya Rao",
        scope_entity_id=ACME,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({PRIYA_RAO}),
        note=(
            "The mirror of `an_affiliation_naming_the_scope_resolves_a_lone_name`. Priya "
            "is uniquely named and her Acme affiliation is recorded as over; `state` is "
            "still `ACTIVE`, because an active row recording a past employment is this "
            "family's ordinary shape rather than a contradiction. Only the dates say it "
            "ended, so this is the case the date half of `is_in_force` is measured by."
        ),
    ),
    ResolutionCase(
        name="a_superseded_affiliation_to_the_scope_does_not_resolve",
        family="stale_scope",
        reference="Leo Marchetti",
        scope_entity_id=ACME,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({LEO_MARCHETTI}),
        note=(
            "The other half, and the one the date rule cannot catch: Leo's Acme "
            "affiliation is open-ended and in force by every date, and only its `state` "
            "says it is no longer the authoritative record. Delete the state filter and a "
            "corrected-away employer starts lifting a bare name to a confident answer. "
            "The same reference resolves against Northwind, which is where the "
            "correction put him."
        ),
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
    ResolutionCase(
        name="another_principals_typed_name_is_invisible",
        family="cross_principal",
        reference="Alice Chen",
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({ALICE_CHEN_ENGINEER, ALICE_CHEN_LAWYER, CHEN_PARTNERS}),
        must_not_include=frozenset({BOB_CHEN_OTHER_PRINCIPAL}),
        note=(
            "The partition case for `entity_names`, and the strong form of it: the three "
            "cross-Principal cases above all answer `NOT_FOUND`, where a missing "
            "candidate is indistinguishable from a corpus that had nothing to offer. "
            "Here `PRINCIPAL_A` gets three candidates and the other Principal's Bob Chen "
            "-- whose recorded legal name is the identical string -- is not the fourth."
        ),
    ),
    ResolutionCase(
        name="a_mailbox_two_entities_share_offers_both_and_chooses_neither",
        family="cross_principal",
        reference="hello@halvard.example.invalid",
        namespace=ExternalIdentifierNamespace.EMAIL,
        expected_outcome=ResolutionOutcome.AMBIGUOUS,
        must_include=frozenset({HALVARD_STUDIO, HALVARD_HOLDINGS}),
        must_not_include=frozenset({BOB_CHEN_OTHER_PRINCIPAL, MERIDEL_LEGAL}),
        note=(
            "Two claims in one answer, because they are the same read. A shared mailbox "
            "answered by two juristic entities of one family produces both claimants and "
            "chooses neither -- `COMMUNICATION_VALUE` never resolves, however few "
            "claimants there are. And the other Principal's contact card carries the "
            "identical address, deliberately, so this is also the partition case for "
            "`entity_communication_methods` in its strong form: a leak here would be a "
            "third candidate on an answer that already has two, not a silence turning "
            "into a name."
        ),
    ),
)
