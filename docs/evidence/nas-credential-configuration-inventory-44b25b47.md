# NAS credential and configuration inventory — candidate `44b25b47`

**Status:** non-secret, candidate-bound repository inventory and remediation
receipt. It is neither a provisioning record, a runtime admission, a backup
receipt, nor an activation receipt.

**Candidate identity:** repository commit
`44b25b4709772a760ed35e3f2e4035a266ae98d7`; repository tree
`b70c2bd7cd72345f6fff9bf1ad9c5c0692dde7b4`.

**Objective:** give future operators and developers an exact-name, no-value
trail for the documented public-browser deployment configuration at this
candidate, while preserving the existing no-provision and no-runtime-change
boundary.

**Evidence boundary:** this inventory is derived from checked-in examples,
schemas, Compose definitions, scripts, runbooks, and previously reported
non-secret NAS metadata. It does not inspect, list, copy, create, or report
the contents of any NAS secret or configuration file. A stated path contract
does not establish that a credential exists at that path.

## Current state deliberately limited to known metadata

| Item | State | Evidence boundary |
| --- | --- | --- |
| Candidate checkout | **Provisioned clean** at `/volume1/my-pa/releases/44b25b4709772a760ed35e3f2e4035a266ae98d7-remediation-20260921T191500Z` (previously reported root-owned `0700`) | Previously reported metadata only; this record does not inspect the NAS. |
| Candidate image manifest | **Deployable image manifest reported** at `/etc/my-pa/image-manifest.44b25b47-20260921T182515Z.toml` | This record does not verify loaded-image state, runtime admission, or a running candidate image. |
| Ordinary runtime admission for this candidate | **Required; not reported provisioned** | Required canonical path: `/etc/my-pa/runtime-admission.toml`. |
| `production.env` | **Required; reported absent** at `/volume1/my-pa/secrets/production.env` | No contents were inspected. |
| `nas.env` and `web.env` | **Required; not inspected / not reported provisioned** at their documented paths | Documentation establishes the path contract, not NAS existence; no contents were inspected. |
| Fresh backup and verified receipt | **Required; not provisioned** | The previously reported September 14 receipt is stale under the 24-hour gate. |
| NAS-10 and pilot activation evidence | **Required for pilot lifecycle; not provisioned** | Signed, exact-head evidence is not reported. |
| Existing runtime | **Out of scope** | Inspect only through lifecycle/runtime-identity gates; do not infer its state from Compose provenance-path labels. |

`Required` is not permission to create an item. A missing or unreported item
remains so until a root-operated, no-overwrite procedure is independently
reviewed and executed under the deployment playbook.

## File, owner, and handling contract

| Artifact/path | Classification | Required metadata and handling | Consumers |
| --- | --- | --- | --- |
| `/volume1/my-pa/secrets/production.env` | Mixed secret and non-secret environment values | Outside Git; owner-only. Use an existing owner-only parent; never put values on a command line or commit a filled copy. | `ops/nas/validate-production-env.py`; deployment-environment export; Compose interpolation. With `--deployment-manifest`, the validator binds only supplied source commit/tree to that manifest. |
| `/volume1/my-pa/secrets/nas.env` | Secret-bearing gateway/application/worker environment | Outside Git; owner-only. The `env_file` for `gateway`, `worker-enrollment`, and `worker-capture`. | `ops/nas/compose.example.yml`; application settings; PostgreSQL client connection. |
| `/volume1/my-pa/secrets/web.env` | Secret-bearing BFF/web environment | Resolved regular path outside Git; mode `0600`; UID equals `web_env_owner_uid` in ingress evidence. The `env_file` for `web`. | `ops/nas/compose.example.yml`; Next.js/BFF passkey and session service. |
| `/volume1/my-pa/secrets/frontend-cloudflared/` | Secret credential directory | Owner-only directory containing frontend tunnel `credentials.json`; never track or copy it into a receipt. | `frontend-cloudflared` read-only mount at `/run/secrets/cloudflared`; `ops/nas/render-frontend-cloudflared-config.py`. |
| `/etc/my-pa/postgres-bootstrap-admission.toml` | Non-secret, sensitive integrity artifact | Root-owned, mode `0400`, regular, single link; new creation only, without overwrite. | PostgreSQL bootstrap gates. |
| `/etc/my-pa/runtime-admission.toml` | Non-secret, sensitive integrity artifact | Root-owned, mode `0400`, regular, single link; publish only after owner-only environment files and ordinary Compose interpolation are complete. | `preflight.sh`, `start.sh`, lifecycle/runtime-identity gates, NAS-10 gate. |
| `/etc/my-pa/pilot-evidence/` | Non-secret, signed integrity evidence | Root-owned mode `0700` directory; expected artifacts root-owned mode `0400`, regular, single-link, canonical path, no-follow read. | `lifecycle_gate.py`; NAS-10/pilot signature validation. |
| `/etc/my-pa/nas10-review-trust.toml` | Non-secret trust configuration | Root-owned mode `0400`; pins reviewer public-key digest. | NAS-10 acceptance. |
| Owner-only backup directory outside both checkouts | Sensitive backup data and checksum receipt | Existing physical, unlinked absolute directory; exact mode `0700`; no repository location; unique/no-collision output. | `backup.sh`, `verify-backup-receipt.sh`, `migrate.sh`, restore-to-scratch. |

