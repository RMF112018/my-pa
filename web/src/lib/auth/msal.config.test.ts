/**
 * Sign-in has no Microsoft Graph dependency.
 *
 * Two claims, and they are different in kind. The first is about the scopes:
 * nothing this app requests at sign-in is served by Graph, so a tenant with
 * Graph unconsented — or an operator who has deliberately left it off, which is
 * this product's default — can still sign in. The second is structural: no
 * module on the sign-in path imports or starts a Graph connector, delta worker,
 * or webhook, which a scope check alone would not catch.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { apiScope, isGraphScope, msalSeamConfig, SIGN_IN_SCOPES } from "@/lib/auth/msal.config";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("sign-in scopes", () => {
  it("requests the OIDC set and nothing else by default", () => {
    vi.stubEnv("NEXT_PUBLIC_MYPA_API_SCOPE", "");
    expect(msalSeamConfig().scopes).toEqual(["openid", "profile", "offline_access"]);
  });

  it("carries no Graph resource scope", () => {
    vi.stubEnv("NEXT_PUBLIC_MYPA_API_SCOPE", "");
    for (const scope of msalSeamConfig().scopes) {
      expect(isGraphScope(scope), `${scope} is a Graph resource scope`).toBe(false);
    }
  });

  it("never requests User.Read, which is what made sign-in depend on Graph", () => {
    vi.stubEnv("NEXT_PUBLIC_MYPA_API_SCOPE", "https://graph.microsoft.com/User.Read");
    expect(msalSeamConfig().scopes).not.toContain("User.Read");
    expect(msalSeamConfig().scopes).toEqual([...SIGN_IN_SCOPES]);
    expect(apiScope()).toBeNull();
  });

  it("adds the application's own API scope when one is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_MYPA_API_SCOPE", "api://mypa-backend/access_as_user");
    expect(msalSeamConfig().scopes).toEqual([...SIGN_IN_SCOPES, "api://mypa-backend/access_as_user"]);
  });

  it("drops a configured scope that points at Graph under any spelling", () => {
    for (const graph of [
      "https://graph.microsoft.com/Mail.Read",
      "https://graph.microsoft.us/User.Read",
      "00000003-0000-0000-c000-000000000000/.default",
      "User.Read",
      "Mail.ReadWrite",
    ]) {
      vi.stubEnv("NEXT_PUBLIC_MYPA_API_SCOPE", graph);
      expect(isGraphScope(graph), `${graph} should be recognised as Graph`).toBe(true);
      expect(apiScope()).toBeNull();
      expect(msalSeamConfig().scopes).toEqual([...SIGN_IN_SCOPES]);
    }
  });

  it("does not mistake the app's own scope for a Graph one", () => {
    // The control at the other end: a guard that called everything Graph would
    // make the previous test pass and this feature impossible.
    for (const own of [
      "api://mypa-backend/access_as_user",
      "https://mypa.example.com/api/.default",
      "openid",
      "offline_access",
    ]) {
      expect(isGraphScope(own), `${own} should not be treated as Graph`).toBe(false);
    }
  });
});

/** Every module reachable from the sign-in page and the session route. */
const SIGN_IN_PATH_ROOTS = [
  "src/app/sign-in/page.tsx",
  "src/app/api/session/route.ts",
  "src/lib/auth/msal.config.ts",
  "src/lib/auth/mode.ts",
  "src/lib/auth/claims.ts",
  "src/lib/auth/session.ts",
  "src/lib/auth/session-registry.ts",
  "src/lib/auth/principal.ts",
  "src/lib/auth/synthetic.ts",
  "src/lib/http/origin.ts",
  "src/middleware.ts",
];

const WEB_ROOT = resolve(__dirname, "..", "..", "..");

/**
 * Anything that would mean a Graph connector, delta worker, or webhook.
 *
 * A Graph *request* is `https://graph.microsoft.…`, with the scheme. The bare
 * host appears in `msal.config.ts` inside the list of markers it refuses, and a
 * pattern that fired on the refusal as well as on the use would have to be
 * turned off. Whether a Graph scope is ever *requested* is proved above, by
 * calling `msalSeamConfig` rather than by reading its source.
 */
const GRAPH_MACHINERY =
  /@microsoft\/microsoft-graph|microsoft-graph-client|https:\/\/graph\.microsoft\.|deltaLink|deltaToken|graphConnector|GraphClient|createSubscription/;

describe("no Graph machinery on the sign-in path", () => {
  it("scans a sign-in path that actually exists", () => {
    for (const relative of SIGN_IN_PATH_ROOTS) {
      expect(statSync(join(WEB_ROOT, relative)).isFile()).toBe(true);
    }
  });

  it("imports or starts no Graph connector, delta worker, or webhook", () => {
    for (const relative of SIGN_IN_PATH_ROOTS) {
      const source = readFileSync(join(WEB_ROOT, relative), "utf8");
      // Comments explain why Graph is absent; the guard is about code, so the
      // block and line comments are stripped before it looks.
      const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
      expect(GRAPH_MACHINERY.test(code), `${relative} reaches Microsoft Graph`).toBe(false);
    }
  });

  it("finds no Graph connector anywhere in the web tier at all", () => {
    // Graph is retained and off by default; the web tier has no implementation
    // of it, and this is what keeps "off" from becoming "off unless someone
    // adds a file".
    const offenders: string[] = [];
    const walk = (directory: string): void => {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === "node_modules" || entry.name === ".next") continue;
          walk(path);
        } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
          const source = readFileSync(path, "utf8");
          if (/@microsoft\/microsoft-graph|microsoft-graph-client/.test(source)) {
            offenders.push(path);
          }
        }
      }
    };
    walk(join(WEB_ROOT, "src"));
    expect(offenders).toEqual([]);
  });

  it("declares no Graph SDK as a dependency", () => {
    const manifest = JSON.parse(readFileSync(join(WEB_ROOT, "package.json"), "utf8"));
    const declared = Object.keys({
      ...(manifest.dependencies ?? {}),
      ...(manifest.devDependencies ?? {}),
    });
    expect(declared.filter((name) => name.includes("graph"))).toEqual([]);
  });
});
