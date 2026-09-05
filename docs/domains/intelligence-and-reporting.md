# Intelligence and reporting

MY-PA's Intelligence Artifact / Report plane stores product-owned immutable report artifacts with cycle-run identity and staged pipeline lineage.

ADR-010 is the durable architecture decision.

## Current model

The report plane supports:

- beginning/identifying a cycle;
- committing immutable artifacts;
- recording run state;
- reading by ID/latest;
- listing/searching;
- resolving required artifact/input sets.

`structured_content` is persisted structured data, not reconstructed by scraping Markdown.

## Authority

Reports are product-owned derived artifacts. They must preserve producer/run/provenance context so generated intelligence cannot be mistaken for authoritative source evidence.

The report plane does not overwrite original sources.

## Readiness

Resolver/readiness results represent a report/input-set contract. A resolver state such as READY is not global system health. Web `/api/system` keeps report readiness separate from backend/worker availability.

## Web

The `/intelligence` surface and BFF routes use canonical report capabilities. The BFF preserves aggregate and per-member resolver state.

## Model/agent use

MCP clients may read/use report capabilities only through the same application authorization and disclosure boundary. Do not add a model-only storage bypass.

## Product intent

Drive's Other Domains lane includes the ChatLLM report persistence/retrieval feature package. Drive owns accepted product intent; repository code/ADR-010 own current technical behavior.

## Extending the report plane

A new artifact type/pipeline stage should define:

- stable artifact/cycle identity;
- immutable payload contract;
- producer/policy version provenance;
- idempotency;
- resolver dependencies;
- Principal partitioning;
- search/list/read contract;
- failure/run-state semantics;
- BFF/MCP exposure;
- tests for immutable lineage and cross-Principal isolation.
