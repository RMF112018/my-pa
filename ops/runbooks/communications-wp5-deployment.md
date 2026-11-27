# WP5 meeting-context deployment

**UNEXECUTED / OPERATOR-GATED.** This is the repository-owned part of the R-OP-7 consolidated
communications activation. Preparation stops at the approval handoff. Planned production
steps below begin only after the operator approves the exact release and target.

WP4 communications reads merged in #388 and WP4P project-report reads merged in #390.
WP5 merged in [#397](https://github.com/RMF112018/my-pa/pull/397) at commit
`8f7c7a3aa63478a955e13197d8c3bab8edc3e05b` (tree
`8ebc98dc9f6b20855e8aea2d7289acf92a63773d`). Use the authenticated `origin/main` release
commit and tree that contain that merge. The release may have a later single Alembic head.
Resolve it from that exact source and image.

Follow the [NAS lifecycle runbook](nas-lifecycle.md), [NAS runtime operations](../nas/README.md)
and [PostgreSQL operations](postgres-operations.md) for target admission, package transfer,
backups, migration, service control and recovery. Use the production procedure applicable to
the approved runtime mode. The smoke upgrade workflow does not authorize pilot or production
activation. This procedure sequences the WP5 work within the [consolidated activation](../../docs/architecture/communications-intelligence-contract.md#206-consolidated-activation-goal-acceptance-manager-ruling-r-op-7).

## Preparation and approval

Rehearse on the reviewed release candidate using disposable PostgreSQL and synthetic data.
Record the applicable CI and independent review results. Rehearsal covers the forward migration,
the off/on communications switch, operator-purpose and non-operator refusals, restricted MCP
role withholding, PULSE off and on, and the counts-only CLI with both timing shapes. Include a
wrong database or head refusal and a fixture with recognizable synthetic content that must be
absent from CLI output. Use the [WP5 acceptance evidence](../../docs/architecture/communications-intelligence-contract.md#205-wp5)
to select the corresponding schema, contract, and PostgreSQL tests.

Give the operator the following release inputs. Verify them through the canonical procedures
at their action boundaries, with live reads limited to the separately approved scope.

| Input | Required record |
| --- | --- |
| Release | Repository, authenticated `origin/main` commit and tree containing the WP5 merge, reviewed package and immutable image identities, applicable CI and exact-head review |
| Target | Exact production host, admitted runtime mode and identity, canonical Compose project and affected services, PostgreSQL instance and physical database name |
| Migration | Starting Alembic revision, image's single expected final revision, approved migration and writer-quiescence window, and approved authority for the target |
| Recovery | Verified pre-migration backup receipt, permitted recovery owner and procedure, previous admitted image and configuration identities, and the safe service and switch state to restore |
| Activation | Exact operator Principal and connected client/profile, eligible data and destination, intended switch and grant changes, and whether optional PULSE reads are approved |
| Verification | Approved scope for any production-data reads, the operator executing the counts-only probes, the protected evidence destination, and the observation window |

Stop at the handoff until approvals cover the exact actions. Keep credentials, connection URLs,
environment values, source identifiers and corpus content out of the release record. Approval
for package deployment alone does not grant production database access, live data reads,
privilege changes, service interruption or recovery authority. Stop on missing authority or an
identity mismatch at any later step.

## Approved release sequence

1. **Migrate before serving the new capability.** Keep read activation off and follow the
   canonical backup, writer quiescence and migration gates. Verify the physical database and
   starting revision against the release record. The path includes WP4 `fa18ef3d9bc0`, WP4P
   `3b3373d8268e` and WP5 `859e93b47a21` where pending. WP5 changes the audit capability
   vocabulary and takes `ACCESS EXCLUSIVE` on `knowledge.audit_events` under a 10 s lock timeout.
   A lock timeout stops activation. After the approved migration, verify the connected database
   at the image's approved single head. Follow the canonical lifecycle procedure to verify that
   the exact admitted WP5-containing image is running and ready with both read switches off.
   Complete these checks before rederivation or switch activation.
2. **Complete the WP4 prerequisite.** When stored text or identifier rows need v2 rederivation,
   follow [communications ingestion sections 12.1–12.3](communications-ingestion.md#121-rederive).
   Start with the dry run, then apply only the authorized bounded batches and inspect the closed
   counts. Resolve a refusal, incomplete run or stalled due set before enabling reads. Observe
   the product-owned derivation and original-source read-only boundaries.
3. **Enable and verify the approved read switches.** Apply `MY_PA_COMMUNICATIONS_ENABLED=true`
   through the approved gateway/MCP composition and verify `meetings.context.read` in the
   eligible runtime catalog. WP5 uses that shared switch and has no separate switch. A restricted
   MCP database role composition must continue to withhold the communications capability.
   For optional PULSE, follow the [WP4P activation checklist](project-reports-ingestion.md#124-activation-checklist).
   Complete its eligibility and ingestion prerequisites and enable and verify
   `MY_PA_PROJECT_REPORTS_ENABLED` on the gateway and remote MCP before its grants/profile step.
   If optional PULSE reads remain off, expect `pulse.state=unavailable` with `reads_disabled`
   and confirm communications context still works.
4. **Apply the approved operator grants and reconcile the profile.** The reviewed WP5 policy
   version is `chatllm-data-v21`. For a later release, use the policy version configured in its
   exact admitted image and renew the plan, data eligibility and drift review for that release.
   The CLI refuses a version that differs from its configured policy. Preview `profile-diff`
   and `profile-plan` with the approved plane switches reflected in the CLI environment. The
   WP5 addition is `meetings.context.read` with the sole purpose `communications_read`, granted
   to the operator profile only. Check the entire plan
   for unexpected additions, removals or client, Principal, scope or purpose drift, including the
   WP4 and optional WP4P grants. The operator applies only the reviewed plan through the
   [profile procedure](managed-knowledge-context.md#activation-sequence). Reconnect the approved
   client and verify the effective catalog. Defer schedulers and calendar reconciliation to the
   consolidated activation procedure.
5. **Verify and observe.** Use the approved runtime status and readiness checks and record the
   observed image, database revision, capability state, grant/profile diff and sanitized
   results. Confirm the authorization and restricted-role behavior from synthetic rehearsal.
   Real smoke reads require approval for that client, data and destination. Record closed codes
   only. Complete the observation window before handing the release back to the operator.

## Counts-only measurement after approval

Run from the approved code and database context. Obtain `APPROVED_DATABASE` and
`APPROVED_ALEMBIC_HEAD` from the verified release record. Before each invocation, reverify the
approved PostgreSQL instance and connection route, and the fixed local operator Principal used
by the CLI. The CLI independently checks the configured and connected database name and a single
matching Alembic revision. Each probe exercises PULSE
reads even when the service switch is off, so require approval for the underlying PULSE probe
access as well as communications. Run one invocation at a time within the approved operating
window. Proceed to the second only if the first succeeds and its output is safe to retain.

```sh
PYTHONPATH=src python apps/cli/communications_ingest.py \
  --expected-database "$APPROVED_DATABASE" \
  --expected-alembic-head "$APPROVED_ALEMBIC_HEAD" \
  measure-context --meetings 10 --runs 40 --lookback-days 14 --per-meeting-limit 15
```

```sh
PYTHONPATH=src python apps/cli/communications_ingest.py \
  --expected-database "$APPROVED_DATABASE" \
  --expected-alembic-head "$APPROVED_ALEMBIC_HEAD" \
  measure-context --meetings 10 --runs 40 --lookback-days 90 --per-meeting-limit 50
```

Each invocation is read-only, uses in-memory probes, and takes no advisory lock. It measures
one and ten Meetings with PULSE reads both off and on inside the probe. The service switch
stays at its approved setting. Keep only the approved aggregate counts, closed codes and timings.
The CLI bounds statements at 60 seconds. Stop on a nonzero exit, target mismatch, timeout,
operating-window expiry, unexpected output shape, or any corpus value in the output.
Withhold any affected output and investigate before retrying. The
[measurement reference](communications-ingestion.md#133-measure-context-counts-only) defines
the statements and counters, including the Meeting input reads excluded from this probe.

The WP5-S6 baseline used 20 runs on a disposable C-locale cluster with synthetic seed data. For
ten Meetings at default bounds the result was **371.3 ms p50 / 381.9 ms p95**
with PULSE off and **463.6 ms p50 / 473.2 ms p95** with PULSE on. Both p95 figures meet the
750 ms target. Both medians exceed the 300 ms target. D15 also targets p95 at or below 300 ms
for one Meeting at defaults and 2,000 ms for ten Meetings at maximum bounds. Record the
production figures and report misses for operator disposition. Preserve matching, coverage,
tiers and limits. These targets do not replace release safety and correctness gates.

## Containment and recovery

Pause the affected activation on migration refusal, readiness or identity drift, unexpected
grants or capability exposure, evidence leakage, or a functional regression. For a PULSE-only
issue, use the approved WP4P disable procedure and verify communications context still works.
For WP5 exposure or a communications issue, use the approved communications switch-off
procedure and verify `meetings.context.read` is withheld and answers `unsupported`. This also
withdraws all three WP4 communications reads. Coordinate that blast radius with the operator.
Disablement leaves grants in place. Use the separately authorized, targeted grant/profile
recovery and verify the effective catalog after reconnecting the client.

Restore a previous admitted image or configuration only through the canonical release procedure
and only after it proves compatibility with the current schema. Retain the migrated schema and
audit history while containing the runtime. Do not use canonical database downgrade or
overwrite as a deployment rollback. WP5 explicitly refuses downgrade once any audit event
names `meetings.context.read`. Refer a data recovery need to the operator under the authorized
backup/restore procedure and report the safe retained state.

## Collector handoff

The external calendar collector owner owns the [meeting-context readiness checklist](../../docs/architecture/meeting-sync-v1-contract.md#87-meeting-context-readiness).
The repository release hands over that checklist and consumes the authorized publications
through the existing read-only boundary. External collector changes, publishing and source writes
need their own approval and execution owner. Outlook-synced Meetings currently
carry no applied attendees, even though the producer sends a validated attendee set. Their
context reports `no_attendee_address` and uses identifiers, the Project number and title terms.
