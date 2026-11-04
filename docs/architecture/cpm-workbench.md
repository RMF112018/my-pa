# CPM Workbench — current state

**Status:** current-state description of the CPM Workbench schedule-evidence plane on the
local branch `feat/cpm-s5b-worker` (slices S5a, S5b-1 and S5b-2 of CPM Workbench R2
work packages WP-00 to WP-04). Nothing described here is merged to `main`, deployed, or
applied to any persistent database. The plane is **off by default** and no real schedule
PDF exists anywhere in the repository. The decision record is
[`ADR-016`](../decisions/ADR-016-cpm-workbench-schedule-evidence.md); the operator
procedure, pre-deploy gates and residuals are in
[`ops/runbooks/cpm-workbench.md`](../../ops/runbooks/cpm-workbench.md).

The three implementation contracts control the detail and are not repeated here:

| Slice | Contract | What it built |
|---|---|---|
| S5a (WP-00 + WP-02) | [`cpm-workbench-p6-full-v1-parser-contract.md`](cpm-workbench-p6-full-v1-parser-contract.md) | the frozen `p6_full_v1` profile, synthetic PDF fixtures and goldens, the deterministic PDFium text-object parser (`src/my_pa/domain/schedule`, `src/my_pa/infrastructure/schedule`) |
| S5b-1 (WP-01) | [`cpm-workbench-foundation-contract.md`](cpm-workbench-foundation-contract.md) | revision `6c2306330ceb`: 7 Principal-partitioned `knowledge.schedule_*` tables, triggers F1–F9, `ScheduleUnitOfWork`/`SqlScheduleRepository`, the `SCHEDULE_JOBS` plane constant |
| S5b-2 (WP-03 + WP-04) | [`cpm-workbench-worker-capabilities-contract.md`](cpm-workbench-worker-capabilities-contract.md) | revision `621ef6786c64`, the `schedule` worker plane and contained parser child, 7 Schedule capabilities, policy closure, ChatLLM `chatllm-data-v11`, the default-off switch, pre-deploy checks, this assurance set |

