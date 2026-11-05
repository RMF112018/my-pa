"""General report plane: frozen bounds, validators and the lifecycle rule (WP01)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import timedelta
from enum import IntEnum, StrEnum
from typing import Any, Final

import pytest

from my_pa.domain.common.identifiers import IdKind, make_identifier, parse_identifier
from my_pa.domain.reports import vocabulary as v
from my_pa.domain.reports.errors import (
    ReportDomainError,
    ReportLifecycleRefusal,
    ReportValidationError,
)
from my_pa.domain.reports.lifecycle import LifecycleDecision, decide_lifecycle_transition
from my_pa.domain.reports.values import (
    ReportAssociation,
    validate_associations,
    validate_change_reason,
    validate_metadata,
    validate_relation,
    validate_summary,
    validate_tags,
    validate_title,
    validate_topics,
    validate_type_token,
)
from my_pa.domain.reports.vocabulary import (
    AssociationTargetKind as K,
)
from my_pa.domain.reports.vocabulary import (
    AssociationVerification as Ver,
)
from my_pa.domain.reports.vocabulary import (
    LifecycleOperation as Op,
)
from my_pa.domain.reports.vocabulary import (
    LifecycleState as S,
)
from my_pa.domain.reports.vocabulary import ReceiptOutcome

_Terms = Callable[[object], tuple[str, ...]]

SECRET = "zqxSECRETzqx"  # noqa: S105 - a marker, not a credential


def _refused(fn: Callable[[Any], object], value: object, code: str) -> ReportValidationError:
    with pytest.raises(ReportValidationError) as info:
        fn(value)
    assert info.value.code == code
    return info.value


# ---- identifiers -------------------------------------------------------------

REPORT_KINDS = {
    IdKind.REPORT: "grpt",
    IdKind.REPORT_VERSION: "grver",
    IdKind.REPORT_CONTENT: "grcnt",
    IdKind.REPORT_ASSOCIATION: "grasc",
    IdKind.REPORT_LIFECYCLE_EVENT: "grlev",
    IdKind.REPORT_RECEIPT: "grrc",
    IdKind.REPORT_TRANSFER_SESSION: "grxfr",
}


@pytest.mark.parametrize(("kind", "prefix"), REPORT_KINDS.items())
def test_report_kinds_are_the_contract_prefixes_and_collide_with_none(
    kind: IdKind, prefix: str
) -> None:
    assert kind.value == prefix
    others = [other.value for other in IdKind if other is not kind]
    assert not any(o.startswith(prefix) or prefix.startswith(o) for o in others)
    identifier = make_identifier(kind, "abc123def456")
    assert parse_identifier(identifier) == (kind, "abc123def456")


def test_report_kinds_are_distinct_from_the_intelligence_plane() -> None:
    assert set(REPORT_KINDS.values()).isdisjoint({"rpt", "rrc", "rrun", "micr"})


# ---- frozen constants (the DB literals) --------------------------------------


def test_frozen_bounds() -> None:
    assert v.TYPE_TOKEN_PATTERN.pattern == r"\A[a-z][a-z0-9_]{0,63}\Z"
    assert v.RESERVED_TYPE_PREFIXES == ("my_pa_", "system_", "internal_")
    assert v.MAX_TITLE_CHARACTERS == 256
    assert v.MAX_SUMMARY_CHARACTERS == 2000
    assert v.MAX_REASON_CHARACTERS == 500
    assert (v.MAX_TERMS, v.MAX_TERM_CHARACTERS) == (24, 64)
    assert v.MAX_METADATA_KEYS == 32
    assert v.MAX_METADATA_DEPTH == 4
    assert v.MAX_METADATA_BYTES == 16384
    assert v.MAX_METADATA_KEY_CHARACTERS == 64
    assert (v.MIN_METADATA_FLOAT_MAGNITUDE, v.MAX_METADATA_FLOAT_MAGNITUDE) == (1e-4, 1e16)
    assert v.RESERVED_METADATA_KEY_PREFIXES == ("_", "my_pa", "system")
    assert v.MAX_DECODED_CONTENT_BYTES == v.MAX_ORIGINAL_CONTENT_BYTES == 16 * 1024 * 1024
    assert v.MANIFEST_SCHEMA == "report_version_manifest_v1"
    assert v.MAX_MANIFEST_BYTES == 65536
    assert v.MAX_ASSOCIATIONS_PER_VERSION == 64
    assert v.MAX_ASSOCIATION_REF_CHARACTERS == 512
    assert v.MAX_SEARCH_TEXT_CHARACTERS == 65536
    assert v.TRANSFER_CHUNK_MAX_BYTES == 262144
    assert timedelta(hours=24) == v.TRANSFER_MAX_TTL


def test_enumeration_literals() -> None:
    def values(enum: type[StrEnum]) -> list[str]:
        return [member.value for member in enum]

    assert values(v.ContentFormat) == ["markdown", "text", "json", "mixed"]
    assert values(v.ContentEncoding) == ["identity", "gzip+base64"]
    assert values(v.StorageKind) == ["inline", "managed_blob"]
    assert values(v.LifecycleState) == ["active", "archived", "trashed"]
    assert values(v.LifecycleOperation) == ["archive", "delete", "restore"]
    assert values(v.ChangeKind) == ["initial", "content", "metadata"]
    assert values(v.ReceiptOperation) == ["publish", "update", "archive", "delete", "restore"]
    assert values(v.ReceiptOutcome) == ["applied", "no_op"]
    assert values(v.AssociationTargetKind) == [
        "project",
        "entity",
        "standalone_report",
        "intelligence_report",
        "external_source",
    ]
    assert values(v.AssociationVerification) == ["asserted", "verified"]
    assert values(v.TransferState) == ["open", "finalized", "consumed", "aborted", "expired"]


# ---- type token and relation -------------------------------------------------


@pytest.mark.parametrize("token", ["a", "weekly_report", "r2d2", "a" + "b" * 63, "a_"])
def test_type_token_accepts(token: str) -> None:
    assert validate_type_token(token) == token
    assert validate_relation(token) == token


@pytest.mark.parametrize(
    "token",
    ["", "A", "1a", "_a", "a-b", "a b", "a" + "b" * 64, "\u00e4", "a\n", "weekly.report"],
)
def test_type_token_rejects_pattern(token: str) -> None:
    _refused(validate_type_token, token, "pattern")
    _refused(validate_relation, token, "pattern")


@pytest.mark.parametrize("token", ["my_pa_x", "system_x", "internal_x", "my_pa_", "system_"])
def test_type_token_rejects_reserved_prefix(token: str) -> None:
    _refused(validate_type_token, token, "reserved")


@pytest.mark.parametrize("token", ["my_pax", "systems", "internal", "system", "my_pa"])
def test_type_token_near_reserved_is_accepted(token: str) -> None:
    assert validate_type_token(token) == token


def test_relation_has_no_reserved_namespace() -> None:
    assert validate_relation("system_of_record") == "system_of_record"


@pytest.mark.parametrize("value", [None, 1, b"abc", ["a"]])
def test_type_token_rejects_non_string(value: object) -> None:
    _refused(validate_type_token, value, "type")


# ---- title -------------------------------------------------------------------


def test_title_bounds_at_the_edge() -> None:
    assert validate_title("x") == "x"
    assert validate_title("x" * 256) == "x" * 256
    _refused(validate_title, "x" * 257, "too_long")
    _refused(validate_title, "", "too_short")


def test_title_is_nfc_and_measured_after_normalization() -> None:
    decomposed = "e\u0301"  # two code points, one after NFC
    assert validate_title(decomposed) == "\u00e9"
    assert validate_title(decomposed * 256) == "\u00e9" * 256
    _refused(validate_title, decomposed * 257, "too_long")


@pytest.mark.parametrize("char", ["\n", "\t", "\r", "\x00", "\x1f", "\x7f", "\x80", "\x9f"])
def test_title_refuses_control_characters(char: str) -> None:
    _refused(validate_title, f"a{char}b", "control_character")


@pytest.mark.parametrize("value", [" ", "   ", "\u3000", "\u00a0"])
def test_title_refuses_all_whitespace(value: str) -> None:
    _refused(validate_title, value, "blank")


def test_title_keeps_surrounding_whitespace() -> None:
    assert validate_title(" a ") == " a "


def test_title_refuses_lone_surrogate_and_non_string() -> None:
    _refused(validate_title, "a\ud800", "malformed")
    _refused(validate_title, None, "type")


# ---- summary -----------------------------------------------------------------


def test_summary_bounds_at_the_edge() -> None:
    assert validate_summary(None) is None
    assert validate_summary("s") == "s"
    assert validate_summary("s" * 2000) == "s" * 2000
    _refused(validate_summary, "s" * 2001, "too_long")
    _refused(validate_summary, "", "too_short")


def test_summary_admits_newline_only() -> None:
    assert validate_summary("a\nb") == "a\nb"
    for char in ("\t", "\r", "\x00", "\x85"):
        _refused(validate_summary, f"a{char}b", "control_character")


def test_summary_is_nfc() -> None:
    assert validate_summary("e\u0301") == "\u00e9"
    _refused(validate_summary, "e\u0301" * 2001, "too_long")


# ---- change / lifecycle reason ----------------------------------------------


def test_reason_bounds_at_the_edge() -> None:
    assert validate_change_reason(None) is None
    assert validate_change_reason("r" * 500) == "r" * 500
    _refused(validate_change_reason, "r" * 501, "too_long")
    _refused(validate_change_reason, "", "too_short")
    assert validate_change_reason("a\nb") == "a\nb"
    _refused(validate_change_reason, "a\tb", "control_character")


def test_reason_field_name_is_the_callers() -> None:
    with pytest.raises(ReportValidationError) as info:
        validate_change_reason("", field="lifecycle_reason")
    assert info.value.field == "lifecycle_reason"


# ---- topics and tags ---------------------------------------------------------


@pytest.mark.parametrize("validate", [validate_topics, validate_tags])
def test_terms_bounds_at_the_edge(validate: _Terms) -> None:
    assert validate(()) == ()
    full = [f"t{i}" for i in range(24)]
    assert validate(full) == tuple(full)
    _refused(validate, [*full, "t24"], "too_many")
    assert validate(["x" * 64]) == ("x" * 64,)
    _refused(validate, ["x" * 65], "too_long")
    _refused(validate, [""], "too_short")


@pytest.mark.parametrize("validate", [validate_topics, validate_tags])
def test_terms_keep_order_and_refuse_casefold_duplicates(
    validate: Callable[[object], tuple[str, ...]],
) -> None:
    assert validate(["Beta", "alpha"]) == ("Beta", "alpha")
    _refused(validate, ["Alpha", "alpha"], "duplicate")
    _refused(validate, ["STRASSE", "stra\u00dfe"], "duplicate")
    # NFC and NFD spellings of one term are one term.
    _refused(validate, ["\u00e9t\u00e9", "e\u0301te\u0301"], "duplicate")


@pytest.mark.parametrize("validate", [validate_topics, validate_tags])
def test_terms_normalize_and_refuse_controls_and_shapes(
    validate: Callable[[object], tuple[str, ...]],
) -> None:
    assert validate(["e\u0301"]) == ("\u00e9",)
    _refused(validate, ["a\nb"], "control_character")
    _refused(validate, "ab", "type")
    _refused(validate, None, "type")
    _refused(validate, [1], "type")


def test_topics_and_tags_are_independent() -> None:
    assert validate_topics(["a"]) == ("a",)
    assert validate_tags(["a"]) == ("a",)
    with pytest.raises(ReportValidationError) as info:
        validate_tags(["a", "A"])
    assert info.value.field == "tags"


# ---- metadata ----------------------------------------------------------------


def test_metadata_accepts_every_json_type() -> None:
    value = {"s": "x", "i": 1, "f": 1.5, "b": True, "n": None, "l": [1, "a"], "d": {"k": False}}
    assert validate_metadata(value) == value
    assert validate_metadata({}) == {}


def test_metadata_returns_a_copy() -> None:
    nested = {"k": [1]}
    accepted = validate_metadata({"a": nested})
    nested["k"].append(2)
    assert accepted == {"a": {"k": [1]}}


def test_metadata_top_level_key_count_at_the_edge() -> None:
    assert len(validate_metadata({f"k{i}": i for i in range(32)})) == 32
    _refused(validate_metadata, {f"k{i}": i for i in range(33)}, "too_many_keys")


def test_metadata_nested_keys_do_not_count_against_the_top_level_bound() -> None:
    assert validate_metadata({"a": {f"k{i}": i for i in range(40)}})


def test_metadata_depth_at_the_edge() -> None:
    assert validate_metadata({"a": {"b": {"c": {"d": 1}}}})
    assert validate_metadata({"a": [[[1]]]})
    _refused(validate_metadata, {"a": {"b": {"c": {"d": {}}}}}, "too_deep")
    _refused(validate_metadata, {"a": [[[[]]]]}, "too_deep")


def test_metadata_key_length_at_the_edge() -> None:
    assert validate_metadata({"k" * 64: 1})
    _refused(validate_metadata, {"k" * 65: 1}, "key_too_long")
    _refused(validate_metadata, {"": 1}, "key_too_short")
    _refused(validate_metadata, {"a": {"k" * 65: 1}}, "key_too_long")


@pytest.mark.parametrize("key", ["_x", "_", "my_pa", "my_pa_x", "system", "systemic"])
def test_metadata_refuses_reserved_keys_at_every_depth(key: str) -> None:
    _refused(validate_metadata, {key: 1}, "reserved_key")
    _refused(validate_metadata, {"a": {key: 1}}, "reserved_key")


def test_metadata_refuses_bad_keys() -> None:
    _refused(validate_metadata, {1: "a"}, "key_type")
    _refused(validate_metadata, {"a\nb": 1}, "control_character")


def test_metadata_size_at_the_edge() -> None:
    # {"k":"<n chars>"} canonical form is 8 + n bytes.
    assert validate_metadata({"k": "x" * (16384 - 8)})
    _refused(validate_metadata, {"k": "x" * (16384 - 7)}, "too_large")


def test_metadata_size_is_utf8_bytes_not_code_points() -> None:
    # U+00E9 is two UTF-8 bytes; ensure_ascii=False keeps it unescaped.
    assert validate_metadata({"k": "\u00e9" * ((16384 - 8) // 2)})
    _refused(validate_metadata, {"k": "\u00e9" * ((16384 - 8) // 2 + 1)}, "too_large")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_metadata_refuses_non_finite_floats(value: float) -> None:
    _refused(validate_metadata, {"f": value}, "non_finite")
    _refused(validate_metadata, {"l": [value]}, "non_finite")


_BELOW_MIN: Final = math.nextafter(1e-4, 0.0)
_BELOW_MAX: Final = math.nextafter(1e16, 0.0)


@pytest.mark.parametrize(
    "value", [1e308, -1e308, 1e16, -1e16, 1e-300, -1e-300, 5e-324, _BELOW_MIN, -_BELOW_MIN, 9e-5]
)
def test_metadata_refuses_floats_whose_text_has_an_exponent(value: float) -> None:
    """`1e308` is 309 digits in jsonb text: outside the magnitudes, refused at every depth."""
    _refused(validate_metadata, {"f": value}, "out_of_range")
    _refused(validate_metadata, {"l": [{"f": value}]}, "out_of_range")


@pytest.mark.parametrize(
    "value",
    [0.0, -0.0, 1e-4, -1e-4, 0.00012345, 1.5, -2.25, 1e15, _BELOW_MAX, -_BELOW_MAX, 1.0e-4 * 3],
)
def test_metadata_admits_floats_at_the_magnitude_edges(value: float) -> None:
    assert validate_metadata({"f": value}) == {"f": value}
    # Python's shortest repr has no exponent here, so jsonb prints the same digits.
    assert "e" not in repr(value)


def test_metadata_refuses_a_nul_character_in_a_string() -> None:
    """PostgreSQL jsonb cannot hold U+0000; every other control character is kept."""
    _refused(validate_metadata, {"s": "a\x00b"}, "malformed")
    _refused(validate_metadata, {"l": ["\x00"]}, "malformed")
    assert validate_metadata({"s": "a\x01\x7f\nb"}) == {"s": "a\x01\x7f\nb"}


def test_metadata_refuses_an_integer_past_the_digit_limit_as_too_large() -> None:
    _refused(validate_metadata, {"i": 10**5000}, "too_large")


class _Flag(IntEnum):
    ON = 1


class _Text(str):
    pass


@pytest.mark.parametrize(
    "value", [(1, 2), {1, 2}, b"x", object(), _Flag.ON, _Text("x"), 1j, bytearray(b"x")]
)
def test_metadata_refuses_non_json_value_types(value: object) -> None:
    _refused(validate_metadata, {"v": value}, "value_type")


def test_metadata_keeps_bool_and_int_distinct() -> None:
    accepted = validate_metadata({"b": True, "i": 1, "z": 0, "f": False})
    assert type(accepted["b"]) is bool
    assert type(accepted["i"]) is int
    assert type(accepted["f"]) is bool


@pytest.mark.parametrize("value", [None, [], "x", 1])
def test_metadata_must_be_an_object(value: object) -> None:
    _refused(validate_metadata, value, "type")


def test_metadata_refuses_lone_surrogates() -> None:
    _refused(validate_metadata, {"k": "\ud800"}, "malformed")
    _refused(validate_metadata, {"\ud800": 1}, "malformed")


# ---- associations ------------------------------------------------------------


def _assoc(**overrides: object) -> ReportAssociation:
    fields: dict[str, object] = {
        "target_kind": K.PROJECT,
        "target_ref": "prj_abc123def456",
        "relation": "about",
        "verification": Ver.VERIFIED,
    }
    fields.update(overrides)
    return ReportAssociation(**fields)  # type: ignore[arg-type]


def test_association_accepts_and_bounds_refs() -> None:
    assert _assoc().target_ref == "prj_abc123def456"
    assert _assoc(target_ref="r" * 512, target_version_ref="v" * 512).target_ref == "r" * 512
    with pytest.raises(ReportValidationError) as info:
        _assoc(target_ref="r" * 513)
    assert (info.value.field, info.value.code) == ("target_ref", "too_long")
    with pytest.raises(ReportValidationError) as info:
        _assoc(target_ref="")
    assert info.value.code == "too_short"
    with pytest.raises(ReportValidationError) as info:
        _assoc(target_version_ref="v" * 513)
    assert (info.value.field, info.value.code) == ("target_version_ref", "too_long")
    with pytest.raises(ReportValidationError) as info:
        _assoc(target_ref="a\nb")
    assert info.value.code == "control_character"


def test_association_relation_uses_the_type_regex() -> None:
    with pytest.raises(ReportValidationError) as info:
        _assoc(relation="About")
    assert (info.value.field, info.value.code) == ("relation", "pattern")


def test_external_source_is_always_asserted() -> None:
    external = _assoc(target_kind=K.EXTERNAL_SOURCE, verification=Ver.ASSERTED)
    assert external.verification is Ver.ASSERTED
    with pytest.raises(ReportValidationError) as info:
        _assoc(target_kind=K.EXTERNAL_SOURCE, verification=Ver.VERIFIED)
    assert info.value.code == "external_source_unverifiable"


def test_association_requires_enum_members() -> None:
    with pytest.raises(ReportValidationError):
        _assoc(target_kind="project")
    with pytest.raises(ReportValidationError):
        _assoc(verification="verified")


def test_associations_count_at_the_edge_and_duplicates() -> None:
    full = [_assoc(target_ref=f"prj_{i:012d}") for i in range(64)]
    assert validate_associations(full) == tuple(full)
    _refused(validate_associations, [*full, _assoc(target_ref="prj_x")], "too_many")
    _refused(validate_associations, [_assoc(), _assoc()], "duplicate")
    # The same target under a different relation is a different association.
    assert len(validate_associations([_assoc(), _assoc(relation="cites")])) == 2
    _refused(validate_associations, ["x"], "type")
    _refused(validate_associations, {"a": 1}, "type")


# ---- lifecycle ---------------------------------------------------------------

LEGAL = [
    (S.ACTIVE, Op.ARCHIVE, None, S.ARCHIVED),
    (S.ACTIVE, Op.DELETE, None, S.TRASHED),
    (S.ARCHIVED, Op.DELETE, None, S.TRASHED),
    (S.ARCHIVED, Op.RESTORE, None, S.ACTIVE),
    (S.TRASHED, Op.RESTORE, S.ACTIVE, S.ACTIVE),
    (S.TRASHED, Op.RESTORE, S.ARCHIVED, S.ARCHIVED),
]


@pytest.mark.parametrize(("state", "op", "trashed_from", "resulting"), LEGAL)
def test_legal_transitions(state: S, op: Op, trashed_from: S | None, resulting: S) -> None:
    decision = decide_lifecycle_transition(state, op, trashed_from=trashed_from)
    assert decision == LifecycleDecision(op, ReceiptOutcome.APPLIED, state, resulting)


def test_trash_from_archived_restores_archived() -> None:
    trashed = decide_lifecycle_transition(S.ARCHIVED, Op.DELETE)
    assert trashed.prior_state is S.ARCHIVED
    restored = decide_lifecycle_transition(
        trashed.resulting_state, Op.RESTORE, trashed_from=trashed.prior_state
    )
    assert restored.resulting_state is S.ARCHIVED


def test_archive_on_archived_is_a_no_op_not_an_error() -> None:
    decision = decide_lifecycle_transition(S.ARCHIVED, Op.ARCHIVE)
    assert decision.outcome is ReceiptOutcome.NO_OP
    assert decision.prior_state is decision.resulting_state is S.ARCHIVED


ILLEGAL = [
    (S.ACTIVE, Op.RESTORE, None),
    (S.TRASHED, Op.ARCHIVE, S.ACTIVE),
    (S.TRASHED, Op.ARCHIVE, S.ARCHIVED),
    (S.TRASHED, Op.DELETE, S.ACTIVE),
    (S.TRASHED, Op.DELETE, S.ARCHIVED),
]


@pytest.mark.parametrize(("state", "op", "trashed_from"), ILLEGAL)
def test_illegal_transitions_are_typed_refusals(state: S, op: Op, trashed_from: S | None) -> None:
    with pytest.raises(ReportLifecycleRefusal) as info:
        decide_lifecycle_transition(state, op, trashed_from=trashed_from)
    assert (info.value.state, info.value.operation) == (state.value, op.value)
    assert info.value.code == "illegal_transition"
    assert isinstance(info.value, ReportDomainError)


def test_every_state_operation_pair_is_covered() -> None:
    covered = {(s, o) for s, o, *_ in LEGAL} | {(s, o) for s, o, _ in ILLEGAL}
    covered.add((S.ARCHIVED, Op.ARCHIVE))
    assert covered == {(s, o) for s in S for o in Op}


@pytest.mark.parametrize("trashed_from", [None, S.TRASHED])
def test_trashed_requires_a_recorded_prior_state(trashed_from: S | None) -> None:
    with pytest.raises(ReportValidationError) as info:
        decide_lifecycle_transition(S.TRASHED, Op.RESTORE, trashed_from=trashed_from)
    assert (info.value.field, info.value.code) == ("trashed_from", "required")


@pytest.mark.parametrize("state", [S.ACTIVE, S.ARCHIVED])
def test_trashed_from_is_refused_outside_trashed(state: S) -> None:
    with pytest.raises(ReportValidationError) as info:
        decide_lifecycle_transition(state, Op.DELETE, trashed_from=S.ACTIVE)
    assert info.value.code == "unexpected"


def test_lifecycle_requires_enum_members() -> None:
    with pytest.raises(ReportValidationError):
        decide_lifecycle_transition("active", Op.ARCHIVE)  # type: ignore[arg-type]
    with pytest.raises(ReportValidationError):
        decide_lifecycle_transition(S.ACTIVE, "archive")  # type: ignore[arg-type]


# ---- refusals never echo the value ------------------------------------------


@pytest.mark.parametrize(
    ("fn", "value"),
    [
        (validate_type_token, SECRET),
        (validate_type_token, "my_pa_" + SECRET.lower()),
        (validate_relation, SECRET),
        (validate_title, SECRET * 30),
        (validate_title, SECRET + "\n"),
        (validate_summary, SECRET * 200),
        (validate_summary, SECRET + "\t"),
        (validate_change_reason, SECRET * 50),
        (validate_topics, [SECRET, SECRET.upper()]),
        (validate_tags, [SECRET * 7]),
        (validate_metadata, {SECRET * 7: 1}),
        (validate_metadata, {"_" + SECRET: 1}),
        (validate_metadata, {"k": SECRET * 2000}),
        (validate_metadata, {SECRET: math.nan}),
        (lambda value: _assoc(target_ref=value), SECRET * 50),
        (lambda value: _assoc(relation=value), SECRET),
    ],
)
def test_refusals_never_echo_the_value(fn: Callable[[Any], object], value: object) -> None:
    with pytest.raises(ReportValidationError) as info:
        fn(value)
    rendered = f"{info.value!s} {info.value!r} {info.value.args!r}"
    assert SECRET not in rendered
    assert SECRET.lower() not in rendered
    assert SECRET.upper() not in rendered


def test_lifecycle_refusal_message_is_the_table_only() -> None:
    with pytest.raises(ReportLifecycleRefusal) as info:
        decide_lifecycle_transition(S.ACTIVE, Op.RESTORE)
    assert str(info.value) == "lifecycle: restore is not legal from active"
