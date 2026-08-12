"""Structural guardrails for the non-deploying NAS-01 runtime contract."""

from __future__ import annotations

import json
import re
import subprocess
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


def _parse_compose(compose: str) -> dict[str, object] | None:
    ruby = """
source = STDIN.read
doc = Psych.parse_stream(source)
raise 'multiple YAML documents' unless doc.children.length == 1
walk = lambda do |node|
  if node.is_a?(Psych::Nodes::Mapping)
    keys = node.children.each_slice(2).map do |key, _value|
      raise 'non-scalar mapping key' unless key.is_a?(Psych::Nodes::Scalar)
      key.value
    end
    raise 'duplicate mapping key' unless keys.uniq.length == keys.length
  end
  children = node.respond_to?(:children) ? node.children : nil
  children.each { |child| walk.call(child) } if children
end
walk.call(doc)
print JSON.generate(YAML.safe_load(source, aliases: true))
"""
    result = subprocess.run(  # noqa: S603 - fixed executable and program
        [
            "/usr/bin/ruby",
            "-rjson",
            "-ryaml",
            "-e",
            ruby,
        ],
        input=compose,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, dict) else None


def validate_nas_scaffold(files: Mapping[str, str]) -> set[str]:
    """Return stable violation codes for real files or deliberately mutated copies."""

    errors: set[str] = set()
    contract_text = files["ops/nas/runtime-contract.toml"]
    compose = files["ops/nas/compose.example.yml"]
    proxy = files["ops/nas/proxy-allowlist.example.caddy"]
    nas_readme = files["ops/nas/README.md"]
    local_readme = files["ops/compose/README.md"]
    local_compose = files["ops/compose/postgres.yml"]
    compose_model = _parse_compose(compose)
    if compose_model is None:
        return {"compose_parse"}
    if set(compose_model) != {"name", "services", "networks"}:
        errors.add("top_level_contract")
    if compose_model.get("name") != "my-pa-nas-contract":
        errors.add("top_level_contract")

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
    compose_services = compose_model.get("services", {})
    if not isinstance(compose_services, dict):
        return {"compose_parse"}
    if set(compose_services) != set(SERVICES):
        errors.add("service_set")
    app_image = (
        "${MY_PA_APP_IMAGE:?repository required}@${MY_PA_APP_IMAGE_DIGEST:?sha256 digest required}"
    )
    expected_images = {
        "postgres": "${MY_PA_POSTGRES_IMAGE:?repository required}@"
        "${MY_PA_POSTGRES_IMAGE_DIGEST:?sha256 digest required}",
        "gateway": app_image,
        "worker-enrollment": app_image,
        "worker-capture": app_image,
        "web": "${MY_PA_WEB_IMAGE:?repository required}@"
        "${MY_PA_WEB_IMAGE_DIGEST:?sha256 digest required}",
        "proxy": "${MY_PA_PROXY_IMAGE:?repository required}@"
        "${MY_PA_PROXY_IMAGE_DIGEST:?sha256 digest required}",
    }
    expected_env_files = {
        "postgres": None,
        "gateway": ["${MY_PA_NAS_ENV_FILE:?owner-only NAS env file required}"],
        "worker-enrollment": ["${MY_PA_NAS_ENV_FILE:?}"],
        "worker-capture": ["${MY_PA_NAS_ENV_FILE:?}"],
        "web": None,
        "proxy": None,
    }
    expected_environments = {
        "postgres": {
            "POSTGRES_DB": "my_pa",
            "POSTGRES_USER": "my_pa",
            "POSTGRES_PASSWORD": "${MY_PA_DB_PASSWORD:?database password required}",
        },
        "gateway": {"MY_PA_GATEWAY_BIND_HOST": "0.0.0.0"},  # noqa: S104
        "worker-enrollment": None,
        "worker-capture": None,
        "web": {
            "NODE_ENV": "production",
            "MYPA_GATEWAY_URL": "http://gateway:8765",
            "MYPA_GATEWAY_AUTH_MODE": "entra",
            "MYPA_SESSION_SECRET": "${MYPA_SESSION_SECRET:?session secret required}",
        },
        "proxy": None,
    }
    expected_commands = {
        "postgres": None,
        "gateway": ["python", "apps/gateway.py", "run"],
        "worker-enrollment": ["python", "apps/worker.py", "run", "--plane", "enrollment"],
        "worker-capture": ["python", "apps/worker.py", "run", "--plane", "capture"],
        "web": ["npm", "run", "start"],
        "proxy": None,
    }
    service_user = "${MY_PA_UID:?}:${MY_PA_GID:?}"
    expected_users = {
        "postgres": None,
        "gateway": "${MY_PA_UID:?dedicated service uid required}:"
        "${MY_PA_GID:?dedicated service gid required}",
        "worker-enrollment": service_user,
        "worker-capture": service_user,
        "web": service_user,
        "proxy": None,
    }
    expected_expose = {
        "postgres": None,
        "gateway": ["8765"],
        "worker-enrollment": None,
        "worker-capture": None,
        "web": ["3000"],
        "proxy": None,
    }
    expected_service_keys = {
        "postgres": {
            "profiles",
            "image",
            "platform",
            "restart",
            "environment",
            "volumes",
            "networks",
        },
        "gateway": {
            "profiles",
            "image",
            "platform",
            "user",
            "restart",
            "command",
            "environment",
            "env_file",
            "expose",
            "volumes",
            "networks",
        },
        "worker-enrollment": {
            "profiles",
            "image",
            "platform",
            "user",
            "restart",
            "command",
            "env_file",
            "volumes",
            "networks",
        },
        "worker-capture": {
            "profiles",
            "image",
            "platform",
            "user",
            "restart",
            "command",
            "env_file",
            "volumes",
            "networks",
        },
        "web": {
            "profiles",
            "image",
            "platform",
            "user",
            "restart",
            "command",
            "environment",
            "expose",
            "networks",
        },
        "proxy": {"profiles", "image", "platform", "restart", "ports", "volumes", "networks"},
    }
    for name in SERVICES:
        service = compose_services.get(name, {})
        if not isinstance(service, dict):
            errors.add("service_contract")
            continue
        if set(service) != expected_service_keys[name]:
            errors.add("service_contract")
        if service.get("platform") != "linux/amd64":
            errors.add("missing_platform")
        if service.get("restart") != "no":
            errors.add("restart_policy")
        if service.get("image") != expected_images[name]:
            errors.add("exact_image_digest")
        if service.get("profiles") != ["nas-01-contract-only"]:
            errors.add("contract_profile")
        if service.get("env_file") != expected_env_files[name]:
            errors.add("credential_authority")
        if service.get("environment") != expected_environments[name]:
            errors.add("environment_contract")
        if service.get("command") != expected_commands[name]:
            errors.add("process_placement")
        if service.get("user") != expected_users[name]:
            errors.add("service_identity")
        if service.get("expose") != expected_expose[name]:
            errors.add("internal_port_contract")
        if "build" in service:
            errors.add("implicit_build")
        expected_ports = (
            ["127.0.0.1:${MY_PA_PROXY_PORT:?explicit smoke port required}:8080"]
            if name == "proxy"
            else None
        )
        if service.get("ports") != expected_ports:
            errors.add("host_publication")
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
    actual_compose_mounts: dict[str, set[tuple[str, str, bool]]] = {}
    mount_model_valid = True
    for name in SERVICES:
        service = compose_services.get(name, {})
        volumes = service.get("volumes", []) if isinstance(service, dict) else None
        normalized: set[tuple[str, str, bool]] = set()
        if not isinstance(volumes, list):
            mount_model_valid = False
            continue
        for volume in volumes:
            expected_keys = {"type", "source", "target"}
            if isinstance(volume, dict) and "read_only" in volume:
                expected_keys.add("read_only")
            if (
                not isinstance(volume, dict)
                or volume.get("type") != "bind"
                or not isinstance(volume.get("source"), str)
                or not isinstance(volume.get("target"), str)
                or not isinstance(volume.get("read_only", False), bool)
                or set(volume) != expected_keys
            ):
                mount_model_valid = False
                continue
            normalized.add((volume["source"], volume["target"], volume.get("read_only", False)))
        if len(normalized) != len(volumes):
            mount_model_valid = False
        actual_compose_mounts[name] = normalized
    if not mount_model_valid or any(
        actual_compose_mounts.get(name) != mounts
        for name, mounts in expected_compose_mounts.items()
    ):
        errors.add("mount_ownership")
    expected_compose_networks = {
        "postgres": {"data-plane"},
        "gateway": {"data-plane", "edge-plane"},
        "worker-enrollment": {"data-plane"},
        "worker-capture": {"data-plane"},
        "web": {"edge-plane"},
        "proxy": {"edge-plane"},
    }
    actual_compose_networks = {
        name: set(compose_services.get(name, {}).get("networks", []))
        for name in SERVICES
        if isinstance(compose_services.get(name), dict)
        and isinstance(compose_services.get(name, {}).get("networks"), list)
    }
    if any(
        actual_compose_networks.get(name) != networks
        for name, networks in expected_compose_networks.items()
    ):
        errors.add("network_planes")
    if compose_model.get("networks") != {
        "data-plane": {"internal": True},
        "edge-plane": {"internal": False},
    }:
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


