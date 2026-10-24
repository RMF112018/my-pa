import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
const ts = createRequire(import.meta.url)("typescript");
const compiled = ts.transpileModule(readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "search-contract.spec.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText.replace(/import \{[^\n]+\} from "@playwright\/test";/, "const { test, expect } = globalThis.__myPaSearchProbe;")
  .replace(/import \{[^\n]+\} from "\.\/fixtures";/, "const { markBrowserEarly, observeSearchMedia, SEARCH_SETTLED, signIn } = globalThis.__myPaSearchProbe.fixtures;");
let moduleNumber = 0;
async function exercise(target, { reject = true, active = true, annotations = [], checkMetadata = true } = {}) {
  const previous = [process.env.CI, process.env.CI_BROWSER_DIAGNOSTIC];
  process.env.CI = active ? "true" : ""; process.env.CI_BROWSER_DIAGNOSTIC = active ? "1" : "";
  const opaque = new Proxy({}, { get() { throw new Error("sensitive error accessed"); } });
  let reached;
  let settle;
  let blocked = false;
  const entered = new Promise((resolve) => { reached = resolve; });
  const calls = [];
  async function act(phase, value) {
    calls.push(phase);
    if (phase === target && !blocked) {
      blocked = true;
      reached();
      await new Promise((resolve, reject) => { settle = { resolve, reject }; });
    }
    return value;
  }
  function links(kind) {
    return { count: () => act(kind, 1), nth: () => ({ getAttribute: () => act(kind,
      kind === "capture-links" ? "/knowledge?captureId=cap_fixture&versionId=fixture" : "/knowledge/goodnotes?pageVersionId=fixture") }) };
  }
  const page = { goto: () => act("nav"), getByRole: (role) => ({ kind: role === "heading" ? "heading" : "query", fill: () => act("query") }),
    locator: (selector) => selector === "settled" ? { first: () => ({ kind: "search-settled" }) }
      : selector.includes("captureId") ? links("capture-links")
        : selector.includes("goodnotes") ? links("goodnotes-links") : { kind: "knowledge-absence" } };
  const fakeTest = () => {}; fakeTest.describe = (_name, callback) => callback(); fakeTest.beforeEach = () => {};
  globalThis.__myPaSearchProbe = { test: fakeTest, fixtures: { SEARCH_SETTLED: "settled" },
    expect: (target) => ({ toBeVisible: (options) => { if (target.kind === "search-settled") assert.deepEqual(options, { timeout: 30_000 }); return act(target.kind); },
      toHaveCount: () => act(target.kind), toMatch() {}, not: { toMatch() {} } }) };
  try {
    const { runSearchHrefJourney } = await import(`data:text/javascript,${encodeURIComponent(compiled)}#${moduleNumber++}`);
    let caught;
    const running = runSearchHrefJourney(page, { annotations }).catch((error) => { caught = error; });
    if (target) {
      await entered;
      if (active && checkMetadata) {
        // Read before settling: catch/finally has not run, matching timeout ordering.
        assert.deepEqual(annotations, [{ type: "my-pa-ci-search-active", description: `${target}:inflight` }]);
      }
      if (reject) settle.reject(opaque); else settle.resolve();
    }
    await running;
    assert.equal(caught, target && reject ? opaque : undefined);
    return { calls, annotations };
  } finally {
    delete globalThis.__myPaSearchProbe;
    if (previous[0] === undefined) delete process.env.CI; else process.env.CI = previous[0];
    if (previous[1] === undefined) delete process.env.CI_BROWSER_DIAGNOSTIC; else process.env.CI_BROWSER_DIAGNOSTIC = previous[1];
  }
}

test("actual Search helper exposes each pending await before catch, preserving opaque rejection", async () => {
  for (const phase of ["nav", "heading", "query", "search-settled", "capture-links", "goodnotes-links", "knowledge-absence"]) {
    const { annotations } = await exercise(phase);
    assert.deepEqual(annotations, [{ type: "my-pa-ci-search-active", description: `${phase}:failed` }]);
  }
});
test("resolution cleans up pending work and retains one honest completion record", async () => {
  const { calls, annotations } = await exercise("search-settled", { reject: false });
  assert.deepEqual(calls, ["nav", "heading", "query", "search-settled", "capture-links", "capture-links", "goodnotes-links", "goodnotes-links", "knowledge-absence"]);
  assert.deepEqual(annotations, [{ type: "my-pa-ci-search-active", description: "knowledge-absence:complete" }]);
});
test("default mode emits nothing and annotation failure cannot change successful work", async () => {
  assert.deepEqual((await exercise("nav", { active: false })).annotations, []);
  const unavailable = new Proxy([], { get() { throw new Error("metadata unavailable"); } });
  await exercise(undefined, { annotations: unavailable });
  await exercise("nav", { annotations: unavailable, checkMetadata: false });
});
