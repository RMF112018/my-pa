# Personal-knowledge pilot harness

This is a checklist for an **operator-authorized** personal-knowledge pilot of
`context.prepare`. It does not access live personal data. This change does not
run the pilot, enroll a live corpus, or commit queries or evidence.

Operator authorization is required before any live corpus is used. Queries,
retrieved excerpts, and personal evidence must **not** be committed to the
repository.

Lexical/structured `context.prepare` is the active path. Semantic retrieval
remains `SEMANTIC_GATE_FAIL`; see
[`context-semantic-retrieval.md`](context-semantic-retrieval.md). Activation
and rollback live in
[`managed-knowledge-context.md`](managed-knowledge-context.md).

## Authorization gate

Do not start a live pilot until the operator has explicitly authorized:

- the live corpus (sources, enrollments, captures, continuity objects);
- the ChatLLM session and remote grants, if any;
- that retrieved text may be shown to the model as **data**, not instructions.

Until that authorization exists, use only the synthetic canaries in
`tests/contract/test_context_prepare_canary.py`.

## Preselected topic classes

Work through each class against the operator's authorized corpus. Record only
redacted identifiers (opaque `prj_`, `cap_`, `sit_`, `kn_`, enrollment IDs) and
coverage tokens. Do not paste query text or excerpts into tickets, commits, or
chat logs that land in git.

| Class | Probe | What to record |
| --- | --- | --- |
| Projects | A named project the operator already holds | Redacted `product_id`; whether it ranked |
| People | A person the operator already holds | Coverage state; relationship plane still `not_admitted` |
| Meetings | A meeting or situation title | Redacted situation/project IDs |
| Commitments | An accepted commitment or pulse item | Redacted `product_id`; accepted lifecycle |
| Captures | A Quick Capture the operator authored | Redacted `capture_id` / version |
| GoodNotes | An enrolled GoodNotes page | Redacted knowledge/source-object IDs |
| Sources | An enrolled source document | Redacted `source_id` / `source_object_id` |

## Metrics to capture

Use redacted IDs only. Do not store query text, conversation text, or excerpts
outside the product.

- Coverage warnings are correct: `searched_complete` no-match is distinct from
  `unavailable` / `incomplete` / `stale` / `not_enrolled`.
- Contradictory packed evidence sets `contradictions_or_conflicts`.
- Cross-conversation persistence is via my-pa (`context.prepare` plus optional
  operator-gated `context.feedback`), not vendor ChatLLM memory.
- `instruction_authority` stays false on the package and every item.
- `retrieval_mode` stays `lexical_structured`.

## What this harness does not do

- Access live personal data as part of this documentation change.
- Authorize production activation, remote writes, OAuth client creation, or
  Abacus account mutation.
- Substitute model memory for retrieved evidence.

No command in this file was executed against a live corpus.
