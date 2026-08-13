# NAS PostgreSQL bootstrap correction

## Objective and boundary

This repository-only correction makes the accepted NAS runtime capable of
bootstrapping its canonical PostgreSQL service without bypassing image,
runtime, storage, network, or Compose identity admission. It performs no NAS
deployment, database creation, container start, credential provisioning,
Cloudflare change, OAuth change, or production mutation.

The implementation is stacked on the remote MCP candidate so the remote live
gate can bind its data-plane dependency in the same review. Cloudflare and
OAuth provisioning remain excluded.

## Repository truth corrected

- Image admission now covers app, web, PostgreSQL 17.10, and proxy archives,
  verifies exact linux/amd64 loaded config identities, and issues an
  engine-bound deployable manifest.
- Runtime admission is generated from canonical smoke and pilot Compose JSON
  renders and binds exact image references/config IDs for all six services.
- PostgreSQL bootstrap is two phase. Prepare creates the canonical stopped
  Compose container/network and records its real identity; start revalidates
  before mutation, starts only that container, waits for health, and repeats
  storage/network/image checks.
- The resource artifact records an operator-reviewed minimum free-space floor,
  not an immutable initial free-space measurement. Numeric PostgreSQL tuning
  remains absent.
- The canonical data network is explicitly
  `my-pa-nas-contract_data-plane`, internal, and Compose-owned.
- Gateway and both workers depend on healthy PostgreSQL. Alembic remains a
  separate operator command and derives the repository's single current head.
- NAS tooling accepts an explicit Docker path, requires Python 3.12+, reports
  unavailable Docker authority, no longer needs Ruby to inspect the closed
  lifecycle YAML shape, and supports either `sha256sum` or `shasum`.
- Remote MCP admission refuses noncanonical/orphaned networks and requires the
  verified, healthy canonical PostgreSQL Compose service on its admitted image.

## Prohibited alternatives

The correction explicitly rejects or documents as prohibited:

- `postgresql_default`;
- `ops/compose/postgres.yml` for NAS provisioning;
- ad-hoc PostgreSQL containers;
- direct production `docker compose up postgres` outside the bootstrap wrapper;
- migration as a container or service-start side effect.

## Terminal architecture

The admitted terminal design remains the canonical six-service `my-pa` NAS
runtime plus the separately enabled remote MCP/Cloudflare edge. A
PostgreSQL-only state is temporary bootstrap state and cannot pass ordinary
six-service health or operational diagnostics.

## Evidence and residual prerequisites

Repository validation on the corrective branch produced:

- Ruff format and lint: clean across the repository;
- mypy: 249 source files clean;
- FAST: 5,149 passed, 720 deselected;
- non-database security: 317 passed, 177 deselected;
- NAS/architecture: 2,755 passed;
- `git diff --check`: clean.

The dedicated pull request records its exact branch, base, head, tree, changed
paths, and isolated-database CI result. Live NAS execution remains deliberately unperformed. The operator
must still provide a clean exact-head NAS checkout, four verified archives, an
exact proxy digest, owner-only environment/credential files, Docker authority,
Python 3.12+, a reviewed minimum free-space floor, runtime and PostgreSQL
admission publication, backup/restore destinations, private identity/ingress
configuration, and the separate pilot acceptance/activation artifacts.
