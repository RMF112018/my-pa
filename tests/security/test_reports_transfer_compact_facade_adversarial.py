"""Reports Modernization WP06 Part D: bounded chunked transfer refusals on the facade.

The harness is `tests/contract/test_reports_transfer_compact_facade.py`'s: the
real remote MCP app over the durable grant store on PostgreSQL, its service
composed with a real `FilesystemReportContentStore` and a real
`FilesystemReportTransferStaging` on `tmp_path`, and a clock the tests may move
(session expiry). Every refusal below asserts ZERO mutation: the row counts of
`report_transfer_sessions`, `report_transfer_chunks`, `report_content_objects`,
`report_versions` and `report_receipts`, every session's mutable columns, the
content store's objects and the staging tree are exactly what they were.

* grant and gate refusals: profile omission, each write gate off, an
  insufficient (read-only) and an inexact (wrong purpose) grant, an expired
  grant, a revoked client, the wrong wrapper both ways;
* T5 uniform refusal: a foreign Principal's session, ANOTHER CLIENT's session
  under the same Principal (append, finalize, abort, consume), an expired
  session (every operation), a consumed or unknown token -- each the one bare
  `not_found`, identical to a session that never existed;
* forged server-owned fields on every operation;
* chunk and declaration rules: oversize chunk, wrong non-final size, gap,
  duplicate-different (conflicts), duplicate-identical (a no-op replay), wrong
  declared size or sha256 at finalize, a gzip bomb at finalize, a malformed
  token, and the begin quota (`rate_limited`).

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine
from tests.conftest import operator
from tests.contract.test_reports_compact_facade import (
    CLIENT,
    MINIMAL,
    OTHER_CLIENT,
    PUBLISH,
    READ,
    WHEN,
    Exchange,
    Harness,
    describe,
    grant_row,
    ok,
    outcome,
    profile_grants,
    refusal,
    remote_principal,
    wrapped,
)
from tests.contract.test_reports_transfer_compact_facade import (
    ABORT,
    APPEND,
    BEGIN,
    CHUNK,
    FINALIZE,
    GZIP,
    READ_CHUNK,
    TRANSFER,
    TRANSFER_TABLES,
    UPLOADS,
    Clock,
    append_payload,
    begin_payload,
    build_transfer_service,
    markdown_text,
    pieces,
    reference,
    rows,
    single,
    staged_tree,
    transfer_grants,
    upload,
)

from my_pa.adapters.mcp.chatllm_gateway import OPERATOR_TOOL, READ_TOOL, WRITE_TOOL
from my_pa.adapters.normalization import normalize
from my_pa.application.service import ApplicationService
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore

pytestmark = pytest.mark.database

UNKNOWN_SESSION: Final = "grxfr_00000000nothere0"
UNKNOWN_TOKEN: Final = "grxtk_" + "0" * 64
UNKNOWN_REPORT: Final = "grpt_00000000nothere0"
_STAGED: Final = markdown_text(CHUNK + 5000, seed=61)


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return (tmp_path / "report-content").resolve()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def harness(migrated_engine: Engine, store_root: Path, clock: Clock) -> Harness:
    built = Harness(
        migrated_engine, build_transfer_service(migrated_engine, store_root, clock=clock)
    )
    built.gates()
    return built


# ---- zero mutation ----------------------------------------------------------------------


class State:
    """Rows, session columns, store objects and staging before a request, compared after."""

    def __init__(self, harness: Harness, root: Path) -> None:
        self.harness, self.root = harness, root
        self.before = self.capture()

    def capture(self) -> tuple[object, ...]:
        engine = self.harness.engine
        counted = {
            table: rows(engine, f"SELECT count(*) FROM knowledge.{table}")[0][0]  # noqa: S608
            for table in TRANSFER_TABLES
        }
        sessions = [
            tuple(row)
            for row in rows(
                engine,
                "SELECT session_id, state, received_byte_count, content_token_digest, "
                "finalized_at, consumed_content_id, consumed_at FROM "
                "knowledge.report_transfer_sessions ORDER BY session_id",
            )
        ]
        objects = (
            FilesystemReportContentStore(self.root).stored_object_ids()
            if self.root.exists()
            else ()
        )
        return counted, sessions, objects, staged_tree(self.root)

    def unchanged(self) -> None:
        assert self.capture() == self.before


def problem(answer: Exchange) -> dict[str, Any]:
    failed, document = outcome(answer)
    assert failed, document
    error = dict(document.get("error", document))
    error.pop("correlation_id", None)
    return error


def bare_not_found(answers: Iterable[Exchange]) -> None:
    """T5: every answer is the one bare `not_found`, identical to each other."""
    seen = [problem(answer) for answer in answers]
    for error in seen:
        assert (error["code"], error.get("safe_details") or []) == ("not_found", []), error
    assert all(error == seen[0] for error in seen), seen


def unknown_session_answers(harness: Harness, token: str) -> list[Exchange]:
    """What a session that never existed answers, on each session operation."""
    return harness.run(
        [
            (
                token,
                wrapped(WRITE_TOOL, APPEND, append_payload(UNKNOWN_SESSION, 0, _STAGED[:CHUNK])),
            ),
            (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": UNKNOWN_SESSION})),
            (token, wrapped(WRITE_TOOL, ABORT, {"session_id": UNKNOWN_SESSION})),
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {**MINIMAL, "content": reference(UNKNOWN_SESSION, UNKNOWN_TOKEN)},
                ),
            ),
        ]
    )


def session_attempts(token: str, session_id: str, content_token: str) -> list[tuple[str, Any]]:
    """append, finalize, abort and consume-by-publish on `session_id`."""
    return [
        (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, 0, _STAGED[:CHUNK]))),
        (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": session_id})),
        (token, wrapped(WRITE_TOOL, ABORT, {"session_id": session_id})),
        (
            token,
            wrapped(
                WRITE_TOOL,
                PUBLISH,
                {
                    **MINIMAL,
                    "title": "Another title",
                    "content": reference(session_id, content_token),
                },
            ),
        ),
    ]


def open_session(harness: Harness, token: str, staged: bytes = _STAGED, **extra: Any) -> str:  # noqa: ANN401
    return str(
        ok(single(harness, token, WRITE_TOOL, BEGIN, begin_payload(staged, **extra)))["session_id"]
    )


def requests_for(capability: Capability, session_id: str = UNKNOWN_SESSION) -> tuple[str, Any]:
    """The wrapper and one well-formed payload of each transfer name."""
    if capability is BEGIN:
        return WRITE_TOOL, begin_payload(_STAGED)
    if capability is APPEND:
        return WRITE_TOOL, append_payload(session_id, 0, _STAGED[:CHUNK])
    if capability in (FINALIZE, ABORT):
        return WRITE_TOOL, {"session_id": session_id}
    return READ_TOOL, {"report_id": UNKNOWN_REPORT, "version_number": 1}


# ---- 1. grants and gates --------------------------------------------------------------------


@pytest.mark.parametrize("capability", TRANSFER, ids=lambda c: c.value)
def test_a_name_omitted_from_the_profile_is_hidden_and_refused(
    harness: Harness, store_root: Path, capability: Capability
) -> None:
    others = tuple(row for row in transfer_grants(harness.service) if row[0] is not capability)
    token = harness.client(CLIENT, others)
    tool, payload = requests_for(capability)
    state = State(harness, store_root)
    exact, called = harness.run(
        [
            (token, describe(capability=capability.value)),
            (token, wrapped(tool, capability, payload)),
        ]
    )
    assert refusal(exact) == ("unsupported", [])
    assert refusal(called) == ("unsupported", [])
    state.unchanged()


@pytest.mark.parametrize(
    ("process", "durable_global", "client"),
    [(False, True, True), (True, False, True), (True, True, False)],
    ids=["process_writes_off", "global_writes_off", "client_writes_off"],
)
def test_any_write_gate_off_hides_and_refuses_the_uploads_and_still_reads(
    harness: Harness, store_root: Path, process: bool, durable_global: bool, client: bool
) -> None:
    # A session opened while every gate was on, so append/finalize/abort name a real one.
    opener = harness.client(OTHER_CLIENT, transfer_grants(harness.service))
    open_session(harness, opener)
    harness.gates(writes=durable_global)
    token = harness.client(CLIENT, transfer_grants(harness.service), writes=client)
    state = State(harness, store_root)
    answers = harness.run(
        [
            (token, describe(feature="reports", limit=100)),
            *((token, wrapped(requests_for(c)[0], c, requests_for(c)[1])) for c in UPLOADS),
            (token, wrapped(READ_TOOL, READ_CHUNK, requests_for(READ_CHUNK)[1])),
        ],
        process_writes=process,
    )
    listed, *uploads, read_chunk = answers
    _failed, catalog = outcome(listed)
    described = {item["capability"] for item in catalog["items"]}
    assert not {c.value for c in UPLOADS} & described
    assert READ_CHUNK.value in described
    for answer in uploads:
        assert refusal(answer) == ("unsupported", [])
    # The read side is untouched by every write gate (an unknown report is not_found).
    assert refusal(read_chunk)[0] == "not_found"
    state.unchanged()


def test_a_read_only_client_cannot_begin(harness: Harness, store_root: Path) -> None:
    """Insufficient grant: only `reports.read` and `read_chunk`, both `report_read`."""
    token = harness.client(CLIENT, [grant_row(READ), grant_row(READ_CHUNK)])
    state = State(harness, store_root)
    exact, begun, catalog = harness.run(
        [
            (token, describe(capability=BEGIN.value)),
            (token, wrapped(WRITE_TOOL, BEGIN, begin_payload(_STAGED))),
            (token, describe(limit=100)),
        ]
    )
    assert refusal(exact) == ("unsupported", [])
    assert refusal(begun) == ("unsupported", [])
    assert {item["capability"] for item in outcome(catalog)[1]["items"]} == {
        READ.value,
        READ_CHUNK.value,
    }
    state.unchanged()


@pytest.mark.parametrize("capability", TRANSFER, ids=lambda c: c.value)
def test_an_inexact_or_expired_grant_is_refused(
    harness: Harness, store_root: Path, capability: Capability
) -> None:
    others = tuple(row for row in transfer_grants(harness.service) if row[0] is not capability)
    wrong = Purpose.REPORT_AUTHORING if capability is READ_CHUNK else Purpose.REPORT_READ
    inexact = harness.client(CLIENT, (*others, grant_row(capability, purpose=wrong)))
    expired = harness.client(
        OTHER_CLIENT, (*others, grant_row(capability, expires_at=WHEN - timedelta(seconds=1)))
    )
    tool, payload = requests_for(capability)
    state = State(harness, store_root)
    for answer in harness.run(
        [
            (inexact, wrapped(tool, capability, payload)),
            (expired, wrapped(tool, capability, payload)),
        ]
    ):
        assert refusal(answer) == ("unsupported", [])
    state.unchanged()


def test_a_revoked_client_is_refused_before_any_tool(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    session_id = open_session(harness, token)
    harness.revoke(CLIENT)
    state = State(harness, store_root)
    answers = harness.run(
        [(token, describe(capability=BEGIN.value))]
        + [
            (token, wrapped(requests_for(c, session_id)[0], c, requests_for(c, session_id)[1]))
            for c in TRANSFER
        ]
    )
    for answer in answers:
        assert (answer.status, answer.document) == (401, {"error": "invalid_token"})
    state.unchanged()


def test_the_wrong_wrapper_is_refused(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    session_id = open_session(harness, token)
    state = State(harness, store_root)
    read_chunk_as_write, append_as_read, begin_as_read, append_as_operator = harness.run(
        [
            (token, wrapped(WRITE_TOOL, READ_CHUNK, requests_for(READ_CHUNK)[1])),
            (token, wrapped(READ_TOOL, APPEND, append_payload(session_id, 0, _STAGED[:CHUNK]))),
            (token, wrapped(READ_TOOL, BEGIN, begin_payload(_STAGED, ttl_seconds=900))),
            (token, wrapped(OPERATOR_TOOL, APPEND, append_payload(session_id, 0, _STAGED[:CHUNK]))),
        ]
    )
    assert refusal(read_chunk_as_write) == ("invalid_request", [])
    assert refusal(append_as_read) == ("invalid_request", [])
    assert refusal(begin_as_read) == ("invalid_request", [])
    assert refusal(append_as_operator) == ("unsupported", [])
    state.unchanged()


# ---- 2. T5: one bare not_found ---------------------------------------------------------------


def _local(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: dict[str, Any],
) -> dict[str, Any]:
    (purpose,) = permitted_purposes(capability)
    metadata, command = normalize(
        capability.value,
        {
            "request_id": f"req-{capability.value}",
            "purpose": purpose.value,
            "principal_id": principal.principal_id,
            "requested_at": "2026-11-04T12:00:00Z",
            "payload": payload,
        },
    )
    answer = service.invoke(
        metadata, command, principal=principal, transport=CaptureTransport.LOCAL
    ).model_dump(mode="json")
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def test_a_foreign_principals_session_is_exactly_an_unknown_one(
    harness: Harness, store_root: Path
) -> None:
    stranger = operator()
    assert stranger.principal_id != remote_principal().principal_id
    opened = _local(
        harness.service,
        stranger,
        BEGIN,
        {**begin_payload(_STAGED), "idempotency_key": "idk_foreign_transfer_0001"},
    )
    session_id = opened["session_id"]
    for sequence, chunk in enumerate(pieces(_STAGED)):
        _local(harness.service, stranger, APPEND, append_payload(session_id, sequence, chunk))
    content_token = _local(harness.service, stranger, FINALIZE, {"session_id": session_id})[
        "content_token"
    ]
    token = harness.client(CLIENT, transfer_grants(harness.service))
    baseline = unknown_session_answers(harness, token)
    state = State(harness, store_root)
    theirs = harness.run(session_attempts(token, session_id, content_token))
    bare_not_found([*baseline, *theirs])
    for answer in theirs:
        assert session_id not in json.dumps(answer.document)
    state.unchanged()


@pytest.mark.parametrize("finalized", [False, True], ids=["open", "finalized"])
def test_another_clients_session_under_the_same_principal_is_exactly_an_unknown_one(
    harness: Harness, store_root: Path, finalized: bool
) -> None:
    """CROSS-CLIENT (T4/T5): B appends to, finalizes, aborts, consumes A's session."""
    grants = transfer_grants(harness.service)
    first = harness.client(CLIENT, grants)
    second = harness.client(OTHER_CLIENT, grants)
    if finalized:
        done = upload(harness, first, _STAGED)
        session_id, content_token = done.session_id, done.content_token
    else:
        session_id, content_token = open_session(harness, first), UNKNOWN_TOKEN
        # A has chunk 0, so B's chunk 0 would otherwise be a replay or a conflict.
        ok(
            single(
                harness, first, WRITE_TOOL, APPEND, append_payload(session_id, 0, _STAGED[:CHUNK])
            )
        )
    baseline = unknown_session_answers(harness, second)
    state = State(harness, store_root)
    theirs = harness.run(session_attempts(second, session_id, content_token))
    bare_not_found([*baseline, *theirs])
    state.unchanged()
    # A's session is untouched and still A's: A completes and consumes it.
    if not finalized:
        ok(
            single(
                harness, first, WRITE_TOOL, APPEND, append_payload(session_id, 1, _STAGED[CHUNK:])
            )
        )
        content_token = ok(
            single(harness, first, WRITE_TOOL, FINALIZE, {"session_id": session_id})
        )["content_token"]
    ok(
        single(
            harness,
            first,
            WRITE_TOOL,
            PUBLISH,
            {**MINIMAL, "content": reference(session_id, content_token)},
        )
    )


