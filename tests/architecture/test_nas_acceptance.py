"""NAS-10 synthetic evidence, independent review, and inert issuance contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEAD = "1" * 40
TREE = "2" * 40
ENGINE_ID = "synthetic-engine-id"
ENGINE_NAME = "synthetic-nas"


def _module() -> ModuleType:
    path = ROOT / "ops/nas/nas10_acceptance_gate.py"
    spec = importlib.util.spec_from_file_location("nas10_acceptance_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runner_module() -> ModuleType:
    path = ROOT / "ops/nas/run_synthetic_acceptance.py"
    spec = importlib.util.spec_from_file_location("run_synthetic_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runner(command: list[str]) -> str:
    assert command[0] == "/usr/bin/git"
    if command[-1] == "HEAD":
        return HEAD
    if command[-1] == "HEAD^{tree}":
        return TREE
    if command[-1] == "--porcelain":
        return ""
    raise AssertionError(command)


def _fixture(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    matrix_path = ROOT / "ops/nas/acceptance-matrix.toml"
    matrix = tomllib.loads(matrix_path.read_text())
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    results: dict[str, str] = {}
    for name, case in matrix["cases"].items():
        selectors = case["selectors"]
        log = evidence_dir / f"{name}.log"
        log.write_text(f"{name}: synthetic pass\n")
        receipt = {
            "schema": "my-pa.nas-10-case-result.v1",
            "case": name,
            "status": "pass",
            "synthetic": True,
            "activation_performed": False,
            "repository_commit": HEAD,
            "repository_tree": TREE,
            "nas_engine_id": ENGINE_ID,
            "nas_engine_name": ENGINE_NAME,
            "command": (
                ["external_device", name]
                if case["requirement"] == "external_device"
                else [
                    "python3",
                    "-m",
                    "pytest",
                    "--import-mode=importlib",
                    "-q",
                    *selectors,
                ]
            ),
            "requirement": case["requirement"],
            "behaviors": case["behaviors"],
            "external_device_verified": case["requirement"] == "external_device",
            "output_sha256": _sha(log),
        }
        result = evidence_dir / f"{name}.json"
        result.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
        results[name] = _sha(result)
    evidence = evidence_dir / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": "my-pa.nas-10-evidence.v1",
                "status": "complete",
                "synthetic": True,
                "activation_performed": False,
                "repository_commit": HEAD,
                "repository_tree": TREE,
                "nas_engine_id": ENGINE_ID,
                "nas_engine_name": ENGINE_NAME,
                "matrix_sha256": _sha(matrix_path),
                "image_manifest_sha256": "DEFERRED_UNTIL_IMAGE_WRITTEN",
                "runtime_admission_sha256": "DEFERRED_UNTIL_ADMISSION_WRITTEN",
                "resolved_compose_sha256": "5" * 64,
                "results": results,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    image = tmp_path / "image-manifest.toml"
    image_sections = []
    image_ids = {"app": "a", "web": "b", "postgres": "c"}
    manifest_digests = {
        "app": "1" * 64,
        "web": "2" * 64,
        "postgres": "dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b",
    }
    for role in ("app", "web", "postgres"):
        digest = "sha256:" + manifest_digests[role]
        image_id = "sha256:" + image_ids[role] * 64
        reference = (
            "postgres@sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b"
            if role == "postgres"
            else f"my-pa-{role}@{digest}"
        )
        image_sections.append(
            f'[images.{role}]\nreference = "{reference}"\n'
            f'load_reference = "{image_id}"\noci_manifest_digest = "{digest}"\n'
            f'docker_image_id = "{image_id}"\narchive_sha256 = "{"6" * 64}"\n'
            f'build_metadata_sha256 = "{"7" * 64}"\n'
        )
    image.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\nstatus = "deployable"\n'
        f'repository_commit = "{HEAD}"\nrepository_tree = "{TREE}"\n'
        f'docker_engine_id = "{ENGINE_ID}"\ndocker_engine_name = "{ENGINE_NAME}"\n'
        'source_clean = true\nbuilt_at = "2026-08-13T12:00:00Z"\n'
        'target_os = "linux"\ntarget_architecture = "amd64"\n'
        f'python_runtime_lock_sha256 = "{"8" * 64}"\n'
        'postgres_source_tag = "postgres:17.10"\n'
        'postgres_index_digest = "sha256:7958605b474b3d264a969cb3a123d6aa'
        '00ad1e1fe9da8a69984dabb704d93317"\n' + "".join(image_sections)
    )
    service_ids = {
        "postgres": "sha256:" + "c" * 64,
        "gateway": "sha256:" + "a" * 64,
        "worker-enrollment": "sha256:" + "a" * 64,
        "worker-capture": "sha256:" + "a" * 64,
        "web": "sha256:" + "b" * 64,
        "proxy": "sha256:" + "e" * 64,
    }
    service_images = {**service_ids, "proxy": "caddy@sha256:" + "9" * 64}
    admission = tmp_path / "runtime-admission.toml"
    admission.write_text(
        'schema = "my-pa.nas-runtime-admission.v1"\nstatus = "admitted"\n'
        f'docker_engine_id = "{ENGINE_ID}"\ndocker_engine_name = "{ENGINE_NAME}"\n'
        f'image_manifest_sha256 = "{_sha(image)}"\n'
        "[resolved_compose_sha256]\n"
        f'smoke = "{"4" * 64}"\npilot = "{"5" * 64}"\n'
        "[service_images]\n"
        + "".join(f'{name} = "{value}"\n' for name, value in service_images.items())
        + "[service_image_ids]\n"
        + "".join(f'{name} = "{value}"\n' for name, value in service_ids.items())
    )
    for name, case in matrix["cases"].items():
        if case["requirement"] != "external_device":
            continue
        result_path = evidence_dir / f"{name}.json"
        result_document = json.loads(result_path.read_text())
        result_document.update(
            {
                "external_harness": "my-pa.nas10-external-device.v1",
                "disposable_engine_ack": "ACKNOWLEDGE_DISPOSABLE_DOCKER_ENGINE",
                "image_manifest_sha256": _sha(image),
                "runtime_admission_sha256": _sha(admission),
                "resolved_compose_sha256": "5" * 64,
            }
        )
        result_path.write_text(
            json.dumps(result_document, sort_keys=True, separators=(",", ":")) + "\n"
        )
        results[name] = _sha(result_path)
    evidence_document = json.loads(evidence.read_text())
    evidence_document["image_manifest_sha256"] = _sha(image)
    evidence_document["runtime_admission_sha256"] = _sha(admission)
    evidence_document["results"] = results
    evidence.write_text(json.dumps(evidence_document, sort_keys=True, separators=(",", ":")) + "\n")
    private = tmp_path / "reviewer-private.pem"
    public = evidence_dir / "reviewer-public.pem"
    subprocess.run(  # noqa: S603 - fixed OpenSSL and synthetic temporary key
        ["/usr/bin/openssl", "genrsa", "-out", str(private), "3072"], check=True
    )
    with public.open("wb") as output:
        subprocess.run(  # noqa: S603 - fixed OpenSSL and synthetic temporary key
            ["/usr/bin/openssl", "rsa", "-in", str(private), "-pubout"],
            check=True,
            stdout=output,
        )
    review = evidence_dir / "independent-review.toml"
    review.write_text(
        'schema = "my-pa.nas-10-independent-review.v1"\nstatus = "pass"\n'
        'independent = true\nreviewer_context = "detached-review-context"\n'
        f'reviewed_head = "{HEAD}"\nreviewed_tree = "{TREE}"\n'
        f'evidence_sha256 = "{_sha(evidence)}"\nmatrix_sha256 = "{_sha(matrix_path)}"\n'
        f'nas_engine_id = "{ENGINE_ID}"\nnas_engine_name = "{ENGINE_NAME}"\n'
        f'image_manifest_sha256 = "{_sha(image)}"\n'
        f'runtime_admission_sha256 = "{_sha(admission)}"\n'
        f'resolved_compose_sha256 = "{"5" * 64}"\n'
    )
    signature = evidence_dir / "independent-review.sig"
    subprocess.run(  # noqa: S603 - fixed OpenSSL and synthetic temporary key
        [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private),
            "-out",
            str(signature),
            str(review),
        ],
        check=True,
    )
    trust = (tmp_path / "review-trust.toml").resolve()
    trust.write_text(
        'schema = "my-pa.nas-10-review-trust.v1"\nstatus = "provisioned"\n'
        f'reviewer_public_key_sha256 = "{_sha(public)}"\n'
    )
    trust.chmod(0o400)
    image.chmod(0o400)
    admission.chmod(0o400)
    for artifact in evidence_dir.iterdir():
        artifact.chmod(0o400)
    evidence_dir.chmod(0o700)
    return {
        "evidence": evidence,
        "image": image,
        "admission": admission,
        "public": public,
        "review": review,
        "signature": signature,
        "trust": trust,
    }


def _verify(gate: ModuleType, paths: dict[str, Path]) -> tuple[list[str], dict[str, str]]:
    return gate.verify(
        paths["evidence"],
        paths["review"],
        paths["signature"],
        paths["public"],
        paths["image"],
        paths["admission"],
        review_trust=paths["trust"],
        expected_evidence_root=paths["evidence"].parent,
        trusted_owner_uid=os.getuid(),
        runner=_runner,
    )


def test_complete_synthetic_matrix_and_signed_exact_head_review_issue_candidate(
    tmp_path: Path,
) -> None:
    errors, candidate = _verify(_module(), _fixture(tmp_path))
    assert errors == []
    assert candidate["schema"] == "my-pa.nas-10-acceptance.v1"
    assert candidate["status"] == "pass"
    assert candidate["repository_commit"] == candidate["reviewed_head"] == HEAD
    assert candidate["repository_tree"] == TREE
    assert candidate["nas_engine_id"] == ENGINE_ID
    assert candidate["resolved_compose_sha256"] == "5" * 64
    assert "activated_at" not in candidate and "canonical_origin" not in candidate


def test_incomplete_fabricated_or_activation_evidence_cannot_issue_pass(tmp_path: Path) -> None:
    gate = _module()
    paths = _fixture(tmp_path)
    evidence = json.loads(paths["evidence"].read_text())
    evidence["activation_performed"] = True
    evidence["results"].pop("principal_isolation")
    paths["evidence"].chmod(0o600)
    paths["evidence"].write_text(json.dumps(evidence))
    paths["evidence"].chmod(0o400)
    errors, _candidate = _verify(gate, paths)
    assert "evidence_manifest" in errors
    assert "independent_exact_head_review" in errors


def test_review_signature_exact_head_and_runtime_bindings_fail_closed(tmp_path: Path) -> None:
    gate = _module()
    paths = _fixture(tmp_path)
    for name, old, new in (("review", HEAD, "9" * 40), ("admission", ENGINE_ID, "other")):
        paths[name].chmod(0o600)
        paths[name].write_text(paths[name].read_text().replace(old, new))
        paths[name].chmod(0o400)
    errors, _candidate = _verify(gate, paths)
    assert "independent_review_signature" in errors
    assert "independent_exact_head_review" in errors
    assert "runtime_identity" in errors


def test_case_log_tamper_invalidates_complete_evidence(tmp_path: Path) -> None:
    gate = _module()
    paths = _fixture(tmp_path)
    log = paths["evidence"].parent / "principal_isolation.log"
    log.chmod(0o600)
    log.write_text("tampered\n")
    log.chmod(0o400)
    errors, _candidate = _verify(gate, paths)
    assert "case_principal_isolation" in errors


def test_external_device_receipt_requires_ack_and_exact_admitted_artifacts(
    tmp_path: Path,
) -> None:
    gate = _module()
    paths = _fixture(tmp_path)
    result_path = paths["evidence"].parent / "scratch_stack_restart_bytes.json"
    result = json.loads(result_path.read_text())
    result["disposable_engine_ack"] = "fabricated"
    result["image_manifest_sha256"] = "0" * 64
    result_path.chmod(0o600)
    result_path.write_text(json.dumps(result))
    result_path.chmod(0o400)
    errors, _candidate = _verify(gate, paths)
    assert "case_scratch_stack_restart_bytes" in errors


def test_case_logs_refuse_database_urls(tmp_path: Path) -> None:
    gate = _module()
    paths = _fixture(tmp_path)
    log = paths["evidence"].parent / "backup_restore_health.log"
    log.chmod(0o600)
    log.write_text("postgresql://synthetic:secret@127.0.0.1/scratch\n")
    log.chmod(0o400)
    errors, _candidate = _verify(gate, paths)
    assert "case_backup_restore_health" in errors


def test_protected_evidence_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    gate = _module()
    paths = _fixture(tmp_path / "symlink")
    result = paths["evidence"].parent / "principal_isolation.json"
    target = tmp_path / "symlink-target"
    target.write_bytes(result.read_bytes())
    target.chmod(0o400)
    result.unlink()
    result.symlink_to(target)
    errors, _candidate = _verify(gate, paths)
    assert "case_principal_isolation" in errors

    paths = _fixture(tmp_path / "hardlink")
    result = paths["evidence"].parent / "principal_isolation.json"
    link = paths["evidence"].parent / "linked-result"
    os.link(result, link)
    errors, _candidate = _verify(gate, paths)
    assert set(errors) & {"case_principal_isolation", "protected_evidence_file_set"}


def test_open_descriptor_snapshot_is_stable_during_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _module()
    paths = _fixture(tmp_path)
    log = paths["evidence"].parent / "principal_isolation.log"
    original_read = gate.os.read
    swapped = False
    log_inode = log.stat().st_ino

    def swapping_read(descriptor: int, amount: int) -> bytes:
        nonlocal swapped
        chunk = original_read(descriptor, amount)
        if not swapped and chunk and os.fstat(descriptor).st_ino == log_inode:
            replacement = log.with_suffix(".replacement")
            replacement.write_text("unreviewed replacement\n")
            replacement.chmod(0o400)
            replacement.replace(log)
            swapped = True
        return chunk

    monkeypatch.setattr(gate.os, "read", swapping_read)
    errors, _candidate = _verify(gate, paths)
    assert swapped
    assert errors == []


def test_real_runner_refuses_dirty_uncommitted_head_before_writing(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    output = tmp_path / "must-not-exist"
    result = subprocess.run(  # noqa: S603 - checked-in inert acceptance runner
        [
            sys.executable,
            str(ROOT / "ops/nas/run_synthetic_acceptance.py"),
            str(ROOT / "ops/nas/acceptance-matrix.toml"),
            str(paths["image"]),
            str(paths["admission"]),
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "exact clean identity required" in result.stdout
    assert not output.exists()


def test_exclusive_output_rejects_existing_symlink_and_traversal(tmp_path: Path) -> None:
    gate = _module()
    parent = tmp_path.resolve()
    parent.chmod(0o700)
    accepted = parent / "acceptance.toml"
    gate._exclusive_write(accepted, b'status = "pass"\n', os.getuid())
    metadata = accepted.stat()
    assert metadata.st_nlink == 1
    assert metadata.st_mode & 0o777 == 0o400
    with pytest.raises(OSError):
        gate._exclusive_write(accepted, b"overwrite", os.getuid())

    dangling = parent / "dangling.toml"
    dangling.symlink_to(parent / "missing-target")
    with pytest.raises(OSError):
        gate._exclusive_write(dangling, b"followed", os.getuid())
    with pytest.raises(OSError):
        gate._exclusive_write(parent / "nested" / ".." / "escape.toml", b"escape", os.getuid())


def test_streaming_case_terminates_noisy_process_at_bound(tmp_path: Path) -> None:
    runner = _runner_module()
    root = tmp_path / "evidence"
    root.mkdir(mode=0o700)
    returncode, digest, exceeded = runner._stream_case(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"],
        root,
        "noisy.log",
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        owner_uid=os.getuid(),
        limit=1024,
    )
    assert exceeded
    assert returncode != 0
    log = root / "noisy.log"
    assert log.stat().st_size == 1024
    assert _sha(log) == digest


def test_runner_uses_fixed_trusted_path_and_redacts_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner_module()
    database_url = "postgresql://synthetic:secret@127.0.0.1/scratch"
    monkeypatch.setenv("PATH", "/attacker/bin")
    environment = runner._case_environment(database_url)
    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["PATH"] != "/attacker/bin"
    root = tmp_path / "evidence"
    root.mkdir(mode=0o700)
    _returncode, _digest, refused = runner._stream_case(
        [sys.executable, "-c", "import os; print(os.environ['MY_PA_DATABASE_URL'])"],
        root,
        "database.log",
        cwd=ROOT,
        env=environment,
        owner_uid=os.getuid(),
        redactions=(database_url.encode(),),
    )
    assert not refused
    log = (root / "database.log").read_text()
    assert database_url not in log
    assert "[REDACTED_DATABASE_URL]" in log
    first, pending = runner._redact_chunk(b"", database_url[:17].encode(), (database_url.encode(),))
    second, pending = runner._redact_chunk(
        pending, database_url[17:].encode(), (database_url.encode(),), final=True
    )
    assert database_url.encode() not in first + second
    assert b"[REDACTED_DATABASE_URL]" in first + second
    assert not runner._local_case_allowed("external_device")
    assert runner._local_case_allowed("bounded_synthetic")


@pytest.mark.parametrize(
    "program",
    [
        "import time; time.sleep(60)",
        "import os,time; os.close(1); os.close(2); time.sleep(60)",
        (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "sys.exit(0)"
        ),
    ],
    ids=["silent-hang", "closed-output-hang", "descendant-holds-pipe"],
)
def test_case_timeout_kills_the_whole_process_group(tmp_path: Path, program: str) -> None:
    runner = _runner_module()
    root = tmp_path / "evidence"
    root.mkdir(mode=0o700)
    started = __import__("time").monotonic()
    returncode, _digest, refused = runner._stream_case(
        [sys.executable, "-c", program],
        root,
        "timeout.log",
        cwd=ROOT,
        env={"PATH": runner.TRUSTED_PATH},
        owner_uid=os.getuid(),
        timeout_seconds=0.25,
    )
    assert refused and returncode != 0
    assert __import__("time").monotonic() - started < 5


def test_matrix_names_every_plan_acceptance_surface_and_examples_are_inert() -> None:
    matrix_path = ROOT / "ops/nas/acceptance-matrix.toml"
    matrix = matrix_path.read_text()
    for marker in (
        "architecture_boundaries",
        "platform_image_runtime",
        "storage_permissions",
        "remote_capture_socket",
        "remote_capture_durable_transaction",
        "cross_principal_database",
        "backup_restore_health",
        "gateway_workers_pwa",
        "proxy_private_origin",
        "principal_isolation",
        "apple_grant_adversarial",
        "goodnotes_ocr_read_only",
        "frontier_mcp_stdio",
        "scratch_stack_restart_bytes",
        "lifecycle_restart_rollback_emergency",
        "diagnostics_and_no_activation",
    ):
        assert marker in matrix
    cases = tomllib.loads(matrix)["cases"]
    required_behaviors = {
        "remote_capture_socket": {
            "real loopback socket",
            "successful ClientCredential",
            "gateway capture admission",
        },
        "remote_capture_durable_transaction": {
            "real loopback socket",
            "registered ClientCredential",
            "same durable transaction as local capture",
        },
        "cross_principal_database": {
            "two authenticated Principals",
            "real PostgreSQL rows",
            "foreign rows are illegible",
        },
        "backup_restore_health": {
            "ops/nas/backup.sh pg_dump",
            "ops/nas/restore-to-scratch.sh fresh PostgreSQL",
            "apps/cli/health.py readiness",
            "exact admitted engine and images",
        },
        "scratch_stack_restart_bytes": {
            "actual Docker Compose scratch stack",
            "admitted PostgreSQL and app images",
            "health passes",
            "restart preserves PostgreSQL and managed sentinel bytes",
            "wrong-architecture image execution refuses",
        },
    }
    for name, behaviors in required_behaviors.items():
        assert set(cases[name]["behaviors"]) == behaviors
        if name in {"backup_restore_health", "scratch_stack_restart_bytes"}:
            assert cases[name]["requirement"] == "external_device"
            assert cases[name]["selectors"] == []
        else:
            assert cases[name]["selectors"]
    for example in (
        "nas-10-acceptance.example.toml",
        "nas10-review-trust.example.toml",
        "nas10-independent-review.example.toml",
    ):
        assert 'status = "pass"' not in (ROOT / "ops/nas" / example).read_text()
    runner = (ROOT / "ops/nas/run_synthetic_acceptance.py").read_text()
    for forbidden in ("tailscale serve", "docker compose up", "pilot-activation.toml"):
        assert forbidden not in runner.lower()
