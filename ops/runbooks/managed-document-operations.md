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

## 7. The report content store (Reports Modernization WP05 C)

A second, separate filesystem plane: report content whose decoded size is above
`MY_PA_REPORT_CONTENT_INLINE_MAX_BYTES` (default 524,288, valid 1..524,288) is
held under `MY_PA_REPORT_CONTENT_ROOT` as `managed_blob` objects, one per
`grcnt_` content row, at `<root>/content/<shard>/<grcnt_id>/{decoded,original}`.
Unset, the root composes no store: report content stays inline, and content is
refused (`invalid_request`, `content`, `max_bytes`) when its decoded size is
above the threshold or, for a `gzip+base64` upload, when its gunzipped bytes
are (a store-less server never inflates past the threshold). The root
must be an existing real directory (not a symbolic link) clear of every source
root and of the managed document root; the gateway refuses to start otherwise.
Neither variable is a secret.

The write window is the same as section 3's: an object is written before the
first row of its request, so a failure can leave an orphan object, never a row
naming absent bytes. Every standalone `reports.read` of a `managed_blob`
version verifies its parts (size and SHA-256), whether or not the body is
requested, and answers `internal_error` without a body when one is missing or
altered. A verified body is returned only up to 524,288 decoded bytes; above
that the read carries `body_omitted: "exceeds_response_bound"` with every
digest. `reports.history`, `reports.list` and `reports.search` never read the
store.

`apps/cli/report_content.py` (`verify`, `backup`, `restore`, each with
`--principal`, in the shape of `apps/cli/managed_documents.py` above) reports
that Principal's missing parts and per-part size or digest mismatches, the
store's orphans (objects no `managed_blob` row of any Principal names; an orphan
may also be an object whose transaction has not committed yet) and unreadable
entries, and copies verified objects to and from a backup root clear of the
live one. It never deletes or repairs anything. The database is backed up with `pg_dump` and
restored first; the objects are then restored and verified against the restored
rows. A `restore` stops at the first damaged object it meets, whether a damaged
copy in the backup root or a damaged object already in the live store (which it
verifies but never overwrites): run `verify` first, move each damaged object it
reports aside (out of the live store root), and move any damaged copy aside out
of the backup root before restoring again. The full dump, copy, restore and
scan cycle is exercised against
temporary roots and a disposable database by
`tests/recovery/test_report_content_recovery.py`; nothing here has been run
against a real deployment root, which remains an operator action.

### 7.1 Transfer staging garbage collection (Reports Modernization WP06)

Content larger than one request is uploaded in chunks through
`reports.transfer.begin` / `append` / `finalize` and consumed by
`reports.publish` or `reports.update`. Until a session is consumed or aborted
its chunks are **transfer staging** under the same root, in its own constant
directory `<root>/transfer/<shard>/<grxfr_id>/<sequence>-<sha256>`, beside the
`content` and `preservation` namespaces. A consume or abort discards the
session's staging after its commit, best effort. Every `begin` first moves its
Principal's (any client's) open or finalized sessions whose `expires_at` has
passed to `expired` (at most 16 per begin, oldest first) and discards their
staging after its own commit, best effort; a refused begin rolls back and
discards nothing. So a Principal's staging on disk is bounded by its live
quota (8 sessions, 64 MiB declared) plus the sessions that ended with no later
begin of that Principal. The collector is still needed for those (a Principal
that stops beginning), for a failed consume, abort or begin discard, and for a
staging directory with no session row:

```sh
MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \
  .venv/bin/python apps/cli/report_content.py transfer-gc [--limit N] [--discard-orphans]
```

**Schedule it hourly as an operator step.** Nothing in the repository
creates a scheduler, timer or cron entry; run it from the operator's own
schedule (and by hand after an incident). It is bounded (`--limit`, 1..1000,
default 100, per step) and idempotent, so an overlapping or repeated run is
harmless; a session a request holds is skipped (`FOR UPDATE SKIP LOCKED`) and
collected next time.

**What one run does.** (1) Moves up to `--limit` `open` or `finalized`
sessions whose `expires_at` has passed to `expired` (no row is deleted). (2)
Discards the staging of consumed, aborted and expired sessions (at most
`--limit`). (3) Reports staging directories that have no session row
(orphans, e.g. after a database restore) and, only with `--discard-orphans`,
discards them (at most `--limit`). Unreadable staging entries (anything that
is not a well-formed session directory or chunk file, links included) are
counted and never removed; inspect them by hand.

**What it can remove.** Only consumed, aborted, expired or orphaned transfer
staging, and only under `<root>/transfer/`: the staging port admits only
`grxfr_` session identifiers, takes no path, walks the directory anchored
without following links and unlinks only chunk-named regular files. The
`content` and `preservation` namespaces are never touched (the content store
has no delete), and the session queries it uses are operator scans across
every Principal by design (staging is one directory for all owners).

