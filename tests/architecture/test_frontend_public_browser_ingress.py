from __future__ import annotations

import importlib.util
import shutil
import stat
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "ops/nas/proxy-public-browser.example.caddy"
CLOUDFLARED_TEMPLATE = ROOT / "ops/nas/frontend-cloudflared-config.example.yml"
RENDERER = ROOT / "ops/nas/render-frontend-cloudflared-config.py"
PUBLIC_COMPOSE = ROOT / "ops/nas/compose.public-browser.example.yml"
TUNNEL_ID = "12345678-1234-5678-9234-567812345678"
PRODUCTION_HOSTNAME = "pa.bobby-fetting.me"


def _module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _service_block(compose: str, service: str) -> str:
    lines = compose.splitlines()
    try:
        services_start = lines.index("services:")
    except ValueError:
        return ""
    services_end = next(
        (
            index
            for index in range(services_start + 1, len(lines))
            if lines[index] and not lines[index].startswith(" ")
        ),
        len(lines),
    )
    marker = f"  {service}:"
    try:
        service_start = lines.index(marker, services_start + 1, services_end)
    except ValueError:
        return ""
    service_end = next(
        (
            index
            for index in range(service_start + 1, services_end)
            if lines[index].startswith("  ")
            and not lines[index].startswith("    ")
            and lines[index].strip()
            and not lines[index].lstrip().startswith("#")
        ),
        services_end,
    )
    return "\n".join(lines[service_start:service_end])


def test_public_browser_caddyfile_is_browser_only() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    assert "pa.bobby-fetting.me" in text
    assert "not host pa.bobby-fetting.me" in text
    for refused in ("/v1/*", "/remote/*", "/apple/*", "/mcp"):
        assert refused in text
    assert "/mcp/*" in text
    assert 'Strict-Transport-Security "max-age=31536000"' in text
    assert "includeSubDomains" not in text
    assert "preload" not in text
    assert "header_up -Cf-Access-Jwt-Assertion" in text
    assert "header_up -X-Forwarded-Host" in text
    assert "reverse_proxy web:3000" in text
    assert "header_up -Cookie" not in text
    assert "Access-Control-Allow-Origin" not in text
    assert "This listener is NOT the Tailscale private proxy" in text


def test_frontend_cloudflared_template_is_hostname_only() -> None:
    text = CLOUDFLARED_TEMPLATE.read_text(encoding="utf-8")
    assert "http_status:404" in text
    assert "hostname: __FRONTEND_HOSTNAME__" in text
    assert "service: http://public-proxy:8080" in text
    assert text.count("__TUNNEL_ID__") == 1
    assert "mcp" not in text.lower()
    assert "*" not in text.split("ingress:", 1)[1]
    assert "gateway" not in text.lower()


def test_frontend_renderer_writes_production_hostname(tmp_path: Path) -> None:
    renderer = _module(RENDERER)
    output = tmp_path / "config.yml"
    renderer.render(
        CLOUDFLARED_TEMPLATE,
        output,
        tunnel_id=TUNNEL_ID,
        hostname=PRODUCTION_HOSTNAME,
    )
    text = output.read_text(encoding="utf-8")
    assert PRODUCTION_HOSTNAME in text
    assert "hostname: pa.bobby-fetting.me" in text
    assert "__" not in text
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    with pytest.raises(FileExistsError):
        renderer.render(
            CLOUDFLARED_TEMPLATE,
            output,
            tunnel_id=TUNNEL_ID,
            hostname=PRODUCTION_HOSTNAME,
        )


def test_frontend_renderer_rejects_invalid_hostname_like_mcp_renderer(
    tmp_path: Path,
) -> None:
    renderer = _module(RENDERER)
    with pytest.raises(ValueError, match="production FQDN"):
        renderer.render(
            CLOUDFLARED_TEMPLATE,
            tmp_path / "config.yml",
            tunnel_id=TUNNEL_ID,
            hostname="example.invalid",
        )


def test_caddyfile_validates_when_caddy_is_installed() -> None:
    caddy = shutil.which("caddy")
    if caddy is None:
        # CI delivery-config will use docker to run `caddy validate` when the
        # host binary is absent from this architecture-test environment.
        return
    completed = subprocess.run(  # noqa: S603
        [caddy, "validate", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_public_browser_compose_keeps_origin_unpublished_when_present() -> None:
    if not PUBLIC_COMPOSE.is_file():
        return
    text = PUBLIC_COMPOSE.read_text(encoding="utf-8")
    assert "data-plane" not in text
    cloudflared = _service_block(text, "frontend-cloudflared")
    assert cloudflared, "frontend-cloudflared service missing"
    assert not any(
        line.split("#", 1)[0].strip().startswith("ports:") for line in cloudflared.splitlines()
    )
    public_proxy = _service_block(text, "public-proxy")
    assert public_proxy, "public-proxy service missing"
    assert "0.0.0.0" not in public_proxy  # noqa: S104 - refuse published all-interfaces binds
