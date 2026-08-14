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
    tmp_path: Path,
    *,
    wrong_network: bool = False,
    missing_docker_accept: bool = False,
    initial_rule_state: str = "missing",
    inserted_rule_state: str = "effective",
    root_uid: int = 0,
) -> tuple[dict[str, str], Path, Path]:
    tools = tmp_path / "bin"
    tools.mkdir()
    state = tmp_path / "rule-present"
    state.write_text(initial_rule_state, encoding="utf-8")
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
        "  '-S FORWARD_FIREWALL')\n"
        f"    value=$(cat '{state}')\n"
        '    case "$value" in\n'
        f"      effective) printf '%s\\n' '-A FORWARD_FIREWALL -i {BRIDGE} -o {BRIDGE} "
        f"-s {SUBNET} -d {SUBNET} -j RETURN' '-A FORWARD_FIREWALL -j DROP' ;;\n"
        f"      misordered) printf '%s\\n' '-A FORWARD_FIREWALL -j DROP' "
        f"'-A FORWARD_FIREWALL -i {BRIDGE} -o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN' ;;\n"
        f"      duplicate) printf '%s\\n' '-A FORWARD_FIREWALL -i {BRIDGE} -o {BRIDGE} "
        f"-s {SUBNET} -d {SUBNET} -j RETURN' '-A FORWARD_FIREWALL -i {BRIDGE} "
        f"-o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN' ;;\n"
        "      missing) printf '%s\\n' '-A FORWARD_FIREWALL -j DROP' ;;\n"
        "    esac ;;\n"
        f"  '-C DEFAULT_FORWARD -i {BRIDGE} -o {BRIDGE} -j ACCEPT') {docker_accept} ;;\n"
        f"  '-C FORWARD_FIREWALL -i {BRIDGE} -o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN') "
        f"[ \"$(cat '{state}')\" != missing ] ;;\n"
        f"  '-I FORWARD_FIREWALL 1 -i {BRIDGE} -o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN') "
        f"printf '%s\\n' '{inserted_rule_state}' > '{state}' ;;\n"
        f"  '-D FORWARD_FIREWALL -i {BRIDGE} -o {BRIDGE} -s {SUBNET} -d {SUBNET} -j RETURN') "
        f"printf '%s\\n' missing > '{state}' ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_id = tools / "id"
    fake_id.write_text(f'#!/bin/sh\n[ "$1" = -u ] && echo {root_uid}\n', encoding="utf-8")
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
    assert state.read_text(encoding="utf-8").strip() == "missing"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert "not effective: missing" in checked.stderr
    assert "-I FORWARD_FIREWALL" not in calls.read_text(encoding="utf-8")


def test_mutation_requires_exact_confirmation(tmp_path: Path) -> None:
    environment, state, _calls = _environment(tmp_path)
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "MY_PA_CONFIRM_FIREWALL_MUTATION" in result.stderr
    assert state.read_text(encoding="utf-8").strip() == "missing"


