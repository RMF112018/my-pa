// @vitest-environment node
/**
 * WP07 U1/U7 source guard: no Reports UI, browser-client or BFF route file
 * carries a purge, hold, release, retention or permanent-delete control, nor
 * addresses an operator-only capability. Comments are stripped first (they
 * may say what is deliberately absent); test files are not scanned (they name
 * the forbidden words to assert their absence).
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "..");
const ROOTS = ["components/reports", "app/(app)/reports", "lib/reports", "app/api/reports"];

/**
 * Hold/retention/purge control wording (case-insensitive, comments stripped). A bare `hold` is not banned:
 * the read-only "On hold" badge (U7) is the one hold datum the UI shows, and none of these phrases match it.
 */
const FORBIDDEN_WORDING = new RegExp(
  [
    "purge",
    "permanent", // also "permanently"
    "empty\\s+trash",
    "legal\\s+hold",
    "place\\s+(on\\s+)?hold",
    "put\\s+on\\s+hold",
    "release\\s+hold",
    "remove\\s+hold",
    "lift\\s+hold",
    "un-?hold",
    "set\\s+retention",
    "retention",
  ].join("|"),
  "i",
);
const FORBIDDEN_CAPABILITY = /reports\.(hold|retention|purge|commit|record_run_state|types|manifest)\b/;

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

/** Source text without block and line comments (string contents kept). */
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
}

const FILES = ROOTS.flatMap((root) => sources(join(SRC, root)));

describe("Reports UI source guard", () => {
  it.each([
    "Remove hold", "LIFT HOLD", "Put on hold", "Place hold", "place on hold", "Unhold", "un-hold", "Legal hold",
    "Set retention", "Purge", "Delete permanently", "Empty trash", "Release hold",
  ])("treats %j as forbidden wording", (phrase) => {
    expect(phrase).toMatch(FORBIDDEN_WORDING);
  });

  it.each(["On hold", "Held", "Move to Trash", "Restore", "Archive"])("allows the existing UI text %j", (phrase) => {
    expect(phrase).not.toMatch(FORBIDDEN_WORDING);
  });

  it("scans the reports UI, client and route files (including the new and edit forms)", () => {
    const names = FILES.map((file) => relative(SRC, file));
    for (const expected of [
      "components/reports/report-form.tsx",
      "components/reports/report-new-form.tsx",
      "components/reports/report-edit-form.tsx",
      "app/(app)/reports/new/page.tsx",
      "app/(app)/reports/[reportId]/edit/page.tsx",
      "lib/reports/client.ts",
      "app/api/reports/route.ts",
    ]) {
      expect(names).toContain(expected);
    }
  });

  it.each(FILES.map((file) => [relative(SRC, file), file]))("%s has no purge/hold/retention/permanent-delete control", (_name, file) => {
    const text = code(readFileSync(file, "utf8"));
    expect(text).not.toMatch(FORBIDDEN_WORDING);
    expect(text).not.toMatch(FORBIDDEN_CAPABILITY);
  });
});
