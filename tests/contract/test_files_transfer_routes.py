"""Files workspace WP6a: the section 10 byte routes, end to end on PostgreSQL.

The `database` tier. A remote client with every `files.*` grant is registered
in `identity.remote_clients`, tickets are begun through `ApplicationService.invoke`
on the remote transport exactly as `/mcp` would, and the routes are served by
`create_remote_mcp_app(..., additional_routes=build_file_transfer_routes(gate))`
over a synthetic `tmp_path` root. It proves:

* HEAD answers the staged offset and the declared length, never cached;
* PATCH appends at the offset, resumes after HEAD, refuses a wrong offset
  with the current one, refuses bytes past the declared size and leaves the
  staged offset where it was;
* `Upload-Complete` finalizes through the same `files.upload.finalize`
  (audited, CAS, `digest_mismatch`), with or without a body, zero bytes included,
  and the answer carries no token;
* GET serves the whole file or one Range (206), 416 for an unsatisfiable
  one, 412 once the file moved, a preserved version, and many ranges per ticket;
* with the plane absent the routes are not composed (404).

Every path, byte and id is synthetic.
"""

from __future__ import annotations

import hashlib
import http.client
import json
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import text, update
from tests.wire import serve

from my_pa.adapters.http.files_transfer import build_file_transfer_routes
from my_pa.adapters.mcp.remote import create_remote_mcp_app
from my_pa.application.commands import (
    BeginFileDownload,
    BeginFileUpload,
    Command,
    WriteFileText,
)
from my_pa.application.file_transfer import FileTransferGate
from my_pa.application.file_workspace import FILE_WORKSPACE_CAPABILITIES, FileWorkspaceApplication
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.operation import Capability, is_write_capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_security_controls,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.security.remote_oauth import DurableRemoteClientStanding

pytestmark = pytest.mark.database

WORKSPACE: Final = "mcp"
RESOURCE: Final = "https://files.invalid/mcp"
SCOPE: Final = "files.synthetic"
OAUTH_CLIENT: Final = "synthetic-files-client-6a"
WHEN: Final = datetime(2026, 1, 1, tzinfo=UTC)
PRINCIPAL: Final = capture_principal_id(LOCAL_OPERATOR_UUID)
LIMITS: Final = EffectiveLimits(
    max_page_size=200, default_page_size=50, max_fetch_bytes=8 * 1024 * 1024, max_enrollment_depth=0
)
GRANTS: Final = frozenset(
    (capability, purpose)
    for capability in FILE_WORKSPACE_CAPABILITIES
    for purpose in permitted_purposes(capability)
)


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class Headers(dict[str, str]):
    """Response headers, looked up case-insensitively."""

    def __getitem__(self, name: str) -> str:
        return super().__getitem__(name.lower())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and super().__contains__(name.lower())


class Answer:
    """One HTTP answer as the stdlib client received it off the loopback socket."""

    def __init__(self, status: int, headers: Headers, content: bytes, method: str) -> None:
        self.method = method
        self.status_code = status
        self.headers = headers
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self) -> Any:  # noqa: ANN401
        return json.loads(self.content)


