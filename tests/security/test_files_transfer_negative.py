"""Files workspace WP6a: what the section 10 byte routes refuse, on PostgreSQL.

The `database` tier, over the contract harness (`tests/contract/
test_files_transfer_routes.py`): a real uvicorn on loopback, a registered
remote client, tickets begun through `invoke`. It proves:

* one undistinguished 401 `ticket_invalid` for no, malformed, unknown,
  other-kind, other-id, expired, aborted and local-transport tickets;
* a query string is 400, a token in it included;
* the grant re-check runs on every request: a revoked `files.upload.begin`
  grant, a revoked or disabled client, remote access off, or writes off is 403
  `denied` on the next request -- mid-upload -- while a download still works
  with only writes off;
* a declared `Content-Length` over 32 MiB is 413 before the body is read; bytes
  streamed past the ceiling are 413 and the staged offset is unchanged;
* the per-process slot cap answers 503 with `Retry-After`; a stalled body
  releases its slot after the idle bound (408);
* a bad ticket is refused before it takes a slot or waits on an upload's lock,
  so a flood of them against a live upload starves no valid request;
* a download whose reader stalls releases its slot after the idle bound, and an
  expired ticket, a revoked grant or the deadline stops a stream mid-way;
* every held-open download file is closed again, a 416 included -- repeated
  unsatisfiable ranges leak no descriptor;
* no answer, header or log record carries the token, the path or body bytes,
  and the MCP interaction log does not see `/files/v1/*`.
"""

from __future__ import annotations

import http.client
import logging
import os
import socket
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text, update
from tests.contract.test_files_transfer_routes import (
    OAUTH_CLIENT,
    RESOURCE,
    SCOPE,
    WORKSPACE,
    Answer,
    Harness,
    Http,
    sha,
)
from tests.wire import serve

from my_pa.adapters.http.files_transfer import build_file_transfer_routes
from my_pa.adapters.mcp.remote import MCP_PATH, create_remote_mcp_app
from my_pa.adapters.mcp_interaction_capture import McpInteractionCapture
from my_pa.application.commands import AbortFileUpload
from my_pa.application.file_transfer import FileTransferGate
from my_pa.contracts.ports import FileTransferKind
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.vocabulary import MAX_UPLOAD_CHUNK_BYTES, FilesReason
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.file_workspace import store
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_capability_grants,
    remote_clients,
    remote_security_controls,
)

pytestmark = pytest.mark.database

TICKET_INVALID = {"error": "denied", "reason": "ticket_invalid"}
DENIED = {"error": "denied", "reason": None}
BODY_MARKER = b"SYNTHETIC-BODY-MARKER-7f3a"
BUSY = {"error": "unavailable", "reason": None}


def _body(answer: Answer, expected: object) -> object:
    """The JSON error document; a HEAD answer has no body, so it must be empty."""
    if answer.method == "HEAD":
        assert answer.content == b""
        return expected
    return answer.json()


@pytest.fixture
def harness(cloned_database_url: str, tmp_path: Path) -> Iterator[Harness]:
    root = tmp_path / "workspace"
    root.mkdir()
    built = Harness(cloned_database_url, root)
    try:
        yield built
    finally:
        built.close()


def _build(url: str, tmp_path: Path, **options: Any) -> Harness:  # noqa: ANN401
    root = tmp_path / "workspace"
    root.mkdir()
    return Harness(url, root, **options)


# ---- authentication -------------------------------------------------------------


