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
enforcement_chain=MY_PA_DATA_PLANE
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

# Synology's iptables 1.8 renderer canonicalizes address matches before
# interface matches regardless of insertion argument order.
p1_rule="-A $enforcement_chain -s $subnet -d $subnet -i $bridge -o $bridge -j ACCEPT"
p2_rule="-A $enforcement_chain -i $bridge -j DROP"
p3_rule="-A $enforcement_chain -o $bridge -j DROP"
p4_rule="-A $enforcement_chain -j RETURN"
broad_return="-A FORWARD_FIREWALL -s $subnet -j RETURN"
negated_egress="-A $enforcement_chain -i $bridge ! -o $bridge -j DROP"
negated_ingress="-A $enforcement_chain ! -i $bridge -o $bridge -j DROP"
my_pa_jump="-A FORWARD -j $enforcement_chain"
firewall_jump="-A FORWARD -j FORWARD_FIREWALL"
default_jump="-A FORWARD -j DEFAULT_FORWARD"

filter_table() {
  "$iptables_save_bin" -t filter || {
    echo "iptables-save inspection failed; root firewall authority is required" >&2
    return 1
  }
}

forward_appends() {
  printf '%s\n' "$1" | awk '$1 == "-A" && $2 == "FORWARD" {print}'
}

chain_appends() {
  printf '%s\n' "$1" | awk -v chain="$enforcement_chain" \
    '$1 == "-A" && $2 == chain {print}'
}

forward_firewall_rules() {
  "$iptables_bin" -S FORWARD_FIREWALL || {
    echo "Synology data-plane firewall rule inspection failed" >&2
    return 1
  }
}

broad_return_count() {
  fw_rules=$(forward_firewall_rules) || return 1
  printf '%s\n' "$fw_rules" | awk -v exact="$broad_return" \
    '$0 == exact {count++} END {print count + 0}'
}

my_pa_forward_jump_count() {
  save=$(filter_table) || return 1
  forwards=$(forward_appends "$save")
  printf '%s\n' "$forwards" | awk -v exact="$my_pa_jump" \
    '$0 == exact {count++} END {print count + 0}'
}

chain_classification() {
  if ! chain_dump=$("$iptables_bin" -S "$enforcement_chain" 2>/dev/null); then
    echo missing
    return 0
  fi
  actual=$(chain_appends "$chain_dump")
  expected=$(printf '%s\n' "$p1_rule" "$p2_rule" "$p3_rule" "$p4_rule")
  if [ "$actual" = "$expected" ]; then
    echo exact
    return 0
  fi
  if [ -z "$actual" ]; then
    echo empty
    return 0
  fi
  printf '%s\n' "$actual" | awk -v neg_e="$negated_egress" -v neg_i="$negated_ingress" '
    $0 == neg_e || $0 == neg_i {found=1}
    END {exit found ? 0 : 1}
  ' && {
    echo negated-drop
    return 0
  }
  printf '%s\n' "$actual" | awk -v p1="$p1_rule" -v p2="$p2_rule" -v p3="$p3_rule" '
    $0 == p1 {has_p1=1}
    $0 == p2 {has_p2=1}
    $0 == p3 {has_p3=1}
    {n++}
    END {
      if (n > 4) {print "extra-rule"; exit}
      if (n != 4) {print "partial-chain"; exit}
      if (!has_p1) {print "missing-p1"; exit}
      if (!has_p2) {print "missing-i-drop"; exit}
      if (!has_p3) {print "missing-o-drop"; exit}
      print "foreign-chain"
    }
  '
}

enforcement_state() {
  save=$(filter_table) || return 1
  forwards=$(forward_appends "$save")
  forward_count=$(printf '%s\n' "$forwards" | awk 'NF {n++} END {print n + 0}')
  my_pa_jumps=$(printf '%s\n' "$forwards" | awk -v exact="$my_pa_jump" \
    '$0 == exact {count++} END {print count + 0}')
  default_jumps=$(printf '%s\n' "$forwards" | awk -v exact="$default_jump" \
    '$0 == exact {count++} END {print count + 0}')
  first=$(printf '%s\n' "$forwards" | awk 'NF {print; exit}')
  second=$(printf '%s\n' "$forwards" | awk 'NF {n++; if (n == 2) {print; exit}}')
  chain_state=$(chain_classification)
  broad_count=$(broad_return_count) || return 1

  if [ "$broad_count" -gt 1 ]; then
    echo duplicate-broad-return
    return 0
  fi
  if [ "$default_jumps" -gt 0 ]; then
    echo default-forward
    return 0
  fi
  if [ "$my_pa_jumps" -gt 1 ]; then
    echo duplicate-jump
    return 0
  fi
  if [ "$forward_count" -eq 0 ]; then
    echo policy-accept-only
    return 0
  fi
  if [ "$first" = "$firewall_jump" ] && [ "$second" = "$my_pa_jump" ]; then
    echo my-pa-after-dsm
    return 0
  fi
  if [ "$first" = "$firewall_jump" ] && [ "$forward_count" -eq 1 ]; then
    case "$chain_state" in
      missing|empty) echo legacy ;;
      exact) echo missing-jump ;;
      *) echo "$chain_state" ;;
    esac
    return 0
  fi
  if [ "$first" != "$my_pa_jump" ] || [ "$second" != "$firewall_jump" ]; then
    echo extra-forward
    return 0
  fi
  if [ "$forward_count" -ne 2 ]; then
    echo extra-forward
    return 0
  fi
  case "$chain_state" in
    missing) echo missing-chain ;;
    exact)
      if [ "$broad_count" -gt 0 ]; then
        echo broad-return
      else
        echo effective
      fi
      ;;
    *) echo "$chain_state" ;;
  esac
}

