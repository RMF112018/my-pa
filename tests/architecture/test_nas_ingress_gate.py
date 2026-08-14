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
    proxy_cap_add: list[str] | None = None,
    host_edge_internal: bool = False,
    extra_host_edge_member: bool = False,
    proxy_live_publication: bool = True,
    lookalike_proxy_host_edge: bool = False,
    extra_live_publication: bool = False,
    missing_proxy_tmpfs: bool = False,
    extra_proxy_tmpfs: bool = False,
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
    web_environment = [
        "NODE_ENV=production",
        "MYPA_AUTH_MODE=local_operator",
        "MYPA_GATEWAY_URL=http://gateway:8765",
        "MYPA_GATEWAY_AUTH_MODE=local_operator",
        "MYPA_CANONICAL_ORIGIN=https://my-pa.tail.example",
        f"MYPA_SESSION_SECRET={session_secret}",
        f"MYPA_LOCAL_OPERATOR_SECRET={operator_secret}",
        *(["MYPA_ENTRA_CLIENT_ID=forbidden"] if planted_entra else []),
    ]

    def runner(command: list[str]) -> str:
        if command[0:2] == ["docker", "info"]:
            return '{"ID":"nas"}'
        if command[0:2] == ["tailscale", "version"]:
            return '{"short":"1.90.1"}'
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
            assert "--no-env-resolution" not in command
            return json.dumps(
                {
                    "services": {
                        "web": {"environment": dict(item.split("=", 1) for item in web_environment)}
                    }
                }
            )
        if command[0:2] == ["docker", "compose"]:
            return f"{command[-1]}-id\n"
        if command[0:3] == ["docker", "network", "inspect"]:
            is_host_edge = command[-1].endswith("_host-edge")
            return json.dumps(
                [
                    {
                        "Internal": host_edge_internal if is_host_edge else True,
                        "Id": "a" * 64,
                        "Containers": (
                            {
                                "proxy-id": {},
                                **({"unrelated-id": {}} if extra_host_edge_member else {}),
                            }
                            if is_host_edge
                            else {}
                        ),
                    }
                ]
            )
        name = command[-1].removesuffix("-id")
        host = {
            "Privileged": False,
            "PublishAllPorts": False,
            "NetworkMode": "default",
            "CapAdd": (
                ["NET_BIND_SERVICE"]
                if name == "proxy" and proxy_cap_add is None
                else proxy_cap_add or []
            ),
            "CapDrop": ["ALL"],
            "Devices": [],
            "SecurityOpt": ["no-new-privileges:true"],
            "ReadonlyRootfs": name == "proxy",
            "Tmpfs": (
                {
                    **({} if missing_proxy_tmpfs else {"/config": "", "/data": ""}),
                    **({"/unexpected": ""} if extra_proxy_tmpfs else {}),
                }
                if name == "proxy"
                else None
            ),
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
            else web_environment
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
                        "Networks": {
                            (
                                f"evil_{item}"
                                if lookalike_proxy_host_edge
                                and name == "proxy"
                                and item == "host-edge"
                                else f"my-pa-nas-contract_{item}"
                            ): {}
                            for item in gate.NETWORKS[name]
                        },
                        "Ports": (
                            {
                                "80/tcp": None,
                                "443/tcp": None,
                                "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}],
                                **(
                                    {
                                        "8443/tcp": [
                                            {
                                                "HostIp": "0.0.0.0",  # noqa: S104
                                                "HostPort": "9443",
                                            }
                                        ]
                                    }
                                    if extra_live_publication
                                    else {}
                                ),
                            }
                            if name == "proxy" and proxy_live_publication
                            else {}
                        ),
                    },
                    "Mounts": (
                        [
                            {
                                "Type": "bind",
                                "Source": str(config.resolve()),
                                "Destination": "/etc/caddy/Caddyfile",
                                "RW": False,
                            }
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
            process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
        )
        == []
    )


def test_gate_refuses_a_different_web_env_interpolation_path(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "other.env")},
    )
    assert errors == ["web_env_compose_binding"]


def test_gate_requires_the_canonical_web_env_file_declaration() -> None:
    gate = _gate()
    compose = (ROOT / "ops/nas/compose.example.yml").read_text(encoding="utf-8")
    assert gate._web_env_file_contract(compose)
    changed = compose.replace(
        'env_file: ["${MY_PA_WEB_ENV_FILE:?owner-only web env file required}"]',
        'env_file: ["${UNBOUND_WEB_ENV_FILE:?owner-only web env file required}"]',
    )
    assert not gate._web_env_file_contract(changed)


def test_gate_requires_non_internal_proxy_only_host_edge(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path, host_edge_internal=True)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "host_edge_network" in errors


def test_gate_refuses_an_unrelated_host_edge_member(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path, extra_host_edge_member=True)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "host_edge_membership" in errors


def test_gate_refuses_saved_binding_without_live_port_allocation(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path, proxy_live_publication=False)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "proxy_publication" in errors


def test_gate_refuses_suffix_matching_lookalike_network(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path, lookalike_proxy_host_edge=True)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "proxy_networks" in errors


def test_gate_refuses_an_extra_live_publication(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path, extra_live_publication=True)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "proxy_publication" in errors


@pytest.mark.parametrize("mode", ("missing", "extra"))
def test_gate_requires_the_exact_proxy_tmpfs_set(tmp_path: Path, mode: str) -> None:
    manifest, runner = _live_fixture(
        tmp_path,
        missing_proxy_tmpfs=mode == "missing",
        extra_proxy_tmpfs=mode == "extra",
    )
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "proxy_config_mount" in errors


def test_gate_refuses_any_residual_entra_environment(tmp_path: Path) -> None:
    manifest, runner = _live_fixture(tmp_path, planted_entra=True)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "entra_environment_present" in errors


@pytest.mark.parametrize("capabilities", ([], ["SYS_ADMIN"], ["NET_BIND_SERVICE", "CHOWN"]))
def test_gate_refuses_proxy_without_the_exact_caddy_exec_capability(
    tmp_path: Path, capabilities: list[str]
) -> None:
    manifest, runner = _live_fixture(tmp_path, proxy_cap_add=capabilities)
    errors = _gate().verify(
        manifest,
        ROOT / "ops/nas/proxy-allowlist.example.caddy",
        ROOT / "ops/nas/compose.example.yml",
        live=True,
        runner=runner,
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
    )
    assert "proxy_runtime_authority" in errors


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
        process_environment={"MY_PA_WEB_ENV_FILE": str(tmp_path / "web.env")},
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
