"""Record lineage S3.1: `records.lineage.related`, the multi-seed related read (database).

S3.1 contract section 7.4 through `ApplicationService.invoke` against
PostgreSQL (worker N3). From 1..25 seeds the read follows, per seed, every
admitted live link one hop away and the Issue-confined S3 expansion under each
of the seed's visible Issues, so a shared Meeting never bridges 2 Issues
(AT-006); it filters by acceptance basis and relation (a filtered link is
neither followed nor emitted); it is one bounded result recomputed per page,
in a deterministic order, under a grant-bound cursor; a hidden record is never
emitted, expanded or counted; and `related_sha256` binds the whole result
without its read stamps, so an explicit `known_at` reproduces it.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any, Final

import pytest

import my_pa.application.record_lineage as lineage_module
from my_pa.application.commands import ReadRelatedRecords
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.canonical import canonical_json
from my_pa.domain.lineage.vocabulary import LINEAGE_RELATED_DIGEST_PREFIX
from my_pa.domain.source.registry import issue_identifier
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_record_harness import NOTE_BODY, note_anchor, originated_from
from tests.database.lineage_s2_harness import assertion
from tests.database.lineage_s3_harness import corroborates
from tests.database.lineage_s3_read_harness import grant, horizon
from tests.database.lineage_s31_harness import GATEWAY, S31Runtime, client_grants

pytestmark = pytest.mark.database

_RELATED: Final = Capability.RECORDS_LINEAGE_RELATED
#: The read stamps `related_sha256` excludes (section 7.4 step 8).
_STAMPS: Final = ("known_at", "valid_at", "lineage_valid_at", "native_cut_at", "next_cursor")


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _related(
    runtime: S31Runtime,
    seeds: list[tuple[str, str]],
    **kwargs: Any,  # noqa: ANN401
) -> ReadRelatedRecords:
    return ReadRelatedRecords(
        seeds=tuple({"family": family, "record_id": record_id} for family, record_id in seeds),
        **kwargs,
    )


def _records(answer: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(record["family"], record["record_id"]): record for record in answer["records"]}


def _links(answer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {link["link_id"]: link for link in answer["links"]}


def _scene(runtime: S31Runtime, key: str) -> dict[str, str]:
    """Issue I with an operator `work` member T; a Meeting M with note N.

    The operator asserts that Commitment C originated from N (context I); a
    client asserts, with its claim, that N discusses T (context I) and, with no
    context, that T blocks T2. So from T: I, N and T2 one hop away, C and M at
    depth 2 under I.
    """
    issue = runtime.issue(f"{key}-issue")
    task = runtime.task(f"{key}-t")
    other = runtime.task(f"{key}-t2")
    commitment = runtime.commitment(f"{key}-c")
    meeting_id, note_id = runtime.note(f"{key}-n")
    member = runtime.member(issue, "task", task, f"{key}-t", "work")
    origin = runtime.ok(
        originated_from(
            "commitment",
            commitment,
            "meeting_note_version",
            note_id,
            f"{key}-origin",
            (note_anchor(meeting_id, note_id, NOTE_BODY),),
            context_issue_id=issue,
        ),
        surface=GATEWAY,
    )["association"]["link_id"]
    discusses = runtime.local_ok(
        _with_claim(
            assertion(
                "discusses",
                ("meeting_note_version", note_id),
                ("task", task),
                f"{key}-discusses",
                (note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
                context=issue,
            )
        )
    )["association"]["link_id"]
    blocks = runtime.local_ok(
        assertion(
            "blocks",
            ("task", task),
            ("task", other),
            f"{key}-blocks",
            (corroborates(meeting_id, note_id),),
        )
    )["association"]["link_id"]
    return {
        "issue": issue,
        "task": task,
        "other": other,
        "commitment": commitment,
        "meeting": meeting_id,
        "note": note_id,
        "member": member,
        "origin": origin,
        "discusses": discusses,
        "blocks": blocks,
    }


def _with_claim(command: Any) -> Any:  # noqa: ANN401
    from dataclasses import replace

    return replace(command, user_directed=True)


def test_related_returns_issue_context_predecessors_successors_and_evidence(
    runtime: S31Runtime,
) -> None:
    scene = _scene(runtime, "rel-basic")
    answer = runtime.ok(_related(runtime, [("task", scene["task"])]))
    records = _records(answer)
    assert set(records) == {
        ("task", scene["task"]),
        ("situation", scene["issue"]),
        ("meeting_note_version", scene["note"]),
        ("task", scene["other"]),
        ("commitment", scene["commitment"]),
        ("meeting", scene["meeting"]),
    }
    depth = {ref: record["depth"] for ref, record in records.items()}
    assert depth[("task", scene["task"])] == 0
    assert depth[("situation", scene["issue"])] == 1
    assert depth[("meeting_note_version", scene["note"])] == 1
    assert depth[("task", scene["other"])] == 1
    assert depth[("commitment", scene["commitment"])] == 2
    assert depth[("meeting", scene["meeting"])] == 2
    # Every record names the one seed; the Issue-confined ones name the Issue,
    # the one-hop-only `blocks` successor names none.
    assert {tuple(record["seeds"]) for record in records.values()} == {(0,)}
    assert records[("commitment", scene["commitment"])]["issue_ids"] == [scene["issue"]]
    assert records[("task", scene["other"])]["issue_ids"] == []
    assert records[("task", scene["task"])]["reached_from"] is None
    assert records[("commitment", scene["commitment"])]["reached_via"] == {
        "edge": "typed",
        "link_id": scene["origin"],
    }
    links = _links(answer)
    assert set(links) == {scene["member"], scene["origin"], scene["discusses"], scene["blocks"]}
    # Evidence: the exact version and code-point passage, never a digest.
    (anchor,) = links[scene["origin"]]["evidence"]
    start = NOTE_BODY.index("façade survey")
    assert (anchor["version_id"], anchor["passage_start_cp"], anchor["passage_end_cp"]) == (
        scene["note"],
        start,
        start + len("façade survey"),
    )
    assert not any("sha256" in key for key in anchor)
    # Provenance labels (section 4.3).
    assert links[scene["origin"]]["acceptance_basis"] == "user_confirmed"
    assert links[scene["discusses"]]["acceptance_basis"] == "client_identified"
    assert links[scene["discusses"]]["user_directed_claim"] is True
    assert links[scene["blocks"]]["user_directed_claim"] is False
    assert answer["virtual_edges"] == [
        {
            "edge_type": "meeting_note_version_of",
            "from": {"family": "meeting_note_version", "record_id": scene["note"]},
            "to": {"family": "meeting", "record_id": scene["meeting"]},
        }
    ]
    assert answer["complete_state"] == "complete"
    assert answer["seeds"] == [{"family": "task", "record_id": scene["task"]}]
    assert answer["next_cursor"] is None


def test_related_never_crosses_issues_through_a_shared_meeting(runtime: S31Runtime) -> None:
    """AT-006: a Meeting in 2 Issues never bridges them, at any depth."""
    meeting_id, note_id = runtime.note("rel-shared")
    first, second = runtime.issue("rel-shared-1"), runtime.issue("rel-shared-2")
    task_one, task_two = runtime.task("rel-shared-t1"), runtime.task("rel-shared-t2")
    runtime.member(first, "task", task_one, "rel-shared-t1", "work")
    runtime.member(second, "task", task_two, "rel-shared-t2", "work")
    runtime.member(first, "meeting", meeting_id, "rel-shared-m1", "discussion")
    runtime.member(second, "meeting", meeting_id, "rel-shared-m2", "discussion")
    for issue, task, passage in ((first, task_one, "Decisions"), (second, task_two, "pour")):
        runtime.local_ok(
            assertion(
                "discusses",
                ("meeting_note_version", note_id),
                ("task", task),
                f"rel-shared-{task}",
                (note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion", passage=passage),),
                context=issue,
            )
        )
    answer = runtime.ok(_related(runtime, [("task", task_one)], max_depth=3))
    records = _records(answer)
    assert ("meeting", meeting_id) in records
    assert ("situation", second) not in records
    assert ("task", task_two) not in records
    # Seeded from the shared Meeting, both Issues are reached -- each only
    # under itself.
    both = _records(runtime.ok(_related(runtime, [("meeting", meeting_id)], max_depth=3)))
    assert both[("task", task_one)]["issue_ids"] == [first]
    assert both[("task", task_two)]["issue_ids"] == [second]


def test_related_filters_by_acceptance_basis_and_relation(runtime: S31Runtime) -> None:
    scene = _scene(runtime, "rel-filter")
    seed = [("task", scene["task"])]
    client = runtime.ok(_related(runtime, seed, acceptance_bases=("client_identified",)))
    # Only the client's links are followed and emitted: the operator's
    # membership and origin are neither, so the Issue and C are not reached.
    assert set(_links(client)) == {scene["discusses"], scene["blocks"]}
    assert set(_records(client)) == {
        ("task", scene["task"]),
        ("meeting_note_version", scene["note"]),
        ("meeting", scene["meeting"]),
        ("task", scene["other"]),
    }
    operator = runtime.ok(_related(runtime, seed, acceptance_bases=("user_confirmed",)))
    assert set(_links(operator)) == {scene["member"]}
    blocks = runtime.ok(_related(runtime, seed, relation_types=("blocks",)))
    assert set(_links(blocks)) == {scene["blocks"]}
    assert set(_records(blocks)) == {("task", scene["task"]), ("task", scene["other"])}
    # The filters are a set: order and the default both name the same request.
    either = runtime.ok(
        _related(runtime, seed, acceptance_bases=("client_identified", "user_confirmed"))
    )
    reordered = runtime.ok(
        _related(runtime, seed, acceptance_bases=("user_confirmed", "client_identified"))
    )
    default = runtime.ok(_related(runtime, seed))
    assert either["related_sha256"] == reordered["related_sha256"] == default["related_sha256"]
    for field, value in (
        ("acceptance_bases", ("client_identified", "client_identified")),
        ("relation_types", ("blocks", "blocks")),
        ("acceptance_bases", ()),
        ("relation_types", ("not_a_relation",)),
    ):
        _refused_request(seed, field, **{field: value})


def _refused_request(seeds: list[tuple[str, str]], detail: str, **kwargs: Any) -> None:  # noqa: ANN401
    """A malformed request is `invalid_request` naming `detail`, before any read."""
    with pytest.raises(InvalidRequestError) as refused:
        ReadRelatedRecords(
            seeds=tuple({"family": family, "record_id": record_id} for family, record_id in seeds),
            **kwargs,
        )
    assert [str(item) for item in refused.value.safe_details] == [detail]


def _fan(runtime: S31Runtime, key: str, count: int) -> tuple[str, list[str], str]:
    """A seed Task blocking `count` Tasks (no context), each link a client's."""
    meeting_id, note_id = runtime.note(f"{key}-src")
    seed = runtime.task(f"{key}-seed")
    blocked = []
    for index in range(count):
        target = runtime.task(f"{key}-{index}")
        blocked.append(target)
        runtime.local_ok(
            assertion(
                "blocks",
                ("task", seed),
                ("task", target),
                f"{key}-{index}",
                (corroborates(meeting_id, note_id),),
            )
        )
    return seed, blocked, note_id