populate_enforcement_chain() {
  "$iptables_bin" -A "$enforcement_chain" \
    -s "$subnet" -d "$subnet" -i "$bridge" -o "$bridge" -j ACCEPT || return 1
  "$iptables_bin" -A "$enforcement_chain" -i "$bridge" -j DROP || return 1
  "$iptables_bin" -A "$enforcement_chain" -o "$bridge" -j DROP || return 1
  "$iptables_bin" -A "$enforcement_chain" -j RETURN || return 1
}

assert_no_my_pa_forward_jump() {
  jump_count=$(my_pa_forward_jump_count) || return 1
  [ "$jump_count" -eq 0 ] || {
    echo "refusing to mutate MY_PA_DATA_PLANE while FORWARD jump exists" >&2
    return 1
  }
}

delete_owned_chain() {
  assert_no_my_pa_forward_jump || return 1
  "$iptables_bin" -F "$enforcement_chain" || return 1
  "$iptables_bin" -X "$enforcement_chain" || return 1
  if "$iptables_bin" -S "$enforcement_chain" >/dev/null 2>&1; then
    echo "MY_PA_DATA_PLANE chain removal failed" >&2
    return 1
  fi
}

restore_empty_owned_chain() {
  assert_no_my_pa_forward_jump || return 1
  "$iptables_bin" -F "$enforcement_chain" || return 1
  [ "$(chain_classification)" = empty ] || {
    echo "failed to restore empty MY_PA_DATA_PLANE" >&2
    return 1
  }
}

restore_legacy_broad_return() {
  fw_rules=$(forward_firewall_rules) || return 1
  if printf '%s\n' "$fw_rules" | awk -v exact="$broad_return" \
    '$0 == exact {found=1} END {exit found ? 0 : 1}'; then
    restored=$(broad_return_count) || return 1
    [ "$restored" -eq 1 ] || {
      echo "duplicate source-only data-plane RETURN requires explicit removal" >&2
      return 1
    }
    return 0
  fi
  drop_pos=$(printf '%s\n' "$fw_rules" | awk '
    $1 == "-A" && $2 == "FORWARD_FIREWALL" {
      n++
      if ($0 == "-A FORWARD_FIREWALL -j DROP") {hits++; pos=n}
    }
    END {if (hits != 1) exit 1; print pos}
  ') || {
    echo "ambiguous rollback identity: unique FORWARD_FIREWALL DROP is unavailable" >&2
    return 1
  }
  "$iptables_bin" -I FORWARD_FIREWALL "$drop_pos" -s "$subnet" -j RETURN
  restored=$(broad_return_count) || return 1
  [ "$restored" -eq 1 ] || {
    echo "legacy source-only data-plane RETURN restore failed" >&2
    return 1
  }
}

