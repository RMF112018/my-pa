"""The configured workspaces and their write modes (files-workspace contract section 18.1).

Pure parsing of `MY_PA_FILES_WORKSPACES` and `MY_PA_FILES_APPLY_ROOTS`; nothing
here touches the filesystem. A refusal is a `WorkspaceConfigError` whose
message names the rule, never a configured path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

__all__ = [
    "DEFAULT_MAX_PENDING_BYTES",
    "MAX_WORKSPACES",
    "WorkspaceConfig",
    "WorkspaceConfigError",
    "WriteMode",
    "parse_apply_roots",
    "parse_workspaces",
]

#: Section 18.1: at most this many configured workspaces.
MAX_WORKSPACES: Final = 8
#: Section 18.1: an `approval` workspace's default cap on staged pending bytes (1 GiB).
DEFAULT_MAX_PENDING_BYTES: Final = 1 << 30
#: Section 2: the alias pattern the persistence rows enforce.
_ALIAS: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_OPTIONS: Final = frozenset(
    {"mode", "state", "max_upload_bytes", "disk_reserve_bytes", "max_pending_bytes"}
)


class WorkspaceConfigError(ValueError):
    """A malformed workspace list; the message names the rule, never a value."""


class WriteMode(StrEnum):
    """Section 18.2: how a workspace's writes are applied."""

    DIRECT = "direct"
    APPROVAL = "approval"
    READ_ONLY = "read_only"

    @property
    def requires_read_only_mount(self) -> bool:
        """Whether the serving processes must see the root through a read-only mount."""
        return self is not WriteMode.DIRECT


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """One configured workspace (section 18.1)."""

    workspace_id: str
    root: str
    write_mode: WriteMode
    max_upload_bytes: int
    disk_reserve_bytes: int
    state_root: str | None = None
    max_pending_bytes: int = DEFAULT_MAX_PENDING_BYTES


def _absolute(text: str, what: str) -> str:
    candidate = text.strip()
    path = PurePosixPath(candidate)
    if not candidate or not path.is_absolute() or ".." in path.parts:
        raise WorkspaceConfigError(f"a workspace {what} must be an absolute path without '..'")
    return str(path)


def _overlaps(one: str, other: str) -> bool:
    first, second = PurePosixPath(one), PurePosixPath(other)
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _positive(text: str, name: str, *, minimum: int) -> int:
    if not text.isdecimal():
        raise WorkspaceConfigError(f"workspace option {name} must be a decimal integer")
    value = int(text)
    if value < minimum:
        raise WorkspaceConfigError(f"workspace option {name} is below its minimum")
    return value


def parse_workspaces(
    text: str, *, default_max_upload_bytes: int, default_disk_reserve_bytes: int
) -> tuple[WorkspaceConfig, ...]:
    """The workspaces `MY_PA_FILES_WORKSPACES` names, in order (section 18.1)."""
    items = [item.strip() for item in text.split(",") if item.strip()]
    if not items:
        return ()
    if len(items) > MAX_WORKSPACES:
        raise WorkspaceConfigError("at most 8 file workspaces may be configured")
    configs: list[WorkspaceConfig] = []
    for item in items:
        head, *option_texts = item.split(";")
        alias, separator, root_text = head.partition("=")
        alias = alias.strip()
        if not separator or not _ALIAS.fullmatch(alias):
            raise WorkspaceConfigError("each workspace must be alias=root with a lower-case alias")
        options: dict[str, str] = {}
        for option_text in option_texts:
            name, equals, value = option_text.partition("=")
            name = name.strip()
            if not equals or name not in _OPTIONS or name in options:
                raise WorkspaceConfigError("a workspace option is unknown, repeated or malformed")
            options[name] = value.strip()
        try:
            mode = WriteMode(options.get("mode", WriteMode.DIRECT.value))
        except ValueError:
            raise WorkspaceConfigError(
                "a workspace mode must be direct, approval or read_only"
            ) from None
        state = options.get("state")
        if (mode is WriteMode.APPROVAL) != (state is not None):
            raise WorkspaceConfigError(
                "a state directory is required for, and only for, an approval workspace"
            )
        if "max_pending_bytes" in options and mode is not WriteMode.APPROVAL:
            raise WorkspaceConfigError("max_pending_bytes applies only to an approval workspace")
        configs.append(
            WorkspaceConfig(
                workspace_id=alias,
                root=_absolute(root_text, "root"),
                write_mode=mode,
                max_upload_bytes=_positive(
                    options.get("max_upload_bytes", str(default_max_upload_bytes)),
                    "max_upload_bytes",
                    minimum=1,
                ),
                disk_reserve_bytes=_positive(
                    options.get("disk_reserve_bytes", str(default_disk_reserve_bytes)),
                    "disk_reserve_bytes",
                    minimum=0,
                ),
                state_root=None if state is None else _absolute(state, "state directory"),
                max_pending_bytes=_positive(
                    options.get("max_pending_bytes", str(DEFAULT_MAX_PENDING_BYTES)),
                    "max_pending_bytes",
                    minimum=1,
                ),
            )
        )
    aliases = [config.workspace_id for config in configs]
    if len(set(aliases)) != len(aliases):
        raise WorkspaceConfigError("workspace aliases must be unique")
    trees = [config.root for config in configs] + [
        config.state_root for config in configs if config.state_root is not None
    ]
    for index, tree in enumerate(trees):
        if any(_overlaps(tree, other) for other in trees[index + 1 :]):
            raise WorkspaceConfigError("no two workspace roots or state directories may overlap")
    return tuple(configs)


def parse_apply_roots(text: str) -> dict[str, str]:
    """`MY_PA_FILES_APPLY_ROOTS`: alias to the apply mount path (section 18.5)."""
    roots: dict[str, str] = {}
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        alias, separator, path = item.partition("=")
        alias = alias.strip()
        if not separator or not _ALIAS.fullmatch(alias) or alias in roots:
            raise WorkspaceConfigError("each apply root must be a unique alias=path")
        roots[alias] = _absolute(path, "apply root")
    return roots
