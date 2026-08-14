"""Behavioral contracts for the bounded Synology ingress-plane firewall gate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops/nas/synology-ingress-plane-firewall.sh"
DATA_ID = "d4d93b25" + "6" * 56
DATA_BRIDGE = "docker-d4d93b25"
DATA_SUBNET = "172.22.0.0/16"
INGRESS_ID = "a1b2c3d4" + "7" * 56
INGRESS_BRIDGE = "docker-a1b2c3d4"
INGRESS_SUBNET = "172.23.0.0/16"
DATA_RULE = (
    f"-A FORWARD_FIREWALL -s {DATA_SUBNET} -d {DATA_SUBNET} "
    f"-i {DATA_BRIDGE} -o {DATA_BRIDGE} -j RETURN"
)
INGRESS_RULE = (
    f"-A FORWARD_FIREWALL -s {INGRESS_SUBNET} -d {INGRESS_SUBNET} "
    f"-i {INGRESS_BRIDGE} -o {INGRESS_BRIDGE} -j RETURN"
)


def _environment(
    tmp_path: Path,
    *,
    wrong_network: bool = False,
    missing_docker_accept: bool = False,
    data_effective: bool = True,
    initial_rule_state: str = "missing",
    inserted_rule_state: str = "effective",
    root_uid: int = 0,
) -> tuple[dict[str, str], Path, Path]:
    tools = tmp_path / "bin"
    tools.mkdir()
    state = tmp_path / "ingress-rule-state"
    state.write_text(initial_rule_state, encoding="utf-8")
    calls = tmp_path / "iptables-calls"
    docker = tools / "docker"
    ingress_project = "other-project" if wrong_network else "my-pa-nas-contract"
    docker.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        "  *' network inspect --format '*' my-pa-nas-contract_data-plane '*)\n"
        f"    printf '%s\\n' '{DATA_ID}|my-pa-nas-contract_data-plane|bridge|local|true|"
        f"my-pa-nas-contract|data-plane|{DATA_SUBNET}' ;;\n"
        "  *' network inspect --format '*' my-pa-nas-contract_ingress-plane '*)\n"
        f"    printf '%s\\n' '{INGRESS_ID}|my-pa-nas-contract_ingress-plane|bridge|local|true|"
        f"{ingress_project}|ingress-plane|{INGRESS_SUBNET}' ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    ip = tools / "ip"
    ip.write_text(
        "#!/bin/sh\n"
        f'[ "$*" = "link show dev {DATA_BRIDGE}" ] || '
        f'[ "$*" = "link show dev {INGRESS_BRIDGE}" ]\n',
        encoding="utf-8",
    )
    data_flag = "true" if data_effective else "false"
    docker_accept = "exit 1" if missing_docker_accept else "exit 0"
    iptables = tools / "iptables"
    iptables.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{calls}'\n"
        'case "$*" in\n'
        "  '-S') printf '%s\\n' '-A FORWARD -j FORWARD_FIREWALL' "
        "'-A FORWARD -j DEFAULT_FORWARD' ;;\n"
        "  '-S FORWARD_FIREWALL')\n"
        f"    value=$(cat '{state}')\n"
        f"    if {data_flag}; then printf '%s\\n' '{DATA_RULE}'; fi\n"
        '    case "$value" in\n'
        f"      effective) printf '%s\\n' '{INGRESS_RULE}' '-A FORWARD_FIREWALL -j DROP' ;;\n"
        f"      misordered) printf '%s\\n' '-A FORWARD_FIREWALL -j DROP' '{INGRESS_RULE}' ;;\n"
        f"      duplicate) printf '%s\\n' '{INGRESS_RULE}' '{INGRESS_RULE}' ;;\n"
        "      missing) printf '%s\\n' '-A FORWARD_FIREWALL -j DROP' ;;\n"
        "    esac ;;\n"
        f"  '-C DEFAULT_FORWARD -i {DATA_BRIDGE} -o {DATA_BRIDGE} -j ACCEPT') exit 0 ;;\n"
        f"  '-C DEFAULT_FORWARD -i {INGRESS_BRIDGE} -o {INGRESS_BRIDGE} -j ACCEPT') "
        f"{docker_accept} ;;\n"
        f"  '-C FORWARD_FIREWALL -i {DATA_BRIDGE} -o {DATA_BRIDGE} -s {DATA_SUBNET} "
        f"-d {DATA_SUBNET} -j RETURN') {data_flag} ;;\n"
        f"  '-C FORWARD_FIREWALL -i {INGRESS_BRIDGE} -o {INGRESS_BRIDGE} "
        f"-s {INGRESS_SUBNET} -d {INGRESS_SUBNET} -j RETURN') "
        f"[ \"$(cat '{state}')\" != missing ] ;;\n"
        f"  '-I FORWARD_FIREWALL 2 -i {INGRESS_BRIDGE} -o {INGRESS_BRIDGE} "
        f"-s {INGRESS_SUBNET} -d {INGRESS_SUBNET} -j RETURN') "
        f"printf '%s\\n' '{inserted_rule_state}' > '{state}' ;;\n"
        f"  '-D FORWARD_FIREWALL -i {INGRESS_BRIDGE} -o {INGRESS_BRIDGE} "
        f"-s {INGRESS_SUBNET} -d {INGRESS_SUBNET} -j RETURN') "
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


def test_apply_check_idempotence_and_exact_remove_preserve_data_rule(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_ingress-plane"
    assert _run("apply", environment).returncode == 0
    assert state.read_text(encoding="utf-8").strip() == "effective"
    assert _run("check", environment).returncode == 0
    assert _run("apply", environment).returncode == 0
    recorded = calls.read_text(encoding="utf-8")
    assert recorded.count("-I FORWARD_FIREWALL 2") == 1
    assert "-I FORWARD_FIREWALL 1" not in recorded
    assert _run("remove", environment).returncode == 0
    assert state.read_text(encoding="utf-8").strip() == "missing"


@pytest.mark.parametrize(
    ("wrong_network", "missing_docker_accept", "data_effective", "expected"),
    [
        (True, False, True, "network identity mismatch"),
        (False, True, True, "same-bridge ACCEPT rule is unavailable"),
        (False, False, False, "data-plane firewall rule is not effective"),
    ],
)
def test_apply_refuses_unproven_network_forwarding_or_data_rule(
    tmp_path: Path,
    wrong_network: bool,
    missing_docker_accept: bool,
    data_effective: bool,
    expected: str,
) -> None:
    environment, state, calls = _environment(
        tmp_path,
        wrong_network=wrong_network,
        missing_docker_accept=missing_docker_accept,
        data_effective=data_effective,
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_ingress-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert expected in result.stderr
    assert state.read_text(encoding="utf-8").strip() == "missing"
    assert "-I FORWARD_FIREWALL 2" not in calls.read_text(encoding="utf-8")


@pytest.mark.parametrize("initial_rule_state", ["misordered", "duplicate"])
def test_check_and_apply_refuse_ineffective_existing_rule(
    tmp_path: Path, initial_rule_state: str
) -> None:
    environment, state, calls = _environment(tmp_path, initial_rule_state=initial_rule_state)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_ingress-plane"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert initial_rule_state in checked.stderr
    applied = _run("apply", environment)
    assert applied.returncode != 0
    assert "explicit removal" in applied.stderr
    assert state.read_text(encoding="utf-8").strip() == initial_rule_state
    assert "-I FORWARD_FIREWALL 2" not in calls.read_text(encoding="utf-8")


def test_failed_post_insert_admission_rolls_back_exact_rule(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, inserted_rule_state="misordered")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_ingress-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "rolled back" in result.stderr
    assert state.read_text(encoding="utf-8").strip() == "missing"
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD_FIREWALL 2" in recorded
    assert "-D FORWARD_FIREWALL" in recorded


@pytest.mark.parametrize("action", ["apply", "remove"])
def test_mutation_requires_root_and_exact_confirmation(tmp_path: Path, action: str) -> None:
    initial = "effective" if action == "remove" else "missing"
    environment, state, calls = _environment(tmp_path, initial_rule_state=initial, root_uid=1000)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_ingress-plane"
    result = _run(action, environment)
    assert result.returncode != 0
    assert "requires root" in result.stderr
    assert state.read_text(encoding="utf-8").strip() == initial
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD_FIREWALL 2" not in recorded
    assert "-D FORWARD_FIREWALL" not in recorded


def test_mutation_refuses_wrong_confirmation(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "MY_PA_CONFIRM_FIREWALL_MUTATION" in result.stderr
    assert state.read_text(encoding="utf-8").strip() == "missing"
    assert "-I FORWARD_FIREWALL 2" not in calls.read_text(encoding="utf-8")


def test_runtime_paths_require_ingress_firewall_gate() -> None:
    for relative in ("ops/nas/start.sh", "ops/nas/restart.sh", "ops/nas/health.sh"):
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert '"$script_dir/synology-ingress-plane-firewall.sh" check' in content
    start = (ROOT / "ops/nas/start.sh").read_text(encoding="utf-8")
    assert start.index("nas_compose create --no-build --pull never") < start.index(
        '"$script_dir/synology-ingress-plane-firewall.sh" check'
    )
    assert start.index('"$script_dir/synology-ingress-plane-firewall.sh" check') < start.index(
        "nas_compose up --detach --no-build --pull never"
    )
