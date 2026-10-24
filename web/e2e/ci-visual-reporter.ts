import { existsSync } from "node:fs";
import path from "node:path";
import type { Reporter, TestCase, TestError, TestResult, TestStep } from "@playwright/test/reporter";

const SPEC = "web/e2e/visual.spec.ts";
const absoluteSpec = () => path.join(process.cwd(), "e2e", "visual.spec.ts");
const CASES = [
  { id: "light", declaration: 18, assertion: 21, snapshot: "shell-light-unavailable" },
  { id: "dark", declaration: 27, assertion: 54, snapshot: "shell-dark-inspector" },
  { id: "launcher", declaration: 60, assertion: 66, snapshot: "shell-command-menu" },
  { id: "zoom", declaration: 72, assertion: 95, snapshot: "shell-zoom-200" },
] as const;
const FAILED = new Set(["failed", "timedOut", "interrupted"]);
const SIGN_IN_STAGES = new Set(["goto", "overlay", "signinbutton", "click", "todayURL", "launcher"]);

function stepsOf(steps: TestStep[]): TestStep[] {
  return steps.flatMap((step) => [step, ...stepsOf(step.steps)]);
}

/** Classify structured locations only; never inspect an exception or attachment body. */
export function failureCategory(
  result: TestResult, assertion: number, snapshot: string, baselineExists: boolean,
): "snapshot-mismatch" | "setup" | "other" {
  const steps = stepsOf(result.steps ?? []);
  const snapshotFailed = steps.some((step) => step.category === "expect" && !!step.error
    && step.location?.file === absoluteSpec() && step.location.line === assertion);
  if (snapshotFailed) {
    if (!baselineExists) return "other";
    const names = new Set(result.attachments.map((attachment) => attachment.name));
    if (["expected", "actual", "diff"].every((kind) => names.has(`${snapshot}-${kind}.png`))) {
      return "snapshot-mismatch";
    }
    return "other";
  }
  return steps.some((step) => step.category === "hook" && !!step.error) ? "setup" : "other";
}

/** Opt-in Linux visual lane only: four fixed, bounded annotations and no raw errors. */
export default class VisualCiReporter implements Reporter {
  private emitted = 0;

  onTestEnd(test: TestCase, result: TestResult): void {
    if (this.emitted >= 4 || test.expectedStatus !== "passed" || !FAILED.has(result.status)) return;
    if (test.parent?.project()?.name !== "desktop" || test.location?.file !== absoluteSpec()) return;
    const admitted = CASES.find((entry) => entry.declaration === test.location.line);
    if (!admitted) return;
    const baseline = path.join(process.cwd(), "e2e", "visual.spec.ts-snapshots",
      `${admitted.snapshot}-desktop-linux.png`);
    const structural = failureCategory(result, admitted.assertion, admitted.snapshot, existsSync(baseline));
    const signIn = (result.annotations ?? []).find((item) => item.type === "my-pa-ci-failed-stage"
      && item.description !== undefined && SIGN_IN_STAGES.has(item.description))?.description;
    const completed = (result.annotations ?? []).some((item) => item.type === "my-pa-ci-signin-complete"
      && item.description === "complete");
    const observations = (result.annotations ?? []).filter((item) => item.type === "my-pa-ci-visual-witness");
    const witness = observations.length === 1
      ? ["absent-created-error", "hard-throw", "matched-no-delta", "unknown"].find((outcome) =>
        observations[0].description === `${admitted.id}:${outcome}`) : undefined;
    const category = witness === "absent-created-error" ? "missing-baseline"
      : witness === "hard-throw" ? "assertion-hard-throw"
        : witness === "matched-no-delta" ? "after-snapshot"
          : signIn ? "setup" : completed && (structural === "setup" || structural === "other")
            ? "after-sign-in" : structural;
    const stage = signIn ? `; stage=${signIn}; status=${result.status}` : "";
    const observation = witness ? `; witness=${witness}` : "";
    this.emitted += 1;
    process.stdout.write(`::error file=${SPEC},line=${admitted.declaration},title=Visual Playwright failure::project=desktop; category=${category}${stage}${observation}\n`);
  }

  onError(_error: TestError): void {
    if (this.emitted >= 4) return;
    this.emitted += 1;
    process.stdout.write("::error title=Visual Playwright failure::category=setup\n");
  }
}
