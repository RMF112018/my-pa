"""`tests/pins.json` equals what the repository derives, section by section.

The snapshot is written only by `python -m tests.pins regen`; these tests only
compare. A migration, purpose, id kind, safe detail or ChatLLM policy change
that was not followed by `regen` turns exactly one
`test_pins_are_current[<section>]` red and names the section, so the reviewed
`pins.json` diff is the acknowledgement of the change. A new capability moves
two facts, its name (`vocabulary`) and its required ChatLLM classification
(`chatllm`), so it turns those two red.

Two rules hold across a `regen` (phase P3), each its own named test:
`test_id_kind_is_append_only` (an `IdKind` may only be appended) and
`test_chatllm_version_moves_with_policy` (the hand-bumped profile version moves
exactly when the policy does). `regen` refuses a change that breaks either.

The other tests keep the snapshot honest without restating a figure: its
counts are the lengths of its own lists, it records one head that is the end
of its chain, it is byte-identical to its canonical rendering (a hand edit is
caught even when it is semantically equal), the accessors read it, and
`spell()` agrees with the two spellings the corpus already uses.

Unmarked: FAST. Reads `migrations/`, `src/` and `tests/pins.json`; writes
nothing.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from tests import pins
from tests.architecture.test_readme_state_claims import SPELLED_COUNTS


@pytest.fixture(scope="module")
def derived() -> dict[str, Any]:
    return pins.derive()


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    return pins.load()


def test_the_snapshot_has_exactly_the_declared_sections(committed: dict[str, Any]) -> None:
    assert sorted(committed) == sorted(pins.SNAPSHOT_SECTIONS)


@pytest.mark.parametrize("section", pins.SECTIONS)
def test_pins_are_current(section: str, committed: dict[str, Any], derived: dict[str, Any]) -> None:
    assert committed[section] == derived[section], (
        f"tests/pins.json section {section!r} is stale; run "
        "`PYTHONPATH=src .venv/bin/python -m tests.pins regen` and review the diff"
    )


def test_the_snapshot_is_its_canonical_rendering(committed: dict[str, Any]) -> None:
    text = pins.PINS_PATH.read_text(encoding="utf-8")
    assert text == pins.render(committed), "tests/pins.json was edited by hand; run regen"


def test_the_snapshot_counts_are_the_lengths_of_its_lists(committed: dict[str, Any]) -> None:
    counts = committed["counts"]
    vocabulary = committed["vocabulary"]
    assert counts["alembic_revisions"] == len(committed["alembic"]["chain"])
    assert committed["alembic"]["revision_files"] == counts["alembic_revisions"]
    for name in ("capability", "id_kind", "purpose", "safe_detail"):
        assert counts[name] == len(vocabulary[name]), name
        assert len(set(vocabulary[name])) == len(vocabulary[name]), f"{name} repeats a value"
    assert counts["chatllm_policy_entries"] == sum(committed["chatllm"]["classes"].values())
    assert counts["chatllm_policy_entries"] == counts["capability"]


def test_the_snapshot_records_one_head_at_the_end_of_its_chain(
    committed: dict[str, Any],
) -> None:
    alembic = committed["alembic"]
    assert len(alembic["heads"]) == 1
    assert alembic["chain"][-1] == alembic["heads"][0]
    assert len(set(alembic["chain"])) == len(alembic["chain"])


def test_the_accessors_read_the_committed_snapshot(committed: dict[str, Any]) -> None:
    assert committed["alembic"]["heads"][0] == pins.ALEMBIC_HEAD
    assert list(pins.ALEMBIC_CHAIN) == committed["alembic"]["chain"]
    assert committed["counts"]["alembic_revisions"] == pins.ALEMBIC_REVISION_COUNT
    assert frozenset(committed["vocabulary"]["capability"]) == pins.CAPABILITY_NAMES
    assert committed["counts"]["capability"] == pins.CAPABILITY_COUNT
    assert committed["counts"]["purpose"] == pins.PURPOSE_COUNT
    assert list(pins.ID_KIND_ORDER) == committed["vocabulary"]["id_kind"]
    assert committed["counts"]["safe_detail"] == pins.SAFE_DETAIL_COUNT
    assert committed["chatllm"]["version"] == pins.CHATLLM_PROFILE_VERSION
    assert committed["chatllm"]["policy_sha256"] == pins.CHATLLM_POLICY_SHA256
    assert committed["chatllm"]["classes"] == dict(pins.CHATLLM_CLASS_COUNTS)


def test_id_kind_is_append_only(committed: dict[str, Any], derived: dict[str, Any]) -> None:
    """The committed `IdKind` order is a prefix of the current declaration order.

    Persisted identifiers carry these prefixes and tests index `list(IdKind)` by
    position, so a kind may be appended but never inserted, reordered or
    removed. `regen` refuses such a change; this names it while it is unregenerated.
    """
    assert pins.id_kind_order_violation(committed, derived) is None, pins.id_kind_order_violation(
        committed, derived
    )


def test_chatllm_version_moves_with_policy(
    committed: dict[str, Any], derived: dict[str, Any]
) -> None:
    """A ChatLLM policy change bumps the profile version, and a bump changes the policy.

    `CHATLLM_DATA_PROFILE_VERSION` stays hand-bumped in `src` (operator-visible:
    remote grant plans compare it). `regen` refuses either half moving alone;
    this names it while the snapshot is stale.
    """
    assert pins.chatllm_version_violation(committed, derived) is None, (
        pins.chatllm_version_violation(committed, derived)
    )


def test_the_regen_rules_refuse_what_they_name(derived: dict[str, Any]) -> None:
    order = derived["vocabulary"]["id_kind"]

    def with_id_kinds(kinds: list[str]) -> dict[str, Any]:
        return {**derived, "vocabulary": {**derived["vocabulary"], "id_kind": kinds}}

    assert pins.id_kind_order_violation(derived, with_id_kinds([*order, "zzz"])) is None
    assert pins.id_kind_order_violation(derived, with_id_kinds([order[1], order[0], *order[2:]]))
    assert pins.id_kind_order_violation(derived, with_id_kinds(order[:-1]))

    def with_chatllm(**changed: str) -> dict[str, Any]:
        return {**derived, "chatllm": {**derived["chatllm"], **changed}}

    moved_both = with_chatllm(policy_sha256="0" * 64, version="chatllm-data-next")
    assert pins.chatllm_version_violation(derived, moved_both) is None
    assert pins.chatllm_version_violation(derived, with_chatllm(policy_sha256="0" * 64))
    assert pins.chatllm_version_violation(derived, with_chatllm(version="chatllm-data-next"))


def test_check_reports_a_stale_section_by_name(derived: dict[str, Any]) -> None:
    stale = {**derived, "counts": {**derived["counts"], "capability": -1}}
    assert pins.stale_sections(stale, derived) == ["counts"]
    assert pins.stale_sections(derived, derived) == []


#: Spellings the corpus writes, at each boundary of the `_cardinals` rule in
#: `tests/architecture/test_spelled_counts_match_the_sets_they_name.py`. That
#: module is not imported: building its sweeps takes minutes at import.
CORPUS_SPELLINGS: Final = {
    0: "zero",
    7: "seven",
    19: "nineteen",
    20: "twenty",
    42: "forty-two",
    99: "ninety-nine",
    100: "one hundred",
    103: "one hundred and three",
    131: "one hundred and thirty-one",
    537: "five hundred and thirty-seven",
    998: "nine hundred and ninety-eight",
    1000: "one thousand",
    1007: "one thousand and seven",
    1099: "one thousand and ninety-nine",
    1100: "one thousand one hundred",
    1999: "one thousand nine hundred and ninety-nine",
}


#: `SPELLED_COUNTS` (tests/architecture/test_readme_state_claims.py) spells
#: these without the "and" that `_cardinals` and every other entry use. The
#: README prose it guards was written that way; unifying the spellers is phase
#: P5. Pinned exactly, so the divergence cannot grow unseen.
SPELLED_COUNTS_WITHOUT_AND: Final = frozenset({101, 102, 103, 105, 106, 107, 108})


def test_spell_agrees_with_the_corpus_spellings() -> None:
    for value, word in CORPUS_SPELLINGS.items():
        assert pins.spell(value) == word, (value, word)
    diverging = set()
    for value, word in SPELLED_COUNTS.items():
        if pins.spell(value) != word.lower():
            assert pins.spell(value).replace(" and ", " ") == word.lower(), (value, word)
            diverging.add(value)
    assert diverging == SPELLED_COUNTS_WITHOUT_AND
    spelled = [pins.spell(value) for value in range(10_000)]
    assert len(set(spelled)) == len(spelled), "two values share a spelling"
    for bad in (-1, 10_000):
        with pytest.raises(ValueError):
            pins.spell(bad)
