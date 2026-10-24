"""The report manifest's pure rules (record lineage S4 contract sections 5.2-5.4, WP-04C).

FAST, over `domain.intelligence.source_manifest`:

* **Golden vectors** (`tests/fixtures/report_manifest_vectors.json`): the exact
  canonical text and digest of `J` over structured content -- an already-normal
  float, a non-ASCII string, C0 controls and DEL, each escaped -- and of whole
  manifests, including the exact instant format (6 fractional digits, a literal
  `Z`, never `+00:00`). Unit vectors hold integers, strings and already-normal
  floats only; numbers JSONB renormalizes are the SQL path's (section 5.2).
* **The Program reference block** (section 5.4): exactly its 4 keys, each of
  its exact type, on a synthesizer, reporter or morning brief only.
* **Every key** of section 5.3 is present in every manifest, whatever is null.
* **Candidates are never typed**: a collector's manifest says
  `unaccepted_candidate`, every other stage `not_a_candidate`, and every
  provenance reference is `uncertified_reference`.

Every identity is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.intelligence.catalog import (
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProvenanceRelation,
    SourceLaneId,
)
from my_pa.domain.intelligence.models import (
    IntelligenceArtifact,
    IntelligencePipelineDependency,
    IntelligenceProvenanceRef,
)
from my_pa.domain.intelligence.source_manifest import (
    MANIFEST_DIGEST_PREFIX,
    STRUCTURED_CONTENT_DIGEST_PREFIX,
    DependencyDigests,
    ProgramReferenceBlock,
    ProgramReferenceError,
    build_manifest,
    canonical,
    manifest_digest,
    program_reference_block,
    program_section,
    structured_content_sha256,
)
from my_pa.domain.program.vocabulary import (
    PROGRAM_REFERENCE_BLOCK_KEY,
    ProgramFamily,
    RecomputeFailure,
)

VECTORS: Final = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "report_manifest_vectors.json").read_text(
        encoding="utf-8"
    )
)

#: Section 5.3: the manifest's top-level keys and its `report` keys, every one present.
MANIFEST_KEYS: Final = {
    "manifest_schema_version",
    "report",
    "structured_content",
    "candidate_status",
    "dependencies",
    "provenance",
    "program",
}
REPORT_KEYS: Final = {
    "report_id",
    "cycle_run_id",
    "producer_run_id",
    "stage",
    "artifact_kind",
    "focus_area_id",
    "source_lane",
    "report_date",
    "version",
    "supersedes_report_id",
    "schema_version",
    "producer_prompt_version",
    "title_sha256",
    "content_sha256",
    "content_bytes",
    "committed_at",
    "artifact_state_at_commit",
    "producer_completeness",
}
DEPENDENCY_KEYS: Final = {
    "report_id",
    "dependency_role",
    "required",
    "content_sha256",
    "structured_content_sha256",
    "manifest_sha256",
    "manifest_state",
}
PROVENANCE_KEYS: Final = {
    "position",
    "source_system",
    "source_ref",
    "relation",
    "source_url",
    "observed_at",
    "retrieved_at",
    "evidence_subject_id",
    "certification",
}
PROGRAM_KEYS: Final = {
    "block_schema_version",
    "program_entity_ids",
    "claimed_overview_sha256",
    "claimed_source_cutoff_at",
    "verification_state",
    "recompute_failure",
    "families_seen",
    "server",
}
_KIND_FOR_STAGE: Final = {
    IntelligenceStage.COLLECTOR: "collector_candidates",
    IntelligenceStage.RESEARCHER: "research_context",
    IntelligenceStage.SYNTHESIZER: "synthesis_package",
    IntelligenceStage.REPORTER: "focus_report",
    IntelligenceStage.MORNING_BRIEF: "morning_brief",
}
#: A valid block, as a producer writes it (section 5.4).
BLOCK: Final = {
    "block_schema_version": 1,
    "program_entity_ids": ["ent_unitprogram00001", "ent_unitprogram00002"],
    "overview_sha256": "a" * 64,
    "source_cutoff_at": "2026-10-24T06:30:00.000001Z",
}


def _instant(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def artifact_of(values: dict[str, Any]) -> IntelligenceArtifact:
    """An artifact from a vector's `artifact` object (defaults for every other field)."""
    stage = IntelligenceStage(values["stage"])
    committed = _instant(values.get("committed_at", "2026-10-24T06:30:00+00:00"))
    assert committed is not None
    return IntelligenceArtifact(
        artifact_id=values["artifact_id"],
        principal_id="prn_vectorprincipal01",
        cycle_run_id="micr_vectorcycle0001",
        producer_run_id="rrun_vectorrun000001",
        stage=stage,
        artifact_kind=values.get("artifact_kind", _KIND_FOR_STAGE[stage]),
        report_date=date.fromisoformat(values.get("report_date", "2026-10-24")),
        title=values.get("title", "Vector title"),
        body_markdown="body",
        content_sha256=values.get("content_sha256", "a" * 64),
        content_bytes=4,
        artifact_state=ArtifactState(values.get("artifact_state", "final")),
        schema_version="1",
        generated_at=committed,
        committed_at=committed,
        version=values.get("version", 1),
        is_current=True,
        focus_area_id=(
            None if values.get("focus_area_id") is None else FocusAreaId(values["focus_area_id"])
        ),
        source_lane=(
            None if values.get("source_lane") is None else SourceLaneId(values["source_lane"])
        ),
        completeness=values.get("completeness"),
        producer_prompt_version=values.get("producer_prompt_version"),
        supersedes_artifact_id=values.get("supersedes_artifact_id"),
        dependencies=tuple(
            IntelligencePipelineDependency(
                upstream_artifact_id=row["upstream_artifact_id"],
                dependency_role=row["dependency_role"],
            )
            for row in values.get("dependencies", [])
        ),
        provenance=tuple(
            IntelligenceProvenanceRef(
                source_system=row["source_system"],
                source_ref=row["source_ref"],
                relation=ProvenanceRelation(row["relation"]),
                source_url=row["source_url"],
                observed_at=_instant(row["observed_at"]),
                retrieved_at=_instant(row["retrieved_at"]),
                evidence_subject_id=row["evidence_subject_id"],
            )
            for row in values.get("provenance", [])
        ),
    )


