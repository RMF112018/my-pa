# Entity resolution calibration

Disposition: `RESOLUTION_PRECISION_HELD`

Measured by `tests/evaluation/resolution_harness.py` over the labelled,
collision-biased corpus in `tests/evaluation/fixtures/`. Every number below is
an observed frequency on that corpus, not a chosen weight — which is what
specification section 22.3 means by a numeric that is "calibrated and
explained". Re-run the harness to recompute; the JSON below must match it
exactly, and `tests/unit/test_entity_resolution_calibration.py` fails if it
does not.

`calibration_by_outcome_and_basis` is the table a reader consults: a `RESOLVED_*`
answer names the basis it rests on, and this says what that combination has
been worth against a corpus built to break it. Note that the two name-shaped
bases, `canonical_name` and `typed_name`, appear only under
`resolved_contextual` — a name never resolves on its own however it was
recorded, and a contextual signal did the selecting wherever one of them is
named. `communication_value` appears under neither `RESOLVED_*` outcome, for
the same reason: it is not a verified identifier.
`exact_resolutions_on_a_bare_name` is the count that must stay zero. It is
measured against a hardcoded allowlist of the three bases that may resolve
exactly, rather than against the basis vocabulary itself, so a basis added
later is caught by it rather than admitted by it.

**What this does not measure.** The corpus is synthetic and small. It is
evidence that the stated refusals hold and that the resolver still answers
the questions it should; it is not a population estimate, and no number here
should be read as a probability about a real person.

```json
{
  "calibration_by_outcome_and_basis": {
    "resolved_contextual:canonical_name": {
      "correct": 5,
      "observed_precision": 1.0,
      "resolutions": 5
    },
    "resolved_contextual:typed_name": {
      "correct": 1,
      "observed_precision": 1.0,
      "resolutions": 1
    },
    "resolved_exact:alias": {
      "correct": 6,
      "observed_precision": 1.0,
      "resolutions": 6
    },
    "resolved_exact:external_identifier": {
      "correct": 1,
      "observed_precision": 1.0,
      "resolutions": 1
    },
    "resolved_exact:verified_external_identifier": {
      "correct": 6,
      "observed_precision": 1.0,
      "resolutions": 6
    }
  },
  "candidate_limit": 10,
  "case_families": 26,
  "cases": 51,
  "cross_principal_leakage": 0,
  "disposition": "RESOLUTION_PRECISION_HELD",
  "exact_resolutions_on_a_bare_name": 0,
  "false_resolution_count": 0,
  "false_resolution_rate": 0.0,
  "forbidden_candidate_cases": 0,
  "missing_required_candidate_cases": 0,
  "must_not_resolve_cases": 32,
  "must_resolve_cases": 18,
  "outcome_mismatch_count": 0,
  "outcomes": {
    "ambiguous": 21,
    "conflicted_identifier": 3,
    "historical_match": 1,
    "not_found": 7,
    "resolved_contextual": 6,
    "resolved_exact": 13
  },
  "recall_floor": 0.9,
  "resolution_recall": 1.0,
  "withholding_precision": 1.0
}
```
