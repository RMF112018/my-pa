"""Execute NAS-03 shell preflights with fake external commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _fake_bin(tmp_path: Path) -> tuple[Path, Path]:
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands.log"
    docker = binary / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{log}'\n"
        'case "$*" in\n'
        "  *'compose' *'ps -q postgres'*) echo pg-id;;\n"
        "  *'compose' *'run --rm --no-deps -e MY_PA_DATABASE_URL='*) exit 0;;\n"
        "  *'compose' *'run --rm --no-deps gateway python -m alembic heads'*) echo b4e8d2c7a613;;\n"
        "  *'inspect pg-id'*) echo '[{\"Mounts\":[]}]';;\n"
        '  *\'info --format\'*) echo \'{"ID":"nas","NCPU":4,"MemTotal":1024}\';;\n'
        "  *'exec -i pg-id sh -eu -c'*) exit 0;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return binary, log


def _restore_env(tmp_path: Path, binary: Path) -> dict[str, str]:
    resources = tmp_path / "resources.toml"
    resources.write_text("invalid = true\n", encoding="utf-8")
    return {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "MY_PA_NAS_COMPOSE_FILE": str(tmp_path / "compose.yml"),
        "MY_PA_POSTGRES_RESOURCES": str(resources),
        "MY_PA_EXPECTED_ALEMBIC_HEAD": "b4e8d2c7a613",
    }


def test_restore_bad_url_refuses_before_any_createdb(tmp_path: Path) -> None:
    binary, log = _fake_bin(tmp_path)
    dump = tmp_path / "input.dump"
    dump.write_bytes(b"dump")
    env = _restore_env(tmp_path, binary)
    env["MY_PA_SCRATCH_DATABASE_URL"] = (
        "postgresql+psycopg://my_pa@postgres:1/my_pa_scratch_test?host=other"
    )
    completed = subprocess.run(  # noqa: S603 - repository script under test
        [str(ROOT / "ops/nas/restore-to-scratch.sh"), str(dump), "my_pa_scratch_test"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert not log.exists() or "createdb" not in log.read_text(encoding="utf-8")


def test_restore_symlink_refuses_before_any_docker_command(tmp_path: Path) -> None:
    binary, log = _fake_bin(tmp_path)
    target = tmp_path / "target.dump"
    target.write_bytes(b"dump")
    linked = tmp_path / "linked.dump"
    linked.symlink_to(target)
    env = _restore_env(tmp_path, binary)
    env["MY_PA_SCRATCH_DATABASE_URL"] = (
        "postgresql+psycopg://my_pa@postgres:5432/my_pa_scratch_test"
    )
    completed = subprocess.run(  # noqa: S603 - repository script under test
        [str(ROOT / "ops/nas/restore-to-scratch.sh"), str(linked), "my_pa_scratch_test"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert not log.exists()


def test_receipt_rejects_multi_entry_before_checksum_reads(tmp_path: Path) -> None:
    dump = tmp_path / "my-pa-20260812T120000Z.dump"
    dump.write_bytes(b"dump")
    receipt = tmp_path / "my-pa-20260812T120000Z.dump.sha256"
    receipt.write_text("0" * 64 + "  " + dump.name + "\n" + "1" * 64 + "  /etc/passwd\n")
    completed = subprocess.run(  # noqa: S603 - repository script under test
        [str(ROOT / "ops/nas/verify-backup-receipt.sh"), str(receipt)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "exactly one dump" in completed.stderr
