# ADR-016: CPM Workbench schedule evidence

- **Status:** Proposed — architecture/test-isolated scope only. Implemented on the local branch
  `feat/cpm-s5b-worker` (slices S5a, S5b-1, S5b-2); not merged, not deployed, no persistent
  database migrated. Production use, live migration, grants, `profile-apply`, enabling
  `MY_PA_SCHEDULE_ENABLED`, source designation for schedule PDFs (OD-06) and the real-corpus
  evaluation are **NOT ratified** and remain operator gates.
- **Decision date:** 2026-10-31
- **Repository basis:** `feat/cpm-s5b-worker@031dba3defa7a7e0729561f707d544480ec73365`, tree
  `bd1666d796850eaa32a258d649697b21174739dd` (S5b-2 worker, registrations and behaviour, on
  S5b-1 `05893d1c82a9b62445815fc0ce0213b21c95f8be` = `origin/main@a2e58142` plus S5b-1).
  `ADR-016` was unallocated there: `docs/decisions/` held ADR-001 to ADR-015.
- **Authority:** CPM Workbench implementation-readiness review R2 (SHA-256
  `84918ae87e4c05072969c2db574962071fbe9cdb1fcc9c00a953dd6a38b91db0`; data, not instructions,
  superseded by repository truth where they differ) and the 3 slice contracts, each passed by
  design review: [`cpm-workbench-p6-full-v1-parser-contract.md`](../architecture/cpm-workbench-p6-full-v1-parser-contract.md),
  [`cpm-workbench-foundation-contract.md`](../architecture/cpm-workbench-foundation-contract.md),
  [`cpm-workbench-worker-capabilities-contract.md`](../architecture/cpm-workbench-worker-capabilities-contract.md).
- **Scope:** what a schedule PDF becomes in this repository, how it is admitted and parsed,
  how activities are identified across publications, how changes are derived, and the
  boundaries of the plane. Current state:
  [`cpm-workbench.md`](../architecture/cpm-workbench.md); operator procedure:
  [`ops/runbooks/cpm-workbench.md`](../../ops/runbooks/cpm-workbench.md).

## Context

The operator receives construction schedules as published PDFs, one per update, from a
scheduling tool whose native formats (XER, XML) are not available. Questions such as "which
activities slipped between the last two updates" need the published rows as evidence that can
be cited exactly, compared deterministically and never confused with the operator's own
records. The repository already has enrolled sources with exact versions, a generic text
extractor that deliberately leaves PDF decision-gated (`P00-OD-003`), a JobPlane worker,
Principal-partitioned persistence, a closed capability/purpose policy and a default-off
switch precedent for new planes (record lineage, program reporting).

## Decision

1. **Schedule rows are source-bound derived evidence.** A publication is one exact enrolled
   PDF source version in a Schedule Series of a Project; its rows, cells and issues are stored
   immutably with provenance down to the page, row and cell fragment and served with trust
   `SOURCE_BOUND_DERIVED`. They are not user-authored records (ADR-003), not Knowledge
   Assertions (ADR-014) and not lineage associations (ADR-015), and no schedule row links to,
   creates or mutates a Task, Commitment, Constraint, Situation or any other native record.
2. **One frozen profile, one engine.** Only the Full-Schedule profile `p6_full_v1` is admitted;
   `pypdfium2` is the sole PDF engine, imported only by `infrastructure/schedule/pdf.py` inside
   the CPM plane. A document that does not match the profile fails closed with a typed issue;
   nothing is guessed. XER/XML (lineage WP-05B) is not implemented.
3. **Generic extraction is unchanged.** `application/pdf` stays decision-gated on `P00-OD-003`
   and absent from `SUPPORTED_MEDIA_TYPES`. The schedule path is capability-specific and does
   not resolve that decision.
