"""AT-004 / AT-012 (SQL parity): the S1 identity functions equal the Python encoding.

`knowledge.lineage_record_link_identity` and `knowledge.lineage_anchor_identity`
(the S1 revision, S1 contract section 5.5) are held to the same golden
vectors as `domain/lineage/canonical.py` (`tests/fixtures/lineage_canonical_vectors.json`,
also read by `tests/unit/test_lineage_canonical.py`), and the two `BEFORE INSERT`
triggers that compare a stored identity with them refuse a row whose identity
is not the canonical one -- so a writer that serializes differently cannot store
a second spelling of one meaning.

`database` tier on a disposable head-migrated clone; rows are written with
direct SQL inserts, as the Meeting and Knowledge precedents do. Every value is
synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    captures,
    lineage_evidence_anchors,
    record_links,
)

pytestmark = pytest.mark.database

VECTORS: Final = Path(__file__).resolve().parents[1] / "fixtures" / "lineage_canonical_vectors.json"
PRINCIPAL: Final = "prn_lineageparity0001"
WHEN: Final = datetime(2026, 10, 17, 12, tzinfo=UTC)
#: PostgreSQL's `check_violation`, which both identity triggers raise.
CHECK_VIOLATION: Final = "23514"


def _vectors(section: str) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads(VECTORS.read_text(encoding="utf-8"))[section]
    return loaded


def _refused(engine: Engine, statement: Callable[[Connection], object], sqlstate: str) -> str:
    with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
        statement(connection)
    assert getattr(refused.value.orig, "sqlstate", None) == sqlstate, refused.value
    return str(refused.value)


def test_sql_link_identity_matches_the_golden_vectors(db_engine: Engine) -> None:
    vectors = _vectors("record_link_identities")
    assert len(vectors) >= 3
    with db_engine.connect() as connection:
        for vector in vectors:
            built = connection.execute(
                text(
                    "SELECT knowledge.lineage_record_link_identity(:kind, :relation_type, "
                    ":from_family, :from_id, :to_family, :to_id, :member_role, "
                    ":context_issue_id)"
                ),
                vector["input"],
            ).scalar_one()
            assert built == vector["expected"], vector["name"]


def test_sql_anchor_identity_matches_the_golden_vectors(db_engine: Engine) -> None:
    vectors = _vectors("anchor_identities")
    assert len(vectors) >= 3
    with db_engine.connect() as connection:
        for vector in vectors:
            built = connection.execute(
                text(
                    "SELECT knowledge.lineage_anchor_identity(:source_family, :source_root_id, "
                    ":source_version_kind, :source_version_id, CAST(:source_version_no AS "
                    "integer), :source_sha256, CAST(:passage_start_cp AS integer), "
                    "CAST(:passage_end_cp AS integer), :passage_sha256)"
                ),
                vector["input"],
            ).scalar_one()
            assert built == vector["expected"], vector["name"]


def _reordered(canonical: str) -> str:
    """The same object with its top-level keys reversed, compactly separated."""
    return json.dumps(dict(reversed(list(json.loads(canonical).items()))), separators=(",", ":"))


def _discusses_link(identity: str) -> dict[str, object]:
    """A semantic `discusses` link with no Issue context: no foreign key applies."""
    vector = next(
        v for v in _vectors("record_link_identities") if v["name"] == "discusses_without_a_context"
    )
    values = vector["input"]
    return {
        "principal_id": PRINCIPAL,
        "link_id": issue_identifier(IdKind.RECORD_LINK),
        "kind": values["kind"],
        "from_family": values["from_family"],
        "from_id": values["from_id"],
        "to_family": values["to_family"],
        "to_id": values["to_id"],
        "relation_type": values["relation_type"],
        "member_role": None,
        "context_issue_id": None,
        "context_issue_kind": None,
        "normalized_identity": identity,
        "authority_class": "local_operator",
        "decision_channel": "local_cli",
        "source_capability": "records.associations.assert",
        "created_at": WHEN,
    }


def test_a_non_canonical_link_identity_is_refused(db_engine: Engine) -> None:
    canonical = next(
        v["expected"]
        for v in _vectors("record_link_identities")
        if v["name"] == "discusses_without_a_context"
    )
    # The canonical spelling is admitted: the refusal below is about spelling.
    with db_engine.begin() as connection:
        connection.execute(insert(record_links).values(**_discusses_link(canonical)))
    for spelling in (
        json.dumps(json.loads(canonical), sort_keys=True),  # spaces after separators
        _reordered(canonical),  # keys out of order
        canonical.replace('"selector":"root"', '"selector":"ROOT"'),
    ):
        assert spelling != canonical
        message = _refused(
            db_engine,
            lambda c, s=spelling: c.execute(insert(record_links).values(**_discusses_link(s))),
            CHECK_VIOLATION,
        )
        assert "a record link identity is the canonical one" in message


def _legacy_anchor(capture_id: str, identity: str) -> dict[str, object]:
    return {
        "principal_id": PRINCIPAL,
        "anchor_id": issue_identifier(IdKind.LINEAGE_EVIDENCE_ANCHOR),
        "source_family": "capture",
        "source_root_id": capture_id,
        "source_version_kind": "legacy_unversioned",
        "source_version_id": None,
        "source_version_no": None,
        "source_sha256": None,
        "passage_start_cp": None,
        "passage_end_cp": None,
        "passage_sha256": None,
        "meeting_id": None,
        "note_version_id": None,
        "capture_id": capture_id,
        "capture_version_id": None,
        "anchor_identity": identity,
        "recorded_at": WHEN,
    }


def test_a_non_canonical_anchor_identity_is_refused(db_engine: Engine) -> None:
    vector = next(v for v in _vectors("anchor_identities") if v["name"] == "legacy_capture_root")
    capture_id = vector["input"]["source_root_id"]
    canonical = vector["expected"]
    with db_engine.begin() as connection:
        connection.execute(
            insert(captures).values(capture_id=capture_id, owner_principal_id=PRINCIPAL)
        )
        connection.execute(
            insert(lineage_evidence_anchors).values(**_legacy_anchor(capture_id, canonical))
        )
    for spelling in (
        json.dumps(json.loads(canonical), sort_keys=True),
        _reordered(canonical),
        canonical.replace('"source_version_no":null', '"source_version_no":0'),
    ):
        assert spelling != canonical
        message = _refused(
            db_engine,
            lambda c, s=spelling: c.execute(
                insert(lineage_evidence_anchors).values(**_legacy_anchor(capture_id, s))
            ),
            CHECK_VIOLATION,
        )
        assert "an anchor identity is the canonical one" in message
