# Record lineage: guidance for connected clients

**Status:** client guidance for record lineage S3.1
([contract](../architecture/record-lineage-s31-open-writes-contract.md) section 7.12,
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) decision 15). It
describes what a connected MCP client may do with lineage once an operator has turned it
on. It turns nothing on: `MY_PA_LINEAGE_ENABLED` is off by default, every lineage
capability needs a grant the operator issues, and every lineage name stays an operator
decision for the ChatLLM profile.

Lineage records **why** records belong together: an Issue and its members, a Commitment
and the exact note passage it came from, a Task that blocks another. A connected client
may **commit** such a link when it has identified the relationship, or when the user told
it to, and may **use** the recorded links to narrow searches, write reports and suggest
work. What the server records about a client's link, and what it never lets a client's
link do, is the subject of this page.

## When to commit a link

Commit a link only in one of these 2 situations:

1. **You identified the relationship from exact evidence.** You read the stored text
   (`meetings.notes.read_version`, or the Capture read surfaces) and a passage of it states
   the relationship: "Ana will send the façade survey by Friday" is the origin of the
   Commitment to send the survey. Cite that passage (below).
2. **The user instructed you to record it.** Then also send `"user_directed": true`. The
   server stores that flag as **your claim**, unverified: it changes no gate, no label and
   no total, and the operator sees it as "the user said they directed it (not verified)".
   Never send it when the user did not ask for this specific write.

## When not to commit a link

Similarity is not causation (OD-05). None of these is evidence of a relationship, alone
or together: a shared Project, Meeting Series, date, participant, name, place or similar
wording; 2 records discussed in the same Meeting; a search ranking them together. Never
infer that a record originated from a discussion because the discussion mentions it. If
you only suspect a relationship, say so in your own answer to the user and write nothing:
a committed link is a fact in the Principal's ledger, not a note.

## How to cite evidence

- Cite the **exact stored version**: a Meeting note version (`mnote_…`) or a Capture
  version (`capver_…`), never "the latest notes".
- Give the passage as **code-point offsets of the stored, unnormalized body**
  (`passage_start_cp`, `passage_end_cp`), read with `meetings.notes.read_version` and
  `include_body: true` first.
- Bind the anchor to the bytes you read: `source_sha256` is the version's
  `content_sha256` from that read (required on every exact-version anchor), and
  `passage_sha256` is the SHA-256 of the passage's UTF-8 text (required with a passage).
  The server refuses an anchor whose digests do not match the stored body and passage.
- Use the relation's own evidence role: `origin` for `originated_from`, `discussion` for
  `discusses`, `corroborates` for `blocks` and `related_context`, `contradicts` to contest,
  `resolution` on a work member's evidence, `handoff` for a handoff.

## How to read provenance labels

Every lineage read labels every fact with `acceptance_basis`:

| Label | Meaning |
| --- | --- |
| `user_confirmed` | Recorded or confirmed by the human channel (the local operator, through the CLI or the HTTP gateway). Accepted. |
| `client_identified` | Recorded by a connected client. **Unreviewed and never accepted-grade.** It is shown, traversed and usable for search, suggestions and reports, but it holds the Issue's close until the user reviews it, and a Project total that depends on it is not reportable. |

`user_directed_claim: true` is the writing client's word that the user directed the
write, nothing more. `asserting_client_id` names the writing OAuth client to a local
reader only; a remote client always reads `null` there. Only the operator confirms a
client fact (`records.associations.confirm`, `issues.memberships.confirm`,
`issues.project_links.confirm`): no client, flag or field can.

## What a client may revise

A client may end, correct, contest, reinstate, void or retime facts the user has never
confirmed, its own or another client's. A fact the user confirmed at any revision is
closed to clients, with 1 exception: a client may contest an active confirmed semantic
link once, with an exact `contradicts` passage; after that only the user writes it. A
client that disagrees with a confirmed membership reports it to the user.

## Bounds and replays

- Each OAuth client may commit at most 120 lineage writes an hour and 1000 a day, and all
  clients of the Principal together 2000 a day; past a bound the write answers
  `rate_limited` / `lineage_write_budget` and writes nothing. Refused writes and replays
  cost nothing.
- Through the remote MCP surface you never send an `idempotency_key`: the server derives
  one from your client and the payload, so resending the same request replays its first
  answer (`replayed: true`). To record a new fact after ending an identical one, change
  the payload (for example its evidence).

