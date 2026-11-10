import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import cp from "node:child_process";
import crypto from "node:crypto";
import net from "node:net";
import { createRequire, Module } from "node:module";
import { test } from "node:test";
const flow = createRequire(import.meta.url)("./linux-visual-assets.cjs");
function header(width, height) {
  const bytes = Buffer.alloc(33);
  Buffer.from("89504e470d0a1a0a", "hex").copy(bytes); bytes.writeUInt32BE(13, 8);
  bytes.write("IHDR", 12); bytes.writeUInt32BE(width, 16); bytes.writeUInt32BE(height, 20);
  return bytes; // Synthetic header fixture only; never a captured or accepted image.
}
const SNAP = "web/e2e/visual.spec.ts-snapshots";
const DARWIN = SNAP + "/shell-zoom-200-desktop-darwin.png";
const baselineBytes = (width, height) => Buffer.concat([header(width, height), Buffer.from("synthetic-previous-baseline")]);
const candidateBytes = (width, height) => Buffer.concat([header(width, height), Buffer.from("synthetic-new-candidate")]);
function fixture({ setAside = true } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "my-pa-asset-unit-"));
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "my-pa-asset-temp-"));
  for (const name of flow.SOURCES) { const file = path.join(root, name); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, "synthetic\n"); }
  const snapshotDir = path.join(root, SNAP); fs.mkdirSync(snapshotDir);
  // The four desktop-linux baselines are TRACKED (unlike PR339), plus one tracked non-target PNG.
  flow.FILES.forEach(([, name, width, height]) => fs.writeFileSync(path.join(snapshotDir, name), baselineBytes(width, height)));
  fs.writeFileSync(path.join(root, DARWIN), baselineBytes(1280, 800));
  cp.execFileSync("git", ["init", "-q"], { cwd: root });
  const approval = { schema: 1, repository: "RMF112018/my-pa", repository_id: 1317234001, branch: flow.BRANCH, base: "main",
    purpose: "PUBLIC_SYNTHETIC_LINUX_BASELINE_CANDIDATES_ONLY", cases: flow.FILES.map((item) => item[1]), expectedSourceDigest: "0".repeat(64) };
  fs.writeFileSync(path.join(root, flow.APPROVAL), JSON.stringify(approval));
  cp.execFileSync("git", ["add", "."], { cwd: root });
  approval.expectedSourceDigest = flow.sourceDigest(root);
  fs.writeFileSync(path.join(root, flow.APPROVAL), JSON.stringify(approval));
  cp.execFileSync("git", ["add", flow.APPROVAL], { cwd: root });
  cp.execFileSync("git", ["-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", "commit", "-qm", "synthetic"], { cwd: root });
  const head = cp.execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
  const env = { CI: "true", CI_VISUAL_ASSET_CAPTURE_REQUEST: "MYPA-WP11-REPORTS-RAIL-LINUX-20261110", GITHUB_REPOSITORY: "RMF112018/my-pa",
    GITHUB_REPOSITORY_ID: "1317234001", MYPA_CAPTURE_VISIBILITY: "public", MYPA_CAPTURE_PR: "352", MYPA_CAPTURE_HEAD_REPO: "1317234001",
    MYPA_CAPTURE_BRANCH: "chore/visual-baselines-reports-rail", GITHUB_HEAD_REF: "chore/visual-baselines-reports-rail",
    MYPA_CAPTURE_BASE: "main", GITHUB_BASE_REF: "main", MYPA_CAPTURE_HEAD: head, MYPA_CAPTURE_FIRST_OUTCOME: "failure",
    GITHUB_EVENT_NAME: "pull_request", GITHUB_JOB: "visual", GITHUB_RUN_ID: "123", GITHUB_RUN_ATTEMPT: "1", RUNNER_OS: "Linux", RUNNER_ARCH: "X64", RUNNER_TEMP: temp,
    MYPA_E2E_ADMIN_URL: "postgresql+psycopg://my_pa:ci_throwaway_not_a_secret@localhost:5432/postgres",
    MYPA_E2E_DATABASE_URL: "postgresql+psycopg://my_pa:ci_throwaway_not_a_secret@localhost:5432/my_pa_wp13_e2e" };
  const clean = () => { fs.rmSync(root, { recursive: true }); fs.rmSync(temp, { recursive: true }); };
  if (!setAside) return { root, temp, env, snapshotDir, clean };
  flow.preflight({ ...env, MYPA_CAPTURE_FIRST_OUTCOME: undefined }, root);
  // Simulated first render: Playwright writes NEW candidates at the vacated tracked paths.
  flow.FILES.forEach(([, name, width, height]) => fs.writeFileSync(path.join(snapshotDir, name), candidateBytes(width, height)));
  const receipt = { schema: 1, pass: "first", head, run: "123", attempt: "1",
    cases: flow.FILES.map(([id]) => ({ id, outcome: "absent-created-error", status: "failed" })) };
  fs.writeFileSync(path.join(temp, "my-pa-linux-visual-first.json"), JSON.stringify(receipt));
  return { root, temp, env, receipt, snapshotDir, clean };
}
const approve = (f) => flow.sourceApproval(f.root, flow.aside(f.env));

