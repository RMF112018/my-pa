"""Frontend CI applicability is a protection control, not a convenience filter.

`frontend / classify` decides whether the heavy frontend jobs run. A regex that
misses a browser-consumed backend path lets a regression merge without
`frontend / required`. A regex that matches every Python file makes every
backend-only change pay for Playwright. This module pins both sides against
the exact pattern currently published in `.github/workflows/frontend-quality.yml`.

It does not run those jobs. It proves the classifier would have marked the
synthetic path sets applicable or not.

Applicability decides *whether* the lanes run; the rest of this module decides
*what they run when they do*, which is the same class of silent failure seen
from the other end. A lane that is scheduled and selects nothing reports green
exactly as a lane that was classified away does. So alongside the classifier
pattern this module pins, against the published workflow text: which specs a
blocking lane names, which Playwright projects CI actually invokes, that the
curated `mobile-webkit` lane stays curated, and that each changed lane proves
its selection before executing it rather than after.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/frontend-quality.yml"


def _published_pattern() -> re.Pattern[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"grep -Eq '(\^\([^']+\))'", text)
    assert match is not None, "frontend / classify grep -Eq pattern is missing"
    return re.compile(match.group(1))


def _applicable(paths: list[str]) -> bool:
    pattern = _published_pattern()
    return any(pattern.search(path) for path in paths)


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["web/src/app/(app)/today/page.tsx"], True),
        (["web/src/contracts/gateway.json"], True),
        (["src/my_pa/contracts/ports.py"], True),
        (["src/my_pa/application/capabilities.py"], True),
        (["tests/contract/test_gateway_capability_catalog.py"], True),
        (["src/my_pa/application/webauthn.py"], True),
        (["src/my_pa/application/session_service.py"], True),
        (["src/my_pa/application/goodnotes.py"], True),
        (["src/my_pa/application/tasks.py"], True),
        (["src/my_pa/application/commitments.py"], True),
        (["src/my_pa/application/intelligence.py"], True),
        (["src/my_pa/application/entity_resolution.py"], True),
        (["src/my_pa/application/identity_history.py"], True),
        (["src/my_pa/application/constraints.py"], True),
        (["src/my_pa/application/constraint_management.py"], True),
        (["src/my_pa/application/constraint_settings.py"], True),
        (["src/my_pa/application/commands.py"], True),
        (["src/my_pa/application/service.py"], True),
        (["src/my_pa/application/authorization.py"], True),
        (["src/my_pa/adapters/mcp/server.py"], True),
        (["src/my_pa/adapters/mcp/tools.py"], True),
        (["src/my_pa/infrastructure/persistence/canvas_workspace.py"], True),
        (["src/my_pa/infrastructure/persistence/task_management.py"], True),
        (["src/my_pa/infrastructure/persistence/constraints.py"], True),
        (["src/my_pa/infrastructure/persistence/capture_search.py"], True),
        (["src/my_pa/infrastructure/persistence/situation_repository.py"], True),
        (["src/my_pa/infrastructure/persistence/tables.py"], True),
        (["src/my_pa/infrastructure/persistence/unit_of_work.py"], True),
        (["src/my_pa/domain/project_controls/settings.py"], True),
        (["src/my_pa/domain/project_controls/business_time.py"], True),
        (["src/my_pa/domain/capture/submission.py"], True),
        (["src/my_pa/domain/situation/situation.py"], True),
        (["src/my_pa/domain/situation/project_history.py"], True),
        (["src/my_pa/domain/task/lifecycle.py"], True),
        (["src/my_pa/domain/relationship/graph.py"], True),
        (["src/my_pa/domain/search/query.py"], True),
        (["src/my_pa/domain/intelligence/reports.py"], True),
        (["migrations/versions/20260906_a1c9e4b72f80_admit_goodnotes_browser_contracts.py"], True),
        (["ops/nas/validate-delivery-config.py"], True),
        (["ops/nas/production-environment.example.env"], True),
        (["ops/nas/compose.public-browser.example.yml"], True),
        (["ops/nas/proxy-public-browser.example.caddy"], True),
        (["docs/decisions/ADR-012-public-browser-cloudflare-tunnel.md"], True),
        (["docs/decisions/ADR-013-fixed-local-principal-and-operator-auth-grants.md"], True),
        (["src/my_pa/domain/identity/auth_grants.py"], True),
        (["src/my_pa/domain/identity/auth_state.py"], True),
        (["src/my_pa/domain/identity/user_account.py"], True),
        (["src/my_pa/infrastructure/persistence/auth_grants.py"], True),
        (["src/my_pa/infrastructure/persistence/auth_state.py"], True),
        (["src/my_pa/infrastructure/persistence/user_accounts.py"], True),
        (["src/my_pa/infrastructure/security/webauthn_ceremony.py"], True),
        (["apps/cli/auth.py"], True),
        (["tests/unit/test_auth_grants.py"], True),
        (["tests/unit/test_auth_state.py"], True),
        (["tests/unit/test_cli_auth.py"], True),
        (["tests/unit/test_user_account_identity.py"], True),
        (["tests/unit/test_webauthn_http.py"], True),
        (["tests/database/test_constraint_read_list.py"], True),
        (["tests/situation/test_continuity.py"], True),
        (["tests/unit/test_task_management_service.py"], True),
        (["tests/schema/test_constraint_management_migration.py"], True),
        (["tests/security/test_cross_principal_capture_isolation.py"], True),
        (["tests/security/test_mcp_surface_controls.py"], True),
        (["tests/policy/test_application_authorization.py"], True),
        (["tests/unit/test_gateway_composition.py"], True),
        ([".github/workflows/frontend-quality.yml"], True),
        # WP08 backend consumer and proof paths, each on its own merit.
        (["tests/capture/test_project_binding.py"], True),
        (["tests/capture/test_conversation_project_lineage.py"], True),
        # FINDING-04: this one selected on no keyword before WP08 — its filename
        # contains neither `capture` as a path remainder keyword nor `project`.
        (["tests/capture/test_conversation_log.py"], True),
        (["tests/unit/test_task_project_assignment.py"], True),
        (["tests/schema/test_project_controls_run01_integrity_migration.py"], True),
        (["tests/unit/test_frontend_ci_classify.py"], True),
        (["src/my_pa/infrastructure/jobs/capture_pipeline.py"], True),
        (["web/src/lib/capture/contract.ts"], True),
        (["web/src/lib/offline/capture-intent-codec.ts"], True),
        (["web/e2e/capture-project.spec.ts"], True),
        # And the negatives the narrow addition must not have widened.
        (["tests/capture/test_display_label.py"], False),
        (["tests/capture/test_idempotency.py"], False),
        (["tests/unit/test_review_policy.py"], False),
        (["tests/capture/test_conversation_log.py.old"], False),
        (["docs/plans/frontend-acceptance-ledger.md"], False),
        (["README.md"], False),
        (["src/my_pa/application/managed_documents.py"], False),
        ([".github/workflows/frontend-quality.yml.old"], False),
        (["src/my_pa/application/service.py.old"], False),
        (["src/my_pa/adapters/mcp/tools.py.old"], False),
        (["src/my_pa/infrastructure/persistence/unit_of_work.py.old"], False),
        (["src/my_pa/domain/situation/project_history.py.old"], False),
        (["tests/database/test_constraint_read_list.py.old"], False),
        (["tests/policy/test_application_authorization.py.old"], False),
        (["tests/security/test_mcp_surface_controls.py.old"], False),
        (["tests/unit/test_gateway_composition.py.old"], False),
    ],
)
def test_frontend_classify_path_sets(paths: list[str], expected: bool) -> None:
    assert _applicable(paths) is expected, paths


def test_unrelated_backend_and_docs_do_not_force_frontend_ci() -> None:
    paths = ["docs/plans/mcv-completion-plan.md", "src/my_pa/application/managed_documents.py"]
    assert _applicable(paths) is False


def test_frontend_only_change_is_applicable() -> None:
    assert _applicable(["web/src/components/shell/command-palette.tsx"]) is True


def test_one_project_controls_backend_change_schedules_frontend_suite() -> None:
    assert _applicable(["src/my_pa/application/constraints.py"]) is True


class TestBlockingGateFailsClosed:
    """F022 — `frontend / required` must not pass on an unresolved applicability.

    The gate used to read `if [[ "${APPLICABLE}" != "true" ]]; then exit 0`.
    Every value other than an exact ``true`` took that branch, including the
    empty string GitHub substitutes when the classifier job was skipped or
    failed. A classifier that crashed therefore reported the one blocking
    frontend check as green, which is the precise opposite of what a required
    check is for.

    These assertions are about the published shell rather than a simulation of
    it, because the defect was a property of the text.
    """

    def _gate(self) -> str:
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index("  required:\n")
        return text[start:]

    def test_the_gate_requires_the_classifier_job_to_have_succeeded(self) -> None:
        gate = self._gate()
        assert "CLASSIFY: ${{ needs.classify.result }}" in gate
        assert '"${CLASSIFY}" != "success"' in gate

    def test_applicability_is_a_closed_vocabulary(self) -> None:
        gate = self._gate()
        # `true` and `false` are the only accepted values; the wildcard arm is
        # what turns an empty or malformed value into a failure.
        assert 'case "${APPLICABLE}" in' in gate
        assert "NOT_APPLICABLE" in gate
        assert "expected 'true' or 'false'" in gate

    def test_the_old_fail_open_comparison_is_gone(self) -> None:
        gate = self._gate()
        assert '"${APPLICABLE}" != "true"' not in gate


class TestApplicabilityUsesEventIdentities:
    """F023 — a push to `main` must not compare a commit against itself.

    `classify` checked out ``github.event.pull_request.head.sha || github.sha``
    and diffed ``origin/main...HEAD``. On a push to `main` the fetched
    `origin/main` *is* that HEAD, so the diff was empty, applicability resolved
    `false`, and the frontend gates classified themselves away on exactly the
    integration event that most needed them.
    """

    def _classify(self) -> str:
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index("      - id: classify")
        return text[start : text.index("  static:")]

    def test_the_self_comparing_diff_is_gone(self) -> None:
        assert "origin/main...HEAD" not in self._classify()

    def test_pull_request_uses_the_event_base_and_head(self) -> None:
        classify = self._classify()
        assert "github.event.pull_request.base.sha" in classify
        assert "github.event.pull_request.head.sha" in classify

    def test_push_uses_the_event_before_and_after(self) -> None:
        classify = self._classify()
        assert "github.event.before" in classify
        assert "github.event.after" in classify

    def test_an_unresolvable_comparison_falls_back_to_applicable(self) -> None:
        classify = self._classify()
        # Zero-before, force-push and shallow-history cases must run the suite
        # rather than silently skip it.
        assert "0000000000000000000000000000000000000000" in classify
        assert 'echo "applicable=true" >> "$GITHUB_OUTPUT"' in classify
        assert 'resolved="false"' in classify


class TestWp07DiagnosticsSpecIsCollected:
    """F024 — a new spec file is not collected by a blocking lane on its own.

    Playwright's default projects match ``**/*.spec.ts``, but the blocking
    `e2e-critical` and `accessibility` lanes each name their specs explicitly.
    A WP07 spec that nothing named would exist, pass locally, and gate nothing.
    """

    def test_named_by_the_blocking_lanes(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        assert text.count("e2e/diagnostics-visibility.spec.ts") >= 2

    def test_the_spec_file_exists(self) -> None:
        assert (REPO / "web/e2e/diagnostics-visibility.spec.ts").is_file()


class TestWp08CaptureProjectSpecsAreCollected:
    """WP08 — four new specs, each named by a lane the gate actually blocks on.

    Playwright's default projects match ``**/*.spec.ts``, so a new spec runs for
    anyone who types `npm run e2e` and gates nothing. Every blocking lane names
    its specs explicitly, so a spec no lane names is free to regress or be
    deleted without a required check noticing. Mirrors the WP07 and
    mobile-foundation guards above.
    """

    SPECS: ClassVar[dict[str, str]] = {
        "e2e/capture-project.spec.ts": "e2e-critical",
        "e2e/capture-task-project.spec.ts": "e2e-critical",
        "e2e/capture-offline-project.spec.ts": "pwa-offline",
        "e2e/capture-project-accessibility.spec.ts": "accessibility",
    }

    @pytest.mark.parametrize("spec", sorted(SPECS))
    def test_the_spec_file_exists(self, spec: str) -> None:
        assert (REPO / "web" / spec).is_file()

    @pytest.mark.parametrize("spec", sorted(SPECS))
    def test_a_required_lane_names_it(self, spec: str) -> None:
        naming = _jobs_naming(spec)
        assert naming, f"no job in the workflow names {spec}"
        blocking = naming & set(_required_needs())
        assert blocking, (
            f"{spec} is named only by {sorted(naming)}, none of which frontend / required waits on"
        )

    @pytest.mark.parametrize(("spec", "job"), sorted(SPECS.items()))
    def test_the_expected_lane_executes_it(self, spec: str, job: str) -> None:
        """Naming it in a sentinel argument alone would prove nothing."""
        block = _without_comments(_job_block(job))
        run_steps = [line for line in block.splitlines() if "npm run e2e --" in line]
        assert run_steps, f"job {job} has no e2e run step"
        assert any(spec in line for line in run_steps), (
            f"{job} does not execute {spec}; it is named only in a non-run step"
        )

    def test_the_capture_route_security_test_is_named_by_the_security_lane(self) -> None:
        block = _without_comments(_job_block("security"))
        assert "src/app/api/capture/project-route.test.ts" in block, (
            "the Capture Project route security test is not named by frontend / security"
        )
        assert (REPO / "web/src/app/api/capture/project-route.test.ts").is_file()

    def test_the_offline_spec_is_in_the_required_pwa_lane(self) -> None:
        """The offline queue's evidence must sit in a lane the gate blocks on."""
        assert "pwa-offline" in set(_required_needs())
        block = _without_comments(_job_block("pwa-offline"))
        assert "e2e/capture-offline-project.spec.ts" in block


