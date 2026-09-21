#!/usr/bin/env node
/**
 * Prove that a CI lane is about to run the tests it claims to run.
 *
 * A Playwright lane is a sentence in a workflow file: some spec paths, some
 * `--project` flags. Every part of that sentence can go quietly wrong — a spec
 * renamed, a `testMatch` narrowed, a project renamed, a describe block that
 * skips itself on every project in the lane. None of those turn the lane red.
 * Playwright exits 0 on an empty selection and 0 on a selection that is
 * entirely skipped, so the lane keeps reporting green while measuring nothing.
 * That is the failure this sentinel exists to make loud.
 *
 * It runs the lane's own selection through `playwright test --list
 * --reporter=json` and refuses, with a non-zero exit, unless all of:
 *
 *   1. the selection contains at least one test;
 *   2. every declared spec file contributes at least one selected test;
 *   3. every declared sentinel title is present in the selection;
 *   4. the selection is not entirely skipped — at least one selected test
 *      carries neither a `skip` nor a `fixme` annotation.
 *
 * No global test total is hard-coded here on purpose. A pinned count is a
 * tripwire for ordinary authoring, and the pressure it creates is to edit the
 * number rather than ask why it moved. The declared files and sentinel titles
 * come from the command line instead, so the workflow file stays the single
 * place the lane's intent is written down.
 *
 * Usage:
 *
 *   node scripts/verify-e2e-selection.mjs \
 *     --project=mobile-webkit \
 *     --file=e2e/mobile-foundation.spec.ts \
 *     --file=e2e/diagnostics-visibility.spec.ts \
 *     --sentinel="the emulation lane really is a coarse pointer" \
 *     --sentinel="the accepted preference survives navigation and reload"
 *
 * `--project` may be repeated (as on the real command) and may be omitted, in
 * which case Playwright's own default projects apply. `--file` is both the
 * selection passed to Playwright and the set that must be covered, so it is
 * never possible for the lane to execute a file this check did not verify.
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";

const USAGE = `verify-e2e-selection — prove a Playwright lane selects what it claims

  node scripts/verify-e2e-selection.mjs [--project=NAME ...] --file=PATH [--file=PATH ...] [--sentinel=TITLE ...]

  --file=PATH       A spec path, exactly as the lane passes it to Playwright.
                    Repeatable, required. Every one must contribute >= 1 test.
  --project=NAME    A Playwright project, exactly as the lane passes it.
                    Repeatable, optional.
  --sentinel=TITLE  A test title that must appear in the selection. Matched
                    against the test's own title and against its full title
                    (describe chain included). Repeatable, optional.
  -h, --help        This text.

Exits 0 only when the selection is non-empty, every declared file contributes,
every sentinel is present, and at least one selected test is not skipped.`;

function parseArgs(argv) {
  const files = [];
  const projects = [];
  const sentinels = [];
  for (const arg of argv) {
    if (arg === "-h" || arg === "--help") return { help: true, files, projects, sentinels };
    const match = /^--(file|project|sentinel)=([\s\S]*)$/.exec(arg);
    if (!match) {
      throw new Error(`unrecognised argument: ${arg}`);
    }
    const value = match[2];
    if (value.length === 0) throw new Error(`--${match[1]} was given an empty value`);
    if (match[1] === "file") files.push(value);
    else if (match[1] === "project") projects.push(value);
    else sentinels.push(value);
  }
  return { help: false, files, projects, sentinels };
}

/** Walk the `--list` JSON, which nests suites by file and then by describe. */
function collectSpecs(node, titleTrail, out) {
  for (const spec of node.specs ?? []) {
    const fullTitle = [...titleTrail, spec.title].join(" › ");
    const tests = spec.tests ?? [];
    // A spec counts as skipped only when every one of its project entries is,
    // so one live projection of a test is enough to keep the lane honest.
    const skipped =
      tests.length > 0 &&
      tests.every((test) =>
        (test.annotations ?? []).some((a) => a.type === "skip" || a.type === "fixme"),
      );
    out.push({ title: spec.title, fullTitle, file: spec.file ?? node.file ?? "", skipped });
  }
  for (const child of node.suites ?? []) {
    collectSpecs(child, child.title ? [...titleTrail, child.title] : titleTrail, out);
  }
}

