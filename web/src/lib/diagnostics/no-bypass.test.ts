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
  // Reads the stored value to advance its generation before writing the next.
  "app/api/system/diagnostics/route.ts",
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
    // Matched on the parameter *key*, not on co-occurrence. Pages legitimately
    // read `searchParams` and also hold a `diagnosticsEnabled` boolean resolved
    // from the cookie; a proximity match flagged six of them and would have
    // trained the next reader to ignore this guard.
    const QUERY_KEY = /(?:get|has)\(\s*["'`][^"'`]*(?:diagnostic|debug)|searchParams\s*\.\s*(?:diagnostics|debug)\b|\[\s*["'`](?:diagnostics|debug)["'`]\s*\]|[?&](?:diagnostics|debug)=/i;
    const offenders = PRODUCTION_FILES.filter((file) => QUERY_KEY.test(file.source));
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

describe("the server never builds diagnostic props while diagnostics are off", () => {
  /**
   * F-01. `SurfaceState` renders client components, so a *server* component
   * that passes `error`, `diagnostic` or `limitations` has those values
   * serialized into the RSC Flight payload — which ships inside the HTML,
   * before any client gate runs. Hiding them on the client is the
   * "server-render then strip" pattern the contract rejects, and no DOM test
   * can see it. Server callsites must therefore wrap every one of those props
   * in its `diagnostic*` helper, which yields nothing while diagnostics are off.
   *
   * This guard exists because the leak is invisible: the page looks correct,
   * the DOM is clean, and only `view-source` shows the problem.
   */
  const SERVER_FILES = ALL_FILES.filter(
    (file) =>
      !/\.(test|stories|story\.test)\./.test(file.path) &&
      /\.tsx$/.test(file.path) &&
      !file.source.trimStart().startsWith('"use client"'),
  );

  /**
   * The prop names that carry engineering detail across the server/client
   * boundary, each with the helper that must decide before the element is built.
   *
   * `unavailableDiagnostic` is here because an independent review found the
   * People entity page handing a raw `outcome.error.message` to its panels as
   * `unavailable`, where it did double duty as both "the read failed" and "here
   * is what the gateway said". That was safe only because the receiving
   * component happens to be a server component too, so the string died
   * server-side — a property of *that* file, not of this boundary. The prop is
   * now split: `unavailable` is the boolean fact, needed in both modes and
   * carrying nothing; `unavailableDiagnostic` is the backend's sentence and is
   * guarded here, so the safety no longer depends on an accident.
   */
  const GUARDED: ReadonlyArray<readonly [string, string]> = [
    ["error", "diagnosticError"],
    ["diagnostic", "diagnosticText"],
    ["limitations", "diagnosticLimitations"],
    ["unavailableDiagnostic", "diagnosticText"],
  ];

  for (const [prop, helper] of GUARDED) {
    it(`wraps every server-side \`${prop}\` in ${helper}`, () => {
      const pattern = new RegExp(`\\b${prop}=\\{(?!${helper}\\()`);
      const offenders = SERVER_FILES.filter((file) => {
        // The component that defines the props is where they are consumed.
        if (file.path === "components/ui/surface-state.tsx") return false;
        return pattern.test(file.source);
      });
      expect(offenders.map((file) => file.path)).toEqual([]);
    });
  }
});

describe("raw transport text never reaches the ungated product-language prop", () => {
  /**
   * F-02. `detail` is the one `SurfaceState` prop deliberately left ungated,
   * because it is meant to be product language. Feeding it a backend
   * `error.message` or an HTTP status template routes raw transport text
   * straight around the policy — the gate is not "one policy" if a caller can
   * walk around it by choosing a different prop name.
   */
  it("never feeds `detail` from a raw message or status template", () => {
    // `mapUserError` returns product language by construction, so a `detail`
    // taken from its result (conventionally `failure`/`presented`) is correct.
    // What is forbidden is a `detail` taken straight off a transport or
    // capability answer, or built from an HTTP status.
    const RAW_DETAIL =
      /\bdetail=\{[^}]*(?:\b(?:error|err|answer|response|result)\.message\b|\.error\.message\b|failed with status|`[^`]*\$\{[^}]*status)/;
    const offenders = ALL_FILES.filter(
      (file) => !/\.(test|stories|story\.test)\./.test(file.path) && RAW_DETAIL.test(file.source),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });
});

