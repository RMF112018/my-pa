"""Files workspace WP7: the synthetic vertical slice, capability to bytes and back.

The `database` tier, over the WP6a harness (`tests/contract/
test_files_transfer_routes.py`): a registered remote client holding every
`files.*` grant, tickets begun through `ApplicationService.invoke` on the
remote transport exactly as `/mcp` would, the section 10 byte routes served by
`create_remote_mcp_app(..., additional_routes=...)` on a real uvicorn on
loopback, and the bytes moved by the stdlib reference client
`scripts/my_pa_files.py` (its `main`, in process). It proves:

* begin -> one PATCH -> an interrupted PATCH -> the client resumes from HEAD ->
  `Upload-Complete` -> `files.list` / `files.stat` -> `files.download.begin` ->
  the client downloads -> SHA-256 equality; a zero-byte round trip; a 17 MiB
  file over several PATCHes;
* a completing PATCH retried after its finalize committed answers 401, and
  `files.stat` is how the caller learns the outcome;
* a change after the download headers left truncates the stream short of
  `Content-Length` (it cannot become a 412 then);
* a replace with `expected_version` leaves a preimage in `files.history` that
  downloads by its `version_id` with the old bytes; trash then restore;
* path escapes (`..`, absolute, reserved `.my-pa`, a planted symlink) are
  refused by the capabilities, and the byte routes reach nothing by path: the
  id is opaque and a ticket opens only its own transfer;
* the audit is one `authorize` row per call -- none for HEAD/PATCH chunks, one
  `files.upload.finalize` for a completing PATCH, and a handler refusal after
  authorization is `allowed` (contract section 11).

Every path, byte and id is synthetic; nothing leaves loopback.
"""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import os
import socket
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
from sqlalchemy import text