def test_every_bad_ticket_is_one_undistinguished_401(harness: Harness) -> None:
    upload_id, token = harness.begin_upload("a.bin")
    other_id, other_token = harness.begin_upload("b.bin")
    harness.write("d.txt", "download synthetic")
    download = harness.begin_download("d.txt")
    unknown = "gfwtk_" + "a" * 64
    path = f"/files/v1/uploads/{upload_id}"
    cases: list[dict[str, str]] = [
        {},
        {"Authorization": f"bearer {token}"},
        {"Authorization": f"Bearer  {token}"},
        {"Authorization": f"Basic {token}"},
        {"Authorization": "Bearer gfwtk_short"},
        {"Authorization": f"Bearer {unknown}"},
        {"Authorization": f"Bearer {other_token}"},  # another upload's token
        {"Authorization": f"Bearer {download['download_token']}"},  # other kind
    ]
    for headers in cases:
        for answer in (
            harness.client.head(path, headers),
            harness.client.patch(path, content=b"x", headers={**headers, "Upload-Offset": "0"}),
        ):
            assert answer.status_code == 401, headers
            assert _body(answer, TICKET_INVALID) == TICKET_INVALID
    # Authenticated before any header is parsed: malformed upload headers with a
    # bad ticket are the same 401, never the 400 a valid ticket would earn.
    for malformed in (
        {},
        {"Upload-Offset": "-1"},
        {"Upload-Offset": "0", "Upload-Complete": "length=1, sha256=" + "0" * 64},
    ):
        for headers in ({}, {"Authorization": f"Bearer {unknown}"}):
            answer = harness.client.patch(path, content=b"x", headers={**headers, **malformed})
            assert answer.status_code == 401, (headers, malformed)
            assert answer.json() == TICKET_INVALID
    # An id of the other kind on each route, with its own valid token.
    wrong_route = harness.client.get(f"/files/v1/downloads/{upload_id}", harness.bearer(token))
    assert (wrong_route.status_code, _body(wrong_route, TICKET_INVALID)) == (401, TICKET_INVALID)
    wrong_route = harness.client.head(
        f"/files/v1/uploads/{download['download_id']}",
        harness.bearer(download["download_token"]),
    )
    assert (wrong_route.status_code, _body(wrong_route, TICKET_INVALID)) == (401, TICKET_INVALID)
    # Nothing was staged by any refused PATCH.
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "0"
    assert harness.head(other_id, other_token).headers["Upload-Offset"] == "0"


def test_an_aborted_ticket_is_401(harness: Harness) -> None:
    upload_id, token = harness.begin_upload("ab.bin")
    harness.ok(
        AbortFileUpload(
            workspace_id=WORKSPACE,
            upload_id=upload_id,
            idempotency_key=issue_identifier(IdKind.CORRELATION),
        )
    )
    answer = harness.patch(upload_id, token, b"x", 0)
    assert (answer.status_code, _body(answer, TICKET_INVALID)) == (401, TICKET_INVALID)


def test_an_expired_ticket_opens_nothing(harness: Harness) -> None:
    upload_id, token = harness.begin_upload("ex.bin")
    later = FileTransferGate(
        service=harness.service,
        store=harness.gate._store,
        unit_of_work=harness.gate._unit_of_work,
        standing=harness.gate._standing,
        workspace_id=WORKSPACE,
        max_upload_bytes=1 << 20,
        remote_writes_enabled=True,
        clock=lambda: datetime.now(UTC) + timedelta(days=2),
    )
    with pytest.raises(FilesRefusal) as refused:
        later.authenticate(FileTransferKind.UPLOAD, upload_id, f"Bearer {token}")
    assert refused.value.reason is FilesReason.TICKET_INVALID


def test_a_local_transport_ticket_is_refused_at_the_remote_routes(harness: Harness) -> None:
    upload_id, token = harness.begin_upload("local.bin", transport=CaptureTransport.LOCAL)
    for answer in (harness.head(upload_id, token), harness.patch(upload_id, token, b"x", 0)):
        assert (answer.status_code, _body(answer, TICKET_INVALID)) == (401, TICKET_INVALID)


def test_a_query_string_is_refused_even_with_a_valid_token(harness: Harness) -> None:
    upload_id, token = harness.begin_upload("q.bin")
    path = f"/files/v1/uploads/{upload_id}"
    for query in ("?x=1", f"?token={token}", f"?access_token={token}"):
        answer = harness.client.head(path + query, harness.bearer(token))
        assert answer.status_code == 400
        answered = harness.client.patch(
            path + query, content=BODY_MARKER, headers={"Upload-Offset": "0"}
        )
        assert answered.status_code == 400
        assert answered.json() == {"error": "invalid_request", "reason": None}
        assert token not in answered.text
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "0"


# ---- the grant re-check -----------------------------------------------------------


def _revoke_grant(harness: Harness, capability: str) -> None:
    with harness.engine.begin() as connection:
        connection.execute(
            update(remote_capability_grants)
            .where(remote_capability_grants.c.capability == capability)
            .values(revoked_at=datetime.now(UTC))
        )


