# Repeatable build and deployment workflow

This procedure covers an update of an already bootstrapped canonical six-service my-pa NAS smoke runtime from the live `origin/main`. First-time NAS/PostgreSQL provisioning and pilot activation or upgrade are separate objectives governed by `ops/runbooks/nas-lifecycle.md` and `ops/runbooks/nas-acceptance.md`; do not splice either into a smoke update.

## 1. Bind intent and source

Record the accepted objective, success criteria, exclusions, authorized mutations, rollback boundary, and—for a deployment—the required target identity. Authenticate the Git remote. A build-only request does not authorize NAS discovery or connection.

Fetch `origin` with pruning, then record `git rev-parse origin/main` and `git rev-parse origin/main^{tree}`. Create a new isolated detached worktree at that commit. Require:

- the remote URL and authenticated repository are `RMF112018/my-pa`;
- the detached checkout's commit and tree equal the just-fetched `origin/main` identities;
- `git status --porcelain --untracked-files=all` is empty; and
- the applicable repository policy and deployment sources were read from that checkout.

Never build from the operator's ordinary checkout, a dirty tree, local `main`, a feature branch, or a reused deployment directory. Do not merge, rebase, or edit the source used for the build.

Stop on repository, branch, commit, tree, or source-cleanliness ambiguity.

## 2. Build a byte-bound package

Use a fresh owner-only artifact directory outside every repository. Resolve the proxy image as an exact digest from the currently accepted canonical deployment evidence or an explicit operator-reviewed source; never use a floating tag.

Run `ops/nas/build-candidates.sh` from the clean detached checkout. It must build app, web, and operator archives with BuildKit for `linux/amd64`, acquire the pinned PostgreSQL child, acquire the exact proxy child, and produce metadata plus `image-manifest.candidate.toml` and the separate operator candidate.

Create a Git bundle from the detached checkout that exposes `HEAD` at exactly
the build commit, verify it with `git bundle verify`, and require its advertised
head to equal that commit. This is the offline source transport; do not copy an
ordinary working directory or its repository-local Git metadata.

Require the candidate manifest to bind the detached commit/tree, clean source, `linux/amd64`, and every archive/metadata digest. Independently compute SHA-256 for every transferred member, including the source bundle, candidate manifest, and supporting index/candidate files, into a package inventory. Record file sizes and reject links, missing members, duplicates, or files that change during hashing.

For a build-only request, report the non-deployable candidate commit/tree,
platform, manifest, member hashes/sizes, and validation results, then stop here.
Do not authenticate a NAS, transfer artifacts, load images, or create an
admission.

## 3. Authenticate the target and admit the NAS candidate

For an authorized deployment, authenticate the NAS connection independently.
Do not infer a host, Compose file, mode, filesystem root, Docker executable, or
protected configuration path from a prior session. Prove the expected
device/host, Synology platform, `linux/amd64` Docker engine, canonical project
`my-pa-nas-contract`, canonical Compose file, lifecycle mode, and storage root
from authenticated runtime state and protected operator configuration.
Inventory the current six-service state, image/config IDs, running/stopped
state, database revision, Docker engine ID/name, runtime admission, image
manifest, firewall checks, and other Compose projects that use the canonical
database or its networks. Redact values that carry credentials or personal
data.

Require the selected and admitted lifecycle mode to be `smoke`. If the target
is in `pilot` mode or the request would activate pilot, stop and route a
separately authorized pilot objective through fresh exact-head NAS-10 evidence,
independent signed review, operator-published PASS, and a distinct signed
activation artifact. Do not reuse prior pilot evidence or silently change the
mode.

Require the canonical PostgreSQL container and data-plane network to already be
bootstrapped. If either is absent, stop this workflow and route a separately
authorized provisioning objective through
`generate-postgres-bootstrap-admission.py`,
`postgres-bootstrap-prepare.sh`, and `postgres-bootstrap-start.sh` in the
current lifecycle runbook before beginning a later update. Do not generate an
ordinary runtime admission or attempt a data-plane check against an
unbootstrapped target. Stop on target, engine, project, storage, Compose, or
mode ambiguity.