def test_an_expired_session_is_not_found_on_every_operation(
    harness: Harness, store_root: Path, clock: Clock
) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    open_id = open_session(harness, token, ttl_seconds=300)
    ok(single(harness, token, WRITE_TOOL, APPEND, append_payload(open_id, 0, _STAGED[:CHUNK])))
    done = upload(harness, token, markdown_text(9000, seed=62), ttl_seconds=300)
    baseline = unknown_session_answers(harness, token)
    clock.advance(300)  # expires_at <= now
    state = State(harness, store_root)
    answers = harness.run(
        [
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(open_id, 1, _STAGED[CHUNK:]))),
            (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": open_id})),
            (token, wrapped(WRITE_TOOL, ABORT, {"session_id": open_id})),
            (token, wrapped(WRITE_TOOL, ABORT, {"session_id": done.session_id})),
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {**MINIMAL, "content": reference(done.session_id, done.content_token)},
                ),
            ),
            # Begin's keyed replay of the expired session is not_found too (T7).
            (token, wrapped(WRITE_TOOL, BEGIN, begin_payload(_STAGED, ttl_seconds=300))),
        ]
    )
    bare_not_found([*baseline, *answers])
    state.unchanged()


def test_a_consumed_token_unknown_token_and_malformed_token(
    harness: Harness, store_root: Path
) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    done = upload(harness, token, _STAGED)
    ok(
        single(
            harness,
            token,
            WRITE_TOOL,
            PUBLISH,
            {**MINIMAL, "content": reference(done.session_id, done.content_token)},
        )
    )
    other = upload(harness, token, markdown_text(7000, seed=63))
    baseline = unknown_session_answers(harness, token)
    state = State(harness, store_root)
    reuse, wrong_token, unknown_both, malformed = harness.run(
        [
            # A new request (another title, so another key) re-presenting the consumed token.
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {
                        **MINIMAL,
                        "title": "Second",
                        "content": reference(done.session_id, done.content_token),
                    },
                ),
            ),
            # A live finalized session with a well-formed token that is not its token.
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {**MINIMAL, "content": reference(other.session_id, UNKNOWN_TOKEN)},
                ),
            ),
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {**MINIMAL, "content": reference(UNKNOWN_SESSION, UNKNOWN_TOKEN)},
                ),
            ),
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {
                        **MINIMAL,
                        "content": reference(other.session_id, other.content_token[:-1] + "G"),
                    },
                ),
            ),
        ]
    )
    bare_not_found([*baseline, reuse, wrong_token, unknown_both])
    assert refusal(malformed)[0] == "invalid_request"
    rendered = json.dumps(malformed.document)
    assert other.content_token[6:30] not in rendered
    state.unchanged()


