// @vitest-environment node
/**
 * Route-integration negatives: a transport-200 Python envelope whose result
 * omits a required field must fail closed as `upstream_contract_invalid`, not
 * as an empty success or a minted receipt.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as reviewList } from "@/app/api/review/route";
import { POST as reviewDecide } from "@/app/api/review/[id]/decide/route";
import { POST as capture } from "@/app/api/capture/route";
import { GET as pulse } from "@/app/api/pulse/route";
import { GET as situations } from "@/app/api/situations/route";
import { GET as projects } from "@/app/api/projects/route";
import { GET as timeline } from "@/app/api/relationships/[personId]/timeline/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";

const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

const CAPTURE_RECEIPT = {
  receipt_id: "rcpt_aaaaaaaa11111111",
  principal_id: "prn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  capture_id: "cap_aaaaaaaa11111111",
  version_id: "capver_aaaaaaaa11111111",
  version_number: 1,
  idempotency_key: "k1",
  content_sha256: "0".repeat(64),
  issued_at: "2026-08-09T12:00:00Z",
  created: true,
};

function stubGateway(result: unknown, disclosure: unknown = DISCLOSURE) {
  vi.stubGlobal(
    "fetch",
    withSessionServiceFetch(async () => {
      return new Response(JSON.stringify({ result, disclosure }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

async function signIn(): Promise<string> {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }),
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

function expectContractInvalid(body: Record<string, unknown>, dump: string) {
  expect(body.error).toMatchObject({
    errorClass: "unavailable",
    code: "upstream_contract_invalid",
  });
  const serialized = JSON.stringify(body);
  expect(serialized).not.toContain(dump);
}

beforeEach(() => {
  resetSessionRegistry();
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubGlobal("fetch", withSessionServiceFetch(vi.fn()));
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("omitted required arrays fail closed at the route", () => {
  it("GET pulse with a missing pulse_items array answers 503 without dumping the payload", async () => {
    const cookie = await signIn();
    stubGateway({ leaked_pulse: "must-not-dump" });
    const response = await pulse(get(cookie, "/api/pulse"));
    expect(response.status).toBe(503);
    const body = await response.json();
    expectContractInvalid(body, "must-not-dump");
    expect(JSON.stringify(body)).not.toContain("leaked_pulse");
    expect(body).not.toHaveProperty("items");
    expect(body).not.toHaveProperty("pulse_items");
  });

  it("GET review with omitted review_cases answers 503", async () => {
    const cookie = await signIn();
    stubGateway({});
    const response = await reviewList(get(cookie, "/api/review"));
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("upstream_contract_invalid");
  });

  it("GET projects with omitted projects answers 503", async () => {
    const cookie = await signIn();
    stubGateway({});
    const response = await projects(get(cookie, "/api/projects"));
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("upstream_contract_invalid");
  });

  it("GET situations with omitted situations answers 503", async () => {
    const cookie = await signIn();
    stubGateway({});
    const response = await situations(get(cookie, "/api/situations"));
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("upstream_contract_invalid");
  });

  it("GET timeline fail-closes when situations succeeds without the workspace group", async () => {
    const cookie = await signIn();
    stubGateway({ situations: [] });
    const response = await timeline(get(cookie, "/api/relationships/p/timeline"), {
      params: Promise.resolve({ personId: "p" }),
    });
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("upstream_contract_invalid");
  });
});

describe("mutation receipts refuse synthesized fields", () => {
  it("POST capture 200 missing receipt_id is 503, not a minted receipt", async () => {
    const cookie = await signIn();
    const { receipt_id: _, ...rest } = CAPTURE_RECEIPT;
    stubGateway(rest);
    const response = await capture(post(cookie, "/api/capture", { text: "a note", idempotencyKey: "k1" }));
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(body.status).not.toBe("persisted");
    expect(body.receipt).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("rcpt_");
  });

  it("POST decide 200 with decision_id but missing review_version is 503", async () => {
    const cookie = await signIn();
    stubGateway({
      review_case_id: "rvw_aaaaaaaa11111111",
      decision_id: "rdec_aaaaaaaa11111111",
      disposition: "accept",
      proposal_state: "accepted",
      assertion_id: "asrt_aaaaaaaa11111111",
      receipt_id: "rcpt_bbbbbbbb22222222",
    });
    const response = await reviewDecide(
      post(cookie, "/api/review/rvw_aaaaaaaa11111111/decide", {
        disposition: "accept",
        expectedReviewVersion: 0,
      }),
      { params: Promise.resolve({ id: "rvw_aaaaaaaa11111111" }) },
    );
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(body.status).not.toBe("persisted");
    expect(body.receipt).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain('"reviewVersion":1');
  });
});

describe("stale expectedReviewVersion does not fabricate a decision", () => {
  it("POST decide 409 conflict is conflict, not a persisted receipt", async () => {
    const cookie = await signIn();
    vi.stubGlobal(
      "fetch",
      withSessionServiceFetch(async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "conflict",
              message: "stale expected_review_version",
              correlation_id: "corr_x",
            },
          }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
      ),
    );
    const response = await reviewDecide(
      post(cookie, "/api/review/rvw_aaaaaaaa11111111/decide", {
        disposition: "accept",
        expectedReviewVersion: 0,
      }),
      { params: Promise.resolve({ id: "rvw_aaaaaaaa11111111" }) },
    );
    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.error.errorClass).toBe("conflict");
    expect(body.status).not.toBe("persisted");
    expect(body.receipt).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("rdec_");
    expect(JSON.stringify(body)).not.toContain("decisionId");
  });
});

describe("partial disclosure is not rewritten as complete", () => {
  it("a valid empty pulse with partial_result and partially_processed is coverage partial", async () => {
    const cookie = await signIn();
    stubGateway(
      { pulse_items: [] },
      {
        ...DISCLOSURE,
        coverage: { state: "partially_processed" },
        partial_result: true,
      },
    );
    const response = await pulse(get(cookie, "/api/pulse"));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.items).toEqual([]);
    expect(body.disclosure.coverage).toBe("partial");
    expect(body.disclosure.coverage).not.toBe("complete");
  });
});
