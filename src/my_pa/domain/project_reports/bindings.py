"""Pure validation of the operator's project-report bindings file (rulings D8, D19).

The file is operator runtime data, never committed. It is the **whole desired
state**: a folder omitted from a later file is retired. Schema
`my_pa_project_report_bindings_v1`::

    {"schema": "my_pa_project_report_bindings_v1", "workspace_id": "<workspace>",
     "export_root": "<relative prefix>",
     "bindings": [{"folder": "<workspace-relative folder inside export_root>",
                   "project_id": "prj_<id>", "project_number": "<number>",
                   "currency": "USD",
                   "reports": [{"slug": "<saved-report slug>", "filter": "<1..500 chars>"}]}]}

`currency` defaults to `USD`; `reports` is optional. The whole file is refused
on the first failure, with one closed code and no content:

* not UTF-8, not JSON, a non-finite or fractional number, a wrong type or
  shape, a missing key, or the wrong schema or workspace: `schema_invalid`;
* a key outside the schema: `unknown_key`; a key twice in one object:
  `duplicate_json_key`;
* a folder that is absolute, holds `..`/`.`/an empty segment or a backslash,
  or is not strictly inside `export_root`: `folder_outside_export_root`;
* 2 folders that resolve to one normalized path (Unicode NFC, case-folded),
  or one inside another: `folder_duplicated`;
* one Project under 2 folders: `project_duplicated`;
* a `project_id` that is not a Project identifier: `project_not_found`;
* a currency outside `[A-Z]{3}`: `currency_invalid`;
* a filter description empty, longer than 500 characters or holding a control
  character: `filter_description_invalid`.

The database checks (the Project exists, its number agrees, the folder exists)
belong to the application service.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, NoReturn

from my_pa.domain.project_reports.model import BindingRefusal, FilterSemantics

__all__ = [
    "BINDINGS_SCHEMA",
    "DEFAULT_CURRENCY",
    "MAX_FILTER_CHARACTERS",
    "BindingEntry",
    "BindingsFile",
    "BindingsRefusedError",
    "ReportFilter",
    "change_set_sha256",
    "filter_semantics",
    "validate_bindings_file",
]

BINDINGS_SCHEMA: Final = "my_pa_project_report_bindings_v1"
DEFAULT_CURRENCY: Final = "USD"
MAX_FILTER_CHARACTERS: Final = 500
_MAX_TEXT: Final = 200

_TOP_KEYS: Final = frozenset({"schema", "workspace_id", "export_root", "bindings"})
_BINDING_REQUIRED: Final = frozenset({"folder", "project_id", "project_number"})
_BINDING_KEYS: Final = _BINDING_REQUIRED | {"currency", "reports"}
_REPORT_KEYS: Final = frozenset({"slug", "filter"})
_PROJECT_ID: Final = re.compile(r"prj_[A-Za-z0-9]{8,64}")
_CURRENCY: Final = re.compile(r"[A-Z]{3}")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_CONTROL_EXCEPT_NEWLINE: Final = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")


class BindingsRefusedError(ValueError):
    """The whole bindings file is refused; `code` names the refusal only."""

    def __init__(self, code: BindingRefusal) -> None:
        super().__init__(code.value)
        self.code = code


def _refuse(code: BindingRefusal) -> NoReturn:
    raise BindingsRefusedError(code)


@dataclass(frozen=True, slots=True)
class ReportFilter:
    slug: str
    description: str


@dataclass(frozen=True, slots=True)
class BindingEntry:
    folder: str
    project_id: str
    project_number: str
    currency: str
    reports: tuple[ReportFilter, ...]


@dataclass(frozen=True, slots=True)
class BindingsFile:
    workspace_id: str
    export_root: str
    bindings: tuple[BindingEntry, ...]


def change_set_sha256(data: bytes) -> str:
    """The revision's `change_set_sha256`: the SHA-256 of the applied file's bytes."""
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            _refuse(BindingRefusal.DUPLICATE_JSON_KEY)
        out[key] = value
    return out


def _no_number(_text: str) -> NoReturn:
    _refuse(BindingRefusal.SCHEMA_INVALID)


def _decode(data: bytes) -> object:
    if type(data) is not bytes:
        raise TypeError("a bindings file is read as bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        _refuse(BindingRefusal.SCHEMA_INVALID)
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_no_number,
            parse_int=_no_number,
            parse_constant=_no_number,
        )
    except json.JSONDecodeError:
        _refuse(BindingRefusal.SCHEMA_INVALID)


def _object(value: object, allowed: frozenset[str], required: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        _refuse(BindingRefusal.SCHEMA_INVALID)
    if set(value) - allowed:
        _refuse(BindingRefusal.UNKNOWN_KEY)
    if required - set(value):
        _refuse(BindingRefusal.SCHEMA_INVALID)
    return value


def _text(value: object, *, limit: int = _MAX_TEXT) -> str:
    if type(value) is not str or value == "" or len(value) > limit or _CONTROL.search(value):
        _refuse(BindingRefusal.SCHEMA_INVALID)
    return value


def _segments(path: str) -> list[str] | None:
    """The segments of a clean relative path, or `None` when it is not one."""
    if path.startswith("/") or "\\" in path:
        return None
    segments = path.removesuffix("/").split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    return segments


def _normal(segments: Sequence[str]) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", segment).casefold() for segment in segments)


def _reports(value: object) -> tuple[ReportFilter, ...]:
    if not isinstance(value, list):
        _refuse(BindingRefusal.SCHEMA_INVALID)
    reports: list[ReportFilter] = []
    for item in value:
        entry = _object(item, _REPORT_KEYS, _REPORT_KEYS)
        slug = _text(entry["slug"])
        if "/" in slug:
            _refuse(BindingRefusal.SCHEMA_INVALID)
        description = entry["filter"]
        if (
            type(description) is not str
            or description.strip() == ""
            or len(description) > MAX_FILTER_CHARACTERS
            or _CONTROL_EXCEPT_NEWLINE.search(description)
        ):
            _refuse(BindingRefusal.FILTER_DESCRIPTION_INVALID)
        reports.append(ReportFilter(slug, description))
    if len({report.slug for report in reports}) != len(reports):
        _refuse(BindingRefusal.SCHEMA_INVALID)
    return tuple(reports)


def _binding(value: object, root: tuple[str, ...]) -> tuple[BindingEntry, tuple[str, ...]]:
    entry = _object(value, _BINDING_KEYS, _BINDING_REQUIRED)
    folder = entry["folder"]
    if type(folder) is not str or folder == "" or _CONTROL.search(folder):
        _refuse(BindingRefusal.SCHEMA_INVALID)
    segments = _segments(folder)
    if segments is None:
        _refuse(BindingRefusal.FOLDER_OUTSIDE_EXPORT_ROOT)
    normal = _normal(segments)
    if len(normal) <= len(root) or normal[: len(root)] != root:
        _refuse(BindingRefusal.FOLDER_OUTSIDE_EXPORT_ROOT)
    project_id = entry["project_id"]
    if type(project_id) is not str or _PROJECT_ID.fullmatch(project_id) is None:
        _refuse(BindingRefusal.PROJECT_NOT_FOUND)
    project_number = _text(entry["project_number"], limit=64)
    currency = entry.get("currency", DEFAULT_CURRENCY)
    if type(currency) is not str or _CURRENCY.fullmatch(currency) is None:
        _refuse(BindingRefusal.CURRENCY_INVALID)
    reports = _reports(entry.get("reports", []))
    binding = BindingEntry("/".join(segments), project_id, project_number, currency, reports)
    return binding, normal


def validate_bindings_file(data: bytes, *, workspace_id: str) -> BindingsFile:
    """The validated desired state, or `BindingsRefusedError` with one closed code."""
    top = _object(_decode(data), _TOP_KEYS, _TOP_KEYS)
    if top["schema"] != BINDINGS_SCHEMA or top["workspace_id"] != workspace_id:
        _refuse(BindingRefusal.SCHEMA_INVALID)
    export_root = _text(top["export_root"])
    root_segments = _segments(export_root)
    if root_segments is None:
        _refuse(BindingRefusal.SCHEMA_INVALID)
    root = _normal(root_segments)
    raw = top["bindings"]
    if not isinstance(raw, list):
        _refuse(BindingRefusal.SCHEMA_INVALID)
    entries: list[BindingEntry] = []
    seen: list[tuple[str, ...]] = []
    for item in raw:
        entry, normal = _binding(item, root)
        for other in seen:
            shorter = min(len(other), len(normal))
            if other[:shorter] == normal[:shorter]:
                _refuse(BindingRefusal.FOLDER_DUPLICATED)
        seen.append(normal)
        entries.append(entry)
    if len({entry.project_id for entry in entries}) != len(entries):
        _refuse(BindingRefusal.PROJECT_DUPLICATED)
    return BindingsFile(workspace_id, "/".join(root_segments), tuple(entries))


def filter_semantics(
    declared_at: datetime | None, version_first_seen_at: datetime
) -> FilterSemantics:
    """Ruling D8 (i): a declaration holds for versions first seen at or after it."""
    if declared_at is not None and version_first_seen_at >= declared_at:
        return FilterSemantics.OPERATOR_DECLARED
    return FilterSemantics.UNKNOWN