def dependencies_of(rows: list[dict[str, Any]]) -> tuple[DependencyDigests, ...]:
    return tuple(DependencyDigests(**row) for row in rows)


@pytest.mark.parametrize("vector", VECTORS["manifest"], ids=lambda vector: vector["name"])
def test_manifest_golden_vectors(vector: dict[str, Any]) -> None:
    built = build_manifest(
        artifact_of(vector["artifact"]),
        stored_structured_content=vector["stored_structured_content"],
        dependencies=dependencies_of(vector["dependencies"]),
        program=vector["program"],
    )
    assert built.manifest_canonical == vector["expected_canonical"]
    assert built.manifest_sha256 == vector["expected_sha256"]
    # The digest is the database CHECK's: over the domain separator and the text.
    assert (
        built.manifest_sha256
        == hashlib.sha256(
            MANIFEST_DIGEST_PREFIX + vector["expected_canonical"].encode()
        ).hexdigest()
    )
    assert manifest_digest(built.manifest_canonical) == built.manifest_sha256
    # Printable ASCII only (`a_manifest_is_printable_ascii`), whatever the input held.
    assert all(" " <= character <= "~" for character in built.manifest_canonical)
    decoded = json.loads(built.manifest_canonical)
    # The exact instant format: 6 fractional digits and a literal `Z`.
    instants = [decoded["report"]["committed_at"]] + [
        value
        for row in decoded["provenance"]
        for value in (row["observed_at"], row["retrieved_at"])
        if value is not None
    ]
    for value in instants:
        assert value.endswith("Z")
        assert "+00:00" not in value
        assert len(value.split(".")[1]) == len("000000Z")
    assert decoded["program"] == vector["program"]
    assert built.program_verification_state == (
        None if vector["program"] is None else vector["program"]["verification_state"]
    )