case "$action" in
  plan)
    state=$(enforcement_state) || exit 1
    if [ "$state" = effective ]; then
      echo "Synology data-plane firewall enforcement is already admitted for $network_name"
    else
      echo "Synology data-plane firewall enforcement requires admission for $network_name on $bridge ($subnet): $state"
    fi
    ;;
  check)
    state=$(enforcement_state) || exit 1
    [ "$state" = effective ] || {
      echo "Synology data-plane firewall is not effective: $state" >&2
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
    state=$(enforcement_state) || exit 1
    case "$state" in
      effective) ;;
      legacy|missing-jump|broad-return|empty)
        population_mode=none
        chain_state=$(chain_classification)
        case "$chain_state" in
          missing)
            "$iptables_bin" -N "$enforcement_chain" || {
              echo "failed to create MY_PA_DATA_PLANE" >&2
              exit 1
            }
            population_mode=created
            if ! populate_enforcement_chain; then
              if ! delete_owned_chain; then
                echo "Synology data-plane enforcement chain population failed and owned chain cleanup failed" >&2
                exit 1
              fi
              echo "Synology data-plane enforcement chain population failed; owned chain was removed" >&2
              exit 1
            fi
            ;;
          empty)
            population_mode=emptied
            if ! populate_enforcement_chain; then
              if ! restore_empty_owned_chain; then
                echo "Synology data-plane enforcement chain population failed and empty-chain restore failed" >&2
                exit 1
              fi
              echo "Synology data-plane enforcement chain population failed; empty chain was restored" >&2
              exit 1
            fi
            ;;
          exact) ;;
          *)
            echo "Synology data-plane firewall state requires explicit removal before apply: $chain_state" >&2
            exit 1
            ;;
        esac
        if [ "$(chain_classification)" != exact ]; then
          case "$population_mode" in
            created)
              delete_owned_chain || true
              ;;
            emptied)
              restore_empty_owned_chain || true
              ;;
          esac
          echo "Synology data-plane enforcement chain is not exact; FORWARD jump was not installed" >&2
          exit 1
        fi
        save=$(filter_table) || exit 1
        forwards=$(forward_appends "$save")
        first=$(printf '%s\n' "$forwards" | awk 'NF {print; exit}')
        forward_count=$(printf '%s\n' "$forwards" | awk 'NF {n++} END {print n + 0}')
        if [ "$first" != "$my_pa_jump" ]; then
          [ "$first" = "$firewall_jump" ] && [ "$forward_count" -eq 1 ] || {
            echo "Synology FORWARD chain identity mismatch" >&2
            exit 1
          }
          "$iptables_bin" -I FORWARD 1 -j "$enforcement_chain"
          save=$(filter_table) || exit 1
          forwards=$(forward_appends "$save")
          first=$(printf '%s\n' "$forwards" | awk 'NF {print; exit}')
          second=$(printf '%s\n' "$forwards" | awk 'NF {n++; if (n == 2) {print; exit}}')
          forward_count=$(printf '%s\n' "$forwards" | awk 'NF {n++} END {print n + 0}')
          if [ "$first" != "$my_pa_jump" ] || [ "$second" != "$firewall_jump" ] || \
             [ "$forward_count" -ne 2 ]; then
            "$iptables_bin" -D FORWARD -j "$enforcement_chain" || true
            if [ "$population_mode" = created ]; then
              delete_owned_chain || true
            fi
            echo "Synology data-plane firewall admission failed; inserted jump was rolled back" >&2
            exit 1
          fi
        fi
        remaining=$(broad_return_count) || exit 1
        case "$remaining" in
          0) ;;
          1)
            "$iptables_bin" -D FORWARD_FIREWALL -s "$subnet" -j RETURN || {
              echo "failed to remove source-only data-plane RETURN" >&2
              exit 1
            }
            ;;
          *)
            echo "duplicate source-only data-plane RETURN requires explicit removal" >&2
            exit 1
            ;;
        esac
        final_state=$(enforcement_state) || exit 1
        if [ "$final_state" != effective ]; then
          echo "Synology data-plane firewall admission failed post-condition" >&2
          exit 1
        fi
        ;;
      *)
        echo "Synology data-plane firewall state requires explicit removal before apply: $state" >&2
        exit 1
        ;;
    esac
    echo "Synology data-plane firewall enforcement admitted"
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
    state=$(enforcement_state) || exit 1
    case "$state" in
      effective|broad-return) ;;
      *)
        echo "one exact Synology data-plane enforcement chain is not present: $state" >&2
        exit 1
      ;;
    esac
    [ "$(chain_classification)" = exact ] || {
      echo "refusing to delete foreign MY_PA_DATA_PLANE contents" >&2
      exit 1
    }
    restore_legacy_broad_return
    save=$(filter_table) || exit 1
    forwards=$(forward_appends "$save")
    my_pa_jumps=$(printf '%s\n' "$forwards" | awk -v exact="$my_pa_jump" \
      '$0 == exact {count++} END {print count + 0}')
    [ "$my_pa_jumps" -eq 1 ] || {
      echo "MY_PA_DATA_PLANE FORWARD jump identity mismatch" >&2
      exit 1
    }
    "$iptables_bin" -D FORWARD -j "$enforcement_chain"
    save=$(filter_table) || exit 1
    forwards=$(forward_appends "$save")
    first=$(printf '%s\n' "$forwards" | awk 'NF {print; exit}')
    forward_count=$(printf '%s\n' "$forwards" | awk 'NF {n++} END {print n + 0}')
    [ "$first" = "$firewall_jump" ] && [ "$forward_count" -eq 1 ] || {
      echo "legacy DSM-first FORWARD restoration failed" >&2
      exit 1
    }
    delete_owned_chain
    if "$iptables_bin" -S "$enforcement_chain" >/dev/null 2>&1; then
      echo "MY_PA_DATA_PLANE chain removal failed" >&2
      exit 1
    fi
    remaining=$(broad_return_count) || exit 1
    [ "$remaining" -eq 1 ] || {
      echo "legacy source-only data-plane RETURN is not present after remove" >&2
      exit 1
    }
    echo "Synology data-plane firewall enforcement removed"
    ;;
  *)
    echo "usage: $0 check|plan|apply|remove" >&2
    exit 64
    ;;
esac
