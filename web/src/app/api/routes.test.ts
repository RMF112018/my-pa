// @vitest-environment node
/**
 * The seven acceptance surfaces, against the real route handlers.
 *
 * Four claims, and each one is a claim about what a *default* build does rather
 * than about what a configured one can be made to do:
 *
 * 1. **No core route serves fixture data with the synthetic switch unset.** Not
 *    "returns a labelled fixture" — returns none at all. The four routes that
 *    have no backend capability answer `not_implemented`, the four that have one
 *    answer from the gateway, and the fixture functions themselves refuse to
 *    produce a value.
 * 2. **Disclosure accuracy, in both directions.** A backend-served route never
 *    carries `coverage: "synthetic"` or `authority: "synthetic_fixture"`, and a
 *    synthetic-served route always carries both. Asserting only the first
 *    direction would pass against a build that labelled everything synthetic.
 * 3. **A foreign principal supplied by the browser is ignored, not honoured.**
 *    Asserted on the outcome *and* on what left the process: the request that
 *    reached the gateway carries the identifier derived from the session, and the
 *    foreign string appears nowhere in it. A body that names one is refused
 *    outright with a typed error class.
 * 4. **`acknowledged_not_persisted` is gone from the backend paths.** It survives
 *    only where it is still true, which is the explicitly-enabled synthetic one.
 *
 * The gateway is stubbed at `fetch`. The chain past that point — document,
 * socket, application, PostgreSQL row — is proved in
 * `tests/end_to_end/test_bff_reaches_postgresql.py` against a real server; a web
 * test asserting it here would be asserting it about a mock.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as system } from "@/app/api/system/route";
import { GET as library } from "@/app/api/library/route";
import { GET as reviewList } from "@/app/api/review/route";
import { POST as reviewDecide } from "@/app/api/review/[id]/decide/route";
import { POST as capture } from "@/app/api/capture/route";
import { GET as pulse } from "@/app/api/pulse/route";
import { GET as situations } from "@/app/api/situations/route";
import { GET as projects } from "@/app/api/projects/route";
import { POST as reveal } from "@/app/api/reveal/route";
import { GET as timeline } from "@/app/api/relationships/[personId]/timeline/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { SyntheticProviderDisabledError } from "@/lib/fixtures/gate";
import { syntheticPulse, syntheticDisclosure } from "@/lib/fixtures/pulse";
import { syntheticReviewCases } from "@/lib/fixtures/review";
import { syntheticSituations } from "@/lib/fixtures/situation";

const ORIGIN = "http://localhost:3000";

/** A `prn_` naming somebody the session is not. It must reach nothing. */
const FOREIGN = "prn_ffffffffffffffffffffffffffffffff";

const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

/** Every document the stubbed gateway was sent, so a test can inspect the wire. */
let sent: Array<{ url: string; body: Record<string, unknown> }> = [];

function stubGateway(result: unknown = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      sent.push({ url: String(url), body: JSON.parse(String(init?.body ?? "{}")) });
      return new Response(JSON.stringify({ result, disclosure: DISCLOSURE }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

async function signIn(key = "synthetic-a"): Promise<string> {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: key }),
    }),
  );
  expect(response.status).toBe(200);
  const cookie = (
    response as unknown as { cookies: { get(n: string): { value: string } | undefined } }
  ).cookies.get(SESSION_COOKIE_NAME);
  expect(cookie).toBeDefined();
  return cookie!.value;
}