def test_a_foreign_principals_report_is_not_found_by_read_chunk(
    harness: Harness, store_root: Path
) -> None:
    stranger = operator()
    published = _local(
        harness.service,
        stranger,
        PUBLISH,
        {**MINIMAL, "idempotency_key": "idk_foreign_transfer_report_01"},
    )
    token = harness.client(CLIENT, transfer_grants(harness.service))
    state = State(harness, store_root)
    theirs, missing = harness.run(
        [
            (
                token,
                wrapped(
                    READ_TOOL,
                    READ_CHUNK,
                    {"report_id": published["report_id"], "version_number": 1},
                ),
            ),
            (
                token,
                wrapped(READ_TOOL, READ_CHUNK, {"report_id": UNKNOWN_REPORT, "version_number": 1}),
            ),
        ]
    )
    assert problem(theirs) == problem(missing)
    assert problem(theirs)["code"] == "not_found"
    assert published["report_id"] not in json.dumps(theirs.document)
    state.unchanged()


# ---- 3. forged server-owned fields -----------------------------------------------------------

_FORGED: Final = (
    "principal_id",
    "owner_principal_id",
    "purpose",
    "idempotency_key",
    "client_ref",
    "state",
    "content_token_digest",
    "chunk_byte_limit",
    "received_byte_count",
)