def _required_needs() -> list[str]:
    """The members `frontend / required` waits on, in published order."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"name: frontend / required\n\s+needs: \[([^\]]+)\]", text)
    assert match is not None, "frontend / required needs list is missing"
    return [item.strip() for item in match.group(1).split(",")]


def _job_block(job: str) -> str:
    """The published text of one job, from its key to the next job key."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(job)}:\n", text, re.M)
    assert match is not None, f"job {job} is not in the workflow"
    rest = text[match.end() :]
    nxt = re.search(r"^  [a-z0-9-]+:", rest, re.M)
    return text[match.start() : match.end() + (nxt.start() if nxt else len(rest))]


def _without_comments(block: str) -> str:
    """The job block with YAML comment lines removed.

    These assertions read flags out of workflow *text*, and a comment is text.
    The mobile-WebKit exclusion is documented in prose that necessarily quotes
    the flags it is explaining -- `--project=mobile`, `--grep-invert` -- and a
    parser that cannot tell a comment from a command reads that documentation
    as configuration. It did: the projects assertion failed because the comment
    explaining where the invariant is still enforced mentions the lane that
    enforces it. Stripping comments fixes the parser rather than the prose,
    because the prose is correct and worth keeping.
    """
    return "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))


def _jobs_naming(fragment: str) -> set[str]:
    """Every job whose published block contains `fragment`."""
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = re.findall(r"^  ([a-z0-9-]+):$", text, re.M)
    return {job for job in jobs if fragment in _job_block(job)}


