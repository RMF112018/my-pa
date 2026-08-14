"""NAS-03 PostgreSQL storage and recovery controls fail closed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _gate() -> ModuleType:
    path = ROOT / "ops/nas/postgres_gate.py"
    spec = importlib.util.spec_from_file_location("nas_postgres_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_compose_is_unpublished_durable_and_untuned_until_measured() -> None:
    compose = (ROOT / "ops/nas/compose.example.yml").read_text()
    postgres = compose.split("  gateway:", 1)[0]
    assert 'POSTGRES_PASSWORD: "${MY_PA_DB_PASSWORD:?' in postgres
    assert 'POSTGRES_INITDB_ARGS: "--data-checksums --locale=C.UTF-8 --encoding=UTF8"' in postgres
    assert "target: /var/lib/postgresql/data" in postgres
    assert "stop_grace_period: 60s" in postgres
    assert "pg_isready -U my_pa -d my_pa" in postgres
    assert "ports:" not in postgres
    assert "shared_buffers=" not in postgres and "shm_size:" not in postgres


def test_resource_example_and_network_filesystem_refuse(tmp_path: Path) -> None:
    gate = _gate()
    assert "status_not_verified" in gate.verify(ROOT / "ops/nas/postgres-resources.example.toml")
    manifest = tmp_path / "resources.toml"
    manifest.write_text(
        'schema = "my-pa.nas-postgres-resources.v1"\nstatus = "verified"\n'
        'docker_engine_id = "nas"\npostgres_container_id = "pg"\n'
        'postgres_image_id = "sha256:image"\n'
        'data_network = "my-pa-nas-contract_data-plane"\n'
        'measured_at = "2026-08-12T12:00:00Z"\n'
        "logical_cpus = 4\nmemory_bytes = 1024\nminimum_available_storage_bytes = 1\n"
        'filesystem_type = "nfs"\npostgres_data_path = "/srv/my-pa/postgres/data"\n'
        '[tuning]\nstatus = "no_numeric_tuning"\n',
        encoding="utf-8",
    )
    assert "network_filesystem" in gate.verify(manifest)


def test_live_gate_binds_engine_resources_and_canonical_path(tmp_path: Path) -> None:
    gate = _gate()
    manifest = tmp_path / "resources.toml"
    manifest.write_text(
        'schema = "my-pa.nas-postgres-resources.v1"\nstatus = "verified"\n'
        'docker_engine_id = "nas"\npostgres_container_id = "pg"\n'
        'postgres_image_id = "sha256:image"\n'
        'data_network = "my-pa-nas-contract_data-plane"\n'
        'measured_at = "2026-08-12T12:00:00Z"\n'
        "logical_cpus = 4\nmemory_bytes = 1024\nminimum_available_storage_bytes = 1\n"
        f'filesystem_type = "btrfs"\npostgres_data_path = "{tmp_path}"\n'
        '[tuning]\nstatus = "no_numeric_tuning"\n',
        encoding="utf-8",
    )

    def runner(command: list[str]) -> str:
        if command[0] == "df":
            return (
                "Filesystem Type 1024-blocks Used Available Capacity Mounted on\n"
                "/dev/x btrfs 1 0 1 0% /\n"
            )
        if command[1] == "network":
            return (
                '[{"Name":"my-pa-nas-contract_data-plane","Internal":true,'
                '"Labels":{"com.docker.compose.project":"my-pa-nas-contract",'
                '"com.docker.compose.network":"data-plane"},'
                '"Containers":{"pg":{}}}]'
            )
        if command[1] == "inspect":
            return (
                '[{"Image":"sha256:image","Config":{"Labels":{'
                '"com.docker.compose.project":"my-pa-nas-contract",'
                '"com.docker.compose.service":"postgres"}},'
                '"State":{"Running":true},'
                '"HostConfig":{"PortBindings":{}},'
                '"NetworkSettings":{"Networks":{"my-pa-nas-contract_data-plane":{}}},'
                '"Mounts":[{"Type":"bind","Source":"'
                + str(tmp_path)
                + '","Destination":"/var/lib/postgresql/data","RW":true}]}]'
            )
        return '{"ID":"nas","NCPU":4,"MemTotal":1024}'

    assert gate.verify(manifest, live=True, container_id="pg", runner=runner) == []

    def stopped_runner(command: list[str]) -> str:
        value = runner(command)
        if command[1] == "network":
            return value.replace('"Containers":{"pg":{}}', '"Containers":{}')
        if command[1] == "inspect":
            return value.replace('"Running":true', '"Running":false')
        return value

    assert gate.verify(manifest, live=True, container_id="pg", runner=stopped_runner) == []

    def unattached_running(command: list[str]) -> str:
        value = runner(command)
        if command[1] == "network":
            return value.replace('"Containers":{"pg":{}}', '"Containers":{}')
        return value

    assert "data_network_postgres_attachment" in gate.verify(
        manifest, live=True, container_id="pg", runner=unattached_running
    )

    missing = object()
    for invalid_state in (missing, None, "true", 0, 1):

        def invalid_state_runner(command: list[str], *, state: object = invalid_state) -> str:
            value = runner(command)
            if command[1] == "network":
                return value.replace('"Containers":{"pg":{}}', '"Containers":{}')
            if command[1] == "inspect":
                parsed = json.loads(value)
                if state is missing:
                    del parsed[0]["State"]["Running"]
                else:
                    parsed[0]["State"]["Running"] = state
                return json.dumps(parsed)
            return value

        assert "postgres_running_state" in gate.verify(
            manifest, live=True, container_id="pg", runner=invalid_state_runner
        )

    insufficient = tmp_path / "insufficient.toml"
    insufficient.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "minimum_available_storage_bytes = 1",
            "minimum_available_storage_bytes = 999999999999999999999999",
        ),
        encoding="utf-8",
    )
    assert "insufficient_free_storage" in gate.verify(
        insufficient, live=True, container_id="pg", runner=runner
    )

    def wrong(command: list[str]) -> str:
        if command[0] == "df":
            return (
                "Filesystem Type 1024-blocks Used Available Capacity Mounted on\n"
                "/dev/x nfs 1 0 1 0% /\n"
            )
        if command[1] == "network":
            return "[]"
        if command[1] == "inspect":
            return "[]"
        return '{"ID":"other","NCPU":8,"MemTotal":2048}'

    errors = gate.verify(manifest, live=True, container_id="wrong", runner=wrong)
    assert {
        "docker_engine_identity",
        "resource_drift",
        "live_filesystem_type",
        "postgres_bind_mount",
        "postgres_compose_identity",
        "postgres_image_identity",
        "postgres_network_identity",
        "data_network_identity",
    } <= set(errors)


def test_lifecycle_wrappers_are_explicit_and_scratch_only() -> None:
    migrate = (ROOT / "ops/nas/migrate.sh").read_text()
    backup = (ROOT / "ops/nas/backup.sh").read_text()
    restore = (ROOT / "ops/nas/restore-to-scratch.sh").read_text()
    assert "alembic upgrade head" in migrate and "VERIFIED_BACKUP_RECEIPT" in migrate
    assert "Alembic head mismatch or multiple heads" in migrate
    assert "apps/cli/health.py" in migrate
    assert "alembic downgrade" not in migrate
    assert "--format custom" in backup and "--compress=zstd:9" in backup
    assert "pg_restore --list" in backup and "umask 077" in backup
    assert "my_pa_scratch_" in restore and "already exists" in restore
    assert "^my_pa_scratch_[A-Za-z0-9_]+$" in restore
    assert "scratch revision mismatch" in restore and "scratch extensions mismatch" in restore
    assert "apps/cli/health.py" in restore
    assert "retained for diagnosis" in restore
