"""The operator's approval and apply of pending changes (files-workspace contract section 18.5).

Reached only from the operator command (`apps/cli/remote_mcp.py`
`files-pending`, `files-approve`, `files-deny`); no `files.*` name, OAuth
client grant or HTTP route reaches it. Every decision runs in one unit of work
under the workspace's advisory lock, so it serializes with the clients' own
pending writes:

- a change is approved by its id **and** its binding digest
  (`pending_binding`), so a record altered after the operator reviewed it is
  refused; only a `pending`, unexpired change of that workspace is decided,
  and it leaves `pending` exactly once (single use);
- the requesting client's standing is re-read at apply time (remote access,
  the client and the write switches, the grant for the change's operation);
- the operation runs through the **apply store** -- the workspace mounted
  read-write in the apply container only -- with every bound preimage version
  as `expected_version`, so any change since the request is refused and
  recorded, never retried; content is copied from the state directory and
  verified against the bound length and SHA-256 before it is published;
- version and trash rows are written for the requesting Principal exactly as
  a `direct` write writes them.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from my_pa.application.file_workspace import (
    ComposedFileWorkspace,
    decide_change,
    entry_shape,
    expire_change,
    pending_binding,
    pending_item,
)
from my_pa.contracts.ports import (
    FilePendingChange,
    FilePendingStatus,
    FileWorkspaceRepository,
    FileWorkspaceStore,
    FileWorkspaceUnavailableError,
    RemoteClientStandingReader,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.domain.files.workspaces import WriteMode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.creator import CreatorKind
from my_pa.domain.source.registry import issue_identifier

__all__ = ["ApprovalRefused", "FileApprovalOperator"]

_REMOTE_CLIENT_REF: Final = f"{CreatorKind.REMOTE_CLIENT.value}:"
_LIST_LIMIT: Final = 512
#: The preimage cause recorded for each content operation (the WP4 closed set).
_VERSION_CAUSE: Final[Mapping[Capability, str]] = {
    Capability.FILES_WRITE_TEXT: Capability.FILES_WRITE_TEXT.value,
    Capability.FILES_UPLOAD_FINALIZE: Capability.FILES_UPLOAD_FINALIZE.value,
    Capability.FILES_UPLOAD_BEGIN: Capability.FILES_UPLOAD_FINALIZE.value,
}


class ApprovalRefused(Exception):  # noqa: N818 - an operator refusal, not a fault
    """An approval or denial that changed nothing; `reason` is a closed token."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class _Context:
    space: ComposedFileWorkspace
    rows: FileWorkspaceRepository
    now: datetime


