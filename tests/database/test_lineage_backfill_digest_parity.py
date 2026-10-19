"""AT-025 (digest parity): the backfill source functions in SQL equal the Python mirror.

S3 contract sections 4.2 and 5 (R3-F09, R3-F22). The S3 revision freezes
`knowledge.lineage_backfill_source_document` and
`knowledge.lineage_backfill_source_digest`; `domain/lineage/backfill.py` mirrors
them. One golden-vector file (`tests/fixtures/lineage_backfill_source_vectors.json`)
drives both this test and the FAST unit test, so the two implementations are
held to the same bytes rather than to each other.

Each vector's native rows are seeded directly, foreign keys and deferred
checks silenced for the seeding transaction (`session_replication_role =
replica`; CHECKs still apply), because the functions read native rows and the
vectors name synthetic parents that need not exist. `database` tier on a
disposable head-migrated clone per test. Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Connection

from my_pa.domain.lineage.backfill import SOURCE_DOMAIN, source_digest
from my_pa.domain.lineage_backfill.vocabulary import BackfillSourceKind
from my_pa.infrastructure.persistence.tables import (
    capture_assertion_spans,
    capture_assertions,
    capture_spans,
    capture_versions,
    captures,
    meetings,
    project_situations,
    projects,
    situations,
    tasks,
)

pytestmark = pytest.mark.database

VECTORS: Final = (
    Path(__file__).resolve().parents[1] / "fixtures" / ("lineage_backfill_source_vectors.json")
)
WHEN: Final = datetime(2026, 10, 19, 12, tzinfo=UTC)


def _loaded() -> dict[str, Any]:
    loaded = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _task(c: Connection, principal: str, task_id: str, **values: object) -> None:
    row: dict[str, object] = {
        "task_id": task_id,
        "principal_id": principal,
        "title": "Synthetic task",
        "origin_kind": "direct_principal",
        "opened_at": WHEN,
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    row.update(values)
    c.execute(insert(tasks).values(**row))


def _evidence_task(c: Connection, principal: str, task_id: str, reference: str) -> None:
    _task(c, principal, task_id, origin_kind="evidence", origin_evidence_ref=reference)


def _situation(c: Connection, principal: str, situation_id: str, **values: object) -> None:
    c.execute(
        insert(situations).values(
            situation_id=situation_id,
            principal_id=principal,
            title="Synthetic context",
            state="open",
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
            **values,
        )
    )


def _seed(engine: Engine) -> dict[str, Any]:
    """Every vector's native rows, in one transaction with its triggers silenced."""
    loaded = _loaded()
    principal = loaded["principal_id"]
    references = {
        vector["input"]["source_id"]: vector["reference"]
        for vector in loaded["vectors"]
        if "reference" in vector
    }
    content = loaded["capture_content"]
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        _task(c, principal, "tsk_lineages3vec0001", commitment_id="cmt_lineages3vec0001")
        c.execute(
            insert(meetings).values(
                meeting_id="mtg_lineages3vec0001",
                principal_id=principal,
                meeting_series_id="mser_lineages3vec0001",
                title="Synthetic meeting",
                start_at=WHEN,
                timezone_name="UTC",
                status="scheduled",
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
        _situation(c, principal, "sit_lineages3vec0001")
        c.execute(
            insert(projects).values(
                project_id="prj_lineages3vec0001",
                principal_id=principal,
                name="Synthetic project",
                state="active",
                participants=[],
                opened_at=WHEN,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
        c.execute(
            insert(project_situations).values(
                project_situation_id="psit_lineages3vec0001",
                project_id="prj_lineages3vec0001",
                situation_id="sit_lineages3vec0001",
                principal_id=principal,
                linked_at=WHEN,
            )
        )
        for task_id in (
            "tsk_lineages3vec0002",
            "tsk_lineages3vec0003",
            "tsk_lineages3vec0004",
            "tsk_lineages3vec0005",
            "tsk_lineages3vec0006",
        ):
            _evidence_task(c, principal, task_id, references[task_id])
        _situation(c, principal, "sit_lineages3vec0002", object_refs=loaded["object_refs"])
        c.execute(
            insert(captures).values(capture_id="cap_lineages3vec0002", owner_principal_id=principal)
        )
        c.execute(
            insert(capture_versions).values(
                version_id="capver_lineages3vec0001",
                capture_id="cap_lineages3vec0002",
                version_number=1,
                supersedes_version_id=None,
                content=content,
                content_sha256=_sha(content),
                owner_principal_id=principal,
                classification="synthetic_test",
                processing_policy="local_only",
                idempotency_key="seed-capver-lineages3vec0001",
                correlation_id="corr_lineages3vec0001",
                audit_id="audit_lineages3vec0001",
                server_received_at=WHEN,
                accepted_at=WHEN,
                recorded_at=WHEN,
            )
        )
        c.execute(
            insert(capture_assertions).values(
                assertion_id="asrt_lineages3vec0001",
                version_id="capver_lineages3vec0001",
                proposal_id="prop_lineages3vec0001",
                decision_id="rdec_lineages3vec0001",
                principal_id=principal,
                assertion_type="task",
                state="accepted",
                accepted_at=WHEN,
            )
        )
        for span_id, start, end, quoted in (
            ("span_lineages3vec0001", 0, 4, "Pour"),
            ("span_lineages3vec0002", 5, 99, "the north slab"),
        ):
            c.execute(
                insert(capture_spans).values(
                    span_id=span_id,
                    version_id="capver_lineages3vec0001",
                    processing_text_id=None,
                    start_offset=start,
                    end_offset=end,
                    offset_basis="unicode_code_point_v1",
                    line_start=1,
                    column_start=start + 1,
                    line_end=1,
                    column_end=end + 1,
                    quoted_text_sha256=_sha(quoted),
                    span_role="direct",
                )
            )
            c.execute(
                insert(capture_assertion_spans).values(
                    assertion_id="asrt_lineages3vec0001", span_id=span_id, principal_id=principal
                )
            )
    return loaded


def _sql(engine: Engine, function: str, principal: str, stated: dict[str, Any]) -> str:
    with engine.connect() as c:
        value = c.execute(
            text(f"SELECT knowledge.{function}(:principal, :kind, :family, :source_id, :ref)"),
            {
                "principal": principal,
                "kind": stated["source_kind"],
                "family": stated["source_family"],
                "source_id": stated["source_id"],
                "ref": stated["source_ref"],
            },
        ).scalar_one()
    assert isinstance(value, str)
    return value


def test_sql_source_document_matches_the_golden_vectors(db_engine: Engine) -> None:
    loaded = _seed(db_engine)
    principal = loaded["principal_id"]
    assert {vector["input"]["source_kind"] for vector in loaded["vectors"]} == {
        kind.value for kind in BackfillSourceKind
    }
    for vector in loaded["vectors"]:
        document = _sql(db_engine, "lineage_backfill_source_document", principal, vector["input"])
        assert document == vector["document"], vector["name"]
    # Another Principal reads none of these rows: every fact answers as absent.
    stranger = _sql(
        db_engine,
        "lineage_backfill_source_document",
        "prn_lineages3vec0002",
        loaded["vectors"][0]["input"],
    )
    assert '"facts":{"commitment_id":null}' in stranger
    assert stranger.endswith('"source_version":null}')


def test_sql_source_digest_matches_python(db_engine: Engine) -> None:
    loaded = _seed(db_engine)
    principal = loaded["principal_id"]
    for vector in loaded["vectors"]:
        stated = vector["input"]
        digest = _sql(db_engine, "lineage_backfill_source_digest", principal, stated)
        document = _sql(db_engine, "lineage_backfill_source_document", principal, stated)
        python = source_digest(
            **{**stated, "source_kind": BackfillSourceKind(stated["source_kind"])}
        )
        assert digest == python == vector["digest"], vector["name"]
        assert digest == hashlib.sha256(SOURCE_DOMAIN + document.encode("utf-8")).hexdigest()
    # A changed native fact changes the digest (the source-changed quarantine's
    # premise): re-pointing the Task's follow-up.
    first = loaded["vectors"][0]
    before = _sql(db_engine, "lineage_backfill_source_digest", principal, first["input"])
    with db_engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(
            text(
                "UPDATE knowledge.tasks SET commitment_id = 'cmt_lineages3vec0009', "
                "version = 2 WHERE task_id = 'tsk_lineages3vec0001'"
            )
        )
    assert _sql(db_engine, "lineage_backfill_source_digest", principal, first["input"]) != before


def test_a_non_ascii_non_nfc_free_text_ref_digests_alike_in_sql_and_python(
    db_engine: Engine,
) -> None:
    loaded = _seed(db_engine)
    principal = loaded["principal_id"]
    vector = next(
        vector
        for vector in loaded["vectors"]
        if vector["name"] == "work_origin_other_non_ascii_non_nfc"
    )
    reference = vector["reference"]
    assert not reference.isascii()
    assert unicodedata.normalize("NFC", reference) != reference
    with db_engine.connect() as c:
        stored, sql_digest = c.execute(
            text(
                "SELECT origin_evidence_ref, "
                "encode(sha256(convert_to(origin_evidence_ref, 'UTF8')), 'hex') "
                "FROM knowledge.tasks WHERE task_id = :task_id"
            ),
            {"task_id": vector["input"]["source_id"]},
        ).one()
    # Stored byte for byte (never normalized), and digested alike on both sides.
    assert stored == reference
    assert sql_digest == hashlib.sha256(reference.encode("utf-8")).hexdigest()
    assert (
        sql_digest
        != hashlib.sha256(unicodedata.normalize("NFC", reference).encode("utf-8")).hexdigest()
    )
    assert vector["input"]["source_ref"] == f"free_text:{sql_digest}"
    document = _sql(db_engine, "lineage_backfill_source_document", principal, vector["input"])
    assert document == vector["document"]
    assert document.isascii()
    assert reference not in document
    assert json.loads(document)["facts"] == {"origin_ref_sha256": sql_digest}