class TestWp08MobileFoundationSpecIsCollected:
    """WP08-RT-F001 — the strongest mobile evidence gated nothing.

    `mobile-foundation.spec.ts` carries the WP01-WP05 phone-geometry
    assertions: coarse-pointer control sizing, the 44px target floor, the
    reflow behaviour the brief was written around. Playwright's default
    projects match ``**/*.spec.ts``, so it ran locally and it ran for anyone
    who typed `npm run e2e` — but every blocking lane in `frontend / required`
    names its specs explicitly, and none of them named this one. The file was
    therefore free to regress, or to be deleted, without a single required
    check noticing.

    Mirrors `TestWp07DiagnosticsSpecIsCollected`: the file has to exist, and a
    lane the gate actually blocks on has to name it.
    """

    def test_the_spec_file_exists(self) -> None:
        assert (REPO / "web/e2e/mobile-foundation.spec.ts").is_file()

    def test_a_required_lane_names_it(self) -> None:
        naming = _jobs_naming("e2e/mobile-foundation.spec.ts")
        assert naming, "no job in the workflow names e2e/mobile-foundation.spec.ts"
        required = set(_required_needs())
        blocking = naming & required
        assert blocking, (
            "e2e/mobile-foundation.spec.ts is named only by "
            f"{sorted(naming)}, none of which frontend / required waits on"
        )

    def test_the_naming_lane_actually_executes_it(self) -> None:
        """Naming it in a sentinel argument alone would prove nothing.

        The sentinel step lists the file to `--list` it; the run step is what
        executes it. A lane that verified the selection and then ran a
        different selection would satisfy a laxer assertion than this one.
        """
        required = set(_required_needs())
        executing = {
            job
            for job in _jobs_naming("e2e/mobile-foundation.spec.ts")
            if re.search(
                r"npm run e2e --[^\n]*e2e/mobile-foundation\.spec\.ts",
                _job_block(job),
            )
        }
        assert executing & required, (
            "no required lane passes e2e/mobile-foundation.spec.ts to `npm run e2e`"
        )