def test_a_revoked_grant_is_403_on_the_next_request_mid_upload(harness: Harness) -> None:
    body = b"revocation synthetic"
    upload_id, token = harness.begin_upload("rv.bin")
    assert harness.patch(upload_id, token, body[:5], 0).status_code == 204
    _revoke_grant(harness, "files.upload.begin")
    for answer in (
        harness.patch(upload_id, token, body[5:], 5),
        harness.head(upload_id, token),
        harness.patch(upload_id, token, b"", 5, complete=(sha(body), len(body))),
    ):
        assert (answer.status_code, _body(answer, DENIED)) == (403, DENIED)
    assert not (harness.root / "rv.bin").exists()


def test_a_revoked_download_grant_is_403(harness: Harness) -> None:
    harness.write("rd.txt", "download grant synthetic")
    ticket = harness.begin_download("rd.txt")
    assert harness.get(ticket["download_id"], ticket["download_token"]).status_code == 200
    _revoke_grant(harness, "files.download.begin")
    answer = harness.get(ticket["download_id"], ticket["download_token"])
    assert (answer.status_code, _body(answer, DENIED)) == (403, DENIED)


def test_finalize_without_its_own_grant_is_403_and_publishes_nothing(harness: Harness) -> None:
    body = b"finalize grant synthetic"
    upload_id, token = harness.begin_upload("fg.bin")
    _revoke_grant(harness, "files.upload.finalize")
    answer = harness.patch(upload_id, token, body, 0, complete=(sha(body), len(body)))
    assert (answer.status_code, answer.json()) == (403, DENIED)
    assert not (harness.root / "fg.bin").exists()


@pytest.mark.parametrize("change", ["revoked", "disabled", "remote_off"])
def test_a_client_that_may_no_longer_act_is_403(harness: Harness, change: str) -> None:
    upload_id, token = harness.begin_upload("c.bin")
    harness.write("c.txt", "client synthetic")
    ticket = harness.begin_download("c.txt")
    with harness.engine.begin() as connection:
        if change == "revoked":
            RemoteIdentityRepository(connection).revoke_client(
                oauth_client_id=OAUTH_CLIENT, now=datetime.now(UTC)
            )
        elif change == "disabled":
            connection.execute(update(remote_clients).values(enabled=False, writes_enabled=False))
        else:
            connection.execute(update(remote_security_controls).values(remote_enabled=False))
    for answer in (
        harness.head(upload_id, token),
        harness.patch(upload_id, token, b"x", 0),
        harness.get(ticket["download_id"], ticket["download_token"]),
    ):
        assert (answer.status_code, _body(answer, DENIED)) == (403, DENIED), change


@pytest.mark.parametrize("switch", ["client", "global"])
def test_writes_off_refuses_uploads_while_downloads_still_work(
    harness: Harness, switch: str
) -> None:
    upload_id, token = harness.begin_upload("w.bin")
    harness.write("w.txt", "writes synthetic")
    ticket = harness.begin_download("w.txt")
    with harness.engine.begin() as connection:
        if switch == "client":
            connection.execute(update(remote_clients).values(writes_enabled=False))
        else:
            connection.execute(update(remote_security_controls).values(writes_enabled=False))
    answer = harness.patch(upload_id, token, b"x", 0)
    assert (answer.status_code, _body(answer, DENIED)) == (403, DENIED)
    served = harness.get(ticket["download_id"], ticket["download_token"])
    assert served.status_code == 200
    assert served.content == b"writes synthetic"


def test_the_process_writes_switch_refuses_uploads(
    cloned_database_url: str, tmp_path: Path
) -> None:
    built = _build(cloned_database_url, tmp_path, remote_writes_enabled=False)
    try:
        upload_id, token = built.begin_upload("p.bin")
        built.write("p.txt", "process switch synthetic")
        ticket = built.begin_download("p.txt")
        answer = built.patch(upload_id, token, b"x", 0)
        assert (answer.status_code, _body(answer, DENIED)) == (403, DENIED)
        assert built.get(ticket["download_id"], ticket["download_token"]).status_code == 200
    finally:
        built.close()


# ---- size bounds ----------------------------------------------------------------------


