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

`regen` also keeps `tests/contract/v1_payload_digests.json` (phase P4, operator
decision O3): the wire-compatibility tripwire for external clients. It records
one digest per published tool's `payload` schema and per v1 view model's field
names, plus a dated acceptance ledger. A new tool or view is recorded only by
`regen --accept-new`; a changed or removed one only by
`regen --accept-v1-change NAME --reason "<ADR ref>"`, which writes a ledger
entry. `tests/contract/test_v1_payload_digests.py` compares and never writes.

Not collected (no `test_` prefix), following `tests/ci_shard.py`.

Usage, from the repository root::

    PYTHONPATH=src .venv/bin/python -m tests.pins regen   # rewrite tests/pins.json
    PYTHONPATH=src .venv/bin/python -m tests.pins check   # exit 1 if it is stale
    PYTHONPATH=src .venv/bin/python -m tests.pins regen --accept-new
    PYTHONPATH=src .venv/bin/python -m tests.pins regen \
        --accept-v1-change reports.read --reason "ADR-0NN: why the v1 shape moves"
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib
import inspect
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
PINS_PATH: Final = ROOT / "tests" / "pins.json"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
DIGESTS_PATH: Final = ROOT / "tests" / "contract" / "v1_payload_digests.json"

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


# --- v1 wire digests (D1) ----------------------------------------------------------------

#: The digest file's sections: published tool name -> SHA-256 of its `payload`
#: schema, and `module.Model` -> SHA-256 of its sorted field names.
DIGEST_SECTIONS: Final = ("tools", "views")
#: The `my_pa.contracts.v1` modules whose models are pinned, as the S3 view pin did.
V1_VIEW_MODULES: Final = (
    "tasks",
    "commitments",
    "meetings",
    "record_events",
    "capture",
    "canvas_workspace",
    "documents",
    "reveal",
    "status",
    "capabilities",
)


def canonical_sha256(document: object) -> str:
    """SHA-256 of compact, key-sorted JSON: the measure every v1 pin has used."""
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def v1_payloads() -> dict[str, Any]:
    """Every published tool's `payload` input schema, by tool name."""
    from my_pa.adapters.mcp.tools import TOOLS

    return {tool.name: tool.input_schema["properties"]["payload"] for tool in TOOLS}


def v1_view_fields() -> dict[str, list[str]]:
    """Every v1 view model's sorted field names, by `module.Model`."""
    from pydantic import BaseModel

    views: dict[str, list[str]] = {}
    for name in V1_VIEW_MODULES:
        module = importlib.import_module(f"my_pa.contracts.v1.{name}")
        for model_name, model in vars(module).items():
            if (
                inspect.isclass(model)
                and issubclass(model, BaseModel)
                and model.__module__ == module.__name__
            ):
                views[f"{name}.{model_name}"] = sorted(model.model_fields)
    return views


def derive_digests() -> dict[str, dict[str, str]]:
    """The per-name digests the repository publishes now. Pure; writes nothing."""
    return {
        "tools": {name: canonical_sha256(payload) for name, payload in v1_payloads().items()},
        "views": {name: canonical_sha256(fields) for name, fields in v1_view_fields().items()},
    }


def load_digests() -> dict[str, Any]:
    """The committed `tests/contract/v1_payload_digests.json`."""
    loaded = json.loads(DIGESTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def digest_seal(document: Mapping[str, Any]) -> str:
    """The seal `regen` writes over the accepted digests and the whole ledger.

    A hand edit of a digest or of a ledger entry that skipped `regen` leaves the
    seal stale, so it is caught even when the edited digest matches the source.
    """
    return canonical_sha256({key: document[key] for key in (*DIGEST_SECTIONS, "ledger")})


def digest_drift(
    committed: Mapping[str, Any], derived: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, list[str]]]:
    """Per section: names `added` (unrecorded), `changed` and `removed` from the repository."""
    drift: dict[str, dict[str, list[str]]] = {}
    for section in DIGEST_SECTIONS:
        accepted, now = committed[section], derived[section]
        drift[section] = {
            "added": sorted(set(now) - set(accepted)),
            "changed": sorted(n for n in set(now) & set(accepted) if now[n] != accepted[n]),
            "removed": sorted(set(accepted) - set(now)),
        }
    return drift


def ledger_violation(committed: Mapping[str, Any]) -> str | None:
    """Why the accepted digests are not what the ledger last accepted. `None` if they are.

    The last `changed` entry naming a digest must record exactly the digest now
    accepted for it (or none, for a removal).
    """
    last: dict[tuple[str, str], str | None] = {}
    for entry in committed["ledger"]:
        if entry["kind"] == "changed":
            last[(entry["section"], entry["name"])] = entry["to"]
    for (section, name), digest in last.items():
        if committed[section].get(name) != digest:
            return f"{section} {name!r} is not the digest its last ledger entry accepted"
    return None


