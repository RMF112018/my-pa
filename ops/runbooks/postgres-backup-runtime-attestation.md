# PostgreSQL backup/runtime attestation boundary

This is a recovery-evidence contract, not a deployment, backup, restore, or
credential-rotation procedure. The canonical attestation writer may publish
only an immutable attestation for a fresh, custom-format PostgreSQL dump receipt
after it binds that dump to
the exact admitted repository, image, engine, PostgreSQL container, and running
six-service runtime. It checks the receipt's checksum and asks `pg_restore --list`
in that authenticated PostgreSQL container to read the archive before
publication. Passing it is prerequisite evidence for a separately
authorized recovery or credential operation; it never authorizes or performs
one.

The deployment manifest's `compose_hash` and PostgreSQL bootstrap admission's
`compose_sha256` must both equal the SHA-256 of the canonical
`ops/nas/compose.example.yml` source bytes. This contract does not interpret
`compose_hash` as either resolved smoke or pilot Compose digest. The deployment
app/web loaded image IDs and proxy OCI digest must match the admitted image
manifest; the runtime proxy reference must match that manifest too. A manifest
using another `compose_hash` convention is refused until it is reviewed and
corrected outside this command.

The writer re-runs the existing read-only bootstrap, PostgreSQL resource, and
runtime identity gates after listing the archive. Runtime verification checks
both admitted Compose render digests and requires exactly one running mode to
match the six service config hashes. Compose and Docker inspection may hold
credential-bearing values transiently inside the protected operator process;
the command emits only generic refusal codes and writes no such values to its
attestation. The Docker socket still confers host-level authority, so the
operator image, fixed script/arguments, and canonical tools are security
boundaries. No filesystem mount alone confines Docker actions.

The protected operator launcher accepts only
`--postgres-backup-attestation` for publication or
`--postgres-backup-attestation --verify` for readback. It selects the fixed
writer itself, requires its existing source/engine/image admission to match
the current clean checkout, refuses extra arguments, alternate NAS roots and
Tailscale authority, and drops caller Python import-path controls. The host
evidence directory must already be a root-owned mode-0700 physical directory
with no symlink or writable ancestor. The launcher mounts the admitted source,
NAS deployment and backup inputs, PostgreSQL data path, Compose environment
files at the fixed `secrets/nas.env` and `secrets/web.env` paths, and
`/etc/my-pa` read-only; only the evidence directory is mounted
read-write for publication and read-only for verification. Compose may read
the root-only environment files inside the protected process, but their values
must not appear in arguments, output, or the attestation. The launcher never
sources `production.env`. A changed checkout needs a new operator admission
before either mode can run. Docker resolves bind paths after the host preflight,
so operators must preserve root ownership and directory integrity during the
launch; the Docker socket remains a host-root capability despite the narrow
mounts.

The PostgreSQL data bind root is an exception to the root-owned input
directory rule: the official image can make that leaf postgres-owned mode 0700
after `initdb`. The launcher still requires a non-symlink mode-0700 directory
under a root-owned, non-writable parent chain. The protected PostgreSQL
resource gate then verifies that the authenticated container has the exact
read-write bind mount; the launcher does not assume a fixed postgres UID.

Publication requires the dump to be at most 900 seconds old. Later verification
checks the recorded creation and attestation times against that publication
window and rechecks the retained dump and current runtime identity. A retained
attestation can therefore verify after 900 seconds if those identities still
match; it cannot be newly published after that window.

An attestation does not restore anything. The existing scratch-only restore
flow can diagnose data recovery from the retained dump, but cannot recreate an
unknown prior PostgreSQL role-password or other role-secret state. A credential
rotation therefore still needs its own reviewed rollback/recovery design and a
future explicit operator action.

Retain the dump, checksum receipt, and immutable attestation together. Do not
overwrite any of them. A collision or interrupted partial is a refusal: retain
the evidence, diagnose the scratch target if one exists, and obtain a new,
distinct dump and attestation before retrying. No successful scratch diagnosis,
attestation, or retry activates a deployment or resumes a stopped runtime.

This document intentionally contains no credentials, tokens, connection
strings, role-password values, or commands that access a live NAS.
