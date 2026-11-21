# ADR-021: Communications intelligence

- **Status:** Proposed — accepted-candidate; **not ratified**. Operator ratification is pending. Nothing is persisted, migrated, exposed, granted or deployed. WP1 (this ADR, its implementation spec, the sanitized corpus evidence and the pure source contract) is the only implemented part.
- **Decision ID:** `MYPA-COMMS-D-021`
- **Goal:** `MYPA-COMMS-MEETCTX-P1P3-20261121`, extended by `MYPA-PULSE-INTELLIGENCE-EXTENSION-20261121` (shared ingestion lifecycle only)
- **Repository:** `RMF112018/my-pa`
- **Repository identity:** branch `feat/comms-intelligence` at `ac0d06ae85200c3aa48c66279745a76808684a35` (tree `44c2dbd6d59af088036f1110281cdbf2b93a85ca`), on `origin/main@092610d36b7d1493fc7fda6e352a4bd06e914f61` (the cycles worker plane, #367, merged). Alembic single head `640aaacc78e8` (129 revision files). `ADR-020` is taken by the meeting prep briefs of PR #368 (branch `feat/meeting-prep`, not merged here), so this is `ADR-021`.
- **Scope:** communications as an evidence class (Outlook mail collected by the ChatLLM collector and published as `communications_evidence_v2` JSON), its identity, storage, search, coverage and meeting-context retrieval, and the ingestion lifecycle it shares with Procore PULSE exports. The concrete contract is [`communications-intelligence-contract.md`](../architecture/communications-intelligence-contract.md) ("the spec"); the corpus evidence is [`docs/evidence/communications-corpus/`](../evidence/communications-corpus/README.md).

## Context

The operator wants meeting preparation to draw on the mail around a meeting: who wrote to the attendees, what was said about the project, which RFIs, change bulletins and GMP items were in play. Mail already reaches the NAS: a ChatLLM collector reads the operator's mailbox and publishes one `communications_evidence_v2` JSON file per business day. my-pa does not read it.

The corpus measured on 2026-11-21 (31 publications: 29 lean-dialect files in the canonical folder, 2 rich-dialect files outside it; 4,141 records) settles most design questions with evidence rather than taste:

- one schema version (`2.0.0`) in **two dialects**, lean and rich;
- every provider id is **mutable**; the Internet Message-ID is present in every record; 3,527 provider ids carry 3,461 distinct messages;
- in 23 backfill files every Sent item also appears as an inbox-lane record with the **same provider id** (421 pairs): folder role in the lean dialect is a lane claim, not verified membership;
- 66 messages are held by **two** mailbox items (50 Inbox+Sent, 16 Inbox+Inbox);
- the producer `dedup_key` is `mailbox | provider id`, 35 body hashes and 479 subjects span distinct messages: none of them is identity;
- 44 bodies are **withheld** by the producer's privacy screen;
- 52 % of records carry quoted reply chains;
- windows are declared with a nominal `hours` label (the live Friday window is 33.2 h, labelled 24) and an inclusive end; merged coverage is one continuous interval 2026-10-17T04:00Z → 2026-11-20T14:12:05Z;
- a bare six-digit number appears in 1,713 records and is not a reliable spec-section identifier.

Meetings carry no provider identity today (`meetings` has a nullable `meeting_series_id` and no calendar columns), so "the mail about this meeting" cannot yet be joined to a calendar event or recurrence.

A second consumer is already named: Procore PULSE CSV exports (Project Reporting Intelligence) arrive as files in the same workspace and need the same snapshot, hashing, idempotency, quarantine and freshness machinery.

## Decision

1. **Communications are a read-only, original-source evidence class.** The authority is the operator's mailbox as observed by the ChatLLM collector; my-pa ingests the collector's `communications_evidence_v2` publications from the `mcp` file workspace ([ADR-019](ADR-019-nas-mcp-file-workspace.md)) and never writes to a publication, the workspace or the mailbox. A communication is neither a product-owned record ([ADR-003](ADR-003-product-owned-user-authored-source-records.md)) nor a managed document. my-pa adds no mail connector of its own.
2. **One shared ingestion lifecycle, domain-specific storage.** A single source registry, immutable snapshots identified by file SHA-256, ingest runs, idempotency by `(source, sha256)`, publication rejection, record quarantine, and coverage/freshness bookkeeping serve every file-published evidence source. Communications is the first consumer; **Procore PULSE CSV exports are the second**. Each consumer keeps its own tables; the lifecycle tables hold no consumer content. PULSE storage is not designed here.
3. **One versioned source contract for both dialects.** `communications_evidence_v2` is parsed by one field-driven parser with dialect detection (lean / rich), major-version rejection (only major `2`), minor tolerance, envelope rejection for envelope faults only and per-record quarantine otherwise. It is the WP1 contract code (`my_pa.domain.communications`, `my_pa.infrastructure.communications.evidence_v2`).
4. **Canonical message identity.** A message is `(principal, mailbox_ref, internet_message_id)` when the Internet Message-ID is provider-returned; otherwise `(principal, mailbox_ref, provider_id)` with identity state `provider_id_only`. The two key spaces never merge. Observations that share a canonical key but disagree on sender or body digest are an `identity_conflict`: quarantined, counted, never merged.
5. **Provider id = mailbox item; records = lane observations.** A provider id names one mailbox item. Each record carrying it is a lane observation of that item: the same provider id in two folder lanes is one item with two observations, not two items, not a dropped duplicate and not a conflict. An exact repeat in the same lane is a `duplicate_observation`. Two provider ids under one Internet Message-ID are two mailbox items of one message.
6. **Folder role is lane evidence with a verification state.** A role is `verified` only when the record returned a folder id or parent folder id; otherwise it is an `unverified_lane_claim`. No logic may treat an unverified role as folder membership.
7. **Participants are reconciled, not overwritten.** Each observation keeps its own normalized participant sets as evidence. Canonical participants are the union by normalized address with per-participant provenance (observations and lanes); `bcc` comes from the sent lane when it returned one; an item with several observations is flagged `participants_reconciled`, and `participants_disagreed` when `to`/`cc` address sets differ. Both raw timestamps are kept per observation; canonical message time is the sent time for a sent-lane primary and the received time for an inbox-lane primary, with its basis recorded.
8. **`dedup_key`, body SHA-256 and subject are never identity.** They are stored as attributes and may be used as signals; nothing merges, splits or suppresses a message on them.
9. **Privacy-withheld bodies are metadata-only.** A withheld body (or unique body) yields no searchable text, is never reconstructed, and is retrievable by metadata only. Its declared digest describes content my-pa never held and is not presented as verified.
10. **Store derived searchable text, a digest and a source pointer; no raw HTML by default.** PostgreSQL holds the versioned searchable text, the body SHA-256 and byte count, and a source pointer (snapshot file SHA-256 + record ordinal). Raw HTML and full bodies stay in the publication file. Storing them in PostgreSQL needs a measured reason and an amendment.
11. **Quoted-chain and signature stripping, versioned.** Searchable text is derived by `comms_search_text_v1`: the provider's `unique_body` when present, else digest-verified producer text, else the body; quoted chains cut, signature/disclaimer blocks removed, markup reduced to text nodes. A derivation change is a new version and a rebuild from the source pointer, never an in-place edit.
12. **Search is PostgreSQL only.** PostgreSQL full-text search (weighted generated `tsvector`) and `pg_trgm`, plus an exact technical-identifier index fed by the versioned extractor `comms_identifiers_v1` (RFI, CB, CO, submittal, GMP, FPL, cued spec sections; bare six-digit numbers are not identifiers by default). No `pgvector`, no semantic index, no external search engine: a semantic index stays behind an abstraction and a benchmark gate (`AGENTS.md` section 4).
13. **Coverage is computed from bounds.** Window ends are inclusive; coverage is the union of `complete` publications' `[start_utc, end_utc]`, merged when at most 1 second apart; gaps are reported, never inferred from business dates or `window.hours`; DST windows are taken as declared.
14. **Meeting provider identity and recurrence resolution are designed here and implemented in WP2.** A Meeting gains a provider binding keyed by calendar reference and iCalendar UID, an occurrence keyed by its original start, and a series binding that resolves to the existing `meeting_series_id`; meeting identity never derives from title or time alone.
15. **Batch MCP reads with neutral names.** Communications are exposed only through bounded, paginated, read-only capabilities with neutral names (proposed: `communications.search`, `communications.read`, `communications.coverage`, and the batch `meetings.context.read`); there is no client write, ingest or delete capability. Ingestion is operator- or worker-driven.
16. **No competing scheduler.** Scheduled ingestion runs on the existing cycles worker plane (`apps/worker.py run --plane cycles`, #367): its poll loop and session advisory-lock single flight, behind its own default-off switch. No cron, queue, daemon or new process type.
17. **Principal isolation.** Every row is Principal-partitioned and reached through the existing partition guard; the Principal is server-derived. The remote principal is always the operator ([ADR-013](ADR-013-fixed-local-principal-and-operator-auth-grants.md)), so client separation is by grant, not by Principal.
18. **Content is inert data.** Subjects, bodies and derived text are never evaluated, followed or treated as instructions; logs, diagnostics and audit rows carry codes and counts, never subjects, bodies or addresses.
19. **No new lineage family yet.** Communications are not admitted to the record-lineage taxonomy ([ADR-015](ADR-015-record-lineage-and-issue-situations.md) decision 6). Admitting a `communication` family with passage anchors over stored searchable text is a later ADR-015 amendment.

## Consequences

- One additive migration in WP3 creates the shared lifecycle tables and the communications tables; a further one in WP2 adds meeting provider bindings. New capability names, a purpose, a ChatLLM data profile bump, a settings switch (`MY_PA_COMMUNICATIONS_ENABLED`, default off) and an ingest switch arrive in WP3–WP5.
- Retrieval quality depends on the collector. Lean folder roles stay unverified until the collector returns folder ids; withheld bodies stay unsearchable; attachments are never collected.
- Search text is a derivation. A rebuild needs the publication file; if a file disappears its stored text stays and is marked source-unavailable.
- Communications returned to a connected client are processed by an external model. That is an eligibility decision (`AGENTS.md` section 5) the operator must make before any grant.
- PULSE inherits the lifecycle without inheriting communications semantics, so the lifecycle tables must stay content-free.

## Rejected alternatives

| Alternative | Reason rejected |
| --- | --- |
| Producer `dedup_key` as identity | it is the mailbox reference joined to the provider id: it splits the 66 two-item messages and changes when a mutable id changes |
| Provider id as message identity | mutable (`graph_default_mutable`), and 66 messages have two items; it is item identity only |
| Dedup by body hash or subject | 35 hash groups and 479 subject groups span distinct messages |
| Two items for one provider id seen in two lanes | the 421 backfill pairs are lane artifacts of one item |
| Drop the inbox-lane copy of a backfill pair | loses evidence (received time, metadata); merge as an observation instead |
| Trust folder role | lean records return no folder id; the defect proves the role can be wrong |
| Rejecting the rich dialect, or one parser per dialect | same schema version; one field-driven parser takes both with less code |
| Store raw HTML or full bodies in PostgreSQL | duplicates the source, enlarges the privacy surface, unused by search; the source pointer suffices |
| Reconstruct or index withheld bodies | the producer withheld them on purpose; digests cannot be verified |
| `pgvector` or a semantic index now | `AGENTS.md` section 4 benchmark gate; lexical plus identifier search is unmeasured yet |
| External search engine (OpenSearch, Elasticsearch, Meilisearch) | new infrastructure without a measured need; tens of thousands of rows a year fit PostgreSQL |
| Six-digit numbers as spec sections | 1,713 noisy records; a cue is required by default |
| Coverage from `window.hours` or business dates | the Friday window is 33.2 h labelled 24; business-date meaning differs by rule |
| A cron job, queue or new worker type for ingestion | #367's cycles plane already provides the poll loop and single flight |
| A direct Graph/Outlook connector or Drive API reader in my-pa | live personal-data connector access is deferred (`AGENTS.md` section 3); the collector already publishes to the NAS |
| A PULSE-specific ingestion lifecycle | duplicates snapshot, idempotency and quarantine logic; one lifecycle with two consumers |
| One generic evidence table for communications and PULSE | different identities, units and queries; storage stays domain-specific |
| Merge identity conflicts heuristically | no evidence says which side is right; quarantine and report |
| Ingest attachments | never collected by the producer; out of scope |

## Supersession

This ADR supersedes nothing. It relies on ADR-019 for the `mcp` workspace and does not amend it: ingestion only reads. Changing the identity key, storing raw bodies in PostgreSQL, adding a semantic index, a client write or delete capability over communications, a new scheduler or process, or a lineage family requires an amendment or a superseding ADR. Adding a third consumer of the lifecycle, a new dialect or minor version, a new identifier kind, a new search-text or extractor version, or new bounds is a spec change.

## Implementation status

- **WP1 (implemented on this branch, not merged):** this ADR; the spec; the six sanitized corpus deliverables; the pure source contract — domain `my_pa.domain.communications` (model, diagnostics, classification, reconciliation, integrity, `comms_search_text_v1`, `comms_identifiers_v1`, corpus summaries), parser `my_pa.infrastructure.communications.evidence_v2`, the aggregate-only CLI `my_pa.infrastructure.communications.aggregate_cli`, synthetic fixtures under `tests/fixtures/communications_evidence/` and FAST tests. No migration, persistence, capability or switch.
- **Planned (each a separate PR and review):** WP2 meeting provider identity and recurrence resolution; WP3 the shared ingestion lifecycle plus communications persistence, ingestion, coverage, backfill and scheduled ingestion; WP3P PULSE persistence and ingestion on that lifecycle; WP4 communications search and its MCP reads; WP4P PULSE retrieval MCP; WP5 batch meeting context with PULSE evidence (communications-only must work when PULSE is absent).
- **Operator-gated:** ratification of this ADR, source admission, the external-model eligibility decision, grants, production migration and deployment.
- **Manager rulings 2026-11-21 (status unchanged: Proposed):** recorded in [spec section 21](../architecture/communications-intelligence-contract.md#21-manager-rulings-2026-11-21). R1 workspace read through the files store, subject to the ADR-019 decision 7 preflight in WP3; R2 the 2 rich off-folder publications admitted to backfill as explicitly registered sources, overlap deduplicated by identity; R3 `english` FTS plus exact identifiers plus `strpos` confirmation for now, WP4 measures `english` against `simple` and may switch; R4 capability names, the `communications_read` purpose and the default-off switches accepted as proposals; R5 identifier-extractor recall recorded as an open WP4 defect; the WP2 meeting-sync source choice deferred to WP2's investigation. Grants, external-model eligibility and acceptance of this ADR remain operator-gated.
