from datetime import UTC, date, datetime

import pytest

from my_pa.application.goodnotes_semantics import (
    GoodNotesDateEvidence,
    GoodNotesDateScope,
    GoodNotesDateSemantics,
    GoodNotesPageDateStatus,
    admit_date_evidence,
)


def _date(
    scope: GoodNotesDateScope,
    value: str,
    *,
    literal: str | None = None,
    confidence: float | None = None,
    evidence_refs: tuple[str, ...] = ("gnver_aaaaaaaaaaaaaaaaaaaaaaaa#region:1",),
) -> GoodNotesDateEvidence:
    return admit_date_evidence(
        scope=scope,
        value=value,
        literal=literal or value,
        confidence=confidence,
        evidence_refs=evidence_refs,
    )


def test_page_date_is_distinct_from_zero_or_more_event_and_body_dates() -> None:
    page = _date(GoodNotesDateScope.PAGE, "2026-09-04", literal="Friday 9/4")
    event = _date(GoodNotesDateScope.EVENT, "2026-09-08", literal="meeting Tuesday")
    body = _date(GoodNotesDateScope.BODY, "2026-09-30", literal="due end of month")

    semantics = GoodNotesDateSemantics(
        page_candidates=(page,), event_dates=(event,), body_dates=(body,)
    )

    assert semantics.page_date_status is GoodNotesPageDateStatus.RESOLVED
    assert semantics.page_date == date(2026, 9, 4)
    assert semantics.event_dates == (event,)
    assert semantics.body_dates == (body,)
    assert GoodNotesDateSemantics().page_date_status is GoodNotesPageDateStatus.ABSENT


def test_distinct_page_dates_remain_explicitly_ambiguous() -> None:
    first = _date(GoodNotesDateScope.PAGE, "2026-09-04", literal="9/4")
    second = _date(
        GoodNotesDateScope.PAGE,
        "2026-09-05",
        literal="maybe 9/5",
        confidence=0.4,
        evidence_refs=("gnver_aaaaaaaaaaaaaaaaaaaaaaaa#region:2",),
    )

    semantics = GoodNotesDateSemantics(page_candidates=(first, second))

    assert semantics.page_date_status is GoodNotesPageDateStatus.AMBIGUOUS
    assert semantics.page_date is None
    assert semantics.page_candidates == (first, second)


def test_same_page_date_from_multiple_regions_is_resolved_without_losing_evidence() -> None:
    first = _date(GoodNotesDateScope.PAGE, "2026-09-04", literal="Friday")
    second = _date(
        GoodNotesDateScope.PAGE,
        "2026-09-04",
        literal="09/04/26",
        evidence_refs=("gnver_aaaaaaaaaaaaaaaaaaaaaaaa#region:header",),
    )

    semantics = GoodNotesDateSemantics(page_candidates=(first, second))

    assert semantics.page_date_status is GoodNotesPageDateStatus.RESOLVED
    assert semantics.page_date == date(2026, 9, 4)
    assert semantics.page_candidates == (first, second)


@pytest.mark.parametrize("value", ("2026-02-30", "09/04/2026", "2026-9-4", ""))
def test_invalid_or_noncanonical_date_values_fail_closed(value: str) -> None:
    with pytest.raises(ValueError, match="date value"):
        _date(GoodNotesDateScope.EVENT, value)


@pytest.mark.parametrize("confidence", (-0.01, 1.01, float("nan"), float("inf"), True))
def test_invalid_confidence_fails_closed(confidence: float) -> None:
    with pytest.raises((TypeError, ValueError), match="date confidence"):
        _date(GoodNotesDateScope.BODY, "2026-09-04", confidence=confidence)


def test_date_evidence_retains_literal_confidence_and_provenance() -> None:
    evidence = _date(
        GoodNotesDateScope.EVENT,
        "2026-09-08",
        literal="meet Alex next Tuesday",
        confidence=0.72,
        evidence_refs=("gnver_aaaaaaaaaaaaaaaaaaaaaaaa#region:left", "crop:abcdef"),
    )

    assert evidence.literal == "meet Alex next Tuesday"
    assert evidence.confidence == 0.72
    assert evidence.evidence_refs == (
        "gnver_aaaaaaaaaaaaaaaaaaaaaaaa#region:left",
        "crop:abcdef",
    )


def test_scope_mixups_and_missing_or_duplicate_provenance_fail_closed() -> None:
    event = _date(GoodNotesDateScope.EVENT, "2026-09-08")
    with pytest.raises(ValueError, match="page dates"):
        GoodNotesDateSemantics(page_candidates=(event,))
    with pytest.raises(ValueError, match="outside their bound"):
        _date(GoodNotesDateScope.PAGE, "2026-09-04", evidence_refs=())
    with pytest.raises(ValueError, match="must be unique"):
        _date(
            GoodNotesDateScope.PAGE,
            "2026-09-04",
            evidence_refs=("region:1", "region:1"),
        )


def test_datetime_cannot_be_substituted_for_a_page_date() -> None:
    with pytest.raises(TypeError, match="without a time"):
        GoodNotesDateEvidence(
            scope=GoodNotesDateScope.PAGE,
            value=datetime(2026, 9, 4, tzinfo=UTC),
            literal="2026-09-04T00:00:00Z",
            evidence_refs=("region:1",),
        )
