"""The mirrored canonical package must equal the bytes its receipts recorded.

`docs/specs/canonical-product-definition/` is a mirror of a ratified product
package held in Google Drive. Its entire value is that a reviewer can check a
citation against a file in this repository instead of against a document they
may not be able to open. That value rests on one thing: the mirrored bytes being
the bytes that were published.

Until this module, nothing checked it. The mirror ships
`READBACK-VERIFICATION-*.json` artifacts that record a per-artifact SHA-256 and
assert `"match": true` / `"readback": "MATCH"` — but those are claims written by
the same process that wrote the files, which is the shape of defect this
campaign keeps finding: *a guarantee that exists only as a disclosure by the
party being checked.* It is not hypothetical here. The RQC publication receipt
(`PUBLICATION-RECEIPT-…-RQC-INTEGRATION-20260802T114700Z.json`) records
`"canonical_specification_readback_observed": true` and no readback-verification
artifact for that cycle exists at all; a separate publication in this campaign
asserted readback was observed while its readback subfolders were empty. This
module converts the receipts from a disclosure into an executable check.

What it does NOT do, and the distinction matters more than the check:

- **It does not prove the mirror is current against Drive.** It compares the
  mirrored bytes to the hashes *a receipt in this repository recorded*. If Drive
  is revised again and no new receipt is mirrored, every assertion here still
  passes. Detecting that needs a network round-trip and cannot live in the FAST
  tier. Treat a green run as "the mirror matches its own published receipts",
  never as "the mirror is up to date".
- **It does not judge content.** Byte equality says nothing about whether the
  package is right, complete, or correctly cited. Neighbouring modules do that.

Two constraints shape the implementation, both learned the hard way:

- The package was revised in place twice on 2026-08-02 — RQC at ~11:49Z and
  Native Reminders at ~15:01Z. The first left `version: 2.1` stale in the front
  matter, so a version comparison could not see the revision and only a hash
  could. The consequence for this test is that older receipts legitimately bind
  superseded bytes: checking every artifact against every receipt naming it
  fails ten ways for the right reason and none for a real one. Each artifact is
  therefore bound to the *newest* receipt that names it.
- A guard that silently checks nothing is worse than no guard. `D-26`'s
  confinement guard listed a package name that could never match and a whole
  tier stayed green over it. So an unrecognised receipt shape is a failure here,
  not a skip, and the count of what was actually checked is asserted to be
  positive.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / "docs" / "specs" / "canonical-product-definition"

#: Receipts are found by glob, never by a list. A future revision cycle mirrors
#: another one and it must be picked up without this file being edited — the
#: hand-maintained list is the defect `test_open_decision_counts.py` and
#: `test_canonical_claims_are_supported.py` were each written to remove.
RECEIPT_GLOB = "READBACK-VERIFICATION-*.json"

#: The field naming the moment the publisher read its own bytes back. The two
#: mirrored cycles spell it differently; both are accepted, neither is guessed.
TIMESTAMP_FIELDS = ("verified_at", "verification_time")

#: The field carrying the coordination request ID, whose trailing
#: `YYYYMMDDThhmmssZ` stamp is the second, independent ordering signal.
REQUEST_ID_FIELDS = ("request_id", "coordination_request_id")

REQUEST_STAMP = re.compile(r"(\d{8}T\d{6}Z)")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Recorded:
    """One artifact as one receipt recorded it."""

    artifact: str
    sha256: str
    size: int
    receipt: str
    verified_at: datetime
    request_stamp: str
    #: Whether the row asserts its own readback matched.
    claims_match: bool
    #: The two hashes a row compared, where the schema records both. `None`
    #: where the schema records only one, which is not a defect — it is simply
    #: a receipt that cannot be checked against itself.
    hash_pair: tuple[str, str] | None


@dataclass(frozen=True)
class _Row:
    """One receipt row, normalised out of whichever schema carried it."""

    name: str
    sha256: str
    size: int
    claims_match: bool
    hash_pair: tuple[str, str] | None


@dataclass(frozen=True)
class _Schema:
    """How one publication cycle spells the fields this test needs.

    Held as data rather than as two hand-written parsers so that adding the next
    cycle's shape is one line, and so the failure message for an unrecognised
    receipt can name every shape that *is* understood without that list drifting
    out of step with the code that understands them.
    """

    #: The top-level key holding the rows.
    list_key: str
    sha_key: str
    size_key: str
    #: The field carrying the row's verdict on its own readback, and the value
    #: of that field which counts as an assertion that the readback matched.
    verdict_key: str
    match_value: object
    #: The second hash, where the schema records the readback separately from
    #: the expectation. `None` where it records only one — not a defect, just a
    #: receipt that cannot be checked against itself.
    readback_sha_key: str | None


SCHEMAS = (
    _Schema("members", "expected_sha256", "expected_bytes", "match", True, "readback_sha256"),
    _Schema("artifacts", "sha256", "bytes", "readback", "MATCH", None),
)


def _pick(payload: dict[str, object], fields: tuple[str, ...]) -> object:
    return next((payload[name] for name in fields if name in payload), None)


def _asserts_match(verdict: object, expected: object) -> bool:
    """Whether a row's verdict field asserts a matching readback.

    Types are compared as well as values, because `1 == True` and `0 == False`
    in Python: a receipt recording its verdict as a number would otherwise be
    read as claiming something it never said.
    """
    return type(verdict) is type(expected) and verdict == expected


def _row_from(entry: object, schema: _Schema) -> _Row | str:
    """One normalised row, or a sentence saying why it could not be read."""
    if not isinstance(entry, dict):
        return "is not a JSON object"
    name, sha, size = entry.get("name"), entry.get(schema.sha_key), entry.get(schema.size_key)
    if not isinstance(name, str) or not isinstance(sha, str):
        return f"has no string 'name' and {schema.sha_key!r}"
    if not isinstance(size, int) or isinstance(size, bool):
        return f"has no integer {schema.size_key!r}"
    if schema.verdict_key not in entry:
        return f"has no {schema.verdict_key!r} field, so it asserts nothing about itself"
    pair: tuple[str, str] | None = None
    if schema.readback_sha_key is not None:
        readback = entry.get(schema.readback_sha_key)
        if not isinstance(readback, str):
            return f"has no string {schema.readback_sha_key!r}"
        pair = (sha, readback)
    return _Row(
        name=name,
        sha256=sha,
        size=size,
        claims_match=_asserts_match(entry[schema.verdict_key], schema.match_value),
        hash_pair=pair,
    )


def _rows_from(entries: object, schema: _Schema) -> tuple[list[_Row], str | None]:
    """Every row under one schema's list key, or the first reason one failed."""
    if not isinstance(entries, list) or not entries:
        return [], f"its {schema.list_key!r} key does not hold a non-empty list"
    rows: list[_Row] = []
    for index, entry in enumerate(entries):
        row = _row_from(entry, schema)
        if isinstance(row, str):
            return [], f"its {schema.list_key}[{index}] {row}"
        rows.append(row)
    return rows, None


