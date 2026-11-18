"""A second workspace with approved-only writes (ADR-019 Amendment 2, contract section 18).

Two synthetic workspaces on `tmp_path`: `mcp` (`direct`) and `work`
(`approval`, its state directory beside it), the real contained stores, the
in-memory WP4 repository of `tests/unit/test_file_workspace_application.py`
and the real operator service with a scripted client standing. The kernel
read-only mount cannot be made on a temporary directory, so the `work` store
is given a probe that reports it read-only; that the probe guards composition
and every call is proved separately. Every path, byte and id is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from my_pa.application.commands import (
    BeginFileUpload,
    Command,
    FinalizeFileUpload,
    GetFileHistory,
    ListFiles,
    ListFileWorkspaces,
    MakeFileDirectory,
    MoveFile,
    RestoreFile,
    SearchFiles,
    StatFile,
    TrashFile,
    WriteFileText,
)
from my_pa.application.errors import (
    ApplicationError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
)
from my_pa.application.file_workspace import (
    ComposedFileWorkspace,
    FileWorkspaceApplication,
    pending_binding,
)
from my_pa.application.file_workspace_approval import ApprovalRefused, FileApprovalOperator
from my_pa.bootstrap.settings import SettingsError, load_settings
from my_pa.contracts.ports import (
    FilePendingStatus,
    FileWorkspaceRootError,
    RemoteClientStanding,
    RemoteClientStandingReader,
)
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.files.workspaces import WriteMode
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.transfer import client_ref_of
from my_pa.infrastructure.file_workspace.pending import FilesystemPendingChanges
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from tests.unit.test_file_workspace_application import NOW, PRINCIPAL, _Rows

CLIENT = "synthetic-work-client"
OTHER_CLIENT = "synthetic-other-client"
_DB = {"MY_PA_DATABASE_URL": "postgresql+psycopg://synthetic@localhost:5432/synthetic"}


def _read_only(_descriptor: int) -> bool:
    return True


class _Standing(RemoteClientStandingReader):
    """A scripted client standing: every files write granted until `revoked`."""

    def __init__(self) -> None:
        self.revoked = False
        self.writes = True
        self.extra: set[tuple[Capability, Purpose | None]] = set()

    def standing(self, client_ref: str, *, now: Any) -> RemoteClientStanding | None:  # noqa: ANN401
        del now
        if self.revoked or client_ref != client_ref_of(
            derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT)
        ):
            return None
        return RemoteClientStanding(
            oauth_client_id=CLIENT,
            principal_id=PRINCIPAL,
            capability_purposes=frozenset(
                (capability, Purpose.FILE_WORKSPACE_AUTHORING)
                for capability in Capability
                if capability.value.startswith("files.") and is_write_capability(capability)
            )
            | self.extra,
            write_allowed=self.writes,
        )


class _Work:
    def __init__(self, base: Path) -> None:
        self.mcp_root = base / "mcp"
        self.work_root = base / "Work"
        self.state_root = base / "state"
        for directory in (self.mcp_root, self.work_root, self.state_root):
            directory.mkdir()
        self.work = FilesystemFileWorkspaceStore(
            self.work_root,
            disk_reserve_bytes=0,
            require_read_only_mount=True,
            read_only_probe=_read_only,
        )
        self.staging = FilesystemFileWorkspaceStore(self.state_root, disk_reserve_bytes=0)
        self.pending = FilesystemPendingChanges(self.state_root)
        self.spaces = (
            ComposedFileWorkspace(
                workspace_id="mcp",
                store=FilesystemFileWorkspaceStore(self.mcp_root, disk_reserve_bytes=0),
                max_upload_bytes=1024,
            ),
            ComposedFileWorkspace(
                workspace_id="work",
                store=self.work,
                write_mode=WriteMode.APPROVAL,
                max_upload_bytes=4096,
                staging=self.staging,
                pending=self.pending,
                max_pending_bytes=8192,
            ),
        )
        self.files = FileWorkspaceApplication(workspaces=self.spaces)
        self.rows = _Rows()
        self.at = NOW
        self.standing = _Standing()
        # The apply mount: the same directory, writable (the apply container's bind).
        self.apply = FilesystemFileWorkspaceStore(self.work_root, disk_reserve_bytes=0)
        self.operator = self.operator_with({"work": self.apply})

    def operator_with(self, apply: dict[str, FilesystemFileWorkspaceStore]) -> FileApprovalOperator:
        return FileApprovalOperator(
            workspaces=self.spaces,
            unit_of_work=lambda: nullcontext(SimpleNamespace(file_workspace=self.rows)),  # type: ignore[arg-type,return-value]
            standing=self.standing,
            remote_writes_enabled=True,
            apply_stores=apply,
            clock=lambda: self.at,
        )

    def run(self, command: Command, *, client: str | None = CLIENT) -> dict[str, Any]:
        return self.files.handle(
            SimpleNamespace(file_workspace=self.rows),  # type: ignore[arg-type]
            SimpleNamespace(  # type: ignore[arg-type]
                principal=SimpleNamespace(principal_id=PRINCIPAL),
                at=self.at,
                capability_grants=None,
                transport=CaptureTransport.REMOTE_CLIENT if client else CaptureTransport.LOCAL,
                authenticated_client_id=client,
            ),
            command,
        )

    def binding(self, pending_change_id: str) -> str:
        change = self.pending.get(pending_change_id)
        assert change is not None
        return pending_binding(change)

    def approve(self, pending_change_id: str) -> dict[str, Any]:
        return self.operator.approve("work", pending_change_id, self.binding(pending_change_id))

    def tree(self) -> list[str]:
        """The `work` root's tree, as relative paths with sizes (the apply's evidence)."""
        listed: list[str] = []
        for directory, names, files in os.walk(self.work_root):
            for name in sorted(names + files):
                path = Path(directory) / name
                size = path.lstat().st_size if path.is_file() else "d"
                listed.append(f"{path.relative_to(self.work_root)}:{size}")
        return sorted(listed)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[_Work]:
    yield _Work(tmp_path)


def _key(tag: str) -> str:
    return f"synthetic-{tag}"


def _refused(world: _Work, command: Command, kind: type[ApplicationError]) -> ApplicationError:
    with pytest.raises(kind) as caught:
        world.run(command)
    return caught.value


# ---- configuration (section 18.1) ----------------------------------------------------


def test_the_explicit_list_parses_with_per_workspace_modes_and_limits() -> None:
    settings = load_settings(
        {
            **_DB,
            "MY_PA_FILES_WORKSPACES": (
                "mcp=/srv/w/mcp,"
                "work=/srv/w/work;mode=approval;state=/srv/state/work;max_upload_bytes=2048"
            ),
            "MY_PA_FILES_APPLY_ROOTS": "work=/srv/apply/work",
        }
    )
    mcp, work = settings.files_workspace_configs()
    assert (mcp.workspace_id, mcp.write_mode, mcp.state_root) == ("mcp", WriteMode.DIRECT, None)
    assert (work.workspace_id, work.write_mode, work.state_root, work.max_upload_bytes) == (
        "work",
        WriteMode.APPROVAL,
        "/srv/state/work",
        2048,
    )
    assert mcp.max_upload_bytes == settings.files_max_upload_bytes
    assert settings.files_apply_root_map() == {"work": "/srv/apply/work"}
    assert settings.files_workspace_is_composed()


def test_the_single_root_settings_still_compose_one_direct_workspace() -> None:
    settings = load_settings({**_DB, "MY_PA_FILES_WORKSPACE_ROOT": "/srv/w/mcp"})
    (only,) = settings.files_workspace_configs()
    assert (only.workspace_id, only.root, only.write_mode) == (
        "mcp",
        "/srv/w/mcp",
        WriteMode.DIRECT,
    )
    assert load_settings(_DB).files_workspace_configs() == ()


@pytest.mark.parametrize(
    "environ",
    [
        {"MY_PA_FILES_WORKSPACES": "mcp=/a", "MY_PA_FILES_WORKSPACE_ROOT": "/b"},
        {"MY_PA_FILES_WORKSPACES": "work=/a;mode=approval"},
        {"MY_PA_FILES_WORKSPACES": "work=/a;state=/s"},
        {"MY_PA_FILES_WORKSPACES": "work=/a;mode=sometimes"},
        {"MY_PA_FILES_WORKSPACES": "work=/a;colour=blue"},
        {"MY_PA_FILES_WORKSPACES": "Work=/a"},
        {"MY_PA_FILES_WORKSPACES": "work=relative"},
        {"MY_PA_FILES_WORKSPACES": "a=/x,b=/x/y"},
        {"MY_PA_FILES_WORKSPACES": "a=/x,a=/y"},
        {"MY_PA_FILES_WORKSPACES": "w=/x;mode=approval;state=/x/state"},
        {"MY_PA_FILES_WORKSPACES": "mcp=/x", "MY_PA_FILES_APPLY_ROOTS": "mcp=/y"},
    ],
)
def test_a_malformed_or_ambiguous_list_refuses_the_settings(environ: dict[str, str]) -> None:
    with pytest.raises(SettingsError):
        load_settings({**_DB, **environ})


# ---- workspaces and reads (sections 6 and 18.2) -----------------------------------------


def test_each_workspace_is_listed_with_its_write_mode_and_limits(world: _Work) -> None:
    answer = world.run(ListFileWorkspaces())
    assert [
        (
            item["workspace_id"],
            item["writable"],
            item["write_mode"],
            item["limits"]["max_upload_bytes"],
        )
        for item in answer["workspaces"]
    ] == [("mcp", True, "direct", 1024), ("work", True, "approval", 4096)]


def test_a_read_only_workspace_reads_and_refuses_every_write(tmp_path: Path) -> None:
    root = tmp_path / "ro"
    root.mkdir()
    (root / "a.txt").write_bytes(b"synthetic")
    store = FilesystemFileWorkspaceStore(
        root, disk_reserve_bytes=0, require_read_only_mount=True, read_only_probe=_read_only
    )
    files = FileWorkspaceApplication(
        workspaces=(
            ComposedFileWorkspace(workspace_id="ro", store=store, write_mode=WriteMode.READ_ONLY),
        )
    )

    def run(command: Command) -> dict[str, Any]:
        return files.handle(
            SimpleNamespace(file_workspace=_Rows()),  # type: ignore[arg-type]
            SimpleNamespace(  # type: ignore[arg-type]
                principal=SimpleNamespace(principal_id=PRINCIPAL),
                at=NOW,
                capability_grants=None,
                transport=CaptureTransport.LOCAL,
                authenticated_client_id=None,
            ),
            command,
        )

    assert [entry["name"] for entry in run(ListFiles(workspace_id="ro", path=""))["entries"]] == [
        "a.txt"
    ]
    assert run(ListFileWorkspaces())["workspaces"][0]["writable"] is False
    for command in (
        MakeFileDirectory(workspace_id="ro", path="d", idempotency_key=_key("ro1")),
        WriteFileText(workspace_id="ro", path="b.txt", text="x", idempotency_key=_key("ro2")),
        TrashFile(workspace_id="ro", path="a.txt", idempotency_key=_key("ro3")),
        BeginFileUpload(workspace_id="ro", path="c.bin", idempotency_key=_key("ro4")),
    ):
        with pytest.raises(UnsupportedError) as caught:
            run(command)
        assert caught.value.safe_details == (SafeDetail.WORKSPACE_READ_ONLY,)
    assert sorted(path.name for path in root.iterdir()) == ["a.txt"]


def test_a_writable_root_is_refused_for_a_read_only_mode(tmp_path: Path) -> None:
    root = tmp_path / "rw"
    root.mkdir()
    # The real probe: a temporary directory is a writable mount.
    with pytest.raises(FileWorkspaceRootError):
        FilesystemFileWorkspaceStore(root, require_read_only_mount=True)


def test_a_root_that_stops_being_read_only_serves_nothing(world: _Work) -> None:
    flag = {"read_only": True}
    store = FilesystemFileWorkspaceStore(
        world.work_root,
        disk_reserve_bytes=0,
        require_read_only_mount=True,
        read_only_probe=lambda _fd: flag["read_only"],
    )
    store.list_directory("", after=None, page_size=10)
    flag["read_only"] = False  # remounted writable, or the bind went away
    with pytest.raises(Exception) as caught:
        store.list_directory("", after=None, page_size=10)
    assert type(caught.value).__name__ == "FileWorkspaceUnavailableError"


def test_hidden_metadata_and_control_directories_are_never_listed_or_searched(
    world: _Work,
) -> None:
    for name in ("@eaDir", ".my-pa", "#recycle", "visible"):
        (world.work_root / name).mkdir()
        (world.work_root / name / "doc.pdf").write_bytes(b"synthetic")
    listed = world.run(ListFiles(workspace_id="work", path=""))["entries"]
    assert [entry["name"] for entry in listed] == ["visible"]
    found = world.run(SearchFiles(workspace_id="work", path="", query="doc"))["entries"]
    assert [entry["path"] for entry in found] == ["visible/doc.pdf"]
    with pytest.raises(InvalidRequestError):
        world.run(StatFile(workspace_id="work", path="@eaDir/doc.pdf"))


def test_a_symlink_out_of_the_root_is_never_followed(world: _Work, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"synthetic secret")
    (world.work_root / "escape").symlink_to(outside)
    error = _refused(
        world, StatFile(workspace_id="work", path="escape/secret.txt"), UnsupportedError
    )
    assert error.safe_details == (SafeDetail.UNSUPPORTED_ENTRY,)
    # Nor can a pending write be routed through it.
    with pytest.raises(UnsupportedError):
        world.run(
            WriteFileText(
                workspace_id="work", path="escape/new.txt", text="x", idempotency_key=_key("sym")
            )
        )


def test_an_unknown_alias_and_another_workspaces_ids_are_not_found(world: _Work) -> None:
    error = _refused(world, ListFiles(workspace_id="nowhere", path=""), NotFoundError)
    assert error.safe_details == (SafeDetail.NOT_FOUND,)
    (world.mcp_root / "m.txt").write_bytes(b"synthetic")
    trashed = world.run(TrashFile(workspace_id="mcp", path="m.txt", idempotency_key=_key("t")))
    # An `mcp` trash item named under `work` is not found, and records nothing.
    _refused(
        world,
        RestoreFile(
            workspace_id="work", trash_item_id=trashed["trash_item_id"], idempotency_key=_key("r")
        ),
        NotFoundError,
    )
    assert world.pending.list_changes(limit=10) == []


# ---- pending changes (section 18.3) and approval (18.5) ---------------------------------


def test_a_client_write_is_never_applied_and_answers_approval_required(world: _Work) -> None:
    before = world.tree()
    answer = world.run(
        MakeFileDirectory(workspace_id="work", path="Reports", idempotency_key=_key("m"))
    )
    assert answer["approval_required"] is True
    assert answer["status"] == "pending"
    assert answer["operation"] == "files.mkdir"
    assert answer["pending_change_id"].startswith("fwpnd_")
    assert world.tree() == before == []
    # The client polls its change (a read).
    status = world.run(
        GetFileHistory(workspace_id="work", pending_change_id=answer["pending_change_id"])
    )
    (item,) = status["items"]
    assert (item["item"], item["status"], item["path"]) == ("pending", "pending", "Reports")


def test_an_approved_mkdir_is_applied_once_and_reported(world: _Work) -> None:
    pending = world.run(
        MakeFileDirectory(workspace_id="work", path="Reports", idempotency_key=_key("m"))
    )["pending_change_id"]
    binding = world.binding(pending)
    decided = world.operator.approve("work", pending, binding)
    assert decided["status"] == "applied"
    assert (world.work_root / "Reports").is_dir()
    # Single use: the same approval again changes nothing.
    with pytest.raises(ApprovalRefused) as again:
        world.operator.approve("work", pending, binding)
    assert again.value.reason == "not_pending"
    (item,) = world.run(GetFileHistory(workspace_id="work", pending_change_id=pending))["items"]
    assert item["status"] == "applied"
    assert item["result"]["path"] == "Reports"


def test_write_text_stages_outside_the_root_and_publishes_only_when_approved(
    world: _Work,
) -> None:
    text = "synthetic report body\n"
    answer = world.run(
        WriteFileText(workspace_id="work", path="note.txt", text=text, idempotency_key=_key("w"))
    )
    assert not (world.work_root / "note.txt").exists()
    record = json.loads(
        next((world.state_root / ".my-pa" / "pending").glob("fwpnd_*.json")).read_text()
    )
    assert record["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert "synthetic report body" not in json.dumps(record)
    assert world.approve(answer["pending_change_id"])["status"] == "applied"
    assert (world.work_root / "note.txt").read_text() == text
    # The state directory's staged bytes are gone; the record moved to `decided`.
    assert list((world.state_root / ".my-pa" / "staging").iterdir()) == []
    assert list((world.state_root / ".my-pa" / "pending").glob("*.json")) == []


def test_a_replace_preserves_the_preimage_and_records_its_version(world: _Work) -> None:
    (world.work_root / "doc.txt").write_text("old")
    current = world.run(StatFile(workspace_id="work", path="doc.txt"))["version"]
    answer = world.run(
        WriteFileText(
            workspace_id="work",
            path="doc.txt",
            text="new",
            expected_version=current,
            idempotency_key=_key("rep"),
        )
    )
    decided = world.approve(answer["pending_change_id"])
    assert decided["status"] == "applied"
    assert (world.work_root / "doc.txt").read_text() == "new"
    (version,) = world.rows.versions.values()
    assert (version.path, version.version, version.cause) == (
        "doc.txt",
        current,
        "files.write_text",
    )
    assert decided["result"]["preimage_version_id"] == version.version_id


def test_an_uploaded_ticket_is_staged_in_the_state_directory_then_approved(
    world: _Work,
) -> None:
    data = b"synthetic upload bytes" * 10
    begun = world.run(
        BeginFileUpload(workspace_id="work", path="up.bin", idempotency_key=_key("ub"))
    )
    # The ticket's staging is the state directory's, never the root's.
    assert (world.state_root / ".my-pa" / "staging" / begun["upload_id"]).exists()
    assert not (world.work_root / ".my-pa").exists()
    world.staging.append_upload(begun["upload_id"], 0, iter((data,)), limit=len(data))
    answer = world.run(
        FinalizeFileUpload(
            workspace_id="work",
            upload_id=begun["upload_id"],
            length=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            idempotency_key=_key("uf"),
        )
    )
    assert answer["approval_required"] is True
    assert answer["operation"] == "files.upload.finalize"
    assert not (world.work_root / "up.bin").exists()
    assert world.approve(answer["pending_change_id"])["status"] == "applied"
    assert (world.work_root / "up.bin").read_bytes() == data


def test_a_trash_is_a_rename_into_the_roots_control_directory_and_can_be_restored(
    world: _Work,
) -> None:
    (world.work_root / "old.pdf").write_bytes(b"synthetic pdf")
    trash = world.run(TrashFile(workspace_id="work", path="old.pdf", idempotency_key=_key("tr")))
    assert (world.work_root / "old.pdf").exists()
    decided = world.approve(trash["pending_change_id"])
    assert decided["status"] == "applied"
    item_id = decided["result"]["trash_item_id"]
    assert not (world.work_root / "old.pdf").exists()
    assert (world.work_root / ".my-pa" / "trash" / item_id).read_bytes() == b"synthetic pdf"
    # `.my-pa` stays hidden from the read-only view.
    assert world.run(ListFiles(workspace_id="work", path=""))["entries"] == []
    restore = world.run(
        RestoreFile(workspace_id="work", trash_item_id=item_id, idempotency_key=_key("rs"))
    )
    assert world.approve(restore["pending_change_id"])["status"] == "applied"
    assert (world.work_root / "old.pdf").read_bytes() == b"synthetic pdf"


def test_an_approval_for_another_change_or_an_altered_record_is_refused(world: _Work) -> None:
    first = world.run(MakeFileDirectory(workspace_id="work", path="A", idempotency_key=_key("a")))
    second = world.run(MakeFileDirectory(workspace_id="work", path="B", idempotency_key=_key("b")))
    # The binding of a different change (another path) does not approve this one.
    with pytest.raises(ApprovalRefused) as wrong:
        world.operator.approve(
            "work", first["pending_change_id"], world.binding(second["pending_change_id"])
        )
    assert wrong.value.reason == "binding_mismatch"
    # A record altered after review (its path) no longer matches the reviewed binding.
    reviewed = world.binding(first["pending_change_id"])
    record_path = world.state_root / ".my-pa" / "pending" / f"{first['pending_change_id']}.json"
    record = json.loads(record_path.read_text())
    record["arguments"]["path"] = "Elsewhere"
    record_path.write_text(json.dumps(record))
    with pytest.raises(ApprovalRefused) as altered:
        world.operator.approve("work", first["pending_change_id"], reviewed)
    assert altered.value.reason == "binding_mismatch"
    assert world.tree() == []


def test_an_approval_bound_to_another_hash_is_refused_at_apply(world: _Work) -> None:
    answer = world.run(
        WriteFileText(workspace_id="work", path="h.txt", text="one", idempotency_key=_key("h"))
    )
    change = world.pending.get(answer["pending_change_id"])
    assert change is not None
    # The staged bytes changed after the request: the apply's digest check refuses.
    staged = world.state_root / ".my-pa" / "staging" / str(change.staged_upload_id)
    staged.write_bytes(b"two")
    decided = world.approve(answer["pending_change_id"])
    assert (decided["status"], decided["reason"]) == ("failed", "digest_mismatch")
    assert not (world.work_root / "h.txt").exists()


def test_an_expired_change_cannot_be_approved_and_its_bytes_are_discarded(world: _Work) -> None:
    answer = world.run(
        WriteFileText(workspace_id="work", path="late.txt", text="x", idempotency_key=_key("l"))
    )
    world.at = NOW + timedelta(seconds=901)
    decided = world.approve(answer["pending_change_id"])
    assert decided["status"] == "expired"
    assert not (world.work_root / "late.txt").exists()
    assert list((world.state_root / ".my-pa" / "staging").iterdir()) == []


def test_a_grant_revoked_before_apply_fails_the_change(world: _Work) -> None:
    answer = world.run(MakeFileDirectory(workspace_id="work", path="R", idempotency_key=_key("rv")))
    world.standing.revoked = True
    decided = world.approve(answer["pending_change_id"])
    assert (decided["status"], decided["reason"]) == ("failed", "denied")
    assert world.tree() == []


def test_writes_disabled_for_the_client_before_apply_fails_the_change(world: _Work) -> None:
    answer = world.run(MakeFileDirectory(workspace_id="work", path="W", idempotency_key=_key("wd")))
    world.standing.writes = False
    assert world.approve(answer["pending_change_id"])["reason"] == "denied"
    assert world.tree() == []


def test_a_change_made_since_the_request_fails_the_apply(world: _Work) -> None:
    (world.work_root / "src.txt").write_text("v1")
    move = world.run(
        MoveFile(workspace_id="work", path="src.txt", to_path="dst.txt", idempotency_key=_key("mv"))
    )
    (world.work_root / "src.txt").write_text("v2, edited over SMB")
    decided = world.approve(move["pending_change_id"])
    assert decided["status"] == "failed"
    assert decided["reason"] in {"version_conflict", "external_change_detected"}
    assert (world.work_root / "src.txt").read_text() == "v2, edited over SMB"
    assert not (world.work_root / "dst.txt").exists()


def test_a_denied_change_is_final_and_discards_its_bytes(world: _Work) -> None:
    answer = world.run(
        WriteFileText(workspace_id="work", path="no.txt", text="x", idempotency_key=_key("d"))
    )
    assert world.operator.deny("work", answer["pending_change_id"])["status"] == "denied"
    assert list((world.state_root / ".my-pa" / "staging").iterdir()) == []
    with pytest.raises(ApprovalRefused):
        world.approve(answer["pending_change_id"])
    journal = (world.state_root / ".my-pa" / "decisions.jsonl").read_text().splitlines()
    assert [json.loads(line)["decision"] for line in journal] == ["denied"]
    assert "no.txt" not in "".join(journal)


def test_the_apply_needs_the_same_directory_mounted_read_write(
    world: _Work, tmp_path: Path
) -> None:
    answer = world.run(MakeFileDirectory(workspace_id="work", path="X", idempotency_key=_key("x")))
    with pytest.raises(ApprovalRefused) as missing:
        world.operator_with({}).approve(
            "work", answer["pending_change_id"], world.binding(answer["pending_change_id"])
        )
    assert missing.value.reason == "no_apply_root"
    other = tmp_path / "not-work"
    other.mkdir()
    wrong = world.operator_with({"work": FilesystemFileWorkspaceStore(other, disk_reserve_bytes=0)})
    with pytest.raises(ApprovalRefused) as mismatched:
        wrong.approve(
            "work", answer["pending_change_id"], world.binding(answer["pending_change_id"])
        )
    assert mismatched.value.reason == "apply_root_mismatch"
    assert world.pending.get(answer["pending_change_id"]).status is FilePendingStatus.PENDING  # type: ignore[union-attr]


def test_a_replayed_key_answers_the_same_change_and_records_one(world: _Work) -> None:
    command = MakeFileDirectory(workspace_id="work", path="Once", idempotency_key=_key("once"))
    first = world.run(command)
    again = world.run(command)
    assert again["pending_change_id"] == first["pending_change_id"]
    assert again["replayed"] is True
    assert len(world.pending.list_changes(limit=10)) == 1


def test_staged_pending_bytes_are_capped(world: _Work) -> None:
    world.run(
        WriteFileText(
            workspace_id="work", path="a.txt", text="x" * 6000, idempotency_key=_key("c1")
        )
    )
    error = _refused(
        world,
        WriteFileText(
            workspace_id="work", path="b.txt", text="y" * 3000, idempotency_key=_key("c2")
        ),
        UnavailableError,
    )
    assert error.safe_details == (SafeDetail.QUOTA,)


def test_a_pending_change_is_readable_only_by_its_own_client(world: _Work) -> None:
    pending = world.run(
        MakeFileDirectory(workspace_id="work", path="Mine", idempotency_key=_key("p"))
    )["pending_change_id"]
    with pytest.raises(NotFoundError):
        world.files.handle(
            SimpleNamespace(file_workspace=world.rows),  # type: ignore[arg-type]
            SimpleNamespace(  # type: ignore[arg-type]
                principal=SimpleNamespace(principal_id=PRINCIPAL),
                at=world.at,
                capability_grants=None,
                transport=CaptureTransport.REMOTE_CLIENT,
                authenticated_client_id=OTHER_CLIENT,
            ),
            GetFileHistory(workspace_id="work", pending_change_id=pending),
        )
    # Unknown ids and the direct workspace answer the same `not_found`.
    for workspace_id, identifier in (
        ("work", "fwpnd_" + "0" * 32),
        ("mcp", pending),
    ):
        error = _refused(
            world,
            GetFileHistory(workspace_id=workspace_id, pending_change_id=identifier),
            NotFoundError,
        )
        assert error.safe_details == (SafeDetail.NOT_FOUND,)


def test_a_pending_change_id_is_read_alone(world: _Work) -> None:
    with pytest.raises(InvalidRequestError) as caught:
        GetFileHistory(workspace_id="work", pending_change_id="fwpnd_" + "0" * 32, path="x")
    assert caught.value.safe_details == (SafeDetail.PENDING_CHANGE_ID,)
    with pytest.raises(InvalidRequestError):
        GetFileHistory(workspace_id="work", pending_change_id="fwupl_" + "0" * 32)


def test_the_operator_list_names_each_live_change_with_its_binding(world: _Work) -> None:
    pending = world.run(
        MakeFileDirectory(workspace_id="work", path="L", idempotency_key=_key("ls"))
    )["pending_change_id"]
    (listed,) = world.operator.list_pending("work")
    assert listed["pending_change_id"] == pending
    assert listed["binding"] == world.binding(pending)
    assert listed["arguments"] == {"path": "L", "parents": False}
    with pytest.raises(ApprovalRefused):
        world.operator.list_pending("mcp")


def test_the_direct_workspace_is_unchanged(world: _Work) -> None:
    answer = world.run(
        WriteFileText(workspace_id="mcp", path="d.txt", text="direct", idempotency_key=_key("dd"))
    )
    assert "approval_required" not in answer
    assert (world.mcp_root / "d.txt").read_text() == "direct"


# ---- `clients=` (section 18.1): the workspace's readers ---------------------------------


def test_the_clients_option_parses_as_a_set_and_refuses_blanks() -> None:
    settings = load_settings(
        {
            **_DB,
            "MY_PA_FILES_WORKSPACES": (
                "work=/srv/w/work;mode=approval;state=/srv/s/work;clients=chatgpt-1|abacus-2"
            ),
        }
    )
    (work,) = settings.files_workspace_configs()
    assert work.clients == frozenset({"chatgpt-1", "abacus-2"})
    for bad in ("clients=", "clients=a||b", "clients=a b"):
        with pytest.raises(SettingsError):
            load_settings({**_DB, "MY_PA_FILES_WORKSPACES": f"w=/x;{bad}"})


def _listed_workspaces(world: _Work, client: str) -> list[str]:
    return [
        item["workspace_id"]
        for item in world.run(ListFileWorkspaces(), client=client)["workspaces"]
    ]


def test_an_unlisted_client_cannot_see_the_workspace_at_all(tmp_path: Path) -> None:
    world = _Work(tmp_path)
    work = world.spaces[1]
    restricted = ComposedFileWorkspace(
        workspace_id=work.workspace_id,
        store=work.store,
        write_mode=work.write_mode,
        max_upload_bytes=work.max_upload_bytes,
        staging=work.staging,
        pending=work.pending,
        max_pending_bytes=work.max_pending_bytes,
        allowed_clients=frozenset({CLIENT}),
    )
    world.spaces = (world.spaces[0], restricted)
    world.files = FileWorkspaceApplication(workspaces=world.spaces)
    (world.work_root / "brief.pdf").write_bytes(b"synthetic")
    assert _listed_workspaces(world, CLIENT) == ["mcp", "work"]
    assert _listed_workspaces(world, OTHER_CLIENT) == ["mcp"]
    for command in (
        ListFiles(workspace_id="work", path=""),
        StatFile(workspace_id="work", path="brief.pdf"),
        MakeFileDirectory(workspace_id="work", path="X", idempotency_key=_key("unl")),
    ):
        with pytest.raises(NotFoundError) as caught:
            world.run(command, client=OTHER_CLIENT)
        assert caught.value.safe_details == (SafeDetail.NOT_FOUND,)
    # The listed client reads, and a local (operator) caller is never restricted.
    assert world.run(StatFile(workspace_id="work", path="brief.pdf"))["name"] == "brief.pdf"
    assert world.run(StatFile(workspace_id="work", path="brief.pdf"), client=None)["size"] == 9


def test_the_byte_routes_refuse_a_ticket_of_a_client_no_longer_listed(world: _Work) -> None:
    from my_pa.application.errors import DeniedError
    from my_pa.application.file_transfer import FileTransferGate
    from my_pa.contracts.ports import FileTransferKind, FileTransferRecord, FileTransferState

    work = world.spaces[1]

    def gate(allowed: frozenset[str] | None) -> FileTransferGate:
        space = ComposedFileWorkspace(
            workspace_id="work",
            store=work.store,
            write_mode=WriteMode.APPROVAL,
            staging=work.staging,
            pending=work.pending,
            allowed_clients=allowed,
        )
        return FileTransferGate(
            service=None,  # type: ignore[arg-type]
            unit_of_work=None,  # type: ignore[arg-type]
            standing=world.standing,
            remote_writes_enabled=True,
            workspaces=(space,),
        )

    ticket = FileTransferRecord(
        transfer_id="fwdnl_" + "1" * 32,
        owner_principal_id=PRINCIPAL,
        client_ref=client_ref_of(derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT)),
        kind=FileTransferKind.DOWNLOAD,
        workspace_id="work",
        path="a.txt",
        expected_version="fv1_" + "0" * 64,
        preserved_version_id=None,
        declared_size=1,
        declared_sha256=None,
        received_bytes=0,
        state=FileTransferState.OPEN,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        finalized_at=None,
        token_digest="0" * 64,
    )
    # Download tickets need the read grant; the scripted standing holds writes only,
    # so grant it here too.
    world.standing.extra = {(Capability.FILES_DOWNLOAD_BEGIN, Purpose.FILE_WORKSPACE_READ)}
    assert gate(None)._standing_checked(FileTransferKind.DOWNLOAD, ticket, NOW).ticket is ticket
    admitted = gate(frozenset({CLIENT}))._standing_checked(FileTransferKind.DOWNLOAD, ticket, NOW)
    assert admitted.ticket is ticket
    with pytest.raises(DeniedError):
        gate(frozenset({OTHER_CLIENT}))._standing_checked(FileTransferKind.DOWNLOAD, ticket, NOW)


def test_an_expired_ticket_is_reaped_from_its_own_workspaces_staging(world: _Work) -> None:
    begun = world.run(
        BeginFileUpload(workspace_id="work", path="stale.bin", idempotency_key=_key("st1"))
    )
    staged = world.state_root / ".my-pa" / "staging" / begun["upload_id"]
    assert staged.exists()
    world.at = NOW + timedelta(hours=2)
    # A begin in the other workspace reaps the caller's due tickets everywhere.
    world.run(BeginFileUpload(workspace_id="mcp", path="new.bin", idempotency_key=_key("st2")))
    assert not staged.exists()
