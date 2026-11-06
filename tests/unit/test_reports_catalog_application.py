"""Reports Modernization WP04: `reports.list`/`reports.search` in the standalone and all planes.

FAST tier over `FakeUnitOfWork` (the in-memory general report plane and the
in-memory intelligence store; `tests/database/` is the authority on SQL
ranking). Covers contract C1 (the plane selector and the presence rule both
ways), C3 (filters, lifecycle default/explicit, bounds), C4 (item shapes, no
counts, no content, no Base64), C5 (the bound cursor and every refusal of it)
and C6 (the `all` merge order with ties, across a page boundary).
"""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.errors import ApplicationError, InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.intelligence.catalog import ArtifactKind, ArtifactState, IntelligenceStage
from my_pa.domain.intelligence.models import IntelligenceArtifact, content_digest
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from tests.conftest import WHEN, Scene, build_service, operator

BODY: Final = "# Curlew\n\nThe secret body text about curlews."
STANDALONE_KEYS: Final = {
    "plane",
    "report_id",
    "title",
    "type",
    "topics",
    "tags",
    "summary",
    "report_date",
    "lifecycle_state",
    "lifecycle_revision",
    "head_version_id",
    "head_version_number",
    "created_at",
    "updated_at",
    "creator",
    # WP05b B7: the root's hold cache.
    "held",
}
INTELLIGENCE_KEYS: Final = {
    "plane",
    "report_id",
    "title",
    "type",
    "report_date",
    "created_at",
    "cycle_run_id",
    "stage",
    "artifact_kind",
    "focus_area_id",
    "source_lane",
    "content_sha256",
    "artifact_state",
}
LEGACY_ONLY: Final = {
    "cycle_run_id": "micr_aaaaaaaa11111111",
    "stage": "collector",
    "artifact_kind": "collector_candidates",
    "focus_area_id": "communications",
    "source_lane": "outlook",
    "report_date": "2026-08-20",
    "include_superseded": False,
}
CATALOG_ONLY: Final[dict[str, object]] = {
    "type": "survey",
    "topics": ["birds"],
    "tags": ["field"],
    "associated_with": {"target_kind": "external_source", "target_ref": "https://example.test/a"},
    "lifecycle_states": ["active"],
    "created_from": "2026-01-01T00:00:00Z",
    "created_to": "2027-01-01T00:00:00Z",
    "report_date_from": "2026-01-01",
    "report_date_to": "2026-12-31",
    "created_by": "gcrt_" + "0" * 40,
}


def _wire(scene: Scene, capability: Capability, payload: dict[str, Any]) -> dict[str, Any]:
    (purpose,) = permitted_purposes(capability)
    return {
        "request_id": f"req-{capability.value}",
        "purpose": purpose.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-11-05T12:00:00Z",
        "payload": payload,
    }


def _invoke(
    service: ApplicationService,
    scene: Scene,
    capability: Capability,
    payload: dict[str, Any],
    *,
    principal: Principal | None = None,
) -> dict[str, Any]:
    metadata, command = normalize(capability.value, _wire(scene, capability, payload))
    envelope = service.invoke(metadata, command, principal=principal or scene.principal)
    return envelope.model_dump(mode="json")


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _refused(capability: Capability, payload: dict[str, Any]) -> InvalidRequestError:
    with pytest.raises(ApplicationError) as refused:
        normalize(
            capability.value,
            {
                "request_id": "req",
                "purpose": "report_read",
                "principal_id": "prn_aaaa0001aaaa0001aaaa0001",
                "requested_at": "2026-11-05T12:00:00Z",
                "payload": payload,
            },
        )
    assert isinstance(refused.value, InvalidRequestError)
    assert refused.value.__context__ is None
    return refused.value


def _query(capability: Capability) -> dict[str, Any]:
    """A valid `query` where the capability has one, so a refusal is about the field tested."""
    return {"query": "curlew"} if capability is Capability.REPORTS_SEARCH else {}


def _publish(
    service: ApplicationService,
    scene: Scene,
    index: int,
    **fields: Any,  # noqa: ANN401
) -> str:
    payload: dict[str, Any] = {
        "title": f"Curlew survey {index}",
        "content": {"format": "markdown", "body": BODY},
        "idempotency_key": f"catalog-{index}",
        "client_intent_id": f"catalog-{index}",
        **fields,
    }
    return str(_ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, payload))["report_id"])