@pytest.mark.parametrize("name", _FORGED)
def test_a_forged_server_field_is_refused_on_every_operation(
    harness: Harness, store_root: Path, name: str
) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    session_id = open_session(harness, token)
    value: Any = 262_144 if name in {"chunk_byte_limit", "received_byte_count"} else "forged-value"
    if name == "state":
        value = "finalized"
    state = State(harness, store_root)
    answers = harness.run(
        [
            (
                token,
                wrapped(
                    WRITE_TOOL, BEGIN, {**begin_payload(_STAGED, ttl_seconds=901), name: value}
                ),
            ),
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    APPEND,
                    {**append_payload(session_id, 0, _STAGED[:CHUNK]), name: value},
                ),
            ),
            (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": session_id, name: value})),
            (token, wrapped(WRITE_TOOL, ABORT, {"session_id": session_id, name: value})),
            (
                token,
                wrapped(
                    READ_TOOL,
                    READ_CHUNK,
                    {"report_id": UNKNOWN_REPORT, "version_number": 1, name: value},
                ),
            ),
            # Inside the transfer reference (T10: exactly two inner keys).
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {
                        **MINIMAL,
                        "content": {
                            "transfer": {
                                "session_id": session_id,
                                "content_token": UNKNOWN_TOKEN,
                                name: value,
                            }
                        },
                    },
                ),
            ),
        ]
    )
    for answer in answers:
        assert refusal(answer)[0] == "invalid_request", (name, answer.document)
    state.unchanged()


