# Compose definitions

Docker Compose files for the local services `my-pa` depends on. Each file is
run explicitly by path from the repository root; there is no default
`docker-compose.yml` and no aggregate stack.

| File | Service | Purpose |
| --- | --- | --- |
| [`postgres.yml`](postgres.yml) | `postgres` (`my-pa-postgres`) | The canonical `my_pa` PostgreSQL 17 database |

```sh
docker compose -f ops/compose/postgres.yml up -d
docker compose -f ops/compose/postgres.yml down
```

The PostgreSQL runbook — connection URL, password handling, psql access, and
how to reset the database — is in
[`../postgres/README.md`](../postgres/README.md).

## Conventions

- **Pin exact image minors.** `postgres:17.10`, not `postgres:17`, so rebuilding
  this machine reproduces the same server.
- **No secrets in a compose file.** Credentials are interpolated from the
  environment with a documented, non-sensitive local-development default:
  `${MY_PA_DB_PASSWORD:-my_pa_local_dev}`.
- **Named volumes with explicit `name:`.** Data must survive
  `docker compose down` and must not depend on a project-name prefix.
- **Non-default host ports.** Services bind a port offset from the convention
  (PostgreSQL on `5433`) so an unqualified local client cannot connect here by
  accident.
- **A healthcheck per service**, so `up -d` has a meaningful ready signal.
- **Tuning flags carry a comment** stating the reason and the machine they are
  sized for.
