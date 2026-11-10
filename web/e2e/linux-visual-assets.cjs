/* One-off WP11 Reports-rail candidate flow. PUBLIC repository audience; never accepts goldens.
 * Gate: same-repository pull_request from the exact branch below into main. No PR number gates it. */
/* eslint-disable @typescript-eslint/no-require-imports -- the CI step runs this helper directly with node as CommonJS. */
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const cp = require("node:child_process");
const net = require("node:net");
const TOKEN = "MYPA-WP11-REPORTS-RAIL-LINUX-20261110";
const BRANCH = "chore/visual-baselines-reports-rail";
const BASE = "main";
const SNAPSHOTS = "web/e2e/visual.spec.ts-snapshots";
const FILES = [
  ["light", "shell-light-unavailable-desktop-linux.png", 1280, 800],
  ["dark", "shell-dark-inspector-desktop-linux.png", 1280, 800],
  ["launcher", "shell-command-menu-desktop-linux.png", 1280, 800],
  ["zoom", "shell-zoom-200-desktop-linux.png", 640, 800],
];
const SOURCES = [".github/workflows/frontend-quality.yml", "web/e2e/stack.sh", "web/playwright.config.ts",
  "web/e2e/visual.spec.ts", "web/e2e/visual-assertion-witness.ts", "web/e2e/ci-visual-reporter.ts",
  "web/e2e/fixtures.ts", "web/package-lock.json", "pyproject.toml", "tests/end_to_end/seed_work.py",
  "tests/end_to_end/seed_review.py", "tests/end_to_end/seed_reports.py", "tests/end_to_end/seed_entities.py",
  "web/e2e/linux-visual-assets.cjs", "web/e2e/ci-diagnostic-source-binding.test.mjs"];
const REFERENCES = ["fad0c511affaa0c6c820dccc5aecd05d3875a88b8c0e123c9e10ab6170642a27",
  "eec58e722bae489417fc67d7d29a90e63cc60196fe455292508157f69ff7d0b6",
  "837775045014c22e469e6c0a0276b54b906f8f24b2a728b41055eeb4057e960f",
  "c39ba0200bc64bc837aad61a4408e7009f644a422d62b11fc51889a1a2bb7ae8"];