def _pages(
    runtime: S31Runtime,
    seeds: list[tuple[str, str]],
    **kwargs: Any,  # noqa: ANN401
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = runtime.ok(_related(runtime, seeds, page_size=10, cursor=cursor, **kwargs))
        found.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return found
        assert len(found) < 50


def _items(answer: dict[str, Any]) -> list[Any]:
    return [*answer["records"], *answer["links"], *answer["virtual_edges"]]


def test_related_order_is_deterministic_and_pages_union_to_one_answer(
    runtime: S31Runtime,
) -> None:
    seed, _blocked, _note = _fan(runtime, "rel-pages", 8)
    scene = _scene(runtime, "rel-pages-b")
    seeds = [("task", seed), ("task", scene["task"])]
    whole = runtime.ok(_related(runtime, seeds))
    again = runtime.ok(_related(runtime, seeds))
    assert _items(whole) == _items(again)
    assert whole["related_sha256"] == again["related_sha256"]
    order = [
        (record["depth"], record["family"], record["record_id"]) for record in whole["records"]
    ]
    assert order == sorted(order)
    assert [link["link_id"] for link in whole["links"]] == sorted(
        link["link_id"] for link in whole["links"]
    )
    pages = _pages(runtime, seeds)
    assert len(pages) > 2
    union = [item for page in pages for item in _items(page)]
    assert union == _items(whole)
    assert {page["related_sha256"] for page in pages} == {whole["related_sha256"]}
    # Seed positions: the second seed's records name position 1.
    assert _records(whole)[("task", scene["task"])]["seeds"] == [1]
    assert _records(whole)[("task", seed)]["seeds"] == [0]


def test_a_grant_change_between_pages_restarts(runtime: S31Runtime) -> None:
    seed, _blocked, _note = _fan(runtime, "rel-scope", 12)
    grants = client_grants(_RELATED)
    first = runtime.client_ok(_related(runtime, [("task", seed)], page_size=10), grants=grants)
    assert first["next_cursor"] is not None
    same = runtime.client_ok(
        _related(runtime, [("task", seed)], page_size=10, cursor=first["next_cursor"]),
        grants=grants,
    )
    assert same["complete_state"] != "scope_changed_restart_required"
    # A family read revoked between pages: every later page restarts.
    narrowed = client_grants(_RELATED, without=("constraints.read",))
    restarted = runtime.client_ok(
        _related(runtime, [("task", seed)], page_size=10, cursor=first["next_cursor"]),
        grants=narrowed,
    )
    assert restarted["complete_state"] == "scope_changed_restart_required"
    assert _items(restarted) == []
    assert restarted["next_cursor"] is None


def test_hidden_records_are_never_emitted_or_counted(
    runtime: S31Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A remote reader without Task visibility: no Task, no link to one, nothing counted."""
    scene = _scene(runtime, "rel-hidden")
    seed = [("meeting_note_version", scene["note"])]
    hidden = client_grants(_RELATED, without=("tasks.read",))
    answer = runtime.client_ok(_related(runtime, seed, max_depth=3), grants=hidden)
    records = _records(answer)
    assert not any(family == "task" for family, _ in records)
    for link in answer["links"]:
        assert "task" not in {link["from"]["family"], link["to"]["family"]}
    assert "restricted_evidence" in answer["qualifiers"]
    visible = len(records)
    # With the node budget exactly the visible count, nothing is truncated:
    # the hidden Tasks never consumed a node.
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_NODES", visible)
    bounded = runtime.client_ok(_related(runtime, seed, max_depth=3), grants=hidden)
    assert "truncated_budget" not in bounded["qualifiers"]
    assert _records(bounded) == records


def test_related_budgets_truncate(runtime: S31Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    seed, _blocked, _note = _fan(runtime, "rel-budget", 6)
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_NODES", 4)
    nodes = runtime.ok(_related(runtime, [("task", seed)]))
    assert nodes["complete_state"] == "truncated_budget"
    assert len(nodes["records"]) == 4
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_NODES", 250)
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_EDGES", 3)
    edges = runtime.ok(_related(runtime, [("task", seed)]))
    assert edges["complete_state"] == "truncated_budget"
    assert len(edges["links"]) + len(edges["virtual_edges"]) <= 3
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_EDGES", 400)
    # More visible Issues than the per-seed cap: the extra Issues are not
    # expanded, and the answer says so.
    task = runtime.task("rel-budget-member")
    for index in range(3):
        issue = runtime.issue(f"rel-budget-{index}")
        runtime.member(issue, "task", task, f"rel-budget-{index}", "work")
    monkeypatch.setattr(lineage_module, "MAX_MATCHING_ISSUES", 2)
    capped = runtime.ok(_related(runtime, [("task", task)]))
    assert "truncated_budget" in capped["qualifiers"]
    assert len(_records(capped)[("task", task)]["issue_ids"]) == 2


def _digest_of(answer: dict[str, Any], **request: Any) -> str:  # noqa: ANN401
    document = {
        "schema_version": 1,
        "seeds": answer["seeds"],
        "max_depth": request["max_depth"],
        "acceptance_bases": request["acceptance_bases"],
        "relation_types": request["relation_types"],
        "records": answer["records"],
        "links": answer["links"],
        "virtual_edges": answer["virtual_edges"],
        "complete_state": answer["complete_state"],
        "qualifiers": answer["qualifiers"],
    }
    body = LINEAGE_RELATED_DIGEST_PREFIX + canonical_json(document).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def test_the_related_digest_is_stable_and_excludes_read_stamps(runtime: S31Runtime) -> None:
    scene = _scene(runtime, "rel-digest")
    seed = [("task", scene["task"])]
    first = runtime.ok(_related(runtime, seed))
    second = runtime.ok(_related(runtime, seed))
    assert first["native_cut_at"] != second["native_cut_at"]
    assert first["related_sha256"] == second["related_sha256"]
    every_relation = [
        "issue_member",
        "originated_from",
        "discusses",
        "delegated_from",
        "escalated_from",
        "blocks",
        "created_to_resolve",
        "related_context",
    ]
    assert first["related_sha256"] == _digest_of(
        first,
        max_depth=2,
        acceptance_bases=["user_confirmed", "client_identified"],
        relation_types=every_relation,
    )
    for stamp in _STAMPS:
        assert stamp in first
    # A remote reader's digest is over what it is answered (no client ids).
    remote = runtime.client_ok(_related(runtime, seed), grants=client_grants(_RELATED))
    assert remote["related_sha256"] == _digest_of(
        remote,
        max_depth=2,
        acceptance_bases=["user_confirmed", "client_identified"],
        relation_types=every_relation,
    )


def test_a_foreign_or_invisible_seed_is_not_found(runtime: S31Runtime) -> None:
    scene = _scene(runtime, "rel-seed")
    foreign = runtime.task("rel-seed-foreign", principal_id=OTHER_PRINCIPAL)
    absent = issue_identifier(IdKind.TASK)
    for seeds in (
        [("task", absent)],
        [("task", scene["task"]), ("task", foreign)],
        [("task", foreign), ("task", scene["task"])],
    ):
        refused = runtime.refused(_related(runtime, seeds))
        assert (refused["code"], refused.get("safe_details")) == ("not_found", ["seeds"])
    hidden = client_grants(_RELATED, without=("tasks.read",))
    invisible = runtime.client_refused(_related(runtime, [("task", scene["task"])]), grants=hidden)
    absent_remote = runtime.client_refused(_related(runtime, [("task", absent)]), grants=hidden)
    assert invisible == {**absent_remote, "correlation_id": invisible["correlation_id"]}
    assert (invisible["code"], invisible.get("safe_details")) == ("not_found", ["seeds"])
    # Malformed seed lists are refused before any read.
    for seeds in (
        [],
        [("task", scene["task"]), ("task", scene["task"])],
        [("task", issue_identifier(IdKind.TASK)) for _ in range(26)],
        [("task", "cmt_notatask00001")],
    ):
        _refused_request(seeds, "seeds")
    _refused_request([("task", scene["task"])], "cursor", cursor="AAAA")
    # A remote reader without the related grant is refused as unsupported.
    ungranted = runtime.client_refused(
        _related(runtime, [("task", scene["task"])]),
        grants=client_grants(Capability.RECORDS_LINEAGE) - grant("records.lineage.related"),
    )
    assert ungranted["code"] == "unsupported"
    assert PRINCIPAL != OTHER_PRINCIPAL


def test_an_explicit_known_at_reproduces_an_earlier_answer(runtime: S31Runtime) -> None:
    scene = _scene(runtime, "rel-asof")
    seed = [("task", scene["task"])]
    cut = horizon(runtime.engine)
    before = runtime.ok(_related(runtime, seed, known_at=cut))
    later = runtime.task("rel-asof-later")
    meeting_id, note_id = scene["meeting"], scene["note"]
    runtime.local_ok(
        assertion(
            "blocks",
            ("task", scene["task"]),
            ("task", later),
            "rel-asof-later",
            (corroborates(meeting_id, note_id),),
        )
    )
    now = runtime.ok(_related(runtime, seed))
    assert ("task", later) in _records(now)
    again = runtime.ok(_related(runtime, seed, known_at=cut))
    assert ("task", later) not in _records(again)
    assert again["related_sha256"] == before["related_sha256"]
    assert {key: value for key, value in again.items() if key != "native_cut_at"} == {
        key: value for key, value in before.items() if key != "native_cut_at"
    }
