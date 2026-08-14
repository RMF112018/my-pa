"""NAS private-ingress evidence for permanent local-operator authentication."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _gate() -> ModuleType:
    path = ROOT / "ops/nas/ingress_gate.py"
    spec = importlib.util.spec_from_file_location("ingress_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_refuses_without_external_commands() -> None:
    called = False

    def runner(_command: list[str]) -> str:
        nonlocal called
        called = True
        raise AssertionError

    errors = _gate().verify(
        ROOT / "ops/nas/ingress-manifest.example.toml",
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
    )
    assert "status_not_verified" in errors
    assert not called


def _live_fixture(
    tmp_path: Path,
    *,
    planted_entra: bool = False,
    session_secret: str = "S" * 32,
    operator_secret: str = "O" * 43,
) -> tuple[Path, object]:
    gate = _gate()
    config = ROOT / "ops/nas/proxy-allowlist.example.caddy"
    image = "sha256:" + "1" * 64
    service_sections = "".join(
        f'\n[services.{name}]\ncontainer_id = "{name}-id"\nimage_id = "{image}"\n'
        for name in gate.SERVICES
    )
    web_env = tmp_path / "web.env"
    web_env.write_text("owner-only-placeholder\n", encoding="utf-8")
    web_env.chmod(0o600)
    manifest = tmp_path / "ingress.toml"
    manifest.write_text(
        'schema = "my-pa.nas-ingress-evidence.v2"\nstatus = "verified"\n'
        'docker_engine_id = "nas"\ncompose_project = "my-pa-nas-contract"\n'
        'tailnet_hostname = "my-pa.tail.example"\n'
        'canonical_origin = "https://my-pa.tail.example"\n'
        f'proxy_config_sha256 = "{hashlib.sha256(config.read_bytes()).hexdigest()}"\n'
        'loopback_target = "127.0.0.1:8443"\nproxy_uid = 100\nproxy_gid = 100\n'
        'tailscale_version = "1.90.1"\n'
        f'web_env_file = "{web_env}"\nweb_env_owner_uid = {web_env.stat().st_uid}\n'
        + service_sections,
        encoding="utf-8",
    )

    def runner(command: list[str]) -> str:
        if command[0:2] == ["docker", "info"]:
            return '{"ID":"nas"}'
        if command[0:2] == ["tailscale", "version"]:
            return '{"Short":"1.90.1"}'
        if command[0:3] == ["tailscale", "serve", "status"]:
            return json.dumps(
                {
                    "TCP": {"443": {"HTTPS": True}},
                    "Web": {
                        "my-pa.tail.example:443": {
                            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8443"}}
                        }
                    },
                    "AllowFunnel": {},
                }
            )
        if command[0:2] == ["docker", "compose"] and "config" in command:
            return json.dumps({"services": {"web": {"env_file": [{"path": str(web_env)}]}}})
        if command[0:2] == ["docker", "compose"]:
            return f"{command[-1]}-id\n"
        if command[0:3] == ["docker", "network", "inspect"]:
            return json.dumps([{"Internal": True, "Id": "a" * 64}])
        name = command[-1].removesuffix("-id")
        host = {
            "Privileged": False,
            "PublishAllPorts": False,
            "NetworkMode": "default",
            "CapAdd": [],
            "CapDrop": ["ALL"],
            "Devices": [],
            "SecurityOpt": ["no-new-privileges:true"],
            "ReadonlyRootfs": name == "proxy",
            "PortBindings": (
                {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
                if name == "proxy"
                else {}
            ),
        }
        environment = (
            ["MY_PA_TAILNET_HOST=my-pa.tail.example"]
            if name == "proxy"
            else ["MY_PA_AUTH_MODE=local_operator", "MY_PA_REMOTE_INGRESS_ENABLED=true"]
            if name == "gateway"
            else [
                "NODE_ENV=production",
                "MYPA_AUTH_MODE=local_operator",
                "MYPA_GATEWAY_URL=http://gateway:8765",
                "MYPA_GATEWAY_AUTH_MODE=local_operator",
                "MYPA_CANONICAL_ORIGIN=https://my-pa.tail.example",
                f"MYPA_SESSION_SECRET={session_secret}",
                f"MYPA_LOCAL_OPERATOR_SECRET={operator_secret}",
                *(["MYPA_ENTRA_CLIENT_ID=forbidden"] if planted_entra else []),
            ]
            if name == "web"
            else []
        )
        return json.dumps(
            [
                {
                    "Image": image,
                    "Config": {
                        "User": "100:100" if name == "proxy" else "10001:10001",
                        "Env": environment,
                    },
                    "HostConfig": host,
                    "NetworkSettings": {
                        "Networks": {f"stack_{item}": {} for item in gate.NETWORKS[name]}
                    },
                    "Mounts": (
                        [
                            {
                                "Type": "bind",
                                "Source": str(config.resolve()),
                                "Destination": "/etc/caddy/Caddyfile",
                                "RW": False,
                            },
                            {"Type": "tmpfs", "Source": "", "Destination": "/config", "RW": True},
                            {"Type": "tmpfs", "Source": "", "Destination": "/data", "RW": True},
                        ]
                        if name == "proxy"
                        else []
                    ),
                }
            ]
        )

    return manifest, runner


def test_gate_binds_private_local_operator_runtime(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path)
    assert (
        _gate().verify(
            manifest,
            ROOT / "ops/nas/proxy-allowlist.example.caddy",
            ROOT / "ops/nas/compose.example.yml",
            live=True,
            runner=runner,
        )
        == []
    )


def test_gate_refuses_any_residual_entra_environment(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path, planted_entra=True)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
    )
    assert "entra_environment_present" in errors


@pytest.mark.parametrize(
    ("session_secret", "operator_secret"),
    (("short", "O" * 43), ("S" * 32, "short"), ("S" * 32, "!" * 43)),
)
def test_gate_refuses_credentials_the_runtime_would_reject(
    tmp_path: Path, session_secret: str, operator_secret: str
) -> None:
    manifest, runner = _live_fixture(
        tmp_path, session_secret=session_secret, operator_secret=operator_secret
    )
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
    )
    assert "web_runtime_authority" in errors


def test_proxy_strips_cross_route_and_spoofable_authority_headers() -> None:
    config = (ROOT / "ops/nas/proxy-allowlist.example.caddy").read_text()
    remote = config.split("handle @remote_capture", 1)[1].split("@remote_capture_wrong_method", 1)[
        0
    ]
    browser = config.rsplit("handle {", 1)[1]
    assert "header_up -Cookie" in remote and "header_up -Authorization" not in remote
    assert "header_up -Authorization" in browser and "header_up -Cookie" not in browser
    for header in (
        "Forwarded",
        "X-Forwarded-*",
        "Tailscale-User-Login",
        "Tailscale-User-Profile-Pic",
        "Tailscale-App-Capabilities",
    ):
        assert f"header_up -{header}" in remote
        assert f"header_up -{header}" in browser