class Http:
    """A stdlib client for one served app: fixed-length or chunked request bodies."""

    def __init__(self, port: int) -> None:
        self.port = port

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        chunks: Sequence[bytes] | None = None,
    ) -> Answer:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.putrequest(method, path, skip_accept_encoding=True)
            for name, value in (headers or {}).items():
                connection.putheader(name, value)
            if chunks is not None:
                connection.putheader("Transfer-Encoding", "chunked")
                connection.endheaders()
                for chunk in chunks:
                    connection.send(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                connection.send(b"0\r\n\r\n")
            else:
                payload = body or b""
                if "content-length" not in {name.lower() for name in headers or {}}:
                    connection.putheader("Content-Length", str(len(payload)))
                connection.endheaders()
                if payload:
                    connection.send(payload)
            response = connection.getresponse()
            received = Headers({name.lower(): value for name, value in response.getheaders()})
            return Answer(response.status, received, response.read(), method)
        finally:
            connection.close()

    def head(self, path: str, headers: dict[str, str] | None = None) -> Answer:
        return self.request("HEAD", path, headers=headers)

    def patch(
        self, path: str, *, content: bytes = b"", headers: dict[str, str] | None = None
    ) -> Answer:
        return self.request("PATCH", path, headers=headers, body=content)

    def get(self, path: str, headers: dict[str, str] | None = None) -> Answer:
        return self.request("GET", path, headers=headers)


class Harness:
    """One synthetic root, one database clone, one remote client and the routes."""

    def __init__(
        self,
        url: str,
        root: Path,
        *,
        max_concurrent: int = 4,
        remote_writes_enabled: bool = True,
        max_upload_bytes: int = 1 << 20,
        body_idle_timeout_seconds: float = 30.0,
        download_deadline_seconds: float = 600.0,
        download_recheck_seconds: float = 5.0,
    ) -> None:
        self.root = root
        self.engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=audit)

        store = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)
        files = FileWorkspaceApplication(
            store, workspace_id=WORKSPACE, max_upload_bytes=max_upload_bytes
        )
        self.service = ApplicationService(
            unit_of_work=unit_of_work, limits=LIMITS, file_workspace=files
        )
        with self.engine.begin() as connection:
            repository = RemoteIdentityRepository(connection)
            self.client_row = repository.register_client(
                oauth_client_id=OAUTH_CLIENT,
                client_name="synthetic files client",
                redirect_uris='["https://client.invalid/callback"]',
                registered_scopes=SCOPE,
                now=WHEN,
                writes_enabled=True,
            )
            for capability, purpose in sorted(GRANTS, key=lambda pair: pair[0].value):
                repository.grant(
                    remote_client_id=self.client_row,
                    external_scope=SCOPE,
                    capability=capability,
                    now=WHEN,
                    is_write=is_write_capability(capability),
                    resource=RESOURCE,
                    purpose=purpose,
                )
            connection.execute(
                update(remote_security_controls).values(
                    remote_enabled=True, writes_enabled=True, updated_at=WHEN
                )
            )
        self.gate = FileTransferGate(
            service=self.service,
            store=store,
            unit_of_work=unit_of_work,
            standing=DurableRemoteClientStanding(
                connections=self.engine.begin, resource=RESOURCE, scopes=frozenset({SCOPE})
            ),
            workspace_id=WORKSPACE,
            max_upload_bytes=max_upload_bytes,
            remote_writes_enabled=remote_writes_enabled,
        )
        self.app = create_remote_mcp_app(
            self.service,
            resolve_access=lambda _header: None,
            allowed_hosts=("testserver",),
            resource=RESOURCE,
            authorization_servers=("https://issuer.invalid",),
            scopes=frozenset({SCOPE}),
            additional_routes=build_file_transfer_routes(
                self.gate,
                max_concurrent=max_concurrent,
                body_idle_timeout_seconds=body_idle_timeout_seconds,
                download_deadline_seconds=download_deadline_seconds,
                download_recheck_seconds=download_recheck_seconds,
            ),
        )
        self._stack = ExitStack()
        self.client = Http(self._stack.enter_context(serve(self.app)).port)

    def close(self) -> None:
        try:
            self._stack.close()
        finally:
            self.engine.dispose()
        self.audit_engine.dispose()

    # ---- capability calls, as `/mcp` makes them --------------------------------

    def invoke(
        self, command: Command, *, transport: CaptureTransport = CaptureTransport.REMOTE_CLIENT
    ) -> ResponseEnvelope:
        capability = command.capability
        (purpose,) = permitted_purposes(capability)
        remote = transport is CaptureTransport.REMOTE_CLIENT
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=purpose,
                principal_id=PRINCIPAL,
                requested_at=datetime.now(UTC),
            ),
            command,
            principal=Principal(
                principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=transport,
            capability_grants=GRANTS if remote else None,
            authenticated_client_id=OAUTH_CLIENT if remote else None,
        )

    def ok(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is None, (command.capability.value, envelope.error)
        result = envelope.to_canonical_dict()["result"]
        assert isinstance(result, dict)
        return result

    def begin_upload(
        self,
        path: str,
        *,
        size: int | None = None,
        sha256: str | None = None,
        expected_version: str | None = None,
        transport: CaptureTransport = CaptureTransport.REMOTE_CLIENT,
    ) -> tuple[str, str]:
        result = self.ok(
            BeginFileUpload(
                workspace_id=WORKSPACE,
                path=path,
                size=size,
                sha256=sha256,
                expected_version=expected_version,
                idempotency_key=issue_identifier(IdKind.CORRELATION),
            ),
            transport=transport,
        )
        assert result["route"] == f"/files/v1/uploads/{result['upload_id']}"
        return result["upload_id"], result["upload_token"]

    def begin_download(self, path: str | None = None, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.ok(BeginFileDownload(workspace_id=WORKSPACE, path=path, **fields))

    def write(self, path: str, body: str, version: str | None = None) -> dict[str, Any]:
        return self.ok(
            WriteFileText(
                workspace_id=WORKSPACE,
                path=path,
                text=body,
                expected_version=version,
                idempotency_key=issue_identifier(IdKind.CORRELATION),
            )
        )

    # ---- byte requests ------------------------------------------------------------

    @staticmethod
    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def head(self, upload_id: str, token: str) -> Answer:
        return self.client.head(f"/files/v1/uploads/{upload_id}", headers=self.bearer(token))

    def patch(
        self,
        upload_id: str,
        token: str,
        body: bytes,
        offset: int,
        *,
        complete: tuple[str, int] | None = None,
        extra: dict[str, str] | None = None,
    ) -> Answer:
        headers = {**self.bearer(token), "Upload-Offset": str(offset), **(extra or {})}
        if complete is not None:
            headers["Upload-Complete"] = f"sha256={complete[0]}, length={complete[1]}"
        return self.client.patch(f"/files/v1/uploads/{upload_id}", content=body, headers=headers)

    def get(self, download_id: str, token: str, **headers: str) -> Answer:
        return self.client.get(
            f"/files/v1/downloads/{download_id}", headers={**self.bearer(token), **headers}
        )

    def count(self, table: str, where: str = "true") -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {where}")  # noqa: S608 - fixed
                ).scalar_one()
            )


