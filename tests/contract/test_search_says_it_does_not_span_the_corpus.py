"""A search answered inside one enrollment cannot look like an answer about everything.

WP-23 P3. `docs/specs` section 23 names the failure this closes: *a search that
silently omits unindexed sources and returns a confident answer.* Coverage is
stated per enrollment and never inferred globally, which is right — and it means
a Principal who holds three enrollments and objects outside all of them can
search one of them, receive a clean disclosure with `processed` coverage and
`partial_result=False`, and have nothing in the reply that says most of what they
hold was never in the question.

**What is added, and what deliberately is not.** One closed limitation token and
`partial_result=True`. No count moves, no coverage state moves, and the scope
still names only the enrollment the request named — because nothing measured a
wider scope, and a number that appeared to would be an answer about rows the
request never authorized. The token says *that* there is scope outside the
answer, never how much or which.

**And the search still reaches nothing outside the enrollment it names.** The
token comes from a boolean asked beside the search, over the enrollment set the
acting Principal already holds. `test_no_row_outside_the_named_enrollment_reaches_the_page`
stages a *different* result under a second enrollment and asserts none of it
appears, so "the caveat did not widen the search" is a measurement rather than a
promise.

Every test here runs at the application level over fakes. The repository-level
claim — that the corpus reads are partitioned by `enrollments.principal_id` — is
`tests/database/test_corpus_coverage.py`, against a real server.
"""

from __future__ import annotations

import pytest
from tests.conftest import Scene, build_service, metadata_for, staged_search

from my_pa.application.commands import SearchKnowledge
from my_pa.application.disclosure import Limitation, with_corpus_caveat
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import SearchOutcome
from my_pa.contracts.v1.disclosure import (
    Coverage,
    Disclosure,
    Freshness,
    FreshnessState,
    Scope,
    SourceReference,
    Truncation,
    Trust,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.search.query import RankCategory, SearchMatch
from my_pa.domain.source.registry import issue_identifier

WHEN_TOKEN = Limitation.SEARCH_DOES_NOT_SPAN_THE_CORPUS.value

#: Every field the mandatory envelope has, written out. An exact equality rather
#: than a floor: `with_corpus_caveat` forwards each of these by name, and a field
#: added to `Disclosure` that this file did not notice would be silently dropped
#: from every search disclosure that carries the caveat.
ENVELOPE_FIELDS = frozenset(
    {
        "scope",
        "coverage",
        "freshness",
        "trust",
        "truncation",
        "limitations",
        "source_references",
        "unavailable_evidence",
        "partial_result",
        "classification",
        "cloud_eligible",
    }
)


def search(scene: Scene, service: ApplicationService) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH, scene.principal),
        SearchKnowledge(enrollment_id=scene.enrollment.enrollment_id, query="revenue"),
        principal=scene.principal,
    )


def a_second_enrollment(scene: Scene) -> str:
    """Another grant of the same Principal, over the same source.

    Over the same source deliberately: a second *source* would also be scope
    outside the answer, and using one here would leave open whether the token
    fires on the narrower case as well.
    """
    other = scene.world.add_enrollment(
        source_id=scene.source.source_id,
        principal_id=scene.principal.principal_id,
        object_ids=(scene.plain.source_object_id,),
    )
    return other.enrollment_id


def test_a_search_beside_a_second_enrollment_says_it_does_not_span_the_corpus(
    scene: Scene,
) -> None:
    """The first of the three ways scope escapes one enrollment."""
    outcome = staged_search(scene)
    scene.world.searches[scene.enrollment.enrollment_id] = outcome
    a_second_enrollment(scene)

    envelope = search(scene, build_service(scene.world, scene.providers))
    disclosure = envelope.disclosure
    assert disclosure is not None
    assert WHEN_TOKEN in disclosure.limitations
    assert disclosure.partial_result is True


