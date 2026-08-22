# Operator CLI

Five programs, five planes. They share this directory because
`docs/architecture/module-boundaries.md` section 5.10 puts operator commands
here, and they share nothing else — no options, no runtime, no output shape.
A migration phase is not a capability, and neither is registering a source or
asking whether the database can serve one.

`tests/contract/test_cli_transport.py` holds the four option surfaces disjoint,
and `tests/architecture/test_operator_commands_are_not_capabilities.py` holds
`sources.py` and `health.py` mechanically outside the capability path.

## `invoke.py` — one public capability

```text
python apps/cli/invoke.py <capability> \
    [--request-id ID] [--purpose PURPOSE] [--principal-id ID] \
    [--requested-at TIME] [--contract-version V] \
    [--scope-source-id ID]... [--scope-enrollment-id ID]... \
    [--payload JSON]
```

The envelope is options and the capability's own fields are one JSON object.
The answer is the response envelope on standard output, one line, always;
standard error stays empty. Exit `0` when the envelope carries a result and `1`
when it carries an error.

**It is not a privileged bypass.** It composes the same runtime the gateway
composes, is handed the same principal, goes through the same authorization
path, and offers no option that could change any of that. `--principal-id` is
correlation input the application does not trust, exactly as it is over HTTP.
[`ops/runbooks/mcp-and-cli-operations.md`](/ops/runbooks/mcp-and-cli-operations.md)
covers running it.

## `gsqs_b0.py` — governed GSQS live-B0 control plane

Preflight never discloses. The RouteLLM incumbent transport is bound, but
execute still requires a later exact-head review and a fresh
`EXECUTE_MEASURED_B0` authorization. Missing env/config/evidence dir keeps
the unbound refuse path. `MEASURED_B0` remains `NOT_YET_ESTABLISHED`.

```text
python apps/cli/gsqs_b0.py preflight
python apps/cli/gsqs_b0.py execute \
  --authorization <artifact> \
  --model-identity routellm-goodnotes-b0-v1@sha256:<digest> \
  --prompt-config ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt \
  --repetitions 3 \
  --evidence-dir <run-dir> \
  --evaluator-corpus <local-private-evaluator-plane.json>
```

See [`ops/goodnotes/gsqs/B0_RUNBOOK.md`](../../ops/goodnotes/gsqs/B0_RUNBOOK.md).
Do not run execute as part of ordinary development.

## `goodnotes.py` — operator reconciliation trigger

```text
MY_PA_AUTH_MODE=local_operator \
MY_PA_GOODNOTES_ROOT=/operator/admitted/root \
MY_PA_GOODNOTES_OCR_ROOT=/operator/admitted/ocr-root \
MY_PA_GOODNOTES_OCR_EXECUTABLE=/absolute/local/ocr \
python apps/cli/goodnotes.py reconcile --idempotency-key <bounded-key>
```

In `local_operator` mode the Principal is derived from the same durable local
binding as the gateway and any different `--principal-id` is refused. In
`entra` mode `--principal-id` is required to bind the owning partition. The
exact source root, OCR root, and absolute OCR executable are explicit operator
settings. Every launch resolves the executable inside the OCR root and refuses
an escaping symlink.
Reconciliation reads the manifest twice through its page generator: once to
compute the bounded immutable
fingerprint and check a short receipt transaction, then once for bounded OCR and
the disabled-by-default proposal gate. No database connection is held during OCR
or model work; the write transaction starts only after both finish. Review and
accepted-content search deliberately remain on the ordinary `review.list`,
`review.decide`, and `knowledge.search` capability surfaces exposed by
`invoke.py`; this operational trigger does not create a parallel workflow.

## `sources.py` — the source configuration plane

`sources.py` configures a root as a source and observes it, which is the
bootstrap `sources.enroll` needs: an enrollment names a `src_…` and a root
`obj_…`, and until this existed nothing in the product issued either.