Re-fetch `origin` immediately before transfer. If `origin/main` no longer equals the build commit/tree, stop, discard the candidate as superseded, and rebuild from a new clean detached worktree. "Live origin/main" means current at this boundary, not current when the session began.

Transfer into a fresh owner-only NAS staging directory. Read every member back on the NAS and verify its SHA-256 and size against the local inventory before any image load. Do not transfer repository dirt, protected configuration, credentials, session tokens, database dumps, or personal data with the package.

Verify the source bundle on the NAS, then clone it without checkout into a new
exclusive owner-only source directory and detach at the exact build commit.
Require `HEAD`, `HEAD^{tree}`, and an empty porcelain status to equal the
candidate identities. The source directory must not pre-exist, and no link or
path may resolve into the prior checkout. Preserve the prior checkout and its
exact path as part of the rollback set; do not fetch into it, overwrite it, or
reuse it for the new gates. From this point onward, invoke every `ops/nas`
script by its absolute path inside the new verified checkout and use that
checkout as the working directory. Stop before any operator/image/admission
mutation if the bundle, clone, commit, tree, cleanliness, ownership, or path
identity differs. The only exceptions are verification, quiescence, and the
pre-migration backup and receipt verification for the still-running old
runtime: perform those old-identity and data-safety gates from the preserved
clean old checkout bound to the old manifest and admissions. Every
candidate/new-runtime gate must run from the new checkout.

Re-fetch `origin` again after remote readback and immediately before the first NAS image/admission mutation. Any commit or tree change invalidates the staged package for a live-main deployment; stop and rebuild rather than loading stale images.

Preserve the previous package, source checkout, deployable manifest, runtime admission, resolved Compose identity, and service-state inventory as the non-destructive rollback candidate. Do not overwrite evidence, source, or admission files; use new exclusive paths.

When the NAS uses the containerized Python operator, first run the new
checkout's `ops/nas/bootstrap-operator-runtime.sh` against the transferred
operator candidate/archive/metadata and issue a new exclusive operator
admission bound to this source and engine. Never run current gates through an
operator admission bound to an older source. When the NAS uses host Python,
prove it meets the current runbook contract instead.

With that canonical NAS Docker/Python operator identity, run `ops/nas/load-candidates.sh` against the verified candidate. This is the live engine mutation boundary: it validates archives before loading, admits exact image/config IDs, and emits a new deployable manifest. Validate the emitted manifest with the live image gate and record its digest plus the live engine identity.

Use protected configuration only after explicit authorization. Read it in place through the repository wrappers, without logging values, placing them on command lines, or copying them to evidence. Any later content change requires explicit protected-configuration mutation authority. Missing, linked, over-permissive, placeholder, or identity-inconsistent protected inputs are blockers.

Keep the old canonical image references, image manifest, runtime admission, and
PostgreSQL bootstrap admission active while the old containers run. In an
isolated prospective environment that supplies the new manifest's exact image
references plus the authorized existing non-image configuration, generate a
new runtime admission and a new PostgreSQL bootstrap admission at exclusive,
noncanonical staging paths. Require both generators to pass, parse the staged
artifacts, and record their hashes and metadata; the generators validate their
inputs and renders. The runtime consumer hardcodes its canonical admission
path. Although the PostgreSQL identity gate exposes a staged-admission
override, this workflow deliberately leaves both staged admissions outside the
consumer path until their coordinated canonical switch, while the old runtime
is still active. All admission and Compose digests must bind the same source
commit/tree, images, engine, and smoke mode. Do not claim consumer validation
until the canonical switch in section 6.

Before stopping anything, return to the preserved old lifecycle environment:
bind the old manifest to the still-canonical old admissions, run its current
image/lifecycle and running-identity gates, and prove the rollback inputs remain
readable and byte-identical. Do not point a running old container at the staged
new admission.

## 4. Firewall admission

Run the data-plane firewall in read-only `plan` and `check` modes first. Run
ingress `plan` and `check` at this phase only when the exact Compose-owned
ingress network already exists. On a fresh deployment the ingress script must
refuse before that network exists; defer its plan/check/admission to the
documented stopped-topology preparation in section 7. A passing check needs no
mutation.

