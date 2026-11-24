"""Wire compatibility for external clients: every published v1 shape is accepted.

`tests/contract/v1_payload_digests.json` (phase P4, operator decision O3)
records one digest per published tool's `payload` schema and per v1 view
model's field names, with a dated acceptance ledger. It replaces the aggregate
`V1_PAYLOAD_SCHEMA_SHA256*` / `_V1_VIEW_FIELDS_SHA256*` pins, their growing
exclusion sets and `len(payloads)` counts in the S3, S3.1 and S4 contract tests.

`test_v1_payload_digests_are_accepted` is red when

* a tool or view is new and unrecorded (`python -m tests.pins regen --accept-new`);
* an existing tool's or view's digest changed, or it was removed: an external
  client breaks, so only `regen --accept-v1-change NAME --reason "<ADR ref>"`
  accepts it, recording a dated ledger entry;
* the file was edited by hand (its seal or rendering is stale, or a digest is
  not what its last ledger entry accepted).

Unmarked: FAST. Reads `src/` and the digest file; writes nothing.
"""

from __future__ import annotations

from tests import pins


def test_v1_payload_digests_are_accepted() -> None:
    committed = pins.load_digests()
    text = pins.DIGESTS_PATH.read_text(encoding="utf-8")
    assert committed.get("seal") == pins.digest_seal(committed), (
        "tests/contract/v1_payload_digests.json was edited by hand; only "
        "`python -m tests.pins regen` may write it"
    )
    assert text == pins.render_digests(committed), "the digest file is not its canonical rendering"
    assert pins.ledger_violation(committed) is None, pins.ledger_violation(committed)
    drift = pins.digest_drift(committed, pins.derive_digests())
    for section, moved in drift.items():
        assert not moved["added"], (
            f"new {section} {moved['added']} are not recorded; run "
            "`PYTHONPATH=src .venv/bin/python -m tests.pins regen --accept-new`"
        )
        assert not moved["changed"] and not moved["removed"], (
            f"v1 {section} changed {moved['changed']} / removed {moved['removed']}: an "
            "external client breaks. Accept only with an ADR: `python -m tests.pins regen "
            '--accept-v1-change NAME --reason "<ADR ref>"`'
        )
