# GoodNotes / GSQS

GoodNotes support combines local-source admission, notebook/page lineage, durable note semantics, proposal/review flows and a bounded GSQS workflow.

## Current authority

Repository code/tests are the technical truth. Accepted GoodNotes product/acceptance intent is indexed in the cleaned Drive GoodNotes/GSQS lane:

Drive folder `1cfQle_VeBfV4qOxCk6O2QQNiV27JnhwM`.

Do not infer current behavior from a completion/audit package when current code differs.

## Major implementation areas

- `src/my_pa/domain/goodnotes/` — GoodNotes values/models/date semantics.
- `src/my_pa/application/goodnotes_*` — lineage, content, durable-note, semantic/proposal/orchestration behavior.
- `src/my_pa/infrastructure/persistence/goodnotes*` — durable state.
- `src/my_pa/infrastructure/goodnotes/` — local/source mechanisms.
- `ops/goodnotes/` and `ops/runbooks/goodnotes-*` — detailed procedures/evaluation assets.
- GoodNotes capabilities/GSQS workflow through canonical application/MCP surfaces.

## Source safety

GoodNotes local-source handling is a filesystem and subprocess security boundary. Preserve:

- admitted root identity;
- descriptor-relative/no-follow path handling;
- bounded reads;
- digest/identity revalidation;
- refusal of unsafe representations;
- content-free/redacted diagnostics;
- regular-file and single-hard-link checks before and after bounded manifest, representation and observer reads; hard-link drift during a read is refused;
- local OCR as one explicit absolute executable and argument vector with no shell;
- on supported POSIX systems, one process session/group per OCR invocation with bounded nonblocking pipe handling and bounded cleanup; timeout, output overflow, pipe failure, or a descendant retaining a pipe cannot turn partial output into success;
- fail-closed behavior when the required process-containment mechanism is unavailable.

The current implementation details are documented in the [GoodNotes local-source contract](../operations/goodnotes-local-source.md) and enforced by the corresponding architecture/security/unit tests. A future unmerged hardening change is candidate evidence until merged; current documentation must follow the authenticated repository tree.

## Semantics and review

GoodNotes-derived semantic material should preserve notebook/page/note-unit lineage and evidence. Model/derived proposals are not silently canonical; review/promotion receipts and human disposition govern promotion where implemented.

## GSQS

GSQS is a bounded model/evaluation workflow. Synthetic B0 execution and measured evaluation state must be distinguished from live/pilot/production operation.

A capability that can start a bounded workflow does not authorize:

- live personal source access;
- external model disclosure of ineligible data;
- deployment/production activation;
- unrelated source mutation.

## Adding a GoodNotes capability

Check:

1. source/admission and subprocess security;
2. stable notebook/page/note identity;
3. persistence/migration;
4. provenance/evidence;
5. idempotency/retry;
6. proposal/review authority;
7. application capability and MCP schema;
8. worker/orchestrator behavior;
9. synthetic security/database/contract tests;
10. runbook/update implications.

Detailed operational truth is routed from the [operations runbook index](../../ops/runbooks/README.md).
