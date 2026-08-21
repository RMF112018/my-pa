# Incident Report: bobby-fetting.me Multi-Endpoint Outage

**Date:** 2026-08-16  
**Status:** Root cause confirmed; remediation pending operator authorization  
**Severity:** P2 — Partial outage (1 of 3 endpoints down, 1 misconfigured, 1 functional)

## Executive Summary

Three public hostnames under `bobby-fetting.me` were investigated:

| Hostname | External Status | Root Cause |
|---|---|---|
| `nas-mcp.bobby-fetting.me` | **FUNCTIONAL** (HTTP 401) | None — working as designed |
| `my-pa-mcp.bobby-fetting.me` | **DOWN** (HTTP 502) | Synology firewall blocks Docker bridge inter-container traffic |
| `bobby-fetting.me` (apex) | **MISCONFIGURED** (HTTP 404) | No ingress route for apex in PA-MCP tunnel |

DNS is healthy for all three hostnames across multiple resolvers.

## Investigation Environment

### Client (investigation origin)

- **Host:** `MacBook-Pro.local` (Apple Silicon, macOS 27.0)
- **Docker:** Client 29.6.1 (local containers, not production)
- **Tailscale:** Connected as `macbook-pro` (100.85.102.83)

### Production NAS (TheLakeHouseNAS)

- **Access:** SSH via Tailscale (`bfetting@100.66.28.14:10021`)
- **Host:** `TheLakeHouseNAS`
- **OS:** Synology DSM 7.3.2 (build 86009, kernel 4.4.302+)
- **Hardware:** `synology_r1000_923+` (x86_64)
- **Docker:** Server 24.0.2 (via Container Manager package)
- **Uptime:** 20 days (no recent reboot)

## Root Cause Analysis

### Endpoint 1: `nas-mcp.bobby-fetting.me` — FUNCTIONAL

**Tunnel:** PA-MCP Cloudflare Tunnel (ID: `20c7c28c-6025-4a04-8f9d-efaaac251275`)  
**Container:** `hb-personal-assistant-cloudflared` (HOST networking)  
**Origin:** `hb-personal-assistant-mcp` at `127.0.0.1:8765` (published via Docker host port mapping)

**Status:** Working correctly. External requests receive HTTP 401 with OAuth challenge.

**Why it works:** The PA-MCP cloudflared container uses Docker `network_mode: host`, which means:
- It uses NAS's host network stack directly
- Origin at `127.0.0.1:8765` is reached via loopback (bypasses iptables FORWARD chain)
- DNS resolution uses the host's `/etc/resolv.conf` directly
- The Synology firewall's FORWARD_FIREWALL chain is never traversed for origin traffic

**No remediation needed.**

---

### Endpoint 2: `my-pa-mcp.bobby-fetting.me` — DOWN (HTTP 502)

**Tunnel:** my-pa-mcp Cloudflare Tunnel (ID: `0609e4e3-a30e-4c3c-a24e-2ddb3a03935a`)  
**Container:** `my-pa-remote-mcp-cloudflared-1` (bridge networking)  
**Origin:** `my-pa-remote-mcp-my-pa-mcp-remote-1` at `172.25.0.3:8766` (Docker network `my-pa-remote-mcp_mcp-origin`)

#### Root Cause

**Synology DSM firewall (`FORWARD_FIREWALL` iptables chain) blocks all inter-container traffic on Docker bridge networks.**

The mechanism is a three-part interaction:

1. **`br_netfilter` module is loaded** with `bridge-nf-call-iptables=1`, which routes all Linux bridge traffic through the host's iptables FORWARD chain.