def test_the_instant_format_is_pinned() -> None:
    (collector, synthesizer) = VECTORS["manifest"]
    assert '"committed_at":"2026-10-24T06:30:00.000000Z"' in collector["expected_canonical"]
    assert '"observed_at":"2026-10-23T23:59:59.999999Z"' in collector["expected_canonical"]
    assert '"retrieved_at":"2026-10-24T01:00:00.500000Z"' in collector["expected_canonical"]
    assert '"committed_at":"2026-10-24T06:30:00.123456Z"' in synthesizer["expected_canonical"]


@pytest.mark.parametrize("vector", VECTORS["structured_content"], ids=lambda vector: vector["name"])
def test_structured_content_digest_golden_vectors(vector: dict[str, Any]) -> None:
    assert canonical(vector["input"]).decode("ascii") == vector["expected_canonical"]
    assert structured_content_sha256(vector["input"]) == vector["expected_sha256"]
    assert (
        vector["expected_sha256"]
        == hashlib.sha256(
            STRUCTURED_CONTENT_DIGEST_PREFIX + vector["expected_canonical"].encode("ascii")
        ).hexdigest()
    )
    # The canonical text is valid JSON for the same value.
    assert json.loads(vector["expected_canonical"]) == vector["input"]
    assert structured_content_sha256(None) is None


def test_del_and_controls_are_escaped_never_raw() -> None:
    """The S4 M1 DEL hazard: `ensure_ascii` escapes 0x7f, so a manifest stays printable."""
    (vector,) = (row for row in VECTORS["structured_content"] if "del" in row["name"])
    assert "\\u007f" in vector["expected_canonical"]
    assert "\\u0001" in vector["expected_canonical"]
    assert "\x7f" not in vector["expected_canonical"]
    collector = VECTORS["manifest"][0]
    assert '"source_ref":"msg-1\\u007fdel"' in collector["expected_canonical"]


def _block(**changes: Any) -> dict[str, object]:  # noqa: ANN401
    block = dict(BLOCK)
    block.update(changes)
    return {PROGRAM_REFERENCE_BLOCK_KEY: block, "other": 1}


def test_program_reference_block_shape() -> None:
    stage = IntelligenceStage.SYNTHESIZER
    assert program_reference_block(None, stage=stage) is None
    assert program_reference_block({"other": 1}, stage=stage) is None
    assert program_reference_block(_block(), stage=stage) == ProgramReferenceBlock(
        program_entity_ids=("ent_unitprogram00001", "ent_unitprogram00002"),
        overview_sha256="a" * 64,
        source_cutoff_at="2026-10-24T06:30:00.000001Z",
    )
    for allowed in (IntelligenceStage.REPORTER, IntelligenceStage.MORNING_BRIEF):
        assert program_reference_block(_block(), stage=allowed) is not None
    malformed: list[dict[str, object]] = [
        {PROGRAM_REFERENCE_BLOCK_KEY: "not an object"},
        {PROGRAM_REFERENCE_BLOCK_KEY: {**BLOCK, "extra": 1}},
        {PROGRAM_REFERENCE_BLOCK_KEY: {key: BLOCK[key] for key in list(BLOCK)[1:]}},
        _block(block_schema_version=2),
        _block(block_schema_version=True),
        _block(block_schema_version="1"),
        _block(program_entity_ids=[]),
        _block(program_entity_ids=[f"ent_unitprogram{index:05d}" for index in range(11)]),
        _block(program_entity_ids=["ent_unitprogram00001", "ent_unitprogram00001"]),
        _block(program_entity_ids=["prj_unitproject00001"]),
        _block(program_entity_ids="ent_unitprogram00001"),
        _block(program_entity_ids=[1]),
        _block(overview_sha256="A" * 64),
        _block(overview_sha256="a" * 63),
        _block(overview_sha256=None),
        _block(source_cutoff_at="2026-10-24T06:30:00Z"),
        _block(source_cutoff_at="2026-10-24T06:30:00.000001+00:00"),
        _block(source_cutoff_at="2026-10-24 06:30:00.000001Z"),
        _block(source_cutoff_at=0),
    ]
    for content in malformed:
        with pytest.raises(ProgramReferenceError):
            program_reference_block(content, stage=stage)
    # A collector or researcher may not carry one, however well formed.
    for refused in (IntelligenceStage.COLLECTOR, IntelligenceStage.RESEARCHER):
        with pytest.raises(ProgramReferenceError):
            program_reference_block(_block(), stage=refused)


