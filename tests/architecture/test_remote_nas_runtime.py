from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remote_runtime_contract_passes_static_gate() -> None:
    gate = _module(ROOT / "ops/nas/remote/validate.py")
    assert gate.validate() == []


def test_remote_runtime_contract_refuses_unsupported_synology_cgroup_controls(
    tmp_path: Path,
) -> None:
    gate = _module(ROOT / "ops/nas/remote/validate.py")
    remote = tmp_path / "remote"
    shutil.copytree(ROOT / "ops/nas/remote", remote)
    compose = remote / "compose.yml"
    expected = '    cpuset: "${MY_PA_REMOTE_CPUSET:?remote MCP CPU set required}"'
    compose.write_text(
        compose.read_text().replace(expected, f"    # {expected.strip()}\n    cpuset: 2")
    )
    assert "my-pa-mcp-remote_resource_contract" in gate.validate(remote)
    compose.write_text(
        compose.read_text().replace("    cpuset: 2", "    pids_limit: 128\n    cpuset: 2")
    )
    assert "my-pa-mcp-remote_unsupported_synology_cgroup_control" in gate.validate(remote)


def test_production_remote_contract_is_local_operator_and_has_no_entra_dependency() -> None:
    environment = (ROOT / "ops/nas/remote/remote.env.example").read_text()
    compose = (ROOT / "ops/nas/remote/compose.yml").read_text()
    gateway = (ROOT / "apps/gateway.py").read_text()
    assert "MY_PA_AUTH_MODE=local_operator" in environment
    assert "MY_PA_OAUTH_OPERATOR_SECRET=" in environment
    for forbidden in ("ENTRA", "JWKS", "OAUTH_TENANT", "OAUTH_ISSUER"):
        assert forbidden not in environment
    assert "identity-egress" not in compose
    remote_entrypoint = gateway.split("def _mcp_remote", 1)[1].split("def build_parser", 1)[0]
    assert "Entra" not in remote_entrypoint
    assert "jwks" not in remote_entrypoint.lower()


def test_cloudflared_renderer_is_exact_and_refuses_overwrite(tmp_path: Path) -> None:
    renderer = _module(ROOT / "ops/nas/remote/render-cloudflared-config.py")
    output = tmp_path / "config.yml"
    renderer.render(
        ROOT / "ops/nas/remote/cloudflared-config.example.yml",
        output,
        tunnel_id="12345678-1234-5678-9234-567812345678",
        hostname="mcp.example.com",
    )
    text = output.read_text()
    assert "__" not in text
    assert text.count("hostname: mcp.example.com") == 9
    assert "http_status:404" in text
    with pytest.raises(FileExistsError):
        renderer.render(
            ROOT / "ops/nas/remote/cloudflared-config.example.yml",
            output,
            tunnel_id="12345678-1234-5678-9234-567812345678",
            hostname="mcp.example.com",
        )


def test_renderer_rejects_placeholder_hostname(tmp_path: Path) -> None:
    renderer = _module(ROOT / "ops/nas/remote/render-cloudflared-config.py")
    with pytest.raises(ValueError):
        renderer.render(
            ROOT / "ops/nas/remote/cloudflared-config.example.yml",
            tmp_path / "config.yml",
            tunnel_id="12345678-1234-5678-9234-567812345678",
            hostname="mcp.example.invalid",
        )


