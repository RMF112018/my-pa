#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 check|plan|apply|remove" >&2
  exit 64
fi

action=$1
network_name=my-pa-nas-contract_data-plane
project_name=my-pa-nas-contract
logical_network=data-plane
: "${MY_PA_NAS_DOCKER:=/usr/local/bin/docker}"
: "${MY_PA_NAS_IPTABLES:=/usr/bin/iptables}"
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

docker_bin=$(resolve_tool "$MY_PA_NAS_DOCKER" Docker)
iptables_bin=$(resolve_tool "$MY_PA_NAS_IPTABLES" iptables)
ip_bin=$(resolve_tool "$MY_PA_NAS_IP" ip)

network_state=$(
  "$docker_bin" network inspect --format \
    '{{.Id}}|{{.Name}}|{{.Driver}}|{{.Scope}}|{{.Internal}}|{{index .Labels "com.docker.compose.project"}}|{{index .Labels "com.docker.compose.network"}}|{{(index .IPAM.Config 0).Subnet}}' \
    "$network_name"
) || {
  echo "canonical data-plane network is unavailable" >&2
  exit 1
}

old_ifs=$IFS
IFS='|'
read -r network_id actual_name driver scope internal project logical subnet <<EOF
$network_state
EOF
IFS=$old_ifs

printf '%s\n' "$network_id" | grep -Eq '^[0-9a-f]{64}$' || {
  echo "canonical data-plane network ID is invalid" >&2
  exit 1
}
printf '%s\n' "$subnet" | grep -Eq '^([0-9]{1,3}[.]){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$' || {
  echo "canonical data-plane subnet is invalid" >&2
  exit 1
}
[ "$subnet" != 0.0.0.0/0 ] || {
  echo "canonical data-plane subnet is unbounded" >&2
  exit 1
}
if [ "$actual_name" != "$network_name" ] || [ "$driver" != bridge ] || \
   [ "$scope" != local ] || [ "$internal" != true ] || \
   [ "$project" != "$project_name" ] || [ "$logical" != "$logical_network" ]; then
  echo "canonical data-plane network identity mismatch" >&2
  exit 1
fi

bridge="docker-$(printf '%s\n' "$network_id" | cut -c1-8)"
"$ip_bin" link show dev "$bridge" >/dev/null 2>&1 || {
  echo "Synology data-plane bridge is unavailable: $bridge" >&2
  exit 1
}

rules=$("$iptables_bin" -S) || {
  echo "iptables inspection failed; root firewall authority is required" >&2
  exit 1
}
firewall_jump=$(printf '%s\n' "$rules" | awk '$0 == "-A FORWARD -j FORWARD_FIREWALL" {print NR; exit}')
docker_jump=$(printf '%s\n' "$rules" | awk '$0 == "-A FORWARD -j DEFAULT_FORWARD" {print NR; exit}')
case "$firewall_jump:$docker_jump" in
  *[!0-9:]*|:*|*:) echo "Synology FORWARD chain identity mismatch" >&2; exit 1 ;;
esac
[ "$firewall_jump" -lt "$docker_jump" ] || {
  echo "Synology firewall does not precede Docker forwarding as expected" >&2
  exit 1
}
"$iptables_bin" -C DEFAULT_FORWARD -i "$bridge" -o "$bridge" -j ACCEPT >/dev/null 2>&1 || {
  echo "Docker same-bridge ACCEPT rule is unavailable" >&2
  exit 1
}

# Synology's iptables 1.8 renderer canonicalizes address matches before
# interface matches regardless of insertion argument order.
exact_rule="-A FORWARD_FIREWALL -s $subnet -d $subnet -i $bridge -o $bridge -j RETURN"

rule_present() {
  "$iptables_bin" -C FORWARD_FIREWALL \
    -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN \
    >/dev/null 2>&1
}

rule_state() {
  chain_rules=$("$iptables_bin" -S FORWARD_FIREWALL) || {
    echo "Synology data-plane firewall rule inspection failed" >&2
    return 1
  }
  exact_count=$(printf '%s\n' "$chain_rules" | awk -v exact="$exact_rule" '$0 == exact {count++} END {print count + 0}')
  first_rule=$(printf '%s\n' "$chain_rules" | awk '$1 == "-A" && $2 == "FORWARD_FIREWALL" {print; exit}')
  case "$exact_count:$first_rule" in
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
      echo "Synology data-plane firewall rule is already admitted for $network_name"
    else
      echo "Synology data-plane firewall rule requires admission for $network_name on $bridge ($subnet): $state"
    fi
    ;;
  check)
    state=$(rule_state)
    [ "$state" = effective ] || {
      echo "Synology data-plane firewall rule is not effective: $state" >&2
      exit 1
    }
    echo "Synology data-plane firewall gate passed"
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
        "$iptables_bin" -I FORWARD_FIREWALL 1 \
          -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN
        if [ "$(rule_state)" != effective ]; then
          if ! "$iptables_bin" -D FORWARD_FIREWALL \
            -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN; then
            echo "Synology data-plane firewall admission failed and exact rollback failed" >&2
            exit 1
          fi
          if rule_present; then
            echo "Synology data-plane firewall admission failed and rollback left the exact rule present" >&2
            exit 1
          fi
          echo "Synology data-plane firewall admission failed; inserted rule was rolled back" >&2
          exit 1
        fi
        ;;
      *)
        echo "Synology data-plane firewall state requires explicit removal before apply: $state" >&2
        exit 1
        ;;
    esac
    echo "Synology data-plane firewall rule admitted"
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
        echo "one exact Synology data-plane firewall rule is not present: $state" >&2
        exit 1
        ;;
    esac
    "$iptables_bin" -D FORWARD_FIREWALL \
      -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" -j RETURN
    if rule_present; then
      echo "Synology data-plane firewall rule removal failed" >&2
      exit 1
    fi
    echo "Synology data-plane firewall rule removed"
    ;;
  *)
    echo "usage: $0 check|plan|apply|remove" >&2
    exit 64
    ;;
esac
