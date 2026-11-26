"""WP4-S3: `english` against `simple` full-text search, measured (ruling D4, report section 2.4).

The `database` tier, on a disposable head-migrated clone. Synthetic messages
are ingested by the real operator command into the real tables, so
`search_document` is the server's generated column. Two things are proved:

1. **The labelled synthetic set.** Labelled queries in four classes
   (identifier surface forms, person names -- two of them `english` stop
   words -- topical inflections and quoted phrases) are run against `english`
   and `simple`, and against what the search will run: `english` plus the
   identifier index for identifier queries and `english` with `strpos`
   confirmation for quoted phrases. Per class the recall of the latter is at
   least that of `simple`, except the stop-word names, which are reported, not
   gated; a quoted phrase is exact.
2. **`communications_fts_measurement` and `measure-fts`.** Counts only; the
   class arithmetic holds (every present probe is an `english` hit or a miss,
   identifier misses are covered and name misses are not); the stop-word
   names are the uncovered misses and make the result material; batching and
   the limit change nothing but how much is measured.

Everything is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import communications_ingest as cli
from sqlalchemy import Engine, text

from my_pa.bootstrap.gateway import local_principal
from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    normalize_identifier_query,
)
from my_pa.infrastructure.persistence.communications import (
    FTS_COUNT_KEYS,
    FTS_PROBE_CLASSES,
    communications_fts_measurement,
)
from tests.database.test_communications_ingest_cli import Operator, _lock, _unlock
from tests.fixtures.communications_evidence import synthetic as s

pytestmark = pytest.mark.database

FOLDER: Final = "My PA/Daily Intelligence/communications"
#: (subject, body, sender) per synthetic message, keyed by a label.
MESSAGES: Final = {
    "rfi": ("RFI 174 response", "Please review RFI-174 before Friday.", "alpha"),
    "rfi_long": ("Schedule", "RFI 1740 is closed.", "alpha"),
    "pco": ("PCO pricing", "PCO 12 pricing is attached.", "alpha"),
    "co_words": ("Change Order", "Change Order 5 executed for the slab.", "alpha"),
    "co_acronym": ("CO update", "The CO 5 paperwork has been signed.", "alpha"),
    "delayed": ("Pour", "The pour was delayed by rain.", "alpha"),
    "delays": ("Delay notice", "Expect delays on the north deck.", "alpha"),
    "ordering": ("Panels", "We changed ordering of the panels.", "alpha"),
    "orders": ("Approvals", "Two change orders were approved today.", "alpha"),
    "will": ("Site walk", "Will Harper confirmed the site walk.", "will.harper"),
    "don": ("Drawings", "Don Chen mailed the revised drawings.", "don.chen"),
    "jones": ("Visit", "Mr Jones visited the site on Tuesday.", "jones"),
}
#: class -> query -> the labels a perfect search answers.
LABELLED: Final = {
    "identifier": {
        "RFI 174": {"rfi"},
        "RFI-174": {"rfi"},
        "PCO 12": {"pco"},
        "Change Order 5": {"co_words", "co_acronym"},
    },
    "name": {"Harper": {"will"}, "Chen": {"don"}, "Jones": {"jones"}},
    "stopword_name": {"Will": {"will"}, "Don": {"don"}},
    "topical": {"delays": {"delayed", "delays"}, "approved orders": {"orders"}},
    "phrase": {'"change orders"': {"orders"}, '"site walk"': {"will"}},
}


def _record(n: int, label: str) -> dict[str, Any]:
    subject, body, sender = MESSAGES[label]
    return s.message(
        n,
        selected="2026-11-17T12:00:00Z",
        subject=subject,
        content=f"<p>{body}</p>",
        sender=f"{sender}@example.invalid",
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "workspace"
    (root / FOLDER).mkdir(parents=True)
    document = s.publication(
        [_record(n, label) for n, label in enumerate(MESSAGES)],
        s.window("2026-11-17T05:00:00Z", "2026-11-18T04:59:59Z", 24, "weekday_prior_24h"),
    )
    (root / FOLDER / "20261117-comms.json").write_bytes(s.encode(document))
    _lock(root)
    monkeypatch.setenv("MY_PA_FILES_WORKSPACES", f"mcp={root};mode=direct")
    monkeypatch.delenv("MY_PA_FILES_WORKSPACE_ROOT", raising=False)
    try:
        yield root
    finally:
        _unlock(root)


@pytest.fixture
def ingested(
    migrated_engine: Engine, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[Operator, str]:
    operator = Operator(migrated_engine, capsys)
    code, out, _ = operator(
        "admit",
        "--consumer",
        "communications_evidence_v2",
        "--workspace",
        "mcp",
        "--path-prefix",
        FOLDER + "/",
        "--file-pattern",
        "*-comms.json",
    )
    assert code == cli.EXIT_OK, out
    source = str(out["ingest_source_id"])
    code, report, _ = operator("backfill", "--source", source)
    assert (code, report["outcome"]) == (cli.EXIT_OK, "completed"), report
    assert operator.scalar("SELECT count(*) FROM knowledge.communication_messages") == len(MESSAGES)
    return operator, source


# ---- 1. the labelled synthetic set ------------------------------------------------------

_BODY: Final = "coalesce(subject, '') || ' ' || coalesce(search_text, '')"


def _labels(engine: Engine) -> dict[str, str]:
    by_subject = {subject: label for label, (subject, _, _) in MESSAGES.items()}
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT message_id, subject FROM knowledge.communication_messages")
        )
        return {str(message_id): by_subject[str(subject)] for message_id, subject in rows}


def _matches(engine: Engine, predicate: str, **params: object) -> set[str]:
    labels = _labels(engine)
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT message_id FROM knowledge.communication_messages WHERE {predicate}"),  # noqa: S608
            params,
        )
        return {labels[str(row[0])] for row in rows}


def _english(engine: Engine, query: str) -> set[str]:
    return _matches(engine, "search_document @@ websearch_to_tsquery('english', :q)", q=query)


def _simple(engine: Engine, query: str) -> set[str]:
    return _matches(
        engine,
        f"to_tsvector('simple', {_BODY}) @@ websearch_to_tsquery('simple', :q)",
        q=query,
    )


def _searched(engine: Engine, cls: str, query: str) -> set[str]:
    """What the WP4 search runs: `english`, plus the index or `strpos` per class."""
    found = _english(engine, query)
    if cls == "identifier":
        identifier = normalize_identifier_query(query)
        assert identifier is not None, query
        found |= _matches(
            engine,
            "message_id IN (SELECT message_id FROM knowledge.communication_identifiers"
            " WHERE extractor_version = :v AND kind = :k AND value = :value)",
            v=IDENTIFIER_VERSION,
            k=identifier.kind.value,
            value=identifier.value,
        )
    if cls == "phrase":
        phrase = query.strip('"')
        found &= _matches(engine, f"strpos(lower({_BODY}), lower(:p)) > 0", p=phrase)
    return found


def _recall(answers: dict[str, set[str]], cls: str) -> float:
    relevant = sum(len(labels) for labels in LABELLED[cls].values())
    hit = sum(len(answers[query] & labels) for query, labels in LABELLED[cls].items())
    return hit / relevant


def test_english_with_the_index_and_strpos_recalls_at_least_simple_per_class(
    migrated_engine: Engine, ingested: tuple[Operator, str]
) -> None:
    report: dict[str, dict[str, float]] = {}
    for cls, queries in LABELLED.items():
        english = {q: _english(migrated_engine, q) for q in queries}
        simple = {q: _simple(migrated_engine, q) for q in queries}
        searched = {q: _searched(migrated_engine, cls, q) for q in queries}
        report[cls] = {
            "english": _recall(english, cls),
            "simple": _recall(simple, cls),
            "searched": _recall(searched, cls),
        }
        if cls == "phrase":  # exact: no false positive survives `strpos`
            assert all(searched[q] <= labels for q, labels in queries.items()), searched
    for cls in ("identifier", "name", "topical", "phrase"):
        assert report[cls]["searched"] >= report[cls]["simple"], (cls, report)
    # The identifier index makes identifier recall exact whatever FTS does.
    assert report["identifier"]["searched"] == 1.0
    # `english` stems: "delays" finds "delayed"; `simple` does not.
    assert report["topical"]["english"] > report["topical"]["simple"]
    # Reported, not gated (D4): `english` drops stop-word names, `simple` keeps them.
    assert report["stopword_name"]["english"] == 0.0
    assert report["stopword_name"]["simple"] == 1.0


# ---- 2. the counts-only measurement ------------------------------------------------------


def _measure(engine: Engine, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    with engine.connect() as connection:
        return communications_fts_measurement(
            connection,
            local_principal().principal_id,
            identifiers_version=IDENTIFIER_VERSION,
            **kwargs,
        )


def test_the_measurement_counts_hold_their_arithmetic_and_find_the_stopword_names(
    migrated_engine: Engine, ingested: tuple[Operator, str]
) -> None:
    measured = _measure(migrated_engine, limit=1000)
    assert measured["messages_measured"] == len(MESSAGES)
    assert measured["messages_deferred"] == 0
    classes = measured["classes"]
    assert set(classes) == set(FTS_PROBE_CLASSES)
    for counts in classes.values():
        assert set(counts) == set(FTS_COUNT_KEYS)
        assert counts["present"] <= counts["probes"]
        misses = counts["english_miss_covered_by_identifier"] + counts["english_miss_uncovered"]
        assert counts["english_hit_of_present"] + misses == counts["present"]
    identifier, name = classes["identifier"], classes["name"]
    # Rows rfi:174, rfi:1740, pco:12 and co:5 twice. The surface form `CO 5` is
    # not in "Change Order 5", so that probe is not present: only present probes
    # are measured (the aggregate's stated limit; the labelled set covers forms).
    assert (identifier["probes"], identifier["present"]) == (5, 4)
    assert identifier["english_miss_uncovered"] == 0
    # Names: alpha (absent from every body), will, harper, don, chen, jones.
    assert name["present"] == 5
    assert name["english_miss_covered_by_identifier"] == 0
    assert name["english_miss_uncovered"] == name["stopword_empty"] == 2  # will, don
    assert name["english_miss_simple_hit"] == 2
    assert measured["english_miss_uncovered_material"] is True


def test_batching_and_the_limit_change_only_how_much_is_measured(
    migrated_engine: Engine, ingested: tuple[Operator, str]
) -> None:
    whole = _measure(migrated_engine, limit=1000)
    batched = _measure(migrated_engine, limit=1000, batch_size=5)
    assert batched == whole
    part = _measure(migrated_engine, limit=5, batch_size=2)
    assert (part["messages_measured"], part["messages_deferred"]) == (5, len(MESSAGES) - 5)
    other_source = _measure(migrated_engine, limit=1000, ingest_source_id="isrc_doesnotexist0000")
    assert other_source["messages_measured"] == 0
    assert all(value == 0 for c in other_source["classes"].values() for value in c.values())
    with pytest.raises(ValueError, match="positive"):
        _measure(migrated_engine, limit=0)


def test_measure_fts_prints_counts_only(
    migrated_engine: Engine, ingested: tuple[Operator, str]
) -> None:
    operator, source = ingested
    code, out, raw = operator("measure-fts", "--source", source)
    assert code == cli.EXIT_OK
    assert out["command"] == "measure-fts"
    assert out["ingest_source_id"] == source
    assert out["messages_measured"] == len(MESSAGES)
    assert out["classes"] == _measure(migrated_engine, limit=1000)["classes"]
    words = {
        word.strip(".,").lower()
        for subject, body, sender in MESSAGES.values()
        for word in (*subject.split(), *body.split(), *sender.split("."))
        if len(word.strip(".,")) >= 4
    }
    printed = json.dumps(out).lower()
    assert sorted(word for word in words if word in printed) == []
    assert "example.invalid" not in raw