function main() {
  let parsed;
  try {
    parsed = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`verify-e2e-selection: ${error.message}\n\n${USAGE}`);
    return 2;
  }
  if (parsed.help) {
    console.log(USAGE);
    return 0;
  }
  const { files, projects, sentinels } = parsed;
  if (files.length === 0) {
    console.error(`verify-e2e-selection: at least one --file is required\n\n${USAGE}`);
    return 2;
  }

  const args = ["playwright", "test", "--list", "--reporter=json", ...files];
  for (const project of projects) args.push(`--project=${project}`);

  const lane = `${files.join(" ")}${projects.length ? ` ${projects.map((p) => `--project=${p}`).join(" ")}` : ""}`;
  console.log(`verify-e2e-selection: listing ${lane}`);

  const listed = spawnSync("npx", args, {
    cwd: process.cwd(),
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    env: process.env,
  });
  if (listed.error) {
    console.error(`verify-e2e-selection: could not run playwright --list: ${listed.error.message}`);
    return 1;
  }

  let report;
  try {
    // `--list --reporter=json` writes the report to stdout, but a dev-server or
    // config banner can precede it. Take from the first `{` so a stray line of
    // noise is not read as a broken selection.
    const start = listed.stdout.indexOf("{");
    if (start < 0) throw new Error("no JSON object in output");
    report = JSON.parse(listed.stdout.slice(start));
  } catch (error) {
    console.error(
      `verify-e2e-selection: playwright --list produced no parseable JSON (${error.message}).\n` +
        `exit code ${listed.status}\n--- stdout ---\n${listed.stdout}\n--- stderr ---\n${listed.stderr}`,
    );
    return 1;
  }

  const specs = [];
  for (const suite of report.suites ?? []) {
    collectSpecs(suite, suite.title ? [suite.title] : [], specs);
  }

  const problems = [];

  if (specs.length === 0) {
    problems.push(
      `the selection is empty: playwright listed 0 tests for ${lane}. ` +
        `A lane that selects nothing passes without measuring anything.`,
    );
  }

  // Every declared file must contribute. Reported paths are relative to the
  // Playwright root, so compare on a normalised suffix rather than demanding
  // the workflow spell the path the same way the reporter does.
  const reportedFiles = new Set(specs.map((spec) => spec.file.split(path.sep).join("/")));
  for (const declared of files) {
    const wanted = declared.split(path.sep).join("/").replace(/^\.\//, "");
    const covered = [...reportedFiles].some(
      (reported) => reported === wanted || reported.endsWith(`/${wanted}`) || wanted.endsWith(`/${reported}`),
    );
    if (!covered) {
      problems.push(
        `declared spec file contributed no selected test: ${declared}. ` +
          `Files that did contribute: ${[...reportedFiles].sort().join(", ") || "(none)"}`,
      );
    }
  }

  for (const sentinel of sentinels) {
    const present = specs.some((spec) => spec.title === sentinel || spec.fullTitle === sentinel);
    if (!present) {
      problems.push(`declared sentinel test title is not in the selection: "${sentinel}"`);
    }
  }

  if (specs.length > 0 && specs.every((spec) => spec.skipped)) {
    problems.push(
      `every one of the ${specs.length} selected tests is annotated skip or fixme. ` +
        `This lane would report green having executed nothing.`,
    );
  }

  const live = specs.filter((spec) => !spec.skipped).length;
  if (problems.length > 0) {
    console.error(`verify-e2e-selection: FAILED for ${lane}`);
    for (const problem of problems) console.error(`  - ${problem}`);
    return 1;
  }

  console.log(
    `verify-e2e-selection: OK — ${specs.length} tests selected (${live} not annotated skip/fixme) ` +
      `across ${reportedFiles.size} file(s); ${sentinels.length} sentinel(s) present.`,
  );
  return 0;
}

process.exit(main());