test("closed public WP11 stage creates ONLY four bounded PNG candidates and finite manifest", () => {
  const f = fixture();
  try {
    const result = flow.stage(f.env, f.root);
    assert.deepEqual(fs.readdirSync(result.dir).sort(), [...flow.FILES.map((item) => item[1]), "MANIFEST.json"].sort());
    assert.equal(fs.statSync(result.dir).mode & 0o777, 0o700);
    for (const name of fs.readdirSync(result.dir)) assert.equal(fs.statSync(path.join(result.dir, name)).mode & 0o777, 0o600);
    flow.validateManifest(result.manifest, result.id);
    assert.equal(result.manifest.status, "CANDIDATE_NOT_ACCEPTED");
    assert.equal(result.manifest.visibility, "public");
    assert.equal(JSON.stringify(result.manifest).includes("postgresql"), false);
    assert.equal(JSON.stringify(result.manifest).includes(f.temp), false);
    assert.equal(result.manifest.sources.length, 15);
    fs.writeFileSync(path.join(result.dir, "UNAPPROVED.txt"), "synthetic");
    assert.throws(() => flow.verifyStaged(result.dir, result.manifest), /REFUSED/);
  } finally { f.clean(); }
});

const GATE_DEVIATIONS = [["GITHUB_REPOSITORY_ID", "1"], ["GITHUB_REPOSITORY", "someone/my-pa"],
  ["MYPA_CAPTURE_BRANCH", "main"], ["MYPA_CAPTURE_BRANCH", "feat/mcp-database-profiles"], ["GITHUB_HEAD_REF", "chore/other"],
  ["MYPA_CAPTURE_BASE", "develop"], ["GITHUB_BASE_REF", "release"], ["MYPA_CAPTURE_HEAD_REPO", "999999"], ["MYPA_CAPTURE_HEAD_REPO", ""],
  ["GITHUB_EVENT_NAME", "push"], ["GITHUB_EVENT_NAME", "pull_request_target"], ["GITHUB_EVENT_NAME", "workflow_dispatch"],
  ["CI_VISUAL_ASSET_CAPTURE_REQUEST", "MYPA-PR339-LINUX-20261024"], ["CI_VISUAL_ASSET_CAPTURE_REQUEST", ""],
  ["CI_VISUAL_ASSET_CAPTURE_REQUEST", undefined], ["CI", undefined], ["MYPA_CAPTURE_PR", "abc"], ["MYPA_CAPTURE_PR", undefined],
  ["MYPA_CAPTURE_VISIBILITY", "private"], ["GITHUB_JOB", "browsers"], ["RUNNER_OS", "macOS"], ["MYPA_CAPTURE_HEAD", "a".repeat(40)]];