If mutation is required, obtain explicit firewall authorization immediately before `apply`, use only the exact confirmation value demanded by the script, unset it immediately afterward, and rerun `check`.

The data-plane contract is exact:

- built-in `FORWARD` has one jump to DSM `FORWARD_FIREWALL`;
- `MY_PA_DATA_PLANE` is rule 1 inside `FORWARD_FIREWALL`;
- its four rules allow only exact same-bridge/subnet traffic, drop every other packet touching that bridge, then return unrelated traffic; and
- `DEFAULT_FORWARD`, a direct `FORWARD` attachment, a source-only data-plane return, foreign rules, duplicates, and misordering refuse.

The ingress-plane contract is exact:

- the data-plane gate remains effective as rule 1; and
- the single exact same-bridge/subnet ingress return is rule 2 inside `FORWARD_FIREWALL`.

Bridge, subnet, network, project, and order are derived live. Never hardcode them, bypass a refusal with raw `iptables`, disable DSM firewall, or equate one plane's passing check with another's. DSM reload or reboot requires data-plane reapply/check first and ingress-plane reapply/check second, with fresh authorization for mutations.

## 5. Writer quiescence and pre-migration backup

Quiesce all database writers, not merely the canonical six-service stack. Capture current state first. Discover sessions from `pg_stat_activity` using metadata only, then map clients and Docker network/container identities to exact Compose project/service labels. Include separately managed overlays or projects (for example remote MCP or GSQS evaluation) whenever live evidence shows they connect to canonical PostgreSQL.

Do not use `ops/nas/stop.sh` for this gate: it stops PostgreSQL with the five
application services. In the preserved old protected lifecycle environment,
from the preserved clean old checkout whose HEAD/tree match the old manifest,
and with the canonical old admissions still selected, source that checkout's
`ops/nas/lifecycle-common.sh`, run `verify_running_identity`, and
use its `nas_compose` wrapper to stop only `proxy`, `web`, `gateway`,
`worker-enrollment`, and `worker-capture` with the canonical 60-second timeout.
Verify those exact five are stopped, the same PostgreSQL container remains
running and healthy, and running identity still matches the admitted project.
Re-read the current Compose service set and helper before execution rather than
carrying this command from memory.

Obtain separate authorization before stopping dependent Compose projects not already covered by the deployment objective. Stop only the exact identified services, preserve their prior running/stopped state, and use their own canonical Compose definitions. Do not use `down`, `down --volumes`, delete containers/data, or alter credentials.

Require zero non-operator sessions capable of writing and recheck after a bounded quiet interval. If sessions return, identify and stop the owning authorized service; do not terminate unknown sessions or continue under contention. Keep PostgreSQL itself running for backup and migration.

Only after the zero-writer quiet gate passes, use an existing owner-only backup
directory outside the repository. With the old manifest, PostgreSQL bootstrap
admission, resource admission, and protected environment still selected, run
the preserved old checkout's `ops/nas/backup.sh`, then that checkout's
`ops/nas/verify-backup-receipt.sh`. Bind the verified receipt to its dump
digest and the pre-migration database revision immediately before migration.
If any writer resumes after the backup starts, quiesce again and create a new
verified backup; do not migrate from the stale receipt.

The pre-migration backup must be byte-verified and readable. Do not require it to restore at the new repository head when the canonical database is legitimately behind that head: `restore-to-scratch.sh` correctly rejects such a restore. The required head-compatible scratch rehearsal is performed from the post-migration backup in the next phase. If canonical data is already at the repository head, a pre-migration scratch rehearsal is also valid.

## 6. Explicit migration

