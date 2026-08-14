#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 check|plan|apply|remove" >&2
  exit 64
fi

action=$1
network_name=my-pa-remote-mcp_cloudflare-egress
project_name=my-pa-remote-mcp
logical_network=cloudflare-egress
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

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker_bin=$(resolve_tool "$MY_PA_NAS_DOCKER" Docker)
iptables_bin=$(resolve_tool "$MY_PA_NAS_IPTABLES" iptables)
ip_bin=$(resolve_tool "$MY_PA_NAS_IP" ip)

if [ "$action" != remove ]; then
  "$script_dir/synology-data-plane-firewall.sh" check >/dev/null
  "$script_dir/synology-ingress-plane-firewall.sh" check >/dev/null
fi

network_state=$(
  "$docker_bin" network inspect --format \
    '{{.Id}}|{{.Name}}|{{.Driver}}|{{.Scope}}|{{.Internal}}|{{index .Labels "com.docker.compose.project"}}|{{index .Labels "com.docker.compose.network"}}|{{(index .IPAM.Config 0).Subnet}}' \
    "$network_name"
) || {
  echo "canonical Cloudflare egress network is unavailable" >&2
  exit 1
}

old_ifs=$IFS
IFS='|'
read -r network_id actual_name driver scope internal project logical subnet <<EOF
$network_state
EOF
IFS=$old_ifs

printf '%s\n' "$network_id" | grep -Eq '^[0-9a-f]{64}$' || {
  echo "canonical Cloudflare egress network ID is invalid" >&2
  exit 1
}
printf '%s\n' "$subnet" | grep -Eq '^([0-9]{1,3}[.]){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$' || {
  echo "canonical Cloudflare egress subnet is invalid" >&2
  exit 1
}
[ "$subnet" != 0.0.0.0/0 ] || {
  echo "canonical Cloudflare egress subnet is unbounded" >&2
  exit 1
}
if [ "$actual_name" != "$network_name" ] || [ "$driver" != bridge ] || \
   [ "$scope" != local ] || [ "$internal" != false ] || \
   [ "$project" != "$project_name" ] || [ "$logical" != "$logical_network" ]; then
  echo "canonical Cloudflare egress network identity mismatch" >&2
  exit 1
fi

bridge="docker-$(printf '%s\n' "$network_id" | cut -c1-8)"
"$ip_bin" link show dev "$bridge" >/dev/null 2>&1 || {
  echo "Synology Cloudflare egress bridge is unavailable: $bridge" >&2
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
nat_rule="-A DEFAULT_POSTROUTING -s $subnet ! -o $bridge -j MASQUERADE"
nat_rules=$("$iptables_bin" -t nat -S DEFAULT_POSTROUTING) || {
  echo "Docker Cloudflare egress masquerade rule inspection failed" >&2
  exit 1
}
nat_exact_count=$(printf '%s\n' "$nat_rules" | awk -v exact="$nat_rule" \
  '$0 == exact {count++} END {print count + 0}')
nat_scope_count=$(printf '%s\n' "$nat_rules" | awk -v subnet="$subnet" -v bridge="$bridge" '
  {
    source = 0
    output = 0
    for (field = 1; field < NF; field++) {
      if ($field == "-s" && $(field + 1) == subnet) source = 1
      if ($field == "-o" && $(field + 1) == bridge) output = 1
    }
    if (source || output) count++
  }
  END {print count + 0}')
[ "$nat_exact_count:$nat_scope_count" = 1:1 ] || {
  echo "Docker Cloudflare egress masquerade rule identity mismatch" >&2
  exit 1
}

rule_dns_udp="-A FORWARD_FIREWALL -s $subnet -i $bridge -p udp -m udp --dport 53 -j RETURN"
rule_dns_tcp="-A FORWARD_FIREWALL -s $subnet -i $bridge -p tcp -m tcp --dport 53 -j RETURN"
rule_quic="-A FORWARD_FIREWALL -s $subnet -i $bridge -p udp -m udp --dport 7844 -j RETURN"
rule_tls="-A FORWARD_FIREWALL -s $subnet -i $bridge -p tcp -m multiport --dports 443,7844 -j RETURN"

rule_state() {
  chain_rules=$("$iptables_bin" -S FORWARD_FIREWALL) || {
    echo "Synology Cloudflare egress firewall rule inspection failed" >&2
    return 1
  }
  counts=""
  exact_total=0
  for exact in "$rule_dns_udp" "$rule_dns_tcp" "$rule_quic" "$rule_tls"; do
    count=$(printf '%s\n' "$chain_rules" | awk -v exact="$exact" '$0 == exact {count++} END {print count + 0}')
    counts="${counts}${counts:+:}${count}"
    exact_total=$((exact_total + count))
  done
  network_scope_count=$(printf '%s\n' "$chain_rules" | awk -v subnet="$subnet" -v bridge="$bridge" '
    {
      source = 0
      ingress = 0
      for (field = 1; field < NF; field++) {
        if ($field == "-s" && $(field + 1) == subnet) source = 1
        if ($field == "-i" && $(field + 1) == bridge) ingress = 1
      }
      if (source || ingress) count++
    }
    END {print count + 0}')
  positions=$(printf '%s\n' "$chain_rules" | awk \
    '$1 == "-A" && $2 == "FORWARD_FIREWALL" {count++; if (count >= 3 && count <= 6) print}')
  expected=$(printf '%s\n%s\n%s\n%s\n' "$rule_dns_udp" "$rule_dns_tcp" "$rule_quic" "$rule_tls")
  case "$counts" in
    0:0:0:0)
      if [ "$network_scope_count" -eq 0 ]; then echo missing; else echo foreign; fi
      ;;
    1:1:1:1)
      if [ "$network_scope_count" -ne 4 ]; then
        echo foreign
      elif [ "$positions" = "$expected" ]; then
        echo effective
      else
        echo recoverable_exact_drift
      fi
      ;;
    *)
      if [ "$network_scope_count" -eq "$exact_total" ]; then
        echo recoverable_exact_drift
      else
        echo foreign
      fi
      ;;
  esac
}

