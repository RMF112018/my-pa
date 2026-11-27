"""WP5-C (WP5-R1 F-1, the operator's direction): the set-based context statement is
result-equivalent to the per-pair one it replaced.

The `database` tier, run on the C and the en_US.UTF-8 clusters alike. A seeded
synthetic world -- ASCII and non-ASCII subjects and texts (`ß`, Greek, Cyrillic,
the `ﬁ` ligature, accents), Project numbers written exactly, split, embedded,
re-cased and accented, identifiers, participants, conversations, messages
outside the windows, withheld bodies -- is read by one batch of Meetings with
every criterion and every kind of number (hyphenated, underscored, spaced,
non-ASCII, none). `SqlCommunicationsRepository.context_candidates` must answer
exactly what the per-pair formulation of `bc8464fe2`
(`tests/database/meeting_context_reference.py`) answers: the same rows per
Meeting, in the same order, with every field equal. Every value is synthetic.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import timedelta
from typing import Final

import pytest
from sqlalchemy import Engine

from my_pa.contracts.ports import MeetingContextCandidateInput, MeetingContextCandidateQuery
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION
from my_pa.infrastructure.persistence.communications import SqlCommunicationsRepository
from tests.database.communications_search_world import World, at
from tests.database.meeting_context_reference import per_pair_candidates

pytestmark = pytest.mark.database

ADDRESSES: Final = (
    "alpha.eq@example.test",
    "bravo.eq@example.test",
    "charlie.eq@example.test",
    "straße.eq@example.test",
    "οδος.eq@example.test",
)
#: Project numbers as Meetings ask them; `None` asks no number.
NUMBERS: Final = ("SYN-4417", "ÄB_12", "Q 77", "ПР-5", "4417", "Straße-9", None)
#: Fragments a message's text is built from: each number exactly, re-cased,
#: split, embedded in a longer token and nearly matching; title words; noise.
FRAGMENTS: Final = (
    "SYN-4417",
    "syn-4417",
    "SYN 4417",
    "xSYN-4417y",
    "SYN-44170",
    "äb_12",
    "ÄB 12",
    "ÄB12",
    "q 77",
    "Q77",
    "77 q",
    "пр-5",
    "ПР 5",
    "ПР-55",
    "4417",
    "44171",
    "STRASSE-9",
    "straße-9",
    "Straße 9",
    "slab pour",
    "meetings",
    "Hauptstraße",
    "ΟΔΟΣ",
    "ﬁnance",
    "finance",
    "café",
    "RFI 7",
    "RFI 8",
    "CO 3",
    "nothing",
)
TERMS: Final = (
    ("slab", "pour"),
    ("meetings",),
    ("straße", "οδος"),
    ("finance",),
    ("café",),
    (),
    ("hauptstraße",),
)
IDENTIFIERS: Final = ((("rfi", "7"),), (("rfi", "8"), ("co", "3")), (), (("co", "3"),))


def _seed(engine: Engine, rng: random.Random) -> str:
    world = World(engine, tag="eq")
    for n in range(1, 151):
        words = rng.sample(FRAGMENTS, rng.randint(1, 4))
        withheld = n % 23 == 0
        world.message(
            n,
            subject=" ".join(rng.sample(FRAGMENTS, rng.randint(0, 2))) or None,
            text=None if withheld else " ".join(words),
            body_state="withheld" if withheld else "present",
            # Days 5 to 21: some messages fall outside every window.
            when=at(5 + n % 17, n % 24, n % 60),
            conversation=f"conv-eq-{n % 9}" if n % 3 else None,
            participants=tuple(
                ("from" if i == 0 else "to", address)
                for i, address in enumerate(rng.sample(ADDRESSES, rng.randint(1, 3)))
            ),
        )
    return world.principal_id


def _meetings(rng: random.Random) -> tuple[MeetingContextCandidateInput, ...]:
    meetings = []
    for k in range(10):
        start = at(8 + k % 5)
        keys = rng.sample(ADDRESSES, rng.randint(0, 2))
        meetings.append(
            MeetingContextCandidateInput(
                ordinal=k,
                window_start=start,
                window_end=start + timedelta(days=rng.choice((3, 7, 12))),
                addresses=tuple((key, key) for key in keys),
                identifiers=IDENTIFIERS[k % len(IDENTIFIERS)],
                title_terms=TERMS[k % len(TERMS)],
                project_number=NUMBERS[k % len(NUMBERS)],
            )
        )
    return tuple(meetings)


@pytest.fixture
def principal(migrated_engine: Engine) -> Iterator[str]:
    yield _seed(migrated_engine, random.Random(5))  # noqa: S311 - synthetic data


@pytest.mark.parametrize("limit", [3, 50])
def test_the_set_based_statement_answers_as_the_per_pair_one(
    migrated_engine: Engine, principal: str, limit: int
) -> None:
    rng = random.Random(11)  # noqa: S311 - synthetic data
    for _ in range(4):
        query = MeetingContextCandidateQuery(
            meetings=_meetings(rng), identifier_version=IDENTIFIER_VERSION, limit=limit
        )
        with migrated_engine.connect() as connection:
            new = SqlCommunicationsRepository(connection).context_candidates(principal, query)
            old = per_pair_candidates(connection, principal, query)
        assert new == old
        # The world exercises what the rewrite touched: number hits of several
        # numbers, non-ASCII title hits, and Meetings without a number.
        assert len({row.ordinal for row in new if row.project_number_hit}) >= 3
        assert any(row.title_hit for row in new)
    # And a batch of one Meeting per number, alone.
    for k, number in enumerate(NUMBERS):
        single = MeetingContextCandidateQuery(
            meetings=(
                MeetingContextCandidateInput(
                    ordinal=0,
                    window_start=at(5),
                    window_end=at(21, 23),
                    addresses=(),
                    identifiers=(),
                    title_terms=TERMS[k % len(TERMS)],
                    project_number=number,
                ),
            ),
            identifier_version=IDENTIFIER_VERSION,
            limit=limit,
        )
        with migrated_engine.connect() as connection:
            assert SqlCommunicationsRepository(connection).context_candidates(
                principal, single
            ) == per_pair_candidates(connection, principal, single), number
