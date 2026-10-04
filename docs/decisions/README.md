# Scaffold Directory

**Status:** `SCAFFOLD_ONLY`

This directory reserves an approved architectural boundary in `RMF112018/my-pa`. Its detailed responsibility is routed through [`docs/00_REPOSITORY_SOURCE_INDEX.md`](/docs/00_REPOSITORY_SOURCE_INDEX.md) and the nearest owning index.

Directory presence does not authorize runtime implementation. Executable code, credentials, source-system access, database changes, background scheduling, deployment, and production activation require a separately approved goal.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.

Accepted decisions are listed in [`00_ADR_INDEX.md`](00_ADR_INDEX.md). The most recent is [ADR-014](ADR-014-knowledge-assertion-layer.md), the Knowledge Assertion layer (architecture contract only; not implemented).
