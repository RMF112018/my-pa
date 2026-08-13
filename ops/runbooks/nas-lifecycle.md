# NAS lifecycle operations

NAS-09 supplies bounded lifecycle commands; it does not activate or deploy a
NAS. Every command requires `MY_PA_NAS_COMPOSE_FILE` naming the exact Compose
file. The default `MY_PA_LIFECYCLE_MODE=smoke` preserves `restart: "no"` for all
six long-lived services.

## Canonical PostgreSQL bootstrap

A new NAS has no database container or data-plane network, so it cannot enter
the six-service lifecycle in one step. PostgreSQL-only operation is admitted
only as this temporary bootstrap sequence. It uses the canonical
`ops/nas/compose.example.yml`; `postgresql_default`, `ops/compose/postgres.yml`,
ad-hoc containers, and direct `docker compose up postgres` are prohibited.

Set `MY_PA_NAS_DOCKER=/usr/local/bin/docker` on Synology. When the host does not
provide Python 3.12, bootstrap the separately checksummed operator archive from
the clean reviewed build before loading the application candidates:

```sh
export MY_PA_NAS_DOCKER=/usr/local/bin/docker
ops/nas/bootstrap-operator-runtime.sh \
  ARTIFACT_DIRECTORY/operator-runtime.candidate.toml \
  ARTIFACT_DIRECTORY/operator.tar \
  ARTIFACT_DIRECTORY/operator.metadata.json \
  /etc/my-pa/operator-runtime.toml
export MY_PA_NAS_OPERATOR_ADMISSION=/etc/my-pa/operator-runtime.toml
export MY_PA_NAS_PYTHON="$PWD/ops/nas/container-python.sh"
```

The operator container is removed after every invocation, has no network, uses
a read-only root filesystem, drops all capabilities, and is not part of the
persistent Compose topology. Its attached standard input preserves checked-in
heredoc validations. Its narrowly mounted Docker socket and exact host Docker
CLI plus Compose plugin give the gate the same bounded engine authority as the
invoking root operator; only the closed canonical Compose interpolation and
synthetic-acceptance environment names are forwarded, without putting their
values in the command line. No application service receives these mounts. The admission binds
the exact archive/config/platform, source commit/tree, Python/Git/OpenSSL
runtime, and live NAS engine. Do not use an unadmitted image or a host Python
older than 3.12.

`emergency-shutdown.sh` deliberately remains a POSIX host-shell path. It checks
the canonical root-owned mode-0400 Compose file, exact project, and exact six
services through `docker compose config --no-interpolate`. It then discovers
only running containers carrying the exact Compose project label, accepts any
incident-time subset of canonical non-oneoff service labels, stops those exact
container IDs directly, and repeats bounded discovery to contain concurrent
replacements. It refuses unknown/oneoff/duplicate identities and reports stop
errors without claiming success. A final fresh project-label query must return
zero running containers. The stop phase does not reparse or interpolate Compose.
It does not require the deployment environment, Python, the operator admission,
or the operator image, so loss of auxiliary state cannot prevent shutdown.

The invoking identity must already have bounded Docker authority; tooling never
prompts for or changes that authority. PostgreSQL bootstrap has a distinct
root-owned mode-0400 admission because database provisioning must not require
external Entra or web credentials. It selects only the canonical `postgres`
service from the canonical six-service Compose file and proves that fixed
parser-only sentinel values cannot reach that service or its internal network.
Those sentinels never authorize or start another service. Before rendering the
ordinary six-service runtime admission, the owner-only application and web
environment files must contain operator-provisioned non-placeholder values,
and every ordinary Compose variable must be exported. Do not enter secrets at
a command prompt or place them in the repository.

Execute the following phases in order from a clean checkout of the exact image
manifest commit. Paths shown below are the canonical production paths; artifact
filenames under `/etc/my-pa` must not already exist.

1. Set the proven host/tool identity and create the still-empty canonical data
   directory owner-only:

