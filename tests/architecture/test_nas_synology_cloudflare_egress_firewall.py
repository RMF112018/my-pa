# ruff: noqa: E501, S603 - executable fake-tool contracts are intentionally literal.

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops/nas/synology-cloudflare-egress-firewall.sh"
NETWORK = "my-pa-remote-mcp_cloudflare-egress"
SUBNET = "172.26.0.0/16"
BRIDGE = "docker-12345678"


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _scene(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    scripts = tmp_path / "ops" / "nas"
    scripts.mkdir(parents=True)
    copied = scripts / SCRIPT.name
    shutil.copy2(SCRIPT, copied)
    for prerequisite in (
        "synology-data-plane-firewall.sh",
        "synology-ingress-plane-firewall.sh",
    ):
        _write(scripts / prerequisite, "#!/bin/sh\nexit 0\n")
    tools = tmp_path / "tools"
    tools.mkdir()
    state = tmp_path / "state"
    state.write_text("missing", encoding="utf-8")
    _write(
        tools / "docker",
        """#!/bin/sh
if [ "$1 $2" != "network inspect" ]; then exit 1; fi
printf '%s\n' "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef|my-pa-remote-mcp_cloudflare-egress|bridge|local|${FAKE_INTERNAL:-false}|my-pa-remote-mcp|cloudflare-egress|172.26.0.0/16"
""",
    )
    _write(tools / "ip", "#!/bin/sh\nexit 0\n")
    _write(tools / "id", '#!/bin/sh\n[ "$1" = -u ] && echo 0\n')
    _write(
        tools / "iptables",
        f"""#!/bin/sh
state_file=${{FAKE_STATE:?}}
if [ "$1" = -t ]; then exit 0; fi
if [ "$1" = -S ] && [ "$#" -eq 1 ]; then
  printf '%s\n' '-A FORWARD -j FORWARD_FIREWALL' '-A FORWARD -j DEFAULT_FORWARD'
  exit 0
fi
if [ "$1 $2" = '-S FORWARD_FIREWALL' ]; then
  printf '%s\n' '-N FORWARD_FIREWALL'
  printf '%s\n' '-A FORWARD_FIREWALL -s 172.22.0.0/16 -d 172.22.0.0/16 -i docker-data -o docker-data -j RETURN'
  printf '%s\n' '-A FORWARD_FIREWALL -s 172.18.0.0/16 -d 172.18.0.0/16 -i docker-ingress -o docker-ingress -j RETURN'
  case "$(cat "$state_file")" in
    effective)
      printf '%s\n' \
        '-A FORWARD_FIREWALL -s {SUBNET} -i {BRIDGE} -p udp -m udp --dport 53 -j RETURN' \
        '-A FORWARD_FIREWALL -s {SUBNET} -i {BRIDGE} -p tcp -m tcp --dport 53 -j RETURN' \
        '-A FORWARD_FIREWALL -s {SUBNET} -i {BRIDGE} -p udp -m udp --dport 7844 -j RETURN' \
        '-A FORWARD_FIREWALL -s {SUBNET} -i {BRIDGE} -p tcp -m multiport --dports 443,7844 -j RETURN'
      ;;
    partial)
      printf '%s\n' '-A FORWARD_FIREWALL -s {SUBNET} -i {BRIDGE} -p udp -m udp --dport 53 -j RETURN'
      ;;
  esac
  printf '%s\n' '-A FORWARD_FIREWALL -j DROP'
  exit 0
fi
if [ "$1" = -I ]; then
  count_file="$state_file.count"
  count=0
  [ ! -f "$count_file" ] || count=$(cat "$count_file")
  count=$((count + 1))
  printf '%s' "$count" > "$count_file"
  [ "$count" -ne 4 ] || printf '%s' effective > "$state_file"
  exit 0
fi
if [ "$1" = -D ]; then
  count_file="$state_file.delete"
  count=0
  [ ! -f "$count_file" ] || count=$(cat "$count_file")
  count=$((count + 1))
  printf '%s' "$count" > "$count_file"
  [ "$count" -ne 4 ] || printf '%s' missing > "$state_file"
  exit 0
fi
exit 1
""",
    )
    environment = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "MY_PA_NAS_DOCKER": str(tools / "docker"),
        "MY_PA_NAS_IPTABLES": str(tools / "iptables"),
        "MY_PA_NAS_IP": str(tools / "ip"),
        "FAKE_STATE": str(state),
    }
    return copied, environment, state


def _run(
    script: Path, action: str, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), action],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_exact_rules_apply_check_and_remove(tmp_path: Path) -> None:
    script, environment, state = _scene(tmp_path)
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = NETWORK
    assert _run(script, "plan", environment).returncode == 0
    applied = _run(script, "apply", environment)
    assert applied.returncode == 0, applied.stderr
    assert state.read_text() == "effective"
    checked = _run(script, "check", environment)
    assert checked.returncode == 0, checked.stderr
    removed = _run(script, "remove", environment)
    assert removed.returncode == 0, removed.stderr
    assert state.read_text() == "missing"


def test_identity_drift_and_partial_rules_fail_closed(tmp_path: Path) -> None:
    script, environment, state = _scene(tmp_path)
    environment["FAKE_INTERNAL"] = "true"
    assert _run(script, "check", environment).returncode != 0
    environment["FAKE_INTERNAL"] = "false"
    environment["MY_PA_CONFIRM_FIREWALL_MUTATION"] = NETWORK
    state.write_text("partial")
    result = _run(script, "apply", environment)
    assert result.returncode != 0
    assert "explicit removal" in result.stderr


def test_contract_is_port_bounded_and_runbook_orders_the_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--dport 53" in source
    assert "--dport 7844" in source
    assert "--dports 443,7844" in source
    assert "-I FORWARD_FIREWALL 3" in source
    assert "0.0.0.0/0" not in source.split("exact_rule", 1)[-1]
    runbook = (ROOT / "ops/runbooks/remote-mcp-cloudflare.md").read_text(encoding="utf-8")
    create = runbook.index("--profile remote-edge create cloudflared")
    check = runbook.index("synology-cloudflare-egress-firewall.sh check", create)
    start = runbook.index("--profile remote-edge up -d --no-build", check)
    assert create < check < start
