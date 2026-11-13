"""Files workspace contract sections 1.4, 5, 7, 8, 10: tickets, headers, ranges, intents."""

from __future__ import annotations

import hashlib

import pytest

from my_pa.domain.files.errors import (
    FilesArgumentError,
    FilesRefusal,
    RangeNotSatisfiableError,
)
from my_pa.domain.files.transfer import (
    ByteRange,
    UploadCompletion,
    UploadDeclaration,
    advance_upload_offset,
    check_upload_offset,
    mint_ticket_token,
    parse_file_id,
    parse_range,
    parse_upload_complete,
    parse_upload_offset,
    ticket_token_digest,
    ticket_token_from_authorization,
    validate_ttl,
    verify_staged,
    write_intent_digest,
)
from my_pa.domain.files.vocabulary import (
    BYTE_ROUTE_CONCURRENCY,
    DISK_RESERVE_BYTES,
    MAX_PREVIEW_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_CHUNK_BYTES,
    MAX_WRITE_TEXT_BYTES,
    PAGE_SIZE,
    SEARCH_WALK_MAX_DEPTH,
    SEARCH_WALK_MAX_ENTRIES,
    TICKET_TTL_DEFAULT_SECONDS,
    TICKET_TTL_MAX_SECONDS,
    FilesReason,
)
from my_pa.domain.identity.secret_digests import digests_match

SHA = "ab" * 32
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def test_section_8_limits_and_section_7_tokens() -> None:
    assert MAX_UPLOAD_BYTES == 10_737_418_240
    assert DISK_RESERVE_BYTES == 21_474_836_480
    assert MAX_UPLOAD_CHUNK_BYTES == 33_554_432
    assert MAX_PREVIEW_BYTES == 262_144
    assert MAX_WRITE_TEXT_BYTES == 1_048_576
    assert PAGE_SIZE == 200
    assert (SEARCH_WALK_MAX_ENTRIES, SEARCH_WALK_MAX_DEPTH) == (20_000, 32)
    assert (TICKET_TTL_DEFAULT_SECONDS, TICKET_TTL_MAX_SECONDS) == (3600, 86400)
    assert BYTE_ROUTE_CONCURRENCY == 4
    assert {reason.value for reason in FilesReason} == {
        "invalid_path",
        "not_found",
        "exists",
        "version_conflict",
        "external_change_detected",
        "unsupported_entry",
        "too_large",
        "quota",
        "digest_mismatch",
        "offset_mismatch",
        "ticket_invalid",
    }


# --- tokens --------------------------------------------------------------------


def test_minted_tokens_round_trip_and_are_fresh() -> None:
    presented, digest = mint_ticket_token()
    assert presented.startswith("gfwtk_")
    assert len(presented) == 6 + 64
    assert presented[6:] == presented[6:].lower()
    assert ticket_token_digest(presented) == digest
    assert digests_match(ticket_token_digest(presented) or "", digest)
    assert digest != presented[6:]
    other, other_digest = mint_ticket_token()
    assert (other, other_digest) != (presented, digest)


def test_token_digest_golden() -> None:
    assert ticket_token_digest("gfwtk_" + "00" * 32) == hashlib.sha256(bytes(32)).hexdigest()
    assert ticket_token_digest("gfwtk_" + "00" * 32) == (
        "66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925"
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        b"gfwtk_" + b"0" * 64,
        "",
        "gfwtk_",
        "gfwtk_" + "0" * 63,
        "gfwtk_" + "0" * 65,
        "gfwtk_" + "A" * 64,
        "GFWTK_" + "0" * 64,
        "grxtk_" + "0" * 64,
        " gfwtk_" + "0" * 64,
        "gfwtk_" + "0" * 64 + "\n",
        "gfwtk-" + "0" * 64,
        "gfwtk_" + "\u0660" * 64,
    ],
)
def test_malformed_tokens_digest_to_none_without_raising(value: object) -> None:
    assert ticket_token_digest(value) is None