function get(cookie: string, path: string): NextRequest {
  const request = new NextRequest(`${ORIGIN}${path}`);
  request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

function post(cookie: string, path: string, body: unknown): NextRequest {
  const request = new NextRequest(`${ORIGIN}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  request.cookies.set(SESSION_COOKIE_NAME, cookie);
  return request;
}

beforeEach(() => {
  resetSessionRegistry();
  sent = [];
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  // MYPA_DATA_PROVIDER is deliberately not stubbed here. Unset is the default
  // build, and the default build is the subject.
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Anything that would betray fixture data in a response body. */
function looksSynthetic(body: string): boolean {
  return (
    /"coverage":"synthetic"/.test(body) ||
    /synthetic_fixture/.test(body) ||
    /Synthetic fixture data/.test(body) ||
    /"pulse-/.test(body) ||
    /"sit-/.test(body) ||
    /"rev-syn/.test(body)
  );
}

describe("a default build produces no fixture data at all", () => {
  it("refuses every fixture function at the source", () => {
    const principal = {
      principalId: "syn-aaaa0001",
      tid: "t",
      oid: "o",
      upn: "u",
      displayName: "d",
      lifecycleState: "active" as const,
      synthetic: true,
    };
    expect(() => syntheticPulse(principal)).toThrow(SyntheticProviderDisabledError);
    expect(() => syntheticReviewCases(principal)).toThrow(SyntheticProviderDisabledError);
    expect(() => syntheticSituations(principal)).toThrow(SyntheticProviderDisabledError);
    expect(() => syntheticDisclosure("anything")).toThrow(SyntheticProviderDisabledError);
  });

  it("answers not_implemented, not a fixture, on every route with no backend capability", async () => {
    const cookie = await signIn();
    const responses = [
      await pulse(get(cookie, "/api/pulse")),
      await situations(get(cookie, "/api/situations")),
      await projects(get(cookie, "/api/projects")),
      await reveal(post(cookie, "/api/reveal", { subjectId: "anything" })),
      await timeline(get(cookie, "/api/relationships/p/timeline"), {
        params: Promise.resolve({ personId: "p" }),
      }),
    ];
    for (const response of responses) {
      expect(response.status).toBe(501);
      const body = await response.text();
      expect(looksSynthetic(body)).toBe(false);
      expect(JSON.parse(body).state).toBe("not_implemented");
    }
  });

  it("serves the backend, not fixtures, on every route that has a capability", async () => {
    const cookie = await signIn();
    stubGateway({ manifest: {}, readiness: {}, review_cases: [], captures: [] });
    const responses = [
      await system(get(cookie, "/api/system")),
      await library(get(cookie, "/api/library")),
      await reviewList(get(cookie, "/api/review")),
    ];
    for (const response of responses) {
      expect(response.status).toBe(200);
      expect(looksSynthetic(await response.text())).toBe(false);
    }
    expect(sent.map((call) => call.url)).toEqual([
      "http://127.0.0.1:8000/v1/capabilities.get",
      "http://127.0.0.1:8000/v1/capture.list",
      "http://127.0.0.1:8000/v1/review.list",
    ]);
  });

  it("refuses rather than falling back to fixtures when the gateway is unconfigured", async () => {
    const cookie = await signIn();
    vi.stubEnv("MYPA_GATEWAY_URL", "");
    const response = await reviewList(get(cookie, "/api/review"));
    expect(response.status).toBe(503);
    const body = await response.text();
    expect(looksSynthetic(body)).toBe(false);
    expect(JSON.parse(body).error.code).toBe("gateway_not_configured");
  });
});

describe("disclosure accuracy, in both directions", () => {
  it("a backend-served route carries a real disclosure and never a synthetic one", async () => {
    const cookie = await signIn();
    stubGateway({ review_cases: [] });
    const body = await (await reviewList(get(cookie, "/api/review"))).json();
    expect(body.shape).toBe("backend");
    expect(body.disclosure.coverage).not.toBe("synthetic");
    expect(body.disclosure.authority).not.toBe("synthetic_fixture");
    expect(body.disclosure.authority).toBe("accepted");
    expect(body.disclosure.freshnessAt).toBe("2026-08-09T12:00:00Z");
    // And it states the local-operator boundary rather than implying otherwise.
    expect(body.disclosure.limitations.join(" ")).toMatch(/local_operator/);
  });

  it("a synthetic-served route always carries the synthetic disclosure", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const cookie = await signIn();
    const body = await (await reviewList(get(cookie, "/api/review"))).json();
    expect(body.shape).toBe("synthetic");
    expect(body.disclosure.coverage).toBe("synthetic");
    expect(body.disclosure.authority).toBe("synthetic_fixture");
    const pulseBody = await (await pulse(get(cookie, "/api/pulse"))).json();
    expect(pulseBody.disclosure.coverage).toBe("synthetic");
    expect(pulseBody.disclosure.authority).toBe("synthetic_fixture");
  });
});

describe("no Principal is ever supplied by the browser", () => {
  it("refuses a body that names a foreign principal, and sends nothing", async () => {
    const cookie = await signIn();
    stubGateway({});
    const response = await capture(
      post(cookie, "/api/capture", {
        text: "a note",
        idempotencyKey: "k1",
        principal_id: FOREIGN,
      }),
    );
    expect(response.status).toBe(400);
    const body = await response.json();
    expect(body.error.code).toBe("caller_supplied_principal");
    expect(sent).toEqual([]);
  });

  it("refuses a nested foreign principal too", async () => {
    const cookie = await signIn();
    stubGateway({});
    const response = await reviewDecide(
      post(cookie, "/api/review/rvw_aaaaaaaa11111111/decide", {
        disposition: "accept",
        expectedReviewVersion: 0,
        context: { actor: { principalId: FOREIGN } },
      }),
      { params: Promise.resolve({ id: "rvw_aaaaaaaa11111111" }) },
    );
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("caller_supplied_principal");
    expect(sent).toEqual([]);
  });

  it("ignores a foreign principal in the query string: the wire carries the session's", async () => {
    const cookie = await signIn();
    stubGateway({ captures: [] });
    const response = await library(
      get(cookie, `/api/library?principalId=${FOREIGN}&principal_id=${FOREIGN}`),
    );
    expect(response.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(JSON.stringify(sent[0].body)).not.toContain(FOREIGN);
    expect(sent[0].body.principal_id).toMatch(/^prn_[0-9a-f]{32}$/);
  });

  it("ignores a foreign principal in a header", async () => {
    const cookieA = await signIn("synthetic-a");
    stubGateway({ captures: [] });
    const requestA = get(cookieA, "/api/library");
    requestA.headers.set("x-principal-id", FOREIGN);
    requestA.headers.set("x-ms-client-principal-id", FOREIGN);
    expect((await library(requestA)).status).toBe(200);

    expect(sent).toHaveLength(1);
    expect(JSON.stringify(sent)).not.toContain(FOREIGN);
    expect(sent[0].body.principal_id).toMatch(/^prn_[0-9a-f]{32}$/);
  });

  /**
   * This assertion used to sign in as `synthetic-b` as well, and check that the
   * two sessions put two different `principal_id` values on the wire. It cannot,
   * because `D-15` removed the second session: these routes run against a
   * `local_operator` gateway, which serves one fixed process principal whoever is
   * signed in, and the web tier now admits exactly one principal in that
   * configuration. That is the point rather than a loss — the two-identifier
   * scenario over a one-identity backend was the defect.
   *
   * The derivation's distinctness is not left unproved: `lib/api/gateway.test.ts`
   * asserts `correlationPrincipalId` differs for a different identity, at the
   * level the property actually lives. What is asserted here is the new fact —
   * that there is no second session to derive a second identifier from.
   */
  it("admits no second session over a local_operator gateway", async () => {
    stubGateway({ captures: [] });
    const refused = await signInRoute(
      new NextRequest(`${ORIGIN}/api/session`, {
        method: "POST",
        headers: { "content-type": "application/json", origin: ORIGIN },
        body: JSON.stringify({ syntheticPrincipal: "synthetic-b" }),
      }),
    );
    expect(refused.status).toBe(403);
    expect((await refused.json()).error.code).toBe("principal_not_admissible");
    expect(sent).toEqual([]);
  });
});

describe("the capture receipt is the backend's own", () => {
  it("returns the durable receipt and no longer says acknowledged_not_persisted", async () => {
    const cookie = await signIn();
    stubGateway({
      receipt_id: "rcpt_aaaaaaaa11111111",
      capture_id: "cap_aaaaaaaa11111111",
      version_id: "capver_aaaaaaaa11111111",
      version_number: 1,
      idempotency_key: "k1",
      content_sha256: "0".repeat(64),
      issued_at: "2026-08-09T12:00:00Z",
      created: true,
    });
    const response = await capture(post(cookie, "/api/capture", { text: "a note", idempotencyKey: "k1" }));
    expect(response.status).toBe(200);
    const raw = await response.text();
    expect(raw).not.toContain("acknowledged_not_persisted");
    const body = JSON.parse(raw);
    expect(body.status).toBe("persisted");
    expect(body.receipt.receiptId).toBe("rcpt_aaaaaaaa11111111");
    expect(body.receipt.captureId).toBe("cap_aaaaaaaa11111111");
    expect(body.created).toBe(true);
    // The note itself is never echoed back.
    expect(raw).not.toContain("a note");
    expect(sent[0].body.payload).toEqual({ text: "a note", idempotency_key: "k1" });
  });

  it("still says acknowledged_not_persisted on the synthetic path, where it is true", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const cookie = await signIn();
    const body = await (
      await capture(post(cookie, "/api/capture", { text: "a note", idempotencyKey: "k2" }))
    ).json();
    expect(body.status).toBe("acknowledged_not_persisted");
    expect(body.shape).toBe("synthetic");
  });
});

describe("the review decision is the backend's own", () => {
  it("returns the receipt review.decide issued, under the caller's stated version", async () => {
    const cookie = await signIn();
    stubGateway({
      review_case_id: "rvw_aaaaaaaa11111111",
      decision_id: "rdec_aaaaaaaa11111111",
      review_version: 1,
      disposition: "correct_and_accept",
      proposal_state: "corrected_accepted",
      assertion_id: "asrt_aaaaaaaa11111111",
      receipt_id: "rcpt_bbbbbbbb22222222",
    });
    const response = await reviewDecide(
      post(cookie, "/api/review/rvw_aaaaaaaa11111111/decide", {
        disposition: "correct",
        correctedValue: "the reviewed value",
        expectedReviewVersion: 0,
      }),
      { params: Promise.resolve({ id: "rvw_aaaaaaaa11111111" }) },
    );
    expect(response.status).toBe(200);
    const raw = await response.text();
    expect(raw).not.toContain("acknowledged_not_persisted");
    const body = JSON.parse(raw);
    expect(body.status).toBe("persisted");
    expect(body.receipt.receiptId).toBe("rcpt_bbbbbbbb22222222");
    expect(body.receipt.assertionId).toBe("asrt_aaaaaaaa11111111");
    // The workbench verb was translated to the domain's own.
    expect(sent[0].body.payload).toMatchObject({
      review_case_id: "rvw_aaaaaaaa11111111",
      expected_review_version: 0,
      disposition: "correct_and_accept",
      corrected_value: "the reviewed value",
    });
  });

  it("requires the expected review version rather than guessing one", async () => {
    const cookie = await signIn();
    stubGateway({});
    const response = await reviewDecide(
      post(cookie, "/api/review/rvw_aaaaaaaa11111111/decide", { disposition: "accept" }),
      { params: Promise.resolve({ id: "rvw_aaaaaaaa11111111" }) },
    );
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("missing_expected_review_version");
    expect(sent).toEqual([]);
  });

  it("passes a backend conflict through as a conflict, not as a success", async () => {
    const cookie = await signIn();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: { code: "conflict", message: "stale version", correlation_id: "corr_x" },
            }),
            { status: 409, headers: { "content-type": "application/json" } },
          ),
      ),
    );
    const response = await reviewDecide(
      post(cookie, "/api/review/rvw_aaaaaaaa11111111/decide", {
        disposition: "accept",
        expectedReviewVersion: 7,
      }),
      { params: Promise.resolve({ id: "rvw_aaaaaaaa11111111" }) },
    );
    expect(response.status).toBe(409);
    expect((await response.json()).error.errorClass).toBe("conflict");
  });
});

describe("System reports what is off as off", () => {
  it("names Graph as deliberately off and never as a degraded source", async () => {
    const cookie = await signIn();
    stubGateway({ manifest: {}, readiness: {} });
    const body = await (await system(get(cookie, "/api/system"))).json();
    expect(body.graphConnector.state).toBe("off_by_default");
    expect(body.graphConnector.detail).toMatch(/deliberately off/);
    // No *value* anywhere reports a degraded state. The word appears in the
    // detail sentence only, which denies degradation rather than asserting it,
    // so the check is on the values rather than on the whole document.
    const values = JSON.stringify(Object.values(body).concat(Object.values(body.graphConnector)));
    expect(values).not.toMatch(/"degraded"/i);
    expect(body.graphConnector.state).not.toBe("degraded");
  });

  it("reports connected sources as unknown rather than asserting there are none", async () => {
    const cookie = await signIn();
    stubGateway({ manifest: {}, readiness: {} });
    const body = await (await system(get(cookie, "/api/system"))).json();
    expect(body.connectedSources).toBeNull();
    expect(body.disclosure.limitations.join(" ")).toMatch(/cannot be enumerated/);
  });

  it("no longer restates a schema head the web tier cannot check", async () => {
    const cookie = await signIn();
    stubGateway({ manifest: {}, readiness: {} });
    const raw = await (await system(get(cookie, "/api/system"))).text();
    expect(raw).not.toContain("schemaHead");
  });
});

describe("an unauthenticated caller reaches nothing", () => {
  it("is refused before any provider is consulted", async () => {
    stubGateway({});
    const response = await reviewList(new NextRequest(`${ORIGIN}/api/review`));
    expect(response.status).toBe(401);
    expect(sent).toEqual([]);
  });
});
