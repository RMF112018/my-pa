// @vitest-environment node
/**
 * The server-side transport: what it sends, what it refuses to send, and where
 * it is allowed to run.
 *
 * The assertions worth naming are the negative ones. A transport that builds a
 * plausible request is easy; the properties that matter here are that it never
 * carries a caller's identity, never invents a credential, never falls back to a
 * default backend address, and never reaches a browser.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import contract from "@/contracts/gateway.json";
import {
  GATEWAY_TIMEOUT_MS,
  GatewayIsServerOnlyError,
  LOCAL_OPERATOR_LIMITATION,
  backendDisclosure,
  buildRequestDocument,
  callGateway,
  correlationPrincipalId,
  transportLimitations,
  type PythonDisclosure,
} from "@/lib/api/gateway";
import {
  MissingGatewayAuthModeError,
  MissingGatewayUrlError,
  SyntheticDataInProductionError,
  UnknownDataProviderError,
  gatewayBaseUrl,
  gatewayAuthMode,
  syntheticDataEnabled,
} from "@/lib/api/gateway-config";
import type { PrincipalSession } from "@/contracts/identity";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const OTHER: PrincipalSession = { ...PRINCIPAL, oid: "bbbb0002-0000-0000-0000-000000000002" };

const DISCLOSURE: PythonDisclosure = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

/** A gateway that answers one envelope, and records what it was sent. */
function stubGateway(body: unknown, status = 200) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fetchStub = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchStub);
  return { calls, fetchStub };
}

beforeEach(() => {
  vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("configuration refuses rather than defaults", () => {
  it("has no default gateway address at all", () => {
    vi.stubEnv("MYPA_GATEWAY_URL", "");
    expect(() => gatewayBaseUrl()).toThrow(MissingGatewayUrlError);
  });

  it("refuses a gateway address that is not an http(s) URL", () => {
    vi.stubEnv("MYPA_GATEWAY_URL", "file:///etc/passwd");
    expect(() => gatewayBaseUrl()).toThrow(MissingGatewayUrlError);
    vi.stubEnv("MYPA_GATEWAY_URL", "not-a-url");
    expect(() => gatewayBaseUrl()).toThrow(MissingGatewayUrlError);
  });

  it("strips a trailing slash so the joined path has one separator", () => {
    vi.stubEnv("MYPA_GATEWAY_URL", "http://127.0.0.1:8000/");
    expect(gatewayBaseUrl()).toBe("http://127.0.0.1:8000");
  });

  it("has no default gateway auth mode", () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "");
    expect(() => gatewayAuthMode()).toThrow(MissingGatewayAuthModeError);
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "whatever");
    expect(() => gatewayAuthMode()).toThrow(MissingGatewayAuthModeError);
  });
});

describe("the synthetic switch", () => {
  it("is off when it is unset — absence never produces fixture data", () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", undefined);
    expect(syntheticDataEnabled()).toBe(false);
  });

  it("is off when it is empty", () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "   ");
    expect(syntheticDataEnabled()).toBe(false);
  });

  it("refuses a value that is not a provider rather than treating it as unset", () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "syntetic");
    expect(() => syntheticDataEnabled()).toThrow(UnknownDataProviderError);
  });

  it("is refused outright in a production build", () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    vi.stubEnv("NODE_ENV", "production");
    expect(() => syntheticDataEnabled()).toThrow(SyntheticDataInProductionError);
  });

  it("is on only when explicitly set outside production", () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    expect(syntheticDataEnabled()).toBe(true);
  });
});