def test_a_declared_length_over_32_mib_is_413_before_the_body_is_read(
    harness: Harness,
) -> None:
    upload_id, token = harness.begin_upload("big.bin")
    connection = http.client.HTTPConnection("127.0.0.1", harness.client.port, timeout=10)
    try:
        connection.putrequest("PATCH", f"/files/v1/uploads/{upload_id}")
        connection.putheader("Authorization", f"Bearer {token}")
        connection.putheader("Upload-Offset", "0")
        connection.putheader("Content-Length", str(MAX_UPLOAD_CHUNK_BYTES + 1))
        connection.endheaders()
        # No body byte is sent: an answer can only come from the headers.
        response = connection.getresponse()
        assert response.status == 413
        assert response.read() == b'{"error":"invalid_request","reason":"too_large"}'
    finally:
        connection.close()
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "0"


def test_a_declared_length_past_the_declared_size_is_413_before_reading(
    harness: Harness,
) -> None:
    upload_id, token = harness.begin_upload("decl.bin", size=8)
    assert harness.patch(upload_id, token, b"1234", 0).status_code == 204
    connection = http.client.HTTPConnection("127.0.0.1", harness.client.port, timeout=10)
    try:
        connection.putrequest("PATCH", f"/files/v1/uploads/{upload_id}")
        connection.putheader("Authorization", f"Bearer {token}")
        connection.putheader("Upload-Offset", "4")
        connection.putheader("Content-Length", "5")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
    finally:
        connection.close()
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "4"


def test_chunked_bytes_past_the_ceiling_are_413_and_the_offset_is_unchanged(
    harness: Harness,
) -> None:
    upload_id, token = harness.begin_upload("chunked.bin", size=10)
    assert harness.patch(upload_id, token, b"12", 0).status_code == 204
    answer = harness.client.request(
        "PATCH",
        f"/files/v1/uploads/{upload_id}",
        headers={**harness.bearer(token), "Upload-Offset": "2"},
        chunks=[b"abcd", b"efgh", b"ijkl"],
    )
    assert answer.status_code == 413
    assert answer.json() == {"error": "invalid_request", "reason": "too_large"}
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "2"


def test_the_32_mib_request_cap_holds_whatever_the_framing(
    cloned_database_url: str, tmp_path: Path
) -> None:
    """The cap is the gate's ceiling, so a body with no `Content-Length` meets it too."""
    built = _build(cloned_database_url, tmp_path, max_upload_bytes=64 << 20)
    try:
        upload_id, token = built.begin_upload("cap.bin")
        access = built.gate.authenticate(FileTransferKind.UPLOAD, upload_id, f"Bearer {token}")
        assert built.gate.upload_ceiling(access, 0) == MAX_UPLOAD_CHUNK_BYTES
        chunk = b"\0" * (1 << 20)
        with pytest.raises(FilesRefusal) as refused:
            built.gate.append(access, 0, (chunk for _ in range(33)))
        assert refused.value.reason is FilesReason.TOO_LARGE
        assert built.head(upload_id, token).headers["Upload-Offset"] == "0"
    finally:
        built.close()


# ---- concurrency --------------------------------------------------------------------


def _open_chunked_patch(port: int, upload_id: str, token: str) -> http.client.HTTPConnection:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.putrequest("PATCH", f"/files/v1/uploads/{upload_id}")
    connection.putheader("Authorization", f"Bearer {token}")
    connection.putheader("Upload-Offset", "0")
    connection.putheader("Transfer-Encoding", "chunked")
    connection.endheaders()
    connection.send(b"5\r\nhello\r\n")
    return connection


def test_the_slot_cap_answers_503_with_retry_after(
    cloned_database_url: str, tmp_path: Path
) -> None:
    built = _build(cloned_database_url, tmp_path, max_concurrent=1)
    try:
        upload_id, token = built.begin_upload("slot.bin")
        other_id, other_token = built.begin_upload("other.bin")
        held = _open_chunked_patch(built.client.port, upload_id, token)
        try:
            deadline = time.monotonic() + 10
            busy = built.head(other_id, other_token)
            while busy.status_code != 503:
                assert time.monotonic() < deadline, "the held PATCH never took the slot"
                time.sleep(0.05)
                busy = built.head(other_id, other_token)
            assert busy.headers["Retry-After"] == "1"
            assert _body(busy, BUSY) == BUSY
            held.send(b"0\r\n\r\n")
            response = held.getresponse()
            assert response.status == 204
            assert response.getheader("Upload-Offset") == "5"
        finally:
            held.close()
        assert built.head(other_id, other_token).status_code == 204
    finally:
        built.close()


