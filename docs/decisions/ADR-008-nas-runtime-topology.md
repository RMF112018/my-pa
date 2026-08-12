# ADR-008: NAS runtime topology and authority boundaries

**Status:** Accepted; implementation staged as NAS-01 through NAS-10
**Decision date:** 2026-08-12
**Repository basis:** `main@c10ecf397e1556ac5da64ff49a608aa8e963cdb3`, tree `838169552d9b8db92c5ba38be93fd6dfc9fbac04`

## Context

The current candidate runs PostgreSQL and application processes on a Mac. That
is not the durable target: application-owned PostgreSQL data and filesystem
state must live on NAS-local storage. macOS remains necessary only for Apple
APIs protected by TCC. Browser, PWA, and iPhone are application clients and
must never receive database or NAS-share authority.

The existing `ops/compose/postgres.yml` is intentionally retained as a local
development tool. Its named volume, loopback database port, development
password fallback, restart policy, and Mac Docker-VM tuning are not a pilot or
NAS design.

## Decision

### Process placement

The NAS runs PostgreSQL 17.10, the Python gateway, separate enrollment and
capture worker processes, the Next.js web/BFF process, and one private reverse
proxy. Optional MCP operation remains the gateway's existing stdio mode and is
not a network service.

The Mac runs only the Swift Apple source host, its owner-only protected spool,
and a thin outbound transport agent. The Mac receives neither a PostgreSQL
credential nor a general NAS filesystem credential.

### Network and ingress

PostgreSQL and database-bearing processes share an internal data-plane network.
PostgreSQL is not published. Gateway also joins an edge plane so web and proxy
can reach it; web joins that edge plane for Entra authorization-code traffic.
Only gateway and web receive bounded outbound access, restricted by NAS-06's
verified host/DNS firewall allowlist to the required Microsoft Entra/OIDC
endpoints. No application data or database port is exposed by that egress path.

The current gateway hard-binds loopback. NAS-04 must add and verify an explicit
container-mode bind setting so it can listen on `0.0.0.0:8765` inside its own
network namespace while remaining unpublished on the NAS host. NAS-01's
Compose file is non-executable until that dependency is satisfied.

The reverse proxy is the only host-published container. Smoke validation binds
that proxy to loopback; pilot activation uses tailnet-only Tailscale Serve and
never Funnel, Cloudflare, public Internet exposure, or production LAN HTTP.

The proxy is a fail-closed route allowlist:

- browser/PWA and BFF routes go to `my-pa-web`;
- only `POST /remote/v1/capture.create` goes directly to `my-pa-gateway`;
- Apple machine routes will be added only as exact dedicated paths when NAS-07
  freezes their names;
- generic `/v1/{capability}` stays internal and is refused at ingress.

Tailscale identity headers are transport metadata only. They are not a
substitute for Entra, the Remote Capture `ClientCredential`, or the future
dedicated Apple machine credential.

### Filesystem authority

The NAS root is supplied by the operator at activation; it is never a host-root
mount and is not inferred by application code. Its authority classes are:

| Path class | Container authority |
| --- | --- |
| `config` | read-only for app containers that need it |
| `postgres/data` | read-write for PostgreSQL only; NAS-local, never network storage |
| `managed-documents` | scoped read-write for the owning application service only |
| `sources` | read-only for source-reading application processes |
| `goodnotes` | read-only for enrollment/OCR work |
| `app-support` | bounded non-canonical state only |
| `backups` | database-aware backup tooling only |
| `logs` | metadata-safe output only |
| `evidence` | sanitized evidence only |

`my-pa-web` receives no database connection string and no application data-root
mount. Source visibility never authorizes source mutation.

### Authorization and lifecycle

NAS/application code is the Apple authorization authority. It issues
Principal-bound, short-lived, single-use grants. The Mac polls outbound,
validates the grant, performs the existing TCC read, uploads the exact envelope,
and deletes the protected spool item only after verifying a durable,
Principal- and envelope-bound NAS receipt. The Mac cannot mint grants.

Pilot/production browser authentication is Entra. Synthetic/local-operator auth
is scratch-only. Smoke services use `restart: "no"`. The separately activated
pilot overlay may use `unless-stopped` only after NAS-10 passes and the operator
activates the pilot.

Images must be built for and verified against the live NAS platform. The
planning expectation is `linux/amd64`, but NAS-02 must confirm Docker OS and
architecture before any image is deployable, record exact digests and source
identity, and make normal start refuse drift. Normal start never builds.

## Consequences

- The NAS, not a Mac-mounted share, becomes the canonical runtime host.
- Web and phone compromise does not directly expose PostgreSQL or NAS shares.
- Apple TCC remains local to macOS without creating a second application
  authority or database.
- Build, start, migration, backup/restore, ingress activation, and live-data
  activation remain explicit later work packages rather than NAS-01 behavior.
- Tailscale Serve availability and the live NAS platform are deployment-time
  gates. Failure stops activation rather than selecting a weaker fallback.

## Supersession

Changing canonical host, publishing PostgreSQL, routing Remote Capture through
Next.js, allowing generic capability ingress, letting the Mac issue grants, or
changing the private HTTPS/auth selections requires a superseding ADR. Numeric
resource tuning, exact NAS paths, UID/GID, ACLs, image digests, and Apple route
names are measured or frozen in their named later work packages and do not by
themselves supersede this decision.
