"""AT-001 (S3 part): every root recovers the same Issue graph as known at one cut.

S3 contract section 10's "AT-001 S3 part, concretely", on the S2 fourteen-stage
fixture (`test_issue_lineage_14step.Workflow`), through `ApplicationService.invoke`:

* at `known_at = valid_at =` the horizon after stage 14, all 14 roots return one
  node set, one typed-edge set and one virtual-edge set, `complete`;
* at `H9`, the horizon after stage 9, the 12 roots that exist and are related
  then return the stage-9 graph, byte-identically before and after stages 10 to
  14 commit;
* M4 and N4 (stage 12) at `H9` match no Issue: with `issue_id` the read is
  `not_found`, without it the one-hop read follows nothing and N4 is no virtual
  edge;
* paging every root at `page_size` 10 to the end reproduces the one-page answer;
* every node's `reached_from` chain ends at its root;
* a remote reader without a Meeting read sees no Meeting or note node, no
  `discusses` edge and no note anchor, and is told only `restricted_evidence`.

Every identity and every body is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Final

import pytest

from tests.database.lineage_s3_read_harness import (
    S3ReadRuntime,
    edge_ids,
    grant,
    horizon,
    lineage_request,
    node_set,
    union,
    virtual_set,
)
from tests.integration.test_issue_lineage_14step import _FAMILY, ROOTS, Workflow

pytestmark = pytest.mark.database

#: The roots that exist and are related at stage 9 (S3 section 10).
STAGE_9_ROOTS: Final = ("M1", "M2", "M3", "N1", "N2", "N3", "C1", "C2", "C3", "T1", "X1", "I")


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _root(flow: Workflow, name: str) -> tuple[str, str]:
    return (_FAMILY[name[0]], flow.ids[name])


def _sets(answer: dict[str, Any]) -> tuple[Any, ...]:
    return (node_set(answer), edge_ids(answer), virtual_set(answer), answer["complete_state"])


def test_every_root_yields_the_same_graph_at_one_known_at_and_valid_at(
    runtime: S3ReadRuntime,
) -> None:
    flow = Workflow(runtime).run(14)
    cut = horizon(runtime.engine)
    answers = {
        name: runtime.lineage(_root(flow, name), issue_id=flow.ids["I"], known_at=cut, valid_at=cut)
        for name in ROOTS
    }
    expected = answers["I"]
    assert node_set(expected) == flow.refs(*ROOTS)
    assert len(edge_ids(expected)) == 21
    assert expected["complete_state"] == "complete"
    for name, answer in answers.items():
        assert _sets(answer) == _sets(expected), name
        assert (answer["known_at"], answer["valid_at"], answer["lineage_valid_at"]) == (
            cut,
            cut,
            cut,
        ), name
        assert answer["qualifiers"] == ["complete"], name


def test_the_stage_9_answer_of_the_12_stage_9_roots_is_unchanged_after_stage_14(
    runtime: S3ReadRuntime,
) -> None:
    seen: dict[str, Any] = {}

    def at_stage_9(flow: Workflow) -> None:
        seen["H9"] = horizon(runtime.engine)
        seen["current"] = flow.from_issue()
        seen["answers"] = {
            name: runtime.lineage(_root(flow, name), issue_id=flow.ids["I"], known_at=seen["H9"])
            for name in STAGE_9_ROOTS
        }

    flow = Workflow(runtime)
    flow.after[9] = at_stage_9
    flow.run(14)
    stage_9 = seen["answers"]["I"]
    # The stage-9 graph: what I's current read returned right after stage 9.
    assert node_set(stage_9) == seen["current"]["nodes"]
    assert edge_ids(stage_9) == seen["current"]["edges"]
    assert node_set(stage_9) == flow.refs(
        "I", "M1", "N1", "C1", "T1", "M2", "N2", "X1", "C2", "C3", "M3", "N3"
    )
    for name in STAGE_9_ROOTS:
        before = seen["answers"][name]
        assert _sets(before) == _sets(stage_9), name
        # Byte-identical after stages 10 to 14 committed (the native cut is H9 too).
        assert (
            runtime.lineage(_root(flow, name), issue_id=flow.ids["I"], known_at=seen["H9"])
            == before
        ), name
        assert before["native_cut_at"] == seen["H9"], name
    # The Issue is open at H9 though it is closed now.
    (match,) = stage_9["issues_matching_root"]
    assert match["state"] == "open"
    assert flow.issue()["state"] == "closed"


def test_m4_and_n4_at_the_stage_9_cut_match_no_issue(runtime: S3ReadRuntime) -> None:
    seen: dict[str, str] = {}
    flow = Workflow(runtime)
    flow.after[9] = lambda _flow: seen.setdefault("H9", horizon(runtime.engine))
    flow.run(14)
    for name in ("M4", "N4"):
        root = _root(flow, name)
        error = runtime.refused(_command(root, issue_id=flow.ids["I"], known_at=seen["H9"]))
        assert (error["code"], error["safe_details"]) == ("not_found", ["issue_id"]), name
        answer = runtime.lineage(root, known_at=seen["H9"])
        assert answer["issues_matching_root"] == [], name
        assert answer["selected_issue_id"] is None, name
        assert node_set(answer) == {root}, name
        assert answer["typed_edges"] == [] and answer["virtual_native_edges"] == [], name
        # Now, both match I and N4 is M4's virtual note edge.
        now = runtime.lineage(root)
        assert [m["issue_id"] for m in now["issues_matching_root"]] == [flow.ids["I"]], name
        assert (flow.ids["N4"], flow.ids["M4"]) in virtual_set(now), name


def _command(root: tuple[str, str], **fields: Any) -> Any:  # noqa: ANN401
    return lineage_request(root, fields)[0]


def test_paging_from_every_root_exhausts_to_the_one_page_answer(runtime: S3ReadRuntime) -> None:
    flow = Workflow(runtime).run(14)
    cut = horizon(runtime.engine)
    for name in ROOTS:
        root = _root(flow, name)
        whole = runtime.lineage(root, issue_id=flow.ids["I"], known_at=cut)
        pages = runtime.pages(root, issue_id=flow.ids["I"], known_at=cut, page_size=10)
        items = len(whole["nodes"]) + len(whole["typed_edges"]) + len(whole["virtual_native_edges"])
        assert len(pages) == -(-items // 10), name
        merged = union(pages)
        assert merged["nodes"] == whole["nodes"], name
        assert merged["typed_edges"] == whole["typed_edges"], name
        assert merged["virtual_native_edges"] == whole["virtual_native_edges"], name
        for page in pages:
            assert (
                len(page["nodes"]) + len(page["typed_edges"]) + len(page["virtual_native_edges"])
                <= 10
            ), name
            for key in ("root", "selected_issue_id", "issues_matching_root", "complete_state"):
                assert page[key] == whole[key], (name, key)
            assert page["known_at"] == whole["known_at"] == cut, name


def test_every_node_explains_its_path_to_the_root(runtime: S3ReadRuntime) -> None:
    flow = Workflow(runtime).run(14)
    for name in ROOTS:
        root = _root(flow, name)
        answer = runtime.lineage(root, issue_id=flow.ids["I"])
        nodes = {(node["family"], node["record_id"]): node for node in answer["nodes"]}
        edges = {edge["link_id"]: edge for edge in answer["typed_edges"]}
        virtual = virtual_set(answer)
        for key, node in nodes.items():
            if key == root:
                assert (node["reached_from"], node["reached_via"], node["depth"]) == (
                    None,
                    None,
                    0,
                ), name
                continue
            parent = (node["reached_from"]["family"], node["reached_from"]["record_id"])
            assert parent in nodes, (name, key)
            via = node["reached_via"]
            if via["edge"] == "typed":
                edge = edges[via["link_id"]]
                ends = {
                    (edge["from"]["family"], edge["from"]["record_id"]),
                    (edge["to"]["family"], edge["to"]["record_id"]),
                }
                assert ends == {parent, key}, (name, key)
            else:
                assert via == {"edge": "virtual", "edge_type": "meeting_note_version_of"}
                pair = {parent[1], key[1]}
                assert any(set(edge) == pair for edge in virtual), (name, key)
            # Following reached_from ends at the root, without a cycle.
            hops, step = 0, key
            while step != root:
                parent_view = nodes[step]["reached_from"]
                step = (parent_view["family"], parent_view["record_id"])
                hops += 1
                assert hops <= len(nodes), (name, key)


def test_a_remote_reader_without_the_meeting_grant_sees_no_note_node_and_no_count(
    runtime: S3ReadRuntime,
) -> None:
    flow = Workflow(runtime).run(14)
    grants = grant(
        "records.lineage", "issues.read", "tasks.read", "commitments.read", "constraints.read"
    )
    local = runtime.lineage(("situation", flow.ids["I"]), issue_id=flow.ids["I"])
    for name in ("I", "T1", "C1", "X1"):
        answer = runtime.lineage(_root(flow, name), issue_id=flow.ids["I"], grants=grants)
        families = {family for family, _ in node_set(answer)}
        assert families <= {"situation", "task", "commitment", "constraint"}, name
        assert not families & {"meeting", "meeting_note_version"}, name
        assert answer["virtual_native_edges"] == [], name
        relations = {edge["relation_type"] for edge in answer["typed_edges"]}
        assert "discusses" not in relations, name
        anchors = [anchor for edge in answer["typed_edges"] for anchor in edge["evidence"]]
        assert all(anchor["family"] not in {"meeting_note_version"} for anchor in anchors), name
        assert answer["complete_state"] == "restricted_evidence", name
        assert answer["qualifiers"] == ["restricted_evidence"], name
        rendered = json.dumps(answer)
        # No count, and no identifier of a hidden record anywhere.
        assert not any("count" in key or "hidden" in key for key in _keys(answer)), name
        for family, record_id in node_set(local):
            if family in {"meeting", "meeting_note_version"}:
                assert record_id not in rendered, name
    # The Meeting root itself answers as absent.
    error = runtime.refused(_command(_root(flow, "M1"), issue_id=flow.ids["I"]), grants=grants)
    assert (error["code"], error["safe_details"]) == ("not_found", ["origin"])


def _keys(document: object) -> set[str]:
    found: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(document, list):
        for item in document:
            found |= _keys(item)
    return found