@pytest.fixture
def harness(cloned_database_url: str, tmp_path: Path) -> Iterator[Harness]:
    root = tmp_path / "workspace"
    root.mkdir()
    built = Harness(cloned_database_url, root)
    try:
        yield built
    finally:
        built.close()


# ---- uploads ---------------------------------------------------------------------


def test_head_patch_resume_and_finalize_through_upload_complete(harness: Harness) -> None:
    body = b"synthetic upload body 6a " * 40
    upload_id, token = harness.begin_upload("up.bin", size=len(body), sha256=sha(body))

    head = harness.head(upload_id, token)
    assert head.status_code == 204
    assert head.headers["Upload-Offset"] == "0"
    assert head.headers["Upload-Length"] == str(len(body))
    assert head.headers["Cache-Control"] == "no-store"

    first = harness.patch(upload_id, token, body[:300], 0)
    assert first.status_code == 204, first.text
    assert first.headers["Upload-Offset"] == "300"
    assert first.headers["Cache-Control"] == "no-store"

    # Resume: the client lost its place and asks again.
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "300"
    stale = harness.patch(upload_id, token, body[:10], 0)
    assert stale.status_code == 409
    assert stale.json() == {"error": "conflict", "reason": "offset_mismatch"}
    assert stale.headers["Upload-Offset"] == "300"

    done = harness.patch(upload_id, token, body[300:], 300, complete=(sha(body), len(body)))
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["entry"]["path"] == "up.bin"
    assert result["entry"]["size"] == len(body)
    assert result["replayed"] is False
    assert "token" not in done.text
    assert (harness.root / "up.bin").read_bytes() == body
    # Finalized: the ticket opens nothing more.
    assert harness.head(upload_id, token).status_code == 401
    # The finalize was the audited capability, under the route's derived key.
    assert (
        harness.count(
            "knowledge.file_workspace_receipts",
            f"capability = 'files.upload.finalize' "
            f"AND idempotency_key = 'files-route-finalize:{upload_id}'",
        )
        == 1
    )
    with harness.audit_engine.connect() as connection:
        outcomes = (
            connection.execute(
                text(
                    "SELECT outcome FROM knowledge.audit_events "
                    "WHERE capability = 'files.upload.finalize'"
                )
            )
            .scalars()
            .all()
        )
    assert outcomes == ["allowed"], "the route finalize was not audited once"


def test_an_empty_completing_patch_finalizes_without_appending(harness: Harness) -> None:
    body = b"two-step synthetic"
    upload_id, token = harness.begin_upload("two.bin")
    assert harness.patch(upload_id, token, body, 0).status_code == 204
    done = harness.patch(upload_id, token, b"", len(body), complete=(sha(body), len(body)))
    assert done.status_code == 200, done.text
    assert (harness.root / "two.bin").read_bytes() == body


def test_a_zero_byte_file_uploads(harness: Harness) -> None:
    upload_id, token = harness.begin_upload("empty.bin", size=0)
    assert harness.head(upload_id, token).headers["Upload-Length"] == "0"
    done = harness.patch(upload_id, token, b"", 0, complete=(sha(b""), 0))
    assert done.status_code == 200, done.text
    assert (harness.root / "empty.bin").read_bytes() == b""


