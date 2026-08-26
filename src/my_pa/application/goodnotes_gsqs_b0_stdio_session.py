"""Synchronous stdio MCP client for canonical `serve-eval-mcp`. No `mcp` SDK import."""

from __future__ import annotations

import base64
import json
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from my_pa.contracts.v1.base import CONTRACT_VERSION
from my_pa.domain.common.time import format_rfc3339, utc_now
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.purpose import Purpose

EVALUATION_TOOLS = frozenset({"goodnotes.work", "goodnotes.content"})
HANDLES_NAME = "EVALUATION_HANDLES.json"
STDERR_NAME = "serve-eval-mcp.stderr"


class StdioHostError(ValueError):
    """Stdio MCP child refused, crashed, or timed out."""


class StdioEvalSession:
    """Owns a `serve-eval-mcp` child and speaks newline JSON-RPC on its pipes."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        evidence_dir: Path,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._command = [str(item) for item in command]
        self._cwd = cwd
        self._env = dict(env)
        self._evidence_dir = evidence_dir
        self._timeout = timeout_seconds
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_handle: Any = None
        self._next_id = 1
        self._handles: dict[str, dict[str, str]] = {}
        self._principal_id = capture_principal_id(LOCAL_OPERATOR_UUID)

    def initialize_and_list_tools(self) -> tuple[str, ...]:
        self._spawn()
        self._wait_for_handles()
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "gsqs-b0-local-exec", "version": "1"},
            },
        )
        self._notify("notifications/initialized")
        listed = self._rpc("tools/list", {})
        tools = listed.get("tools")
        if not isinstance(tools, list):
            raise StdioHostError("tools/list mismatch")
        names = tuple(sorted(str(item.get("name")) for item in tools if isinstance(item, dict)))
        extra = set(names) - EVALUATION_TOOLS
        if extra:
            raise StdioHostError("tools/list mismatch")
        if set(names) != EVALUATION_TOOLS:
            raise StdioHostError("tools/list mismatch")
        return names

    def fetch_png(self, *, case_id: str, expected_sha256: str) -> bytes:
        handle = self._handles.get(case_id)
        if handle is None:
            raise StdioHostError("raster missing")
        work = self._call_tool(
            "goodnotes.work",
            Purpose.GOODNOTES_WORK.value,
            {"run_id": handle["run_id"], "page_version_id": handle["page_version_id"]},
        )
        content_sha = str(work.get("content_sha256") or handle["content_sha256"])
        if content_sha != expected_sha256:
            raise StdioHostError("raster hash mismatch")
        content = self._call_tool(
            "goodnotes.content",
            Purpose.GOODNOTES_CONTENT.value,
            {
                "run_id": handle["run_id"],
                "page_version_id": handle["page_version_id"],
                "content_sha256": content_sha,
            },
            expect_image=True,
        )
        png = content["png"]
        if not isinstance(png, bytes):
            raise StdioHostError("goodnotes.content returned no PNG")
        return png

    def close(self) -> None:
        process = self._process
        if process is not None:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=self._timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self._timeout)
            self._process = None
        handle = self._stderr_handle
        if handle is not None:
            handle.close()
            self._stderr_handle = None

    def _spawn(self) -> None:
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = self._evidence_dir / STDERR_NAME
        try:
            self._stderr_handle = stderr_path.open("wb")
            self._process = subprocess.Popen(  # noqa: S603 - argument list is constructed by this host
                self._command,
                cwd=str(self._cwd),
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_handle,
            )
        except OSError as error:
            if self._stderr_handle is not None:
                self._stderr_handle.close()
                self._stderr_handle = None
            raise StdioHostError("stdio server failed startup") from error
        if self._process.stdin is None or self._process.stdout is None:
            raise StdioHostError("stdio server failed startup")

    def _wait_for_handles(self) -> None:
        deadline = time.monotonic() + self._timeout
        path = self._evidence_dir / HANDLES_NAME
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise StdioHostError("stdio server failed startup")
            if path.is_file() and not path.is_symlink():
                payload = json.loads(path.read_text(encoding="utf-8"))
                raw = payload.get("handles") if isinstance(payload, dict) else None
                if isinstance(raw, list) and raw:
                    mapped: dict[str, dict[str, str]] = {}
                    for item in raw:
                        if isinstance(item, dict) and item.get("case_id"):
                            mapped[str(item["case_id"])] = {
                                "run_id": str(item["run_id"]),
                                "page_version_id": str(item["page_version_id"]),
                                "content_sha256": str(item["content_sha256"]),
                            }
                    if mapped:
                        self._handles = mapped
                        return
            time.sleep(0.05)
        raise StdioHostError("stdio server failed startup")

    def _call_tool(
        self,
        name: str,
        purpose: str,
        payload: dict[str, str],
        *,
        expect_image: bool = False,
    ) -> dict[str, Any]:
        result = self._rpc(
            "tools/call",
            {
                "name": name,
                "arguments": {
                    "request_id": f"req-{name}-{self._next_id}",
                    "purpose": purpose,
                    "principal_id": self._principal_id,
                    "requested_at": format_rfc3339(utc_now()),
                    "contract_version": CONTRACT_VERSION,
                    "payload": payload,
                },
            },
        )
        if result.get("isError") is True:
            raise StdioHostError(f"{name} failed")
        blocks = result.get("content")
        if not isinstance(blocks, list) or not blocks:
            raise StdioHostError(f"{name} returned no content")
        text = blocks[0].get("text") if isinstance(blocks[0], dict) else None
        if not isinstance(text, str):
            raise StdioHostError(f"{name} returned no envelope")
        envelope = json.loads(text)
        body = envelope.get("result") if isinstance(envelope, dict) else None
        if not isinstance(body, dict):
            raise StdioHostError(f"{name} returned no result")
        if expect_image:
            image = None
            for block in blocks[1:]:
                if isinstance(block, dict) and block.get("type") == "image":
                    image = block.get("data")
                    break
            if not isinstance(image, str):
                raise StdioHostError("goodnotes.content returned no PNG")
            body = dict(body)
            body["png"] = base64.b64decode(image)
        return body

    def _rpc(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        message = self._read()
        if message.get("id") != request_id:
            raise StdioHostError("stdio RPC id mismatch")
        if "error" in message:
            raise StdioHostError(str(message["error"]))
        result = message.get("result")
        if not isinstance(result, dict):
            raise StdioHostError("stdio RPC result missing")
        return result

    def _notify(self, method: str) -> None:
        self._write({"jsonrpc": "2.0", "method": method})

    def _write(self, message: dict[str, object]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise StdioHostError("stdio server failed startup")
        process.stdin.write((json.dumps(message) + "\n").encode())
        process.stdin.flush()

    def _read(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise StdioHostError("stdio server failed startup")
        ready, _, _ = select.select([process.stdout], [], [], self._timeout)
        if not ready:
            raise StdioHostError("analyzer/model timeout")
        line = process.stdout.readline()
        if not line:
            raise StdioHostError("process crash")
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise StdioHostError("stdio RPC is not an object")
        return payload


def serve_eval_mcp_command(
    *,
    python: str = sys.executable,
    authorization: Path,
    evidence_dir: Path,
    campaign_fixture: Path | None = None,
) -> list[str]:
    command = [
        python,
        "apps/cli/gsqs_b0.py",
        "serve-eval-mcp",
        "--authorization",
        str(authorization),
        "--evidence-dir",
        str(evidence_dir),
    ]
    if campaign_fixture is not None:
        command.extend(["--campaign-fixture", str(campaign_fixture)])
    return command


def stdio_env(*, raster_root: Path, pythonpath: Sequence[Path]) -> dict[str, str]:
    env = dict(os.environ)
    env["MY_PA_GSQS_B0_RASTER_ROOT"] = str(raster_root)
    env["PYTHONPATH"] = os.pathsep.join(str(item) for item in pythonpath)
    env.pop("MY_PA_ROUTELLM_API_KEY", None)
    env.pop("MY_PA_ROUTELLM_BASE_URL", None)
    env.pop("MY_PA_GSQS_B0_ROUTELLM_ACTIVATION", None)
    return env
