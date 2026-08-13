"""NAS-08 GoodNotes placement and Frontier stdio-only contract tests."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "ops/nas/source-contract.toml"
COMPOSE = ROOT / "ops/nas/compose.sources.example.yml"
RUNTIME_COMPOSE = ROOT / "ops/nas/compose.example.yml"
CHILD = ROOT / "ops/nas/frontier-mcp-child.example.json"
PROXY = ROOT / "ops/nas/proxy-allowlist.example.caddy"


def _gate_module() -> ModuleType:
    path = ROOT / "ops/nas/source_gate.py"
    spec = importlib.util.spec_from_file_location("nas_source_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify(
    tmp_path: Path,
    *,
    contract: str | None = None,
    compose: str | None = None,
    runtime_compose: str | None = None,
    child: str | None = None,
    proxy: str | None = None,
) -> list[str]:
    contract_path = tmp_path / "source-contract.toml"
    compose_path = tmp_path / "compose.sources.yml"
    runtime_compose_path = tmp_path / "compose.yml"
    child_path = tmp_path / "frontier.json"
    proxy_path = tmp_path / "Caddyfile"
    contract_path.write_text(
        CONTRACT.read_text(encoding="utf-8") if contract is None else contract,
        encoding="utf-8",
    )
    compose_path.write_text(
        COMPOSE.read_text(encoding="utf-8") if compose is None else compose,
        encoding="utf-8",
    )
    runtime_compose_path.write_text(
        RUNTIME_COMPOSE.read_text(encoding="utf-8") if runtime_compose is None else runtime_compose,
        encoding="utf-8",
    )
    child_path.write_text(
        CHILD.read_text(encoding="utf-8") if child is None else child,
        encoding="utf-8",
    )
    proxy_path.write_text(
        PROXY.read_text(encoding="utf-8") if proxy is None else proxy,
        encoding="utf-8",
    )
    return _gate_module().verify(
        contract_path, compose_path, runtime_compose_path, child_path, proxy_path
    )


def test_checked_in_nas_source_contract_is_exact_and_inert(tmp_path: Path) -> None:
    assert _verify(tmp_path) == []


def test_source_overlay_cannot_override_base_network_topology(tmp_path: Path) -> None:
    compose = (
        COMPOSE.read_text(encoding="utf-8") + "\nnetworks:\n  data-plane:\n    internal: false\n"
    )
    assert "overlay_topology" in _verify(tmp_path, compose=compose)


@pytest.mark.parametrize(
    ("mutation", "violation"),
    [
        (
            lambda text: text.replace('manifest = "goodnotes-manifest.json"', 'manifest = "../x"'),
            "goodnotes_manifest",
        ),
        (
            lambda text: text.replace(
                'ocr_executable = "/srv/my-pa/goodnotes-ocr/ocr"',
                'ocr_executable = "/usr/local/bin/ocr"',
            ),
            "goodnotes_ocr",
        ),
    ],
)
def test_source_contract_rejects_escape_from_read_only_roots(
    tmp_path: Path, mutation: Callable[[str], str], violation: str
) -> None:
    errors = _verify(tmp_path, contract=mutation(CONTRACT.read_text(encoding="utf-8")))
    assert violation in errors


def test_goodnotes_mount_must_be_read_only_and_exclusive(tmp_path: Path) -> None:
    compose = COMPOSE.read_text(encoding="utf-8").replace(
        "target: /srv/my-pa/goodnotes, read_only: true",
        "target: /srv/my-pa/goodnotes, read_only: false",
    )
    assert "goodnotes_mount" in _verify(tmp_path, compose=compose)

    base = RUNTIME_COMPOSE.read_text(encoding="utf-8")
    assert base.count("/srv/my-pa/goodnotes") == 0
    assert COMPOSE.read_text(encoding="utf-8").count("target: /srv/my-pa/goodnotes, ") == 1

    contaminated = base.replace(
        "    networks: [data-plane]\n\n  worker-capture:",
        "    volumes:\n"
        '      - {type: bind, source: "${MY_PA_NAS_ROOT:?}/goodnotes", '
        "target: /srv/my-pa/goodnotes, read_only: true}\n"
        "    networks: [data-plane]\n\n  worker-capture:",
    )
    assert "goodnotes_mount_owner" in _verify(tmp_path, runtime_compose=contaminated)

    shared_ocr = base.replace(
        "    networks: [data-plane]\n\n  worker-capture:",
        "    volumes:\n"
        '      - {type: bind, source: "${MY_PA_NAS_ROOT:?}/goodnotes-ocr", '
        "target: /srv/my-pa/goodnotes-ocr, read_only: true}\n"
        "    networks: [data-plane]\n\n  worker-capture:",
    )
    assert "goodnotes_mount_owner" in _verify(tmp_path, runtime_compose=shared_ocr)

    short_form = base.replace(
        "    networks: [data-plane]\n\n  worker-capture:",
        "    volumes:\n"
        '      - "${MY_PA_NAS_ROOT:?}/goodnotes:/srv/my-pa/goodnotes:ro"\n'
        "    networks: [data-plane]\n\n  worker-capture:",
    )
    assert "goodnotes_mount_owner" in _verify(tmp_path, runtime_compose=short_form)

    parent_mount = base.replace(
        "    networks: [data-plane]\n\n  worker-capture:",
        "    volumes:\n"
        '      - {type: bind, source: "${MY_PA_NAS_ROOT:?}", '
        "target: /srv/my-pa, read_only: true}\n"
        "    networks: [data-plane]\n\n  worker-capture:",
    )
    assert "goodnotes_mount_owner" in _verify(tmp_path, runtime_compose=parent_mount)

    inherited = base.replace(
        "    networks: [data-plane]\n\n  worker-capture:",
        "    volumes_from: [goodnotes-reconcile]\n    networks: [data-plane]\n\n  worker-capture:",
    )
    assert "goodnotes_mount_owner" in _verify(tmp_path, runtime_compose=inherited)

    aliased_source = base.replace(
        "    networks: [data-plane]\n\n  worker-capture:",
        "    volumes:\n"
        '      - {type: bind, source: "${MY_PA_NAS_ROOT:?}/goodnotes/../goodnotes/", '
        "target: /mnt/alias, read_only: true}\n"
        "    networks: [data-plane]\n\n  worker-capture:",
    )
    assert "goodnotes_mount_owner" in _verify(tmp_path, runtime_compose=aliased_source)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace("      - --idempotency-key\n", ""),
        lambda text: text.replace('    restart: "no"\n', '    restart: "always"\n', 1),
        lambda text: text.replace("    networks: [data-plane]\n", "    network_mode: host\n", 1),
    ],
)
def test_goodnotes_one_shot_lifecycle_is_exact(
    tmp_path: Path, mutation: Callable[[str], str]
) -> None:
    assert "goodnotes_composition" in _verify(
        tmp_path, compose=mutation(COMPOSE.read_text(encoding="utf-8"))
    )


def test_frontier_mcp_cannot_become_a_network_service(tmp_path: Path) -> None:
    compose = COMPOSE.read_text(encoding="utf-8").replace(
        "    stdin_open: true\n", '    stdin_open: true\n    ports: ["127.0.0.1:9999:9999"]\n'
    )
    assert "frontier_stdio" in _verify(tmp_path, compose=compose)

    prefix, separator, suffix = COMPOSE.read_text(encoding="utf-8").rpartition(
        "    networks: [data-plane]\n"
    )
    assert separator
    host_network = prefix + "    network_mode: host\n" + suffix
    assert "frontier_stdio" in _verify(tmp_path, compose=host_network)

    extra_network = prefix + "    networks: [data-plane, ingress-plane]\n" + suffix
    assert "frontier_stdio" in _verify(tmp_path, compose=extra_network)

    oauth_environment = COMPOSE.read_text(encoding="utf-8").replace(
        "      MY_PA_AUTH_MODE: local_operator\n",
        "      MY_PA_AUTH_MODE: local_operator\n      MY_PA_OAUTH_TOKEN: forbidden\n",
    )
    assert "frontier_stdio" in _verify(tmp_path, compose=oauth_environment)

    root_user = COMPOSE.read_text(encoding="utf-8").replace(
        '    user: "${MY_PA_UID:?dedicated service uid required}:'
        '${MY_PA_GID:?dedicated service gid required}"\n',
        '    user: "0:0"\n',
        2,
    )
    assert "frontier_stdio" in _verify(tmp_path, compose=root_user)

    proxy = PROXY.read_text(encoding="utf-8")
    assert "frontier-mcp" not in proxy
    assert "oauth" not in COMPOSE.read_text(encoding="utf-8").lower()
    assert "browser" not in COMPOSE.read_text(encoding="utf-8").lower()
    assert "frontier_proxy" in _verify(
        tmp_path, proxy=proxy + "\nhandle /mcp { reverse_proxy frontier-mcp }\n"
    )


def test_frontier_launch_is_an_exact_client_child_process(tmp_path: Path) -> None:
    document = json.loads(CHILD.read_text(encoding="utf-8"))
    document["mcpServers"]["my-pa"]["args"][-1] = "gateway"
    errors = _verify(tmp_path, child=json.dumps(document))
    assert "frontier_child" in errors
