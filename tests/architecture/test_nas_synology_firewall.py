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
default_forward=$(cat "${state_dir}/default_forward")
foreign_reference=$(cat "${state_dir}/foreign_reference")
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

emit_default_forward() {
  case "$default_forward" in
    absent) ;;
    docker)
      printf '%s\n' '-A DEFAULT_FORWARD -j DOCKER-USER' \
        '-A DEFAULT_FORWARD -j DOCKER-ISOLATION-STAGE-1'
      ;;
    redirected)
      printf '%s\n' '-A DEFAULT_FORWARD -j MY_PA_DATA_PLANE'
      ;;
    redirected_foreign)
      printf '%s\n' '-A DEFAULT_FORWARD -j MY_PA_DATA_PLANE' \
        '-A DEFAULT_FORWARD -j FOREIGN_TARGET'
      ;;
  esac
}

emit_foreign_reference() {
  [ "$foreign_reference" = present ] || return 0
  printf '%s\n' '-A FOREIGN_CHAIN -j MY_PA_DATA_PLANE'
}

has_external_reference() {
  case "$forward" in
    effective|after_dsm|duplicate|extra) return 0 ;;
  esac
  case "$default_forward" in
    redirected|redirected_foreign) return 0 ;;
  esac
  [ "$foreign_reference" = present ]
}

