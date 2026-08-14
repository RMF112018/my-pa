"""Behavioral contracts for the bounded Synology data-plane firewall gate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops/nas/synology-data-plane-firewall.sh"
NETWORK_ID = "d4d93b25" + "6" * 56
BRIDGE = "docker-d4d93b25"
SUBNET = "172.22.0.0/16"


def _environment(
    tmp_path: Path, *, wrong_network: bool = False, missing_docker_accept: bool = False
) -> tuple[dict[str, str], Path, Path]:
    tools = tmp_path / "bin"
    tools.mkdir()
    state = tmp_path / "rule-present"
    calls = tmp_path / "iptables-calls"
    docker = tools / "docker"
    project = "other-project" if wrong_network else "my-pa-nas-contract"
    docker.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        "  *' network inspect --format '*' my-pa-nas-contract_data-plane '*)\n"
        f"    printf '%s\\n' '{NETWORK_ID}|my-pa-nas-contract_data-plane|bridge|local|true|"
        f"{project}|data-plane|{SUBNET}' ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    ip = tools / "ip"
    ip.write_text(
        f'#!/bin/sh\n[ "$*" = "link show dev {BRIDGE}" ]\n',
        encoding="utf-8",
    )
    iptables = tools / "iptables"
    docker_accept = "exit 1" if missing_docker_accept else "exit 0"
    iptables.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{calls}'\n"
        'case "$*" in\n'
        "  '-S') printf '%s\\n' '-A FORWARD -j FORWARD_FIREWALL' "
        "'-A FORWARD -j DEFAULT_FORWARD' ;;\n"
        f"  '-C DEFAULT_FORWARD -i {BRIDGE} -o {BRIDGE} -j ACCEPT') {docker_accept} ;;\n"
        f"  '-C FORWARD_FIREWALL -i {BRIDGE} -o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN') "
        f"[ -f '{state}' ] ;;\n"
        f"  '-I FORWARD_FIREWALL 1 -i {BRIDGE} -o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN') "
        f": > '{state}' ;;\n"
        f"  '-D FORWARD_FIREWALL -i {BRIDGE} -o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN') "
        f"rm -f '{state}' ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_id = tools / "id"
    fake_id.write_text('#!/bin/sh\n[ "$1" = -u ] && echo 0\n', encoding="utf-8")
    for path in (docker, ip, iptables, fake_id):
        path.chmod(0o700)
    return (
        {
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_DOCKER": str(docker),
            "MY_PA_NAS_IPTABLES": str(iptables),
            "MY_PA_NAS_IP": str(ip),
        },
        state,
        calls,
    )


def _run(action: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - checked-in script with synthetic tools
        [str(SCRIPT), action],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_plan_is_read_only_and_check_fails_when_rule_is_missing(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    planned = _run("plan", environment)
    assert planned.returncode == 0
    assert "requires admission" in planned.stdout
    assert not state.exists()
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert "rule is missing" in checked.stderr
    assert "-I FORWARD_FIREWALL" not in calls.read_text(encoding="utf-8")


def test_mutation_requires_exact_confirmation(tmp_path: Path) -> None:
    environment, state, _calls = _environment(tmp_path)
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "MY_PA_CONFIRM_FIREWALL_MUTATION" in result.stderr
    assert not state.exists()


def test_apply_check_idempotence_and_exact_remove(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    assert _run("apply", environment).returncode == 0
    assert state.exists()
    assert _run("check", environment).returncode == 0
    assert _run("apply", environment).returncode == 0
    assert calls.read_text(encoding="utf-8").count("-I FORWARD_FIREWALL") == 1
    assert _run("remove", environment).returncode == 0
    assert not state.exists()
    assert _run("check", environment).returncode != 0


@pytest.mark.parametrize(
    ("wrong_network", "missing_docker_accept", "expected"),
    [
        (True, False, "network identity mismatch"),
        (False, True, "same-bridge ACCEPT rule is unavailable"),
    ],
)
def test_apply_refuses_unproven_network_or_docker_forwarding(
    tmp_path: Path, wrong_network: bool, missing_docker_accept: bool, expected: str
) -> None:
    environment, state, calls = _environment(
        tmp_path,
        wrong_network=wrong_network,
        missing_docker_accept=missing_docker_accept,
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert expected in result.stderr
    assert not state.exists()
    assert not calls.exists() or "-I FORWARD_FIREWALL" not in calls.read_text(encoding="utf-8")


def test_database_and_runtime_paths_require_the_firewall_gate() -> None:
    for relative in (
        "ops/nas/postgres-common.sh",
        "ops/nas/start.sh",
        "ops/nas/restart.sh",
        "ops/nas/health.sh",
    ):
        assert '"$script_dir/synology-data-plane-firewall.sh" check' in (ROOT / relative).read_text(
            encoding="utf-8"
        )
