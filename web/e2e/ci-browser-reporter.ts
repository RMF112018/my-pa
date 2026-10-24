import path from "node:path";
import type { Reporter, TestCase, TestError, TestResult, TestStep } from "@playwright/test/reporter";

// Exact declarations/assertion locations in the two advisory critical-path specs.
// No messages, titles, cookies, request/response data or attachment content is read.
const SPECS = [
  { name: "browser-security.spec.ts", declarations: [82, 108, 120, 133, 152, 170, 192, 211],
    assertions: [22, 23, 24, 64, 65, 67, 74, 104, 105, 115, 116, 117, 226, 228] },
  { name: "search-contract.spec.ts", declarations: [60, 109, 165, 201, 249, 321, 369],
    assertions: [64, 65, 69, 70, 71, 73, 75, 76, 77, 82, 83, 85, 86, 87, 88, 91, 92, 96, 97, 99, 100, 104, 106, 112, 114, 122, 123, 124, 125, 132, 133, 134, 135, 136, 139, 170, 172, 173, 175, 176, 177, 179, 180, 181, 182, 184, 186, 188, 191, 192, 193, 195, 196, 197, 198, 242, 244, 245, 298, 299, 302, 303, 304, 305, 306, 307, 311, 312, 313, 314, 315, 316, 317, 327, 328, 329, 343, 345, 346, 381, 386, 388, 451, 455, 456, 457, 458, 461, 467, 468, 469, 477, 478, 479, 484, 489, 491, 492, 493, 494, 498, 504, 505] },
];
const PROJECTS = new Set(["firefox", "webkit"]);
const FAILED = new Set(["failed", "timedOut", "interrupted"]);
const SIGN_IN_STAGES = new Set(["goto", "overlay", "signinbutton", "click", "todayURL", "launcher"]);
const BROWSER_PHASES = ["emulateMedia-failed", "after-emulateMedia", "before-emulateMedia", "page-ready", "early-entered"];
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
    const phase = BROWSER_PHASES.find((value) => (result.annotations ?? []).some((item) =>
      item.type === "my-pa-ci-browser-phase" && item.description === value));
    const category = signIn || phase === "emulateMedia-failed" ? "setup" : assertion !== undefined ? "assertion"
      : completed ? "after-sign-in" : steps.some((step) => step.category === "hook" && !!step.error) ? "setup" : "other";
    const stage = signIn ? `; stage=${signIn}; status=${result.status}` : "";
    const boundary = phase ? `; phase=${phase}` : "";
    this.emitted += 1;
    process.stdout.write(`::error file=web/e2e/${spec.name},line=${assertion ?? test.location.line},title=Browser Playwright failure::project=${project}; category=${category}${stage}${boundary}\n`);
  }

  onError(_error: TestError): void {
    if (this.emitted >= 10) return;
    this.emitted += 1;
    process.stdout.write("::error title=Browser Playwright failure::category=setup\n");
  }
}