```text
python apps/cli/sources.py register \
    --provider fixture --root <path> \
    --label "MCV fixture corpus" --classification private_local
python apps/cli/sources.py list
```

`register` prints the `source_id` and the `root_object_id` an enrollment then
names, and `list` prints one line per configured source. **Neither prints the
root.** Every option is required — nothing is inferred — and the target database
comes from `MY_PA_DATABASE_URL`. Exit `0` on success, `1` on a refusal that names
the defect and never the value.

**It creates configuration, not a grant.** Registering a source authorizes
nobody to read anything: every read still requires an enrollment, which requires
the operator-only `sources.enroll`, which is authorized and audited. This program
builds no application service and no principal, and it writes no audit event —
`audit_events.capability` is closed to the sixty-five capabilities, and a further
member for source registration is exactly what an operator command must not
become. (It read "the eight" before WP-6; WP-6 through WP-9 moved the count,
the argument did not.)

The register-then-enroll-then-run sequence is in
[`ops/runbooks/worker-operations.md`](/ops/runbooks/worker-operations.md).

## `health.py` — the runtime probe

`health.py` answers one question about the configured database: can it serve
this build?

```text
python apps/cli/health.py
```

It takes no option at all — the target is `MY_PA_DATABASE_URL` and there is
nothing else to decide. It prints a `state` line with one of three values and
exits `0` only for the first:

| `state` | means | exit |
| --- | --- | --- |
| `ready` | reachable, and carrying the migration head's schema | `0` |
| `not_at_head` | reachable, but its Alembic revision is not head | `1` |
| `unreachable` | no server answered | `1` |

**The revision half is the part that earns the command** (`D-61`, `D-62`).
Reachability alone would call the canonical `my_pa` database healthy while it
cannot serve a single capability: it carries no `knowledge` schema, so it has no
`knowledge.audit_events` for the audit row every served request commits, and a
request through it answers `internal_error` and says nothing about why.
Correcting that classification is out of scope and named by `D-65`; this command
is how an operator finds out.

**`not_at_head` is per-build, not per-capability.** At `9c6b4a18ed72` — **two**
revisions behind head `1a4c9e77b2d5` since WP-6, and one behind `af3d35efb9c0`
when this was measured — `capabilities.get` serves and `sources.list`
answers exactly as it does at head, so `not_at_head` is not a diagnosis that
every capability fails. It is still the right refusal: at that same revision
`sources.enroll` answers `internal_error` because `af3d35efb9c0` creates
`enrollment_objects`, and every `capture.*` request does too, because
`1a4c9e77b2d5` creates the capture tables and widens `audit_events.capability` to
admit a capture at all. Exiting `1` below head is an operational policy (`D-62`)
that the measurement supports rather than a claim the measurement refutes.

**It prints no URL, host, port, or database name, on any path.** The
unreachable report states the fact rather than the driver's message, because the
driver's message renders with the endpoint it failed to reach.
[`ops/runbooks/end-to-end-operations.md`](/ops/runbooks/end-to-end-operations.md)
runs it as the first step of the operator sequence.

## `migration.py` — the migration control plane

`migration.py` drives the legacy-SQLite to PostgreSQL migration.

```text
python apps/cli/migration.py init-run --source <path>
python apps/cli/migration.py status   --run-id <id>
python apps/cli/migration.py load     --run-id <id> --source <path> --phase PHASE-03
python apps/cli/migration.py resume   --run-id <id> --source <path>
python apps/cli/migration.py dry-run  --run-id <id> --source <path> --phase PHASE-03
```

Targets are always explicit: `--source` is required wherever the legacy database
is read, and the target comes from `MY_PA_DATABASE_URL`. The source is opened
read-only and is never written to. Output carries counts, table names, states,
and error codes — never a row value.

The engine behind it lives in `src/my_pa/infrastructure/migration/`; the load's
place in the Alembic sequence is documented in
[`migrations/README.md`](/migrations/README.md).

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
