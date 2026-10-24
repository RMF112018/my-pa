import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const here = path.dirname(fileURLToPath(import.meta.url));
const compiled = ts.transpileModule(readFileSync(path.join(here, "visual-assertion-witness.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText.replace(/import \{ existsSync \} from "node:fs";/,
  "const { existsSync } = globalThis.__myPaVisualWitnessProbe;");
const cases = { light: "shell-light-unavailable.png", dark: "shell-dark-inspector.png",
  launcher: "shell-command-menu.png", zoom: "shell-zoom-200.png" };
let moduleNumber = 0;

async function probe(caseId, { active = true, before = false, after = true, delta = 1,
  hard = false, unavailable, annotations = [], project = "desktop" } = {}) {
  const flags = ["CI", "CI_VISUAL_DIAGNOSTIC"];
  const previous = flags.map((key) => process.env[key]);
  process.env.CI = active ? "true" : "";
  process.env.CI_VISUAL_DIAGNOSTIC = active ? "1" : "";
  const calls = [];
  let count = 0;
  let existenceCalls = 0;
  let annotationReads = 0;
  let projectReads = 0;
  const opaque = new Proxy({}, { get() { throw new Error("error content read"); } });
  const info = {
    get project() { projectReads++; return { name: project }; },
    snapshotPath(name, options) {
      calls.push("path");
      if (!active || unavailable === "path") throw new Error("synthetic unavailable path");
      assert.equal(name, cases[caseId]);
      assert.deepEqual(options, { kind: "screenshot" });
      return "synthetic-fixed-snapshot";
    },
    errors: new Proxy([], { get(_target, key) {
      if (key !== "length") throw new Error("error array contents read");
      calls.push("count");
      if (!active || unavailable === "count") throw new Error("synthetic unavailable count");
      return count;
    } }), get annotations() { annotationReads++; return annotations; },
  };
  globalThis.__myPaVisualWitnessProbe = { existsSync(value) {
    calls.push("exists");
    assert.equal(value, "synthetic-fixed-snapshot");
    if (!active || unavailable === "exists") throw new Error("synthetic unavailable existence");
    return existenceCalls++ === 0 ? before : after;
  } };
  let caught;
  try {
    const { witnessVisualAssertion } = await import(`data:text/javascript,${encodeURIComponent(compiled)}#${moduleNumber++}`);
    try {
      await witnessVisualAssertion(info, caseId, async () => {
        calls.push("assertion");
        if (hard) throw opaque;
        count += delta;
      });
    } catch (error) { caught = error; }
    assert.equal(caught, hard ? opaque : undefined);
    return { calls, annotations, annotationReads, projectReads };
  } finally {
    delete globalThis.__myPaVisualWitnessProbe;
    flags.forEach((key, index) => { if (previous[index] === undefined) delete process.env[key]; else process.env[key] = previous[index]; });
  }
}

test("all four actual helper cases witness before/assertion/after using lengths only", async () => {
  for (const caseId of Object.keys(cases)) {
    const { calls, annotations } = await probe(caseId);
    assert.deepEqual(calls, ["path", "count", "exists", "assertion", "exists", "count"]);
    assert.deepEqual(annotations, [{ type: "my-pa-ci-visual-witness", description: `${caseId}:absent-created-error` }]);
  }
});

test("disabled and unknown IDs perform only the exact assertion", async () => {
  for (const [caseId, active] of [["light", false], ["unknown", true], ["__proto__", true]]) {
    const { calls, annotations, annotationReads, projectReads } = await probe(caseId, { active });
    assert.deepEqual(calls, ["assertion"]);
    assert.deepEqual(annotations, []);
    assert.equal(annotationReads, 0);
    assert.equal(projectReads, 0);
  }
  for (const project of ["mobile", "firefox", "desktop\n::error::x"]) {
    const { calls, annotations, annotationReads } = await probe("light", { project });
    assert.deepEqual(calls, ["assertion"]);
    assert.deepEqual(annotations, []);
    assert.equal(annotationReads, 0);
  }
});

test("absence, creation, positive delta and hard throws remain distinct", async () => {
  for (const [options, outcome] of [
    [{ before: false, after: true, delta: 0 }, "unknown"],
    [{ before: false, after: false, delta: 1 }, "unknown"],
    [{ before: true, after: true, delta: 1 }, "unknown"],
    [{ before: true, after: true, delta: 0 }, "matched-no-delta"],
    [{ hard: true }, "hard-throw"],
  ]) assert.equal((await probe("light", options)).annotations[0].description, `light:${outcome}`);
});

test("observations and metadata failures cannot change success or SAME opaque hard failure", async () => {
  for (const unavailable of ["path", "count", "exists"]) {
    assert.equal((await probe("light", { unavailable })).annotations[0].description, "light:unknown");
    assert.equal((await probe("light", { unavailable, hard: true })).annotations[0].description, "light:hard-throw");
  }
  const unavailable = new Proxy([], { get() { throw new Error("synthetic unavailable metadata"); } });
  await probe("light", { annotations: unavailable });
  await probe("light", { annotations: unavailable, hard: true });
});

test("metadata is capped by literal cases and conflicts become unknown", async () => {
  const annotations = [];
  for (const caseId of Object.keys(cases)) await probe(caseId, { annotations });
  assert.equal(annotations.length, 4);
  await probe("light", { annotations, before: true, delta: 0 });
  assert.equal(annotations.length, 4);
  assert.equal(annotations[0].description, "light:unknown");
});

test("the actual visual spec retains all four literal callbacks/options and order", () => {
  const source = ts.createSourceFile("visual.spec.ts", readFileSync(path.join(here, "visual.spec.ts"), "utf8"), ts.ScriptTarget.Latest, true);
  const observed = [];
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(source) === "witnessVisualAssertion") {
      const [info, caseId, callback] = node.arguments;
      assert.equal(info.getText(source), "testInfo");
      assert.ok(ts.isAwaitExpression(node.parent));
      assert.ok(ts.isArrowFunction(callback));
      const screenshot = callback.body;
      assert.equal(screenshot.expression.getText(source), "expect(page).toHaveScreenshot");
      observed.push([caseId.text, screenshot.arguments[0].text,
        Object.fromEntries(screenshot.arguments[1].properties.map((property) =>
          [property.name.getText(source), property.initializer.getText(source)]))]);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.deepEqual(observed, Object.entries(cases).map(([id, name]) =>
    [id, name, { animations: '"disabled"', fullPage: id === "zoom" ? "false" : "true" }]));
});
