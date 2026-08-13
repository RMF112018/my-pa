"""Canonical PostgreSQL bootstrap remains two-phase, admitted, and temporary."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _module(name: str) -> ModuleType:
    path = ROOT / f"ops/nas/{name}.py"
    spec = importlib.util.spec_from_file_location(f"nas_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tools(tmp_path: Path) -> tuple[Path, Path]:
    tools = tmp_path / "bin"
    tools.mkdir()
    log = tmp_path / "calls"
    python = tools / "python3"
    python.write_text(
        f"#!/bin/sh\nprintf 'python %s\\n' \"$*\" >> {log}\nexit 0\n",
        encoding="utf-8",
    )
    docker = tools / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f"printf 'docker %s\\n' \"$*\" >> {log}\n"
        'case " $* " in\n'
        "  *' compose '*' ps -a -q postgres '*) "
        f"[ -f {tmp_path / 'created'} ] && echo postgres-id; exit 0;;\n"
        "  *' compose '*' create postgres '*) "
        f"touch {tmp_path / 'created'}; exit 0;;\n"
        "  *' compose '*' config '*) exit 0;;\n"
        "  *' compose '*' start postgres '*) exit 0;;\n"
        "  *' inspect --format {{.State.Running}} postgres-id '*) echo false; exit 0;;\n"
        "  *' inspect --format '*'State.Health'*' postgres-id '*) echo healthy; exit 0;;\n"
        "  *' exec -i postgres-id sh -eu -c '*) exit 0;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    docker.chmod(0o700)
    return tools, log


def _environment(tmp_path: Path, tools: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{tools}:/usr/bin:/bin",
        "MY_PA_NAS_DOCKER": str(tools / "docker"),
        "MY_PA_NAS_PYTHON": str(tools / "python3"),
        "MY_PA_NAS_COMPOSE_FILE": str(ROOT / "ops/nas/compose.example.yml"),
        "MY_PA_NAS_ROOT": str(tmp_path / "nas"),
        "MY_PA_LIFECYCLE_MODE": "smoke",
    }


def test_prepare_creates_and_captures_without_starting(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "nas/postgres/data").mkdir(parents=True)
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-prepare.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
            "1",
        ],
        cwd=ROOT,
        env=_environment(tmp_path, tools),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    assert "create postgres" in calls
    assert "ps -a -q postgres" in calls
    assert "generate-postgres-resources.py --container-id postgres-id" in calls
    assert "start postgres" not in calls and "up postgres" not in calls


def test_start_revalidates_before_start_and_checks_health(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "created").touch()
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-start.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
        ],
        cwd=ROOT,
        env=_environment(tmp_path, tools),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    first_gate = calls.index("postgres_gate.py")
    start = calls.index("start postgres")
    health = calls.index("State.Health")
    assert first_gate < start < health
    assert "alembic upgrade" not in calls


def test_bootstrap_contract_prohibits_ad_hoc_targets_and_orders_services() -> None:
    prepare = (ROOT / "ops/nas/postgres-bootstrap-prepare.sh").read_text(encoding="utf-8")
    start = (ROOT / "ops/nas/postgres-bootstrap-start.sh").read_text(encoding="utf-8")
    compose = (ROOT / "ops/nas/compose.example.yml").read_text(encoding="utf-8")
    assert "postgresql_default is prohibited" in prepare
    assert "docker compose" not in prepare + start  # only the canonical nas_compose wrapper
    assert "nas_compose up postgres" not in prepare + start
    assert "alembic" not in prepare + start
    assert compose.count("condition: service_healthy") == 3
    assert "name: my-pa-nas-contract_data-plane" in compose
    assert 'postgres --version | grep -Eq "PostgreSQL[)]? 17[.]10' in start


def test_runtime_admission_generator_binds_engine_renders_and_six_images(
    tmp_path: Path, monkeypatch: object
) -> None:
    generator = _module("generate-runtime-admission")
    ids = {
        "postgres": "sha256:" + "1" * 64,
        "app": "sha256:" + "2" * 64,
        "web": "sha256:" + "3" * 64,
        "proxy": "sha256:" + "4" * 64,
    }
    references = {
        "postgres": ids["postgres"],
        "gateway": ids["app"],
        "worker-enrollment": ids["app"],
        "worker-capture": ids["app"],
        "web": ids["web"],
        "proxy": "caddy@sha256:" + "5" * 64,
    }
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        'status = "deployable"\ndocker_engine_id = "engine"\ndocker_engine_name = "nas"\n'
        + "\n".join(
            f'[images.{name}]\ndocker_image_id = "{image_id}"' for name, image_id in ids.items()
        ),
        encoding="utf-8",
    )
    smoke = {"services": {name: {"image": value} for name, value in references.items()}}
    pilot = {**smoke, "pilot": True}
    monkeypatch.setattr(generator, "_render", lambda _compose, overlay: pilot if overlay else smoke)

    role_by_reference = {
        references["postgres"]: "postgres",
        references["gateway"]: "app",
        references["web"]: "web",
        references["proxy"]: "proxy",
    }

    def run(command: list[str]) -> str:
        if command[1] == "info":
            return '{"ID":"engine","Name":"nas"}'
        return '[{"Id":"' + ids[role_by_reference[command[-1]]] + '"}]'

    monkeypatch.setattr(generator, "_run", run)
    output = tmp_path / "runtime-admission.toml"
    assert generator.generate(tmp_path / "compose", tmp_path / "overlay", manifest, output) == []
    admitted = tomllib.loads(output.read_text(encoding="utf-8"))
    assert admitted["docker_engine_id"] == "engine"
    assert set(admitted["service_image_ids"]) == generator.SERVICES
    assert admitted["service_image_ids"]["gateway"] == ids["app"]
    assert output.stat().st_mode & 0o777 == 0o400