def test_a_stalled_body_releases_its_slot_after_the_idle_bound(
    cloned_database_url: str, tmp_path: Path
) -> None:
    built = _build(cloned_database_url, tmp_path, max_concurrent=1, body_idle_timeout_seconds=0.5)
    try:
        upload_id, token = built.begin_upload("stall.bin")
        held = _open_chunked_patch(built.client.port, upload_id, token)
        try:
            response = held.getresponse()
            assert response.status == 408
        finally:
            held.close()
        # The slot is free again, and what arrived before the stall stayed staged.
        assert built.head(upload_id, token).headers["Upload-Offset"] == "5"
        resumed = built.patch(upload_id, token, b" world", 5)
        assert resumed.status_code == 204
        assert resumed.headers["Upload-Offset"] == "11"
    finally:
        built.close()


def test_bad_tickets_never_take_a_slot_nor_wait_on_an_upload_lock(
    harness: Harness,
) -> None:
    """With the cap at 4 and one upload streaming (its lock held), six PATCHes
    with bad tickets -- four against the live upload -- are 401 at once, and
    valid HEAD, PATCH and GET requests still get a slot."""
    upload_id, token = harness.begin_upload("live.bin")
    other_id, other_token = harness.begin_upload("other.bin")
    harness.write("free.txt", "download while flooded")
    ticket = harness.begin_download("free.txt")
    held = _open_chunked_patch(harness.client.port, upload_id, token)
    flood: list[http.client.HTTPConnection] = []
    try:
        deadline = time.monotonic() + 10
        while harness.head(upload_id, token).headers["Upload-Offset"] != "5":
            assert time.monotonic() < deadline, "the live PATCH never streamed"
            time.sleep(0.05)
        unknown = "gfwtk_" + "c" * 64
        for target, bad in (
            (upload_id, other_token),  # a real token of another upload
            (upload_id, unknown),
            (upload_id, ticket["download_token"]),  # the other kind
            (upload_id, None),  # no Authorization at all
            (other_id, token),
            (other_id, unknown),
        ):
            connection = http.client.HTTPConnection("127.0.0.1", harness.client.port, timeout=10)
            connection.putrequest("PATCH", f"/files/v1/uploads/{target}")
            if bad is not None:
                connection.putheader("Authorization", f"Bearer {bad}")
            connection.putheader("Upload-Offset", "0")
            connection.putheader("Content-Length", "64")  # announced, never sent
            connection.endheaders()
            flood.append(connection)
        started = time.monotonic()
        for connection in flood:
            response = connection.getresponse()
            assert response.status == 401
            assert response.read() == b'{"error":"denied","reason":"ticket_invalid"}'
        assert time.monotonic() - started < 5, "a bad ticket waited (the idle bound is 30 s)"
        # Every refused request answered and held nothing: valid ones still run.
        assert harness.head(other_id, other_token).status_code == 204
        resumed = harness.patch(other_id, other_token, b"abc", 0)
        assert (resumed.status_code, resumed.headers["Upload-Offset"]) == (204, "3")
        served = harness.get(ticket["download_id"], ticket["download_token"])
        assert (served.status_code, served.content) == (200, b"download while flooded")
        held.send(b"0\r\n\r\n")
        response = held.getresponse()
        assert (response.status, response.getheader("Upload-Offset")) == (204, "5")
    finally:
        for connection in flood:
            connection.close()
        held.close()


_BIG_DOWNLOAD_BYTES = 16 << 20


def _open_unread_get(port: int, download_id: str, token: str) -> socket.socket:
    """A GET whose reader keeps a tiny receive window and reads only when told."""
    reader = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reader.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    reader.settimeout(10)
    reader.connect(("127.0.0.1", port))
    reader.sendall(
        (
            f"GET /files/v1/downloads/{download_id} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\n\r\n"
        ).encode()
    )
    return reader