def _parse(path: Path) -> tuple[list[Recorded], str | None]:
    """Read one receipt into `Recorded` rows, or explain why it was not read.

    Returning the reason rather than raising is deliberate. Raising at import
    would take the whole module down as a collection error, including the
    non-vacuity guard that reports how much was checked. Instead every
    unreadable receipt is carried to `test_every_receipt_has_a_known_shape`,
    which turns it red with its reason attached — so an unknown shape still
    fails, and the rest of the run still says what it managed to verify.
    """
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"could not be read as JSON: {exc}"
    if not isinstance(payload, dict):
        return [], "its top level is not a JSON object"

    raw_time = _pick(payload, TIMESTAMP_FIELDS)
    if not isinstance(raw_time, str):
        return [], f"it declares none of the readback-time fields {TIMESTAMP_FIELDS}"
    try:
        verified_at = datetime.fromisoformat(raw_time)
    except ValueError:
        return [], f"its readback time {raw_time!r} is not an ISO-8601 timestamp"

    raw_id = _pick(payload, REQUEST_ID_FIELDS)
    if not isinstance(raw_id, str):
        return [], f"it declares none of the request-ID fields {REQUEST_ID_FIELDS}"
    stamp = REQUEST_STAMP.search(raw_id)
    if stamp is None:
        return [], f"its request ID {raw_id!r} carries no YYYYMMDDThhmmssZ stamp"

    schema = next((s for s in SCHEMAS if s.list_key in payload), None)
    if schema is None:
        return [], (
            "it carries no recognised member list: this test understands the "
            f"top-level keys {[s.list_key for s in SCHEMAS]}, and found "
            f"{sorted(payload)}"
        )
    rows, why = _rows_from(payload[schema.list_key], schema)
    if why is not None:
        return [], why

    return [
        Recorded(
            artifact=row.name,
            sha256=row.sha256,
            size=row.size,
            receipt=path.name,
            verified_at=verified_at,
            request_stamp=stamp.group(1),
            claims_match=row.claims_match,
            hash_pair=row.hash_pair,
        )
        for row in rows
    ], None


RECEIPT_PATHS = sorted(MIRROR.glob(RECEIPT_GLOB))
PARSED = {path: _parse(path) for path in RECEIPT_PATHS}
UNREADABLE = {path.name: why for path, (_rows, why) in PARSED.items() if why is not None}
ALL_ROWS = [row for rows, _why in PARSED.values() for row in rows]


