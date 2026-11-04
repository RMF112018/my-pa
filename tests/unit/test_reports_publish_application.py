"""Reports Modernization WP02: `reports.publish` and standalone `reports.read`, canonical path.

Through `normalize` and `ApplicationService.invoke` -- the exact path every
local transport takes -- over the FAST world's in-memory general report fake.
PostgreSQL behaviour (the real repository, row counts, the intelligence plane
untouched, the MCP transport over a real database) is
`tests/database/test_reports_general_application.py`'s.

Every title, body and identifier is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.commands import PublishGeneralReport, ReadIntelligenceArtifact
from my_pa.application.errors import (
    ApplicationError,
    InvalidRequestError,
    SafeDetail,
    UnsupportedError,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ReportIntegrityError
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES
from my_pa.domain.reports.manifest import manifest_digest
from my_pa.domain.reports.vocabulary import LifecycleState
from tests.conftest import Scene, build_service, operator

BODY: Final = "# Assessment\n\nReport text"
MINIMAL: Final[dict[str, Any]] = {
    "title": "Project Schedule Risk Assessment",
    "content": {"format": "markdown", "body": BODY},
    "idempotency_key": "publish-minimal",
}

#: Every field the server derives, each forged by a caller.
FORGED_SERVER_FIELDS: Final = (
    "principal_id",
    "owner",
    "created_at",
    "recorded_at",
    "report_id",
    "version_id",
    "version_number",
    "manifest",
    "manifest_sha256",
    "receipt_id",
    "verification",
    "content_id",
    "lifecycle_state",
)
PIPELINE_FIELDS: Final[dict[str, str]] = {
    "cycle_run_id": "cycle_run_id",
    "stage": "stage",
    "producer": "selector",
    "producer_task_id": "selector",
    "focus_area": "focus_area_id",
    "focus_area_id": "focus_area_id",
    "source_lane": "source_lane",
}


def _wire(scene: Scene, capability: Capability, payload: dict[str, Any]) -> dict[str, Any]:
    (purpose,) = permitted_purposes(capability)
    return {
        "request_id": f"req-{capability.value}",
        "purpose": purpose.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-11-04T12:00:00Z",
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


def _refusal(payload: dict[str, Any], capability: Capability = Capability.REPORTS_PUBLISH) -> Any:  # noqa: ANN401
    with pytest.raises(ApplicationError) as refused:
        normalize(
            capability.value,
            {
                "request_id": "req",
                "purpose": next(iter(permitted_purposes(capability))).value,
                "principal_id": "prn_aaaa0001aaaa0001aaaa0001",
                "requested_at": "2026-11-04T12:00:00Z",
                "payload": payload,
            },
        )
    return refused.value


# ---- vocabulary ----------------------------------------------------------------


def test_publish_is_an_additive_report_authoring_write() -> None:
    assert permitted_purposes(Capability.REPORTS_PUBLISH) == {Purpose.REPORT_AUTHORING}
    assert is_write_capability(Capability.REPORTS_PUBLISH)
    assert not is_destructive_capability(Capability.REPORTS_PUBLISH)


# ---- publish ---------------------------------------------------------------------


def test_title_and_content_alone_publish_version_one_with_a_receipt(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, dict(MINIMAL)))
    assert result["plane"] == "standalone"
    assert result["report_id"].startswith("grpt_")
    assert result["version_id"].startswith("grver_")
    assert result["receipt_id"].startswith("grrc_")
    assert result["version_number"] == 1
    assert result["lifecycle_state"] == "active"
    assert result["lifecycle_revision"] == 0
    assert result["replayed"] is False
    content = result["content"]
    assert content["format"] == "markdown"
    assert content["decoded_sha256"] == hashlib.sha256(BODY.encode()).hexdigest()
    assert content["decoded_byte_count"] == len(BODY.encode())
    assert content["canonical_sha256"] is None
    assert len(result["manifest_sha256"]) == 64
    # Nothing of the pipeline plane is touched.
    store = scene.world.intelligence
    assert not (store.cycles or store.runs or store.artifacts or store.receipts)


def test_a_retry_replays_and_a_changed_retry_conflicts(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, dict(MINIMAL)))
    again = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, dict(MINIMAL)))
    assert again["replayed"] is True
    assert {key: value for key, value in again.items() if key != "replayed"} == {
        key: value for key, value in first.items() if key != "replayed"
    }
    changed = _invoke(
        service, scene, Capability.REPORTS_PUBLISH, {**MINIMAL, "title": "Another title"}
    )
    assert changed["error"]["code"] == ErrorCode.CONFLICT.value
    assert changed["error"]["safe_details"] == ["idempotency_key"]
    assert len(scene.world.general_report_versions) == 1


def test_a_distinct_client_intent_id_is_a_second_report(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    one = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_PUBLISH,
            {**MINIMAL, "idempotency_key": "intent-1", "client_intent_id": "draft-1"},
        )
    )
    two = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_PUBLISH,
            {**MINIMAL, "idempotency_key": "intent-2", "client_intent_id": "draft-2"},
        )
    )
    assert one["report_id"] != two["report_id"]
    assert one["content"]["decoded_sha256"] == two["content"]["decoded_sha256"]
    # The same key with another intent id is another intent: refused, never merged.
    clash = _invoke(
        service,
        scene,
        Capability.REPORTS_PUBLISH,
        {**MINIMAL, "idempotency_key": "intent-1", "client_intent_id": "draft-3"},
    )
    assert clash["error"]["code"] == ErrorCode.CONFLICT.value


@pytest.mark.parametrize("field", FORGED_SERVER_FIELDS)
def test_a_forged_server_field_is_refused(field: str) -> None:
    refusal = _refusal({**MINIMAL, field: "forged"})
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == ()


@pytest.mark.parametrize(("field", "detail"), sorted(PIPELINE_FIELDS.items()))
def test_a_pipeline_field_is_refused_by_name(field: str, detail: str) -> None:
    refusal = _refusal({**MINIMAL, field: "collector"})
    assert isinstance(refusal, InvalidRequestError)
    assert [item.value for item in refusal.safe_details] == [detail]


def test_gzip_base64_is_unsupported_and_an_unknown_encoding_is_invalid() -> None:
    gzip = _refusal(
        {**MINIMAL, "content": {"format": "markdown", "encoding": "gzip+base64", "body": "H4sI"}}
    )
    assert isinstance(gzip, UnsupportedError)
    assert gzip.safe_details == (SafeDetail.CONTENT_ENCODING,)
    unknown = _refusal(
        {**MINIMAL, "content": {"format": "markdown", "encoding": "rot13", "body": "x"}}
    )
    assert isinstance(unknown, InvalidRequestError)
    assert unknown.safe_details == (SafeDetail.CONTENT,)


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"title": "   "}, SafeDetail.TITLE),
        ({"content": {"format": "markdown", "body": "x", "extra": 1}}, SafeDetail.CONTENT),
        ({"content": {"format": "pdf", "body": "x"}}, SafeDetail.CONTENT),
        ({"type": "Not A Token"}, SafeDetail.REPORT_TYPE),
        ({"topics": ["a", "A"]}, SafeDetail.TOPICS),
        ({"tags": "not-a-list"}, SafeDetail.TAGS),
        ({"summary": ""}, SafeDetail.SUMMARY),
        ({"report_date": "2026-13-01"}, SafeDetail.REPORT_DATE),
        ({"coverage_period": {"start": "2026-11-02T00:00:00"}}, SafeDetail.COVERAGE_PERIOD),
        (
            {
                "coverage_period": {
                    "start": "2026-11-03T00:00:00Z",
                    "end": "2026-11-02T00:00:00Z",
                }
            },
            SafeDetail.COVERAGE_PERIOD,
        ),
        (
            {"associations": [{"target_kind": "planet", "target_ref": "x", "relation": "r"}]},
            SafeDetail.ASSOCIATIONS,
        ),
        (
            {
                "associations": [
                    {
                        "target_kind": "external_source",
                        "target_ref": "x",
                        "relation": "cites",
                        "verification": "verified",
                    }
                ]
            },
            SafeDetail.ASSOCIATIONS,
        ),
        ({"metadata": {"_reserved": 1}}, SafeDetail.METADATA),
        ({"client_intent_id": "-leading-dash"}, SafeDetail.CLIENT_INTENT_ID),
        ({"idempotency_key": ""}, SafeDetail.IDEMPOTENCY_KEY),
    ],
)
def test_each_invalid_field_names_itself(payload: dict[str, Any], detail: SafeDetail) -> None:
    refusal = _refusal({**MINIMAL, **payload})
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details[0] is detail


def test_a_512_kib_markdown_body_fits_the_request_ceiling_and_one_byte_more_does_not() -> None:
    body = "a" * INLINE_CONTENT_MAX_BYTES
    request = {
        "request_id": "req",
        "purpose": "report_authoring",
        "principal_id": "prn_aaaa0001aaaa0001aaaa0001",
        "requested_at": "2026-11-04T12:00:00Z",
        "payload": {**MINIMAL, "content": {"format": "markdown", "body": body}},
    }
    assert len(json.dumps(request, separators=(",", ":")).encode()) <= MAX_REQUEST_BYTES
    _metadata, command = normalize(Capability.REPORTS_PUBLISH.value, request)
    assert isinstance(command, PublishGeneralReport)
    over = _refusal({**MINIMAL, "content": {"format": "markdown", "body": body + "a"}})
    assert isinstance(over, InvalidRequestError)
    assert over.safe_details == (SafeDetail.CONTENT, SafeDetail.MAX_BYTES)


# ---- standalone read ----------------------------------------------------------------


def test_the_standalone_read_returns_the_exact_version_manifest_and_digests(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    published = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_PUBLISH,
            {
                **MINIMAL,
                "content": {"format": "mixed", "body": BODY, "data": {"risk": 3}},
                "type": "schedule_risk",
                "topics": ["schedule"],
                "associations": [
                    {
                        "target_kind": "external_source",
                        "target_ref": "https://example.invalid/source",
                        "relation": "cites",
                    }
                ],
            },
        )
    )
    report_id = published["report_id"]
    for selector in ({}, {"version_number": 1}, {"version_id": published["version_id"]}):
        read = _ok(
            _invoke(
                service,
                scene,
                Capability.REPORTS_READ,
                {"report_id": report_id, "include_manifest": True, **selector},
            )
        )
        assert read["plane"] == "standalone"
        assert read["version_id"] == published["version_id"]
        assert read["version_number"] == 1
        assert read["type"] == "schedule_risk"
        assert read["content"]["body"] == BODY
        assert read["content"]["data"] == {"risk": 3}
        assert read["content"]["decoded_sha256"] == published["content"]["decoded_sha256"]
        assert read["content"]["canonical_sha256"] == published["content"]["decoded_sha256"]
        assert read["manifest_sha256"] == published["manifest_sha256"]
        assert manifest_digest(read["manifest"]) == published["manifest_sha256"]
        assert read["manifest"]["report_id"] == report_id
        assert read["associations"][0]["verification"] == "asserted"
    without = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    assert "manifest" not in without
    bare = _ok(
        _invoke(
            service, scene, Capability.REPORTS_READ, {"report_id": report_id, "include_body": False}
        )
    )
    assert "body" not in bare["content"]
    assert "data" not in bare["content"]


def test_foreign_nonexistent_and_wrong_version_reads_are_one_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, dict(MINIMAL)))["report_id"]
    answers = [
        _invoke(
            service, scene, Capability.REPORTS_READ, {"report_id": report_id}, principal=operator()
        ),
        _invoke(service, scene, Capability.REPORTS_READ, {"report_id": "grpt_00000000nothere0"}),
        _invoke(
            service, scene, Capability.REPORTS_READ, {"report_id": report_id, "version_number": 2}
        ),
    ]
    errors = [{k: v for k, v in a["error"].items() if k != "correlation_id"} for a in answers]
    assert errors[0]["code"] == ErrorCode.NOT_FOUND.value
    assert errors[0]["safe_details"] == ["artifact_id"]
    assert errors[0] == errors[1] == errors[2]


def test_a_withdrawn_report_is_hidden_unless_asked_for(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, dict(MINIMAL)))["report_id"]
    key = (scene.principal.principal_id, report_id)
    stored = scene.world.general_report_versions[key]
    scene.world.general_report_versions[key] = replace(
        stored, root=replace(stored.root, lifecycle_state=LifecycleState.ARCHIVED)
    )
    hidden = _invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id})
    assert hidden["error"]["code"] == ErrorCode.NOT_FOUND.value
    shown = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_READ,
            {"report_id": report_id, "include_withdrawn": True},
        )
    )
    assert shown["lifecycle_state"] == "archived"


def test_an_integrity_failure_is_refused_never_returned(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import conftest

    service = build_service(scene.world, scene.providers)
    report_id = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, dict(MINIMAL)))["report_id"]

    def tampered(*_args: object, **_kwargs: object) -> None:
        raise ReportIntegrityError()

    monkeypatch.setattr(conftest._GeneralReports, "read_version", tampered)
    answer = _invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id})
    assert answer["result"] is None
    assert answer["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert BODY not in json.dumps(answer)


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"version_id": "grver_00000000abcdefgh", "version_number": 1}, "version_id"),
        ({"version_id": "rptv_00000000abcdefgh"}, "version_id"),
        ({"version_number": 0}, "version_number"),
        ({"include_manifest": "yes"}, "include_manifest"),
        ({"include_withdrawn": 1}, "include_withdrawn"),
    ],
)
def test_the_standalone_selectors_are_validated(payload: dict[str, Any], detail: str) -> None:
    refusal = _refusal(
        {"report_id": "grpt_00000000abcdefgh", **payload}, capability=Capability.REPORTS_READ
    )
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details[0].value == detail


def test_a_legacy_identifier_keeps_its_legacy_command_shape() -> None:
    command = ReadIntelligenceArtifact(report_id="rpt_00000000abcdefgh")
    assert command.standalone is False
    assert command.include_body is True
    assert ReadIntelligenceArtifact(report_id="grpt_00000000abcdefgh").standalone is True
