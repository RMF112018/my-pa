// @vitest-environment node
/**
 * The seven acceptance surfaces, against the real route handlers.
 *
 * Four claims, and each one is a claim about what a *default* build does rather
 * than about what a configured one can be made to do:
 *
 * 1. **No core route serves fixture data with the synthetic switch unset.** Not
 *    "returns a labelled fixture" — returns none at all. The four routes that
 *    have no backend capability answer `not_implemented`, the five that have one
 *    answer from the gateway, and the fixture functions themselves refuse to
 *    produce a value. Reveal moved from the first group to the second at WP-09,
 *    when `knowledge.reveal` gave it a capability to reach.
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
import { GET as sessionIntrospection, POST as signInRoute } from "@/app/api/session/route";
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
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";
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
    withSessionServiceFetch(async (url: string | URL | Request, init?: RequestInit) => {
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
    headers: { "content-type": "application/json", origin: ORIGIN },
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
  vi.stubGlobal("fetch", withSessionServiceFetch(vi.fn()));
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

  it("serves the backend, not fixtures, on every route that has a capability", async () => {
    const cookie = await signIn();
    stubGateway({
      manifest: {},
      readiness: {},
      review_cases: [],
      captures: [],
      pulse_items: [],
      situations: [],
      projects: [],
      relationship_events: [],
    });
    const responses = [
      await system(get(cookie, "/api/system")),
      await library(get(cookie, "/api/library")),
      await reviewList(get(cookie, "/api/review")),
      await reveal(post(cookie, "/api/reveal", { subjectId: "cap_aaaaaaaa11111111" })),
      await pulse(get(cookie, "/api/pulse")),
      await situations(get(cookie, "/api/situations")),
      await projects(get(cookie, "/api/projects")),
      await timeline(get(cookie, "/api/relationships/p/timeline"), {
        params: Promise.resolve({ personId: "p" }),
      }),
    ];
    for (const response of responses) {
      expect(response.status).toBe(200);
      expect(looksSynthetic(await response.text())).toBe(false);
    }
    expect(sent.map((call) => call.url)).toEqual([
      "http://127.0.0.1:8000/v1/capabilities.get",
      "http://127.0.0.1:8000/v1/capture.list",
      "http://127.0.0.1:8000/v1/review.list",
      "http://127.0.0.1:8000/v1/knowledge.reveal",
      "http://127.0.0.1:8000/v1/continuity.pulse",
      "http://127.0.0.1:8000/v1/continuity.situations",
      "http://127.0.0.1:8000/v1/continuity.projects",
      "http://127.0.0.1:8000/v1/continuity.situations",
    ]);
  });

  it("refuses rather than falling back to fixtures when the gateway is unconfigured", async () => {
    const cookie = await signIn();
    vi.stubEnv("MYPA_GATEWAY_URL", "");
    const response = await reviewList(get(cookie, "/api/review"));
    expect(response.status).toBe(503);
    const body = await response.text();
    expect(looksSynthetic(body)).toBe(false);
    // Session-service and Capture share MYPA_GATEWAY_URL. An unset URL fails
    // SID resolve first, which is still a refusal rather than fixture data.
    expect(JSON.parse(body).error.code).toBe("authority_unavailable");
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

describe("Library distinguishes an unavailable scope from an empty one", () => {
  /** The gateway envelope for a scope that could not be searched. */
  const UNAVAILABLE_DISCLOSURE = {
    ...DISCLOSURE,
    coverage: { state: "unavailable" },
    partial_result: true,
    limitations: ["evidence_scope_was_not_searched"],
  };

  function stubGatewayWith(result: unknown, disclosure: unknown) {
    vi.stubGlobal(
      "fetch",
      withSessionServiceFetch(async (url: string | URL | Request, init?: RequestInit) => {
        sent.push({ url: String(url), body: JSON.parse(String(init?.body ?? "{}")) });
        return new Response(JSON.stringify({ result, disclosure }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );
  }

  it("says `unavailable` for a scope the backend could not search", async () => {
    const cookie = await signIn();
    stubGatewayWith({ captures: [] }, UNAVAILABLE_DISCLOSURE);
    const body = await (await library(get(cookie, "/api/library"))).json();
    expect(body.state).toBe("unavailable");
    expect(body.disclosure.coverage).toBe("unavailable");
  });

  it("says `results` for the identical empty page over a scope that was searched", async () => {
    const cookie = await signIn();
    stubGatewayWith({ captures: [] }, DISCLOSURE);
    const body = await (await library(get(cookie, "/api/library"))).json();
    // The same empty `captures` as the test above, and a different answer.
    expect(body.result.captures).toEqual([]);
    expect(body.state).toBe("results");
    expect(body.disclosure.coverage).not.toBe("unavailable");
  });
});

describe("Reveal carries the backend's own outcome, and does not recompute one", () => {
  /** An unavailable reveal: no rows, and a state that is not "found nothing". */
  const UNAVAILABLE = {
    state: "unavailable",
    gap: "derivation_has_not_completed_for_every_version",
    subject_kind: "capture",
    capture_id: "cap_aaaaaaaa11111111",
    versions: [],
    spans: [],
    proposed: [],
    accepted: [],
    versions_with_completed_derivation: 0,
  };

  it("passes an unavailable state through rather than deriving one from empty arrays", async () => {
    const cookie = await signIn();
    stubGateway(UNAVAILABLE);
    const response = await reveal(
      post(cookie, "/api/reveal", { subjectId: "cap_aaaaaaaa11111111" }),
    );
    expect(response.status).toBe(200);
    const body = await response.json();
    // The route did not turn "we could not search" into "here is nothing".
    expect(body.state).toBe("unavailable");
    expect(body.result.gap).toBe("derivation_has_not_completed_for_every_version");
    expect(body.shape).toBe("backend");
  });

  it("keeps `no_evidence` distinct from `unavailable` over identical empty rows", async () => {
    const cookie = await signIn();
    stubGateway({ ...UNAVAILABLE, state: "no_evidence", gap: null });
    const body = await (
      await reveal(post(cookie, "/api/reveal", { subjectId: "cap_aaaaaaaa11111111" }))
    ).json();
    // Same arrays as the test above, different answer.
    expect(body.result.spans).toEqual([]);
    expect(body.state).toBe("no_evidence");
    expect(body.result.gap).toBeNull();
  });

  it("refuses a subject identifier that is not opaque, before any request is sent", async () => {
    const cookie = await signIn();
    stubGateway(UNAVAILABLE);
    const response = await reveal(post(cookie, "/api/reveal", { subjectId: "../../etc/passwd" }));
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("invalid_identifier");
    expect(sent).toEqual([]);
  });

  it("sends the session-derived principal and never one the body names", async () => {
    const cookie = await signIn();
    stubGateway(UNAVAILABLE);
    const response = await reveal(
      post(cookie, "/api/reveal", { subjectId: "cap_aaaaaaaa11111111", principal_id: FOREIGN }),
    );
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("caller_supplied_principal");
    expect(sent).toEqual([]);
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
      principal_id: "prn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
    expect(body.receipt.principalId).toBe("syn-aaaa0001");
    expect(body.created).toBe(true);
    // The note itself is never echoed back.
    expect(raw).not.toContain("a note");
    // The kind travels with the note and defaults rather than being required.
    expect(sent[0].body.payload).toEqual({
      text: "a note",
      idempotency_key: "k1",
      capture_kind: "quick_note",
    });
  });

  it("binds the browser receipt to the authenticated BFF Principal", async () => {
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
    expect((await response.json()).receipt.principalId).toBe("syn-aaaa0001");
  });

  it("refuses a replay when the authenticating cookie changes after session introspection", async () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
    const cookieA = await signIn("synthetic-a");
    const authority = await (await sessionIntrospection(get(cookieA, "/api/session"))).json();
    expect(authority).toMatchObject({ principalId: "syn-aaaa0001" });

    const cookieB = await signIn("synthetic-b");
    stubGateway({});
    const replayRequest = post(cookieB, "/api/capture", {
      text: "synthetic held note",
      idempotencyKey: "held-a-1",
    });
    replayRequest.headers.set("x-my-pa-replay-binding", authority.replayBinding);
    const response = await capture(replayRequest);

    expect(response.status).toBe(409);
    expect((await response.json()).error.code).toBe("replay_session_changed");
    expect(sent).toEqual([]);
  });

  it("checks a changed replay session before parsing queued plaintext", async () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
    const cookieA = await signIn("synthetic-a");
    const authority = await (await sessionIntrospection(get(cookieA, "/api/session"))).json();
    const cookieB = await signIn("synthetic-b");
    const request = new NextRequest(`${ORIGIN}/api/capture`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: ORIGIN,
        "x-my-pa-replay-binding": authority.replayBinding,
      },
      body: "synthetic plaintext that is deliberately not parsed as JSON",
    });
    request.cookies.set(SESSION_COOKIE_NAME, cookieB);

    const response = await capture(request);

    expect(response.status).toBe(409);
    expect((await response.json()).error.code).toBe("replay_session_changed");
    expect(sent).toEqual([]);
  });

  it("carries an explicitly selected conversation log through to the gateway", async () => {
    const cookie = await signIn();
    stubGateway({
      receipt_id: "rcpt_aaaaaaaa11111111",
      principal_id: "prn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      capture_id: "cap_aaaaaaaa11111111",
      version_id: "capver_aaaaaaaa11111111",
      version_number: 1,
      idempotency_key: "k3",
      content_sha256: "0".repeat(64),
      issued_at: "2026-08-09T12:00:00Z",
      created: true,
    });
    const response = await capture(
      post(cookie, "/api/capture", {
        text: "a note",
        idempotencyKey: "k3",
        captureKind: "conversation_log",
      }),
    );
    expect(response.status).toBe(200);
    expect(sent[0].body.payload).toMatchObject({ capture_kind: "conversation_log" });
  });

  it("refuses a kind it does not know rather than defaulting it silently", async () => {
    const cookie = await signIn();
    stubGateway({});
    const response = await capture(
      post(cookie, "/api/capture", {
        text: "a note",
        idempotencyKey: "k4",
        captureKind: "voice_memo",
      }),
    );
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("unknown_capture_kind");
    // A refused request reaches no backend at all.
    expect(sent).toEqual([]);
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
      withSessionServiceFetch(async () =>
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

describe("Today is a derivation, not a feed", () => {
  /** Two derived items whose urgency order is the reverse of their recency order. */
  const DERIVED = [
    {
      pulse_id: "puls_overdue0001overdue0001",
      item_type: "commitment",
      item_ref: "cmt_overdue0001overdue001",
      reason_code: "commitment_overdue",
      reason: "The agreed moment passed 10 day(s) ago and the commitment is still open.",
      basis_refs: ["cmt_overdue0001overdue001", "cap_origin0001origin0001"],
      consequence: "A counterparty is still entitled to expect this.",
      next_step: "Close it with the evidence that discharged it.",
      priority: 9,
      generated_at: "2026-08-10T12:00:00Z",
    },
    {
      pulse_id: "puls_soon00001soon00001aa",
      item_type: "commitment",
      item_ref: "cmt_soon00001soon00001aa",
      reason_code: "commitment_due_soon",
      reason: "The agreed moment is 3 hour(s) away.",
      basis_refs: ["cmt_soon00001soon00001aa"],
      consequence: "Leaving it later removes the option of re-agreeing the moment.",
      next_step: "Confirm it will be met, or say now that it will not.",
      priority: 4,
      generated_at: "2026-08-10T12:00:00Z",
    },
  ];

  it("carries a why-now reason code and an evidentiary basis on every item", async () => {
    const cookie = await signIn();
    stubGateway({ pulse_items: DERIVED });
    const body = await (await pulse(get(cookie, "/api/pulse"))).json();
    expect(body.shape).toBe("backend");
    expect(body.items).toHaveLength(2);
    for (const item of body.items) {
      expect(item.reasonCode).toMatch(/^[a-z_]+$/);
      expect(item.basisRefs.length).toBeGreaterThan(0);
      expect(item.nextStep).toBeTruthy();
      expect(item.priority).toBeGreaterThan(0);
    }
  });

  it("preserves the gateway's ranked order and never re-sorts by time", async () => {
    // Every item shares one `generatedAt` — it is the moment of the read — so a
    // route that sorted by it would produce an arbitrary order. The assertion is
    // that the order out is the order in.
    const cookie = await signIn();
    stubGateway({ pulse_items: DERIVED });
    const body = await (await pulse(get(cookie, "/api/pulse"))).json();
    expect(body.items.map((i: { pulseId: string }) => i.pulseId)).toEqual(
      DERIVED.map((i) => i.pulse_id),
    );
    expect(new Set(body.items.map((i: { generatedAt: string }) => i.generatedAt)).size).toBe(1);
  });

  it("sends no principal on the wire and no payload a caller could shape", async () => {
    const cookie = await signIn();
    stubGateway({ pulse_items: [] });
    await pulse(get(cookie, "/api/pulse"));
    const call = sent.at(-1)!;
    expect(call.url).toBe("http://127.0.0.1:8000/v1/continuity.pulse");
    expect(call.body.payload).toEqual({});
    // The envelope carries a session-derived correlation principal and the
    // request body carries no other identity field at all.
    expect(Object.keys(call.body).sort()).toEqual(
      ["contract_version", "payload", "principal_id", "purpose", "request_id", "requested_at"],
    );
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

describe("mutating capture, review, and reveal refuse cross-site callers", () => {
  function mutatingPost(
    cookie: string,
    path: string,
    body: unknown,
    origin: string | null,
  ): NextRequest {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (origin !== null) headers.origin = origin;
    const request = new NextRequest(`${ORIGIN}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    request.cookies.set(SESSION_COOKIE_NAME, cookie);
    return request;
  }

  it.each([
    { name: "foreign Origin", origin: "https://attacker.example" },
    { name: "missing Origin", origin: null },
  ])("refuses Capture with $name before the gateway", async ({ origin }) => {
    const cookie = await signIn();
    stubGateway({});
    const response = await capture(
      mutatingPost(cookie, "/api/capture", { text: "a note", idempotencyKey: "k-cross" }, origin),
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(sent).toEqual([]);
    expect(JSON.stringify(sent)).not.toContain("capture.create");
  });

  it.each([
    { name: "foreign Origin", origin: "https://attacker.example" },
    { name: "missing Origin", origin: null },
  ])("refuses Review decide with $name before the gateway", async ({ origin }) => {
    const cookie = await signIn();
    stubGateway({});
    const response = await reviewDecide(
      mutatingPost(
        cookie,
        "/api/review/rvw_aaaaaaaa11111111/decide",
        { disposition: "accept", expectedReviewVersion: 0 },
        origin,
      ),
      { params: Promise.resolve({ id: "rvw_aaaaaaaa11111111" }) },
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(sent).toEqual([]);
    expect(JSON.stringify(sent)).not.toContain("review.decide");
  });

  it.each([
    { name: "foreign Origin", origin: "https://attacker.example" },
    { name: "missing Origin", origin: null },
  ])("refuses Reveal with $name before the gateway", async ({ origin }) => {
    const cookie = await signIn();
    stubGateway({});
    const response = await reveal(
      mutatingPost(cookie, "/api/reveal", { subjectId: "cap_aaaaaaaa11111111" }, origin),
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(sent).toEqual([]);
    expect(JSON.stringify(sent)).not.toContain("knowledge.reveal");
  });
});