```sh
export MY_PA_NAS_DOCKER=/usr/local/bin/docker
export MY_PA_NAS_PYTHON=/absolute/path/to/python3.12
export MY_PA_NAS_COMPOSE_FILE="$PWD/ops/nas/compose.example.yml"
export MY_PA_NAS_ROOT=/volume1/my-pa
export MY_PA_LIFECYCLE_MODE=smoke
mkdir -p /volume1/my-pa/postgres/data
chmod 0700 /volume1/my-pa/postgres/data
```

2. Load and admit the four exact linux/amd64 images. Generate the separate
   root-owned PostgreSQL bootstrap admission with only the real PostgreSQL
   image ID, database password, and canonical NAS root in the environment:

```sh
ops/nas/load-candidates.sh CANDIDATE_MANIFEST ARCHIVE_DIRECTORY DEPLOYABLE_MANIFEST
"$MY_PA_NAS_PYTHON" ops/nas/generate-postgres-bootstrap-admission.py \
  ops/nas/compose.example.yml DEPLOYABLE_MANIFEST \
  /etc/my-pa/postgres-bootstrap-admission.toml
```

`load-candidates.sh` verifies all four archives before loading app, web,
PostgreSQL, and proxy, then binds exact loaded config IDs to the live engine.
The bootstrap admission binds the canonical source file, selected PostgreSQL
render, internal network, exact loaded image, repository, and live engine. It
contains no database password. Application/web env files and external identity
values are neither read nor required.

3. Select and record a positive operator-reviewed byte floor below current
   available btrfs space. Prepare creates only the canonical PostgreSQL
   container and internal
`my-pa-nas-contract_data-plane` network. It does not start PostgreSQL:

```sh
ops/nas/postgres-bootstrap-prepare.sh \
  DEPLOYABLE_MANIFEST ARCHIVE_DIRECTORY \
  /etc/my-pa/postgres-resources.toml MINIMUM_AVAILABLE_STORAGE_BYTES
```

The generated resource artifact records the real stopped container ID, exact
PostgreSQL image ID, canonical btrfs path, engine identity, CPU/RAM measurement,
canonical internal network, and an operator-reviewed free-space floor. It
records `no_numeric_tuning`; measured resources do not invent tuning values.

4. Start revalidates the same identities before and after starting only that
container, waits for Docker health, and proves PostgreSQL 17.10 readiness:

```sh
ops/nas/postgres-bootstrap-start.sh \
  DEPLOYABLE_MANIFEST ARCHIVE_DIRECTORY /etc/my-pa/postgres-resources.toml
```

5. Export the admitted resource artifact, validate it against the running
   container, take the required initial backup, and invoke migration explicitly:

```sh
export MY_PA_POSTGRES_RESOURCES=/etc/my-pa/postgres-resources.toml
ops/nas/validate-storage.sh
initial_receipt=$(ops/nas/backup.sh EXISTING_OWNER_ONLY_BACKUP_DIRECTORY)
ops/nas/verify-backup-receipt.sh "$initial_receipt"
export MY_PA_VERIFIED_BACKUP_RECEIPT="$initial_receipt"
ops/nas/migrate.sh
```

Migration derives the repository's single Alembic head at execution time; no
revision is copied into deployment state.

6. Take a post-migration backup and restore it into a new scratch database.
   Before entering the ordinary six-service lifecycle, provision every real
   application/web value and generate the ordinary runtime admission:

```sh
post_receipt=$(ops/nas/backup.sh EXISTING_OWNER_ONLY_BACKUP_DIRECTORY)
ops/nas/verify-backup-receipt.sh "$post_receipt"
export MY_PA_SCRATCH_DATABASE_URL=postgresql+psycopg://my_pa@postgres:5432/my_pa_scratch_BOOTSTRAP
ops/nas/restore-to-scratch.sh "${post_receipt%.sha256}" my_pa_scratch_BOOTSTRAP
"$MY_PA_NAS_PYTHON" ops/nas/generate-runtime-admission.py \
  ops/nas/compose.example.yml ops/nas/compose.pilot.example.yml \
  DEPLOYABLE_MANIFEST /etc/my-pa/runtime-admission.toml
ops/nas/start.sh DEPLOYABLE_MANIFEST ARCHIVE_DIRECTORY
ops/nas/health.sh
```

