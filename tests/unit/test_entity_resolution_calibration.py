"""The false-resolution evaluation, and the calibration it produces.

**Why this is FAST rather than SPECIALIZED.** `tests/evaluation`'s other
harness is marked `evaluation`, which no CI job selects — appropriate for a
suite that exercises a whole retrieval pipeline. This one is a few hundred
microseconds of pure Python over an in-memory corpus, and what it protects is
the single claim the relationship plane exists to make: that the resolver does
not join two different people. `AGENTS.md` section 7 admits a test to the PR
gate when it "protects a critical contract" at acceptable cost. Both halves are
true here, and a safety evaluation nobody runs is not a safety evaluation.

The frozen record is checked in the same run, so the published calibration
cannot rot the way a report recomputed only on demand can.

**What the assertions are, and why each is needed.**

* Zero false resolutions — the failure itself.
* Zero cross-Principal leakage — the failure that is invisible to the person it
  happens to.
* Zero exact resolutions on a bare name — the specific reasoning error that
  produces the first two.
* Recall above a floor — because a resolver that answers nothing satisfies all
  three of the above and is worthless. Without this, the suite would reward
  exactly the wrong fix for a failure of the others.
"""

from __future__ import annotations

import pytest

from my_pa.domain.relationship.resolution import (
    RESOLUTION_CANDIDATE_LIMIT,
    ResolutionBasis,
    ResolutionOutcome,
)
from tests.evaluation.fixtures.resolution_cases import (
    MUST_RESOLVE_FAMILIES,
    RESOLUTION_CASES,
)
from tests.evaluation.resolution_harness import (
    RECALL_FLOOR,
    RESOLUTION_SAFE,
    CaseResult,
    compute_calibration_record,
    exact_resolutions_on_a_bare_name,
    load_frozen_record,
    render_report,
    run_cases,
)


@pytest.fixture(scope="module")
def results() -> tuple[CaseResult, ...]:
    return run_cases()


@pytest.fixture(scope="module")
def record() -> dict[str, object]:
    return compute_calibration_record()


# --- the corpus is worth measuring against ----------------------------------


def test_the_corpus_contains_both_kinds_of_case() -> None:
    """Guards every assertion below against a corpus that cannot fail.

    A corpus of only-must-resolve cases rewards recklessness and a corpus of
    only-must-not rewards silence. Both must be present, and in quantity.
    """
    must_resolve = [case for case in RESOLUTION_CASES if case.expected_entity_id is not None]
    must_not = [case for case in RESOLUTION_CASES if case.expected_entity_id is None]
    assert len(must_resolve) >= 10, "too few cases the resolver is supposed to answer"
    assert len(must_not) >= 10, "too few cases the resolver is supposed to refuse"
    assert {case.family for case in RESOLUTION_CASES} >= MUST_RESOLVE_FAMILIES


def test_the_corpus_is_collision_biased() -> None:
    """Every name in the corpus that could collide, does.

    Asserted rather than asserted-in-a-docstring: a corpus that drifted into
    well-separated people would score perfectly and mean nothing.
    """
    from tests.evaluation.fixtures.resolution_corpus import (
        CORPUS_ALIASES,
        CORPUS_ENTITIES,
        CORPUS_IDENTIFIERS,
    )

    names = [entity.canonical_name for entity in CORPUS_ENTITIES]
    assert len(set(names)) < len(names), "no two entities share a canonical name"

    aliases = [alias.normalized_value for alias in CORPUS_ALIASES]
    assert len(set(aliases)) < len(aliases), "no two entities share an alias"

    addresses = [identifier.normalized_value for identifier in CORPUS_IDENTIFIERS]
    assert len(set(addresses)) < len(addresses), "no address is claimed twice"

    local_parts = [address.partition("@")[0] for address in set(addresses)]
    assert len(set(local_parts)) < len(local_parts), "no local part is recycled"


# --- the safety claims ------------------------------------------------------


