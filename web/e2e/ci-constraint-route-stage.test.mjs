import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "journeys.spec.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText.replace(/import \{[^\n]+\} from "@playwright\/test";/,
  "const { expect, test } = globalThis.__myPaConstraintStageProbe;")
  .replace(/import \{[^\n]+\} from "\.\/fixtures";/,
    "const { enableDiagnostics, expectState, openCaptureNote, pinInspector, SEARCH_SETTLED, signIn, syntheticNote, visibleCaptureButton } = globalThis.__myPaConstraintStageProbe.fixtures;");
let moduleNumber = 0;

async function probe(failure, { active = true, annotations = [], project = "desktop" } = {}) {
  const keys = ["CI", "CI_RESPONSIVE_DIAGNOSTIC"];
  const before = keys.map((key) => process.env[key]);
  process.env.CI = active ? "true" : "";
  process.env.CI_RESPONSIVE_DIAGNOSTIC = active ? "1" : "";
  const sensitive = new Proxy({}, { get() { throw new Error("sensitive error content was accessed"); } });
  const calls = [];
  const selected = [];
  const act = async (stage) => { calls.push(stage); if (failure === stage) throw sensitive; };
  const workspace = { getByTestId(id) {
    selected.push(id);
    return { kind: id === "register-loading" ? "loading" : "row-visible" };
  } };
  const page = { goto: () => act("nav"), getByTestId: (id) =>
    id === "constraints-live-workspace" ? workspace : { kind: "unavailable" } };
  const fakeTest = () => {};
  fakeTest.describe = (_title, body) => body();
  fakeTest.beforeEach = () => {};
  globalThis.__myPaConstraintStageProbe = {
    test: fakeTest,
    expect: (target) => ({ toHaveURL: () => act("URL-state"),
      toHaveCount: () => act(target.kind), toBeVisible: () => act(target.kind) }),
    fixtures: { signIn: () => act("signIn") },
  };
  let caught;
  try {
    const { runDeepLinkedConstraintView } = await import(`data:text/javascript,${encodeURIComponent(compiled)}#${moduleNumber++}`);
    try { await runDeepLinkedConstraintView(page, { annotations, project: { name: project } }); }
    catch (error) { caught = error; }
    assert.equal(caught, failure ? sensitive : undefined);
    return { annotations, calls, selected };
  } finally {
    delete globalThis.__myPaConstraintStageProbe;
    keys.forEach((key, index) => { if (before[index] === undefined) delete process.env[key]; else process.env[key] = before[index]; });
  }
}

test("the actual exported route helper rethrows each identical opaque stage error", async () => {
  for (const stage of ["nav", "URL-state", "loading", "unavailable", "row-visible"]) {
    assert.deepEqual((await probe(stage)).annotations,
      [{ type: "my-pa-ci-constraint-stage", description: stage }]);
  }
});

test("successful calls and desktop/mobile selectors retain their original order", async () => {
  for (const project of ["desktop", "mobile"]) {
    const { calls, annotations, selected } = await probe(undefined, { project });
    assert.deepEqual(calls, ["signIn", "nav", "URL-state", "URL-state", "loading", "unavailable", "row-visible"]);
    assert.deepEqual(annotations, []);
    assert.equal(selected.at(-1), project === "mobile"
      ? "register-card-cst_e2ecst0000000001" : "register-row-cst_e2ecst0000000001");
  }
});

test("default mode and pre-route sign-in errors produce no route metadata", async () => {
  assert.deepEqual((await probe("nav", { active: false })).annotations, []);
  assert.deepEqual((await probe("signIn")).annotations, []);
});

test("metadata is capped and write failures cannot mask failure or change success", async () => {
  const annotations = [{ type: "my-pa-ci-constraint-stage", description: "nav" }];
  assert.deepEqual((await probe("loading", { annotations })).annotations, annotations);
  const unavailable = new Proxy([], { get() { throw new Error("synthetic unavailable annotations"); } });
  await probe("loading", { annotations: unavailable });
  await probe(undefined, { annotations: unavailable });
});