def test_live_gate_accepts_only_the_expected_least_privilege_shape() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")

    def state(*, image: str, networks: tuple[str, ...], mounts: list[dict[str, object]]) -> dict:
        command = gate.APP_COMMAND if image.startswith("app") else gate.EDGE_COMMAND
        return {
            "Config": {"Image": image, "User": "10001:10001", "Cmd": command},
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "HostConfig": {
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "CapAdd": None,
                "Devices": [],
                "SecurityOpt": ["no-new-privileges:true"],
                "PortBindings": {},
                "Init": True,
                "RestartPolicy": {"Name": "unless-stopped"},
                "CpusetCpus": "0" if image.startswith("app") else "1",
                "CpusetMems": "",
                "CpuShares": 0,
                "NanoCpus": 0,
                "CpuPeriod": 0,
                "CpuQuota": 0,
                "PidsLimit": None,
                "Ulimits": None,
                "Memory": (768 if image.startswith("app") else 256) * 1024 * 1024,
            },
            "Mounts": mounts,
            "NetworkSettings": {"Networks": {name: {} for name in networks}},
        }

    app = state(
        image="app@sha256:exact",
        networks=(
            "my-pa-remote-mcp_mcp-origin",
            "my-pa-nas-contract_data-plane",
        ),
        mounts=[
            {"Source": "/nas/config", "Destination": "/srv/my-pa/config", "RW": False},
            {"Source": "/nas/source", "Destination": "/srv/my-pa/sources", "RW": False},
            {
                "Source": "/nas/managed",
                "Destination": "/srv/my-pa/managed-documents",
                "RW": True,
            },
        ],
    )
    edge = state(
        image="edge@sha256:exact",
        networks=(
            "my-pa-remote-mcp_mcp-origin",
            "my-pa-remote-mcp_cloudflare-egress",
        ),
        mounts=[
            {
                "Source": "/nas/cloudflared/config.yml",
                "Destination": "/etc/cloudflared/config.yml",
                "RW": False,
            },
            {
                "Source": "/nas/cloudflared/credentials",
                "Destination": "/run/secrets/cloudflared",
                "RW": False,
            },
        ],
    )
    network_states = {
        "my-pa-nas-contract_data-plane": {
            "Name": "my-pa-nas-contract_data-plane",
            "Internal": True,
            "Labels": {
                "com.docker.compose.project": "my-pa-nas-contract",
                "com.docker.compose.network": "data-plane",
            },
            "Containers": {"postgres-id": {}},
        },
        "my-pa-remote-mcp_mcp-origin": {"Internal": True},
        "my-pa-remote-mcp_cloudflare-egress": {"Internal": False},
    }
    assert (
        gate.violations(
            app,
            edge,
            app_image="app@sha256:exact",
            edge_image="edge@sha256:exact",
            data_network="my-pa-nas-contract_data-plane",
            networks=network_states,
            postgres_resources={
                "status": "verified",
                "data_network": "my-pa-nas-contract_data-plane",
                "postgres_container_id": "postgres-id",
                "postgres_image_id": "sha256:postgres",
            },
            postgres={
                "Id": "postgres-id",
                "Image": "sha256:postgres",
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "my-pa-nas-contract",
                        "com.docker.compose.service": "postgres",
                    }
                },
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
                "NetworkSettings": {"Networks": {"my-pa-nas-contract_data-plane": {}}},
            },
        )
        == []
    )
    app["HostConfig"]["CpusetCpus"] = "0-3"
    assert "app_cpuset" in gate.violations(
        app,
        edge,
        app_image="app@sha256:exact",
        edge_image="edge@sha256:exact",
        data_network="my-pa-nas-contract_data-plane",
        networks=network_states,
        postgres_resources={
            "status": "verified",
            "data_network": "my-pa-nas-contract_data-plane",
            "postgres_container_id": "postgres-id",
            "postgres_image_id": "sha256:postgres",
        },
        postgres={
            "Id": "postgres-id",
            "Image": "sha256:postgres",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "my-pa-nas-contract",
                    "com.docker.compose.service": "postgres",
                }
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "NetworkSettings": {"Networks": {"my-pa-nas-contract_data-plane": {}}},
        },
    )
    app["HostConfig"]["CpusetCpus"] = "0"
    edge["HostConfig"]["NanoCpus"] = 500_000_000
    assert "edge_unadmitted_resource_control" in gate.violations(
        app,
        edge,
        app_image="app@sha256:exact",
        edge_image="edge@sha256:exact",
        data_network="my-pa-nas-contract_data-plane",
        networks=network_states,
        postgres_resources={
            "status": "verified",
            "data_network": "my-pa-nas-contract_data-plane",
            "postgres_container_id": "postgres-id",
            "postgres_image_id": "sha256:postgres",
        },
        postgres={
            "Id": "postgres-id",
            "Image": "sha256:postgres",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "my-pa-nas-contract",
                    "com.docker.compose.service": "postgres",
                }
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "NetworkSettings": {"Networks": {"my-pa-nas-contract_data-plane": {}}},
        },
    )
    edge["HostConfig"]["NanoCpus"] = 0
    assert "noncanonical_data_network" in gate.violations(
        app,
        edge,
        app_image="app@sha256:exact",
        edge_image="edge@sha256:exact",
        data_network="postgresql_default",
        networks=network_states,
        postgres_resources={},
        postgres={},
    )
    network_states["my-pa-nas-contract_data-plane"]["Internal"] = False
    assert "canonical_data_network_identity" in gate.violations(
        app,
        edge,
        app_image="app@sha256:exact",
        edge_image="edge@sha256:exact",
        data_network="my-pa-nas-contract_data-plane",
        networks=network_states,
        postgres_resources={},
        postgres={},
    )
    network_states["my-pa-nas-contract_data-plane"]["Internal"] = True
    network_states["my-pa-nas-contract_data-plane"]["Containers"] = {}
    assert "canonical_data_network_identity" in gate.violations(
        app,
        edge,
        app_image="app@sha256:exact",
        edge_image="edge@sha256:exact",
        data_network="my-pa-nas-contract_data-plane",
        networks=network_states,
        postgres_resources={
            "status": "verified",
            "data_network": "my-pa-nas-contract_data-plane",
            "postgres_container_id": "postgres-id",
            "postgres_image_id": "sha256:postgres",
        },
        postgres={
            "Id": "postgres-id",
            "Image": "sha256:postgres",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "my-pa-nas-contract",
                    "com.docker.compose.service": "postgres",
                }
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "NetworkSettings": {"Networks": {"my-pa-nas-contract_data-plane": {}}},
        },
    )
    network_states["my-pa-nas-contract_data-plane"]["Containers"] = {"postgres-id": {}}
    app["HostConfig"]["PortBindings"] = {
        "8766/tcp": [{"HostIp": "0.0.0.0"}]  # noqa: S104 - deliberately invalid fixture
    }
    app["Mounts"][1]["RW"] = True
    assert set(
        gate.violations(
            app,
            edge,
            app_image="app@sha256:exact",
            edge_image="edge@sha256:exact",
            data_network="my-pa-nas-contract_data-plane",
            networks=network_states,
            postgres_resources={
                "status": "verified",
                "data_network": "my-pa-nas-contract_data-plane",
                "postgres_container_id": "postgres-id",
                "postgres_image_id": "sha256:postgres",
            },
            postgres={
                "Id": "postgres-id",
                "Image": "sha256:postgres",
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "my-pa-nas-contract",
                        "com.docker.compose.service": "postgres",
                    }
                },
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
                "NetworkSettings": {"Networks": {"my-pa-nas-contract_data-plane": {}}},
            },
        )
    ) == {"origin_host_port", "source_mount_not_read_only"}
