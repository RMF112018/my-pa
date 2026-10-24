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
async function exercise(target, { reject = true, active = true, annotations = [], checkMetadata = true, project, snapshot = {}, observationError = false } = {}) {
  const previous = [process.env.CI, process.env.CI_BROWSER_DIAGNOSTIC];
  process.env.CI = active ? "true" : ""; process.env.CI_BROWSER_DIAGNOSTIC = active ? "1" : "";
  const opaque = new Proxy({}, { get() { throw new Error("sensitive error accessed"); } });
  let reached;
  let settle;
  let blocked = false;
  const entered = new Promise((resolve) => { reached = resolve; });
  const calls = [];
  let observations = 0;
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
  const page = { async evaluate(callback, settledSelector) {
    observations++;
    assert.equal(settledSelector, "settled");
    if (observationError) throw opaque;
    const previousDocument = globalThis.document;
    const previousInput = globalThis.HTMLInputElement;
    class SyntheticInput { get value() { return snapshot.queryValue ?? "morning brief"; } }
    const list = {
      querySelector(selector) { assert.equal(selector, ":scope > p:not([role])"); return snapshot.idle ? {} : null; },
      getAttribute(name) { assert.equal(name, "aria-busy"); return snapshot.busy ? "true" : null; },
    };
    globalThis.HTMLInputElement = SyntheticInput;
    globalThis.document = { querySelector(selector) {
      if (selector === '[data-testid="search-command-input"]') return new SyntheticInput();
      if (selector === '[data-testid="search-command-list"]') return list;
      assert.equal(selector, "settled"); return snapshot.settled ? {} : null;
    } };
    try { return callback(settledSelector); }
    finally {
      if (previousDocument === undefined) delete globalThis.document; else globalThis.document = previousDocument;
      if (previousInput === undefined) delete globalThis.HTMLInputElement; else globalThis.HTMLInputElement = previousInput;
    }
  }, goto: () => act("nav"), getByRole: (role) => ({ kind: role === "heading" ? "heading" : "query", fill: () => act("query") }),
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
    const running = runSearchHrefJourney(page, { annotations, project: project ? { name: project } : undefined }).catch((error) => { caught = error; });
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
    return { calls, annotations, observations };
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

test("actual failed-settle snapshot exposes only four booleans for fixed WebKit109 DOM", async () => {
  for (const snapshot of [{ queryValue: "morning brief", idle: true, busy: false, settled: false },
    { queryValue: "OPAQUE_PRIVATE_QUERY\n::error::private", idle: false, busy: true, settled: false },
    { queryValue: "morning brief", idle: false, busy: false, settled: true }]) {
    const result = await exercise("search-settled", { project: "webkit", snapshot });
    const description = `q${Number(snapshot.queryValue === "morning brief")}-i${Number(snapshot.idle)}-b${Number(snapshot.busy)}-s${Number(snapshot.settled)}`;
    assert.equal(result.observations, 1);
    assert.deepEqual(result.annotations, [{ type: "my-pa-ci-search-active", description: "search-settled:failed" },
      { type: "my-pa-ci-search-snapshot", description }]);
    assert.equal(JSON.stringify(result.annotations).includes("PRIVATE"), false);
  }
});
test("snapshot failure or metadata failure preserves the SAME original settled-wait error", async () => {
  const result = await exercise("search-settled", { project: "webkit", observationError: true });
  assert.deepEqual(result.annotations.at(-1), { type: "my-pa-ci-search-snapshot", description: "unavailable" });
  const unavailable = new Proxy([], { get() { throw new Error("opaque metadata unavailable"); } });
  await exercise("search-settled", { project: "webkit", annotations: unavailable, checkMetadata: false });
});
test("successful/other-phase/other-project/default-off journeys perform no DOM snapshot", async () => {
  for (const [phase, options] of [["search-settled", { project: "webkit", reject: false }],
    ["heading", { project: "webkit" }], ["search-settled", { project: "firefox" }],
    ["search-settled", { project: "webkit", active: false }]]) {
    const result = await exercise(phase, options);
    assert.equal(result.observations, 0);
    assert.equal(result.annotations.some((item) => item.type === "my-pa-ci-search-snapshot"), false);
  }
});

test("idle snapshot selector binds to the current sole direct non-status paragraph", () => {
  const file = path.join(path.dirname(fileURLToPath(import.meta.url)), "../src/components/shell/command-palette.tsx");
  const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found = [];
  function visit(node) {
    if (ts.isJsxElement(node) && node.openingElement.attributes.properties.some((property) =>
      ts.isJsxAttribute(property) && property.name.getText(source) === "data-testid"
      && property.initializer?.text === "search-command-list")) found.push(node);
    ts.forEachChild(node, visit);
  }
  visit(source); assert.equal(found.length, 1);
  const paragraphs = found[0].children.filter(ts.isJsxExpression).flatMap((node) => {
    const conditional = node.expression;
    if (!conditional || !ts.isConditionalExpression(conditional) || !ts.isParenthesizedExpression(conditional.whenTrue)) return [];
    const element = conditional.whenTrue.expression;
    if (!ts.isJsxElement(element) || element.openingElement.tagName.getText(source) !== "p"
      || element.openingElement.attributes.properties.some((property) => property.name?.getText(source) === "role")) return [];
    return [{ condition: conditional.condition.getText(source), copy: element.children.map((child) => child.getText(source)).join("").trim() }];
  });
  assert.deepEqual(paragraphs, [{ condition: "idle", copy: "Start typing to search." }]);
});
