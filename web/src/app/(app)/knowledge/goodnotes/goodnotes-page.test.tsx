/**
 * GoodNotes Knowledge page answers, rendered against a stubbed gateway socket.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
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

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ name: "mypa_session", value: "stub" }) }),
}));
vi.mock("@/lib/auth/principal", () => ({
  resolveSessionPrincipal: async () => PRINCIPAL,
}));
vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next/navigation")>();
  return {
    ...actual,
    useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  };
});

import { GoodNotesPage } from "./goodnotes-page";

const DIGEST = "a".repeat(64);
const NOTEBOOK_ID = "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa";
const RUN_ID = "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa";
const PAGE_VERSION_ID = "gnver_aaaaaaaaaaaaaaaaaaaaaaaa";
const NAS_PATH = "/nas/secret/notebooks/private.goodnotes";

const NOTEBOOK = {
  notebook_id: NOTEBOOK_ID,
  title: "Synthetic notebook",
  updated_at: "2026-08-09T12:00:00.000Z",
  page_count: 2,
  liveness: "unknown",
  path: NAS_PATH,
};

const PAGE = {
  logical_page_id: "gnlp_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: PAGE_VERSION_ID,
  run_id: RUN_ID,
  content_sha256: DIGEST,
  is_latest: true,
  updated_at: "2026-08-09T12:00:00.000Z",
  path: NAS_PATH,
};

const RUN = {
  run_id: RUN_ID,
  state: "succeeded",
  failure_class: null,
  started_at: "2026-08-09T12:00:00.000Z",
  completed_at: "2026-08-09T12:01:00.000Z",
  path: NAS_PATH,
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
  interpretation: {
    authority: "interpretation",
    items: [
      {
        occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
        transcription: "synthetic note",
      },
    ],
  },
  provenance: { run_id: RUN_ID, page_version_id: PAGE_VERSION_ID, content_sha256: DIGEST },
  processing: { run_status: null, failure_class: null },
  path: NAS_PATH,
};

function whole(overrides: Record<string, unknown> = {}) {
  return {
    coverage: { state: "not_enrolled" },
    freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
    trust: { level: "source_original", basis: ["user_authored_record"] },
    truncation: { is_truncated: false },
    limitations: [],
    partial_result: false,
    ...overrides,
  };
}

function notSearched() {
  return whole({ coverage: { state: "unavailable" }, limitations: ["the scope was not searched"] });
}

function answerByCapability(map: Record<string, unknown>, disclosure: unknown = whole()) {
  const spy = vi.fn(async (url: unknown) => {
    const capability = String(url).match(/\/v1\/([^/?#]+)/)?.[1] ?? "";
    const result = Object.prototype.hasOwnProperty.call(map, capability) ? map[capability] : {};
    return new Response(JSON.stringify({ result, disclosure }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

async function renderServerPage(page: () => Promise<React.ReactNode>) {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "window");
  Reflect.deleteProperty(globalThis, "window");
  let tree: React.ReactNode;
  try {
    tree = await page();
  } finally {
    if (saved) Object.defineProperty(globalThis, "window", saved);
  }
  return render(tree);
}

const NO_PARAMS = Promise.resolve({});

beforeEach(() => {
  vi.stubEnv("MYPA_GATEWAY_URL", "http://gateway.invalid");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("GoodNotes synthetic serving", () => {
  it("says not_implemented rather than inventing notebooks", async () => {
    const spy = vi.fn(async () => {
      throw new Error("gateway must not be called in synthetic serving");
    });
    vi.stubGlobal("fetch", spy);
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await renderServerPage(() => GoodNotesPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("goodnotes-synthetic")).toHaveAttribute(
      "data-state",
      "not_implemented",
    );
    expect(spy).not.toHaveBeenCalled();
    expect(screen.queryByTestId("goodnotes-notebooks")).toBeNull();
  });
});

describe("GoodNotes catalog", () => {
  it("lists notebooks a successful catalog returned and does not leak paths", async () => {
    answerByCapability({ "goodnotes.notebooks.list": { notebooks: [NOTEBOOK] } });
    await renderServerPage(() => GoodNotesPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("goodnotes-notebooks")).toBeTruthy();
    expect(screen.getByText("Synthetic notebook")).toBeTruthy();
    expect(screen.getByTestId("goodnotes-notebook-liveness").textContent).toBe("unknown");
    expect(document.body.textContent).not.toContain(NAS_PATH);
    expect(screen.queryByTestId("goodnotes-notebooks-empty")).toBeNull();
  });

  it("says empty only when the catalog was actually read", async () => {
    answerByCapability({ "goodnotes.notebooks.list": { notebooks: [] } });
    await renderServerPage(() => GoodNotesPage({ searchParams: NO_PARAMS }));
    const empty = screen.getByTestId("goodnotes-notebooks-empty");
    expect(empty).toHaveAttribute("data-state", "empty");
    expect(empty.textContent).not.toMatch(/nas/i);
    expect(screen.queryByTestId("goodnotes-notebooks-unavailable")).toBeNull();
  });

  it("does NOT say empty when the backend answered that it did not search", async () => {
    answerByCapability({ "goodnotes.notebooks.list": { notebooks: [] } }, notSearched());
    await renderServerPage(() => GoodNotesPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("goodnotes-notebooks-unavailable")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
    expect(screen.queryByTestId("goodnotes-notebooks-empty")).toBeNull();
  });

  it("lists pages and runs for a selected notebook", async () => {
    const spy = answerByCapability({
      "goodnotes.notebooks.list": { notebooks: [NOTEBOOK] },
      "goodnotes.pages.list": { pages: [PAGE] },
      "goodnotes.runs.list": { runs: [RUN] },
    });
    await renderServerPage(() =>
      GoodNotesPage({ searchParams: Promise.resolve({ notebookId: NOTEBOOK_ID }) }),
    );
    expect(screen.getByTestId("goodnotes-pages")).toBeTruthy();
    expect(screen.getByTestId("goodnotes-runs")).toBeTruthy();
    const urls = spy.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.includes("/v1/goodnotes.pages.list"))).toBe(true);
    expect(urls.some((url) => url.includes("/v1/goodnotes.runs.list"))).toBe(true);
    expect(document.body.textContent).not.toContain(NAS_PATH);
  });
});

describe("GoodNotes evidence deep-links", () => {
  it("fails closed when runId is present without pageVersionId and does not guess", async () => {
    const spy = vi.fn(async () => {
      throw new Error("gateway must not be called without both read identifiers");
    });
    vi.stubGlobal("fetch", spy);
    await renderServerPage(() =>
      GoodNotesPage({ searchParams: Promise.resolve({ runId: RUN_ID }) }),
    );
    expect(spy).not.toHaveBeenCalled();
    const state = screen.getByTestId("goodnotes-read-missing-ids");
    expect(state).toHaveAttribute("data-state", "unavailable");
    expect(state.textContent).toMatch(/was not guessed/i);
    expect(screen.queryByTestId("goodnotes-evidence")).toBeNull();
    expect(screen.queryByTestId("goodnotes-notebooks")).toBeNull();
  });

  it("fails closed when pageVersionId is present without runId", async () => {
    const spy = vi.fn(async () => {
      throw new Error("gateway must not be called without both read identifiers");
    });
    vi.stubGlobal("fetch", spy);
    await renderServerPage(() =>
      GoodNotesPage({ searchParams: Promise.resolve({ pageVersionId: PAGE_VERSION_ID }) }),
    );
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByTestId("goodnotes-read-missing-ids")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
  });

  it("reads evidence when both ids are present and uses the raster contract", async () => {
    const spy = answerByCapability({ "goodnotes.read": READ });
    await renderServerPage(() =>
      GoodNotesPage({
        searchParams: Promise.resolve({
          runId: RUN_ID,
          pageVersionId: PAGE_VERSION_ID,
          contentSha256: DIGEST,
        }),
      }),
    );
    expect(String(spy.mock.calls[0]?.[0])).toContain("/v1/goodnotes.read");
    expect(String(spy.mock.calls[0]?.[0])).not.toContain("/v1/goodnotes.notebooks.list");
    const img = screen.getByRole("img");
    expect(img.getAttribute("src")).toBe(
      `/api/goodnotes/raster?runId=${RUN_ID}&pageVersionId=${PAGE_VERSION_ID}&contentSha256=${DIGEST}`,
    );
    expect(img.getAttribute("alt")).toMatch(/source raster/i);
    expect(img.getAttribute("alt")).not.toMatch(/synthetic note/i);
    expect(screen.getByTestId("goodnotes-transcription").textContent).toBe("synthetic note");
    expect(screen.getByTestId("goodnotes-evidence-tablist")).toHaveAttribute("role", "tablist");
    expect(screen.getByTestId("goodnotes-evidence-split").className).toContain("md:grid-cols-2");
    expect(document.body.textContent).not.toContain(NAS_PATH);
  });

  it("says the record carries no transcription when the read sent none", async () => {
    answerByCapability({
      "goodnotes.read": {
        ...READ,
        interpretation: { authority: "source", items: [{ occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb" }] },
      },
    });
    await renderServerPage(() =>
      GoodNotesPage({
        searchParams: Promise.resolve({ runId: RUN_ID, pageVersionId: PAGE_VERSION_ID }),
      }),
    );
    expect(screen.getByTestId("goodnotes-no-transcription").textContent).toMatch(
      /carries no transcription/i,
    );
    expect(screen.queryByTestId("goodnotes-transcription")).toBeNull();
  });
});
