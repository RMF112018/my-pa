"""NAS-04/05 runtime identity and permission boundaries."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _gate() -> ModuleType:
    path = ROOT / "ops/nas/runtime_gate.py"
    spec = importlib.util.spec_from_file_location("runtime_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unverified_runtime_manifest_refuses() -> None:
    gate = _gate()
    errors = gate.verify(ROOT / "ops/nas/runtime-services.example.toml")
    assert {"status_not_verified", "service_identity", "live_verification_required"} <= set(errors)


def test_compose_keeps_gateway_internal_and_mount_authority_narrow() -> None:
    compose = (ROOT / "ops/nas/compose.example.yml").read_text()
    gateway = compose.split("  gateway:", 1)[1].split("  worker-enrollment:", 1)[0]
    enrollment = compose.split("  worker-enrollment:", 1)[1].split("  worker-capture:", 1)[0]
    capture = compose.split("  worker-capture:", 1)[1].split("  web:", 1)[0]
    web = compose.split("  web:", 1)[1].split("  proxy:", 1)[0]
    assert "MY_PA_GATEWAY_BIND_MODE: container" in gateway
    assert "MY_PA_MANAGED_DOCUMENT_ROOT: /srv/my-pa/managed-documents" in gateway
    assert "expose:" in gateway and "ports:" not in gateway and "network_mode:" not in gateway
    assert "managed-documents" not in enrollment + capture + web
    assert "read_only: true" in enrollment


def test_live_gate_binds_compose_identity_images_networks_and_mounts(tmp_path: Path) -> None:
    gate = _gate()
    compose = tmp_path / "compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    services = ("gateway", "worker_enrollment", "worker_capture", "web")
    paths = {key: tmp_path / key for key in ("config", "sources", "goodnotes", "managed_documents")}
    for value in paths.values():
        value.mkdir()
    manifest = tmp_path / "services.toml"
    sections = "".join(
        f'\n[services.{name}]\ncontainer_id = "{name}-id"\nimage_id = "sha256:{index:064x}"\n'
        for index, name in enumerate(services, start=1)
    )
    manifest.write_text(
        'schema = "my-pa.nas-runtime-services.v1"\nstatus = "verified"\n'
        'docker_engine_id = "nas"\nuid = 10001\ngid = 10001\n'
        + "[paths]\n"
        + "".join(f'{key} = "{value}"\n' for key, value in paths.items())
        + "[filesystem_types]\n"
        + "".join(f'{key} = "btrfs"\n' for key in paths)
        + sections,
        encoding="utf-8",
    )

    overrides: dict[str, object] = {}
    exec_calls = 0

    def runner(command: list[str]) -> str:
        nonlocal exec_calls
        if command[1] == "info":
            return '{"ID":"nas"}'
        if command[1] == "compose":
            service = command[-1].replace("-", "_")
            return service + "-id\n"
        if command[1] == "exec":
            exec_calls += 1
            return ""
        name = command[-1].removesuffix("-id")
        expected = gate.MOUNTS[name]
        inspected = {
            "Image": f"sha256:{services.index(name) + 1:064x}",
            "Config": {
                "User": "10001:10001",
                "Cmd": gate.COMMANDS[name],
                "Entrypoint": None,
                "Env": (
                    [
                        "MY_PA_GATEWAY_BIND_MODE=container",
                        "MY_PA_MANAGED_DOCUMENT_ROOT=/srv/my-pa/managed-documents",
                    ]
                    if name == "gateway"
                    else []
                ),
            },
            "HostConfig": {
                "NetworkMode": "default",
                "Privileged": False,
                "PortBindings": {},
                "PublishAllPorts": False,
                "CapAdd": [],
                "CapDrop": ["ALL"],
                "Devices": [],
                "SecurityOpt": ["no-new-privileges:true"],
            },
            "NetworkSettings": {
                "Networks": {f"stack_{value}": {} for value in gate.NETWORKS[name]}
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(paths[gate.PATH_KEYS[destination]]),
                    "Destination": destination,
                    "RW": writable,
                }
                for destination, writable in expected.items()
            ],
        }
        inspected.update(overrides)
        return json.dumps([inspected])

    live_args = {
        "live": True,
        "compose_file": compose,
        "runner": runner,
        "filesystem_type": lambda _path: "btrfs",
    }
    assert gate.verify(manifest, **live_args) == []

    overrides["Config"] = {
        "User": "10001:10001",
        "Cmd": gate.COMMANDS["gateway"],
        "Entrypoint": ["/untrusted"],
        "Env": [
            "MY_PA_GATEWAY_BIND_MODE=container",
            "MY_PA_MANAGED_DOCUMENT_ROOT=/srv/my-pa/managed-documents",
        ],
    }
    assert any(
        error.endswith("_entrypoint")
        for error in gate.verify(manifest, permissions=True, **live_args)
    )
    assert exec_calls == 0
    overrides["Config"] = {
        "User": "10001:10001",
        "Cmd": gate.COMMANDS["gateway"],
        "Entrypoint": None,
        "Env": [
            "MY_PA_GATEWAY_BIND_MODE=container",
            "MY_PA_GATEWAY_BIND_MODE=loopback",
            "MY_PA_MANAGED_DOCUMENT_ROOT=/srv/my-pa/managed-documents",
        ],
    }
    assert "gateway_environment" in gate.verify(manifest, **live_args)
    overrides.clear()
    original_runner = runner

    def leaked_authority_runner(command: list[str]) -> str:
        result = original_runner(command)
        if command[1] == "inspect" and "worker" in command[-1]:
            inspected = json.loads(result)
            inspected[0]["Config"]["Env"] = ["MY_PA_MANAGED_DOCUMENT_ROOT=/forbidden"]
            return json.dumps(inspected)
        return result

    assert any(
        error.endswith("_gateway_authority")
        for error in gate.verify(
            manifest,
            live=True,
            compose_file=compose,
            runner=leaked_authority_runner,
            filesystem_type=lambda _path: "btrfs",
        )
    )

    compose_calls = 0

    def drifting_runner(command: list[str]) -> str:
        nonlocal compose_calls
        if command[1] == "compose":
            compose_calls += 1
            if compose_calls == len(services) + 1:
                return "recreated-container-id\n"
        return original_runner(command)

    assert any(
        error.endswith("_permission_identity")
        for error in gate.verify(
            manifest,
            live=True,
            compose_file=compose,
            permissions=True,
            runner=drifting_runner,
            filesystem_type=lambda _path: "btrfs",
        )
    )

    rebind_compose_calls = 0

    def failed_rebind_runner(command: list[str]) -> str:
        nonlocal rebind_compose_calls
        if command[1] == "compose":
            rebind_compose_calls += 1
            if rebind_compose_calls == len(services) + 1:
                raise subprocess.CalledProcessError(1, command)
        return original_runner(command)

    before_exec_calls = exec_calls
    assert any(
        error.endswith("_permission_rebind")
        for error in gate.verify(
            manifest,
            live=True,
            compose_file=compose,
            permissions=True,
            runner=failed_rebind_runner,
            filesystem_type=lambda _path: "btrfs",
        )
    )
    assert exec_calls == before_exec_calls

    overlap = tmp_path / "overlap.toml"
    overlap.write_text(
        manifest.read_text().replace(
            f'goodnotes = "{paths["goodnotes"]}"',
            f'goodnotes = "{paths["config"]}"',
        ),
        encoding="utf-8",
    )
    docker_called = False

    def forbidden_runner(_command: list[str]) -> str:
        nonlocal docker_called
        docker_called = True
        raise AssertionError("Docker must not be called for invalid path classes")

    assert "path_class_overlap" in gate.verify(
        overlap,
        live=True,
        compose_file=compose,
        runner=forbidden_runner,
        filesystem_type=lambda _path: "btrfs",
    )
    assert not docker_called

    nested = paths["config"] / "nested"
    nested.mkdir()
    reverse_nested = paths["goodnotes"] / "nested"
    reverse_nested.mkdir()
    for old, new in (
        (paths["goodnotes"], nested),
        (paths["config"], reverse_nested),
    ):
        nested_manifest = tmp_path / f"nested-{old.name}.toml"
        nested_manifest.write_text(
            manifest.read_text().replace(f'"{old}"', f'"{new}"'), encoding="utf-8"
        )
        assert "path_class_overlap" in gate.verify(
            nested_manifest,
            live=True,
            compose_file=compose,
            runner=forbidden_runner,
            filesystem_type=lambda _path: "btrfs",
        )

    def failed_exec_runner(command: list[str]) -> str:
        if command[1] == "exec":
            raise subprocess.CalledProcessError(1, command)
        return original_runner(command)

    permission_errors = gate.verify(
        manifest,
        live=True,
        compose_file=compose,
        permissions=True,
        runner=failed_exec_runner,
        filesystem_type=lambda _path: "btrfs",
    )
    assert any(error.endswith("_permission_probe") for error in permission_errors)

    assert any(
        error.endswith("_filesystem_not_local")
        for error in gate.verify(
            manifest,
            live=True,
            compose_file=compose,
            runner=forbidden_runner,
            filesystem_type=lambda _path: "nfs4",
        )
    )


def test_wrong_compose_container_and_root_user_refuse(tmp_path: Path) -> None:
    gate = _gate()
    manifest = tmp_path / "services.toml"
    manifest.write_text(
        'schema = "my-pa.nas-runtime-services.v1"\nstatus = "verified"\n'
        'docker_engine_id = "nas"\nuid = 0\ngid = 0\n'
        '[paths]\nconfig = "/bad"\nsources = "/bad"\n'
        'goodnotes = "/bad"\nmanaged_documents = "/bad"\n'
        '[filesystem_types]\nconfig = "btrfs"\nsources = "btrfs"\n'
        'goodnotes = "btrfs"\nmanaged_documents = "btrfs"\n'
        + "".join(
            f'\n[services.{name}]\ncontainer_id = "{name}-id"\nimage_id = "sha256:{"1" * 64}"\n'
            for name in gate.SERVICES
        ),
        encoding="utf-8",
    )
    assert "service_identity" in gate.verify(manifest)