def test_authorization_header_is_exactly_bearer_and_a_token() -> None:
    token = "gfwtk_" + "1f" * 32
    assert ticket_token_from_authorization(f"Bearer {token}") == token
    for bad in (
        None,
        token,
        f"bearer {token}",
        f"Bearer  {token}",
        f"Bearer {token} ",
        f" Bearer {token}",
        f"Basic {token}",
        "Bearer ",
        "Bearer gfwtk_xyz",
    ):
        assert ticket_token_from_authorization(bad) is None


def test_file_ids_use_local_prefix_patterns() -> None:
    assert parse_file_id("fwupl_abcdEFGH1234", "fwupl") == "fwupl_abcdEFGH1234"
    for bad in (None, "fwupl_short", "fwdnl_abcdefgh", "fwupl_abcd-efgh", "fwupl_" + "a" * 65):
        assert parse_file_id(bad, "fwupl") is None
    with pytest.raises(ValueError, match="prefix"):
        parse_file_id("grxfr_abcdefgh", "grxfr")


# --- declaration ------------------------------------------------------------------


def test_declaration_defaults_and_zero_byte() -> None:
    declared = UploadDeclaration.of()
    assert (declared.size, declared.sha256, declared.ttl_seconds) == (None, None, 3600)
    zero = UploadDeclaration.of(size=0, sha256=EMPTY_SHA, ttl_seconds=86400)
    assert (zero.size, zero.sha256, zero.ttl_seconds) == (0, EMPTY_SHA, 86400)
    assert UploadDeclaration.of(size=MAX_UPLOAD_BYTES).size == MAX_UPLOAD_BYTES


def test_declaration_over_the_ceiling_is_too_large() -> None:
    with pytest.raises(FilesRefusal) as caught:
        UploadDeclaration.of(size=MAX_UPLOAD_BYTES + 1)
    assert caught.value.reason is FilesReason.TOO_LARGE
    with pytest.raises(FilesRefusal):
        UploadDeclaration.of(size=11, max_upload_bytes=10)


@pytest.mark.parametrize(
    ("kwargs", "field", "code"),
    [
        ({"size": -1}, "size", "bounds"),
        ({"size": True}, "size", "type"),
        ({"size": "1"}, "size", "type"),
        ({"sha256": "AB" * 32}, "sha256", "pattern"),
        ({"sha256": "ab" * 31}, "sha256", "pattern"),
        ({"sha256": 1}, "sha256", "type"),
        ({"ttl_seconds": 299}, "ttl_seconds", "bounds"),
        ({"ttl_seconds": 86401}, "ttl_seconds", "bounds"),
        ({"ttl_seconds": 3600.0}, "ttl_seconds", "type"),
        ({"ttl_seconds": False}, "ttl_seconds", "type"),
        ({"max_upload_bytes": -1}, "max_upload_bytes", "bounds"),
    ],
)
def test_declaration_refusals(kwargs: dict[str, object], field: str, code: str) -> None:
    with pytest.raises(FilesArgumentError) as caught:
        UploadDeclaration.of(**kwargs)
    assert (caught.value.field, caught.value.code) == (field, code)


def test_validate_ttl_bounds() -> None:
    assert validate_ttl(None) == 3600
    assert validate_ttl(300) == 300
    assert validate_ttl(86400) == 86400


# --- offsets and headers ------------------------------------------------------------


@pytest.mark.parametrize(("header", "value"), [("0", 0), ("1", 1), ("33554432", 33554432)])
def test_upload_offset_header(header: str, value: int) -> None:
    assert parse_upload_offset(header) == value


@pytest.mark.parametrize(
    "header",
    [None, "", " 1", "1 ", "+1", "-1", "01", "1_000", "1.0", "0x10", "\u0661", "1" * 20, "1,2"],
)
def test_malformed_upload_offset(header: object) -> None:
    with pytest.raises(FilesArgumentError) as caught:
        parse_upload_offset(header)
    assert caught.value.field == "Upload-Offset"


