# NAS-10 synthetic acceptance

NAS-10 is an inert evidence and review gate. It does not deploy, activate a
pilot, enable Tailscale, access a NAS, create credentials, or read personal
data. The checked-in acceptance, review, and trust examples are deliberately
non-pass placeholders.

`acceptance-matrix.toml` is the closed synthetic matrix. It covers architecture
and Principal boundaries; platform, image, runtime, storage, backup, and restore
contracts; gateway, workers, PWA/BFF, proxy, and private-origin behavior; Apple
grant/admit adversarial cases; GoodNotes/OCR read-only containment; Frontier MCP
stdio; and lifecycle restart, rollback, emergency, diagnostics, and
non-activation behavior. `run_synthetic_acceptance.py` requires the exact image
manifest and runtime-admission artifacts, derives Git head/tree itself, refuses
a dirty or mismatched checkout, and runs only the exact checked-in pytest
selectors. Each case receipt says `synthetic = true` and
`activation_performed = false`; bounded synthetic pytest output is preserved in
a companion log and bound by SHA-256 from its case receipt.

Cases are not accepted by names or marker substrings: every matrix entry states
its environment requirement, concrete behaviors, and exact pytest node
selectors, and the receipt must reproduce all three. Real-socket ingress runs on
loopback. Database cases require both
`MY_PA_NAS10_DISPOSABLE_DATABASE_ACK=YES` and an explicit
`MY_PA_NAS10_SYNTHETIC_DATABASE_URL` whose hostname is loopback; absence or any
non-loopback host refuses. The database fixtures create/drop isolated synthetic
databases and must never target a configured canonical database. Scratch
Docker lifecycle and NAS `pg_dump`/restore/readiness are `external_device`
cases. The local runner always refuses at those cases. A dedicated trusted
harness must use an explicitly acknowledged disposable Docker engine, exact
admitted images/runtime artifacts, actual Compose start/health/restart, sentinel
bytes in PostgreSQL and managed storage, wrong-architecture execution, then
`ops/nas/backup.sh`, `ops/nas/restore-to-scratch.sh`, and
`apps/cli/health.py`. Its protected PASS receipts are mandatory before the
acceptance gate can issue a candidate; this repository run does not claim those
device tests passed. Each external receipt must identify
`my-pa.nas10-external-device.v1`, carry the literal disposable-engine
acknowledgement, and bind the exact image-manifest, runtime-admission, and pilot
resolved-Compose digests. The independently signed evidence manifest binds
those receipts and logs. Any PostgreSQL URL found in a case log is a refusal.

The runner creates a new mode-0700 evidence directory beneath an existing
canonical owner-only parent and creates every log, receipt, and manifest with
exclusive no-follow mode-0400 descriptors. It streams the child process's
combined output directly into the log, terminates it when the 10 MiB case bound
is reached or the five-minute case timeout expires, and kills the entire new
process session with TERM then KILL so descendants cannot retain the output
pipe. It fsyncs artifacts and their directory and never accumulates unbounded
stdout/stderr in memory. Child PATH is fixed to `/usr/bin:/bin`; caller PATH is
ignored, Python is the already resolved absolute interpreter, and database URLs
are redacted from logs.

The runner's evidence is not acceptance. `nas10_acceptance_gate.py` will issue
an unsigned `my-pa.nas-10-acceptance.v1` PASS candidate only when all of these
conditions hold:

- the repository is clean at the exact evidence, image, and review head/tree;
- all closed matrix cases have byte-bound PASS receipts and none claims activation;
- the complete deployable linux/amd64 image manifest and complete runtime
  admission bind the same engine, service image roles, and pilot resolved
  Compose digest;
- an independent review binds the exact head/tree, evidence manifest, and
  matrix and has a valid detached RSA-SHA256 signature from a 3072-bit-or-stronger
  key pinned by root-owned mode-0400 `/etc/my-pa/nas10-review-trust.toml`.

Acceptance reads the canonical root-owned mode-0700
`/var/lib/my-pa/nas10-evidence` only. Every evidence, result, log, review,
signature, key, image-manifest, runtime-admission, and review-trust input must be
owner-only mode-0400, regular, single-link, and opened with `O_NOFOLLOW`. Each
file is snapshotted once from its descriptor and every parse, hash, and signature
check uses that same byte snapshot. Candidate output uses exclusive
`O_CREAT|O_EXCL|O_NOFOLLOW` creation beneath an existing canonical mode-0700
owner directory and is fsynced at file and directory level. Existing files,
dangling symlinks, unsafe parents, and traversal refuse. Test output is streamed
into the protected log and the process is terminated if its bound is exceeded;
it is never accumulated by `capture_output`.

The PASS candidate matches the artifact schema consumed by the NAS-09 pilot
gate. It still cannot activate anything: the operator must separately verify and
sign that acceptance artifact, publish it in the NAS-09 trusted evidence
directory, and later publish a distinct signed pilot-activation artifact.
Provisioning reviewer/operator trust, independent review, live platform and
engine verification, NAS-10 execution against a committed clean head, pilot
activation, deployment, credentials, Tailscale changes, backup policy, live
Apple/TCC, corpus loading, and risk acceptance remain operator gates.
