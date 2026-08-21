# STOP Report: AUTH-MY-PA-MCP-HOST-NETWORK-REMEDIATION-20260816-001

**Date:** 2026-08-16  
**Authorization:** AUTH-MY-PA-MCP-HOST-NETWORK-REMEDIATION-20260816-001  
**Status:** STOPPED — rollback incomplete, operator decision required

## Executive Summary

The authorized remediation attempted to move the my-pa-mcp cloudflared connector from Docker bridge networking to host networking (the proven PA-MCP pattern) to bypass the Synology `FORWARD_FIREWALL` block on Docker bridge inter-container traffic.

**The remediation failed and was rolled back, but rollback is incomplete.** The `docker compose up --force-recreate` required to apply configuration changes destroyed `ESTABLISHED` network connections that the previous container instances relied on. The Synology firewall blocks all `NEW` inter-container connections on Docker bridge networks, so the destroyed connections cannot be re-established. Both containers are now in crash-restart loops.

**This exposed a pre-existing fragility:** the previous "healthy" my-pa-mcp-remote container was entirely dependent on grandfathered `ESTABLISHED` connections (maintained by the firewall's `RELATED,ESTABLISHED` rule). It could never have survived a restart.

## Timeline of Actions

| Time (UTC) | Action | Result |
|---|---|---|
| 15:07 | Pre-change evidence captured | External: my-pa-mcp returns HTTP 502; cloudflared logs show origin timeout |
| 15:13 | `config.yml` backed up to `config.yml.pre-remediation-backup` | OK |
| 15:14 | `config.yml` updated: `my-pa-mcp-remote:8766` → `127.0.0.1:8766` | OK |
| 15:14 | Override compose file `compose.host-bridge-fix.yml` created on NAS | OK (host networking + loopback port) |
| 15:16 | `compose up -d --force-recreate` with override | **FAILED** — my-pa-mcp-remote crashes on PostgreSQL connection |
| 15:18 | Diagnosis: `psycopg.OperationalError: connection to server at "172.22.0.3", port 5432 failed` | Same firewall root cause blocks data-plane bridge |
| 15:19 | Rollback: restored original `config.yml`, removed override file, `compose up --force-recreate` with original compose | **ALSO FAILED** — same PostgreSQL connection error |
| 15:24 | Manually started cloudflared container | Running but can't resolve DNS (bridge DNS blocked) |
| 15:27 | Final state verified | Both containers in crash-restart loops; my-pa-mcp returns HTTP 530 |

## Root Cause of Failure

The investigation report identified that the Synology `FORWARD_FIREWALL` iptables chain blocks all Docker bridge inter-container traffic (source IPs in `172.16.0.0/12` don't match the `10.0.0.0/24` or `100.64.0.0/10` allow rules). This affects **all** Docker bridge networks on the NAS, not just `mcp-origin`:

1. **cloudflared → my-pa-mcp-remote** (mcp-origin bridge): blocked — this was the known issue
2. **my-pa-mcp-remote → PostgreSQL** (data-plane bridge): **also blocked** — this was not initially apparent

The previous container instances had `ESTABLISHED` TCP connections that predated the firewall's effectiveness (or were established during a window when `bridge-nf-call-iptables` was not yet set to 1). These connections were maintained by the firewall's `RELATED,ESTABLISHED` ACCEPT rule (rule 2 in `FORWARD_FIREWALL`). The `force-recreate` destroyed these connections, and new connections cannot be established.

## What Was Changed and Rolled Back

### Changes made (all rolled back):

1. **`/volume1/my-pa/cloudflared/config.yml`**: Modified service URLs from `http://my-pa-mcp-remote:8766` to `http://127.0.0.1:8766`. **Rolled back** — file restored from backup, verified identical to original.

2. **`/volume1/my-pa/repository/ops/nas/remote/compose.host-bridge-fix.yml`**: New override file created. **Removed** — file deleted.

3. **Containers**: Both `my-pa-remote-mcp-my-pa-mcp-remote-1` and `my-pa-remote-mcp-cloudflared-1` were force-recreated (twice — once with override, once without for rollback). **Cannot be rolled back** — the previous container instances with their `ESTABLISHED` connections no longer exist. Docker does not preserve stopped containers after force-recreate.

### Artifacts remaining (for operator reference):

- `/volume1/my-pa/cloudflared/config.yml.pre-remediation-backup` — backup of original config (retained for audit)

## Current State (as of 2026-08-16 15:27 UTC)

### External Endpoints

| Hostname | Status | Change from pre-remediation |
|---|---|---|
| `nas-mcp.bobby-fetting.me` | HTTP 401 (functional) | **No change** — unaffected |
| `my-pa-mcp.bobby-fetting.me` | HTTP 530 (tunnel down) | **Worse** — was HTTP 502 (tunnel up, origin unreachable) |
| `bobby-fetting.me` (apex) | HTTP 404 (misconfigured) | **No change** — unaffected |

### Container State

| Container | Status | Issue |
|---|---|---|
| `my-pa-remote-mcp-my-pa-mcp-remote-1` | Running (restart loop) | Cannot connect to PostgreSQL at 172.22.0.3:5432 (firewall blocks data-plane bridge) |
| `my-pa-remote-mcp-cloudflared-1` | Running (restart loop) | Cannot resolve DNS for Cloudflare edge (firewall blocks bridge DNS forwarding) |
| `my-pa-nas-contract-postgres-1` | Up 43 hours (healthy) | **Unaffected** |
| `hb-personal-assistant-mcp` | Up 43 hours | **Unaffected** (uses SQLite, host-networked cloudflared) |
| `hb-personal-assistant-cloudflared` | Up 43 hours | **Unaffected** (host networking) |

## Why This Cannot Be Fixed Within the Authorization

The authorization prohibits:
- Synology firewall / iptables changes
- Disabling `bridge-nf-call-iptables`
- Application code changes
- Database or migration state changes
- Modifying unrelated workloads (postgres container is in `my-pa-nas-contract` project)

Fixing the PostgreSQL connectivity requires **one** of:
1. **Firewall change**: Add an iptables rule allowing traffic from Docker bridge subnets (`172.16.0.0/12`) in `FORWARD_FIREWALL` — **prohibited**
2. **Disable `bridge-nf-call-iptables`**: Set `/proc/sys/net/bridge/bridge-nf-call-iptables` to 0 — **prohibited**
3. **Publish postgres on host loopback**: Add port binding `127.0.0.1:5432->5432` to postgres container — requires modifying **unrelated workload** (different compose project)
4. **Application change**: Modify DATABASE_URL to use `host.docker.internal` or host IP — requires **application config change**
5. **TCP proxy**: Set up a host-level TCP proxy from bridge gateway to postgres container — new infrastructure (violates YAGNI/MCV scope)

None of these are within the authorized scope.

## Recommendation for Operator

The operator must authorize **one** of the following to restore the my-pa-mcp stack:

### Option A: Firewall exception (recommended)
Add a targeted iptables rule in `FORWARD_FIREWALL` (before the DROP rule) to allow traffic from Docker bridge subnets:
```
iptables -I FORWARD_FIREWALL 6 -s 172.16.0.0/12 -j RETURN
```
This unblocks ALL Docker inter-container traffic. Combined with the original cloudflared→origin bridge issue, this would also fix the original my-pa-mcp outage without needing host networking at all.

### Option B: Disable bridge-nf-call-iptables
```
echo 0 > /proc/sys/net/bridge/bridge-nf-call-iptables
```
This prevents bridge traffic from traversing iptables entirely. Less targeted but simpler.

### Option C: Publish postgres on host loopback + host networking for cloudflared
1. Add `ports: ["127.0.0.1:5432:5432"]` to postgres container in my-pa-nas-contract compose (requires recreating postgres)
2. Add `extra_hosts: ["postgres:host-gateway"]` to my-pa-mcp-remote
3. Change cloudflared to host networking
4. Publish my-pa-mcp-remote on 127.0.0.1:8766

This is the most surgical approach but requires modifying two compose projects.

### Option D: Full host networking for my-pa-mcp-remote
Switch my-pa-mcp-remote to host networking entirely. It would connect to postgres via 127.0.0.1:5432 (requires postgres port publishing) and cloudflared would connect to 127.0.0.1:8766. Both containers would bypass the bridge firewall.

## Pre-Existing Condition Disclosure

The investigation report stated that my-pa-mcp-remote was "healthy" and "serving on 0.0.0.0:8766". This was accurate at the time — the container WAS running and its healthcheck WAS passing. However, the container's health was entirely dependent on a long-lived PostgreSQL connection that could not be re-established if broken. The container would have failed on any restart, Docker daemon restart, or NAS reboot. This fragility was not visible in the original investigation because the container had not been restarted since its initial deployment.