describe("the request document", () => {
  it("carries exactly the envelope fields the shared contract declares", async () => {
    const document = await buildRequestDocument(PRINCIPAL, "capture.list", { page_size: 25 });
    expect(Object.keys(document).sort()).toEqual(
      [...contract.envelopeFields, contract.payloadKey].sort(),
    );
  });

  it("never carries the capability, which the path routes on", async () => {
    const document = await buildRequestDocument(PRINCIPAL, "capture.list", {});
    expect(document).not.toHaveProperty("capability");
  });

  it("states the purpose the domain permits for that capability", async () => {
    const document = await buildRequestDocument(PRINCIPAL, "review.decide", {
      review_case_id: "rvw_aaaaaaaa11111111",
      expected_review_version: 0,
      disposition: "accept",
    });
    expect(document.purpose).toBe(contract.capabilities["review.decide"].purpose);
  });

  it("drops undefined payload entries rather than sending them as null", async () => {
    const document = await buildRequestDocument(PRINCIPAL, "capture.list", {
      page_size: undefined,
    });
    expect(document[contract.payloadKey]).toEqual({});
  });

  it("refuses a payload that carries a caller-supplied identity field", async () => {
    await expect(
      buildRequestDocument(PRINCIPAL, "capture.create", {
        text: "x",
        idempotency_key: "k",
        principal_id: "prn_ffffffffffffffffffffffffffffffff",
      }),
    ).rejects.toThrow(/caller-supplied identity field/);
  });
});

describe("the correlation principal identifier", () => {
  it("is a valid opaque principal identifier", async () => {
    expect(await correlationPrincipalId(PRINCIPAL)).toMatch(/^prn_[0-9a-f]{32}$/);
  });

  it("is derived from the session and is stable for it", async () => {
    expect(await correlationPrincipalId(PRINCIPAL)).toBe(await correlationPrincipalId(PRINCIPAL));
  });

  it("differs for a different identity", async () => {
    expect(await correlationPrincipalId(PRINCIPAL)).not.toBe(await correlationPrincipalId(OTHER));
  });

  it("does not depend on the mutable observations", async () => {
    const renamed = { ...PRINCIPAL, upn: "someone.else@moss.example", displayName: "Renamed" };
    expect(await correlationPrincipalId(renamed)).toBe(await correlationPrincipalId(PRINCIPAL));
  });
});

describe("credentials", () => {
  it("sends no Authorization header in local_operator mode", async () => {
    const { calls } = stubGateway({ result: {}, disclosure: DISCLOSURE });
    await callGateway(PRINCIPAL, "capabilities.get");
    const headers = calls[0].init.headers as Record<string, string>;
    expect(Object.keys(headers).map((k) => k.toLowerCase())).not.toContain("authorization");
  });

  it("refuses in entra mode rather than fabricating or omitting a token", async () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
    const { fetchStub } = stubGateway({ result: {}, disclosure: DISCLOSURE });
    const outcome = await callGateway(PRINCIPAL, "capabilities.get");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error.code).toBe("no_forwardable_credential");
      expect(outcome.error.errorClass).toBe("unavailable");
    }
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("refuses when the gateway address is unset, and does not serve fixtures instead", async () => {
    vi.stubEnv("MYPA_GATEWAY_URL", "");
    const { fetchStub } = stubGateway({ result: {}, disclosure: DISCLOSURE });
    const outcome = await callGateway(PRINCIPAL, "capabilities.get");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.error.code).toBe("gateway_not_configured");
    expect(fetchStub).not.toHaveBeenCalled();
  });
});

describe("the wire", () => {
  it("posts to /v1/{capability} with a bounded timeout", async () => {
    const { calls } = stubGateway({ result: { a: 1 }, disclosure: DISCLOSURE });
    const outcome = await callGateway(PRINCIPAL, "capture.list", { page_size: 5 });
    expect(calls[0].url).toBe("http://127.0.0.1:8000/v1/capture.list");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.signal).toBeInstanceOf(AbortSignal);
    expect(GATEWAY_TIMEOUT_MS).toBeGreaterThan(0);
    expect(outcome.ok).toBe(true);
  });

  it("maps an application error envelope onto the typed web vocabulary", async () => {
    stubGateway(
      { error: { code: "not_found", message: "no such thing", correlation_id: "corr_x" } },
      404,
    );
    const outcome = await callGateway(PRINCIPAL, "capture.list");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error.errorClass).toBe("not_found");
      expect(outcome.status).toBe(404);
    }
  });

  it("maps a bare problem detail, which has no envelope around it", async () => {
    stubGateway({ code: "denied", message: "refused", correlation_id: "corr_x" }, 401);
    const outcome = await callGateway(PRINCIPAL, "capture.list");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.error.errorClass).toBe("authorization");
  });

  it("reports an unreachable gateway as unavailable, not as empty data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("connect ECONNREFUSED");
      }),
    );
    const outcome = await callGateway(PRINCIPAL, "capture.list");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error.errorClass).toBe("unavailable");
      expect(outcome.error.code).toBe("gateway_unreachable");
      // The configured address is not echoed back to a caller.
      expect(JSON.stringify(outcome.error)).not.toContain("127.0.0.1");
    }
  });

  it("refuses a success that carries no disclosure, which the contract forbids", async () => {
    stubGateway({ result: { a: 1 } });
    const outcome = await callGateway(PRINCIPAL, "capture.list");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.error.code).toBe("gateway_response_uncontracted");
  });
});