The scratch URL is non-secret and must name only the verified Compose database;
authentication remains in the protected service environment. Gateway and both
workers wait for healthy PostgreSQL. The temporary PostgreSQL-only state is not
a terminal runtime.

Run `preflight.sh IMAGE_MANIFEST ARCHIVE_DIRECTORY` before `start.sh` with the
same arguments. Both reverify exact loaded images and parse Compose. Start uses
only `up --detach --no-build --pull never`.

The root-published mode-0400 `/etc/my-pa/runtime-admission.toml` closes the
remaining Compose interpolation boundary. It binds the complete deployable
image manifest, exact NAS engine, distinct canonical smoke and pilot rendered
Compose digests, and all six resolved service image IDs (app role for
gateway/workers, web, PostgreSQL, and proxy). Smoke is always rendered from the
base file alone; pilot is always rendered from the ordered base-then-overlay
file list. Every lifecycle command validates its mode's rendered config; commands acting
on an existing stack also inspect every running container's image and Compose
project/service labels. An incomplete manifest, changed env image, old bundle,
or container created from a different image refuses. Start catches every failed
post-up check, stops the partial stack, and verifies zero running services.

The remaining commands are `stop.sh`, `restart.sh`, `status.sh`, `health.sh`,
`logs.sh SERVICE`, `diagnostics.sh`, and `emergency-shutdown.sh`. Restart refuses a missing
PostgreSQL instance and verifies that its container identity did not change.
Stop and emergency shutdown do not remove containers, volumes, bind mounts, or
data. Emergency shutdown deliberately does not load pilot or lifecycle evidence:
it accepts only root-owned mode-0400 `/etc/my-pa/compose.yml`, exact project
`my-pa-nas-contract`, and the closed six-service set. Logs accept only those
services and are bounded to 200 lines.

`health.sh` proves process/database readiness only and says so. Full operational
diagnostics additionally require fresh enrollment/capture worker heartbeats,
web and proxy reads, a bounded authenticated `GET /api/system` through the
browser/BFF to the gateway, and a proxy-classification probe proving
`/remote/v1/capture.create` cannot fall through to Next.js. The authenticated
probe requires an exact private `/api/system` URL and a current session token in
a caller-owned, mode-0400, single-link file; its value is read only into the HTTP
Cookie header and is never printed. The URL and host must exactly match the
canonical origin returned by the same signature-validated pilot activation gate;
caller agreement alone is insufficient. Redirects are never followed, and every
3xx response fails, so the Cookie cannot be forwarded to a redirect target.
Diagnostics also require runtime
filesystem/permission probes, a configured disk floor, a recent verified backup
receipt, and a configured maximum age for the last Apple admission. Missing
configuration or a stale signal refuses.

## Pilot restart policy

[`../nas/compose.pilot.example.yml`](../nas/compose.pilot.example.yml) contains
only `restart: unless-stopped` for PostgreSQL, gateway, both workers, web, and
proxy. GoodNotes one-shot and Frontier child-process profiles remain
`restart: "no"` and are not in the pilot overlay.

Pilot evidence is read only from root-owned mode-0700
`/etc/my-pa/pilot-evidence`; each expected file must be root-owned mode-0400,
regular, single-link, and canonical. The acceptance and activation artifacts
carry detached RSA-SHA256 signatures verified against the public key whose
digest is pinned in `trust.toml`; only RSA public keys of at least 3072 bits are
accepted. All three bind the exact NAS Docker engine;
the signed artifacts additionally bind repository commit/tree, base Compose,
runtime contract, deployable image manifest, runtime-admission and resolved
Compose digests, reviewed head, and acceptance digest. NAS-10 completion must
precede activation, both timestamps require explicit timezones, and the private
origin is parsed as HTTPS on a true `.ts.net` hostname with no userinfo,
unapproved port, path, query, or fragment. The live clean checkout and Docker identity must match. Arbitrary TOML
or an older otherwise-valid image bundle refuses. Checked-in examples
intentionally refuse. Provisioning the trusted directory/key or creating artifacts,
supplying credentials, enabling Tailscale Serve, or running these commands on a
NAS remains outside NAS-09.