def test_offset_check_and_arithmetic() -> None:
    check_upload_offset(5, 5)
    with pytest.raises(FilesRefusal) as caught:
        check_upload_offset(4, 5)
    assert caught.value.reason is FilesReason.OFFSET_MISMATCH
    assert advance_upload_offset(0, 0, declared_size=0) == 0
    assert advance_upload_offset(0, MAX_UPLOAD_CHUNK_BYTES, declared_size=None) == (
        MAX_UPLOAD_CHUNK_BYTES
    )
    assert advance_upload_offset(10, 5, declared_size=15) == 15
    for current, chunk, declared, limit in (
        (0, MAX_UPLOAD_CHUNK_BYTES + 1, None, MAX_UPLOAD_BYTES),
        (10, 6, 15, MAX_UPLOAD_BYTES),
        (MAX_UPLOAD_BYTES, 1, None, MAX_UPLOAD_BYTES),
        (90, 11, None, 100),
    ):
        with pytest.raises(FilesRefusal) as refused:
            advance_upload_offset(current, chunk, declared_size=declared, max_upload_bytes=limit)
        assert refused.value.reason is FilesReason.TOO_LARGE
    with pytest.raises(FilesArgumentError):
        advance_upload_offset(-1, 1, declared_size=None)
    with pytest.raises(FilesArgumentError):
        advance_upload_offset(True, 1, declared_size=None)


def test_upload_complete_grammar() -> None:
    assert parse_upload_complete(f"sha256={SHA}, length=0") == UploadCompletion(SHA, 0)
    assert parse_upload_complete(f"sha256={SHA}, length=10737418240").length == MAX_UPLOAD_BYTES


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        f"length=1, sha256={SHA}",
        f"sha256={SHA},length=1",
        f"sha256={SHA},  length=1",
        f"sha256={SHA}, length=01",
        f"sha256={SHA}, length=-1",
        f"sha256={SHA}, length=",
        f"sha256={SHA.upper()}, length=1",
        f"sha256={SHA[:-1]}, length=1",
        f"SHA256={SHA}, length=1",
        f"sha256={SHA}, length=1, extra=2",
        f"sha256={SHA}, length=1 ",
        f"sha256={SHA}, length=1\r\n",
        f"sha256={SHA}",
        f'sha256="{SHA}", length=1',
    ],
)
def test_malformed_upload_complete(header: object) -> None:
    with pytest.raises(FilesArgumentError) as caught:
        parse_upload_complete(header)
    assert caught.value.field == "Upload-Complete"
    assert SHA not in str(caught.value)


def test_verify_staged() -> None:
    declared = UploadDeclaration.of(size=3, sha256=SHA)
    verify_staged(UploadCompletion(SHA, 3), declared, staged_length=3, staged_sha256=SHA)
    verify_staged(
        UploadCompletion(EMPTY_SHA, 0),
        UploadDeclaration.of(),
        staged_length=0,
        staged_sha256=EMPTY_SHA,
    )
    other = "cd" * 32
    for completion, declaration, length, digest in (
        (UploadCompletion(SHA, 4), declared, 3, SHA),
        (UploadCompletion(other, 3), declared, 3, SHA),
        (UploadCompletion(other, 3), UploadDeclaration.of(size=3, sha256=SHA), 3, other),
        (UploadCompletion(SHA, 4), UploadDeclaration.of(size=3), 4, SHA),
    ):
        with pytest.raises(FilesRefusal) as caught:
            verify_staged(completion, declaration, staged_length=length, staged_sha256=digest)
        assert caught.value.reason is FilesReason.DIGEST_MISMATCH


