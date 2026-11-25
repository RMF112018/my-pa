# Scaffold Directory

**Status:** `SCAFFOLD_ONLY`

This directory reserves an approved architectural boundary in `RMF112018/my-pa`. Its detailed responsibility is routed through [`docs/00_REPOSITORY_SOURCE_INDEX.md`](/docs/00_REPOSITORY_SOURCE_INDEX.md) and the nearest owning index.

Directory presence does not authorize runtime implementation. Executable code, credentials, source-system access, database changes, background scheduling, deployment, and production activation require a separately approved goal.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.

## Scripts

| Script | Covers |
| --- | --- |
| [`inspect_entity_plane.py`](inspect_entity_plane.py) | Read-only counts report for the relationship-intelligence entity plane (`--principal` required). |
| [`my_pa_files.py`](my_pa_files.py) | Stdlib reference client for the files byte routes (contract §10): resumable upload with SHA-256 finalize and verified, resumable download. The ticket comes from `MY_PA_FILES_TICKET` or `--token-file`, never the command line. Runbook [`ops/runbooks/files-workspace.md`](../ops/runbooks/files-workspace.md). |
| [`sdcc_publish.py`](sdcc_publish.py) | Bounded SDCR session publisher for Issue #365, using existing `my_pa.read`/`my_pa.write` and `my_pa_files.py` byte tickets; reference [SDCR publication instructions](SDCR_PUBLISHER_README.md). Implementation candidate only; no live client/grant/cutover activation. |