def test_apply_check_idempotence_and_exact_remove(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    assert _run("apply", environment).returncode == 0
    assert state.read_text(encoding="utf-8").strip() == "effective"
    assert _run("check", environment).returncode == 0
    assert _run("apply", environment).returncode == 0
    assert calls.read_text(encoding="utf-8").count("-I FORWARD_FIREWALL") == 1
    assert _run("remove", environment).returncode == 0
    assert state.read_text(encoding="utf-8").strip() == "missing"
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
    assert state.read_text(encoding="utf-8").strip() == "missing"
    assert not calls.exists() or "-I FORWARD_FIREWALL" not in calls.read_text(encoding="utf-8")


@pytest.mark.parametrize("initial_rule_state", ["misordered", "duplicate"])
def test_check_and_apply_refuse_ineffective_existing_rule(
    tmp_path: Path, initial_rule_state: str
) -> None:
    environment, state, calls = _environment(tmp_path, initial_rule_state=initial_rule_state)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert initial_rule_state in checked.stderr
    applied = _run("apply", environment)
    assert applied.returncode != 0
    assert "explicit removal" in applied.stderr
    assert state.read_text(encoding="utf-8").strip() == initial_rule_state
    assert "-I FORWARD_FIREWALL" not in calls.read_text(encoding="utf-8")
    removed = _run("remove", environment)
    if initial_rule_state == "misordered":
        assert removed.returncode == 0
        assert state.read_text(encoding="utf-8").strip() == "missing"
    else:
        assert removed.returncode != 0
        assert state.read_text(encoding="utf-8").strip() == "duplicate"


def test_failed_post_insert_admission_rolls_back_exact_rule(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, inserted_rule_state="misordered")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "rolled back" in result.stderr
    assert state.read_text(encoding="utf-8").strip() == "missing"
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD_FIREWALL" in recorded
    assert "-D FORWARD_FIREWALL" in recorded


@pytest.mark.parametrize("action", ["apply", "remove"])
def test_mutation_refuses_non_root_without_changing_rule(tmp_path: Path, action: str) -> None:
    initial = "effective" if action == "remove" else "missing"
    environment, state, calls = _environment(tmp_path, initial_rule_state=initial, root_uid=1000)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run(action, environment)
    assert result.returncode != 0
    assert "requires root" in result.stderr
    assert state.read_text(encoding="utf-8").strip() == initial
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD_FIREWALL" not in recorded
    assert "-D FORWARD_FIREWALL" not in recorded


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


def test_database_path_stops_before_container_exec_when_firewall_is_missing(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "database-bin"
    tools.mkdir()
    docker_calls = tmp_path / "docker-calls"
    container_id = "6" * 64
    docker = tools / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{docker_calls}'\n"
        'case " $* " in\n'
        "  *' network inspect --format '*' my-pa-nas-contract_data-plane '*) "
        f"printf '%s\\n' '{NETWORK_ID}|my-pa-nas-contract_data-plane|bridge|local|true|"
        f"my-pa-nas-contract|data-plane|{SUBNET}' ;;\n"
        "  *' ps -q postgres '*) "
        f"printf '%s\\n' '{container_id}' ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    python = tools / "python3"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ip = tools / "ip"
    ip.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    iptables = tools / "iptables"
    iptables.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  '-S') printf '%s\\n' '-A FORWARD -j FORWARD_FIREWALL' "
        "'-A FORWARD -j DEFAULT_FORWARD' ;;\n"
        "  '-S FORWARD_FIREWALL') printf '%s\\n' '-A FORWARD_FIREWALL -j DROP' ;;\n"
        f"  '-C DEFAULT_FORWARD -i {BRIDGE} -o {BRIDGE} -j ACCEPT') exit 0 ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for tool in (docker, python, ip, iptables):
        tool.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - checked-in script with synthetic tools
        [str(ROOT / "ops/nas/postgres-common.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_DOCKER": str(docker),
            "MY_PA_NAS_PYTHON": str(python),
            "MY_PA_NAS_IP": str(ip),
            "MY_PA_NAS_IPTABLES": str(iptables),
            "MY_PA_NAS_COMPOSE_FILE": str(tmp_path / "compose.yml"),
            "MY_PA_IMAGE_MANIFEST": str(tmp_path / "manifest.toml"),
            "MY_PA_POSTGRES_RESOURCES": str(tmp_path / "resources.toml"),
            "MY_PA_POSTGRES_IMAGE_ID": f"sha256:{'1' * 64}",
            "MY_PA_DB_PASSWORD": "synthetic-test-only",
            "MY_PA_NAS_ROOT": "/volume1/my-pa",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not effective: missing" in result.stderr
    calls = docker_calls.read_text(encoding="utf-8")
    assert " ps -q postgres" in calls
    assert "network inspect " in calls
    assert " exec " not in calls
