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
  location: { file, line: 17 }, ...overrides,
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

test("distinguishes missing platform baseline, evidenced mismatch, setup and other", () => {
  assert.equal(failureCategory(resultFor(), 20, "shell-light-unavailable", false), "missing-baseline");
  const attachments = ["expected", "actual", "diff"].map((kind) => ({ name: `shell-light-unavailable-${kind}.png` }));
  assert.equal(failureCategory(resultFor({ attachments }), 20, "shell-light-unavailable", true), "snapshot-mismatch");
  assert.equal(failureCategory(resultFor(), 20, "shell-light-unavailable", true), "other");
  assert.equal(failureCategory(resultFor({ steps: [{ category: "hook", error: {}, steps: [] }] }), 20, "shell-light-unavailable", false), "setup");
  assert.equal(failureCategory(resultFor({ steps: [] }), 20, "shell-light-unavailable", false), "other");
});

test("missing files alone do not misclassify an earlier assertion or foreign step", () => {
  for (const location of [{ file, line: 19 }, { file: `${file}\n::error::x`, line: 20 }]) {
    assert.equal(failureCategory(resultFor({ steps: [{ category: "expect", error: {}, location, steps: [] }] }), 20, "shell-light-unavailable", false), "other");
  }
});

test("classifies located missing-baseline soft errors without an errored step", () => {
  const soft = resultFor({ steps: [], errors: [{ location: { file, line: 20 } }] });
  assert.equal(failureCategory(soft, 20, "shell-light-unavailable", false), "missing-baseline");
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
  assert.match(output, /^::error file=web\/e2e\/visual.spec.ts,line=17,title=Visual Playwright failure::project=desktop; category=(missing-baseline|other)\n::error title=Visual Playwright failure::category=setup\n$/);
  assert.equal(output.includes(secret), false);
});

test("refuses unknown spec, project, declaration and nonfailure results", () => {
  for (const candidate of [caseFor({ location: { file: `${file}\n::error::x`, line: 17 } }),
    caseFor({ location: { file, line: 18 } }), caseFor({ expectedStatus: "failed" }),
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
