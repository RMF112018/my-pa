import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, "ci-visual-reporter.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { default: VisualCiReporter, failureCategory } = await import(
  `data:text/javascript,${encodeURIComponent(compiled)}`
);
const file = path.join(process.cwd(), "e2e", "visual.spec.ts");
const caseFor = (overrides = {}) => ({
  expectedStatus: "passed", parent: { project: () => ({ name: "desktop" }) },
  location: { file, line: 18 }, ...overrides,
});
const resultFor = (overrides = {}) => ({
  status: "failed", attachments: [], steps: [{ category: "expect", error: {},
    location: { file, line: 20 }, steps: [] }], ...overrides,
});
function capture(run) {
  const chunks = [];
  const original = process.stdout.write;
  process.stdout.write = (chunk) => { chunks.push(String(chunk)); return true; };
  try { run(); } finally { process.stdout.write = original; }
  return chunks.join("");
}

test("post-test absence stays unknown while evidenced mismatch and setup remain distinct", () => {
  assert.equal(failureCategory(resultFor(), 20, "shell-light-unavailable", false), "other");
  const attachments = ["expected", "actual", "diff"].map((kind) => ({ name: `shell-light-unavailable-${kind}.png` }));
  assert.equal(failureCategory(resultFor({ attachments }), 20, "shell-light-unavailable", true), "snapshot-mismatch");
  assert.equal(failureCategory(resultFor(), 20, "shell-light-unavailable", true), "other");
  assert.equal(failureCategory(resultFor({ steps: [{ category: "hook", error: {}, steps: [] }] }), 20, "shell-light-unavailable", false), "setup");
  assert.equal(failureCategory(resultFor({ steps: [] }), 20, "shell-light-unavailable", false), "other");
});

test("only a unique matching case witness can establish the baseline creation pattern", () => {
  for (const [id, line] of [["light", 18], ["dark", 27], ["launcher", 60], ["zoom", 72]]) {
    for (const [outcome, category] of [["absent-created-error", "missing-baseline"],
      ["hard-throw", "assertion-hard-throw"], ["matched-no-delta", "after-snapshot"], ["unknown", "other"]]) {
      const output = capture(() => new VisualCiReporter().onTestEnd(caseFor({ location: { file, line } }), resultFor({
        steps: [], annotations: [{ type: "my-pa-ci-visual-witness", description: `${id}:${outcome}` }],
      })));
      assert.match(output, new RegExp(`category=${category}; witness=${outcome}\\n$`));
    }
  }
});

test("unknown, foreign, duplicate and conflicting witnesses cannot claim a baseline cause", () => {
  for (const descriptions of [["other:absent-created-error"], ["light:SECRET\n::error::x"],
    ["light:absent-created-error", "light:hard-throw"], ["light:absent-created-error", "light:absent-created-error"]]) {
    const output = capture(() => new VisualCiReporter().onTestEnd(caseFor(), resultFor({ steps: [],
      annotations: descriptions.map((description) => ({ type: "my-pa-ci-visual-witness", description })),
    })));
    assert.equal(output.includes("witness="), false);
    assert.equal(output.includes("SECRET"), false);
    assert.equal(output.includes("category=missing-baseline"), false);
  }
});

test("missing files alone do not misclassify an earlier assertion or foreign step", () => {
  for (const location of [{ file, line: 19 }, { file: `${file}\n::error::x`, line: 20 }]) {
    assert.equal(failureCategory(resultFor({ steps: [{ category: "expect", error: {}, location, steps: [] }] }), 20, "shell-light-unavailable", false), "other");
  }
});

test("does not infer baseline cause from a post-test location and absence", () => {
  const soft = resultFor({ steps: [], errors: [{ location: { file, line: 20 } }] });
  assert.equal(failureCategory(soft, 20, "shell-light-unavailable", false), "other");
  assert.equal(failureCategory(soft, 20, "shell-light-unavailable", true), "other");
  for (const location of [{ file, line: 19 }, { file: `${file}\n::error::x`, line: 20 }]) {
    assert.equal(failureCategory(resultFor({ steps: [], errors: [{ location }] }), 20, "shell-light-unavailable", false), "other");
  }
});

test("emits only fixed test identity/category and never secret error data", () => {
  const secret = "SYNTHETIC_PRIVATE_HEADER_BODY_URL\n::error::injected";
  const forbidden = new Proxy({}, { get(_target, key) {
    if (key === "location") return undefined;
    throw new Error("raw error content accessed");
  } });
  const output = capture(() => {
    const reporter = new VisualCiReporter();
    reporter.onTestEnd(caseFor({ title: secret, id: secret }), resultFor({
      errors: [forbidden], stdout: [secret], stderr: [secret],
      attachments: [{ name: secret, body: secret }],
      steps: [{ category: "expect", error: forbidden, location: { file, line: 20 }, steps: [] }],
    }));
    reporter.onError(forbidden);
  });
  assert.match(output, /^::error file=web\/e2e\/visual.spec.ts,line=18,title=Visual Playwright failure::project=desktop; category=(missing-baseline|other)\n::error title=Visual Playwright failure::category=setup\n$/);
  assert.equal(output.includes(secret), false);
});

test("refuses unknown spec, project, declaration and nonfailure results", () => {
  for (const candidate of [caseFor({ location: { file: `${file}\n::error::x`, line: 17 } }),
    caseFor({ location: { file, line: 19 } }), caseFor({ expectedStatus: "failed" }),
    caseFor({ parent: { project: () => ({ name: "desktop\n::error::x" }) } })]) {
    assert.equal(capture(() => new VisualCiReporter().onTestEnd(candidate, resultFor())), "");
  }
  for (const status of ["passed", "skipped", "failed\n::error::x"]) {
    assert.equal(capture(() => new VisualCiReporter().onTestEnd(caseFor(), resultFor({ status }))), "");
  }
});

test("caps annotations without altering test outcomes", () => {
  const reporter = new VisualCiReporter();
  const result = resultFor();
  const output = capture(() => {
    for (let index = 0; index < 10; index++) reporter.onTestEnd(caseFor(), result);
    reporter.onError({});
  });
  assert.equal(output.trim().split("\n").length, 4);
  assert.equal(result.status, "failed");
});

test("admits only fixed runtime stage metadata and treats completion as after sign-in", () => {
  for (const stage of ["goto", "overlay", "signinbutton", "click", "todayURL", "launcher"]) {
    const output = capture(() => new VisualCiReporter().onTestEnd(caseFor(), resultFor({
      steps: [], annotations: [{ type: "my-pa-ci-failed-stage", description: stage }],
    })));
    assert.match(output, new RegExp(`category=setup; stage=${stage}; status=failed\\n$`));
  }
  const complete = capture(() => new VisualCiReporter().onTestEnd(caseFor(), resultFor({
    steps: [], annotations: [{ type: "my-pa-ci-signin-complete", description: "complete" }],
  })));
  assert.match(complete, /category=after-sign-in\n$/);
  assert.equal(complete.includes("stage="), false);
  for (const annotation of [{ type: "unknown", description: "goto" },
    { type: "my-pa-ci-failed-stage", description: "goto\n::error::SECRET" },
    { type: "my-pa-ci-signin-complete", description: "SECRET" }]) {
    const output = capture(() => new VisualCiReporter().onTestEnd(caseFor(), resultFor({ steps: [], annotations: [annotation] })));
    assert.match(output, /category=other\n$/);
    assert.equal(output.includes("SECRET"), false);
  }
});