Successor work: the Schedule Scenarios slices S6-1 to S6-3 are
specified in [`schedule-scenarios-contract.md`](schedule-scenarios-contract.md) under
[`ADR-017`](../decisions/ADR-017-schedule-scenarios-and-baselines.md). S6-1 (the pure domain
and engine) is implemented and merged (#348); S6-2 (contract section 14) is implemented on
the branch `feat/schedule-scenarios-persistence` and not merged; S6-3 is not implemented;
nothing is deployed. This document describes the merged S5 behaviour and changes when they
land. **S6-2 change (implemented on that branch, not merged):** the `reference` role and kind
`working` are retired, every role-`baseline` import is refused
`invalid_request(PUBLICATION_ROLE)` until S6-3 adds the approval fields, and
`schedule_publications.list` refuses the filter `publication_role=reference` (contract section
12.2, S6-2-D04). Revision `2a90f91dd786` adds the 11 plane tables; the S5 admission writes an
import-time approval under the Project lock and admits an automatic import into its own intake
Series (both reachable only from tests until S6-3), and the worker's H8 and fail paths run the
series-match hook in the same transaction with the effective-plane bit off (sections 14.8.5 to
14.8.7). The revision-A pre-deploy checks Q0-Q9 and the operator procedure are section 8 of
[`ops/runbooks/cpm-workbench.md`](../../ops/runbooks/cpm-workbench.md).

## 1. What it is

A Schedule Series is a named sequence of published construction schedules for one Project.
A **publication** is one exact, enrolled PDF source version admitted into a Series with an
explicit role (`update`, `baseline` with kind `working`/`contract`, or `reference`). The
worker parses the PDF under the single admitted Full-Schedule profile `p6_full_v1` and
stores every row with its cell evidence and provenance. Activities are linked across a
Series' publications only by their exact published Activity ID (a **Stable Activity**).
Changes between 2 publications are computed on demand, never stored.

Everything stored is **source-bound derived** evidence (`TrustLevel.SOURCE_BOUND_DERIVED`):
it says what one exact PDF version published, traced to the Principal, Project, Series,
enrollment, source object, source version, document SHA-256, job attempt, parser and
profile, page, row and cell. It is not a canonical Task, Commitment, Constraint or
Knowledge Assertion, and nothing links it to them.

## 2. Data flow

```text
operator (CLI or HTTP gateway only)
  └─ schedule_publications.import ──► authorize (operator-only, purpose schedule_import,
        scope = the caller's own enrollment's source) ─► audit ─► admit_publication
        (one transaction: idempotency, ownership, enrollment, object, version, PDF media
        type, size ≤ 16 MiB, Series resolve-or-create, supersession) ─► 1 schedule_jobs row
worker  apps/worker.py run --plane schedule   (switch on, lease ≥ 300 s)
  └─ process_schedule_publication: plan (lease-checked) ─► provider metadata + fetch on an
        AUTOCOMMIT connection, version re-pinned ─► pin document digest ─► parse in a
        contained child (stdin bytes, stdout one canonical frame) ─► parser run, rows and
        issues in batches of ≤ 1,000 ─► canonicalize Stable Activities ─► finalize
reads (6 scopeless capabilities, purpose schedule_read)
  └─ series / publications / publication detail / activities / activity history /
     changes (delta cpm-workbench-full-delta-v1), keyset cursors, disclosure
```

Every worker transaction is short and begins with the lease check; the source read and the
parse hold no database transaction. The handler's budget is 240 s inside a lease of at least
300 s.

## 3. Components

| Component | Path | Role |
|---|---|---|
| Parser (S5a) | `src/my_pa/domain/schedule`, `src/my_pa/infrastructure/schedule` | pure profile algorithm; `infrastructure/schedule/pdf.py` is the only CPM module that imports `pypdfium2` |
| Canonical form | `src/my_pa/domain/schedule/canonical.py` | canonical JSON of a parse result, its SHA-256, and `parse_result_from_object` (the parent's strict decoder of the child's frame) |
| Schema (S5b-1) | `migrations/versions/20261027_6c2306330ceb_cpm_workbench_foundation.py` | 7 tables; F1–F9 guards (set-once, append-only, terminal immutability, finalization verification) |
| Vocabulary (S5b-2) | `migrations/versions/20261028_621ef6786c64_cpm_workbench_vocabulary.py` | admits the 7 capability names, 2 purposes and the `schedule` heartbeat plane; grant-free; downgrade refused once the vocabulary is used |
| Repository | `src/my_pa/infrastructure/persistence/schedule.py` | every write and read, Principal-partitioned through `_mine`/`principal_scoped` |
| Worker handler | `src/my_pa/infrastructure/jobs/schedule.py` | phases H1–H8, failure classification (deterministic terminal vs transient retry vs lost lease) |
| Contained parse | `src/my_pa/infrastructure/jobs/schedule_parser_process.py`, `schedule_parser_child.py` | `subprocess` child of the same interpreter with `-I -B`, empty environment, rlimits, audit hook; the parent never imports PDFium |
| Read service | `src/my_pa/application/schedules.py` | 7 capability behaviours, disclosure, cursor binding |
| Delta | `src/my_pa/domain/schedule/compare.py` | single-pass exact-ID merge, 11 change kinds, `to − from` |
| Cursor | `src/my_pa/domain/schedule/cursor.py` | 512-character, 300 s, request-bound keyset cursor |
| Pre-deploy checks | `src/my_pa/infrastructure/database/cpm_workbench_predeploy.py`, `ops/postgres/cpm_workbench_predeploy_check.py` | read-only catalog checks P0–P8 (runbook section 3) |

## 4. Capabilities

| Capability | Kind | Purpose | Scope | ChatLLM `chatllm-data-v11` | Remote |
|---|---|---|---|---|---|
| `schedule_publications.import` | write, additive, operator-only | `schedule_import` | the caller's own enrollment's source | `CONTROL_PLANE_EXCLUDED` | never published; the handler also refuses any remote composition |
| `schedule_series.list` | read | `schedule_read` | scopeless | `DATA_CONDITIONAL` under prerequisite `SCHEDULE` | only with the switch on, the factory composed and a grant |
| `schedule_publications.list` | read | `schedule_read` | scopeless | same | same |
| `schedule_publications.read` | read | `schedule_read` | scopeless | same | same |
| `schedule_activities.list` | read | `schedule_read` | scopeless | same | same |
| `schedule_activities.history` | read | `schedule_read` | scopeless | same | same |
| `schedule_changes.list` | read | `schedule_read` | scopeless | same | same |

The repository defines 240 capabilities and 62 purposes. All 7 Schedule names travel the
generic adapters (normalization `_BUILDERS`, `ApplicationService._HANDLERS`, the derived MCP
`TOOLS` and the HTTP/CLI transports); there is no schedule-specific route, MCP server or CLI
program. Import is **attested-local only**: `attested_lineage_authority` admits the CLI and
the HTTP gateway and denies stdio MCP and every unattested local caller (contract E-12).

ChatLLM targets at `chatllm-data-v11`: 164 names for the full plane set and 98 for the
default set (both unchanged from v10 because the switch is off); 170 with the schedule plane;
204 with lineage, program reporting and schedule; 136 for the default set with all 3.

## 5. Read rules

- **Visibility (S5b-1 U-03).** A Stable Activity is visible only through a row of the
  accepted parser run of a `complete` or `partial` publication; an orphan created by a batch
  whose publication never finalized answers `not_found` exactly like an absent or foreign
  one. `schedule_activities.created_at` is never returned or presented as first-seen.
- **Issue counts (RR1-I01).** For a `complete`, `partial` or `review_required` publication
  only the accepted run's issues are counted; a `failed` one counts every issue.
- **Effective status.** A publication whose job is dead-lettered or abandoned at its last
  attempt reads as `failed`; no read writes.
- **Baselines (R2 section 30).** The role is a required field with no default; the series
  list's latest update considers role `update` only; the caller always names both
  publications of a comparison.
- **Delta.** `cpm-workbench-full-delta-v1`: matched by exact published Activity ID inside
  one Series, `reintroduced` replaces `added` when the activity was observed before the
  first publication, numeric deltas only when both cells are published values, a
  marker-only change on an equal date is not a change (U2-07).
- **Pages and cursors.** Page size 1–100 (default 25); a cursor carries a position, never
  authority, and every page is re-authorized and re-partitioned.
- **Disclosure.** Every answer states scope, coverage of the referenced publications only,
  freshness, trust `SOURCE_BOUND_DERIVED` with its parser/profile (and delta) basis, source
  references, truncation and classification `PRIVATE_LOCAL`.

No payload carries a filename, locator, path, raw PDF or page text, raw cell fragment,
exception text or stack trace.

## 6. The switch and the plane

`MY_PA_SCHEDULE_ENABLED` (`Settings.schedule_enabled`, default `false`) gates the Schedule
unit-of-work factory, all 7 Schedule capabilities (absent from `capabilities.get`, readiness, the MCP
tool list, remote profiles, the façade and ChatLLM composition; each handler answers
`unsupported` first), and the `schedule` worker plane (`apps/worker.py run --plane schedule`
exits 2 with `plane schedule disabled` before building an engine). A restricted MCP-profile
composition never composes the factory: no profile role holds a CPM privilege. With the
switch off, `capabilities.get` reports the same 2 worker planes as before S5b-2.

The `schedule` plane is admitted on all 4 surfaces together: the worker program's plane map,
the heartbeat CHECK `worker_plane_is_known`, `worker_health.py`, and the unit-of-work and
service fallback (the last two only when the switch is on).

## 7. Containment of the PDF parser

The parent passes the admitted bytes on the child's stdin and reads one frame
(`CPMWB-PARSE-1`, schema `cpm-workbench-parse-frame-v1`) from its stdout, capped at
134,217,728 bytes. The child runs with an empty environment, `cwd` `/`, no inherited
descriptor but 0/1/2, `stderr` discarded, its own session, and `RLIMIT_CORE = 0`,
`RLIMIT_FSIZE = 0`, `RLIMIT_NOFILE = 32`, `RLIMIT_CPU` from the wall, and on Linux
`RLIMIT_AS = RLIMIT_DATA = 1 GiB` (provisional, residual U2-12). An audit hook refuses
Python-level sockets, process spawn, exec, `ctypes.dlopen` and file writes. The parent kills
the process group at wall + 2 s and always reaps it. The frame is JSON (never `pickle`) and
is re-rendered to its canonical bytes and bound to the digest and size of the bytes sent.

**Not enforced** (residuals U2-01, U2-10): native code issuing raw socket system calls,
native file-system effects that do not grow a file, and a compromised child returning a
well-formed frame of fabricated rows for the right digest. The mitigations are operator-level
(runbook section 4): a network-less runtime under a dedicated UID with a read-only root
filesystem and no write access to any source root.

## 8. Boundaries

- Generic text extraction is unchanged: `application/pdf` stays decision-gated on
  `P00-OD-003` in `capabilities.get` and absent from `SUPPORTED_MEDIA_TYPES`; the schedule
  path is a separate capability-specific one (R2 section 8.4).
- Only `p6_full_v1` Full-Schedule PDFs. XER and XML (lineage WP-05B) are **not
  implemented**; supplemental, narrative and adjustment evidence (R2 sections 26–28),
  cross-domain links (R2 section 33), frontend UI and AI are out of scope.
- No logging or metrics emitter exists in the job plane (contract E-05). Observable,
  content-free: publication status and counts, issue counts by code, job state, attempts and
  `last_error_code` (one of the 11 public codes), the plane's backlog, dead-letter count and
  heartbeat, and the worker's per-run counts.
- No grant, `profile-apply`, OAuth change, source designation or deployment is part of this
  plane's code; each is an operator gate (runbook section 4).

## 9. Measured

On the implementation host (macOS, Homebrew PostgreSQL 15 scratch cluster, synthetic data):
a 25,000-row A→B delta in 0.709 s against a 5 s target, and a 25,000-row import plus
persistence in 18.6 s (worker I7-C). The bounds-maximal synthetic (250 pages, 23,250 rows)
parsed `complete` in the contained child with a peak RSS of 440 MiB on macOS, where no
address-space cap applies — an observation, not the Linux `VmPeak` the 2× rule needs. The
Linux-only address-space tests of the parser child (7 nodes, both the 86-page golden and the
bounds-maximal case) are **CI-only, not executed on the implementation host** (runbook gate 6).
A 2,610-byte text-flood page drives PDFium to an early call boundary, then one long native call past the whole parse wall, so the child is ended from outside (or stops itself at the early boundary on a slow host) and the publication fails `processing_budget_exceeded` (residual U2-13).
`tests/ci_shard_weights.json` is macOS-derived and is to be re-weighed from the first ubuntu CI
JUnit (U2-14).

## 10. Residuals

The contract's section 8.2 lists every residual with its owner; the runbook section 6 states
the operator-facing ones (S5b-1 U-06, U-09, U-10; S5b-2 U2-01 to U2-12; S5a U-01) and the
acceptance-criteria table in contract section 7 records which R2 section 45 criteria are met
by executed tests, which are operator-gated and which are CI-only.
