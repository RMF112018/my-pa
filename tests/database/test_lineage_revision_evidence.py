"""AT-004: each link revision's frozen evidence set and its digest (S1).

S1 contract sections 4.2 and 5.1 against PostgreSQL: a revision reads its own
evidence set, the stored `evidence_set_digest` rebuilds from the stored anchor
rows, a committed revision admits no further evidence, one evidence set has
one digest wherever it is cited (and its anchors are reused), a mixed note /
Capture version / legacy root set rebuilds, an anchor repeated in one set is
refused, and two transactions reusing overlapping anchors in opposite input
orders do not deadlock. Every identity and body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import (
    CorrectRecordAssociation,
    EndRecordAssociation,
    ReadIssue,
    ReadRecordLineage,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.ports import LinkRevisionRecord
from my_pa.domain.lineage.canonical import evidence_set_digest
from my_pa.infrastructure.persistence.record_lineage import SqlRecordLineageRepository
from my_pa.infrastructure.persistence.tables import lineage_evidence_anchors
from tests.database.lineage_issue_harness import PRINCIPAL, LineageRuntime
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    capture,
    capture_anchor,
    commitment,
    legacy_anchor,
    meeting,
    membership,
    note_anchor,
    originated_from,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _revision(runtime: LineageRuntime, link_id: str, revision_no: int) -> LinkRevisionRecord:
    with runtime.engine.connect() as connection:
        revision = SqlRecordLineageRepository(connection).read_revision(
            PRINCIPAL, link_id, revision_no
        )
    assert revision is not None
    return revision


def _origin_link(runtime: LineageRuntime, key: str) -> tuple[str, str, str, str]:
    m1, n1 = meeting(runtime, key)
    c1 = commitment(runtime, key)
    written = runtime.ok(
        originated_from(
            "commitment", c1, "meeting_note_version", n1, key, (note_anchor(m1, n1, NOTE_BODY),)
        ),
        surface=GATEWAY,
    )
    return written["association"]["link_id"], m1, n1, c1


def test_each_revision_reads_its_own_evidence_set(runtime: LineageRuntime) -> None:
    link_id, m1, n1, _c1 = _origin_link(runtime, "own-set")
    narrower = note_anchor(m1, n1, NOTE_BODY, passage="façade")
    corrected = runtime.ok(
        CorrectRecordAssociation(
            link_id=link_id,
            expected_revision=1,
            idempotency_key="lineage-own-set-correct",
            reason="the origin passage was narrowed",
            evidence_anchors=(narrower,),
        ),
        surface=GATEWAY,
    )
    assert corrected["association"]["revision_no"] == 2
    first, second = _revision(runtime, link_id, 1), _revision(runtime, link_id, 2)
    assert [cited.anchor.passage_end_cp for cited in first.evidence] != [
        cited.anchor.passage_end_cp for cited in second.evidence
    ]
    assert second.action.value == "correct_evidence" and second.reason is not None
    assert first.evidence_set_digest != second.evidence_set_digest
    # The root never changed.
    assert corrected["association"]["link_id"] == link_id
    assert corrected["association"]["to"]["record_id"] == n1


def test_the_stored_digest_rebuilds_from_stored_rows(runtime: LineageRuntime) -> None:
    link_id, *_ = _origin_link(runtime, "rebuild")
    revision = _revision(runtime, link_id, 1)
    assert evidence_set_digest(cited.anchor for cited in revision.evidence) == (
        revision.evidence_set_digest
    )


def test_evidence_cannot_be_added_to_a_committed_revision(runtime: LineageRuntime) -> None:
    link_id, *_ = _origin_link(runtime, "frozen")
    # A second anchor row of the same Principal, cited by another link.
    other, *_ = _origin_link(runtime, "frozen-other")
    extra = _revision(runtime, other, 1).evidence[0].anchor_id
    with pytest.raises(DBAPIError) as refused, runtime.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.record_link_revision_evidence "
                "(principal_id, link_id, revision_no, ordinal, anchor_id, role) "
                "VALUES (:principal, :link, 1, 2, :anchor, 'corroborates')"
            ),
            {"principal": PRINCIPAL, "link": link_id, "anchor": extra},
        )
    assert "evidence count" in str(refused.value)
    assert len(_revision(runtime, link_id, 1).evidence) == 1


def test_identical_evidence_has_one_digest_across_revisions(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "same-digest")
    anchor = note_anchor(m1, n1, NOTE_BODY)
    links = []
    for key in ("a", "b"):
        c1 = commitment(runtime, f"same-digest-{key}")
        written = runtime.ok(
            originated_from(
                "commitment", c1, "meeting_note_version", n1, f"same-digest-{key}", (anchor,)
            ),
            surface=GATEWAY,
        )
        links.append(written["association"])
    stored = [_revision(runtime, link["link_id"], 1).evidence_set_digest for link in links]
    assert stored[0] == stored[1]
    assert links[0]["evidence"][0]["anchor_id"] == links[1]["evidence"][0]["anchor_id"]
    with runtime.engine.connect() as connection:
        anchors = connection.execute(
            select(func.count()).select_from(lineage_evidence_anchors)
        ).scalar_one()
    assert anchors == 1


def test_a_mixed_note_capture_and_legacy_set_rebuilds_its_digest(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "mixed")
    root, version, _ = capture(runtime, "mixed")
    issue = runtime.issue("mixed")
    c1 = commitment(runtime, "mixed")
    written = runtime.ok(
        membership(
            issue,
            "commitment",
            c1,
            "mixed",
            anchors=(
                legacy_anchor(root),
                capture_anchor(root, version, NOTE_BODY, role="corroborates"),
                note_anchor(m1, n1, NOTE_BODY, role="discussion"),
            ),
        ),
        surface=GATEWAY,
    )
    revision = _revision(runtime, written["membership"]["link_id"], 1)
    assert [cited.anchor.source_family.value for cited in revision.evidence] == [
        "capture",
        "capture_version",
        "meeting_note_version",
    ]
    assert evidence_set_digest(cited.anchor for cited in revision.evidence) == (
        revision.evidence_set_digest
    )
    assert "evidence_set_digest" not in written["membership"]


def test_the_same_anchor_twice_in_one_set_is_refused(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "twice")
    issue = runtime.issue("twice")
    once = note_anchor(m1, n1, NOTE_BODY, role="discussion")
    with pytest.raises(InvalidRequestError) as refused:
        membership(issue, "meeting", m1, "twice", anchors=(once, {**once, "role": "corroborates"}))
    assert refused.value.safe_details == (SafeDetail.EVIDENCE_ANCHORS,)


def test_overlapping_anchor_reuse_in_two_transactions_does_not_deadlock(
    runtime: LineageRuntime,
) -> None:
    m1, n1 = meeting(runtime, "overlap")
    root, version, _ = capture(runtime, "overlap")
    issue = runtime.issue("overlap")
    first = note_anchor(m1, n1, NOTE_BODY, role="discussion")
    second = capture_anchor(root, version, NOTE_BODY, role="corroborates")
    third = note_anchor(m1, n1, NOTE_BODY, passage="Next: pour", role="discussion")
    commitments = [commitment(runtime, f"overlap-{index}") for index in range(6)]
    for round_no in range(3):
        barrier = Barrier(2)

        def write(
            index: int,
            anchors: tuple[dict[str, object], ...],
            barrier: Barrier = barrier,
            round_no: int = round_no,
        ) -> Any:  # noqa: ANN401
            command = membership(
                issue,
                "commitment",
                commitments[index],
                f"overlap-{round_no}-{index}",
                anchors=anchors,
            )
            barrier.wait(timeout=30)
            return runtime.invoke(command, surface=GATEWAY)

        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(write, round_no * 2, (first, second, third))
            right = pool.submit(write, round_no * 2 + 1, (third, second, first))
            answers = [left.result(timeout=60), right.result(timeout=60)]
        for answer in answers:
            assert answer.error is None, answer.error
    with runtime.engine.connect() as connection:
        anchors = connection.execute(
            select(func.count()).select_from(lineage_evidence_anchors)
        ).scalar_one()
    assert anchors == 3


def _keys(document: object) -> set[str]:
    if isinstance(document, dict):
        return set(document) | {key for value in document.values() for key in _keys(value)}
    if isinstance(document, list):
        return {key for item in document for key in _keys(item)}
    return set()


def test_no_view_carries_the_evidence_set_digest(runtime: LineageRuntime) -> None:
    """FR1-F05: the stored set digest is withheld from every write and read answer."""
    link_id, m1, n1, c1 = _origin_link(runtime, "withheld")
    issue = runtime.issue("withheld")
    answers = [
        runtime.ok(membership(issue, "commitment", c1, "withheld"), surface=GATEWAY),
        runtime.ok(
            CorrectRecordAssociation(
                link_id=link_id,
                expected_revision=1,
                idempotency_key="lineage-withheld-correct",
                reason="narrowed",
                evidence_anchors=(note_anchor(m1, n1, NOTE_BODY, passage="façade"),),
            ),
            surface=GATEWAY,
        ),
        runtime.ok(ReadIssue(issue_id=issue, include_members=True)),
        runtime.ok(ReadRecordLineage(origin={"family": "commitment", "record_id": c1})),
        runtime.ok(
            EndRecordAssociation(
                link_id=link_id,
                expected_revision=2,
                idempotency_key="lineage-withheld-end",
                reason="ended",
            ),
            surface=GATEWAY,
        ),
    ]
    for answer in answers:
        keys = _keys(answer)
        assert "evidence" in keys or "typed_edges" in keys
        assert "evidence_set_digest" not in keys
    # It is still stored and still rebuilds.
    revision = _revision(runtime, link_id, 3)
    assert evidence_set_digest(cited.anchor for cited in revision.evidence) == (
        revision.evidence_set_digest
    )
