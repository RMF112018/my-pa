// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as signInRoute } from "@/app/api/session/route";
import { GET as notebooks } from "@/app/api/goodnotes/notebooks/route";
import { GET as pages } from "@/app/api/goodnotes/pages/route";
import { GET as runs } from "@/app/api/goodnotes/runs/route";
import { GET as item } from "@/app/api/goodnotes/item/route";
import { GET as raster } from "@/app/api/goodnotes/raster/route";
import { POST as correct } from "@/app/api/goodnotes/correct/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resetSessionRegistry } from "@/lib/auth/session-registry";
import { withSessionServiceFetch } from "@/lib/auth/session-service-fetch-stub";

const ORIGIN = "http://localhost:3000";
const NOTEBOOK_ID = "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa";
const RUN_ID = "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa";
const PAGE_VERSION_ID = "gnver_aaaaaaaaaaaaaaaaaaaaaaaa";
const DIGEST = "a".repeat(64);
const CONTENT_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR42mP4DwABAQEAHLCMmQAAAABJRU5ErkJggg==";
const NOTEBOOK = {
  notebook_id: NOTEBOOK_ID,
  title: "Synthetic notebook",
  updated_at: "2026-08-09T12:00:00.000Z",
  page_count: 2,
  liveness: "unknown",
};
const PAGE = {
  logical_page_id: "gnlp_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: PAGE_VERSION_ID,
  run_id: RUN_ID,
  content_sha256: DIGEST,
  is_latest: true,
  updated_at: "2026-08-09T12:00:00.000Z",
};
const RUN = {
  run_id: RUN_ID,
  state: "succeeded",
  failure_class: null,
  started_at: "2026-08-09T12:00:00.000Z",
  completed_at: "2026-08-09T12:01:00.000Z",
};
const READ = {
  run_id: RUN_ID,
  page_version_id: PAGE_VERSION_ID,
  content_sha256: DIGEST,
  exact_render_sha256: "b".repeat(64),
  raster_digest: "c".repeat(64),
  media_type: "image/png",
  renderer_name: "synthetic",
  renderer_version: "1",
  render_profile_version: "v1",
  interpretation: { authority: "source", items: [] },
  provenance: { run_id: RUN_ID, page_version_id: PAGE_VERSION_ID, content_sha256: DIGEST },
  processing: { run_status: null, failure_class: null },
};
const CONTENT = {
  run_id: RUN_ID,
  page_version_id: PAGE_VERSION_ID,
  content_sha256: DIGEST,
  exact_render_sha256: "b".repeat(64),
  media_type: "image/png",
  byte_length: 67,
  digest: "c".repeat(64),
  content_base64: CONTENT_PNG_BASE64,
  renderer_name: "synthetic",
  renderer_version: "1",
  render_profile_version: "v1",
};
const CORRECT = {
  occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
  revision_id: "gnrev_aaaaaaaaaaaaaaaaaaaaaaaa",
  prior_revision_id: "gnrev_bbbbbbbbbbbbbbbbbbbbbbbb",
  replayed: false,
  disposition: "canonical_revision_appended",
};
const DISCLOSURE = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
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

function get(session: string, path: string) {
  const value = new NextRequest(`${ORIGIN}${path}`);
  value.cookies.set(SESSION_COOKIE_NAME, session);
  return value;
}

