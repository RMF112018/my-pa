import path from "node:path";
import type { Reporter, TestCase, TestError, TestResult, TestStep } from "@playwright/test/reporter";

// Exact declarations/assertion locations in the two advisory critical-path specs.
// No messages, titles, cookies, request/response data or attachment content is read.
const SPECS = [
  { name: "browser-security.spec.ts", declarations: [82, 108, 120, 133, 152, 170, 192, 211],
    assertions: [22, 23, 24, 64, 65, 67, 74, 104, 105, 115, 116, 117, 226, 228] },
  { name: "search-contract.spec.ts", declarations: [60, 109, 137, 173, 221, 293, 341],
    assertions: [64, 65, 69, 70, 71, 73, 75, 76, 77, 82, 83, 85, 86, 87, 88, 91, 92, 96, 97, 99, 100, 104, 106, 142, 144, 145, 147, 148, 149, 151, 152, 153, 154, 156, 158, 160, 163, 164, 165, 167, 168, 169, 170, 214, 216, 217, 270, 271, 274, 275, 276, 277, 278, 279, 283, 284, 285, 286, 287, 288, 289, 299, 300, 301, 315, 317, 318, 353, 358, 360, 423, 427, 428, 429, 430, 433, 439, 440, 441, 449, 450, 451, 456, 461, 463, 464, 465, 466, 470, 476, 477, 527, 531, 540, 541, 542, 543, 551, 552, 553, 554, 555, 559] },
];
const PROJECTS = new Set(["firefox", "webkit"]);
const FAILED = new Set(["failed", "timedOut", "interrupted"]);
const SIGN_IN_STAGES = new Set(["goto", "overlay", "signinbutton", "click", "todayURL", "launcher"]);
const BROWSER_PHASES = ["emulateMedia-failed", "after-emulateMedia", "before-emulateMedia", "page-ready", "early-entered"];
const SEARCH_PHASES = ["nav", "heading", "query", "search-settled", "capture-links", "goodnotes-links", "knowledge-absence"];
const ACTIVE_SEARCH_DECLARATION = 109;
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
    const searchRecords = (result.annotations ?? []).filter((item) => item.type === "my-pa-ci-search-active");
    const search = spec.name === "search-contract.spec.ts" && test.location.line === ACTIVE_SEARCH_DECLARATION && searchRecords.length === 1
      ? SEARCH_PHASES.flatMap((value) => ["inflight", "failed", "complete"].map((state) => ({ value, state })))
        .find((entry) => searchRecords[0].description === `${entry.value}:${entry.state}`) : undefined;
    const snapshots = (result.annotations ?? []).filter((item) => item.type === "my-pa-ci-search-snapshot");
    const snapshot = project === "webkit" && search?.value === "search-settled" && search.state === "failed" && snapshots.length === 1
      && /^(?:q[01]-i[01]-b[01]-s[01]|unavailable)$/.test(snapshots[0].description ?? "") ? snapshots[0].description : undefined;
    const category = search ? (search.state === "complete" ? "after-search" : "search-phase")
      : signIn || phase === "emulateMedia-failed" ? "setup" : assertion !== undefined ? "assertion"
      : completed ? "after-sign-in" : steps.some((step) => step.category === "hook" && !!step.error) ? "setup" : "other";
    const stage = signIn ? `; stage=${signIn}; status=${result.status}` : "";
    const boundary = phase ? `; phase=${phase}` : "";
    const active = search ? `; active=${search.value}; state=${search.state}` : "";
    const observation = snapshot ? `; snapshot=${snapshot}` : "";
    this.emitted += 1;
    process.stdout.write(`::error file=web/e2e/${spec.name},line=${assertion ?? test.location.line},title=Browser Playwright failure::project=${project}; category=${category}${stage}${boundary}${active}${observation}\n`);
  }

  onError(_error: TestError): void {
    if (this.emitted >= 10) return;
    this.emitted += 1;
    process.stdout.write("::error title=Browser Playwright failure::category=setup\n");
  }
}
