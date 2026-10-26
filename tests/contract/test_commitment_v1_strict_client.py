"""AT-015 + AT-023 (S4): a strict old client sees nothing new on the v1 Commitment reads.

Record lineage S4 contract sections 7.3, 7.6 and 8 (worker M3). The opt-in to
Project references is the capability name (`commitments.v2.*`); the 4 v1
Commitment reads keep their request schemas, their answers and their view
keys, with the switch on and over Commitments that store a `project_id`:

* `test_v1_commitment_answers_are_byte_identical` (database) -- the same v1
  request answers the same bytes with `MY_PA_PROGRAM_REPORTING_ENABLED` on as
  with it off;
* `test_v1_tool_schemas_are_unchanged_by_s4` -- the S3 payload-schema pin over
  the 192 v1 tools holds, and the envelope's `$defs.Purpose.enum` is exactly
  the basis enum plus `program_reporting_read` (R4-F04, R4-F15);
* `test_v1_commitment_views_keep_their_keys` -- the 3 v1 Commitment views'
  field lists, exactly;
* `test_s4_adds_no_gateway_entry` -- the web BFF contract still names 110
  capabilities and no S4 one (section 7.6).

Every identity here is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pytest
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_s4_harness import T0, S4Runtime

from my_pa.adapters.mcp.tools import TOOLS
from my_pa.application.commands import (
    Command,
    ListCommitments,
    ReadCommitment,
    SearchCommitments,
    WaitingOn,
)
from my_pa.application.service import _LINEAGE_CAPABILITIES
from my_pa.contracts.v1.commitments import CommitmentListEntry, CommitmentView, WaitingOnEntry
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

ROOT: Final = Path(__file__).resolve().parents[2]
GATEWAY_CONTRACT: Final = ROOT / "web" / "src" / "contracts" / "gateway.json"

#: The S3 pin of `test_lineage_s3_capability_admission`: SHA-256 of every
#: non-lineage, non-S4 tool's `payload` schema (canonical JSON), measured at the
#: S2 basis `84ddab37` and unchanged since.
V1_PAYLOAD_SCHEMA_SHA256: Final = "e87a5186273905f60ae033764f70d6715cb01829a56a19e77409ab2d2de63ebb"
#: SHA-256 of the envelope `$defs.Purpose.enum` at the S4 basis (`3d1593aa`,
#: the 59 `Purpose` values in declaration order, compact JSON).
BASIS_PURPOSE_ENUM_SHA256: Final = (
    "29c46c3112e62fe8a032e82030e57850aa9b2fae0d1d562b2095c502b34e02e6"
)
#: The 3 v1 Commitment views, field for field, in declaration order.
V1_COMMITMENT_VIEW_FIELDS: Final[dict[type, tuple[str, ...]]] = {
    CommitmentView: (
        "commitment_id",
        "direction",
        "state",
        "counterparty_entity_id",
        "title",
        "description",
        "due_date",
        "created_at",
        "updated_at",
        "version",
        "evidence_state",
        "origin_evidence_ref",
        "closure_evidence_ref",
        "accepted_by_review_decision_id",
        "closed_at",
        "origin_evidence_capture_state",
        "closure_evidence_capture_state",
    ),
    CommitmentListEntry: (
        "commitment_id",
        "direction",
        "state",
        "counterparty_entity_id",
        "title",
        "description",
        "due_date",
        "created_at",
        "updated_at",
        "version",
        "origin_evidence_capture_state",
        "closure_evidence_capture_state",
    ),
    WaitingOnEntry: (
        "commitment_id",
        "title",
        "counterparty_entity_id",
        "due_date",
        "state",
        "follow_up_task_id",
        "follow_up_task_title",
        "follow_up_task_state",
        "origin_evidence_capture_state",
        "closure_evidence_capture_state",
    ),
}
#: The 4 v1 Commitment reads, by capability name.
V1_READS: Final = frozenset(
    {"commitments.read", "commitments.list", "commitments.search", "commitments.waiting_on"}
)


def _canonical_sha256(document: object) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _bytes(envelope: ResponseEnvelope) -> bytes:
    """The answer's bytes, without its per-request values.

    Those are the request and correlation ids, the completion instant and the
    disclosure's `freshness.observed_at` (the instant the request was served);
    every other byte, `result` included, is compared.
    """
    document = envelope.to_canonical_dict()
    for per_request in ("request_id", "correlation_id", "completed_at"):
        document.pop(per_request)
    assert document.get("error") is None, document
    document["disclosure"]["freshness"].pop("observed_at")
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


@pytest.mark.database
def test_v1_commitment_answers_are_byte_identical(disposable_database: str) -> None:
    on = S4Runtime(disposable_database)
    off = S4Runtime(disposable_database, program_reporting_enabled=False)
    try:
        project, _entity = on.seeds.project("Strict client project")
        situation = on.context_situation("strict-client")
        stored = on.work_commitment(
            "strict-stored", project_id=project, situation_id=situation, due_at=T0
        )
        on.follow_up(stored, "strict-stored")
        plain = on.work_commitment("strict-plain")
        proposed = on.work_commitment("strict-proposed", project_id=project, accepted=False)
        requests: list[Command] = [
            ReadCommitment(commitment_id=stored),
            ReadCommitment(commitment_id=plain),
            ReadCommitment(commitment_id=proposed),
            ListCommitments(),
            ListCommitments(page_size=1),
            SearchCommitments(query="strict"),
            WaitingOn(),
        ]
        assert {request.capability.value for request in requests} == V1_READS
        for request in requests:
            served_on = on.invoke(request, principal_id=PRINCIPAL)
            served_off = off.invoke(request, principal_id=PRINCIPAL)
            assert _bytes(served_on) == _bytes(served_off), request.capability.value
            # And the stored Project never reaches a v1 answer.
            assert project not in _bytes(served_on).decode("utf-8"), request.capability.value
        listed = on.ok(ListCommitments())["commitments"]
        assert {stored, plain, proposed} <= {entry["commitment_id"] for entry in listed}
        for entry in listed:
            assert set(entry) == {*V1_COMMITMENT_VIEW_FIELDS[CommitmentListEntry], "counterparty"}
    finally:
        off.close()
        on.close()


def test_v1_tool_schemas_are_unchanged_by_s4() -> None:
    excluded = {capability.value for capability in _LINEAGE_CAPABILITIES}
    excluded |= PROGRAM_REPORTING_CAPABILITIES
    payloads = {
        tool.name: tool.input_schema["properties"]["payload"]
        for tool in TOOLS
        if tool.name not in excluded
    }
    assert len(payloads) == 192
    assert set(payloads) >= V1_READS
    assert _canonical_sha256(payloads) == V1_PAYLOAD_SCHEMA_SHA256
    # Every tool carries the one envelope purpose enum: the basis enum, then
    # exactly the one S4 purpose -- nothing removed, reordered or added beside it.
    enums = {json.dumps(tool.input_schema["$defs"]["Purpose"]["enum"]) for tool in TOOLS}
    assert len(enums) == 1
    published = json.loads(enums.pop())
    assert len(published) == 60
    basis = published[:-1]
    assert hashlib.sha256(json.dumps(basis, separators=(",", ":")).encode("utf-8")).hexdigest() == (
        BASIS_PURPOSE_ENUM_SHA256
    )
    assert published[-1] == "program_reporting_read"
    assert "program_reporting_read" not in basis


def test_v1_commitment_views_keep_their_keys() -> None:
    for view, fields in V1_COMMITMENT_VIEW_FIELDS.items():
        assert tuple(view.__dataclass_fields__) == fields, view.__name__
        for added in ("project_id", "situation_id", "project_reference", "situation_reference"):
            assert added not in view.__dataclass_fields__, (view.__name__, added)


def test_s4_adds_no_gateway_entry() -> None:
    contract: dict[str, Any] = json.loads(GATEWAY_CONTRACT.read_text(encoding="utf-8"))
    declared = set(contract["capabilities"])
    assert len(declared) == 110
    assert not declared & PROGRAM_REPORTING_CAPABILITIES
    # The v1 Commitment reads the web client calls are still the v1 names.
    assert not {name for name in declared if ".v2." in name}