def _read_until_closed(reader: socket.socket) -> int:
    """Every byte left, to the server's close; a hang past the timeout fails."""
    total = 0
    try:
        while block := reader.recv(1 << 16):
            total += len(block)
    except TimeoutError:
        raise AssertionError("the server never closed the stopped stream") from None
    return total


def _big_download(harness: Harness) -> dict[str, Any]:
    (harness.root / "big.bin").write_bytes(b"\x5a" * _BIG_DOWNLOAD_BYTES)
    return harness.begin_download("big.bin")


def test_a_stalled_download_reader_releases_its_slot_after_the_idle_bound(
    cloned_database_url: str, tmp_path: Path
) -> None:
    built = _build(cloned_database_url, tmp_path, max_concurrent=1, body_idle_timeout_seconds=1.0)
    try:
        upload_id, token = built.begin_upload("waiting.bin")
        ticket = _big_download(built)
        reader = _open_unread_get(
            built.client.port, ticket["download_id"], ticket["download_token"]
        )
        try:
            deadline = time.monotonic() + 10
            seen_busy = False
            answer = built.head(upload_id, token)
            while answer.status_code != 204:
                assert answer.status_code == 503
                seen_busy = True
                assert time.monotonic() < deadline, "the stalled GET never released its slot"
                time.sleep(0.02)
                answer = built.head(upload_id, token)
            assert seen_busy, "the GET never held the only slot"
            # The stream was cut, not finished, and the connection is closed.
            assert _read_until_closed(reader) < _BIG_DOWNLOAD_BYTES
        finally:
            reader.close()
    finally:
        built.close()


@pytest.mark.parametrize("change", ["revoked", "expired", "deadline"])
def test_a_download_stops_mid_stream_on_revocation_expiry_or_its_deadline(
    cloned_database_url: str, tmp_path: Path, change: str
) -> None:
    built = _build(
        cloned_database_url,
        tmp_path,
        max_concurrent=1,
        download_recheck_seconds=0.05,
        download_deadline_seconds=1.0 if change == "deadline" else 600.0,
    )
    try:
        upload_id, token = built.begin_upload("after.bin")
        ticket = _big_download(built)
        clock = built.gate._clock
        reader = _open_unread_get(
            built.client.port, ticket["download_id"], ticket["download_token"]
        )
        try:
            received = len(reader.recv(1 << 16))
            assert received > 0
            if change == "revoked":
                _revoke_grant(built, "files.download.begin")
            elif change == "expired":
                # Time passes the ticket's expiry: the gate's clock moves past it.
                built.gate._clock = lambda: datetime.now(UTC) + timedelta(days=2)
            time.sleep(1.2)
            received += _read_until_closed(reader)
            assert received < _BIG_DOWNLOAD_BYTES, change
        finally:
            reader.close()
            built.gate._clock = clock
        # The stopped stream gave its slot back.
        assert built.head(upload_id, token).status_code == 204
    finally:
        built.close()


# ---- privacy ------------------------------------------------------------------------