def _set_created(scene: Scene, report_id: str, at: datetime) -> None:
    key = (scene.principal.principal_id, report_id)
    stored = scene.world.general_report_versions[key]
    scene.world.general_report_versions[key] = replace(
        stored, root=replace(stored.root, created_at=at)
    )


def _legacy(
    scene: Scene, artifact_id: str, *, at: datetime = WHEN, title: str = "Curlew brief"
) -> None:
    body = "legacy body about curlews"
    scene.world.intelligence.artifacts[(scene.principal.principal_id, artifact_id)] = (
        IntelligenceArtifact(
            artifact_id=artifact_id,
            principal_id=scene.principal.principal_id,
            cycle_run_id="micr_catalogcycle0001",
            producer_run_id="rrun_catalogrun00001",
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES.value,
            report_date=date(2026, 8, 20),
            title=title,
            body_markdown=body,
            content_sha256=content_digest(body),
            content_bytes=len(body.encode("utf-8")),
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            generated_at=at,
            committed_at=at,
            version=1,
            is_current=True,
        )
    )


def _ids(result: dict[str, Any]) -> list[str]:
    return [item["report_id"] for item in result["items"]]


def _walk(
    service: ApplicationService, scene: Scene, capability: Capability, payload: dict[str, Any]
) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(50):
        page = _ok(
            _invoke(
                service,
                scene,
                capability,
                payload if cursor is None else {**payload, "cursor": cursor},
            )
        )
        seen.extend(_ids(page))
        cursor = page["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("the walk did not end")


# ---- the plane selector and the presence rule ------------------------------------------


@pytest.mark.parametrize("capability", [Capability.REPORTS_LIST, Capability.REPORTS_SEARCH])
@pytest.mark.parametrize("plane", ["", "Standalone", "both", 1, None])
def test_an_invalid_plane_names_plane_with_its_vocabulary(
    capability: Capability, plane: object
) -> None:
    refusal = _refused(capability, {**_query(capability), "plane": plane})
    assert refusal.safe_details == (SafeDetail.PLANE,)
    assert refusal.allowed_values == {SafeDetail.PLANE: ("intelligence", "standalone", "all")}


@pytest.mark.parametrize("capability", [Capability.REPORTS_LIST, Capability.REPORTS_SEARCH])
@pytest.mark.parametrize("plane", ["standalone", "all"])
@pytest.mark.parametrize("name", sorted(LEGACY_ONLY))
def test_a_pipeline_field_is_a_bare_refusal_in_standalone_and_all(
    capability: Capability, plane: str, name: str
) -> None:
    for value in (LEGACY_ONLY[name], None):
        refusal = _refused(capability, {**_query(capability), "plane": plane, name: value})
        assert refusal.safe_details == ()


@pytest.mark.parametrize(
    ("capability", "name"),
    [(Capability.REPORTS_LIST, name) for name in sorted(CATALOG_ONLY)]
    # The pipeline list has always had a cursor; the pipeline search never had one.
    + [(Capability.REPORTS_SEARCH, name) for name in sorted({*CATALOG_ONLY, "cursor"})],
)
@pytest.mark.parametrize("plane", [None, "intelligence"])
def test_a_catalog_field_is_a_bare_refusal_in_the_pipeline_plane(
    capability: Capability, plane: str | None, name: str
) -> None:
    selected = {} if plane is None else {"plane": plane}
    for value in (CATALOG_ONLY.get(name, "token"), None):
        refusal = _refused(capability, {**_query(capability), **selected, name: value})
        assert refusal.safe_details == ()


# ---- the standalone plane ---------------------------------------------------------------


def test_the_standalone_list_shape_has_no_count_and_no_content(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _publish(
        service,
        scene,
        1,
        type="survey",
        topics=["birds"],
        tags=["field"],
        summary="A short summary.",
        report_date="2026-08-20",
    )
    _legacy(scene, "rpt_legacycatalog01")
    answer = _invoke(service, scene, Capability.REPORTS_LIST, {"plane": "standalone"})
    result = _ok(answer)
    assert set(result) == {"plane", "items", "next_cursor"}
    assert result["plane"] == "standalone"
    assert result["next_cursor"] is None
    (item,) = result["items"]
    assert set(item) == STANDALONE_KEYS
    assert item == {
        "plane": "standalone",
        "report_id": report_id,
        "title": "Curlew survey 1",
        "type": "survey",
        "topics": ["birds"],
        "tags": ["field"],
        "summary": "A short summary.",
        "report_date": "2026-08-20",
        "lifecycle_state": "active",
        "lifecycle_revision": 0,
        "head_version_id": item["head_version_id"],
        "head_version_number": 1,
        "created_at": "2026-08-02T12:00:00.000Z",
        "updated_at": "2026-08-02T12:00:00.000Z",
        # WP05 A4: the server-derived creator (here the local Principal).
        "creator": {
            "kind": "local_principal",
            "id": derive_creator(
                CreatorKind.LOCAL_PRINCIPAL, scene.principal.principal_id
            ).creator_id,
        },
        # WP05b B7: the root's hold cache, never a reason, actor or seal.
        "held": False,
    }
    assert item["head_version_id"].startswith("grver_")
    assert answer["disclosure"]["truncation"] == {
        "is_truncated": False,
        "reason": None,
        "next_cursor": None,
    }
    rendered = json.dumps(answer)
    assert "secret body" not in rendered
    assert base64.b64encode(BODY.encode()).decode()[:16] not in rendered
    assert "count" not in rendered and "total" not in rendered


def test_the_lifecycle_default_is_active_and_withdrawn_appear_only_when_listed(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    active = _publish(service, scene, 1)
    archived = _publish(service, scene, 2)
    trashed = _publish(service, scene, 3)
    move = {"expected_lifecycle_revision": 0}
    _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_ARCHIVE,
            {"report_id": archived, "idempotency_key": "a", **move},
        )
    )
    _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_DELETE,
            {"report_id": trashed, "idempotency_key": "d", **move},
        )
    )

    def listed(states: list[str] | None, capability: Capability) -> set[str]:
        payload: dict[str, Any] = {"plane": "standalone", "query": "curlew"}
        if capability is Capability.REPORTS_LIST:
            payload.pop("query")
        if states is not None:
            payload["lifecycle_states"] = states
        return set(_ids(_ok(_invoke(service, scene, capability, payload))))

    for capability in (Capability.REPORTS_LIST, Capability.REPORTS_SEARCH):
        assert listed(None, capability) == {active}
        assert listed(["active"], capability) == {active}
        assert listed(["archived"], capability) == {archived}
        assert listed(["trashed"], capability) == {trashed}
        assert listed(["trashed", "active", "archived"], capability) == {active, archived, trashed}


