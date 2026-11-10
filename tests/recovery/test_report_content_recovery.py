"""Reports Modernization WP05 C7: the report content plane survives a dump, copy and restore.

The recovery the runbook describes, end to end against a real server and real
filesystem roots: `managed_blob` reports are published into a migrated
disposable database with a temporary report content root; the database is
dumped with `pg_dump` (custom format) and the store copied with
`back_up_report_content`; a fresh empty database receives the dump through
`pg_restore` and a fresh root receives the objects through
`restore_report_content`, verified against the restored rows. The restored
pair then scans clean and reads every body back exactly. Finally one object
is deleted, one tampered and one orphan planted, and the scan names each.

`pg_dump`/`pg_restore` are looked up in `MY_PA_PG_BIN`, then on `PATH`, then
in `/opt/homebrew/opt/postgresql@15/bin`; without them the test is skipped
with that reason. The fresh database is the `empty_database_url` fixture's,
dropped when the test ends. Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import random
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, make_url

from my_pa.adapters.normalization import normalize
from my_pa.application.report_content import (
    ReportContentMismatch,
    back_up_report_content,
    restore_report_content,
    scan_report_content,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ReportContentPart
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from tests.conftest import DEFAULT_LIMITS, operator

pytestmark = pytest.mark.recovery

WHEN: Final = datetime(2026, 11, 5, 12, tzinfo=UTC)
THRESHOLD: Final = 1024
_HOMEBREW: Final = Path("/opt/homebrew/opt/postgresql@15/bin")


def _tool(name: str) -> str | None:
    configured = os.environ.get("MY_PA_PG_BIN")
    if configured:
        candidate = Path(configured) / name
        return str(candidate) if candidate.is_file() else None
    found = shutil.which(name)
    if found:
        return found
    candidate = _HOMEBREW / name
    return str(candidate) if candidate.is_file() else None


def _libpq(url: str) -> str:
    """A SQLAlchemy URL as the libpq URI `pg_dump`/`pg_restore` accept."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _text(size: int, seed: int) -> str:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    words = [f"r{rng.getrandbits(28):07x}" for _ in range(1024)]
    out = ["# Synthetic recovery report"]
    length = len(out[0])
    while length < size:
        word = " " + rng.choice(words)
        out.append(word)
        length += len(word)
    return "".join(out)[:size]


def _gzip(raw: bytes, fmt: str) -> dict[str, Any]:
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    return {"format": fmt, "encoding": "gzip+base64", "encoded": encoded}


def _service(engine: Engine, store: FilesystemReportContentStore) -> ApplicationService:
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        report_content_store=store,
        report_content_inline_max_bytes=THRESHOLD,
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
    answer = service.invoke(metadata, command, principal=principal).model_dump(mode="json")
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _root(tmp_path: Path, name: str) -> FilesystemReportContentStore:
    path = tmp_path / name
    path.mkdir()
    return FilesystemReportContentStore(path)


def _run(command: list[str]) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed tool, arguments built here
        command, capture_output=True, text=True, timeout=120, check=False
    )
    assert completed.returncode == 0, completed.stderr[-2000:]


