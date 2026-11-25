"""Project reports: pure validation of the bindings file (plan 6.4; rulings D8, D19).

Every pure refusal, each on an otherwise valid synthetic file. Synthetic folders,
project numbers and `prj_` identifiers only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from my_pa.domain.project_reports.bindings import (
    BINDINGS_SCHEMA,
    DEFAULT_CURRENCY,
    MAX_FILTER_CHARACTERS,
    BindingEntry,
    BindingsRefusedError,
    ReportFilter,
    change_set_sha256,
    filter_semantics,
    validate_bindings_file,
)
from my_pa.domain.project_reports.model import BindingRefusal, FilterSemantics

WORKSPACE = "wsx"
PROJECT_A = "prj_SYNTHaaaa0001"
PROJECT_B = "prj_SYNTHbbbb0002"


def _file(**overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": BINDINGS_SCHEMA,
        "workspace_id": WORKSPACE,
        "export_root": "exports",
        "bindings": [
            {"folder": "exports/alpha/out", "project_id": PROJECT_A, "project_number": "T-001"},
            {
                "folder": "exports/beta/out",
                "project_id": PROJECT_B,
                "project_number": "T-002",
                "currency": "EUR",
                "reports": [{"slug": "open-items", "filter": "Open items only."}],
            },
        ],
    }
    base.update(overrides)
    return base


def _bytes(document: object) -> bytes:
    return json.dumps(document).encode("utf-8")


def _refusal(data: bytes) -> BindingRefusal:
    with pytest.raises(BindingsRefusedError) as refused:
        validate_bindings_file(data, workspace_id=WORKSPACE)
    return refused.value.code


def _binding(**overrides: object) -> bytes:
    entry: dict[str, object] = {
        "folder": "exports/alpha/out",
        "project_id": PROJECT_A,
        "project_number": "T-001",
    }
    entry.update(overrides)
    return _bytes(_file(bindings=[entry]))


def test_a_valid_file_is_the_whole_desired_state() -> None:
    result = validate_bindings_file(_bytes(_file()), workspace_id=WORKSPACE)
    assert result.workspace_id == WORKSPACE and result.export_root == "exports"
    assert result.bindings == (
        BindingEntry("exports/alpha/out", PROJECT_A, "T-001", DEFAULT_CURRENCY, ()),
        BindingEntry(
            "exports/beta/out",
            PROJECT_B,
            "T-002",
            "EUR",
            (ReportFilter("open-items", "Open items only."),),
        ),
    )


def test_an_empty_bindings_list_retires_everything() -> None:
    result = validate_bindings_file(_bytes(_file(bindings=[])), workspace_id=WORKSPACE)
    assert result.bindings == ()


def test_a_trailing_slash_is_normalized_away() -> None:
    result = validate_bindings_file(_binding(folder="exports/alpha/out/"), workspace_id=WORKSPACE)
    assert result.bindings[0].folder == "exports/alpha/out"


@pytest.mark.parametrize(
    "data",
    [
        b"\xff\xfe",
        b"not json",
        b"[]",
        b'{"schema": 1}',
        b"",
    ],
)
def test_unreadable_shapes_are_schema_invalid(data: bytes) -> None:
    assert _refusal(data) is BindingRefusal.SCHEMA_INVALID


@pytest.mark.parametrize(
    "document",
    [
        _file(schema="my_pa_project_report_bindings_v2"),
        _file(workspace_id="other"),
        _file(export_root=""),
        _file(export_root="/abs"),
        _file(export_root="a/../b"),
        _file(bindings={}),
        {k: v for k, v in _file().items() if k != "export_root"},
    ],
)
def test_top_level_errors_are_schema_invalid(document: object) -> None:
    assert _refusal(_bytes(document)) is BindingRefusal.SCHEMA_INVALID


@pytest.mark.parametrize("number", ["1", "1.5", "NaN", "Infinity", "-Infinity"])
def test_any_json_number_is_refused(number: str) -> None:
    data = _bytes(_file()).replace(b'"T-001"', number.encode())
    assert _refusal(data) is BindingRefusal.SCHEMA_INVALID


def test_an_unknown_key_is_refused_at_every_level() -> None:
    assert _refusal(_bytes(_file(extra=True))) is BindingRefusal.UNKNOWN_KEY
    assert _refusal(_binding(note="x")) is BindingRefusal.UNKNOWN_KEY
    report = {"slug": "s", "filter": "f", "owner": "x"}
    assert _refusal(_binding(reports=[report])) is BindingRefusal.UNKNOWN_KEY


def test_a_duplicate_json_key_is_refused() -> None:
    data = _bytes(_file()).replace(
        b'"export_root": "exports"', b'"export_root": "exports", "export_root": "exports"'
    )
    assert _refusal(data) is BindingRefusal.DUPLICATE_JSON_KEY
    nested = _binding().replace(
        b'"project_number": "T-001"', b'"project_number": "T-001", "project_number": "T-009"'
    )
    assert _refusal(nested) is BindingRefusal.DUPLICATE_JSON_KEY


@pytest.mark.parametrize(
    "folder",
    [
        "/exports/alpha",
        "exports/../alpha",
        "exports/./alpha",
        "exports//alpha",
        "exports\\alpha",
        "exports",
        "exports/",
        "other/alpha",
        "exportsx/alpha",
    ],
)
def test_a_folder_outside_the_export_root_is_refused(folder: str) -> None:
    assert _refusal(_binding(folder=folder)) is BindingRefusal.FOLDER_OUTSIDE_EXPORT_ROOT


def test_a_folder_with_a_control_character_is_schema_invalid() -> None:
    assert _refusal(_binding(folder="exports/al\npha")) is BindingRefusal.SCHEMA_INVALID


@pytest.mark.parametrize(
    "second",
    [
        "exports/alpha/out",  # the same folder twice
        "exports/ALPHA/out",  # case-folded collision
        "exports/alpha/out/",  # the same after normalization
    ],
)
def test_a_folder_mapped_twice_is_refused(second: str) -> None:
    document = _file()
    document["bindings"][1]["folder"] = second
    assert _refusal(_bytes(document)) is BindingRefusal.FOLDER_DUPLICATED


@pytest.mark.parametrize(
    "second",
    [
        "exports/alpha/out/deeper",  # nested inside the first
        "exports/alpha",  # the first nested inside it
        "exports/ALPHA/out/Deeper",  # nested after case folding
        "exports/alpha/out/deeper/",  # nested after normalization
    ],
)
def test_a_folder_inside_another_is_nested(second: str) -> None:
    document = _file()
    document["bindings"][1]["folder"] = second
    assert _refusal(_bytes(document)) is BindingRefusal.FOLDER_NESTED


def test_a_sibling_sharing_a_name_prefix_is_not_nested() -> None:
    document = _file()
    document["bindings"][1]["folder"] = "exports/alpha/outer"
    result = validate_bindings_file(_bytes(document), workspace_id=WORKSPACE)
    assert [entry.folder for entry in result.bindings] == [
        "exports/alpha/out",
        "exports/alpha/outer",
    ]


def test_unicode_normalization_collides() -> None:
    document = _file()
    document["bindings"][0]["folder"] = "exports/café"
    document["bindings"][1]["folder"] = "exports/café"
    assert _refusal(_bytes(document)) is BindingRefusal.FOLDER_DUPLICATED


def test_a_project_under_two_folders_is_refused() -> None:
    document = _file()
    document["bindings"][1]["project_id"] = PROJECT_A
    assert _refusal(_bytes(document)) is BindingRefusal.PROJECT_DUPLICATED


@pytest.mark.parametrize(
    "project_id", ["prj_short", "ent_SYNTHaaaa0001", "prj_SYNTH-aaaa01", None, ["x"]]
)
def test_a_non_project_identifier_is_project_not_found(project_id: object) -> None:
    assert _refusal(_binding(project_id=project_id)) is BindingRefusal.PROJECT_NOT_FOUND


@pytest.mark.parametrize("number", ["", "x" * 65, "T\t1"])
def test_a_bad_project_number_is_schema_invalid(number: str) -> None:
    assert _refusal(_binding(project_number=number)) is BindingRefusal.SCHEMA_INVALID


@pytest.mark.parametrize("currency", ["usd", "US", "USDX", "", None])
def test_a_bad_currency_is_refused(currency: object) -> None:
    assert _refusal(_binding(currency=currency)) is BindingRefusal.CURRENCY_INVALID


@pytest.mark.parametrize(
    "description",
    ["", "   ", "x" * (MAX_FILTER_CHARACTERS + 1), "bad\x00char", "tab\there", None],
)
def test_a_bad_filter_description_is_refused(description: object) -> None:
    reports = [{"slug": "open-items", "filter": description}]
    assert _refusal(_binding(reports=reports)) is BindingRefusal.FILTER_DESCRIPTION_INVALID


def test_a_filter_description_at_the_limit_with_newlines_is_accepted() -> None:
    text = "line one\n" + "x" * (MAX_FILTER_CHARACTERS - 9)
    result = validate_bindings_file(
        _binding(reports=[{"slug": "s", "filter": text}]), workspace_id=WORKSPACE
    )
    assert result.bindings[0].reports == (ReportFilter("s", text),)


@pytest.mark.parametrize(
    "reports",
    [
        {},
        [{"slug": "s"}],
        [{"slug": "", "filter": "f"}],
        [{"slug": "a/b", "filter": "f"}],
        [{"slug": "s", "filter": "f"}, {"slug": "s", "filter": "g"}],
    ],
)
def test_a_bad_report_list_is_schema_invalid(reports: object) -> None:
    assert _refusal(_binding(reports=reports)) is BindingRefusal.SCHEMA_INVALID


def test_a_missing_binding_key_is_schema_invalid() -> None:
    data = _bytes(_file(bindings=[{"folder": "exports/a", "project_id": PROJECT_A}]))
    assert _refusal(data) is BindingRefusal.SCHEMA_INVALID


def test_refusals_carry_the_code_only() -> None:
    with pytest.raises(BindingsRefusedError) as refused:
        validate_bindings_file(_binding(folder="/secret/path"), workspace_id=WORKSPACE)
    assert str(refused.value) == "folder_outside_export_root"


def test_the_change_set_digest_is_of_the_file_bytes() -> None:
    data = _bytes(_file())
    assert change_set_sha256(data) == hashlib.sha256(data).hexdigest()


def test_a_filter_declaration_holds_for_versions_first_seen_at_or_after_it() -> None:
    declared = datetime(2030, 1, 2, tzinfo=UTC)
    assert filter_semantics(None, declared) is FilterSemantics.UNKNOWN
    assert filter_semantics(declared, declared) is FilterSemantics.OPERATOR_DECLARED
    later = datetime(2030, 1, 3, tzinfo=UTC)
    assert filter_semantics(declared, later) is FilterSemantics.OPERATOR_DECLARED
    earlier = datetime(2030, 1, 1, tzinfo=UTC)
    assert filter_semantics(declared, earlier) is FilterSemantics.UNKNOWN


def test_a_binding_is_active_or_retired_only() -> None:
    """WP3P-S3: the binding state the revision freezes (`active`, `retired`)."""
    from my_pa.domain.project_reports.model import BindingState

    assert [state.value for state in BindingState] == ["active", "retired"]
