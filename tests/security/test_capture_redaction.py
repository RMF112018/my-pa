"""`QC-AC-041`: capture text reaches no log, no audit row, no error payload, and no URL.

The plan's paraphrase at `:591-592` named three sinks — logs, audit rows, error
payloads. `docs/specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:214`
names telemetry, **URL parameters**, and lock-screen notifications as well, and
`D-75` rules that the spec governs. Of the three the plan omitted, **URL
parameters is live for WP-6**: `capture.create` is reachable over HTTP, and a
transport that accepted the note in a query string would put it in a request
line, an access log, a proxy log, and a browser history in one step. So this
module covers four sinks, not three.

**The subject is a distinctive synthetic sentinel**, so an assertion cannot pass
because the text happened to be a common word. It is swept for across *every
column of every row* of the whole capture plane and the audit table — rendered
as JSON per row rather than column by column, so a column added to a table is
covered without this file being edited — and it is required to appear in exactly
one place: the `content` column of the version that stores it.

**The control is the whole point.** A build that stored nothing at all would
satisfy every absence here. So the same test reads the sentinel back through
`capture.read` and requires it *verbatim*, and the sweep requires exactly one
occurrence rather than none. An absence beside a presence is a boundary; an
absence on its own is an empty database.

The log assertion carries its own control too: the request is made over a real
loopback socket so uvicorn's own records are captured, and `caplog` is required
to be non-empty before the sentinel's absence from it means anything.

The database is disposable, created and dropped by its fixture, and never the
configured one. No path is opened, no source is reached, and the only socket
bound is a loopback one.
"""

from __future__ import annotations

import io
import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from tests.wire import serve

from my_pa.adapters.http import PATH_TEMPLATE, create_http_app
from my_pa.application.commands import Command, CreateCapture, ReadCapture
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_capture_redaction_test"

#: A token that occurs nowhere else in this repository, so finding it anywhere
#: is finding *this* capture's text and not a coincidence.
SENTINEL: Final = "zamboni-quokka-7741"

CONTENT: Final = f"a private note whose only distinguishing word is {SENTINEL}"

#: A second text carrying the same sentinel, used to provoke the conflict whose
#: error payload must carry neither.
OTHER_CONTENT: Final = f"a different private note, also mentioning {SENTINEL}"

#: Every table a capture request writes to, plus the audit table. Swept whole.
_TABLES: Final = (
    "knowledge.captures",
    "knowledge.capture_versions",
    "knowledge.capture_receipts",
    "knowledge.capture_submissions",
    "knowledge.capture_jobs",
    "knowledge.audit_events",
)

WHEN: Final = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
WHEN_WIRE: Final = "2026-08-03T12:00:00Z"


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[GatewayRuntime]:
    built = build_gateway_runtime(Settings(database_url=disposable_database))
    try:
        with built.work_engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {', '.join(_TABLES)} CASCADE"))
        yield built
    finally:
        built.close()


def _invoke(
    runtime: GatewayRuntime, capability: Capability, purpose: Purpose, request: Command, tag: str
) -> ResponseEnvelope:
    return runtime.service.invoke(
        RequestMetadata(
            request_id=f"req-redaction-{tag}",
            capability=capability,
            purpose=purpose,
            principal_id=runtime.principal.principal_id,
            requested_at=WHEN,
        ),
        request,
        principal=runtime.principal,
    )


def _rows_as_json(engine: Engine) -> dict[str, list[str]]:
    """Every row of every capture table, rendered whole.

    `row_to_json` rather than a column list, so a column added to any of these
    tables is swept without this file being edited — which is the difference
    between a sweep and a list that rots.
    """
    with engine.connect() as connection:
        return {
            table: [
                str(row[0])
                # S608: every name is a literal in `_TABLES`; nothing here is input.
                for row in connection.execute(
                    text(f"SELECT row_to_json(t)::text FROM {table} t")  # noqa: S608
                )
            ]
            for table in _TABLES
        }


