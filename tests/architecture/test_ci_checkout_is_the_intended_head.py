"""CI must exercise the intended commit and the published single-entry package.

A green check against `refs/pull/*/merge` is not evidence that the reviewed
head ran. Checkout identity is fail-closed: HEAD must equal the PR head SHA
when GitHub supplies one, otherwise the push SHA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

WORKFLOW: Final = Path(__file__).resolve().parents[2] / ".github/workflows/repository-checks.yml"
CHECKOUT_PIN: Final = "github.event.pull_request.head.sha || github.sha"
FAIL_CLOSED: Final = "Checked-out HEAD is not the intended commit"
PACKAGE_NAME_LOG: Final = "package_name="
INVOKE_LOG: Final = "ApplicationService.invoke"


def test_repository_checks_pin_checkout_and_record_package_identity() -> None:
    """The provenance the frozen audit required, as workflow text.

    Eight jobs check out this repository: validate, web-security,
    dependency-floor, and the five database-tier lanes. The database-tier
    aggregator does not check out. Each checkout must pin `ref` to the PR head
    (or push SHA) and refuse when `git rev-parse HEAD` disagrees. Jobs that
    install Python must also print the published package name and the
    `ApplicationService.invoke` execution boundary.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    checkouts = text.count("uses: actions/checkout@")
    assert checkouts == 8, checkouts
    assert text.count(CHECKOUT_PIN) >= checkouts, (
        f"each checkout must set ref to `{CHECKOUT_PIN}`; found "
        f"{text.count(CHECKOUT_PIN)} pins for {checkouts} checkouts"
    )
    assert FAIL_CLOSED in text, "checkout identity must fail closed when HEAD drifts"
    assert text.count(FAIL_CLOSED) == checkouts
    assert PACKAGE_NAME_LOG in text
    assert INVOKE_LOG in text
    assert "answer_file=" in text or "answer=" in text