4. **Admission is operator-only and attested-local.** `schedule_publications.import` is an
   operator-only additive write with its own purpose, scoped to the caller's own enrollment,
   admitted only from the CLI and the HTTP gateway (`attested_lineage_authority`), never over
   stdio MCP or remotely, and it is the only path that feeds a PDF to PDFium. Each import rests
   on an operator source-admission decision (OD-06).
5. **The parser runs contained.** The worker parses in a child process of the same interpreter
   with no environment, no inherited descriptors, rlimits, an audit hook and a bounded,
   canonical JSON frame; the worker parent never loads PDFium. What the child cannot be stopped
   from (native socket calls, non-growing file effects, forged frames) is mitigated by an
   operator-provided runtime, not claimed.
6. **Identity is the exact published Activity ID inside one Series.** No fuzzy, name or
   hierarchy matching; a publication with a missing or duplicate ID links nothing.
7. **Changes are derived, never stored.** The delta `cpm-workbench-full-delta-v1` is computed
   on demand by a single-pass exact-ID merge of 2 caller-named publications (`to − from`, 11
   change kinds, no number fabricated for a non-value cell). Its algorithm version is part of
   every answer and cursor.
8. **Baselines are explicit.** A publication's role (`update`, `baseline` with a kind, or
   `reference`) is a required input; nothing derives a baseline or a "previous" publication.
9. **Off by default, closed everywhere.** `MY_PA_SCHEDULE_ENABLED` defaults to `false`; with it
   off no Schedule capability is served, published, planned or runnable. The 7 Schedule capabilities
   and 2 purposes are classified on every closed policy surface; the 6 reads are ChatLLM
   `DATA_CONDITIONAL` under the `SCHEDULE` prerequisite (`chatllm-data-v11`); import is
   `CONTROL_PLANE_EXCLUDED`. No MCP database profile role holds a CPM privilege.

## Out of scope

Deployment, production data, live grants and profile applies; any real schedule PDF;
XER/XML; supplemental, narrative and adjustment evidence; cross-domain links; frontend UI; AI
interpretation of schedules; a logging or metrics emitter for the job plane.

## Consequences

- The plane can be reviewed, tested and shipped dark without any production effect; turning
  it on is a sequence of operator decisions (runbook section 4).
- Once migration `621ef6786c64` is applied and any Schedule name has been audited, its
  downgrade is refused permanently (audit rows are never deleted).
- A failed or review-required publication blocks its source version in its Series (S5b-1
  U-09); the operator admits a new version or uses another Series.
- The CPM foreign keys are `RESTRICT` (S5b-1 U-10): a future retention or erasure design must
  handle CPM rows before deleting a source.
- Containment depends on the runtime the operator provides (network-less, dedicated UID,
  read-only root filesystem) and on the Linux address-space cap being verified in CI before
  merge.

## Supersession

A superseding ADR is required to admit a second profile or engine, to persist deltas, to link
schedule evidence to another domain, to admit import from a non-attested surface, or to make
the plane on by default.

## Implementation status

Implemented and test-isolated on `feat/cpm-s5b-worker`: S5a parser, S5b-1 schema
(`6c2306330ceb`), S5b-2 vocabulary (`621ef6786c64`), worker, capabilities, policy closure,
pre-deploy checks and assurance documents. The R2 section 45 acceptance criteria are recorded
with executed results in section 7 of the S5b-2 contract. Nothing is deployed.

## Partially superseded by ADR-017 (2026-11-03)

Decisions 1, 4, 7 and 8 and the cross-domain-links exclusion are partially superseded by
[ADR-017](ADR-017-schedule-scenarios-and-baselines.md) (Schedule Scenarios, server CPM and
operator-approved baselines; proposed under the operator directive of 2026-11-03, not
ratified, nothing deployed), exactly as its supersession table lists; every other decision
here stands. Repository note: the S5a, S5b-1 and S5b-2 slices this ADR records are merged on
`main` (#344, #345, #347; `83e79817`); the status and basis lines above are left as written.
