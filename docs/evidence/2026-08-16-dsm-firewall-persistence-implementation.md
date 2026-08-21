# DSM Firewall Persistence — Implementation & Reboot-Validation Evidence

**Authorization**: AUTH-MY-PA-DSM-FIREWALL-PERSISTENCE-20260816-003
**Executed**: 2026-08-16, via `ssh bf-nas` (passwordless sudo, confirmed by operator) to TheLakeHouseNAS
**Disposition**: `DSM_FIREWALL_PERSISTENCE_VERIFIED`

Per operator instruction, the DSM-supported CLI tool `synofirewall --export`/`--import` (which
manipulates the same DSM-owned profile the GUI writes to) was used in place of clicking through
Control Panel → Security → Firewall, and treated as satisfying Section 6's "supported Synology DSM
firewall configuration interface" requirement. No `/usr/syno/etc/firewall.d/*.json` file was
hand-edited directly — all changes went through `synofirewall`.

## 1. Pre-change reconfirmation

- Uptime before change: 20 days, 4h12m (no reboot yet).
- `FORWARD_FIREWALL` unchanged from the AUTH-002 recovery state: temporary runtime rules at lines
  6–8 (`172.22.0.0/16`, `172.25.0.0/16`, `172.26.0.0/16` → RETURN), DROP at line 9.
- External: `my-pa-mcp.../healthz` = 200, `/mcp` = 401, `nas-mcp...` = 401.
- No subnet drift from the authorized identities.

## 2. Persistence mechanism used

```
sudo /usr/syno/bin/synofirewall --export                     # captured pre-change profile (backed up)
sudo /usr/syno/bin/synofirewall --import "$(cat <modified-config>)"
sudo /usr/syno/bin/synofirewall --reload
```

Note: `--import` requires the JSON as an **inline argument**, not a file path (passing a path
produces `Cannot parse input as Json value.` — a CLI usage quirk, not a policy issue).

Three new rule objects were added to the exported `1.json` profile (`default`), in the same shape
as the pre-existing custom-subnet rules for `10.0.0.0/24` and `100.64.0.0/10`:

| ruleIndex | ipList | policy | chainList |
|---|---|---|---|
| 3 | 172.22.0.0 / 255.255.0.0 | 0 (Allow) | FORWARD_FIREWALL, INPUT_FIREWALL |
| 4 | 172.25.0.0 / 255.255.0.0 | 0 (Allow) | FORWARD_FIREWALL, INPUT_FIREWALL |
| 5 | 172.26.0.0 / 255.255.0.0 | 0 (Allow) | FORWARD_FIREWALL, INPUT_FIREWALL |
| 6 (was 3) | (any) | 1 (Deny) | FORWARD_FIREWALL, INPUT_FIREWALL |

**Finding**: DSM's rule model couples `FORWARD_FIREWALL` and `INPUT_FIREWALL` on every "global"
adapter rule — this is the same representation already used by the pre-existing `10.0.0.0/24` and
`100.64.0.0/10` rules, not a broadening introduced by this change. Practical impact is negligible:
`172.22.0.0/16` and `172.25.0.0/16` are `internal=true` Docker networks with no route to/from the
internet, so INPUT exposure only affects traffic that could only ever originate from containers
already on those isolated bridges. `172.26.0.0/16` (`cloudflare-egress`, not internal) has only one
member (cloudflared) both before and after this change.

## 3. Apply/reload result

`synofirewall --reload` rebuilt the live `FORWARD_FIREWALL` chain from the persisted profile —
counters reset (confirming a genuine rebuild, not a no-op), management access via `bf-nas`
survived. Rule order confirmed correct: three new subnet RETURNs at lines 6–8, catch-all DROP at
line 9, unchanged otherwise.

## 4. Fresh-connection validation (post-apply, pre-reboot)