class TestMobileWebkitProjectIsInvokedByABlockingLane:
    """WP08-RT-F002 — a Playwright project no workflow ever ran.

    `mobile-webkit` was declared in `playwright.config.ts` and selected by
    nothing: no job passed ``--project=mobile-webkit``, so the WebKit phone
    profile existed as configuration and produced no evidence. A project that
    CI never invokes is indistinguishable from a project that does not work.

    Declaring it is not the claim being protected. The claim is that some job
    runs it and that the gate blocks on that job.
    """

    def test_the_project_is_declared_in_the_playwright_config(self) -> None:
        config = (REPO / "web/playwright.config.ts").read_text(encoding="utf-8")
        assert 'name: "mobile-webkit"' in config

    def test_a_job_passes_the_project_flag(self) -> None:
        assert _jobs_naming("--project=mobile-webkit"), (
            "no job invokes --project=mobile-webkit; the project is dead configuration"
        )

    def test_that_job_is_a_required_gate_member(self) -> None:
        invoking = _jobs_naming("--project=mobile-webkit")
        required = set(_required_needs())
        assert invoking & required, (
            f"--project=mobile-webkit is invoked only by {sorted(invoking)}, "
            "none of which frontend / required waits on"
        )

    def test_the_lane_installs_the_engine_it_claims_to_test(self) -> None:
        """WebKit at phone geometry needs the WebKit browser, not Chromium.

        `npx playwright install chromium` followed by `--project=mobile-webkit`
        fails at launch rather than silently running Chromium, but it fails as
        an infrastructure error in a required lane, which reads as flakiness
        and invites a `continue-on-error` rather than a fix.
        """
        for job in _jobs_naming("--project=mobile-webkit") & set(_required_needs()):
            block = _job_block(job)
            assert "playwright install" in block and "webkit" in block, (
                f"{job} runs --project=mobile-webkit without installing webkit"
            )

    def test_every_webkit_install_carries_with_deps(self) -> None:
        """Downloading WebKit is not the same as being able to launch it.

        `npx playwright install webkit` fetches the browser and nothing else.
        Chromium happens to run anyway on `ubuntu-latest` because its shared
        libraries are already on the image; WebKit's are not, so the lane died
        at `browserType.launch` with `libgtk-4.so.1`, `libgraphene-1.0.so.0`,
        `libevent-2.1.so.7` and the whole GStreamer set missing. Every one of
        the 80 tests failed in two to four milliseconds, before a page existed.

        That failure mode is the dangerous one: it is indistinguishable at a
        glance from the suite being broken, it lands in a *required* lane, and
        the obvious way to quiet it is the `continue-on-error` this package
        exists to remove. The repository already had the answer -- the
        pre-existing `browsers` lane installs `--with-deps firefox webkit` --
        so this asserts the convention rather than leaving the next lane to
        rediscover it by burning a CI cycle.
        """
        text = WORKFLOW.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in text.splitlines()
            if "playwright install" in line and "webkit" in line and "--with-deps" not in line
        ]
        assert offenders == [], (
            "a lane installs webkit without --with-deps, so the browser "
            f"downloads but cannot launch: {offenders}"
        )


