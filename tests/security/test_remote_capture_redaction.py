"""`QC-AC-041` on the remote ingress: no note in a log, a URL, a row, or an error.

WP-10's fourth control. `tests/security/test_capture_redaction.py` proves the
four sinks for a locally submitted capture; this proves them for the one path
where a note crosses a credential boundary — and it is the path most likely to be
quietly violated, because an ingress is exactly where an implementer reaches for
a log line to debug an authentication failure.

**Five sinks, not four.** The four that module names — logs, rows, error
payloads, URL parameters — plus **the credential**, which only exists here. A
client secret in a log record is the same class of defect as a note in one, and
the same sweep finds both because both are distinctive synthetic sentinels.

**Every zero sits beside a non-zero.** The log assertion runs over a real
loopback server so uvicorn's own records exist and `caplog` is required to be
non-empty first; the row sweep requires the note to appear exactly once, in the
column that stores it, before it requires it to appear nowhere else; and the URL
refusal is paired with the same request in a body, which succeeds. An absence on
its own is an empty database.

**The URL sink is closed by refusal rather than by omission.** The ingress
refuses any query string at all, so a caller that put its note in `?text=` is
told no — rather than being told yes about a request whose body happened to carry
the note as well. That is a stronger property than `/v1/{capability}`'s, and the
test drives it directly.

The database is disposable, created and dropped by this module's fixture, and is
never the configured one. Every value is synthetic.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.wire import Reply, Wire, serve

from my_pa.adapters.http import REMOTE_CAPTURE_CAPABILITY, REMOTE_CAPTURE_PATH, create_http_app
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime, local_principal
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.client import issue_client_secret
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.capture_clients import register_client
from my_pa.infrastructure.persistence.principal_scope import capture_context

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_remote_redaction_test"

#: A token that occurs nowhere else in this repository, so finding it anywhere is
#: finding *this* capture's text and not a coincidence.
SENTINEL: Final = "quokka-marmoset-8813"

CONTENT: Final = f"a private note whose only distinguishing word is {SENTINEL}"

#: A second note carrying the same sentinel, used to provoke the conflict whose
#: error payload must carry neither.
OTHER_CONTENT: Final = f"a different private note, also mentioning {SENTINEL}"

#: Every table a remote capture request writes to, plus the audit and client
#: tables. Swept whole with `row_to_json`, so a column added to any of them is
#: covered without this file being edited.
_TABLES: Final = (
    "knowledge.captures",
    "knowledge.capture_versions",
    "knowledge.capture_receipts",
    "knowledge.capture_submissions",
    "knowledge.capture_jobs",
    "knowledge.capture_clients",
    "knowledge.audit_events",
)

WHEN_WIRE: Final = "2026-08-10T12:00:00Z"


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[GatewayRuntime]:
    built = build_gateway_runtime(
        Settings(database_url=disposable_database, remote_ingress_enabled=True)
    )
    try:
        with built.work_engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {', '.join(_TABLES)} CASCADE"))
        yield built
    finally:
        built.close()


@pytest.fixture
def credential(runtime: GatewayRuntime) -> str:
    """One registered client for the process principal, as a whole header value."""
    secret, digest = issue_client_secret()
    with runtime.work_engine.begin() as connection:
        client = register_client(
            connection,
            secret_sha256=digest,
            at=datetime.now(UTC),
            context=capture_context(local_principal().principal_id),
        )
    return f"ClientCredential {client.client_id}:{secret}"


def document(key: str, *, note: str = CONTENT) -> dict[str, Any]:
    return {
        "request_id": f"req-remote-{key}",
        "purpose": Purpose.CAPTURE_AUTHORING.value,
        "requested_at": WHEN_WIRE,
        "payload": {"text": note, "idempotency_key": key},
    }


def submit(wire: Wire, credential: str, body: dict[str, Any], *, path: str | None = None) -> Reply:
    return wire.send(
        REMOTE_CAPTURE_CAPABILITY,
        body,
        path=path or REMOTE_CAPTURE_PATH,
        extra_headers={"authorization": credential},
    )


def _rows_as_json(engine: Engine) -> dict[str, list[str]]:
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


@pytest.mark.database
def test_no_log_record_carries_the_note_or_the_credential(
    runtime: GatewayRuntime, credential: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The log sink, with the control that says the capture is capturing.

    The request goes over a real loopback socket precisely so uvicorn's own
    records exist: asserting that `caplog.text` lacks the sentinel is worth
    nothing if `caplog` collected nothing at all.

    The credential is swept alongside the note. An ingress is where a helpful
    `logger.info("client %s presented", credential)` is most tempting, and a
    secret in a log file is a credential disclosure whatever the intent.
    """
    application = create_http_app(
        runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
    )
    with caplog.at_level(logging.DEBUG), serve(application) as wire:
        answer = submit(wire, credential, document("redaction-log"))

    assert answer.status == 200, answer.body
    assert caplog.records, (
        "no log record was captured at all, so the absence of the note from the "
        "log is an absence from an empty log"
    )
    assert SENTINEL not in caplog.text, "capture text reached a log record"
    secret = credential.split(":", 1)[1]
    assert secret not in caplog.text, "a client secret reached a log record"
    assert SENTINEL not in answer.rendered(), (
        "the note came back in the acknowledgement's status line, headers, or body"
    )
    assert secret not in answer.rendered()


