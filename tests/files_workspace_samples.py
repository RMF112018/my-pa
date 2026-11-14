"""Synthetic sample payloads for the 17 files workspace capabilities (WP5).

The transport-parity, negative-evidence and policy suites keep one valid
payload per handler-backed capability. Every path, id and token here is
synthetic and names nothing on any disk; each payload passes its command's own
validation (files-workspace contract sections 3 and 6), so a transport reaches
authorization and the plane's composition check.
"""

from __future__ import annotations

from typing import Any, Final

from my_pa.application.commands import (
    AbortFileUpload,
    BeginFileDownload,
    BeginFileUpload,
    CopyFile,
    FinalizeFileUpload,
    GetFileHistory,
    ListFiles,
    ListFileWorkspaces,
    MakeFileDirectory,
    MoveFile,
    PreviewFile,
    RenameFile,
    RestoreFile,
    SearchFiles,
    StatFile,
    TrashFile,
    WriteFileText,
)
from my_pa.domain.identity.operation import Capability

__all__ = [
    "FILES_WORKSPACE_CAPABILITIES",
    "FILES_WORKSPACE_COMMAND_TYPES",
    "files_commands",
    "files_payloads",
]

#: The command class of each of the 17 plane capabilities.
FILES_WORKSPACE_COMMAND_TYPES: Final[dict[Capability, type[Any]]] = {
    Capability.FILES_WORKSPACES_LIST: ListFileWorkspaces,
    Capability.FILES_LIST: ListFiles,
    Capability.FILES_STAT: StatFile,
    Capability.FILES_SEARCH: SearchFiles,
    Capability.FILES_PREVIEW: PreviewFile,
    Capability.FILES_HISTORY: GetFileHistory,
    Capability.FILES_DOWNLOAD_BEGIN: BeginFileDownload,
    Capability.FILES_MKDIR: MakeFileDirectory,
    Capability.FILES_COPY: CopyFile,
    Capability.FILES_UPLOAD_BEGIN: BeginFileUpload,
    Capability.FILES_UPLOAD_ABORT: AbortFileUpload,
    Capability.FILES_RENAME: RenameFile,
    Capability.FILES_MOVE: MoveFile,
    Capability.FILES_TRASH: TrashFile,
    Capability.FILES_RESTORE: RestoreFile,
    Capability.FILES_UPLOAD_FINALIZE: FinalizeFileUpload,
    Capability.FILES_WRITE_TEXT: WriteFileText,
}
FILES_WORKSPACE_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    FILES_WORKSPACE_COMMAND_TYPES
)

_VERSION: Final = "fv1_" + "a" * 64
_SHA256: Final = "b" * 64


def files_payloads(tag: str) -> dict[Capability, dict[str, Any]]:
    """One valid payload per plane capability; `tag` (alphanumeric) marks the suite."""
    workspace = "mcp"
    upload = f"fwupl_{tag}file0001"
    trash = f"fwtrs_{tag}file0001"
    version = f"fwver_{tag}file0001"

    def key(name: str) -> str:
        return f"{tag}-{name}-0001"

    return {
        Capability.FILES_WORKSPACES_LIST: {},
        Capability.FILES_LIST: {"workspace_id": workspace, "path": ""},
        Capability.FILES_STAT: {"workspace_id": workspace, "path": "Synthetic/a.txt"},
        Capability.FILES_SEARCH: {"workspace_id": workspace, "path": "", "query": "synthetic"},
        Capability.FILES_PREVIEW: {"workspace_id": workspace, "path": "Synthetic/a.txt"},
        Capability.FILES_HISTORY: {"workspace_id": workspace},
        Capability.FILES_DOWNLOAD_BEGIN: {"workspace_id": workspace, "version_id": version},
        Capability.FILES_MKDIR: {
            "workspace_id": workspace,
            "path": "Synthetic",
            "idempotency_key": key("mkdir"),
        },
        Capability.FILES_COPY: {
            "workspace_id": workspace,
            "path": "Synthetic/a.txt",
            "to_path": "Synthetic/b.txt",
            "idempotency_key": key("copy"),
        },
        Capability.FILES_UPLOAD_BEGIN: {
            "workspace_id": workspace,
            "path": "Synthetic/c.bin",
            "size": 3,
            "sha256": _SHA256,
            "idempotency_key": key("upload-begin"),
        },
        Capability.FILES_UPLOAD_ABORT: {
            "workspace_id": workspace,
            "upload_id": upload,
            "idempotency_key": key("upload-abort"),
        },
        Capability.FILES_RENAME: {
            "workspace_id": workspace,
            "path": "Synthetic/a.txt",
            "new_name": "renamed.txt",
            "idempotency_key": key("rename"),
        },
        Capability.FILES_MOVE: {
            "workspace_id": workspace,
            "path": "Synthetic/a.txt",
            "to_path": "Elsewhere/a.txt",
            "expected_version": _VERSION,
            "idempotency_key": key("move"),
        },
        Capability.FILES_TRASH: {
            "workspace_id": workspace,
            "path": "Synthetic/a.txt",
            "idempotency_key": key("trash"),
        },
        Capability.FILES_RESTORE: {
            "workspace_id": workspace,
            "trash_item_id": trash,
            "idempotency_key": key("restore"),
        },
        Capability.FILES_UPLOAD_FINALIZE: {
            "workspace_id": workspace,
            "upload_id": upload,
            "length": 3,
            "sha256": _SHA256,
            "idempotency_key": key("upload-finalize"),
        },
        Capability.FILES_WRITE_TEXT: {
            "workspace_id": workspace,
            "path": "Synthetic/note.md",
            "text": "Synthetic note text.",
            "idempotency_key": key("write-text"),
        },
    }


def files_commands(tag: str) -> dict[Capability, Any]:
    """The same samples as built commands."""
    return {
        capability: FILES_WORKSPACE_COMMAND_TYPES[capability](**payload)
        for capability, payload in files_payloads(tag).items()
    }