def test_a_wrong_digest_is_digest_mismatch_and_the_target_is_untouched(harness: Harness) -> None:
    body = b"digest synthetic"
    upload_id, token = harness.begin_upload("d.bin")
    refused = harness.patch(upload_id, token, body, 0, complete=("0" * 64, len(body)))
    assert refused.status_code == 409
    assert refused.json() == {"error": "conflict", "reason": "digest_mismatch"}
    assert not (harness.root / "d.bin").exists()
    # The bytes stayed staged; a correct completion still finalizes.
    retry = harness.patch(upload_id, token, b"", len(body), complete=(sha(body), len(body)))
    assert retry.status_code == 200, retry.text


def test_bytes_past_the_declared_size_are_too_large_and_the_offset_stays(
    harness: Harness,
) -> None:
    upload_id, token = harness.begin_upload("s.bin", size=4)
    refused = harness.patch(upload_id, token, b"12345", 0)
    assert refused.status_code == 413
    assert refused.json() == {"error": "invalid_request", "reason": "too_large"}
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "0"
    assert harness.patch(upload_id, token, b"1234", 0).headers["Upload-Offset"] == "4"


def test_a_replace_needs_the_bound_version_and_preserves_the_preimage(harness: Harness) -> None:
    created = harness.write("r.txt", "original synthetic")
    version = created["entry"]["version"]
    upload_id, token = harness.begin_upload("r.txt", expected_version=version)
    body = b"replacement synthetic"
    done = harness.patch(upload_id, token, body, 0, complete=(sha(body), len(body)))
    assert done.status_code == 200, done.text
    assert done.json()["preimage_version_id"].startswith("fwver_")
    assert (harness.root / "r.txt").read_bytes() == body


def test_malformed_headers_are_invalid_request(harness: Harness) -> None:
    upload_id, token = harness.begin_upload("h.bin")
    path = f"/files/v1/uploads/{upload_id}"
    for headers in (
        {},
        {"Upload-Offset": "-1"},
        {"Upload-Offset": "01"},
        {"Upload-Offset": "0", "Upload-Complete": "length=1, sha256=" + "0" * 64},
    ):
        answer = harness.client.patch(
            path, content=b"x", headers={**harness.bearer(token), **headers}
        )
        assert answer.status_code == 400, headers
        assert answer.json() == {"error": "invalid_request", "reason": None}
    assert harness.head(upload_id, token).headers["Upload-Offset"] == "0"


# ---- downloads -----------------------------------------------------------------------


def test_a_download_streams_the_whole_file_and_ranges(harness: Harness) -> None:
    content = "0123456789 synthetic download"
    entry = harness.write("g.txt", content)["entry"]
    ticket = harness.begin_download("g.txt", include_sha256=True)
    assert ticket["route"] == f"/files/v1/downloads/{ticket['download_id']}"
    whole = harness.get(ticket["download_id"], ticket["download_token"])
    assert whole.status_code == 200
    assert whole.content == content.encode()
    assert whole.headers["Content-Length"] == str(len(content))
    assert whole.headers["Content-Type"] == "application/octet-stream"
    assert whole.headers["Cache-Control"] == "no-store"
    assert whole.headers["ETag"] == f'"{entry["version"]}"'
    assert whole.headers["X-Content-SHA256"] == sha(content.encode())

    # Many range requests on one ticket.
    for header, expected, content_range in (
        ("bytes=2-5", "2345", f"bytes 2-5/{len(content)}"),
        ("bytes=10-", content[10:], f"bytes 10-{len(content) - 1}/{len(content)}"),
        ("bytes=-4", content[-4:], f"bytes {len(content) - 4}-{len(content) - 1}/{len(content)}"),
        ("bytes=0-999", content, f"bytes 0-{len(content) - 1}/{len(content)}"),
    ):
        part = harness.get(ticket["download_id"], ticket["download_token"], Range=header)
        assert part.status_code == 206, header
        assert part.content == expected.encode()
        assert part.headers["Content-Range"] == content_range
        assert part.headers["Content-Length"] == str(len(expected))

    unsatisfiable = harness.get(ticket["download_id"], ticket["download_token"], Range="bytes=99-")
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["Content-Range"] == f"bytes */{len(content)}"
    assert unsatisfiable.json()["reason"] is None
    multi = harness.get(ticket["download_id"], ticket["download_token"], Range="bytes=0-1,3-4")
    assert multi.status_code == 400