@pytest.mark.database
def test_a_failed_authentication_logs_nothing_about_the_credential(
    runtime: GatewayRuntime, caplog: pytest.LogCaptureFixture
) -> None:
    """The sink an ingress adds, on the path an implementer most wants to debug.

    A refused credential is the one event where writing the presented value
    somewhere feels justified. Nothing does, and the control is the same as
    above: real records exist, and the presented value is not among them.
    """
    presented = "ClientCredential cclt_nosuchclientexistsanywhereatall0:synthetic-refused-secret"
    application = create_http_app(
        runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
    )
    with caplog.at_level(logging.DEBUG), serve(application) as wire:
        refused = submit(wire, presented, document("redaction-refused"))

    assert refused.status == 401
    assert caplog.records, "no log record was captured at all"
    assert "synthetic-refused-secret" not in caplog.text
    assert "cclt_nosuchclientexistsanywhereatall0" not in caplog.text
    assert "synthetic-refused-secret" not in refused.rendered()


@pytest.mark.database
def test_the_remote_note_appears_in_exactly_one_column(
    runtime: GatewayRuntime, credential: str
) -> None:
    """The row sweep, and the presence that makes its zeros mean something.

    One occurrence, in `capture_versions.content`. A build that copied the note
    into the submission row, the receipt, the queued job, the client row or the
    audit event fails the second half; a build that stored nothing fails the
    first.
    """
    application = create_http_app(
        runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
    )
    with serve(application) as wire:
        answer = submit(wire, credential, document("redaction-rows"))
    assert answer.status == 200, answer.body

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
        f"capture text reached a table that is not the version that stores it: {sorted(elsewhere)}"
    )

    secret = credential.split(":", 1)[1]
    holding = {table: [row for row in found if secret in row] for table, found in rows.items()}
    assert not any(holding.values()), (
        f"the client secret reached a stored row: {sorted(t for t, f in holding.items() if f)}. "
        "It is stored as a SHA-256 digest and nowhere else"
    )


@pytest.mark.database
def test_a_note_in_the_query_string_is_refused_and_stored_nowhere(
    runtime: GatewayRuntime, credential: str
) -> None:
    """The URL sink, closed by refusal at the ingress rather than by omission.

    Three assertions and a control. The address carries no placeholder, so there
    is nothing a caller could substitute; a request whose URL carries the note is
    refused even though its body is complete and would have succeeded; and
    nothing is stored as a result. The control is the same body without the query
    string, which is accepted — so the refusal is about *where* the text was.
    """
    assert "{" not in REMOTE_CAPTURE_PATH
    assert "?" not in REMOTE_CAPTURE_PATH

    application = create_http_app(
        runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
    )
    with serve(application) as wire:
        smuggled = submit(
            wire,
            credential,
            document("redaction-url"),
            path=f"{REMOTE_CAPTURE_PATH}?text={SENTINEL}",
        )
        assert smuggled.status == 400, (
            "a request carrying the note in its query string was accepted. A "
            "request line reaches an access log, a proxy log and a device history "
            "before anything in this repository sees it"
        )
        assert smuggled.document()["code"] == ErrorCode.INVALID_REQUEST.value
        assert SENTINEL not in smuggled.rendered()

        proper = submit(wire, credential, document("redaction-url-body"))
        assert proper.status == 200, proper.body

    rows = _rows_as_json(runtime.work_engine)
    versions = [row for row in rows["knowledge.capture_versions"] if SENTINEL in row]
    assert len(versions) == 1, (
        f"{len(versions)} versions hold the note. The refused request stored "
        "nothing and the accepted one stored it once"
    )


@pytest.mark.database
def test_a_refused_remote_capture_reports_no_part_of_either_note(
    runtime: GatewayRuntime, credential: str
) -> None:
    """The error-payload sink, provoked by a real conflict rather than constructed.

    Two notes, one key, over the ingress. The refusal names the key and nothing
    else — not the stored text, not the submitted text, and not which of them
    differed, because that would describe the stored request to whoever guessed
    the key.
    """
    application = create_http_app(
        runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
    )
    with serve(application) as wire:
        first = submit(wire, credential, document("redaction-conflict"))
        assert first.status == 200
        refused = submit(wire, credential, document("redaction-conflict", note=OTHER_CONTENT))

    assert refused.status == 409
    problem = refused.document()["error"]
    assert problem["code"] == ErrorCode.CONFLICT.value
    assert problem["safe_details"] == ["idempotency_key"]
    assert SENTINEL not in refused.rendered(), f"the refusal carried the note: {refused.rendered()}"
