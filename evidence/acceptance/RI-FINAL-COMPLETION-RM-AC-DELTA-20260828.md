# RI final-completion Relationship Memory access delta

This additive record supersedes only the identity-correction table-reach clauses in
`RM-API-AC-002`; the 2026-08-22 acceptance package remains historical evidence for
everything else.

`entities.merge.preview` reads three of the eight (`relationship_memories`,
`relationship_memory_context_links`, `relationship_memory_proposals`) and
`entities.merge.preview` writes none of the eight. `entities.merge` reads four of the eight (`relationship_memories`,
`relationship_memory_context_links`, `relationship_memory_proposals`, `relationship_memory_versions`) and
`entities.merge` writes three of the eight (`relationship_memories`, `relationship_memory_context_links`,
`relationship_memory_proposals`). `entities.split.preview` reads three of the eight
(`relationship_memories`, `relationship_memory_context_links`,
`relationship_memory_proposals`) and writes none of the eight. `entities.split` reads four
of the eight (`relationship_memories`, `relationship_memory_context_links`,
`relationship_memory_proposals`, `relationship_memory_versions`) and writes three of the eight (`relationship_memories`,
`relationship_memory_context_links`, `relationship_memory_proposals`).

Merge and split change only exact opaque subject/context bindings under guarded
before/after state while retaining immutable origin subjects. They read or write no memory
statement or evidence payload.

**WP-RE-04 Phase 4B (Record Event feed, 2026-09-29):** merge and split additionally read
`relationship_memory_versions`, and from it select only the `classification` column -- of
the memory's current version -- matched on the join key `memory_version_id` under the
Principal partition (`memory_feed_facts` / `context_link_owner`; the context-link owner
lookup also joins on `memory_version_id` and `memory_id`). Every `relationship_memory`
Record Event they stage stores that classification (operator ruling OD-8 (i), Manager
ruling MR-06). No statement, structured value, evidence payload or any other version column
is read; `tests/security/test_record_events_carry_no_payload.py` holds the read to those
columns.

**WP-RE-06 (Record Event feed read, 2026-09-30):** `record_events.list` reads two of the eight
(`relationship_memories`, `relationship_memory_versions`) and writes none of the eight. The
reach exists only for a remote caller, inside the operator-ruled OD-8 (i) `EXISTS` that
withholds every Record Event of a memory whose current version is `restricted_local`: it
joins `relationship_memories.memory_id` and `current_version_id` to
`relationship_memory_versions.memory_version_id` under the Principal partition and compares
that version's `classification`. No memory column enters a returned row -- a feed item
carries only the event's own metadata -- and no statement, structured value, evidence
payload or any other memory or version column is read;
`tests/security/test_record_events_carry_no_payload.py` holds the reader to those columns.

**KLP-WP-03 (Knowledge Assertion plane, 2026-10-04):**
`knowledge.assertions.read` reads one of the eight (`relationship_memory_versions`) and writes
none of the eight; `knowledge.assertions.list` reads one of the eight
(`relationship_memory_versions`) and writes none of the eight; `knowledge.assertions.search`
reads one of the eight (`relationship_memory_versions`) and writes none of the eight;
`knowledge.assertions.history` reads one of the eight (`relationship_memory_versions`) and
writes none of the eight; `knowledge.assertions.reveal` reads one of the eight
(`relationship_memory_versions`) and writes none of the eight. Each of those five reaches it
only for a remote caller, inside the R6 section 5.2 `withheld_remote` `EXISTS`, comparing the
`classification` of every version of a cited memory under the Principal partition to withhold
the assertion; no memory column enters a returned row.
`knowledge.assertions.create` reads one of the eight (`relationship_memory_versions`) and writes
none of the eight: for a cited memory
it reads each version's `statement_sha256` and `classification` under the Principal partition,
to verify the cited digest and take the rank-max class onto the Knowledge evidence row. No
statement, structured value or evidence payload is read.
