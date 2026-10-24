import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText.replace(/import \{[^\n]+\} from "@playwright\/test";/,
  "const { expect, test } = globalThis.__myPaSyntheticStageProbe;");

let moduleNumber = 0;
async function probe(failure, { active = true, annotations = [], mode = "visual", operation = "signin" } = {}) {
  const keys = ["CI", "CI_VISUAL_DIAGNOSTIC", "CI_BROWSER_DIAGNOSTIC", "CI_RESPONSIVE_DIAGNOSTIC"];
  const before = keys.map((key) => process.env[key]);
  process.env.CI = active ? "true" : "";
  process.env.CI_VISUAL_DIAGNOSTIC = active && mode === "visual" ? "1" : "";
  process.env.CI_BROWSER_DIAGNOSTIC = active && mode === "browser" ? "1" : "";
  process.env.CI_RESPONSIVE_DIAGNOSTIC = active && mode === "responsive" ? "1" : "";
  const sensitive = new Proxy({}, { get() { throw new Error("sensitive error content was accessed"); } });
  const calls = [];
  const act = async (stage) => { calls.push(stage); if (failure === stage) throw sensitive; };
  const launcher = { kind: "launcher", filter() { return this; } };
  const button = { kind: "signinbutton", click: () => act("click") };
  const page = { goto: () => act("goto"), addStyleTag: () => act("overlay"),
    getByTestId: () => button, waitForURL: () => act("todayURL"), locator: () => launcher,
    emulateMedia: (options) => { assert.deepEqual(options, { reducedMotion: "reduce" }); return act("media"); } };
  globalThis.__myPaSyntheticStageProbe = {
    expect: (locator) => ({ toBeVisible: () => act(locator.kind) }),
    test: { info: () => ({ annotations }) },
  };
  let caught;
  try {
    const { signIn, markBrowserEarly, observeSearchMedia } = await import(`data:text/javascript,${encodeURIComponent(compiled)}#${moduleNumber++}`);
    try {
      if (operation === "early") markBrowserEarly();
      else if (operation === "media") await observeSearchMedia(page);
      else await signIn(page);
    } catch (error) { caught = error; }
    if (failure) assert.equal(caught, sensitive);
    else assert.equal(caught, undefined);
    return { annotations, calls };
  } finally {
    delete globalThis.__myPaSyntheticStageProbe;
    keys.forEach((key, index) => { if (before[index] === undefined) delete process.env[key]; else process.env[key] = before[index]; });
  }
}

test("records each fixed failing sign-in stage and rethrows the identical opaque error", async () => {
  for (const stage of ["goto", "overlay", "signinbutton", "click", "todayURL", "launcher"]) {
    const { annotations } = await probe(stage);
    assert.deepEqual(annotations, [{ type: "my-pa-ci-failed-stage", description: stage }]);
  }
});

test("preserves successful await order and emits nothing outside diagnostics", async () => {
  const success = await probe();
  assert.deepEqual(success.calls, ["goto", "overlay", "signinbutton", "click", "todayURL", "launcher"]);
  assert.deepEqual(success.annotations, [{ type: "my-pa-ci-signin-complete", description: "complete" }]);
  assert.deepEqual((await probe(undefined, { active: false })).annotations, []);
  assert.deepEqual((await probe("click", { active: false })).annotations, []);
  assert.deepEqual((await probe("click", { mode: "browser" })).annotations.filter((item) => item.type !== "my-pa-ci-browser-phase"),
    [{ type: "my-pa-ci-failed-stage", description: "click" }]);
  assert.deepEqual((await probe("click", { mode: "responsive" })).annotations,
    [{ type: "my-pa-ci-failed-stage", description: "click" }]);
  assert.deepEqual((await probe("overlay")).annotations, [{ type: "my-pa-ci-failed-stage", description: "overlay" }]);
});

test("the fixed early/media boundaries preserve Page options, order and opaque failures", async () => {
  const early = await probe(undefined, { mode: "browser", operation: "early" });
  assert.deepEqual(early.calls, []);
  assert.deepEqual(early.annotations, [{ type: "my-pa-ci-browser-phase", description: "early-entered" }]);
  const media = await probe(undefined, { mode: "browser", operation: "media" });
  assert.deepEqual(media.calls, ["media"]);
  assert.deepEqual(media.annotations.map((item) => item.description), ["page-ready", "before-emulateMedia", "after-emulateMedia"]);
  const failed = await probe("media", { mode: "browser", operation: "media" });
  assert.deepEqual(failed.annotations.map((item) => item.description), ["page-ready", "before-emulateMedia", "emulateMedia-failed"]);
  assert.deepEqual((await probe("media", { active: false, mode: "browser", operation: "media" })).annotations, []);
  const unavailable = new Proxy([], { get() { throw new Error("synthetic unavailable annotations"); } });
  await probe("media", { mode: "browser", operation: "media", annotations: unavailable });
  await probe(undefined, { mode: "browser", operation: "media", annotations: unavailable });
});

test("caps metadata and cannot replace the original failure if metadata recording fails", async () => {
  const existing = [{ type: "my-pa-ci-failed-stage", description: "goto" }];
  assert.deepEqual((await probe("click", { annotations: existing })).annotations, existing);
  const unavailable = new Proxy([], { get() { throw new Error("synthetic unavailable annotations"); } });
  await probe("click", { annotations: unavailable });
  await probe(undefined, { annotations: unavailable });
});

test("a later failing helper replaces earlier completion within the one-metadata cap", async () => {
  const { annotations } = await probe();
  assert.deepEqual(annotations, [{ type: "my-pa-ci-signin-complete", description: "complete" }]);
  const later = await probe("click", { annotations });
  assert.equal(later.annotations, annotations);
  assert.deepEqual(annotations, [{ type: "my-pa-ci-failed-stage", description: "click" }]);
});
