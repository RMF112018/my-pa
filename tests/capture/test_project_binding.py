"""WP04B: a Capture root may carry one immutable Project binding."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, select, text
from tests.capture.conftest import counts, invoke, succeeded

from my_pa.application.commands import (
    CreateCapture,
    ListCaptures,
    ReadCapture,
    ReviseCapture,
    SearchCaptures,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.ports import CaptureAdmissionRequest
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.persistence.tables import audit_events, projects

PROJECT: Final = "prj_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OTHER_PROJECT: Final = "prj_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
FOREIGN_PROJECT: Final = "prj_cccccccccccccccccccccccccccccccc"
MISSING_PROJECT: Final = "prj_dddddddddddddddddddddddddddddddd"
FOREIGN_PRINCIPAL: Final = "prn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
TEXT: Final = "wp04b cobalt project capture"
NULL_TEXT: Final = "wp04b amber unbound capture"
AUDIT: Final = "knowledge.audit_events"


def _admission_request(project_id: str | None) -> CaptureAdmissionRequest:
    at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    return CaptureAdmissionRequest(
        capture_id=None,
        content=CaptureContent(TEXT),
        idempotency_key="wp04b-digest",
        request_id="req-wp04b-digest",
        correlation_id="corr_11111111111111111111111111111111",
        principal_id="prn_22222222222222222222222222222222",
        audit_id="audit_33333333333333333333333333333333",
        classification=Classification.PRIVATE_LOCAL,
        processing_policy=ProcessingPolicy.LOCAL_ONLY,
        server_received_at=at,
        accepted_at=at,
        project_id=project_id,
    )


def test_project_identifier_is_validated_at_the_command_boundary() -> None:
    with pytest.raises(InvalidRequestError) as raised:
        CreateCapture(text=TEXT, idempotency_key="wp04b-invalid", project_id="not-a-project")
    assert raised.value.safe_details == (SafeDetail.PROJECT_ID,)


def test_project_is_material_to_the_root_admission_digest() -> None:
    assert _admission_request(None).payload_digest != _admission_request(PROJECT).payload_digest
    assert (
        _admission_request(PROJECT).payload_digest
        != _admission_request(OTHER_PROJECT).payload_digest
    )


def _seed_project(engine: Engine, project_id: str, principal_id: str) -> None:
    with engine.begin() as connection:
        at = connection.execute(select(text("clock_timestamp()"))).scalar_one()
        connection.execute(
            insert(projects).values(
                project_id=project_id,
                principal_id=principal_id,
                name=f"Synthetic {project_id[-4:]}",
                opened_at=at,
                created_at=at,
                updated_at=at,
            )
        )


def _create(
    runtime: GatewayRuntime,
    *,
    key: str,
    text_: str = TEXT,
    project_id: str | None = None,
) -> ResponseEnvelope:
    return invoke(
        runtime,
        Capability.CAPTURE_CREATE,
        CreateCapture(text=text_, idempotency_key=key, project_id=project_id),
        key,
    )


def _work_plane(snapshot: dict[str, int]) -> dict[str, int]:
    return {table: value for table, value in snapshot.items() if table != AUDIT}


def _audit(runtime: GatewayRuntime, correlation_id: str) -> dict[str, Any]:
    with runtime.work_engine.connect() as connection:
        row = connection.execute(
            select(audit_events).where(audit_events.c.correlation_id == correlation_id)
        ).one()
    return dict(row._mapping)


def _assert_redacted_allowed_create_audit(
    runtime: GatewayRuntime, response: ResponseEnvelope, forbidden_project_id: str
) -> None:
    row = _audit(runtime, response.correlation_id)
    assert row["capability"] == Capability.CAPTURE_CREATE.value
    assert row["outcome"] == "allowed"
    rendered = json.dumps(row, default=str, sort_keys=True)
    assert forbidden_project_id not in rendered
    assert TEXT not in rendered
    assert "success" not in rendered.lower()


@pytest.mark.database
def test_null_and_owned_project_round_trip_and_revision_inherits(
    runtime: GatewayRuntime,
) -> None:
    principal_id = runtime.principal.principal_id
    _seed_project(runtime.work_engine, PROJECT, principal_id)

    unbound = succeeded(
        _create(runtime, key="wp04b-null", text_=NULL_TEXT), "unbound capture.create"
    )
    assert unbound["project_id"] is None
    unbound_read = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_READ,
            ReadCapture(capture_id=unbound["capture_id"]),
            "wp04b-null-read",
        ),
        "unbound capture.read",
    )
    assert unbound_read["project_id"] is None

    created = succeeded(
        _create(runtime, key="wp04b-owned", project_id=PROJECT), "bound capture.create"
    )
    replayed = succeeded(
        _create(runtime, key="wp04b-owned", project_id=PROJECT), "bound capture replay"
    )
    assert created["project_id"] == PROJECT
    assert replayed["project_id"] == PROJECT
    assert replayed["created"] is False
    assert replayed["receipt_id"] == created["receipt_id"]

    revised = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_REVISE,
            ReviseCapture(
                capture_id=created["capture_id"],
                text=f"{TEXT} revised",
                idempotency_key="wp04b-revise",
            ),
            "wp04b-revise",
        ),
        "capture.revise",
    )
    assert revised["project_id"] == PROJECT

    read = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_READ,
            ReadCapture(capture_id=created["capture_id"]),
            "wp04b-read",
        ),
        "capture.read",
    )
    assert read["project_id"] == PROJECT
    listing = succeeded(
        invoke(runtime, Capability.CAPTURE_LIST, ListCaptures(), "wp04b-list"),
        "capture.list",
    )
    listed = {entry["capture_id"]: entry["project_id"] for entry in listing["captures"]}
    assert listed == {created["capture_id"]: PROJECT, unbound["capture_id"]: None}
    search = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_SEARCH,
            SearchCaptures(query="cobalt project"),
            "wp04b-search",
        ),
        "capture.search",
    )
    assert [(match["capture_id"], match["project_id"]) for match in search["matches"]] == [
        (created["capture_id"], PROJECT)
    ]

    with runtime.work_engine.connect() as connection:
        root = connection.execute(
            text(
                "SELECT owner_principal_id, project_id FROM knowledge.captures "
                "WHERE capture_id = :capture_id"
            ),
            {"capture_id": created["capture_id"]},
        ).one()
    assert tuple(root) == (principal_id, PROJECT)


@pytest.mark.database
def test_project_is_material_to_idempotency_and_never_reassigned(
    runtime: GatewayRuntime,
) -> None:
    principal_id = runtime.principal.principal_id
    _seed_project(runtime.work_engine, PROJECT, principal_id)
    _seed_project(runtime.work_engine, OTHER_PROJECT, principal_id)
    created = succeeded(
        _create(runtime, key="wp04b-material", project_id=PROJECT), "bound capture.create"
    )
    before = counts(runtime.work_engine)
    assert sum(_work_plane(before).values()) > 0

    for project_id in (None, OTHER_PROJECT):
        refused = _create(runtime, key="wp04b-material", project_id=project_id)
        assert refused.error is not None
        assert refused.error.code == ErrorCode.CONFLICT
        assert tuple(refused.error.safe_details) == ("idempotency_key",)
        assert _work_plane(counts(runtime.work_engine)) == _work_plane(before)

    revised = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_REVISE,
            ReviseCapture(
                capture_id=created["capture_id"],
                text=f"{TEXT} immutable root",
                idempotency_key="wp04b-material-revise",
            ),
            "wp04b-material-revise",
        ),
        "capture.revise",
    )
    assert revised["project_id"] == PROJECT
    with runtime.work_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT project_id FROM knowledge.captures WHERE capture_id = :capture_id"),
                {"capture_id": created["capture_id"]},
            ).scalar_one()
            == PROJECT
        )


@pytest.mark.database
def test_missing_and_foreign_projects_are_one_redacted_no_work_refusal(
    runtime: GatewayRuntime,
) -> None:
    principal_id = runtime.principal.principal_id
    _seed_project(runtime.work_engine, PROJECT, principal_id)
    _seed_project(runtime.work_engine, FOREIGN_PROJECT, FOREIGN_PRINCIPAL)
    baseline = succeeded(
        _create(runtime, key="wp04b-baseline", project_id=PROJECT), "baseline capture.create"
    )
    before = counts(runtime.work_engine)
    assert sum(_work_plane(before).values()) > 0

    refusals: list[ResponseEnvelope] = []
    for tag, project_id in (("missing", MISSING_PROJECT), ("foreign", FOREIGN_PROJECT)):
        immediately_before = counts(runtime.work_engine)
        refusal = _create(runtime, key=f"wp04b-{tag}", project_id=project_id)
        immediately_after = counts(runtime.work_engine)
        assert refusal.error is not None
        assert refusal.error.code == ErrorCode.NOT_FOUND
        assert tuple(refusal.error.safe_details) == ("project_id",)
        assert refusal.result is None
        assert _work_plane(immediately_after) == _work_plane(immediately_before)
        assert immediately_after[AUDIT] == immediately_before[AUDIT] + 1
        _assert_redacted_allowed_create_audit(runtime, refusal, project_id)
        assert project_id not in repr(refusal)
        refusals.append(refusal)

    assert refusals[0].error is not None and refusals[1].error is not None
    assert refusals[0].error.code == refusals[1].error.code
    assert refusals[0].error.safe_details == refusals[1].error.safe_details

    read = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_READ,
            ReadCapture(capture_id=baseline["capture_id"]),
            "wp04b-baseline-read",
        ),
        "baseline capture.read",
    )
    assert read["project_id"] == PROJECT
    listing = succeeded(
        invoke(runtime, Capability.CAPTURE_LIST, ListCaptures(), "wp04b-baseline-list"),
        "baseline capture.list",
    )
    assert [(entry["capture_id"], entry["project_id"]) for entry in listing["captures"]] == [
        (baseline["capture_id"], PROJECT)
    ]
    search = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_SEARCH,
            SearchCaptures(query="cobalt project"),
            "wp04b-baseline-search",
        ),
        "baseline capture.search",
    )
    assert [(match["capture_id"], match["project_id"]) for match in search["matches"]] == [
        (baseline["capture_id"], PROJECT)
    ]
    assert _work_plane(counts(runtime.work_engine)) == _work_plane(before)


@pytest.mark.database
def test_count_inventory_is_closed_over_every_capture_table(runtime: GatewayRuntime) -> None:
    expected = {
        name.removeprefix("knowledge.") for name in _work_plane(counts(runtime.work_engine))
    }
    with runtime.work_engine.connect() as connection:
        actual = {
            str(name)
            for name in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'knowledge' "
                    "AND (table_name = 'captures' OR table_name LIKE 'capture\\_%' ESCAPE '\\')"
                )
            ).scalars()
        }
    assert actual == expected
