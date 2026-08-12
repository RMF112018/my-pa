"""Structural guardrails for the non-deploying NAS-01 runtime contract."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATHS = (
    "ops/nas/runtime-contract.toml",
    "ops/nas/compose.example.yml",
    "ops/nas/proxy-allowlist.example.caddy",
    "ops/nas/README.md",
    "ops/compose/README.md",
    "ops/compose/postgres.yml",
)
SERVICES = (
    "postgres",
    "gateway",
    "worker-enrollment",
    "worker-capture",
    "web",
    "proxy",
)


def _files() -> dict[str, str]:
    return {path: (ROOT / path).read_text(encoding="utf-8") for path in PATHS}


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^networks:\n|\Z)",
        compose,
    )
    return match.group(1) if match else ""


def _compose_mounts(block: str) -> set[tuple[str, str, bool]]:
    mounts: set[tuple[str, str, bool]] = set()
    for match in re.finditer(
        r"type:\s*bind,\s*source:\s*[\"']?([^,\"']+)[\"']?,\s*"
        r"target:\s*([^,}\s]+)(?:,\s*read_only:\s*(true|false))?",
        block,
        re.IGNORECASE,
    ):
        mounts.add((match.group(1), match.group(2), (match.group(3) or "false").lower() == "true"))
    multiline_pattern = re.compile(
        r"type:\s*bind\s*\n\s*source:\s*[\"']?([^\n\"']+)[\"']?\s*\n"
        r"\s*target:\s*([^\s]+)(?:\s*\n\s*read_only:\s*(true|false))?",
        re.IGNORECASE,
    )
    for multiline in multiline_pattern.finditer(block):
        mounts.add(
            (
                multiline.group(1),
                multiline.group(2),
                (multiline.group(3) or "false").lower() == "true",
            )
        )
    return mounts


def _compose_networks(block: str) -> set[str]:
    match = re.search(r"(?m)^    networks:\s*\[([^]]*)\]", block)
    return {item.strip() for item in match.group(1).split(",")} if match else set()


def _compose_volume_item_count(block: str) -> int:
    section = re.search(r"(?ms)^    volumes:\n(.*?)(?=^    [a-z_]+:|\Z)", block)
    return len(re.findall(r"(?m)^      -(?:[ \t]|$)", section.group(1))) if section else 0


def _has_noncanonical_read_only(block: str) -> bool:
    tokens = re.findall(r"read_only:\s*([^,}\s]+)", block)
    return len(tokens) != block.count("read_only:") or any(
        token.lower() not in {"true", "false"} for token in tokens
    )


def validate_nas_scaffold(files: Mapping[str, str]) -> set[str]:
    """Return stable violation codes for real files or deliberately mutated copies."""

    errors: set[str] = set()
    contract_text = files["ops/nas/runtime-contract.toml"]
    compose = files["ops/nas/compose.example.yml"]
    proxy = files["ops/nas/proxy-allowlist.example.caddy"]
    nas_readme = files["ops/nas/README.md"]
    local_readme = files["ops/compose/README.md"]
    local_compose = files["ops/compose/postgres.yml"]

    try:
        contract = tomllib.loads(contract_text)
    except tomllib.TOMLDecodeError:
        return {"contract_parse"}

    if contract.get("status") != "contract_only_not_deployable":
        errors.add("contract_status")
    if contract.get("canonical_host") != "nas":
        errors.add("canonical_host")
    if contract.get("target_platform", {}).get("planning_value") != "linux/amd64":
        errors.add("platform_contract")
    images = contract.get("images", {})
    if images.get("build_during_start") is not False:
        errors.add("implicit_build")
    if images.get("require_exact_digest") is not True:
        errors.add("exact_image_digest")
    network = contract.get("network", {})
    if (
        network.get("only_host_published_service") != "proxy"
        or network.get("postgres_published") is not False
    ):
        errors.add("postgres_published")
    if network.get("public_exposure") != "forbidden":
        errors.add("public_exposure")
    if network.get("pilot_https") != "tailscale_serve":
        errors.add("pilot_https")
    if (
        network.get("data_network") != "data-plane"
        or network.get("data_network_internal") is not True
        or network.get("edge_network") != "edge-plane"
        or network.get("edge_network_egress") != "firewall_allowlisted_entra_only"
        or network.get("egress_services") != ["gateway", "web"]
    ):
        errors.add("network_planes")
    if contract.get("auth", {}).get("pilot_web") != "entra":
        errors.add("pilot_auth")
    if (
        contract.get("restart", {}).get("pilot_after_nas_10_and_operator_activation")
        != "unless-stopped"
    ):
        errors.add("pilot_restart")
    services = contract.get("services", {})
    expected_mounts = {
        "postgres": ["postgres_data_rw"],
        "gateway": ["config_ro", "managed_documents_rw", "sources_ro"],
        "worker_enrollment": ["config_ro", "sources_ro", "goodnotes_ro"],
        "worker_capture": ["config_ro"],
        "web": [],
        "proxy": ["proxy_config_ro"],
    }
    if any(
        services.get(name, {}).get("mounts") != mounts for name, mounts in expected_mounts.items()
    ):
        errors.add("mount_ownership")
    expected_networks = {
        "postgres": ["data-plane"],
        "gateway": ["data-plane", "edge-plane"],
        "worker_enrollment": ["data-plane"],
        "worker_capture": ["data-plane"],
        "web": ["edge-plane"],
        "proxy": ["edge-plane"],
    }
    if any(
        services.get(name, {}).get("networks") != networks
        for name, networks in expected_networks.items()
    ):
        errors.add("network_planes")
    gateway = services.get("gateway", {})
    if (
        gateway.get("container_bind") != "0.0.0.0:8765"
        or gateway.get("bind_implementation_owned_by") != "NAS-04"
    ):
        errors.add("gateway_container_bind")
    web = services.get("web", {})
    if web.get("database_credential") is not False or web.get("mounts") != []:
        errors.add("web_authority")
    apple = services.get("apple_source_host", {})
    if (
        apple.get("host") != "mac"
        or apple.get("database_credential") is not False
        or apple.get("general_nas_filesystem_credential") is not False
        or apple.get("grant_issuer") != "nas_application"
        or apple.get("transport") != "outbound_poll"
    ):
        errors.add("apple_authority")
    remote = contract.get("ingress", {}).get("remote_capture", {})
    if remote != {
        "method": "POST",
        "path": "/remote/v1/capture.create",
        "upstream": "gateway",
        "auth": "ClientCredential",
        "capability": "capture.create",
        "principal_source": "credential",
        "caller_principal_forbidden": True,
    }:
        errors.add("remote_capture_contract")
    if (
        contract.get("ingress", {}).get("generic_capabilities", {}).get("exposure")
        != "internal_only"
    ):
        errors.add("generic_ingress")
    if contract.get("mcp", {}).get("transport") != "stdio_only":
        errors.add("mcp_transport")
    mounts = contract.get("mounts", {})
    if mounts.get("postgres_data_rw", {}).get("storage") != "nas_local":
        errors.add("postgres_storage")
    if any(
        mounts.get(name, {}).get("mode") != "read_only"
        for name in ("config_ro", "sources_ro", "goodnotes_ro")
    ):
        errors.add("read_only_mount_contract")

    if re.search(r"(?m)^\s*build:\s*", compose) or "up --build" in nas_readme:
        errors.add("implicit_build")
    if "/Volumes/" in compose:
        errors.add("host_volume_path")
    if any(re.search(r"source:\s*[\"']?/[\"']?(?:,|$)", line) for line in compose.splitlines()):
        errors.add("host_root_mount")
    if re.search(r"\$\{[^}\n]+:-", compose):
        errors.add("password_default")
    if "my_pa_pgdata" in compose:
        errors.add("named_postgres_volume")

    blocks = {service: _service_block(compose, service) for service in SERVICES}
    expected_compose_mounts = {
        "postgres": {
            (
                "${MY_PA_NAS_ROOT:?explicit NAS root required}/postgres/data",
                "/var/lib/postgresql/data",
                False,
            )
        },
        "gateway": {
            ("${MY_PA_NAS_ROOT:?}/config", "/srv/my-pa/config", True),
            (
                "${MY_PA_NAS_ROOT:?}/managed-documents",
                "/srv/my-pa/managed-documents",
                False,
            ),
            ("${MY_PA_NAS_ROOT:?}/sources", "/srv/my-pa/sources", True),
        },
        "worker-enrollment": {
            ("${MY_PA_NAS_ROOT:?}/config", "/srv/my-pa/config", True),
            ("${MY_PA_NAS_ROOT:?}/sources", "/srv/my-pa/sources", True),
            ("${MY_PA_NAS_ROOT:?}/goodnotes", "/srv/my-pa/goodnotes", True),
        },
        "worker-capture": {("${MY_PA_NAS_ROOT:?}/config", "/srv/my-pa/config", True)},
        "web": set(),
        "proxy": {("./proxy-allowlist.example.caddy", "/etc/caddy/Caddyfile", True)},
    }
    if any(
        _compose_mounts(blocks[name]) != mounts for name, mounts in expected_compose_mounts.items()
    ):
        errors.add("mount_ownership")
    if any(
        _compose_volume_item_count(blocks[name]) != len(_compose_mounts(blocks[name]))
        for name in SERVICES
    ):
        errors.add("mount_ownership")
    if any(_has_noncanonical_read_only(block) for block in blocks.values()):
        errors.add("mount_ownership")
    expected_compose_networks = {
        "postgres": {"data-plane"},
        "gateway": {"data-plane", "edge-plane"},
        "worker-enrollment": {"data-plane"},
        "worker-capture": {"data-plane"},
        "web": {"edge-plane"},
        "proxy": {"edge-plane"},
    }
    if any(
        _compose_networks(blocks[name]) != networks
        for name, networks in expected_compose_networks.items()
    ):
        errors.add("network_planes")
    if any(not block or "    platform: linux/amd64" not in block for block in blocks.values()):
        errors.add("missing_platform")
    if any("_DIGEST:?sha256 digest required}" not in block for block in blocks.values()):
        errors.add("exact_image_digest")
    if "    ports:" in blocks["postgres"] or "0.0.0.0" in blocks["postgres"]:  # noqa: S104
        errors.add("postgres_published")
    if any("    ports:" in blocks[name] for name in SERVICES if name != "proxy"):
        errors.add("non_proxy_published")
    if "127.0.0.1:" not in blocks["proxy"] or "0.0.0.0" in blocks["proxy"]:  # noqa: S104
        errors.add("public_proxy_bind")
    if "MY_PA_DATABASE_URL" in blocks["web"] or "    volumes:" in blocks["web"]:
        errors.add("web_authority")
    if "MYPA_GATEWAY_URL: http://gateway:8765" not in blocks["web"]:
        errors.add("web_gateway_contract")
    if (
        "MY_PA_GATEWAY_BIND_HOST: 0.0.0.0" not in blocks["gateway"]
        or "networks: [data-plane, edge-plane]" not in blocks["gateway"]
        or "networks: [edge-plane]" not in blocks["web"]
        or "networks: [data-plane]" not in blocks["postgres"]
        or "data-plane:\n    internal: true" not in compose
        or "edge-plane:\n    internal: false" not in compose
    ):
        errors.add("network_planes")
    if "managed-documents" in compose.replace(blocks["gateway"], ""):
        errors.add("mount_ownership")
    if "/postgres/data" in compose.replace(blocks["postgres"], ""):
        errors.add("mount_ownership")
    if any('    restart: "no"' not in block for block in blocks.values()):
        errors.add("restart_policy")
    for line in compose.splitlines():
        if (
            any(f'/{name}"' in line for name in ("config", "sources", "goodnotes"))
            and "read_only: true" not in line
        ):
            errors.add("writable_control_mount")

    exact = proxy.find("path /remote/v1/capture.create")
    exact_gateway = proxy.find("reverse_proxy gateway:8765", exact)
    remote_deny = proxy.find("path /remote/*")
    generic_deny = proxy.find("path /v1/*")
    apple_deny = proxy.find("path /apple/*")
    web_fallback = proxy.find("reverse_proxy web:3000")
    if (
        exact < 0
        or exact_gateway < exact
        or "method POST" not in proxy[:exact]
        or exact_gateway > remote_deny
    ):
        errors.add("remote_capture_route")
    generic_block = proxy[generic_deny:remote_deny] if generic_deny >= 0 else ""
    if 'respond "not found" 404' not in generic_block:
        errors.add("generic_ingress")
    if not (0 <= remote_deny < web_fallback) or not (0 <= apple_deny < web_fallback):
        errors.add("machine_route_fallthrough")
    if web_fallback < 0 or proxy.count("reverse_proxy web:3000") != 1:
        errors.add("browser_route")

    if "Local development only" not in local_readme or "NAS pilot" not in local_readme:
        errors.add("local_non_pilot_label")
    if "local-development" not in local_compose or "not the NAS pilot" not in local_compose:
        errors.add("local_non_pilot_label")
    return errors


def test_real_nas_scaffold_is_fail_closed() -> None:
    assert validate_nas_scaffold(_files()) == set()


def _replace(files: dict[str, str], path: str, old: str, new: str) -> dict[str, str]:
    assert old in files[path]
    files[path] = files[path].replace(old, new, 1)
    return files


@pytest.mark.parametrize(
    ("path", "old", "new", "expected"),
    (
        (
            "ops/nas/compose.example.yml",
            "${MY_PA_NAS_ROOT:?explicit NAS root required}",
            "/Volumes/my-pa",
            "host_volume_path",
        ),
        (
            "ops/nas/compose.example.yml",
            'source: "${MY_PA_NAS_ROOT:?explicit NAS root required}/postgres/data"',
            'source: "/"',
            "host_root_mount",
        ),
        (
            "ops/nas/compose.example.yml",
            "    networks: [data-plane]\n\n  gateway:",
            '    ports: ["0.0.0.0:5432:5432"]\n    networks: [data-plane]\n\n  gateway:',
            "postgres_published",
        ),
        (
            "ops/nas/compose.example.yml",
            'POSTGRES_PASSWORD: "${MY_PA_DB_PASSWORD:?database password required}"',
            'POSTGRES_PASSWORD: "${MY_PA_DB_PASSWORD:-unsafe}"',
            "password_default",
        ),
        (
            "ops/nas/compose.example.yml",
            "    platform: linux/amd64",
            "",
            "missing_platform",
        ),
        (
            "ops/nas/compose.example.yml",
            "${MY_PA_APP_IMAGE_DIGEST:?sha256 digest required}",
            "latest",
            "exact_image_digest",
        ),
        (
            "ops/nas/compose.example.yml",
            "networks: [data-plane, edge-plane]",
            "networks: [data-plane]",
            "network_planes",
        ),
        (
            "ops/nas/compose.example.yml",
            "    networks: [data-plane]\n\n  web:",
            "    networks: [data-plane, edge-plane]\n\n  web:",
            "network_planes",
        ),
        (
            "ops/nas/compose.example.yml",
            "edge-plane:\n    internal: false",
            "edge-plane:\n    internal: true",
            "network_planes",
        ),
        (
            "ops/nas/compose.example.yml",
            "127.0.0.1:${MY_PA_PROXY_PORT:?explicit smoke port required}:8080",
            "0.0.0.0:${MY_PA_PROXY_PORT:?explicit smoke port required}:8080",
            "public_proxy_bind",
        ),
        (
            "ops/nas/compose.example.yml",
            '    restart: "no"',
            "    restart: unless-stopped",
            "restart_policy",
        ),
        (
            "ops/nas/compose.example.yml",
            "      MYPA_GATEWAY_URL: http://gateway:8765",
            "      MY_PA_DATABASE_URL: postgresql://web@postgres/my_pa",
            "web_authority",
        ),
        (
            "ops/nas/compose.example.yml",
            'source: "${MY_PA_NAS_ROOT:?}/sources", target: /srv/my-pa/sources, read_only: true',
            'source: "${MY_PA_NAS_ROOT:?}/sources", target: /srv/my-pa/sources',
            "writable_control_mount",
        ),
        (
            "ops/nas/compose.example.yml",
            'source: "${MY_PA_NAS_ROOT:?}/managed-documents", target: /srv/my-pa/managed-documents',
            'source: "${MY_PA_NAS_ROOT:?}/backups", target: /srv/my-pa/managed-documents',
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            'source: "${MY_PA_NAS_ROOT:?explicit NAS root required}/postgres/data"',
            'source: "${MY_PA_NAS_ROOT:?explicit NAS root required}/backups"',
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "      - type: bind\n"
            "        source: ./proxy-allowlist.example.caddy\n"
            "        target: /srv/my-pa/extra\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "        read_only:\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "        read_only: yes\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            '        read_only: "true"\n'
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "        read_only: True\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "      -\n"
            "        type: volume\n"
            "        source: unexpected_data\n"
            "        target: /srv/my-pa/extra\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "      - ./proxy-allowlist.example.caddy:/srv/my-pa/extra:ro\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "      - type: volume\n"
            "        source: unexpected\n"
            "        target: /srv/my-pa/extra\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "        read_only: true\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            'source: "./proxy-allowlist.example.caddy", target: /etc/caddy/Caddyfile',
            'source: "${MY_PA_NAS_ROOT:?}/sources", target: /etc/caddy/Caddyfile',
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "    networks: [data-plane]\n\n  worker-capture:",
            "    volumes:\n"
            '      - {type: bind, source: "${MY_PA_NAS_ROOT:?}/managed-documents", '
            "target: /srv/my-pa/managed-documents}\n"
            "    networks: [data-plane]\n\n  worker-capture:",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            'source: "${MY_PA_NAS_ROOT:?}/config", target: /srv/my-pa/config, '
            "read_only: true}\n    networks: [data-plane]\n\n  web:",
            'source: "${MY_PA_NAS_ROOT:?}/config", target: /srv/my-pa/config, read_only: true}\n'
            '      - {type: bind, source: "${MY_PA_NAS_ROOT:?}/sources", '
            "target: /srv/my-pa/sources, read_only: true}\n"
            "    networks: [data-plane]\n\n  web:",
            "mount_ownership",
        ),
        (
            "ops/nas/runtime-contract.toml",
            'pilot_web = "entra"',
            'pilot_web = "synthetic"',
            "pilot_auth",
        ),
        (
            "ops/nas/runtime-contract.toml",
            'pilot_https = "tailscale_serve"',
            'pilot_https = "public_http"',
            "pilot_https",
        ),
        (
            "ops/nas/runtime-contract.toml",
            'pilot_after_nas_10_and_operator_activation = "unless-stopped"',
            'pilot_after_nas_10_and_operator_activation = "always"',
            "pilot_restart",
        ),
        (
            "ops/nas/runtime-contract.toml",
            'storage = "nas_local"',
            'storage = "network_share"',
            "postgres_storage",
        ),
        (
            "ops/nas/runtime-contract.toml",
            '[mounts.sources_ro]\nclass = "sources"\nmode = "read_only"',
            '[mounts.sources_ro]\nclass = "sources"\nmode = "read_write"',
            "read_only_mount_contract",
        ),
        (
            "ops/nas/runtime-contract.toml",
            "require_exact_digest = true",
            "require_exact_digest = false",
            "exact_image_digest",
        ),
        (
            "ops/nas/runtime-contract.toml",
            'mounts = ["config_ro", "managed_documents_rw", "sources_ro"]',
            'mounts = ["config_ro", "sources_ro"]',
            "mount_ownership",
        ),
        (
            "ops/nas/runtime-contract.toml",
            'networks = ["data-plane"]',
            'networks = ["data-plane", "edge-plane"]',
            "network_planes",
        ),
        (
            "ops/nas/proxy-allowlist.example.caddy",
            "reverse_proxy gateway:8765",
            "reverse_proxy web:3000",
            "remote_capture_route",
        ),
        (
            "ops/nas/proxy-allowlist.example.caddy",
            '@internal_capabilities {\n        respond "not found" 404',
            "@internal_capabilities {\n        reverse_proxy gateway:8765",
            "generic_ingress",
        ),
        (
            "ops/nas/proxy-allowlist.example.caddy",
            "@unmatched_remote path /remote/*",
            "@unmatched_remote path /unused/*",
            "machine_route_fallthrough",
        ),
        (
            "ops/nas/README.md",
            "NAS-02 images",
            "NAS-02 images and normal start up --build",
            "implicit_build",
        ),
        (
            "ops/compose/README.md",
            "Local development only",
            "Compose definitions",
            "local_non_pilot_label",
        ),
    ),
)
def test_planted_violation_is_detected(path: str, old: str, new: str, expected: str) -> None:
    assert expected in validate_nas_scaffold(_replace(_files(), path, old, new))
