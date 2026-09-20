// @vitest-environment node
/**
 * WP07 AC-41 / AC-47 / AC-52 / WP07-AC-062 — there is one control and no way around it.
 *
 * This is a source-scanning test, deliberately, and it is the only kind that can
 * hold this particular line. Every other test in the package proves that the
 * surfaces which exist today obey the policy; none of them can notice a *new*
 * file that quietly adds a second toggle, reads the preference out of a query
 * parameter, or writes the cookie from somewhere other than its one owner. The
 * contract is a statement about the whole application, so the assertion has to
 * be about the whole tree.
 *
 * It is written against an explicit allowlist rather than a count, so the
 * failure message names the offending file and a reviewer can see in the diff
 * whether a new entry was justified or smuggled in.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "../..");

function walk(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const full = join(directory, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.(ts|tsx)$/.test(entry) ? [full] : [];
  });
}

/**
 * Comments are stripped before scanning.
 *
 * Without this the guard reads its own documentation: the modules that explain
 * *why* `localStorage` may not be the authority for this preference contain the
 * word `localStorage` next to the word `diagnostics`, and would report
 * themselves as bypasses. A rule that punishes writing down the reason is a
 * rule people delete. What is scanned is therefore code.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const ALL_FILES = walk(srcRoot).map((full) => ({
  path: relative(srcRoot, full).split("\\").join("/"),
  source: stripComments(readFileSync(full, "utf8")),
}));

const PRODUCTION_FILES = ALL_FILES.filter((file) => !/\.(test|stories|story\.test)\./.test(file.path));

/** Files permitted to name the preference cookie at all. */
const COOKIE_NAME_OWNERS = [
  "lib/diagnostics/preference.ts",
  "lib/diagnostics/server.ts",
  "app/(app)/layout.tsx",
  "app/(app)/system/page.tsx",
];

/** The one module allowed to produce a `Set-Cookie` for the preference. */
const SERIALIZER_CALLERS = [
  "lib/diagnostics/preference.ts",
  "app/api/system/diagnostics/route.ts",
  "app/api/session/route.ts",
];

describe("exactly one diagnostics visibility control", () => {
  it("defines the Show diagnostics switch in exactly one file", () => {
    const owners = PRODUCTION_FILES.filter((file) => file.source.includes("Show diagnostics"));
    expect(owners.map((file) => file.path)).toEqual([
      "app/(app)/system/show-diagnostics-toggle.tsx",
    ]);
  });

  it("mounts that control only on the root System page", () => {
    const mounts = PRODUCTION_FILES.filter(
      (file) =>
        file.path !== "app/(app)/system/show-diagnostics-toggle.tsx" &&
        file.source.includes("ShowDiagnosticsToggle"),
    );
    expect(mounts.map((file) => file.path)).toEqual(["app/(app)/system/page.tsx"]);
  });

  it("has no other switch or checkbox whose label mentions diagnostics", () => {
    const offenders = PRODUCTION_FILES.filter((file) => {
      if (file.path === "app/(app)/system/show-diagnostics-toggle.tsx") return false;
      return /role=["']switch["']/.test(file.source) && /diagnostic/i.test(file.source);
    });
    expect(offenders.map((file) => file.path)).toEqual([]);
  });
});

describe("no bypass", () => {
  it("never reads the preference from a query parameter", () => {
    const offenders = PRODUCTION_FILES.filter((file) =>
      /(searchParams|URLSearchParams|useSearchParams)[\s\S]{0,200}?diagnostic/i.test(file.source),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });

  it("never stores diagnostic visibility in browser storage", () => {
    // localStorage may not be an authority for this preference — it is not
    // server-readable, so it could not prevent a server-rendered flash even if
    // it were trusted.
    const offenders = PRODUCTION_FILES.filter((file) =>
      /(localStorage|sessionStorage|indexedDB)[\s\S]{0,200}?diagnostic/i.test(file.source),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });

  it("binds no keyboard shortcut to diagnostic visibility", () => {
    const offenders = PRODUCTION_FILES.filter(
      (file) =>
        /(onKeyDown|addEventListener\(\s*["']keydown)/.test(file.source) &&
        /setEnabled|Show diagnostics/.test(file.source),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });
});

describe("one authority", () => {
  it("names the preference cookie only in its owning modules", () => {
    const offenders = PRODUCTION_FILES.filter(
      (file) =>
        (file.source.includes("my-pa-diagnostics") || file.source.includes("DIAGNOSTICS_COOKIE")) &&
        !COOKIE_NAME_OWNERS.includes(file.path),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });

  it("writes the preference cookie from exactly one route", () => {
    const offenders = PRODUCTION_FILES.filter(
      (file) =>
        /serializeDiagnosticsPreference|clearDiagnosticsPreference/.test(file.source) &&
        !SERIALIZER_CALLERS.includes(file.path),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });

  it("exposes no second client-side diagnostics context or provider", () => {
    const providers = PRODUCTION_FILES.filter(
      (file) =>
        /createContext/.test(file.source) && /diagnostic/i.test(file.source),
    );
    expect(providers.map((file) => file.path)).toEqual([
      "components/diagnostics/diagnostics-provider.tsx",
    ]);
  });

  it("routes every diagnostic gate through the one policy module", () => {
    // Any file that guards diagnostic presentation must import the shared
    // policy rather than deciding for itself.
    const offenders = PRODUCTION_FILES.filter((file) => {
      if (file.path.startsWith("lib/diagnostics/")) return false;
      if (file.path === "components/diagnostics/diagnostics-provider.tsx") return false;
      const usesGate = /\bWhenDiagnostics\b|\buseDiagnosticsEnabled\b|\buseDiagnosticsPolicy\b/.test(
        file.source,
      );
      if (!usesGate) return false;
      return !file.source.includes("@/components/diagnostics/diagnostics-provider");
    });
    expect(offenders.map((file) => file.path)).toEqual([]);
  });
});

describe("the scan itself is wired to real files", () => {
  it("found the modules it is guarding", () => {
    // A walker pointed at the wrong directory would make every assertion above
    // vacuously pass.
    const paths = new Set(ALL_FILES.map((file) => file.path));
    expect(paths.has("lib/diagnostics/preference.ts")).toBe(true);
    expect(paths.has("app/(app)/system/show-diagnostics-toggle.tsx")).toBe(true);
    expect(paths.has("components/diagnostics/diagnostics-provider.tsx")).toBe(true);
    expect(ALL_FILES.length).toBeGreaterThan(300);
  });
});
