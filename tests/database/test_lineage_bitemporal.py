"""AT-008: what was known when, and what was in effect then (S3 contract sections 3.4 and 7.2).

Against PostgreSQL through `ApplicationService.invoke` only:

* a late handoff correction never changes an answer for a `known_at` before it
  and does change one after it -- the corrected past (a `retime`) and the
  voided event (a `void`) -- so the chain's holder at a business time moves only
  for later knowledge;
* `records.lineage` reads every link and every Issue title and state at the
  commit mark of `T_v = min(valid_at, T_k)`, reports `lineage_valid_at`, and
  refuses a `known_at` or `valid_at` after now;
* a Meeting's note versions are cut at the native cut `N`: a note saved after an
  explicit `known_at` never changes that answer, while a current read shows a
  note saved after the last lineage write;
* an as-of read writes nothing and takes no commit mark.

Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.application.commands import (
    EndRecordAssociation,
    ListIssueHandoffs,
    ReadIssueHistory,
    ReadRecordAssociationHistory,
    UpdateIssue,
)
from tests.database.lineage_record_harness import NOTE_BODY, revise_notes
from tests.database.lineage_s2_harness import assertion, handoff
from tests.database.lineage_s3_harness import (
    GATEWAY,
    all_s3_counts,
    contradicts,
    correct_handoff,
    corroborates,
    mark_count,
    shortly_after,
)
from tests.database.lineage_s3_read_harness import (
    S3ReadRuntime,
    edge_ids,
    horizon,
    instant,
    lineage_request,
    node_set,
    virtual_set,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _refused(runtime: S3ReadRuntime, command: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    error = runtime.refused(command)
    return str(error["code"]), list(error.get("safe_details") or [])


def _shown(value: str) -> str:
    """An instant as a view shows it: RFC 3339 UTC to the millisecond."""
    parsed = datetime.fromisoformat(value).astimezone(UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class _Chain:
    """An Issue, a Commitment member and its handoff chain, with millisecond-apart times."""

    def __init__(self, runtime: S3ReadRuntime, key: str) -> None:
        self.rt = runtime
        self.issue = runtime.issue(key)
        self.commitment = runtime.commitment(key)
        runtime.member(self.issue, "commitment", self.commitment, key, "discussion")
        self.created = str(runtime.commitment_view(self.commitment)["created_at"])
        self.key = key
        self.events: list[str] = []

    def at(self, milliseconds: int) -> str:
        return shortly_after(self.created, 1000 * milliseconds)

    def record(self, side: str, milliseconds: int) -> str:
        number = len(self.events) + 1
        written = self.rt.ok(
            handoff(
                self.issue,
                self.commitment,
                side,
                self.at(milliseconds),
                f"{self.key}-{number}",
                self.rt.handoff_anchor(f"{self.key}-{number}"),
            ),
            surface=GATEWAY,
        )["handoff"]
        self.events.append(str(written["handoff_id"]))
        return self.events[-1]

    def listed(self, known_at: str | None = None) -> dict[str, dict[str, Any]]:
        page = self.rt.ok(
            ListIssueHandoffs(issue_id=self.issue, commitment_id=self.commitment, known_at=known_at)
        )
        return {view["handoff_id"]: view for view in page["handoffs"]}

    def holder_at(self, business: str, known_at: str | None = None) -> dict[str, Any] | None:
        """The arrival holder of the last live event in effect at `business`, as known."""
        moment = datetime.fromisoformat(business.replace("Z", "+00:00"))
        holder: dict[str, Any] | None = None
        for view in sorted(
            self.listed(known_at).values(), key=lambda view: view["current_effective_at"]
        ):
            effective = datetime.fromisoformat(view["current_effective_at"].replace("Z", "+00:00"))
            if not view["voided"] and effective <= moment:
                holder = view["to"]
        return holder


# ---- handoff corrections at known_at (section 3.4, AT-008) ----------------------------------


def test_known_at_before_a_correction_shows_the_old_belief(runtime: S3ReadRuntime) -> None:
    chain = _Chain(runtime, "bt-old")
    event = chain.record("counterparty", 10)
    before = horizon(runtime.engine)
    runtime.ok(
        correct_handoff(
            event, "retime", "bt-old", runtime.handoff_anchor("bt-old-c"), effective_at=chain.at(4)
        ),
        surface=GATEWAY,
    )
    old = chain.listed(before)[event]
    assert old["current_effective_at"] == old["effective_at"] == _shown(chain.at(10))
    assert (old["voided"], old["correction_ids"]) == (False, [])
    # The answer at that `known_at` is byte-identical after the correction committed.
    assert chain.listed(before) == chain.listed(before)


def test_known_at_after_a_correction_shows_the_corrected_past(runtime: S3ReadRuntime) -> None:
    chain = _Chain(runtime, "bt-new")
    event = chain.record("counterparty", 10)
    before = horizon(runtime.engine)
    written = runtime.ok(
        correct_handoff(
            event, "retime", "bt-new", runtime.handoff_anchor("bt-new-c"), effective_at=chain.at(4)
        ),
        surface=GATEWAY,
    )
    after = horizon(runtime.engine)
    assert after > before
    corrected = chain.listed(after)[event]
    # The event is unchanged; the knowledge after the correction moves its effect.
    assert corrected["effective_at"] == _shown(chain.at(10))
    assert corrected["current_effective_at"] == _shown(chain.at(4))
    assert corrected["correction_ids"] == [written["correction"]["correction_id"]]
    # The current read agrees, and the old belief is still the old belief.
    assert chain.listed()[event]["current_effective_at"] == _shown(chain.at(4))
    assert chain.listed(before)[event]["current_effective_at"] == _shown(chain.at(10))


def test_a_retimed_handoff_moves_the_holder_only_for_later_knowledge(
    runtime: S3ReadRuntime,
) -> None:
    chain = _Chain(runtime, "bt-holder")
    chain.record("counterparty", 10)
    second = chain.record("principal", 30)
    known_before = horizon(runtime.engine)
    # D + 5: the second event really happened at 20, not 30.
    runtime.ok(
        correct_handoff(
            second,
            "retime",
            "bt-holder",
            runtime.handoff_anchor("bt-holder-c"),
            effective_at=chain.at(20),
        ),
        surface=GATEWAY,
    )
    known_after = horizon(runtime.engine)
    business = chain.at(25)
    first_holder = chain.holder_at(chain.at(15), known_before)
    assert first_holder is not None and first_holder["kind"] == "principal"
    # At business time 25: still the first event's holder for the old knowledge,
    # the second event's holder for the knowledge after the correction.
    assert chain.holder_at(business, known_before) == first_holder
    moved = chain.holder_at(business, known_after)
    assert moved is not None and moved != first_holder and moved["kind"] == "entity"
    assert chain.holder_at(business, known_before) == first_holder


def test_a_voided_handoff_is_present_before_and_absent_after_its_void(
    runtime: S3ReadRuntime,
) -> None:
    chain = _Chain(runtime, "bt-void")
    event = chain.record("counterparty", 10)
    before = horizon(runtime.engine)
    meeting_id, note_id = runtime.note("bt-void-source")
    runtime.ok(
        correct_handoff(event, "void", "bt-void", contradicts(meeting_id, note_id)),
        surface=GATEWAY,
    )
    after = horizon(runtime.engine)
    assert chain.listed(before)[event]["voided"] is False
    assert chain.holder_at(chain.at(20), before) is not None
    # Still listed (an append-only ledger), but voided: it is no holder.
    assert chain.listed(after)[event]["voided"] is True
    assert chain.holder_at(chain.at(20), after) is None


# ---- records.lineage cuts (sections 3.4 and 7.2) --------------------------------------------


def _blocks_issue(runtime: S3ReadRuntime, key: str) -> dict[str, str]:
    issue = runtime.issue(key, title=f"Synthetic {key} before")
    first, second = runtime.task(f"{key}-a"), runtime.task(f"{key}-b")
    runtime.member(issue, "task", first, f"{key}-a", "reference")
    runtime.member(issue, "task", second, f"{key}-b", "reference")
    meeting_id, note_id = runtime.note(f"{key}-source")
    return {
        "issue": issue,
        "first": first,
        "second": second,
        "meeting": meeting_id,
        "note": note_id,
    }


def _link(runtime: S3ReadRuntime, scene: dict[str, str], key: str) -> str:
    written = runtime.ok(
        assertion(
            "blocks",
            ("task", scene["first"]),
            ("task", scene["second"]),
            key,
            (corroborates(scene["meeting"], scene["note"]),),
            context=scene["issue"],
        ),
        surface=GATEWAY,
    )
    return str(written["association"]["link_id"])


def _marked_at(runtime: S3ReadRuntime, link_id: str, revision_no: int) -> datetime:
    with runtime.engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT m.marked_at FROM knowledge.record_link_revisions r "
                "JOIN knowledge.lineage_commit_marks m "
                "ON m.principal_id = r.principal_id AND m.commit_seq = r.commit_seq "
                "WHERE r.link_id = :link AND r.revision_no = :revision"
            ),
            {"link": link_id, "revision": revision_no},
        ).scalar_one()
    assert isinstance(value, datetime)
    return value


def test_lineage_valid_at_is_bounded_by_known_at(runtime: S3ReadRuntime) -> None:
    scene = _blocks_issue(runtime, "bt-valid")
    early = horizon(runtime.engine)
    link = _link(runtime, scene, "bt-valid")
    known = horizon(runtime.engine)
    root = ("situation", scene["issue"])
    # A later `valid_at` than `known_at` is cut to `known_at`.
    later = runtime.lineage(root, known_at=early, valid_at=known)
    assert (later["known_at"], later["valid_at"], later["lineage_valid_at"]) == (
        early,
        known,
        early,
    )
    assert link not in edge_ids(later)
    # An earlier `valid_at` cuts the lineage plane there, under the later knowledge.
    earlier = runtime.lineage(root, known_at=known, valid_at=early)
    assert (earlier["known_at"], earlier["valid_at"], earlier["lineage_valid_at"]) == (
        known,
        early,
        early,
    )
    assert link not in edge_ids(earlier)
    both = runtime.lineage(root, known_at=known)
    assert (both["valid_at"], both["lineage_valid_at"]) == (known, known)
    assert link in edge_ids(both)
    # A current read answers at the committed horizon.
    current = runtime.lineage(root)
    assert current["known_at"] == current["lineage_valid_at"] == known


def test_known_at_or_valid_at_after_now_is_refused(runtime: S3ReadRuntime) -> None:
    scene = _blocks_issue(runtime, "bt-future")
    link = _link(runtime, scene, "bt-future")
    future = instant(datetime.now(UTC), plus=timedelta(days=1))
    root = ("situation", scene["issue"])
    before = all_s3_counts(runtime.engine)
    for field in ("known_at", "valid_at"):
        error = runtime.refused(lineage_request(root, {field: future})[0])
        assert (error["code"], error["safe_details"]) == ("invalid_request", [field])
    for command in (
        ReadIssueHistory(issue_id=scene["issue"], known_at=future),
        ReadRecordAssociationHistory(link_id=link, known_at=future),
        ListIssueHandoffs(issue_id=scene["issue"], known_at=future),
    ):
        assert _refused(runtime, command) == ("invalid_request", ["known_at"])
    assert all_s3_counts(runtime.engine) == before


def _meeting_issue(runtime: S3ReadRuntime, key: str) -> dict[str, str]:
    issue = runtime.issue(key)
    meeting_id, note_id = runtime.note(key)
    runtime.member(issue, "meeting", meeting_id, key, "discussion")
    return {"issue": issue, "meeting": meeting_id, "note": note_id}


def test_a_note_saved_after_known_at_leaves_the_answer_unchanged(runtime: S3ReadRuntime) -> None:
    scene = _meeting_issue(runtime, "bt-note-asof")
    known = horizon(runtime.engine)
    roots = (("situation", scene["issue"]), ("meeting", scene["meeting"]))
    answers = {root: runtime.lineage(root, known_at=known) for root in roots}
    assert virtual_set(answers[roots[0]]) == {(scene["note"], scene["meeting"])}
    later = revise_notes(runtime, scene["meeting"], "bt-note-asof-2", body=NOTE_BODY + " Later.")
    for root in roots:
        again = runtime.lineage(root, known_at=known)
        assert again == answers[root], root
        assert later not in {edge[0] for edge in virtual_set(again)}
    # The new note is the Meeting's, and a current read does show it.
    assert (later, scene["meeting"]) in virtual_set(runtime.lineage(roots[0]))


def test_a_current_read_shows_a_note_saved_after_the_lineage_horizon(
    runtime: S3ReadRuntime,
) -> None:
    scene = _meeting_issue(runtime, "bt-note-now")
    known = horizon(runtime.engine)
    later = revise_notes(runtime, scene["meeting"], "bt-note-now-2", body=NOTE_BODY + " Later.")
    # No lineage write since: the horizon did not move, the note is after it.
    assert horizon(runtime.engine) == known
    for root in (("situation", scene["issue"]), ("meeting", scene["meeting"])):
        current = runtime.lineage(root)
        assert current["known_at"] == known
        assert current["native_cut_at"] > known
        assert virtual_set(current) == {
            (scene["note"], scene["meeting"]),
            (later, scene["meeting"]),
        }, root


def test_a_link_revision_takes_effect_at_its_commit_mark(runtime: S3ReadRuntime) -> None:
    scene = _blocks_issue(runtime, "bt-mark")
    link = _link(runtime, scene, "bt-mark")
    asserted = _marked_at(runtime, link, 1)
    root = ("situation", scene["issue"])
    just_before = instant(asserted, plus=-timedelta(microseconds=1))
    assert link not in edge_ids(runtime.lineage(root, known_at=just_before))
    assert link in edge_ids(runtime.lineage(root, known_at=instant(asserted)))
    runtime.ok(
        EndRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key="bt-mark-end",
            reason="Synthetic end.",
            evidence_anchors=(),
        ),
        surface=GATEWAY,
    )
    ended = _marked_at(runtime, link, 2)
    edges = runtime.lineage(root, known_at=instant(ended, plus=-timedelta(microseconds=1)))
    (shown,) = [edge for edge in edges["typed_edges"] if edge["link_id"] == link]
    assert (shown["revision_no"], shown["lifecycle_state"]) == (1, "active")
    assert link not in edge_ids(runtime.lineage(root, known_at=instant(ended)))
    assert link not in edge_ids(runtime.lineage(root))


def test_issue_titles_and_states_are_read_at_known_at(runtime: S3ReadRuntime) -> None:
    scene = _blocks_issue(runtime, "bt-title")
    before = horizon(runtime.engine)
    runtime.ok(
        UpdateIssue(
            issue_id=scene["issue"],
            expected_version=1,
            idempotency_key="bt-title-update",
            title="Synthetic bt-title after",
            state="active",
        )
    )
    after = horizon(runtime.engine)
    for root in (("situation", scene["issue"]), ("task", scene["first"])):
        for known, title, state in (
            (before, "Synthetic bt-title before", "open"),
            (after, "Synthetic bt-title after", "active"),
        ):
            answer = runtime.lineage(root, known_at=known)
            (match,) = answer["issues_matching_root"]
            assert (match["title"], match["state"]) == (title, state), (root, known)
            (node,) = [node for node in answer["nodes"] if node["family"] == "situation"]
            assert (node["title"], node["state"]) == (title, state), (root, known)


def test_an_as_of_read_writes_nothing(runtime: S3ReadRuntime) -> None:
    scene = _blocks_issue(runtime, "bt-nowrite")
    link = _link(runtime, scene, "bt-nowrite")
    known = horizon(runtime.engine)
    counts, marks = all_s3_counts(runtime.engine), mark_count(runtime.engine)
    root = ("situation", scene["issue"])
    answers = [
        runtime.lineage(root, known_at=known),
        runtime.lineage(root, known_at=known, valid_at=known, page_size=10),
        runtime.ok(ReadIssueHistory(issue_id=scene["issue"], known_at=known)),
        runtime.ok(ReadRecordAssociationHistory(link_id=link, known_at=known)),
    ]
    assert node_set(answers[0]) >= {("situation", scene["issue"])}
    assert all_s3_counts(runtime.engine) == counts
    assert mark_count(runtime.engine) == marks
    assert horizon(runtime.engine) == known