def test_no_case_resolves_to_the_wrong_entity(results: tuple[CaseResult, ...]) -> None:
    """The one that matters. A named wrong person is the failure, not a metric."""
    wrong = [
        f"{result.case.name}: resolved to {result.resolution.resolved_entity_id}, "
        f"labelled {result.case.expected_entity_id}"
        for result in results
        if result.is_false_resolution
    ]
    assert wrong == []


def test_no_case_offers_a_forbidden_candidate(results: tuple[CaseResult, ...]) -> None:
    """A candidate list is shown to a person; the wrong Alice must not be on it."""
    leaked = {
        result.case.name: sorted(result.leaked_ids) for result in results if result.leaked_ids
    }
    assert leaked == {}


def test_no_case_resolves_exactly_on_a_bare_name(results: tuple[CaseResult, ...]) -> None:
    assert exact_resolutions_on_a_bare_name(results) == ()


def test_every_case_answers_the_outcome_its_label_names(
    results: tuple[CaseResult, ...],
) -> None:
    mismatched = {
        result.case.name: (result.resolution.outcome.value, result.case.expected_outcome.value)
        for result in results
        if not result.outcome_matches
    }
    assert mismatched == {}


def test_the_resolver_still_answers_what_it_should(record: dict[str, object]) -> None:
    """The floor that stops "never resolve" from being a passing strategy."""
    assert record["resolution_recall"] >= RECALL_FLOOR


def test_every_candidate_of_every_answer_carries_its_evidence(
    results: tuple[CaseResult, ...],
) -> None:
    for result in results:
        for candidate in result.resolution.candidates:
            assert candidate.evidence, f"{result.case.name} offers an unexplained candidate"


def test_no_answer_exceeds_the_candidate_bound(results: tuple[CaseResult, ...]) -> None:
    for result in results:
        assert len(result.resolution.candidates) <= RESOLUTION_CANDIDATE_LIMIT


def test_a_contextual_resolution_names_the_signal_that_selected_it(
    results: tuple[CaseResult, ...],
) -> None:
    """`RESOLVED_CONTEXTUAL` without a signal would be an unexplained selection."""
    contextual = [
        result
        for result in results
        if result.resolution.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    ]
    assert contextual, "the corpus exercises no contextual resolution"
    for result in contextual:
        assert result.resolution.candidates[0].signals, result.case.name


def test_a_conflicted_identifier_is_never_resolved(results: tuple[CaseResult, ...]) -> None:
    conflicted = [
        result
        for result in results
        if result.resolution.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER
    ]
    assert conflicted, "the corpus exercises no conflicted identifier"
    for result in conflicted:
        assert result.resolution.resolved_entity_id is None
        assert len(result.resolution.candidates) >= 2


# --- the calibration record -------------------------------------------------


def test_the_frozen_calibration_matches_the_computed_one(record: dict[str, object]) -> None:
    """The published table is what the harness actually measures, today."""
    assert record == load_frozen_record()


def test_the_frozen_report_is_the_rendered_record(record: dict[str, object]) -> None:
    from tests.evaluation.resolution_harness import REPORT_PATH

    assert REPORT_PATH.read_text(encoding="utf-8") == render_report(record)


def test_the_disposition_reflects_the_measurement(record: dict[str, object]) -> None:
    assert record["disposition"] == RESOLUTION_SAFE
    assert record["false_resolution_count"] == 0
    assert record["cross_principal_leakage"] == 0
    assert record["exact_resolutions_on_a_bare_name"] == 0


def test_the_calibration_table_keeps_a_bare_name_out_of_exact_resolution(
    record: dict[str, object],
) -> None:
    """The published table must not read as though a name were sufficient."""
    table = record["calibration_by_outcome_and_basis"]
    assert isinstance(table, dict)
    exact_on_name = (
        f"{ResolutionOutcome.RESOLVED_EXACT.value}:{ResolutionBasis.CANONICAL_NAME.value}"
    )
    assert exact_on_name not in table