class TestTheMobileWebkitLaneStaysCurated:
    """WP08 — the curated lane must not be widened to the whole suite.

    At this head the full suite under `mobile-webkit` collects 121 tests and
    returns 18 failures, none of them a product defect: fourteen come from
    accommodations written as exact-equality guards on the project name, and
    four are harness races. Admitting the whole suite to a *blocking* lane
    would hand the repository a permanently red required check, and the
    pressure that creates is to make the lane advisory again — which would
    destroy the evidence the lane exists to produce.

    So `testMatch` names exactly the two specs whose green is measured and
    repeatable here. Widening it to ``**/*.spec.ts`` to maximise the test count
    must fail this test. Growing the lane by evidence means editing this list
    deliberately, one spec at a time, which is the intended cost.
    """

    CURATED: ClassVar[list[str]] = [
        "**/mobile-foundation.spec.ts",
        "**/diagnostics-visibility.spec.ts",
        # WP08: the Capture Project control is a native `<select>`, whose
        # intrinsics WebKit resolves differently from Chromium. Admitted by name
        # and measured, which is how this list is meant to grow.
        "**/capture-project-accessibility.spec.ts",
    ]

    def _test_match(self) -> str:
        config = (REPO / "web/playwright.config.ts").read_text(encoding="utf-8")
        start = config.index('name: "mobile-webkit"')
        match = re.search(r"^\s+testMatch: (\[[^\]]*\]|\"[^\"]*\"),", config[start:], re.M)
        assert match is not None, "the mobile-webkit project declares no testMatch"
        return match.group(1)

    def test_testmatch_names_exactly_the_curated_specs(self) -> None:
        listed = re.findall(r'"([^"]+)"', self._test_match())
        assert listed == self.CURATED, (
            f"the mobile-webkit testMatch is {listed}, expected exactly {self.CURATED}"
        )

    def test_testmatch_is_not_a_whole_suite_glob(self) -> None:
        listed = re.findall(r'"([^"]+)"', self._test_match())
        for pattern in listed:
            # Each entry must name one spec, not a wildcard over spec names. The
            # leading `**/` is a directory wildcard and is fine; a `*` in the
            # filename itself is how a curated list becomes the whole suite.
            filename = pattern.rsplit("/", 1)[-1]
            assert "*" not in filename, (
                f"the mobile-webkit testMatch entry {pattern!r} wildcards the spec name; "
                "at this head the whole suite is 18 non-product failures in a blocking lane"
            )

    def test_the_lane_runs_only_specs_the_testmatch_admits(self) -> None:
        """A spec the lane passes that `testMatch` excludes selects zero tests.

        Playwright intersects the command-line selection with the project's
        `testMatch` and exits 0 on an empty result, so the mismatch is silent:
        the lane reports green having run nothing for that file.
        """
        admitted = [p.removeprefix("**/") for p in re.findall(r'"([^"]+)"', self._test_match())]
        for job in _jobs_naming("--project=mobile-webkit"):
            run = re.search(r"npm run e2e -- ([^\n]*)--project=mobile-webkit", _job_block(job))
            assert run is not None, job
            for spec in re.findall(r"\S+\.spec\.ts", run.group(1)):
                assert any(spec.endswith(name) for name in admitted), (
                    f"{job} passes {spec} to the mobile-webkit project, whose testMatch "
                    f"admits only {admitted}; that file would select zero tests"
                )


