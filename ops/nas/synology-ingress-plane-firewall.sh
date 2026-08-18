#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 check|plan|apply|remove" >&2
  exit 64
fi

action=$1
network_name=my-pa-nas-contract_ingress-plane
project_name=my-pa-nas-contract
logical_network=ingress-plane
: "${MY_PA_NAS_DOCKER:=/usr/local/bin/docker}"
: "${MY_PA_NAS_IPTABLES:=/usr/bin/iptables}"
: "${MY_PA_NAS_IPTABLES_SAVE:=}"
: "${MY_PA_NAS_IP:=/usr/bin/ip}"

resolve_tool() {
  value=$1
  label=$2
  case "$value" in
    /*) resolved=$value ;;
    *) resolved=$(command -v "$value" 2>/dev/null) || {
      echo "$label executable is unavailable" >&2
      return 1
    } ;;
  esac
  [ -x "$resolved" ] || {
    echo "$label executable is unavailable: $resolved" >&2
    return 1
  }
  printf '%s\n' "$resolved"
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker_bin=$(resolve_tool "$MY_PA_NAS_DOCKER" Docker)
iptables_bin=$(resolve_tool "$MY_PA_NAS_IPTABLES" iptables)
ip_bin=$(resolve_tool "$MY_PA_NAS_IP" ip)
if [ -n "$MY_PA_NAS_IPTABLES_SAVE" ]; then
  iptables_save_bin=$(resolve_tool "$MY_PA_NAS_IPTABLES_SAVE" iptables-save)
else
  iptables_dir=$(dirname -- "$iptables_bin")
  if [ -x "$iptables_dir/iptables-save" ]; then
    iptables_save_bin=$iptables_dir/iptables-save
  else
    iptables_save_bin=$(resolve_tool iptables-save iptables-save)
  fi
fi

# The ingress allowance is deliberately subordinate to the canonical data-plane
# MY_PA-first enforcement. Mutating or accepting an ingress rule never weakens
# that gate.
if [ "$action" != remove ]; then
  "$script_dir/synology-data-plane-firewall.sh" check >/dev/null
fi

network_state=$(
  "$docker_bin" network inspect --format \
    '{{.Id}}|{{.Name}}|{{.Driver}}|{{.Scope}}|{{.Internal}}|{{index .Labels "com.docker.compose.project"}}|{{index .Labels "com.docker.compose.network"}}|{{(index .IPAM.Config 0).Subnet}}' \
    "$network_name"
) || {
  echo "canonical ingress-plane network is unavailable" >&2
  exit 1
}

old_ifs=$IFS
IFS='|'
read -r network_id actual_name driver scope internal project logical subnet <<EOF
$network_state
EOF
IFS=$old_ifs

printf '%s\n' "$network_id" | grep -Eq '^[0-9a-f]{64}$' || {
  echo "canonical ingress-plane network ID is invalid" >&2
  exit 1
}
printf '%s\n' "$subnet" | grep -Eq '^([0-9]{1,3}[.]){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$' || {
  echo "canonical ingress-plane subnet is invalid" >&2
  exit 1
}
[ "$subnet" != 0.0.0.0/0 ] || {
  echo "canonical ingress-plane subnet is unbounded" >&2
  exit 1
}
if [ "$actual_name" != "$network_name" ] || [ "$driver" != bridge ] || \
   [ "$scope" != local ] || [ "$internal" != true ] || \
   [ "$project" != "$project_name" ] || [ "$logical" != "$logical_network" ]; then
  echo "canonical ingress-plane network identity mismatch" >&2
  exit 1
fi

bridge="docker-$(printf '%s\n' "$network_id" | cut -c1-8)"
"$ip_bin" link show dev "$bridge" >/dev/null 2>&1 || {
  echo "Synology ingress-plane bridge is unavailable: $bridge" >&2
  exit 1
}

# Shared data-plane FORWARD identity: MY_PA_DATA_PLANE then FORWARD_FIREWALL.
# Independent ingress same-bridge RETURN contract is unchanged below.
filter_save=$("$iptables_save_bin" -t filter) || {
  echo "iptables-save inspection failed; root firewall authority is required" >&2
  exit 1
}
first_forward=$(printf '%s\n' "$filter_save" | awk '$1 == "-A" && $2 == "FORWARD" {print; exit}')
second_forward=$(printf '%s\n' "$filter_save" | awk '$1 == "-A" && $2 == "FORWARD" {n++; if (n == 2) {print; exit}}')
my_pa_jumps=$(printf '%s\n' "$filter_save" | awk '$0 == "-A FORWARD -j MY_PA_DATA_PLANE" {count++} END {print count + 0}')
default_jumps=$(printf '%s\n' "$filter_save" | awk '$0 == "-A FORWARD -j DEFAULT_FORWARD" {count++} END {print count + 0}')
if [ "$first_forward" != "-A FORWARD -j MY_PA_DATA_PLANE" ] || \
   [ "$second_forward" != "-A FORWARD -j FORWARD_FIREWALL" ] || \
   [ "$my_pa_jumps" -ne 1 ] || [ "$default_jumps" -ne 0 ]; then
  echo "Synology FORWARD chain identity mismatch" >&2
  exit 1
fi

exact_rule="-A FORWARD_FIREWALL -s $subnet -d $subnet -i $bridge -o $bridge -j RETURN"

rule_present() {
  "$iptables_bin" -C FORWARD_FIREWALL \
    -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN \
    >/dev/null 2>&1
}

rule_state() {
  chain_rules=$("$iptables_bin" -S FORWARD_FIREWALL) || {
    echo "Synology ingress-plane firewall rule inspection failed" >&2
    return 1
  }
  exact_count=$(printf '%s\n' "$chain_rules" | awk -v exact="$exact_rule" '$0 == exact {count++} END {print count + 0}')
  second_rule=$(printf '%s\n' "$chain_rules" | awk '$1 == "-A" && $2 == "FORWARD_FIREWALL" {count++; if (count == 2) {print; exit}}')
  case "$exact_count:$second_rule" in
    0:*) echo missing ;;
    1:"$exact_rule") echo effective ;;
    1:*) echo misordered ;;
    *) echo duplicate ;;
  esac
}

case "$action" in
  plan)
    state=$(rule_state)
    if [ "$state" = effective ]; then
      echo "Synology ingress-plane firewall rule is already admitted for $network_name"
    else
      echo "Synology ingress-plane firewall rule requires admission for $network_name on $bridge ($subnet): $state"
    fi
    ;;
  check)
    state=$(rule_state)
    [ "$state" = effective ] || {
      echo "Synology ingress-plane firewall rule is not effective: $state" >&2
      exit 1
    }
    echo "Synology ingress-plane firewall gate passed"
    ;;
  apply)
    [ "$(id -u)" -eq 0 ] || {
      echo "firewall mutation requires root" >&2
      exit 1
    }
    [ "${MY_PA_CONFIRM_FIREWALL_MUTATION:-}" = "$network_name" ] || {
      echo "set MY_PA_CONFIRM_FIREWALL_MUTATION=$network_name to admit the exact rule" >&2
      exit 1
    }
    state=$(rule_state)
    case "$state" in
      effective) ;;
      missing)
        "$iptables_bin" -I FORWARD_FIREWALL 2 \
          -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN
        if [ "$(rule_state)" != effective ]; then
          if ! "$iptables_bin" -D FORWARD_FIREWALL \
            -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN; then
            echo "Synology ingress-plane firewall admission failed and exact rollback failed" >&2
            exit 1
          fi
          if rule_present; then
            echo "Synology ingress-plane firewall admission failed and rollback left the exact rule present" >&2
            exit 1
          fi
          echo "Synology ingress-plane firewall admission failed; inserted rule was rolled back" >&2
          exit 1
        fi
        ;;
      *)
        echo "Synology ingress-plane firewall state requires explicit removal before apply: $state" >&2
        exit 1
        ;;
    esac
    echo "Synology ingress-plane firewall rule admitted"
    ;;
  remove)
    [ "$(id -u)" -eq 0 ] || {
      echo "firewall mutation requires root" >&2
      exit 1
    }
    [ "${MY_PA_CONFIRM_FIREWALL_MUTATION:-}" = "$network_name" ] || {
      echo "set MY_PA_CONFIRM_FIREWALL_MUTATION=$network_name to remove the exact rule" >&2
      exit 1
    }
    state=$(rule_state)
    case "$state" in
      effective|misordered) ;;
      *)
        echo "one exact Synology ingress-plane firewall rule is not present: $state" >&2
        exit 1
        ;;
    esac
    "$iptables_bin" -D FORWARD_FIREWALL \
      -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN
    if rule_present; then
      echo "Synology ingress-plane firewall rule removal failed" >&2
      exit 1
    fi
    echo "Synology ingress-plane firewall rule removed"
    ;;
  *)
    echo "usage: $0 check|plan|apply|remove" >&2
    exit 64
    ;;
esac
