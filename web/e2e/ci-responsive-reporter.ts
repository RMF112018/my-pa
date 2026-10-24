import path from "node:path";
import type { Reporter, TestCase, TestError, TestResult } from "@playwright/test/reporter";

const PROJECTS = new Set(["desktop", "tablet", "mobile"]);
const SPECS = [
  "work-acceptance.spec.ts",
  "today-tasks.spec.ts",
  "journeys.spec.ts",
  "intelligence-journey.spec.ts",
  "constraints-read-plane.spec.ts",
  "mobile-foundation.spec.ts",
] as const;
const FAILURE_STATUSES = new Set(["failed", "timedOut", "interrupted"]);
const MAX_ANNOTATIONS = 10;
const MAX_LINE = 100_000;
const SIGN_IN_STAGES = new Set(["goto", "overlay", "signinbutton", "click", "todayURL", "launcher"]);
const CONSTRAINT_STAGES = new Set(["nav", "URL-state", "loading", "unavailable", "row-visible"]);

/** CI-only, bounded annotations. Never interpolate a title, error, or raw path. */
export default class ResponsiveCiReporter implements Reporter {
  private emitted = 0;

  onTestEnd(test: TestCase, result: TestResult): void {
    if (this.emitted >= MAX_ANNOTATIONS || test.expectedStatus !== "passed") return;

    const project = test.parent?.project()?.name;
    const status = result.status;
    const file = test.location?.file;
    const line = test.location?.line;
    if (!project || !PROJECTS.has(project) || !FAILURE_STATUSES.has(status)) return;
    if (!Number.isSafeInteger(line) || line < 1 || line > MAX_LINE) return;

    // Equality to a constructed path rejects traversal, control characters,
    // alternate directories, and unknown specs without printing input paths.
    const spec = SPECS.find((name) => file === path.join(process.cwd(), "e2e", name));
    if (!spec) return;

    const signIn = (result.annotations ?? []).find((item) => item.type === "my-pa-ci-failed-stage"
      && item.description !== undefined && SIGN_IN_STAGES.has(item.description))?.description;
    const route = spec === "journeys.spec.ts" && line === 634
      ? (result.annotations ?? []).find((item) => item.type === "my-pa-ci-constraint-stage"
        && item.description !== undefined && CONSTRAINT_STAGES.has(item.description))?.description
      : undefined;
    const completed = (result.annotations ?? []).some((item) => item.type === "my-pa-ci-signin-complete"
      && item.description === "complete");
    const detail = signIn ? `; category=setup; stage=${signIn}`
      : route ? `; category=constraint-route; stage=${route}`
        : completed ? "; category=after-sign-in" : "";

    this.emitted += 1;
    process.stdout.write(
      `::error file=web/e2e/${spec},line=${line},title=Responsive Playwright failure::project=${project}; status=${status}${detail}\n`,
    );
  }

  onError(_error: TestError): void {
    if (this.emitted >= MAX_ANNOTATIONS) return;
    this.emitted += 1;
    process.stdout.write("::error title=Responsive Playwright failure::phase=playwright-global\n");
  }
}
