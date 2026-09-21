# PostgreSQL backup/runtime attestation boundary

This is a recovery-evidence contract, not a deployment, backup, restore, or
credential-rotation procedure. The canonical attestation writer may publish
only an immutable attestation for a fresh, custom-format PostgreSQL dump receipt
after it binds that dump to
the exact admitted repository, image, engine, PostgreSQL container, and running
six-service runtime. Passing it is prerequisite evidence for a separately
authorized recovery or credential operation; it never authorizes or performs
one.

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