delete_all_exact_rules() {
  for arguments in \
    'tcp|-m|multiport|--dports|443,7844' \
    'udp|-m|udp|--dport|7844' \
    'tcp|-m|tcp|--dport|53' \
    'udp|-m|udp|--dport|53'
  do
    old_ifs=$IFS
    IFS='|'
    set -- $arguments
    IFS=$old_ifs
    deletions=0
    while "$iptables_bin" -C FORWARD_FIREWALL -s "$subnet" -i "$bridge" \
      -p "$1" "$2" "$3" "$4" "$5" -j RETURN >/dev/null 2>&1
    do
      [ "$deletions" -lt 8 ] || {
        echo "Synology Cloudflare egress exact-rule deletion bound exceeded" >&2
        return 1
      }
      "$iptables_bin" -D FORWARD_FIREWALL -s "$subnet" -i "$bridge" \
        -p "$1" "$2" "$3" "$4" "$5" -j RETURN >/dev/null 2>&1 || return 1
      deletions=$((deletions + 1))
    done
  done
}

case "$action" in
  plan)
    state=$(rule_state)
    if [ "$state" = effective ]; then
      echo "Synology Cloudflare egress firewall rules are already admitted for $network_name"
    else
      echo "Synology Cloudflare egress firewall rules require admission for $network_name on $bridge ($subnet): $state"
    fi
    ;;
  check)
    state=$(rule_state)
    [ "$state" = effective ] || {
      echo "Synology Cloudflare egress firewall rules are not effective: $state" >&2
      exit 1
    }
    echo "Synology Cloudflare egress firewall gate passed"
    ;;
  apply)
    [ "$(id -u)" -eq 0 ] || { echo "firewall mutation requires root" >&2; exit 1; }
    [ "${MY_PA_CONFIRM_FIREWALL_MUTATION:-}" = "$network_name" ] || {
      echo "set MY_PA_CONFIRM_FIREWALL_MUTATION=$network_name to admit the exact rules" >&2
      exit 1
    }
    state=$(rule_state)
    case "$state" in
      effective) ;;
      missing)
        if ! "$iptables_bin" -I FORWARD_FIREWALL 3 -s "$subnet" -i "$bridge" \
          -p udp -m udp --dport 53 -j RETURN || \
           ! "$iptables_bin" -I FORWARD_FIREWALL 4 -s "$subnet" -i "$bridge" \
          -p tcp -m tcp --dport 53 -j RETURN || \
           ! "$iptables_bin" -I FORWARD_FIREWALL 5 -s "$subnet" -i "$bridge" \
          -p udp -m udp --dport 7844 -j RETURN || \
           ! "$iptables_bin" -I FORWARD_FIREWALL 6 -s "$subnet" -i "$bridge" \
          -p tcp -m multiport --dports 443,7844 -j RETURN; then
          rollback_status=0
          delete_all_exact_rules || rollback_status=1
          rollback_state=$(rule_state) || rollback_status=1
          [ "$rollback_status" -eq 0 ] && [ "$rollback_state" = missing ] || {
            echo "Synology Cloudflare egress admission failed and rollback left rule drift" >&2
            exit 1
          }
          echo "Synology Cloudflare egress admission failed; inserted rules were rolled back" >&2
          exit 1
        fi
        if [ "$(rule_state)" != effective ]; then
          rollback_status=0
          delete_all_exact_rules || rollback_status=1
          rollback_state=$(rule_state) || rollback_status=1
          [ "$rollback_status" -eq 0 ] && [ "$rollback_state" = missing ] || {
            echo "Synology Cloudflare egress admission failed and rollback left rule drift" >&2
            exit 1
          }
          echo "Synology Cloudflare egress admission failed; inserted rules were rolled back" >&2
          exit 1
        fi
        ;;
      *)
        echo "Synology Cloudflare egress firewall state requires explicit removal before apply: $state" >&2
        exit 1
        ;;
    esac
    echo "Synology Cloudflare egress firewall rules admitted"
    ;;
  remove)
    [ "$(id -u)" -eq 0 ] || { echo "firewall mutation requires root" >&2; exit 1; }
    [ "${MY_PA_CONFIRM_FIREWALL_MUTATION:-}" = "$network_name" ] || {
      echo "set MY_PA_CONFIRM_FIREWALL_MUTATION=$network_name to remove the exact rules" >&2
      exit 1
    }
    state=$(rule_state)
    case "$state" in
      missing) echo "Synology Cloudflare egress firewall rules are already absent"; exit 0 ;;
      effective|recoverable_exact_drift) ;;
      *)
        echo "Synology Cloudflare egress firewall state contains foreign rules: $state" >&2
        exit 1
        ;;
    esac
    delete_all_exact_rules || {
      echo "Synology Cloudflare egress firewall rule removal failed" >&2
      exit 1
    }
    [ "$(rule_state)" = missing ] || {
      echo "Synology Cloudflare egress firewall rule removal left drift" >&2
      exit 1
    }
    echo "Synology Cloudflare egress firewall rules removed"
    ;;
  *)
    echo "usage: $0 check|plan|apply|remove" >&2
    exit 64
    ;;
esac
