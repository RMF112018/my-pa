import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

// The production module stays TypeScript; transpilation uses the existing
// TypeScript dev dependency so this synthetic test also runs on CI's Node 20.
const require = createRequire(import.meta.url);
const ts = require("typescript");
const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, "ci-responsive-reporter.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { default: ResponsiveCiReporter } = await import(
  `data:text/javascript,${encodeURIComponent(compiled)}`
);

const specs = [
  "work-acceptance.spec.ts",
  "today-tasks.spec.ts",
  "journeys.spec.ts",
  "intelligence-journey.spec.ts",
  "constraints-read-plane.spec.ts",
  "mobile-foundation.spec.ts",
];
const projects = ["desktop", "tablet", "mobile"];
const failures = ["failed", "timedOut", "interrupted"];
const specPath = (name) => path.join(process.cwd(), "e2e", name);

function caseFor(overrides = {}) {
  return {
    expectedStatus: "passed",
    parent: { project: () => ({ name: "desktop" }) },
    location: { file: specPath(specs[0]), line: 42 },
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

test("emits exact bounded bytes for each admitted spec, project, and failure status", () => {
  for (const spec of specs) {
    for (const project of projects) {
      for (const status of failures) {
        const reporter = new ResponsiveCiReporter();
        const output = capture(() =>
          reporter.onTestEnd(
            caseFor({
              parent: { project: () => ({ name: project }) },
              location: { file: specPath(spec), line: 42 },
            }),
            { status },
          ),
        );
        assert.equal(
          output,
          `::error file=web/e2e/${spec},line=42,title=Responsive Playwright failure::project=${project}; status=${status}\n`,
        );
      }
    }
  }
});

test("rejects expected failures and non-failure results", () => {
  for (const expectedStatus of ["failed", "timedOut", "skipped", "interrupted", "unknown"]) {
    assert.equal(
      capture(() => new ResponsiveCiReporter().onTestEnd(caseFor({ expectedStatus }), { status: "failed" })),
      "",
    );
  }
  for (const status of ["passed", "skipped", "unknown", "failed\n::error::injected"]) {
    assert.equal(
      capture(() => new ResponsiveCiReporter().onTestEnd(caseFor(), { status })),
      "",
    );
  }
});

test("rejects unknown projects, unsafe paths, and non-declaration lines without leaking input", () => {
  const unsafeProjects = ["firefox", "mobile-webkit", "desktop\n::error::injected", "", "desktop,foo=bar"];
  for (const name of unsafeProjects) {
    assert.equal(
      capture(() =>
        new ResponsiveCiReporter().onTestEnd(
          caseFor({ parent: { project: () => ({ name }) } }),
          { status: "failed" },
        ),
      ),
      "",
    );
  }

  const unsafePaths = [
    "e2e/work-acceptance.spec.ts",
    `${process.cwd()}/e2e/../e2e/${specs[0]}`,
    `${specPath(specs[0])}\n::error::injected`,
    `${specPath(specs[0])}\0`,
    path.join(process.cwd(), "other", specs[0]),
    specPath("visual.spec.ts"),
  ];
  for (const file of unsafePaths) {
    assert.equal(
      capture(() =>
        new ResponsiveCiReporter().onTestEnd(caseFor({ location: { file, line: 42 } }), {
          status: "failed",
        }),
      ),
      "",
    );
  }

  for (const line of [0, -1, 100_001, Number.MAX_SAFE_INTEGER, 1.5, NaN, "3", "2\n::error::x"]) {
    assert.equal(
      capture(() =>
        new ResponsiveCiReporter().onTestEnd(caseFor({ location: { file: specPath(specs[0]), line } }), {
          status: "failed",
        }),
      ),
      "",
    );
  }
});

test("never includes dynamic title, error, output, attachment, URL, or global-error data", () => {
  const secret = "SYNTHETIC_PRIVATE_PAYLOAD\n::error::injected";
  const reporter = new ResponsiveCiReporter();
  const output = capture(() => {
    reporter.onTestEnd(
      caseFor({ title: secret, id: secret, url: secret }),
      { status: "failed", error: { message: secret, stack: secret }, stdout: [secret], stderr: [secret], attachments: [{ name: secret, body: secret }] },
    );
    reporter.onError({ message: secret, stack: secret });
  });
  assert.equal(
    output,
    `::error file=web/e2e/${specs[0]},line=42,title=Responsive Playwright failure::project=desktop; status=failed\n` +
      "::error title=Responsive Playwright failure::phase=playwright-global\n",
  );
  assert.equal(output.includes(secret), false);
});

test("caps test and global annotations together at ten", () => {
  const reporter = new ResponsiveCiReporter();
  const output = capture(() => {
    reporter.onError({ message: "ignored" });
    for (let index = 0; index < 12; index += 1) {
      reporter.onTestEnd(caseFor(), { status: "failed" });
    }
    reporter.onError({ message: "ignored again" });
  });
  assert.equal(output.trimEnd().split("\n").length, 10);
  assert.equal(output.match(/phase=playwright-global/g)?.length, 1);
  assert.equal(output.match(/project=desktop; status=failed/g)?.length, 9);
});