def render_digests(document: Mapping[str, Any]) -> str:
    sealed = {key: document[key] for key in (*DIGEST_SECTIONS, "ledger")}
    sealed["seal"] = digest_seal(sealed)
    sealed["about"] = (
        "Written by `python -m tests.pins regen`; never edit by hand. A new name needs "
        "`--accept-new`; a changed or removed one `--accept-v1-change NAME --reason`."
    )
    return json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def accept_digests(
    committed: Mapping[str, Any],
    derived: Mapping[str, Mapping[str, str]],
    *,
    accept_new: bool,
    accept_change: list[str],
    reason: str | None,
    today: datetime.date,
) -> tuple[dict[str, Any] | None, str | None]:
    """The digest document after accepting the named drift, or why it is refused."""
    drift = digest_drift(committed, derived)
    moved = {
        name
        for section in DIGEST_SECTIONS
        for name in (*drift[section]["changed"], *drift[section]["removed"])
    }
    if accept_change and not (reason and reason.strip()):
        return None, "--accept-v1-change needs --reason naming the ADR that allows it"
    unmoved = sorted(set(accept_change) - moved)
    if unmoved:
        return None, f"--accept-v1-change names {unmoved}, whose digests did not move"
    unaccepted = sorted(moved - set(accept_change))
    if unaccepted:
        return None, (
            f"v1 digests changed or were removed for {unaccepted}: an external client "
            'breaks; rerun with --accept-v1-change NAME --reason "<ADR ref>" for each'
        )
    new = {section: drift[section]["added"] for section in DIGEST_SECTIONS}
    if any(new.values()) and not accept_new:
        return None, f"new names {new} are not yet recorded; rerun with --accept-new"
    document: dict[str, Any] = {
        "ledger": list(committed["ledger"]),
        **{section: dict(committed[section]) for section in DIGEST_SECTIONS},
    }
    for section in DIGEST_SECTIONS:
        if new[section]:
            document["ledger"].append(
                {
                    "date": today.isoformat(),
                    "kind": "added",
                    "names": new[section],
                    "section": section,
                }
            )
            for name in new[section]:
                document[section][name] = derived[section][name]
        for name in (*drift[section]["changed"], *drift[section]["removed"]):
            digest = derived[section].get(name)
            document["ledger"].append(
                {
                    "date": today.isoformat(),
                    "from": committed[section][name],
                    "kind": "changed",
                    "name": name,
                    "reason": (reason or "").strip(),
                    "section": section,
                    "to": digest,
                }
            )
            if digest is None:
                del document[section][name]
            else:
                document[section][name] = digest
    return document, None


# --- CLI ----------------------------------------------------------------------------------


def stale_sections(committed: dict[str, Any], derived: dict[str, Any]) -> list[str]:
    return [
        section for section in SNAPSHOT_SECTIONS if committed.get(section) != derived.get(section)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.pins", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    regen = commands.add_parser(
        "regen", help="rewrite tests/pins.json and accept v1 digest drift you name"
    )
    regen.add_argument(
        "--accept-new", action="store_true", help="record new tools and views in the digest file"
    )
    regen.add_argument(
        "--accept-v1-change",
        action="append",
        default=[],
        metavar="NAME",
        help="accept a changed or removed v1 digest (repeatable); needs --reason",
    )
    regen.add_argument("--reason", help="the ADR reference the ledger records")
    commands.add_parser("check", help="exit 1 if tests/pins.json or the digest file is stale")
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
        digests, refusal = accept_digests(
            load_digests(),
            derive_digests(),
            accept_new=arguments.accept_new,
            accept_change=arguments.accept_v1_change,
            reason=arguments.reason,
            today=datetime.date.today(),
        )
        if digests is None:
            print(f"refusing to regenerate: {refusal}", file=sys.stderr)
            return 1
        PINS_PATH.write_text(render(derived), encoding="utf-8")
        DIGESTS_PATH.write_text(render_digests(digests), encoding="utf-8")
        print(f"wrote {PINS_PATH.relative_to(ROOT)} and {DIGESTS_PATH.relative_to(ROOT)}")
        return 0
    stale = stale_sections(load(), derived)
    if PINS_PATH.read_text(encoding="utf-8") != render(load()):
        stale.append("(formatting)")
    digests = load_digests()
    drift = digest_drift(digests, derive_digests())
    if any(names for section in drift.values() for names in section.values()):
        stale.append(f"v1 digests {drift}")
    if DIGESTS_PATH.read_text(encoding="utf-8") != render_digests(digests):
        stale.append("v1 digests (hand edited: seal or formatting)")
    if stale:
        print(f"pins are stale in {stale}; run `python -m tests.pins regen`")
        return 1
    print("tests/pins.json and the v1 digests are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
