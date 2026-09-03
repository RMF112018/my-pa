// @vitest-environment node
/**
 * `D-15`: two identities over a one-identity backend is one identity in two costumes.
 *
 * The defect this file closes was demonstrated live, not theorised. WP-06's
 * reviewer signed in as `synthetic-a`, captured a note, signed in as
 * `synthetic-b`, and read A's capture back through `/api/library` — a full-text
 * match on A's exact text — because the Python gateway in
 * `MYPA_GATEWAY_AUTH_MODE=local_operator` serves one fixed process principal
 * whoever is signed in here. It was disclosed and not prevented. WP-07 makes that
 * read carry durable user-authored text, so under the operating brief's
 * release-blocking Principal-isolation invariant it had to be prevented.
 *
 * **The controlling assertion is the second sign-in, not the first.** A test that
 * only checked that `synthetic-a` still works would pass against an
 * implementation that changed nothing. What is asserted here is that
 * `synthetic-b` **cannot sign in at all** in that configuration — no cookie, no
 * session, no fallback to A's — so the second identity does not exist to read A's
 * data with.
 *
 * The complementary case is asserted too: under `MYPA_GATEWAY_AUTH_MODE=entra`
 * both principals remain admissible, because two real Principals there are two
 * real datasets and narrowing them would be deleting a capability rather than a
 * costume.
 *
 * Everything here is synthetic. No live tenant, no live principal, no real text.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "@/app/api/session/route";
import { GET as library } from "@/app/api/library/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { issueSyntheticSession } from "@/lib/auth/session-service";
import {
  admissibleSyntheticPrincipals,
  resolveAdmissibleSyntheticPrincipal,
  PrincipalNotAdmissibleError,
  PINNED_SYNTHETIC_PRINCIPAL_KEY,
  SYNTHETIC_MOSS_TENANT_ID,
} from "@/lib/auth/synthetic";

vi.mock("@/lib/auth/session-service", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth/session-service")>();
  return {
    ...actual,
    issueSyntheticSession: vi.fn(),
  };
});

const ORIGIN = "http://localhost:3000";
const mockedIssue = vi.mocked(issueSyntheticSession);
let sidSeq = 0;

function nextSid(): string {
  sidSeq += 1;
  return sidSeq.toString(16).padStart(64, "0");
}

function signInRequest(key: string): NextRequest {
  return new NextRequest(`${ORIGIN}/api/session`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: ORIGIN },
    body: JSON.stringify({ syntheticPrincipal: key }),
  });
}

function issuedCookie(response: Response): string | undefined {
  return (
    response as unknown as { cookies: { get(name: string): { value: string } | undefined } }
  ).cookies.get(SESSION_COOKIE_NAME)?.value;
}

beforeEach(() => {
  resetSessionRegistry();
  sidSeq = 0;
  mockedIssue.mockImplementation(async (key) => {
    const issuedSid = nextSid();
    return {
      issuedSid,
      principal: {
        principalId: key === "synthetic-b" ? "syn-bbbb0002" : "syn-aaaa0001",
        tid: SYNTHETIC_MOSS_TENANT_ID,
        oid:
          key === "synthetic-b"
            ? "bbbb0002-0000-0000-0000-000000000002"
            : "aaaa0001-0000-0000-0000-000000000001",
        upn: key === "synthetic-b" ? "synthetic.b@moss.example" : "synthetic.a@moss.example",
        displayName: key === "synthetic-b" ? "Synthetic B" : "Synthetic A",
        lifecycleState: "active" as const,
        synthetic: true,
        authenticationProvider: "synthetic" as const,
      },
    };
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("a local_operator gateway admits exactly one principal", () => {
  beforeEach(() => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  });

  it("admits the pinned principal and no other", () => {
    const keys = admissibleSyntheticPrincipals().map((p) => p.key);
    expect(keys).toEqual([PINNED_SYNTHETIC_PRINCIPAL_KEY]);
    expect(keys).not.toContain("synthetic-b");
  });

  it("signs the pinned principal in", async () => {
    const response = await POST(signInRequest("synthetic-a"));
    expect(response.status).toBe(200);
    expect(issuedCookie(response)).toBeTruthy();
  });

  it("refuses the second principal, with a typed refusal and no session", async () => {
    const response = await POST(signInRequest("synthetic-b"));
    expect(response.status).toBe(403);
    const body = await response.json();
    // Typed, and not the pre-existing "unknown principal" answer: the key is
    // real and the deployment is the reason it is refused.
    expect(body.error.code).toBe("principal_not_admissible");
    expect(body.error.message).toContain("local_operator");
    // No cookie, no session, and — the part that matters — no substitution of
    // the pinned principal, which would rebind one identity to another.
    expect(issuedCookie(response)).toBeFalsy();
    expect(body.signedIn).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("synthetic.a@moss.example");
  });

  it("has no session for the refused principal to reach data with", async () => {
    const refused = await POST(signInRequest("synthetic-b"));
    const cookie = issuedCookie(refused);
    expect(cookie).toBeFalsy();

    // The cross-principal read the reviewer performed, attempted with whatever
    // the refusal left behind: nothing, so the request is unauthenticated.
    const probe = new NextRequest(`${ORIGIN}/api/library`);
    if (cookie) probe.cookies.set(SESSION_COOKIE_NAME, cookie);
    expect((await library(probe)).status).toBe(401);
  });

  it("raises the typed error from the resolver itself, not only from the route", () => {
    expect(() => resolveAdmissibleSyntheticPrincipal("synthetic-b")).toThrow(
      PrincipalNotAdmissibleError,
    );
    // A key that names no principal at all is a different answer, not this one.
    expect(resolveAdmissibleSyntheticPrincipal("synthetic-z")).toBeUndefined();
  });
});

describe("an entra gateway is unaffected", () => {
  beforeEach(() => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
  });

  it("keeps both principals admissible", () => {
    expect(admissibleSyntheticPrincipals().map((p) => p.key)).toEqual([
      "synthetic-a",
      "synthetic-b",
    ]);
  });

  it("signs either principal in", async () => {
    for (const key of ["synthetic-a", "synthetic-b"]) {
      const response = await POST(signInRequest(key));
      expect(response.status).toBe(200);
      expect(issuedCookie(response)).toBeTruthy();
    }
  });
});

describe("an unconfigured gateway mode", () => {
  beforeEach(() => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "");
  });

  it("does not narrow, because no backend request is made at all", () => {
    // The narrowing is keyed to the mode that creates the hazard. With no
    // gateway mode configured, `callGateway` refuses before it reaches a socket,
    // so there is no backend data for a second identity to read.
    expect(admissibleSyntheticPrincipals()).toHaveLength(2);
  });

  it("still refuses to serve backend data, which is what makes that safe", async () => {
    const cookie = issuedCookie(await POST(signInRequest("synthetic-b")));
    expect(cookie).toBeTruthy();
    const probe = new NextRequest(`${ORIGIN}/api/library`);
    probe.cookies.set(SESSION_COOKIE_NAME, cookie!);
    const response = await library(probe);
    expect(response.status).toBeGreaterThanOrEqual(500);
  });
});