const without = (env, key, value) => { const next = { ...env }; if (value === undefined) delete next[key]; else next[key] = value; return next; };
test("identity() gate is closed: wrong branch/base/fork head repo/event/token/repository each refuse; PR number is NOT a gate", () => {
  const f = fixture({ setAside: false });
  try {
    const env = { ...f.env, MYPA_CAPTURE_FIRST_OUTCOME: undefined };
    assert.ok(flow.identity(env, f.root, true).approvedSourceDigest); // Positive control: the exact gate opens.
    assert.ok(flow.identity({ ...env, MYPA_CAPTURE_PR: "1" }, f.root, true)); // Any digits: informational only.
    for (const [key, value] of GATE_DEVIATIONS) {
      assert.throws(() => flow.identity(without(env, key, value), f.root, true), /REFUSED/, `${key}=${value}`);
      assert.throws(() => flow.preflight(without(env, key, value), f.root), /REFUSED/, `${key}=${value}`);
    }
    // A refused preflight never moved a baseline and never created the set-aside directory.
    for (const [, name] of flow.FILES) assert.ok(fs.existsSync(path.join(f.snapshotDir, name)));
    assert.deepEqual(fs.readdirSync(f.temp), []);
  } finally { f.clean(); }
});
test("other repositories/branches/bases/forks/events/visibility/outcomes cannot stage", () => {
  const f = fixture();
  try {
    for (const [key, value] of [...GATE_DEVIATIONS, ["MYPA_CAPTURE_FIRST_OUTCOME", "success"]]) {
      assert.throws(() => flow.stage(without(f.env, key, value), f.root), /REFUSED/, `${key}=${value}`);
    }
    assert.ok(flow.stage(f.env, f.root).manifest); // Positive control after all refusals.
  } finally { f.clean(); }
});
test("preflight verifies the pristine checkout, then moves ONLY the four tracked desktop-linux baselines into a 0700 dir", () => {
  const f = fixture({ setAside: false });
  try {
    const env = { ...f.env, MYPA_CAPTURE_FIRST_OUTCOME: undefined };
    const pristine = flow.sourceApproval(f.root);
    const before = flow.FILES.map(([, name]) => fs.readFileSync(path.join(f.snapshotDir, name)));
    const result = flow.preflight(env, f.root);
    assert.equal(result.dir, flow.asidePath(env));
    assert.equal(fs.statSync(result.dir).mode & 0o777, 0o700);
    assert.deepEqual(fs.readdirSync(result.dir).sort(), flow.FILES.map((item) => item[1]).sort());
    flow.FILES.forEach(([, name], index) => {
      assert.equal(fs.existsSync(path.join(f.snapshotDir, name)), false); // Playwright will CREATE, not compare.
      assert.deepEqual(fs.readFileSync(path.join(result.dir, name)), before[index]);
      assert.equal(fs.statSync(path.join(result.dir, name)).mode & 0o777, 0o600);
    });
    assert.ok(fs.existsSync(path.join(f.root, DARWIN))); // Non-target tracked PNGs untouched.
    // Absent workspace paths: pristine verification refuses; held verification yields the SAME digest.
    assert.throws(() => flow.sourceApproval(f.root), /REFUSED/);
    assert.equal(flow.sourceApproval(f.root, flow.aside(env)), pristine);
    // A second preflight cannot overwrite the held copies.
    assert.throws(() => flow.preflight(env, f.root), /REFUSED/);
  } finally { f.clean(); }
});
test("preflight refuses a tampered or untracked baseline before moving anything", () => {
  for (const action of ["tampered", "untracked"]) {
    const f = fixture({ setAside: false });
    try {
      const name = path.join(f.snapshotDir, flow.FILES[2][1]);
      if (action === "tampered") fs.appendFileSync(name, "x");
      if (action === "untracked") { cp.execFileSync("git", ["rm", "-q", "--cached", path.join(SNAP, flow.FILES[2][1])], { cwd: f.root }); }
      assert.throws(() => flow.preflight({ ...f.env, MYPA_CAPTURE_FIRST_OUTCOME: undefined }, f.root), /REFUSED/);
      for (const [, file] of flow.FILES) assert.ok(fs.existsSync(path.join(f.snapshotDir, file)));
    } finally { f.clean(); }
  }
});
test("held verification redirects EXACTLY the four baselines; everything else stays verified in the workspace", () => {
  const cases = {
    "tampered held copy": (f, held) => fs.appendFileSync(path.join(held.dir, flow.FILES[0][1]), "x"),
    "missing held copy": (f, held) => fs.unlinkSync(path.join(held.dir, flow.FILES[3][1])),
    "extra held member": (f, held) => fs.writeFileSync(path.join(held.dir, "extra.png"), "x", { mode: 0o600 }),
    "held copy mode 0644": (f, held) => fs.chmodSync(path.join(held.dir, flow.FILES[1][1]), 0o644),
    "held dir mode 0755": (f, held) => fs.chmodSync(held.dir, 0o755),
    "tampered non-target tracked PNG": (f) => fs.appendFileSync(path.join(f.root, DARWIN), "x"),
    "tampered tracked source": (f) => fs.appendFileSync(path.join(f.root, flow.SOURCES[3]), "x"),
  };
  for (const [label, mutate] of Object.entries(cases)) {
    const f = fixture();
    try {
      approve(f); // Positive control on candidate-bearing workspace.
      mutate(f, flow.aside(f.env));
      assert.throws(() => approve(f), /REFUSED/, label);
    } finally { f.clean(); }
  }
  const f = fixture();
  try { // A swapped held directory (same name, new inode) refuses under the remembered identity.
    const held = flow.aside(f.env);
    fs.renameSync(held.dir, held.dir + "-moved"); fs.mkdirSync(held.dir, { mode: 0o700 });
    for (const name of fs.readdirSync(held.dir + "-moved")) fs.copyFileSync(path.join(held.dir + "-moved", name), path.join(held.dir, name));
    for (const name of fs.readdirSync(held.dir)) fs.chmodSync(path.join(held.dir, name), 0o600);
    assert.throws(() => flow.sourceApproval(f.root, held), /REFUSED/);
  } finally { f.clean(); }
});
test("manifest records previous_baselines bound to the tracked blobs of the moved-aside copies", () => {
  const f = fixture();
  try {
    const { manifest } = flow.stage(f.env, f.root);
    assert.equal(manifest.pr_informational, "352");
    assert.equal(manifest.branch, "chore/visual-baselines-reports-rail"); assert.equal(manifest.base, "main");
    const blobs = cp.execFileSync("git", ["ls-files", "-s", SNAP], { cwd: f.root, encoding: "utf8" });
    manifest.previous_baselines.forEach((item, index) => {
      const [, name, width, height] = flow.FILES[index];
      assert.equal(item.name, name);
      assert.ok(blobs.includes(`${item.blob} 0\t${SNAP}/${name}`));
      assert.equal(item.sha256, crypto.createHash("sha256").update(baselineBytes(width, height)).digest("hex"));
      assert.notEqual(item.sha256, manifest.images[index].sha256); // Candidates are the NEW renders.
    });
  } finally { f.clean(); }
});

