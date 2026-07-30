# my-pa

`my-pa` is the clean implementation repository for a local-first personal knowledge layer that mediates access to authoritative NAS files, managed documents, personal-data connectors, knowledge records, relationship intelligence, and model-facing context.

## Current state

This branch contains a documentation-only repository scaffold. It establishes module boundaries and routing files but does not implement runtime behavior.

## Approved architectural decisions

- Repository: `RMF112018/my-pa`
- Delivery model: modular monolith in one monorepo with separate gateway and worker processes plus an operator CLI
- Python namespace: `my_pa`
- Configuration prefix: `MY_PA_`
- Canonical logical database identity: `my_pa`
- Existing physical database compatibility: supported through an explicit runtime alias; no database rename, migration, or connection is performed by this scaffold
- External capability names: neutral; no legacy product aliases

## Repository map

Start with [`docs/00_REPOSITORY_SOURCE_INDEX.md`](docs/00_REPOSITORY_SOURCE_INDEX.md).

## Boundaries

Original source systems remain authoritative and read-only by default. Managed output storage is a separate capability. PostgreSQL is the planned canonical metadata and knowledge store. Obsidian is a rebuildable projection, not the authority.

No source-system mutation, managed-document write, connector access, credential use, database change, service activation, deployment, or production action is authorized by this scaffold.