Where a checked-in playbook specifies a mode, it is stated above. Where it
says only `owner-only`, this document intentionally does not invent a mode.
The approved root procedure must impose and verify it before use.

## Configuration inventory

All names below are names and semantics only. No value, token, private key,
password, password-bearing URL, cookie, tunnel credential, credential ID,
signature, or configuration-file content belongs in this record, a ticket,
terminal history, receipt, or repository file.

### `production.env`: canonical public-browser production contract

Schema: `ops/nas/production-environment.schema.toml`.

| Classification | Exact keys |
| --- | --- |
| Secret, required | `MYPA_SESSION_SERVICE_SECRET`, `MY_PA_SESSION_SERVICE_SECRET`, `MYPA_WEBAUTHN_BFF_SECRET`, `MY_PA_WEBAUTHN_BFF_SECRET`, `MY_PA_DB_PASSWORD`, `MY_PA_FRONTEND_CLOUDFLARED_CREDENTIALS_DIR` (the directory path is sensitive because it identifies the credential location). |
| Non-secret, required | `NODE_ENV`, `MYPA_AUTH_MODE`, `MYPA_CANONICAL_ORIGIN`, `MYPA_GATEWAY_URL`, `MYPA_GATEWAY_AUTH_MODE`, `MY_PA_WEBAUTHN_RP_ID`, `MY_PA_WEBAUTHN_RP_NAME`, `MY_PA_WEBAUTHN_ALLOWED_ORIGINS`, `MY_PA_APP_IMAGE_ID`, `MY_PA_WEB_IMAGE_ID`, `MY_PA_POSTGRES_IMAGE_ID`, `MY_PA_PROXY_IMAGE`, `MY_PA_PROXY_IMAGE_DIGEST`, `MY_PA_UID`, `MY_PA_GID`, `MY_PA_PROXY_UID`, `MY_PA_PROXY_GID`, `MY_PA_NAS_ROOT`, `MY_PA_NAS_ENV_FILE`, `MY_PA_WEB_ENV_FILE`, `MY_PA_FRONTEND_CLOUDFLARED_IMAGE`, `MY_PA_FRONTEND_CLOUDFLARED_CONFIG`, `MY_PA_FRONTEND_CLOUDFLARED_UID`, `MY_PA_FRONTEND_CLOUDFLARED_GID`, `MYPA_SOURCE_COMMIT`, `MYPA_SOURCE_TREE`. |
| Must be absent or empty | `MYPA_SESSION_SERVICE_URL`. |
| Forbidden when non-empty | `NEXT_PUBLIC_AZURE_AD_CLIENT_ID`, `NEXT_PUBLIC_AZURE_AD_TENANT_ID`, `NEXT_PUBLIC_AZURE_AD_AUTHORITY`, `NEXT_PUBLIC_MSAL_CLIENT_ID`, `NEXT_PUBLIC_MSAL_AUTHORITY`, `NEXT_PUBLIC_ENTRA_CLIENT_ID`, `NEXT_PUBLIC_ENTRA_TENANT_ID`, `MYPA_ENTRA_CLIENT_ID`, `MYPA_ENTRA_CLIENT_SECRET`, `MY_PA_ENTRA_CLIENT_ID`, `MY_PA_ENTRA_CLIENT_SECRET`, `MYPA_SESSION_SECRET`, `MYPA_LOCAL_OPERATOR_SECRET`. |