def test_a_dumped_database_and_copied_store_restore_scan_clean_and_read_back(
    migrated_engine: Engine, empty_database_url: str, tmp_path: Path
) -> None:
    pg_dump, pg_restore = _tool("pg_dump"), _tool("pg_restore")
    if pg_dump is None or pg_restore is None:
        pytest.skip("pg_dump/pg_restore not found in MY_PA_PG_BIN, on PATH, or in Homebrew 15")
    principal = operator()
    live = _root(tmp_path, "live")
    service = _service(migrated_engine, live)
    bodies: dict[str, str] = {}
    data: dict[str, object] = {}
    markdown = _text(3000, seed=1)
    report = _invoke(
        service,
        principal,
        Capability.REPORTS_PUBLISH,
        {
            "title": "Recovery A",
            "content": {"format": "markdown", "body": markdown},
            "idempotency_key": "a",
        },
    )
    bodies[report["report_id"]] = markdown
    plain = _text(2500, seed=2)
    report = _invoke(
        service,
        principal,
        Capability.REPORTS_PUBLISH,
        {"title": "Recovery B", "content": _gzip(plain.encode(), "text"), "idempotency_key": "b"},
    )
    bodies[report["report_id"]] = plain
    structured = {"items": [_text(1500, seed=3), 2.5, None], "flag": True}
    report = _invoke(
        service,
        principal,
        Capability.REPORTS_PUBLISH,
        {
            "title": "Recovery C",
            "content": _gzip(json.dumps(structured).encode(), "json"),
            "idempotency_key": "c",
        },
    )
    data[report["report_id"]] = structured
    inline = _invoke(
        service,
        principal,
        Capability.REPORTS_PUBLISH,
        {
            "title": "Recovery D",
            "content": {"format": "text", "body": "inline"},
            "idempotency_key": "d",
        },
    )
    assert inline["content"]["decoded_byte_count"] <= THRESHOLD
    assert len(live.stored_object_ids()) == 3

    # Dump the database; copy the store, verified against the rows.
    dump = tmp_path / "plane.dump"
    _run(
        [
            pg_dump,
            "--format=custom",
            f"--file={dump}",
            _libpq(migrated_engine.url.render_as_string(hide_password=False)),
        ]
    )
    backup = FilesystemReportContentStore(_mkdir(tmp_path / "backup"), other_roots=[live.root])
    with migrated_engine.connect() as connection:
        copied = back_up_report_content(
            SqlGeneralReportRepository(connection),
            live,
            backup,
            principal_id=principal.principal_id,
        )
    assert (copied.objects, copied.copied) == (3, 3)

    # Restore into a fresh database and a fresh root.
    _run(
        [
            pg_restore,
            "--no-owner",
            "--exit-on-error",
            f"--dbname={_libpq(empty_database_url)}",
            str(dump),
        ]
    )
    restored_engine = create_database_engine(empty_database_url)
    try:
        fresh = _root(tmp_path, "fresh")
        with restored_engine.connect() as connection:
            repository = SqlGeneralReportRepository(connection)
            summary = restore_report_content(
                repository, backup, fresh, principal_id=principal.principal_id
            )
            assert (summary.objects, summary.copied) == (3, 3)
            scan = scan_report_content(repository, fresh, principal_id=principal.principal_id)
        assert scan.checked == 3
        assert scan.consistent, scan

        restored = _service(restored_engine, fresh)
        for report_id, body in bodies.items():
            read = _invoke(restored, principal, Capability.REPORTS_READ, {"report_id": report_id})
            assert read["content"]["storage_kind"] == "managed_blob"
            assert read["content"]["body"] == body
        for report_id, value in data.items():
            read = _invoke(restored, principal, Capability.REPORTS_READ, {"report_id": report_id})
            assert read["content"]["data"] == value

        # Now damage the restored root: one deleted, one tampered, one orphan.
        ids = sorted(fresh.stored_object_ids())
        _part(fresh, ids[0], "decoded").unlink()
        tampered = _part(fresh, ids[1], "decoded")
        payload = bytearray(tampered.read_bytes())
        payload[3] ^= 0x01
        tampered.write_bytes(bytes(payload))
        orphan = "grcnt_" + "cd" * 16
        fresh.put(orphan, decoded=b"orphaned synthetic bytes", original=None)
        with restored_engine.connect() as connection:
            damaged = scan_report_content(
                SqlGeneralReportRepository(connection), fresh, principal_id=principal.principal_id
            )
        assert damaged.missing == ((ids[0], ReportContentPart.DECODED),)
        assert damaged.mismatched == (
            ReportContentMismatch(ids[1], ReportContentPart.DECODED, "digest"),
        )
        assert damaged.orphans == (orphan,)
        assert not damaged.consistent
    finally:
        restored_engine.dispose()


def _mkdir(path: Path) -> Path:
    path.mkdir()
    return path


def _part(store: FilesystemReportContentStore, object_id: str, part: str) -> Path:
    return store.root / "content" / object_id.split("_", 1)[1][:2] / object_id / part
