import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
const ts = createRequire(import.meta.url)("typescript");
const compiled = ts.transpileModule(readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText.replace(/import \{[^\n]+\} from "@playwright\/test";/, "const expect = undefined; const test = undefined;");
const { hideNextjsDevOverlay } = await import(`data:text/javascript,${encodeURIComponent(compiled)}`);
function portal() {
  return { nodeType: 1, localName: "nextjs-portal", removed: false,
    remove() { this.removed = true; }, querySelectorAll(selector) { assert.equal(selector, "nextjs-portal"); return []; } };
}

test("actual helper removes only existing/late portals with one observer per document", async () => {
  const existing = portal();
  const observers = [];
  let document = { documentElement: {}, querySelectorAll(selector) {
    assert.equal(selector, "nextjs-portal"); return existing.removed ? [] : [existing];
  } };
  const page = { async evaluate(callback) {
    const previousDocument = globalThis.document;
    const previousObserver = globalThis.MutationObserver;
    globalThis.document = document;
    globalThis.MutationObserver = class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe(target, options) { assert.equal(target, document.documentElement); assert.deepEqual(options, { childList: true, subtree: true }); }
    };
    try { return callback(); }
    finally { globalThis.document = previousDocument; globalThis.MutationObserver = previousObserver; }
  } };
  await hideNextjsDevOverlay(page);
  assert.equal(existing.removed, true);
  const late = portal();
  const nested = portal();
  const app = { nodeType: 1, localName: "main", remove() { throw new Error("application node removed"); },
    querySelectorAll(selector) { assert.equal(selector, "nextjs-portal"); return [nested]; } };
  observers[0].callback([{ addedNodes: [late, app, { nodeType: 3 }] }]);
  assert.equal(late.removed, true);
  assert.equal(nested.removed, true);
  await hideNextjsDevOverlay(page);
  assert.equal(observers.length, 1);
  assert.equal(document.__myPaE2EPortalObserver, observers[0]);
  assert.equal(Object.keys(document).includes("__myPaE2EPortalObserver"), false);
  const previousDocument = document;
  document = { documentElement: {}, querySelectorAll: () => [] };
  await hideNextjsDevOverlay(page);
  assert.equal(observers.length, 2);
  assert.notEqual(document.__myPaE2EPortalObserver, previousDocument.__myPaE2EPortalObserver);
});

test("opaque evaluation failures propagate unchanged and no style API is called", async () => {
  const opaque = new Proxy({}, { get() { throw new Error("sensitive error accessed"); } });
  let caught;
  try { await hideNextjsDevOverlay({ evaluate: async () => { throw opaque; },
    addStyleTag() { throw new Error("style injection called"); } }); } catch (error) { caught = error; }
  assert.equal(caught, opaque);
});