Required constraints are production/passkey browser mode, the documented
canonical origin and WebAuthn RP/origin pair, matching session aliases,
matching WebAuthn aliases distinct from the session pair, and the schema's
minimum secret lengths. The validator with `--deployment-manifest` binds only
`MYPA_SOURCE_COMMIT` and `MYPA_SOURCE_TREE` to `repository_commit` and
`repository_tree`; it validates image-ID/digest syntax but does not bind image
identities to that manifest. The deployable image manifest, image gate, and
runtime admission establish exact image identity, which runtime identity gates
then compare with a running service. Internal BFF transport may use
`MYPA_GATEWAY_AUTH_MODE=local_operator`; that does not authorize
`local_operator` as browser `MYPA_AUTH_MODE`.

### `nas.env`: gateway and workers

The candidate Compose contract loads this file into `gateway`,
`worker-enrollment`, and `worker-capture`. It does not establish a complete
`nas.env` schema, and `validate-production-env.py` does not read this file.
The following names are a bounded inventory from checked-in application
examples, schema, Compose precedence, and runtime gates; they do not claim
that every named value is present in this one file.

| Classification | Exact keys | Notes |
| --- | --- | --- |
| Secret-bearing/protected Python-side distribution | `MY_PA_DATABASE_URL`, `MY_PA_SESSION_SERVICE_SECRET`, `MY_PA_WEBAUTHN_BFF_SECRET` | The database URL includes the `my_pa` role credential when provisioned. Protected delivery must yield the paired runtime values without printing, logging, or recording them. |
| Non-secret application controls | `MY_PA_ENVIRONMENT`, `MY_PA_LOG_LEVEL`, `MY_PA_REDACTION_ENABLED`, `MY_PA_CONTRACT_STRICT_MODE`, `MY_PA_MAX_PAGE_SIZE`, `MY_PA_DEFAULT_PAGE_SIZE`, `MY_PA_MAX_FETCH_BYTES`, `MY_PA_MAX_ENROLLMENT_DEPTH`, `MY_PA_AUTH_MODE`, `MY_PA_REMOTE_INGRESS_ENABLED`, `MY_PA_MANAGED_DOCUMENT_ROOT` | Production preserves redaction and strict contract parsing. |
| Entra-related application settings | `MY_PA_ENTRA_TENANT_ID`, `MY_PA_ENTRA_CLIENT_ID`, `MY_PA_ENTRA_ISSUER`, `MY_PA_ENTRA_JWKS_URI` | Not required for the public-browser baseline. `ingress_gate.py` rejects a running gateway or web container exposing an environment-name containing `ENTRA`. |

Compose supplies `MY_PA_GATEWAY_BIND_MODE=container`, the managed-document
root, and for gateway `MY_PA_AUTH_MODE=local_operator` plus
`MY_PA_REMOTE_INGRESS_ENABLED=true` as service-level values. The ingress gate
checks the resulting gateway environment for the latter two settings and
rejects Entra-named variables; that is a running-container check, not
validation that `nas.env` exists.

### `web.env`: BFF/web

The candidate Compose contract loads this file into `web`, then service
`environment` takes precedence for `NODE_ENV`, `MYPA_AUTH_MODE`,
`MYPA_GATEWAY_URL`, `MYPA_GATEWAY_AUTH_MODE`, `MYPA_CANONICAL_ORIGIN`, and
`MYPA_SESSION_SERVICE_SECRET`. `validate-production-env.py` does not read this
file. Protected BFF/Python distribution must still produce matching
`MYPA_SESSION_SERVICE_SECRET`/`MY_PA_SESSION_SERVICE_SECRET` and
`MYPA_WEBAUTHN_BFF_SECRET`/`MY_PA_WEBAUTHN_BFF_SECRET` pairs.

Only the final running-container environment is enforced by `ingress_gate.py`:
production/passkey web values, internal gateway URL and local-operator
transport, a sufficiently long session secret, absent/empty
`MYPA_SESSION_SERVICE_URL`, no database/PostgreSQL-named web variable, no web
mounts, and no Entra-named variable in web or gateway. This is not evidence a
file exists or that physical-device passkey validation occurred.

### Lifecycle-only interpolation and diagnostic inputs

These names are not permission to place secrets in a shell environment. Supply
them only through the closed invocation context prescribed by the playbook and
validate them against admissions/manifests rather than copying them into
`nas.env` or `web.env`.

