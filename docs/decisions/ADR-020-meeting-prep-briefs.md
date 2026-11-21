# ADR-020: Versioned meeting prep briefs

- **Status:** Accepted by operator directive 2026-11-20
- **Decision ID:** `MYPA-MTG-D-020`
- **Repository:** `RMF112018/my-pa`
- **Repository identity:** `main@ee44e8f57` (branch `feat/meeting-prep`)
- **Scope:** One new Meeting child record, the *prep brief*, written through the existing `meetings.create` and `meetings.update` capabilities and read through the existing `meetings.read` and `meetings.search` capabilities. This ADR is also the frozen contract for that change (sections C1-C9 below). No new capability, purpose, grant, profile switch or deployment authority.

## Context

A Meeting (WP-MTG-01..04, revision `7d9a450dfd07`) already carries one versioned Markdown body: the meeting *notes*, an immutable chain of full-body versions in `meeting_note_versions` whose head is the current note. Notes record what happened. The operator wants connected clients (ChatGPT, Abacus/ChatLLM, CLI) to commit a *prep brief* against a Meeting before it happens: agenda, background, questions, positions. A prep brief is a separate body with a separate history; overloading the notes chain would mix pre-meeting and post-meeting text and corrupt the record-lineage evidence anchors that cite exact note versions (ADR-015, S1 contract section 7.2).

## Decision

1. **A versioned history, not an overwritable column.** Prep briefs live in a new table `meeting_prep_versions` that copies the `meeting_note_versions` design: an immutable chain of full-body versions, each naming the Meeting receipt that wrote it. The current prep is the one version no other version supersedes.
2. **The existing write grant.** A prep brief is written through `meetings.create` (first version) and `meetings.update` (each later version) with one new optional payload field, `prep_markdown`. No new capability, grant, purpose or audit name. A caller that may update a Meeting may write its prep.
3. **Markdown stored inert, under a high named cap.** The body is stored exactly as sent, never rendered or trusted. The operator asked for no size limit; the accepted policy is a high bound, `MAX_MEETING_PREP_CHARACTERS = 4 * MAX_MEETING_NOTES_CHARACTERS` (400,000 code points), one named constant enforced in the domain validator, the command and MCP schema, and a database CHECK.
4. **Searchable.** `meetings.search` matches the current prep version, exactly as it matches the current note version; a superseded prep version is never matched.
5. **Readable through the existing read surface.** `meetings.read` returns the current prep head and, with one new optional parameter, any earlier prep version by number. No new capability name (section C6).
6. **Additive and reversible schema.** One Alembic revision on `640aaacc78e8` creates the table, its indexes and (following the `meeting_note_versions` precedent) an append-only trigger and its function; its downgrade refuses while any prep row exists and otherwise drops exactly what the upgrade created. No existing row, column, constraint or vocabulary changes.

## Contract

### C1. Table `meeting_prep_versions`

| Column | Type | Rule |
| --- | --- | --- |
| `prep_version_id` | text PK | identifier of new kind `IdKind.MEETING_PREP_VERSION` (prefix `mprep`) |
| `principal_id` | text not null | the Meeting's Principal |
| `meeting_id` | text not null | the Meeting |
| `version_number` | integer not null | `>= 1`; unique per Meeting |
| `supersedes_prep_version_id` | text null | null exactly when `version_number = 1`; unique (a chain, not a tree) |
| `content_markdown` | text not null | `length BETWEEN 1 AND 400000` |
| `content_sha256` | text not null | lowercase SHA-256 hex of the UTF-8 body |
| `meeting_history_id` | text not null | the `meeting_history` receipt that wrote it |
| `recorded_at` | timestamptz not null | server clock |

Constraints parallel `meeting_note_versions`: identifier-shape CHECKs; composite FKs `(meeting_id, principal_id) -> meetings`, `(supersedes_prep_version_id, meeting_id, principal_id) -> meeting_prep_versions`, `(meeting_history_id, meeting_id, principal_id) -> meeting_history`, all `ON DELETE RESTRICT`; unique `(prep_version_id, meeting_id, principal_id)`; index `(principal_id, meeting_id, version_number DESC)`; GIN index on `to_tsvector('simple', content_markdown)`. Unlike notes, no lineage evidence anchor references a prep version, so there is no digest-bearing unique target.

### C2. Writing

