# my-pa-mcp Temporary Firewall Exception — Implementation Evidence

**Authorization**: AUTH-MY-PA-SYNOLOGY-FORWARD-RECOVERY-20260816-002
**Executed**: 2026-08-16, via SSH to TheLakeHouseNAS (`bfetting@100.66.28.14:10021`)
**Disposition**: `MY_PA_MCP_TEMPORARY_NETWORK_RECOVERY_VERIFIED`

This document supersedes nothing in `2026-08-16-bobby-fetting-me-outage-investigation.md`,
`2026-08-16-outage-evidence-manifest.md`, or `2026-08-16-host-network-remediation-stop-report.md`;
it records the successful remediation performed under the second (narrower) authorization after
the host-networking attempt (AUTH-...-001) failed and was rolled back.

## 1. Mandatory preflight (captured before any change)

### 1.1 FORWARD / FORWARD_FIREWALL / DOCKER-USER — before change

```
-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
-N DOCKER
-N DOCKER-ISOLATION-STAGE-1
-N DOCKER-ISOLATION-STAGE-2
-N DOCKER-USER
-N FORWARD_FIREWALL
-N INPUT_FIREWALL
-N QUICKCONNECT_RELAY
-A FORWARD -j FORWARD_FIREWALL
-A DOCKER-USER -j RETURN
```

`iptables -S FORWARD` / `iptables -L FORWARD` (single-chain lookup) errored with
`No chain/target/match by that name` on this DSM iptables v1.8.3 (legacy) build — a pre-existing
tool quirk, not a policy issue. The full ruleset dump (`iptables -S` / `iptables -L -n -v`, no
chain argument) reliably returns `Chain FORWARD (policy ACCEPT ...)` with the single rule
`-A FORWARD -j FORWARD_FIREWALL`, confirming policy ACCEPT and that FORWARD_FIREWALL is the sole
gate for all forwarded (Docker bridge) traffic. `DOCKER-USER` and both `DOCKER-ISOLATION-STAGE-*`
chains are defined but have **0 references** from `FORWARD` — Docker's own isolation is
disconnected; Synology's `FORWARD_FIREWALL` is the only enforcement point, confirming the original
root-cause model.

`FORWARD_FIREWALL` immediately before change:

```
Chain FORWARD_FIREWALL (1 references)
num      pkts      bytes target     prot opt in     out     source               destination
1           0        0 ACCEPT     all  --  lo     *       0.0.0.0/0            0.0.0.0/0
2      292784 25768454 ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            state RELATED,ESTABLISHED
3           0        0 RETURN     tcp  --  *      *       0.0.0.0/0            0.0.0.0/0            multiport dports 5000,5001,6690
4           0        0 RETURN     all  --  *      *       10.0.0.0/24          0.0.0.0/0
5           0        0 RETURN     all  --  *      *       100.64.0.0/10        0.0.0.0/0
6         804    61564 DROP       all  --  *      *       0.0.0.0/0            0.0.0.0/0
7           0        0 RETURN     all  --  ovs_eth0 *       0.0.0.0/0            0.0.0.0/0
```

DROP (rule 6) was actively climbing during preflight (742 → 804 → 809 pkts) — live evidence of the
ongoing outage caused by the two crash-looping containers.

### 1.2 Docker networks attached to the three in-scope containers (freshly inspected)

| Network | Subnet | Internal | Bridge iface | Members (name = IP) |
|---|---|---|---|---|
| `my-pa-nas-contract_data-plane` | 172.22.0.0/16 | true | `docker-d4d93b25` | my-pa-mcp-remote=.2, postgres=.3, gateway=.5, worker-enrollment=.4, worker-capture=.6 |
| `my-pa-remote-mcp_mcp-origin` | 172.25.0.0/16 | true | `docker-4b5aa893` | my-pa-mcp-remote=.2, cloudflared=.3 |
| `my-pa-remote-mcp_cloudflare-egress` | 172.26.0.0/16 | false | `docker-eb6f144d` | cloudflared=.2 (only member) |

