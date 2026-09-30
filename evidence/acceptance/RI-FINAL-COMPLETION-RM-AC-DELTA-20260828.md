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
