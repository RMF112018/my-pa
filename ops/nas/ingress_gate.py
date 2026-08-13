#!/usr/bin/env python3
"""Read-only NAS-06 private ingress and egress evidence gate."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

SERVICES = ("postgres", "gateway", "worker-enrollment", "worker-capture", "web", "proxy")
NETWORKS = {
    "postgres": {"data-plane"},
    "gateway": {"data-plane", "ingress-plane", "entra-egress"},
    "worker-enrollment": {"data-plane"},
    "worker-capture": {"data-plane"},
    "web": {"ingress-plane", "entra-egress"},
    "proxy": {"ingress-plane"},
}


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout  # noqa: S603


def _hostname(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 253 or value.endswith("."):
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        pass
    labels = value.split(".")
    return len(labels) >= 2 and all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
    )


def _json_object(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError("JSON root is not an object")
    return parsed


def _json_single_object(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
        raise TypeError("JSON root is not a single-object array")
    return parsed[0]


def _environment(config: dict[str, Any]) -> dict[str, str] | None:
    items = config.get("Env") or []
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        return None
    pairs = [item.partition("=") for item in items]
    keys = [key for key, separator, _value in pairs if separator]
    if len(keys) != len(items) or len(keys) != len(set(keys)):
        return None
    return {key: value for key, _separator, value in pairs}


def _normalize_nft(policy: dict[str, Any]) -> dict[str, Any] | None:
    items = policy.get("nftables")
    if not isinstance(items, list) or not items:
        return None
    meta = items[0].get("metainfo") if isinstance(items[0], dict) else None
    if not isinstance(meta, dict) or meta.get("json_schema_version") != 1:
        return None
    normalized: list[dict[str, Any]] = []
    for item in items[1:]:
        if not isinstance(item, dict) or len(item) != 1:
            return None
        kind, value = next(iter(item.items()))
        if kind not in {"table", "chain", "rule"} or not isinstance(value, dict):
            return None
        value = {key: entry for key, entry in value.items() if key not in {"handle", "index"}}
        normalized.append({kind: value})
    return {"nftables": normalized}


def _dns_answer(raw: str, host: str, record_type: str) -> tuple[set[str], list[str]]:
    current = host.rstrip(".")
    chain = [current]
    records: set[str] = set()
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[2] != "IN" or fields[3] not in {"CNAME", record_type}:
            raise ValueError("unexpected DNS answer")
        owner = fields[0].rstrip(".")
        if owner != current:
            raise ValueError("disconnected DNS answer")
        if fields[3] == "CNAME":
            current = fields[4].rstrip(".")
            if current in chain or len(chain) >= 8 or not _hostname(current):
                raise ValueError("unsafe CNAME chain")
            chain.append(current)
        else:
            address = ipaddress.ip_address(fields[4])
            if (record_type == "A" and address.version != 4) or (
                record_type == "AAAA" and address.version != 6
            ):
                raise ValueError("wrong DNS address family")
            records.add(str(address))
    return records, chain


def _dns_evidence_matches(
    answers: list[
        tuple[tuple[set[str], list[str]], tuple[set[str], list[str]]]
    ],
    evidence: dict[str, Any],
) -> tuple[bool, set[str]]:
    ipv4 = set().union(*(answer[0][0] for answer in answers))
    ipv6 = set().union(*(answer[1][0] for answer in answers))
    chains = {
        tuple(result[1])
        for answer in answers
        for result in answer
    }
    matches = (
        chains == {tuple(evidence["cname_chain"])}
        and sorted(ipv4) == sorted(evidence["ipv4"])
        and not ipv6
    )
    return matches, ipv4


def verify(
    manifest_path: Path,
    proxy_config: Path,
    compose_file: Path,
    *,
    live: bool = False,
    runner: Callable[[list[str]], str] = _run,
) -> list[str]:
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        config_path = proxy_config.resolve(strict=True)
        config_bytes = config_path.read_bytes()
    except (OSError, tomllib.TOMLDecodeError):
        return ["evidence_unreadable"]
    errors: list[str] = []
    required = {
        "schema",
        "status",
        "docker_engine_id",
        "compose_project",
        "tailnet_hostname",
        "canonical_origin",
        "proxy_config_sha256",
        "loopback_target",
        "proxy_uid",
        "proxy_gid",
        "tailscale_version",
        "egress_policy_sha256",
        "entra_hosts",
        "entra_addresses",
        "dns_servers",
        "endpoint_evidence",
        "web_env_file",
        "web_env_owner_uid",
        "services",
    }
    if set(data) != required or data.get("schema") != "my-pa.nas-ingress-evidence.v1":
        errors.append("manifest_schema")
    if data.get("status") != "verified":
        errors.append("status_not_verified")
    host = data.get("tailnet_hostname")
    if not _hostname(host):
        errors.append("tailnet_hostname")
    if data.get("canonical_origin") != f"https://{host}":
        errors.append("canonical_origin")
    if data.get("proxy_config_sha256") != hashlib.sha256(config_bytes).hexdigest():
        errors.append("proxy_config_hash")
    for key in ("docker_engine_id", "compose_project", "tailscale_version"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key}_identity")
    for key in ("proxy_uid", "proxy_gid"):
        if type(data.get(key)) is not int or data[key] <= 0:
            errors.append("proxy_user_identity")
    target = data.get("loopback_target")
    match = re.fullmatch(r"127\.0\.0\.1:([1-9][0-9]{0,4})", str(target))
    if match is None or int(match.group(1)) > 65535:
        errors.append("loopback_target")
    hosts = data.get("entra_hosts")
    if (
        not isinstance(hosts, list)
        or not hosts
        or len(hosts) != len(set(hosts))
        or not all(_hostname(item) for item in hosts)
    ):
        errors.append("egress_hosts")
    addresses = data.get("entra_addresses")
    dns_servers = data.get("dns_servers")
    for value, code in ((addresses, "egress_addresses"), (dns_servers, "dns_servers")):
        try:
            valid = (
                isinstance(value, list)
                and bool(value)
                and len(value) == len(set(value))
                and all(
                    isinstance(item, str) and ipaddress.ip_address(item).version == 4
                    for item in value
                )
            )
        except ValueError:
            valid = False
        if not valid:
            errors.append(code)
    if re.fullmatch(r"[0-9a-f]{64}", str(data.get("egress_policy_sha256"))) is None:
        errors.append("egress_policy_hash")
    endpoint_evidence = data.get("endpoint_evidence")
    if not isinstance(endpoint_evidence, dict) or set(endpoint_evidence) != set(hosts or []):
        errors.append("endpoint_evidence")
    else:
        for endpoint_host, evidence in endpoint_evidence.items():
            if (
                not isinstance(evidence, dict)
                or set(evidence)
                != {
                    "roles",
                    "cname_chain",
                    "ipv4",
                    "ipv6_policy",
                    "observed_at",
                    "ttl_seconds",
                }
                or not isinstance(evidence.get("roles"), list)
                or set(evidence["roles"]) != {"discovery", "authorize", "token", "jwks"}
                or not isinstance(evidence.get("cname_chain"), list)
                or not 1 <= len(evidence["cname_chain"]) <= 8
                or evidence["cname_chain"][0] != endpoint_host
                or len(evidence["cname_chain"]) != len(set(evidence["cname_chain"]))
                or not all(_hostname(item) for item in evidence["cname_chain"])
                or not isinstance(evidence.get("ipv4"), list)
                or evidence.get("ipv6_policy") != "refuse_until_separately_allowlisted"
                or not isinstance(evidence.get("observed_at"), str)
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", evidence["observed_at"])
                is None
                or type(evidence.get("ttl_seconds")) is not int
                or not 1 <= evidence["ttl_seconds"] <= 86400
                or endpoint_host not in (hosts if isinstance(hosts, list) else [])
            ):
                errors.append("endpoint_evidence")
            else:
                observed = datetime.strptime(evidence["observed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=UTC
                )
                now = datetime.now(UTC)
                if observed > now + timedelta(minutes=5):
                    errors.append("endpoint_evidence_future")
                if now > observed + timedelta(seconds=evidence["ttl_seconds"]):
                    errors.append("endpoint_evidence_expired")
    web_env_raw = data.get("web_env_file")
    if not isinstance(web_env_raw, str):
        errors.append("web_env_file")
    if type(data.get("web_env_owner_uid")) is not int or data["web_env_owner_uid"] <= 0:
        errors.append("web_env_file")
    services = data.get("services")
    if not isinstance(services, dict) or set(services) != set(SERVICES):
        errors.append("service_set")
    else:
        for name, identity in services.items():
            if (
                not isinstance(identity, dict)
                or set(identity) != {"container_id", "image_id"}
                or not isinstance(identity.get("container_id"), str)
                or not identity["container_id"].strip()
                or re.fullmatch(r"sha256:[0-9a-f]{64}", str(identity.get("image_id"))) is None
            ):
                errors.append(f"{name}_manifest_identity")
    if not live:
        return [*errors, "live_verification_required"]
    if errors or not compose_file.is_file():
        return errors or ["compose_file_required"]
    hosts = cast(list[str], hosts)
    addresses = cast(list[str], addresses)
    dns_servers = cast(list[str], dns_servers)
    services = cast(dict[str, dict[str, str]], services)
    target = cast(str, target)
    try:
        web_env_path = Path(cast(str, web_env_raw)).resolve(strict=True)
        metadata = web_env_path.stat()
        repo_root = compose_file.resolve(strict=True).parents[2]
    except OSError:
        return ["web_env_file"]
    if (
        web_env_path != Path(cast(str, web_env_raw))
        or not web_env_path.is_file()
        or metadata.st_uid != data["web_env_owner_uid"]
        or metadata.st_mode & 0o777 != 0o600
        or web_env_path == repo_root
        or repo_root in web_env_path.parents
    ):
        return ["web_env_file"]
    try:
        engine = _json_object(runner(["docker", "info", "--format", "{{json .}}"]))
        version = _json_object(runner(["tailscale", "version", "--json"]))
        policy_raw = runner(["nft", "--json", "list", "table", "inet", "my_pa_egress"])
        policy = _json_object(policy_raw)
        tailscale = _json_object(runner(["tailscale", "serve", "status", "--json"]))
        compose_model = _json_object(
            runner(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    data["compose_project"],
                    "--file",
                    str(compose_file),
                    "--profile",
                    "nas-01-contract-only",
                    "config",
                    "--format",
                    "json",
                    "--no-env-resolution",
                ]
            )
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return ["live_inspection"]
    if engine.get("ID") != data["docker_engine_id"]:
        errors.append("docker_engine_identity")
    if version.get("Short") != data["tailscale_version"]:
        errors.append("tailscale_version")
    if hashlib.sha256(policy_raw.encode()).hexdigest() != data["egress_policy_sha256"]:
        errors.append("egress_policy_hash")
    configured_env_files = compose_model.get("services", {}).get("web", {}).get("env_file")
    if (
        not isinstance(configured_env_files, list)
        or len(configured_env_files) != 1
        or not isinstance(configured_env_files[0], dict)
        or set(configured_env_files[0]) not in ({"path"}, {"path", "required"})
        or configured_env_files[0].get("path") != str(web_env_path)
        or configured_env_files[0].get("required", True) is not True
    ):
        errors.append("web_env_compose_binding")
    observed_addresses: set[str] = set()
    for endpoint_host, evidence in cast(dict[str, dict[str, Any]], endpoint_evidence).items():
        try:
            answers = [
                (
                    _dns_answer(
                        runner(
                            [
                                "dig",
                                f"@{server}",
                                "+noall",
                                "+answer",
                                "+time=3",
                                "+tries=1",
                                "A",
                                endpoint_host,
                            ]
                        ),
                        endpoint_host,
                        "A",
                    ),
                    _dns_answer(
                        runner(
                            [
                                "dig",
                                f"@{server}",
                                "+noall",
                                "+answer",
                                "+time=3",
                                "+tries=1",
                                "AAAA",
                                endpoint_host,
                            ]
                        ),
                        endpoint_host,
                        "AAAA",
                    ),
                )
                for server in dns_servers
            ]
        except (OSError, subprocess.SubprocessError, ValueError):
            errors.append("endpoint_resolution")
            continue
        matches, ipv4 = _dns_evidence_matches(answers, evidence)
        if not matches:
            errors.append("endpoint_resolution")
        observed_addresses |= ipv4
    if observed_addresses != set(addresses):
        errors.append("endpoint_address_union")
    inspected_by_name: dict[str, dict[str, Any]] = {}
    for name in SERVICES:
        identity = services[name]
        try:
            compose_id = runner(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    data["compose_project"],
                    "--file",
                    str(compose_file),
                    "--profile",
                    "nas-01-contract-only",
                    "ps",
                    "-q",
                    name,
                ]
            ).strip()
            inspected = json.loads(runner(["docker", "inspect", identity["container_id"]]))
            if (
                not isinstance(inspected, list)
                or len(inspected) != 1
                or not isinstance(inspected[0], dict)
            ):
                raise TypeError
            inspected_by_name[name] = inspected[0]
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
            errors.append(f"{name}_inspection")
            continue
        if compose_id != identity["container_id"]:
            errors.append(f"{name}_compose_identity")
        if inspected[0].get("Image") != identity["image_id"]:
            errors.append(f"{name}_image_identity")
        actual_networks = {
            item.rpartition("_")[2]
            for item in inspected[0].get("NetworkSettings", {}).get("Networks", {})
        }
        if actual_networks != NETWORKS[name]:
            errors.append(f"{name}_networks")
        published = inspected[0].get("HostConfig", {}).get("PortBindings") or {}
        expected_ports = (
            {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": target.rsplit(":", 1)[1]}]}
            if name == "proxy"
            else {}
        )
        if published != expected_ports:
            errors.append(f"{name}_publication")
    if errors:
        return errors
    proxy = inspected_by_name["proxy"]
    proxy_config_data = proxy.get("Config", {})
    proxy_host = proxy.get("HostConfig", {})
    environment = _environment(proxy_config_data)
    if environment is None or environment.get("MY_PA_TAILNET_HOST") != host:
        errors.append("proxy_hostname_environment")
    if (
        proxy_config_data.get("User") != f"{data['proxy_uid']}:{data['proxy_gid']}"
        or proxy_host.get("Privileged")
        or proxy_host.get("PublishAllPorts")
        or proxy_host.get("NetworkMode") == "host"
        or proxy_host.get("CapAdd")
        or set(proxy_host.get("CapDrop") or []) != {"ALL"}
        or proxy_host.get("Devices")
        or set(proxy_host.get("SecurityOpt") or []) != {"no-new-privileges:true"}
        or proxy_host.get("ReadonlyRootfs") is not True
    ):
        errors.append("proxy_runtime_authority")
    mounts = proxy.get("Mounts") or []
    actual_mounts = {
        item.get("Destination"): (item.get("Type"), item.get("Source"), item.get("RW"))
        for item in mounts
        if isinstance(item, dict)
    }
    expected_mounts = {
        "/etc/caddy/Caddyfile": ("bind", str(config_path), False),
        "/config": ("tmpfs", "", True),
        "/data": ("tmpfs", "", True),
    }
    if actual_mounts != expected_mounts:
        errors.append("proxy_config_mount")
    gateway_environment = _environment(inspected_by_name["gateway"].get("Config", {}))
    if gateway_environment is None or (
        gateway_environment.get("MY_PA_AUTH_MODE") != "entra"
        or gateway_environment.get("MY_PA_REMOTE_INGRESS_ENABLED") != "true"
    ):
        errors.append("gateway_ingress_environment")
    web = inspected_by_name["web"]
    web_environment = _environment(web.get("Config", {}))
    required_web = {
        "NODE_ENV": "production",
        "MYPA_AUTH_MODE": "entra",
        "MYPA_GATEWAY_URL": "http://gateway:8765",
        "MYPA_GATEWAY_AUTH_MODE": "entra",
        "MYPA_CANONICAL_ORIGIN": f"https://{host}",
        "MYPA_ENTRA_REDIRECT_URI": f"https://{host}/auth/callback",
    }
    secret_web = {
        "MYPA_ENTRA_HOME_TENANT_ID",
        "MYPA_ENTRA_CLIENT_ID",
        "MYPA_ENTRA_CLIENT_SECRET",
        "MYPA_ENTRA_API_SCOPE",
        "MYPA_SESSION_SECRET",
    }
    if (
        web_environment is None
        or any(web_environment.get(key) != value for key, value in required_web.items())
        or any(not web_environment.get(key) for key in secret_web)
        or any("DATABASE" in key or "POSTGRES" in key for key in web_environment)
        or web.get("Mounts")
    ):
        errors.append("web_runtime_authority")
    gateway_secret_keys = {
        "MY_PA_ENTRA_TENANT_ID",
        "MY_PA_ENTRA_CLIENT_ID",
        "MY_PA_ENTRA_ISSUER",
        "MY_PA_ENTRA_JWKS_URI",
    }
    if gateway_environment is None or any(
        not gateway_environment.get(key) for key in gateway_secret_keys
    ):
        errors.append("gateway_entra_environment")
    elif web_environment is None or (
        gateway_environment["MY_PA_ENTRA_TENANT_ID"]
        != web_environment.get("MYPA_ENTRA_HOME_TENANT_ID")
        or gateway_environment["MY_PA_ENTRA_CLIENT_ID"]
        != web_environment.get("MYPA_ENTRA_CLIENT_ID")
    ):
        errors.append("entra_cross_tier_identity")
    else:
        try:
            issuer = gateway_environment["MY_PA_ENTRA_ISSUER"]
            jwks = gateway_environment["MY_PA_ENTRA_JWKS_URI"]
            issuer_url, jwks_url = urlparse(issuer), urlparse(jwks)
        except ValueError:
            errors.append("gateway_entra_endpoints")
        else:
            configured_hosts = {issuer_url.hostname, jwks_url.hostname}
            if (
                issuer_url.scheme != "https"
                or jwks_url.scheme != "https"
                or None in configured_hosts
                or not configured_hosts <= set(hosts)
            ):
                errors.append("gateway_entra_endpoints")
    try:
        internal = {
            name: _json_single_object(
                runner(["docker", "network", "inspect", f"{data['compose_project']}_{name}"])
            )
            for name in ("data-plane", "ingress-plane", "entra-egress")
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return [*errors, "network_inspection"]
    if (
        internal["data-plane"].get("Internal") is not True
        or internal["ingress-plane"].get("Internal") is not True
        or internal["entra-egress"].get("Internal") is not False
    ):
        errors.append("network_internality")
    egress_id = internal["entra-egress"].get("Id")
    if not isinstance(egress_id, str) or re.fullmatch(r"[0-9a-f]{64}", egress_id) is None:
        errors.append("egress_network_identity")
    else:
        bridge = f"br-{egress_id[:12]}"
        base = {"family": "inet", "table": "my_pa_egress", "chain": "entra_only"}
        forward = {"family": "inet", "table": "my_pa_egress", "chain": "forward"}
        expected_policy = {
            "nftables": [
                {"table": {"family": "inet", "name": "my_pa_egress"}},
                {
                    "chain": {
                        **base,
                    }
                },
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
                                    "right": {"set": sorted(addresses)},
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
                                    "right": {"set": sorted(dns_servers)},
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
        if _normalize_nft(policy) != expected_policy:
            errors.append("egress_policy_content")
    hostport = f"{host}:443"
    expected_web = {hostport: {"Handlers": {"/": {"Proxy": f"http://{target}"}}}}
    if tailscale.get("TCP") != {"443": {"HTTPS": True}} or tailscale.get("Web") != expected_web:
        errors.append("tailscale_private_https")
    allow_funnel = tailscale.get("AllowFunnel") or {}
    if not isinstance(allow_funnel, dict) or any(
        value is not False for value in allow_funnel.values()
    ):
        errors.append("tailscale_funnel")
    if tailscale.get("Services") or tailscale.get("Foreground"):
        errors.append("tailscale_extra_exposure")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("proxy_config", type=Path)
    parser.add_argument("compose_file", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    errors = verify(args.manifest, args.proxy_config, args.compose_file, live=args.live)
    if errors:
        print("NAS ingress gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
