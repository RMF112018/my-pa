"""The README's statement of what this build reports is derived, not asserted.

The paragraph in question said "every capability still reports `not_implemented`
… readiness reports `contracts_only`" and stayed there while the capabilities
were wired. Nothing connected the prose to the value, so nothing went red — the
same shape of defect `test_open_decision_counts.py` exists to prevent for section
14's figures, and the same remedy: recompute the claim and compare.

What is bound is deliberately narrow. Only the availability and readiness
*vocabulary* is checked — the closed sets of `Availability` and `ReadinessState`
values — against what the manifest a running service would publish actually
holds. The surrounding sentences are prose and stay prose; binding those would be
brittle without being useful, because they say things no value can confirm.

The manifest is built the way `ApplicationService._capabilities_get` builds it:
from the dispatch table's own keys and from the limits `bootstrap.settings`
defaults to. A README claim checked against a manifest assembled by hand here
would be checked against this file's opinion rather than against the build.
"""

from __future__ import annotations

import re
from pathlib import Path

from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.contracts.v1.capabilities import Availability, ReadinessState

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

#: The paragraph that states what this build reports. Anchored on its opening
#: word rather than on a line number, and read to the next blank line, so
#: reflowing it is safe and moving it is not silent.
CLAIM = re.compile(r"^Accordingly, (.+?)\n\n", re.DOTALL | re.MULTILINE)

_BACKTICKED = re.compile(r"`([A-Za-z][A-Za-z0-9_.-]*)`")

#: A settings URL that is well formed and unreachable, as in `tests/unit`.
#: Nothing connects; the limits are what this test is after.
_A_URL = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"


def claimed_tokens() -> set[str]:
    """Every backticked token in the README's state paragraph."""
    match = CLAIM.search(README.read_text(encoding="utf-8"))
    assert match is not None, (
        "The README paragraph beginning 'Accordingly,' is gone. It states what "
        "this build reports, and this test is the only thing keeping that "
        "statement true. Move the anchor deliberately, not by watching this pass."
    )
    return set(_BACKTICKED.findall(match.group(1)))


def published() -> tuple[set[str], str]:
    """What a running service would publish: availabilities, and readiness."""
    manifest = build_capability_manifest(
        implemented=frozenset(_HANDLERS),
        limits=Settings(database_url=_A_URL).effective_limits(),
    )
    availabilities = {status.availability.value for status in manifest.capabilities} | {
        status.availability.value for status in manifest.content_types
    }
    return availabilities, build_readiness_report(manifest).state.value


def test_the_state_paragraph_still_names_states() -> None:
    """Guard the parser: a paragraph naming none would make the checks vacuous."""
    tokens = claimed_tokens()
    assert tokens & {member.value for member in Availability}, (
        "The README's state paragraph names no availability value. Either it was "
        "reworded past this parser or it stopped making the claim; decide which."
    )
    assert tokens & {member.value for member in ReadinessState}, (
        "The README's state paragraph names no readiness state."
    )


def test_the_readme_names_exactly_the_availabilities_the_build_publishes() -> None:
    """Both directions: nothing claimed that is absent, nothing present unclaimed."""
    claimed = claimed_tokens() & {member.value for member in Availability}
    availabilities, _ = published()
    assert claimed == availabilities, (
        f"The README says this build reports {sorted(claimed)}; it reports "
        f"{sorted(availabilities)}. The manifest is derived from the application's "
        "dispatch table, so the prose is what is wrong."
    )


def test_the_readme_names_the_readiness_state_the_build_reports() -> None:
    claimed = claimed_tokens() & {member.value for member in ReadinessState}
    _, readiness = published()
    assert claimed == {readiness}, (
        f"The README says readiness is {sorted(claimed)}; it is {readiness!r}."
    )
