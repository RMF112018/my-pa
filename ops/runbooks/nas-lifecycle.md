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
external identity or web credentials. It selects only the canonical `postgres`
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
contains no database password. Application/web env files and browser identity
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

5. Synology DSM `FORWARD_FIREWALL` contains RELATED/ESTABLISHED ACCEPT and
   broad source RETURNs. Data-plane protection is a repository-owned
   `MY_PA_DATA_PLANE` chain installed as FORWARD rule 1, before
   `FORWARD_FIREWALL`. It ACCEPTs only exact canonical same-bridge/subnet
   traffic, DROPs every other packet that touches the data-plane bridge, and
   RETURNs unrelated forwarding to DSM. Plan, explicitly admit, and verify:

```sh
export MY_PA_NAS_IPTABLES=/usr/bin/iptables
export MY_PA_NAS_IPTABLES_SAVE=/usr/bin/iptables-save
export MY_PA_NAS_IP=/usr/bin/ip
ops/nas/synology-data-plane-firewall.sh plan
export MY_PA_CONFIRM_FIREWALL_MUTATION=my-pa-nas-contract_data-plane
ops/nas/synology-data-plane-firewall.sh apply
unset MY_PA_CONFIRM_FIREWALL_MUTATION
ops/nas/synology-data-plane-firewall.sh check
```

The preserved bounded DSM observation established this legitimate baseline:

```text
FORWARD
  -j FORWARD_FIREWALL
  -j DEFAULT_FORWARD

DEFAULT_FORWARD
  -j DOCKER-USER
  -j DOCKER-ISOLATION-STAGE-1
```

That baseline is DSM/Docker infrastructure, not MY-PA enforcement. On the
observed host, requesting `iptables -I FORWARD 1 -j MY_PA_DATA_PLANE` produced
this redirected shape instead of a rule at the head of built-in `FORWARD`:

```text
FORWARD
  -j FORWARD_FIREWALL
  -j DEFAULT_FORWARD

DEFAULT_FORWARD
  -j MY_PA_DATA_PLANE
  -j DOCKER-USER
  -j DOCKER-ISOLATION-STAGE-1
```

The script recognizes that redirection only when both chains and all three
`DEFAULT_FORWARD` jumps match exactly. It then withdraws only the exact
`MY_PA_DATA_PLANE` attachment, reports
`UNSUPPORTED_DSM_FORWARD_REDIRECTION`, and proves restoration of the complete
Docker-bearing baseline. Successful rollback retains `FORWARD_FIREWALL`,
`DEFAULT_FORWARD`, `DOCKER-USER`, and `DOCKER-ISOLATION-STAGE-1`; none is owned
or deleted by this script. Generic `DEFAULT_FORWARD` content, additional or
duplicate MY-PA references, a goto in place of the expected jump, or any other
topology is foreign or ambiguous and is not attributed to MY-PA. Do not retry,
accept `DEFAULT_FORWARD` as enforcement, or edit the check; a reviewed platform
mechanism that can enforce the same pre-DSM boundary is required before
deployment continues.

The script derives the current network ID, Synology bridge name, and subnet
from the exact internal Compose-owned data plane. Built-in and user-chain rules
are read from `iptables-save -t filter`. Before `check` treats enforcement as
effective, or any mutating path treats `MY_PA_DATA_PLANE` as owned, the script
enumerates every exact jump and goto to that chain across the filter table.
Only one supported attachment is allowed: the exact direct FORWARD jump in the
accepted direct topology, or the exact redirected DEFAULT_FORWARD jump in the
Docker-bearing topology above. A reference from any other chain, any goto,
both supported references at once, or multiple references fails closed.
`check` and `plan` do not mutate; `apply`, `remove`, empty-chain restoration,
and cleanup do not populate, detach, flush, or delete the chain when initial
ownership is foreign or ambiguous.