After the verified backup and a final zero-writer check, return to the new
checkout and reverify its exact HEAD/tree, empty status, ownership, source
bundle identity, staged manifests, and staged admissions. Before changing any
canonical file or migrating, open an isolated read-only shell with
`MY_PA_NAS_COMPOSE_FILE` bound to the staged new Compose file, source only the
new checkout's `ops/nas/tooling-common.sh`, and obtain the prospective hash with
`nas_docker compose --file "$MY_PA_NAS_COMPOSE_FILE" --profile nas-01-contract-only config --hash postgres`.
Do not source a lifecycle or PostgreSQL common script for this pre-switch
render because those scripts execute canonical-admission gates. Require
exactly one non-empty output line, parse it as `postgres HASH`, and reject a
missing, duplicate, malformed, or differently named service result. Compare
only the parsed `HASH` value with the live PostgreSQL
container's `com.docker.compose.config-hash` label, require the live container
ID to equal the existing resource artifact's admitted ID, and run the new
checkout's `postgres_gate.py` against that artifact with `--live` and
`--container-id` bound to the exact live ID. Also require the prospective and
admitted project, service, image, mounts, and data-directory identities to
match. Any mismatch is a mandatory stop before canonical switch or migration:
leave the old configuration and runtime selected and hand off to a separate
provisioning/resource-readmission objective.

Only after that complete compatibility gate passes, cross the
admission boundary under the explicit protected-configuration mutation authorization.
Preserve byte hashes, ownership, and modes for the rollback files. Update only
the canonical source/Compose path to the new verified checkout and the
image-reference fields to the new admitted IDs, then publish each
already-validated staged PostgreSQL bootstrap admission and runtime admission
by atomic same-filesystem replacement at its exact canonical regular-file path
with required root ownership and mode `0400`. Do not use symlinks or expose
unrelated protected values. Verify the canonical files byte-match the staged artifacts and rerun
the new manifest's non-running image, bootstrap, lifecycle, and Compose gates.
Any partial switch must remain fail-closed; restore the complete old
configuration/admission set before migration or stop for operator recovery.

Export the just-verified pre-migration backup receipt and run `ops/nas/migrate.sh` explicitly from the newly admitted source checkout and new manifest/bootstrap admission. Migration must never be an application startup side effect.

The script must derive exactly one current Alembic head, upgrade canonical `my_pa`, prove the stored revision equals that head, and pass application database health. Never run a downgrade against canonical `my_pa`. Do not use an unset or caller-invented database URL, and do not interpret a historical runbook revision as current truth.

After migration, create and verify a second backup and restore it through `ops/nas/restore-to-scratch.sh` into a new script-valid `my_pa_scratch_...` database. Require archive readability, successful restore, repository-head revision, required extensions, and application health. Retain a failed scratch database for diagnosis. Removing a scratch database is destructive and requires exact target review; never target `my_pa`. Record the pre/post database revisions and both receipt digests. A failed migration, revision mismatch, health failure, or restore rehearsal is a stop condition.

Schema rollback is forward-only by default. Reverting images does not authorize a database downgrade. If the previous application is incompatible with the migrated schema, leave writers stopped and request an operator decision. Replacing canonical data from a dump is a separately authorized destructive restore and risk-acceptance action.

## 7. Start without building or pulling

Run `ops/nas/preflight.sh` with the new deployable manifest and exact verified archive directory. Immediately before starting, repeat the complete prospective/live PostgreSQL config-hash, admitted-container, resource-gate, image, mount, data-directory, project, and service comparison from section 6, including the same side-effect-free `tooling-common.sh` plus exact `nas_docker compose ... config --hash postgres` invocation. Any mismatch is a mandatory stop; do not rely on its earlier result. A complete match does not eliminate interruption risk because `start.sh` invokes all-service cleanup after several failure modes.

Immediately before `ops/nas/start.sh`, obtain a separate point-of-action authorization for possible interruption of that same admitted canonical PostgreSQL container and the resulting impact on every dependent service. Present the matching identities, verified post-migration backup/restore receipt, stopped dependent-service state, and recovery plan. This authorization does not permit container recreation or resource re-admission. If authorization is withheld, stop before start. Then use `ops/nas/start.sh`; the canonical start path is `create --no-build --pull never` followed by `up --detach --no-build --pull never`. Do not invoke a generic Compose build, pull, or unbounded `up` on the NAS.

If a first start is intentionally preparing a previously absent ingress network, accept only the exact documented ingress-firewall refusal and verified zero-running-service cleanup. That refusal can stop PostgreSQL and therefore consumes the PostgreSQL interruption authorization above. Then run the ingress script's read-only `plan` and `check`; if mutation is required, obtain its separate point-of-action authorization, apply only with the exact confirmation value, unset it immediately, and require `check` to pass before retrying `start.sh`. Every other failure is a blocker.

