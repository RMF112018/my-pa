"""WP29 production env, delivery-config, and rollback dry-run contracts."""

from __future__ import annotations

import importlib.util
import shutil
import stat
import subprocess
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
NAS = ROOT / "ops" / "nas"
ROLLBACK = NAS / "rollback.sh"
EXAMPLE_MANIFEST = NAS / "deployment-manifest.example.toml"


def _module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_example_env_validates() -> None:
    env = _module(NAS / "validate-production-env.py")
    errors = env.validate_paths(
        NAS / "production-environment.example.env",
        NAS / "production-environment.schema.toml",
    )
    assert errors == []


def test_production_env_refuses_synthetic_and_http_origin(tmp_path: Path) -> None:
    env = _module(NAS / "validate-production-env.py")
    schema = env.load_schema(NAS / "production-environment.schema.toml")
    values = env.load_env(NAS / "production-environment.example.env")
    values["MYPA_AUTH_MODE"] = "synthetic"
    values["MYPA_CANONICAL_ORIGIN"] = "http://pa.bobby-fetting.me"
    values["MYPA_SESSION_SERVICE_URL"] = "http://session:9000"
    values["MYPA_SESSION_SERVICE_SECRET"] = "short"  # noqa: S105 - planted too-short secret
    values["MYPA_SESSION_SECRET"] = "x" * 32
    values["NEXT_PUBLIC_MSAL_CLIENT_ID"] = "browser-msal"
    errors = env.validate_env(values, schema)
    assert "production_auth_not_passkey" in errors
    assert "forbidden_web_auth_mode" in errors
    assert "canonical_origin_mismatch" in errors
    assert "canonical_origin_not_https" in errors
    assert "session_service_url_set" in errors
    assert "secret_too_short:MYPA_SESSION_SERVICE_SECRET" in errors
    assert "forbidden_browser_var:MYPA_SESSION_SECRET" in errors
    assert "forbidden_browser_var:NEXT_PUBLIC_MSAL_CLIENT_ID" in errors
    assert "unknown_variable:NEXT_PUBLIC_MSAL_CLIENT_ID" in errors


def test_production_env_refuses_host_published_postgres(tmp_path: Path) -> None:
    env = _module(NAS / "validate-production-env.py")
    compose = (NAS / "compose.example.yml").read_text(encoding="utf-8")
    planted = compose.replace(
        "    networks: [data-plane]\n",
        '    ports:\n      - "0.0.0.0:5432:5432"\n    networks: [data-plane]\n',
        1,
    )
    errors = env.check_compose_unpublished(planted)
    assert "postgres_host_published" in errors
    assert "postgres_all_interfaces_bind" in errors


def test_delivery_config_passes_checked_in_contract() -> None:
    gate = _module(NAS / "validate-delivery-config.py")
    assert gate.validate(ROOT) == []


def test_delivery_config_refuses_synthetic_example(tmp_path: Path) -> None:
    gate = _module(NAS / "validate-delivery-config.py")
    cloned = tmp_path / "repo"
    cloned.mkdir()
    nas = cloned / "ops" / "nas"
    nas.mkdir(parents=True)
    for name in (
        "validate-production-env.py",
        "production-environment.schema.toml",
        "production-environment.example.env",
        "compose.example.yml",
        "compose.public-browser.example.yml",
        "proxy-public-browser.example.caddy",
    ):
        shutil.copy(NAS / name, nas / name)
    env_file = nas / "production-environment.example.env"
    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace(
            "MYPA_AUTH_MODE=passkey",
            "MYPA_AUTH_MODE=synthetic",
        ),
        encoding="utf-8",
    )
    errors = gate.validate(cloned)
    assert "production_auth_not_passkey" in errors or "example_env_synthetic" in errors


def test_rollback_dry_run_prints_image_ids(tmp_path: Path) -> None:
    manifest = tmp_path / "previous.toml"
    manifest.write_text(
        EXAMPLE_MANIFEST.read_text(encoding="utf-8")
        .replace("REQUIRED_LOADED_APP_CONFIG_ID", "a" * 64)
        .replace("REQUIRED_LOADED_WEB_CONFIG_ID", "b" * 64)
        .replace("REQUIRED_CADDY_DIGEST", "c" * 64)
        .replace(
            "cloudflare/cloudflared:REQUIRED_TAG@sha256:REQUIRED_DIGEST",
            "cloudflare/cloudflared:2026.7.3@sha256:" + ("d" * 64),
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(  # noqa: S603
        [str(ROLLBACK), "--dry-run", str(manifest)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "app_image_id=sha256:" + ("a" * 64) in completed.stdout
    assert "web_image_id=sha256:" + ("b" * 64) in completed.stdout
    assert "docker build" in completed.stdout
    assert "PRODUCTION_ACTIVATION_NOT_PERFORMED" in completed.stdout


def test_rollback_refuses_latest_and_missing_and_build(tmp_path: Path) -> None:
    missing = subprocess.run(  # noqa: S603
        [str(ROLLBACK), "--dry-run", str(tmp_path / "gone.toml")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 1
    assert "previous manifest missing" in missing.stderr

    latest = tmp_path / "latest.toml"
    latest.write_text(
        EXAMPLE_MANIFEST.read_text(encoding="utf-8")
        .replace("REQUIRED_LOADED_APP_CONFIG_ID", "a" * 64)
        .replace("REQUIRED_LOADED_WEB_CONFIG_ID", "b" * 64)
        .replace("REQUIRED_CADDY_DIGEST", "c" * 64)
        .replace(
            "cloudflare/cloudflared:REQUIRED_TAG@sha256:REQUIRED_DIGEST",
            "cloudflare/cloudflared:latest",
        ),
        encoding="utf-8",
    )
    tagged = subprocess.run(  # noqa: S603
        [str(ROLLBACK), "--dry-run", str(latest)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert tagged.returncode == 1
    assert "latest tag forbidden" in tagged.stderr

    good = tmp_path / "good.toml"
    good.write_text(
        EXAMPLE_MANIFEST.read_text(encoding="utf-8")
        .replace("REQUIRED_LOADED_APP_CONFIG_ID", "a" * 64)
        .replace("REQUIRED_LOADED_WEB_CONFIG_ID", "b" * 64)
        .replace("REQUIRED_CADDY_DIGEST", "c" * 64)
        .replace(
            "cloudflare/cloudflared:REQUIRED_TAG@sha256:REQUIRED_DIGEST",
            "cloudflare/cloudflared:2026.7.3@sha256:" + ("d" * 64),
        ),
        encoding="utf-8",
    )
    built = subprocess.run(  # noqa: S603
        [str(ROLLBACK), "--dry-run", "--build", str(good)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 1
    assert "docker build is forbidden" in built.stderr

    live = subprocess.run(  # noqa: S603
        [str(ROLLBACK), str(good)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert live.returncode == 1
    assert "live rollback is operator-gated" in live.stderr


def test_rollback_script_is_executable() -> None:
    assert ROLLBACK.is_file()
    assert stat.S_IXUSR & ROLLBACK.stat().st_mode