# --- Range ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 10, None),
        (None, 0, None),
        ("bytes=0-0", 10, (0, 0)),
        ("bytes=0-9", 10, (0, 9)),
        ("bytes=0-99", 10, (0, 9)),
        ("bytes=3-", 10, (3, 9)),
        ("bytes=9-", 10, (9, 9)),
        ("bytes=-1", 10, (9, 9)),
        ("bytes=-10", 10, (0, 9)),
        ("bytes=-100", 10, (0, 9)),
        ("bytes=00-01", 10, (0, 1)),
    ],
)
def test_satisfiable_ranges(
    header: str | None, size: int, expected: tuple[int, int] | None
) -> None:
    parsed = parse_range(header, size)
    if expected is None:
        assert parsed is None
    else:
        assert parsed == ByteRange(start=expected[0], end=expected[1], size=size)
        assert parsed.length == expected[1] - expected[0] + 1


def test_content_range() -> None:
    parsed = parse_range("bytes=2-4", 10)
    assert parsed is not None
    assert parsed.content_range == "bytes 2-4/10"


@pytest.mark.parametrize(
    ("header", "size"),
    [
        ("bytes=10-", 10),
        ("bytes=10-20", 10),
        ("bytes=-0", 10),
        ("bytes=0-0", 0),
        ("bytes=0-", 0),
        ("bytes=-5", 0),
    ],
)
def test_unsatisfiable_ranges_are_distinguished(header: str, size: int) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_range(header, size)


@pytest.mark.parametrize(
    "header",
    [
        "",
        "bytes=",
        "bytes=-",
        "bytes=5-3",
        "bytes=0-1,3-4",
        "bytes=0-1, 3-4",
        "bytes = 0-1",
        "Bytes=0-1",
        "items=0-1",
        "bytes=a-b",
        "bytes=+1-2",
        "bytes=0-1 ",
        "bytes=\u0661-\u0662",
        "bytes=" + "1" * 20 + "-",
        1,
    ],
)
def test_malformed_ranges_are_argument_errors(header: object) -> None:
    with pytest.raises(FilesArgumentError) as caught:
        parse_range(header, 10)
    assert caught.value.field == "Range"
    assert not isinstance(caught.value, RangeNotSatisfiableError)


# --- intent ------------------------------------------------------------------------------


def test_intent_digest_golden_and_order_independent() -> None:
    golden = "d0a0dac4f5644168a5c5f62e6faa718d25c1c9d6c13cbc59ae1e664f1136ee12"
    arguments = {"workspace_id": "mcp", "path": "a/b", "parents": False}
    assert write_intent_digest("files.mkdir", arguments) == golden
    assert write_intent_digest("files.mkdir", dict(reversed(arguments.items()))) == golden
    assert write_intent_digest("files.copy", arguments) != golden
    assert write_intent_digest("files.mkdir", {**arguments, "parents": True}) != golden


def test_intent_digest_binds_a_token_digest_never_the_raw_token() -> None:
    presented, digest = mint_ticket_token()
    bound = write_intent_digest("files.upload.finalize", {"upload_token_sha256": digest})
    assert len(bound) == 64
    for refused in (
        {"upload_token": presented},
        {"download_token": presented},
        {"idempotency_key": "k"},
    ):
        with pytest.raises(FilesArgumentError) as caught:
            write_intent_digest("files.upload.finalize", refused)
        assert presented not in str(caught.value)
        assert presented not in repr(caught.value)


@pytest.mark.parametrize(
    ("capability", "arguments"),
    [
        ("reports.publish", {}),
        (1, {}),
        ("files.mkdir", []),
        ("files.mkdir", {1: "x"}),
        ("files.mkdir", {"x": float("nan")}),
        ("files.mkdir", {"x": object()}),
    ],
)
def test_intent_digest_refusals(capability: object, arguments: object) -> None:
    with pytest.raises(FilesArgumentError):
        write_intent_digest(capability, arguments)  # type: ignore[arg-type]