def _document(runtime: GatewayRuntime, purpose: Purpose, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": "req-redaction-url",
        "purpose": purpose.value,
        "principal_id": runtime.principal.principal_id,
        "requested_at": WHEN_WIRE,
        "payload": payload,
    }


@pytest.mark.database
def test_the_stored_text_appears_in_exactly_one_column_and_reads_back_verbatim(
    runtime: GatewayRuntime,
) -> None:
    """The sweep, and the control that makes its zeros mean something.

    One occurrence, in `capture_versions.content`, and the same text back out of
    `capture.read`. A build that stored nothing would fail both halves; a build
    that copied the note into the submission row, the receipt, or the audit
    event would fail the first.
    """
    receipt = _invoke(
        runtime,
        Capability.CAPTURE_CREATE,
        Purpose.CAPTURE_AUTHORING,
        CreateCapture(text=CONTENT, idempotency_key="redaction-1"),
        "create",
    )
    assert receipt.error is None and receipt.result is not None
    stored = receipt.result

    # --- the receipt the caller keeps carries no text ---------------------------
    assert SENTINEL not in json.dumps(stored), (
        "the acknowledgement quoted the note back. A receipt is the thing a "
        "caller keeps and the digest is what lets it verify what was stored"
    )
    assert stored["content_sha256"]

    # --- the sweep --------------------------------------------------------------
    rows = _rows_as_json(runtime.work_engine)
    assert rows["knowledge.audit_events"], (
        "no audit event was written at all, so its silence about the note proves "
        "nothing about redaction"
    )
    carrying = {
        table: [row for row in table_rows if SENTINEL in row] for table, table_rows in rows.items()
    }
    assert len(carrying["knowledge.capture_versions"]) == 1, (
        "the stored version does not hold the note, so every absence below is an "
        "absence from an empty store"
    )
    elsewhere = {
        table: found
        for table, found in carrying.items()
        if table != "knowledge.capture_versions" and found
    }
    assert elsewhere == {}, (
        f"capture text reached a table that is not the version that stores it: "
        f"{sorted(elsewhere)}. The audit event, the submission, the receipt and "
        "the queued job carry identifiers, counts and digests only"
    )

    # --- and the note is retrievable, verbatim ----------------------------------
    read = _invoke(
        runtime,
        Capability.CAPTURE_READ,
        Purpose.CAPTURE_REVIEW,
        ReadCapture(capture_id=stored["capture_id"]),
        "read",
    )
    assert read.error is None and read.result is not None
    assert read.result["text"] == CONTENT, (
        "the note did not read back as written. `QC-AC-041` is about where the "
        "text must not go; a build that stored nothing satisfies that trivially "
        "and this is what refuses to accept it"
    )


@pytest.mark.database
def test_a_refused_capture_reports_no_part_of_either_note(runtime: GatewayRuntime) -> None:
    """The error-payload sink, provoked by a real refusal rather than constructed.

    Two notes, one key. The refusal has to name the key and nothing else — not
    the stored text, not the submitted text, and not which of them differed,
    because that would describe the stored request to whoever guessed the key.
    """
    first = _invoke(
        runtime,
        Capability.CAPTURE_CREATE,
        Purpose.CAPTURE_AUTHORING,
        CreateCapture(text=CONTENT, idempotency_key="redaction-conflict"),
        "conflict-1",
    )
    assert first.error is None

    refused = _invoke(
        runtime,
        Capability.CAPTURE_CREATE,
        Purpose.CAPTURE_AUTHORING,
        CreateCapture(text=OTHER_CONTENT, idempotency_key="redaction-conflict"),
        "conflict-2",
    )
    assert refused.error is not None
    assert refused.error.code == ErrorCode.CONFLICT
    assert list(refused.error.safe_details) == ["idempotency_key"]

    rendered = repr(refused)
    assert SENTINEL not in rendered, f"the refusal carried the note: {rendered}"
    assert SENTINEL not in refused.error.to_canonical_json()

    # A refusal that names an absent capture is the other error shape a caller
    # can reach with content in hand, and it discloses no more.
    missing = _invoke(
        runtime,
        Capability.CAPTURE_READ,
        Purpose.CAPTURE_REVIEW,
        ReadCapture(capture_id="cap_thiscaptureisnotstoredanywhere"),
        "missing",
    )
    assert missing.error is not None and missing.error.code == ErrorCode.NOT_FOUND
    assert SENTINEL not in repr(missing)