@pytest.mark.parametrize("name", ["principal_id", "purpose", "request_id", "scope"])
def test_a_forged_envelope_field_is_refused(harness: Harness, store_root: Path, name: str) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    state = State(harness, store_root)
    (answer,) = harness.run(
        [
            (
                token,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": WRITE_TOOL,
                        "arguments": {
                            "capability": BEGIN.value,
                            "arguments": {"payload": begin_payload(_STAGED), name: "forged"},
                        },
                    },
                },
            )
        ]
    )
    assert refusal(answer)[0] == "invalid_request"
    state.unchanged()


# ---- 4. chunk and declaration rules ---------------------------------------------------------


def test_chunk_size_rules(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    big = markdown_text(3 * CHUNK, seed=64)
    session_id = open_session(harness, token, big)
    state = State(harness, store_root)
    oversize, short_non_final = harness.run(
        [
            # 262,145 raw bytes: 349,528 Base64 characters is the schema's maximum.
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, 0, big[: CHUNK + 1]))),
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, 0, big[: CHUNK - 1]))),
        ]
    )
    assert refusal(oversize)[0] == "invalid_request"
    assert refusal(short_non_final) == ("invalid_request", ["chunk"])
    state.unchanged()
    print("\noversize:", problem(oversize), "\nshort non-final:", problem(short_non_final))


