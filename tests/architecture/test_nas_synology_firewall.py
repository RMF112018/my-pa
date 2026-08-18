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
P1 = f"-A MY_PA_DATA_PLANE -s {SUBNET} -d {SUBNET} -i {BRIDGE} -o {BRIDGE} -j ACCEPT"
P2 = f"-A MY_PA_DATA_PLANE -i {BRIDGE} -j DROP"
P3 = f"-A MY_PA_DATA_PLANE -o {BRIDGE} -j DROP"
P4 = "-A MY_PA_DATA_PLANE -j RETURN"
BROAD = f"-A FORWARD_FIREWALL -s {SUBNET} -j RETURN"
NEG_EGRESS = f"-A MY_PA_DATA_PLANE -i {BRIDGE} ! -o {BRIDGE} -j DROP"
NEG_INGRESS = f"-A MY_PA_DATA_PLANE ! -i {BRIDGE} -o {BRIDGE} -j DROP"

_FAKE_IPTABLES = r"""
#!/bin/sh
set -eu
state_dir=${FAKE_FW_STATE:?}
printf '%s\n' "$*" >> "${state_dir}/calls"
forward=$(cat "${state_dir}/forward")
chain=$(cat "${state_dir}/chain")
broad=$(cat "${state_dir}/broad")
drop=$(cat "${state_dir}/drop")
chain_file="${state_dir}/chain_lines"

emit_chain_lines() {
  if [ -f "$chain_file" ]; then
    cat "$chain_file"
    return
  fi
  case "$chain" in
    exact)
      printf '%s\n' '{P1}' '{P2}' '{P3}' '{P4}'
      ;;
    empty) ;;
    partial)
      printf '%s\n' '{P1}'
      ;;
    negated)
      printf '%s\n' '{P1}' '{NEG_EGRESS}' '{NEG_INGRESS}' '{P4}'
      ;;
    extra)
      printf '%s\n' '{P1}' '{P2}' '{P3}' '{P4}' '-A MY_PA_DATA_PLANE -p tcp -j ACCEPT'
      ;;
    foreign)
      printf '%s\n' '{P1}' '{P2}' '{P3}' '-A MY_PA_DATA_PLANE -j ACCEPT'
      ;;
    missing_p1)
      printf '%s\n' '{P2}' '{P2}' '{P3}' '{P4}'
      ;;
    missing_i)
      printf '%s\n' '{P1}' '{P4}' '{P3}' '{P4}'
      ;;
    missing_o)
      printf '%s\n' '{P1}' '{P2}' '{P4}' '{P4}'
      ;;
  esac
}

emit_forward() {
  case "$forward" in
    legacy) printf '%s\n' '-A FORWARD -j FORWARD_FIREWALL' ;;
    effective)
      printf '%s\n' '-A FORWARD -j MY_PA_DATA_PLANE' '-A FORWARD -j FORWARD_FIREWALL'
      ;;
    after_dsm)
      printf '%s\n' '-A FORWARD -j FORWARD_FIREWALL' '-A FORWARD -j MY_PA_DATA_PLANE'
      ;;
    default_forward)
      printf '%s\n' '-A FORWARD -j FORWARD_FIREWALL' '-A FORWARD -j DEFAULT_FORWARD'
      ;;
    policy_only) ;;
    duplicate)
      printf '%s\n' '-A FORWARD -j MY_PA_DATA_PLANE' '-A FORWARD -j FORWARD_FIREWALL' \
        '-A FORWARD -j MY_PA_DATA_PLANE'
      ;;
    extra)
      printf '%s\n' '-A FORWARD -j MY_PA_DATA_PLANE' '-A FORWARD -j FORWARD_FIREWALL' \
        '-A FORWARD -j DOCKER-USER'
      ;;
  esac
}

emit_firewall() {
  printf '%s\n' '-N FORWARD_FIREWALL'
  printf '%s\n' '-A FORWARD_FIREWALL -m state --state RELATED,ESTABLISHED -j ACCEPT'
  printf '%s\n' '-A FORWARD_FIREWALL -s 10.0.0.0/24 -j RETURN'
  if [ "$broad" = present ]; then
    printf '%s\n' '{BROAD}'
  fi
  printf '%s\n' '-A FORWARD_FIREWALL -s 172.25.0.0/16 -j RETURN'
  case "$drop" in
    missing) ;;
    duplicate)
      printf '%s\n' '-A FORWARD_FIREWALL -j DROP'
      printf '%s\n' '-A FORWARD_FIREWALL -j DROP'
      ;;
    *)
      printf '%s\n' '-A FORWARD_FIREWALL -j DROP'
      ;;
  esac
}

if [ "${FAKE_TOOL:-iptables}" = save ]; then
  printf '%s\n' '*filter' ':FORWARD ACCEPT [0:0]' ':FORWARD_FIREWALL - [0:0]'
  if [ "$chain" != missing ] || [ -f "$chain_file" ]; then
    printf '%s\n' ':MY_PA_DATA_PLANE - [0:0]'
  fi
  emit_forward
  emit_firewall | awk '$1 == "-A"'
  if [ "$chain" != missing ] || [ -f "$chain_file" ]; then
    emit_chain_lines
  fi
  printf '%s\n' COMMIT
  exit 0
fi

case "$*" in
  "-S MY_PA_DATA_PLANE")
    [ "$chain" != missing ] || [ -f "$chain_file" ] || exit 1
    printf '%s\n' '-N MY_PA_DATA_PLANE'
    emit_chain_lines
    ;;
  "-S FORWARD_FIREWALL")
    emit_firewall
    ;;
  "-N MY_PA_DATA_PLANE")
    printf '%s\n' empty > "${state_dir}/chain"
    : > "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -s {SUBNET} -d {SUBNET} -i {BRIDGE} -o {BRIDGE} -j ACCEPT")
    printf '%s\n' '{P1}' >> "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -i {BRIDGE} -j DROP")
    printf '%s\n' '{P2}' >> "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -o {BRIDGE} -j DROP")
    printf '%s\n' '{P3}' >> "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -j RETURN")
    printf '%s\n' '{P4}' >> "$chain_file"
    printf '%s\n' exact > "${state_dir}/chain"
    ;;
  "-I FORWARD 1 -j MY_PA_DATA_PLANE")
    if [ "${FAKE_JUMP_FAIL:-0}" = 1 ]; then exit 1; fi
    if [ "${FAKE_JUMP_VERIFY_FAIL:-0}" = 1 ]; then
      printf '%s\n' after_dsm > "${state_dir}/forward"
    else
      printf '%s\n' effective > "${state_dir}/forward"
    fi
    ;;
  "-D FORWARD -j MY_PA_DATA_PLANE")
    printf '%s\n' legacy > "${state_dir}/forward"
    ;;
  "-C FORWARD_FIREWALL -s {SUBNET} -j RETURN")
    [ "$broad" = present ]
    ;;
  "-D FORWARD_FIREWALL -s {SUBNET} -j RETURN")
    printf '%s\n' absent > "${state_dir}/broad"
    ;;
  "-I FORWARD_FIREWALL "*)
    printf '%s\n' present > "${state_dir}/broad"
    ;;
  "-F MY_PA_DATA_PLANE")
    : > "$chain_file"
    printf '%s\n' empty > "${state_dir}/chain"
    ;;
  "-X MY_PA_DATA_PLANE")
    rm -f "$chain_file"
    printf '%s\n' missing > "${state_dir}/chain"
    ;;
  *)
    exit 1
    ;;
esac
"""


