"use strict";

/* eslint-disable @typescript-eslint/no-require-imports -- Node --require must load this preload as CommonJS. */

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const http = require("node:http");
const net = require("node:net");
const childProcess = require("node:child_process");
const os = require("node:os");
const safe = require("./wp03-main-ci-diagnostic-reporter.cjs");
const ROOT = path.resolve(__dirname, "../node_modules");
const HASHES = Object.freeze({
  "playwright-core/lib/coreBundle.js": "9393fa79e1c67c74edc26b610d65a4f7ed73d345a762465cc88340a33a2454ac",
  "next/dist/server/lib/start-server.js": "df49eef9e57cd9e121de511af12bbfb1666de7b0bba93755fa248255df707105",
  "next/dist/server/lib/utils.js": "1cfc963c2f2707c3dc6068cd53c061c50097d297291fb0ad31d38fd06d1b487e",
  "next/dist/cli/next-dev.js": "e6202db1ebc93814d32215436bb7b6e8fef7a2747fcc32aa1800bf757089dd1b",
  "next/dist/server/lib/router-server.js": "3b07e8ff37540617545d46fb48963b5ceda9197ea0f7025f6d980e37ec2e7b52",
  "next/dist/server/dev/browser-logs/file-logger.js": "3c2bc1c00fde56db669a9073c9921ccd1524e1aa36ce6879e9965261365d3692",
  "next/dist/trace/report/to-json.js": "9711ac078d49e09a2ff690ba3ba2a7d93e24c482afb0567f2b1926de11bf2ead",
  "next/dist/trace/report/to-json-build.js": "9262fc6a7cfd7c5b62f5b79e76f84d884ea3635577ee480075e46152a6e0eed2",
});
function fail() { throw new Error("WP03_DIAGNOSTIC_INVALID"); }
function verify(root = ROOT) {
  for (const [file, expected] of Object.entries(HASHES)) {
    const actual = crypto.createHash("sha256").update(fs.readFileSync(path.join(root, file))).digest("hex");
    if (actual !== expected) fail();
  }
}
function canonical(args) {
  try {
    const input = args[0];
    const options = typeof args[1] === "object" && args[1] !== null ? args[1] : typeof input === "object" && !(input instanceof URL) ? input : {};
    const url = typeof input === "string" || input instanceof URL ? new URL(input) :
      new URL(`${options.protocol || "http:"}//${options.hostname || options.host}:${options.port || 80}${options.path || "/"}`);
    return (options.method || "GET") === "GET" && url.protocol === "http:" &&
      ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) && url.port === "3100" &&
      !url.username && !url.password && !url.search && !url.hash && /^\/api\/tasks\/[A-Za-z0-9_-]+$/.test(url.pathname);
  } catch { return false; }
}
function observeHttp(original, emit = safe.emit, active = safe.targetActive) {
  return function (...args) {
    let target = false;
    const observe = (...event) => {
      try { emit(...event); } catch { process.exitCode = 1; }
    };
    try { target = canonical(args) && active(); } catch { process.exitCode = 1; }
    if (target) observe("CANONICAL_BEGIN", "PW_HTTP_CLIENT");
    const request = Reflect.apply(original, this, args);
    if (target) {
      request.once("socket", () => observe("SOCKET", "PW_HTTP_CLIENT", { reusedSocket: request.reusedSocket === true, newSocket: request.reusedSocket !== true }));
      request.once("response", (response) => {
        observe("RESPONSE", "PW_HTTP_CLIENT", { status: response.statusCode });
        observe("CANONICAL_END", "PW_HTTP_CLIENT");
      });
      request.once("error", (error) => {
        observe("ERROR", "PW_HTTP_CLIENT", { error: ["ECONNRESET", "ECONNREFUSED", "ETIMEDOUT"].includes(error?.code) ? error.code : "OTHER_REDACTED" });
        observe("CANONICAL_END", "PW_HTTP_CLIENT");
      });
    }
    return request;
  };
}
function observeExit(original, role, emit = safe.emit) {
  return function (...args) {
    try { if (args[0] === 77) emit("EXIT77_INTENT", role); }
    finally { return Reflect.apply(original, this, args); }
  };
}
function observeProcessExit(role, emit = safe.emit) {
  return (code) => {
    // A missing exit observation remains unknown; never overwrite Next's exit77.
    try { emit("EXIT", role, { code }); } catch { /* The summary validates the sink independently. */ }
  };
}
function suppressWriters() {
  const logger = require(path.join(ROOT, "next/dist/server/dev/browser-logs/file-logger.js"));
  logger.FileLogger.prototype.initialize = function () {};
  logger.FileLogger.prototype.isEnabled = function () { return false; };
  for (const file of ["next/dist/trace/report/to-json.js", "next/dist/trace/report/to-json-build.js"]) {
    const id = path.join(ROOT, file);
    require.cache[id] = { id, filename: id, loaded: true, exports: { __esModule: true,
      default: { report() {}, async flushAll() {} },
      createJsonReporter() { return { report() {}, async flushAll() {} }; } } };
  }
}
function sanitizeEnvironment() {
  for (const key of Object.keys(process.env)) {
    if (/^(NEXT_|__NEXT_|TURBOPACK_|DEBUG$)/.test(key) && /TRACE|DEBUG|REPORT|UPLOAD/.test(key)) delete process.env[key];
  }
  process.env.NEXT_TRACE_UPLOAD_DISABLED = "1";
  process.env.NEXT_TELEMETRY_DISABLED = "1";
}
function probe(role, connect = net.createConnection, emit = safe.emit) {
  return new Promise((resolve, reject) => {
    const socket = connect({ host: "127.0.0.1", port: 9099 });
    let settled = false;
    function done(success) {
      if (settled) return;
      settled = true; socket.destroy(); emit("READINESS", role, { alive: success });
      if (success) resolve(); else reject(new Error("WP03_DIAGNOSTIC_READINESS_FAILED"));
    }
    socket.setTimeout(2000, () => done(false));
    socket.once("connect", () => done(true));
    socket.once("error", () => done(false));
  });
}
function activate(role) {
  if (!["PW_HTTP_CLIENT", "LIVE_NEXT", "DEAD_NEXT"].includes(role) || process.platform !== "linux") fail();
  safe.readEvents(); verify();
  if (globalThis[Symbol.for("wp03.diagnostic.role")] === role) return;
  if (globalThis[Symbol.for("wp03.diagnostic.role")]) fail();
  globalThis[Symbol.for("wp03.diagnostic.role")] = role;
  if (role === "PW_HTTP_CLIENT") {
    http.request = observeHttp(http.request); return;
  }
  sanitizeEnvironment(); suppressWriters();
  safe.emit("REGISTER", role, { start: safe.processStart(process.pid) });
  process.exit = observeExit(process.exit, role);
  process.on("exit", observeProcessExit(role));
  const fork = childProcess.fork;
  childProcess.fork = function (...args) {
    const child = Reflect.apply(fork, this, args);
    child.once("exit", (code, signal) => {
      try { safe.emit("CHILD_EXIT", role, { pid: child.pid, code: code === null ? -1 : code, signal: signal === null ? 0 : os.constants.signals[signal] }); }
      catch { process.exitCode = 1; }
    });
    return child;
  };
}
async function main(args) {
  if (!safe.enabled()) fail();
  const [role, ...nextArgs] = args;
  const port = role === "LIVE_NEXT" ? "3100" : role === "DEAD_NEXT" ? "3101" : null;
  if (!port || nextArgs.length !== 4 || nextArgs[0] !== "dev" || nextArgs[1] !== "--turbopack" || nextArgs[2] !== "--port" || nextArgs[3] !== port) fail();
  process.env.CI_WP03_DIAGNOSTIC_ROLE = role;
  // Replace inherited preload/options with only this bounded, role-aware preload.
  process.env.NODE_OPTIONS = `--require=${JSON.stringify(__filename)}`;
  activate(role);
  await probe(role);
  process.argv = [process.argv[0], path.join(ROOT, "next/dist/bin/next"), ...nextArgs];
  require(path.join(ROOT, "next/dist/bin/next"));
}
module.exports = { HASHES, verify, canonical, observeHttp, observeExit, observeProcessExit, probe, main };
if (require.main === module) {
  main(process.argv.slice(2)).catch(() => { process.exitCode = 1; });
} else if (safe.enabled()) {
  try { activate(process.env.CI_WP03_DIAGNOSTIC_ROLE); } catch { process.exit(1); }
} else if (process.env.CI_WP03_MAIN_DIAGNOSTIC === "1") {
  process.exit(1);
}
