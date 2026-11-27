"""WP4-S4: the latency record of the communications reads (design report section 2.10).

The `database` tier. A synthetic set of real-corpus size -- 3,500 messages and
about 27,000 participant rows, each message with one item, one observation and
its identifiers -- is bulk-written into the head-migrated clone, then each read
shape is timed end to end through `CommunicationsReads` (unit of work, every
statement, the Python assembly):

* a 20-result search on a common term (the `english` path);
* a 20-result search on a stop-word name (the D4-final `simple` fallback);
* a 20-result identifier search;
* a 25-id read.

The p50 and p95 are recorded (`record_property`, and printed under `-s`). The
assertion is only a generous ceiling (1 s at p95), so the test does not flake;
the figures are the evidence. Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import random
import statistics
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, insert

from my_pa.application.communications_search import ReadRequest, SearchRequest
from my_pa.infrastructure.persistence.tables import (
    communication_identifiers,
    communication_mailbox_items,
    communication_messages,
    communication_observations,
    communication_participants,
)
from tests.database.communications_search_world import P, World, at, reads

pytestmark = pytest.mark.database

MESSAGES: Final = 3_500
PARTICIPANTS_PER_MESSAGE: Final = 8  # 28,000 rows, about the corpus's 27,000
RUNS: Final = 40
CEILING_SECONDS: Final = 1.0
_WORDS: Final = (
    "slab",
    "pour",
    "schedule",
    "concrete",
    "deck",
    "formwork",
    "rebar",
    "inspection",
    "submittal",
    "pricing",
    "change",
    "order",
    "request",
    "delivery",
    "crane",
    "steel",
    "erection",
    "window",
    "curtain",
    "wall",
    "roofing",
    "drywall",
    "framing",
    "electrical",
    "plumbing",
    "mechanical",
    "survey",
    "permit",
    "meeting",
    "minutes",
    "budget",
    "variance",
    "contingency",
    "punch",
    "list",
    "closeout",
    "warranty",
    "schedule",
    "update",
    "weather",
)
_NAMES: Final = ("Will", "Don", "Bob", "Ana", "Kim", "Lee")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(rng: random.Random, n: int) -> str:
    size = rng.choice((40, 80, 150, 300, 600)) if n % 97 else 4_000
    words = [rng.choice(_WORDS) for _ in range(size)]
    words.insert(rng.randrange(len(words)), rng.choice(_NAMES))
    words.append(f"RFI {n % 400}")
    return " ".join(words) + "."


def _seed(engine: Engine, principal_id: str = P) -> list[str]:
    """The synthetic set, under `principal_id` (the WP5 context latency test reuses it)."""
    world = World(engine, principal_id=principal_id, tag="l")
    rng = random.Random(4)  # noqa: S311 - synthetic data, not security
    days = [17 + d for d in range(4)]
    snapshots = {day: world.snapshot(day) for day in days}
    messages, items, observations, participants, identifiers = [], [], [], [], []
    ids: list[str] = []
    for n in range(MESSAGES):
        day = days[n % len(days)]
        when = at(day, 0) + timedelta(seconds=(n * 37) % 86_000)
        message_id = f"cmsg_lat{n:08d}"
        item_id = f"cmitm_lat{n:08d}"
        text = _text(rng, n)
        ids.append(message_id)
        addresses = [f"person{rng.randrange(600)}@example.invalid" for _ in range(40)]
        chosen = list(dict.fromkeys(addresses))[:PARTICIPANTS_PER_MESSAGE]
        messages.append(
            {
                "message_id": message_id,
                "principal_id": principal_id,
                "mailbox_ref": "mbx-synthetic",
                "identity_kind": "provider_returned",
                "identity_value": f"<lat{n}@example.invalid>",
                "conversation_id": f"conv-{n // 3}",
                "subject": f"{rng.choice(_WORDS)} {rng.choice(_WORDS)} {n}",
                "sender_address": chosen[0],
                "message_time": when,
                "message_time_basis": "sent",
                "has_attachments": False,
                "body_state": "present",
                "body_sha256": _sha(f"body{n}"),
                "body_utf8_bytes": len(text),
                "content_type": "text",
                "search_text": text,
                "search_text_sha256": _sha(text),
                "search_text_version": "comms_search_text_v2",
                "search_text_basis": "body_content",
                "search_text_flags": [],
                "text_snapshot_id": snapshots[day],
                "text_record_ordinal": n,
                "first_snapshot_id": snapshots[day],
                "latest_snapshot_id": snapshots[day],
                "identifiers_version": "comms_identifiers_v2",
            }
        )
        items.append(
            {
                "item_id": item_id,
                "principal_id": principal_id,
                "message_id": message_id,
                "mailbox_ref": "mbx-synthetic",
                "provider_id": f"AAMk-lat-{n}",
                "provider_id_format": "mutable",
                "first_snapshot_id": snapshots[day],
            }
        )
        observation_id = f"cobs_lat{n:08d}"
        observations.append(
            {
                "observation_id": observation_id,
                "principal_id": principal_id,
                "item_id": item_id,
                "snapshot_id": snapshots[day],
                "record_ordinal": n,
                "classification": "accepted",
                "reasons": [],
                "folder_role": "inbox" if n % 3 else "sent",
                "lane_verification": "verified" if n % 20 == 0 else "unverified_lane_claim",
                "selected_field": "sent",
                "selected_utc": when,
                "received_utc": None,
                "received_state": "absent",
                "sent_utc": when,
                "sent_state": "present",
                "body_sha256": _sha(f"body{n}"),
                "unique_body_sha256": None,
                "participants": {"from": chosen[:1], "to": chosen[1:]},
            }
        )
        participants.extend(
            {
                "principal_id": principal_id,
                "message_id": message_id,
                "field": "from" if index == 0 else "to",
                "address": address,
                "first_observation_id": observation_id,
            }
            for index, address in enumerate(chosen)
        )
        identifiers.append(
            {
                "principal_id": principal_id,
                "message_id": message_id,
                "kind": "rfi",
                "value": str(n % 400),
                "extractor_version": "comms_identifiers_v2",
            }
        )
    with engine.begin() as connection:
        for table, rows in (
            (communication_messages, messages),
            (communication_mailbox_items, items),
            (communication_observations, observations),
            (communication_participants, participants),
            (communication_identifiers, identifiers),
        ):
            for start in range(0, len(rows), 1_000):
                connection.execute(insert(table), rows[start : start + 1_000])
    return ids


def _timed(call: Callable[[], object]) -> tuple[float, float]:
    call()  # warm the plan and the cache
    samples = []
    for _ in range(RUNS):
        start = time.perf_counter()
        call()
        samples.append(time.perf_counter() - start)
    samples.sort()
    return statistics.median(samples), samples[int(0.95 * (len(samples) - 1))]


def test_the_latency_record_at_real_corpus_size(
    migrated_engine: Engine, record_property: Callable[[str, object], None]
) -> None:
    ids = _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.exec_driver_sql("ANALYZE knowledge.communication_messages")
        connection.exec_driver_sql("ANALYZE knowledge.communication_participants")
        connection.exec_driver_sql("ANALYZE knowledge.communication_identifiers")
        connection.exec_driver_sql("ANALYZE knowledge.communication_observations")
        participants = connection.exec_driver_sql(
            "SELECT count(*) FROM knowledge.communication_participants"
        ).scalar_one()
    service = reads(migrated_engine)
    normal = service.search(P, SearchRequest(query="concrete inspection", limit=20))
    fallback = service.search(P, SearchRequest(query="Will", limit=20))
    assert len(normal.results) == 20 and normal.text_fallback is None
    assert len(fallback.results) == 20 and fallback.text_fallback == "simple_stopwords"
    shapes: dict[str, Callable[[], object]] = {
        "search_20_english": lambda: service.search(
            P, SearchRequest(query="concrete inspection", limit=20)
        ),
        "search_20_fallback": lambda: service.search(P, SearchRequest(query="Will", limit=20)),
        "search_20_identifier": lambda: service.search(
            P, SearchRequest(identifiers=["RFI 7"], limit=20, collapse="none")
        ),
        "search_20_browse": lambda: service.search(P, SearchRequest(limit=20)),
        "read_25_ids": lambda: service.read(P, ReadRequest(message_ids=ids[100:125])),
    }
    figures = {}
    for name, call in shapes.items():
        p50, p95 = _timed(call)
        figures[name] = (round(p50 * 1000, 1), round(p95 * 1000, 1))
        record_property(name, f"p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms")
    print(f"\nlatency (ms, p50/p95) over {MESSAGES} messages, {participants} participants:")
    for name, (p50, p95) in figures.items():
        print(f"  {name}: {p50} / {p95}")
    assert participants >= 27_000
    assert all(p95 / 1000 < CEILING_SECONDS for _, p95 in figures.values()), figures