def test_program_sections_by_outcome() -> None:
    block = program_reference_block(_block(), stage=IntelligenceStage.REPORTER)
    assert block is not None
    claim = program_section(block)
    assert set(claim) == PROGRAM_KEYS
    assert (claim["verification_state"], claim["server"], claim["families_seen"]) == (
        "not_attempted",
        None,
        None,
    )
    failed = program_section(block, failure=RecomputeFailure.STATEMENT_TIMEOUT)
    assert (failed["verification_state"], failed["recompute_failure"]) == (
        "recompute_failed",
        "statement_timeout",
    )
    families = frozenset(ProgramFamily)
    same = program_section(block, server={"overview_sha256": "a" * 64}, families_seen=families)
    assert same["verification_state"] == "verified_at_commit"
    # Never `situation`: no overview field derives from it (R4-F23).
    assert same["families_seen"] == ["commitment", "constraint", "entity", "issue", "project"]
    moved = program_section(block, server={"overview_sha256": "b" * 64}, families_seen=families)
    assert moved["verification_state"] == "changed_since_read"
    with pytest.raises(ValueError, match="bound together"):
        program_section(block, server={"overview_sha256": "a" * 64})


@pytest.mark.parametrize("vector", VECTORS["manifest"], ids=lambda vector: vector["name"])
def test_the_manifest_has_every_key(vector: dict[str, Any]) -> None:
    decoded = json.loads(vector["expected_canonical"])
    assert set(decoded) == MANIFEST_KEYS
    assert set(decoded["report"]) == REPORT_KEYS
    assert set(decoded["structured_content"]) == {"present", "sha256"}
    assert all(set(row) == DEPENDENCY_KEYS for row in decoded["dependencies"])
    assert all(set(row) == PROVENANCE_KEYS for row in decoded["provenance"])
    if decoded["program"] is not None:
        assert set(decoded["program"]) == PROGRAM_KEYS
    # Dependencies in report-id (`COLLATE "C"`) order, provenance by position.
    ids = [row["report_id"] for row in decoded["dependencies"]]
    assert ids == sorted(ids)
    positions = [row["position"] for row in decoded["provenance"]]
    assert positions == list(range(1, len(positions) + 1))
    # A legacy upstream is named as such, a recorded one carries its manifest.
    for row in decoded["dependencies"]:
        assert row["manifest_state"] == (
            "manifest_unavailable_legacy" if row["manifest_sha256"] is None else "recorded"
        )
    # No narrative: the title is a digest only.
    assert "title" not in decoded["report"]
    # Excluded by design (section 5.3, D-23).
    for excluded in ("is_current", "artifact_state", "evaluation_metric_id", "body_markdown"):
        assert excluded not in decoded["report"]


@pytest.mark.parametrize("stage", list(IntelligenceStage), ids=lambda stage: stage.value)
def test_candidate_status_by_stage(stage: IntelligenceStage) -> None:
    built = build_manifest(
        artifact_of(
            {
                "artifact_id": "rpt_unitstagevector1",
                "stage": stage.value,
                "focus_area_id": None
                if stage is IntelligenceStage.MORNING_BRIEF
                else "risk_deadline_exception",
                "source_lane": "sharepoint" if stage is IntelligenceStage.RESEARCHER else None,
                "provenance": [
                    {
                        "source_system": "procore",
                        "source_ref": "RFI-12",
                        "relation": "supports",
                        "source_url": None,
                        "observed_at": None,
                        "retrieved_at": None,
                        "evidence_subject_id": None,
                    }
                ],
            }
        ),
        stored_structured_content=None,
        dependencies=(),
    )
    decoded = json.loads(built.manifest_canonical)
    assert decoded["candidate_status"] == (
        "unaccepted_candidate" if stage is IntelligenceStage.COLLECTOR else "not_a_candidate"
    )
    # A reference is never typed: no field could call it a Procore RFI, a
    # financial fact or an accepted record.
    assert [row["certification"] for row in decoded["provenance"]] == ["uncertified_reference"]
    for forbidden in ("rfi", "financial", "accepted", "record_type", "source_type"):
        assert forbidden not in json.dumps(sorted(_keys(decoded)))


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()