def test_a_search_beside_an_object_no_enrollment_enumerates_says_the_same(
    scene: Scene,
) -> None:
    """The second way, and the one a Principal with a single grant still hits.

    An object observed in a source the Principal holds, enumerated by no
    enrollment of theirs. It is outside every question they can ask, and a search
    that did not say so would be reporting confidently on a fraction of a source.
    """
    outcome = staged_search(scene)
    scene.world.searches[scene.enrollment.enrollment_id] = outcome
    scene.world.objects[issue_identifier(IdKind.SOURCE_OBJECT)] = scene.source.source_id

    envelope = search(scene, build_service(scene.world, scene.providers))
    disclosure = envelope.disclosure
    assert disclosure is not None
    assert WHEN_TOKEN in disclosure.limitations
    assert disclosure.partial_result is True


def test_a_search_over_the_whole_of_what_a_principal_holds_carries_no_such_token(
    scene: Scene,
) -> None:
    """The green half, and it is what makes the token a measurement.

    `Scene` enrolls every object of its source under one grant, so there is
    nothing outside the question and the envelope is the one the search produced,
    unchanged. A token emitted unconditionally would pass every assertion above
    and prove nothing.
    """
    outcome = staged_search(scene)
    scene.world.searches[scene.enrollment.enrollment_id] = outcome

    envelope = search(scene, build_service(scene.world, scene.providers))
    assert envelope.disclosure == outcome.disclosure
    assert WHEN_TOKEN not in (envelope.disclosure.limitations if envelope.disclosure else ())


def test_the_caveat_changes_the_token_and_the_flag_and_nothing_else(scene: Scene) -> None:
    """Additive means additive: two fields move and the other nine do not."""
    outcome = staged_search(scene)
    scene.world.searches[scene.enrollment.enrollment_id] = outcome
    a_second_enrollment(scene)

    envelope = search(scene, build_service(scene.world, scene.providers))
    disclosure = envelope.disclosure
    assert disclosure is not None
    before = outcome.disclosure
    assert disclosure.coverage == before.coverage
    assert disclosure.coverage.state is CoverageState.PROCESSED
    assert disclosure.scope == before.scope
    assert disclosure.scope.enrollment_ids == (scene.enrollment.enrollment_id,)
    assert disclosure.freshness == before.freshness
    assert disclosure.trust == before.trust
    assert disclosure.truncation == before.truncation
    assert disclosure.source_references == before.source_references
    assert disclosure.classification == before.classification
    assert disclosure.cloud_eligible == before.cloud_eligible
    assert set(disclosure.limitations) - set(before.limitations) == {WHEN_TOKEN}


def test_the_token_names_no_scope_no_count_and_no_identifier(scene: Scene) -> None:
    """It says there is scope outside the answer, and nothing about what.

    A count would be a number about rows this request never authorized, which is
    a wider disclosure than the one the aggregate-limitation rule permits for the
    scope actually in question.
    """
    outcome = staged_search(scene)
    scene.world.searches[scene.enrollment.enrollment_id] = outcome
    other = a_second_enrollment(scene)
    scene.world.objects[issue_identifier(IdKind.SOURCE_OBJECT)] = scene.source.source_id

    envelope = search(scene, build_service(scene.world, scene.providers))
    disclosure = envelope.disclosure
    assert disclosure is not None
    rendered = " ".join(disclosure.limitations)
    assert other not in rendered
    assert scene.plain.source_object_id not in rendered
    assert not any(character.isdigit() for character in WHEN_TOKEN)