emit_firewall() {
  printf '%s\n' '-N FORWARD_FIREWALL'
  printf '%s\n' '-A FORWARD_FIREWALL -m state --state RELATED,ESTABLISHED -j ACCEPT'
  printf '%s\n' '-A FORWARD_FIREWALL -s 10.0.0.0/24 -j RETURN'
  if [ "$broad" = present ]; then
    printf '%s\n' '{BROAD}'
  elif [ "$broad" = duplicate ]; then
    printf '%s\n' '{BROAD}'
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
  if [ "$default_forward" != absent ]; then
    printf '%s\n' ':DEFAULT_FORWARD - [0:0]'
  fi
  if [ "$foreign_reference" = present ]; then
    printf '%s\n' ':FOREIGN_CHAIN - [0:0]'
  fi
  if [ "$chain" != missing ] || [ -f "$chain_file" ]; then
    printf '%s\n' ':MY_PA_DATA_PLANE - [0:0]'
  fi
  emit_forward
  emit_default_forward
  emit_foreign_reference
  emit_firewall | awk '$1 == "-A"'
  if [ "$chain" != missing ] || [ -f "$chain_file" ]; then
    emit_chain_lines
  fi
  printf '%s\n' COMMIT
  exit 0
fi

case "$*" in
  "-S FORWARD")
    printf '%s\n' '-P FORWARD ACCEPT'
    emit_forward
    ;;
  "-S DEFAULT_FORWARD")
    [ "$default_forward" != absent ] || exit 1
    printf '%s\n' '-N DEFAULT_FORWARD'
    emit_default_forward
    ;;
  "-S MY_PA_DATA_PLANE")
    [ "$chain" != missing ] || [ -f "$chain_file" ] || exit 1
    printf '%s\n' '-N MY_PA_DATA_PLANE'
    emit_chain_lines
    if [ "${FAKE_EXACT_VERIFY_FAIL:-0}" = 1 ]; then
      printf '%s\n' '-A MY_PA_DATA_PLANE -j ACCEPT'
    fi
    ;;
  "-S FORWARD_FIREWALL")
    [ "${FAKE_FW_S_FAIL:-0}" = 1 ] && exit 1
    emit_firewall
    ;;
  "-N MY_PA_DATA_PLANE")
    printf '%s\n' empty > "${state_dir}/chain"
    : > "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -s {SUBNET} -d {SUBNET} -i {BRIDGE} -o {BRIDGE} -j ACCEPT")
    [ "${FAKE_APPEND_FAIL:-}" = p1 ] && exit 1
    printf '%s\n' '{P1}' >> "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -i {BRIDGE} -j DROP")
    [ "${FAKE_APPEND_FAIL:-}" = p2 ] && exit 1
    printf '%s\n' '{P2}' >> "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -o {BRIDGE} -j DROP")
    [ "${FAKE_APPEND_FAIL:-}" = p3 ] && exit 1
    printf '%s\n' '{P3}' >> "$chain_file"
    ;;
  "-A MY_PA_DATA_PLANE -j RETURN")
    [ "${FAKE_APPEND_FAIL:-}" = p4 ] && exit 1
    printf '%s\n' '{P4}' >> "$chain_file"
    printf '%s\n' exact > "${state_dir}/chain"
    ;;
  "-I FORWARD 1 -j MY_PA_DATA_PLANE")
    if [ "${FAKE_JUMP_FAIL:-0}" = 1 ]; then exit 1; fi
    if [ "${FAKE_JUMP_VERIFY_FAIL:-0}" = redirect ]; then
      printf '%s\n' default_forward > "${state_dir}/forward"
      printf '%s\n' redirected > "${state_dir}/default_forward"
    elif [ "${FAKE_JUMP_VERIFY_FAIL:-0}" = redirect-foreign ]; then
      printf '%s\n' default_forward > "${state_dir}/forward"
      printf '%s\n' redirected_foreign > "${state_dir}/default_forward"
    elif [ "${FAKE_JUMP_VERIFY_FAIL:-0}" = 1 ]; then
      printf '%s\n' after_dsm > "${state_dir}/forward"
    else
      printf '%s\n' effective > "${state_dir}/forward"
    fi
    ;;
  "-D FORWARD -j MY_PA_DATA_PLANE")
    [ "${FAKE_JUMP_DELETE_FAIL:-0}" = 1 ] && exit 1
    case "${FAKE_JUMP_DELETE_MODE:-correct}" in
      correct)
        printf '%s\n' legacy > "${state_dir}/forward"
        printf '%s\n' absent > "${state_dir}/default_forward"
        ;;
      nested-remains) ;;
      outer-restored-nested-remains)
        printf '%s\n' legacy > "${state_dir}/forward"
        ;;
      outer-remains)
        printf '%s\n' default_forward > "${state_dir}/forward"
        printf '%s\n' absent > "${state_dir}/default_forward"
        ;;
      other-reference-remains)
        printf '%s\n' legacy > "${state_dir}/forward"
        printf '%s\n' absent > "${state_dir}/default_forward"
        printf '%s\n' present > "${state_dir}/foreign_reference"
        ;;
      *) exit 1 ;;
    esac
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
    [ "${FAKE_F_FAIL:-0}" = 1 ] && exit 1
    : > "$chain_file"
    printf '%s\n' empty > "${state_dir}/chain"
    ;;
  "-X MY_PA_DATA_PLANE")
    [ "${FAKE_X_FAIL:-0}" = 1 ] && exit 1
    ! has_external_reference || exit 1
    rm -f "$chain_file"
    printf '%s\n' missing > "${state_dir}/chain"
    ;;
  *)
    exit 1
    ;;
esac
"""

_FAKE_IPTABLES_SAVE = r"""
#!/bin/sh
set -eu
state_dir=${FAKE_FW_STATE:?}
count_file="${state_dir}/save_count"
count=0
[ -f "$count_file" ] && count=$(cat "$count_file")
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
mode=${FAKE_FILTER_SAVE_FAIL_MODE:-}
at=${FAKE_FILTER_SAVE_FAIL_AT:-0}
calls="${state_dir}/calls"
after_insert=0
after_delete=0
after_x=0
after_create=0
after_p4=0
after_broad_delete=0
if [ -f "$calls" ] && grep -q -- '-I FORWARD 1 -j MY_PA_DATA_PLANE' "$calls"; then
  after_insert=1
fi
if [ -f "$calls" ] && grep -q -- '-D FORWARD -j MY_PA_DATA_PLANE' "$calls"; then
  after_delete=1