`DEFAULT_FORWARD` is not an accepted enforcement location for this gate.
Admission means exact four-rule `MY_PA_DATA_PLANE` contents, FORWARD jumps
`MY_PA_DATA_PLANE` then `FORWARD_FIREWALL`, and no source-only data-plane RETURN
in `FORWARD_FIREWALL`. `apply` is idempotent and requires the exact confirmation
value; `remove` restores the legacy source-only RETURN before withdrawing an
exactly owned attachment, then re-enumerates the whole filter table. If any
reference remains, it retains the chain contents and refuses cleanup. Only a
zero-reference proof immediately before flush permits `-F`; the script then
proves the chain empty and repeats the zero-reference proof immediately before
`-X`. Empty-chain deletion also repeats the proof before deletion. `remove`
resumes missing-attachment cleanup; `apply` may populate only an empty,
unreferenced chain; a proven baseline with the chain absent is already removed.

These checks narrow but cannot eliminate races between separate iptables
inspection and mutation commands; they do not claim atomic ownership or
cleanup. A newly appearing reference is detected at the next proof and blocks
the next destructive step. Operators must treat any rollback or cleanup
failure as retained state requiring inspection, never as successful removal.
The topology contract comes from the preserved bounded DSM observation; this
corrective change did not repeat a live probe or mutate a live firewall.

The rule set is runtime firewall state, not a DSM profile mutation. A DSM
firewall reload or NAS reboot can remove it, so re-run
`apply` before lifecycle recovery. Database operations, six-service
start/restart, and health fail closed when `check` does not pass. Do not add a
broad subnet rule to `INPUT_FIREWALL`, disable DSM firewall, wire Docker
isolation globally, or treat data-plane `check` as admission of the
ingress-plane or Cloudflare-egress gates. Passing data-plane alone does not
authorize GoodNotes validation.

The canonical ingress plane needs the same bounded same-bridge allowance so
the proxy can reach the web service. It does not exist during PostgreSQL-only
bootstrap. Do not attempt ingress admission yet. After ordinary runtime
admission exists, the first `start.sh` invocation in step 7 creates the admitted
six-service Compose topology in a stopped state and must refuse before `up` for
the missing ingress rule. Step 7 then admits the real network and reruns start.

The ingress gate first requires the data-plane rule to remain effective, then
requires one exact ingress bridge/subnet rule in the second
`FORWARD_FIREWALL` position. Apply inserts only at position 2, preserving the
data-plane rule at position 1; removal targets only the exact ingress rule.
Start, restart, health, and diagnostics fail closed if the ingress rule is
missing. After a DSM firewall reload or reboot, reapply the data-plane rule
first and the ingress-plane rule second before lifecycle recovery.

6. Export the admitted resource artifact, validate it against the running
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

7. Take a post-migration backup and restore it into a new scratch database.
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
# This first invocation prepares the stopped topology. Confirm that it refuses
# specifically because the ingress-plane firewall rule is not effective. Any
# other refusal is a blocker and must not be treated as successful preparation.
ops/nas/start.sh DEPLOYABLE_MANIFEST ARCHIVE_DIRECTORY
ops/nas/synology-ingress-plane-firewall.sh plan
export MY_PA_CONFIRM_FIREWALL_MUTATION=my-pa-nas-contract_ingress-plane
ops/nas/synology-ingress-plane-firewall.sh apply
unset MY_PA_CONFIRM_FIREWALL_MUTATION
ops/nas/synology-ingress-plane-firewall.sh check
ops/nas/start.sh DEPLOYABLE_MANIFEST ARCHIVE_DIRECTORY
ops/nas/health.sh
```

The first `start.sh` invocation above is an expected nonzero gate, not a
successful start. Its bounded cleanup must leave zero running runtime services
and print
`Synology ingress-plane firewall is not admitted; stopping the prepared stack`.
Continue only after checking that exact refusal and confirming that the
canonical ingress network now exists. The second invocation is the only one
that may reach `up`.

The scratch URL is non-secret and must name only the verified Compose database;
authentication remains in the protected service environment. Gateway and both
workers wait for healthy PostgreSQL. The temporary PostgreSQL-only state is not
a terminal runtime.

Run `preflight.sh IMAGE_MANIFEST ARCHIVE_DIRECTORY` before `start.sh` with the
same arguments. Both reverify exact loaded images and parse Compose. Start uses
only `create --no-build --pull never` followed, after both firewall gates pass,
by `up --detach --no-build --pull never`.

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
