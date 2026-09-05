"""Synthetic POSIX proofs for local source and OCR containment boundaries."""

from __future__ import annotations

import multiprocessing
import os
import queue
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path, PurePosixPath

import pytest

from my_pa.domain.goodnotes.models import SourcePage
from my_pa.infrastructure.goodnotes.local import (
    BoundedLocalOCRTranscriber,
    GoodNotesLocalSourceError,
    GoodNotesTranscriptionError,
    LocalGoodNotesObserver,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX containment boundary")


def _observe_nonregular(root: Path, result: Connection) -> None:
    try:
        LocalGoodNotesObserver(root=root, source_root_id="synthetic").settle(
            PurePosixPath("blocked.pdf")
        )
    except GoodNotesLocalSourceError:
        result.send("refused")
    else:
        result.send("admitted")
    finally:
        result.close()


@pytest.mark.parametrize("kind", ["fifo", "socket", "directory", "symlink"])
def test_nonregular_source_is_refused_without_blocking(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "blocked.pdf"
    local_socket = None
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "socket":
        local_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # The macOS pytest temporary root can exceed the Unix socket path limit.
        with monkeypatch.context() as patch:
            patch.chdir(tmp_path)
            local_socket.bind(path.name)
    elif kind == "directory":
        path.mkdir()
    else:
        target = tmp_path / "ordinary.pdf"
        target.write_bytes(b"%PDF-synthetic")
        path.symlink_to(target)
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    probe = context.Process(target=_observe_nonregular, args=(tmp_path, sender))
    try:
        probe.start()
        sender.close()
        assert receiver.poll(5), "source admission blocked on a nonregular file"
        assert receiver.recv() == "refused"
        probe.join(timeout=2)
        assert probe.exitcode == 0
    finally:
        if probe.is_alive():
            probe.kill()
            probe.join(timeout=2)
        receiver.close()
        sender.close()
        if local_socket is not None:
            local_socket.close()


_TREE_SCRIPT = """\
import os, signal, sys
mode, ready_path, release_path = sys.argv[1:4]
ready = os.open(ready_path, os.O_WRONLY)
release = os.open(release_path, os.O_RDONLY)
if mode not in ('stdin-holder', 'broken-input'):
    sys.stdin.buffer.read()
read_end, write_end = os.pipe()
descendant = os.fork()
if descendant == 0:
    os.close(read_end)
    os.close(ready)
    os.close(release)
    if mode == 'stdin-holder':
        os.close(1)
    if mode == 'broken-input':
        os.close(0)
    os.write(write_end, b'R')
    os.close(write_end)
    while True:
        signal.pause()
os.close(write_end)
assert os.read(read_end, 1) == b'R'
os.close(read_end)
os.write(ready, f'{os.getpid()} {os.getpgrp()} {descendant}\\n'.encode())
os.close(ready)
assert os.read(release, 1) == b'G'
os.close(release)
if mode == 'broken-input':
    os.close(0)
    os.write(1, b'{"regions": []}')
if mode in ('stdout-holder', 'stdin-holder'):
    os.write(1, b'{"regions": []}')
    os._exit(0)
if mode == 'overflow':
    os.write(1, b'SYNTHETIC-OCR-CONTENT' * 10000)
while True:
    signal.pause()
"""


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed orphan may await the host's reaper; a zombie cannot run or hold pipes.
    status = subprocess.run(  # noqa: S603 - fixed ps command and this test's child PID
        ("/bin/ps", "-p", str(pid), "-o", "stat="),
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    return bool(status.stdout.strip()) and not status.stdout.lstrip().startswith("Z")


def _assert_stopped(pid: int) -> None:
    deadline = time.monotonic() + 3
    while _is_running(pid) and time.monotonic() < deadline:
        threading.Event().wait(0.02)
    assert not _is_running(pid), "synthetic OCR descendant remained running"


@pytest.mark.parametrize(
    "mode", ["timeout", "overflow", "stdout-holder", "stdin-holder", "broken-input"]
)
def test_ocr_failure_stops_descendants_and_preserves_caller_group(
    tmp_path: Path, mode: str
) -> None:
    script = tmp_path / "synthetic-ocr-tree.py"
    script.write_text(_TREE_SCRIPT)
    ready_path, release_path = tmp_path / "ready", tmp_path / "release"
    os.mkfifo(ready_path)
    os.mkfifo(release_path)
    ready = os.open(ready_path, os.O_RDWR | os.O_NONBLOCK)
    release = os.open(release_path, os.O_RDWR | os.O_NONBLOCK)
    caller_group = os.getpgrp()
    result: queue.Queue[object] = queue.Queue()
    transcriber = BoundedLocalOCRTranscriber(
        command=(sys.executable, str(script), mode, str(ready_path), str(release_path)),
        name="synthetic_containment",
        version="1",
        timeout_seconds=3,
        maximum_output_bytes=64,
    )
    page = SourcePage(
        principal_id="prn_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_number=1,
        observed_at=datetime(2026, 9, 5, tzinfo=UTC),
        content=b"%PDF-synthetic"
        + (b"x" * 8_388_608 if mode in {"stdin-holder", "broken-input"} else b""),
        representation_media_type="application/pdf",
    )

    def transcribe() -> None:
        try:
            result.put(transcriber.transcribe(page))
        except Exception as error:
            result.put(error)

    runner = threading.Thread(target=transcribe, daemon=True)
    parent = None
    group = None
    descendant = None
    try:
        runner.start()
        readable, _, _ = select.select([ready], [], [], 5)
        assert readable, "synthetic OCR descendant did not signal readiness"
        parent, group, descendant = map(int, os.read(ready, 128).split())
        assert parent == group
        assert group != caller_group
        assert _is_running(descendant)
        os.write(release, b"G")
        runner.join(timeout=8)
        assert not runner.is_alive(), "OCR failure exceeded the bounded cleanup interval"
        outcome = result.get_nowait()
        assert isinstance(outcome, GoodNotesTranscriptionError), outcome
        if mode == "broken-input":
            assert "input was not consumed" in str(outcome)
        assert "SYNTHETIC-OCR-CONTENT" not in str(outcome)
        assert len(str(outcome)) < 200
        _assert_stopped(descendant)
        _assert_stopped(parent)
        assert os.getpgrp() == caller_group
        os.kill(os.getpid(), 0)
    finally:
        if group is not None and group != caller_group:
            with suppress(ProcessLookupError):
                os.killpg(group, signal.SIGKILL)
        elif parent is not None:
            # Even a regression in group isolation must not leak the synthetic tree.
            for pid in (parent, descendant):
                if pid is not None:
                    with suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)
        os.close(ready)
        os.close(release)
        runner.join(timeout=2)
        if descendant is not None:
            _assert_stopped(descendant)
