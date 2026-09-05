---
name: my-pa-nas-build-deploy
description: Build the exact live origin/main my-pa linux/amd64 image package and upgrade or redeploy an already bootstrapped canonical Synology NAS smoke runtime. Use for my-pa NAS builds, smoke upgrades, redeployments, rollback preparation, or post-deployment verification; do not use for first-time NAS provisioning, pilot activation/upgrades, local development starts, or remote-MCP-only operations.
---

# my-pa NAS build and deploy

Use repository truth and authenticated runtime evidence. This skill coordinates the existing `ops/nas` gates; it does not replace, weaken, or reimplement them.

## Authority

The skill grants no authority. Establish one bounded objective, acceptance criteria, target, in-scope behavior, exclusions, and stop conditions. Obtain explicit operator authorization for production deployment or activation before mutating the NAS.

Treat these as separate point-of-action gates when needed:

- use of protected configuration (read in place; never print or copy values) and
  any mutation of protected deployment configuration;
- data-plane or ingress-plane firewall mutation;
- stopping the five canonical application services for writer quiescence;
- possible interruption of the same admitted canonical PostgreSQL container,
  including impact on every dependent service, immediately before
  `ops/nas/start.sh`;
- quiescing each dependent Compose project outside the canonical runtime;
- destructive restore or canonical data replacement;
- credential creation, disclosure, rotation, or mutation; and
- material risk acceptance.

Prior approval for deployment does not imply any of those permissions. Read-only discovery and checks do not require mutation authority.

## Required topology

Follow root `AGENTS.md`, including Manager → Orchestrator → specialized workers for substantive execution. Assign non-overlapping build/artifact, NAS admission/data-safety, and validation/receipt work. A fresh independent reviewer must bind any corrective code change to its exact head before merge. Deployment itself must bind to authenticated `origin/main`, not an unmerged candidate.

## Route

Read [references/workflow.md](references/workflow.md) before any build or NAS action. Also read the current versions of:

- `ops/nas/README.md` and `ops/runbooks/nas-lifecycle.md`;
- `ops/runbooks/postgres-operations.md` when persistence or migration is involved;
- `ops/runbooks/nas-acceptance.md` when a discovered pilot state requires a
  separately scoped handoff; and
- every `ops/nas/*.sh` script that will be invoked.

The checked-in scripts are authoritative over copied commands, remembered hashes, and historical transcripts. Never carry forward a stored migration head, commit, tree, image ID, engine ID, archive digest, admission digest, network ID, bridge name, temporary path, or session token.
Some runbooks preserve chronological evidence and superseded statements. Use
their explicit current-state corrections and current executable contracts; do
not treat an older transcript or scaffold-era description as present truth.

For a build-only request, stop after workflow section 2 and report the
non-deployable candidate identities; do not connect to or mutate a NAS. The NAS
phases apply only when deployment is in scope and authorized.
PostgreSQL container recreation or resource re-admission is a provisioning
objective outside this smoke-upgrade skill; never infer that authority.

## Completion standard

Claim success only when the exact current `origin/main` commit/tree built the transferred package; the live NAS admitted the same byte identities; required backup, scratch restore, quiescence, migration, firewall, lifecycle, and health gates passed; pilot-only diagnostics were recorded as inapplicable to smoke mode; previously running compatible dependent services were restored; and a sanitized receipt records every identity and command result.

If a required gate fails or identity drifts, preserve evidence, keep or return the system to the last verified safe state, and stop. Never improvise around a fail-closed gate.