def _environment(
    tmp_path: Path,
    *,
    forward: str = "legacy",
    chain: str = "missing",
    broad: str = "present",
    wrong_network: bool = False,
    root_uid: int = 0,
    jump_fail: str = "0",
    jump_verify_fail: str = "0",
    drop: str = "unique",
) -> tuple[dict[str, str], Path, Path]:
    tools = tmp_path / "bin"
    tools.mkdir()
    state = tmp_path / "fw-state"
    state.mkdir()
    (state / "forward").write_text(forward + "\n", encoding="utf-8")
    (state / "chain").write_text(chain + "\n", encoding="utf-8")
    (state / "broad").write_text(broad + "\n", encoding="utf-8")
    (state / "drop").write_text(drop + "\n", encoding="utf-8")
    (state / "calls").write_text("", encoding="utf-8")
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
    body = (
        _FAKE_IPTABLES.replace("{P1}", P1)
        .replace("{P2}", P2)
        .replace("{P3}", P3)
        .replace("{P4}", P4)
        .replace("{BROAD}", BROAD)
        .replace("{NEG_EGRESS}", NEG_EGRESS)
        .replace("{NEG_INGRESS}", NEG_INGRESS)
        .replace("{SUBNET}", SUBNET)
        .replace("{BRIDGE}", BRIDGE)
    )
    iptables = tools / "iptables"
    iptables.write_text(body, encoding="utf-8")
    iptables_save = tools / "iptables-save"
    iptables_save.write_text(
        '#!/bin/sh\nFAKE_TOOL=save exec "$(dirname -- "$0")/iptables" "$@"\n',
        encoding="utf-8",
    )
    fake_id = tools / "id"
    fake_id.write_text(f'#!/bin/sh\n[ "$1" = -u ] && echo {root_uid}\n', encoding="utf-8")
    for path in (docker, ip, iptables, iptables_save, fake_id):
        path.chmod(0o700)
    return (
        {
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "MY_PA_NAS_DOCKER": str(docker),
            "MY_PA_NAS_IPTABLES": str(iptables),
            "MY_PA_NAS_IPTABLES_SAVE": str(iptables_save),
            "MY_PA_NAS_IP": str(ip),
            "FAKE_FW_STATE": str(state),
            "FAKE_JUMP_FAIL": jump_fail,
            "FAKE_JUMP_VERIFY_FAIL": jump_verify_fail,
        },
        state,
        state / "calls",
    )