## The compact facade: call shape

A client connected through the compact facade sees 4 tools at most: `my_pa.describe`,
`my_pa.read`, `my_pa.write` and `my_pa.operator`. Lineage writes are `write` kind,
lineage reads `read` kind, and the operator-only names (close, reopen, the 3 confirms,
backfill) are never published to a remote client.

1. Call `my_pa.describe` to find a capability and read its exact remote input schema.
2. Call `my_pa.read` or `my_pa.write` with `{"capability": <name>, "arguments": <document>}`,
   where the document is `{"payload": {...}}` as that schema states: **no**
   `idempotency_key`, purpose or provenance field (the server derives the key, the purpose
   and the provenance).

Each line below is the params of one MCP `tools/call`.

Committing a link with evidence: find the writes, read the assert schema, then commit
that the Commitment originated from an exact passage of a note version the user told you
about:

```json
{"name": "my_pa.describe", "arguments": {"feature": "lineage", "kind": "write"}}
{"name": "my_pa.describe", "arguments": {"capability": "records.associations.assert"}}
{"name": "my_pa.write", "arguments": {"capability": "records.associations.assert", "arguments": {"payload": {"relation_type": "originated_from", "from_record": {"family": "commitment", "record_id": "cmt_EXAMPLE0001"}, "to_record": {"family": "meeting_note_version", "record_id": "mnote_EXAMPLE0001"}, "evidence_anchors": [{"family": "meeting_note_version", "root_id": "mtg_EXAMPLE0001", "version_kind": "immutable_version", "version_id": "mnote_EXAMPLE0001", "source_sha256": "76882f6bd444bba13fb8da1a52a98fe551eb82ad1c49738bb60077e4dea86f59", "passage_start_cp": 120, "passage_end_cp": 184, "passage_sha256": "2f700a1e53741668269d27af061342fbb1ee756ff93670c800ddbda5de8e0ba1", "role": "origin"}], "user_directed": true}}}}
```

A lineage-aware search: search Tasks, then read what recorded lineage relates to the
hits, mapping each hit's `task_id` to a seed `{"family": "task", "record_id": <task_id>}`:

```json
{"name": "my_pa.read", "arguments": {"capability": "tasks.search", "arguments": {"payload": {"query": "crane permit"}}}}
{"name": "my_pa.read", "arguments": {"capability": "records.lineage.related", "arguments": {"payload": {"seeds": [{"family": "task", "record_id": "tsk_EXAMPLE0001"}, {"family": "task", "record_id": "tsk_EXAMPLE0002"}], "max_depth": 2, "acceptance_bases": ["user_confirmed", "client_identified"]}}}}
```

`records.lineage.related` answers each related record with its depth, the seeds that
reached it and the Issues it was reached under, each link with its exact evidence and
label, `complete_state` and `qualifiers` (what the answer can claim), and
`related_sha256`. Pass `acceptance_bases: ["client_identified"]` to list unreviewed client
facts around the seeds; `issues.closure_readiness` lists an Issue's gaps (blocked members,
stale evidence, contested links and `unreviewed_links`).

## Reproducible report references

A read at an explicit `known_at` (an instant no later than the answer's `known_at`)
reproduces the same facts and the same `related_sha256` while visibility, native records
and evidence availability are unchanged. To cite lineage in a report, pin `known_at` from
the answer you used and record the seeds, filters and `related_sha256` with it; the server
recomputes and records whether they still agree when the report is committed. A report
should say plainly that `client_identified` links are client-identified and unreviewed,
and that `user_directed_claim` is a claim.

Concretely, a synthesizer, reporter or morning-brief artifact cites the read under the
reserved `structured_content` key `lineage_context_ref` with exactly these keys:
`block_schema_version` (the integer 1), `seeds`, `max_depth`, `acceptance_bases` and
`relation_types` as the read was made (list every relation when the read used the
default), `known_at` (the answer's, `YYYY-MM-DDTHH:MM:SS.ffffffZ`) and `related_sha256`.
A collector or researcher artifact may not carry it, and a malformed block is refused as
`invalid_request` / `structured_content`. The `reports.commit` answer is unchanged: what
the server found (`verified_at_commit`, `changed_since_read`, `recompute_failed` or
`not_attempted`), its own digest and its counts of links by label and of claims are in the
artifact's `reports.manifest`, which a remote reader can read in full only while it holds
a `records.lineage.related` grant and sees every family the reference names.