class FileApprovalOperator:
    """List, approve and deny one deployment's pending changes (see the module docstring)."""

    def __init__(
        self,
        *,
        workspaces: Sequence[ComposedFileWorkspace],
        unit_of_work: Callable[[], UnitOfWork],
        standing: RemoteClientStandingReader | None,
        remote_writes_enabled: bool,
        apply_stores: Mapping[str, FileWorkspaceStore] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._spaces: Final = {space.workspace_id: space for space in workspaces}
        self._apply: Final = dict(apply_stores or {})
        self._unit_of_work = unit_of_work
        self._standing = standing
        self._remote_writes_enabled: Final = remote_writes_enabled
        self._clock = clock

    def _space(self, workspace_id: str) -> ComposedFileWorkspace:
        space = self._spaces.get(workspace_id)
        if space is None or space.write_mode is not WriteMode.APPROVAL or space.pending is None:
            raise ApprovalRefused("not_an_approval_workspace")
        return space

    # ---- list -------------------------------------------------------------------------

    def list_pending(self, workspace_id: str) -> list[dict[str, Any]]:
        """The live changes, newest first, each with the binding the operator approves by.

        Expires the due ones first (under the lock). Paths are workspace-relative.
        """
        space = self._space(workspace_id)
        assert space.pending is not None  # noqa: S101 - checked by `_space`
        with self._unit_of_work() as unit_of_work:
            unit_of_work.file_workspace.lock_workspace(workspace_id)
            now = self._clock()
            listed: list[dict[str, Any]] = []
            for change in space.pending.list_changes(limit=_LIST_LIMIT):
                if change.status is FilePendingStatus.PENDING and change.expires_at <= now:
                    expire_change(space, change, now=now)
                    continue
                item = pending_item(change, now=now)
                item["client_ref"] = change.client_ref
                item["arguments"] = dict(change.arguments)
                item["binding"] = pending_binding(change)
                listed.append(item)
        return listed

    # ---- deny -------------------------------------------------------------------------

    def deny(self, workspace_id: str, pending_change_id: str) -> dict[str, Any]:
        space = self._space(workspace_id)
        with self._unit_of_work() as unit_of_work:
            unit_of_work.file_workspace.lock_workspace(workspace_id)
            now = self._clock()
            change = self._live(space, pending_change_id)
            if change.expires_at <= now:
                decided = expire_change(space, change, now=now)
            else:
                decided = decide_change(
                    space, change, status=FilePendingStatus.DENIED, now=now, decision="denied"
                )
        return pending_item(decided, now=now)

    # ---- approve ----------------------------------------------------------------------

    def approve(self, workspace_id: str, pending_change_id: str, binding: str) -> dict[str, Any]:
        """Apply one change; answers its final item (`applied`, `failed` or `expired`)."""
        space = self._space(workspace_id)
        apply = self._apply.get(workspace_id)
        if apply is None:
            raise ApprovalRefused("no_apply_root")
        if apply.root_identity != space.store.root_identity:
            raise ApprovalRefused("apply_root_mismatch")
        with self._unit_of_work() as unit_of_work:
            rows = unit_of_work.file_workspace
            rows.lock_workspace(workspace_id)
            now = self._clock()
            change = self._live(space, pending_change_id)
            if change.expires_at <= now:
                decided = expire_change(space, change, now=now)
                return pending_item(decided, now=now)
            if not hmac.compare_digest(binding.encode(), pending_binding(change).encode()):
                raise ApprovalRefused("binding_mismatch")
            if not self._standing_allows(space, change, now):
                decided = decide_change(
                    space,
                    change,
                    status=FilePendingStatus.FAILED,
                    now=now,
                    decision="approved",
                    reason="denied",
                )
                return pending_item(decided, now=now)
            applying = decide_change(
                space, change, status=FilePendingStatus.APPLYING, now=now, decision="approved"
            )
            try:
                result = self._perform(_Context(space, rows, now), apply, applying)
            except FilesRefusal as refusal:
                decided = decide_change(
                    space,
                    applying,
                    status=FilePendingStatus.FAILED,
                    now=now,
                    decision="approved",
                    reason=refusal.reason.value,
                )
            except FileWorkspaceUnavailableError:
                decided = decide_change(
                    space,
                    applying,
                    status=FilePendingStatus.FAILED,
                    now=now,
                    decision="approved",
                    reason="unavailable",
                )
            else:
                decided = decide_change(
                    space,
                    applying,
                    status=FilePendingStatus.APPLIED,
                    now=now,
                    decision="approved",
                    result=result,
                )
        return pending_item(decided, now=now)

    # ---- checks -----------------------------------------------------------------------

    @staticmethod
    def _live(space: ComposedFileWorkspace, pending_change_id: str) -> FilePendingChange:
        assert space.pending is not None  # noqa: S101 - an approval workspace has one
        change = space.pending.get(pending_change_id)
        if change is None or change.workspace_id != space.workspace_id:
            raise ApprovalRefused("not_found")
        if change.status is not FilePendingStatus.PENDING:
            raise ApprovalRefused("not_pending")
        return change

    def _standing_allows(
        self, space: ComposedFileWorkspace, change: FilePendingChange, now: datetime
    ) -> bool:
        """The requesting client may still make this write (contract section 18.5)."""
        if not change.client_ref.startswith(_REMOTE_CLIENT_REF):
            # A local caller is the operator's own Principal; it has no grant row.
            return True
        if self._standing is None or not self._remote_writes_enabled:
            return False
        standing = self._standing.standing(change.client_ref, now=now)
        capability = Capability(change.operation)
        return (
            standing is not None
            and standing.principal_id == change.owner_principal_id
            and standing.write_allowed
            and (space.allowed_clients is None or standing.oauth_client_id in space.allowed_clients)
            and (
                (capability, Purpose.FILE_WORKSPACE_AUTHORING) in standing.capability_purposes
                or (capability, None) in standing.capability_purposes
            )
        )

    # ---- the operation ----------------------------------------------------------------

    def _perform(
        self, context: _Context, apply: FileWorkspaceStore, change: FilePendingChange
    ) -> dict[str, Any]:
        arguments = change.arguments
        operation = Capability(change.operation)
        workspace_id = change.workspace_id
        if operation is Capability.FILES_MKDIR:
            entry = apply.mkdir(arguments["path"], parents=bool(arguments["parents"]))
            return entry_shape(workspace_id, entry)
        if operation is Capability.FILES_COPY:
            entry = apply.copy(
                arguments["path"], arguments["to_path"], expected_version=arguments["version"]
            )
            return entry_shape(workspace_id, entry)
        if operation in {Capability.FILES_MOVE, Capability.FILES_RENAME}:
            entry = apply.move(
                arguments["path"], arguments["to_path"], expected_version=arguments["version"]
            )
            return entry_shape(workspace_id, entry)
        if operation is Capability.FILES_TRASH:
            return self._trash(context, apply, change)
        if operation is Capability.FILES_RESTORE:
            return self._restore(context, apply, change)
        if operation in _VERSION_CAUSE:
            return self._publish(context, apply, change, _VERSION_CAUSE[operation])
        raise ApprovalRefused("unknown_operation")  # pragma: no cover - a closed set

    @staticmethod
    def _trash(
        context: _Context, apply: FileWorkspaceStore, change: FilePendingChange
    ) -> dict[str, Any]:
        item_id = issue_identifier(IdKind.FILE_TRASH_ITEM)
        moved = apply.trash(
            change.arguments["path"], item_id, expected_version=change.arguments["version"]
        )
        context.rows.record_trash(
            trash_item_id=item_id,
            principal_id=change.owner_principal_id,
            workspace_id=change.workspace_id,
            original_path=moved.entry.path,
            kind=moved.entry.kind,
            original_version=moved.entry.version,
            trashed_version=moved.trashed_version,
            size=moved.entry.size,
            trashed_at=context.now,
        )
        return {
            "trash_item_id": item_id,
            "entry": entry_shape(change.workspace_id, moved.entry),
        }

    @staticmethod
    def _restore(
        context: _Context, apply: FileWorkspaceStore, change: FilePendingChange
    ) -> dict[str, Any]:
        arguments = change.arguments
        item_id = arguments["trash_item_id"]
        item = context.rows.get_trash_item(
            item_id, principal_id=change.owner_principal_id, for_update=True
        )
        if (
            item is None
            or item.workspace_id != change.workspace_id
            or item.restored_at is not None
            or item.trashed_version != arguments["trashed_version"]
        ):
            raise FilesRefusal("trash_item_id", FilesReason.NOT_FOUND)
        target = arguments["to_path"]
        entry = apply.restore(item_id, target, trashed_version=item.trashed_version)
        if (
            context.rows.mark_restored(
                item_id,
                principal_id=change.owner_principal_id,
                restored_path=target,
                now=context.now,
            )
            is None
        ):  # pragma: no cover - the row was locked unrestored above
            raise FilesRefusal("trash_item_id", FilesReason.NOT_FOUND)
        return entry_shape(change.workspace_id, entry)

    @staticmethod
    def _publish(
        context: _Context, apply: FileWorkspaceStore, change: FilePendingChange, cause: str
    ) -> dict[str, Any]:
        """Copy the staged content into the apply mount, verify it, publish it."""
        staging = context.space.staging
        size, sha256, staged_id = change.size, change.sha256, change.staged_upload_id
        if staging is None or size is None or sha256 is None or staged_id is None:
            raise FilesRefusal("pending_change_id", FilesReason.NOT_FOUND)
        path: str = change.arguments["path"]
        expected: str | None = change.arguments["expected_version"]
        apply.ensure_free_space(size)
        upload_id = issue_identifier(IdKind.FILE_UPLOAD)
        apply.begin_upload(upload_id)
        try:
            reader = staging.open_staged_upload(staged_id)
            try:
                apply.append_upload(upload_id, 0, reader.read_range(0, reader.size), limit=size)
            finally:
                reader.close()
            length, digest, staged_version = apply.upload_digest(upload_id)
            if length != size or not hmac.compare_digest(digest, sha256):
                raise FilesRefusal("sha256", FilesReason.DIGEST_MISMATCH)
            if expected is None:
                published = apply.publish_upload(
                    upload_id, path, length=length, sha256=digest, staged_version=staged_version
                )
            else:
                current = apply.stat(path)
                if current.kind is not EntryKind.FILE:
                    raise FilesRefusal("path", FilesReason.UNSUPPORTED_ENTRY)
                if current.version != expected:
                    raise FilesRefusal("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
                version_id = issue_identifier(IdKind.FILE_VERSION)
                published = apply.publish_upload(
                    upload_id,
                    path,
                    length=length,
                    sha256=digest,
                    expected_version=expected,
                    preimage_version_id=version_id,
                    staged_version=staged_version,
                )
                context.rows.record_version(
                    version_id=version_id,
                    principal_id=change.owner_principal_id,
                    workspace_id=change.workspace_id,
                    path=current.path,
                    version=current.version,
                    size=0 if current.size is None else current.size,
                    sha256=None,
                    cause=cause,
                    captured_at=context.now,
                )
            return {
                "entry": entry_shape(change.workspace_id, published.entry),
                "preimage_version_id": published.preimage_version_id,
            }
        finally:
            # Published bytes were renamed out of the apply staging; anything
            # left belongs to a refused apply and is never needed.
            with suppress(FilesRefusal, FileWorkspaceUnavailableError):
                apply.discard_upload(upload_id)