* `prep_markdown` (string, 1..400,000 code points, at least one non-whitespace character, storable text) is optional on `meetings.create` and `meetings.update`.
* **Replace only.** There is no `prep_mode`: a sent body is the whole new version. (Notes have `append`/`replace`; prep is a document the client rewrites, and append adds nothing a client cannot do by sending the composed body.)
* **No-op.** On update, a body byte-identical (equal SHA-256) to the current head writes no version. If nothing else in the request changes, the receipt outcome is `no_op` and the Meeting version does not move, exactly as for an unchanged note `replace`.
* **Applied.** A changed body inserts version `n + 1` superseding the head (or version 1 when there is none), in the same transaction as the Meeting version bump and the one `meeting_history` receipt the version names.
* **Clear.** There is no clear, mirroring notes: `prep` is not a `clear_fields` member, and an empty or blank body is `invalid_request` on field `prep`. A client that wants to retire a brief writes a short replacement body. (Admitting a clear would need a tombstone version; not in scope.)
* **Concurrency and idempotency.** Unchanged: `expected_version` is required on update and a stale value is `conflict`, writing nothing; the same `idempotency_key` with the same request replays the original receipt, and with a different request is `conflict`.
* **Request digest.** `prep_markdown` enters the request digest document only when sent, so every pre-existing request digest is byte-identical.
* **Record Events.** An applied write that creates a prep version names the field `prep` in `changed_fields` (a name, never the body).
* **Errors.** One new field token, `prep`, in the Meeting error family and `SafeDetail`; it names the field, never its content.

### C3. Cap

`MAX_MEETING_PREP_CHARACTERS: Final = 4 * MAX_MEETING_NOTES_CHARACTERS` in `my_pa.domain.meeting.model`. The multiple 4 was chosen as the operator-accepted "high cap": a prep brief may hold pasted background material larger than a note. The transport request bound is not raised: `MAX_REQUEST_BYTES` (762,288 bytes) admits a maximal mostly-ASCII body, but a maximal body dense in multi-byte or JSON-escaped characters can exceed it and is then refused by the transport as too large before it reaches the command, exactly as a worst-case note body already can. The effective ceiling for such text is the transport bound, not the cap. The constant is the single source for the domain validator, the command and MCP `maxLength`, the contract views and the DB CHECK literal (the migration freezes the literal 400000, as migrations freeze every bound).

### C4. Reading the current prep

`MeetingView` gains `prep: MeetingPrepView | None` (`None` when the Meeting has no prep). `MeetingPrepView` carries `prep_version_id`, `version_number`, `supersedes_prep_version_id`, `content_sha256`, `character_count`, `recorded_at`, `is_current` and `body_markdown`. Every answer that returns a `MeetingView` (read and every write result) carries the current head. `MeetingListEntry` (list and search rows) carries no prep body, consistent with section 19.4's minimized rows.

### C5. Search

`meetings.search` adds the current prep version's text to the fields its lexical query matches (title, description, location, series title, current note, and now current prep), with the same `simple` text configuration, the same principal partition, the same filters, keyset order and page bound. Superseded prep versions are never matched.

### C6. History (read surface choice)

`meetings.read` gains one optional parameter, `prep_version_number` (integer `>= 1`). When sent, the answer's additional field `prep_version` holds that exact version of this Meeting's prep (`is_current` says whether it is the head); a number with no version is `not_found` on field `prep`. When omitted, `prep_version` is `null`. Because a prep chain is contiguous (`1..n`, unique per Meeting) and the head carries `n`, a client can walk the whole history without a listing tool.

Chosen over generalizing `meetings.notes.versions` / `meetings.notes.read_version` with a `kind` selector because those two names are bound to the record-lineage S1 note evidence contract: their identifiers are typed `IdKind.MEETING_NOTE_VERSION`, `meetings.notes.read_version` has its own purpose (`meeting_note_history_read`) for citing exact note offsets, and the lineage source family `meeting_note_version` is note-only. A selector would make one identifier argument polymorphic and blur what an evidence citation can name. Chosen over new names (`meetings.prep.versions`, `meetings.prep.read_version`) because those would need new grants for every client; this ADR adds no capability.

### C7. Principal partition

Every prep row carries the Meeting's `principal_id`, enforced by the composite FKs. Reads, search and history are principal-scoped; another Principal's Meeting (and so its prep) is `not_found`, indistinguishable from an absent one. The Principal is never a request field.

### C8. Audit and history rows

A prep write is part of its `meetings.create` / `meetings.update` request: one `meeting_write_requests` arbitration row, one `meeting_history` receipt, one Meeting version bump, and (when applied) one prep version naming that receipt. No separate prep receipt exists.

### C9. Client tool lists

The published MCP input schemas of `meetings.create`, `meetings.update` and `meetings.read`, and the `MeetingView` answer shape, change. Connected clients (ChatGPT, Abacus/ChatLLM, Claude) must refresh their tool lists after deployment to see `prep_markdown` and `prep_version_number`. The capability set is unchanged.

## Consequences

* A Meeting gains a second versioned body with its own history; storage grows by full-body versions, bounded per version by the cap.
* No grant, policy, purpose or audit vocabulary changes, so no operator grant step is needed; the migration and a tool-list refresh are.
* Prep is not record-lineage evidence. Admitting it as an evidence source would be a separate ADR-015 amendment.

## Supersession

Amends the Meeting records contract (WP-MTG-01..04 and its section 19 surfaces) additively. Supersedes nothing. A later clear or append mode for prep would amend sections C2 and C1.

## Implementation status

Implemented on branch `feat/meeting-prep`; not merged, migrated or deployed.
