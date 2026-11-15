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
    compose.write_text(
        compose.read_text().replace(
            "    pids_limit: 128",
            "    cpu_quota: 50000\n    cpu_period: 100000\n    pids_limit: 128",
        )
    )
    assert "my-pa-mcp-remote_unsupported_synology_cgroup_control" in gate.validate(remote)
    environment = remote / "compose.env.example"
    environment.write_text(environment.read_text() + "MY_PA_REMOTE_CPUSET=7\n")
    assert "resource_example_contract" in gate.validate(remote)


def test_remote_memory_template_is_896m_and_other_values_are_refused(tmp_path: Path) -> None:
    gate = _module(ROOT / "ops/nas/remote/validate.py")
    remote = tmp_path / "remote"
    shutil.copytree(ROOT / "ops/nas/remote", remote)
    environment = remote / "compose.env.example"
    template = environment.read_text()
    assert template.splitlines().count("MY_PA_REMOTE_MEMORY=896m") == 1
    assert "resource_example_contract" not in gate.validate(remote)
    for refused in ("768m", "1g", ""):
        environment.write_text(
            template.replace("MY_PA_REMOTE_MEMORY=896m", f"MY_PA_REMOTE_MEMORY={refused}")
        )
        assert "resource_example_contract" in gate.validate(remote), refused
    environment.write_text(template + "MY_PA_REMOTE_MEMORY=896m\n")
    assert "resource_example_contract" in gate.validate(remote)


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
    # 11 before the files-workspace contract section 17.6 browser download rule.
    assert text.count("hostname: mcp.example.com") == 12
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
                "CpuCount": 0,
                "CpuPercent": 0,
                "CpuRealtimePeriod": 0,
                "CpuRealtimeRuntime": 0,
                "PidsLimit": None,
                "Ulimits": None,
                "Memory": (896 if image.startswith("app") else 256) * 1024 * 1024,
                "MemoryReservation": 0,
                "MemorySwap": (1792 if image.startswith("app") else 512) * 1024 * 1024,
                "MemorySwappiness": None,
                "OomKillDisable": False,
                "BlkioWeight": 0,
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
    edge["HostConfig"]["CpuRealtimeRuntime"] = 10_000
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
    edge["HostConfig"]["CpuRealtimeRuntime"] = 0
    app["HostConfig"]["Memory"] = 1
    assert "app_memory_limit" in gate.violations(
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
    app["HostConfig"]["Memory"] = 896 * 1024 * 1024
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


def _live_gate_shape(gate: ModuleType) -> tuple[dict, dict, dict[str, object]]:
    """A passing app/edge/postgres shape for the live gate (as admitted above)."""

    def state(*, image: str, networks: tuple[str, ...], mounts: list[dict[str, object]]) -> dict:
        app = image.startswith("app")
        return {
            "Config": {
                "Image": image,
                "User": "10001:10001",
                "Cmd": gate.APP_COMMAND if app else gate.EDGE_COMMAND,
            },
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
                "CpusetCpus": "0" if app else "1",
                "CpusetMems": "",
                "CpuShares": 0,
                "NanoCpus": 0,
                "CpuPeriod": 0,
                "CpuQuota": 0,
                "CpuCount": 0,
                "CpuPercent": 0,
                "CpuRealtimePeriod": 0,
                "CpuRealtimeRuntime": 0,
                "PidsLimit": None,
                "Ulimits": None,
                "Memory": (896 if app else 256) * 1024 * 1024,
                "MemoryReservation": 0,
                "MemorySwap": (1792 if app else 512) * 1024 * 1024,
                "MemorySwappiness": None,
                "OomKillDisable": False,
                "BlkioWeight": 0,
            },
            "Mounts": mounts,
            "NetworkSettings": {"Networks": {name: {} for name in networks}},
        }

    app = state(
        image="app@sha256:exact",
        networks=("my-pa-remote-mcp_mcp-origin", "my-pa-nas-contract_data-plane"),
        mounts=[
            {"Source": "/volume1/my-pa/config", "Destination": "/srv/my-pa/config", "RW": False},
            {"Source": "/volume1/sources", "Destination": "/srv/my-pa/sources", "RW": False},
            {
                "Source": "/volume1/my-pa/managed",
                "Destination": "/srv/my-pa/managed-documents",
                "RW": True,
            },
        ],
    )
    edge = state(
        image="edge@sha256:exact",
        networks=("my-pa-remote-mcp_mcp-origin", "my-pa-remote-mcp_cloudflare-egress"),
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
    context: dict[str, object] = {
        "app_image": "app@sha256:exact",
        "edge_image": "edge@sha256:exact",
        "data_network": "my-pa-nas-contract_data-plane",
        "networks": {
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
        },
        "postgres_resources": {
            "status": "verified",
            "data_network": "my-pa-nas-contract_data-plane",
            "postgres_container_id": "postgres-id",
            "postgres_image_id": "sha256:postgres",
        },
        "postgres": {
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
    }
    return app, edge, context


def _with_workspace(app: dict, source: object, *, rw: object = True) -> dict:
    mounts = [
        *app["Mounts"],
        {"Source": source, "Destination": "/srv/my-pa/workspaces/mcp", "RW": rw},
    ]
    return {**app, "Mounts": mounts}


def test_live_gate_workspace_mount_is_optional() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    assert gate.violations(app, edge, **context) == []


def test_live_gate_accepts_one_writable_disjoint_workspace_subtree() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    mounted = _with_workspace(app, "/volume1/homes/bfetting/MCP")
    assert gate.violations(mounted, edge, **context) == []


def test_live_gate_refuses_a_read_only_workspace_mount() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    for rw in (False, None, "true"):
        mounted = _with_workspace(app, "/volume1/homes/bfetting/MCP", rw=rw)
        assert gate.violations(mounted, edge, **context) == ["workspace_mount_not_writable"], rw


@pytest.mark.parametrize("source", ["/", "/volume1", "/volume1/", "/volume1/homes"])
def test_live_gate_refuses_the_share_or_homes_root_as_workspace(source: str) -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    errors = gate.violations(_with_workspace(app, source), edge, **context)
    assert "workspace_mount_too_broad" in errors
    assert "workspace_mount_not_writable" not in errors


@pytest.mark.parametrize("source", ["/volume1/homes/bfetting", "/volume1/homes/someone"])
def test_live_gate_refuses_a_whole_home_as_workspace(source: str) -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    errors = gate.violations(_with_workspace(app, source), edge, **context)
    assert errors == ["workspace_mount_too_broad", "workspace_mount_source_mismatch"]
    # Even configured to it, a whole home is too broad.
    configured = gate.violations(
        _with_workspace(app, source), edge, **context, admitted_workspace_source=source
    )
    assert configured == ["workspace_mount_too_broad"]


@pytest.mark.parametrize(
    "source",
    [
        "/volume1/homes/bfetting/Other",  # a sibling subtree
        "/volume1/homes/bfetting/MCP/inner",  # inside the admitted subtree
        "/volume1/homes/bfetting/MCP/",  # not the exact spelling
        "/volume1/homes/other/MCP",  # another user's folder of the same name
        "/volume1/docker",  # outside the homes tree
    ],
)
def test_live_gate_requires_exactly_the_admitted_workspace_source(source: str) -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    errors = gate.violations(_with_workspace(app, source), edge, **context)
    assert errors == ["workspace_mount_source_mismatch"]


@pytest.mark.parametrize("source", [None, "", "volume1/homes/bfetting/MCP", 7])
def test_live_gate_refuses_a_relative_or_missing_workspace_source(source: object) -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    errors = gate.violations(_with_workspace(app, source), edge, **context)
    assert errors == ["workspace_mount_source_identity"]


@pytest.mark.parametrize(
    "source",
    [
        "/volume1/my-pa/config",  # equal to the config source
        "/volume1/my-pa",  # an ancestor of config and managed
        "/volume1/my-pa/managed/inner",  # inside the managed source
        "/volume1/sources/MCP",  # inside the read-only sources
    ],
)
def test_live_gate_refuses_a_workspace_overlapping_another_mount(source: str) -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    # Configured to the overlapping path itself, so only the overlap remains.
    errors = gate.violations(
        _with_workspace(app, source), edge, **context, admitted_workspace_source=source
    )
    assert errors == ["app_mount_overlap"]


@pytest.mark.parametrize(
    ("overlay", "service"),
    [
        ("ops/nas/compose.files-workspace.gateway.example.yml", "gateway"),
        ("ops/nas/remote/compose.files-workspace.remote.example.yml", "my-pa-mcp-remote"),
    ],
)
def test_files_workspace_overlays_bind_one_writable_subtree(overlay: str, service: str) -> None:
    text = (ROOT / overlay).read_text(encoding="utf-8")
    body = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert body == [
        "services:",
        f"  {service}:",
        "    environment:",
        "      MY_PA_FILES_WORKSPACE_ROOT: /srv/my-pa/workspaces/mcp",
        "      MY_PA_FILES_WORKSPACE_ID: mcp",
        '      MY_PA_FILES_MAX_UPLOAD_BYTES: "10737418240"',
        '      MY_PA_FILES_DISK_RESERVE_BYTES: "21474836480"',
        "    volumes:",
        "      - type: bind",
        "        source: /volume1/homes/bfetting/MCP",
        "        target: /srv/my-pa/workspaces/mcp",
        "        read_only: false",
    ]
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    assert gate.WORKSPACE_DESTINATION == "/srv/my-pa/workspaces/mcp"
    assert gate.WORKSPACE_SOURCE == "/volume1/homes/bfetting/MCP"  # the bind source above
    assert "ops/runbooks/files-workspace.md" in text


CLOUDFLARE_EGRESS = "my-pa-remote-mcp_cloudflare-egress"


def _with_network(state: dict, name: str) -> dict:
    networks = {**state["NetworkSettings"]["Networks"], name: {}}
    return {**state, "NetworkSettings": {"Networks": networks}}


def test_live_gate_accepts_the_cloudflare_egress_network_on_the_app() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    assert gate.violations(_with_network(app, CLOUDFLARE_EGRESS), edge, **context) == []


def test_live_gate_refuses_an_internal_cloudflare_egress_network_for_the_app() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    context["networks"] = {**context["networks"], CLOUDFLARE_EGRESS: {"Internal": True}}  # type: ignore[dict-item]
    errors = gate.violations(_with_network(app, CLOUDFLARE_EGRESS), edge, **context)
    assert errors == [f"network_internalness:{CLOUDFLARE_EGRESS}"]


def test_live_gate_refuses_a_dedicated_handle_egress_network() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    errors = gate.violations(_with_network(app, "my-pa-remote-mcp_handle-egress"), edge, **context)
    assert errors == ["app_network_identity"]


def test_live_gate_refuses_any_other_extra_app_network() -> None:
    gate = _module(ROOT / "ops/nas/remote/live-gate.py")
    app, edge, context = _live_gate_shape(gate)
    errors = gate.violations(_with_network(app, "my-pa-remote-mcp_other"), edge, **context)
    assert errors == ["app_network_identity"]


def test_handle_egress_overlay_joins_the_app_to_the_cloudflare_egress_network() -> None:
    text = (ROOT / "ops/nas/remote/compose.files-handle-egress.remote.example.yml").read_text(
        encoding="utf-8"
    )
    body = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert body == [
        "services:",
        "  my-pa-mcp-remote:",
        "    networks: [data-plane, mcp-origin, cloudflare-egress]",
    ]
    assert "ops/runbooks/files-workspace.md" in text