const refuse = () => { throw new Error("LINUX_VISUAL_CANDIDATES_REFUSED"); };
const digest = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
function exactKeys(value, keys) {
  if (!value || typeof value !== "object" || Object.keys(value).sort().join() !== [...keys].sort().join()) refuse();
}
// POSIX dir_fd is required: Node has no portable openat. This uses only the
// already-installed Python stdlib and never prints source/file contents on error.
const SAFE_IO = String.raw`
import os,sys,json,stat,hashlib,contextlib
q=json.loads(sys.stdin.buffer.read(16*1024*1024+1))
@contextlib.contextmanager
def parent(file,ident=None):
    if sys.platform=='darwin' and file.startswith('/var/'):file='/private'+file
    if sys.platform=='darwin' and file.startswith('/tmp/'):file='/private'+file
    parts=file.split('/')
    assert parts[0]=='' and all(x not in ('','.','..') for x in parts[1:])
    fds=[os.open('/',os.O_RDONLY|os.O_DIRECTORY)]
    try:
        for part in parts[1:-1]:
            before=os.stat(part,dir_fd=fds[-1],follow_symlinks=False)
            fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fds[-1]);fds.append(fd)
            after=os.fstat(fd)
            assert stat.S_ISDIR(after.st_mode) and (before.st_dev,before.st_ino)==(after.st_dev,after.st_ino)
        if ident is None:ident=q.get('parentIdentity')
        if ident is not None:
            opened=os.fstat(fds[-1]);assert [opened.st_dev,opened.st_ino]==ident
        yield fds[-1],parts[-1]
    finally:
        for fd in reversed(fds):os.close(fd)
def read(file,limit,blob=None,expected_mode=None,permission=None,capture=False,ident=None):
    with parent(file,ident) as (p,n):
        before=os.stat(n,dir_fd=p,follow_symlinks=False)
        assert stat.S_ISREG(before.st_mode)
        fd=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=p)
        try:
            opened=os.fstat(fd)
            assert stat.S_ISREG(opened.st_mode) and (before.st_dev,before.st_ino)==(opened.st_dev,opened.st_ino)
            assert opened.st_size<=limit
            if permission is not None:assert stat.S_IMODE(opened.st_mode)==permission
            if expected_mode is not None:assert bool(opened.st_mode&0o111)==(expected_mode=='100755')
            if blob is not None:
                assert opened.st_size==limit
                h=hashlib.sha1(b'blob '+str(limit).encode()+b'\0')
            if blob is None or capture:out=bytearray()
            total=0
            while total<=limit:
                b=os.read(fd,min(65536,limit+1-total))
                if not b:break
                total+=len(b)
                assert total<=limit
                if blob is not None:h.update(b)
                if blob is None or capture:out.extend(b)
            final=os.fstat(fd)
            assert (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns,opened.st_mode)==(final.st_dev,final.st_ino,final.st_size,final.st_mtime_ns,final.st_ctime_ns,final.st_mode)
            assert total==opened.st_size
            if blob is not None:assert h.hexdigest()==blob
            if blob is None or capture:return bytes(out)
        finally:os.close(fd)
def write(file,data,exclusive,ident=None):
    with parent(file,ident) as (p,n):
        if not exclusive:
            before=os.stat(n,dir_fd=p,follow_symlinks=False)
            assert stat.S_ISREG(before.st_mode)
        flags=os.O_WRONLY|os.O_NOFOLLOW|os.O_NONBLOCK|(os.O_CREAT|os.O_EXCL if exclusive else 0)
        fd=os.open(n,flags,0o600,dir_fd=p)
        try:
            st=os.fstat(fd);assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode)==0o600
            if not exclusive:
                assert (before.st_dev,before.st_ino)==(st.st_dev,st.st_ino)
                os.ftruncate(fd,0)
            view=memoryview(data)
            while view:view=view[os.write(fd,view):]
            os.fsync(fd)
        finally:os.close(fd)
verb=q['verb']
if verb=='read':sys.stdout.buffer.write(read(q['file'],q['limit'],permission=q.get('permission')))
elif verb=='mkdir':
    with parent(q['file']) as (p,n):
        os.mkdir(n,0o700,dir_fd=p)
        fd=os.open(n,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=p)
        try:
            st=os.fstat(fd);assert stat.S_IMODE(st.st_mode)==0o700
            sys.stdout.write(json.dumps([st.st_dev,st.st_ino]))
        finally:os.close(fd)
elif verb=='write':
    import base64
    data=base64.b64decode(q['data'],validate=True);assert len(data)<=q['limit']
    write(q['file'],data,q['exclusive'])
elif verb in ('directory','directoryIdentity'):
    with parent(q['file']) as (p,n):
        fd=os.open(n,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=p)
        try:
            st=os.fstat(fd)
            if q.get('targetIdentity') is not None:assert [st.st_dev,st.st_ino]==q['targetIdentity']
            if verb=='directory':
                assert stat.S_IMODE(st.st_mode)==0o700
                sys.stdout.write(json.dumps(sorted(os.listdir(fd))))
            else:sys.stdout.write(json.dumps([st.st_dev,st.st_ino]))
        finally:os.close(fd)
elif verb=='sources':
    approval=None
    # redirect: EXACTLY the set-aside baselines are verified from their 0700
    # copies (held to redirectIdentity) against the SAME tracked blob ids.
    redirect=q.get('redirect') or {}
    names=[e[2] for e in q['entries']]
    assert set(redirect)<=set(names)
    if redirect:assert q.get('redirectIdentity') is not None
    used=0
    for mode,oid,name,size in q['entries']:
        assert not name.startswith('/') and all(x not in ('','.','..') for x in name.split('/'))
        control=name=='web/e2e/capture-approval.json'
        if control:assert size<=4096 and name not in redirect
        if name in redirect:
            used+=1
            read(redirect[name],size,oid,mode,permission=0o600,ident=q['redirectIdentity'])
        else:value=read(q['root']+'/'+name,size,oid,mode,capture=control)
        if control:approval=value
    assert approval is not None and used==len(redirect)
    sys.stdout.buffer.write(approval)
elif verb=='aside':
    # Copy each verified tracked baseline into the held 0700 directory, verify
    # the copy against the same blob, then unlink ONLY the workspace original.
    out=[]
    for mode,oid,name,size in q['entries']:
        assert not name.startswith('/') and all(x not in ('','.','..') for x in name.split('/'))
        assert mode=='100644' and name.startswith('web/e2e/visual.spec.ts-snapshots/') and name.endswith('-desktop-linux.png')
        source=q['root']+'/'+name
        data=read(source,size,oid,mode,capture=True)
        target=q['dest']+'/'+name.rsplit('/',1)[1]
        write(target,data,True,ident=q['destIdentity'])
        read(target,size,oid,mode,permission=0o600,ident=q['destIdentity'])
        with parent(source) as (p,n):
            st=os.stat(n,dir_fd=p,follow_symlinks=False);assert stat.S_ISREG(st.st_mode)
            os.unlink(n,dir_fd=p)
        out.append(hashlib.sha256(data).hexdigest())
    sys.stdout.write(json.dumps(out))
else:raise ValueError()
`;
function safeIO(verb, fields, maxBuffer = 32769) {
  const result = cp.spawnSync("python3", ["-c", SAFE_IO], { input: JSON.stringify({ verb, ...fields }),
    stdio: ["pipe", "pipe", "ignore"], maxBuffer, env: { PATH: process.env.PATH } });
  if (result.status !== 0 || result.error) refuse();
  return result.stdout;
}
function regular(file, limit, permission, parentIdentity) {
  return safeIO("read", { file: path.resolve(file), limit, permission, parentIdentity }, limit + 1);
}
function directoryIdentity(dir) { return JSON.parse(safeIO("directoryIdentity", { file: path.resolve(dir) })); }
function secureWrite(file, bytes, exclusive = true, parentIdentity) {
  safeIO("write", { file: path.resolve(file), data: bytes.toString("base64"), limit: bytes.length, exclusive, parentIdentity });
}
const APPROVAL = "web/e2e/capture-approval.json";
const APPROVAL_PLACEHOLDER = "MANAGER_APPROVED_SOURCE_DIGEST_SELF_BLOB_EXCLUDED";
function git(root, args, input) {
  return cp.execFileSync("git", ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", ...args],
    { cwd: root, input, encoding: "utf8", maxBuffer: 16 * 1024 * 1024, stdio: ["pipe", "pipe", "ignore"] });
}
function indexEntries(root) {
  if (git(root, ["rev-parse", "--show-object-format"]).trim() !== "sha1") refuse();
  const entries = git(root, ["ls-files", "--stage", "-z"]).split("\0").filter(Boolean).map((entry) => {
    const match = /^(100644|100755) ([0-9a-f]{40}) 0\t([^\0]+)$/.exec(entry);
    if (!match || match[3].startsWith("/") || match[3].split("/").some((part) => ["", ".", ".."].includes(part))) refuse();
    return [match[1], match[2], match[3]];
  });
  if (!entries.length || entries.length > 10000 || new Set(entries.map((item) => item[2])).size !== entries.length
    || entries.filter((item) => item[2] === APPROVAL && item[0] === "100644").length !== 1) refuse();
  return entries;
}
function sourceDigest(root) {
  return digest(Buffer.from(JSON.stringify(indexEntries(root).map(([mode, oid, name]) =>
    [mode, name === APPROVAL ? APPROVAL_PLACEHOLDER : oid, name]))));
}
const BASELINE_PATHS = () => FILES.map((item) => `${SNAPSHOTS}/${item[1]}`);
function checkedEntries(root) {
  const entries = indexEntries(root);
  const flags = git(root, ["ls-files", "-v", "-f", "-z"]).split("\0").filter(Boolean);
  if (flags.length !== entries.length || flags.some((item) => !item.startsWith("H "))) refuse();
  const head = git(root, ["ls-tree", "-r", "-z", "HEAD"]).split("\0").filter(Boolean).map((entry) => {
    const match = /^(100644|100755) blob ([0-9a-f]{40})\t([^\0]+)$/.exec(entry);
    if (!match) refuse(); return [match[1], match[2], match[3]];
  });
  if (JSON.stringify(head) !== JSON.stringify(entries)) refuse();
  const sizes = git(root, ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"], entries.map((e) => e[1]).join("\n") + "\n").trim().split("\n");
  if (sizes.length !== entries.length) refuse();
  const checked = entries.map(([mode, oid, name], index) => {
    const match = /^([0-9a-f]{40}) blob (0|[1-9][0-9]*)$/.exec(sizes[index]);
    if (!match || match[1] !== oid || Number(match[2]) > 32 * 1024 * 1024 || (name === APPROVAL && Number(match[2]) > 4096)) refuse();
    return [mode, oid, name, Number(match[2])];
  });
  if (checked.reduce((sum, item) => sum + item[3], 0) > 256 * 1024 * 1024) refuse();
  // The four desktop-linux baselines are TRACKED; each must be one regular 100644 entry.
  for (const name of BASELINE_PATHS()) if (checked.filter((item) => item[2] === name && item[0] === "100644").length !== 1) refuse();
  return checked;
}
/** Verify EVERY tracked blob. Pristine (aside undefined): every path in the workspace.
 * Set-aside (aside = {dir, identity}): exactly the four desktop-linux baselines are verified
 * from the held 0700 copies against the SAME tracked blob ids; every other path from the
 * workspace. The workspace copies of those four are then render candidates (or absent). */
function sourceApproval(root, aside) {
  const checked = checkedEntries(root);
  let redirect;
  if (aside !== undefined) {
    if (!aside || typeof aside.dir !== "string" || !path.isAbsolute(aside.dir) || !Array.isArray(aside.identity)) refuse();
    const members = JSON.parse(safeIO("directory", { file: path.resolve(aside.dir), targetIdentity: aside.identity }));
    if (members.sort().join() !== FILES.map((item) => item[1]).sort().join()) refuse();
    redirect = Object.fromEntries(FILES.map((item) => [`${SNAPSHOTS}/${item[1]}`, path.join(path.resolve(aside.dir), item[1])]));
  }
  // Parse the SAME bounded control bytes whose Git blob was verified above.
  // Never reopen the control after verifying it. All other source bodies stay in the streaming helper.
  const verifiedApproval = safeIO("sources", { root: path.resolve(root), entries: checked,
    ...(redirect ? { redirect, redirectIdentity: aside.identity } : {}) }, 4097);
  const value = JSON.parse(verifiedApproval);
  exactKeys(value, ["schema", "repository", "repository_id", "branch", "base", "purpose", "cases", "expectedSourceDigest"]);
  if (value.schema !== 1 || value.repository !== "RMF112018/my-pa" || value.repository_id !== 1317234001
    || value.branch !== BRANCH || value.base !== BASE
    || value.purpose !== "PUBLIC_SYNTHETIC_LINUX_BASELINE_CANDIDATES_ONLY"
    || JSON.stringify(value.cases) !== JSON.stringify(FILES.map((item) => item[1]))
    || !/^[0-9a-f]{64}$/.test(value.expectedSourceDigest) || value.expectedSourceDigest !== sourceDigest(root)) refuse();
  return value.expectedSourceDigest;
}
function asidePath(env) {
  if (!/^\d{1,20}$/.test(env.GITHUB_RUN_ID || "") || !/^\d{1,20}$/.test(env.GITHUB_RUN_ATTEMPT || "")
    || !env.RUNNER_TEMP || !path.isAbsolute(env.RUNNER_TEMP)) refuse();
  return path.join(env.RUNNER_TEMP, `my-pa-linux-visual-previous-${env.GITHUB_RUN_ID}-${env.GITHUB_RUN_ATTEMPT}`);
}
function aside(env) { const dir = asidePath(env); return { dir, identity: directoryIdentity(dir) }; }
function gate(env) {
  // MYPA_CAPTURE_PR is informational only (digits); it never selects the run.
  if (env.CI !== "true" || env.CI_VISUAL_ASSET_CAPTURE_REQUEST !== TOKEN
    || env.GITHUB_REPOSITORY !== "RMF112018/my-pa" || env.GITHUB_REPOSITORY_ID !== "1317234001"
    || env.MYPA_CAPTURE_VISIBILITY !== "public" || !/^\d{1,10}$/.test(env.MYPA_CAPTURE_PR || "")
    || env.MYPA_CAPTURE_HEAD_REPO !== "1317234001"
    || env.MYPA_CAPTURE_BRANCH !== BRANCH || env.GITHUB_HEAD_REF !== BRANCH
    || env.MYPA_CAPTURE_BASE !== BASE || env.GITHUB_BASE_REF !== BASE
    || env.GITHUB_EVENT_NAME !== "pull_request" || env.GITHUB_JOB !== "visual") refuse();
}
function identity(env, root, beforeRender = false) {
  gate(env);
  if (env.GITHUB_JOB !== "visual"
    || (!beforeRender && env.MYPA_CAPTURE_FIRST_OUTCOME !== "failure") || env.RUNNER_OS !== "Linux" || env.RUNNER_ARCH !== "X64"
    || !/^[0-9a-f]{40}$/.test(env.MYPA_CAPTURE_HEAD || "")
    || !/^\d{1,20}$/.test(env.GITHUB_RUN_ID || "") || !/^\d{1,20}$/.test(env.GITHUB_RUN_ATTEMPT || "")) refuse();
  const head = cp.execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
  const tree = cp.execFileSync("git", ["rev-parse", "HEAD^{tree}"], { cwd: root, encoding: "utf8" }).trim();
  if (head !== env.MYPA_CAPTURE_HEAD || !/^[0-9a-f]{40}$/.test(tree)) refuse();
  const temp = env.RUNNER_TEMP;
  if (!temp || !path.isAbsolute(temp) || !fs.lstatSync(temp).isDirectory() || fs.lstatSync(temp).isSymbolicLink()) refuse();
  // Before the first render the checkout must be pristine; afterwards the four baselines
  // must verify from the held set-aside copies (see sourceApproval).
  const held = beforeRender ? undefined : aside(env);
  const approvedSourceDigest = sourceApproval(root, held);
  return { head, tree, approvedSourceDigest, trackedSourceCount: indexEntries(root).length, run: env.GITHUB_RUN_ID,
    attempt: env.GITHUB_RUN_ATTEMPT, temp, pr: env.MYPA_CAPTURE_PR, aside: held };
}
/** Preflight: authenticate the PRISTINE checkout, then move ONLY the four tracked desktop-linux
 * baselines into a new 0700 RUNNER_TEMP directory so the first render creates candidates. */
function preflight(env, root) {
  const id = identity(env, root, true);
  const dir = asidePath(env);
  const checked = checkedEntries(root);
  const four = BASELINE_PATHS().map((name) => checked.find((item) => item[2] === name));
  const destIdentity = JSON.parse(safeIO("mkdir", { file: path.resolve(dir) }));
  const hashes = JSON.parse(safeIO("aside", { root: path.resolve(root), entries: four, dest: path.resolve(dir), destIdentity }));
  if (!Array.isArray(hashes) || hashes.length !== 4 || hashes.some((value) => !/^[0-9a-f]{64}$/.test(value))) refuse();
  for (const name of BASELINE_PATHS()) {
    try { fs.lstatSync(path.join(root, name)); } catch (error) { if (error.code === "ENOENT") continue; }
    refuse(); // Still present (or unreadable state): Playwright would compare, not create.
  }
  // The held copies must now authenticate the whole index exactly as the pristine checkout did.
  if (sourceApproval(root, aside(env)) !== id.approvedSourceDigest) refuse();
  return { dir, hashes };
}
function previousBaselines(root, held) {
  const checked = checkedEntries(root);
  return FILES.map(([, name, width, height]) => {
    const entry = checked.find((item) => item[2] === `${SNAPSHOTS}/${name}`);
    const image = png(path.join(held.dir, name), width, height, 0o600, held.identity);
    return { name, blob: entry[1], sha256: image.sha256, bytes: image.bytes.length };
  });
}
function receipt(file, pass, id) {
  const value = JSON.parse(regular(file, 8192));
  exactKeys(value, ["schema", "pass", "head", "run", "attempt", "cases"]);
  if (value.schema !== 1 || value.pass !== pass || value.head !== id.head || value.run !== id.run || value.attempt !== id.attempt
    || !Array.isArray(value.cases) || value.cases.length !== 4) refuse();
  value.cases.forEach((item, index) => {
    exactKeys(item, ["id", "outcome", "status"]);
    if (item.id !== FILES[index][0] || item.outcome !== (pass === "first" ? "absent-created-error" : "matched-no-delta")
      || item.status !== (pass === "first" ? "failed" : "passed")) refuse();
  });
  return value.cases;
}
function png(file, width, height, permission, parentIdentity) {
  const bytes = regular(file, 2 * 1024 * 1024, permission, parentIdentity);
  if (bytes.length < 33 || bytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a"
    || bytes.readUInt32BE(8) !== 13 || bytes.subarray(12, 16).toString() !== "IHDR"
    || bytes.readUInt32BE(16) !== width || bytes.readUInt32BE(20) !== height) refuse();
  return { bytes, sha256: digest(bytes), width, height };
}
function candidates(root) {
  const parentIdentity = directoryIdentity(path.join(root, "web/e2e/visual.spec.ts-snapshots"));
  return FILES.map(([caseId, name, width, height]) => ({ case: caseId, name,
    ...png(path.join(root, "web/e2e/visual.spec.ts-snapshots", name), width, height, undefined, parentIdentity) }));
}
function stagePath(id) { return path.join(id.temp, `my-pa-linux-visual-${id.run}-${id.attempt}`); }
function saveManifest(dir, value, replace = false, parentIdentity) {
  const bytes = Buffer.from(JSON.stringify(value, null, 2) + "\n");
  if (bytes.length > 32768) refuse();
  secureWrite(path.join(dir, "MANIFEST.json"), bytes, !replace, parentIdentity);
}
function verifyStaged(dir, manifest, expectedIdentity = directoryIdentity(dir)) {
  const currentIdentity = directoryIdentity(dir);
  if (JSON.stringify(currentIdentity) !== JSON.stringify(expectedIdentity)) refuse();
  const members = JSON.parse(safeIO("directory", { file: path.resolve(dir), targetIdentity: expectedIdentity }));
  if (members.sort().join() !== [...FILES.map((item) => item[1]), "MANIFEST.json"].sort().join()) refuse();
  for (let index = 0; index < FILES.length; index++) {
    const [, name, width, height] = FILES[index];
    const file = path.join(dir, name);
    if (png(file, width, height, 0o600, expectedIdentity).sha256 !== manifest.images[index].sha256) refuse();
  }
  const file = path.join(dir, "MANIFEST.json");
  if (regular(file, 32768, 0o600, expectedIdentity).toString() !== JSON.stringify(manifest, null, 2) + "\n") refuse();
}
function stage(env, root) {
  const id = identity(env, root);
  testUrl(env.MYPA_E2E_ADMIN_URL, "postgres");
  testUrl(env.MYPA_E2E_DATABASE_URL, "my_pa_wp13_e2e");
  const witnesses = receipt(path.join(id.temp, "my-pa-linux-visual-first.json"), "first", id);
  const images = candidates(root);
  const dir = stagePath(id);
  const stageIdentity = JSON.parse(safeIO("mkdir", { file: path.resolve(dir) }));
  images.forEach((item) => secureWrite(path.join(dir, item.name), item.bytes, true, stageIdentity));
  const manifest = { schema: 1, status: "CANDIDATE_NOT_ACCEPTED", repository: "RMF112018/my-pa", repository_id: 1317234001,
    visibility: "public", audience: "same public repository/CI artifact audience", pr_informational: id.pr, branch: BRANCH, base: BASE,
    head: id.head, tree: id.tree, approved_source_digest: id.approvedSourceDigest, tracked_source_count: id.trackedSourceCount, run: id.run, attempt: id.attempt, job: "visual", first_step: "failure_preserved",
    eligibility: "controlled-synthetic-only-pending-independent-visual-review", references: REFERENCES, witnesses,
    previous_baselines: previousBaselines(root, id.aside),
    sources: SOURCES.map((name) => ({ path: name, sha256: digest(regular(path.join(root, name), 4 * 1024 * 1024)) })),
    images: images.map(({ bytes, ...item }) => ({ ...item, bytes: bytes.length })), repeat: "not_run" };
  saveManifest(dir, manifest, false, stageIdentity);
  verifyStaged(dir, manifest, stageIdentity);
  return { id, dir, manifest };
}
function validateManifest(value, id) {
  exactKeys(value, ["schema", "status", "repository", "repository_id", "visibility", "audience", "pr_informational", "branch", "base", "head", "tree", "approved_source_digest", "tracked_source_count",
    "run", "attempt", "job", "first_step", "eligibility", "references", "previous_baselines", "witnesses", "sources", "images", "repeat"]);
  if (value.schema !== 1 || value.status !== "CANDIDATE_NOT_ACCEPTED" || value.repository !== "RMF112018/my-pa"
    || value.repository_id !== 1317234001 || value.visibility !== "public" || value.audience !== "same public repository/CI artifact audience"
    || value.approved_source_digest !== id.approvedSourceDigest || value.tracked_source_count !== id.trackedSourceCount
    || typeof value.pr_informational !== "string" || !/^\d{1,10}$/.test(value.pr_informational) || value.pr_informational !== id.pr
    || value.branch !== BRANCH || value.base !== BASE || value.head !== id.head || value.tree !== id.tree
    || value.run !== id.run || value.attempt !== id.attempt || value.job !== "visual" || value.first_step !== "failure_preserved"
    || value.eligibility !== "controlled-synthetic-only-pending-independent-visual-review"
    || JSON.stringify(value.references) !== JSON.stringify(REFERENCES) || value.repeat !== "not_run"
    || !Array.isArray(value.previous_baselines) || value.previous_baselines.length !== 4
    || !Array.isArray(value.sources) || value.sources.length !== SOURCES.length || !Array.isArray(value.images) || value.images.length !== 4) refuse();
  value.sources.forEach((item, index) => { exactKeys(item, ["path", "sha256"]); if (item.path !== SOURCES[index] || !/^[0-9a-f]{64}$/.test(item.sha256)) refuse(); });
  value.images.forEach((item, index) => {
    exactKeys(item, ["case", "name", "sha256", "width", "height", "bytes"]);
    if (item.case !== FILES[index][0] || item.name !== FILES[index][1] || item.width !== FILES[index][2] || item.height !== FILES[index][3]
      || !Number.isInteger(item.bytes) || item.bytes < 33 || item.bytes > 2 * 1024 * 1024 || !/^[0-9a-f]{64}$/.test(item.sha256)) refuse();
  });
  value.previous_baselines.forEach((item, index) => {
    exactKeys(item, ["name", "blob", "sha256", "bytes"]);
    if (item.name !== FILES[index][1] || !/^[0-9a-f]{40}$/.test(item.blob) || !/^[0-9a-f]{64}$/.test(item.sha256)
      || !Number.isInteger(item.bytes) || item.bytes < 33 || item.bytes > 2 * 1024 * 1024) refuse();
  });
  if (!Array.isArray(value.witnesses) || value.witnesses.length !== 4) refuse();
  value.witnesses.forEach((item, index) => {
    exactKeys(item, ["id", "outcome", "status"]);
    if (item.id !== FILES[index][0] || item.outcome !== "absent-created-error" || item.status !== "failed") refuse();
  });
}
function testUrl(value, database) {
  const url = new URL(value);
  if (url.protocol !== "postgresql+psycopg:" || !["localhost", "127.0.0.1"].includes(url.hostname)
    || url.port !== "5432" || url.username !== "my_pa" || url.password !== "ci_throwaway_not_a_secret"
    || url.pathname !== "/" + database || url.search || url.hash) refuse();
  return url;
}
async function portsFree() {
  for (const port of [9099, 3100, 3101]) {
    const free = await new Promise((resolve) => {
      const server = net.createServer();
      server.once("error", () => resolve(false));
      server.listen(port, "127.0.0.1", () => server.close(() => resolve(true)));
    });
    if (!free) refuse();
  }
}
function databaseAbsent(env, name) {
  const script = "import os,sqlalchemy as s\ne=s.create_engine(os.environ['MYPA_E2E_ADMIN_URL'])\nwith e.connect() as c:r=c.execute(s.text('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)'),{'name':os.environ['MYPA_CHECK_DB']}).scalar_one()\ne.dispose()\nprint('present' if r else 'absent')";
  const result = cp.spawnSync(env.MYPA_E2E_PYTHON, ["-c", script], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
    env: { PATH: env.PATH, MYPA_E2E_ADMIN_URL: env.MYPA_E2E_ADMIN_URL, MYPA_CHECK_DB: name } });
  if (result.status !== 0 || result.stdout !== "absent\n") refuse();
}
async function repeat(env, root) {
  const id = identity(env, root);
  testUrl(env.MYPA_E2E_ADMIN_URL, "postgres");
  const url = testUrl(env.MYPA_E2E_DATABASE_URL, "my_pa_wp13_e2e");
  const dir = stagePath(id);
  const stageIdentity = directoryIdentity(dir);
  const manifest = JSON.parse(regular(path.join(dir, "MANIFEST.json"), 32768, 0o600, stageIdentity));
  validateManifest(manifest, id);
  if (SOURCES.some((name, index) => digest(regular(path.join(root, name), 4 * 1024 * 1024)) !== manifest.sources[index].sha256)) refuse();
  if (JSON.stringify(previousBaselines(root, id.aside)) !== JSON.stringify(manifest.previous_baselines)) refuse();
  const original = candidates(root);
  if (original.some((item, index) => item.sha256 !== manifest.images[index].sha256)) refuse();
  databaseAbsent(env, "my_pa_wp13_e2e");
  await portsFree();
  const database = `my_pa_visual_repeat_${id.run}_${id.attempt}`;
  if (database.length > 63 || !/^my_pa_visual_repeat_\d+_\d+$/.test(database)) refuse();
  databaseAbsent(env, database); // BEFORE stack.sh can issue its unconditional DROP.
  url.pathname = "/" + database;
  const child = {};
  for (const key of ["PATH", "CI", "RUNNER_TEMP", "GITHUB_REPOSITORY", "GITHUB_REPOSITORY_ID", "GITHUB_EVENT_NAME", "GITHUB_JOB",
    "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_HEAD_REF", "GITHUB_BASE_REF", "MYPA_CAPTURE_HEAD", "MYPA_CAPTURE_PR", "MYPA_CAPTURE_HEAD_REPO",
    "MYPA_CAPTURE_BRANCH", "MYPA_CAPTURE_BASE",
    "MYPA_CAPTURE_VISIBILITY", "MYPA_CAPTURE_FIRST_OUTCOME", "RUNNER_OS", "RUNNER_ARCH", "CI_VISUAL_ASSET_CAPTURE_REQUEST", "MYPA_E2E_PYTHON", "MYPA_E2E_ADMIN_URL"]) child[key] = env[key];
  Object.assign(child, { MYPA_E2E_DATABASE: database, MYPA_E2E_DATABASE_URL: url.toString(), MYPA_CAPTURE_PASS: "repeat", CI_VISUAL_DIAGNOSTIC: "1" });
  sourceApproval(root, id.aside); // Fresh byte verification immediately before the repeat renderer.
  const result = cp.spawnSync("npm", ["run", "e2e", "--", "e2e/visual.spec.ts", "--project=desktop"], { cwd: path.join(root, "web"), env: child, stdio: "inherit" });
  databaseAbsent(env, database);
  await portsFree();
  if (result.status !== 0) refuse();
  const witnesses = receipt(path.join(id.temp, "my-pa-linux-visual-repeat.json"), "repeat", id);
  if (candidates(root).some((item, index) => item.sha256 !== manifest.images[index].sha256)) refuse();
  sourceApproval(root, id.aside); // Reauthenticate all source bytes before upload eligibility.
  manifest.repeat = { result: "existing_matcher_pass", first_hashes_unchanged: true, databases_absent: true, ports_bindable: true, witnesses };
  saveManifest(dir, manifest, true, stageIdentity);
  verifyStaged(dir, manifest, stageIdentity);
  return dir;
}
module.exports = { TOKEN, BRANCH, BASE, FILES, SOURCES, APPROVAL, sourceDigest, sourceApproval, regular, receipt, png, candidates, gate, identity,
  asidePath, aside, preflight, previousBaselines, stage, repeat, testUrl, validateManifest, verifyStaged };
if (require.main === module) {
  (async () => {
    const root = path.resolve(__dirname, "../..");
    if (process.argv[2] === "preflight") { preflight(process.env, root); }
    else if (process.argv[2] === "digest") { process.stdout.write(sourceDigest(root) + "\n"); }
    else if (process.argv[2] === "stage") { stage(process.env, root); fs.appendFileSync(process.env.GITHUB_OUTPUT, "safe=true\n"); }
    else if (process.argv[2] === "repeat") { await repeat(process.env, root); fs.appendFileSync(process.env.GITHUB_OUTPUT, "safe_upload=true\n"); }
    else refuse();
  })().catch(() => { process.stdout.write("::error title=Linux visual candidates::validation=refused\n"); process.exitCode = 1; });
}