2. **Synology DSM firewall** injects a `FORWARD_FIREWALL` chain into iptables FORWARD that is the sole rule in FORWARD:
   ```
   -A FORWARD -j FORWARD_FIREWALL
   ```
   The `FORWARD_FIREWALL` chain:
   - Rule 1: ACCEPT loopback
   - Rule 2: ACCEPT RELATED,ESTABLISHED
   - Rule 3: RETURN for DSM ports (5000, 5001, 6690)
   - Rule 4: RETURN for source `10.0.0.0/24` (LAN)
   - Rule 5: RETURN for source `100.64.0.0/10` (Tailscale CGNAT)
   - **Rule 6: DROP all other traffic**
   - Rule 7: RETURN for `ovs_eth0` interface

3. **Docker bridge traffic** (e.g., `172.25.0.2` → `172.25.0.3` on `mcp-origin` network) matches none of rules 1–5 and is DROPped at rule 6.

#### Consequences

- cloudflared (172.25.0.2) cannot establish TCP connections to my-pa-mcp-remote (172.25.0.3:8766)
- The Cloudflare edge sees origin timeout → returns HTTP 502 to clients
- Docker's embedded DNS (127.0.0.11) cannot forward external lookups through the bridge → persistent DNS resolution failures in cloudflared logs
- The QUIC tunnel connections to Cloudflare's edge persist (established via `cloudflare-egress` network, maintained by RELATED,ESTABLISHED rule), but origin proxying fails

#### Evidence

- NAS host can reach `172.25.0.3:8766/healthz` → 200 OK (uses INPUT/OUTPUT chain, not FORWARD)
- Container on same `mcp-origin` network cannot reach `172.25.0.3:8766` → timeout (goes through FORWARD → FORWARD_FIREWALL → DROP)
- cloudflared logs show continuous `dial tcp 172.25.0.3:8766: i/o timeout` errors since first deployment
- FORWARD_FIREWALL rule 6 DROP counter: 443 packets / 35,204 bytes (increasing)
- The PA-MCP compose-cloudflared.yaml documentation explicitly states: *"this NAS's Docker embedded bridge DNS (127.0.0.11) cannot forward external lookups, so a bridge-attached connector cannot resolve Cloudflare's edge"*

#### Timeline

- **2026-07-04:** Synology DSM firewall enabled (`firewall_settings.json` modified; profile: `default`)
- **2026-08-14 15:49:** `my-pa-remote-mcp-cloudflared-1` container created
- **2026-08-14 18:09:** my-pa-mcp tunnel (0609e4e3) first connected to Cloudflare edge
- **2026-08-14 18:11:** First origin timeout errors (`dial tcp 172.25.0.2:8766: i/o timeout`) — **the endpoint has never been functional**
- **2026-08-14 19:56:** Container restarted, tunnel reconnected, ingress config loaded (version 2)
- **2026-08-16 13:45:** Current observed failures (our investigation)

**The my-pa-mcp endpoint has been non-functional since initial deployment.** There was no "working period" — earlier "context canceled" errors in logs were Cloudflare edge-side timeouts, not successful origin connections.

#### Remediation Options (require operator authorization)

1. **Preferred: Switch cloudflared to host networking** (same pattern as PA-MCP tunnel). Apply `compose.loopback.yml` to publish `127.0.0.1:8766` and reconfigure cloudflared to use HOST networking with origin at `127.0.0.1:8766`. This aligns with the known-good PA-MCP pattern already documented in this NAS environment.

2. **Alternative: Add iptables rules to allow Docker bridge traffic.** Insert a rule in `FORWARD_FIREWALL` before the DROP to allow traffic from Docker bridge subnets (`172.16.0.0/12`). This is fragile — Synology firmware updates may overwrite it.

3. **Alternative: Disable `bridge-nf-call-iptables`.** Set `/proc/sys/net/bridge/bridge-nf-call-iptables` to 0. This prevents bridge traffic from going through iptables at all. Also fragile and may affect Docker's network isolation guarantees.

---

### Endpoint 3: `bobby-fetting.me` (apex) — MISCONFIGURED (HTTP 404)

