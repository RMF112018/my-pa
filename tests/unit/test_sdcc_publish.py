"""Synthetic end-to-end contract tests for the standalone SDCR publisher.

No network, provider accounts, credentials, production file mounts, or source writes.
"""

import asyncio
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import sdcc_publish as publisher
from scripts.sdcc_publish import (
    Artifact,
    PublicationError,
    RemoteFilesAPI,
    TEXT_LIMIT,
    _relative_path,
    _spec,
    capture_git,
    inventory,
    publish,
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SyntheticFilesWorkspace:
    """Simulates MY-PA create-only, stat/digest, binary and directory capabilities."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes | None] = {
            "SDCR": None,
            "SDCR/20-Programs": None,
            "SDCR/40-Publication": None,
        }
        self.versions: dict[str, int] = dict.fromkeys(self.entries, 1)
        self.writes: dict[str, int] = {}
        self.fail_upload_relative: str | None = None
        self.fail_text_relative: str | None = None
        self.drop_text_ack_relative: str | None = None
        self.drop_upload_ack_relative: str | None = None
        self.hide_version_relative: str | None = None
        self.uploaded_paths: set[str] = set()

    def _entry(self, name: str) -> dict:
        if name not in self.entries:
            raise PublicationError("not_found")
        blob = self.entries[name]
        result = {
            "kind": "directory" if blob is None else "file",
            "path": name,
            "version": "fv1_test_" + str(self.versions[name]),
            "size": None if blob is None else len(blob),
        }
        if blob is not None:
            result["sha256"] = sha(blob)
        if self.hide_version_relative and name.endswith(self.hide_version_relative):
            result.pop("version")
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
            if self.fail_text_relative and name.endswith(self.fail_text_relative):
                raise PublicationError("simulated_text_failure")
            if name in self.entries:
                raise PublicationError("conflict")
            data = payload["text"].encode("utf-8")
            if len(data) > TEXT_LIMIT:
                raise PublicationError("metadata_exceeds_text_limit")
            self.entries[name] = data
            self.versions[name] = 1
            self.writes[name] = self.writes.get(name, 0) + 1
            if self.drop_text_ack_relative and name.endswith(self.drop_text_ack_relative):
                raise PublicationError("simulated_lost_ack")
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
        self.uploaded_paths.add(destination)
        if self.drop_upload_ack_relative and destination.endswith(self.drop_upload_ack_relative):
            raise PublicationError("simulated_lost_ack")
        return self._entry(destination)


def spec(session_id: str = "SESSION-20261119-365-001") -> dict:
    return {
        "session_id": session_id,
        "session_date": "2026-11-19",
        "work_item_id": "365",
        "program": "shared-platform",
        "workstream": "cross-client-publication",
        "source_client": "synthetic-agent",
        "publisher_client": "synthetic-publisher",
        "execution_lane": "C",
        "next_action": "review synthetic results",
        "github": {
            "repo": "RMF112018/my-pa",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "tree_sha": "c" * 40,
        },
        "artifact_statuses": {"failed/evidence.log": "FAILED_EVIDENCE"},
    }


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
    assert manifest["transient_exclusions"] == [
        {"category": "tool_cache", "count": 1, "rule": "TRANSIENT_EXCLUSION_POLICY_v3"}
    ]
    assert {x["relative_path"] for x in manifest["artifacts"]} == {
        "report.md",
        "failed/evidence.log",
        "package.zip",
    }
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
    marker = b"-----BEGIN " + b"PRIVATE KEY-----"
    secret = marker + b"\ntest-secret\n-----END " + b"PRIVATE KEY-----"
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
        archive.writestr("inner/key.txt", b"-----BEGIN " + b"PRIVATE KEY-----\nABC\n")
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
    root = tmp_path / "repo"
    out = tmp_path / "output"
    root.mkdir()
    out.mkdir()

    def git(*args: str) -> str:
        executable = shutil.which("git")
        assert executable is not None
        return (
            subprocess.run(  # noqa: S603 - deterministic synthetic Git setup
                [executable, *args], cwd=root, check=True, capture_output=True
            )
            .stdout.decode()
            .strip()
        )

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


def _synthetic_many(
    monkeypatch: pytest.MonkeyPatch, folder: Path, count: int
) -> list[Artifact]:
    """An in-memory 10k-entry inventory; just one tiny file touches local disk."""
    local = folder / "fixture.bin"
    local.write_bytes(b"ok")
    items = [
        Artifact(
            f"long/α-{i:05d}-{'x' * 80}.txt",
            local,
            2,
            sha(b"ok"),
            "FINAL",
        )
        for i in range(count)
    ]
    monkeypatch.setattr(publisher, "inventory", lambda _source, _statuses: (items, []))
    return items


@pytest.mark.parametrize("count", [1, 150, 220, 10_000])
def test_manifest_real_text_limit_falls_back_to_verified_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    _synthetic_many(monkeypatch, tmp_path, count)
    store = SyntheticFilesWorkspace()
    data = spec()
    data["artifact_statuses"] = {}
    outcome = run(store, tmp_path, data)
    assert outcome["status"] == "READY_FOR_HANDOFF"
    assert outcome["verified"] == outcome["total"] == count
    manifest_bytes = store.entries[outcome["manifest_path"]]
    assert isinstance(manifest_bytes, bytes)
    manifest = json.loads(manifest_bytes)
    assert publisher._json(manifest).encode("utf-8") == manifest_bytes
    assert all(item["version"] for item in manifest["artifacts"])
    assert all(item["sha256"] == sha(b"ok") for item in manifest["artifacts"])
    assert any("α" in item["relative_path"] for item in manifest["artifacts"])
    assert (outcome["manifest_path"] in store.uploaded_paths) == (
        len(manifest_bytes) > TEXT_LIMIT
    )
    assert payload(store, outcome["recovery_path"])["publication_status"] == "NOT_READY"
    assert payload(store, outcome["recovery_locator_path"])["status"] == "NOT_READY"
    registry = payload(store, outcome["registry_path"])
    assert registry["status"] == "AWAITING_TERMINAL_RECEIPT"
    receipt = payload(store, outcome["receipt_path"])
    assert receipt["disposition"] == "READY_FOR_HANDOFF"
    assert receipt["manifest_sha256"] == sha(manifest_bytes)
    assert receipt["registry_sha256"] == sha(store.entries[outcome["registry_path"]])
    if count == 10_000:
        assert len(manifest_bytes) > 1024 * 1024


def test_failed_oversized_manifest_has_durable_recovery_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synthetic_many(monkeypatch, tmp_path, 300)
    store = SyntheticFilesWorkspace()
    data = spec()
    data["artifact_statuses"] = {}
    store.fail_upload_relative = "/SESSION_MANIFEST.json"
    with pytest.raises(PublicationError, match="artifact_missing_or_mismatched"):
        run(store, tmp_path, data)
    prefix = publisher._session_path(data)
    assert f"{prefix}/SESSION_RECOVERY.json" in store.entries
    assert f"{prefix}/SESSION_PUBLICATION_FAILURE.json" in store.entries
    assert f"{prefix}/SESSION_MANIFEST.json" not in store.entries
    assert f"{prefix}/SESSION_PUBLICATION_RECEIPT.json" not in store.entries
    assert any(p.endswith(".recovery.json") for p in store.entries)
    store.fail_upload_relative = None
    outcome = run(store, tmp_path, data)
    assert outcome["status"] == "READY_FOR_HANDOFF"
    assert payload(store, outcome["receipt_path"])["verified_count"] == 300


@pytest.mark.parametrize(
    "failed_suffix",
    [
        "/SESSION-20261119-365-001.recovery.json",
        "/SESSION-20261119-365-001.json",
        "/SESSION_PUBLICATION_RECEIPT.json",
    ],
)
def test_metadata_failure_cannot_claim_ready_and_retry_recovers(
    tmp_path: Path, failed_suffix: str
) -> None:
    (tmp_path / "one.md").write_text("ok\n")
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    store.fail_text_relative = failed_suffix
    with pytest.raises(PublicationError, match="metadata_publication_conflict"):
        run(store, tmp_path, data)
    prefix = publisher._session_path(data)
    assert f"{prefix}/SESSION_PUBLICATION_RECEIPT.json" not in store.entries
    assert f"{prefix}/SESSION_RECOVERY.json" in store.entries
    if failed_suffix.endswith(".recovery.json"):
        assert not any("/artifacts/" in item for item in store.entries)
    else:
        registry = f"{publisher.REGISTRY_ROOT}/2026/11/{data['session_id']}.json"
        if registry in store.entries:
            assert payload(store, registry)["status"] != "READY_FOR_HANDOFF"
    store.fail_text_relative = None
    assert run(store, tmp_path, data)["status"] == "READY_FOR_HANDOFF"


@pytest.mark.parametrize(
    "drop_suffix",
    ["/SESSION_RECOVERY.json", "/SESSION_PUBLICATION_RECEIPT.json"],
)
def test_lost_inline_metadata_ack_uses_digest_readback(
    tmp_path: Path, drop_suffix: str
) -> None:
    (tmp_path / "one.md").write_text("ok\n")
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    store.drop_text_ack_relative = drop_suffix
    first = run(store, tmp_path, data)
    previous_writes = store.writes.copy()
    second = run(store, tmp_path, data)
    assert first == second
    assert previous_writes == store.writes


def test_lost_binary_manifest_ack_uses_digest_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synthetic_many(monkeypatch, tmp_path, 250)
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    store.drop_upload_ack_relative = "/SESSION_MANIFEST.json"
    first = run(store, tmp_path, data)
    previous_writes = store.writes.copy()
    assert first["manifest_path"] in store.uploaded_paths
    assert run(store, tmp_path, data) == first
    assert store.writes == previous_writes


def test_recovery_binding_refuses_changed_source_on_replay(tmp_path: Path) -> None:
    local = tmp_path / "one.md"
    local.write_bytes(b"one")
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    store.fail_text_relative = "/SESSION_MANIFEST.json"
    with pytest.raises(PublicationError, match="metadata_publication_conflict"):
        run(store, tmp_path, data)
    local.write_bytes(b"two")
    store.fail_text_relative = None
    with pytest.raises(PublicationError, match="metadata_publication_conflict"):
        run(store, tmp_path, data)
    assert payload(store, f"{publisher._session_path(data)}/SESSION_RECOVERY.json")[
        "publication_status"
    ] == "NOT_READY"


def test_missing_declared_artifact_refused_before_remote_publication(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("ok")
    data = spec()
    data["artifact_statuses"] = {"missing.md": "SOURCE"}
    store = SyntheticFilesWorkspace()
    with pytest.raises(PublicationError, match="status_names_missing_artifact"):
        run(store, tmp_path, data)
    assert not any("/sessions/" in item for item in store.entries)


def test_unverified_artifact_version_blocks_ready(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("ok")
    data = spec()
    data["artifact_statuses"] = {}
    store = SyntheticFilesWorkspace()
    store.hide_version_relative = "/one.md"
    result = run(store, tmp_path, data)
    assert result["status"] == "PUBLICATION_INCOMPLETE"
    assert payload(store, result["receipt_path"])["disposition"] == "PUBLICATION_INCOMPLETE"
    assert payload(store, result["manifest_path"])["artifacts"][0]["version"] is None