def test_yaml_comments_do_not_change_mount_semantics() -> None:
    files = _files()
    files["ops/nas/compose.example.yml"] += "\n# read_only behavior is model-validated\n"
    assert validate_nas_scaffold(files) == set()


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
            "\nnetworks:\n",
            "\n  sidecar:\n"
            "    image: example.invalid/sidecar@sha256:deadbeef\n"
            "    platform: linux/amd64\n"
            '    ports: ["0.0.0.0:9999:9999"]\n'
            "    networks: [edge-plane]\n"
            "\nnetworks:\n",
            "service_set",
        ),
        (
            "ops/nas/compose.example.yml",
            '    expose: ["8765"]\n',
            '    expose: ["8765"]\n    ports : ["0.0.0.0:8765:8765"]\n',
            "host_publication",
        ),
        (
            "ops/nas/compose.example.yml",
            '    expose: ["8765"]\n',
            '    expose: ["8765"]\n    privileged: true\n',
            "service_contract",
        ),
        (
            "ops/nas/compose.example.yml",
            '    env_file: ["${MY_PA_NAS_ENV_FILE:?owner-only NAS env file required}"]\n',
            "    environment:\n      MY_PA_GATEWAY_BIND_HOST: 127.0.0.1\n"
            '    env_file: ["${MY_PA_NAS_ENV_FILE:?owner-only NAS env file required}"]\n',
            "compose_parse",
        ),
        (
            "ops/nas/compose.example.yml",
            "command: [python, apps/gateway.py, run]",
            "command: [python, apps/worker.py, run, --plane, capture]",
            "process_placement",
        ),
        (
            "ops/nas/compose.example.yml",
            "command: [python, apps/worker.py, run, --plane, enrollment]",
            "command: [python, apps/worker.py, run, --plane, capture]",
            "process_placement",
        ),
        (
            "ops/nas/compose.example.yml",
            '    expose: ["3000"]\n',
            '    expose: ["3000"]\n'
            '    env_file: ["${MY_PA_NAS_ENV_FILE:?owner-only NAS env file required}"]\n',
            "credential_authority",
        ),
        (
            "ops/nas/compose.example.yml",
            '    expose: ["3000"]\n',
            "    environment:\n"
            "      NODE_ENV: production\n"
            "      MYPA_GATEWAY_URL: http://wrong:9999\n"
            "      MYPA_GATEWAY_AUTH_MODE: local_operator\n"
            '      MYPA_SESSION_SECRET: "${MYPA_SESSION_SECRET:?session secret required}"\n'
            '    expose: ["3000"]\n',
            "compose_parse",
        ),
        (
            "ops/nas/compose.example.yml",
            "edge-plane:\n    internal: false",
            "edge-plane:\n    internal: false\n  edge-plane:\n    internal: true",
            "compose_parse",
        ),
        (
            "ops/nas/compose.example.yml",
            "data-plane:\n    internal: true",
            "data-plane:\n    internal: true\n  data-plane:\n    internal: false",
            "compose_parse",
        ),
        (
            "ops/nas/compose.example.yml",
            "\nnetworks:\n",
            "\nvolumes: {unexpected: {}}\nnetworks:\n",
            "top_level_contract",
        ),
        (
            "ops/nas/compose.example.yml",
            "name: my-pa-nas-contract",
            "name: wrong-stack",
            "top_level_contract",
        ),
        (
            "ops/nas/compose.example.yml",
            "name: my-pa-nas-contract",
            "name: my-pa-nas-contract\n---\nname: other",
            "compose_parse",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "        bind: {propagation: rshared}\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            '    expose: ["8765"]\n',
            '    expose: ["8765"]\n    expose: ["9999"]\n',
            "compose_parse",
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
            "        &ro read_only: true\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "        !!str read_only: true\n"
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            '        "read_only": true\n'
            "    networks: [data-plane]",
            "mount_ownership",
        ),
        (
            "ops/nas/compose.example.yml",
            "        target: /var/lib/postgresql/data\n    networks: [data-plane]",
            "        target: /var/lib/postgresql/data\n"
            "        read_only : true\n"
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
            "compose_parse",
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