- Fresh PostgreSQL (`docker exec`, new SQLAlchemy engine): `DB_CHECK_OK 1`.
- Fresh mcp-origin healthz probe: `{"status":"ok"}`.
- External: healthz=200, /mcp=401, nas-mcp=401.
- **Controlled restart** of `my-pa-mcp-remote` and `cloudflared` (Section 10): both returned to
  healthy within ~30s; fresh DB check after restart: `DB_CHECK_OK 1`; cloudflared re-registered new
  tunnel connections and logged "Environment is healthy"; external re-checks unchanged (200/401/401).

## 5. Reboot preconditions (Section 11)

- Storage: all `md0`–`md4` RAID arrays `active`, `[U]` (no degraded arrays).
- Volumes mounted, capacity healthy (60%/50% used, no full volumes).
- No pending update/maintenance lock found under `/tmp`.
- PostgreSQL healthy pre-reboot.
- DSM-native firewall config already persisted (Section 2) — no separate save step required.
- Pre-reboot uptime recorded: 20 days, 4h20m.

## 6. Controlled reboot and post-reboot validation

`sudo reboot` executed via `bf-nas`. NAS returned within ~90s (post-reboot uptime observed at
1 minute, confirming a genuine cold boot).

- **DSM version unchanged**: 7.3.2-86009.
- **Firewall profile unchanged**: `default`, status true.
- **`FORWARD_FIREWALL` regenerated automatically by DSM**, with zero manual iptables insertion:
  three subnet RETURN rules present at lines 6–8, DROP at line 9, all counters at 0 (fresh chain
  since boot) — proving the rules came from DSM's own boot-time regeneration.
- **Docker network subnets unchanged** post-reboot: `data-plane`=172.22.0.0/16,
  `mcp-origin`=172.25.0.0/16, `cloudflare-egress`=172.26.0.0/16 — no subnet reassignment occurred.
  (Container **IPs within** those subnets did shift on recreate — e.g. my-pa-mcp-remote moved from
  `.2`→`.6` on data-plane and `.2`→`.3` on mcp-origin — this is expected Docker bridge behavior and
  does not affect the subnet-scoped firewall rules.)
- Docker/Container Manager took ~1–2 minutes to come back up after boot (expected); all three
  in-scope containers (`my-pa-mcp-remote`, `cloudflared`, `postgres`) self-recovered to healthy via
  their own restart policy — no manual container start was required.
- **Fresh PostgreSQL connection post-reboot**: `DB_CHECK_OK 1`.
- **cloudflared tunnel post-reboot**: registered 4 new tunnel connections, "Environment is healthy."
- **cloudflared → origin post-reboot**: `{"status":"ok"}` (using the DNS alias `my-pa-mcp-remote`,
  since the container's origin-network IP changed on recreate — DNS-based lookup is robust to this).
- **External my-pa-mcp healthz**: HTTP 200.
- **MCP auth check**: HTTP 401.
- **nas-mcp regression**: HTTP 401, unchanged; container untouched throughout.

## 7. Rollback status

Not needed — all acceptance criteria in Section 16 of the authorization were met. Pre-change
`synofirewall --export` output was captured before any modification for rollback reference (not
retained beyond the session; the modification is fully described in Section 2 above and is
reversible via `synofirewall --import` of the original 4-rule profile followed by `--reload`).

## 8. Prohibited-action attestation

No hand-edit of `/usr/syno/etc/firewall.d/*.json` was performed (all changes went through
`synofirewall --import`/`--reload`). No changes to apex routing, nas-mcp, Cloudflare DNS/Tunnel
config, catch-all DROP removal, blanket `172.16.0.0/12` allowance, `bridge-nf-call-iptables`,
Docker daemon config, Docker network recreation, Compose files, application code, database
schema/data, credentials, DSM/Container Manager upgrade, Task Scheduler, boot scripts, or a
reconciliation daemon. Exactly one NAS reboot was performed, as authorized, combined with no other
maintenance operation.
