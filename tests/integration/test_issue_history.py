"""AT-007 (history): an Issue's and a link's revisions, as known at `known_at` (S3 section 7.3).

Against PostgreSQL through `ApplicationService.invoke`:

* `issues.history` lists every Issue revision in version order with its closure
  basis (`closed_at`, `outcome`, the closing evidence; a reopening's `reason`),
  omits revisions not yet known at `known_at`, and pages by version;
* `records.associations.history` lists every revision of a link -- assert,
  contest, reinstate, end -- with its own evidence set;
* another Principal's Issue or link, and one not yet known at `known_at`,
  answers like an absent one.

Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from my_pa.application.commands import (
    EndRecordAssociation,
    ReadIssueHistory,
    ReadRecordAssociationHistory,
    UpdateIssue,
)
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL
from tests.database.lineage_s2_harness import close, reopen
from tests.database.lineage_s3_harness import GATEWAY, blocks_scene, contest, reinstate
from tests.database.lineage_s3_read_harness import S3ReadRuntime, horizon

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _code(error: dict[str, Any]) -> tuple[str, list[str]]:
    return str(error["code"]), list(error.get("safe_details") or [])


def _lived(runtime: S3ReadRuntime, key: str) -> dict[str, Any]:
    """An Issue created, renamed, closed on exact evidence and reopened; horizons between."""
    issue = runtime.issue(key, title=f"Synthetic {key}")
    cuts = {"created": horizon(runtime.engine)}
    runtime.ok(
        UpdateIssue(
            issue_id=issue,
            expected_version=1,
            idempotency_key=f"{key}-update",
            title=f"Synthetic {key} renamed",
        )
    )
    cuts["updated"] = horizon(runtime.engine)
    _, _, anchor = runtime.evidence_source(f"{key}-closure")
    closed = runtime.ok(
        close(issue, 2, key, (anchor,), outcome="Synthetic outcome."), surface=GATEWAY
    )
    cuts["closed"] = horizon(runtime.engine)
    runtime.ok(reopen(issue, 3, key, reason="Synthetic recurrence."), surface=GATEWAY)
    cuts["reopened"] = horizon(runtime.engine)
    return {"issue": issue, "cuts": cuts, "closure": closed["closure"], "anchor": anchor}


def test_history_lists_every_revision_with_its_closure_basis(runtime: S3ReadRuntime) -> None:
    lived = _lived(runtime, "hist-basis")
    history = runtime.ok(ReadIssueHistory(issue_id=lived["issue"]))
    assert history["issue_id"] == lived["issue"]
    assert history["known_at"] == lived["cuts"]["reopened"]
    assert history["next_cursor"] is None
    revisions = history["revisions"]
    assert [(r["version"], r["action"], r["state"]) for r in revisions] == [
        (1, "created", "open"),
        (2, "updated", "open"),
        (3, "closed", "closed"),
        (4, "reopened", "active"),
    ]
    assert revisions[1]["title"] == "Synthetic hist-basis renamed"
    closing = revisions[2]
    assert closing["outcome"] == "Synthetic outcome."
    assert closing["closed_at"] == lived["closure"]["closed_at"]
    assert closing["evidence"] == lived["closure"]["evidence"]
    (anchor,) = closing["evidence"]
    assert (anchor["role"], anchor["version_id"]) == ("resolution", lived["anchor"]["version_id"])
    assert "source_sha256" not in anchor and "passage_sha256" not in anchor
    assert revisions[3]["reason"] == "Synthetic recurrence."
    for revision in (revisions[0], revisions[1]):
        assert (revision["closed_at"], revision["outcome"], revision["reason"]) == (None,) * 3
        assert revision["evidence"] == []


def test_history_at_known_at_omits_later_revisions(runtime: S3ReadRuntime) -> None:
    lived = _lived(runtime, "hist-asof")
    for cut, versions in (("created", [1]), ("updated", [1, 2]), ("closed", [1, 2, 3])):
        known = lived["cuts"][cut]
        history = runtime.ok(ReadIssueHistory(issue_id=lived["issue"], known_at=known))
        assert history["known_at"] == known, cut
        assert [r["version"] for r in history["revisions"]] == versions, cut


def test_history_pages_by_version(runtime: S3ReadRuntime) -> None:
    lived = _lived(runtime, "hist-pages")
    seen: list[int] = []
    after: int | None = None
    while True:
        page = runtime.ok(ReadIssueHistory(issue_id=lived["issue"], page_size=1, after=after))
        seen.extend(r["version"] for r in page["revisions"])
        after = page["next_cursor"]
        if after is None:
            break
        assert after == seen[-1]
    assert seen == [1, 2, 3, 4]
    # A client paging at an explicit `known_at` reads a fixed set.
    fixed = runtime.ok(
        ReadIssueHistory(
            issue_id=lived["issue"], page_size=2, after=1, known_at=lived["cuts"]["closed"]
        )
    )
    assert [r["version"] for r in fixed["revisions"]] == [2, 3]
    assert fixed["next_cursor"] is None
    for wrong in ({"page_size": 0}, {"page_size": 101}, {"after": 0}):
        with pytest.raises(Exception, match="invalid_request"):
            ReadIssueHistory(issue_id=lived["issue"], **wrong)


def test_association_history_lists_every_revision_with_its_evidence(
    runtime: S3ReadRuntime,
) -> None:
    scene = blocks_scene(runtime, "hist-link")
    link = scene["link"]
    runtime.ok(contest(link, 1, "hist-link", (scene["contradicts"],)), surface=GATEWAY)
    contested = horizon(runtime.engine)
    runtime.ok(reinstate(link, 2, "hist-link", (scene["corroborates"],)), surface=GATEWAY)
    runtime.ok(
        EndRecordAssociation(
            link_id=link,
            expected_revision=3,
            idempotency_key="hist-link-end",
            reason="Synthetic end.",
            evidence_anchors=(),
        ),
        surface=GATEWAY,
    )
    history = runtime.ok(ReadRecordAssociationHistory(link_id=link))
    root = history["link"]
    assert (root["link_id"], root["kind"], root["relation_type"]) == (link, "semantic", "blocks")
    assert root["from"] == {"family": "task", "record_id": scene["first"]}
    assert root["context_issue_id"] == scene["issue"]
    revisions = history["revisions"]
    assert [(r["revision_no"], r["action"], r["lifecycle_state"]) for r in revisions] == [
        (1, "assert", "active"),
        (2, "contest", "contested"),
        (3, "reinstate", "active"),
        (4, "end", "ended"),
    ]
    assert [[a["role"] for a in r["evidence"]] for r in revisions] == [
        ["corroborates"],
        ["contradicts"],
        ["corroborates"],
        [],
    ]
    assert revisions[1]["reason"] == "The source says otherwise."
    assert all(r["acceptance_basis"] == "user_confirmed" for r in revisions)
    # As known at the contest: two revisions; one page at a time by revision number.
    asof = runtime.ok(ReadRecordAssociationHistory(link_id=link, known_at=contested))
    assert [r["revision_no"] for r in asof["revisions"]] == [1, 2]
    first = runtime.ok(ReadRecordAssociationHistory(link_id=link, page_size=3))
    assert (len(first["revisions"]), first["next_cursor"]) == (3, 3)
    rest = runtime.ok(ReadRecordAssociationHistory(link_id=link, page_size=3, after=3))
    assert ([r["revision_no"] for r in rest["revisions"]], rest["next_cursor"]) == ([4], None)
    # A membership's history is read the same way.
    member = runtime.member(scene["issue"], "task", scene["first"], "hist-link-m", "reference")
    (only,) = runtime.ok(ReadRecordAssociationHistory(link_id=member))["revisions"]
    assert (only["action"], only["lifecycle_state"]) == ("assert", "active")


def test_a_foreign_issue_or_link_history_is_not_found(runtime: S3ReadRuntime) -> None:
    scene = blocks_scene(runtime, "hist-foreign")
    before = horizon(runtime.engine)
    later_issue = runtime.issue("hist-foreign-later")
    runtime.issue("hist-foreign-other", principal_id=OTHER_PRINCIPAL)
    for subject, absent, detail in (
        (scene["issue"], "sit_lineages3absent0001", "issue_id"),
        (scene["link"], "irl_lineages3absent0001", "link_id"),
    ):
        command = (
            ReadIssueHistory(issue_id=subject)
            if detail == "issue_id"
            else ReadRecordAssociationHistory(link_id=subject)
        )
        missing = (
            ReadIssueHistory(issue_id=absent)
            if detail == "issue_id"
            else ReadRecordAssociationHistory(link_id=absent)
        )
        foreign = runtime.refused(command, principal_id=OTHER_PRINCIPAL)
        assert _code(foreign) == _code(runtime.refused(missing)) == ("not_found", [detail])
        assert _code(foreign) == _code(runtime.refused(missing, principal_id=OTHER_PRINCIPAL))
    # An Issue not yet known at `known_at` answers alike.
    error = runtime.refused(ReadIssueHistory(issue_id=later_issue, known_at=before))
    assert _code(error) == ("not_found", ["issue_id"])
