import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
const ts = createRequire(import.meta.url)("typescript");
const here = path.dirname(fileURLToPath(import.meta.url));
const load = (name) => ts.createSourceFile(name, readFileSync(path.join(here, name), "utf8"), ts.ScriptTarget.Latest, true);
function nodes(root, predicate) {
  const found = [];
  function visit(node) { if (predicate(node)) found.push(node); ts.forEachChild(node, visit); }
  visit(root);
  return found;
}
const line = (source, node) => source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
function variable(source, name) {
  return nodes(source, (node) => ts.isVariableDeclaration(node) && node.name.getText(source) === name)[0].initializer;
}
function literal(node) {
  if (ts.isStringLiteral(node)) return node.text;
  if (ts.isNumericLiteral(node)) return Number(node.text);
  if (ts.isArrayLiteralExpression(node)) return node.elements.map(literal);
  if (ts.isObjectLiteralExpression(node)) return Object.fromEntries(node.properties.map((property) => [property.name.getText(), literal(property.initializer)]));
  if (ts.isAsExpression(node)) return literal(node.expression);
  throw new Error("unexpected static binding shape");
}
const calls = (source, name) => nodes(source, (node) => ts.isCallExpression(node)
  && ts.isIdentifier(node.expression) && node.expression.text === name);

test("visual reporter cases bind exactly to the four intended literal screenshot callbacks", () => {
  const source = load("visual.spec.ts");
  const reporter = literal(variable(load("ci-visual-reporter.ts"), "CASES"));
  const producer = literal(variable(load("visual-assertion-witness.ts"), "CASES"));
  const titles = ["light successor shell is visually reviewable", "dark shell captures responsive navigation and Inspector states",
    "unified launcher has a deterministic reduced-motion initial state", "the shell reflows at 200 percent without horizontal loss"];
  const tests = calls(source, "test");
  assert.deepEqual(tests.map((node) => node.arguments[0].text), titles);
  assert.equal(reporter.length, 4);
  for (let index = 0; index < tests.length; index++) {
    const witness = calls(tests[index], "witnessVisualAssertion");
    assert.equal(witness.length, 1);
    const screenshot = witness[0].arguments[2].body;
    assert.equal(line(source, tests[index]), reporter[index].declaration);
    assert.equal(line(source, witness[0]), reporter[index].assertion);
    assert.equal(witness[0].arguments[1].text, reporter[index].id);
    assert.equal(screenshot.arguments[0].text, reporter[index].snapshot + ".png");
    assert.deepEqual(producer[index], { id: reporter[index].id, snapshot: screenshot.arguments[0].text });
  }
});

test("browser reporter declaration and assertion whitelists bind to the two closed real specs", () => {
  const admitted = literal(variable(load("ci-browser-reporter.ts"), "SPECS"));
  assert.deepEqual(admitted.map((item) => item.name), ["browser-security.spec.ts", "search-contract.spec.ts"]);
  const titles = [
    ["cross-origin Capture POST is 403 and does not mutate", "same-origin authenticated Capture still works", "missing Origin Capture POST is 403",
      "cross-origin Work PATCH is 403", "missing Origin Work PATCH is 403", "127.0.0.1 Origin against localhost Work PATCH is 403",
      "cross-origin Review decide POST is 403", "cross-origin public WebAuthn POSTs are 403"],
    ["Federated Search BFF keeps typed hits and honest omitted coverage", "Search UX maps federated hits to honest hrefs without capture text",
      "Cmd/Ctrl+K opens Search/New before reusing the same SearchCommandPanel as /search", "a stale out-of-order search response does not replace a newer query",
      "Capture and Knowledge search hrefs are identifier-only", "Search destinations and empty state do not resurrect Assistant, ChatLLM, or MossAIc",
      "TASK-AC-019 a Search Task hit reads the canonical Task once and mutates on that version"],
  ];
  for (let index = 0; index < admitted.length; index++) {
    const spec = admitted[index];
    const source = load(spec.name);
    const tests = calls(source, "test");
    assert.deepEqual(tests.map((node) => node.arguments[0].text), titles[index]);
    assert.deepEqual(tests.map((node) => line(source, node)), spec.declarations);
    assert.deepEqual([...new Set(calls(source, "expect").map((node) => line(source, node)))], spec.assertions);
    const hooks = nodes(source, (node) => ts.isCallExpression(node) && node.expression.getText(source) === "test.beforeEach");
    assert.equal(hooks[0].arguments[0].parameters.length, 0);
    assert.equal(calls(hooks[0], "markBrowserEarly").length, 1);
    if (spec.name === "search-contract.spec.ts") {
      assert.equal(calls(hooks[1], "observeSearchMedia").length, 1);
      assert.equal(calls(hooks[1], "signIn").length, 1);
      assert.ok(calls(hooks[1], "observeSearchMedia")[0].pos < calls(hooks[1], "signIn")[0].pos);
    }
  }
});

test("all three reporter stage enums match the actual signIn producer, not stale helper lines", () => {
  const source = load("fixtures.ts");
  const signIn = nodes(source, (node) => ts.isFunctionDeclaration(node) && node.name?.text === "signIn")[0];
  const stages = new Set(nodes(signIn, (node) => ts.isVariableDeclaration(node) && node.name.getText(source) === "stage").map((node) => node.initializer.text));
  for (const assignment of nodes(signIn, (node) => ts.isBinaryExpression(node) && node.left.getText(source) === "stage")) stages.add(assignment.right.text);
  assert.deepEqual([...stages].sort(), ["click", "goto", "launcher", "overlay", "signinbutton", "todayURL"]);
  for (const name of ["ci-browser-reporter.ts", "ci-responsive-reporter.ts", "ci-visual-reporter.ts"]) {
    const declaration = variable(load(name), "SIGN_IN_STAGES");
    assert.deepEqual(literal(declaration.arguments[0]).sort(), [...stages].sort());
  }
});
