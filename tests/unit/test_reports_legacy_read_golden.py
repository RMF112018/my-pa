"""Reports Modernization WP02: the legacy `rpt_` `reports.read` is byte-identical.

`reports.read` now also reads standalone `grpt_` reports. That extension must
leave the pipeline plane's read exactly as it was, for every input that plane
already accepted and every refusal it already gave. `GOLDEN` was captured by
running `_transcript` against the base tree (`09a05158c`, before the
extension) and is compared here byte for byte, after replacing the identifiers
the server mints randomly with stable placeholders.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import BeginIntelligenceCycle, CommitIntelligenceArtifact
from my_pa.application.errors import ApplicationError, problem_detail
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from tests.conftest import Scene, build_service, metadata_for

BODY: Final = "# Collector\n\nGolden legacy read body."

#: Captured at base `09a05158c` by `_transcript`; see the module docstring.
GOLDEN: Final = (
    '{"absent_id":{"error":{"code":"invalid_request","correlation_id":"<correlation_i'
    'd>","message":"the request is malformed, incomplete, or contradictory","retry":"'
    'after_correction","safe_details":[]},"refused_by":"normalize"},"bad_include_body'
    '":{"error":{"code":"invalid_request","correlation_id":"<correlation_id>","messag'
    'e":"the request is malformed, incomplete, or contradictory","retry":"after_corre'
    'ction","safe_details":["selector"]},"refused_by":"normalize"},"body":{"error":nu'
    'll,"result":{"artifact_kind":"collector_candidates","artifact_state":"final","bo'
    'dy_markdown":"# Collector\\n\\nGolden legacy read body.","committed_at":"2026-08-0'
    '2T12:00:00.000Z","content_bytes":37,"content_sha256":"f3ca330f1a6f8d4ef523f6aab9'
    '0480586fb1d0069368e127559f9c431ec0556a","cycle_run_id":"<cycle_run_id>","depende'
    'ncy_report_ids":[],"focus_area_id":"communications","provenance":[],"report_date'
    '":"2026-08-20","report_id":"<report_id>","report_run_id":"<report_run_id>","sour'
    'ce_lane":null,"stage":"collector","structured_content":{"items":[1,2],"note":"sy'
    'nthetic"},"supersedes_report_id":null,"title":"Golden collector","version":1}},"'
    'default_include_manifest":{"error":{"code":"invalid_request","correlation_id":"<'
    'correlation_id>","message":"the request is malformed, incomplete, or contradicto'
    'ry","retry":"after_correction","safe_details":[]},"refused_by":"normalize"},"def'
    'ault_include_withdrawn":{"error":{"code":"invalid_request","correlation_id":"<co'
    'rrelation_id>","message":"the request is malformed, incomplete, or contradictory'
    '","retry":"after_correction","safe_details":[]},"refused_by":"normalize"},"defau'
    'lt_on_wrong_kind":{"error":{"code":"invalid_request","correlation_id":"<correlat'
    'ion_id>","message":"the request is malformed, incomplete, or contradictory","ret'
    'ry":"after_correction","safe_details":[]},"refused_by":"normalize"},"default_ver'
    'sion_id":{"error":{"code":"invalid_request","correlation_id":"<correlation_id>",'
    '"message":"the request is malformed, incomplete, or contradictory","retry":"afte'
    'r_correction","safe_details":[]},"refused_by":"normalize"},"default_version_numb'
    'er":{"error":{"code":"invalid_request","correlation_id":"<correlation_id>","mess'
    'age":"the request is malformed, incomplete, or contradictory","retry":"after_cor'
    'rection","safe_details":[]},"refused_by":"normalize"},"malformed":{"error":{"cod'
    'e":"invalid_request","correlation_id":"<correlation_id>","message":"the request '
    'is malformed, incomplete, or contradictory","retry":"after_correction","safe_det'
    'ails":["artifact_id"]},"refused_by":"normalize"},"missing":{"error":{"code":"not'
    '_found","correlation_id":"<correlation_id>","message":"no record matches the req'
    'uest within the authorized scope","retry":"conditional","safe_details":["artifac'
    't_id"]},"result":null},"no_body":{"error":null,"result":{"artifact_kind":"collec'
    'tor_candidates","artifact_state":"final","committed_at":"2026-08-02T12:00:00.000'
    'Z","content_bytes":37,"content_sha256":"f3ca330f1a6f8d4ef523f6aab90480586fb1d006'
    '9368e127559f9c431ec0556a","cycle_run_id":"<cycle_run_id>","dependency_report_ids'
    '":[],"focus_area_id":"communications","provenance":[],"report_date":"2026-08-20"'
    ',"report_id":"<report_id>","report_run_id":"<report_run_id>","source_lane":null,'
    '"stage":"collector","structured_content":{"items":[1,2],"note":"synthetic"},"sup'
    'ersedes_report_id":null,"title":"Golden collector","version":1}},"unknown_field"'
    ':{"error":{"code":"invalid_request","correlation_id":"<correlation_id>","message'
    '":"the request is malformed, incomplete, or contradictory","retry":"after_correc'
    'tion","safe_details":[]},"refused_by":"normalize"},"wrong_kind":{"error":{"code"'
    ':"invalid_request","correlation_id":"<correlation_id>","message":"the request is'
    ' malformed, incomplete, or contradictory","retry":"after_correction","safe_detai'
    'ls":["artifact_id"]},"refused_by":"normalize"}}'
)


def _wire(scene: Scene, payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-golden-read",
        "purpose": Purpose.REPORT_READ.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-08-20T12:00:00Z",
        "payload": payload,
    }


def _answer(service: ApplicationService, scene: Scene, payload: dict[str, object]) -> Any:  # noqa: ANN401
    try:
        metadata, command = normalize(Capability.REPORTS_READ.value, _wire(scene, payload))
    except ApplicationError as error:
        problem = problem_detail(error, correlation_id="corr_golden0000000000000000000000")
        return {"refused_by": "normalize", "error": problem.model_dump(mode="json")}
    envelope = service.invoke(metadata, command, principal=scene.principal)
    rendered = envelope.model_dump(mode="json")
    return {key: rendered[key] for key in ("result", "error")}


def _transcript(scene: Scene) -> str:
    service = build_service(scene.world, scene.providers)
    begun = service.invoke(
        metadata_for(BeginIntelligenceCycle.capability, Purpose.REPORT_AUTHORING, scene.principal),
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-20",
            idempotency_key="golden-cycle",
        ),
        principal=scene.principal,
    )
    assert begun.result is not None, begun.error
    cycle_run_id = str(begun.result["cycle_run_id"])
    committed = service.invoke(
        metadata_for(
            CommitIntelligenceArtifact.capability, Purpose.REPORT_AUTHORING, scene.principal
        ),
        CommitIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="task-golden",
            producer_task_name="Golden collector",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="Golden collector",
            body_markdown=BODY,
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="golden-collector",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            structured_content={"items": [1, 2], "note": "synthetic"},
        ),
        principal=scene.principal,
    )
    assert committed.result is not None, committed.error
    report_id = str(committed.result["report_id"])
    report_run_id = str(committed.result["report_run_id"])
    cases: dict[str, dict[str, object]] = {
        "body": {"report_id": report_id},
        "no_body": {"report_id": report_id, "include_body": False},
        "missing": {"report_id": "rpt_0000000000000000golden"},
        "malformed": {"report_id": "rpt_x"},
        "wrong_kind": {"report_id": "cap_0000000000000000golden"},
        "bad_include_body": {"report_id": report_id, "include_body": "yes"},
        "unknown_field": {"report_id": report_id, "version_number": 1},
        # The four standalone selectors, each at its default value: the
        # legacy plane never had them, so even a default is an unknown field.
        "default_version_id": {"report_id": report_id, "version_id": None},
        "default_version_number": {"report_id": report_id, "version_number": None},
        "default_include_manifest": {"report_id": report_id, "include_manifest": False},
        "default_include_withdrawn": {"report_id": report_id, "include_withdrawn": False},
        "default_on_wrong_kind": {"report_id": "cap_0000000000000000golden", "version_id": None},
        "absent_id": {},
    }
    transcript = json.dumps(
        {name: _answer(service, scene, payload) for name, payload in cases.items()},
        sort_keys=True,
        separators=(",", ":"),
    )
    for value, placeholder in (
        (report_id, "<report_id>"),
        (report_run_id, "<report_run_id>"),
        (cycle_run_id, "<cycle_run_id>"),
    ):
        transcript = transcript.replace(value, placeholder)
    # Issued per request, never part of the read's answer.
    return re.sub(r"corr_[A-Za-z0-9]+", "<correlation_id>", transcript)


def test_the_legacy_read_answers_exactly_as_it_did_before_the_extension(scene: Scene) -> None:
    transcript = _transcript(scene)
    assert transcript == GOLDEN
