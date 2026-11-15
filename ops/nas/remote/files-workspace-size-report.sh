#!/bin/sh
# Read-only size report for the files workspace (ops/runbooks/files-workspace.md section 8).
# Policy (operator, 2026-11-15): keep everything. Nothing is purged; this only measures growth.
# Run on the NAS: sudo -n sh ops/nas/remote/files-workspace-size-report.sh [WORKSPACE]
# The workspace default is the one admitted folder. Writes nothing; exit 0 always except a
# missing folder (2). Free space is compared with the 20 GiB reserve the product enforces.
set -eu
WS=${1:-/volume1/homes/bfetting/MCP}
RESERVE_KB=$((21474836480 / 1024))
[ -d "$WS" ] && [ ! -L "$WS" ] || { echo "REFUSE: $WS is not a real directory" >&2; exit 2; }
kb() { du -sk "$1" 2>/dev/null | cut -f1; }
count() { find "$1" -type f 2>/dev/null | wc -l | tr -d ' '; }
echo "files workspace size report $(date -u +%Y-%m-%dT%H:%M:%SZ) workspace=$WS"
total=$(kb "$WS"); ctl=$(kb "$WS/.my-pa")
echo "total_kb=$total  control_kb=${ctl:-0}"
for d in staging versions trash; do
  p="$WS/.my-pa/$d"
  if [ -d "$p" ]; then echo ".my-pa/$d  kb=$(kb "$p")  files=$(count "$p")"; else echo ".my-pa/$d  absent"; fi
done
avail=$(df -Pk "$WS" | awk 'NR==2{print $4}')
echo "volume_free_kb=$avail  reserve_kb=$RESERVE_KB"
if [ "$avail" -le $((RESERVE_KB * 2)) ]; then echo "WARN: free space is within twice the reserve"; fi
