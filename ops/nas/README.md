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
- [`image-manifest.example.toml`](image-manifest.example.toml) separates the
  OCI platform-child digest, Docker image/config ID, and exported archive
  checksum. Its candidate status and placeholder evidence deliberately fail
  [`image_gate.py`](image_gate.py); only `--live` inspection of the target
  Docker engine and all three exported archives can pass.
- Offline app/web/PostgreSQL archives are addressed at runtime by the exact
  loaded Docker image/config ID because `docker load` does not preserve a
  registry `RepoDigest`. PostgreSQL candidate creation separately verifies the
  exported child against the pinned `postgres:17.10` parent index. The OCI
  child digest, loaded config ID, and archive checksum remain distinct.
- [`start.sh`](start.sh) is an intentional refusal until the exact live NAS
  reports `linux/amd64`, loaded digest resolution is proven, and NAS-04 adds the
  gateway container bind. A later activation may use only Compose `--no-build
  --pull never` after that gate passes.
- [`build-candidates.sh`](build-candidates.sh) refuses a dirty source tree and
  exports linux/amd64 app/web archives plus BuildKit identity metadata. Its
  output is still non-deployable. [`load-candidates.sh`](load-candidates.sh)
  remains an explicit operator/device refusal until the live NAS and the exact
  official PostgreSQL platform-child archive are available.

The existing [`../compose/postgres.yml`](../compose/postgres.yml) remains a
single-Mac local-development service. It is not a NAS, pilot, or production
compose file.

NAS-03 adds an unpublished PostgreSQL bind-mount contract plus explicit
[`validate-storage.sh`](validate-storage.sh), [`migrate.sh`](migrate.sh),
[`backup.sh`](backup.sh), and
[`restore-to-scratch.sh`](restore-to-scratch.sh) operations. They all require a
live-verified [`postgres-resources.example.toml`](postgres-resources.example.toml)
replacement bound to the exact Docker engine and canonical local filesystem.
The checked-in example refuses, and numeric PostgreSQL tuning remains absent
until CPU, memory, free storage, and filesystem type are measured on that NAS.
Migration is never an application startup side effect; canonical migration also
requires a recent backup receipt. Backups are custom-format, integrity-listed,
owner-only artifacts outside the repository. Restore accepts only a new
`my_pa_scratch_*` database and retains a failed scratch target for diagnosis.

NAS-04/05 add the validated `container` gateway bind mode and the
[`runtime-services.example.toml`](runtime-services.example.toml) identity
contract. [`runtime_gate.py`](runtime_gate.py) binds each app container to its
exact Compose service, loaded image, dedicated non-root UID/GID, networks,
mounts, and absence of host publication or privilege. Its live permission pass
requires reads through allowed roots, refuses writes to config/source roots,
and performs a create/sync/rename/delete probe only in the gateway's managed
root. The checked-in example refuses until live NAS IDs and ACLs are provisioned.

Later packages own executable behavior:

- NAS-02 images supply app/web Dockerfiles and the
  platform/digest/archive contract.
  Live NAS inspection, image load, and deployable-manifest issuance remain
  operator/device gates; no image here is currently deployable;
- NAS-03 PostgreSQL storage, migration, backup, and scratch restore;
- NAS-04/05 services and filesystem permissions;
- NAS-06 private HTTPS ingress, Entra pilot origin, and a verified Microsoft
  OIDC/JWKS egress allowlist for gateway and web;
- NAS-07 Apple grant/poll/admit/receipt protocol;
- NAS-08 source placement; NAS-09 lifecycle; NAS-10 acceptance.