**Output and exit codes.** One JSON object of counts, no identifier, path or
byte: `expired`, `discarded`, `orphans_found`, `orphans_discarded`,
`orphans_remaining`, `unreadable`, `more_remaining`. Exit `0` when clean; `3`
when a bound left more to do (`more_remaining`), orphans remain unremoved, or
unreadable entries exist (run again, or add `--discard-orphans` after
checking the orphans are not a restore in progress); `1` on refusal (usage
error, no `MY_PA_REPORT_CONTENT_ROOT`, a staging failure).

**Backups need not include `transfer/`.** Staging is transient: `backup` and
`restore` copy only `content` objects, and a session whose staging is lost
can only be aborted and uploaded again (the client begins a new session).

## 8. Report holds and retention (Reports Modernization WP05b)

**What a hold does.** A legal hold is placed and released by the operator only:
`reports.hold.place` and `reports.hold.release` (purpose `report_hold`) are
operator-only capabilities attested to the local operator surface — the CLI
(`apps/cli/invoke.py`) or the HTTP gateway's stamped operator surface. A held
report cannot be moved to the Trash: `reports.delete` is refused `denied
[report_held]` and writes no lifecycle row, and any future purge is blocked the
same way. Nothing else is: archive, restore, update, `reports.read`,
`reports.history`, list and search all work on a held report, and `reports.read`
and `reports.history` answer `"held": true`. Placing a hold first writes a
sealed, digest-verified **preservation copy** of every version, content object
and lifecycle event to the report content store, in the `preservation`
namespace (`<root>/preservation/<shard>/<grprv_id>/...`, beside section 7's
`content` namespace), reads it back and verifies it, and only then records the
hold. The copy is kept after the hold is released; the store has no delete.
Every `reports.delete` also preflights the report's content integrity, so a
report with a missing or altered part is refused `internal_error` with no
lifecycle row, held or not.

**What retention does.** Retention is an operator policy per Principal:
`reports.retention.set` and `reports.retention.get` (purpose
`report_retention`), operator-only on the same terms. It is **unset by default**:
no period applies until the operator sets one. Every change is appended to the
policy history (who, when, old period, new period, reason); nothing is
overwritten. Retention gates only **purge eligibility**, which
`reports.retention.get` reports for one report as information: purge is not
implemented, and retention never blocks an update, archive, restore or Trash.
Eligibility is decided in this order: `no_policy`, `held`, `not_trashed`,
`retention_running`, `eligible`. **Open operator decisions:** the retention
clock start (the implemented default is the report's most recent move to the
Trash, `most_recent_trash_event`) and the period itself. The period is an
operator decision, recorded here as **unset by default**: no period is
approved, and nothing in the repository sets or assumes one. The period in the
`reports.retention.set` example below (`{"count": 30, "unit": "days"}`) is a
neutral placeholder showing the shape, not a proposed or recommended value.

**Commands.** All four run through `apps/cli/invoke.py` as the local operator,
with `MY_PA_DATABASE_URL` set and, for a placement, `MY_PA_REPORT_CONTENT_ROOT`
(section 7). `--principal-id` is the local operator Principal; `--requested-at`
is the request time in RFC 3339. Reasons are required (1..500 characters) and
are recorded, never echoed. `expected_hold_revision` is the `hold_revision` you
last read (0 for a report never held); `expected_policy_revision` is the
`policy_revision` you last read (0 before the first change). A retry with the
same `idempotency_key` and the same request replays (`"replayed": true`).

```sh
MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \
  .venv/bin/python apps/cli/invoke.py reports.hold.place \
    --request-id req-hold-0001 --purpose report_hold \
    --principal-id prn_... --requested-at 2026-11-06T12:00:00Z \
    --payload '{"report_id": "grpt_...", "expected_hold_revision": 0, "reason": "Litigation hold.", "idempotency_key": "hold-0001"}'

.venv/bin/python apps/cli/invoke.py reports.hold.release \
    --request-id req-hold-0002 --purpose report_hold \
    --principal-id prn_... --requested-at 2026-11-06T12:00:00Z \
    --payload '{"report_id": "grpt_...", "expected_hold_revision": 1, "reason": "Hold lifted.", "idempotency_key": "hold-0002"}'

.venv/bin/python apps/cli/invoke.py reports.retention.set \
    --request-id req-retention-0001 --purpose report_retention \
    --principal-id prn_... --requested-at 2026-11-06T12:00:00Z \
    --payload '{"expected_policy_revision": 0, "reason": "Policy adopted.", "idempotency_key": "retention-0001", "period": {"count": 30, "unit": "days"}}'

.venv/bin/python apps/cli/invoke.py reports.retention.set \
    --request-id req-retention-0002 --purpose report_retention \
    --principal-id prn_... --requested-at 2026-11-06T12:00:00Z \
    --payload '{"expected_policy_revision": 1, "reason": "Policy withdrawn.", "idempotency_key": "retention-0002", "unset": true}'

.venv/bin/python apps/cli/invoke.py reports.retention.get \
    --request-id req-retention-0003 --purpose report_retention \
    --principal-id prn_... --requested-at 2026-11-06T12:00:00Z \
    --payload '{"report_id": "grpt_...", "history_limit": 20}'
```