def test_each_filter_selects_on_the_head_version(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    plain = _publish(service, scene, 1)
    rich = _publish(
        service,
        scene,
        2,
        type="survey",
        topics=["birds", "coast"],
        tags=["field"],
        report_date="2026-08-20",
        associations=[
            {
                "target_kind": "external_source",
                "target_ref": "https://example.test/a",
                "relation": "cites",
            }
        ],
    )
    _set_created(scene, plain, datetime(2026, 1, 1, tzinfo=UTC))
    base: dict[str, Any] = {"plane": "standalone"}

    def ids(**filters: Any) -> list[str]:  # noqa: ANN401
        return _ids(_ok(_invoke(service, scene, Capability.REPORTS_LIST, {**base, **filters})))

    assert ids() == [rich, plain]
    assert ids(type="survey") == [rich]
    assert ids(type="other") == []
    assert ids(topics=["coast", "birds"]) == [rich]
    assert ids(topics=["birds", "lake"]) == []
    assert ids(tags=["field"]) == [rich]
    assert ids(
        associated_with={"target_kind": "external_source", "target_ref": "https://example.test/a"}
    ) == [rich]
    assert (
        ids(
            associated_with={
                "target_kind": "external_source",
                "target_ref": "https://example.test/b",
            }
        )
        == []
    )
    assert ids(created_from="2026-06-01T00:00:00+02:00") == [rich]
    assert ids(created_to="2026-06-01T00:00:00Z") == [plain]
    assert ids(created_from="2026-01-01T00:00:00Z", created_to="2026-01-01T00:00:00.000001Z") == [
        plain
    ]
    assert ids(report_date_from="2026-08-20", report_date_to="2026-08-20") == [rich]
    assert ids(report_date_to="2026-12-31") == [rich]


@pytest.mark.parametrize(
    ("payload", "details"),
    [
        ({"type": "Not A Type"}, (SafeDetail.REPORT_TYPE,)),
        ({"type": 5}, (SafeDetail.REPORT_TYPE,)),
        ({"topics": []}, (SafeDetail.TOPICS,)),
        ({"topics": "birds"}, (SafeDetail.TOPICS,)),
        ({"topics": ["a", "a"]}, (SafeDetail.TOPICS,)),
        ({"topics": [f"t{i}" for i in range(25)]}, (SafeDetail.TOPICS,)),
        ({"tags": [5]}, (SafeDetail.TAGS,)),
        ({"associated_with": "project"}, (SafeDetail.ASSOCIATED_WITH,)),
        ({"associated_with": {"target_kind": "project"}}, (SafeDetail.ASSOCIATED_WITH,)),
        (
            {"associated_with": {"target_kind": "project", "target_ref": ""}},
            (SafeDetail.ASSOCIATED_WITH,),
        ),
        ({"lifecycle_states": []}, (SafeDetail.LIFECYCLE_STATES,)),
        ({"lifecycle_states": ["active", "active"]}, (SafeDetail.LIFECYCLE_STATES,)),
        ({"lifecycle_states": "active"}, (SafeDetail.LIFECYCLE_STATES,)),
        ({"created_from": "2026-01-01T00:00:00"}, (SafeDetail.CREATED_FROM,)),
        ({"created_from": "2026-01-01"}, (SafeDetail.CREATED_FROM,)),
        ({"created_to": 5}, (SafeDetail.CREATED_TO,)),
        (
            {"created_from": "2026-02-01T00:00:00Z", "created_to": "2026-02-01T00:00:00Z"},
            (SafeDetail.CREATED_FROM, SafeDetail.CREATED_TO),
        ),
        ({"report_date_from": "2026-13-01"}, (SafeDetail.REPORT_DATE_FROM,)),
        ({"report_date_to": "2026-1-01"}, (SafeDetail.REPORT_DATE_TO,)),
        (
            {"report_date_from": "2026-02-02", "report_date_to": "2026-02-01"},
            (SafeDetail.REPORT_DATE_FROM, SafeDetail.REPORT_DATE_TO),
        ),
        ({"created_by": "gcrt_" + "0" * 39}, (SafeDetail.CREATED_BY,)),
        ({"created_by": "gcrt_" + "A" * 40}, (SafeDetail.CREATED_BY,)),
        ({"created_by": "GCRT_" + "0" * 40}, (SafeDetail.CREATED_BY,)),
        ({"created_by": "gcrt_" + "0" * 40 + "\n"}, (SafeDetail.CREATED_BY,)),
        ({"created_by": ""}, (SafeDetail.CREATED_BY,)),
        ({"created_by": 5}, (SafeDetail.CREATED_BY,)),
        ({"created_by": ["gcrt_" + "0" * 40]}, (SafeDetail.CREATED_BY,)),
        ({"page_size": 0}, (SafeDetail.PAGE_SIZE,)),
        ({"page_size": 101}, (SafeDetail.PAGE_SIZE,)),
        ({"page_size": "5"}, (SafeDetail.PAGE_SIZE,)),
        ({"page_size": True}, (SafeDetail.PAGE_SIZE,)),
        ({"cursor": 5}, (SafeDetail.CURSOR,)),
        ({"cursor": ""}, (SafeDetail.CURSOR,)),
        ({"cursor": "a" * 513}, (SafeDetail.CURSOR,)),
    ],
)
@pytest.mark.parametrize("plane", ["standalone", "all"])
def test_a_bad_catalog_field_names_itself(
    payload: dict[str, Any], details: tuple[SafeDetail, ...], plane: str
) -> None:
    for capability, query in (
        (Capability.REPORTS_LIST, {}),
        (Capability.REPORTS_SEARCH, {"query": "curlew"}),
    ):
        refusal = _refused(capability, {**query, "plane": plane, **payload})
        assert refusal.safe_details == details, capability


def test_closed_vocabularies_are_listed_and_the_association_object_is_closed() -> None:
    kind = _refused(
        Capability.REPORTS_LIST,
        {"plane": "all", "associated_with": {"target_kind": "nowhere", "target_ref": "x"}},
    )
    assert kind.safe_details == (SafeDetail.ASSOCIATED_WITH,)
    assert kind.allowed_values[SafeDetail.ASSOCIATED_WITH] == (
        "project",
        "entity",
        "standalone_report",
        "intelligence_report",
        "external_source",
    )
    state = _refused(Capability.REPORTS_LIST, {"plane": "all", "lifecycle_states": ["gone"]})
    assert state.allowed_values == {SafeDetail.LIFECYCLE_STATES: ("active", "archived", "trashed")}
    extra = _refused(
        Capability.REPORTS_LIST,
        {
            "plane": "all",
            "associated_with": {
                "target_kind": "external_source",
                "target_ref": "https://example.test/a",
                "relation": "cites",
            },
        },
    )
    assert extra.safe_details == ()


def test_page_size_bounds_and_default(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    for index in range(21):
        _publish(service, scene, index)
    default = _ok(_invoke(service, scene, Capability.REPORTS_LIST, {"plane": "standalone"}))
    assert len(default["items"]) == 20
    assert default["next_cursor"] is not None
    one = _ok(
        _invoke(service, scene, Capability.REPORTS_LIST, {"plane": "standalone", "page_size": 1})
    )
    assert len(one["items"]) == 1
    whole = _ok(
        _invoke(service, scene, Capability.REPORTS_LIST, {"plane": "standalone", "page_size": 100})
    )
    assert len(whole["items"]) == 21
    assert whole["next_cursor"] is None


@pytest.mark.parametrize("query", ["", "   ", "a" * 513, "bad\x00query", 5])
@pytest.mark.parametrize("plane", ["standalone", "all"])
def test_an_empty_invalid_or_oversize_query_is_refused(query: object, plane: str) -> None:
    refusal = _refused(Capability.REPORTS_SEARCH, {"plane": plane, "query": query})
    assert refusal.safe_details == (SafeDetail.QUERY,)
    assert "bad" not in repr(refusal) and "aaaa" not in repr(refusal)


def test_a_512_character_query_is_accepted(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = _ok(
        _invoke(
            service, scene, Capability.REPORTS_SEARCH, {"plane": "standalone", "query": "a" * 512}
        )
    )
    assert result["items"] == []


# ---- the cursor --------------------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2, 3])
@pytest.mark.parametrize("capability", [Capability.REPORTS_LIST, Capability.REPORTS_SEARCH])
def test_a_cursor_walk_neither_skips_nor_repeats(
    scene: Scene, size: int, capability: Capability
) -> None:
    service = build_service(scene.world, scene.providers)
    ids = [_publish(service, scene, index) for index in range(5)]
    payload: dict[str, Any] = {"plane": "standalone", "page_size": size, "query": "curlew"}
    if capability is Capability.REPORTS_LIST:
        payload.pop("query")
    walked = _walk(service, scene, capability, payload)
    assert sorted(walked) == sorted(ids)
    assert len(walked) == len(set(walked))
    # Identical created_at (the fixed clock): ties fall to the id, code point order.
    if capability is Capability.REPORTS_LIST:
        assert walked == sorted(ids, reverse=True)


def test_the_truncation_disclosure_carries_the_same_cursor(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    for index in range(3):
        _publish(service, scene, index)
    answer = _invoke(
        service, scene, Capability.REPORTS_LIST, {"plane": "standalone", "page_size": 2}
    )
    result = _ok(answer)
    assert answer["disclosure"]["truncation"] == {
        "is_truncated": True,
        "reason": "page_size_reached",
        "next_cursor": result["next_cursor"],
    }
    token = result["next_cursor"]
    decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert set(decoded) == {"b", "t", "i"}
    assert decoded["i"] == result["items"][-1]["report_id"]


def _first_cursor(
    service: ApplicationService, scene: Scene, capability: Capability, payload: dict[str, Any]
) -> str:
    cursor = _ok(_invoke(service, scene, capability, {**payload, "page_size": 1}))["next_cursor"]
    assert isinstance(cursor, str)
    return cursor


def test_a_cursor_is_refused_for_any_other_request(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    for index in range(3):
        _publish(service, scene, index, topics=["birds"])
    listing: dict[str, Any] = {"plane": "standalone", "topics": ["birds"]}
    searching: dict[str, Any] = {"plane": "standalone", "query": "curlew"}
    list_cursor = _first_cursor(service, scene, Capability.REPORTS_LIST, listing)
    search_cursor = _first_cursor(service, scene, Capability.REPORTS_SEARCH, searching)
    raw = json.loads(base64.urlsafe_b64decode(list_cursor + "=" * (-len(list_cursor) % 4)))
    tampered_payload = {**raw, "b": "0" * 64}
    tampered = (
        base64.urlsafe_b64encode(
            json.dumps(tampered_payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    stranger = operator()
    cases: list[tuple[Capability, dict[str, Any], Principal | None]] = [
        (Capability.REPORTS_LIST, {**listing, "cursor": "garbage!"}, None),
        (Capability.REPORTS_LIST, {**listing, "cursor": "Zm9v"}, None),
        (Capability.REPORTS_LIST, {**listing, "cursor": tampered}, None),
        (Capability.REPORTS_LIST, {**listing, "cursor": list_cursor, "page_size": 1}, stranger),
        (Capability.REPORTS_LIST, {**listing, "cursor": list_cursor, "page_size": 2}, None),
        (Capability.REPORTS_LIST, {**listing, "cursor": list_cursor}, None),
        (
            Capability.REPORTS_LIST,
            {**listing, "cursor": list_cursor, "page_size": 1, "tags": ["x"]},
            None,
        ),
        (
            Capability.REPORTS_LIST,
            {**listing, "cursor": list_cursor, "page_size": 1, "plane": "all"},
            None,
        ),
        (
            Capability.REPORTS_LIST,
            {
                **listing,
                "cursor": list_cursor,
                "page_size": 1,
                "lifecycle_states": ["active", "archived"],
            },
            None,
        ),
        (Capability.REPORTS_SEARCH, {**searching, "cursor": list_cursor, "page_size": 1}, None),
        (
            Capability.REPORTS_SEARCH,
            {**searching, "cursor": search_cursor, "page_size": 1, "query": "survey"},
            None,
        ),
        (
            Capability.REPORTS_LIST,
            {"plane": "standalone", "cursor": search_cursor, "page_size": 1},
            None,
        ),
    ]
    for capability, payload, principal in cases:
        answer = _invoke(service, scene, capability, payload, principal=principal)
        assert answer["result"] is None, (sorted(payload), principal is not None)
        assert answer["error"]["code"] == ErrorCode.INVALID_REQUEST.value
        assert answer["error"]["safe_details"] == ["cursor"], payload
        assert str(payload["cursor"]) not in json.dumps(answer["error"])
    # The same request again is accepted: the binding names the request, not the time.
    # So is the same request with the default lifecycle spelled out: filters are
    # bound in their normalized form, defaults explicit.
    for payload in (
        {**listing, "cursor": list_cursor, "page_size": 1},
        {**listing, "cursor": list_cursor, "page_size": 1, "lifecycle_states": ["active"]},
    ):
        assert _invoke(service, scene, Capability.REPORTS_LIST, payload)["error"] is None


# ---- the all plane -----------------------------------------------------------------------


def test_the_all_plane_merges_both_planes_in_one_order_with_ties(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    standalone = sorted((_publish(service, scene, index) for index in range(2)), reverse=True)
    # Same instant as both standalone reports (the fixed clock): ties fall to the id,
    # and every `rpt_` id sorts after every `grpt_` id in code point order.
    _legacy(scene, "rpt_catalogtie00001")
    _legacy(scene, "rpt_catalogtie00002")
    _legacy(scene, "rpt_catalognewer001", at=WHEN + timedelta(hours=1))
    _legacy(scene, "rpt_catalogolder001", at=WHEN - timedelta(hours=1))
    expected = [
        "rpt_catalognewer001",
        "rpt_catalogtie00002",
        "rpt_catalogtie00001",
        *standalone,
        "rpt_catalogolder001",
    ]
    whole = _ok(_invoke(service, scene, Capability.REPORTS_LIST, {"plane": "all"}))
    assert _ids(whole) == expected
    for item in whole["items"]:
        keys = STANDALONE_KEYS if item["plane"] == "standalone" else INTELLIGENCE_KEYS
        assert set(item) == keys
    legacy = next(item for item in whole["items"] if item["plane"] == "intelligence")
    assert legacy["type"] == legacy["artifact_kind"] == "collector_candidates"
    assert legacy["created_at"] == "2026-08-02T13:00:00.000Z"
    for size in (1, 2, 3, 4):
        walked = _walk(service, scene, Capability.REPORTS_LIST, {"plane": "all", "page_size": size})
        assert walked == expected, size
    # The standalone plane alone never lists a pipeline artifact.
    alone = _ok(_invoke(service, scene, Capability.REPORTS_LIST, {"plane": "standalone"}))
    assert _ids(alone) == standalone
    # A filter a pipeline artifact cannot match leaves only standalone reports.
    topical = _ok(
        _invoke(service, scene, Capability.REPORTS_LIST, {"plane": "all", "tags": ["field"]})
    )
    assert topical["items"] == []
    archived_only = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_LIST,
            {"plane": "all", "lifecycle_states": ["archived"]},
        )
    )
    assert archived_only["items"] == []


def test_the_all_search_ranks_across_planes_with_snippets(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    standalone = _publish(service, scene, 1, summary="A short summary.")
    _legacy(scene, "rpt_catalogsearch01", title="Curlew brief")
    _legacy(scene, "rpt_catalogsearch02", title="Unrelated")
    answer = _invoke(service, scene, Capability.REPORTS_SEARCH, {"plane": "all", "query": "curlew"})
    result = _ok(answer)
    assert result["plane"] == "all"
    items = {item["report_id"]: item for item in result["items"]}
    # The in-memory stand-in matches the legacy body too; ranks order them.
    assert standalone in items and "rpt_catalogsearch01" in items
    assert set(items[standalone]) == STANDALONE_KEYS | {"snippet"}
    assert items[standalone]["snippet"] == "A short summary."
    assert set(items["rpt_catalogsearch01"]) == INTELLIGENCE_KEYS | {"snippet"}
    assert items["rpt_catalogsearch01"]["snippet"] == "Curlew brief"
    assert "secret body" not in json.dumps(answer)
    alone = _ok(
        _invoke(
            service, scene, Capability.REPORTS_SEARCH, {"plane": "standalone", "query": "curlew"}
        )
    )
    assert _ids(alone) == [standalone]


def test_another_principals_reports_are_never_listed(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    _publish(service, scene, 1)
    _legacy(scene, "rpt_catalogmine0001")
    stranger = operator()
    for capability, payload in (
        (Capability.REPORTS_LIST, {"plane": "all"}),
        (Capability.REPORTS_SEARCH, {"plane": "all", "query": "curlew"}),
    ):
        answer = _invoke(service, scene, capability, payload, principal=stranger)
        assert _ok(answer)["items"] == []


def test_created_by_in_all_never_matches_a_pipeline_artifact(scene: Scene) -> None:
    """WP05 A5: legacy items carry no creator, so a `created_by` filter excludes them."""
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene, 1)
    _legacy(scene, "rpt_legacycreator001")
    local = derive_creator(CreatorKind.LOCAL_PRINCIPAL, scene.principal.principal_id).creator_id
    for capability in (Capability.REPORTS_LIST, Capability.REPORTS_SEARCH):
        base = {"plane": "all", **_query(capability)}
        assert set(_ids(_ok(_invoke(service, scene, capability, base)))) == {
            report_id,
            "rpt_legacycreator001",
        }
        filtered = _ok(_invoke(service, scene, capability, {**base, "created_by": local}))
        assert _ids(filtered) == [report_id]
