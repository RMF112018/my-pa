# WP-P00-02 Deterministic Validation

## Validator

`docs/migration/governance/validate_phase00_governance.py`

The validator uses only the Python standard library. It checks:

- required governance/evidence files exist and JSON parses;
- one active work item and one active authorization;
- `WP-P00-01` remains closed and `WP-P00-02` is pending exact-head review;
- stale `required_base_for_future_authorization` keys are absent;
- P00-AC-06 through P00-AC-08 are demonstrated, not self-PASSed;
- branch/worktree, logging/audit, and naming contracts contain their required controls;
- current public target surfaces contain no known former-employer naming patterns when run from a full repository checkout;
- all access and mutation attestations remain false and agree across records.

## Pre-commit candidate execution

Command:

```text
python docs/migration/governance/validate_phase00_governance.py --allow-partial-checkout
```

Output:

```text
PASS json-parse
PASS lifecycle-consistency
PASS stale-base-field-absent
PASS P00-AC-06-contract
PASS P00-AC-07-contract
SKIP P00-AC-08-public-surface-scan partial-checkout; require repository scan
PASS access-attestation
```

The partial-checkout skip is explicit and is not represented as PASS.

## Repository naming scan

Authenticated GitHub connector searches at runtime base `9039c587680866bfe4c1568db1992335778c5950` returned no indexed results for:

- `hb`
- `hb-personal-assistant`
- `hb_`
- `HB_`

This connector scan plus the deterministic full-checkout validator contract demonstrates the target-surface rule for review. The exact-head reviewer must repeat or independently inspect the scan.

## Post-commit checks required

After the single commit exists:

1. compare the exact candidate head to `9039c587680866bfe4c1568db1992335778c5950`;
2. verify every changed path is in the published allowlist;
3. fetch and parse every changed JSON file from the exact head;
4. verify the validator source at the exact head;
5. bind the exact head and tree in external implementation evidence.

No in-repository record predicts its own containing commit identity.
