"""The NAS operator runtime is exact, short-lived, and fail closed."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import tarfile
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module(name: str) -> ModuleType:
    path = ROOT / f"ops/nas/{name}.py"
    spec = importlib.util.spec_from_file_location(f"nas_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(path: Path, *, architecture: str = "amd64", named_correctly: bool = True) -> str:
    config = json.dumps({"os": "linux", "architecture": architecture}, sort_keys=True).encode()
    digest = hashlib.sha256(config).hexdigest()
    config_name = f"{digest if named_correctly else '0' * 64}.json"
    manifest = json.dumps([{"Config": config_name, "RepoTags": [], "Layers": []}]).encode()
    with tarfile.open(path, "w") as archive:
        for name, value in (("manifest.json", manifest), (config_name, config)):
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    return f"sha256:{digest}"


def test_archive_config_identity_is_content_derived(tmp_path: Path) -> None:
    module = _module("archive_image")
    archive = tmp_path / "image.tar"
    expected = _archive(archive)
    assert module.inspect_archive(archive).config_digest == expected

    mismatched = tmp_path / "mismatched.tar"
    _archive(mismatched, named_correctly=False)
    with pytest.raises(ValueError, match="filename"):
        module.inspect_archive(mismatched)

    arm = tmp_path / "arm.tar"
    _archive(arm, architecture="arm64")
    with pytest.raises(ValueError, match="platform"):
        module.inspect_archive(arm)


def test_upstream_metadata_uses_archive_not_docker_desktop_id() -> None:
    writer = (ROOT / "ops/nas/write-image-metadata.py").read_text(encoding="utf-8")
    build = (ROOT / "ops/nas/build-candidates.sh").read_text(encoding="utf-8")
    assert "inspect_archive(archive)" in writer
    assert "docker image inspect" not in writer
    assert '"$output_dir/postgres.tar" "$output_dir/postgres.metadata.json"' in build
    assert '"$output_dir/proxy.tar" "$output_dir/proxy.metadata.json"' in build


def test_operator_runtime_is_separate_hardened_and_nonpersistent() -> None:
    dockerfile = (ROOT / "ops/docker/operator.Dockerfile").read_text(encoding="utf-8")
    bootstrap = (ROOT / "ops/nas/bootstrap-operator-runtime.sh").read_text(encoding="utf-8")
    wrapper = (ROOT / "ops/nas/container-python.sh").read_text(encoding="utf-8")
    compose = (ROOT / "ops/nas/compose.example.yml").read_text(encoding="utf-8")
    assert "python@sha256:" in dockerfile
    assert 'test "${TARGETPLATFORM}" = "linux/amd64"' in dockerfile
    assert "git --version" in dockerfile and "/usr/bin/openssl version" in dockerfile
    assert "operator:" not in compose
    for script in (bootstrap, wrapper):
        assert "--rm" in script
        assert "--network none" in script
        assert "--read-only" in script
        assert "--cap-drop ALL" in script
        assert "no-new-privileges" in script
        assert "/var/run/docker.sock:/var/run/docker.sock" in script
    assert "operator admission must be root-owned mode 0400 with one link" in wrapper
    assert "--rm -i" in wrapper
    for script in (bootstrap, wrapper):
        assert "$compose_plugin_dir/docker-compose:ro" in script
        assert 'DOCKER_CLI_PLUGIN_EXTRA_DIRS="$compose_plugin_dir"' in script
    assert "mkdir -p /usr/local/lib/docker/cli-plugins" in dockerfile
    assert "python3.12" not in (ROOT / "ops/nas/tooling-common.sh").read_text(encoding="utf-8")


def test_operator_admission_is_exclusive_and_engine_bound() -> None:
    source = (ROOT / "ops/nas/admit-operator-runtime.py").read_text(encoding="utf-8")
    assert "os.O_EXCL" in source and "0o400" in source
    assert 'engine.get("Architecture") != "x86_64"' in source
    assert 'labels.get("io.my-pa.operator-runtime") != "python-3.12"' in source
    assert '"compose", "version", "--short"' in source
    assert '"--services"' in source
    assert '"--profile"' in source and '"nas-01-contract-only"' in source
    assert "COMPOSE_SENTINEL_ENVIRONMENT" in source
    assert '"--no-interpolate"' not in source
    assert 'f"compose_version = ' in source


def _operator_artifacts(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    archive = tmp_path / "operator.tar"
    image_id = _archive(archive)
    metadata = tmp_path / "operator.metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "containerimage.digest": "sha256:" + "b" * 64,
                "containerimage.config.digest": image_id,
            }
        ),
        encoding="utf-8",
    )
    candidate = tmp_path / "operator.toml"
    candidate.write_text(
        "\n".join(
            [
                'schema = "my-pa.nas-operator-runtime-candidate.v1"',
                'status = "candidate_not_admitted"',
                'repository_commit = "' + "a" * 40 + '"',
                'repository_tree = "' + "c" * 40 + '"',
                'built_at = "2026-08-14T00:00:00Z"',
                'target_os = "linux"',
                'target_architecture = "amd64"',
                'oci_manifest_digest = "sha256:' + "b" * 64 + '"',
                f'docker_image_id = "{image_id}"',
                f'archive_sha256 = "{hashlib.sha256(archive.read_bytes()).hexdigest()}"',
                f'build_metadata_sha256 = "{hashlib.sha256(metadata.read_bytes()).hexdigest()}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return candidate, archive, metadata, image_id


def test_operator_admission_refuses_undiscoverable_compose_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module("admit-operator-runtime")
    candidate, archive, metadata, _ = _operator_artifacts(tmp_path)

    def run(command: list[str], *, environment: dict[str, str] | None = None) -> str:
        del environment
        if command[1:3] == ["compose", "version"]:
            raise subprocess.CalledProcessError(125, command, stderr="unknown flag: --file")
        if command[1] == "info":
            return '{"OSType":"linux","Architecture":"x86_64","ID":"engine","Name":"nas"}'
        if command[1:3] == ["image", "inspect"]:
            image_id = module.inspect_archive(archive).config_digest
            return json.dumps(
                [
                    {
                        "Id": image_id,
                        "Os": "linux",
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": "a" * 40,
                                "io.my-pa.repository-tree": "c" * 40,
                                "io.my-pa.target-platform": "linux/amd64",
                                "io.my-pa.operator-runtime": "python-3.12",
                            }
                        },
                    }
                ]
            )
        if command == ["git", "--version"]:
            return "git version 2.47.3"
        if command == ["/usr/bin/openssl", "version"]:
            return "OpenSSL 3.5.1"
        raise AssertionError(command)

    monkeypatch.setattr(module, "_run", run)
    output = tmp_path / "admission.toml"
    assert "live_operator_inspection" in module.admit(candidate, archive, metadata, output)
    assert not output.exists()


def test_operator_admission_renders_with_closed_nonsecret_sentinels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module("admit-operator-runtime")
    candidate, archive, metadata, image_id = _operator_artifacts(tmp_path)

    def run(command: list[str], *, environment: dict[str, str] | None = None) -> str:
        if command[1] == "info":
            return '{"OSType":"linux","Architecture":"x86_64","ID":"engine","Name":"nas"}'
        if command[1:3] == ["image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": image_id,
                        "Os": "linux",
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": "a" * 40,
                                "io.my-pa.repository-tree": "c" * 40,
                                "io.my-pa.target-platform": "linux/amd64",
                                "io.my-pa.operator-runtime": "python-3.12",
                            }
                        },
                    }
                ]
            )
        if command == ["git", "--version"]:
            return "git version 2.47.3"
        if command == ["/usr/bin/openssl", "version"]:
            return "OpenSSL 3.5.1"
        if command[1:4] == ["compose", "version", "--short"]:
            return "2.20.1-6047-g6817716"
        if command[1:3] == ["compose", "--file"]:
            assert environment is not None
            assert environment["MY_PA_DB_PASSWORD"] == "operator-admission-sentinel"  # noqa: S105
            assert environment["MY_PA_PROXY_PORT"] == "1"
            assert "--no-interpolate" not in command
            assert command[-4:] == [
                "--profile",
                "nas-01-contract-only",
                "config",
                "--services",
            ]
            return "postgres\ngateway\nproxy\nweb\nworker-capture\nworker-enrollment"
        raise AssertionError(command)

    monkeypatch.setattr(module, "_run", run)
    output = tmp_path / "admission.toml"
    assert module.admit(candidate, archive, metadata, output) == []
    assert 'compose_version = "2.20.1-6047-g6817716"' in output.read_text(encoding="utf-8")


def test_container_python_preserves_stdin_compose_plugin_and_closed_environment(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "docker-argv"
    stdin = tmp_path / "docker-stdin"
    image_id = "sha256:" + "a" * 64
    admission = tmp_path / "operator-runtime.toml"
    admission.write_text(f'operator_image_id = "{image_id}"\n', encoding="utf-8")
    admission.chmod(0o400)
    fake_stat = tools / "stat"
    fake_stat.write_text("#!/bin/sh\nprintf '0:400:1\\n'\n", encoding="utf-8")
    fake_compose = tools / "docker-compose"
    fake_compose.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_tailscale = tools / "tailscale"
    fake_tailscale.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    socket_suffix = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    tailscale_socket = Path(tempfile.gettempdir()) / f"my-pa-{socket_suffix}.sock"
    socket_handle = socket.socket(socket.AF_UNIX)
    socket_handle.bind(str(tailscale_socket))
    request.addfinalizer(socket_handle.close)
    request.addfinalizer(lambda: tailscale_socket.unlink(missing_ok=True))
    fake_docker = tools / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        f'image_id="{image_id}"\n'
        'if [ "$1 $2" = "image inspect" ]; then '
        'printf "%s|linux|amd64\\n" "$image_id"; exit 0; fi\n'
        f': > "{calls}"\n'
        f'for value in "$@"; do printf "%s\\n" "$value" >> "{calls}"; done\n'
        f'cat > "{stdin}"\n',
        encoding="utf-8",
    )
    for path in (fake_stat, fake_compose, fake_tailscale, fake_docker):
        path.chmod(0o700)

    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [str(ROOT / "ops/nas/container-python.sh"), "-", "argument"],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_DOCKER": str(fake_docker),
            "MY_PA_NAS_COMPOSE_PLUGIN": str(fake_compose),
            "MY_PA_NAS_OPERATOR_ADMISSION": str(admission),
            "MY_PA_NAS_TAILSCALE": str(fake_tailscale),
            "MY_PA_NAS_TAILSCALE_SOCKET": str(tailscale_socket),
            "MY_PA_DB_PASSWORD": "synthetic-not-a-secret",
            "UNAPPROVED_OPERATOR_VALUE": "must-not-pass",
        },
        input="stdin-sentinel",
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    arguments = calls.read_text(encoding="utf-8").splitlines()
    assert "-i" in arguments
    assert f"{fake_compose}:/usr/local/lib/docker/cli-plugins/docker-compose:ro" in arguments
    assert f"{fake_tailscale}:/usr/local/bin/tailscale:ro" in arguments
    assert f"{tailscale_socket}:/var/run/tailscale/tailscaled.sock:ro" in arguments
    assert "DOCKER_CLI_PLUGIN_EXTRA_DIRS=/usr/local/lib/docker/cli-plugins" in arguments
    assert "MY_PA_DB_PASSWORD" in arguments
    assert "UNAPPROVED_OPERATOR_VALUE" not in arguments
    assert "synthetic-not-a-secret" not in arguments
    assert arguments[-3:] == [image_id, "-", "argument"]
    assert stdin.read_text(encoding="utf-8") == "stdin-sentinel"


def test_container_python_refuses_invalid_tailscale_authority(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    image_id = "sha256:" + "a" * 64
    admission = tmp_path / "operator-runtime.toml"
    admission.write_text(f'operator_image_id = "{image_id}"\n', encoding="utf-8")
    admission.chmod(0o400)
    fake_stat = tools / "stat"
    fake_stat.write_text("#!/bin/sh\nprintf '0:400:1\\n'\n", encoding="utf-8")
    fake_compose = tools / "docker-compose"
    fake_compose.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_docker = tools / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        f'image_id="{image_id}"\n'
        'if [ "$1 $2" = "image inspect" ]; then '
        'printf "%s|linux|amd64\\n" "$image_id"; exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_tailscale = tools / "tailscale"
    fake_tailscale.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    for path in (fake_stat, fake_compose, fake_docker, fake_tailscale):
        path.chmod(0o700)
    socket_suffix = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    tailscale_socket = Path(tempfile.gettempdir()) / f"my-pa-neg-{socket_suffix}.sock"
    socket_handle = socket.socket(socket.AF_UNIX)
    socket_handle.bind(str(tailscale_socket))
    request.addfinalizer(socket_handle.close)
    request.addfinalizer(lambda: tailscale_socket.unlink(missing_ok=True))
    nonsocket = tmp_path / "not-a-socket"
    nonsocket.touch()
    base_environment = {
        **os.environ,
        "PATH": f"{tools}:/usr/bin:/bin",
        "MY_PA_NAS_DOCKER": str(fake_docker),
        "MY_PA_NAS_COMPOSE_PLUGIN": str(fake_compose),
        "MY_PA_NAS_OPERATOR_ADMISSION": str(admission),
    }
    cases = (
        (
            {"MY_PA_NAS_TAILSCALE": str(fake_tailscale)},
            "exact NAS Tailscale socket required",
        ),
        (
            {"MY_PA_NAS_TAILSCALE_SOCKET": str(tailscale_socket)},
            "exact NAS Tailscale executable required",
        ),
        (
            {
                "MY_PA_NAS_TAILSCALE": str(fake_tailscale),
                "MY_PA_NAS_TAILSCALE_SOCKET": str(nonsocket),
            },
            "Tailscale socket is unavailable",
        ),
        (
            {
                "MY_PA_NAS_TAILSCALE": str(tools),
                "MY_PA_NAS_TAILSCALE_SOCKET": str(tailscale_socket),
            },
            "Tailscale executable is unavailable",
        ),
        (
            {
                "MY_PA_NAS_TAILSCALE": f"{fake_tailscale}\n--privileged",
                "MY_PA_NAS_TAILSCALE_SOCKET": str(tailscale_socket),
            },
            "newline-containing Tailscale paths are prohibited",
        ),
        (
            {
                "MY_PA_NAS_TAILSCALE": fake_tailscale.name,
                "MY_PA_NAS_TAILSCALE_SOCKET": str(tailscale_socket),
            },
            "Tailscale executable path must be absolute",
        ),
        (
            {
                "MY_PA_NAS_TAILSCALE": str(fake_tailscale),
                "MY_PA_NAS_TAILSCALE_SOCKET": os.path.relpath(tailscale_socket, ROOT),
            },
            "Tailscale socket path must be absolute",
        ),
    )
    for extra_environment, expected_error in cases:
        result = subprocess.run(  # noqa: S603 - wrapper with synthetic tools
            [str(ROOT / "ops/nas/container-python.sh"), "-c", "pass"],
            cwd=ROOT,
            env={**base_environment, **extra_environment},
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert expected_error in result.stderr