fi
if [ "${FAKE_INJECT_REFERENCE_AFTER_ROLLBACK_PROOF:-0}" = 1 ] && \
   [ "$after_delete" -eq 1 ]; then
  if [ -f "${state_dir}/rollback_proof_seen" ]; then
    printf '%s\n' present > "${state_dir}/foreign_reference"
  else
    : > "${state_dir}/rollback_proof_seen"
  fi
fi
if [ -f "$calls" ] && grep -q -- '-X MY_PA_DATA_PLANE' "$calls"; then
  after_x=1
fi
if [ -f "$calls" ] && grep -q -- '-N MY_PA_DATA_PLANE' "$calls"; then
  after_create=1
fi
if [ -f "$calls" ] && grep -q -- '-A MY_PA_DATA_PLANE -j RETURN' "$calls"; then
  after_p4=1
fi
if [ -f "$calls" ] && grep -q -- '-D FORWARD_FIREWALL' "$calls"; then
  after_broad_delete=1
fi
case "$mode" in
  once)
    [ "$at" -gt 0 ] && [ "$count" -eq "$at" ] && exit 1
    ;;
  always)
    [ "$at" -gt 0 ] && [ "$count" -ge "$at" ] && exit 1
    ;;
  once-after-insert)
    if [ "$after_insert" -eq 1 ] && [ ! -f "${state_dir}/save_fail_insert" ]; then
      : > "${state_dir}/save_fail_insert"
      exit 1
    fi
    ;;
  always-after-insert)
    [ "$after_insert" -eq 1 ] && exit 1
    ;;
  once-after-jump-delete)
    if [ "$after_delete" -eq 1 ] && [ ! -f "${state_dir}/save_fail_jump_del" ]; then
      : > "${state_dir}/save_fail_jump_del"
      exit 1
    fi
    ;;
  once-after-chain-delete)
    if [ "$after_x" -eq 1 ] && [ ! -f "${state_dir}/save_fail_x" ]; then
      : > "${state_dir}/save_fail_x"
      exit 1
    fi
    ;;
  once-after-create)
    if [ "$after_create" -eq 1 ] && [ ! -f "${state_dir}/save_fail_create" ]; then
      : > "${state_dir}/save_fail_create"
      exit 1
    fi
    ;;
  once-after-p4)
    if [ "$after_p4" -eq 1 ] && [ ! -f "${state_dir}/save_fail_p4" ]; then
      : > "${state_dir}/save_fail_p4"
      exit 1
    fi
    ;;
  once-after-broad-delete)
    if [ "$after_broad_delete" -eq 1 ] && [ ! -f "${state_dir}/save_fail_broad" ]; then
      : > "${state_dir}/save_fail_broad"
      exit 1
    fi
    ;;
esac
FAKE_TOOL=save exec "$(dirname -- "$0")/iptables" "$@"
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
    jump_delete_mode: str = "correct",
    default_forward: str | None = None,
    foreign_reference: bool = False,
    drop: str = "unique",
) -> tuple[dict[str, str], Path, Path]:
    tools = tmp_path / "bin"
    tools.mkdir(parents=True)
    state = tmp_path / "fw-state"
    state.mkdir(parents=True)
    (state / "forward").write_text(forward + "\n", encoding="utf-8")
    if default_forward is None:
        default_forward = "docker" if forward == "default_forward" else "absent"
    (state / "default_forward").write_text(default_forward + "\n", encoding="utf-8")
    (state / "foreign_reference").write_text(
        ("present" if foreign_reference else "absent") + "\n", encoding="utf-8"
    )
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
    iptables_save.write_text(_FAKE_IPTABLES_SAVE.lstrip("\n"), encoding="utf-8")
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
            "FAKE_JUMP_DELETE_MODE": jump_delete_mode,
            "FAKE_JUMP_DELETE_FAIL": "0",
            "FAKE_INJECT_REFERENCE_AFTER_ROLLBACK_PROOF": "0",
            "FAKE_FW_S_FAIL": "0",
            "FAKE_APPEND_FAIL": "",
            "FAKE_F_FAIL": "0",
            "FAKE_X_FAIL": "0",
            "FAKE_EXACT_VERIFY_FAIL": "0",
            "FAKE_FILTER_SAVE_FAIL_MODE": "",
            "FAKE_FILTER_SAVE_FAIL_AT": "0",
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


