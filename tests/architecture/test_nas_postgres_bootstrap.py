"""Canonical PostgreSQL bootstrap remains two-phase, admitted, and temporary."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace

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
        "#!/bin/sh\n"
        f"printf 'python %s\\n' \"$*\" >> {log}\n"
        f"gate_count={tmp_path / 'gate-count'}\n"
        'case "$*" in\n'
        "  *postgres_gate.py*)\n"
        '    count=$(cat "$gate_count" 2>/dev/null || echo 0)\n'
        "    count=$((count + 1))\n"
        '    echo "$count" > "$gate_count"\n'
        '    [ "${MY_TEST_MODE:-}" = fail_second_gate ] && '
        '[ "$count" -eq 2 ] && exit 1;;\n'
        "  *generate-postgres-resources.py*)\n"
        '    case "${MY_TEST_MODE:-}" in fail_resources|fail_container_rm|'
        "fail_network_rm) exit 1;; esac;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    container_id = "a" * 64
    network_id = "b" * 64
    docker = tools / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f"printf 'docker %s\\n' \"$*\" >> {log}\n"
        'case " $* " in\n'
        "  *' compose '*' ps -a -q postgres '*) "
        f"[ -f {tmp_path / 'created'} ] && "
        '[ "${MY_TEST_MODE:-}" != fail_capture ] && '
        f"echo {container_id}; exit 0;;\n"
        "  *' compose '*' create postgres '*) "
        '[ "${MY_TEST_MODE:-}" = oneoff_collision ] && '
        f"touch {tmp_path / 'oneoff'} || touch {tmp_path / 'created'}; exit 0;;\n"
        "  *' compose '*' config '*) exit 0;;\n"
        "  *' compose '*' start postgres '*) exit 0;;\n"
        f"  *' stop --time 60 {container_id} '*) "
        '[ "${MY_TEST_MODE:-}" = fail_stop ] && exit 1; exit 0;;\n'
        f"  *' container rm {container_id} '*) "
        '[ "${MY_TEST_MODE:-}" = fail_container_rm ] && exit 1; '
        f"rm -f {tmp_path / 'created'}; exit 0;;\n"
        "  *' ps -a --no-trunc '*'com.docker.compose.project=my-pa-nas-contract'*"
        "'com.docker.compose.service=postgres'*' --format {{.ID}} '*) "
        f"[ -f {tmp_path / 'created'} ] && echo {container_id}; exit 0;;\n"
        f"  *' inspect --format {{{{.State.Running}}}} {container_id} '*) "
        '[ "${MY_TEST_MODE:-}" = fail_stop ] && echo true || echo false; exit 0;;\n'
        f"  *' inspect --format '*'State.Health'*' {container_id} '*) echo healthy; exit 0;;\n"
        f"  *' inspect --format '*'com.docker.compose.project'*' {container_id} '*) "
        "echo my-pa-nas-contract; exit 0;;\n"
        f"  *' inspect --format '*'com.docker.compose.service'*' {container_id} '*) "
        "echo postgres; exit 0;;\n"
        f"  *' inspect --format '*'com.docker.compose.oneoff'*' {container_id} '*) "
        "echo False; exit 0;;\n"
        f"  *' inspect --format '*'com.docker.compose.container-number'*' {container_id} '*) "
        "echo 1; exit 0;;\n"
        f"  *' inspect --format {{{{.Image}}}} {container_id} '*) "
        f"echo sha256:{'1' * 64}; exit 0;;\n"
        "  *' network inspect --format {{.Id}} my-pa-nas-contract_data-plane '*) "
        f"echo {network_id}; exit 0;;\n"
        "  *' network inspect --format '*'com.docker.compose.project'*' "
        f"{network_id} '*) echo my-pa-nas-contract; exit 0;;\n"
        "  *' network inspect --format '*'com.docker.compose.network'*' "
        f"{network_id} '*) echo data-plane; exit 0;;\n"
        "  *' network inspect --format {{.Internal}} "
        f"{network_id} '*) echo true; exit 0;;\n"
        "  *' network inspect --format {{len .Containers}} "
        f"{network_id} '*) "
        f"[ -f {tmp_path / 'oneoff'} ] && echo 1 || echo 0; exit 0;;\n"
        f"  *' network rm {network_id} '*) "
        '[ "${MY_TEST_MODE:-}" = fail_network_rm ] && exit 1; exit 0;;\n'
        f"  *' exec -i {container_id} sh -eu -c '*) "
        'case "${MY_TEST_MODE:-}" in fail_version|fail_stop) exit 1;; esac; exit 0;;\n'
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
        "MY_PA_POSTGRES_IMAGE_ID": "sha256:" + "1" * 64,
        "MY_PA_DB_PASSWORD": "synthetic-test-only",
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
    assert f"generate-postgres-resources.py --container-id {'a' * 64}" in calls
    assert "start postgres" not in calls and "up postgres" not in calls


def test_resource_admission_accepts_synology_stopped_network_state(
    tmp_path: Path, monkeypatch: object
) -> None:
    generator = _module("generate-postgres-resources")
    container_id = "a" * 64

    def run(command: list[str]) -> str:
        if command[0] == "df":
            return (
                "Filesystem Type 1024-blocks Used Available Capacity Mounted on\n"
                "/dev/x btrfs 1 0 1 0% /\n"
            )
        if command[1] == "info":
            return '{"ID":"nas","NCPU":4,"MemTotal":1024}'
        if command[1] == "inspect":
            return json.dumps(
                [
                    {
                        "Image": "sha256:image",
                        "State": {"Running": False},
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": "my-pa-nas-contract",
                                "com.docker.compose.service": "postgres",
                            }
                        },
                        "HostConfig": {"PortBindings": {}},
                        "NetworkSettings": {"Networks": {"my-pa-nas-contract_data-plane": {}}},
                        "Mounts": [
                            {
                                "Type": "bind",
                                "Source": str(tmp_path),
                                "Destination": "/var/lib/postgresql/data",
                                "RW": True,
                            }
                        ],
                    }
                ]
            )
        if command[1:3] == ["network", "inspect"]:
            return json.dumps(
                [
                    {
                        "Name": "my-pa-nas-contract_data-plane",
                        "Internal": True,
                        "Labels": {
                            "com.docker.compose.project": "my-pa-nas-contract",
                            "com.docker.compose.network": "data-plane",
                        },
                        "Containers": {},
                    }
                ]
            )
        raise AssertionError(command)

    monkeypatch.setattr(generator, "_run", run)
    output = tmp_path / "resources.toml"
    assert generator.generate(container_id, tmp_path, 1, output) == []
    assert f'postgres_container_id = "{container_id}"' in output.read_text(encoding="utf-8")


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


def test_start_stops_postgres_when_post_health_gate_fails(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "created").touch()
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "fail_second_gate"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-start.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    calls = log.read_text(encoding="utf-8")
    assert f"stop --time 60 {'a' * 64}" in calls
    assert "compose" not in calls[calls.index("stop --time 60") :]


def test_start_stops_postgres_when_version_check_fails(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "created").touch()
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "fail_version"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-start.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert f"stop --time 60 {'a' * 64}" in log.read_text(encoding="utf-8")


def test_prepare_cleans_exact_partial_identity_on_resource_failure(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "nas/postgres/data").mkdir(parents=True)
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "fail_resources"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-prepare.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
            "1",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    calls = log.read_text(encoding="utf-8")
    assert f"container rm {'a' * 64}" in calls
    assert f"network rm {'b' * 64}" in calls
    assert "rm --force --stop postgres" not in calls
    assert "network rm my-pa-nas-contract_data-plane" not in calls
    assert not (tmp_path / "created").exists()


def test_prepare_recovers_when_post_create_capture_is_empty(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "nas/postgres/data").mkdir(parents=True)
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "fail_capture"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-prepare.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
            "1",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    calls = log.read_text(encoding="utf-8")
    assert "ps -a --no-trunc" in calls
    assert f"container rm {'a' * 64}" in calls
    assert not (tmp_path / "created").exists()


def test_prepare_capture_gap_leaves_matching_oneoff_untouched(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "nas/postgres/data").mkdir(parents=True)
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "oneoff_collision"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-prepare.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
            "1",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    calls = log.read_text(encoding="utf-8")
    assert "label=com.docker.compose.oneoff=False" in calls
    assert "container rm" not in calls
    assert (tmp_path / "oneoff").exists()


def test_start_reports_exact_stop_failure_and_residual_running(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "created").touch()
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "fail_stop"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-start.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "failed to stop exact PostgreSQL container" in result.stderr
    assert "remains running" in result.stderr
    assert f"stop --time 60 {'a' * 64}" in log.read_text(encoding="utf-8")


def test_prepare_reports_exact_container_removal_failure(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "nas/postgres/data").mkdir(parents=True)
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "fail_container_rm"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-prepare.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
            "1",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "failed to remove exact partial PostgreSQL container" in result.stderr
    assert f"container rm {'a' * 64}" in log.read_text(encoding="utf-8")
    assert (tmp_path / "created").exists()


def test_prepare_reports_exact_network_removal_failure(tmp_path: Path) -> None:
    tools, log = _tools(tmp_path)
    (tmp_path / "nas/postgres/data").mkdir(parents=True)
    environment = _environment(tmp_path, tools)
    environment["MY_TEST_MODE"] = "fail_network_rm"
    result = subprocess.run(  # noqa: S603 - checked-in wrapper with synthetic tools
        [
            str(ROOT / "ops/nas/postgres-bootstrap-prepare.sh"),
            str(tmp_path / "manifest"),
            str(tmp_path),
            str(tmp_path / "resources.toml"),
            "1",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "failed to remove exact partial PostgreSQL network" in result.stderr
    assert f"network rm {'b' * 64}" in log.read_text(encoding="utf-8")


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


def test_postgres_bootstrap_is_independent_of_application_credentials() -> None:
    prepare = (ROOT / "ops/nas/postgres-bootstrap-prepare.sh").read_text(encoding="utf-8")
    start = (ROOT / "ops/nas/postgres-bootstrap-start.sh").read_text(encoding="utf-8")
    common = (ROOT / "ops/nas/postgres-bootstrap-common.sh").read_text(encoding="utf-8")
    assert "postgres-bootstrap-common.sh" in prepare + start
    assert "lifecycle-common.sh" not in prepare + start
    assert "runtime_identity_gate.py" not in prepare + start + common
    assert "postgres-bootstrap-identity-gate.py" in common
    assert "MY_PA_NAS_ENV_FILE=/dev/null" in common
    assert "MY_PA_WEB_ENV_FILE=/dev/null" in common


def test_bootstrap_admission_binds_only_selected_postgres_render(
    tmp_path: Path, monkeypatch: object
) -> None:
    generator = _module("generate-postgres-bootstrap-admission")
    image_id = "sha256:" + "1" * 64
    monkeypatch.setenv("MY_PA_POSTGRES_IMAGE_ID", image_id)
    monkeypatch.setenv("MY_PA_DB_PASSWORD", "synthetic-db-secret")
    monkeypatch.setenv("MY_PA_NAS_ROOT", "/volume1/my-pa")
    rendered = {
        "name": "my-pa-nas-contract",
        "services": {
            "postgres": {
                "image": image_id,
                "platform": "linux/amd64",
                "restart": "no",
                "environment": {
                    "POSTGRES_DB": "my_pa",
                    "POSTGRES_USER": "my_pa",
                    "POSTGRES_PASSWORD": "synthetic-db-secret",
                    "POSTGRES_INITDB_ARGS": ("--data-checksums --locale=C.UTF-8 --encoding=UTF8"),
                },
                "networks": {"data-plane": None},
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/volume1/my-pa/postgres/data",
                        "target": "/var/lib/postgresql/data",
                    }
                ],
            }
        },
        "networks": {
            "data-plane": {
                "name": "my-pa-nas-contract_data-plane",
                "internal": True,
                "external": False,
            }
        },
    }
    assert generator.render_errors(rendered, image_id=image_id, root="/volume1/my-pa") == []
    leaked = json.loads(json.dumps(rendered))
    leaked["services"]["postgres"]["labels"] = {"unsafe": generator.SENTINEL_IMAGE}
    assert "non_postgres_sentinel_leak" in generator.render_errors(
        leaked, image_id=image_id, root="/volume1/my-pa"
    )


def test_bootstrap_admission_contains_no_database_password(
    tmp_path: Path, monkeypatch: object
) -> None:
    generator = _module("generate-postgres-bootstrap-admission")
    image_id = "sha256:" + "1" * 64
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\nstatus = "deployable"\n'
        'repository_commit = "' + "a" * 40 + '"\n'
        'repository_tree = "' + "b" * 40 + '"\n'
        'docker_engine_id = "engine"\ndocker_engine_name = "nas"\n'
        f'[images.postgres]\ndocker_image_id = "{image_id}"\n'
        '[images.app]\ndocker_image_id = "sha256:' + "2" * 64 + '"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_PA_POSTGRES_IMAGE_ID", image_id)
    monkeypatch.setenv("MY_PA_DB_PASSWORD", "synthetic-db-secret")
    monkeypatch.setenv("MY_PA_NAS_ROOT", "/volume1/my-pa")
    rendered = {
        "name": "my-pa-nas-contract",
        "services": {
            "postgres": {
                "image": image_id,
                "platform": "linux/amd64",
                "restart": "no",
                "environment": {
                    "POSTGRES_DB": "my_pa",
                    "POSTGRES_USER": "my_pa",
                    "POSTGRES_PASSWORD": "synthetic-db-secret",
                    "POSTGRES_INITDB_ARGS": ("--data-checksums --locale=C.UTF-8 --encoding=UTF8"),
                },
                "networks": {"data-plane": None},
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/volume1/my-pa/postgres/data",
                        "target": "/var/lib/postgresql/data",
                    }
                ],
            }
        },
        "networks": {
            "data-plane": {
                "name": "my-pa-nas-contract_data-plane",
                "internal": True,
                "external": False,
            }
        },
    }
    monkeypatch.setattr(generator, "render_postgres", lambda _compose: rendered)
    monkeypatch.setattr(
        generator,
        "_run",
        lambda command, **_kwargs: (
            '{"ID":"engine","Name":"nas"}'
            if command[1] == "info"
            else json.dumps(
                [
                    {
                        "Id": command[-1],
                        "Os": "linux",
                        "Architecture": "amd64",
                    }
                ]
            )
        ),
    )
    output = tmp_path / "bootstrap-admission.toml"
    assert generator.generate(ROOT / "ops/nas/compose.example.yml", manifest, output) == []
    assert "synthetic-db-secret" not in output.read_text(encoding="utf-8")
    assert output.stat().st_mode & 0o777 == 0o400

    first_binding = tomllib.loads(output.read_text(encoding="utf-8"))["resolved_postgres_sha256"]
    monkeypatch.setenv("MY_PA_DB_PASSWORD", "different-synthetic-secret")
    alternate_secret = os.environ["MY_PA_DB_PASSWORD"]
    rendered["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"] = alternate_secret
    second_output = tmp_path / "second-bootstrap-admission.toml"
    assert generator.generate(ROOT / "ops/nas/compose.example.yml", manifest, second_output) == []
    second_binding = tomllib.loads(second_output.read_text(encoding="utf-8"))[
        "resolved_postgres_sha256"
    ]
    assert first_binding == second_binding


def test_database_operations_use_hardened_exact_image_operator() -> None:
    common = (ROOT / "ops/nas/postgres-common.sh").read_text(encoding="utf-8")
    migrate = (ROOT / "ops/nas/migrate.sh").read_text(encoding="utf-8")
    restore = (ROOT / "ops/nas/restore-to-scratch.sh").read_text(encoding="utf-8")
    assert "database_operator_image_id" in common
    assert "--network my-pa-nas-contract_data-plane" in common
    assert "--read-only" in common and "--cap-drop ALL" in common
    assert "--security-opt no-new-privileges" in common
    assert "--user 10001:10001" in common
    assert "--env PGPASSWORD" in common
    assert "database_operator python -m alembic upgrade head" in migrate
    assert "nas_compose run" not in migrate
    assert 'database_operator_with_url "$MY_PA_SCRATCH_DATABASE_URL"' in restore


def test_bootstrap_identity_gate_recomputes_every_binding(
    tmp_path: Path, monkeypatch: object
) -> None:
    gate = _module("postgres-bootstrap-identity-gate")
    postgres_id = "sha256:" + "1" * 64
    app_id = "sha256:" + "2" * 64
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        'repository_commit = "' + "a" * 40 + '"\n'
        'repository_tree = "' + "b" * 40 + '"\n'
        'docker_engine_id = "engine"\ndocker_engine_name = "nas"\n'
        f'[images.postgres]\ndocker_image_id = "{postgres_id}"\n'
        f'[images.app]\ndocker_image_id = "{app_id}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_PA_NAS_ROOT", "/volume1/my-pa")
    rendered = {"selected": "postgres"}
    fake_generator = SimpleNamespace(
        PROJECT="my-pa-nas-contract",
        SERVICE="postgres",
        NETWORK="my-pa-nas-contract_data-plane",
        render_postgres=lambda _compose: rendered,
        render_errors=lambda _rendered, **_kwargs: [],
        canonical_render=lambda value: json.dumps(value, sort_keys=True).encode(),
        binding_render=lambda value: value,
    )
    monkeypatch.setattr(gate, "_generator", lambda: fake_generator)

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[1] == "info":
            return SimpleNamespace(stdout='{"ID":"engine","Name":"nas"}')
        return SimpleNamespace(
            stdout=json.dumps(
                [
                    {"Id": postgres_id, "Os": "linux", "Architecture": "amd64"},
                    {"Id": app_id, "Os": "linux", "Architecture": "amd64"},
                ]
            )
        )

    monkeypatch.setattr(gate.subprocess, "run", run)
    manifest_bytes = manifest.read_bytes()
    compose = ROOT / "ops/nas/compose.example.yml"
    admission = tmp_path / "bootstrap-admission.toml"
    fields = {
        "schema": "my-pa.nas-postgres-bootstrap-admission.v1",
        "status": "admitted",
        "repository_commit": "a" * 40,
        "repository_tree": "b" * 40,
        "docker_engine_id": "engine",
        "docker_engine_name": "nas",
        "image_manifest_sha256": gate._sha256(manifest_bytes),
        "compose_sha256": gate._file_sha256(compose),
        "resolved_postgres_sha256": gate._sha256(fake_generator.canonical_render(rendered)),
        "postgres_image_id": postgres_id,
        "database_operator_image_id": app_id,
        "project_name": fake_generator.PROJECT,
        "service_name": fake_generator.SERVICE,
        "data_network": fake_generator.NETWORK,
        "postgres_data_path": "/volume1/my-pa/postgres/data",
    }
    admission.write_text(
        "\n".join(f"{key} = {json.dumps(value)}" for key, value in fields.items())
        + "\ndata_network_internal = true\n",
        encoding="utf-8",
    )
    admission.chmod(0o400)
    assert (
        gate.verify(
            compose,
            manifest,
            admission_path=admission,
            owner_uid=os.getuid(),
        )
        == []
    )
    admission.chmod(0o600)
    admission.write_text(
        admission.read_text(encoding="utf-8").replace(fields["resolved_postgres_sha256"], "0" * 64),
        encoding="utf-8",
    )
    admission.chmod(0o400)
    assert "bootstrap_admission_binding" in gate.verify(
        compose,
        manifest,
        admission_path=admission,
        owner_uid=os.getuid(),
    )


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
