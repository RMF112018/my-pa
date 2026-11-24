"""The single reviewed snapshot of the repository's pinned figures (`tests/pins.json`).

Why this exists (SCOPE "pins and counts", phase P1; operator decisions of
2026-11-22). The same figures -- the Alembic head, the revision count, the
capability count, the ChatLLM profile version -- are restated by hand in sixty
to ninety test files, so every migration or capability pays a find-and-replace
across all of them. This module is the one place they are recorded:

- `derive()` computes every figure from its source of truth (the Alembic graph,
  the closed enums, the ChatLLM policy table). It is pure and writes nothing.
- `tests/pins.json` is the committed snapshot, written only by
  `python -m tests.pins regen`. A test never writes it: a test that refreshed
  the snapshot it compares against would be vacuous.
- `tests/architecture/test_pins_are_current.py` asserts, section by section,
  that the committed snapshot equals `derive()`. Adding a migration or a
  capability without `regen` fails there, naming the section; the reviewed
  `pins.json` diff is then the acknowledgement (new head, new names).
- The typed accessors below (`ALEMBIC_HEAD`, `CAPABILITY_COUNT`, ...) read the
  committed snapshot, for later phases to import instead of restating literals.

`regen` also enforces two rules a plain snapshot cannot (phase P3): `IdKind`
only ever grows at its end, and the hand-bumped ChatLLM profile version moves
exactly when the policy table does. A change breaking either is refused, and
`test_pins_are_current.py` names the same rule while the snapshot is stale.

Not collected (no `test_` prefix), following `tests/ci_shard.py`.

Usage, from the repository root::

    PYTHONPATH=src .venv/bin/python -m tests.pins regen   # rewrite tests/pins.json
    PYTHONPATH=src .venv/bin/python -m tests.pins check   # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
PINS_PATH: Final = ROOT / "tests" / "pins.json"
MIGRATIONS: Final = ROOT / "migrations" / "versions"

#: The sections `test_pins_are_current` compares with `derive()`, one test each.
SECTIONS: Final = ("alembic", "vocabulary", "chatllm")
#: Every section of the snapshot. `counts` is not compared separately: each
#: count is asserted equal to the length of a committed list that *is*
#: compared, so a stale count is caught without a second red for one change.
SNAPSHOT_SECTIONS: Final = (*SECTIONS, "counts")


# --- Derivation ------------------------------------------------------------------------


def _alembic() -> dict[str, Any]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = list(script.get_heads())
    # Base first. `walk_revisions` runs head to base and raises on a cycle.
    chain = [revision.revision for revision in script.walk_revisions()][::-1]
    files = len(list(MIGRATIONS.glob("*.py")))
    return {"chain": chain, "heads": sorted(heads), "revision_files": files}


def _vocabulary() -> dict[str, list[str]]:
    from my_pa.application.errors import SafeDetail
    from my_pa.domain.common.identifiers import IdKind
    from my_pa.domain.identity.operation import Capability
    from my_pa.domain.identity.purpose import Purpose

    return {
        "capability": sorted(member.value for member in Capability),
        # Declaration order: persisted id prefixes are append-only.
        "id_kind": [member.value for member in IdKind],
        "purpose": sorted(member.value for member in Purpose),
        "safe_detail": sorted(member.value for member in SafeDetail),
    }


def _chatllm() -> dict[str, Any]:
    from my_pa.domain.identity.chatllm_capability_policy import (
        CHATLLM_CAPABILITY_POLICY,
        CHATLLM_DATA_PROFILE_VERSION,
        ChatLLMCapabilityClass,
    )

    entries = {
        capability.value: {
            "classification": policy.classification.value,
            "compatibility_replacement": (
                None
                if policy.compatibility_replacement is None
                else policy.compatibility_replacement.value
            ),
            "composition_prerequisite": policy.composition_prerequisite.value,
            "exclusion_rationale": policy.exclusion_rationale,
            "family": policy.family,
        }
        for capability, policy in CHATLLM_CAPABILITY_POLICY.items()
    }
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    classes = {member.value: 0 for member in ChatLLMCapabilityClass}
    for policy in CHATLLM_CAPABILITY_POLICY.values():
        classes[policy.classification.value] += 1
    return {
        "classes": classes,
        "policy_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "version": CHATLLM_DATA_PROFILE_VERSION,
    }


def derive() -> dict[str, Any]:
    """Every pinned figure, computed from the repository. Pure; writes nothing."""
    alembic = _alembic()
    vocabulary = _vocabulary()
    chatllm = _chatllm()
    counts = {
        "alembic_revisions": len(alembic["chain"]),
        "capability": len(vocabulary["capability"]),
        "chatllm_policy_entries": sum(chatllm["classes"].values()),
        "id_kind": len(vocabulary["id_kind"]),
        "purpose": len(vocabulary["purpose"]),
        "safe_detail": len(vocabulary["safe_detail"]),
    }
    return {"alembic": alembic, "chatllm": chatllm, "counts": counts, "vocabulary": vocabulary}


# --- The committed snapshot -------------------------------------------------------------


def render(snapshot: dict[str, Any]) -> str:
    """The one serialisation: sorted keys, one list item per line, a final newline."""
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def load() -> dict[str, Any]:
    """The committed `tests/pins.json`."""
    loaded = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


_COMMITTED: Final = load()

#: The single Alembic head the snapshot records.
ALEMBIC_HEAD: Final[str] = _COMMITTED["alembic"]["heads"][0]
#: The revision chain, base first.
ALEMBIC_CHAIN: Final[tuple[str, ...]] = tuple(_COMMITTED["alembic"]["chain"])
ALEMBIC_REVISION_COUNT: Final[int] = _COMMITTED["counts"]["alembic_revisions"]
CAPABILITY_NAMES: Final[frozenset[str]] = frozenset(_COMMITTED["vocabulary"]["capability"])
CAPABILITY_COUNT: Final[int] = _COMMITTED["counts"]["capability"]
PURPOSE_COUNT: Final[int] = _COMMITTED["counts"]["purpose"]
ID_KIND_ORDER: Final[tuple[str, ...]] = tuple(_COMMITTED["vocabulary"]["id_kind"])
SAFE_DETAIL_COUNT: Final[int] = _COMMITTED["counts"]["safe_detail"]
CHATLLM_PROFILE_VERSION: Final[str] = _COMMITTED["chatllm"]["version"]
CHATLLM_POLICY_SHA256: Final[str] = _COMMITTED["chatllm"]["policy_sha256"]
#: `ChatLLMCapabilityClass` value -> how many policy entries carry it.
CHATLLM_CLASS_COUNTS: Final[Mapping[str, int]] = MappingProxyType(
    dict(_COMMITTED["chatllm"]["classes"])
)


# --- Rules regen enforces (and the tests re-check) ------------------------------------------


def id_kind_order_violation(committed: dict[str, Any], derived: dict[str, Any]) -> str | None:
    """Why the derived `IdKind` order is not an append-only extension of the snapshot.

    `IdKind` values are persisted identifier prefixes and tests index the enum
    by position, so a kind may only ever be appended: the committed order must
    be a prefix of the derived one. `None` when it is.
    """
    before = list(committed["vocabulary"]["id_kind"])
    after = list(derived["vocabulary"]["id_kind"])
    if after[: len(before)] == before:
        return None
    for position, (old, new) in enumerate(zip(before, after, strict=False)):
        if old != new:
            return f"IdKind position {position} was {old!r} and is now {new!r}"
    return f"IdKind shrank from {len(before)} to {len(after)} kinds"


def chatllm_version_violation(committed: dict[str, Any], derived: dict[str, Any]) -> str | None:
    """Why the ChatLLM profile version and policy did not move together.

    `CHATLLM_DATA_PROFILE_VERSION` is hand-bumped and operator-visible (remote
    grant plans compare it), so it must change exactly when the policy table
    does: a policy change under the old version, or a version bump with an
    unchanged policy, is refused. `None` when they moved together.
    """
    old, new = committed["chatllm"], derived["chatllm"]
    policy_moved = old["policy_sha256"] != new["policy_sha256"]
    version_moved = old["version"] != new["version"]
    if policy_moved and not version_moved:
        return (
            f"the ChatLLM policy changed but CHATLLM_DATA_PROFILE_VERSION is still "
            f"{new['version']!r}; bump it"
        )
    if version_moved and not policy_moved:
        return (
            f"CHATLLM_DATA_PROFILE_VERSION moved {old['version']!r} -> {new['version']!r} "
            "but the policy is unchanged"
        )
    return None


# --- Spelling ---------------------------------------------------------------------------

_UNITS: Final = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS: Final = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def spell(value: int) -> str:
    """The lower-case English cardinal this corpus writes for `value` (0..9999).

    British "and" after hundreds ("two hundred and ninety-eight"); after
    thousands only below a hundred ("one thousand and seven", but "one thousand
    one hundred"), matching `_cardinals` in
    `tests/architecture/test_spelled_counts_match_the_sets_they_name.py`.
    """
    if not 0 <= value <= 9999:
        raise ValueError(f"spell() covers 0..9999, not {value}")
    if value < 20:
        return _UNITS[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        head = _TENS[tens - 2]
        return head if unit == 0 else f"{head}-{_UNITS[unit]}"
    if value < 1000:
        hundreds, rest = divmod(value, 100)
        prefix = f"{_UNITS[hundreds]} hundred"
        return prefix if rest == 0 else f"{prefix} and {spell(rest)}"
    thousands, rest = divmod(value, 1000)
    prefix = f"{_UNITS[thousands]} thousand"
    if rest == 0:
        return prefix
    return f"{prefix}{' and ' if rest < 100 else ' '}{spell(rest)}"


# --- CLI ----------------------------------------------------------------------------------


def stale_sections(committed: dict[str, Any], derived: dict[str, Any]) -> list[str]:
    return [
        section for section in SNAPSHOT_SECTIONS if committed.get(section) != derived.get(section)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.pins", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("regen", help="rewrite tests/pins.json from the repository")
    commands.add_parser("check", help="exit 1 if tests/pins.json is stale")
    arguments = parser.parse_args(argv)
    derived = derive()
    if arguments.command == "regen":
        heads = derived["alembic"]["heads"]
        if len(heads) != 1:
            print(f"refusing to pin {len(heads)} Alembic heads: {heads}", file=sys.stderr)
            return 1
        committed = load()
        for rule in (id_kind_order_violation, chatllm_version_violation):
            violation = rule(committed, derived)
            if violation is not None:
                print(f"refusing to regenerate: {violation}", file=sys.stderr)
                return 1
        PINS_PATH.write_text(render(derived), encoding="utf-8")
        print(f"wrote {PINS_PATH.relative_to(ROOT)}")
        return 0
    stale = stale_sections(load(), derived)
    if PINS_PATH.read_text(encoding="utf-8") != render(load()):
        stale.append("(formatting)")
    if stale:
        print(f"tests/pins.json is stale in {stale}; run `python -m tests.pins regen`")
        return 1
    print("tests/pins.json is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
