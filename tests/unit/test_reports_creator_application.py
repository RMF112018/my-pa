"""Reports Modernization WP05 (A1, A4, A5, A6): creator attribution through the service.

FAST tier over `FakeUnitOfWork`, through `normalize` and
`ApplicationService.invoke` -- the path every transport takes. Covers the
server derivation (`_report_creator`: remote client, remote without a client
id, local Principal), the outputs (`reports.read` creator/author,
`reports.history` author, standalone list/search creator, receipts unchanged),
the `created_by` filter and its cursor binding, and forgery refusal on
`reports.publish`/`reports.update`. `tests/database/test_reports_creator.py` is
the authority on SQL. Every title, body and client id is synthetic.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Final, cast

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.authorization import Authorization
from my_pa.application.errors import (
    ApplicationError,
    InternalError,
    InvalidRequestError,
    SafeDetail,
)
from my_pa.application.service import ApplicationService, _report_creator
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from tests.conftest import Scene, build_service, operator

BODY: Final = "# Creator\n\nSynthetic report text"
CLIENT_A: Final = "wp05-synthetic-client-a"
CLIENT_B: Final = "wp05-synthetic-client-b"
UNKNOWN_CREATOR: Final = "gcrt_" + "0" * 40
#: Every spelling of a caller-asserted writer A6 names; none is a command field.
FORGED_CREATOR_FIELDS: Final = (
    "creator",
    "created_by",
    "author",
    "authored_by",
    "created_by_id",
    "creator_id",
)
FORGED_VALUES: Final[tuple[object, ...]] = (
    UNKNOWN_CREATOR,
    {"kind": "remote_client", "id": UNKNOWN_CREATOR},
    None,
)


def _creator(kind: CreatorKind, subject: str) -> dict[str, str]:
    derived = derive_creator(kind, subject)
    return {"kind": derived.kind.value, "id": derived.creator_id}


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
    client: str | None = None,
    remote: bool | None = None,
    principal: Principal | None = None,
) -> dict[str, Any]:
    """Invoke locally, or as remote `client` (`remote=True` with no client: no client id)."""
    metadata, command = normalize(capability.value, _wire(scene, capability, payload))
    is_remote = client is not None if remote is None else remote
    envelope = service.invoke(
        metadata,
        command,
        principal=principal or scene.principal,
        transport=CaptureTransport.REMOTE_CLIENT if is_remote else CaptureTransport.LOCAL,
        authenticated_client_id=client,
    )
    return envelope.model_dump(mode="json")


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _refusal(capability: Capability, payload: dict[str, Any]) -> ApplicationError:
    with pytest.raises(ApplicationError) as refused:
        normalize(capability.value, _wire_for_refusal(capability, payload))
    return refused.value


def _wire_for_refusal(capability: Capability, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": "req",
        "purpose": next(iter(permitted_purposes(capability))).value,
        "principal_id": "prn_aaaa0001aaaa0001aaaa0001",
        "requested_at": "2026-11-05T12:00:00Z",
        "payload": payload,
    }


def _publish_payload(index: int) -> dict[str, Any]:
    return {
        "title": f"Creator report {index}",
        "content": {"format": "markdown", "body": BODY},
        "idempotency_key": f"creator-{index}",
    }


def _update_payload(report_id: str, key: str, expected_version: int = 1) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "expected_version": expected_version,
        "patch": {"title": f"Revised {key}"},
        "change_reason": "A synthetic revision.",
        "idempotency_key": key,
    }


def _publish(
    service: ApplicationService, scene: Scene, index: int, *, client: str | None = None
) -> str:
    result = _ok(
        _invoke(service, scene, Capability.REPORTS_PUBLISH, _publish_payload(index), client=client)
    )
    return str(result["report_id"])


def _ids(result: dict[str, Any]) -> list[str]:
    return [item["report_id"] for item in result["items"]]


def _written(scene: Scene) -> tuple[int, ...]:
    world = scene.world
    return (
        len(world.general_report_versions),
        len(world.general_report_receipts),
        sum(len(versions) for versions in world.general_report_ledger.values()),
        len(world.general_report_update_receipts),
    )


# ---- _report_creator: derived from the Authorization only -------------------------------


def _authorization(
    transport: CaptureTransport, client: str | None, principal: Principal
) -> Authorization:
    # `_report_creator` reads exactly these three; the rest of the record is irrelevant.
    return cast(
        "Authorization",
        SimpleNamespace(transport=transport, authenticated_client_id=client, principal=principal),
    )


def test_a_remote_client_is_the_pseudonym_of_its_client_id() -> None:
    principal = operator()
    creator = _report_creator(_authorization(CaptureTransport.REMOTE_CLIENT, CLIENT_A, principal))
    assert creator == derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT_A)
    assert creator.kind is CreatorKind.REMOTE_CLIENT
    assert CLIENT_A not in repr(creator)
    assert creator != derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal.principal_id)


@pytest.mark.parametrize("client", [None, ""])
def test_a_remote_authorization_without_a_client_id_is_an_internal_error(
    client: str | None,
) -> None:
    with pytest.raises(InternalError):
        _report_creator(_authorization(CaptureTransport.REMOTE_CLIENT, client, operator()))


def test_a_local_caller_is_the_pseudonym_of_its_principal() -> None:
    principal = operator()
    # A client id on a local authorization is never the subject.
    for client in (None, CLIENT_A):
        creator = _report_creator(_authorization(CaptureTransport.LOCAL, client, principal))
        assert creator == derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal.principal_id)


def test_two_clients_of_one_principal_differ_and_one_client_is_stable() -> None:
    principal = operator()
    first = _report_creator(_authorization(CaptureTransport.REMOTE_CLIENT, CLIENT_A, principal))
    again = _report_creator(_authorization(CaptureTransport.REMOTE_CLIENT, CLIENT_A, operator()))
    other = _report_creator(_authorization(CaptureTransport.REMOTE_CLIENT, CLIENT_B, principal))
    assert first == again
    assert first.creator_id != other.creator_id


def test_a_remote_publish_without_a_client_id_is_internal_error_and_writes_nothing(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    answer = _invoke(service, scene, Capability.REPORTS_PUBLISH, _publish_payload(1), remote=True)
    assert answer["result"] is None
    assert answer["error"]["code"] == "internal_error"
    assert _written(scene) == (0, 0, 0, 0)


def test_a_remote_update_without_a_client_id_is_internal_error_and_writes_nothing(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene, 1, client=CLIENT_A)
    before = _written(scene)
    answer = _invoke(
        service, scene, Capability.REPORTS_UPDATE, _update_payload(report_id, "u"), remote=True
    )
    assert answer["result"] is None
    assert answer["error"]["code"] == "internal_error"
    assert _written(scene) == before


# ---- outputs (A4) ------------------------------------------------------------------------


def test_read_history_and_catalog_carry_the_creator_and_each_author(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    a = _creator(CreatorKind.REMOTE_CLIENT, CLIENT_A)
    b = _creator(CreatorKind.REMOTE_CLIENT, CLIENT_B)
    published = _ok(
        _invoke(service, scene, Capability.REPORTS_PUBLISH, _publish_payload(1), client=CLIENT_A)
    )
    report_id = published["report_id"]
    first = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    assert first["creator"] == a
    assert first["author"] == a
    updated = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update_payload(report_id, "by-b"),
            client=CLIENT_B,
        )
    )
    # Receipts are unchanged: no creator or author.
    for receipt in (published, updated):
        assert not {"creator", "author"} & set(receipt)
    head = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    assert head["version_number"] == 2
    assert head["creator"] == a
    assert head["author"] == b
    v1 = _ok(
        _invoke(
            service, scene, Capability.REPORTS_READ, {"report_id": report_id, "version_number": 1}
        )
    )
    assert (v1["creator"], v1["author"]) == (a, a)
    history = _ok(_invoke(service, scene, Capability.REPORTS_HISTORY, {"report_id": report_id}))
    assert [item["author"] for item in history["items"]] == [a, b]
    assert "creator" not in history
    for capability, extra in (
        (Capability.REPORTS_LIST, {}),
        (Capability.REPORTS_SEARCH, {"query": "creator"}),
    ):
        listed = _ok(_invoke(service, scene, capability, {"plane": "standalone", **extra}))
        (item,) = listed["items"]
        assert item["creator"] == a
        assert "author" not in item


def test_a_local_publish_is_attributed_to_the_local_principal(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene, 1)
    read = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    local = _creator(CreatorKind.LOCAL_PRINCIPAL, scene.principal.principal_id)
    assert read["creator"] == read["author"] == local


def test_lifecycle_receipts_carry_no_creator(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene, 1, client=CLIENT_A)
    receipt = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_ARCHIVE,
            {"report_id": report_id, "expected_lifecycle_revision": 0, "idempotency_key": "a"},
            client=CLIENT_A,
        )
    )
    assert not {"creator", "author"} & set(receipt)


# ---- the created_by filter (A5) -----------------------------------------------------------


@pytest.mark.parametrize("plane", ["standalone", "all"])
def test_created_by_selects_exactly_that_creator(scene: Scene, plane: str) -> None:
    service = build_service(scene.world, scene.providers)
    by_a = _publish(service, scene, 1, client=CLIENT_A)
    by_b = _publish(service, scene, 2, client=CLIENT_B)
    # Updated by A: the filter is the root's creator, never a later author.
    _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update_payload(by_b, "b-by-a"),
            client=CLIENT_A,
        )
    )
    a_id = derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT_A).creator_id
    b_id = derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT_B).creator_id
    for capability, extra in (
        (Capability.REPORTS_LIST, {}),
        (Capability.REPORTS_SEARCH, {"query": "creator"}),
    ):
        for created_by, expected in ((a_id, [by_a]), (b_id, [by_b]), (UNKNOWN_CREATOR, [])):
            payload = {"plane": plane, "created_by": created_by, **extra}
            assert _ids(_ok(_invoke(service, scene, capability, payload))) == expected


def test_created_by_of_another_principal_sees_nothing(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    _publish(service, scene, 1, client=CLIENT_A)
    a_id = derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT_A).creator_id
    stranger = operator()
    listed = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_LIST,
            {"plane": "standalone", "created_by": a_id},
            client=CLIENT_A,
            principal=stranger,
        )
    )
    assert listed["items"] == []
    assert listed["next_cursor"] is None


@pytest.mark.parametrize("plane", [None, "intelligence"])
@pytest.mark.parametrize("value", [UNKNOWN_CREATOR, "not-a-creator", None])
def test_created_by_is_refused_by_presence_in_the_pipeline_plane(
    plane: str | None, value: object
) -> None:
    selected = {} if plane is None else {"plane": plane}
    for capability, extra in (
        (Capability.REPORTS_LIST, {}),
        (Capability.REPORTS_SEARCH, {"query": "creator"}),
    ):
        refusal = _refusal(capability, {**extra, **selected, "created_by": value})
        assert isinstance(refusal, InvalidRequestError)
        assert refusal.safe_details == ()


@pytest.mark.parametrize(
    "value", ["gcrt_" + "f" * 41, "gcrt-" + "0" * 40, "crt_" + "0" * 40, 7, {"id": "x"}]
)
def test_a_malformed_created_by_names_created_by_and_never_its_value(value: object) -> None:
    refusal = _refusal(Capability.REPORTS_LIST, {"plane": "standalone", "created_by": value})
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == (SafeDetail.CREATED_BY,)
    assert refusal.__context__ is None
    assert str(value) not in str(refusal)


def test_a_cursor_is_bound_to_its_created_by(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    for index in range(3):
        _publish(service, scene, index, client=CLIENT_A)
    a_id = derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT_A).creator_id
    first = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_LIST,
            {"plane": "standalone", "created_by": a_id, "page_size": 1},
        )
    )
    cursor = first["next_cursor"]
    assert isinstance(cursor, str)
    # The same request continues.
    _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_LIST,
            {"plane": "standalone", "created_by": a_id, "page_size": 1, "cursor": cursor},
        )
    )
    for changed in ({}, {"created_by": UNKNOWN_CREATOR}):
        answer = _invoke(
            service,
            scene,
            Capability.REPORTS_LIST,
            {"plane": "standalone", "page_size": 1, "cursor": cursor, **changed},
        )
        assert answer["result"] is None
        assert answer["error"]["code"] == "invalid_request"
        assert answer["error"]["safe_details"] == ["cursor"]


# ---- forgery (A6) -------------------------------------------------------------------------


@pytest.mark.parametrize("field", FORGED_CREATOR_FIELDS)
@pytest.mark.parametrize("value", FORGED_VALUES)
def test_publish_refuses_a_caller_asserted_creator(field: str, value: object) -> None:
    refusal = _refusal(Capability.REPORTS_PUBLISH, {**_publish_payload(1), field: value})
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == ()


@pytest.mark.parametrize("field", FORGED_CREATOR_FIELDS)
@pytest.mark.parametrize("value", FORGED_VALUES)
def test_update_refuses_a_caller_asserted_author(field: str, value: object) -> None:
    payload = _update_payload("grpt_00000000abcdefgh", "k")
    refusal = _refusal(Capability.REPORTS_UPDATE, {**payload, field: value})
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == ()
    inside = _refusal(Capability.REPORTS_UPDATE, {**payload, "patch": {"title": "T", field: value}})
    assert isinstance(inside, InvalidRequestError)


@pytest.mark.parametrize("field", FORGED_CREATOR_FIELDS)
def test_a_forged_creator_writes_nothing_through_the_service(scene: Scene, field: str) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene, 1, client=CLIENT_A)
    before = _written(scene)
    forged = {field: UNKNOWN_CREATOR}
    for capability, payload in (
        (Capability.REPORTS_PUBLISH, {**_publish_payload(2), **forged}),
        (Capability.REPORTS_UPDATE, {**_update_payload(report_id, "f"), **forged}),
    ):
        with pytest.raises(InvalidRequestError):
            _invoke(service, scene, capability, payload, client=CLIENT_B)
    assert _written(scene) == before
    read = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    a = _creator(CreatorKind.REMOTE_CLIENT, CLIENT_A)
    assert (read["version_number"], read["creator"], read["author"]) == (1, a, a)