test("receipts reject unknown/conflicting cases, extra payload fields and wrong head", () => {
  const f = fixture();
  try {
    for (const edit of [(r) => { r.cases[1].id = "light"; }, (r) => { r.cases[0].outcome = "hard-throw"; },
      (r) => { r.body = "SYNTHETIC_PRIVATE_MARKER"; }, (r) => { r.head = "a".repeat(40); }]) {
      const value = structuredClone(f.receipt); edit(value);
      const file = path.join(f.temp, "bad.json"); fs.writeFileSync(file, JSON.stringify(value));
      assert.throws(() => flow.receipt(file, "first", flow.identity(f.env, f.root)), /REFUSED/);
    }
  } finally { f.clean(); }
});

test("PNG validation rejects symlinks, malformed signature, dimensions, size and parent links", () => {
  const f = fixture();
  try {
    const file = path.join(f.snapshotDir, flow.FILES[0][1]);
    fs.writeFileSync(file, header(640, 800)); assert.throws(() => flow.candidates(f.root), /REFUSED/);
    fs.writeFileSync(file, Buffer.alloc(33)); assert.throws(() => flow.candidates(f.root), /REFUSED/);
    fs.writeFileSync(file, Buffer.alloc(2 * 1024 * 1024 + 1)); assert.throws(() => flow.candidates(f.root), /REFUSED/);
    fs.unlinkSync(file); fs.symlinkSync(path.join(f.snapshotDir, flow.FILES[1][1]), file); assert.throws(() => flow.candidates(f.root), /REFUSED/);
    fs.unlinkSync(file); fs.writeFileSync(file, header(1280, 800));
    fs.renameSync(f.snapshotDir, f.snapshotDir + "-owned"); fs.symlinkSync(f.snapshotDir + "-owned", f.snapshotDir);
    assert.throws(() => flow.candidates(f.root), /REFUSED/);
  } finally { f.clean(); }
});

test("manifest and endpoint checks reject added payload or non-synthetic targets", () => {
  const f = fixture();
  try {
    const result = flow.stage(f.env, f.root); result.manifest.extra = "SYNTHETIC_PRIVATE_MARKER";
    assert.throws(() => flow.validateManifest(result.manifest, result.id), /REFUSED/);
    for (const url of ["postgresql+psycopg://my_pa:ci_throwaway_not_a_secret@db.invalid:5432/postgres",
      "postgresql+psycopg://owner@localhost:5432/postgres", "postgresql+psycopg://my_pa:ci_throwaway_not_a_secret@localhost:5432/postgres?options=other"]) {
      assert.throws(() => flow.testUrl(url, "postgres"), /REFUSED/);
    }
  } finally { f.clean(); }
});

test("ONE controlled repeat uses a distinct fresh seed and gates upload on all matches/cleanup", async () => {
  const f = fixture();
  const originalSpawn = cp.spawnSync;
  const originalServer = net.createServer;
  let runs = 0;
  let bindChecks = 0;
  try {
    flow.stage(f.env, f.root);
    net.createServer = () => ({ once() {}, listen(port, host, callback) {
      assert.ok([9099, 3100, 3101].includes(port)); assert.equal(host, "127.0.0.1"); bindChecks++; callback();
    }, close(callback) { callback(); } });
    cp.spawnSync = (command, args, options) => {
      if (command === "python3") return originalSpawn(command, args, options);
      if (command === "synthetic-python") return { status: 0, stdout: "absent\n" };
      assert.equal(command, "npm"); runs++;
      assert.deepEqual(args, ["run", "e2e", "--", "e2e/visual.spec.ts", "--project=desktop"]);
      assert.equal(options.env.MYPA_E2E_DATABASE, "my_pa_visual_repeat_123_1");
      assert.equal(new URL(options.env.MYPA_E2E_DATABASE_URL).pathname, "/my_pa_visual_repeat_123_1");
      assert.equal(options.env.PRIVATE_TOKEN, undefined);
      fs.writeFileSync(path.join(f.temp, "my-pa-linux-visual-repeat.json"), JSON.stringify({ ...f.receipt, pass: "repeat",
        cases: flow.FILES.map(([id]) => ({ id, outcome: "matched-no-delta", status: "passed" })) }));
      return { status: 0 };
    };
    const dir = await flow.repeat({ ...f.env, MYPA_E2E_PYTHON: "synthetic-python", PRIVATE_TOKEN: "MUST_NOT_COPY" }, f.root);
    assert.equal(runs, 1); assert.equal(bindChecks, 6);
    const manifest = JSON.parse(fs.readFileSync(path.join(dir, "MANIFEST.json")));
    assert.equal(manifest.first_step, "failure_preserved");
    assert.equal(manifest.repeat.result, "existing_matcher_pass");
    assert.equal(manifest.repeat.first_hashes_unchanged, true);
    assert.equal(JSON.stringify(manifest).includes("MUST_NOT_COPY"), false);
  } finally { cp.spawnSync = originalSpawn; net.createServer = originalServer; f.clean(); }
});