@pytest.mark.database
def test_no_log_record_carries_the_note_over_a_real_socket(
    runtime: GatewayRuntime, caplog: pytest.LogCaptureFixture
) -> None:
    """The log sink, with a control that says the capture is capturing.

    The request is made over a real loopback socket precisely so that uvicorn's
    own records exist: an assertion that `caplog.text` lacks the sentinel is
    worth nothing if `caplog` collected nothing at all.
    """
    application = create_http_app(runtime.service, principal=runtime.principal)
    with caplog.at_level(logging.DEBUG), serve(application) as wire:
        answer = wire.send(
            Capability.CAPTURE_CREATE.value,
            _document(
                runtime,
                Purpose.CAPTURE_AUTHORING,
                {"text": CONTENT, "idempotency_key": "redaction-log"},
            ),
        )

    assert answer.status == 200, answer.body
    assert caplog.records, (
        "no log record was captured at all, so the absence of the note from the "
        "log is an absence from an empty log"
    )
    assert SENTINEL not in caplog.text, "capture text reached a log record"
    assert SENTINEL not in answer.rendered(), (
        "the note came back in the acknowledgement's status line, headers, or body"
    )


@pytest.mark.database
def test_capture_text_in_a_url_is_refused_and_stored_nowhere(runtime: GatewayRuntime) -> None:
    """The sink the plan omitted (`D-75`): a note in a query string is not a request.

    A request line reaches an access log, a proxy log and a browser history
    before anything in this repository sees it, so the only safe answer is that
    the transport never reads one. Asserted three ways: the address a capability
    is reached at has no place for content; a request carrying the note in a
    query parameter and not in its body is **refused**; and nothing is stored as
    a result.

    The control is the same request with the note in the body, which succeeds —
    so the refusal is about *where* the text was, not about the transport being
    broken.
    """
    assert "{capability}" in PATH_TEMPLATE
    assert PATH_TEMPLATE.count("{") == 1, (
        f"the address template is {PATH_TEMPLATE!r}; a second placeholder would "
        "be a second thing a caller puts in a URL"
    )

    application = create_http_app(runtime.service, principal=runtime.principal)
    with serve(application) as wire:
        smuggled = wire.send(
            Capability.CAPTURE_CREATE.value,
            _document(runtime, Purpose.CAPTURE_AUTHORING, {"idempotency_key": "redaction-url"}),
            path=f"/v1/{Capability.CAPTURE_CREATE.value}?text={SENTINEL}",
        )
        assert smuggled.status != 200, (
            "a request whose only text was in the query string was accepted. The "
            "transport reads the body and the capability from the path, and "
            "nothing else from the URL"
        )
        # A refusal raised by normalization, before the service, is the bare
        # problem detail rather than an envelope carrying one — the same shape
        # `tests/contract/test_http_transport.py` asserts for a malformed body.
        assert smuggled.document()["code"] == ErrorCode.INVALID_REQUEST.value
        assert SENTINEL not in smuggled.rendered()

        # The control: the same request, with the note where a request carries
        # one, is accepted.
        proper = wire.send(
            Capability.CAPTURE_CREATE.value,
            _document(
                runtime,
                Purpose.CAPTURE_AUTHORING,
                {"text": CONTENT, "idempotency_key": "redaction-url-body"},
            ),
        )
        assert proper.status == 200, proper.body

    rows = _rows_as_json(runtime.work_engine)
    versions = [row for row in rows["knowledge.capture_versions"] if SENTINEL in row]
    assert len(versions) == 1, (
        f"{len(versions)} versions hold the note. The refused request stored "
        "nothing and the accepted one stored it once"
    )