- `my-pa-remote-mcp-my-pa-mcp-remote-1` is a member of `data-plane` and `mcp-origin` only.
- `my-pa-nas-contract-postgres-1` is a member of `data-plane` only, IP 172.22.0.3, no host port
  binding (unrelated to Synology's own local Postgres on 127.0.0.1:5432).
- `my-pa-remote-mcp-cloudflared-1` is a member of `mcp-origin` and `cloudflare-egress` only.

No other network is attached to any of the three containers, so no additional subnet is required
beyond these three.

`docker network ls` (full, for record):
```
83e8ce709426   bridge                               bridge    local
edd3c5d633f7   hb-mcp-internal                      bridge    local
c71f36cb4d5e   host                                 host      local
d4d93b256b6e   my-pa-nas-contract_data-plane        bridge    local
837686ac0a8c   my-pa-nas-contract_entra-egress      bridge    local
210fefcbeefe   my-pa-nas-contract_host-edge         bridge    local
831c22ba1ce0   my-pa-nas-contract_ingress-plane     bridge    local
eb6f144d4726   my-pa-remote-mcp_cloudflare-egress   bridge    local
4b5aa8938a2a   my-pa-remote-mcp_mcp-origin          bridge    local
ca002aa47298   none                                 null      local
```

No deviation from the prior root-cause model was found — proceeded without invoking a stop
condition.

## 2. Exact subnets authorized and rules inserted

Minimal required subnets (source-based `RETURN`, matching the existing rule style used by rules 4
and 5 in the same chain):

- `172.22.0.0/16` — my-pa app <-> PostgreSQL (data-plane)
- `172.25.0.0/16` — cloudflared <-> my-pa MCP origin (mcp-origin)
- `172.26.0.0/16` — cloudflared DNS/Cloudflare edge egress (cloudflare-egress)

No blanket `172.16.0.0/12` exemption was used. Commands (inserted at freshly-observed position 6,
immediately before the DROP rule; `iptables -m comment` was unavailable on this kernel build, so no
comment annotation could be attached — noted as a minor limitation, not a scope deviation):

```
iptables -I FORWARD_FIREWALL 6 -s 172.26.0.0/16 -j RETURN
iptables -I FORWARD_FIREWALL 6 -s 172.25.0.0/16 -j RETURN
iptables -I FORWARD_FIREWALL 6 -s 172.22.0.0/16 -j RETURN
```

`FORWARD_FIREWALL` immediately after insertion (all new rules at 0 packets, confirming freshly
inserted; DROP still at 809, rules 1-5 byte-for-byte unchanged in content):

```
1           0        0 ACCEPT     all  --  lo     *       0.0.0.0/0            0.0.0.0/0
2      292904 25779905 ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            state RELATED,ESTABLISHED
3           0        0 RETURN     tcp  --  *      *       0.0.0.0/0            0.0.0.0/0            multiport dports 5000,5001,6690
4           0        0 RETURN     all  --  *      *       10.0.0.0/24          0.0.0.0/0
5           0        0 RETURN     all  --  *      *       100.64.0.0/10        0.0.0.0/0
6           0        0 RETURN     all  --  *      *       172.22.0.0/16        0.0.0.0/0
7           0        0 RETURN     all  --  *      *       172.25.0.0/16        0.0.0.0/0
8           0        0 RETURN     all  --  *      *       172.26.0.0/16        0.0.0.0/0
9         809    61983 DROP       all  --  *      *       0.0.0.0/0            0.0.0.0/0
10          0        0 RETURN     all  --  ovs_eth0 *       0.0.0.0/0            0.0.0.0/0
```

## 3. Pre-restart connectivity validation (before touching any container)

Using disposable, non-persistent `curlimages/curl:8.12.1` containers on the respective networks:

- `data-plane` -> `172.22.0.3:5432` (postgres): TCP connect **open**.
- `mcp-origin` -> `http://172.25.0.2:8766/healthz`: **HTTP 200**.
- `cloudflare-egress` -> DNS lookup `region1.v2.argotunnel.com`: resolved; HTTPS to `1.1.1.1`:
  **HTTP 301** (connection succeeded).

## 4. Container recovery

No manual container recreation was required for the initial recovery — Docker's own restart policy
had kept `my-pa-remote-mcp-my-pa-mcp-remote-1` and `my-pa-remote-mcp-cloudflared-1` in a crash-retry
loop throughout the outage; the very next retry after the rule insertion succeeded on its own:

| Container | State before | State after (self-healed) |
|---|---|---|
| my-pa-mcp-remote | crash-looping | Up 30s (healthy), RestartCount=6 |
| cloudflared | crash-looping | Up 57s (running), RestartCount=7 |
| postgres | Up 44h (healthy) | unchanged — never stopped, not touched |

No compose file, image, network definition, or `config.yml` was modified. `config.yml` origin
remained `http://my-pa-mcp-remote:8766` throughout (per rollback-authoritative state already in
place from the prior session).

## 5. Acceptance tests — first recovery

- **Fresh PostgreSQL connection**: `docker exec` into my-pa-mcp-remote, brand-new SQLAlchemy engine
  (not the app's existing pool) -> `SELECT 1` -> `DB_CHECK_OK 1`.
- **Fresh cloudflared -> origin**: internal probe from a fresh container on `mcp-origin` to
  `http://172.25.0.2:8766/healthz` -> `{"status":"ok"}`.
- **Fresh cloudflared DNS/edge**: cloudflared logs show a full precheck (`DNS Resolution` PASS x2,
  `UDP/TCP Connectivity` PASS x2, `Cloudflare API` PASS) and 3 new `Registered tunnel connection`
  events (protocol=quic, locations mia08/mia01) with `SUMMARY: Environment is healthy.`
- **External `/healthz`**: `https://my-pa-mcp.bobby-fetting.me/healthz` -> **HTTP 200**.
- **Safe non-mutating MCP/auth check**: `https://my-pa-mcp.bobby-fetting.me/mcp` -> **HTTP 401**
  (expected auth challenge, no state mutated).
- **nas-mcp regression**: `https://nas-mcp.bobby-fetting.me/` -> **HTTP 401**, unchanged.

## 6. Restart-resilience test (second controlled restart)

To avoid relying on a lucky grandfathered state, `my-pa-mcp-remote` and `cloudflared` were
explicitly restarted a second time (`docker restart`, no config change):

- Both containers returned to `healthy`/`running` within ~30s.
- Fresh PostgreSQL connection re-verified post-restart: `DB_CHECK_OK 1`.
- cloudflared re-registered 3 new tunnel connections and logged `Environment is healthy` again.
- External re-checks after the second restart:
  - `my-pa-mcp.bobby-fetting.me/healthz` -> **HTTP 200**
  - `my-pa-mcp.bobby-fetting.me/mcp` -> **HTTP 401**
  - `nas-mcp.bobby-fetting.me/` -> **HTTP 401** (still unchanged)

## 7. Final firewall state

```
-N FORWARD_FIREWALL
-A FORWARD_FIREWALL -i lo -j ACCEPT
-A FORWARD_FIREWALL -m state --state RELATED,ESTABLISHED -j ACCEPT
-A FORWARD_FIREWALL -p tcp -m multiport --dports 5000,5001,6690 -j RETURN
-A FORWARD_FIREWALL -s 10.0.0.0/24 -j RETURN
-A FORWARD_FIREWALL -s 100.64.0.0/10 -j RETURN
-A FORWARD_FIREWALL -s 172.22.0.0/16 -j RETURN
-A FORWARD_FIREWALL -s 172.25.0.0/16 -j RETURN
-A FORWARD_FIREWALL -s 172.26.0.0/16 -j RETURN
-A FORWARD_FIREWALL -j DROP
-A FORWARD_FIREWALL -i ovs_eth0 -j RETURN
```

Post-recovery packet counters on the three new rules (traffic is flowing through them as expected):
rule 6 (172.22.0.0/16) = 6 pkts/360 bytes, rule 7 (172.25.0.0/16) = 5 pkts/300 bytes, rule 8
(172.26.0.0/16) = 67 pkts/34011 bytes, at time of this snapshot; DROP counter stayed flat at 809
(no longer climbing — the outage-driving traffic is gone).

## 8. Persistence risk (explicitly NOT remediated now, per authorization boundary)

These three `iptables` rules are **runtime-only** and were applied directly against the live
kernel ruleset via `iptables -I`. They are **not** written into
`/usr/syno/etc/firewall.d/1.json` or `firewall_settings.json`, and there is no boot script or
scheduled task. **They will be lost** on NAS reboot, DSM firewall service restart/reload, or a DSM
upgrade that reapplies the firewall profile — at which point `my-pa-mcp` and its cloudflared tunnel
will crash-loop again exactly as before this fix. This is a known residual risk, intentionally left
unaddressed pending a separate operator decision on a durable persistence mechanism (e.g. an
accepted change to the DSM firewall profile itself, or a documented boot-time reapplication step).

## 9. Scope confirmation

No changes were made to: apex `bobby-fetting.me`, `nas-mcp`/`hb-personal-assistant-*` containers or
networks, application code, database schema/data, credentials/OAuth config, Cloudflare DNS/tunnel
definitions, FORWARD chain policy, `bridge-nf-call-iptables`, DSM firewall enable/disable state, or
any container/network outside the three named in the authorization. No `iptables -F`, no
`docker system prune`, no host-networking or loopback experiment was retried.