test("an incomplete cleanup refuses the repeat instead of retrying or masking first failure", async () => {
  const f = fixture(); const original = cp.spawnSync;
  try {
    flow.stage(f.env, f.root);
    cp.spawnSync = (command, args, options) => command === "python3" ? original(command, args, options) : ({ status: 0, stdout: "present\n" });
    await assert.rejects(flow.repeat({ ...f.env, MYPA_E2E_PYTHON: "synthetic-python" }, f.root), /REFUSED/);
  } finally { cp.spawnSync = original; f.clean(); }
});

const WORKFLOW = fs.readFileSync(new URL("../../.github/workflows/frontend-quality.yml", import.meta.url), "utf8");
const VISUAL = WORKFLOW.slice(WORKFLOW.indexOf("\n  visual:\n"), WORKFLOW.indexOf("\n  performance:\n"));
test("the public artifact flow is closed to the WP11 branch gate and preserves first-step failure", () => {
  const visual = VISUAL;
  const gateLine = visual.split("\n").find((line) => line.trim().startsWith("CI_VISUAL_ASSET_CAPTURE_REQUEST:"));
  assert.ok(gateLine);
  for (const clause of ["github.event_name == 'pull_request'", "github.repository_id == '1317234001'",
    "github.event.pull_request.head.repo.id == 1317234001", "github.head_ref == 'chore/visual-baselines-reports-rail'",
    "github.base_ref == 'main'", "'MYPA-WP11-REPORTS-RAIL-LINUX-20261110' || ''"]) assert.ok(gateLine.includes(clause), clause);
  // Every clause is conjunctive: no alternative branch can open the gate.
  assert.equal(gateLine.split("||").length, 2);
  assert.equal(/pull_request\.number/.test(gateLine), false); // A PR number never gates.
  assert.equal((visual.match(/MYPA-WP11-REPORTS-RAIL-LINUX-20261110/g) || []).length, 3); // gate expression + preflight + stage conditions only
  assert.equal(/MYPA-PR339|feat\/mcp-database-profiles/.test(visual), false);
  assert.match(visual, /steps\.visual_assertions\.outcome == 'failure'/);
  assert.match(visual, /steps\.linux_repeat\.outputs\.safe_upload == 'true'/);
  assert.match(visual, /upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9/);
  const paths = visual.slice(visual.indexOf("          path: |"), visual.indexOf("          include-hidden-files:"));
  assert.equal(paths.trim().split("\n").length, 6);
  assert.equal(paths.includes("*"), false);
  assert.equal(paths.includes("previous"), false); // The held baselines are never uploaded.
  assert.match(visual, /retention-days: 1\n/);
  assert.match(visual, /if-no-files-found: error\n/);
  assert.equal((visual.match(/continue-on-error:/g) || []).length, 1); // Existing advisory job only.
  assert.equal((visual.match(/--update-snapshots/g) || []).length, 1); // Existing prohibition comment only.
  assert.equal((visual.match(/uses: /g) || []).length, 4); // checkout, setup-python, setup-node, upload-artifact.
});
test("workflow structure: no privileged trigger anywhere and no write permission anywhere", () => {
  assert.equal(WORKFLOW.includes("pull_request_target"), false);
  const lines = WORKFLOW.split("\n");
  assert.deepEqual(lines.filter((line) => /:\s*write(-all)?\b/.test(line)), []);
  let blocks = 0;
  lines.forEach((line, index) => {
    const opened = /^(\s*)permissions:\s*(.*)$/.exec(line);
    if (!opened) return;
    blocks++;
    if (opened[2] !== "") { assert.match(opened[2], /^(read-all|\{\})$/); return; }
    for (let next = index + 1; next < lines.length; next++) {
      const indent = /^(\s*)/.exec(lines[next])[1].length;
      if (lines[next].trim() === "" || indent <= opened[1].length) break;
      assert.match(lines[next].trim(), /^[a-z-]+: (read|none)$/);
    }
  });
  assert.ok(blocks >= 1);
  assert.equal(/\n    permissions:/.test(VISUAL), false); // The visual job inherits the workflow-level read-only token.
  assert.match(WORKFLOW, /\npermissions:\n  contents: read\n/);
});