describe("the disclosure a backend answer carries", () => {
  it("is never synthetic, whatever the gateway said", () => {
    const disclosure = backendDisclosure("scope", DISCLOSURE);
    expect(disclosure.coverage).not.toBe("synthetic");
    expect(disclosure.authority).not.toBe("synthetic_fixture");
    expect(disclosure.coverage).toBe("complete");
    expect(disclosure.authority).toBe("accepted");
    expect(disclosure.freshnessAt).toBe("2026-08-09T12:00:00Z");
  });

  it("reports partial and truncated states rather than flattening them", () => {
    const partial = backendDisclosure("scope", {
      ...DISCLOSURE,
      coverage: { state: "partially_processed" },
      truncation: { is_truncated: true },
      partial_result: true,
      limitations: ["listing_has_no_continuation"],
    });
    expect(partial.coverage).toBe("partial");
    expect(partial.truncated).toBe(true);
    expect(partial.limitations).toContain("listing_has_no_continuation");
  });

  it("reports an unavailable coverage state as unavailable", () => {
    const unavailable = backendDisclosure("scope", {
      ...DISCLOSURE,
      coverage: { state: "unavailable" },
      partial_result: true,
    });
    expect(unavailable.coverage).toBe("unavailable");
  });

  it("states the local-operator boundary rather than implying session scoping", () => {
    expect(transportLimitations()).toContain(LOCAL_OPERATOR_LIMITATION);
  });
});

/**
 * The server-only rule, held structurally.
 *
 * A client component that imported this module would either ship the backend
 * address to a browser or run where the session registry does not exist, and
 * neither failure announces itself. Edge middleware is checked separately for
 * the same reason `principal.ts` exists: middleware cannot reach Node-only state.
 */
describe("the transport stays on the server", () => {
  const SRC = join(process.cwd(), "src");

  function sources(directory: string): string[] {
    return readdirSync(directory).flatMap((entry) => {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) return sources(path);
      return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
    });
  }

  it("is imported by no client component and by no middleware", () => {
    const offenders = sources(SRC).filter((path) => {
      const text = readFileSync(path, "utf8");
      const imports = /from "@\/lib\/api\/gateway"/.test(text);
      if (!imports) return false;
      return /^\s*["']use client["']/m.test(text) || path.endsWith("middleware.ts");
    });
    expect(offenders).toEqual([]);
  });

  it("refuses outright when a browser global is present", async () => {
    // The file runs under the node environment, so `window` is absent and the
    // guard is unexercised by every other test here. Planting one is what makes
    // the refusal a measured behaviour rather than an unreached branch.
    vi.stubGlobal("window", {});
    await expect(callGateway(PRINCIPAL, "capture.list")).rejects.toThrow(
      GatewayIsServerOnlyError,
    );
  });

  it("found the modules that do import it, so the rule is not describing nothing", () => {
    const importers = sources(SRC).filter((path) =>
      /from "@\/lib\/api\/gateway"/.test(readFileSync(path, "utf8")),
    );
    expect(importers.length).toBeGreaterThan(0);
    expect(importers.every((path) => path.includes(join("app", "api")) || path.includes(join("lib", "api")))).toBe(true);
  });
});