def _newest_per_artifact() -> dict[str, Recorded]:
    """Bind each artifact to the newest receipt that names it.

    "Newest" is the receipt's own declared readback time, cross-checked against
    the `YYYYMMDDThhmmssZ` stamp in its coordination request ID. Both are
    written by the publisher, but they are written by different parts of it and
    for different purposes, and `test_two_independent_clocks_agree_on_order`
    fails if they ever disagree about which receipt came last. Filename sort
    order is deliberately not used: it happens to agree today only because the
    request stamps sort lexically, and a cycle named for a topic beginning with
    an earlier letter would silently reverse it.
    """
    newest: dict[str, Recorded] = {}
    for row in ALL_ROWS:
        held = newest.get(row.artifact)
        if held is None or (row.verified_at, row.request_stamp) > (
            held.verified_at,
            held.request_stamp,
        ):
            newest[row.artifact] = row
    return newest


NEWEST = _newest_per_artifact()
BOUND = sorted(NEWEST.items())
BOUND_IDS = [artifact for artifact, _row in BOUND]


def test_the_mirror_carries_at_least_one_readback_receipt() -> None:
    """Non-vacuity, first half: a glob that matched nothing passes everything."""
    assert RECEIPT_PATHS, (
        f"No file matching {RECEIPT_GLOB!r} was found in {MIRROR}. Every check in "
        "this module is keyed on those receipts, so without one the module "
        "reports green while verifying nothing — which is the exact failure it "
        "was written to remove. Either the mirror lost its receipts or this "
        "test is pointed at the wrong directory."
    )


def test_the_check_covers_a_positive_number_of_artifacts() -> None:
    """Non-vacuity, second half: receipts that parse to no rows check nothing."""
    assert BOUND, (
        f"{len(RECEIPT_PATHS)} readback receipt(s) were found but they bound zero "
        "artifacts, so no byte was compared. A receipt that parses to an empty "
        "member list must not be allowed to look like a passing verification."
    )
    assert len(BOUND) >= len(RECEIPT_PATHS), (
        f"{len(RECEIPT_PATHS)} receipts bound only {len(BOUND)} artifacts. That is "
        "fewer than one artifact per receipt, which means at least one receipt "
        "contributed nothing to the check."
    )


@pytest.mark.parametrize("path", RECEIPT_PATHS, ids=lambda p: p.name)
def test_every_receipt_has_a_known_shape(path: Path) -> None:
    """An unrecognised receipt goes red; it never quietly contributes nothing.

    This is the most important assertion in the module. A receipt whose shape
    this test does not understand is a receipt nothing is checking, and the way
    that fails is invisible: the artifacts it covers simply stop being compared
    while every other test still passes.
    """
    why = UNREADABLE.get(path.name)
    assert why is None, (
        f"{path.name} matches {RECEIPT_GLOB!r} but {why}. A readback receipt this "
        "test cannot read is a receipt nothing verifies. Teach _parse the new "
        "shape — do not exclude the file, and do not narrow the glob."
    )


@pytest.mark.parametrize("path", RECEIPT_PATHS, ids=lambda p: p.name)
def test_receipt_row_count_matches_its_own_declared_count(path: Path) -> None:
    """A receipt that states how many members it has must have that many."""
    rows, why = PARSED[path]
    if why is not None:
        pytest.skip("shape reported by test_every_receipt_has_a_known_shape")
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.get("member_count") if isinstance(payload, dict) else None
    if not isinstance(declared, int):
        return
    assert declared == len(rows), (
        f"{path.name} declares member_count {declared} but carries {len(rows)} "
        "rows. One of the two was hand-edited; the rows are the evidence and "
        "the count is the claim, so re-derive the count."
    )


@pytest.mark.parametrize(("artifact", "row"), BOUND, ids=BOUND_IDS)
def test_named_artifact_exists_in_the_mirror(artifact: str, row: Recorded) -> None:
    """Every artifact any receipt names must be present as a file.

    A receipt naming a file that is not mirrored is the emptier form of the
    defect this module exists for: the publication reports a verified artifact
    and the repository has nothing a reviewer can open.
    """
    path = MIRROR / artifact
    assert path.is_file(), (
        f"{row.receipt} records a verified readback for {artifact!r} "
        f"({row.size} bytes, sha256 {row.sha256[:12]}…) but no such file exists "
        f"in {MIRROR}. Either the mirror is incomplete or the receipt records an "
        "artifact that was never published here."
    )