def _run(action: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - checked-in script with synthetic tools
        [str(SCRIPT), action],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_plan_is_read_only_and_check_fails_on_legacy_state(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    planned = _run("plan", environment)
    assert planned.returncode == 0
    assert "requires admission" in planned.stdout
    assert "legacy" in planned.stdout
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert "not effective: legacy" in checked.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD" not in recorded
    assert "-N MY_PA_DATA_PLANE" not in recorded


def test_check_passes_only_for_exact_my_pa_first_state(tmp_path: Path) -> None:
    environment, _state, _calls = _environment(
        tmp_path, forward="effective", chain="exact", broad="absent"
    )
    result = _run("check", environment)
    assert result.returncode == 0, result.stderr
    assert "gate passed" in result.stdout


def test_mutation_requires_exact_confirmation(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "MY_PA_CONFIRM_FIREWALL_MUTATION" in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert "-I FORWARD" not in calls.read_text(encoding="utf-8")


def test_apply_check_idempotence_and_exact_remove(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    applied = _run("apply", environment)
    assert applied.returncode == 0, applied.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "absent"
    recorded = calls.read_text(encoding="utf-8")
    jump = recorded.index("-I FORWARD 1 -j MY_PA_DATA_PLANE")
    assert recorded.index("-N MY_PA_DATA_PLANE") < jump
    assert jump < recorded.index(f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN")
    assert _run("check", environment).returncode == 0
    calls.write_text("", encoding="utf-8")
    assert _run("apply", environment).returncode == 0
    assert "-I FORWARD" not in calls.read_text(encoding="utf-8")
    removed = _run("remove", environment)
    assert removed.returncode == 0, removed.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "present"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    assert _run("check", environment).returncode != 0


@pytest.mark.parametrize(
    ("forward", "chain", "broad", "needle"),
    [
        ("after_dsm", "exact", "absent", "my-pa-after-dsm"),
        ("default_forward", "missing", "present", "default-forward"),
        ("policy_only", "missing", "present", "policy-accept-only"),
        ("duplicate", "exact", "absent", "duplicate-jump"),
        ("extra", "exact", "absent", "extra-forward"),
        ("effective", "missing", "absent", "missing-chain"),
        ("effective", "foreign", "absent", "foreign-chain"),
        ("effective", "partial", "absent", "partial-chain"),
        ("effective", "negated", "absent", "negated-drop"),
        ("effective", "extra", "absent", "extra-rule"),
        ("effective", "missing_p1", "absent", "missing-p1"),
        ("effective", "missing_i", "absent", "missing-i-drop"),
        ("effective", "missing_o", "absent", "missing-o-drop"),
        ("effective", "exact", "present", "broad-return"),
        ("legacy", "exact", "present", "missing-jump"),
    ],
)
def test_check_and_apply_refuse_abnormal_states(
    tmp_path: Path, forward: str, chain: str, broad: str, needle: str
) -> None:
    environment, _state, calls = _environment(tmp_path, forward=forward, chain=chain, broad=broad)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert needle in checked.stderr
    if needle in {"missing-jump", "broad-return"}:
        applied = _run("apply", environment)
        assert applied.returncode == 0, applied.stderr
        assert _run("check", environment).returncode == 0
        return
    applied = _run("apply", environment)
    assert applied.returncode != 0
    assert "explicit removal" in applied.stderr or needle in applied.stderr
    assert "-I FORWARD 1" not in calls.read_text(encoding="utf-8")


def test_r1_001_dsm_established_cannot_precede_my_pa(tmp_path: Path) -> None:
    environment, _state, _calls = _environment(
        tmp_path, forward="after_dsm", chain="exact", broad="absent"
    )
    result = _run("check", environment)
    assert result.returncode != 0
    assert "my-pa-after-dsm" in result.stderr
    source = SCRIPT.read_text(encoding="utf-8")
    assert '-I FORWARD 1 -j "$enforcement_chain"' in source
    assert "my-pa-after-dsm" in source


def test_r1_002_negated_interface_pair_is_rejected(tmp_path: Path) -> None:
    environment, _state, _calls = _environment(
        tmp_path, forward="effective", chain="negated", broad="absent"
    )
    result = _run("check", environment)
    assert result.returncode != 0
    assert "negated-drop" in result.stderr
    source = SCRIPT.read_text(encoding="utf-8")
    assert "-i $bridge -j DROP" in source
    assert "-o $bridge -j DROP" in source
    assert "! -o $bridge" in source  # detection of the rejected pair
    assert source.count("-i $bridge ! -o $bridge -j DROP") == 1


def test_wrong_network_refuses_before_iptables_mutation(tmp_path: Path) -> None:
    environment, _state, calls = _environment(tmp_path, wrong_network=True)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "network identity mismatch" in result.stderr
    assert not calls.exists() or "-I FORWARD" not in calls.read_text(encoding="utf-8")


def test_failed_jump_install_rolls_back_owned_chain(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="1")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "rolled back" in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded


def test_remove_refuses_foreign_chain(tmp_path: Path) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="foreign", broad="absent"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("remove", environment)
    assert result.returncode != 0
    assert "foreign" in result.stderr
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "foreign"
    assert "-X MY_PA_DATA_PLANE" not in calls.read_text(encoding="utf-8")


def test_remove_refuses_ambiguous_drop_identity(tmp_path: Path) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="exact", broad="absent", drop="missing"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("remove", environment)
    assert result.returncode != 0
    assert "ambiguous rollback identity" in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert "-X MY_PA_DATA_PLANE" not in calls.read_text(encoding="utf-8")


@pytest.mark.parametrize("action", ["apply", "remove"])
def test_mutation_refuses_non_root_without_changing_rule(tmp_path: Path, action: str) -> None:
    initial_forward = "effective" if action == "remove" else "legacy"
    initial_chain = "exact" if action == "remove" else "missing"
    initial_broad = "absent" if action == "remove" else "present"
    environment, state, calls = _environment(
        tmp_path,
        forward=initial_forward,
        chain=initial_chain,
        broad=initial_broad,
        root_uid=1000,
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run(action, environment)
    assert result.returncode != 0
    assert "requires root" in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == initial_forward
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD 1" not in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" not in recorded


def test_script_inspects_forward_through_iptables_save() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "iptables_save_bin" in source
    assert '"$iptables_save_bin" -t filter' in source
    assert "-S FORWARD_FIREWALL" in source
    assert '-S FORWARD"' not in source and "-S FORWARD " not in source
    assert "-L FORWARD" not in source
    assert "-C FORWARD " not in source
    assert "default-forward" in source


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
    iptables.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    iptables_save = tools / "iptables-save"
    iptables_save.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '*filter' ':FORWARD ACCEPT [0:0]' "
        "':FORWARD_FIREWALL - [0:0]' '-A FORWARD -j FORWARD_FIREWALL' "
        f"'-A FORWARD_FIREWALL -s {SUBNET} -j RETURN' "
        "'-A FORWARD_FIREWALL -j DROP' COMMIT\n",
        encoding="utf-8",
    )
    for tool in (docker, python, ip, iptables, iptables_save):
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
            "MY_PA_NAS_IPTABLES_SAVE": str(iptables_save),
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
    assert "not effective: legacy" in result.stderr
    calls = docker_calls.read_text(encoding="utf-8")
    assert " ps -q postgres" in calls
    assert "network inspect " in calls
    assert " exec " not in calls
