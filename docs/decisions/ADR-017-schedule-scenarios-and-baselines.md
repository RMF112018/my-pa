# ADR-017: Schedule Scenarios, server CPM and operator-approved baselines

- **Status:** Proposed — directive-selected by the operator on 2026-11-03; not ratified for
  production. Nothing is implemented, merged, migrated, granted or deployed. Its switch
  `MY_PA_SCHEDULE_SCENARIOS_ENABLED` is default off and effective only together with
  `MY_PA_SCHEDULE_ENABLED`. Live migration, grants, `profile-apply`, enabling either switch
  and any certified use remain operator gates.
- **Decision date:** 2026-11-03
- **Repository basis:** `feat/schedule-scenarios-engine@83e7981718ee467f0d41c42b7cc353bfbf329c14`,
  tree `3407926c30fc17730dc4889fc837628449a62c33` (`origin/main` with the S5a, S5b-1 and
  S5b-2 CPM Workbench slices merged: #344, #345, #347). `ADR-017` was unallocated there:
  `docs/decisions/` held ADR-001 to ADR-016.
- **Authority:** 4 operator statements of 2026-11-03 given directly to the Manager: the
  directive "The write capabilities need to be able to create entirely new versions of the
  schedule data for the purpose of running what-if scenarios, updating schedules, Monte
  Carlo sims, etc as well as creating lineage records for the schedule data." with the
  decisions that schedule logic is client-authored from a published baseline and that the
  server provides deterministic CPM while Monte Carlo runs client-side; the request for series
  auto-matching and a defined latest version; the authoritative-baseline statement; and the
  closed baseline decisions (per Project, unlimited, governing by append-only events,
  operator approval of every baseline and governing change, clients only propose). Design
  review R8 ruled that a superseding ADR is required because
  [ADR-016](ADR-016-cpm-workbench-schedule-evidence.md)'s own Supersession section requires
  one to persist derived data or to link schedule evidence to another domain.
- **Scope and contract:** the Schedule Scenarios plane; the concrete contract is
  [`schedule-scenarios-contract.md`](../architecture/schedule-scenarios-contract.md). The
  lineage vocabulary it needs is decision 17 of
  [ADR-015](ADR-015-record-lineage-and-issue-situations.md).

## Context

ADR-016 made a schedule PDF publication immutable source-bound derived evidence and excluded,
following review R2, any application-computed CPM, persisted derived schedule data and
schedule-specific links. The operator now needs to model schedules: author logic over a
published baseline, compute critical paths, run Monte Carlo, keep the results, link them to
Issues, Constraints and work, file imported updates into the right Series, know which update
is current, and hold an authoritative baseline per Project.

## Decision

1. **Scenario data is a new, non-authoritative data class.** A Scenario is a linear chain of
   immutable, append-only versions whose content (activities, relationships, calendars,
   constraints, durations, distributions, progress) is client-authored. Version 1 is the
   exact snapshot of an eligible publication (or approved baseline) or a byte-identical copy
   of another version. Nothing in it is source-bound, accepted-grade or reportable.
2. **The server computes CPM deterministically** with engine `my-pa-cpm-v1` over integer
   working minutes, stores each run immutably by `(version, engine version)` and labels it
   `server_computed` over client-authored input. It never computes over a publication and
   never samples; Monte Carlo results are stored as `client_asserted` outputs after schema,
   bound and consistency checks only.
3. **Schedule and scenario records join the lineage ledger** as 6 endpoint families with a
   minimal set of relations (ADR-015 decision 17); links are `client_identified` unless the
   human channel writes them; no native record is mutated, coerced or linked by a column.
4. **Imports may be auto-matched.** An import may ask for its Series to be matched; it is
   admitted into its own intake Series, parsed, deterministically matched by exact published
   Activity IDs with a conservative, name-vetoed rule, and the decision is recorded; a match
   completes by a worker-performed second admission of the same source version that inherits
   the attested operator import. An explicit Series always wins.
5. **The current standard update is derived, never stored**: among eligible publications of a
   Series that are not approved baselines and are not displaced by an eligible successor, the
   maximum by `(data_date, admitted_at, publication_id)`, with a visible same-Data-Date
   ambiguity flag. All files are retained.
6. **Baselines are operator-approved Project objects.** A publication is a baseline only when
   an operator-approved Baseline names it; every other publication is a standard update; the
   `reference` role is retired by an additive restating migration. Authority is per Project
   with no limit on the number of baselines; which baseline governs is set by append-only
   operator events. Clients may only propose; a proposal is never a baseline or authoritative.
   Every output naming a baseline shows its provenance.
7. **Off by default, closed everywhere**: 26 capabilities and 3 purposes on every closed
   policy surface; client-usable names ChatLLM `DATA_CONDITIONAL` (data profile
   `chatllm-data-v12`), operator-only approvals `CONTROL_PLANE_EXCLUDED` and attested-local.

## Supersession of ADR-016 (only these points)

| ADR-016 | Superseded by |
|---|---|
| Decision 1 ("no schedule row links to … any other native record") | decision 3 here: lineage associations only |
| Decision 4 (import only by the attested operator) | decision 4 here adds the worker-performed second admission that inherits the attested import; import remains operator-only |
| Decision 7 ("changes are derived, never stored") | kept for the delta; decisions 1, 2 and 4 here persist scenario, CPM, output and match data |
| Decision 8 (role is an input with `update`, `baseline` with a kind, or `reference`; nothing derives a baseline or a previous publication) | decisions 5 and 6 here: baselines are approved objects, `reference` is retired, the kinds are `contract` and `approved_update`, a derived current standard update exists; nothing derives a baseline |
| Out of scope: cross-domain links | decision 3 here |

Every other ADR-016 decision stands: immutable publications, one profile and engine, generic
extraction unchanged, contained parser, exact-ID identity, switch default off; and baselines
are still never derived (they are now operator-approved objects).

## Out of scope

Production use; server Monte Carlo; resources, correlation and risk events; a Program-level
critical path (it stays unproven); certified Program totals from schedule data (OD-08);
XER/XML; frontend UI.

## Consequences

- The plane can ship dark; turning it on is a sequence of operator gates.
- Client claims stay labelled; only operator-approved baselines are authoritative, and only
  for scenario derivation and baseline comparison.
- A scratch database holding S5 `baseline` or `reference` publications must be rebuilt before
  the restating revision applies; production holds none.
- **Change to the merged S5 import:** `reference` and kind `working` are refused whatever the
  switches; a role-`baseline` import needs the approval fields and is refused while the plane is
  not effective, so with only `MY_PA_SCHEDULE_ENABLED` on, the import admits role `update` only.
- Baseline and governing events form per-Project ordered chains written under a Project lock;
  as-of answers are "as recorded", never by `effective_from`.
- Revoking a baseline is final for its publication; recovery means approving a different
  publication. The effective baseline type is the one recorded at approval.
- A matched auto import is parsed twice; a CPM run is computed synchronously within bounds,
  or moved to a worker plane if the measured time misses its target.

## Supersession

A superseding ADR is required to make any scenario, CPM or client output authoritative or
reportable, to let a client approve a baseline or set the governing one, to compute CPM over
a publication, to sample on the server, or to turn the plane on by default.

## Implementation status

S6-1 (the pure domain and the CPM engine, contract section 9.1) is implemented on the branch
`feat/schedule-scenarios-engine` and not merged (contract section 9.1.1 records what was
executed). S6-2 (persistence) and S6-3 (capabilities) are not implemented. Nothing is
deployed, migrated or granted, and no switch exists yet.
