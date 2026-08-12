# Runbook — the managed-document plane

Configuring the managed write plane, checking that its two halves agree, backing
it up, and restoring it. The managed plane is the only place `my-pa` writes bytes
it owns; source roots stay read-only.

All commands run from the repository root.

**Provenance.** All three procedures — `verify`, `backup`, `restore` — plus the
two refusals below were executed on 2026-08-11 at head `bf/wp-27-managed-documents`
against a **disposable** database created and dropped by the run and **temporary**
roots created and deleted with it, seeded with two synthetic documents. No command
here was run against the canonical `my_pa` database or against any real document
tree, and no path in this file names one, so the counts in the transcripts below
are illustrative shapes rather than a record of a live plane. Pointing this at
real storage is `EXT-10` and is reserved to the operator — see *What still needs
the operator* at the end.

## 1. Configuration

| Setting | Meaning |
| --- | --- |
| `MY_PA_MANAGED_DOCUMENT_ROOT` | the directory managed bytes are stored under. **No default.** |
| `MY_PA_DATABASE_URL` | the metadata database, as everywhere else. No default. |

**Unset means there is no managed plane.** A process that has not been told where
managed bytes go composes no byte store and can write no managed document. That
is the fail-closed direction: an unconfigured or mistyped deployment writes
nothing rather than writing somewhere convenient.

**The root must already exist, must be a real directory, and must not be a
symbolic link.** The store never creates its own root — choosing where a user's
documents live is an operator decision — and it refuses a link because the
location an operator configured and the location the process writes must be the
same place.

**The root may not be, contain, or sit inside a configured source root.** Source
roots are the `knowledge.sources` rows registered through
[`apps/cli/sources.py`](../../apps/cli/sources.py); the managed root is process
configuration. The two are separate channels, and the store additionally compares
them after resolving both, so a managed root spelled as a link into a source tree
is refused as well.

**There is no managed-store credential in this build**, and that is stated rather
than left as an absence: the store is a local filesystem reached with the
process's own identity, so there is nothing to hold. A remote managed store would
carry its own `MY_PA_MANAGED_DOCUMENT_*` credential setting rather than reuse any
source credential, and standing one up is an `EXT-10` operator-gated action.

## 2. Check that the rows and the bytes agree

```
MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/my_pa \
MY_PA_MANAGED_DOCUMENT_ROOT=/path/to/managed \
  .venv/bin/python apps/cli/managed_documents.py verify --principal prn_...
```

Output is one line per measure and then one line per finding:

```
versions_checked 12
missing_bytes 0
digest_mismatches 0
orphaned_objects 1
unreadable_entries 0
orphan mdver_...
```

Exit status: `0` consistent, `2` inconsistent, `1` the command could not run.

### What each finding means

| Finding | Severity | What it means |
| --- | --- | --- |
| `missing_bytes` | **data loss** | a stored row names bytes that are not there. This product's write ordering cannot produce it; something removed the object. Restore from backup. |
| `digest_mismatches` | **integrity** | the bytes are present and are not the bytes the row records. Nothing in this product reopens a stored object for writing, so something outside it wrote into the managed root. Treat the root as compromised and restore from backup. |
| `orphaned_objects` | recoverable | bytes with no row. Expected and harmless — see the failure window below. |
| `unreadable_entries` | investigate | something in the object tree is not a managed version object at all. |

## 3. The failure window, stated honestly

**The filesystem and the database are not one transaction, and this product does
not claim they are.**

A managed write does this, in this order: it mints a version identifier, checks
whether the idempotency key is already bound, writes and `fsync`s the bytes under
that identifier, inserts the metadata rows, and returns — leaving the caller's
transaction to commit.

The ordering is chosen so that the failure that survives a crash is the
recoverable one:

* **What can be left behind:** bytes on disk that no row names. This happens when
  a process dies, a transaction rolls back, or a request is refused *after* the
  bytes were written — a stale expected version is the ordinary case.
* **For how long:** indefinitely. Nothing reclaims them automatically.
* **What it costs:** disk space. The bytes are unreachable — nothing can name a
  version that does not exist — so an orphan is not a disclosure and not a
  correctness problem.
* **How it is found:** `verify` reports it as `orphaned_objects`.
* **What never happens:** a row naming absent bytes. That is the failure no
  reconciliation can repair, because there is nothing left to repair it from, and
  the ordering above never produces it.

### Reclaiming an orphan

**Not automated, and deliberately not.** Deleting bytes is irreversible,
`AGENTS.md` section 8.2 reserves irreversible destruction of canonical data to
the operator, and an orphan reported by one process is indistinguishable from
bytes whose transaction has not yet committed in another. So:

1. stop every process that writes managed documents;
2. run `verify` and record the reported `orphan` identifiers;
3. run `verify` a second time and use only the identifiers reported by **both**
   runs;
4. take a backup (section 4);
5. remove those objects by hand, from the managed root, one at a time.

## 4. Backup

```
MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/my_pa \
MY_PA_MANAGED_DOCUMENT_ROOT=/path/to/managed \
  .venv/bin/python apps/cli/managed_documents.py backup \
    --principal prn_... --destination /path/to/backup
```

```
documents 2
versions 3
bytes_copied 4096
manifest_sha256 ...
```

**The destination is a managed root, not a directory.** It must already exist,
must be a real directory, must not overlap a configured source root, and must not
be, contain, or sit inside the live managed root — so "back up in place" is
refused rather than quietly mixing a manifest into the object tree. The backup is
written through the same containment as a live write.

**It is per Principal.** `--principal` is required and a backup carries exactly
that Principal's documents. Under the single-local-Principal deployment this
build supports there is one of them; the argument is explicit rather than
inferred so that a two-Principal deployment does not silently back up half a
plane.

**What a backup contains:** every version of every document the Principal owns —
active and archived — as objects, plus one `manifest.json` holding each version's
metadata. **Titles are in the manifest**, so a backup root holds user-authored
text and is as sensitive as the managed root itself.

**What a backup does not contain, and this is the residual:** the lifecycle rows.
A restored plane is **active**; a document that was archived when the backup was
taken comes back active and has to be archived again. The submissions and
receipts are not carried either, so an idempotency key used before a restore is
free again afterwards.

## 5. Restore

```
MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/my_pa \
MY_PA_MANAGED_DOCUMENT_ROOT=/path/to/managed \
  .venv/bin/python apps/cli/managed_documents.py restore \
    --principal prn_... --source /path/to/backup
```

```
documents 2
versions 3
bytes_restored 4096
versions_already_present 0
```

**The Principal must match the one the backup was taken for.** A manifest taken
for another Principal is refused, so a mistyped argument cannot move documents
between partitions.

**It is additive and safe to re-run.** A version whose bytes are already present
is counted and not rewritten; the row insert is what fails if a version is
already stored, so restoring over a live plane that already holds the data is a
refusal rather than a duplication. Restore into an empty root and an empty plane.

**Verify afterwards.** Run section 2 and require `missing_bytes 0` and
`digest_mismatches 0` before putting the plane back into service.

## 6. What still needs the operator

* **`EXT-10`.** The real NAS read-only source roots and the real managed-write
  root. Everything above has been exercised against temporary roots only; nothing
  in this repository knows where the operator's real roots are, and pointing the
  plane at them is an operator action.
* **Reclaiming orphans**, per section 3.
* **Hard deletion of a managed document.** Out of scope by the work package and
  reserved by `AGENTS.md` section 8.2. Archive is the vocabulary; there is no
  delete command, no delete statement, and no `deleted` state in the schema.
* **Backup retention and off-host copies.** This runbook covers taking a backup,
  not where it lives afterwards.