| Function | Classification and exact names | Consumers |
| --- | --- | --- |
| Host/tool and rendered Compose identity | Non-secret: `MY_PA_NAS_DOCKER`, `MY_PA_NAS_PYTHON`, `MY_PA_NAS_COMPOSE_FILE`, `MY_PA_NAS_COMPOSE_PLUGIN`, `MY_PA_LIFECYCLE_MODE`, `MY_PA_IMAGE_MANIFEST`, `MY_PA_NAS_ROOT` | `preflight.sh`, `start.sh`, `restart.sh`, lifecycle/runtime gates. |
| Six-service interpolation | Non-secret: `MY_PA_PROXY_PORT`, `MY_PA_TAILNET_HOST`, `MY_PA_APP_IMAGE_ID`, `MY_PA_WEB_IMAGE_ID`, `MY_PA_POSTGRES_IMAGE_ID`, `MY_PA_PROXY_IMAGE`, `MY_PA_PROXY_IMAGE_DIGEST`, `MY_PA_UID`, `MY_PA_GID`, `MY_PA_PROXY_UID`, `MY_PA_PROXY_GID`, `MYPA_CANONICAL_ORIGIN` | `compose.example.yml`; private-proxy settings omitted from the public-production schema but needed for full render. |
| Sensitive Compose interpolation | Secret: `MYPA_SESSION_SERVICE_SECRET` | `compose.example.yml` web service; overrides an `env_file` value. |
| Storage/backup/migration binding | Non-secret/sensitive integrity paths: `MY_PA_VERIFIED_BACKUP_RECEIPT`, `MY_PA_BACKUP_RECEIPT`, `MY_PA_POSTGRES_BOOTSTRAP_ADMISSION`, `MY_PA_POSTGRES_RESOURCES`, `MY_PA_PRESERVED_RUNTIME_SOURCE`, `MY_PA_CURRENT_GATE_SOURCE`, `MY_PA_CURRENT_GATE_IMAGE_MANIFEST`; constrained non-secret internal URL: `MY_PA_SCRATCH_DATABASE_URL` | `backup.sh`, `verify-backup-receipt.sh`, `migrate.sh`, PostgreSQL bootstrap/restore and preserved-runtime gates; protected `MY_PA_DB_PASSWORD` supplies scratch authentication separately. |
| Runtime/diagnostic thresholds and evidence selectors | Non-secret/sensitive integrity selectors: `MY_PA_RUNTIME_SERVICES`, `MY_PA_MIN_FREE_KIB`, `MY_PA_WORKER_MAX_AGE_SECONDS`, `MY_PA_APPLE_MAX_AGE_SECONDS`, `MY_PA_DIAGNOSTIC_BFF_URL`, `MY_PA_VERIFIED_PILOT_ORIGIN` | Runtime/lifecycle/diagnostic gates. |
| Diagnostic session input | Sensitive: `MY_PA_DIAGNOSTIC_SESSION_COOKIE_FILE` | `diagnostics.sh`; caller-owned mode-`0400`, single-link file. Cookie material must only enter the HTTP Cookie header and never be printed. |

Remote-MCP, GoodNotes, GSQS remote-evaluation, Apple, firewall, and NAS-10
synthetic-test selectors are distinct. They are not required for this
six-service public-browser remediation; do not provision or infer their
credentials from this inventory.

## PostgreSQL `my_pa` rotation dependency — hard stop

`MY_PA_DB_PASSWORD` supplies `POSTGRES_PASSWORD` for the `postgres` service.
`MY_PA_DATABASE_URL` is the corresponding client credential for
gateway/workers. On an already initialized PostgreSQL data directory, changing
only `POSTGRES_PASSWORD` in environment does not rotate the existing role
password. A mismatch leaves the database role and its clients unable to
authenticate.

Configuration generation must therefore not invent a replacement database
password. It requires a separately reviewed local, in-container role-rotation
procedure that:

1. proves exact target identity and preserves the existing database role;
2. takes and verifies a current backup receipt before mutation;
3. changes the existing `my_pa` role without exposing its new password in
   arguments, logs, a receipt, or Git;
4. atomically updates only `MY_PA_DB_PASSWORD` and the password component of
   `MY_PA_DATABASE_URL`, with a safe rollback/reconnect plan;
5. validates a reconnect by real services and a scratch restore; and
6. records only redacted result metadata and digests.

No supported rotation helper was identified in the candidate NAS playbook. Do
not substitute ad-hoc remote copy/command methods, shell redirection, an
interactive SQL prompt, a generic importer, or a repository edit for this
procedure.