def test_no_row_outside_the_named_enrollment_reaches_the_page(scene: Scene) -> None:
    """The caveat did not widen the search, measured rather than promised.

    A different result is staged under the second enrollment. If asking whether
    scope exists beyond the named enrollment had turned into *reading* it, the
    other enrollment's match would appear here.
    """
    mine = staged_search(scene)
    scene.world.searches[scene.enrollment.enrollment_id] = mine
    other = a_second_enrollment(scene)
    scene.world.searches[other] = SearchOutcome(
        matches=(
            SearchMatch(
                knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
                label="Plain text document",
                snippet="the alpha report",
                rank=RankCategory.STRONG,
                source_id=scene.source.source_id,
                source_object_id=scene.plain.source_object_id,
                version_id=scene.plain.version_id,
            ),
        ),
        disclosure=mine.disclosure,
    )

    envelope = search(scene, build_service(scene.world, scene.providers))
    assert envelope.result is not None
    matches = envelope.result["matches"]
    assert isinstance(matches, list)
    assert [match["knowledge_id"] for match in matches] == [mine.matches[0].knowledge_id]
    assert [match["source_object_id"] for match in matches] == [scene.markdown.source_object_id]
    disclosure = envelope.disclosure
    assert disclosure is not None
    assert disclosure.scope.enrollment_ids == (scene.enrollment.enrollment_id,)


@pytest.mark.parametrize(
    "state",
    [CoverageState.PARTIALLY_PROCESSED, CoverageState.QUARANTINED, CoverageState.STALE],
    ids=lambda s: s.value,
)
def test_a_partial_coverage_state_still_cannot_claim_completeness(
    scene: Scene, state: CoverageState
) -> None:
    """The envelope's own rule, still holding under the caveat.

    `Disclosure._check_partial_is_truthful` refuses a partial coverage state
    beside `partial_result=False`, and the caveat rebuilds the envelope through
    the constructor precisely so that rule is re-evaluated rather than bypassed
    by a copy. Asserted over three of the five partial states rather than one.
    """
    base = Disclosure(
        scope=Scope(enrollment_ids=(scene.enrollment.enrollment_id,)),
        coverage=Coverage(state=state, eligible=4, processed=1),
        freshness=Freshness(observed_at=scene.enrollment.accepted_at, state=FreshnessState.STALE),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=("lexical_index",)),
        partial_result=True,
    )
    widened = with_corpus_caveat(base)
    assert widened.partial_result is True
    assert widened.coverage.state is state
    with pytest.raises(ValueError, match="partial_result"):
        Disclosure(
            scope=base.scope,
            coverage=base.coverage,
            freshness=base.freshness,
            trust=base.trust,
            partial_result=False,
        )


def test_the_caveat_forwards_every_field_the_envelope_has(scene: Scene) -> None:
    """A field added to `Disclosure` cannot be dropped here in silence.

    Two halves, and neither is enough alone. The set of field names is pinned as
    an exact equality, so a new field reddens rather than joining quietly. And a
    fully populated envelope is put through the function and compared field by
    field, so a name that *is* in the list but is not forwarded reddens too — the
    hole a name check alone would leave.
    """
    assert set(Disclosure.model_fields) == ENVELOPE_FIELDS

    populated = Disclosure(
        scope=Scope(
            source_ids=(scene.source.source_id,),
            enrollment_ids=(scene.enrollment.enrollment_id,),
        ),
        coverage=Coverage(state=CoverageState.PARTIALLY_PROCESSED, eligible=4, processed=2),
        freshness=Freshness(
            observed_at=scene.enrollment.accepted_at,
            state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION,
        ),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=("lexical_index",)),
        truncation=Truncation(
            is_truncated=True, reason="page_size_reached", next_cursor="cursor-alpha"
        ),
        limitations=("result_label_is_media_type_only",),
        source_references=(
            SourceReference(
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                version_id=scene.markdown.version_id,
            ),
        ),
        unavailable_evidence=("derivation_has_not_completed_for_every_version",),
        partial_result=True,
        classification=Classification.SYNTHETIC_TEST,
        cloud_eligible=False,
    )
    widened = with_corpus_caveat(populated)
    for field in ENVELOPE_FIELDS - {"limitations", "partial_result"}:
        assert getattr(widened, field) == getattr(populated, field), field
    assert widened.limitations == tuple(sorted({*populated.limitations, WHEN_TOKEN}))
    assert widened.partial_result is True