After every apparently successful `start.sh` and before health completion or any writer restoration, re-read the live PostgreSQL container ID and require it to equal the pre-start admitted ID. Run the verified new checkout's `postgres_gate.py` against the existing resource artifact with `--live --container-id` set to that exact live ID. Any ID or resource-gate mismatch means unexpected recreation: stop only the five application services, keep every writer stopped, preserve the data directory and evidence, and hand off to the separate provisioning/resource-readmission objective without operating on the replacement container.

Then require all six canonical services running with exact project/service/image labels, `ops/nas/health.sh` passing, and PostgreSQL at the repository-derived migration head. Health is readiness, not full operational acceptance.

Do not run `ops/nas/diagnostics.sh` in this smoke-only workflow: the script
requires admitted pilot identity and authorized protected diagnostic inputs.
Record the diagnostic gate as inapplicable because the verified mode is
`smoke`, and do not relabel readiness health as pilot operational acceptance.
If the operator separately scopes a pilot objective, that workflow must run the
diagnostic coverage for runtime permissions, disk floor, recent backup, worker
heartbeats, web/proxy paths, authenticated BFF/system routing, proxy
classification, and Apple admission freshness without exposing the session
credential.

## 8. Restore dependent state and close out

Restore each previously running dependent service only after the canonical runtime and database are verified, using the exact project/service identity and prior mode captured before quiescence. Recheck active sessions, canonical health, and relevant project-specific health after each restoration. Leave previously stopped services stopped. Do not start a deferred or unapproved plane merely because its Compose project exists.

If post-start validation fails while PostgreSQL remains healthy, use the verified new checkout's `lifecycle-common.sh` wrapper to stop only the five canonical application services by exact service name; do not use `ops/nas/stop.sh`, because it stops PostgreSQL too. If `start.sh` cleanup already stopped all six services, do not call `stop.sh` again. Within the separately authorized PostgreSQL recovery boundary, start only `postgres` through that same verified wrapper only when the stopped container still has the exact admitted container, config-hash, image, mounts, data-directory, project, service, and backup identities. Validate its existing resource admission and PostgreSQL readiness before any writer can restart.

If the PostgreSQL container identity changed unexpectedly, leave it and every writer stopped, preserve the data directory and evidence, and hand off to a separately scoped provisioning/resource-readmission objective. Do not generate or publish a replacement resource artifact in this workflow. Any other incompatibility or uncertain recovery identity is likewise a stop and escalation condition.

Before migration, rollback may restore the prior image manifest/runtime admission and exact prior service states. After migration, use only a compatibility-proven prior runtime; never downgrade or destructively restore canonical data without explicit authorization. If safe compatibility cannot be proved, preserve PostgreSQL and evidence, keep writers stopped, and escalate.

Write a sanitized, immutable deployment receipt outside the repository. It must include:

- repository remote identity, final fetched `origin/main` commit/tree, clean detached worktree identity, and build time;
- package inventory SHA-256/size, source-bundle identity, candidate/deployable manifest digests, archive/config/OCI identities, platform, and Docker engine identity;
- target host/device identity, verified new and preserved prior checkout paths and commit/tree/cleanliness, canonical Compose/project/mode/root, resolved Compose and runtime-admission digests;
- pre/post database revisions, verified backup and scratch-restore receipt identities;
- prospective/live PostgreSQL Compose config hashes and whether PostgreSQL was
  interrupted, recreated, or recovered;
- firewall plan/check/apply outcomes without rule-set secrets;
- exact prior/final canonical and dependent-service states;
- preflight, migration, start, health, diagnostics, and rollback-check results with timestamps and exit status; and
- deviations, gates not run, residual risks, and intentionally unperformed work.

Exclude environment values, URLs containing credentials, cookies/tokens, personal data, database contents, and unbounded logs. Re-fetch `origin/main` once more for reporting. If it advanced after the mutation boundary, report the deployed commit/tree accurately as the last pre-transfer live main; do not silently claim the newer commit was deployed.

Deployment is complete only when every applicable gate passes and prior compatible dependent state is restored. Otherwise report the exact safe state and blocker.
