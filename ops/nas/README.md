# NAS runtime scaffold

This directory records the accepted NAS runtime contract. NAS-01 is
non-deploying: these files do not create a NAS root, build images, start
containers, enable Tailscale Serve, initialize or migrate a database, read live
personal data, or mint credentials.

Files:

- [`runtime-contract.toml`](runtime-contract.toml) is the machine-readable
  topology and authority contract used by architecture tests.
- [`compose.example.yml`](compose.example.yml) is a disabled example of the
  future container layout. Every image, secret, NAS path, platform, and service
  identity is required explicitly; it has no usable defaults. It also names a
  NAS-04 gateway bind setting that does not exist yet, deliberately preventing
  this topology contract from being mistaken for a runnable stack.
- [`proxy-allowlist.example.caddy`](proxy-allowlist.example.caddy) shows the
  fail-closed route ordering. It is mounted only by the disabled example.

The existing [`../compose/postgres.yml`](../compose/postgres.yml) remains a
single-Mac local-development service. It is not a NAS, pilot, or production
compose file.

Later packages own executable behavior:

- NAS-02 images, platform/digest manifest, load, and no-build start;
- NAS-03 PostgreSQL storage, migration, backup, and scratch restore;
- NAS-04/05 services and filesystem permissions;
- NAS-06 private HTTPS ingress, Entra pilot origin, and a verified Microsoft
  OIDC/JWKS egress allowlist for gateway and web;
- NAS-07 Apple grant/poll/admit/receipt protocol;
- NAS-08 source placement; NAS-09 lifecycle; NAS-10 acceptance.
