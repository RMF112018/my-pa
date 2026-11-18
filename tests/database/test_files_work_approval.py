"""The `work` workspace end to end on PostgreSQL (ADR-019 Amendment 2, contract section 18).

The `database` tier, on a disposable head clone and synthetic `tmp_path`
folders standing in for the NAS: settings from the overlay's environment shape
(`MY_PA_FILES_WORKSPACES`, `MY_PA_FILES_APPLY_ROOTS`), the workspaces composed
by `bootstrap.gateway.files_workspaces`, every client call through
`ApplicationService.invoke` with the SQL unit of work and audit sink, and the
operator's `apps/cli/remote_mcp.py files-pending` / `files-approve` /
`files-deny` run in process. A temporary directory cannot be a read-only mount,
so the store's mount probe is replaced by one that reports the `work` root (and
only it) read-only; the apply root's writability check is the real one.

It proves: a client write to `work` is audited `allowed`, answers
`approval_required` and changes nothing in the folder; the operator lists it
with its binding, approves it once (a replay is refused, exit 2), and the bytes
appear; a denial is final; the `mcp` workspace is unchanged. Every path, byte
and id is synthetic; nothing leaves the machine.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from collections.abc import Iterator
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import remote_mcp
from sqlalchemy import text

from my_pa.application.commands import (
    Command,
    GetFileHistory,
    ListFileWorkspaces,
    MakeFileDirectory,
    WriteFileText,
)
from my_pa.application.file_workspace import FileWorkspaceApplication
from my_pa.application.service import ApplicationService
from my_pa.bootstrap import gateway
from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.file_workspace import store as store_module
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

PRINCIPAL: Final = "prn_fileswork00000001"
LIMITS: Final = EffectiveLimits(
    max_page_size=200, default_page_size=50, max_fetch_bytes=8 * 1024 * 1024, max_enrollment_depth=0
)


class _Deployment:
    def __init__(self, url: str, base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.mcp = base / "MCP"
        self.work = base / "Work"
        self.state = base / "workspace-state" / "work"
        for directory in (self.mcp, self.work, self.state):
            directory.mkdir(parents=True)
        status = self.work.stat()
        identity = (status.st_dev, status.st_ino)
        monkeypatch.setattr(
            store_module,
            "_mounted_read_only",
            lambda fd: (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == identity,
        )
        environment = {
            "MY_PA_FILES_WORKSPACES": (
                f"mcp={self.mcp},"
                f"work={self.work};mode=approval;state={self.state};max_pending_bytes=65536"
            ),
            # The apply container's read-write bind of the same folder.
            "MY_PA_FILES_APPLY_ROOTS": f"work={self.work}",
        }
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        self.settings = load_settings()
        self.engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=audit)

        files = FileWorkspaceApplication(
            workspaces=gateway.files_workspaces(self.settings, self.engine)
        )
        self.service = ApplicationService(
            unit_of_work=unit_of_work, limits=LIMITS, file_workspace=files
        )

    def ok(self, command: Command) -> dict[str, Any]:
        capability = command.capability
        (purpose,) = permitted_purposes(capability)
        envelope = self.service.invoke(
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
        assert envelope.error is None, (capability.value, envelope.error)
        result = envelope.to_canonical_dict()["result"]
        assert isinstance(result, dict)
        return result

    @staticmethod
    def cli(*argv: str) -> tuple[int, dict[str, Any]]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = remote_mcp.main(list(argv))
        printed = out.getvalue() or err.getvalue()
        return code, json.loads(printed)

    def audited(self, capability: Capability) -> list[str]:
        with self.engine.connect() as connection:
            return [
                str(row)
                for row in connection.execute(
                    text(
                        "SELECT outcome FROM knowledge.audit_events "
                        "WHERE capability = :capability ORDER BY recorded_at"
                    ),
                    {"capability": capability.value},
                ).scalars()
            ]


@pytest.fixture
def deployment(
    cloned_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[_Deployment]:
    built = _Deployment(cloned_database_url, tmp_path, monkeypatch)
    try:
        yield built
    finally:
        built.engine.dispose()


def test_a_work_write_waits_for_the_operator_then_applies_once(deployment: _Deployment) -> None:
    listed = deployment.ok(ListFileWorkspaces())["workspaces"]
    assert [(item["workspace_id"], item["write_mode"]) for item in listed] == [
        ("mcp", "direct"),
        ("work", "approval"),
    ]
    body = "synthetic approved text"
    answer = deployment.ok(
        WriteFileText(workspace_id="work", path="memo.txt", text=body, idempotency_key="wk-1")
    )
    assert answer["approval_required"] is True
    assert list(deployment.work.iterdir()) == []
    assert deployment.audited(Capability.FILES_WRITE_TEXT) == ["allowed"]

    code, pending = deployment.cli("files-pending", "--workspace", "work")
    assert code == 0
    (item,) = pending["pending"]
    assert item["pending_change_id"] == answer["pending_change_id"]
    assert item["sha256"] == hashlib.sha256(body.encode()).hexdigest()

    code, refused = deployment.cli(
        "files-approve",
        "--workspace",
        "work",
        "--pending-change-id",
        item["pending_change_id"],
        "--binding",
        "0" * 64,
    )
    assert (code, refused) == (2, {"refused": "binding_mismatch"})
    assert not (deployment.work / "memo.txt").exists()

    approve = (
        "files-approve",
        "--workspace",
        "work",
        "--pending-change-id",
        item["pending_change_id"],
        "--binding",
        item["binding"],
    )
    code, applied = deployment.cli(*approve)
    assert (code, applied["status"]) == (0, "applied")
    assert (deployment.work / "memo.txt").read_text() == body
    assert deployment.cli(*approve) == (2, {"refused": "not_pending"})

    (status,) = deployment.ok(
        GetFileHistory(workspace_id="work", pending_change_id=item["pending_change_id"])
    )["items"]
    assert status["status"] == "applied"


def test_a_denied_work_write_is_final_and_mcp_is_unchanged(deployment: _Deployment) -> None:
    answer = deployment.ok(
        MakeFileDirectory(workspace_id="work", path="Never", idempotency_key="wk-2")
    )
    code, denied = deployment.cli(
        "files-deny", "--workspace", "work", "--pending-change-id", answer["pending_change_id"]
    )
    assert (code, denied["status"]) == (0, "denied")
    assert not (deployment.work / "Never").exists()
    direct = deployment.ok(MakeFileDirectory(workspace_id="mcp", path="Now", idempotency_key="m-1"))
    assert "approval_required" not in direct
    assert (deployment.mcp / "Now").is_dir()