class TestCollectionSentinelsRunBeforeExecution:
    """WP08-RT-F008 — a selection check after the run proves nothing.

    Playwright exits 0 on an empty selection and 0 on a selection that is
    entirely skipped. A renamed spec, a narrowed `testMatch` or a describe
    block that skips itself on every project in the lane therefore leaves the
    lane green while it measures nothing. `verify-e2e-selection.mjs` refuses
    that, and both lanes WP08 changed invoke it.

    Ordering is the entire control. A sentinel step placed after `npm run e2e`
    still verifies the selection, but only after the lane has already reported
    on whatever it did or did not run — and if the run step fails first, the
    sentinel never executes at all. It has to come first.
    """

    CHANGED_LANES = ("responsive", "mobile-webkit-postux")

    def test_the_sentinel_script_exists(self) -> None:
        assert (REPO / "web/scripts/verify-e2e-selection.mjs").is_file()

    def test_each_changed_lane_invokes_the_sentinel(self) -> None:
        for job in self.CHANGED_LANES:
            assert "scripts/verify-e2e-selection.mjs" in _job_block(job), (
                f"{job} changed its selection without a sentinel proving what it selects"
            )

    def test_the_sentinel_precedes_the_run_step_in_each_lane(self) -> None:
        for job in self.CHANGED_LANES:
            block = _job_block(job)
            sentinel = block.index("scripts/verify-e2e-selection.mjs")
            run = block.index("npm run e2e")
            assert sentinel < run, (
                f"{job} invokes verify-e2e-selection.mjs after `npm run e2e`; "
                "a selection proved after execution proves nothing about that execution"
            )

    def test_the_sentinel_verifies_the_projects_the_lane_runs(self) -> None:
        """Verifying a different project than the one executed is the same blind spot.

        The sentinel lists the selection *for the projects it is given*. Given
        `--project=desktop` while the lane runs `--project=mobile-webkit`, it
        would happily pass on a selection the lane never touches.
        """
        for job in self.CHANGED_LANES:
            block = _job_block(job)
            start = block.index("verify-e2e-selection.mjs")
            run_at = block.index("npm run e2e")
            assert start < run_at, f"{job} invokes the sentinel after the run step"
            scan = _without_comments(block[start:run_at])
            verified = set(re.findall(r"--project=([a-z-]+)", scan))
            run_line = re.search(r"npm run e2e -- ([^\n]+)", block)
            assert run_line is not None, job
            executed = set(re.findall(r"--project=([a-z-]+)", run_line.group(1)))
            assert verified == executed, (
                f"{job} verifies projects {sorted(verified)} but executes {sorted(executed)}"
            )

    def test_the_sentinel_declares_every_spec_the_lane_runs(self) -> None:
        """A spec run but not declared to the sentinel is an unverified selection.

        `--file` is both what the sentinel lists and what it requires to
        contribute at least one test, so a spec left out of the `--file` set is
        exactly the spec that can silently select nothing.
        """
        for job in self.CHANGED_LANES:
            block = _job_block(job)
            declared = set(re.findall(r"--file=(\S+\.spec\.ts)", _without_comments(block)))
            run_line = re.search(r"npm run e2e -- ([^\n]+)", block)
            assert run_line is not None, job
            executed = set(re.findall(r"(e2e/\S+\.spec\.ts)", run_line.group(1)))
            assert executed <= declared, (
                f"{job} runs {sorted(executed - declared)} without declaring them to "
                "the selection sentinel"
            )


