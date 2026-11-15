"""Download tickets read as MCP resources (files-workspace contract section 17.3).

`FileTransferGate.authenticate_resource` and `WorkspaceDownloadResources` over
the real contained store on a synthetic `tmp_path` root, the in-memory
repository of `tests/unit/test_file_workspace_application.py` and a synthetic
standing reader: a ticket opens only for its own Principal and OAuth client,
usable now, with the client's standing re-checked; the stream re-checks and
stops on revocation, expiry, a changed file or its deadline; the held file is
closed exactly once and the per-process stream slot always comes back. Every
value is synthetic.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest

from my_pa.adapters.http.files_resources import RESOURCE_PIECE_BYTES, WorkspaceDownloadResources
from my_pa.adapters.mcp.remote import RemoteAccessContext
from my_pa.adapters.remote_resources import RemoteResourceRefused
from my_pa.application.commands import BeginFileDownload, BeginFileUpload
from my_pa.application.errors import DeniedError
from my_pa.application.file_transfer import FileTransferGate
from my_pa.contracts.ports import RemoteClientStanding
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.transfer import client_ref_of
from tests.unit.test_file_workspace_application import NOW, PRINCIPAL, WORKSPACE, _World

CLIENT: Final = "synthetic-oauth-client"
OTHER: Final = "another-synthetic-client"
READ: Final = (Capability.FILES_DOWNLOAD_BEGIN, Purpose.FILE_WORKSPACE_READ)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Standing:
    def __init__(self) -> None:
        self.grants: frozenset[tuple[Capability, Purpose | None]] = frozenset({READ})
        self.calls = 0

    def standing(self, client_ref: str, *, now: datetime) -> RemoteClientStanding | None:
        del now
        self.calls += 1
        if client_ref != client_ref_of(derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT)):
            return None
        return RemoteClientStanding(
            oauth_client_id=CLIENT,
            principal_id=PRINCIPAL,
            capability_purposes=self.grants,
            write_allowed=False,
        )


class _Slice:
    def __init__(self, root: Path) -> None:
        self.world = _World(root)
        self.standing = _Standing()
        self.now = NOW

        @contextmanager
        def unit_of_work() -> Iterator[SimpleNamespace]:
            yield SimpleNamespace(file_workspace=self.world.rows)

        self.gate = FileTransferGate(
            service=None,  # type: ignore[arg-type] - no finalize here
            store=self.world.store,
            unit_of_work=unit_of_work,  # type: ignore[arg-type]
            standing=self.standing,  # type: ignore[arg-type]
            workspace_id=WORKSPACE,
            max_upload_bytes=1 << 30,
            remote_writes_enabled=False,
            clock=lambda: self.now,
        )

    def write(self, path: str, text: str) -> None:
        target = self.world.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def begin(self, path: str, client: str = CLIENT) -> dict[str, Any]:
        return self.world.run(
            BeginFileDownload(workspace_id=WORKSPACE, path=path, include_sha256=True),
            grants=frozenset({READ}),
            client=client,
        )


@pytest.fixture
def world(tmp_path: Path) -> _Slice:
    root = tmp_path / "workspace"
    root.mkdir()
    return _Slice(root)


def _access(client: str | None = CLIENT, principal: str = PRINCIPAL) -> RemoteAccessContext:
    return RemoteAccessContext(
        Principal(principal_id=principal, kind=PrincipalKind.OPERATOR, authenticated=True),
        authenticated_client_id=client,
    )


# ---- the result names the resource -------------------------------------------------------


def test_download_begin_answers_the_resource_uri_and_the_file_name(world: _Slice) -> None:
    world.write("dir/report.txt", "synthetic report")
    begun = world.begin("dir/report.txt")
    assert begun["resource_uri"] == "mcp-files://downloads/" + begun["download_id"]
    assert begun["name"] == "report.txt"
    assert begun["route"] == "/files/v1/downloads/" + begun["download_id"]


# ---- authenticate_resource ---------------------------------------------------------------


def test_the_issuing_client_opens_its_ticket(world: _Slice) -> None:
    world.write("a.txt", "synthetic a")
    begun = world.begin("a.txt")
    access = world.gate.authenticate_resource(
        begun["download_id"], principal_id=PRINCIPAL, oauth_client_id=CLIENT
    )
    assert access.ticket.transfer_id == begun["download_id"]
    assert world.standing.calls == 1


@pytest.mark.parametrize(
    ("client", "principal"),
    [(OTHER, PRINCIPAL), (CLIENT, "prn_someoneelse0000001"), (None, PRINCIPAL), ("", PRINCIPAL)],
)
def test_another_client_or_principal_is_one_ticket_invalid(
    world: _Slice, client: str | None, principal: str
) -> None:
    world.write("a.txt", "synthetic a")
    begun = world.begin("a.txt")
    with pytest.raises(FilesRefusal) as caught:
        world.gate.authenticate_resource(
            begun["download_id"], principal_id=principal, oauth_client_id=client
        )
    assert caught.value.reason is FilesReason.TICKET_INVALID


@pytest.mark.parametrize("download_id", ["fwdnl_nope", "fwupl_" + "0" * 26, "", "../x"])
def test_an_unknown_or_malformed_id_is_ticket_invalid(world: _Slice, download_id: str) -> None:
    with pytest.raises(FilesRefusal) as caught:
        world.gate.authenticate_resource(
            download_id, principal_id=PRINCIPAL, oauth_client_id=CLIENT
        )
    assert caught.value.reason is FilesReason.TICKET_INVALID


def test_an_upload_ticket_is_not_a_download_resource(world: _Slice) -> None:
    upload = world.world.run(
        BeginFileUpload(workspace_id=WORKSPACE, path="u.bin", idempotency_key="u"),
        grants=frozenset({(Capability.FILES_UPLOAD_BEGIN, Purpose.FILE_WORKSPACE_AUTHORING)}),
        client=CLIENT,
    )
    with pytest.raises(FilesRefusal) as caught:
        world.gate.authenticate_resource(
            upload["upload_id"], principal_id=PRINCIPAL, oauth_client_id=CLIENT
        )
    assert caught.value.reason is FilesReason.TICKET_INVALID


def test_an_expired_ticket_is_ticket_invalid(world: _Slice) -> None:
    world.write("a.txt", "synthetic a")
    begun = world.begin("a.txt")
    world.now = NOW + timedelta(seconds=3601)
    with pytest.raises(FilesRefusal) as caught:
        world.gate.authenticate_resource(
            begun["download_id"], principal_id=PRINCIPAL, oauth_client_id=CLIENT
        )
    assert caught.value.reason is FilesReason.TICKET_INVALID


def test_a_revoked_grant_is_denied(world: _Slice) -> None:
    world.write("a.txt", "synthetic a")
    begun = world.begin("a.txt")
    world.standing.grants = frozenset()
    with pytest.raises(DeniedError):
        world.gate.authenticate_resource(
            begun["download_id"], principal_id=PRINCIPAL, oauth_client_id=CLIENT
        )


# ---- WorkspaceDownloadResources --------------------------------------------------------------


async def _collect(stream: Any) -> bytes:  # noqa: ANN401
    pieces: list[bytes] = []

    async def write(piece: bytes) -> None:
        assert len(piece) % 3 == 0 or len(pieces) * RESOURCE_PIECE_BYTES + len(piece) == stream.size
        pieces.append(piece)

    await stream.stream(write)
    return b"".join(pieces)


@pytest.mark.anyio
async def test_a_resource_streams_the_file_exactly_and_returns_its_slot(world: _Slice) -> None:
    text = "synthetic " * 200_000  # about 2 MiB, three pieces
    world.write("big.txt", text)
    begun = world.begin("big.txt")
    resources = WorkspaceDownloadResources(world.gate, max_concurrent=1)
    stream = await resources.open(begun["resource_uri"], _access())
    with pytest.raises(RemoteResourceRefused) as busy:
        await resources.open(begun["resource_uri"], _access())
    assert busy.value.reason == "unavailable"
    data = await _collect(stream)
    assert hashlib.sha256(data).hexdigest() == begun["sha256"]
    await stream.aclose()
    await stream.aclose()
    again = await resources.open(begun["resource_uri"], _access())
    await again.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "uri",
    [
        "mcp-files://downloads/fwdnl_unknown",
        "mcp-files://uploads/x",
        "https://example.invalid/x",
        "file:///etc/passwd",
    ],
)
async def test_a_bad_uri_is_ticket_invalid_and_keeps_the_slot(world: _Slice, uri: str) -> None:
    resources = WorkspaceDownloadResources(world.gate, max_concurrent=1)
    with pytest.raises(RemoteResourceRefused) as caught:
        await resources.open(uri, _access())
    assert caught.value.reason == "ticket_invalid"
    world.write("a.txt", "synthetic")
    opened = await resources.open(world.begin("a.txt")["resource_uri"], _access())
    await opened.aclose()


@pytest.mark.anyio
async def test_another_clients_read_is_refused_and_a_revoked_one_is_denied(world: _Slice) -> None:
    world.write("a.txt", "synthetic")
    begun = world.begin("a.txt")
    resources = WorkspaceDownloadResources(world.gate)
    with pytest.raises(RemoteResourceRefused) as other:
        await resources.open(begun["resource_uri"], _access(OTHER))
    assert other.value.reason == "ticket_invalid"
    world.standing.grants = frozenset()
    with pytest.raises(RemoteResourceRefused) as revoked:
        await resources.open(begun["resource_uri"], _access())
    assert revoked.value.reason == "denied"


@pytest.mark.anyio
async def test_a_change_after_the_ticket_is_external_change_detected(world: _Slice) -> None:
    world.write("a.txt", "synthetic before")
    begun = world.begin("a.txt")
    (world.world.root / "a.txt").write_text("synthetic after, longer")
    resources = WorkspaceDownloadResources(world.gate)
    with pytest.raises(RemoteResourceRefused) as caught:
        await resources.open(begun["resource_uri"], _access())
    assert caught.value.reason == "external_change_detected"


@pytest.mark.anyio
async def test_a_revocation_mid_stream_stops_it_at_the_next_recheck(world: _Slice) -> None:
    world.write("big.txt", "synthetic " * 200_000)
    begun = world.begin("big.txt")
    ticks = iter(range(1000))
    resources = WorkspaceDownloadResources(
        world.gate, recheck_seconds=1, clock=lambda: float(next(ticks))
    )
    stream = await resources.open(begun["resource_uri"], _access())
    sent: list[int] = []

    async def write(piece: bytes) -> None:
        sent.append(len(piece))
        world.standing.grants = frozenset()

    with pytest.raises(DeniedError):
        await stream.stream(write)
    assert len(sent) == 1
    await stream.aclose()


@pytest.mark.anyio
async def test_the_deadline_stops_a_stream(world: _Slice) -> None:
    world.write("big.txt", "synthetic " * 200_000)
    begun = world.begin("big.txt")
    ticks = iter([0.0, 0.0, 0.0, 0.0, 99.0, 99.0, 99.0])
    resources = WorkspaceDownloadResources(
        world.gate, deadline_seconds=10, recheck_seconds=50, clock=lambda: next(ticks)
    )
    stream = await resources.open(begun["resource_uri"], _access())
    sent: list[int] = []

    async def write(piece: bytes) -> None:
        sent.append(len(piece))

    with pytest.raises(FilesRefusal):
        await stream.stream(write)
    assert sent and sum(sent) < stream.size
    await stream.aclose()


@pytest.mark.anyio
async def test_a_cancelled_read_closes_the_file_when_its_thread_returns(world: _Slice) -> None:
    world.write("big.txt", "synthetic " * 200_000)
    begun = world.begin("big.txt")
    resources = WorkspaceDownloadResources(world.gate, max_concurrent=1)
    stream = await resources.open(begun["resource_uri"], _access())

    async def write(_piece: bytes) -> None:
        await asyncio.sleep(3600)

    task = asyncio.create_task(stream.stream(write))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stream.aclose()
    await asyncio.sleep(0.1)
    # The slot came back: another open succeeds.
    again = await resources.open(begun["resource_uri"], _access())
    await again.aclose()


def test_bounds_must_be_positive(world: _Slice) -> None:
    for options in ({"max_concurrent": 0}, {"deadline_seconds": 0}, {"recheck_seconds": 0}):
        with pytest.raises(ValueError):
            WorkspaceDownloadResources(world.gate, **options)  # type: ignore[arg-type]