def test_repeated_unsatisfiable_ranges_close_every_file_they_open(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.write("r.txt", "0123456789")
    harness.write("empty.txt", "")
    sized = harness.begin_download("r.txt")
    empty = harness.begin_download("empty.txt")
    counts = {"opened": 0, "closed": 0}
    held = store._HeldFile
    original_init, original_close = held.__init__, held.close

    def counting_init(self: Any, descriptor: int, status: os.stat_result) -> None:  # noqa: ANN401
        counts["opened"] += 1
        original_init(self, descriptor, status)

    def counting_close(self: Any) -> None:  # noqa: ANN401
        if self._descriptor is not None:
            counts["closed"] += 1
        original_close(self)

    monkeypatch.setattr(held, "__init__", counting_init)
    monkeypatch.setattr(held, "close", counting_close)
    rounds = 25
    for _ in range(rounds):
        past = harness.get(sized["download_id"], sized["download_token"], Range="bytes=10-")
        assert past.status_code == 416
        zero = harness.get(empty["download_id"], empty["download_token"], Range="bytes=0-")
        assert zero.status_code == 416
    assert harness.get(sized["download_id"], sized["download_token"]).status_code == 200
    deadline = time.monotonic() + 10
    while counts["closed"] < counts["opened"]:
        assert time.monotonic() < deadline, counts
        time.sleep(0.01)
    assert counts == {"opened": 2 * rounds + 1, "closed": 2 * rounds + 1}


def test_no_answer_or_log_record_carries_a_token_a_path_or_body_bytes(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret_name = "secret-name-7f3a.bin"  # noqa: S105 - a synthetic file name
    upload_id, token = harness.begin_upload(secret_name, size=4)
    harness.write("secret-download-7f3a.txt", "download body synthetic")
    ticket = harness.begin_download("secret-download-7f3a.txt")
    (harness.root / "secret-download-7f3a.txt").write_text("moved synthetic")
    answers = [
        harness.patch(upload_id, token, BODY_MARKER, 0),  # 413
        harness.patch(upload_id, token, BODY_MARKER[:4], 3),  # 409
        harness.patch(upload_id, "gfwtk_" + "b" * 64, BODY_MARKER, 0),  # 401
        harness.patch(upload_id, token, b"", 0, complete=("0" * 64, 0)),  # 409 digest
        harness.get(ticket["download_id"], ticket["download_token"]),  # 412
        harness.client.patch(
            f"/files/v1/uploads/{upload_id}?t={token}", content=BODY_MARKER
        ),  # 400
    ]
    _revoke_grant(harness, "files.upload.begin")
    answers.append(harness.patch(upload_id, token, BODY_MARKER[:4], 0))  # 403
    assert [answer.status_code for answer in answers] == [413, 409, 401, 409, 412, 400, 403]
    # The production server runs with `access_log=False` (`apps/gateway.py`), so
    # the request line -- where a token a client misplaced in a query string
    # would be -- is never logged there; this harness's access records are left
    # out of the scan for that reason, and every other record is scanned.
    logged = "\n".join(
        record.getMessage() for record in caplog.records if record.name != "uvicorn.access"
    )
    rendered = " ".join(
        f"{answer.status_code} {sorted(answer.headers.items())} {answer.text}" for answer in answers
    )
    for secret in (
        token,
        ticket["download_token"],
        secret_name,
        "secret-download-7f3a",
        str(harness.root),
    ):
        assert secret not in rendered
        assert secret not in logged
    assert BODY_MARKER.decode() not in rendered
    assert BODY_MARKER.decode() not in logged
    with harness.audit_engine.connect() as connection:
        audit = " ".join(
            connection.execute(text("SELECT row_to_json(a)::text FROM knowledge.audit_events a"))
            .scalars()
            .all()
        )
    assert token not in audit and BODY_MARKER.decode() not in audit


class _Collector:
    """A recorder stand-in: it keeps whatever the capture hands it."""

    def __init__(self) -> None:
        self.exchanges: list[object] = []
        self.errors = 0

    def submit(self, exchange: object) -> None:
        self.exchanges.append(exchange)

    def note_capture_error(self) -> None:
        self.errors += 1

    def stop(self, timeout: float) -> None:
        del timeout


def test_the_interaction_log_does_not_capture_the_byte_routes(harness: Harness) -> None:
    collector = _Collector()
    # A second app over the same gate: one SDK session manager runs one lifespan.
    app = create_remote_mcp_app(
        harness.service,
        resolve_access=lambda _header: None,
        allowed_hosts=("testserver",),
        resource=RESOURCE,
        authorization_servers=("https://issuer.invalid",),
        scopes=frozenset({SCOPE}),
        additional_routes=build_file_transfer_routes(harness.gate),
    )
    wrapped = McpInteractionCapture(app, collector, path=MCP_PATH)  # type: ignore[arg-type]
    body = b"captured? synthetic"
    upload_id, token = harness.begin_upload("cap.bin")
    harness.write("cap.txt", "download synthetic")
    ticket = harness.begin_download("cap.txt")
    with serve(wrapped) as wire:
        client = Http(wire.port)
        patched = client.patch(
            f"/files/v1/uploads/{upload_id}",
            content=body,
            headers={
                **harness.bearer(token),
                "Upload-Offset": "0",
                "Upload-Complete": f"sha256={sha(body)}, length={len(body)}",
            },
        )
        assert patched.status_code == 200, patched.text
        got = client.get(
            f"/files/v1/downloads/{ticket['download_id']}",
            harness.bearer(ticket["download_token"]),
        )
        assert got.status_code == 200
    assert collector.exchanges == []
    assert collector.errors == 0