function commitSynthetic(f) {
  // Never stage the simulated render candidates: only the drift under test may change the index.
  cp.execFileSync("git", ["add", "--", ".", ":(exclude)" + SNAP], { cwd: f.root });
  cp.execFileSync("git", ["-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", "commit", "-qm", "synthetic drift"], { cwd: f.root });
}
test("Manager source approval refuses committed workflow/render/seed/extra-file changes", () => {
  for (const name of [".github/workflows/frontend-quality.yml", "web/e2e/visual.spec.ts", "tests/end_to_end/seed_work.py", "extra-tracked.txt"]) {
    const f = fixture();
    try {
      fs.appendFileSync(path.join(f.root, name), "changed\n"); commitSynthetic(f);
      assert.throws(() => approve(f), /REFUSED/);
    } finally { f.clean(); }
  }
});
test("approval must be a single tracked non-executable regular file with a strict bounded schema", () => {
  for (const action of ["untracked", "symlink", "executable", "extra-key", "oversize"]) {
    const f = fixture(); const file = path.join(f.root, flow.APPROVAL);
    try {
      if (action === "untracked") cp.execFileSync("git", ["rm", "--cached", flow.APPROVAL], { cwd: f.root });
      if (action === "symlink") { fs.unlinkSync(file); fs.symlinkSync(path.join(f.root, flow.SOURCES[0]), file); }
      if (action === "executable") fs.chmodSync(file, 0o755);
      if (action === "extra-key") { const value = JSON.parse(fs.readFileSync(file)); value.extra = "OPAQUE_PRIVATE_MARKER"; fs.writeFileSync(file, JSON.stringify(value)); }
      if (action === "oversize") fs.writeFileSync(file, "x".repeat(4097));
      assert.throws(() => approve(f), /REFUSED/);
    } finally { f.clean(); }
  }
});
test("source byte verification ignores stat-cache shortcuts and rejects mode/index flags", () => {
  for (const action of ["same-size-restored-mtime", "executable", "assume-unchanged", "skip-worktree", "staged-drift"]) {
    const f = fixture(); const relative = flow.SOURCES[0]; const file = path.join(f.root, relative);
    try {
      if (action === "same-size-restored-mtime") { const st = fs.statSync(file); fs.writeFileSync(file, "different\n"); fs.utimesSync(file, st.atime, st.mtime); }
      if (action === "executable") fs.chmodSync(file, 0o755);
      if (["assume-unchanged", "skip-worktree"].includes(action)) cp.execFileSync("git", ["update-index", "--" + action, relative], { cwd: f.root });
      if (action === "staged-drift") { fs.appendFileSync(file, "drift\n"); cp.execFileSync("git", ["add", relative], { cwd: f.root }); }
      assert.throws(() => approve(f), /REFUSED/);
    } finally { f.clean(); }
  }
});
test("nofollow parent traversal rejects a replacement symlink before unknown bytes are acquired", () => {
  const f = fixture(); const original = cp.spawnSync; let planted = false;
  try {
    cp.spawnSync = (command, args, options) => {
      if (command !== "python3" || planted || JSON.parse(options.input).verb !== "read") return original(command, args, options);
      planted = true;
      const marker = "        before=os.stat(part,dir_fd=fds[-1],follow_symlinks=False)";
      const injected = marker + "\n        if part=='visual.spec.ts-snapshots':\n            os.rename('visual.spec.ts-snapshots','owned-original',src_dir_fd=fds[-1],dst_dir_fd=fds[-1])\n            os.symlink('owned-original','visual.spec.ts-snapshots',dir_fd=fds[-1])";
      return original(command, [args[0], args[1].replace(marker, injected)], options);
    };
    assert.throws(() => flow.candidates(f.root), /REFUSED/); assert.equal(planted, true);
  } finally { cp.spawnSync = original; f.clean(); }
});
test("an already-open parent fd retains the verified original directory after a path swap", () => {
  const f = fixture(); const original = cp.spawnSync; let planted = false;
  try {
    cp.spawnSync = (command, args, options) => {
      if (command !== "python3" || planted || JSON.parse(options.input).verb !== "read") return original(command, args, options);
      planted = true;
      const marker = "        fd=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=p)";
      const injected = "        if file.endswith('shell-light-unavailable-desktop-linux.png'):\n            os.rename(os.path.dirname(file),os.path.dirname(file)+'-original')\n            os.symlink(os.path.dirname(file)+'-original',os.path.dirname(file))\n" + marker;
      return original(command, [args[0], args[1].replace(marker, injected)], options);
    };
    // The first file is read from the held original fd; subsequent traversal
    // refuses the symlink. The replacement can never redirect later reads.
    assert.throws(() => flow.candidates(f.root), /REFUSED/); assert.equal(planted, true);
  } finally { cp.spawnSync = original; f.clean(); }
});
test("growth after fstat is acquired only through a limit+1 bounded read before refusal", () => {
  const f = fixture(); const original = cp.spawnSync; let planted = false;
  const file = path.join(f.root, "owned-growth.bin"); fs.writeFileSync(file, Buffer.alloc(16));
  try {
    cp.spawnSync = (command, args, options) => {
      if (command !== "python3" || planted) return original(command, args, options);
      planted = true;
      const marker = "            total=0";
      const injected = "            grow=os.open(file,os.O_WRONLY|os.O_APPEND)\n            os.write(grow,b'x'*1024);os.close(grow)\n            original_read=os.read\n            def checked_read(fd,count):\n                assert count<=limit+1\n                return original_read(fd,count)\n            os.read=checked_read\n" + marker;
      const result = original(command, [args[0], args[1].replace(marker, injected)], options);
      assert.equal(result.stdout.length, 0); return result;
    };
    assert.throws(() => flow.regular(file, 16), /REFUSED/); assert.equal(planted, true);
  } finally { cp.spawnSync = original; f.clean(); }
});
test("repeat refuses an existing repeat database BEFORE invoking stack.sh's unconditional DROP", async () => {
  const f = fixture(); const original = cp.spawnSync; const originalServer = net.createServer; let launches = 0; const probes = [];
  try {
    flow.stage(f.env, f.root);
    net.createServer = () => ({ once() {}, listen(port, host, callback) { callback(); }, close(callback) { callback(); } });
    cp.spawnSync = (command, args, options) => {
      if (command === "python3") return original(command, args, options);
      if (command === "synthetic-python") { probes.push(options.env.MYPA_CHECK_DB); return { status: 0, stdout: options.env.MYPA_CHECK_DB === "my_pa_visual_repeat_123_1" ? "present\n" : "absent\n" }; }
      launches++; return { status: 0 };
    };
    await assert.rejects(flow.repeat({ ...f.env, MYPA_E2E_PYTHON: "synthetic-python" }, f.root), /REFUSED/);
    assert.deepEqual(probes, ["my_pa_wp13_e2e", "my_pa_visual_repeat_123_1"]); assert.equal(launches, 0);
  } finally { cp.spawnSync = original; net.createServer = originalServer; f.clean(); }
});
test("stage writes retain the created directory identity and refuse a swapped parent", () => {
  const f = fixture(); const original = cp.spawnSync; let planted = false;
  try {
    cp.spawnSync = (command, args, options) => {
      if (command === "python3") {
        const q = JSON.parse(options.input);
        if (q.verb === "write" && !planted) {
          planted = true; const dir = path.dirname(q.file);
          fs.renameSync(dir, dir + "-original"); fs.symlinkSync(dir + "-original", dir);
        }
      }
      return original(command, args, options);
    };
    assert.throws(() => flow.stage(f.env, f.root), /REFUSED/); assert.equal(planted, true);
    assert.deepEqual(fs.readdirSync(path.join(f.temp, "my-pa-linux-visual-123-1-original")), []);
  } finally { cp.spawnSync = original; f.clean(); }
});
test("fsmonitor-valid lowercase Git flags are rejected without trusting cached source status", () => {
  const f = fixture(); const original = cp.execFileSync; let planted = false;
  try {
    cp.execFileSync = (command, args, options) => {
      const result = original(command, args, options);
      if (command === "git" && args.includes("-v") && args.includes("-f")) { planted = true; return result.replace(/^H /, "h "); }
      return result;
    };
    assert.throws(() => approve(f), /REFUSED/); assert.equal(planted, true);
  } finally { cp.execFileSync = original; f.clean(); }
});
test("approval parsing uses the SAME verified buffer when the on-disk control changes afterward", () => {
  const f = fixture(); const original = cp.spawnSync; let planted = false;
  try {
    const file = path.join(f.root, flow.APPROVAL);
    const control = JSON.parse(fs.readFileSync(file)); control.expectedSourceDigest = "0".repeat(64);
    fs.writeFileSync(file, JSON.stringify(control)); commitSynthetic(f);
    cp.spawnSync = (command, args, options) => {
      const result = original(command, args, options);
      if (command === "python3" && JSON.parse(options.input).verb === "sources") {
        planted = true; control.expectedSourceDigest = flow.sourceDigest(f.root);
        fs.writeFileSync(file, JSON.stringify(control));
      }
      return result;
    };
    assert.throws(() => approve(f), /REFUSED/); assert.equal(planted, true);
  } finally { cp.spawnSync = original; f.clean(); }
});
test("Linux /tmp and /var paths are preserved before the actual nofollow traversal", () => {
  const original = cp.spawnSync;
  try {
    for (const prefix of ["/tmp", "/var"]) {
      let checked = false;
      cp.spawnSync = (command, args, options) => {
        const q = JSON.parse(options.input);
        assert.equal(q.file, prefix + "/owned-synthetic-parent/fixture");
        // Exercise the actual normalization branches under Linux semantics,
        // then exit before touching an artificial Linux path on a Darwin host.
        const source = args[1].replace("q=json.loads", "sys.platform='linux'\nq=json.loads")
          .replace("    parts=file.split('/')", "    assert file==q['file']\n    sys.stdout.buffer.write(b'linux-path-preserved');sys.exit(0)\n    parts=file.split('/')");
        checked = true; return original(command, [args[0], source], options);
      };
      assert.equal(flow.regular(prefix + "/owned-synthetic-parent/fixture", 64).toString(), "linux-path-preserved");
      assert.equal(checked, true);
    }
  } finally { cp.spawnSync = original; }
});
function boundedFifoSpawn(original, transform = (source) => source) {
  return (command, args, options) => {
    assert.equal(command, "python3");
    const result = original(command, [args[0], transform(args[1])], { ...options, timeout: 1000, killSignal: "SIGKILL" });
    // The deadline cleans up only this owned test child. A timeout is a test
    // failure, never evidence that the production helper correctly refused.
    assert.notEqual(result.error?.code, "ETIMEDOUT"); return result;
  };
}
test("an owned FIFO leaf refuses before opening or acquiring bytes", () => {
  const f = fixture(); const original = cp.spawnSync; const file = path.join(f.root, "owned-fifo");
  try {
    cp.execFileSync("mkfifo", [file]); cp.spawnSync = boundedFifoSpawn(original);
    assert.throws(() => flow.regular(file, 64), /REFUSED/);
  } finally { cp.spawnSync = original; f.clean(); }
});
test("a regular read leaf replaced by a FIFO between stat/open refuses without blocking", () => {
  const f = fixture(); const original = cp.spawnSync; const file = path.join(f.root, "owned-race-leaf"); let planted = false;
  fs.writeFileSync(file, "synthetic");
  try {
    cp.spawnSync = boundedFifoSpawn(original, (source) => {
      const marker = "        fd=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=p)";
      assert.ok(source.includes(marker)); planted = true;
      return source.replace(marker, "        os.unlink(n,dir_fd=p);os.mkfifo(n,0o600,dir_fd=p)\n" + marker);
    });
    assert.throws(() => flow.regular(file, 64), /REFUSED/); assert.equal(planted, true);
  } finally { cp.spawnSync = original; f.clean(); }
});
function actualManifestWriter() {
  const file = new URL("./linux-visual-assets.cjs", import.meta.url);
  const loaded = new Module(file.pathname); loaded.filename = file.pathname;
  loaded.paths = Module._nodeModulePaths(path.dirname(file.pathname));
  loaded._compile(fs.readFileSync(file, "utf8") + "\nmodule.exports.unitManifestWriter=saveManifest;\n", file.pathname);
  return loaded.exports.unitManifestWriter;
}
test("manifest replacement refuses existing FIFO and regular-to-FIFO race before truncation/write", () => {
  const f = fixture(); const original = cp.spawnSync; const writeManifest = actualManifestWriter();
  const file = path.join(f.temp, "MANIFEST.json");
  try {
    cp.execFileSync("mkfifo", [file]); cp.spawnSync = boundedFifoSpawn(original);
    assert.throws(() => writeManifest(f.temp, { finite: true }, true), /REFUSED/);
    cp.spawnSync = original; fs.unlinkSync(file); fs.writeFileSync(file, "original", { mode: 0o600 });
    let planted = false;
    cp.spawnSync = boundedFifoSpawn(original, (source) => {
      const marker = "        fd=os.open(n,flags,0o600,dir_fd=p)";
      assert.ok(source.includes(marker)); planted = true;
      return source.replace(marker, "        os.unlink(n,dir_fd=p);os.mkfifo(n,0o600,dir_fd=p)\n" + marker);
    });
    assert.throws(() => writeManifest(f.temp, { finite: true }, true), /REFUSED/); assert.equal(planted, true);
  } finally { cp.spawnSync = original; f.clean(); }
});
