"""Capture domain: records the user authors inside `my-pa`.

`ADR-003` makes these a third authority class — product-owned, append-only, and
held in PostgreSQL. They are neither a source-system write nor a
managed-document write, and nothing in this package reaches a source provider:
the read-only source port gains no method because capture exists.

Three modules, one rule between them: what the user wrote is preserved exactly
and never edited in place. `version` holds the capture's stable identity, the
immutable content, and the supersession chain an edit appends to; `submission`
holds the admission record and the receipt, which are facts about the *request*
rather than about the content; `errors` are the refusals, none of which carries
the value it refused.
"""