@pytest.mark.parametrize(("artifact", "row"), BOUND, ids=BOUND_IDS)
def test_mirrored_bytes_match_the_newest_receipt_naming_them(artifact: str, row: Recorded) -> None:
    """The mirrored bytes must be the bytes the newest receipt recorded.

    Bound to the newest receipt only. The MCP cycle's hashes for the ten
    artifacts later revised in place are superseded, not wrong, and comparing
    against them would report ten failures for a revision that did happen.
    """
    path = MIRROR / artifact
    if not path.is_file():
        pytest.skip("absence is reported by test_named_artifact_exists_in_the_mirror")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert (digest, len(data)) == (row.sha256, row.size), (
        f"{artifact} does not match the bytes {row.receipt} recorded for it at "
        f"{row.verified_at.isoformat()}.\n"
        f"  recorded: {row.sha256} ({row.size} bytes)\n"
        f"  mirrored: {digest} ({len(data)} bytes)\n"
        "The mirror is supposed to be a byte copy of the ratified package, so a "
        "citation checked against this file is checked against something that "
        "was never published. Either the file was edited in place here — which "
        "the mirror does not permit — or the package was revised in Drive and "
        "re-mirrored without its new readback receipt being mirrored alongside "
        "it. Re-run the publication and mirror the receipt; do not edit either "
        "side to agree."
    )


@pytest.mark.parametrize("path", RECEIPT_PATHS, ids=lambda p: p.name)
def test_receipt_rows_do_not_contradict_themselves(path: Path) -> None:
    """A row claiming MATCH must show one hash, and every row must claim MATCH.

    Both halves are needed and the second is not decoration. Without it the
    first is satisfiable by lowering the claim: a publisher whose readback
    genuinely differed could write `"match": false` and pass. A mirrored
    readback receipt records a verification that succeeded — a row admitting its
    own mismatch means the Drive publication was never verified, and the bytes
    beneath it are unattested however well they hash.
    """
    rows, why = PARSED[path]
    if why is not None:
        pytest.skip("shape reported by test_every_receipt_has_a_known_shape")

    disowned = [row.artifact for row in rows if not row.claims_match]
    assert not disowned, (
        f"{path.name} carries rows that do not assert a matching readback: "
        f"{disowned}. A receipt is mirrored as evidence that the published bytes "
        "were read back and agreed; a row conceding they did not means that "
        "artifact is unverified at source. Re-publish and re-verify rather than "
        "mirroring a receipt that reports its own failure."
    )

    contradictory = [
        f"{row.artifact}: expected {row.hash_pair[0]} vs readback {row.hash_pair[1]}"
        for row in rows
        if row.hash_pair is not None and row.hash_pair[0] != row.hash_pair[1]
    ]
    assert not contradictory, (
        f"{path.name} claims a matching readback on rows whose two recorded "
        f"hashes differ: {contradictory}. The receipt contradicts itself, so its "
        "verdict cannot be used as evidence for any artifact in it — including "
        "the ones whose hashes do agree."
    )


def test_two_independent_clocks_agree_on_receipt_order() -> None:
    """The ordering "newest" rests on must be corroborated, not assumed.

    Every artifact is bound by the receipt's declared readback time. That field
    is written by the publisher, so on its own it is another self-assertion. The
    coordination request ID carries an independent `YYYYMMDDThhmmssZ` stamp,
    minted when the cycle was requested rather than when it finished. Ordering
    the receipts by each must produce the same sequence; if it ever does not,
    one of the two is wrong and which receipt is newest is no longer knowable
    from the mirror alone — so this fails rather than picking a winner.
    """
    readable = [(rows[0], path) for path, (rows, why) in PARSED.items() if why is None and rows]
    if len(readable) < 2:
        pytest.skip("ordering is only meaningful with two or more readable receipts")
    by_declared = [p.name for _row, p in sorted(readable, key=lambda pair: pair[0].verified_at)]
    by_request = [p.name for _row, p in sorted(readable, key=lambda pair: pair[0].request_stamp)]
    assert by_declared == by_request, (
        "The readback receipts order differently by their declared readback time "
        f"({by_declared}) than by their request-ID stamp ({by_request}). Those "
        "two are supposed to be independent witnesses to the same sequence, and "
        "every artifact in this module is bound to the receipt they agree is "
        "newest. Resolve which cycle actually came last before trusting either."
    )


@pytest.mark.parametrize(("artifact", "row"), BOUND, ids=BOUND_IDS)
def test_recorded_hash_is_a_sha256(artifact: str, row: Recorded) -> None:
    """Guard the comparison itself: a truncated or upper-cased hash never matches."""
    assert SHA256.fullmatch(row.sha256), (
        f"{row.receipt} records {row.sha256!r} for {artifact}, which is not 64 "
        "lower-case hex digits. The byte comparison would fail against every "
        "possible file, so this is a defect in the receipt rather than in the "
        "mirror."
    )
