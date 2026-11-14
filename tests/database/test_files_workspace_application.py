"""Files workspace WP5: the `files.*` capabilities end to end on PostgreSQL.

The `database` tier, each test on its own disposable head clone. Every request
goes through `ApplicationService.invoke` composed as `bootstrap/gateway.py`
composes it -- the SQL unit of work (with `file_workspace` wired), the audit
sink, and `FileWorkspaceApplication` over the contained store on a synthetic
`tmp_path` root -- so `authorize` audits each call against the stored
`capability_is_known` and `purpose_is_known` CHECKs WP4 restated. It proves:

* idempotency: a replay answers the stored result (`replayed: true`) and
  touches neither the filesystem nor a row; another intent under the same key
  is `conflict` on `idempotency_key`; an upload's token is answered once and
  never stored;
* CAS and no overwrite, with the preimage row of a replace;
* trash and restore rows, history from rows, the ticket rows;
* the per-workspace advisory lock: a second transaction cannot take it while
  the first holds it, a different alias can, and it is released at the end of
  the holder's transaction;
* the audit trail names the capability and the purpose and no path or text;
* the plane absent (no store composed): every name is `unsupported`.

Lock waits are bounded (`lock_timeout`). Every path, byte and id is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import (
    BeginFileUpload,
    Command,
    FinalizeFileUpload,
    GetFileHistory,
    ListFileWorkspaces,
    MakeFileDirectory,
    RestoreFile,
    TrashFile,
    WriteFileText,
)
from my_pa.application.file_workspace import FileWorkspaceApplication
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.file_workspace import SqlFileWorkspaceRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

PRINCIPAL: Final = "prn_fileswp5db000001"
WORKSPACE: Final = "mcp"
TEXT: Final = "Synthetic workspace text 5c1e"
LOCK_NOT_AVAILABLE: Final = "55P03"
LIMITS: Final = EffectiveLimits(
    max_page_size=200, default_page_size=50, max_fetch_bytes=8 * 1024 * 1024, max_enrollment_depth=0
)


class _Runtime:
    def __init__(self, url: str, root: Path | None) -> None:
        self.engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=audit)

        self.root = root
        files = (
            None
            if root is None
            else FileWorkspaceApplication(
                FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0),
                workspace_id=WORKSPACE,
                max_upload_bytes=1 << 20,
            )
        )
        self.service = ApplicationService(
            unit_of_work=unit_of_work, limits=LIMITS, file_workspace=files
        )

    def close(self) -> None:
        self.engine.dispose()
        self.audit_engine.dispose()

    def invoke(self, command: Command) -> ResponseEnvelope:
        capability = command.capability
        (purpose,) = permitted_purposes(capability)
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=purpose,
                principal_id=PRINCIPAL,
                requested_at=datetime.now(UTC),
            ),
            command,
            principal=Principal(
                principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=CaptureTransport.LOCAL,
        )

    def ok(self, command: Command) -> dict[str, Any]:
        envelope = self.invoke(command)
        assert envelope.error is None, (command.capability.value, envelope.error)
        result = envelope.to_canonical_dict()["result"]
        assert isinstance(result, dict)
        return result

    def refused(self, command: Command) -> tuple[str, list[str]]:
        envelope = self.invoke(command)
        assert envelope.error is not None, command.capability.value
        error = envelope.to_canonical_dict()["error"]
        assert isinstance(error, dict)
        return str(error["code"]), list(error.get("safe_details") or [])

    def count(self, table: str) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
            )


@pytest.fixture
def runtime(cloned_database_url: str, tmp_path: Path) -> Iterator[_Runtime]:
    root = tmp_path / "workspace"
    root.mkdir()
    built = _Runtime(cloned_database_url, root)
    try:
        yield built
    finally:
        built.close()


def _write(
    rt: _Runtime, path: str, body: str, key: str, version: str | None = None
) -> dict[str, Any]:
    return rt.ok(
        WriteFileText(
            workspace_id=WORKSPACE,
            path=path,
            text=body,
            idempotency_key=key,
            expected_version=version,
        )
    )


def test_a_replay_answers_the_stored_receipt_and_touches_nothing(runtime: _Runtime) -> None:
    command = MakeFileDirectory(workspace_id=WORKSPACE, path="Synthetic", idempotency_key="db-k1")
    first = runtime.ok(command)
    assert first["replayed"] is False
    assert runtime.root is not None
    (runtime.root / "Synthetic").rmdir()
    again = runtime.ok(command)
    assert again == {**first, "replayed": True}
    assert not (runtime.root / "Synthetic").exists()
    assert runtime.count("file_workspace_receipts") == 1
    code, details = runtime.refused(
        MakeFileDirectory(workspace_id=WORKSPACE, path="Other", idempotency_key="db-k1")
    )
    assert (code, details) == ("conflict", ["idempotency_key"])
    assert runtime.count("file_workspace_receipts") == 1


def test_cas_no_overwrite_and_the_preimage_row(runtime: _Runtime) -> None:
    created = _write(runtime, "a.txt", TEXT, "db-w1")
    version = created["entry"]["version"]
    assert runtime.refused(
        WriteFileText(workspace_id=WORKSPACE, path="a.txt", text="x", idempotency_key="db-w2")
    ) == ("conflict", ["exists"])
    assert runtime.refused(
        WriteFileText(
            workspace_id=WORKSPACE,
            path="a.txt",
            text="x",
            idempotency_key="db-w3",
            expected_version="fv1_" + "0" * 64,
        )
    ) == ("conflict", ["version_conflict"])
    replaced = _write(runtime, "a.txt", "replacement", "db-w4", version)
    preimage = replaced["preimage_version_id"]
    with runtime.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT path, version, size, cause FROM knowledge.file_workspace_versions "
                "WHERE version_id = :id"
            ),
            {"id": preimage},
        ).one()
        results = connection.execute(
            text("SELECT result::text FROM knowledge.file_workspace_receipts")
        ).scalars()
        stored = " ".join(results)
    assert tuple(row) == ("a.txt", version, len(TEXT), "files.write_text")
    assert TEXT not in stored and "replacement" not in stored
    history = runtime.ok(GetFileHistory(workspace_id=WORKSPACE, path="a.txt"))
    assert [item["version_id"] for item in history["items"]] == [preimage]


def test_trash_restore_and_history_come_from_rows(runtime: _Runtime) -> None:
    _write(runtime, "t.txt", TEXT, "db-t1")
    trashed = runtime.ok(TrashFile(workspace_id=WORKSPACE, path="t.txt", idempotency_key="db-t2"))
    item = trashed["trash_item_id"]
    history = runtime.ok(GetFileHistory(workspace_id=WORKSPACE))
    assert [entry["trash_item_id"] for entry in history["items"]] == [item]
    runtime.ok(RestoreFile(workspace_id=WORKSPACE, trash_item_id=item, idempotency_key="db-t3"))
    assert runtime.refused(
        RestoreFile(workspace_id=WORKSPACE, trash_item_id=item, idempotency_key="db-t4")
    ) == ("not_found", ["not_found"])
    with runtime.engine.connect() as connection:
        restored = connection.execute(
            text(
                "SELECT restored_path FROM knowledge.file_workspace_trash WHERE trash_item_id = :id"
            ),
            {"id": item},
        ).scalar_one()
    assert restored == "t.txt"


def test_an_upload_token_is_answered_once_and_only_its_digest_is_stored(
    runtime: _Runtime,
) -> None:
    data = b"synthetic bytes"
    digest = hashlib.sha256(data).hexdigest()
    begin = BeginFileUpload(
        workspace_id=WORKSPACE, path="u.bin", idempotency_key="db-u1", size=len(data)
    )
    begun = runtime.ok(begin)
    token = begun["upload_token"]
    replay = runtime.ok(begin)
    assert replay["replayed"] is True and "upload_token" not in replay
    with runtime.engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT token_digest FROM knowledge.file_workspace_transfers "
                "WHERE transfer_id = :id"
            ),
            {"id": begun["upload_id"]},
        ).scalar_one()
        everything = " ".join(
            connection.execute(
                text(
                    "SELECT t::text FROM knowledge.file_workspace_transfers t "
                    "UNION ALL SELECT r::text FROM knowledge.file_workspace_receipts r"
                )
            ).scalars()
        )
    assert stored == hashlib.sha256(bytes.fromhex(token.removeprefix("gfwtk_"))).hexdigest()
    assert token not in everything and token.removeprefix("gfwtk_") not in everything
    assert runtime.root is not None
    FilesystemFileWorkspaceStore(runtime.root, disk_reserve_bytes=0).append_upload(
        begun["upload_id"], 0, [data], limit=1 << 20
    )
    published = runtime.ok(
        FinalizeFileUpload(
            workspace_id=WORKSPACE,
            upload_id=begun["upload_id"],
            length=len(data),
            sha256=digest,
            idempotency_key="db-u2",
        )
    )
    assert published["entry"]["size"] == len(data)
    assert (runtime.root / "u.bin").read_bytes() == data


def test_the_audit_trail_names_the_capability_and_never_a_path_or_text(
    runtime: _Runtime,
) -> None:
    _write(runtime, "secret-name.md", TEXT, "db-a1")
    with runtime.audit_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT capability, purpose, outcome, row_to_json(a)::text "
                "FROM knowledge.audit_events a WHERE principal_id = :p"
            ),
            {"p": PRINCIPAL},
        ).all()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("files.write_text", "file_workspace_authoring", "allowed")
    ]
    assert "secret-name" not in rows[0][3] and TEXT not in rows[0][3]


def test_the_workspace_lock_serializes_one_alias_and_is_released_at_commit(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as holder:
        holder_transaction = holder.begin()
        SqlFileWorkspaceRepository(holder).lock_workspace(WORKSPACE)
        with migrated_engine.connect() as contender:
            with contender.begin():
                contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
                with pytest.raises(DBAPIError) as caught:
                    SqlFileWorkspaceRepository(contender).lock_workspace(WORKSPACE)
                assert getattr(caught.value.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE
            with contender.begin():
                contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
                SqlFileWorkspaceRepository(contender).lock_workspace("other_alias")
            holder_transaction.commit()
            with contender.begin():
                contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
                SqlFileWorkspaceRepository(contender).lock_workspace(WORKSPACE)


def test_no_composed_store_serves_no_files_name(cloned_database_url: str) -> None:
    absent = _Runtime(cloned_database_url, None)
    try:
        assert not {
            capability
            for capability in absent.service.available_capabilities
            if capability.value.startswith("files.")
        }
        assert absent.refused(ListFileWorkspaces()) == ("unsupported", [])
        assert Capability.FILES_WRITE_TEXT not in absent.service.available_capabilities
    finally:
        absent.close()
