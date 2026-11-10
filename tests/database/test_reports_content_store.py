"""Reports Modernization WP05 C4-C7: `managed_blob` report content on PostgreSQL.

The `database` tier, each test on its own disposable clone (`migrated_engine`)
with a real `FilesystemReportContentStore` on `tmp_path`. A low inline
threshold (1,024) exercises the body-returning blob read; the default
threshold exercises the above-the-response-bound marker. What it proves:

* a blob publish writes a `managed_blob` row (`blob_ref` = its content id,
  every inline column NULL, manifest `storage_kind` `managed_blob`) and the
  object; the read returns the exact body, data, `encoded` and digests;
* above 524,288 decoded bytes the read is `body_omitted` with every digest;
* the object is written before any row: a store whose `put` raises leaves zero
  rows (publish and update), and a database failure after the `put` leaves an
  orphan the scan reports;
* a missing or tampered object makes the read `internal_error`, no body;
* a content update writes a new blob, a metadata-only update reuses the blob
  row and copies its search text, and search finds a blob report's words;
* the scan reports missing, size- and digest-mismatched, orphan and
  unreadable objects; reads and the scan's row direction are Principal-scoped.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import report_content as report_content_cli
from sqlalchemy import Connection, Engine, text

from my_pa.adapters.normalization import normalize
from my_pa.application.report_content import (
    ReportContentMismatch,
    scan_report_content,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    ReportContentPart,
    ReportContentStore,
    ReportContentStoreError,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES, validate_content
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.publication import PublicationRequest
from my_pa.domain.reports.revision import ReportPatch, UpdateRequest
from my_pa.domain.reports.vocabulary import READ_INLINE_CONTENT_MAX_BYTES
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from tests.conftest import DEFAULT_LIMITS, operator

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 5, 12, tzinfo=UTC)
LOW: Final = 1024
PLANE_TABLES: Final = (
    "report_content_objects",
    "report_roots",
    "report_versions",
    "report_version_manifests",
    "report_associations",
    "report_receipts",
)


def _text(size: int, seed: int = 11) -> str:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    words = [f"q{rng.getrandbits(28):07x}" for _ in range(2048)]
    out = ["# Synthetic blob report"]
    length = len(out[0])
    while length < size:
        word = " " + rng.choice(words)
        out.append(word)
        length += len(word)
    return "".join(out)[:size]


def _gzip(raw: bytes, fmt: str = "text") -> dict[str, Any]:
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    return {"format": fmt, "encoding": "gzip+base64", "encoded": encoded}


def _store(tmp_path: Path, name: str = "report-content") -> FilesystemReportContentStore:
    root = tmp_path / name
    root.mkdir()
    return FilesystemReportContentStore(root)


def _service(
    engine: Engine, store: ReportContentStore | None, threshold: int = LOW
) -> ApplicationService:
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        report_content_store=store,
        report_content_inline_max_bytes=threshold,
    )


def _invoke(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: dict[str, Any],
) -> dict[str, Any]:
    (purpose,) = permitted_purposes(capability)
    metadata, command = normalize(
        capability.value,
        {
            "request_id": f"req-{capability.value}",
            "purpose": purpose.value,
            "principal_id": principal.principal_id,
            "requested_at": "2026-11-05T12:00:00Z",
            "payload": payload,
        },
    )
    return service.invoke(metadata, command, principal=principal).model_dump(mode="json")


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _publish(
    service: ApplicationService, principal: Principal, content: dict[str, Any], key: str
) -> dict[str, Any]:
    return _ok(
        _invoke(
            service,
            principal,
            Capability.REPORTS_PUBLISH,
            {"title": "Synthetic blob report", "content": content, "idempotency_key": key},
        )
    )


def _read(
    service: ApplicationService, principal: Principal, report_id: str, **extra: object
) -> dict[str, Any]:
    return _invoke(service, principal, Capability.REPORTS_READ, {"report_id": report_id, **extra})


def _update(
    service: ApplicationService,
    principal: Principal,
    report_id: str,
    expected: int,
    patch: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    return _invoke(
        service,
        principal,
        Capability.REPORTS_UPDATE,
        {
            "report_id": report_id,
            "expected_version": expected,
            "patch": patch,
            "change_reason": "Synthetic change.",
            "idempotency_key": key,
        },
    )


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
            )
            for table in PLANE_TABLES
        }


def _row(engine: Engine, table: str, column: str, value: str) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return (
            connection.execute(
                text(f"SELECT * FROM knowledge.{table} WHERE {column} = :v"),  # noqa: S608
                {"v": value},
            )
            .one()
            ._mapping
        )


def _object_dir(store: FilesystemReportContentStore, object_id: str) -> Path:
    return store.root / "content" / object_id.split("_", 1)[1][:2] / object_id


def _scan(engine: Engine, store: ReportContentStore, principal: Principal) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return scan_report_content(
            SqlGeneralReportRepository(connection), store, principal_id=principal.principal_id
        )


class _RefusingStore(FilesystemReportContentStore):
    """A real store whose `put` always fails, after counting the call."""

    calls = 0

    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        type(self).calls += 1
        raise ReportContentStoreError("synthetic put failure")


# ---- write and read -------------------------------------------------------------------


def test_a_blob_publish_writes_a_managed_blob_row_and_reads_back_exactly(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    principal = operator()
    body = _text(3000)
    identity = _publish(service, principal, {"format": "markdown", "body": body}, "id")
    raw_json = json.dumps({"alpha": [_text(1500, seed=2), 1.5, None], "k": "é"}).encode()
    gz = _gzip(raw_json, fmt="json")
    structured = _publish(service, principal, gz, "gz")

    for published in (identity, structured):
        content_id = published["content"]["content_id"]
        row = _row(migrated_engine, "report_content_objects", "content_id", content_id)
        assert row["storage_kind"] == "managed_blob"
        assert row["blob_ref"] == content_id
        assert row["inline_text"] is None
        assert row["inline_data"] is None
        assert row["inline_original"] is None
        manifest = _row(
            migrated_engine, "report_version_manifests", "version_id", published["version_id"]
        )["manifest"]
        assert manifest["content"]["storage_kind"] == "managed_blob"
        assert store.has(content_id)

    read = _ok(_read(service, principal, identity["report_id"], include_manifest=True))
    assert read["content"]["body"] == body
    assert read["content"]["storage_kind"] == "managed_blob"
    assert read["content"]["decoded_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert read["content"]["decoded_byte_count"] == len(body.encode())
    assert read["manifest"]["content"]["storage_kind"] == "managed_blob"
    parts = sorted(
        entry.name for entry in _object_dir(store, identity["content"]["content_id"]).iterdir()
    )
    assert parts == ["decoded"]

    gread = _ok(_read(service, principal, structured["report_id"]))["content"]
    assert gread["data"] == json.loads(raw_json)
    assert gread["encoded"] == gz["encoded"]
    original = gzip.compress(raw_json, compresslevel=9, mtime=0)
    assert gread["original_sha256"] == hashlib.sha256(original).hexdigest()
    assert gread["original_byte_count"] == len(original)
    assert sorted(
        entry.name for entry in _object_dir(store, structured["content"]["content_id"]).iterdir()
    ) == ["decoded", "original"]

    # The repository returns facts only; history lists the blob without the store.
    with migrated_engine.connect() as connection:
        stored = SqlGeneralReportRepository(connection).read_version(
            identity["report_id"], principal_id=principal.principal_id
        )
    assert stored is not None
    assert stored.content.materialized is False
    assert stored.content.body is None


def test_content_at_the_threshold_stays_inline(migrated_engine: Engine, tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    principal = operator()
    at = _publish(service, principal, {"format": "text", "body": _text(LOW)}, "at")
    row = _row(migrated_engine, "report_content_objects", "content_id", at["content"]["content_id"])
    assert row["storage_kind"] == "inline"
    assert store.stored_object_ids() == ()


def test_above_the_response_bound_the_read_is_body_omitted_with_every_digest(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    service = _service(migrated_engine, store, threshold=INLINE_CONTENT_MAX_BYTES)
    principal = operator()
    raw = _text(READ_INLINE_CONTENT_MAX_BYTES + 1).encode()
    content = _gzip(raw)
    published = _publish(service, principal, content, "big")
    row = _row(
        migrated_engine, "report_content_objects", "content_id", published["content"]["content_id"]
    )
    assert row["storage_kind"] == "managed_blob"
    read = _ok(_read(service, principal, published["report_id"]))["content"]
    assert read["body_omitted"] == "exceeds_response_bound"
    assert "body" not in read
    assert read["decoded_sha256"] == hashlib.sha256(raw).hexdigest() == row["decoded_sha256"]
    assert read["decoded_byte_count"] == len(raw)
    assert read["original_sha256"] == row["original_sha256"]
    assert read["encoded"] == content["encoded"]
    # Exactly the bound is inline at the default threshold, and returned whole.
    at = _publish(service, principal, _gzip(raw[:-1]), "at-bound")
    inline = _ok(_read(service, principal, at["report_id"]))["content"]
    assert inline["storage_kind"] == "inline"
    assert inline["body"] == raw[:-1].decode()


# ---- ordering -----------------------------------------------------------------------


def test_a_failing_put_writes_no_row_for_publish_or_update(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """The prove-red target for blob-before-commit: the `put` precedes every INSERT."""
    root = tmp_path / "refusing"
    root.mkdir()
    refusing = _RefusingStore(root)
    _RefusingStore.calls = 0
    principal = operator()
    service = _service(migrated_engine, refusing)
    before = _counts(migrated_engine)
    answer = _invoke(
        service,
        principal,
        Capability.REPORTS_PUBLISH,
        {
            "title": "Refused",
            "content": {"format": "text", "body": _text(2000)},
            "idempotency_key": "r",
        },
    )
    assert answer["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert _RefusingStore.calls == 1
    assert _counts(migrated_engine) == before

    inline = _publish(service, principal, {"format": "text", "body": "small synthetic"}, "s")
    after_publish = _counts(migrated_engine)
    answer = _update(
        service,
        principal,
        inline["report_id"],
        1,
        {"content": {"format": "text", "body": _text(2000)}},
        "u",
    )
    assert answer["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert _RefusingStore.calls == 2
    assert _counts(migrated_engine) == after_publish


class _ObservingStore(FilesystemReportContentStore):
    """A real store that, at each `put`, counts the plane's rows on the writer's connection.

    The connection is the repository's own, so its uncommitted INSERTs are
    visible: a count at `put` time equal to the count before the request
    proves the object was written before the request's first INSERT.
    """

    def __init__(self, root: Path, connection: Connection) -> None:
        super().__init__(root)
        self._connection = connection
        self.seen: list[dict[str, int]] = []

    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        self.seen.append(
            {
                table: int(
                    self._connection.execute(
                        text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608
                    ).scalar_one()
                )
                for table in PLANE_TABLES
            }
        )
        super().put(object_id, decoded=decoded, original=original)


def test_the_object_is_put_before_the_first_insert_of_its_request(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """The prove-red target for blob-before-commit ordering (C4)."""
    principal = operator()
    creator = derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal.principal_id)
    root = tmp_path / "observed"
    root.mkdir()

    def common(key: str) -> dict[str, Any]:
        return {
            "principal_id": principal.principal_id,
            "creator": creator,
            "idempotency_key": key,
            "recorded_at": WHEN,
            "correlation_id": issue_identifier(IdKind.CORRELATION),
            "audit_id": issue_identifier(IdKind.AUDIT),
            "inline_max_bytes": LOW,
        }

    with migrated_engine.begin() as connection:
        store = _ObservingStore(root, connection)
        repository = SqlGeneralReportRepository(connection)
        before = _counts(migrated_engine)
        published = repository.publish(
            PublicationRequest(
                title="Ordered", content=validate_content({"format": "text", "body": _text(2000)})
            ),
            content_store=store,
            **common("ordered-publish"),
        )
        assert store.seen == [before]
        rows_after_publish = {
            table: int(
                connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
            )
            for table in PLANE_TABLES
        }
        repository.update(
            UpdateRequest(
                report_id=published.receipt.report_id,
                expected_version=1,
                patch=ReportPatch(
                    content=validate_content({"format": "text", "body": _text(2200, seed=4)})
                ),
                change_reason="Synthetic change.",
            ),
            content_store=store,
            **common("ordered-update"),
        )
        assert store.seen == [before, rows_after_publish]


def test_a_database_failure_after_the_put_leaves_an_orphan_the_scan_reports(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    principal = operator()
    before = _counts(migrated_engine)
    request = PublicationRequest(
        title="Rolled back", content=validate_content({"format": "text", "body": _text(2000)})
    )

    class _AfterInsertsError(RuntimeError):
        pass

    with pytest.raises(_AfterInsertsError), migrated_engine.begin() as connection:
        result = SqlGeneralReportRepository(connection).publish(
            request,
            principal_id=principal.principal_id,
            creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal.principal_id),
            idempotency_key="rolled-back",
            recorded_at=WHEN,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            content_store=store,
            inline_max_bytes=LOW,
        )
        assert store.has(result.content_id)
        raise _AfterInsertsError
    assert _counts(migrated_engine) == before
    scan = _scan(migrated_engine, store, principal)
    assert scan.checked == 0
    assert scan.orphans == (result.content_id,)
    assert not scan.consistent


# ---- verification on read -----------------------------------------------------------


@pytest.mark.parametrize("include_body", [True, False])
@pytest.mark.parametrize("damage", ["missing", "tampered", "truncated"])
def test_a_missing_or_tampered_object_makes_the_read_internal_error(
    migrated_engine: Engine, tmp_path: Path, include_body: bool, damage: str
) -> None:
    """The prove-red target for digest verification on read."""
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    principal = operator()
    body = _text(2500)
    published = _publish(service, principal, {"format": "markdown", "body": body}, "t")
    part = _object_dir(store, published["content"]["content_id"]) / "decoded"
    if damage == "missing":
        part.unlink()
    elif damage == "tampered":
        part.write_bytes(body.replace("Synthetic", "Synthetik", 1).encode())
    else:
        part.write_bytes(body.encode()[:-1])
    answer = _read(service, principal, published["report_id"], include_body=include_body)
    assert answer["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert answer["result"] is None
    rendered = json.dumps(answer)
    assert body[30:80] not in rendered
    assert published["content"]["decoded_sha256"] not in rendered
    assert str(tmp_path) not in rendered


# ---- update and search --------------------------------------------------------------


def test_updates_write_or_reuse_the_blob_and_search_finds_its_words(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    principal = operator()
    first_body = _text(1500, seed=21) + " zanzibarite"
    published = _publish(service, principal, {"format": "markdown", "body": first_body}, "p")
    report_id = published["report_id"]
    second_body = _text(1800, seed=22) + " quillwortish"
    content = _ok(
        _update(
            service,
            principal,
            report_id,
            1,
            {"content": {"format": "markdown", "body": second_body}},
            "c",
        )
    )
    assert content["change_kind"] == "content"
    assert content["content_id"] != published["content"]["content_id"]
    assert set(store.stored_object_ids()) == {
        published["content"]["content_id"],
        content["content_id"],
    }
    metadata = _ok(_update(service, principal, report_id, 2, {"title": "Renamed blob"}, "m"))
    assert metadata["change_kind"] == "metadata"
    assert metadata["content_id"] == content["content_id"]
    assert len(store.stored_object_ids()) == 2
    assert (
        _row(migrated_engine, "report_versions", "version_id", metadata["version_id"])[
            "search_text"
        ]
        == _row(migrated_engine, "report_versions", "version_id", content["version_id"])[
            "search_text"
        ]
    )
    read = _ok(_read(service, principal, report_id))
    assert read["version_number"] == 3
    assert read["title"] == "Renamed blob"
    assert read["content"]["body"] == second_body
    for version in (1, 2):
        older = _ok(_read(service, principal, report_id, version_number=version))
        assert older["content"]["body"] == (first_body if version == 1 else second_body)
    found = _ok(
        _invoke(
            service,
            principal,
            Capability.REPORTS_SEARCH,
            {"plane": "standalone", "query": "quillwortish"},
        )
    )
    assert [item["report_id"] for item in found["items"]] == [report_id]
    stale = _ok(
        _invoke(
            service,
            principal,
            Capability.REPORTS_SEARCH,
            {"plane": "standalone", "query": "zanzibarite"},
        )
    )
    assert stale["items"] == []
    history = _ok(_invoke(service, principal, Capability.REPORTS_HISTORY, {"report_id": report_id}))
    assert [item["content"]["storage_kind"] for item in history["items"]] == ["managed_blob"] * 3


# ---- scan and isolation -------------------------------------------------------------


def test_the_scan_reports_every_kind_of_damage(migrated_engine: Engine, tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    principal = operator()
    ids = [
        _publish(service, principal, _gzip(_text(2000 + n, seed=n).encode()), f"k{n}")["content"][
            "content_id"
        ]
        for n in range(4)
    ]
    clean = _scan(migrated_engine, store, principal)
    assert (clean.checked, clean.consistent) == (4, True)

    (_object_dir(store, ids[0]) / "original").unlink()
    sized = _object_dir(store, ids[1]) / "decoded"
    sized.write_bytes(sized.read_bytes() + b"!")
    digest = _object_dir(store, ids[2]) / "decoded"
    data = bytearray(digest.read_bytes())
    data[5] ^= 0x01
    digest.write_bytes(bytes(data))
    orphan = "grcnt_" + "ab" * 16
    store.put(orphan, decoded=b"orphan synthetic bytes", original=None)
    (store.root / "content" / "stray.bin").write_bytes(b"x")

    scan = _scan(migrated_engine, store, principal)
    assert scan.checked == 4
    assert scan.missing == ((ids[0], ReportContentPart.ORIGINAL),)
    assert set(scan.mismatched) == {
        ReportContentMismatch(ids[1], ReportContentPart.DECODED, "size"),
        ReportContentMismatch(ids[2], ReportContentPart.DECODED, "digest"),
    }
    assert scan.orphans == (orphan,)
    assert scan.unreadable == ("content/stray.bin",)
    assert not scan.consistent


def test_the_live_scan_reports_stale_temporaries_apart_from_unreadable_entries(
    migrated_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # WP08 (WP05b corrective n2): the same classification as preservation-verify;
    # `verify` treats a stale temporary like an orphan (not clean, exit 2).
    store = _store(tmp_path)
    principal = operator()
    published = _publish(
        _service(migrated_engine, store), principal, _gzip(_text(2000).encode()), "stale"
    )
    content_id = published["content"]["content_id"]
    leftover = _object_dir(store, content_id) / ".original.tmp"
    leftover.write_bytes(b"partial")
    scan = _scan(migrated_engine, store, principal)
    assert scan.missing == () and scan.mismatched == () and scan.orphans == ()
    assert scan.unreadable == ()
    assert len(scan.stale_temporaries) == 1 and not scan.consistent
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", str(store.root))
    assert report_content_cli.main(["verify", "--principal", principal.principal_id]) == 2
    out = capsys.readouterr().out
    assert "unreadable_entries 0" in out and "stale_temporaries 1" in out
    assert str(tmp_path) not in out
    assert leftover.exists()


def test_reads_and_the_scan_are_principal_scoped(migrated_engine: Engine, tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    owner, stranger = operator(), operator()
    published = _publish(service, owner, {"format": "text", "body": _text(2000)}, "own")
    foreign = _read(service, stranger, published["report_id"])
    missing = _read(service, stranger, "grpt_" + "0" * 26)
    assert foreign["error"]["code"] == ErrorCode.NOT_FOUND.value
    assert {k: v for k, v in foreign["error"].items() if k != "correlation_id"} == {
        k: v for k, v in missing["error"].items() if k != "correlation_id"
    }
    theirs = _scan(migrated_engine, store, stranger)
    assert theirs.checked == 0
    # The orphan direction is across Principals: the owner's object is no orphan.
    assert theirs.orphans == ()
    assert _scan(migrated_engine, store, owner).checked == 1


def test_the_operator_command_scans_backs_up_and_refuses_an_in_place_backup(
    migrated_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`apps/cli/report_content.py` against this clone (its URL is in the environment)."""
    store = _store(tmp_path)
    principal = operator()
    published = _publish(
        _service(migrated_engine, store), principal, {"format": "text", "body": _text(2000)}, "cli"
    )
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", str(store.root))
    assert report_content_cli.main(["verify", "--principal", principal.principal_id]) == 0
    out = capsys.readouterr().out
    assert "objects_checked 1" in out
    assert "orphaned_objects 0" in out
    assert str(tmp_path) not in out

    backup = tmp_path / "backup"
    backup.mkdir()
    assert (
        report_content_cli.main(
            ["backup", "--principal", principal.principal_id, "--destination", str(backup)]
        )
        == 0
    )
    assert "copied 1" in capsys.readouterr().out
    inside = store.root / "nested-backup"
    inside.mkdir()
    refused = report_content_cli.main(
        ["backup", "--principal", principal.principal_id, "--destination", str(inside)]
    )
    captured = capsys.readouterr()
    assert refused == 1
    assert str(tmp_path) not in captured.err

    (_object_dir(store, published["content"]["content_id"]) / "decoded").unlink()
    assert report_content_cli.main(["verify", "--principal", principal.principal_id]) == 2
    assert f"missing {published['content']['content_id']} decoded" in capsys.readouterr().out