function post(session: string, body: unknown, origin: string | null = ORIGIN) {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (origin !== null) headers.origin = origin;
  const request = new NextRequest(`${ORIGIN}/api/goodnotes/correct`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  request.cookies.set(SESSION_COOKIE_NAME, session);
  return request;
}

function stubGateway(impl?: (url: string | URL | Request, init?: RequestInit) => unknown) {
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

describe("GoodNotes BFF lists", () => {
  it("lists notebooks through goodnotes.notebooks.list", async () => {
    const gateway = stubGateway(async () => gatewayOk({ notebooks: [NOTEBOOK] }));
    const response = await notebooks(get(await cookie(), "/api/goodnotes/notebooks"));
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const body = await response.json();
    expect(body.notebooks).toEqual([NOTEBOOK]);
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/goodnotes.notebooks.list");
    const sent = JSON.parse(String(gateway.mock.calls[0]?.[1]?.body ?? "{}")) as {
      payload?: Record<string, unknown>;
    };
    expect(sent.payload).not.toHaveProperty("principal_id");
  });

  it("requires notebookId for pages", async () => {
    const gateway = stubGateway();
    const response = await pages(get(await cookie(), "/api/goodnotes/pages"));
    expect(response.status).toBe(400);
    expect(gateway).not.toHaveBeenCalled();
  });

  it("lists pages through goodnotes.pages.list", async () => {
    const gateway = stubGateway(async () => gatewayOk({ pages: [PAGE] }));
    const response = await pages(
      get(await cookie(), `/api/goodnotes/pages?notebookId=${NOTEBOOK_ID}`),
    );
    expect(response.status).toBe(200);
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/goodnotes.pages.list");
    const sent = JSON.parse(String(gateway.mock.calls[0]?.[1]?.body ?? "{}")) as {
      payload?: Record<string, unknown>;
    };
    expect(sent.payload).toMatchObject({ notebook_id: NOTEBOOK_ID });
  });

  it("lists runs through goodnotes.runs.list", async () => {
    const gateway = stubGateway(async () => gatewayOk({ runs: [RUN] }));
    const response = await runs(get(await cookie(), "/api/goodnotes/runs"));
    expect(response.status).toBe(200);
    expect((await response.json()).runs).toEqual([RUN]);
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/goodnotes.runs.list");
  });

  it("fails closed when notebooks is omitted", async () => {
    stubGateway(async () => gatewayOk({ leaked: "must-not-dump" }));
    const response = await notebooks(get(await cookie(), "/api/goodnotes/notebooks"));
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(JSON.stringify(body)).not.toContain("must-not-dump");
  });

  it("answers not_implemented under the synthetic provider", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const gateway = stubGateway();
    const response = await notebooks(get(await cookie(), "/api/goodnotes/notebooks"));
    expect(response.status).toBe(501);
    expect(await response.json()).toMatchObject({
      state: "not_implemented",
      error: { errorClass: "unavailable", code: "not_implemented" },
    });
    expect(gateway).not.toHaveBeenCalled();
  });
});

describe("GoodNotes BFF item", () => {
  it("requires runId and pageVersionId", async () => {
    const gateway = stubGateway();
    const response = await item(get(await cookie(), "/api/goodnotes/item"));
    expect(response.status).toBe(400);
    expect(gateway).not.toHaveBeenCalled();
  });

  it("reads through goodnotes.read", async () => {
    const gateway = stubGateway(async () => gatewayOk(READ));
    const response = await item(
      get(
        await cookie(),
        `/api/goodnotes/item?runId=${RUN_ID}&pageVersionId=${PAGE_VERSION_ID}&contentSha256=${DIGEST}`,
      ),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/goodnotes.read");
    const sent = JSON.parse(String(gateway.mock.calls[0]?.[1]?.body ?? "{}")) as {
      payload?: Record<string, unknown>;
    };
    expect(sent.payload).toMatchObject({
      run_id: RUN_ID,
      page_version_id: PAGE_VERSION_ID,
      content_sha256: DIGEST,
    });
    expect(sent.payload).not.toHaveProperty("principal_id");
  });
});

describe("GoodNotes BFF raster", () => {
  it("returns image/png bytes rather than JSON base64", async () => {
    const gateway = stubGateway(async () => gatewayOk(CONTENT));
    const response = await raster(
      get(
        await cookie(),
        `/api/goodnotes/raster?runId=${RUN_ID}&pageVersionId=${PAGE_VERSION_ID}&contentSha256=${DIGEST}`,
      ),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const bytes = Buffer.from(await response.arrayBuffer());
    expect(bytes.equals(Buffer.from(CONTENT_PNG_BASE64, "base64"))).toBe(true);
    const asText = bytes.toString("utf8");
    expect(asText).not.toContain("content_base64");
    expect(asText).not.toContain("/secret");
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/goodnotes.content");
  });

  it("fails closed on malformed raster success without leaking a path", async () => {
    stubGateway(async () => gatewayOk({ ...CONTENT, media_type: "application/pdf", path: "/secret.png" }));
    const response = await raster(
      get(
        await cookie(),
        `/api/goodnotes/raster?runId=${RUN_ID}&pageVersionId=${PAGE_VERSION_ID}&contentSha256=${DIGEST}`,
      ),
    );
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body.error.code).toBe("upstream_contract_invalid");
    expect(JSON.stringify(body)).not.toContain("/secret.png");
    expect(JSON.stringify(body)).not.toContain("content_base64");
  });

  it("requires the three raster identifiers", async () => {
    const gateway = stubGateway();
    const response = await raster(get(await cookie(), `/api/goodnotes/raster?runId=${RUN_ID}`));
    expect(response.status).toBe(400);
    expect(gateway).not.toHaveBeenCalled();
  });
});

describe("GoodNotes BFF correct", () => {
  it("refuses a cross-site POST before reading the principal", async () => {
    const gateway = stubGateway();
    const response = await correct(
      post(await cookie(), { occurrenceId: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb", transcription: "x" }, null),
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: { errorClass: "authorization", code: "cross_site_request" },
    });
    expect(gateway).not.toHaveBeenCalled();
  });

  it("invokes goodnotes.correct after Origin then principal", async () => {
    const gateway = stubGateway(async () => gatewayOk(CORRECT));
    const response = await correct(
      post(await cookie(), {
        occurrenceId: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
        transcription: "synthetic correction",
      }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(String(gateway.mock.calls[0]?.[0])).toContain("/v1/goodnotes.correct");
    const sent = JSON.parse(String(gateway.mock.calls[0]?.[1]?.body ?? "{}")) as {
      payload?: Record<string, unknown>;
    };
    expect(sent.payload).toEqual({
      occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
      transcription: "synthetic correction",
    });
    expect(sent.payload).not.toHaveProperty("principal_id");
    expect((await response.json()).disposition).toBe("canonical_revision_appended");
  });

  it("answers not_implemented under the synthetic provider", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const gateway = stubGateway();
    const response = await correct(
      post(await cookie(), {
        occurrenceId: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
        transcription: "synthetic correction",
      }),
    );
    expect(response.status).toBe(501);
    expect((await response.json()).error.code).toBe("not_implemented");
    expect(gateway).not.toHaveBeenCalled();
  });
});