def _recorded(calls: Path) -> str:
    return calls.read_text(encoding="utf-8")


def _assert_no_enforcement_mutation(calls: Path) -> None:
    recorded = _recorded(calls)
    assert "-N MY_PA_DATA_PLANE" not in recorded
    assert "-A MY_PA_DATA_PLANE" not in recorded
    assert "-I FORWARD 1" not in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" not in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


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


def test_forward_firewall_inspection_failure_fails_closed(tmp_path: Path) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="exact", broad="absent"
    )
    environment["FAKE_FW_S_FAIL"] = "1"
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert "inspection failed" in checked.stderr
    assert "effective" not in checked.stderr
    assert "gate passed" not in checked.stdout
    calls.write_text("", encoding="utf-8")
    applied = _run("apply", environment)
    assert applied.returncode != 0
    assert "inspection failed" in applied.stderr
    _assert_no_enforcement_mutation(calls)
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    calls.write_text("", encoding="utf-8")
    removed = _run("remove", environment)
    assert removed.returncode != 0
    assert "inspection failed" in removed.stderr
    _assert_no_enforcement_mutation(calls)
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "absent"


def test_duplicate_broad_return_is_refused_before_mutation(tmp_path: Path) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="legacy", chain="missing", broad="duplicate"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert "duplicate-broad-return" in checked.stderr
    assert "gate passed" not in checked.stdout
    calls.write_text("", encoding="utf-8")
    applied = _run("apply", environment)
    assert applied.returncode != 0
    assert "duplicate-broad-return" in applied.stderr
    _assert_no_enforcement_mutation(calls)
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "duplicate"
    calls.write_text("", encoding="utf-8")
    removed = _run("remove", environment)
    assert removed.returncode != 0
    assert "duplicate-broad-return" in removed.stderr
    _assert_no_enforcement_mutation(calls)
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "duplicate"