class TestTheMobileWebkitExclusionIsExactlyOneNamedTest:
    """WP08 — the one assertion this lane does not run, pinned by name.

    `an ordinary active row sits under the rhythm ceiling` is excluded from the
    mobile-WebKit lane, and the reason is measured rather than asserted. The row
    is 164.0px under Chromium on the CI image and under both engines on macOS,
    and 212.0px under WebKit on that same image. Fontconfig there resolves every
    family in `--font-sans` to DejaVu Sans -- no Apple face is installed -- and
    WebKit sizes a `<select>` from the resolved font, so the Status control is
    142px rather than 116px, its band overflows the 332px row and reflows onto a
    second 44px line. 212 - 164 = 48 is that wrapped band; the title reports
    `lineBoxes: 1` identically everywhere and never wrapped.

    **Why this guard exists at all.** An exclusion is a bypass with a good
    reason attached, and the reason does not travel. Once `--grep-invert` is in
    a lane, the next red test has both a precedent and a mechanism, and the
    second exclusion will not get the scrutiny the first one did. So the shape
    is pinned: exactly one lane may exclude, exactly one test by that exact
    name, and the assertion must still be enforced somewhere that can measure
    it. Widening the exclusion fails here rather than passing quietly.
    """

    EXCLUDED: ClassVar[str] = "an ordinary active row sits under the rhythm ceiling"

    def test_only_the_mobile_webkit_lane_excludes_anything(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        assert text.count("--grep-invert") == 1, (
            "exactly one lane may exclude a test by name; a second exclusion "
            "must be argued on its own evidence, not inherited from this one"
        )
        assert "--grep-invert" in _job_block("mobile-webkit-postux")

    def test_it_excludes_that_one_test_and_no_other(self) -> None:
        block = _job_block("mobile-webkit-postux")
        found = re.findall(r'--grep-invert\s+"([^"]+)"', block)
        assert found == [self.EXCLUDED], (
            f"the mobile-webkit exclusion must be exactly {self.EXCLUDED!r}, got {found!r}"
        )
        # A regex alternation would widen the exclusion while still matching a
        # single --grep-invert, so the pattern must be a plain literal.
        for metacharacter in ("|", "*", "+", ".*", "(", "["):
            assert metacharacter not in self.EXCLUDED, metacharacter

    def test_the_excluded_test_actually_exists(self) -> None:
        """An exclusion naming nothing would silently exclude nothing."""
        spec = (REPO / "web/e2e/mobile-foundation.spec.ts").read_text(encoding="utf-8")
        assert f'test("{self.EXCLUDED}"' in spec, (
            f"{self.EXCLUDED!r} is excluded by name but no test declares that title"
        )

    def test_the_assertion_is_still_gated_by_a_lane_that_can_measure_it(self) -> None:
        """The invariant must lose an engine, not its enforcement.

        `responsive` runs the same spec under `--project=mobile` at the same
        390px and enforces the same ceiling, on Chromium, where the control
        intrinsic does not depend on the absent font. If that lane ever stops
        running the spec, or starts excluding things itself, this exclusion
        stops being a duplicate and starts being a hole.
        """
        responsive = _without_comments(_job_block("responsive"))
        # The *run* command, not the job block: the sentinel also names this
        # spec in a --file argument, so a block-wide substring check passes on
        # a lane that has stopped executing it. A perturbation that removed the
        # spec from the command and left the sentinel argument in place slipped
        # through exactly that way.
        run_line = re.search(r"npm run e2e -- ([^\n]+)", responsive)
        assert run_line is not None, "responsive has no run command"
        command = run_line.group(1)
        assert "e2e/mobile-foundation.spec.ts" in command, (
            "responsive no longer executes mobile-foundation.spec.ts, so the "
            "mobile-webkit exclusion is a coverage hole rather than a duplicate"
        )
        assert "--project=mobile" in command
        assert "--grep-invert" not in command
        assert "responsive" in _required_needs()
