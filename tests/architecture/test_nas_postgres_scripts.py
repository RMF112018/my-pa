"""Execute NAS-03 shell preflights with fake external commands."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
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


def test_receipt_recency_uses_portable_admitted_python(tmp_path: Path) -> None:
    def verify(created: datetime) -> subprocess.CompletedProcess[str]:
        dump = tmp_path / f"my-pa-{created:%Y%m%dT%H%M%SZ}.dump"
        dump.write_bytes(b"synthetic-backup")
        receipt = dump.with_suffix(".dump.sha256")
        digest = hashlib.sha256(dump.read_bytes()).hexdigest()
        receipt.write_text(f"{digest}  {dump.name}\n", encoding="utf-8")
        return subprocess.run(  # noqa: S603 - repository script under test
            [str(ROOT / "ops/nas/verify-backup-receipt.sh"), str(receipt)],
            env={
                **os.environ,
                "MY_PA_NAS_DOCKER": "/usr/bin/true",
                "MY_PA_NAS_PYTHON": sys.executable,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    assert verify(datetime.now(UTC) - timedelta(minutes=1)).returncode == 0
    stale = verify(datetime.now(UTC) - timedelta(days=2))
    assert stale.returncode != 0
    assert "not recent" in stale.stderr