@pytest.mark.parametrize("fail_at", ["p1", "p2", "p3", "p4"])
def test_created_chain_population_failure_rolls_back_completely(
    tmp_path: Path, fail_at: str
) -> None:
    environment, state, calls = _environment(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_APPEND_FAIL"] = fail_at
    applied = _run("apply", environment)
    assert applied.returncode != 0, applied.stderr
    assert "population failed" in applied.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "present"
    recorded = _recorded(calls)
    assert "-N MY_PA_DATA_PLANE" in recorded
    assert "-I FORWARD 1" not in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded
    environment["FAKE_APPEND_FAIL"] = ""
    calls.write_text("", encoding="utf-8")
    retried = _run("apply", environment)
    assert retried.returncode == 0, retried.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "absent"
    assert _run("check", environment).returncode == 0


def test_empty_chain_population_failure_restores_empty_chain(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, chain="empty")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_APPEND_FAIL"] = "p2"
    applied = _run("apply", environment)
    assert applied.returncode != 0, applied.stderr
    assert "empty chain was restored" in applied.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "present"
    recorded = _recorded(calls)
    assert "-N MY_PA_DATA_PLANE" not in recorded
    assert "-I FORWARD 1" not in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded
    assert "-F MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded
    environment["FAKE_APPEND_FAIL"] = ""
    calls.write_text("", encoding="utf-8")
    retried = _run("apply", environment)
    assert retried.returncode == 0, retried.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "absent"
    assert _run("check", environment).returncode == 0


def test_referenced_empty_chain_is_refused_with_zero_mutation(tmp_path: Path) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="empty", broad="absent"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    checked = _run("check", environment)
    assert checked.returncode != 0
    assert "referenced-empty-chain" in checked.stderr
    assert "gate passed" not in checked.stdout
    calls.write_text("", encoding="utf-8")
    applied = _run("apply", environment)
    assert applied.returncode != 0
    assert "referenced-empty-chain" in applied.stderr
    _assert_no_enforcement_mutation(calls)
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "absent"
    calls.write_text("", encoding="utf-8")
    removed = _run("remove", environment)
    assert removed.returncode != 0
    assert "referenced-empty-chain" in removed.stderr
    _assert_no_enforcement_mutation(calls)
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"


def test_referenced_empty_append_failure_is_never_reached(tmp_path: Path) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="empty", broad="absent"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_APPEND_FAIL"] = "p1"
    applied = _run("apply", environment)
    assert applied.returncode != 0
    assert "referenced-empty-chain" in applied.stderr
    recorded = _recorded(calls)
    assert "-A MY_PA_DATA_PLANE" not in recorded
    assert "-N MY_PA_DATA_PLANE" not in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded
    assert "-I FORWARD" not in recorded
    assert "-D FORWARD" not in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"


def test_jump_deletion_failure_after_verify_failure_is_rollback_failed(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="1")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_JUMP_DELETE_FAIL"] = "1"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "rollback succeeded" not in result.stderr
    assert "rolled back" not in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "after_dsm"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded


def test_cleanup_failure_after_jump_removed_is_rollback_failed(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="1")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_X_FAIL"] = "1"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "rollback succeeded" not in result.stderr
    assert "rolled back" not in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"
    recorded = _recorded(calls)
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-F MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded


def test_post_population_cleanup_failure_is_rollback_failed(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_EXACT_VERIFY_FAIL"] = "1"
    environment["FAKE_X_FAIL"] = "1"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "was removed" not in result.stderr
    assert "rollback succeeded" not in result.stderr
    assert "-I FORWARD" not in _recorded(calls)
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"


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


def test_jump_insert_failure_cleans_created_chain(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, jump_fail="1")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "failed to insert MY_PA_DATA_PLANE FORWARD jump" in result.stderr
    assert "ROLLBACK_FAILED" not in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    recorded = _recorded(calls)
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" not in recorded


def test_failed_jump_install_rolls_back_owned_chain(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="1")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "rollback succeeded" in result.stderr
    assert "ROLLBACK_FAILED" not in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    recorded = calls.read_text(encoding="utf-8")
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded


def test_dsm_default_forward_redirection_is_named_and_rolled_back(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="redirect")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "UNSUPPORTED_DSM_FORWARD_REDIRECTION" in result.stderr
    assert "rollback succeeded" in result.stderr
    assert "ROLLBACK_FAILED" not in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("default_forward").read_text(encoding="utf-8").strip() == "absent"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "present"
    recorded = _recorded(calls)
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-S DEFAULT_FORWARD" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded


@pytest.mark.parametrize("delete_mode", ["nested-remains", "outer-restored-nested-remains"])
def test_redirected_delete_success_with_nested_reference_is_rollback_failed(
    tmp_path: Path, delete_mode: str
) -> None:
    environment, state, calls = _environment(
        tmp_path, jump_verify_fail="redirect", jump_delete_mode=delete_mode
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "DEFAULT_FORWARD still references MY_PA_DATA_PLANE" in result.stderr
    assert "rollback succeeded" not in result.stderr
    assert state.joinpath("default_forward").read_text(encoding="utf-8").strip() == "redirected"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


def test_redirected_delete_with_outer_topology_remaining_is_rollback_failed(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(
        tmp_path, jump_verify_fail="redirect", jump_delete_mode="outer-remains"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "legacy DSM-first FORWARD restoration could not be verified" in result.stderr
    assert state.joinpath("default_forward").read_text(encoding="utf-8").strip() == "absent"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


def test_redirected_delete_with_other_reference_remaining_is_rollback_failed(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(
        tmp_path, jump_verify_fail="redirect", jump_delete_mode="other-reference-remains"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "another filter chain still references MY_PA_DATA_PLANE" in result.stderr
    assert state.joinpath("foreign_reference").read_text(encoding="utf-8").strip() == "present"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


def test_preexisting_docker_default_forward_is_refused_without_attribution(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="default_forward", default_forward="docker"
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "default-forward" in result.stderr
    assert "UNSUPPORTED_DSM_FORWARD_REDIRECTION" not in result.stderr
    assert state.joinpath("default_forward").read_text(encoding="utf-8").strip() == "docker"
    assert "-I FORWARD" not in _recorded(calls)


def test_foreign_default_forward_content_is_not_named_as_owned_redirection(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(
        tmp_path,
        jump_verify_fail="redirect-foreign",
        jump_delete_mode="nested-remains",
    )
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "UNSUPPORTED_DSM_FORWARD_REDIRECTION" not in result.stderr
    assert "ROLLBACK_FAILED" in result.stderr
    assert state.joinpath("default_forward").read_text(encoding="utf-8").strip() == (
        "redirected_foreign"
    )
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    assert "-X MY_PA_DATA_PLANE" not in _recorded(calls)


def test_redirected_delete_command_failure_retains_owned_chain(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="redirect")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_JUMP_DELETE_FAIL"] = "1"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert state.joinpath("default_forward").read_text(encoding="utf-8").strip() == "redirected"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


def test_redirected_cleanup_delete_failure_is_explicit(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="redirect")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_X_FAIL"] = "1"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "owned chain cleanup after jump rollback" in result.stderr
    assert state.joinpath("default_forward").read_text(encoding="utf-8").strip() == "absent"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"
    recorded = _recorded(calls)
    assert "-F MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded


def test_reference_appearing_after_rollback_proof_prevents_chain_cleanup(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(tmp_path, jump_verify_fail="redirect")
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    environment["FAKE_INJECT_REFERENCE_AFTER_ROLLBACK_PROOF"] = "1"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "owned chain cleanup after jump rollback" in result.stderr
    assert state.joinpath("foreign_reference").read_text(encoding="utf-8").strip() == "present"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


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
    iptables.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  "-S FORWARD_FIREWALL")\n'
        "    printf '%s\\n' '-N FORWARD_FIREWALL' "
        "'-A FORWARD_FIREWALL -m state --state RELATED,ESTABLISHED -j ACCEPT' "
        f"'-A FORWARD_FIREWALL -s {SUBNET} -j RETURN' "
        "'-A FORWARD_FIREWALL -j DROP' ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
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


def _confirm(environment: dict[str, str]) -> dict[str, str]:
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = "my-pa-nas-contract_data-plane"
    return environment


def test_r3_t1_post_insert_save_fail_rolls_back_when_verified(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "once-after-insert"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "rollback succeeded" in result.stderr
    assert "ROLLBACK_FAILED" not in result.stderr
    assert "firewall enforcement admitted" not in result.stdout
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    recorded = _recorded(calls)
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-F MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" not in recorded


def test_r3_t2_post_insert_save_fail_then_unreadable_rollback_is_failed(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(tmp_path)
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "always-after-insert"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "rollback succeeded" not in result.stderr
    assert "rolled back" not in result.stderr
    assert "firewall enforcement admitted" not in result.stdout
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


def test_r3_t3_post_insert_save_fail_then_jump_delete_fail_skips_chain_cleanup(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(tmp_path)
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "once-after-insert"
    environment["FAKE_JUMP_DELETE_FAIL"] = "1"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "ROLLBACK_FAILED" in result.stderr
    assert "rollback succeeded" not in result.stderr
    assert "rolled back" not in result.stderr
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded


def test_r3_t4_remove_resumes_missing_jump_cleanup_after_save_fail(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="exact", broad="absent"
    )
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "once-after-jump-delete"
    first = _run("remove", environment)
    assert first.returncode != 0
    assert "REMOVE_CLEANUP_PENDING" in first.stderr
    assert "firewall enforcement removed" not in first.stdout
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    recorded = _recorded(calls)
    assert "-D FORWARD -j MY_PA_DATA_PLANE" in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = ""
    calls.write_text("", encoding="utf-8")
    second = _run("remove", environment)
    assert second.returncode == 0, second.stderr
    assert "firewall enforcement removed" in second.stdout
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    resumed = _recorded(calls)
    assert "-D FORWARD -j MY_PA_DATA_PLANE" not in resumed
    assert "-F MY_PA_DATA_PLANE" in resumed
    assert "-X MY_PA_DATA_PLANE" in resumed


@pytest.mark.parametrize(
    ("forward", "chain", "broad"),
    [
        ("extra", "exact", "absent"),
        ("after_dsm", "exact", "absent"),
        ("legacy", "foreign", "present"),
        ("legacy", "partial", "present"),
        ("legacy", "exact", "duplicate"),
        ("effective", "empty", "absent"),
    ],
)
def test_r3_t5_ambiguous_cleanup_pending_refuses_chain_delete(
    tmp_path: Path, forward: str, chain: str, broad: str
) -> None:
    environment, _state, calls = _environment(tmp_path, forward=forward, chain=chain, broad=broad)
    _confirm(environment)
    result = _run("remove", environment)
    assert result.returncode != 0
    assert "firewall enforcement removed" not in result.stdout
    recorded = _recorded(calls)
    assert "-X MY_PA_DATA_PLANE" not in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded


def test_r3_t6_absence_unverified_then_legacy_missing_is_cleanup_complete(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="exact", broad="absent"
    )
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "once-after-chain-delete"
    first = _run("remove", environment)
    assert first.returncode != 0
    assert "POSTCONDITION_UNVERIFIED" in first.stderr
    assert "firewall enforcement removed" not in first.stdout
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    recorded = _recorded(calls)
    assert "-X MY_PA_DATA_PLANE" in recorded
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = ""
    calls.write_text("", encoding="utf-8")
    second = _run("remove", environment)
    assert second.returncode == 0, second.stderr
    assert "firewall enforcement removed" in second.stdout
    resumed = _recorded(calls)
    assert "-X MY_PA_DATA_PLANE" not in resumed
    assert "-F MY_PA_DATA_PLANE" not in resumed
    assert "-D FORWARD -j MY_PA_DATA_PLANE" not in resumed


def test_r3_t8_flush_ok_delete_fail_then_empty_cleanup_deletes_only(
    tmp_path: Path,
) -> None:
    environment, state, calls = _environment(
        tmp_path, forward="effective", chain="exact", broad="absent"
    )
    _confirm(environment)
    environment["FAKE_X_FAIL"] = "1"
    first = _run("remove", environment)
    assert first.returncode != 0
    assert "REMOVE_CLEANUP_PENDING" in first.stderr
    assert "firewall enforcement removed" not in first.stdout
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"
    recorded = _recorded(calls)
    assert "-F MY_PA_DATA_PLANE" in recorded
    assert "-X MY_PA_DATA_PLANE" in recorded
    environment["FAKE_X_FAIL"] = "0"
    calls.write_text("", encoding="utf-8")
    second = _run("remove", environment)
    assert second.returncode == 0, second.stderr
    assert "firewall enforcement removed" in second.stdout
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "missing"
    resumed = _recorded(calls)
    assert "-F MY_PA_DATA_PLANE" not in resumed
    assert "-X MY_PA_DATA_PLANE" in resumed
    assert "-D FORWARD -j MY_PA_DATA_PLANE" not in resumed


@pytest.mark.parametrize(
    ("forward", "chain", "broad", "save_mode"),
    [
        ("legacy", "empty", "absent", ""),
        ("legacy", "empty", "duplicate", ""),
        ("extra", "empty", "absent", ""),
        ("effective", "empty", "absent", ""),
        ("legacy", "partial", "present", ""),
        ("legacy", "foreign", "present", ""),
        ("legacy", "empty", "present", "always"),
    ],
)
def test_r3_t9_empty_cleanup_ambiguity_refuses_delete(
    tmp_path: Path, forward: str, chain: str, broad: str, save_mode: str
) -> None:
    environment, _state, calls = _environment(tmp_path, forward=forward, chain=chain, broad=broad)
    _confirm(environment)
    if save_mode:
        environment["FAKE_FILTER_SAVE_FAIL_MODE"] = save_mode
        environment["FAKE_FILTER_SAVE_FAIL_AT"] = "1"
    result = _run("remove", environment)
    assert result.returncode != 0
    assert "firewall enforcement removed" not in result.stdout
    assert "-X MY_PA_DATA_PLANE" not in _recorded(calls)


def test_r3_apply_still_activates_missing_jump_and_populates_empty(
    tmp_path: Path,
) -> None:
    environment, state, _calls = _environment(
        tmp_path / "missing-jump", forward="legacy", chain="exact", broad="present"
    )
    _confirm(environment)
    applied = _run("apply", environment)
    assert applied.returncode == 0, applied.stderr
    assert "firewall enforcement admitted" in applied.stdout
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"

    environment, state, calls = _environment(
        tmp_path / "empty", forward="legacy", chain="empty", broad="present"
    )
    _confirm(environment)
    applied = _run("apply", environment)
    assert applied.returncode == 0, applied.stderr
    recorded = _recorded(calls)
    assert "-A MY_PA_DATA_PLANE" in recorded
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"


def test_r3_create_unverified_does_not_populate_or_delete(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "once-after-create"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "POSTCONDITION_UNVERIFIED" in result.stderr
    assert "failed to create MY_PA_DATA_PLANE" not in result.stderr
    assert "rollback succeeded" not in result.stderr
    assert "ROLLBACK_FAILED" not in result.stderr
    recorded = _recorded(calls)
    assert "-N MY_PA_DATA_PLANE" in recorded
    assert "-A MY_PA_DATA_PLANE" not in recorded
    assert "-I FORWARD" not in recorded
    assert "-F MY_PA_DATA_PLANE" not in recorded
    assert "-X MY_PA_DATA_PLANE" not in recorded
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "empty"


def test_r3_pre_insert_save_fail_does_not_install_jump(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "once-after-p4"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "POSTCONDITION_UNVERIFIED" in result.stderr
    assert "firewall enforcement admitted" not in result.stdout
    recorded = _recorded(calls)
    assert "-A MY_PA_DATA_PLANE -j RETURN" in recorded
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" not in recorded
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "legacy"
    assert state.joinpath("chain").read_text(encoding="utf-8").strip() == "exact"


def test_r3_post_broad_delete_save_fail_does_not_undo_jump(tmp_path: Path) -> None:
    environment, state, calls = _environment(tmp_path)
    _confirm(environment)
    environment["FAKE_FILTER_SAVE_FAIL_MODE"] = "once-after-broad-delete"
    result = _run("apply", environment)
    assert result.returncode != 0
    assert "POSTCONDITION_UNVERIFIED" in result.stderr
    assert "firewall enforcement admitted" not in result.stdout
    recorded = _recorded(calls)
    assert "-I FORWARD 1 -j MY_PA_DATA_PLANE" in recorded
    assert f"-D FORWARD_FIREWALL -s {SUBNET} -j RETURN" in recorded
    assert "-D FORWARD -j MY_PA_DATA_PLANE" not in recorded
    assert state.joinpath("forward").read_text(encoding="utf-8").strip() == "effective"
    assert state.joinpath("broad").read_text(encoding="utf-8").strip() == "absent"
