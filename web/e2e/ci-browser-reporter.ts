import path from "node:path";
import type { Reporter, TestCase, TestError, TestResult, TestStep } from "@playwright/test/reporter";

// Exact declarations/assertion locations in the two advisory critical-path specs.
// No messages, titles, cookies, request/response data or attachment content is read.
const SPECS = [
  { name: "browser-security.spec.ts", declarations: [78, 104, 116, 129, 148, 166, 188, 207],
    assertions: [18, 19, 20, 60, 61, 63, 70, 100, 101, 111, 112, 113, 222, 224] },
  { name: "search-contract.spec.ts", declarations: [56, 105, 161, 197, 245, 317, 365],
    assertions: [60, 61, 65, 66, 67, 69, 71, 72, 73, 78, 79, 81, 82, 83, 84, 87, 88, 92, 93, 95, 96, 100, 102, 108, 110, 118, 119, 120, 121, 128, 129, 130, 131, 132, 135, 166, 168, 169, 171, 172, 173, 175, 176, 177, 178, 180, 182, 184, 187, 188, 189, 191, 192, 193, 194, 238, 240, 241, 294, 295, 298, 299, 300, 301, 302, 303, 307, 308, 309, 310, 311, 312, 313, 323, 324, 325, 339, 341, 342, 377, 382, 384, 447, 451, 452, 453, 454, 457, 463, 464, 465, 473, 474, 475, 480, 485, 487, 488, 489, 490, 494, 500, 501] },
];
const PROJECTS = new Set(["firefox", "webkit"]);
const FAILED = new Set(["failed", "timedOut", "interrupted"]);
const SIGN_IN_STAGES = new Set(["goto", "signinbutton", "click", "todayURL", "launcher"]);
function stepsOf(steps: TestStep[]): TestStep[] {
  return steps.flatMap((step) => [step, ...stepsOf(step.steps)]);
}

export default class BrowserCiReporter implements Reporter {
  private emitted = 0;

  onTestEnd(test: TestCase, result: TestResult): void {
    if (this.emitted >= 10 || test.expectedStatus !== "passed" || !FAILED.has(result.status)) return;
    const project = test.parent?.project()?.name;
    if (!project || !PROJECTS.has(project)) return;
    const spec = SPECS.find((entry) => test.location?.file === path.join(process.cwd(), "e2e", entry.name)
      && entry.declarations.includes(test.location.line));
    if (!spec) return;
    const steps = stepsOf(result.steps ?? []);
    const locations = [
      ...steps.filter((step) => !!step.error).map((step) => step.location),
      ...(result.errors ?? []).map((error) => error.location),
    ];
    const assertion = spec.assertions.find((line) => locations.some((location) =>
      location?.file === test.location.file && location.line === line));
    const signIn = (result.annotations ?? []).find((item) => item.type === "my-pa-ci-failed-stage"
      && item.description !== undefined && SIGN_IN_STAGES.has(item.description))?.description;
    const completed = (result.annotations ?? []).some((item) => item.type === "my-pa-ci-signin-complete"
      && item.description === "complete");
    const category = signIn ? "setup" : assertion !== undefined ? "assertion"
      : completed ? "after-sign-in" : steps.some((step) => step.category === "hook" && !!step.error) ? "setup" : "other";
    const stage = signIn ? `; stage=${signIn}; status=${result.status}` : "";
    this.emitted += 1;
    process.stdout.write(`::error file=web/e2e/${spec.name},line=${assertion ?? test.location.line},title=Browser Playwright failure::project=${project}; category=${category}${stage}\n`);
  }

  onError(_error: TestError): void {
    if (this.emitted >= 10) return;
    this.emitted += 1;
    process.stdout.write("::error title=Browser Playwright failure::category=setup\n");
  }
}
