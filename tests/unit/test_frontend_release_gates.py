"""WP28/WP29/WP08 gate membership must stay explicit.

Advisory jobs may exist. They must not silently join `frontend / required`.
WP29 adds `delivery-config` as a required child.

WP08 adds three more, and the reason each was promoted is part of the record
because a promotion without evidence is how a flaky lane becomes a permanently
red required check:

* `pwa-offline` — promoted from advisory. Twelve clean runs across two
  independent batches at this head; nothing in its history at this head is
  intermittent, so `continue-on-error` was buying nothing but silence.
* `degraded-gateway` — promoted from advisory on the same evidence: twelve
  clean runs across the same two independent batches at this head. It proves
  unavailable-is-not-empty, which is precisely the claim that must not be
  allowed to rot unnoticed.
* `mobile-webkit-postux` — new, and blocking from birth. It is the only
  mobile-WebKit evidence in the repository: a curated lane on the engine Safari
  ships, at phone geometry. Introduced as advisory it would have measured
  nothing anybody had to read.

Promotion is one-directional in intent but not enforced as such: this module
pins the current membership, so both adding and removing a member is a
deliberate edit here. That is the point.

This is still not a coverage-percentage gate and still not a budget.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "frontend-quality.yml"

REQUIRED_CHILDREN = (
    "static",
    "unit",
    "production-build",
    "contract",
    "security",
    "e2e-critical",
    "accessibility",
    "responsive",
    "mobile-webkit-postux",
    "pwa-offline",
    "degraded-gateway",
    "delivery-config",
)

ADVISORY = (
    "browsers",
    "visual",
    "performance",
)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_required_aggregate_lists_exactly_the_required_children() -> None:
    text = _workflow()
    match = re.search(
        r"name: frontend / required\n\s+needs: \[([^\]]+)\]",
        text,
    )
    assert match is not None, "frontend / required needs list is missing"
    needs = [item.strip() for item in match.group(1).split(",")]
    assert needs[0] == "classify"
    assert needs[1:] == list(REQUIRED_CHILDREN)
    for job in ADVISORY:
        assert job not in needs


def test_advisory_jobs_use_continue_on_error_and_exist() -> None:
    text = _workflow()
    for job in ADVISORY:
        block = re.search(
            rf"  {re.escape(job)}:\n    name: frontend / {re.escape(job)}\n"
            rf"    needs: classify\n"
            rf"    if: needs.classify.outputs.applicable == 'true'\n"
            rf"    continue-on-error: true\n",
            text,
        )
        assert block is not None, f"{job} must exist as continue-on-error advisory"


def _job_block(text: str, job: str) -> str:
    match = re.search(rf"^  {re.escape(job)}:\n", text, re.M)
    assert match is not None, job
    rest = text[match.end() :]
    nxt = re.search(r"^  [a-z0-9-]+:", rest, re.M)
    return text[match.start() : match.end() + (nxt.start() if nxt else len(rest))]


def test_required_child_jobs_do_not_continue_on_error() -> None:
    text = _workflow()
    for job in REQUIRED_CHILDREN:
        assert "continue-on-error: true" not in _job_block(text, job), job


def test_dead_gateway_harness_allowlists_session_origin_and_splits_urls() -> None:
    """Sign-in on :3101 needs both the session URL split and the RP origin list."""
    repo = Path(__file__).resolve().parents[2]
    stack = (repo / "web" / "e2e" / "stack.sh").read_text(encoding="utf-8")
    assert "http://localhost:3100" in stack
    assert "http://localhost:3101" in stack
    config = (repo / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    assert "MYPA_SESSION_SERVICE_URL: GATEWAY_URL" in config
    assert "MYPA_CANONICAL_ORIGIN: DEAD_GATEWAY_URL" in config
    assert 'MYPA_GATEWAY_URL: "http://127.0.0.1:1"' in config


class TestPromotedLanesAreNoLongerAdvisory:
    """WP08-RT-F004/F005 — a promotion is three edits, and two of them are silent.

    Promoting `pwa-offline` and `degraded-gateway` meant deleting
    `continue-on-error: true` from each job AND adding each to the aggregator.
    Only the first is visible in the job block. Doing just the first leaves two
    lanes that can fail the workflow run without failing the one check branch
    protection consults; doing just the second leaves two lanes that report
    `success` to the aggregator no matter what they found, because
    `continue-on-error` makes a failed job's ``result`` ``success``. Either
    half alone is worse than not having promoted them, so all three edits are
    asserted together here.
    """

    PROMOTED = ("pwa-offline", "degraded-gateway")

    def test_the_job_blocks_no_longer_carry_continue_on_error(self) -> None:
        text = _workflow()
        for job in self.PROMOTED:
            assert "continue-on-error" not in _job_block(text, job), (
                f"{job} was promoted to required but still carries continue-on-error, "
                "which forces its result to 'success' even when it fails"
            )

    def test_the_aggregator_declares_and_inspects_them(self) -> None:
        gate = _job_block(_workflow(), "required")
        needs, env, loop = _aggregator_parts(gate)
        for job in self.PROMOTED:
            assert job in needs, f"{job} is promoted but absent from the aggregator needs"
            assert job in env, f"{job} is in needs but has no env: entry in the aggregator"
            assert f'"${env[job]}"' in loop, (
                f"{job} has an env entry ({env[job]}) that the result loop never reads"
            )


def _aggregator_parts(gate: str) -> tuple[list[str], dict[str, str], str]:
    """Split `frontend / required` into its needs list, env map and result loop.

    Returns the ordered `needs` members, a mapping of job name to the
    environment variable that carries its `result`, and the text of the
    `for result in ...` line.
    """
    needs_match = re.search(r"needs: \[([^\]]+)\]", gate)
    assert needs_match is not None, "the aggregator has no needs list"
    needs = [item.strip() for item in needs_match.group(1).split(",")]

    env: dict[str, str] = {}
    for var, job in re.findall(
        r"^\s+([A-Z0-9_]+): \$\{\{ needs\.([a-z0-9-]+)\.result \}\}", gate, re.M
    ):
        env[job] = var

    loop_match = re.search(r"^\s+for result in (.+); do$", gate, re.M)
    assert loop_match is not None, "the aggregator has no `for result in ...` loop"
    return needs, env, loop_match.group(1)


class TestTheAggregatorInspectsEveryMemberItDeclares:
    """WP08 — a member in `needs` that the loop forgets is an unenforced check.

    `frontend / required` is `if: always()`, so `needs` only sequences the job;
    it does not make a member's failure fail the gate. The failure is detected
    solely by the `for result in ...` loop, and only for members that were
    given an `env:` entry and whose variable that loop actually names. Adding a
    thirteenth member to `needs` and stopping there produces a required check
    that waits for the lane, watches it fail, and reports green.

    The three lists are derived from the published text rather than restated
    here, so this keeps holding for member fourteen without an edit — which is
    the whole reason it is written this way and not as a list of names.
    """

    def test_every_needs_member_has_an_env_entry_the_loop_reads(self) -> None:
        gate = _job_block(_workflow(), "required")
        needs, env, loop = _aggregator_parts(gate)
        members = [job for job in needs if job != "classify"]
        assert members, "the aggregator declares no members besides classify"
        for job in members:
            assert job in env, (
                f"{job} is in the aggregator needs but has no `env:` entry; "
                "its result is never read and its failure cannot fail the gate"
            )
            assert f'"${env[job]}"' in loop, (
                f"{job} maps to {env[job]}, which the result loop never inspects; "
                "this member is a silently unenforced required check"
            )

    def test_the_loop_reads_nothing_that_is_not_a_declared_member(self) -> None:
        """A stale variable in the loop is an unset value, and unset is not success.

        `set -u` is in force, so a variable left in the loop after its job was
        removed from `needs` aborts the gate. That fails closed rather than
        open, but it fails every run, which is a different kind of broken.
        """
        gate = _job_block(_workflow(), "required")
        needs, env, loop = _aggregator_parts(gate)
        declared = {env[job] for job in needs if job in env}
        for var in re.findall(r'"\$([A-Z0-9_]+)"', loop):
            assert var in declared, (
                f"the result loop reads ${var}, which no declared member defines"
            )

    def test_the_classifier_is_checked_by_its_own_branch_not_the_loop(self) -> None:
        """`classify` is in `needs` but must not be in the loop; it has a stricter arm.

        Its failure is caught by the `CLASSIFY != success` check above the
        `case`, which also runs before applicability is read. Folding it into
        the loop would move that check after the `false) exit 0` arm, where a
        crashed classifier would again be able to exit the gate green.
        """
        gate = _job_block(_workflow(), "required")
        _needs, env, loop = _aggregator_parts(gate)
        assert env.get("classify") == "CLASSIFY"
        assert '"$CLASSIFY"' not in loop
        assert gate.index('"${CLASSIFY}" != "success"') < gate.index('case "${APPLICABLE}" in')