def _oversized_associations() -> list[dict[str, Any]]:
    """64 asserted external sources whose refs push the manifest past its byte bound."""
    return [
        {
            "target_kind": "external_source",
            "target_ref": f"https://example.test/{n:03d}" + "r" * 480,
            "relation": "cites",
            "target_version_ref": "v" * 512,
        }
        for n in range(64)
    ]


def test_a_manifest_too_large_publish_leaves_no_object_and_no_row(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """Corrective B1: the manifest bound is a refusal, so it must precede the `put`."""
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    principal = operator()
    before = _counts(migrated_engine)
    answer = _invoke(
        service,
        principal,
        Capability.REPORTS_PUBLISH,
        {
            "title": "Synthetic oversized manifest",
            "content": _gzip(_text(4000).encode()),
            "idempotency_key": "too-large-publish",
            "associations": _oversized_associations(),
        },
    )
    assert answer["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    # The manifest bound (`manifest_too_large`), not an earlier refusal.
    assert answer["error"]["safe_details"] == ["metadata", "max_bytes"]
    assert _counts(migrated_engine) == before
    assert store.stored_object_ids() == ()
    assert store.unreadable_entries() == ()
    assert _scan(migrated_engine, store, principal).consistent


def test_a_manifest_too_large_update_leaves_no_object_and_no_row(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """Corrective B1, update: new blob content refused by the manifest bound writes nothing."""
    store = _store(tmp_path)
    service = _service(migrated_engine, store)
    principal = operator()
    published = _publish(service, principal, {"format": "text", "body": "small synthetic"}, "s")
    before = _counts(migrated_engine)
    answer = _update(
        service,
        principal,
        published["report_id"],
        1,
        {
            "content": _gzip(_text(4000, seed=9).encode()),
            "associations": _oversized_associations(),
        },
        "too-large-update",
    )
    assert answer["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    # The manifest bound (`manifest_too_large`), not an earlier refusal.
    assert answer["error"]["safe_details"] == ["metadata", "max_bytes"]
    assert _counts(migrated_engine) == before
    assert store.stored_object_ids() == ()
    assert _scan(migrated_engine, store, principal).consistent
