# Evidence Manifest: bobby-fetting.me Outage Investigation

**Date:** 2026-08-16  
**Investigator:** MossAIc Agent  
**Investigation window:** 2026-08-16 14:36–14:55 UTC (10:36–10:55 EDT)

## 1. Runtime Identity

### Client (MacBook-Pro.local)

| Property | Value |
|---|---|
| Hostname | MacBook-Pro.local |
| OS | macOS 27.0 (Build 26A5378n) |
| Kernel | Darwin 27.0.0 (xnu-13432.0.50.501.3~1/RELEASE_ARM64_T6041) |
| Docker Client | 29.6.1 |
| Tailscale | macbook-pro (100.85.102.83) |

### NAS (TheLakeHouseNAS)

| Property | Value |
|---|---|
| Hostname | TheLakeHouseNAS |
| OS | Synology DSM 7.3.2 (build 86009) |
| Kernel | Linux 4.4.302+ #86009 SMP x86_64 |
| Docker | Client/Server 24.0.2 (Container Manager) |
| IP (Tailscale) | 100.66.28.14 |
| IP (LAN) | 10.0.0.25 |
| Uptime | 20 days |

## 2. DNS Verification

### Independent resolver tests (all 3 hostnames)

| Resolver | bobby-fetting.me | nas-mcp.bobby-fetting.me | my-pa-mcp.bobby-fetting.me |
|---|---|---|---|
| System | 104.21.74.100, 172.67.201.197 | (same CF proxy IPs) | (same CF proxy IPs) |
| Cloudflare 1.1.1.1 | 104.21.74.100, 172.67.201.197 | (same) | (same) |
| Google 8.8.8.8 | 104.21.74.100, 172.67.201.197 | (same) | (same) |

**Result:** All hostnames resolve to Cloudflare proxy IPs. DNS is healthy. No split-horizon.

### DNS trace (dig +trace @1.1.1.1 bobby-fetting.me)

Root → TLD (.me) → Cloudflare nameservers → A records. Full delegation chain intact.

## 3. External HTTP Reachability

### Test: `https://bobby-fetting.me/` (apex)

```
HTTP/2 404
date: Sun, 16 Aug 2026 14:54:56 GMT
server: cloudflare
cf-ray: a2c146f14f055018-MIA
```

**Result:** HTTP 404 from cloudflared catch-all ingress. Not a Cloudflare CDN 404.

### Test: `https://nas-mcp.bobby-fetting.me/`

```
HTTP/2 401
www-authenticate: Bearer resource_metadata="https://nas-mcp.bobby-fetting.me/.well-known/oauth-protected-resource", scope="nas.read"
content-type: application/json
{"detail":"unauthorized"}
```

**Result:** HTTP 401 with OAuth challenge. Tunnel and origin both functional.

### Test: `https://my-pa-mcp.bobby-fetting.me/healthz`

```
< HTTP/2 502
cf-ray: 905c1a4a2a632271-MIA
```

Cloudflare returns 502 after ~30s origin timeout.

**Result:** HTTP 502 Bad Gateway. cloudflared cannot reach origin.

## 4. Cloudflared Container State

### PA-MCP Tunnel (`hb-personal-assistant-cloudflared`)

| Property | Value |
|---|---|
| Container ID | (from `docker ps`) |
| Image | cloudflare/cloudflared:2024.12.2 |
| Network Mode | host |
| Created | 2026-07-05 13:34:48 UTC |
| Status | Up 43 hours |
| Tunnel ID | 20c7c28c-6025-4a04-8f9d-efaaac251275 |
| QUIC Connections | 4 (registered) |
| Ingress (from dashboard config in logs) | `nas-mcp.bobby-fetting.me → 127.0.0.1:8765`, catch-all 404 |
| Compose file | `/volume2/personal-assistant/deploy/nas/mcp/compose-cloudflared.yaml` |

### my-pa-mcp Tunnel (`my-pa-remote-mcp-cloudflared-1`)

| Property | Value |
|---|---|
| Container ID | (from `docker ps`) |
| Image | cloudflare/cloudflared:2026.7.3 (digest-pinned) |
| Network Mode | bridge (mcp-origin + cloudflare-egress) |
| Created | 2026-08-14 15:49:12 UTC |
| Status | Up 43 hours (healthy) |
| Tunnel ID | 0609e4e3-a30e-4c3c-a24e-2ddb3a03935a |
| QUIC Connections | 4 (registered) |
| mcp-origin IP | 172.25.0.2 |
| cloudflare-egress IP | 172.26.0.2 |
| Ingress (from config.yml + dashboard) | `my-pa-mcp.bobby-fetting.me` (path-restricted) → `my-pa-mcp-remote:8766`, catch-all 404 |
| Compose file | `/volume1/my-pa/repository/ops/nas/remote/compose.yml` |
| Config file | `/volume1/my-pa/cloudflared/config.yml` |

