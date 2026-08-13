from __future__ import annotations

import importlib.util
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
    assert text.count("hostname: mcp.example.com") == 3
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
                "PidsLimit": 128 if image.startswith("app") else 64,
                "NanoCpus": 1_000_000_000,
                "Memory": 256 * 1024 * 1024,
            },
            "Mounts": mounts,
            "NetworkSettings": {"Networks": {name: {} for name in networks}},
        }

    app = state(
        image="app@sha256:exact",
        networks=(
            "my-pa-remote-mcp_mcp-origin",
            "private-data",
            "my-pa-remote-mcp_identity-egress",
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
        "private-data": {"Internal": False},
        "my-pa-remote-mcp_mcp-origin": {"Internal": True},
        "my-pa-remote-mcp_identity-egress": {"Internal": False},
        "my-pa-remote-mcp_cloudflare-egress": {"Internal": False},
    }
    assert (
        gate.violations(
            app,
            edge,
            app_image="app@sha256:exact",
            edge_image="edge@sha256:exact",
            data_network="private-data",
            networks=network_states,
        )
        == []
    )
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
            data_network="private-data",
            networks=network_states,
        )
    ) == {"origin_host_port", "source_mount_not_read_only"}