describe("a diagnostic is a closed record, and nothing else can become one", () => {
  /**
   * WP08-RT-F010. The WP07 guards above are about *whether* engineering detail
   * is built. This one is about *what* it may be. The three helpers were
   * pass-through filters, `mapUserError` deliberately put raw transport text in
   * its `diagnostic`, and `DiagnosticsDetails` rendered that string verbatim —
   * so with diagnostics on, an arbitrary backend string reached the DOM. The
   * fix is a type: `SafeDiagnostic` and `SafeLimitations` in
   * `lib/diagnostics/safe-detail.ts`, which the props now demand.
   *
   * The compiler holds most of that line on its own. What it cannot hold is the
   * three edits that would quietly take it back — widening a prop declaration
   * to `string`, casting into the branded type from outside its module, or
   * routing an upstream `message` into something diagnostic-shaped. Those are
   * whole-tree statements, so they are asserted here, in the same
   * offender-list style as the rules above.
   */

  /** Where the vocabulary is defined, and the only place it may be minted. */
  const VOCABULARY_OWNER = "lib/diagnostics/safe-detail.ts";

  it("mints the safe types only inside their own module", () => {
    // A cast is the one way to conjure a branded value without a constructor.
    const MINT = /\bas\s+(?:unknown\s+as\s+)?Safe(?:Diagnostic|Limitations)\b|\bsatisfies\s+Safe(?:Diagnostic|Limitations)\b/;
    const offenders = ALL_FILES.filter(
      (file) => file.path !== VOCABULARY_OWNER && MINT.test(file.source),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });

  it("declares no diagnostic-bearing prop as a raw string again", () => {
    // The reintroduction edit, named directly: a prop or field called
    // `diagnostic` or `unavailableDiagnostic` typed back to free text. Those
    // two names exist in this tree only as rendering props, so the rule can be
    // whole-tree without catching the data model. `limitations` is not included
    // here for the opposite reason — `DisclosureEnvelope.limitations` is the
    // contract's own `readonly string[]` and must stay one; what may not be a
    // string list is the *prop*, and the assertion below holds that.
    //
    // `receipt` is not in this alternation, and the test that follows says why:
    // it is deliberately still a `string`, because what it carries is text this
    // tier formatted itself, so its guarantee is a feed rule rather than a type.
    const WIDENED = /\b(?:diagnostic|unavailableDiagnostic)\??:\s*(?:readonly\s+)?string\b/;
    const offenders = PRODUCTION_FILES.filter(
      (file) => file.path !== VOCABULARY_OWNER && WIDENED.test(file.source),
    );
    expect(offenders.map((file) => file.path)).toEqual([]);
  });

  it("feeds the one remaining free-string receipt channel only from its own writers", () => {
    // NB-03. WP08-RT-F010 renamed `StatusNote`'s diagnostic prop from
    // `diagnostic` to `receipt`, which moved the tree's last free-string
    // diagnostic-bearing prop outside the `WIDENED` rule above. Adding
    // `receipt` to that alternation would fail immediately and for the wrong
    // reason: the prop is *meant* to be a string, because what it carries is
    // receipt text this tier formatted itself — a bulk-operation id and an ISO
    // expiry — which no closed vocabulary can express. So the rule is stated
    // over the feed instead: the channel exists in exactly one place, and
    // everything that reaches it is either described from the closed
    // vocabulary or built from this tier's own template. An upstream
    // `message` never is.
    const callsites = PRODUCTION_FILES.filter((file) => /\breceipt=\{/.test(file.source));
    expect(callsites.map((file) => file.path)).toEqual(["components/work/workbench.tsx"]);
    const workbench = callsites[0]!.source;
    expect(workbench).toContain("describeSafeDiagnostic(safeDiagnostic(error))");
    expect(workbench).not.toMatch(/setStatusReceipt\([^)]*\.message\b/);
    expect(workbench).not.toMatch(/\breceipt\s*=\s*[^;\n]*\.message\b/);
    expect(workbench).not.toMatch(/\breceipt=\{[^}]*\.message\b/);
  });

  it("keeps the rendering props declared as the safe types", () => {
    // The two components that consume the vocabulary. A widening edit lands
    // here first, and the compiler only helps once these say what they say.
    const details = PRODUCTION_FILES.find(
      (file) => file.path === "components/ui/diagnostics-details.tsx",
    );
    const surface = PRODUCTION_FILES.find(
      (file) => file.path === "components/ui/surface-state.tsx",
    );
    expect(details?.source).toContain("diagnostic?: SafeDiagnostic | null");
    expect(details?.source).toContain("limitations: SafeLimitations");
    expect(surface?.source).toContain("readonly diagnostic?: SafeDiagnostic | null");
    expect(surface?.source).toContain("readonly error?: SafeDiagnostic");
    expect(surface?.source).toContain("readonly limitations?: SafeLimitations");
  });

  it("never routes an upstream message into anything diagnostic-shaped", () => {
    // `error.message` is the field with no shape and no upstream guarantee, and
    // it is where a raw exception or a connection string arrives when one does.
    // It may not be assigned to a diagnostic-named binding, nor handed to one
    // of the diagnostic-bearing props.
    const RAW_INTO_DIAGNOSTIC =
      /\b\w*[Dd]iagnostic\w*\s*[=:]\s*[^;,\n]*\b\w+\.message\b|\b(?:diagnostic|error|unavailableDiagnostic)=\{[^}]*\b\w+\.message\b/;
    const offenders = PRODUCTION_FILES.filter((file) => RAW_INTO_DIAGNOSTIC.test(file.source));
    expect(offenders.map((file) => file.path)).toEqual([]);
  });

  it("renders the diagnostic through the module's own writer", () => {
    // Interpolating the record itself, or any field of it, would put text on
    // the page that this module did not author.
    const owner = PRODUCTION_FILES.find(
      (file) => file.path === "components/ui/diagnostics-details.tsx",
    );
    expect(owner).toBeDefined();
    expect(owner?.source).toContain("describeSafeDiagnostic(diagnostic)");
    expect(owner?.source).not.toMatch(/\{\s*diagnostic\s*\}/);
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
    expect(paths.has("lib/diagnostics/safe-detail.ts")).toBe(true);
    expect(ALL_FILES.length).toBeGreaterThan(300);
  });
});
