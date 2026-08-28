# RI final-completion Relationship Memory access delta

This additive record supersedes only the identity-correction table-reach clauses in
`RM-API-AC-002`; the 2026-08-22 acceptance package remains historical evidence for
everything else.

`entities.merge.preview` reads three of the eight (`relationship_memories`,
`relationship_memory_context_links`, `relationship_memory_proposals`) and
`entities.merge.preview` writes none of the eight. `entities.merge` reads three of the eight (`relationship_memories`,
`relationship_memory_context_links`, `relationship_memory_proposals`) and
`entities.merge` writes three of the eight (`relationship_memories`, `relationship_memory_context_links`,
`relationship_memory_proposals`). `entities.split.preview` reads three of the eight
(`relationship_memories`, `relationship_memory_context_links`,
`relationship_memory_proposals`) and writes none of the eight. `entities.split` reads three
of the eight (`relationship_memories`, `relationship_memory_context_links`,
`relationship_memory_proposals`) and writes three of the eight (`relationship_memories`,
`relationship_memory_context_links`, `relationship_memory_proposals`).

Merge and split change only exact opaque subject/context bindings under guarded
before/after state while retaining immutable origin subjects. They read or write no memory
statement, classification, or evidence payload.
