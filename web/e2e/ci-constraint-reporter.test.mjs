import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire, Module } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.dirname(here);
const spec = path.join(here, "constraints-mutations.spec.ts");
const reporterSource = readFileSync(path.join(here, "ci-constraint-reporter.ts"), "utf8");
const compiledReporter = ts.transpileModule(reporterSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { default: ConstraintCiReporter } = await import(
  `data:text/javascript,${encodeURIComponent(compiledReporter)}`
);

const cases = [
  {
    id: "CONSTRAINT_AUTHORING_JOURNEY",
    category: "authoring",
    title: "the Constraint authoring journey writes through the BFF to PostgreSQL",
    declarationLine: 170,
    assertionLine: 183,
  },
  {
    id: "CONSTRAINT_CROSS_PROJECT_REFUSAL",
    category: "project-boundary",
    title: "a record addressed through another owned Project is not found and not changed",
    declarationLine: 393,
    assertionLine: 404,
  },
  {
    id: "CONSTRAINT_FIELD_REFUSAL",
    category: "request-validation",
    title: "an undeclared or Principal-naming body field is refused before a write",
    declarationLine: 449,
    assertionLine: 470,
  },
];

function testCase(entry = cases[0], overrides = {}) {
  return {
    title: entry.title,
    expectedStatus: "passed",
    parent: { project: () => ({ name: "desktop" }) },
    location: { file: spec, line: entry.declarationLine },
    ...overrides,
  };
}

function result(entry = cases[0], overrides = {}) {
  return {
    status: "failed",
    errors: [{ location: { file: spec, line: entry.assertionLine } }],
    ...overrides,
  };
}

function capture(run) {
  const chunks = [];
  const original = process.stdout.write;
  process.stdout.write = (chunk) => {
    chunks.push(String(chunk));
    return true;
  };
  try {
    run();
  } finally {
    process.stdout.write = original;
  }
  return chunks.join("");
}

test("the exact three declared cases produce only their static IDs and categories", () => {
  const ids = [...reporterSource.matchAll(/id: "(CONSTRAINT_[A-Z_]+)"/g)].map((match) => match[1]);
  assert.deepEqual(ids, cases.map((entry) => entry.id));
  for (const entry of cases) {
    const output = capture(() =>
      new ConstraintCiReporter().onTestEnd(testCase(entry), result(entry)),
    );
    assert.equal(
      output,
      `::error file=web/e2e/constraints-mutations.spec.ts,line=${entry.assertionLine},title=${entry.id}::category=${entry.category}\n`,
    );
  }
});

test("the checked-in line allowlists contain exactly the current assertion call sites", () => {
  const specLines = readFileSync(spec, "utf8").split("\n");
  assert.match(specLines[113], /expect\(answer\.status/);
  const declared = [...reporterSource.matchAll(/declarationLine: (\d+),/g)].map((match) => Number(match[1]));
  assert.deepEqual(declared, cases.map((entry) => entry.declarationLine));
  const allowlists = [...reporterSource.matchAll(/assertionLines: new Set\(\[([\s\S]*?)\]\)/g)]
    .map((match) => [...match[1].matchAll(/\d+/g)].map((number) => Number(number[0])));
  assert.equal(allowlists.length, cases.length);
  for (const [index, entry] of cases.entries()) {
    assert.ok(specLines[entry.declarationLine - 1].includes(`test("${entry.title}"`));
    const end = cases[index + 1]?.declarationLine ?? specLines.length + 1;
    const actual = specLines.flatMap((line, offset) =>
      offset + 1 > entry.declarationLine && offset + 1 < end && /expect\(|expectSafe\(/.test(line)
        ? [offset + 1]
        : [],
    );
    assert.deepEqual(allowlists[index], [114, ...actual]);
  }
});

test("shared expectSafe line 114 yields only static bytes for each case", () => {
  const hostile = "SYNTHETIC_PRIVATE_PAYLOAD\n::error::injected";
  for (const entry of cases) {
    const output = capture(() => new ConstraintCiReporter().onTestEnd(
      testCase(entry, { id: hostile, annotations: [{ description: hostile }] }),
      result(entry, {
        errors: [{ location: { file: spec, line: 114 }, message: hostile, stack: hostile, snippet: hostile }],
        stdout: [hostile],
        stderr: [hostile],
        attachments: [{ name: hostile, body: hostile }],
      }),
    ));
    assert.equal(
      output,
      `::error file=web/e2e/constraints-mutations.spec.ts,line=114,title=${entry.id}::category=${entry.category}\n`,
    );
    assert.equal(output.includes(hostile), false);
  }
});

test("other expectSafe helper lines remain unknown for every case", () => {
  for (const entry of cases) {
    for (const line of [115, 124]) {
      assert.equal(capture(() => new ConstraintCiReporter().onTestEnd(
        testCase(entry),
        result(entry, { errors: [{ location: { file: spec, line } }] }),
      )), "");
    }
  }
});

test("hostile result payloads cannot enter the annotation", () => {
  const hostile = "SYNTHETIC_PRIVATE_PAYLOAD\n::error::injected";
  const entry = cases[0];
  const output = capture(() =>
    new ConstraintCiReporter().onTestEnd(
      testCase(entry, { id: hostile, url: hostile, annotations: [{ type: hostile, description: hostile }] }),
      result(entry, {
        error: { message: hostile, stack: hostile, snippet: hostile, value: hostile },
        errors: [{ location: { file: spec, line: entry.assertionLine }, message: hostile, stack: hostile, snippet: hostile, value: hostile }],
        stdout: [hostile],
        stderr: [hostile],
        attachments: [{ name: hostile, body: hostile, path: hostile }],
      }),
    ),
  );
  assert.equal(
    output,
    `::error file=web/e2e/constraints-mutations.spec.ts,line=183,title=${entry.id}::category=${entry.category}\n`,
  );
  assert.equal(output.includes(hostile), false);
});

test("project, path, title, declaration, result status, and assertion location fail closed", () => {
  const entry = cases[0];
  const unsafeCases = [
    [testCase(entry, { parent: { project: () => ({ name: "tablet" }) } }), result(entry)],
    [testCase(entry, { parent: { project: () => ({ name: "desktop\n::error::injected" }) } }), result(entry)],
    [testCase(entry, { location: { file: "e2e/constraints-mutations.spec.ts", line: 170 } }), result(entry)],
    [testCase(entry, { location: { file: `${spec}\n::error::injected`, line: 170 } }), result(entry)],
    [testCase(entry, { title: `${entry.title}\n::error::injected` }), result(entry)],
    [testCase(entry, { location: { file: spec, line: 171 } }), result(entry)],
    [testCase(entry, { expectedStatus: "failed" }), result(entry)],
    [testCase(entry), result(entry, { status: "passed" })],
    [testCase(entry), result(entry, { status: "timedOut" })],
    [testCase(entry), result(entry, { errors: [] })],
    [testCase(entry), result(entry, { errors: [{ location: { file: spec, line: 182 } }] })],
    [testCase(entry), result(entry, { errors: [{ location: { file: path.join(web, "other.ts"), line: 183 } }] })],
    [testCase(entry), result(entry, { errors: [{ location: { file: spec, line: "183\n::error::injected" } }] })],
  ];
  for (const [caseInput, resultInput] of unsafeCases) {
    assert.equal(capture(() => new ConstraintCiReporter().onTestEnd(caseInput, resultInput)), "");
  }
});

test("one reporter emits no more than one annotation across all failures", () => {
  const reporter = new ConstraintCiReporter();
  const output = capture(() => {
    reporter.onTestEnd(testCase(cases[0]), result(cases[0], { status: "passed" }));
    for (const entry of cases) reporter.onTestEnd(testCase(entry), result(entry));
  });
  assert.equal(output.split("::error").length - 1, 1);
  assert.match(output, /CONSTRAINT_AUTHORING_JOURNEY/);
});

test("only the Constraint CI command enables the extra reporter; default reporters remain", () => {
  const workflow = readFileSync(path.join(web, "..", ".github/workflows/frontend-quality.yml"), "utf8");
  const marker = "- name: Run the Constraint authoring real-stack desktop e2e";
  const start = workflow.indexOf(marker);
  assert.ok(start >= 0);
  const end = workflow.indexOf("\n  accessibility:", start);
  assert.ok(end > start);
  const step = workflow.slice(start, end);
  assert.equal(workflow.match(/CI_CONSTRAINT_DIAGNOSTIC/g)?.length, 1);
  assert.match(step, /CI_CONSTRAINT_DIAGNOSTIC: "1"/);
  assert.match(step, /npm run e2e -- e2e\/constraints-mutations\.spec\.ts --project=desktop/);

  const configFile = path.join(web, "playwright.config.ts");
  const configSource = readFileSync(configFile, "utf8");
  const compiledConfig = ts.transpileModule(configSource, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const previous = {
    CI: process.env.CI,
    CI_CONSTRAINT_DIAGNOSTIC: process.env.CI_CONSTRAINT_DIAGNOSTIC,
    CI_RESPONSIVE_DIAGNOSTIC: process.env.CI_RESPONSIVE_DIAGNOSTIC,
  };
  function reporters(ci, constraint, responsive) {
    if (ci === undefined) delete process.env.CI;
    else process.env.CI = ci;
    if (constraint === undefined) delete process.env.CI_CONSTRAINT_DIAGNOSTIC;
    else process.env.CI_CONSTRAINT_DIAGNOSTIC = constraint;
    if (responsive === undefined) delete process.env.CI_RESPONSIVE_DIAGNOSTIC;
    else process.env.CI_RESPONSIVE_DIAGNOSTIC = responsive;
    const configModule = new Module(configFile);
    configModule.filename = configFile;
    configModule.paths = Module._nodeModulePaths(web);
    configModule._compile(compiledConfig, configFile);
    return configModule.exports.default.reporter;
  }
  try {
    assert.deepEqual(reporters(undefined, "1", undefined), [["list"]]);
    assert.deepEqual(reporters("true", undefined, undefined), [["list"], ["html", { open: "never" }]]);
    assert.deepEqual(reporters("true", "0", undefined), [["list"], ["html", { open: "never" }]]);
    assert.deepEqual(reporters("true", "1", undefined), [
      ["list"], ["html", { open: "never" }], ["./e2e/ci-constraint-reporter.ts"],
    ]);
    assert.deepEqual(reporters("true", undefined, "1"), [
      ["list"], ["html", { open: "never" }], ["./e2e/ci-responsive-reporter.ts"],
    ]);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});