def test_sequence_gap_duplicate_different_and_identical_replay(
    harness: Harness, store_root: Path
) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    big = markdown_text(3 * CHUNK, seed=65)
    session_id = open_session(harness, token, big)
    first = big[:CHUNK]
    ok(single(harness, token, WRITE_TOOL, APPEND, append_payload(session_id, 0, first)))
    state = State(harness, store_root)
    different = markdown_text(CHUNK, seed=66)
    assert different != first
    gap, duplicate_different, replay = harness.run(
        [
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, 2, big[2 * CHUNK :]))),
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, 0, different))),
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, 0, first))),
        ]
    )
    assert refusal(gap) == ("conflict", ["transfer_sequence"])
    assert refusal(duplicate_different) == ("conflict", ["transfer_chunk_conflict"])
    replayed = ok(replay)
    assert (replayed["replayed"], replayed["received_byte_count"], replayed["next_sequence"]) == (
        True,
        CHUNK,
        1,
    )
    state.unchanged()
    print("\ngap:", problem(gap), "\nduplicate-different:", problem(duplicate_different))


def test_finalize_refuses_a_wrong_declared_size_or_sha256(
    harness: Harness, store_root: Path
) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    # Declared one byte more than will be sent: the session never completes.
    short_id = str(
        ok(
            single(
                harness,
                token,
                WRITE_TOOL,
                BEGIN,
                {**begin_payload(_STAGED), "byte_count": len(_STAGED) + 1},
            )
        )["session_id"]
    )
    first, last = pieces(_STAGED)
    ok(single(harness, token, WRITE_TOOL, APPEND, append_payload(short_id, 0, first)))
    # The real last chunk falls one byte short of the declaration: refused at append.
    # Declared another sha256: every chunk verifies, the whole does not.
    wrong_sha = str(
        ok(
            single(
                harness,
                token,
                WRITE_TOOL,
                BEGIN,
                {**begin_payload(_STAGED), "sha256": "ab" * 32},
            )
        )["session_id"]
    )
    for sequence, chunk in enumerate(pieces(_STAGED)):
        ok(single(harness, token, WRITE_TOOL, APPEND, append_payload(wrong_sha, sequence, chunk)))
    state = State(harness, store_root)
    short_last, incomplete, mismatch = harness.run(
        [
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(short_id, 1, last))),
            (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": short_id})),
            (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": wrong_sha})),
        ]
    )
    assert refusal(short_last) == ("invalid_request", ["chunk"])
    assert refusal(incomplete) == ("conflict", ["transfer_incomplete"])
    assert refusal(mismatch)[0] == "invalid_request"
    assert "transfer" in refusal(mismatch)[1]
    state.unchanged()
    print(
        "\nshort last chunk:",
        problem(short_last),
        "\nincomplete:",
        problem(incomplete),
        "\nwhole-digest mismatch:",
        problem(mismatch),
    )


