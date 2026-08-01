# Before / After Semantic Comparison

## Before

- Committed `goal-state.json` presented `current_baseline.sha = 3e5aad7b…` as the merged baseline any future authorization must bind.
- Migration index and goal charter repeated that SHA as “Current merged baseline”.
- Authorization ledger top-level rule invalidated on movement of main from `3e5aad7b…`, treating that SHA as live current authority.

## After

- Exact current SHA/tree are **not** persisted as continuously current.
- Authority = `RUNTIME_GIT` with required resolution commands.
- `178a7e24…` appears only as `RECORD_BASE` / historical `MERGE_SHA`.
- `3e5aad7b…` and `d4fed7ec…` remain as labelled historical identities.
- Top-level invalidation compares runtime Git to an authorization’s **external** bound identity.

## Defect not reproduced

This correction does **not** replace `3e5aad7b…` with `178a7e24…` as a new embedded “current baseline”.
