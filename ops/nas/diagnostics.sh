#!/bin/sh
set -eu
: "${MY_PA_RUNTIME_SERVICES:?verified runtime service manifest required}"
: "${MY_PA_NAS_ROOT:?exact canonical NAS root required}"
: "${MY_PA_MIN_FREE_KIB:?minimum free disk threshold required}"
: "${MY_PA_BACKUP_RECEIPT:?recent verified backup receipt required}"
: "${MY_PA_TAILNET_HOST:?exact private tailnet hostname required}"
: "${MY_PA_DIAGNOSTIC_BFF_URL:?exact authenticated browser/BFF diagnostic endpoint required}"
: "${MY_PA_DIAGNOSTIC_SESSION_COOKIE_FILE:?protected diagnostic session credential file required}"
: "${MY_PA_WORKER_MAX_AGE_SECONDS:?worker heartbeat maximum age required}"
: "${MY_PA_APPLE_MAX_AGE_SECONDS:?Apple handoff maximum age required}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/lifecycle-common.sh"
[ "$MY_PA_LIFECYCLE_MODE" = pilot ] || { echo "operational diagnostics require admitted pilot identity" >&2; exit 1; }
: "${MY_PA_VERIFIED_PILOT_ORIGIN:?signed pilot canonical origin required}"
verify_running_identity
case "$MY_PA_WORKER_MAX_AGE_SECONDS:$MY_PA_APPLE_MAX_AGE_SECONDS" in
  *[!0-9:]*|:*|*:) echo "diagnostic age thresholds must be numeric" >&2; exit 1 ;;
esac
"$script_dir/health.sh"
python3 "$script_dir/runtime_gate.py" "$MY_PA_RUNTIME_SERVICES" --live \
  --compose-file "$MY_PA_NAS_COMPOSE_FILE" --permissions
"$script_dir/verify-backup-receipt.sh" "$MY_PA_BACKUP_RECEIPT"
free_kib=$(df -Pk "$MY_PA_NAS_ROOT" | awk 'NR == 2 {print $4}')
case "$free_kib:$MY_PA_MIN_FREE_KIB" in
  *[!0-9:]*|:*|*:) echo "disk threshold is not numeric" >&2; exit 1 ;;
esac
[ "$free_kib" -ge "$MY_PA_MIN_FREE_KIB" ] || { echo "NAS free disk is below threshold" >&2; exit 1; }
nas_compose exec -T gateway python -c \
  'import urllib.request; urllib.request.urlopen("http://web:3000/", timeout=5).read(1)' >/dev/null
nas_compose exec -T gateway python -c \
  'import sys, urllib.request; r=urllib.request.Request("http://proxy:8080/", headers={"Host":sys.argv[1]}); urllib.request.urlopen(r, timeout=5).read(1)' \
  "$MY_PA_TAILNET_HOST" >/dev/null
python3 "$script_dir/diagnostic_http_probe.py" \
  "$MY_PA_DIAGNOSTIC_BFF_URL" "$MY_PA_DIAGNOSTIC_SESSION_COOKIE_FILE" \
  "$MY_PA_TAILNET_HOST" "$MY_PA_VERIFIED_PILOT_ORIGIN"
postgres_id=$(nas_compose ps -q postgres)
[ -n "$postgres_id" ] || { echo "postgres is not running" >&2; exit 1; }
docker exec -i "$postgres_id" psql -v ON_ERROR_STOP=1 -U my_pa -d my_pa -Atqc \
  "SELECT CASE WHEN count(DISTINCT plane) = 2 THEN 1 ELSE 0 END
     FROM knowledge.worker_heartbeats
    WHERE stopped_at IS NULL
      AND heartbeat_at >= now() - make_interval(secs => ${MY_PA_WORKER_MAX_AGE_SECONDS})
      AND plane IN ('enrollment', 'capture')" | grep -qx 1
docker exec -i "$postgres_id" psql -v ON_ERROR_STOP=1 -U my_pa -d my_pa -Atqc \
  "SELECT CASE WHEN max(consumed_at) >= now() - make_interval(secs => ${MY_PA_APPLE_MAX_AGE_SECONDS})
               THEN 1 ELSE 0 END
     FROM knowledge.native_admission_authorities" | grep -qx 1
echo "NAS operational diagnostics passed"
