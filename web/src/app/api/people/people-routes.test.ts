// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as peopleCollection } from "@/app/api/people/route";
import { GET as peopleGet } from "@/app/api/people/[entityId]/route";
import { GET as peopleProfile } from "@/app/api/people/[entityId]/profile/route";
import { GET as peopleUnresolved } from "@/app/api/people/unresolved/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";
import {
  ENTITY_ID,
  ENTITY_SUMMARY,
  ENTITY_VIEW,
  PROFILE,
  RESOLUTION,
  UNRESOLVED_MENTION,
} from "@/lib/api/decode/capabilities/_entity-fixtures";

const ORIGIN = "http://localhost:3000";
const FOREIGN_ENTITY = "ent_bbbbbbbb22222222";
const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-21T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

function gatewayOk(result: unknown) {
  return new Response(JSON.stringify({ result, disclosure: DISCLOSURE }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function gatewayNotFound() {
  return new Response(
    JSON.stringify({
      error: {
        code: "not_found",
        message: "the named target was not found",
        correlation_id: "corr_aaaaaaaa11111111",
      },
    }),
    { status: 404, headers: { "content-type": "application/json" } },
  );
}

async function cookie() {
  const response = await signInRoute(
    new NextRequest(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: ORIGIN },
      body: JSON.stringify({ syntheticPrincipal: "synthetic-a" }),
    }),
  );
  return (response as unknown as { cookies: { get(name: string): { value: string } } }).cookies.get(
    SESSION_COOKIE_NAME,
  ).value;
}

function request(session: string, path: string) {
  const value = new NextRequest(`${ORIGIN}${path}`);
  value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

function stubPeopleGateway(impl?: (url: string | URL | Request, init?: RequestInit) => unknown) {
  const gateway = impl ? vi.fn(impl) : vi.fn();
  vi.stubGlobal("fetch", withSessionServiceFetch(gateway));
  return gateway;
}

beforeEach(() => {
  resetSessionRegistry();
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("People BFF collection", () => {
  it("refuses a listing with neither q nor reference", async () => {
    const gateway = stubPeopleGateway();
    const response = await peopleCollection(request(await cookie(), "/api/people"));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "validation", code: "invalid_request" },
    });
    expect(gateway).not.toHaveBeenCalled();
  });

  it("searches through entities.search", async () => {
    const gateway = stubPeopleGateway(async () => gatewayOk({ entities: [ENTITY_SUMMARY] }));
    const response = await peopleCollection(request(await cookie(), "/api/people?q=Pat%20Synthetic"));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.entities).toEqual([ENTITY_SUMMARY]);
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/entities.search");
  });

  it("resolves through entities.resolve and keeps outcome visible", async () => {
    stubPeopleGateway(async () => gatewayOk({ resolution: RESOLUTION }));
    const response = await peopleCollection(
      request(await cookie(), "/api/people?reference=Alex%20Chen"),
    );
    expect(response.status).toBe(200);
    expect((await response.json()).resolution.outcome).toBe("ambiguous");
  });

  it("fails closed when entities is omitted", async () => {
    stubPeopleGateway(async () => gatewayOk({ leaked: "must-not-dump" }));
    const response = await peopleCollection(request(await cookie(), "/api/people?q=Pat"));
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(JSON.stringify(body)).not.toContain("must-not-dump");
    expect(body).not.toHaveProperty("entities");
  });
});

describe("People BFF entity reads", () => {
  it("answers not-found for a foreign entity_id without leaking existence", async () => {
    const gateway = stubPeopleGateway(async () => gatewayNotFound());
    const response = await peopleGet(request(await cookie(), `/api/people/${FOREIGN_ENTITY}`), {
      params: Promise.resolve({ entityId: FOREIGN_ENTITY }),
    });
    expect(response.status).toBe(404);
    const body = await response.json();
    expect(body.error.errorClass).toBe("not_found");
    const serialized = JSON.stringify(body);
    expect(serialized).not.toMatch(/exist/i);
    expect(serialized).not.toMatch(/another principal/i);
    expect(serialized).not.toMatch(/belongs to/i);
    expect(serialized).not.toContain("syn-bbbb0002");
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/entities.get");
  });

  it("reads a profile through entities.profile", async () => {
    stubPeopleGateway(async () => gatewayOk({ profile: PROFILE }));
    const response = await peopleProfile(request(await cookie(), `/api/people/${ENTITY_ID}/profile`), {
      params: Promise.resolve({ entityId: ENTITY_ID }),
    });
    expect(response.status).toBe(200);
    expect((await response.json()).profile.entity).toEqual(ENTITY_VIEW);
  });

  it("fails closed when a profile family array is omitted", async () => {
    const { names: _, ...rest } = PROFILE;
    stubPeopleGateway(async () => gatewayOk({ profile: rest }));
    const response = await peopleProfile(request(await cookie(), `/api/people/${ENTITY_ID}/profile`), {
      params: Promise.resolve({ entityId: ENTITY_ID }),
    });
    expect(response.status).toBe(503);
    expect((await response.json()).error.code).toBe("upstream_contract_invalid");
  });

  it("lists unresolved mentions without echoing observed_value", async () => {
    stubPeopleGateway(async () => gatewayOk({ mentions: [UNRESOLVED_MENTION] }));
    const response = await peopleUnresolved(request(await cookie(), "/api/people/unresolved"));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.mentions[0]).not.toHaveProperty("observed_value");
  });

  it("refuses unresolved mentions that disclose observed_value", async () => {
    stubPeopleGateway(async () =>
      gatewayOk({ mentions: [{ ...UNRESOLVED_MENTION, observed_value: "should-not-leak" }] }),
    );
    const response = await peopleUnresolved(request(await cookie(), "/api/people/unresolved"));
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(JSON.stringify(body)).not.toContain("should-not-leak");
  });
});
