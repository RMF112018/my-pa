"""Reports Modernization WP02, contract C: the general report repository on PostgreSQL.

The `database` tier. Every test runs on its own disposable clone of the current
head (`migrated_engine`), never the configured database. What it proves:

* publish then `read_version` round-trips exact content bytes and digests for
  all four formats, through jsonb, and the manifest digest is recomputed;
* a replay of one key and intent returns the original receipt and writes no
  row; the same key with another intent is a conflict and writes no row;
  distinct keys are distinct reports; a concurrent same-key race on two
  connections ends with one report and one receipt;
* a foreign Principal's report reads exactly as a nonexistent one; association
  targets resolve only in the owner's scope;
* a publish writes no `knowledge.intelligence_*` row;
* a version ref is verified against the caller's own versions of the named
  report, never stored `verified` on trust;
* a tampered stored row makes the read refuse, including a manifest rewritten
  with both digests recomputed to name another title, version or byte count.
  Every plane row is append-only by trigger, so the tamper is done honestly:
  in this test's disposable clone, `ALTER TABLE ... DISABLE TRIGGER` on the
  append-only trigger of each table tampered, then a plain `UPDATE`.

Every identifier, title and byte is synthetic.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, text

from my_pa.contracts.ports import (
    ReportAssociationTargetNotFoundError,
    ReportIdempotencyConflictError,
    ReportIntegrityError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.creator import CreatorKind, ReportCreator, derive_creator
from my_pa.domain.reports.manifest import manifest_digest
from my_pa.domain.reports.publication import (
    PublicationRequest,
    PublicationResult,
    RequestedAssociation,
)
from my_pa.domain.reports.vocabulary import (
    AssociationTargetKind,
    AssociationVerification,
    LifecycleState,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
T0: Final = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)

PLANE_TABLES: Final = (
    "report_content_objects",
    "report_roots",
    "report_versions",
    "report_version_manifests",
    "report_associations",
    "report_lifecycle_events",
    "report_receipts",
    "report_transfer_sessions",
)

#: Numbers chosen to catch a jsonb round trip that rewrote digits.
NUMBERS: Final[dict[str, object]] = {
    "int": 12345678901234567890,
    "neg_int": -7,
    "one": 1.0,
    "small": 0.0001,
    "inexact": 0.30000000000000004,
    "large": 1e15,
    "zero": 0.0,
    "neg_zero": -0.0,
    "text": 'é \u2713 \u2028 "q" \\ \t',
    "nested": {"b": [1, 2.5, None, True, False], "a": {}},
}

CONTENTS: Final[dict[str, dict[str, object]]] = {
    "markdown": {"format": "markdown", "body": "# Synthetic\n\nBody é ✓\n"},
    "text": {"format": "text", "body": "plain synthetic text\n"},
    "json": {"format": "json", "data": NUMBERS},
    "mixed": {"format": "mixed", "body": "see data", "data": [NUMBERS, "x"]},
}


def _request(content: dict[str, object] | None = None, **overrides: object) -> PublicationRequest:
    fields: dict[str, object] = {
        "title": "Synthetic report",
        "content": validate_content(content or CONTENTS["markdown"]),
        "report_type": "synthetic_note",
        "topics": ("alpha",),
        "tags": ("t1",),
        "summary": "Synthetic summary.",
        "report_date": date(2026, 11, 4),
        "metadata": {"k": 1.0, "n": 3, "z": -0.0, "s": 0.0001},
    }
    fields.update(overrides)
    return PublicationRequest(**fields)  # type: ignore[arg-type]


def _publish(
    connection: Connection,
    request: PublicationRequest,
    key: str,
    *,
    principal_id: str = PRINCIPAL_A,
    creator: ReportCreator | None = None,
) -> PublicationResult:
    return SqlGeneralReportRepository(connection).publish(
        request,
        principal_id=principal_id,
        creator=creator or derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal_id),
        idempotency_key=key,
        recorded_at=datetime.now(UTC),
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
    )


def _publish_committed(
    engine: Engine, request: PublicationRequest, key: str, *, principal_id: str = PRINCIPAL_A
) -> PublicationResult:
    with engine.begin() as connection:
        return _publish(connection, request, key, principal_id=principal_id)


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
            )
            for table in PLANE_TABLES
        }


def _intelligence_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = "
                "'knowledge' AND table_name LIKE 'intelligence\\_%' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
        ).scalars()
        names = list(tables)
        return {
            name: int(
                connection.execute(text(f"SELECT count(*) FROM knowledge.{name}")).scalar_one()  # noqa: S608
            )
            for name in names
        }


def _read(
    engine: Engine, report_id: str, *, principal_id: str = PRINCIPAL_A, **kwargs: object
) -> object:
    with engine.connect() as connection:
        return SqlGeneralReportRepository(connection).read_version(
            report_id,
            principal_id=principal_id,
            **kwargs,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("fmt", ["markdown", "text", "json", "mixed"])
def test_publish_then_read_round_trips_exact_bytes_and_digests(
    migrated_engine: Engine, fmt: str
) -> None:
    request = _request(CONTENTS[fmt])
    result = _publish_committed(migrated_engine, request, f"key-{fmt}")
    assert result.replayed is False
    assert result.decoded_sha256 == request.content.decoded_sha256

    with migrated_engine.connect() as connection:
        stored = SqlGeneralReportRepository(connection).read_version(
            result.receipt.report_id, principal_id=PRINCIPAL_A
        )
    assert stored is not None
    assert stored.content.decoded == request.content.decoded
    assert stored.content.decoded_sha256 == request.content.decoded_sha256
    assert stored.content.canonical_sha256 == request.content.canonical_sha256
    assert stored.content.format.value == fmt
    assert stored.version.manifest_sha256 == result.manifest_sha256
    assert manifest_digest(stored.manifest) == result.manifest_sha256
    assert stored.root.head_version_number == 1
    assert stored.root.lifecycle_state is LifecycleState.ACTIVE
    assert stored.root.lifecycle_revision == 0
    assert stored.version.title == "Synthetic report"
    assert stored.version.metadata == {"k": 1.0, "n": 3, "z": 0.0, "s": 0.0001}
    assert stored.version.topics == ("alpha",)
    # By number and by id answer the same version.
    by_number = _read(migrated_engine, result.receipt.report_id, version_number=1)
    by_id = _read(migrated_engine, result.receipt.report_id, version_id=result.receipt.version_id)
    assert by_number == by_id == stored
    assert _read(migrated_engine, result.receipt.report_id, version_number=2) is None


def test_jsonb_reproduces_the_canonical_number_digits(migrated_engine: Engine) -> None:
    result = _publish_committed(migrated_engine, _request(CONTENTS["json"]), "numbers")
    with migrated_engine.connect() as connection:
        raw = connection.execute(
            text("SELECT inline_data FROM knowledge.report_content_objects WHERE content_id = :c"),
            {"c": result.content_id},
        ).scalar_one()
    assert raw["one"] == 1.0
    assert isinstance(raw["one"], float)
    assert raw["small"] == 0.0001
    assert raw["inexact"] == 0.30000000000000004
    assert raw["int"] == 12345678901234567890
    assert isinstance(raw["int"], int)
    assert (
        _request(CONTENTS["json"]).content.decoded
        == validate_content({"format": "json", "data": raw}).decoded
    )


def test_replay_returns_the_original_receipt_and_writes_nothing(migrated_engine: Engine) -> None:
    request = _request()
    first = _publish_committed(migrated_engine, request, "replay-key")
    before = _counts(migrated_engine)
    again = _publish_committed(migrated_engine, _request(), "replay-key")
    assert _counts(migrated_engine) == before
    assert again.replayed is True
    assert again.receipt == first.receipt
    assert dataclass_without_replayed(again) == dataclass_without_replayed(first)
    with migrated_engine.connect() as connection:
        found = SqlGeneralReportRepository(connection).find_publish_receipt(
            "replay-key", principal_id=PRINCIPAL_A
        )
    assert found is not None
    assert found.receipt == first.receipt


def dataclass_without_replayed(result: PublicationResult) -> tuple[object, ...]:
    return (
        result.receipt,
        result.content_id,
        result.format,
        result.decoded_sha256,
        result.decoded_byte_count,
        result.canonical_sha256,
        result.manifest_sha256,
        result.recorded_at,
    )


def test_same_key_with_another_intent_is_a_conflict_with_zero_writes(
    migrated_engine: Engine,
) -> None:
    _publish_committed(migrated_engine, _request(), "conflict-key")
    before = _counts(migrated_engine)
    with pytest.raises(ReportIdempotencyConflictError):
        _publish_committed(migrated_engine, _request(client_intent_id="other"), "conflict-key")
    assert _counts(migrated_engine) == before


def test_distinct_keys_are_two_reports(migrated_engine: Engine) -> None:
    first = _publish_committed(migrated_engine, _request(), "key-one")
    second = _publish_committed(migrated_engine, _request(), "key-two")
    assert first.receipt.report_id != second.receipt.report_id
    counts = _counts(migrated_engine)
    assert counts["report_roots"] == counts["report_receipts"] == 2


def test_a_foreign_report_reads_as_a_nonexistent_one(migrated_engine: Engine) -> None:
    result = _publish_committed(migrated_engine, _request(), "mine")
    report_id = result.receipt.report_id
    assert _read(migrated_engine, report_id) is not None  # the non-zero control
    foreign = _read(migrated_engine, report_id, principal_id=PRINCIPAL_B)
    missing = _read(migrated_engine, issue_identifier(IdKind.REPORT))
    malformed = _read(migrated_engine, "rpt_aaaaaaaa")
    assert foreign is missing is malformed is None
    foreign_version = _read(
        migrated_engine,
        report_id,
        principal_id=PRINCIPAL_B,
        version_id=result.receipt.version_id,
    )
    assert foreign_version is None
    with migrated_engine.connect() as connection:
        repository = SqlGeneralReportRepository(connection)
        assert repository.find_publish_receipt("mine", principal_id=PRINCIPAL_B) is None
    # The key's collision domain is the Principal's own: B's same key is B's report.
    other = _publish_committed(migrated_engine, _request(), "mine", principal_id=PRINCIPAL_B)
    assert other.replayed is False
    assert other.receipt.report_id != report_id


def _project(engine: Engine, principal_id: str) -> str:
    project_id = issue_identifier(IdKind.PROJECT)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.projects (project_id, principal_id, name, state, "
                "participants, opened_at, created_at, updated_at) VALUES (:p, :o, "
                "'Synthetic project', 'active', '[]'::jsonb, :t, :t, :t)"
            ),
            {"p": project_id, "o": principal_id, "t": T0},
        )
    return project_id


def _entity(engine: Engine, principal_id: str) -> str:
    entity_id = issue_identifier(IdKind.ENTITY)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.entities (entity_id, principal_id, entity_type, "
                "canonical_name, display_name, status) VALUES (:e, :o, 'person', "
                "'synthetic person', 'Synthetic Person', 'active')"
            ),
            {"e": entity_id, "o": principal_id},
        )
    return entity_id


def test_association_targets_resolve_only_in_the_owners_scope(migrated_engine: Engine) -> None:
    project_a, entity_a = (
        _project(migrated_engine, PRINCIPAL_A),
        _entity(migrated_engine, PRINCIPAL_A),
    )
    project_b, entity_b = (
        _project(migrated_engine, PRINCIPAL_B),
        _entity(migrated_engine, PRINCIPAL_B),
    )
    receipt_a = _publish_committed(migrated_engine, _request(), "target-a").receipt
    receipt_b = _publish_committed(
        migrated_engine, _request(), "target-b", principal_id=PRINCIPAL_B
    ).receipt
    report_a, version_a = receipt_a.report_id, receipt_a.version_id
    report_b, version_b = receipt_b.report_id, receipt_b.version_id
    other_a = _publish_committed(migrated_engine, _request(), "target-a2").receipt
    p, e, s, i = (
        AssociationTargetKind.PROJECT,
        AssociationTargetKind.ENTITY,
        AssociationTargetKind.STANDALONE_REPORT,
        AssociationTargetKind.INTELLIGENCE_REPORT,
    )
    targets = [
        (p, project_a),
        (p, project_b),
        (e, entity_a),
        (e, entity_b),
        (s, report_a),
        (s, report_b),
        (i, "rpt_aaaaaaaa0000"),
        (AssociationTargetKind.EXTERNAL_SOURCE, "https://x.test/a"),
        (p, entity_a),  # right id, wrong kind
    ]
    with migrated_engine.connect() as connection:
        repository = SqlGeneralReportRepository(connection)
        assert repository.resolve_association_targets(targets, principal_id=PRINCIPAL_A) == {
            (p, project_a),
            (e, entity_a),
            (s, report_a),
        }
        assert repository.resolve_association_targets(targets, principal_id=PRINCIPAL_B) == {
            (p, project_b),
            (e, entity_b),
            (s, report_b),
        }

    associated = _request(
        associations=(
            RequestedAssociation(p, project_a, "about"),
            RequestedAssociation(e, entity_a, "mentions"),
            RequestedAssociation(s, report_a, "follows", version_a),
            RequestedAssociation(
                AssociationTargetKind.EXTERNAL_SOURCE, "https://x.test/a", "cites", "v9"
            ),
        )
    )
    result = _publish_committed(migrated_engine, associated, "associated")
    with migrated_engine.connect() as connection:
        stored = SqlGeneralReportRepository(connection).read_version(
            result.receipt.report_id, principal_id=PRINCIPAL_A
        )
    assert stored is not None
    assert [(a.target_kind, a.verification) for a in stored.associations] == [
        (p, AssociationVerification.VERIFIED),
        (e, AssociationVerification.VERIFIED),
        (s, AssociationVerification.VERIFIED),
        (AssociationTargetKind.EXTERNAL_SOURCE, AssociationVerification.ASSERTED),
    ]
    assert stored.associations[2].target_version_ref == version_a
    # An external version is not checkable: it is kept as asserted text.
    assert stored.associations[3].target_version_ref == "v9"
    assert [a["verification"] for a in stored.manifest["associations"]] == [
        "verified",
        "verified",
        "verified",
        "asserted",
    ]

    before = _counts(migrated_engine)
    for foreign in (
        RequestedAssociation(p, project_b, "about"),
        RequestedAssociation(e, entity_b, "about"),
        RequestedAssociation(s, report_b, "about"),
        RequestedAssociation(i, "rpt_aaaaaaaa0000", "about"),
        # A version ref is verified, never trusted: a foreign Principal's
        # version, a nonexistent one, the caller's own version of ANOTHER
        # report, a non-`grver_` ref, and any version ref on a kind with no
        # verifiable version all refuse as the target's own not-found.
        RequestedAssociation(s, report_a, "follows", version_b),
        RequestedAssociation(s, report_a, "follows", "grver_aaaaaaaa"),
        RequestedAssociation(s, report_a, "follows", other_a.version_id),
        RequestedAssociation(s, report_a, "follows", "v1"),
        RequestedAssociation(p, project_a, "about", version_a),
        RequestedAssociation(e, entity_a, "about", "v1"),
    ):
        with pytest.raises(ReportAssociationTargetNotFoundError):
            _publish_committed(
                migrated_engine,
                _request(associations=(foreign,)),
                f"foreign-{foreign.target_ref}-{foreign.target_version_ref}",
            )
    assert _counts(migrated_engine) == before


def test_a_publish_writes_no_intelligence_row(migrated_engine: Engine) -> None:
    before = _intelligence_counts(migrated_engine)
    assert "intelligence_artifacts" in before
    assert "intelligence_cycle_runs" in before
    for fmt, content in CONTENTS.items():
        _publish_committed(migrated_engine, _request(content), f"intel-{fmt}")
    after = _intelligence_counts(migrated_engine)
    assert after == before
    assert set(after.values()) == {0}


def _tamper(engine: Engine, table: str, statement: str, parameters: dict[str, str]) -> None:
    """Disable one append-only trigger in this disposable clone and rewrite a row."""
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE knowledge.{table} DISABLE TRIGGER {table}_are_append_only")
        )
        assert connection.execute(text(statement), parameters).rowcount == 1
        connection.execute(
            text(f"ALTER TABLE knowledge.{table} ENABLE TRIGGER {table}_are_append_only")
        )


def _tamper_manifest_and_digest(
    engine: Engine, version_id: str, manifest: dict[str, object], digest: str
) -> None:
    """Rewrite a manifest and BOTH digests that name it, in one statement.

    The manifest's `(version_id, manifest_sha256)` foreign key to its version is
    not deferrable, so the two rows change in one writable-CTE statement, with
    the two append-only triggers disabled in this disposable clone.
    """
    tables = ("report_version_manifests", "report_versions")
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(f"ALTER TABLE knowledge.{table} DISABLE TRIGGER {table}_are_append_only")
            )
        changed = connection.execute(
            text(
                "WITH m AS (UPDATE knowledge.report_version_manifests SET manifest = "
                "CAST(:m AS jsonb), manifest_sha256 = :d WHERE version_id = :v RETURNING 1) "
                "UPDATE knowledge.report_versions SET manifest_sha256 = :d "
                "WHERE version_id = :v AND (SELECT count(*) FROM m) = 1"
            ),
            {"m": json.dumps(manifest), "d": digest, "v": version_id},
        ).rowcount
        assert changed == 1
        for table in tables:
            connection.execute(
                text(f"ALTER TABLE knowledge.{table} ENABLE TRIGGER {table}_are_append_only")
            )


def test_a_tampered_content_digest_makes_the_read_refuse(migrated_engine: Engine) -> None:
    result = _publish_committed(migrated_engine, _request(CONTENTS["json"]), "tamper-content")
    assert _read(migrated_engine, result.receipt.report_id) is not None
    forged = "0" * 64
    _tamper(
        migrated_engine,
        "report_content_objects",
        "UPDATE knowledge.report_content_objects SET decoded_sha256 = :d, original_sha256 = :d, "
        "canonical_sha256 = :d WHERE content_id = :c",
        {"d": forged, "c": result.content_id},
    )
    with pytest.raises(ReportIntegrityError):
        _read(migrated_engine, result.receipt.report_id)


def test_tampered_content_data_makes_the_read_refuse(migrated_engine: Engine) -> None:
    result = _publish_committed(migrated_engine, _request(CONTENTS["mixed"]), "tamper-data")
    _tamper(
        migrated_engine,
        "report_content_objects",
        "UPDATE knowledge.report_content_objects SET inline_data = '[\"forged\"]'::jsonb "
        "WHERE content_id = :c",
        {"c": result.content_id},
    )
    with pytest.raises(ReportIntegrityError):
        _read(migrated_engine, result.receipt.report_id)


def test_a_tampered_manifest_makes_the_read_refuse(migrated_engine: Engine) -> None:
    result = _publish_committed(migrated_engine, _request(), "tamper-manifest")
    _tamper(
        migrated_engine,
        "report_version_manifests",
        "UPDATE knowledge.report_version_manifests SET manifest = manifest || "
        '\'{"title": "forged"}\'::jsonb WHERE version_id = :v',
        {"v": result.receipt.version_id},
    )
    with pytest.raises(ReportIntegrityError):
        _read(migrated_engine, result.receipt.report_id)

    # A manifest rewritten to name another title, version number, report or
    # version, or other byte counts, with BOTH stored digests recomputed to
    # match it, still refuses: the read compares it to the version row.
    for field, forged_value in (
        ("title", "forged"),
        ("version_number", 2),
        ("report_id", issue_identifier(IdKind.REPORT)),
        ("version_id", issue_identifier(IdKind.REPORT_VERSION)),
        ("content.original_byte_count", 999),
        ("content.decoded_byte_count", 999),
    ):
        published = _publish_committed(migrated_engine, _request(), f"tamper-identity-{field}")
        version_id = published.receipt.version_id
        stored = _read(migrated_engine, published.receipt.report_id)
        assert stored is not None
        manifest = dict(stored.manifest)  # type: ignore[attr-defined]
        if field.startswith("content."):
            manifest["content"] = {**manifest["content"], field.split(".", 1)[1]: forged_value}
        else:
            manifest[field] = forged_value
        digest = manifest_digest(manifest)
        _tamper_manifest_and_digest(migrated_engine, version_id, manifest, digest)
        with pytest.raises(ReportIntegrityError):
            _read(migrated_engine, published.receipt.report_id)


def _wait_until(condition: Callable[[], bool], *, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_a_concurrent_same_key_race_ends_with_one_report_and_one_receipt(
    migrated_engine: Engine,
) -> None:
    request = _request()
    outcome: dict[str, object] = {}

    first = migrated_engine.connect()
    transaction = first.begin()
    try:
        winner = _publish(first, request, "race-key")

        def second() -> None:
            try:
                outcome["result"] = _publish_committed(migrated_engine, _request(), "race-key")
            except Exception as error:
                outcome["error"] = error

        thread = threading.Thread(target=second)
        thread.start()

        def waiting_on_a_lock() -> bool:
            with migrated_engine.connect() as observer:
                return bool(
                    observer.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = "
                            "current_database() AND wait_event_type = 'Lock'"
                        )
                    ).scalar_one()
                )

        assert _wait_until(waiting_on_a_lock), "the second writer never blocked on the key"
        transaction.commit()
    finally:
        first.close()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert "error" not in outcome, outcome.get("error")
    loser = outcome["result"]
    assert isinstance(loser, PublicationResult)
    assert loser.replayed is True
    assert loser.receipt == winner.receipt
    counts = _counts(migrated_engine)
    assert counts["report_roots"] == counts["report_receipts"] == counts["report_versions"] == 1
    assert counts["report_content_objects"] == counts["report_version_manifests"] == 1