**Tunnel:** Routes through PA-MCP Cloudflare Tunnel (ID: `20c7c28c-...`)  
**Ingress config (from Cloudflare dashboard, shown in cloudflared logs):**
```json
{
  "ingress": [
    {
      "hostname": "nas-mcp.bobby-fetting.me",
      "originRequest": {"httpHostHeader": "127.0.0.1:8765"},
      "service": "http://127.0.0.1:8765"
    },
    {
      "service": "http_status:404"
    }
  ]
}
```

#### Root Cause

The PA-MCP tunnel's ingress configuration has **no hostname rule for `bobby-fetting.me` (apex)**. Only `nas-mcp.bobby-fetting.me` is routed. The apex matches the catch-all `http_status:404` rule, returning HTTP 404.

#### Evidence

- External curl to `https://bobby-fetting.me/` returns HTTP 404 with Cloudflare headers (`server: cloudflare`, `cf-ray: a2c146f14f055018-MIA`)
- The 404 comes from cloudflared's catch-all ingress rule, not from Cloudflare's CDN layer
- No web server on the NAS is configured to serve the apex domain content
- DNS for `bobby-fetting.me` resolves to Cloudflare proxy IPs (104.21.74.100, 172.67.201.197) — DNS is correct

#### Remediation Options (require operator authorization)

1. Add a hostname rule for `bobby-fetting.me` in the PA-MCP tunnel's Cloudflare dashboard ingress config, pointing to whatever origin service should serve the apex.
2. If the apex should be a static landing page or redirect, add an appropriate ingress rule or configure it at the Cloudflare edge (Page Rules / Redirect Rules).

## Hypothesis Testing Summary

### H1: DNS resolution failure (Split Horizon / hydration)  
**Status: REJECTED.** DNS resolves correctly to Cloudflare proxy IPs (104.21.74.100, 172.67.201.197) across system resolver, Cloudflare 1.1.1.1, and Google 8.8.8.8. No split-horizon or hydration issue. All three hostnames resolve to the same Cloudflare IPs.

### H2: Cloudflare tunnel ingress routing failure  
**Status: CONFIRMED (apex only).** The PA-MCP tunnel has no ingress rule for the apex `bobby-fetting.me`. The my-pa-mcp tunnel's ingress rules are correct but origin is unreachable. The apex 404 is a tunnel ingress configuration gap.

### H3: Origin service/app not listening on expected port  
**Status: REJECTED.** `my-pa-mcp-remote` is listening on `0.0.0.0:8766` and its healthcheck passes (ExitCode 0). Direct access from NAS host to `172.25.0.3:8766/healthz` returns 200 OK with `{"status":"ok"}`. The application is healthy and listening correctly.

### H4: Cloudflare tunnel edge / data-plane failure  
**Status: REJECTED.** Both tunnels maintain 4 registered QUIC connections to Cloudflare's MIA edge locations. The tunnel edge is healthy. The failure is at the origin-reachability layer, not the tunnel transport layer.

### H5: Certificate/secret expiry or rotation failure  
**Status: REJECTED.** TLS certificates are managed by Cloudflare and are valid (Google Trust Services, expires Sep 26, 2026). Tunnel credentials are loaded via bind-mounted JSON files. No certificate errors appear in any cloudflared logs.

### H6: Recent deployment/change introduced regression  
**Status: PARTIALLY CONFIRMED.** The Synology firewall has been enabled since July 4, 2026. The my-pa-mcp tunnel was deployed August 14 (post-firewall). The deployment did not account for the firewall blocking Docker bridge traffic. The PA-MCP tunnel (deployed earlier, July 5) works because it uses host networking. The my-pa deployment replicated the cloudflared ingress pattern but used bridge networking instead of host networking, inheriting the firewall block.

## Recommended Action Items

1. **Operator decision required:** Authorize remediation for `my-pa-mcp` endpoint (Option 1: host networking recommended).
2. **Operator decision required:** Authorize apex domain ingress configuration.
3. Document the Synology firewall / Docker bridge interaction as an operational constraint for all future Docker deployments on this NAS.
4. Consider adding a smoke test that validates cloudflared-to-origin reachability (not just container health) to deployment scripts.
