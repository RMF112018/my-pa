"use strict";

const fs = require("node:fs");
const path = require("node:path");
const SINK = path.resolve(__dirname, "../.wp03-main-ci-diagnostic-v1.jsonl");
const MAX_BYTES = 4 * 1024 * 1024;
const MAX_EVENTS = 10000;
const ROLES = ["PW_HTTP_CLIENT", "LIVE_NEXT", "DEAD_NEXT"];
const PHASES = ["BEFORE_TARGET", "AT_CANONICAL_GET", "AFTER_TARGET"];
const ERRORS = ["ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "OTHER_REDACTED"];
const FIELDS = {
  REGISTER: ["start"], EXIT77_INTENT: [], EXIT: ["code"], CHILD_EXIT: ["code", "signal"],
  LISTENER: ["alive"], PROCESS: ["alive"],
  TARGET_BEGIN: [], TARGET_END: [], CANONICAL_BEGIN: [], CANONICAL_END: [], STEP_BEGIN: [], STEP_END: [],
  SOCKET: ["reusedSocket", "newSocket"], RESPONSE: ["status"], ERROR: ["error"],
  READINESS: ["alive"], TEST_END: ["status"], RUN_END: ["status"],
};
const BASE = ["version", "event", "role", "phase", "target", "pid", "time"];
function fail() { throw new Error("WP03_DIAGNOSTIC_INVALID"); }
function enabled() {
  return process.env.CI_WP03_MAIN_DIAGNOSTIC === "1" && process.env.CI === "true" &&
    process.env.GITHUB_EVENT_NAME === "workflow_dispatch" && process.env.NODE_ENV !== "production";
}
function integer(value, min, max) {
  return Number.isSafeInteger(value) && value >= min && value <= max;
}
function validate(event) {
  if (!event || typeof event !== "object" || Array.isArray(event) ||
      Object.getPrototypeOf(event) !== Object.prototype || !Object.hasOwn(FIELDS, event.event)) fail();
  const keys = [...BASE, ...FIELDS[event.event]];
  if (Object.keys(event).length !== keys.length || keys.some((key) => !Object.hasOwn(event, key))) fail();
  if (event.version !== 1 || !ROLES.includes(event.role) || !PHASES.includes(event.phase) ||
      typeof event.target !== "boolean" || !integer(event.pid, 1, 2147483647) || !integer(event.time, 0, Number.MAX_SAFE_INTEGER)) fail();
  const client = ["TARGET_BEGIN", "TARGET_END", "CANONICAL_BEGIN", "CANONICAL_END", "STEP_BEGIN", "STEP_END", "SOCKET", "RESPONSE", "ERROR", "TEST_END", "RUN_END"];
  if (client.includes(event.event) !== (event.role === "PW_HTTP_CLIENT")) fail();
  if (Object.hasOwn(event, "start") && !integer(event.start, 1, Number.MAX_SAFE_INTEGER)) fail();
  if (Object.hasOwn(event, "code") && !integer(event.code, event.event === "CHILD_EXIT" ? -1 : 0, 255)) fail();
  if (Object.hasOwn(event, "signal") && !integer(event.signal, 0, 64)) fail();
  for (const key of ["alive", "reusedSocket", "newSocket"]) {
    if (Object.hasOwn(event, key) && typeof event[key] !== "boolean") fail();
  }
  if (event.event === "SOCKET" && event.newSocket === event.reusedSocket) fail();
  if (event.event === "ERROR" && !ERRORS.includes(event.error)) fail();
  if (event.event === "RESPONSE" && !integer(event.status, 100, 599)) fail();
  if (event.event === "TEST_END" && !["passed", "failed", "timedOut", "skipped", "interrupted"].includes(event.status)) fail();
  if (event.event === "RUN_END" && !["passed", "failed", "timedout", "interrupted"].includes(event.status)) fail();
  return event;
}
function openSink(flags) {
  const fd = fs.openSync(SINK, flags | fs.constants.O_NOFOLLOW);
  const stat = fs.fstatSync(fd);
  if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid() || (stat.mode & 0o777) !== 0o600 || stat.size > MAX_BYTES) {
    fs.closeSync(fd); fail();
  }
  return fd;
}
function readEvents() {
  const fd = openSink(fs.constants.O_RDONLY);
  let source;
  try { source = fs.readFileSync(fd, "utf8"); } finally { fs.closeSync(fd); }
  if (Buffer.byteLength(source) > MAX_BYTES || (source && !source.endsWith("\n"))) fail();
  const lines = source ? source.slice(0, -1).split("\n") : [];
  if (lines.length > MAX_EVENTS || lines.some((line) => Buffer.byteLength(line) > 1024)) fail();
  return lines.map((line) => validate(JSON.parse(line)));
}
function phase(events = readEvents()) {
  let current = "BEFORE_TARGET";
  for (const event of events) {
    if (event.event === "TARGET_BEGIN") current = "BEFORE_TARGET";
    if (event.event === "CANONICAL_BEGIN") current = "AT_CANONICAL_GET";
    if (event.event === "CANONICAL_END") current = "AFTER_TARGET";
    if (event.event === "TARGET_END") current = "AFTER_TARGET";
  }
  return current;
}
function targetActive(events = readEvents()) {
  let active = false;
  for (const event of events) {
    if (event.event === "TARGET_BEGIN") active = true;
    if (event.event === "TARGET_END") active = false;
  }
  return active;
}
function emit(event, role, fields = {}) {
  if (!enabled()) fail();
  const events = readEvents();
  const record = validate({ version: 1, event, role, phase: phase(events), target: targetActive(events), pid: process.pid,
    time: Number(process.hrtime.bigint() / 1000000n), ...fields });
  const line = `${JSON.stringify(record)}\n`;
  if (Buffer.byteLength(line) > 1024) fail();
  const fd = openSink(fs.constants.O_WRONLY | fs.constants.O_APPEND);
  try {
    if (fs.fstatSync(fd).size + Buffer.byteLength(line) > MAX_BYTES) fail();
    fs.writeSync(fd, line);
  } finally { fs.closeSync(fd); }
}
function processStart(pid) {
  // Skip the parenthesized process name without retaining or returning it.
  const stat = fs.readFileSync(`/proc/${pid}/stat`, "utf8");
  const fields = stat.slice(stat.lastIndexOf(")") + 2).split(" ");
  const start = Number(fields[19]);
  if (!integer(start, 1, Number.MAX_SAFE_INTEGER)) fail();
  return start;
}
function registered(events) {
  const owned = new Map();
  for (const event of events) {
    if (event.event !== "REGISTER") continue;
    const prior = owned.get(event.pid);
    if (prior && (prior.role !== event.role || prior.start !== event.start)) fail();
    owned.set(event.pid, event);
  }
  return [...owned.values()];
}
function alive(record) {
  try { return processStart(record.pid) === record.start; } catch { return false; }
}
function listener(record) {
  if (!alive(record)) return false;
  const sockets = new Set();
  try {
    for (const name of fs.readdirSync(`/proc/${record.pid}/fd`)) {
      if (!/^\d+$/.test(name)) continue;
      try {
        const target = fs.readlinkSync(`/proc/${record.pid}/fd/${name}`);
        const match = /^socket:\[(\d+)\]$/.exec(target);
        if (match) sockets.add(match[1]);
      } catch { /* A descriptor may close during the observation. */ }
    }
    const port = record.role === "LIVE_NEXT" ? "0C1C" : "0C1D";
    for (const file of ["tcp", "tcp6"]) {
      for (const line of fs.readFileSync(`/proc/${record.pid}/net/${file}`, "utf8").split("\n").slice(1)) {
        const fields = line.trim().split(/\s+/);
        if (fields[1]?.split(":")[1] === port && fields[3] === "0A" && sockets.has(fields[9])) return true;
      }
    }
  } catch { return false; }
  return false;
}
function snapshot(previous) {
  for (const record of registered(readEvents())) {
    for (const [event, value] of [["PROCESS", alive(record)], ["LISTENER", listener(record)]]) {
      const key = `${record.pid}:${event}`;
      if (previous.get(key) === value) continue;
      previous.set(key, value);
      // Poll observations retain the registered subject PID, never the poller PID.
      emit(event, record.role, { pid: record.pid, alive: value });
    }
  }
}
class Reporter {
  constructor() { this.previous = new Map(); this.target = false; this.failed = false; }
  onBegin() {
    if (!enabled() || process.platform !== "linux") fail();
    readEvents();
    this.timer = setInterval(() => {
      try { snapshot(this.previous); } catch { this.failed = true; clearInterval(this.timer); }
    }, 250);
  }
  onTestBegin(test) {
    if (path.basename(test.location.file) === "capture-task-project.spec.ts" && test.location.line === 109) {
      this.target = true; emit("TARGET_BEGIN", "PW_HTTP_CLIENT"); snapshot(this.previous);
    }
  }
  onStepBegin(_test, _result, step) {
    if (this.target && step.location && path.basename(step.location.file) === "capture-task-project.spec.ts" && step.location.line === 39)
      emit("STEP_BEGIN", "PW_HTTP_CLIENT");
  }
  onStepEnd(_test, _result, step) {
    if (this.target && step.location && path.basename(step.location.file) === "capture-task-project.spec.ts" && step.location.line === 39)
      emit("STEP_END", "PW_HTTP_CLIENT");
  }
  onTestEnd(_test, result) {
    if (this.target) {
      emit("TEST_END", "PW_HTTP_CLIENT", { status: result.status });
      snapshot(this.previous); emit("TARGET_END", "PW_HTTP_CLIENT"); this.target = false;
    }
  }
  onEnd(result) {
    clearInterval(this.timer);
    snapshot(this.previous); emit("RUN_END", "PW_HTTP_CLIENT", { status: result.status });
    if (this.failed) return { status: "failed" };
  }
  printsToStdio() { return false; }
}
function cli(args) {
  if (!enabled() || process.platform !== "linux") fail();
  if (args.length === 1 && args[0] === "--init") {
    const fd = fs.openSync(SINK, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY | fs.constants.O_NOFOLLOW, 0o600);
    fs.closeSync(fd); return;
  }
  const events = readEvents();
  registered(events);
  if (args.length === 1 && args[0] === "--check") return;
  if (args.length === 1 && args[0] === "--owned-pids") {
    const pids = registered(events).filter(alive).map((event) => event.pid);
    if (pids.length) process.stdout.write(`${pids.join("\n")}\n`);
    return;
  }
  if (args.length !== 2 || args[0] !== "--summary" || !/^(0|[1-9]\d{0,2})$/.test(args[1]) || !integer(Number(args[1]), 0, 255)) fail();
  // Validate the entire file before the first provider annotation is emitted.
  const counts = new Map();
  for (const event of events) {
    const detail = event.event === "ERROR" ? event.error : event.event === "SOCKET" ? (event.reusedSocket ? "REUSED" : "NEW") :
      ["PROCESS", "LISTENER", "READINESS"].includes(event.event) ? (event.alive ? "ALIVE" : "ABSENT") : "OBSERVED";
    const key = `${event.role}/${event.phase}/${event.event}/${detail}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  process.stdout.write(`::notice title=WP03_DIAGNOSTIC::SCHEMA_VALID version=1 events=${events.length} stack_exit=${Number(args[1])}\n`);
  for (const [key, count] of [...counts].sort()) process.stdout.write(`::notice title=WP03_DIAGNOSTIC::${key} count=${count}\n`);
  for (const event of events) process.stdout.write(`::notice title=WP03_DIAGNOSTIC_EVENT::${JSON.stringify(event)}\n`);
  process.stdout.write(`::notice title=WP03_DIAGNOSTIC::CLIENT_HOOK_OBSERVED=${events.some((event) => event.event === "SOCKET")}\n`);
  process.stdout.write("::notice title=WP03_DIAGNOSTIC::CORRELATION_ONLY ORIGINAL_MAIN_FAILURE_UNRESOLVED\n");
}
module.exports = Reporter;
Object.assign(module.exports, { enabled, validate, readEvents, phase, targetActive, emit, processStart, registered, alive, listener, cli, SINK });
if (require.main === module) {
  try { cli(process.argv.slice(2)); } catch { process.stderr.write("::error title=WP03_DIAGNOSTIC::VALIDATION_FAILED\n"); process.exitCode = 1; }
}
