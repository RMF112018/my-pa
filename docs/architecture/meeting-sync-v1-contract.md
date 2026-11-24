# `meeting_sync_v1` — ChatLLM meeting-sync publication contract

**Status:** producer contract under [ADR-022](../decisions/ADR-022-communications-intelligence.md) (Accepted under operator delegation 2026-11-22, Manager ruling R-OP-1) and [spec section 12](communications-intelligence-contract.md), **schema version 1.1.0**. WP2 (the parser and the resolution service) is merged to `main` (#373); the shared ingestion lifecycle (WP3a) is merged (#376). **WP3b**, on branch `feat/comms-meeting-sync` (not merged), adds the 1.1.0 `coverage` (section 1.1), parser v2, and the `meeting_sync_v1` lifecycle consumer, which **stages** each ingested publication (`meeting_sync_publications`, `meeting_sync_events`) and applies nothing to Meetings; applying staged publications waits for the reconciliation pass (WP3b rulings D1, D4). **The ChatLLM collector change that would produce them** is applied once by the operator from the [collector implementation notes](#8-collector-implementation-notes) (Manager ruling R-OP-8) and has not been made yet. Nothing is admitted, scheduled, granted or deployed.

**Code:** the parser `my_pa.infrastructure.meeting_sync.parser` (`parse_publication`, `PARSER_VERSION` = `meeting_sync_v1_parser_v2`, which accepts 1.0.x and 1.1.x; every 1.0.x publication has the outcome parser v1 gave it); the staging consumer `my_pa.application.meeting_sync_ingest.MeetingSyncHandler`; the vocabularies in `my_pa.domain.meeting_sync.model` and `my_pa.domain.meeting_sync.diagnostics`; the resolution rules in `my_pa.domain.meeting_sync.resolution`. Synthetic fixtures are under `tests/fixtures/meeting_sync/`. Where this document and the code disagree, the code is the contract and this document is the defect.

This document is for the producer (the ChatLLM collector) and for reviewers. It is the calendar counterpart of the `communications_evidence_v2` contract in [spec section 2](communications-intelligence-contract.md).

## 1. Publication envelope

One publication is one UTF-8 JSON object, at most 16 MiB (`MAX_PUBLICATION_BYTES`). Duplicate object keys, `NaN` and `Infinity` are refused.

| Key | Required | Type | Rule |
| --- | --- | --- | --- |
| `schema` | yes | string | exactly `meeting_sync_v1` |
| `schema_version` | yes | string | `MAJOR.MINOR.PATCH`; major `1` only; `1.0.x` and `1.1.x` are known; a newer minor (`1.2` on) is accepted with diagnostic `schema_minor_newer` |
| `events` | yes | array | the event records (section 2); may be empty |
| `generated_at_utc` | yes | string | an aware ISO-8601 timestamp (section 3): the publication's ordering stamp (section 5) |
| `cycle_run_id` | no | string | non-empty; producer run reference, informational |
| `coverage` | no (1.1.0) | object | the publication's completeness claim (section 1.1); read from minor `1` on |

Any other top-level key is counted (`unknown_top_level_keys`) and ignored, never fatal. In a `1.0.x` publication `coverage` is such an unknown key: it is ignored and counted, exactly as parser v1 treated it, and claims nothing.

### 1.1 `coverage` (1.1.0)

`coverage` is `{start_utc, end_utc, calendar_refs}`. It states that the publication is **complete** for each listed calendar over the inclusive window `[start_utc, end_utc]`: every event of that calendar whose **current** start lies in the window, cancelled ones included, is in `events` (a quarantined record still counts as present). It is the only basis on which my-pa may conclude that a bound event has gone (`not_seen`, Manager ruling D7): a publication without `coverage` claims nothing, and `not_seen` is never written from it. `not_seen` is a binding state only; it never changes the Meeting. Whether a bound event falls inside the window is judged by its bound Meeting's **current** start, so an event the provider moved out of the window, and therefore did not send, may be marked `not_seen`: state only, and restored the next time a publication carries it. Any quarantined record in the publication suppresses the whole `not_seen` pass (`not_seen_suppressed_quarantine`).

| Key | Type | Rule |
| --- | --- | --- |
| `start_utc`, `end_utc` | timestamp | section 3, **written in UTC** (`Z` or `+00:00`); `start_utc` not after `end_utc` (a single instant is allowed) |
| `calendar_refs` | array of strings | 1–100 distinct `calendar_ref` values (each 1–320 characters, not blank): the calendars the claim covers |

The object is **all-or-none**: all three keys, no other key. A malformed `coverage` rejects the whole publication with `invalid_coverage` (section 4), never a partial claim and never a silently dropped one. A calendar the collector could not read completely must not be listed. Listing a calendar no event names is allowed (it then claims that calendar had no event in the window).

## 2. Event record

One record per calendar event: a single meeting, or one occurrence of a recurring series. A recurring **master with no instances is not sent** and would create nothing (Manager ruling D7); a series exists in my-pa once its first occurrence arrives.

| Field | Required | Type | Rule |
| --- | --- | --- | --- |
| `calendar_ref` | yes | string | neutral calendar reference (like `mailbox_ref`), 1–320 characters, not blank |
| `ical_uid` | yes | string | the iCalendar UID, 1–1024 characters, not blank |
| `series_ical_uid` | no | string or null | the recurrence master's UID; present exactly when `occurrence_original_start_utc` is |
| `occurrence_original_start_utc` | no | timestamp or null | the occurrence's **original** start, never its current start, so a moved occurrence keeps its identity |
| `start_utc`, `end_utc` | yes | timestamp | the current schedule; `end_utc` not before `start_utc` |
| `timezone_name` | yes | string | an IANA zone name (1–64 characters) known to the installed zone database |
| `status` | yes | string | `confirmed`, `tentative` or `cancelled` |
| `all_day` | yes | boolean | must be `false`: all-day events are not supported in v1 |
| `title` | yes | string | 1–200 characters, at least one non-whitespace character |
| `location_text` | no | string or null | at most 500 characters |
| `virtual_meeting_url` | no | string or null | an `https` URL with a host, 1–2048 characters, no whitespace, control characters or credentials |
| `provider_event_id` | no | string or null | 1–1024 characters; a mutable attribute, never identity |
| `provider_event_id_format` | no | string or null | `immutable_verified`, `mutable` or `unknown` (default `unknown`) |
| `attendees` | no | array of objects | at most 100; each `{email, display_name?, is_organizer?, response_status?}`; `email` required; no two attendees with one normalized address; at most one organizer |

`response_status` is one of `unknown` (default), `needs_action`, `accepted`, `declined`, `tentative`. Attendees are parsed and validated only: **WP2 never applies them to a Meeting** (Manager ruling D2), but a record whose attendee set is invalid is quarantined, so a producer must send a valid set now.

**Identity.** An event's key is `(calendar_ref, ical_uid, occurrence_original_start_utc)`: a single meeting has a null original start, an occurrence has one. One `(calendar_ref, ical_uid)` is either a single meeting or a set of occurrences, never both (Manager ruling D9). Provider event ids, titles and times are never identity.

**No bodies.** A record carries no body, preview, description or notes. If a record carries `body`, `body_preview`, `description` or `notes`, the value is never read: the parser drops it and reports `content_field_ignored`. Any other unknown record key is counted (`unknown_record_keys`) and ignored.

## 3. Normalization rules

- **Time.** Every timestamp is `YYYY-MM-DDTHH:MM:SS`, optional fraction of 1–6 digits, then `Z` or `±HH:MM`; a naive timestamp is refused. The parser converts it to UTC; the producer should emit UTC (`Z`) throughout. A timestamp within one day of either end of the representable range is refused.
- **Time zone.** `timezone_name` is an IANA name (`America/New_York`), never a Windows zone name, an abbreviation or an offset (`timezone_not_iana`).
- **Addresses.** Attendee addresses are normalized by the Meeting attendee rule (the Relationship Intelligence EMAIL rule, local part and domain `casefold`ed). The producer may send any case; two addresses that normalize alike are duplicates.
- **Links.** `virtual_meeting_url` is stored exactly as sent and must be `https`; anything else is quarantined, never rewritten.
- **Nothing is truncated or coerced** (Manager ruling D3): a value the Meeting plane cannot hold exactly quarantines the record under the reason code that names it.

## 4. Rejection and quarantine codes

**Publication rejection** (the whole publication is refused with one code; the first failure decides). The checks run in this order: size (`file_too_large`); strict UTF-8 (`invalid_encoding`); JSON (`duplicate_json_key`, `malformed_json`, which carries line, column and offset only); an object (`not_an_object`); `schema` present (`missing_required_key`) and equal to `meeting_sync_v1` (`unknown_schema`); `schema_version` present (`missing_required_key`), well formed (`invalid_schema_version`) and major `1` (`unsupported_major_version`); `events` present (`missing_required_key`) and an array (`invalid_top_level_field`); `generated_at_utc` present (`missing_required_key`) and a valid timestamp (`invalid_top_level_field`); `cycle_run_id`, when present, a non-empty string (`invalid_top_level_field`); from minor `1`, `coverage`, when present, well formed (`invalid_coverage`).

**Coverage defects.** An `invalid_coverage` rejection carries one closed `defect` in its diagnostic detail (`CoverageDefect`), checked in this order: `not_an_object` (including `null`), `incomplete` (a key missing), `unknown_key`, `invalid_timestamp`, `not_utc`, `end_before_start`, `calendar_refs_not_a_list`, `calendar_refs_empty`, `calendar_refs_too_many` (over 100), `calendar_ref_unrepresentable` (not a string, blank, or over 320 characters), `duplicate_calendar_ref`. No diagnostic carries a calendar reference.

**Record quarantine** (one record is refused; the rest of the publication is accepted; every reason quarantines, there is no degraded-but-usable event):

| Group | Codes |
| --- | --- |
| structural | `record_not_an_object`, `missing_required_field`, `invalid_field_type`, `invalid_field_value`, `unparseable_timestamp` |
| representability | `identifier_unrepresentable`, `title_unrepresentable`, `timezone_not_iana`, `url_unrepresentable`, `location_unrepresentable`, `attendees_unrepresentable`, `all_day_unsupported`, `series_key_incomplete`, `end_before_start` |
| within one publication | `duplicate_occurrence_key` (two records with one key: both are quarantined) |

**Diagnostics** (informational, change no outcome): `schema_minor_newer` (a minor newer than `1.1`), `unknown_top_level_keys`, `unknown_record_keys`, `content_field_ignored`. A publication keeps at most 200 diagnostics and counts the rest. No diagnostic carries a title, location, link, address, name, calendar reference, UID or provider event id.

**Resolution skips** (my-pa side, after parsing; the record is valid but nothing is written): `cancelled_unknown_skipped` (a cancelled event my-pa never bound), `binding_kind_conflict` (the UID is bound as the other kind), `stale_record_skipped` and `ordering_conflict_skipped` (section 5). Each is returned in that record's `MeetingSyncOutcome` (kind `skipped`, the code in `diagnostic`), not in the parser's diagnostics.

## 5. Ordering

**The producer must emit a strictly increasing `generated_at_utc`** across publications for one calendar. my-pa applies a record of a known key only in publication order (resolution rule 7, WP2-F1): each binding stores the stamp of the last record applied to it (`last_applied_generated_at_utc`, also stored for a record that changed nothing).

- a record whose stamp is strictly older than the binding's is skipped (`stale_record_skipped`);
- a record whose stamp equals the binding's but comes from a different publication (different file SHA-256) is ambiguous and skipped (`ordering_conflict_skipped`);
- a replay of the same publication is idempotent; a newer stamp, or a binding with no stamp yet (just made by `meetings.provider.bind`), applies.

**Known risk.** A producer clock regression makes every record of a known key skip until a publication with a newer stamp than the last applied one arrives. Nothing fails loudly: each skip is returned only as a `skipped` `MeetingSyncOutcome` carrying its resolution code (`diagnostic`), which the caller must surface; the parser's diagnostics do not list resolution skips.

## 6. What my-pa does with an event (summary)

**Staging first (WP3b, Manager ruling D1).** The ingestion lifecycle hands each new, accepted publication to the `meeting_sync_v1` consumer, which stages it in the snapshot's transaction: one `meeting_sync_publications` row (stamp, record, accepted and quarantined counts, the coverage when declared) and one `meeting_sync_events` row per accepted record (its key and the provider-owned fields; no attendee, body or description). A quarantined record leaves no row: its evidence is the counts (ruling D14; run counts `records_total`, `records_staged`, `records_quarantined`, `records_quarantined_<reason>`, with `records_total = records_staged + records_quarantined`). Snapshots of one run are staged oldest `generated_at_utc` first. A declared coverage is also recorded as the snapshot's lifecycle coverage window, state `complete`, with no lane objects. The rules below are applied to staged publications later, by the applier (`MeetingSyncApplier.apply_pending`, WP3b-S3; the cycles-plane `comms_ingest` step after each poll, and the operator CLI's `run-once` and `backfill`, under `COMMS_INGEST_LOCK_KEY`), and only once the reconciliation latch exists (spec section 12.7, ruling D4); until then it counts `unapplied_awaiting_reconciliation` and writes nothing.

**Apply order (ruling D8).** Per source, unapplied publications in `(generated_at_utc, file_sha256)` order, each in its own transaction: a stamp older than the newest *applied* publication of the source is `skipped_stale`, an equal stamp is `skipped_ordering_conflict`, and either writes only the publication's apply columns. Events of an applied publication in key order `(calendar_ref, ical_uid, occurrence_original_start_utc` nulls first`, record ordinal)`. Every binding writer (the sync apply, `not_seen`, `meetings.provider.bind`, the reconcile) first takes the Principal's binding-writer advisory lock. No audit row is written (ruling D9): the evidence is the Meeting history, the Record Events, the publication's `apply_outcome`/`apply_counts` and the run counts.

Spec section 12.2 rules 1–7: a known key updates only the provider-owned fields of its Meeting (`start_at`, `end_at`, `timezone_name`, `status`, `title`, `location_text`, `virtual_meeting_url`); an unknown occurrence of a known series creates a Meeting in that series; an unknown series is created with its first occurrence, titled by the event; an unknown single event creates a standalone Meeting; a cancelled known event cancels its Meeting and never deletes it. An existing hand-made Meeting is never matched by title or time: it is bound only through `meetings.provider.bind`. Sync writes as actor `system`.

**Unbind tombstone (ruling D5).** A `meetings.provider.bind` unbind records a tombstone for the unbound key in the same transaction; a later publication carrying that key while it has no binding is skipped (`unbound_key_suppressed`) and nothing is written, so no duplicate Meeting is created. An explicit bind of the key wins (the binding is read first); the tombstone stays and there is no release. After a series move a rebind is still refused (`provider_series_binding_conflict`) until `adopt_provider_series` (ruling D6, WP3b-S4).

## 7. Synthetic example

Synthetic values only; `example.invalid` addresses, no real calendar, person or provider identifier.

```json
{
  "schema": "meeting_sync_v1",
  "schema_version": "1.1.0",
  "generated_at_utc": "2030-01-06T06:00:00Z",
  "cycle_run_id": "synthetic-run-0001",
  "coverage": {
    "start_utc": "2029-12-07T06:00:00Z",
    "end_utc": "2030-04-06T06:00:00Z",
    "calendar_refs": ["cal-synthetic-primary"]
  },
  "events": [
    {
      "calendar_ref": "cal-synthetic-primary",
      "ical_uid": "uid-single-0001@example.invalid",
      "series_ical_uid": null,
      "occurrence_original_start_utc": null,
      "start_utc": "2030-01-07T15:00:00Z",
      "end_utc": "2030-01-07T16:00:00Z",
      "timezone_name": "America/New_York",
      "status": "confirmed",
      "all_day": false,
      "provider_event_id": "evt-synthetic-0001",
      "provider_event_id_format": "mutable",
      "title": "Synthetic kickoff",
      "location_text": "Room 1",
      "virtual_meeting_url": "https://meet.example.invalid/kickoff",
      "attendees": [
        {"email": "organizer@example.invalid", "display_name": "Synthetic Organizer", "is_organizer": true, "response_status": "accepted"},
        {"email": "guest@example.invalid", "display_name": null, "is_organizer": false, "response_status": "needs_action"}
      ]
    },
    {
      "calendar_ref": "cal-synthetic-primary",
      "ical_uid": "uid-series-0001@example.invalid",
      "series_ical_uid": "uid-series-0001@example.invalid",
      "occurrence_original_start_utc": "2030-01-08T14:00:00Z",
      "start_utc": "2030-01-08T15:00:00Z",
      "end_utc": "2030-01-08T15:30:00Z",
      "timezone_name": "Europe/London",
      "status": "confirmed",
      "all_day": false,
      "title": "Synthetic weekly",
      "attendees": []
    }
  ]
}
```

The second record is an occurrence moved one hour later: its key keeps the original start `2030-01-08T14:00:00Z`. The coverage claims `cal-synthetic-primary` complete from `generated_at_utc` minus the 30-day lookback (section 8.1) to a 90-day horizon. Without the `coverage` object and with `schema_version` `1.0.0`, the example is a valid 1.0 publication.

## 8. Collector implementation notes

A ready-to-apply checklist for the external ChatLLM calendar collector (Manager ruling R-OP-8, operator delegation 2026-11-22). The collector is outside this repository; the operator applies these notes to it once. Sections 1–5 above are the contract; where this checklist and those sections disagree, those sections win. All values below are synthetic.

### 8.1 Which events to send

- [ ] **The window.** Send every timed event of the calendar whose current start is at or after `generated_at_utc` minus the **collector lookback L = 30 days** (`my_pa.domain.meeting_sync.model.COLLECTOR_LOOKBACK`; Manager ruling D3), up to the collector's forward horizon: single meetings and each **occurrence** of a recurring series (expanded instances, including moved and cancelled ones). my-pa relies on L: a Meeting that starts before `now - L` can never meet a sync record, so the reconciliation pass does not review it. A collector that changes L must have this contract changed first.
- [ ] **Exclude all-day events.** Do not send them at all. (If one is sent it must carry `all_day: true` and is quarantined as `all_day_unsupported`, ruling D4; omitting it is the clean path.)
- [ ] Do not send a recurrence master by itself (ruling D7); send its occurrences.
- [ ] Send a cancelled event or occurrence with `status` `cancelled`. Do not drop it: a cancelled known event cancels its Meeting; a cancelled unknown one is skipped harmlessly (`cancelled_unknown_skipped`).
- [ ] **No bodies.** Never send a body, body preview, description, notes or attachment. Do not add `body`, `body_preview`, `description` or `notes` keys, even empty: the parser drops them (`content_field_ignored`), but the collector must not read or ship them.

### 8.2 Field by field

| Field | Required | Derive it from the calendar event |
| --- | --- | --- |
| `calendar_ref` | yes | A neutral, stable label the operator configures once per calendar (for example `cal-synthetic-primary`), like `mailbox_ref` for mail. Never an address. Never change it: it is part of every event's identity. |
| `ical_uid` | yes | The iCalendar `UID` property. For an occurrence, the UID the whole series shares (the master's UID), not a per-instance id. With Microsoft Graph that is the series-wide `uid`, not the per-instance `iCalUId`. |
| `series_ical_uid` | occurrences only | The recurrence master's `UID`. Send it exactly when `occurrence_original_start_utc` is sent; `null` (or absent) for a single meeting. |
| `occurrence_original_start_utc` | occurrences only | The occurrence's **original** start: the iCalendar `RECURRENCE-ID` (Graph `originalStart`), or for an unmodified instance its scheduled start in the series pattern. Never its current start, so a moved occurrence keeps its identity. UTC with `Z`. |
| `start_utc`, `end_utc` | yes | The current start and end, converted to UTC, `YYYY-MM-DDTHH:MM:SSZ`. `end_utc` is not before `start_utc`. |
| `timezone_name` | yes | The event's IANA zone (`America/New_York`). A Windows zone name (`Eastern Standard Time`) must be mapped to IANA with the CLDR `windowsZones` table. Never send an abbreviation or an offset. If a zone has no mapping, send the record unchanged so it is quarantined visibly (`timezone_not_iana`); do not guess. |
| `status` | yes | `cancelled` for a cancelled event or occurrence; otherwise the event's own status (iCalendar `STATUS`): `tentative` or `confirmed` (the default). Free/busy show-as and attendee responses are not status. |
| `all_day` | yes | Always `false` (all-day events are excluded, section 8.1). |
| `title` | yes | The subject, 1–200 characters, not only whitespace. Never truncate: a longer subject quarantines the record (`title_unrepresentable`). |
| `location_text` | no | The display location, at most 500 characters; `null` when none. |
| `virtual_meeting_url` | no | The online-meeting **join URL** only, exactly as the provider gives it, when it is `https` with a host, at most 2048 characters, with no whitespace, control characters or credentials. Otherwise send `null`. Never rewrite a URL (for example `http` to `https`); never take a URL out of the body. |
| `provider_event_id` | no | The provider's event id, 1–1024 characters. It is an attribute, never identity. |
| `provider_event_id_format` | no | `immutable_verified` only when the collector requests immutable ids and has verified it; `mutable` when the id is known to change; otherwise `unknown`. |
| `attendees` | no | At most 100 entries `{email, display_name, is_organizer, response_status}`. See the address rules below. |

Top level: `schema` = `meeting_sync_v1`, `schema_version` = `1.1.0`, `generated_at_utc` (section 8.3), `events`, `coverage` (below), and optionally `cycle_run_id` (the collector's run reference).

**Coverage (1.1.0, section 1.1).**

- [ ] Emit `coverage` on every publication whose read of its calendars completed: `start_utc` = the window start the collector used (no later than `generated_at_utc` minus 30 days), `end_utc` = its forward horizon, both UTC with `Z`; `calendar_refs` = every calendar read **completely** over that window (1–100, each once).
- [ ] Leave a calendar out of `calendar_refs` if its read failed, was paged short, or was filtered; if no calendar was read completely, omit `coverage` entirely (and keep `schema_version` `1.1.0`). Never emit an empty or partial `coverage` object: it rejects the whole publication (`invalid_coverage`).
- [ ] The window must contain every event sent for the listed calendars' claim, by current start (section 1.1); an event moved out of the window is simply not sent.

**Addresses.** my-pa normalizes each attendee address with `casefold` on the local part and the domain. Before sending:

- [ ] drop attendees with no address (an entry without `email` quarantines the record);
- [ ] merge entries whose addresses are equal after `casefold` (`Organizer@Example.invalid` and `organizer@example.invalid` are one attendee; keep `is_organizer` if either has it);
- [ ] mark at most one organizer;
- [ ] map response states to `unknown`, `needs_action`, `accepted`, `declined` or `tentative`.

An event with more than 100 distinct attendees cannot be held and is quarantined (`attendees_unrepresentable`); do not truncate the list. WP2 validates attendees but never applies them to a Meeting (ruling D2).

### 8.3 `generated_at_utc`: strictly increasing

- [ ] Set `generated_at_utc` to the publication time in UTC (`YYYY-MM-DDTHH:MM:SSZ`), **strictly greater** than the stamp of every earlier publication for the same calendar.
- [ ] Persist the last stamp the collector published. If the clock reads a time at or before it (clock step, retry within one second), use the last stamp plus 1 second instead.
- [ ] Never re-use a stamp for different bytes. Re-uploading the exact same file is safe (idempotent).

**Why.** my-pa applies records for a known event only in publication order (resolution rule 7, section 5). Each binding remembers the stamp of the last record applied to it. A publication with an older stamp is skipped (`stale_record_skipped`) and one with an equal stamp but different bytes is skipped as ambiguous (`ordering_conflict_skipped`). Both skips are reported only in each record's `MeetingSyncOutcome` and fail nothing, so a stamp that goes backwards freezes every known Meeting until a newer stamp arrives.

### 8.4 File naming and placement

Fixed by Manager ruling D1 (WP3b), which registers the source (spec section 1.2). It mirrors the WP1 communications convention (spec section 1.1: the `mcp` file workspace, canonical folder `My PA/Daily Intelligence/communications/`, one `YYYYMMDD-comms.json` per business date):

- **Folder:** `My PA/Daily Intelligence/meetings/` in the `mcp` file workspace, a sibling of the communications folder.
- **Name:** `YYYYMMDD-meetings.json`, the UTC date of `generated_at_utc`, one file per date.
- **Re-publication:** a later run on the same date overwrites that file with new bytes and a newer `generated_at_utc`. my-pa keys files by SHA-256, so the new bytes are a new snapshot and the earlier one is superseded for that path (spec section 1.3).
- **Atomic write:** write to a name outside the pattern (for example `.YYYYMMDD-meetings.json.partial`) and rename it into place when complete. The stability rule (spec section 11) tolerates a slow writer, but a partial file must never carry the final name.
- my-pa only reads this folder; it never renames, moves or deletes the collector's files.

### 8.5 Verify a publication before upload

- [ ] Size at most 16 MiB; strict UTF-8; no duplicate keys, `NaN` or `Infinity`.
- [ ] `coverage` present, UTC, `start_utc` not after `end_utc`, at least `generated_at_utc` minus 30 days back, listing only completely read calendars (section 8.2).
- [ ] `generated_at_utc` is later than the last uploaded stamp (section 8.3).
- [ ] No all-day event, no body or description key, no non-`https` join URL.
- [ ] Run the repository parser over the file from a my-pa source checkout. It prints counts, closed-vocabulary codes and the stamp only, never event content:

  ```
  PYTHONPATH=src python - FILE <<'PY'
  import sys
  from pathlib import Path
  from my_pa.infrastructure.meeting_sync.parser import parse_publication

  result = parse_publication(Path(sys.argv[1]).read_bytes())
  print("status", result.status.value, "rejection", result.rejection)
  publication = result.publication
  if publication is not None:
      print("generated_at_utc", publication.generated_at_utc.isoformat())
      print("records", publication.record_count, "accepted", len(publication.events),
            "quarantined", len(publication.quarantined))
  print("codes", dict(result.diagnostics.code_counts))
  for entry in result.diagnostics.entries:
      if entry.code.value == "invalid_coverage":
          print("coverage defect", dict(entry.detail)["defect"].value)
  if publication is not None:
      print("coverage", publication.coverage is not None)
  sys.exit(0 if publication is not None and not publication.quarantined else 1)
  PY
  ```

  Upload only on exit 0 (accepted, 0 quarantined). Also expect no `content_field_ignored` or `unknown_record_keys` code, and `coverage True` when any calendar was read completely. On the synthetic fixture `tests/fixtures/meeting_sync/sync_publication.json`, which carries deliberate faults, it prints `accepted`, 5 records, 4 accepted, 1 quarantined, with the codes `all_day_unsupported`, `content_field_ignored` and `timezone_not_iana`, and exits 1. On `tests/fixtures/meeting_sync/sync_publication_v1_1.json` (the same events as a 1.1.0 publication with a two-calendar coverage) it prints the same counts and codes, then `coverage True`, and exits 1.

### 8.6 Synthetic values only

Test the collector change with synthetic calendars only: `example.invalid` addresses and hosts, `uid-…@example.invalid` UIDs, `cal-synthetic-…` references and `evt-synthetic-…` ids, as in section 7. Never put a real calendar, address, UID, provider id or join URL in a fixture, a log line, a ticket or this document.
