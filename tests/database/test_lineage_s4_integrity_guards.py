"""AT-022 (guards): the record lineage S4 report-manifest guards, on a live server.

The S4 revision (S4 contract section 4.1) puts the manifest invariants in the
database so they hold for every writer: the digest is the canonical text's, a
manifest names its own artifact (report id, Markdown digest, structured-content
digest and the Program claim), every artifact committed after the revision has
its manifest by commit, and manifests are append-only and refuse TRUNCATE. Each
test drives one guard with direct SQL and asserts the SQLSTATE and the guard's
own message or constraint name, so a test can only pass for the reason it names.

`database` tier on a disposable head-migrated clone per test. Every value is
synthetic.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from my_pa.application.commands import BeginIntelligenceCycle, CommitIntelligenceArtifact
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import operator
from tests.database.test_intelligence_artifact_plane import _ok, _service
from tests.database.test_lineage_integrity_guards import CHECK, RESTRICT, _refused

pytestmark = pytest.mark.database

RAISE_EXCEPTION: Final = "P0001"
#: The columns copied from one artifact row into another by direct SQL.
_ARTIFACT_COLUMNS: Final = (
    "cycle_run_id, producer_run_id, focus_area_id, stage, artifact_kind, source_lane, "
    "report_date, title, body_markdown, structured_content, content_sha256, content_bytes, "
    "artifact_state, completeness, schema_version, producer_prompt_version, generated_at, "
    "committed_at, version"
)


def _committed(engine: Engine) -> tuple[str, str, str]:
    """`(principal_id, artifact_id, content_sha256)` of one artifact committed normally."""
    service = _service(engine)
    principal = operator()
    cycle = _ok(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-20",
            idempotency_key="s4-guard-cycle",
        ),
    )["cycle_run_id"]
    committed = _ok(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=str(cycle),
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="s4-guard-collector",
            producer_task_name="S4 guard collector",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="S4 guard collector",
            body_markdown="# Collector\n\nsynthetic S4 guard",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="s4-guard-collector",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            structured_content={"candidates": 3},
        ),
    )
    return principal.principal_id, str(committed["report_id"]), str(committed["content_sha256"])


def _copy_artifact(c: Connection, principal: str, source: str) -> str:
    """A second artifact row, inserted by direct SQL (no manifest, not current)."""
    copy = issue_identifier(IdKind.INTELLIGENCE_ARTIFACT)
    c.execute(
        text(
            f"INSERT INTO knowledge.intelligence_artifacts (principal_id, artifact_id, "  # noqa: S608
            f"{_ARTIFACT_COLUMNS}, is_current) SELECT principal_id, :copy, {_ARTIFACT_COLUMNS}, "
            "false FROM knowledge.intelligence_artifacts "
            "WHERE principal_id = :p AND artifact_id = :source"
        ),
        {"p": principal, "copy": copy, "source": source},
    )
    return copy


def _manifest(
    report_id: str,
    content_sha256: str,
    *,
    structured: str | None = None,
    program: dict[str, object] | None = None,
) -> str:
    return json.dumps(
        {
            "manifest_schema_version": 1,
            "report": {"report_id": report_id, "content_sha256": content_sha256},
            "structured_content": {"present": structured is not None, "sha256": structured},
            "program": program,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(canonical: str) -> str:
    return hashlib.sha256(b"report-manifest-v1\n" + canonical.encode("ascii")).hexdigest()


def _insert_manifest(
    c: Connection,
    principal: str,
    artifact_id: str,
    canonical: str,
    *,
    digest: str | None = None,
    structured: str | None = None,
    claimed: str | None = None,
    state: str | None = None,
) -> None:
    c.execute(
        text(
            "INSERT INTO knowledge.intelligence_artifact_manifests (principal_id, artifact_id, "
            "manifest_schema_version, manifest_canonical, manifest_sha256, "
            "structured_content_sha256, program_overview_sha256, program_verification_state) "
            "VALUES (:p, :a, 1, :canonical, :digest, :structured, :claimed, :state)"
        ),
        {
            "p": principal,
            "a": artifact_id,
            "canonical": canonical,
            "digest": _digest(canonical) if digest is None else digest,
            "structured": structured,
            "claimed": claimed,
            "state": state,
        },
    )


def test_a_manifest_digest_must_be_its_canonical_text(db_engine: Engine) -> None:
    principal, source, content = _committed(db_engine)

    def wrong_digest(c: Connection) -> None:
        copy = _copy_artifact(c, principal, source)
        _insert_manifest(c, principal, copy, _manifest(copy, content), digest="0" * 64)

    _refused(db_engine, wrong_digest, CHECK, "a_report_manifest_digest_is_its_canonical_text")

    # The same row with the digest of its own text is admitted.
    with db_engine.begin() as c:
        copy = _copy_artifact(c, principal, source)
        _insert_manifest(c, principal, copy, _manifest(copy, content))
    with db_engine.connect() as c:
        stored = c.execute(
            text(
                "SELECT manifest_canonical, manifest_sha256 FROM "
                "knowledge.intelligence_artifact_manifests WHERE principal_id = :p "
                "AND artifact_id = :a"
            ),
            {"p": principal, "a": copy},
        ).one()
    assert stored.manifest_sha256 == _digest(stored.manifest_canonical)


#: Each case breaks exactly one field the trigger binds to the row or artifact.
_MISNAMED: Final[dict[str, Callable[[str, str], dict[str, object]]]] = {
    "another_report_id": lambda copy, content: {
        "canonical": _manifest("rpt_s4guardnotthisone", content)
    },
    "another_markdown_digest": lambda copy, content: {"canonical": _manifest(copy, "e" * 64)},
    "structured_digest_not_projected": lambda copy, content: {
        "canonical": _manifest(copy, content, structured="a" * 64)
    },
    "program_claim_not_projected": lambda copy, content: {
        "canonical": _manifest(
            copy,
            content,
            program={"claimed_overview_sha256": "b" * 64, "verification_state": "not_attempted"},
        ),
        "claimed": "c" * 64,
        "state": "not_attempted",
    },
    "program_state_not_projected": lambda copy, content: {
        "canonical": _manifest(
            copy,
            content,
            program={"claimed_overview_sha256": "b" * 64, "verification_state": "not_attempted"},
        ),
        "claimed": "b" * 64,
        "state": "recompute_failed",
    },
}


@pytest.mark.parametrize("case", sorted(_MISNAMED))
def test_a_manifest_names_its_own_artifact(db_engine: Engine, case: str) -> None:
    principal, source, content = _committed(db_engine)

    def misnamed(c: Connection) -> None:
        copy = _copy_artifact(c, principal, source)
        values = _MISNAMED[case](copy, content)
        canonical = str(values.pop("canonical"))
        _insert_manifest(c, principal, copy, canonical, **values)  # type: ignore[arg-type]

    _refused(db_engine, misnamed, CHECK, "a report manifest names its own artifact")


def test_every_artifact_committed_after_s4_has_a_manifest(db_engine: Engine) -> None:
    principal, source, content = _committed(db_engine)
    # Committed through the store: exactly one manifest, naming it, whose digest
    # recomputes from its stored text.
    with db_engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT manifest_canonical, manifest_sha256, structured_content_sha256 "
                "FROM knowledge.intelligence_artifact_manifests WHERE principal_id = :p"
            ),
            {"p": principal},
        ).all()
    assert len(rows) == 1
    (row,) = rows
    assert row.manifest_sha256 == _digest(row.manifest_canonical)
    manifest = json.loads(row.manifest_canonical)
    assert manifest["report"]["report_id"] == source
    assert manifest["report"]["content_sha256"] == content
    assert manifest["structured_content"]["sha256"] == row.structured_content_sha256
    assert manifest["program"] is None

    # An artifact inserted by direct SQL with no manifest: refused at commit.
    _refused(
        db_engine,
        lambda c: _copy_artifact(c, principal, source),
        CHECK,
        "an intelligence artifact committed after S4 has its manifest",
    )


def test_manifests_refuse_update_and_delete(db_engine: Engine) -> None:
    principal, _source, _content = _committed(db_engine)
    _refused(
        db_engine,
        lambda c: c.execute(
            text(
                "UPDATE knowledge.intelligence_artifact_manifests SET recorded_at = now() "
                "WHERE principal_id = :p"
            ),
            {"p": principal},
        ),
        RAISE_EXCEPTION,
        "intelligence lineage rows are append-only",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            text("DELETE FROM knowledge.intelligence_artifact_manifests WHERE principal_id = :p"),
            {"p": principal},
        ),
        RAISE_EXCEPTION,
        "intelligence lineage rows are append-only",
    )


def test_manifests_refuse_truncate(db_engine: Engine) -> None:
    _committed(db_engine)
    _refused(
        db_engine,
        lambda c: c.execute(text("TRUNCATE knowledge.intelligence_artifact_manifests")),
        RESTRICT,
        "intelligence_artifact_manifests refuses TRUNCATE",
    )
