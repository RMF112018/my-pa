# Operator CLI

Three programs, three planes. They share this directory because
`docs/architecture/module-boundaries.md` section 5.10 puts operator commands
here, and they share nothing else — no options, no runtime, no output shape.
A migration phase is not a capability, and neither is registering a source.

`tests/contract/test_cli_transport.py` holds the three option surfaces disjoint,
and `tests/architecture/test_operator_commands_are_not_capabilities.py` holds
`sources.py` mechanically outside the capability path.

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
`audit_events.capability` is closed to the eight capabilities, and a ninth member
is exactly what an operator command must not become.

The register-then-enroll-then-run sequence is in
[`ops/runbooks/worker-operations.md`](/ops/runbooks/worker-operations.md).

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