def test_a_gzip_bomb_is_refused_at_finalize(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    bomb = gzip.compress(b"a" * (8 * 1024 * 1024), compresslevel=9, mtime=0)
    assert len(bomb) * 256 < 8 * 1024 * 1024
    done_id = open_session(harness, token, bomb, fmt="markdown", encoding=GZIP)
    for sequence, chunk in enumerate(pieces(bomb)):
        ok(single(harness, token, WRITE_TOOL, APPEND, append_payload(done_id, sequence, chunk)))
    state = State(harness, store_root)
    (refused,) = harness.run([(token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": done_id}))])
    code, details = refusal(refused)
    assert code == "invalid_request"
    assert "transfer" in details
    state.unchanged()
    print("\ngzip bomb:", problem(refused))


def test_the_begin_quota_is_rate_limited(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    for n in range(4):
        open_session(harness, token, markdown_text(1000 + n, seed=70 + n))
    state = State(harness, store_root)
    (fifth,) = harness.run(
        [(token, wrapped(WRITE_TOOL, BEGIN, begin_payload(markdown_text(2000, seed=80))))]
    )
    assert refusal(fifth)[0] == "rate_limited"
    state.unchanged()
    print("\nquota:", problem(fifth))


def test_a_refusal_echoes_no_chunk_token_or_digest(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    done = upload(harness, token, _STAGED)
    session_id = open_session(harness, token, markdown_text(3 * CHUNK, seed=67))
    answers = harness.run(
        [
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, 2, _STAGED[:CHUNK]))),
            (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": session_id})),
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {**MINIMAL, "content": reference(session_id, done.content_token)},
                ),
            ),
        ]
    )
    chunk_b64 = base64.b64encode(_STAGED[:CHUNK]).decode()
    for answer in answers:
        assert outcome(answer)[0]
        rendered = json.dumps(answer.document)
        for secret in (chunk_b64[:24], done.content_token[6:30], done.content_token):
            assert secret not in rendered


def test_profile_grants_are_the_planners(harness: Harness) -> None:
    """Sanity: the grants every test above starts from include the five, exactly stamped."""
    assert set(transfer_grants(harness.service)) >= {
        grant_row(capability) for capability in TRANSFER
    }
    assert len(profile_grants(harness.service)) == len(transfer_grants(harness.service))