### my-pa-mcp-remote (`my-pa-remote-mcp-my-pa-mcp-remote-1`)

| Property | Value |
|---|---|
| Status | Up 19 hours (healthy) |
| Started At | 2026-08-15T19:47:29Z |
| Restart Count | 0 |
| data-plane IP | 172.22.0.2 |
| mcp-origin IP | 172.25.0.3 |
| Healthcheck | `http://127.0.0.1:8766/readyz` (ExitCode 0, passing) |
| App log | `serving remote mcp on 0.0.0.0:8766/mcp` |

## 5. Origin Reachability Tests

### From NAS host (bypasses FORWARD chain)

| Target | Result |
|---|---|
| `http://172.25.0.3:8766/healthz` | 200 OK, `{"status":"ok"}` |
| `http://172.22.0.2:8766/healthz` | 200 OK, `{"status":"ok"}` |
| `http://127.0.0.1:8765/` (PA-MCP) | 401 Unauthorized |
| `http://127.0.0.1:8766/healthz` (my-pa loopback) | Not reachable (port not published) |

### From Docker bridge network (goes through FORWARD chain)

| Test | Result |
|---|---|
| curl container on `mcp-origin` → `172.25.0.3:8766` | **TIMEOUT** (5s) |
| curl container on `cloudflare-egress` → `google.com:80` | **DNS resolution timeout** |
| curl container on `cloudflare-egress` → `1.1.1.1:443` (bypass DNS) | **Connection timeout** |

**Conclusion:** Inter-container and outbound traffic from Docker bridge networks is completely blocked.

## 6. Synology Firewall Configuration

### Firewall settings file

**Path:** `/usr/syno/etc/firewall.d/firewall_settings.json`  
**Content:**
```json
{
   "profile" : "default",
   "status" : true
}
```

**Last modified:** 2026-07-04 05:39:47 UTC

### Active profile (default)

**Path:** `/usr/syno/etc/firewall.d/1.json`  
**Last modified:** 2026-08-14 19:56:00 UTC

**Adapter policy:** `global: 2` (deny by default), `ovs_eth0: 0` (allow)

**Rules:**
1. Allow DSM service ports (5000, 5001, 6690) from any source
2. Allow all from `10.0.0.0/24` (LAN) — RETURN
3. Allow all from `100.64.0.0/10` (Tailscale CGNAT) — RETURN
4. Deny all from any source — DROP
5. Allow all from `ovs_eth0` interface — RETURN

### iptables FORWARD chain

```
-P FORWARD ACCEPT
-N FORWARD_FIREWALL
-A FORWARD -j FORWARD_FIREWALL
-A FORWARD_FIREWALL -i lo -j ACCEPT
-A FORWARD_FIREWALL -m state --state RELATED,ESTABLISHED -j ACCEPT
-A FORWARD_FIREWALL -p tcp -m multiport --dports 5000,5001,6690 -j RETURN
-A FORWARD_FIREWALL -s 10.0.0.0/24 -j RETURN
-A FORWARD_FIREWALL -s 100.64.0.0/10 -j RETURN
-A FORWARD_FIREWALL -j DROP
-A FORWARD_FIREWALL -i ovs_eth0 -j RETURN
```

**Key observation:** Docker's standard FORWARD chain rules (DOCKER-USER, DOCKER-ISOLATION-STAGE-1, DOCKER) are NOT linked from the FORWARD chain. Only `FORWARD_FIREWALL` is present. The DOCKER-ISOLATION-STAGE-* chains exist but are never reached for inter-container traffic.

### br_netfilter state

```
br_netfilter 13051 0 - Live
bridge 56359 1 br_netfilter, Live
/proc/sys/net/bridge/bridge-nf-call-iptables = 1
/proc/sys/net/bridge/bridge-nf-call-ip6tables = 1
```

**This means all bridge (Docker inter-container) traffic traverses iptables FORWARD → FORWARD_FIREWALL → DROP.**

### FORWARD_FIREWALL counter (at time of investigation)

| Rule | Packets | Bytes |
|---|---|---|
| 1 (lo ACCEPT) | 0 | 0 |
| 2 (ESTABLISHED ACCEPT) | 265,514 | 23,298,650 |
| 3 (DSM ports RETURN) | 0 | 0 |
| 4 (10.0.0.0/24 RETURN) | 0 | 0 |
| 5 (100.64.0.0/10 RETURN) | 0 | 0 |
| **6 (DROP ALL)** | **443** | **35,204** |
| 7 (ovs_eth0 RETURN) | 0 | 0 |