def test_no_sha256_header_unless_the_ticket_carries_one(harness: Harness) -> None:
    harness.write("n.txt", "no digest synthetic")
    ticket = harness.begin_download("n.txt")
    answer = harness.get(ticket["download_id"], ticket["download_token"])
    assert answer.status_code == 200
    assert "X-Content-SHA256" not in answer.headers


def test_a_zero_byte_download(harness: Harness) -> None:
    harness.write("z.txt", "")
    ticket = harness.begin_download("z.txt")
    answer = harness.get(ticket["download_id"], ticket["download_token"])
    assert answer.status_code == 200
    assert answer.content == b""
    assert answer.headers["Content-Length"] == "0"
    ranged = harness.get(ticket["download_id"], ticket["download_token"], Range="bytes=0-")
    assert ranged.status_code == 416


def test_a_moved_file_is_412_external_change_detected(harness: Harness) -> None:
    harness.write("m.txt", "before synthetic")
    ticket = harness.begin_download("m.txt")
    (harness.root / "m.txt").write_text("changed outside the product, synthetic")
    answer = harness.get(ticket["download_id"], ticket["download_token"])
    assert answer.status_code == 412
    assert answer.json() == {"error": "conflict", "reason": "external_change_detected"}


def test_a_preserved_version_downloads_by_its_ticket(harness: Harness) -> None:
    created = harness.write("p.txt", "first synthetic")
    replaced = harness.write("p.txt", "second synthetic", created["entry"]["version"])
    ticket = harness.begin_download(version_id=replaced["preimage_version_id"])
    answer = harness.get(ticket["download_id"], ticket["download_token"])
    assert answer.status_code == 200
    assert answer.content == b"first synthetic"


def test_head_on_a_download_is_not_served(harness: Harness) -> None:
    harness.write("hd.txt", "synthetic")
    ticket = harness.begin_download("hd.txt")
    answer = harness.client.head(
        f"/files/v1/downloads/{ticket['download_id']}",
        headers=harness.bearer(ticket["download_token"]),
    )
    assert answer.status_code == 405


# ---- composition ---------------------------------------------------------------------


def test_the_routes_are_absent_without_the_plane(harness: Harness) -> None:
    bare = create_remote_mcp_app(
        harness.service,
        resolve_access=lambda _header: None,
        allowed_hosts=("testserver",),
        resource=RESOURCE,
        authorization_servers=("https://issuer.invalid",),
        scopes=frozenset({SCOPE}),
    )
    with serve(bare) as wire:
        client = Http(wire.port)
        assert client.head("/files/v1/uploads/fwupl_abcdefgh").status_code == 404
        assert client.patch("/files/v1/uploads/fwupl_abcdefgh").status_code == 404
        assert client.get("/files/v1/downloads/fwdnl_abcdefgh").status_code == 404


def test_the_gateway_composes_no_gate_without_a_workspace_root(
    cloned_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from my_pa.bootstrap.gateway import build_gateway_runtime
    from my_pa.bootstrap.settings import load_settings

    monkeypatch.delenv("MY_PA_FILES_WORKSPACE_ROOT", raising=False)
    runtime = build_gateway_runtime(load_settings())
    try:
        assert runtime.file_transfer is None
    finally:
        runtime.close()


def test_the_gateway_composes_the_gate_with_a_workspace_root(
    cloned_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from my_pa.bootstrap.gateway import build_gateway_runtime
    from my_pa.bootstrap.settings import load_settings

    root = tmp_path / "composed"
    root.mkdir()
    monkeypatch.setenv("MY_PA_FILES_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("MY_PA_FILES_DISK_RESERVE_BYTES", "0")
    monkeypatch.setenv("MY_PA_OAUTH_AUDIENCE", RESOURCE)
    monkeypatch.setenv("MY_PA_OAUTH_SCOPES", SCOPE)
    runtime = build_gateway_runtime(load_settings())
    try:
        assert isinstance(runtime.file_transfer, FileTransferGate)
    finally:
        runtime.close()


def test_the_issuing_capabilities_are_the_grant_rechecked(harness: Harness) -> None:
    """The issuing capabilities whose grant every byte request re-reads, and their purposes."""
    assert (Capability.FILES_UPLOAD_BEGIN, Purpose.FILE_WORKSPACE_AUTHORING) in GRANTS
    assert (Capability.FILES_DOWNLOAD_BEGIN, Purpose.FILE_WORKSPACE_READ) in GRANTS