`reports.retention.set` takes exactly one of `period` (`{"count", "unit"}`:
1..36525 `days` or 1..100 `years`) and `"unset": true`. `reports.retention.get`
takes an optional `report_id` (for that report's eligibility) and an optional
`history_limit` (1..50, default 20).

**Outputs** (the `result` of the one-line JSON envelope the CLI prints):

* hold place/release: `plane` (`standalone`), `report_id`, `operation`
  (`place`/`release`), `held`, `hold_revision`, `event_id`, `recorded_at`,
  `replayed`, and on a placement `preservation` {`seal_object_id`,
  `seal_sha256`, `seal_byte_count`, `object_count`, `version_count`} — the
  sealed copy's identity and size, never its content or the reason;
* retention set: `policy_revision`, `period` (or `null` when unset),
  `previous_period`, `event_id`, `recorded_at`, `replayed`;
* retention get: `policy` {`policy_revision`, `period`, `set_at`, `reason`} or
  `null` when never set, `history` (newest first: `event_id`,
  `policy_revision`, `period`, `previous_period`, `reason`, `authority_class`,
  `decision_channel`, `recorded_at`), and with `report_id` an `eligibility`
  {`report_id`, `eligible`, `reason`, `clock_start`, `eligible_at`,
  `clock_start_strategy`}.

**Refusals** (`code [safe_details]`):

* `denied [report_held]` — `reports.delete` on a held report; nothing written.
* `unavailable [preservation_store]` — a placement in a process without
  `MY_PA_REPORT_CONTENT_ROOT`; no hold row is written.
* `conflict [expected_hold_revision]` / `conflict [expected_policy_revision]` —
  a stale revision; `conflict [hold_state]` — placing a hold on a held report
  or releasing one not held; `conflict [idempotency_key]` — a key reused for a
  different request; `not_found [artifact_id]` — no such report of yours.
* `internal_error` — the preservation copy could not be written or did not
  verify; no hold row is written.
* `denied` (no detail) — any of the four from a surface that is not the local
  operator surface (stdio MCP, an unattested local caller); nothing is read or
  written.
* Remote and compact ChatLLM facade: these custody operations are absent from
  `my_pa.describe` and every remote tool list, and naming one is `unsupported`,
  even with a forged grant. The ChatLLM capability policy classifies all four
  `CONTROL_PLANE_EXCLUDED`.

**Verifying preservation copies.**

```sh
MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \
  .venv/bin/python apps/cli/report_content.py preservation-verify [--fail-on-orphans]
```

It takes no `--principal` (the orphan direction cannot be partitioned) and
prints `holds_checked`, `missing_parts`, `mismatched_parts`, `orphaned_objects`,
`unreadable_entries`, `integrity_findings` and `orphans`, then one `missing` or
`mismatch` line per integrity finding and, in their own section headed
`orphans_informational`, one `orphan` line per orphan (identifiers only; no
path, body or digest).

* **Integrity findings** — a missing, mismatched or corrupt part of a copy a
  hold seal references, a missing or malformed seal, a seal listing another
  number of objects than its hold row records, and unreadable store entries.
  A copy is damaged.
* **Orphans** — preservation objects no hold seal references. A placement that
  failed after writing some objects leaves them behind by design: they are
  reported, never deleted, and no hold row names them. Informational.

Exit codes of `preservation-verify`:

| Exit | Meaning |
| --- | --- |
| `0` | no integrity finding (orphans may be present and are reported) |
| `1` | refused: a usage or operational error (for example, no root configured) |
| `2` | at least one integrity finding (with or without orphans, with or without `--fail-on-orphans`) |
| `3` | `--fail-on-orphans` given, no integrity finding, at least one orphan |

The other subcommands are unchanged: section 7's `verify` exits `0`
consistent, `1` refused, `2` inconsistent.

**Backups do not copy the preservation namespace.** Section 7's `backup` and
`restore` copy only `content` objects (operator decision: backups need not
honor holds). After a restore, `preservation-verify` reports any preservation
copy the restored store lacks as missing parts.

The end-to-end CLI sequence above (publish, place, delete refused, archive,
restore, update, retention get/set/get, release, delete, store-less refusal,
unstamped `denied`) is exercised against a disposable database and a temporary
root by `tests/database/test_reports_custody_cli.py`; nothing here has been run
against a real deployment root, which remains an operator action.
