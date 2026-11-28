# Retire dedicated WP5 and P6 smoke fixtures

Use this local operator command to hide a dedicated communications fixture and a
dedicated P6 fixture through ordinary application reads. The command records
append-only retirement markers. It preserves the underlying message, source,
publication, Scenario, and existing audit trail.

The accepted fixture shape is one disabled communications source with one
verified synthetic publication and one corresponding message, and one closed
synthetic project with one completed P6 import, one dedicated series, and one
Scenario version. The command refuses mismatched source or XER hashes,
nonexclusive fixture relationships, and linked records. Obtain the four exact
IDs and the two file hashes from the fixture receipts. Use only the already
approved operator database route.

Preview with the exact deployed Alembic head and physical PostgreSQL identity.

```sh
python -m apps.cli.retire_smoke_fixtures \
  --expected-database "$APPROVED_DATABASE" \
  --expected-alembic-head "$APPROVED_ALEMBIC_HEAD" \
  --expected-system-id "$APPROVED_SYSTEM_ID" \
  --message-id "$SMOKE_MESSAGE" --source-id "$SMOKE_SOURCE" \
  --publication-id "$SMOKE_PUBLICATION" --scenario-id "$SMOKE_SCENARIO" \
  --expected-source-sha256 "$SMOKE_SOURCE_SHA256" \
  --expected-xer-sha256 "$SMOKE_XER_SHA256"
```

Review the exact IDs and the two derived IDs for the dedicated series and
Scenario version. Add `--apply-plan-sha256 "$REVIEWED_PLAN_SHA256"` to apply
the preview in one transaction. Apply refuses if PULSE or the communications
poll is on. It serializes with ingestion and takes bounded locks on the
fixture source and project. Keep other writers to those fixture records idle
during the maintenance step.

Run the same preview again and check all six marker IDs. Verify that the
ordinary reads with the approved client withhold the retired publication and
Scenario and that the fixture message is absent from meeting context. Check a
separately authorized unaffected fixture in the same Principal. A successful
apply is idempotent. The historical rows continue to be available to
authorized database and audit operators. There is no purge or undo command.

Application database roles that serve the filtered reads need `SELECT` on
`knowledge.smoke_fixture_retirements`. For a separate reader role, use the
approved database role procedure to verify the table privilege before rollout.
Schedule Scenarios preflight Q8 checks this
dependency when the table exists. Keep retirement writes on the operator
database route.
