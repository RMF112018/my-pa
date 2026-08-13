"""NAS-06 private ingress evidence gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

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


def test_dns_evidence_refuses_divergent_aaaa_cname_chain() -> None:
    gate = _gate()
    host = "login.microsoftonline.com"
    a_answer = gate._dns_answer(
        "login.microsoftonline.com. 300 IN CNAME login.example.edge.\n"
        "login.example.edge. 300 IN A 20.190.128.1\n",
        host,
        "A",
    )
    aaaa_answer = gate._dns_answer(
        "login.microsoftonline.com. 300 IN CNAME login.other.edge.\n",
        host,
        "AAAA",
    )

    matches, _ipv4 = gate._dns_evidence_matches(
        [(a_answer, aaaa_answer)],
        {
            "cname_chain": ["login.microsoftonline.com", "login.example.edge"],
            "ipv4": ["20.190.128.1"],
        },
    )

    assert not matches


def test_gate_uses_real_serve_shape_and_binds_all_compose_services(tmp_path: Path) -> None:
    gate = _gate()
    config = ROOT / "ops/nas/proxy-allowlist.example.caddy"
    compose = ROOT / "ops/nas/compose.example.yml"
    bridge = "br-" + "a" * 12
    base = {"family": "inet", "table": "my_pa_egress", "chain": "entra_only"}
    forward = {"family": "inet", "table": "my_pa_egress", "chain": "forward"}
    policy_object = {
        "nftables": [
            {"metainfo": {"json_schema_version": 1}},
            {"table": {"family": "inet", "name": "my_pa_egress"}},
            {"chain": base},
            {
                "chain": {
                    **forward,
                    "type": "filter",
                    "hook": "forward",
                    "prio": 0,
                    "policy": "accept",
                }
            },
            {
                "rule": {
                    **forward,
                    "expr": [
                        {
                            "match": {
                                "left": {"meta": {"key": "iifname"}},
                                "op": "==",
                                "right": bridge,
                            }
                        },
                        {"jump": {"target": "entra_only"}},
                    ],
                }
            },
            {
                "rule": {
                    **forward,
                    "expr": [
                        {
                            "match": {
                                "left": {"meta": {"key": "oifname"}},
                                "op": "==",
                                "right": bridge,
                            }
                        },
                        {
                            "match": {
                                "left": {"ct": {"key": "state"}},
                                "op": "in",
                                "right": {"set": ["established", "related"]},
                            }
                        },
                        {"accept": None},
                    ],
                }
            },
            {
                "rule": {
                    **base,
                    "expr": [
                        {
                            "match": {
                                "left": {"meta": {"key": "iifname"}},
                                "op": "==",
                                "right": bridge,
                            }
                        },
                        {
                            "match": {
                                "left": {"payload": {"protocol": "ip", "field": "daddr"}},
                                "op": "in",
                                "right": {"set": ["20.190.128.1"]},
                            }
                        },
                        {
                            "match": {
                                "left": {"payload": {"protocol": "tcp", "field": "dport"}},
                                "op": "==",
                                "right": 443,
                            }
                        },
                        {"accept": None},
                    ],
                }
            },
            {
                "rule": {
                    **base,
                    "expr": [
                        {
                            "match": {
                                "left": {"meta": {"key": "iifname"}},
                                "op": "==",
                                "right": bridge,
                            }
                        },
                        {
                            "match": {
                                "left": {"payload": {"protocol": "ip", "field": "daddr"}},
                                "op": "in",
                                "right": {"set": ["1.1.1.1"]},
                            }
                        },
                        {
                            "match": {
                                "left": {"meta": {"key": "l4proto"}},
                                "op": "in",
                                "right": {"set": ["tcp", "udp"]},
                            }
                        },
                        {
                            "match": {
                                "left": {"payload": {"protocol": "th", "field": "dport"}},
                                "op": "==",
                                "right": 53,
                            }
                        },
                        {"accept": None},
                    ],
                }
            },
            {"rule": {**base, "expr": [{"drop": None}]}},
        ]
    }
    policy = json.dumps(policy_object, separators=(",", ":"))
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
        'schema = "my-pa.nas-ingress-evidence.v1"\nstatus = "verified"\n'
        'docker_engine_id = "nas"\ncompose_project = "my-pa-nas-contract"\n'
        'tailnet_hostname = "my-pa.tail.example"\n'
        'canonical_origin = "https://my-pa.tail.example"\n'
        f'proxy_config_sha256 = "{hashlib.sha256(config.read_bytes()).hexdigest()}"\n'
        'loopback_target = "127.0.0.1:8443"\nproxy_uid = 100\nproxy_gid = 100\n'
        'tailscale_version = "1.90.1"\n'
        f'egress_policy_sha256 = "{hashlib.sha256(policy.encode()).hexdigest()}"\n'
        'entra_hosts = ["login.microsoftonline.com"]\n'
        'entra_addresses = ["20.190.128.1"]\n'
        'dns_servers = ["1.1.1.1"]\n'
        f'web_env_file = "{web_env}"\nweb_env_owner_uid = {web_env.stat().st_uid}\n'
        '[endpoint_evidence."login.microsoftonline.com"]\n'
        'roles = ["discovery", "authorize", "token", "jwks"]\n'
        'cname_chain = ["login.microsoftonline.com", "login.example.edge"]\n'
        'ipv4 = ["20.190.128.1"]\n'
        'ipv6_policy = "refuse_until_separately_allowlisted"\n'
        f'observed_at = "{datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}"\n'
        "ttl_seconds = 3600\n" + service_sections,
        encoding="utf-8",
    )

    def runner(command: list[str]) -> str:
        if command[0:2] == ["docker", "info"]:
            return '{"ID":"nas"}'
        if command[0:2] == ["tailscale", "version"]:
            return '{"Short":"1.90.1"}'
        if command[0] == "nft":
            return policy
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
        if command[0] == "dig":
            cname = "login.microsoftonline.com. 300 IN CNAME login.example.edge.\n"
            return (
                cname + "login.example.edge. 300 IN A 20.190.128.1\n" if "A" in command else cname
            )
        if command[0:3] == ["docker", "network", "inspect"]:
            return json.dumps(
                [
                    {
                        "Internal": not command[-1].endswith("entra-egress"),
                        "Id": "a" * 64,
                    }
                ]
            )
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
        return json.dumps(
            [
                {
                    "Image": image,
                    "Config": {
                        "User": "100:100" if name == "proxy" else "10001:10001",
                        "Env": (
                            ["MY_PA_TAILNET_HOST=my-pa.tail.example"]
                            if name == "proxy"
                            else [
                                "MY_PA_AUTH_MODE=entra",
                                "MY_PA_REMOTE_INGRESS_ENABLED=true",
                                "MY_PA_ENTRA_TENANT_ID=tenant",
                                "MY_PA_ENTRA_CLIENT_ID=client",
                                "MY_PA_ENTRA_ISSUER=https://login.microsoftonline.com/tenant/v2.0",
                                "MY_PA_ENTRA_JWKS_URI=https://login.microsoftonline.com/discovery/keys",
                            ]
                            if name == "gateway"
                            else [
                                "NODE_ENV=production",
                                "MYPA_AUTH_MODE=entra",
                                "MYPA_GATEWAY_URL=http://gateway:8765",
                                "MYPA_GATEWAY_AUTH_MODE=entra",
                                "MYPA_CANONICAL_ORIGIN=https://my-pa.tail.example",
                                "MYPA_ENTRA_REDIRECT_URI=https://my-pa.tail.example/auth/callback",
                                "MYPA_ENTRA_HOME_TENANT_ID=tenant",
                                "MYPA_ENTRA_CLIENT_ID=client",
                                "MYPA_ENTRA_CLIENT_SECRET=secret",
                                "MYPA_ENTRA_API_SCOPE=scope",
                                "MYPA_SESSION_SECRET=session-secret",
                            ]
                            if name == "web"
                            else []
                        ),
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

    assert gate.verify(manifest, config, compose, live=True, runner=runner) == []


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