from my_pa.application.commands import (
    BeginFileDownload,
    BeginFileUpload,
    Command,
    GetFileHistory,
    ListFiles,
    MakeFileDirectory,
    RestoreFile,
    StatFile,
    TrashFile,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from tests.contract.test_files_transfer_routes import WORKSPACE, Harness, sha

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = ROOT / "scripts" / "my_pa_files.py"
SECRET: Final = b"synthetic outside-the-root bytes wp7"


def _load_client() -> ModuleType:
    spec = importlib.util.spec_from_file_location("my_pa_files_wp7", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLIENT: Final = _load_client()


def key() -> str:
    return issue_identifier(IdKind.CORRELATION)


class Slice:
    """The WP6a harness plus the reference client and a few readers."""

    def __init__(self, harness: Harness, scratch: Path) -> None:
        self.h = harness
        self.scratch = scratch
        self.origin = f"http://127.0.0.1:{harness.client.port}"

    def ok(self, command: Command) -> dict[str, Any]:
        return self.h.ok(command)

    def refused(self, command: Command) -> tuple[str, list[str]]:
        envelope = self.h.invoke(command)
        assert envelope.error is not None, command.capability.value
        error = envelope.to_canonical_dict()["error"]
        return str(error["code"]), list(error.get("safe_details") or [])

    def run(self, argv: list[str], token: str) -> int:
        return int(CLIENT.main(argv, environ={CLIENT.TOKEN_ENV: token}))

    def upload(self, local: Path, route: str, token: str, *extra: str) -> int:
        argv = ["upload", str(local), "--origin", self.origin, "--route", route]
        return self.run([*argv, "--backoff-seconds", "0.05", *extra], token)

    def download(self, path: str, out: Path, **fields: Any) -> int:  # noqa: ANN401
        begun = self.ok(BeginFileDownload(workspace_id=WORKSPACE, path=path, **fields))
        argv = ["download", str(out), "--origin", self.origin, "--route", begun["route"]]
        return self.run(argv, begun["download_token"])

    def begin(self, path: str, body: bytes, version: str | None = None) -> dict[str, Any]:
        return self.ok(
            BeginFileUpload(
                workspace_id=WORKSPACE,
                path=path,
                size=len(body),
                sha256=sha(body),
                expected_version=version,
                idempotency_key=key(),
            )
        )

    def local(self, name: str, body: bytes) -> Path:
        path = self.scratch / name
        path.write_bytes(body)
        return path

    def put(self, path: str, body: bytes, version: str | None = None) -> None:
        begun = self.begin(path, body, version)
        local = self.local(f"put-{issue_identifier(IdKind.CORRELATION)}", body)
        assert self.upload(local, begun["route"], begun["upload_token"]) == 0

    def stat(self, path: str) -> dict[str, Any]:
        return self.ok(StatFile(workspace_id=WORKSPACE, path=path, include_sha256=True))

    def audits(self, capability: str | None = None) -> list[tuple[str, str]]:
        where = "" if capability is None else "WHERE capability = :capability"
        with self.h.engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT capability, outcome FROM knowledge.audit_events {where}"),  # noqa: S608
                {"capability": capability},
            )
            return [(str(row[0]), str(row[1])) for row in rows]


@pytest.fixture
def slice_(cloned_database_url: str, tmp_path: Path) -> Iterator[Slice]:
    root = tmp_path / "workspace"
    root.mkdir()
    scratch = tmp_path / "client"
    scratch.mkdir()
    harness = Harness(cloned_database_url, root, max_upload_bytes=64 << 20)
    try:
        yield Slice(harness, scratch)
    finally:
        harness.close()


def _interrupted_patch(port: int, upload_id: str, token: str, offset: int, body: bytes) -> None:
    """Declare twice `body`'s length, send `body`, then drop the connection."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
        head = (
            f"PATCH /files/v1/uploads/{upload_id} HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Upload-Offset: {offset}\r\n"
            f"Content-Length: {2 * len(body)}\r\n"
            "Content-Type: application/offset+octet-stream\r\n\r\n"
        )
        connection.sendall(head.encode("ascii") + body)
        time.sleep(0.2)


def _settled_offset(slice_: Slice, upload_id: str, token: str) -> int:
    """HEAD until the interrupted request's lock is released (503 meanwhile)."""
    deadline = time.monotonic() + 20
    while True:
        answer = slice_.h.head(upload_id, token)
        if answer.status_code == 204:
            return int(answer.headers["Upload-Offset"])
        assert answer.status_code == 503, answer.status_code
        assert time.monotonic() < deadline, "the interrupted PATCH never released its lock"
        time.sleep(0.1)


# ---- the round trip ---------------------------------------------------------------


def test_begin_bytes_interrupt_resume_finalize_list_stat_download(slice_: Slice) -> None:
    body = os.urandom(300 * 1024)
    refused = slice_.refused(
        BeginFileUpload(workspace_id=WORKSPACE, path="Reports/round.bin", idempotency_key=key())
    )
    assert refused == ("not_found", ["not_found"])  # the parent does not exist yet
    slice_.ok(MakeFileDirectory(workspace_id=WORKSPACE, path="Reports", idempotency_key=key()))
    begun = slice_.begin("Reports/round.bin", body)
    upload_id, token = begun["upload_id"], begun["upload_token"]
    assert begun["route"] == f"/files/v1/uploads/{upload_id}"
    assert upload_id.startswith("fwupl_")

    first = slice_.h.patch(upload_id, token, body[:65536], 0)
    assert first.status_code == 204, first.text
    _interrupted_patch(slice_.h.client.port, upload_id, token, 65536, body[65536:131072])
    staged = _settled_offset(slice_, upload_id, token)
    assert 65536 <= staged <= 131072

    audits_before = len(slice_.audits())
    local = slice_.local("round.bin", body)
    assert slice_.upload(local, begun["route"], token, "--chunk-bytes", "65536") == 0
    finalizes = slice_.audits("files.upload.finalize")
    assert finalizes == [("files.upload.finalize", "allowed")]
    # HEAD and every chunk PATCH added nothing; the completing PATCH added the finalize.
    assert len(slice_.audits()) == audits_before + 1

    listed = slice_.ok(ListFiles(workspace_id=WORKSPACE, path="Reports"))
    assert [entry["name"] for entry in listed["entries"]] == ["round.bin"]
    stat = slice_.stat("Reports/round.bin")
    assert stat["size"] == len(body)
    assert stat["sha256"] == sha(body)

    out = slice_.scratch / "round.out"
    assert slice_.download("Reports/round.bin", out, include_sha256=True) == 0
    assert hashlib.sha256(out.read_bytes()).hexdigest() == sha(body)
    assert not (slice_.scratch / "round.out.part").exists()


def test_a_zero_byte_file_round_trips(slice_: Slice) -> None:
    slice_.put("empty.bin", b"")
    assert slice_.stat("empty.bin")["size"] == 0
    out = slice_.scratch / "empty.out"
    assert slice_.download("empty.bin", out, include_sha256=True) == 0
    assert out.read_bytes() == b""


def test_a_17_mib_file_goes_over_several_patches(slice_: Slice) -> None:
    body = os.urandom(17 * 1024 * 1024)
    begun = slice_.begin("big.bin", body)
    local = slice_.local("big.bin", body)
    chunk = str(4 * 1024 * 1024)
    assert slice_.upload(local, begun["route"], begun["upload_token"], "--chunk-bytes", chunk) == 0
    assert slice_.stat("big.bin")["sha256"] == sha(body)
    out = slice_.scratch / "big.out"
    assert slice_.download("big.bin", out, include_sha256=True) == 0
    assert hashlib.sha256(out.read_bytes()).hexdigest() == sha(body)


def test_a_completing_patch_retried_after_its_finalize_committed_is_401(slice_: Slice) -> None:
    body = b"synthetic retried completion wp7"
    begun = slice_.begin("retried.bin", body)
    upload_id, token = begun["upload_id"], begun["upload_token"]
    done = slice_.h.patch(upload_id, token, body, 0, complete=(sha(body), len(body)))
    assert done.status_code == 200, done.text
    # The response "lost": the same completing request again.
    again = slice_.h.patch(upload_id, token, body, 0, complete=(sha(body), len(body)))
    assert again.status_code == 401
    assert again.json() == {"error": "denied", "reason": "ticket_invalid"}
    # The caller learns the outcome from files.stat, never from a replay.
    assert slice_.stat("retried.bin")["sha256"] == sha(body)
    assert slice_.audits("files.upload.finalize") == [("files.upload.finalize", "allowed")]


def test_a_change_after_the_headers_truncates_the_stream(slice_: Slice) -> None:
    """The stream stops short of `Content-Length`; a retry is then a 412.

    The server neither sends the rest nor closes the connection today, so a
    reader sees the truncation as its read timeout (the reference client's
    `--timeout`, default 60 s); both are accepted here.
    """
    body = os.urandom(17 * 1024 * 1024)
    slice_.put("moving.bin", body)
    begun = slice_.ok(
        BeginFileDownload(workspace_id=WORKSPACE, path="moving.bin", include_sha256=True)
    )
    auth = {"Authorization": f"Bearer {begun['download_token']}"}
    connection = http.client.HTTPConnection("127.0.0.1", slice_.h.client.port, timeout=3)
    received = 0
    try:
        connection.request("GET", begun["route"], headers=auth)
        response = connection.getresponse()
        assert response.status == 200
        assert int(response.getheader("Content-Length") or 0) == len(body)
        os.utime(slice_.h.root / "moving.bin", ns=(1_000_000_000, 1_000_000_000))  # external
        try:
            while block := response.read1(1 << 20):
                received += len(block)
        except (TimeoutError, http.client.IncompleteRead):
            pass
    finally:
        connection.close()
    assert received < len(body)
    # The same ticket, retried, is refused: the file is not the one it names.
    out = slice_.scratch / "moving.out"
    argv = ["download", str(out), "--origin", slice_.origin, "--route", begun["route"]]
    assert slice_.run([*argv, "--retries", "0"], begun["download_token"]) == CLIENT.EXIT_REFUSED
    assert not out.exists()


# ---- replace, history, trash, restore ---------------------------------------------


def test_a_replace_leaves_a_downloadable_preimage_and_trash_restores(slice_: Slice) -> None:
    old = b"synthetic first content wp7\n"
    new = b"synthetic second content wp7, longer\n"
    slice_.put("doc.txt", old)
    version = slice_.stat("doc.txt")["version"]

    # No expected_version: no overwrite by default, refused before any byte moves.
    assert slice_.refused(
        BeginFileUpload(workspace_id=WORKSPACE, path="doc.txt", idempotency_key=key())
    ) == ("conflict", ["exists"])
    assert slice_.stat("doc.txt")["sha256"] == sha(old)

    slice_.put("doc.txt", new, version)
    assert slice_.stat("doc.txt")["sha256"] == sha(new)
    history = slice_.ok(GetFileHistory(workspace_id=WORKSPACE, path="doc.txt"))
    (item,) = history["items"]
    assert item["version_id"].startswith("fwver_")
    out = slice_.scratch / "preimage.out"
    begun = slice_.ok(
        BeginFileDownload(
            workspace_id=WORKSPACE, version_id=item["version_id"], include_sha256=True
        )
    )
    argv = ["download", str(out), "--origin", slice_.origin, "--route", begun["route"]]
    assert slice_.run(argv, begun["download_token"]) == 0
    assert out.read_bytes() == old

    # A stale CAS is refused by the handler after authorize: audited `allowed`.
    before = slice_.audits("files.trash")
    assert slice_.refused(
        TrashFile(
            workspace_id=WORKSPACE, path="doc.txt", idempotency_key=key(), expected_version=version
        )
    ) == ("conflict", ["version_conflict"])
    assert slice_.audits("files.trash") == [*before, ("files.trash", "allowed")]

    trashed = slice_.ok(TrashFile(workspace_id=WORKSPACE, path="doc.txt", idempotency_key=key()))
    assert not (slice_.h.root / "doc.txt").exists()
    assert slice_.refused(StatFile(workspace_id=WORKSPACE, path="doc.txt")) == (
        "not_found",
        ["not_found"],
    )
    slice_.ok(
        RestoreFile(
            workspace_id=WORKSPACE, trash_item_id=trashed["trash_item_id"], idempotency_key=key()
        )
    )
    assert slice_.stat("doc.txt")["sha256"] == sha(new)


# ---- containment --------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["../x", "a/../../x", "/etc/passwd", ".my-pa", ".my-pa/staging", "x/.MY-PA/y"]
)
def test_an_escaping_or_reserved_path_is_refused_by_every_capability(path: str) -> None:
    for build in (
        lambda: StatFile(workspace_id=WORKSPACE, path=path),
        lambda: ListFiles(workspace_id=WORKSPACE, path=path),
        lambda: BeginFileDownload(workspace_id=WORKSPACE, path=path),
        lambda: BeginFileUpload(workspace_id=WORKSPACE, path=path, idempotency_key=key()),
        lambda: TrashFile(workspace_id=WORKSPACE, path=path, idempotency_key=key()),
    ):
        with pytest.raises(InvalidRequestError) as refused:
            build()
        assert SafeDetail.INVALID_PATH in refused.value.safe_details