## Required verification sequence and current outcome

| Command/gate | Permitted outcome after inputs exist | Current outcome for this record |
| --- | --- | --- |
| `ops/nas/validate-production-env.py --env … --schema … --compose … --deployment-manifest …` | Exit 0 / `production environment: PASS`; schema, secret-length/equality, origin/auth constraints, exact source commit/tree binding, and unpublished PostgreSQL/gateway. | Not run: required environment is reported absent. |
| `ops/nas/validate-delivery-config.py` | Exit 0 / `delivery-config: PASS`; static contract validation only, never live deployment proof. | Not run by this inventory task. |
| `ops/nas/backup.sh OWNER_ONLY_BACKUP_DIRECTORY`; `ops/nas/verify-backup-receipt.sh RECEIPT` | New unique dump plus valid recent checksum receipt; output is outside checkout(s), mode `0700`. | Not run; fresh backup absent. |
| `ops/nas/migrate.sh` | Only with separate migration authority and a current verified backup receipt; never an app-start side effect. | Prohibited in this remediation stage. |
| `ops/nas/generate-runtime-admission.py … /etc/my-pa/runtime-admission.toml` | New admission binding manifest, engine, six images, and rendered Compose digests. | Not run; exact admission absent. |
| `ops/nas/preflight.sh …`, `start.sh`, `health.sh`, `diagnostics.sh` | Only after admission and gates; health proves process/database readiness, diagnostics adds service/BFF/proxy/permission/disk/backup/Apple-admission checks. | Not run. |
| `ops/nas/nas10_acceptance_gate.py` and independent exact-head review | Protected PASS candidate only if synthetic receipts, signatures/trust, engine, manifest, admission, and pilot digest match. | Not run; evidence absent. |
| `ops/nas/lifecycle_gate.py --pilot …` | Pilot restart policy only after signed NAS-10 and separately signed pilot-activation evidence. | Not run; evidence absent. |
| `ops/nas/render-frontend-cloudflared-config.py` and public-edge start | Only after private checks and explicit production activation approval; no public PostgreSQL/gateway binding. | Not run by this inventory task. |

## Receipt limitation and explicit prohibitions

The candidate has protected-write patterns for existing gates, but no approved
writer or canonical NAS publication location for this inventory. This document
therefore proposes no NAS path, no NAS publication, and no claim of NAS
immutability. A future durable NAS receipt requires separately reviewed
implementation and authority, using the protected-write patterns in
`ops/nas/nas10_acceptance_gate.py` and `ops/nas/lifecycle_gate.py`: verified
owner parent, regular single-link artifacts, no-follow reads, exclusive
no-overwrite creation, mode/owner checks, and durability handling. Its schema
must exclude all secret and personal material named in this document.

- Do not inspect, print, list, copy, archive, or commit secret/config content.
- Do not create credentials, rotate the initialized PostgreSQL `my_pa` role,
  alter secrets, migrate, start/recreate services, change tunnel/DNS/firewall,
  or activate a public edge under this inventory task.
- Do not use `:latest`, build during start, host-publish PostgreSQL/gateway, or
  treat Compose `config_files`/`working_dir` labels as runtime authority.
- Do not treat private-origin checks as WebAuthn commissioning or physical
  iPhone/passkey validation.
- Do not overwrite admissions, evidence, manifests, receipt files, backups, or
  configuration files; collision is a refusal requiring a distinct safe target.

## Exact candidate sources

- `ops/nas/production-environment.schema.toml`
- `ops/nas/production-environment.example.env`
- `ops/nas/compose.example.yml`, `ops/nas/compose.pilot.example.yml`, and
  `ops/nas/compose.public-browser.example.yml`
- `ops/nas/runtime-contract.toml`, `ops/nas/runtime-admission.example.toml`,
  `ops/nas/deployment-manifest.example.toml`, and
  `ops/nas/image-manifest.example.toml`
- `ops/nas/backup.sh`, `ops/nas/verify-backup-receipt.sh`, `ops/nas/migrate.sh`,
  `ops/nas/generate-runtime-admission.py`, `ops/nas/lifecycle_gate.py`,
  `ops/nas/nas10_acceptance_gate.py`, and
  `ops/nas/validate-production-env.py`
- `ops/runbooks/nas-lifecycle.md`, `ops/runbooks/nas-acceptance.md`, and
  `ops/runbooks/production-frontend-deployment.md`
- `.env.example`