## 7. Docker Network Inventory

| Network Name | Subnet | Internal | Key Containers |
|---|---|---|---|
| my-pa-remote-mcp_mcp-origin | 172.25.0.0/16 | **YES** | cloudflared (172.25.0.2), my-pa-mcp-remote (172.25.0.3) |
| my-pa-remote-mcp_cloudflare-egress | 172.26.0.0/16 | no | cloudflared (172.26.0.2) |
| my-pa-nas-contract_data-plane | 172.22.0.0/16 | no | my-pa-mcp-remote (172.22.0.2), postgres, gateway, proxy |
| my-pa-nas-contract_ingress-plane | 172.18.0.0/16 | no | gateway, proxy |
| my-pa-nas-contract_host-edge | 172.23.0.0/16 | no | proxy |
| hb-mcp-internal | 172.20.0.0/16 | no | hb-personal-assistant-mcp (172.20.0.2) |
| bridge | (default) | no | — |

## 8. Key Log Excerpts

### my-pa-mcp cloudflared: first origin timeout (Aug 14, 18:11 UTC)

```
2026-08-14T18:11:25Z ERR error="Unable to reach the origin service.
  The service may be down or it may not be responding to traffic from cloudflared:
  dial tcp 172.25.0.2:8766: i/o timeout"
  connIndex=2 event=1 ingressRule=0 originService=http://my-pa-mcp-remote:8766
```

### my-pa-mcp cloudflared: repetitive origin failures (Aug 16, 13:45 UTC)

```
2026-08-16T13:45:19Z ERR error="Unable to reach the origin service...
  dial tcp 172.25.0.3:8766: i/o timeout"
  dest=https://my-pa-mcp.bobby-fetting.me/oauth/authorize?...
```

### my-pa-mcp cloudflared: DNS resolution failures (continuous)

```
2026-08-14T15:49:57Z ERR edge discovery: error looking up Cloudflare edge IPs:
  the DNS query failed error="lookup _v2-origintunneld._tcp.argotunnel.com
  on 127.0.0.11:53: read udp 127.0.0.1:44351->127.0.0.11:53: i/o timeout"
```

### PA-MCP cloudflared: ingress config from dashboard

```
2026-08-14T16:39:59Z INF Updated to new configuration
  config="{\"ingress\":[{\"hostname\":\"nas-mcp.bobby-fetting.me\",
  \"originRequest\":{\"httpHostHeader\":\"127.0.0.1:8765\"},
  \"service\":\"http://127.0.0.1:8765\"},{\"service\":\"http_status:404\"}],
  \"warp-routing\":{\"enabled\":false}}" version=16
```

### my-pa-mcp-remote: healthy application log

```
2026-08-15T19:47:34.042775751Z serving     remote mcp on 0.0.0.0:8766/mcp
```

## 9. PA-MCP Compose Documentation (Key Quote)

From `/volume2/personal-assistant/deploy/nas/mcp/compose-cloudflared.yaml`:

> this NAS's Docker embedded bridge DNS (127.0.0.11) cannot forward external lookups,
> so a bridge-attached connector cannot resolve Cloudflare's edge
> (_v2-origintunneld._tcp.argotunnel.com) and never registers. We therefore run the
> connector with HOST networking so it uses the host's working resolv.conf.

This confirms the Docker bridge DNS block is a known and previously documented issue on this NAS.

## 10. Compose File Locations

| Service | Path |
|---|---|
| PA-MCP cloudflared | `/volume2/personal-assistant/deploy/nas/mcp/compose-cloudflared.yaml` |
| my-pa remote MCP | `/volume1/my-pa/repository/ops/nas/remote/compose.yml` |
| my-pa loopback fallback | `/volume1/my-pa/repository/ops/nas/remote/compose.loopback.yml` |
| my-pa cloudflared config | `/volume1/my-pa/cloudflared/config.yml` |
| my-pa cloudflared config template | `/volume1/my-pa/repository/ops/nas/remote/cloudflared-config.example.yml` |
| my-pa compose env example | `/volume1/my-pa/repository/ops/nas/remote/compose.env.example` |
| my-pa validate.py | `/volume1/my-pa/repository/ops/nas/remote/validate.py` |
| my-pa live-gate.py | `/volume1/my-pa/repository/ops/nas/remote/live-gate.py` |