def test_a_planted_symlink_is_never_followed(slice_: Slice, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(SECRET)
    root = slice_.h.root
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    (root / "linkfile").symlink_to(outside / "secret.bin")

    listed = {
        e["name"]: e["kind"]
        for e in slice_.ok(ListFiles(workspace_id=WORKSPACE, path=""))["entries"]
    }
    assert listed == {"linkdir": "other", "linkfile": "other"}
    unsupported = ("unsupported", ["unsupported_entry"])
    assert (
        slice_.refused(StatFile(workspace_id=WORKSPACE, path="linkdir/secret.bin")) == unsupported
    )
    assert slice_.refused(BeginFileDownload(workspace_id=WORKSPACE, path="linkfile")) == unsupported
    assert (
        slice_.refused(
            BeginFileUpload(workspace_id=WORKSPACE, path="linkdir/new.bin", idempotency_key=key())
        )
        == unsupported
    )
    assert not (outside / "new.bin").exists()
    assert sorted(p.name for p in outside.iterdir()) == ["secret.bin"]


def test_the_byte_routes_reach_nothing_by_path(slice_: Slice) -> None:
    slice_.put("mine.txt", b"synthetic mine wp7")
    slice_.put("other.txt", SECRET)
    mine = slice_.ok(BeginFileDownload(workspace_id=WORKSPACE, path="mine.txt"))
    other = slice_.ok(BeginFileDownload(workspace_id=WORKSPACE, path="other.txt"))
    upload = slice_.begin("third.bin", b"x")
    auth = {"Authorization": f"Bearer {mine['download_token']}"}
    client = slice_.h.client
    for route in (
        other["route"],  # another ticket's id
        upload["route"].replace("uploads", "downloads"),  # an upload id at the download route
        "/files/v1/downloads/other.txt",
        "/files/v1/downloads/..%2Fother.txt",
        "/files/v1/downloads/../other.txt",
        "/files/v1/downloads/%2E%2E",
    ):
        answer = client.get(route, headers=auth)
        assert answer.status_code in (401, 404), (route, answer.status_code)
        assert SECRET not in answer.content
    own = client.get(mine["route"], headers=auth)
    assert own.status_code == 200
    assert own.content == b"synthetic mine wp7"
    # The upload ticket never opens a download, even its own id at the other route.
    as_download = client.get(
        upload["route"].replace("uploads", "downloads"),
        headers={"Authorization": f"Bearer {upload['upload_token']}"},
    )
    assert as_download.status_code == 401


def test_the_audit_records_the_decision_and_nothing_about_the_file(slice_: Slice) -> None:
    with slice_.h.engine.connect() as connection:
        columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'knowledge' AND table_name = 'audit_events'"
                )
            ).scalars()
        )
    assert columns == {
        "audit_id",
        "correlation_id",
        "principal_id",
        "capability",
        "purpose",
        "outcome",
        "policy_version",
        "denial_reason",
        "scope_source_id_count",
        "recorded_at",
    }
    slice_.put("audited.bin", b"synthetic audited wp7")
    rows = slice_.audits()
    assert ("files.upload.begin", "allowed") in rows
    assert ("files.upload.finalize", "allowed") in rows
