import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "ci-browser-reporter.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { default: BrowserCiReporter } = await import(`data:text/javascript,${encodeURIComponent(compiled)}`);
const file = (spec) => path.join(process.cwd(), "e2e", spec);
const caseFor = (spec = "browser-security.spec.ts", line = 78, project = "firefox") => ({
  expectedStatus: "passed", parent: { project: () => ({ name: project }) }, location: { file: file(spec), line },
});
const resultFor = (spec = "browser-security.spec.ts", line = 60) => ({
  status: "failed", steps: [{ category: "expect", error: {}, location: { file: file(spec), line }, steps: [] }],
});
function capture(run) {
  const chunks = [];
  const original = process.stdout.write;
  process.stdout.write = (chunk) => { chunks.push(String(chunk)); return true; };
  try { run(); } finally { process.stdout.write = original; }
  return chunks.join("");
}

test("emits only admitted spec/project/assertion identities", () => {
  for (const project of ["firefox", "webkit"]) {
    for (const [spec, declaration, assertion] of [["browser-security.spec.ts", 78, 60], ["search-contract.spec.ts", 56, 61]]) {
      assert.equal(capture(() => new BrowserCiReporter().onTestEnd(caseFor(spec, declaration, project), resultFor(spec, assertion))),
        `::error file=web/e2e/${spec},line=${assertion},title=Browser Playwright failure::project=${project}; category=assertion\n`);
    }
  }
});

test("unknown assertions stay other; hook failures are setup", () => {
  assert.match(capture(() => new BrowserCiReporter().onTestEnd(caseFor(), resultFor("browser-security.spec.ts", 999))), /line=78,.*category=other/);
  assert.match(capture(() => new BrowserCiReporter().onTestEnd(caseFor(), { status: "failed", steps: [{ category: "hook", error: {}, steps: [] }] })), /category=setup/);
});

test("uses only admitted structured error locations for assertion fallback", () => {
  for (const location of [{ file: file("browser-security.spec.ts"), line: 60 },
    { file: file("browser-security.spec.ts"), line: 999 },
    { file: `${file("browser-security.spec.ts")}\n::error::x`, line: 60 }]) {
    const output = capture(() => new BrowserCiReporter().onTestEnd(caseFor(), {
      status: "failed", steps: [], errors: [{ location }],
    }));
    assert.equal(output.includes("category=assertion"), location.line === 60 && location.file === file("browser-security.spec.ts"));
  }
});

test("reports only fixed admitted runtime sign-in stages and failure statuses", () => {
  for (const stage of ["goto", "signinbutton", "click", "todayURL", "launcher"]) {
    const output = capture(() => new BrowserCiReporter().onTestEnd(caseFor(), {
      status: "timedOut", steps: [], annotations: [{ type: "my-pa-ci-failed-stage", description: stage }],
    }));
    assert.match(output, new RegExp(`category=setup; stage=${stage}; status=timedOut\\n$`));
  }
  for (const location of [{ file: file("fixtures.ts"), line: 56 }, { file: `${file("fixtures.ts")}\n::error::x`, line: 54 }]) {
    const output = capture(() => new BrowserCiReporter().onTestEnd(caseFor(), { status: "failed", steps: [], errors: [{ location }] }));
    assert.match(output, /category=other\n$/);
    assert.equal(output.includes("stage="), false);
  }
});

test("completion means a later failure, and unknown metadata never becomes output", () => {
  const completed = capture(() => new BrowserCiReporter().onTestEnd(caseFor(), {
    status: "failed", steps: [], annotations: [{ type: "my-pa-ci-signin-complete", description: "complete" }],
  }));
  assert.match(completed, /category=after-sign-in\n$/);
  assert.equal(completed.includes("stage="), false);
  for (const annotation of [{ type: "unknown", description: "click" },
    { type: "my-pa-ci-failed-stage", description: "click\n::error::SECRET" },
    { type: "my-pa-ci-signin-complete", description: "SECRET" }]) {
    const output = capture(() => new BrowserCiReporter().onTestEnd(caseFor(), { status: "failed", steps: [], annotations: [annotation] }));
    assert.match(output, /category=other\n$/);
    assert.equal(output.includes("SECRET"), false);
  }
  assert.equal(capture(() => new BrowserCiReporter().onTestEnd(caseFor(), {
    status: "passed", steps: [], annotations: [{ type: "my-pa-ci-signin-complete", description: "complete" }],
  })), "");
});

test("unknown path/project/declaration/status fail closed without printing values", () => {
  for (const candidate of [caseFor("other.spec.ts"),
    { ...caseFor(), location: { file: `${process.cwd()}/e2e/../e2e/browser-security.spec.ts`, line: 78 } },
    caseFor("browser-security.spec.ts", 79), caseFor("browser-security.spec.ts", 78, "desktop\n::error::x")]) {
    assert.equal(capture(() => new BrowserCiReporter().onTestEnd(candidate, resultFor())), "");
  }
  assert.equal(capture(() => new BrowserCiReporter().onTestEnd(caseFor(), { status: "passed", steps: [] })), "");
});

test("does not access or emit any error/title/request/payload data and caps output", () => {
  const secret = "SYNTHETIC_COOKIE_URL_BODY\n::error::injected";
  const error = new Proxy({}, { get(_target, key) {
    if (key === "location") return undefined;
    throw new Error("error content accessed");
  } });
  const reporter = new BrowserCiReporter();
  const output = capture(() => {
    for (let index = 0; index < 12; index++) {
      reporter.onTestEnd({ ...caseFor(), title: secret, id: secret }, {
        ...resultFor(), errors: [error], stdout: [secret], stderr: [secret],
        attachments: [{ name: secret, body: secret }],
        steps: [{ ...resultFor().steps[0], error }],
      });
    }
    reporter.onError(error);
  });
  assert.equal(output.includes(secret), false);
  assert.equal(output.trim().split("\n").length, 10);
});
