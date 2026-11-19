"""Synthetic end-to-end contract tests for the standalone SDCR publisher.

No network, provider accounts, credentials, production file mounts, or source writes.
"""

import asyncio
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.sdcc_publish import (
    PublicationError,
    RemoteFilesAPI,
    _relative_path,
    _spec,
    inventory,
    publish,
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SyntheticFilesWorkspace:
    """Simulates MY-PA create-only, stat/digest, binary and directory capabilities."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes | None] = {"SDCR": None, "SDCR/20-Programs": None,
                                                "SDCR/40-Publication": None}
        self.versions: dict[str, int] = dict.fromkeys(self.entries, 1)
        self.writes: dict[str, int] = {}
        self.fail_upload_relative: str | None = None

    def _entry(self, name: str) -> dict:
        if name not in self.entries:
            raise PublicationError("not_found")
        blob = self.entries[name]
        result = {"kind": "directory" if blob is None else "file", "path": name,
                  "version": "fv1_test_" + str(self.versions[name]),
                  "size": None if blob is None else len(blob)}
        if blob is not None:
            result["sha256"] = sha(blob)
        return result

    async def call(self, capability: str, payload: dict, *, write: bool = False) -> dict:
        assert payload.get("workspace_id") == "mcp"
        name = payload.get("path", "")
        if capability == "files.stat":
            return self._entry(name)
        if capability == "files.mkdir":
            assert write
            parts = name.split("/")
            for i in range(1, len(parts) + 1):
                parent = "/".join(parts[:i])
                if parent not in self.entries:
                    self.entries[parent] = None
                    self.versions[parent] = 1
                assert self.entries[parent] is None
            return self._entry(name)
        if capability == "files.write_text":
            assert write
            if name in self.entries:
                raise PublicationError("conflict")
            data = payload["text"].encode("utf-8")
            self.entries[name] = data
            self.versions[name] = 1
            self.writes[name] = self.writes.get(name, 0) + 1
            return self._entry(name)
        raise AssertionError(f"Unexpected capability {capability}")

    async def upload(self, local: Path, destination: str, digest: str, size: int) -> dict:
        if self.fail_upload_relative and destination.endswith(self.fail_upload_relative):
            raise PublicationError("simulated_transport_failure")
        if destination in self.entries:
            raise PublicationError("conflict")
        data = local.read_bytes()
        assert sha(data) == digest and len(data) == size
        self.entries[destination] = data
        self.versions[destination] = 1
        self.writes[destination] = self.writes.get(destination, 0) + 1
        return self._entry(destination)


def spec(session_id: str = "SESSION-20261119-365-001") -> dict:
    return {"session_id": session_id, "session_date": "2026-11-19",
            "work_item_id": "365", "program": "shared-platform",
            "workstream": "cross-client-publication", "source_client": "synthetic-agent",
            "publisher_client": "synthetic-publisher", "execution_lane": "C",
            "next_action": "review synthetic results", "github": {"repo": "RMF112018/my-pa",
            "base_sha": "a" * 40, "head_sha": "b" * 40, "tree_sha": "c" * 40},
            "artifact_statuses": {"failed/evidence.log": "FAILED_EVIDENCE"}}


def payload(workspace: SyntheticFilesWorkspace, path: str) -> dict:
    return json.loads(workspace.entries[path].decode("utf-8"))


def run(pub: SyntheticFilesWorkspace, folder: Path, data: dict) -> dict:
    return asyncio.run(publish(pub, folder, data))


def test_end_to_end_text_binary_failed_evidence_and_handoff(tmp_path: Path) -> None:
    (tmp_path / "failed").mkdir()
    (tmp_path / "report.md").write_bytes(b"Report\r\nlast line\n")
    (tmp_path / "failed/evidence.log").write_bytes(b"FAILED_ASSERTION\n")
    (tmp_path / "package.zip").write_bytes(b"\x00\xff\xaa\xfe\nBINARY\x00")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/cache.pyc").write_bytes(b"\x00TEMP")
    client = SyntheticFilesWorkspace()
    outcome = run(client, tmp_path, spec())
    assert outcome["status"] == "READY_FOR_HANDOFF"
    assert "365" in outcome["handoff"] and outcome["manifest_version"] in outcome["handoff"]
    assert outcome["verified"] == outcome["total"] == 3
    manifest = payload(client, outcome["manifest_path"])
    assert manifest["canonical_authority_activated"] is False
    assert manifest["transient_exclusions"] == [{"category": "tool_cache", "count": 1,
                                                  "rule": "TRANSIENT_EXCLUSION_POLICY_v3"}]
    assert {x["relative_path"] for x in manifest["artifacts"]} == {
        "report.md", "failed/evidence.log", "package.zip"}
    assert [
        x["status"] for x in manifest["artifacts"] if x["relative_path"].startswith("failed/")
    ] == ["FAILED_EVIDENCE"]
    for entry in manifest["artifacts"]:
        local_bytes = (tmp_path / entry["relative_path"]).read_bytes()
        assert client.entries[entry["path"]] == local_bytes  # independent receiver read
        assert entry["sha256"] == sha(local_bytes)
        assert entry["version"] is not None
        assert entry["hash_scope"] == "stored_raw_bytes"
    reg = payload(client, outcome["registry_path"])
    assert reg["manifest_path"] == outcome["manifest_path"]
    assert "/2026/11/" in outcome["registry_path"]
    receipt = payload(client, outcome["receipt_path"])
    assert receipt["verified_count"] == 3
    assert receipt["disposition"] == "READY_FOR_HANDOFF"


def test_idempotent_replay_no_new_writes(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("pass\n")
    spec0 = spec()
    spec0["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    first = run(store, tmp_path, spec0)
    writes = store.writes.copy()
    second = run(store, tmp_path, spec0)
    assert first == second
    assert writes == store.writes


def test_conflict_never_overwrites_canonical_bytes(tmp_path: Path) -> None:
    file = tmp_path / "one.md"
    file.write_bytes(b"original\n")
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    result = run(store, tmp_path, data)
    original_path = payload(store, result["manifest_path"])["artifacts"][0]["path"]
    old_bytes = store.entries[original_path]
    file.write_bytes(b"changed\n")
    with pytest.raises(PublicationError, match="metadata_publication_conflict"):
        run(store, tmp_path, data)
    assert store.entries[original_path] == old_bytes


def test_partial_upload_failure_keeps_successful_evidence_and_reports_incomplete(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_bytes(b"ok\n")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-synthetic\n")
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    store.fail_upload_relative = "/b.pdf"
    result = run(store, tmp_path, data)
    assert result["status"] == "PUBLICATION_INCOMPLETE"
    assert result["verified"] == 1 and result["total"] == 2
    manifest = payload(store, result["manifest_path"])
    failed = next(a for a in manifest["artifacts"] if a["relative_path"] == "b.pdf")
    assert failed["version"] is None and failed["reason"] == "artifact_missing_or_mismatched"
    assert payload(store, result["receipt_path"])["disposition"] == "PUBLICATION_INCOMPLETE"


def test_secret_withheld_not_uploaded_or_reported_in_plaintext(tmp_path: Path) -> None:
    secret = b"-----BEGIN PRIVATE KEY-----\ntest-secret\n-----END PRIVATE KEY-----"
    (tmp_path / "secret.pem").write_bytes(secret)
    (tmp_path / "ordinary.txt").write_bytes(b"clean\n")
    store = SyntheticFilesWorkspace()
    data = spec()
    data["artifact_statuses"] = {}
    result = run(store, tmp_path, data)
    assert result["status"] == "PUBLICATION_INCOMPLETE"
    m = payload(store, result["manifest_path"])
    withheld = next(a for a in m["artifacts"] if a["relative_path"] == "secret.pem")
    assert withheld["status"] == "PROTECTED_WITHHELD"
    assert withheld["path"] is None and withheld["sha256"] is None
    assert secret not in b"".join(x for x in store.entries.values() if isinstance(x, bytes))
    assert m["publication_status"] == "PUBLICATION_INCOMPLETE"


def test_secret_in_zip_withheld(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "package.zip", "w") as archive:
        archive.writestr("inner/key.txt", b"-----BEGIN PRIVATE KEY-----\nABC\n")
    store = SyntheticFilesWorkspace()
    data = spec()
    data["artifact_statuses"] = {}
    result = run(store, tmp_path, data)
    assert result["status"] == "PUBLICATION_INCOMPLETE"
    assert len(payload(store, result["manifest_path"])["artifacts"]) == 1
    assert all(not p.endswith("/artifacts/package.zip") for p in store.entries)


def test_invalid_spec_or_paths_are_rejected_without_writes(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_bytes(b"content")
    data = spec()
    data["artifact_statuses"] = {"../outside": "FINAL"}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(data))
    with pytest.raises(PublicationError, match="invalid_artifact_path"):
        _spec(path)
    with pytest.raises(PublicationError, match="invalid_artifact_path"):
        _relative_path("../../home")
    store = SyntheticFilesWorkspace()
    data["artifact_statuses"] = {}
    data["session_id"] = "../not-valid"
    with pytest.raises(PublicationError, match="invalid_identity"):
        run(store, tmp_path, data)


def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    (tmp_path / "original.txt").write_text("safe")
    (tmp_path / "alias").symlink_to(tmp_path / "original.txt")
    with pytest.raises(PublicationError, match="symlink_refused"):
        inventory(tmp_path, {})


def test_two_clients_publish_separate_sessions_in_same_registry(tmp_path: Path) -> None:
    (tmp_path / "report.txt").write_bytes(b"two clients\n")
    first = spec("SESSION-20261119-A")
    second = spec("SESSION-20261119-B")
    first["artifact_statuses"] = second["artifact_statuses"] = {}
    first["source_client"] = "ChatGPT"
    second["source_client"] = "local-code-agent"
    store = SyntheticFilesWorkspace()
    one = run(store, tmp_path, first)
    two = run(store, tmp_path, second)
    assert one["registry_path"] != two["registry_path"]
    assert payload(store, one["manifest_path"])["source_client"] == "ChatGPT"
    assert payload(store, two["manifest_path"])["source_client"] == "local-code-agent"


class McpStub:
    def __init__(self, response: SimpleNamespace | None) -> None:
        self.response = response
        self.last: tuple[str, dict] | None = None

    async def call_tool(self, name: str, args: dict) -> SimpleNamespace | None:
        self.last = name, args
        return self.response


def test_facade_structured_and_text_response_without_credentials() -> None:
    response = SimpleNamespace(
        is_error=False, structured_content={"result": {"kind": "directory"}}, content=[]
    )
    stub = McpStub(response)
    api = RemoteFilesAPI(stub, "https://synthetic.example/mcp")
    res = asyncio.run(api.call("files.stat", {"workspace_id": "mcp", "path": "SDCR"}))
    assert res["kind"] == "directory"
    assert stub.last[0] == "my_pa.read"
    response.structured_content = None
    response.content = [SimpleNamespace(text=json.dumps({"result": {"version": "fv1_testing"}}))]
    assert (
        asyncio.run(api.call("files.stat", {"workspace_id": "mcp", "path": "x"}))["version"]
        == "fv1_testing"
    )
    response.is_error = True
    response.content = [SimpleNamespace(text=json.dumps({"error": {"code": "not_found"}}))]
    with pytest.raises(PublicationError, match="not_found"):
        asyncio.run(api.call("files.stat", {"workspace_id": "mcp", "path": "x"}))


def test_endpoint_refuses_insecure_and_credential_urls() -> None:
    stub = McpStub(None)
    for url in (
        "http://example.test/mcp",
        "https://user:pass@example.test/mcp",
        "https://example.test/mcp?token=bad",
        "https://example.test/other",
    ):
        with pytest.raises(PublicationError, match="invalid_endpoint"):
            RemoteFilesAPI(stub, url)


def test_multi_megabyte_binary_exact_digest(tmp_path: Path) -> None:
    large = b"X" * (2 * 1024 * 1024 + 11) + b"\0END"
    (tmp_path / "archive.bin").write_bytes(large)
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    result = run(store, tmp_path, data)
    entry = payload(store, result["manifest_path"])["artifacts"][0]
    assert result["status"] == "READY_FOR_HANDOFF"
    assert store.entries[entry["path"]] == large
    assert entry["sha256"] == sha(large)


def test_git_capture_exact_commit_and_reconstructable_patch(tmp_path: Path) -> None:
    import subprocess
    from scripts.sdcc_publish import capture_git

    root = tmp_path / "repo"
    out = tmp_path / "output"
    root.mkdir()
    out.mkdir()
    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603,S607 - deterministic synthetic Git setup
            ["git", *args], cwd=root, check=True, capture_output=True
        ).stdout.decode().strip()
    git("init", "-q")
    git("config", "user.email", "synthetic@example.test")
    git("config", "user.name", "Synthetic Test")
    (root / "source.txt").write_text("version one\n")
    git("add", "source.txt")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (root / "source.txt").write_text("version two\n")
    git("add", "source.txt")
    git("commit", "-qm", "head")
    data = spec()
    data["github"]["base_sha"] = base
    data["github"]["head_sha"] = git("rev-parse", "HEAD")
    data["github"]["tree_sha"] = git("rev-parse", "HEAD^{tree}")
    capture_git(out, data, root)
    assert b"+version two" in (out / "_git/changes.patch").read_bytes()
    assert b"source.txt" in (out / "_git/changed-paths.txt").read_bytes()
    store = SyntheticFilesWorkspace()
    data["artifact_statuses"] = {}
    result = run(store, out, data)
    assert result["verified"] == 3
    assert result["status"] == "READY_FOR_HANDOFF"
    (root / "untracked.txt").write_text("dirty")
    with pytest.raises(PublicationError, match="dirty_repository_refused"):
        capture_git(out, data, root)
