/**
 * The wired destinations, rendered against a stubbed gateway socket.
 *
 * **The subject is the page, not the component.** `surface-state.test.tsx`
 * proves the four state cards differ from one another; this file proves each
 * page actually *reaches* the right one for the right backend answer — which is
 * the half that can regress silently, because a page that always rendered the
 * empty card would pass every component test ever written about that card.
 *
 * The stub is placed at `fetch`, the same seam `app/api/routes.test.ts` uses, so
 * everything between the page and the socket is the real thing: the real
 * `callGateway`, the real envelope construction, the real disclosure mapping,
 * the real `surfaceAnswer` classification. What is faked is one HTTP response.
 *
 * At least three answers are asserted for each page and they are three different
 * HTTP facts, not three shapes of the same one:
 *
 * 1. a `200` carrying rows -> records;
 * 2. a `200` carrying **no** rows and a complete coverage -> empty;
 * 3. a `200` carrying no rows and `coverage.state: "unavailable"` -> **not**
 *    empty. This is the case a naive implementation gets wrong, because the
 *    payload is byte-identical to case 2 apart from one field nobody has to
 *    read. `INV-PKL-007` is exactly this distinction and the reason
 *    `surfaceAnswer` refuses to count rows before it has read coverage.
 *
 * A transport failure is asserted too, because "the socket never answered" and
 * "the backend said it could not search" are both unavailable but arrive by
 * completely different paths through `callGateway`.
 *
 * Situations adds a fifth: a `200` carrying no rows whose disclosure says the
 * answer was **partial**. That is not an empty record either — the rows may
 * exist and simply not have been returned — and the board has two halves, so a
 * whole half's emptiness must still be stated while a partial half's must not.
 * System is here for a related reason: a successful response that omitted its
 * `readiness` block must not be rendered as a readiness of zero.
 *
 * Every identifier below is synthetic and well-formed under the domain's own
 * opaque-identifier patterns. No real capture, no real person, no real text.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";
import type { PulseItem } from "@/lib/api/decode/capabilities/continuity.pulse";

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "11111111-2222-3333-4444-555555555555:aaaa0001-0000-0000-0000-000000000001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

// The session is resolved server-side from a signed cookie. These two mocks
// stand in for the cookie jar and the signature check *only*; nothing here
// supplies an identity to the page through a payload, and the pages under test
// have no parameter one could arrive through.
/**
 * The diagnostics preference cookie, as this browser would carry it.
 *
 * `undefined` is a browser that has never turned diagnostics on, which is the
 * product default and therefore the default here. Tests that exercise the ON
 * presentation set a real serialized value, bound to `PRINCIPAL`, so the page
 * is gated by the genuine parser rather than by a stubbed boolean.
 */
const { diagnosticsCookie } = vi.hoisted(() => ({
  diagnosticsCookie: { value: undefined as string | undefined },
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => {
      if (name === "my-pa-diagnostics") {
        return diagnosticsCookie.value === undefined
          ? undefined
          : { name, value: diagnosticsCookie.value };
      }
      return { name: "mypa_session", value: "stub" };
    },
  }),
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

import LibraryPage from "@/app/(app)/library/page";
import KnowledgePage from "@/app/(app)/knowledge/page";
import PeoplePage from "@/app/(app)/people/page";
import PeopleEntityPage from "@/app/(app)/people/[entityId]/page";
import ReviewPage from "@/app/(app)/review/page";
import TodayPage from "@/app/(app)/today/page";
import SituationsPage from "@/app/(app)/situations/page";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { TODAY_EMPTY_COPY } from "@/components/pulse/today-pulse-surface";
import SystemPage from "@/app/(app)/system/page";
import {
  diagnosticsPreferenceValue,
  diagnosticsPrincipalBinding,
} from "@/lib/diagnostics/preference";
import RelationshipPage from "@/app/(app)/relationships/[personId]/page";

/** A disclosure whose coverage says the answer is whole. */
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

/** The same envelope, with the one field that means "this was not searched". */
function notSearched() {
  return whole({ coverage: { state: "unavailable" }, limitations: ["the scope was not searched"] });
}

/** The same envelope, with the backend's own admission that it is partial. */
function partial() {
  return whole({ partial_result: true, limitations: ["one scope was skipped"] });
}

function answerWith(result: unknown, disclosure: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ result, disclosure }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
}

function answerByCapability(map: Record<string, unknown>, disclosure: unknown = whole()) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const capability = String(url).match(/\/v1\/([^/?#]+)/)?.[1] ?? "";
      const result = Object.prototype.hasOwnProperty.call(map, capability) ? map[capability] : {};
      return new Response(JSON.stringify({ result, disclosure }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

/**
 * Mock /api/pulse with the BFF JSON shape.
 *
 * The route answers `todayRows`: one row per canonical Today Task, carrying the
 * derivation's own row under `attention` where there is one, then the non-Task
 * rows the derivation raised. This helper composes the same thing from a Task
 * list and a Pulse list so a test can state both halves separately. The route's
 * own composition is proven against the route in `routes.test.ts`; what is
 * proven here is what the page then says about it.
 */
function bffDisclosure(disclosure: unknown) {
  const raw = (disclosure ?? {}) as {
    coverage?: { state?: string } | string;
    freshness?: { observed_at?: string };
    limitations?: readonly string[];
    truncation?: { is_truncated?: boolean };
    partial_result?: boolean;
  };
  const state = typeof raw.coverage === "string" ? raw.coverage : raw.coverage?.state;
  const truncated = raw.truncation?.is_truncated === true;
  const coverage =
    state === "unavailable"
      ? "unavailable"
      : raw.partial_result || truncated || state === "partially_processed"
        ? "partial"
        : "complete";
  return {
    scope: "continuity.pulse",
    coverage,
    freshnessAt: raw.freshness?.observed_at ?? "2026-01-01T00:00:00Z",
    authority: "accepted_record",
    limitations: raw.limitations ?? [],
    truncated,
  };
}

/** A canonical Today Task as `tasks.list?work_view=today` names one here. */
interface CanonicalTask {
  readonly taskId: string;
  readonly title: string;
}

function toBackendItem(item: PulseItem) {
  return {
    pulseId: item.pulse_id,
    itemType: item.item_type,
    itemRef: item.item_ref,
    reasonCode: item.reason_code,
    reason: item.reason,
    basisRefs: item.basis_refs,
    consequence: item.consequence,
    nextStep: item.next_step,
    attentionRank: item.attention_rank,
    generatedAt: item.generated_at,
    ...(item.subject_title !== undefined ? { subjectTitle: item.subject_title } : {}),
  };
}

function answerPulseWith(
  pulseItems: readonly PulseItem[] | undefined,
  disclosure: unknown = whole(),
  canonicalTasks: readonly CanonicalTask[] = [],
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const urlStr = String(url);
      // /api/pulse requests get the new BFF shape
      if (urlStr.includes("/api/pulse")) {
        if (pulseItems === undefined) {
          // No `todayRows` at all: a read that did not happen, not a quiet day.
          return new Response(
            JSON.stringify({
              shape: "backend",
              disclosure: bffDisclosure(disclosure),
              completeness: "full",
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }
        const backendItems = pulseItems.map(toBackendItem);
        const attentionByTaskId = new Map(
          backendItems.filter((item) => item.itemType === "task").map((item) => [item.itemRef, item]),
        );
        const todayRows = [
          ...canonicalTasks.map((task) => {
            const attention = attentionByTaskId.get(task.taskId);
            return {
              kind: "task",
              taskId: task.taskId,
              title: task.title,
              ...(attention ? { attention } : {}),
            };
          }),
          ...backendItems
            .filter((item) => item.itemType !== "task")
            .map((item) => ({ kind: "attention", item })),
        ];
        const envelope = bffDisclosure(disclosure);
        return new Response(
          JSON.stringify({
            shape: "backend",
            todayRows,
            disclosure: envelope,
            completeness: envelope.coverage === "complete" ? "full" : "partial",
          }),
          {
            status: 200,
            headers: { "content-type": "application/json" },
          },
        );
      }
      // Other requests still get the gateway envelope shape
      return new Response(JSON.stringify({ result: {}, disclosure }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

/**
 * Await a server component the way a server would, then render what it
 * produced.
 *
 * `lib/api/gateway` refuses to run where `window` exists, and that refusal is
 * load-bearing — it is what stops a backend address and a server-side session
 * lookup from being pulled into a client bundle. jsdom defines `window`, so a
 * naive `render(await Page())` would either fail or force that guard to be
 * softened for the convenience of a test, which is the wrong trade every time.
 *
 * So the guard is left exactly as it is and the *test* supplies the right
 * context: `window` is removed for the duration of the page's own await — the
 * part that talks to the gateway — and restored before React touches the DOM.
 * The page therefore runs under the same condition it runs under in production,
 * and the tree it returned is rendered under the condition React needs.
 */
async function renderServerPage(page: () => Promise<React.ReactNode>) {
  const tree = await serverTreeOf(page);
  return render(tree);
}

async function serverTreeOf(page: () => Promise<React.ReactNode>) {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "window");
  Reflect.deleteProperty(globalThis, "window");
  try {
    return await page();
  } finally {
    if (saved) Object.defineProperty(globalThis, "window", saved);
  }
}

/**
 * Today's server half hands its one classified answer to a client surface, and
 * that surface binds the session-scoped Task runtime the shell provides. The
 * provider is harness, not subject: nothing below asserts anything about it, and
 * the page still runs under exactly the server conditions above.
 *
 * The surface revalidates through `/api/pulse` once it mounts. Under this file's
 * stub that read cannot succeed — the socket answers with a gateway envelope,
 * not a route answer — and the assertions below are precisely that a refresh
 * which does not succeed changes none of the four answers the server reached.
 */
async function renderTodayPage() {
  const tree = await serverTreeOf(() => TodayPage());
  const view = render(
    <TaskRuntimeProvider principalId={PRINCIPAL.principalId} sessionEpoch="surfaces-test">
      {tree}
    </TaskRuntimeProvider>,
  );
  await waitFor(() => {
    expect(
      screen.queryByTestId("today-empty") ||
        screen.queryByTestId("today-unavailable") ||
        screen.queryByTestId("today-degraded-empty") ||
        screen.queryByTestId("pulse-reason") ||
        screen.queryByTestId("today-task-card") ||
        screen.queryByTestId("backend-pulse-list"),
    ).toBeTruthy();
  });
  return view;
}

function socketFails() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("fetch failed");
    }),
  );
}

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

const CAPTURE = {
  capture_id: "cap_aaaa0001aaaa0001aaaa0001",
  owner_principal_id: "prn_aaaa0001aaaa0001aaaa0001",
  created_at: "2026-01-01T00:00:00Z",
  version_count: 1,
  latest_version_id: "capver_aaaa0001aaaa0001aaaa0001",
  latest_version_number: 1,
  latest_recorded_at: "2026-01-01T00:00:00Z",
  project_id: null,
};

const REVIEW_CASE = {
  review_case_id: "rvc_aaaa0001aaaa0001aaaa0001",
  proposal_id: "prop_aaaa0001aaaa0001aaaa0001",
  subject_kind: "capture_proposal",
  capture_id: CAPTURE.capture_id,
  version_id: CAPTURE.latest_version_id,
  proposal_type: "commitment",
  proposal_state: "proposed",
  risk_class: "high",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 3,
  latest_disposition: null,
};

const GOODNOTES_SEMANTIC_CASE = {
  review_case_id: "rvc_cccc0001cccc0001cccc0001",
  proposal_id: "prop_cccc0001cccc0001cccc0001",
  proposal_state: "proposed",
  risk_class: "moderate",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 1,
  latest_disposition: null,
  subject_kind: "goodnotes_semantic",
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
};

const GOODNOTES_REGION_CASE = {
  review_case_id: "rvc_dddd0001dddd0001dddd0001",
  proposal_id: "prop_dddd0001dddd0001dddd0001",
  proposal_state: "needs_review",
  risk_class: "low",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 2,
  latest_disposition: null,
  subject_kind: "goodnotes_region",
  region_id: "gnreg_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
  confidence: 0.82,
};

const PULSE_ITEM = {
  pulse_id: "pls_aaaa0001aaaa0001aaaa0001",
  item_type: "commitment",
  item_ref: "cmt_aaaa0001aaaa0001aaaa0001",
  reason_code: "commitment_overdue",
  reason: "two days past its agreed moment",
  basis_refs: ["asr_aaaa0001aaaa0001aaaa0001"],
  consequence: null,
  next_step: null,
  attention_rank: 1,
  generated_at: "2026-01-01T00:00:00Z",
} satisfies PulseItem;

const PROJECT = {
  project_id: "prj_aaaa0001aaaa0001aaaa0001",
  name: "North slab pour",
  state: "active",
  description: null,
  participants: [],
  canonical_participations: [],
  opened_at: "2026-01-01T00:00:00Z",
  closed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  version: 1,
};

const NO_PARAMS = Promise.resolve({});

describe("Library reaches the record instead of asserting about it", () => {
  it("renders the stored captures a successful listing returned", async () => {
    answerWith({ captures: [CAPTURE] }, whole());
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("library-listing")).toBeTruthy();
    expect(screen.getByText(CAPTURE.capture_id)).toBeTruthy();
    // A listing carries no content, so none may appear.
    expect(screen.queryByTestId("state-empty")).toBeNull();
  });

  it("says the record is empty only when the record was actually read", async () => {
    answerWith({ captures: [] }, whole());
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    const empty = screen.getByTestId("library-empty");
    expect(empty).toHaveAttribute("data-state", "empty");
    expect(empty.textContent).toMatch(/read successfully/i);
  });

  it("does NOT say empty when the backend answered that it did not search", async () => {
    // Byte-identical payload to the empty case. Only the coverage differs.
    answerWith({ captures: [] }, notSearched());
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    const state = screen.getByTestId("library-unavailable");
    expect(state).toHaveAttribute("data-state", "unavailable");
    expect(state.getAttribute("role")).toBe("alert");
    expect(state.textContent).not.toMatch(/holds nothing/i);
    expect(screen.queryByTestId("library-empty")).toBeNull();
  });

  it("does NOT say empty when the socket never answered", async () => {
    socketFails();
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("library-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("library-empty")).toBeNull();
  });

  it("shows real rows under a stated banner when the answer is partial", async () => {
    answerWith({ captures: [CAPTURE] }, partial());
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("degraded-banner")).toBeTruthy();
    expect(screen.getByTestId("library-listing")).toBeTruthy();
    expect(screen.getByTestId("degraded-banner").textContent).toContain("one scope was skipped");
  });

  it("separates 'nothing matched' from 'the search did not run'", async () => {
    answerWith({ matches: [], searchable_versions: 0, stored_versions: 0 }, whole());
    const { unmount } = await renderServerPage(() => LibraryPage({ searchParams: Promise.resolve({ q: "slab" }) }));
    expect(screen.getByTestId("library-search-empty")).toHaveAttribute("data-state", "empty");
    unmount();

    answerWith({ matches: [], searchable_versions: 0, stored_versions: 0 }, notSearched());
    await renderServerPage(() => LibraryPage({ searchParams: Promise.resolve({ q: "slab" }) }));
    expect(screen.getByTestId("library-search-unavailable")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
  });

  it("does NOT say empty when the backend omitted the required captures array", async () => {
    answerWith({}, whole());
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("library-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("library-empty")).toBeNull();
  });

  it("offers no synthetic Library and says so rather than inventing one", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("library-synthetic")).toHaveAttribute("data-state", "not_implemented");
  });
});

const CAPTURE_VERSION = {
  capture_id: CAPTURE.capture_id,
  version_id: CAPTURE.latest_version_id,
  version_number: 1,
  supersedes_version_id: null,
  is_current: true,
  owner_principal_id: CAPTURE.owner_principal_id,
  project_id: null,
  classification: "synthetic_test",
  processing_policy: "local_only",
  content_sha256: "a".repeat(64),
  character_count: 22,
  text: "synthetic capture body",
  is_truncated: false,
  client_created_at: null,
  server_received_at: "2026-01-01T00:00:00Z",
  occurred_at: null,
  accepted_at: "2026-01-01T00:00:00Z",
  recorded_at: "2026-01-01T00:00:00Z",
};

const KNOWLEDGE_RECORD = {
  knowledge_id: "kn_aaaa0001aaaa0001aaaa0001",
  label: "text/plain",
  media_type: "text/plain",
  character_count: 12,
  metadata_only: false,
  is_truncated: false,
  provenance: {
    source_id: "src_aaaa0001aaaa0001aaaa0001",
    source_object_id: "sobj_aaaa0001aaaa0001aaaa0001",
    version_id: "ver_aaaa0001aaaa0001aaaa0001",
    extractor: "plain_text",
    extractor_version: "1",
    trust_level: "source_original",
    observed_at: "2026-01-01T00:00:00Z",
    processed_at: "2026-01-01T00:00:00Z",
  },
  text: "hello world",
};

const ENROLLMENT_ID = "enr_aaaa0001aaaa0001aaaa0001";

function recordedAnswer(result: unknown, disclosure: unknown = whole()) {
  const fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
    if (url == null) throw new Error("missing gateway url");
    void init;
    return new Response(JSON.stringify({ result, disclosure }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Library identity projections invoke the matching capability", () => {
  it("invokes capture.read for captureId and may show canonical text", async () => {
    const fetchMock = recordedAnswer(CAPTURE_VERSION);
    await renderServerPage(() =>
      LibraryPage({
        searchParams: Promise.resolve({
          captureId: CAPTURE.capture_id,
          versionId: CAPTURE.latest_version_id,
        }),
      }),
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/v1/capture.read");
    const body = JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit | undefined)?.body ?? "{}"));
    expect(body.payload).toEqual({
      capture_id: CAPTURE.capture_id,
      version_id: CAPTURE.latest_version_id,
    });
    expect(screen.getByTestId("library-capture-item")).toBeTruthy();
    expect(screen.getByTestId("library-capture-text").textContent).toBe("synthetic capture body");
    expect(screen.queryByTestId("library-listing")).toBeNull();
  });

  it("captureId beats q and does not search", async () => {
    const fetchMock = recordedAnswer(CAPTURE_VERSION);
    await renderServerPage(() =>
      LibraryPage({
        searchParams: Promise.resolve({ captureId: CAPTURE.capture_id, q: "slab" }),
      }),
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/v1/capture.read");
    expect(String(fetchMock.mock.calls[0]?.[0])).not.toContain("/v1/capture.search");
    const body = JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit | undefined)?.body ?? "{}"));
    expect(body.payload).toEqual({ capture_id: CAPTURE.capture_id });
  });

  it("invokes knowledge.read when knowledgeId and enrollmentId are both present", async () => {
    const fetchMock = recordedAnswer(KNOWLEDGE_RECORD);
    await renderServerPage(() =>
      LibraryPage({
        searchParams: Promise.resolve({
          knowledgeId: KNOWLEDGE_RECORD.knowledge_id,
          enrollmentId: ENROLLMENT_ID,
        }),
      }),
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/v1/knowledge.read");
    const body = JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit | undefined)?.body ?? "{}"));
    expect(body.payload).toEqual({
      knowledge_id: KNOWLEDGE_RECORD.knowledge_id,
      enrollment_id: ENROLLMENT_ID,
    });
    expect(screen.getByTestId("library-knowledge-item")).toBeTruthy();
    expect(screen.getByTestId("library-knowledge-text").textContent).toBe("hello world");
  });

  it("fails closed when knowledgeId is present without enrollmentId", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("gateway must not be called without enrollmentId");
    });
    vi.stubGlobal("fetch", fetchMock);
    await renderServerPage(() =>
      LibraryPage({
        searchParams: Promise.resolve({ knowledgeId: KNOWLEDGE_RECORD.knowledge_id }),
      }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
    const state = screen.getByTestId("library-knowledge-missing-enrollment");
    expect(state).toHaveAttribute("data-state", "unavailable");
    expect(state.textContent).toMatch(/enrollmentId/i);
    expect(screen.queryByTestId("library-knowledge-item")).toBeNull();
    expect(screen.queryByTestId("library-listing")).toBeNull();
  });

  it("still does not render capture body on listing cards", async () => {
    answerWith({ captures: [{ ...CAPTURE, text: "SECRET BODY TEXT" }] }, whole());
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("library-listing")).toBeTruthy();
    expect(screen.queryByText("SECRET BODY TEXT")).toBeNull();
    expect(screen.queryByTestId("library-capture-text")).toBeNull();
    expect(screen.queryByTestId("library-capture-item")).toBeNull();
  });
});

describe("Review distinguishes an empty queue from an unread one", () => {
  it("renders the backend's cases and states that they carry no text", async () => {
    answerWith({ review_cases: [REVIEW_CASE] }, whole());
    await renderServerPage(() => ReviewPage());
    expect(screen.getByTestId("backend-review-list")).toBeTruthy();
    // The version a decision will be submitted against is on the row, because
    // `review.decide` runs under optimistic concurrency.
    expect(screen.getByTestId("review-version").textContent).toBe("3");
    expect(screen.getByTestId("review-listing-limitation").textContent).toMatch(
      /carries no proposal text/i,
    );
    expect(screen.getByTestId("review-capture-id").textContent).toBe(CAPTURE.capture_id);
    expect(screen.getByTestId("review-version-id").textContent).toBe(CAPTURE.latest_version_id);
    expect(screen.getByTestId("review-reveal")).toBeTruthy();
    expect(screen.queryByTestId("review-goodnotes-link")).toBeNull();
  });

  it("does not render a GoodNotes semantic case as a capture identifier", async () => {
    answerWith({ review_cases: [GOODNOTES_SEMANTIC_CASE] }, whole());
    await renderServerPage(() => ReviewPage());
    const card = screen.getByTestId("backend-review-case");
    expect(card).toHaveAttribute("data-subject-kind", "goodnotes_semantic");
    expect(screen.getByTestId("review-run-id").textContent).toBe(GOODNOTES_SEMANTIC_CASE.run_id);
    expect(screen.getByTestId("review-page-version-id").textContent).toBe(
      GOODNOTES_SEMANTIC_CASE.page_version_id,
    );
    expect(screen.queryByTestId("review-capture-id")).toBeNull();
    expect(screen.queryByTestId("review-reveal")).toBeNull();
    expect(screen.getByTestId("review-goodnotes-link")).toHaveAttribute(
      "href",
      "/knowledge/goodnotes?runId=gnrun_aaaaaaaaaaaaaaaaaaaaaaaa&pageVersionId=gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
    );
  });

  it("links a GoodNotes region case by pageVersionId only", async () => {
    answerWith({ review_cases: [GOODNOTES_REGION_CASE] }, whole());
    await renderServerPage(() => ReviewPage());
    expect(screen.getByTestId("review-region-id").textContent).toBe(GOODNOTES_REGION_CASE.region_id);
    expect(screen.getByTestId("review-confidence").textContent).toBe("0.82");
    expect(screen.queryByTestId("review-run-id")).toBeNull();
    expect(screen.queryByTestId("review-capture-id")).toBeNull();
    expect(screen.getByTestId("review-goodnotes-link")).toHaveAttribute(
      "href",
      "/knowledge/goodnotes?pageVersionId=gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
    );
  });

  it("says nothing is waiting only for a queue it actually read", async () => {
    answerWith({ review_cases: [] }, whole());
    const { unmount } = await renderServerPage(() => ReviewPage());
    expect(screen.getByTestId("review-queue-empty")).toHaveAttribute("data-state", "empty");
    unmount();

    answerWith({ review_cases: [] }, notSearched());
    await renderServerPage(() => ReviewPage());
    expect(screen.getByTestId("review-queue-unavailable")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
    // A full queue misreported as clear is the specific harm here.
    expect(screen.queryByText(/nothing is waiting/i)).toBeNull();
    expect(screen.queryByTestId("review-queue-empty")).toBeNull();
    expect(screen.queryByText(/nothing to review/i)).toBeNull();
    expect(screen.queryByText(/all-clear/i)).toBeNull();
  });
});

/**
 * Today's content is the canonical Today Task set (`tasks.list?work_view=today`),
 * and the derived Pulse annotates it and adds the non-Task material it raised.
 *
 * That is what re-keys the quiet-day sentence. It used to mean "the derivation
 * returned no rows"; it now means the canonical Task set was empty and the
 * derivation raised nothing else. The tests below assert that meaning, which is
 * why several of them now name a Task list as well as a Pulse list.
 */
describe("Today distinguishes a quiet day from a failed derivation", () => {
  /** A canonical Today Task the derivation also flagged. */
  const FLAGGED_TASK_ITEM = {
    pulse_id: "pls_bbbb0001bbbb0001bbbb0001",
    item_type: "task",
    item_ref: "tsk_flagged0001",
    reason_code: "task_overdue",
    reason: "past its date by two days",
    basis_refs: ["asr_bbbb0001bbbb0001bbbb0001"],
    consequence: null,
    next_step: null,
    attention_rank: 2,
    generated_at: "2026-01-01T00:00:00Z",
  } satisfies PulseItem;

  it("renders derived items when the derivation returned some", async () => {
    answerPulseWith([PULSE_ITEM], whole());
    await renderTodayPage();
    expect(screen.getByTestId("pulse-reason").textContent).toContain("two days past");
  });

  it("renders a canonical Today Task the derivation never flagged", async () => {
    /*
      The whole point of the composition. Pulse raised nothing at all, and this
      Task is still Today's content because the canonical predicate returned it.
      A surface that rendered only what Pulse flagged would call this a quiet day.
    */
    answerPulseWith([], whole(), [{ taskId: "tsk_unflagged0001", title: "Unflagged but scheduled" }]);
    await renderTodayPage();
    const card = screen.getByTestId("today-task-card");
    expect(within(card).getByTestId("today-task-card-title").textContent).toBe(
      "Unflagged but scheduled",
    );
    expect(within(card).getByTestId("today-task-card-reason").textContent).toBe("Needs you today");
    expect(screen.queryByTestId("today-empty")).toBeNull();
    expect(screen.queryByText(TODAY_EMPTY_COPY)).toBeNull();
  });

  it("annotates a canonical Task the derivation did flag, and keeps one row for it", async () => {
    answerPulseWith([FLAGGED_TASK_ITEM], whole(), [
      { taskId: "tsk_flagged0001", title: "Flagged and scheduled" },
    ]);
    await renderTodayPage();
    const cards = screen.getAllByTestId("today-task-card");
    expect(cards).toHaveLength(1);
    expect(within(cards[0]!).getByTestId("today-task-card-title").textContent).toBe(
      "Flagged and scheduled",
    );
    // The flag is the difference, and it is the concise reason and nothing else.
    expect(within(cards[0]!).getByTestId("today-task-card-reason").textContent).toBe("Overdue");
  });

  it("says nothing meets a condition only when the canonical set is empty and the read ran", async () => {
    answerPulseWith([], whole());
    const { unmount } = await renderTodayPage();
    await waitFor(() => expect(screen.getByTestId("today-empty")).toHaveAttribute("data-state", "empty"));
    unmount();

    answerPulseWith([], notSearched());
    const failed = await renderTodayPage();
    expect(screen.getByTestId("today-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("today-empty")).toBeNull();
    failed.unmount();

    // And a canonical Task standing is never a quiet day, whatever Pulse said.
    answerPulseWith([], whole(), [{ taskId: "tsk_standing0001", title: "A Task for today" }]);
    await renderTodayPage();
    expect(screen.queryByTestId("today-empty")).toBeNull();
    expect(screen.getByTestId("today-task-card")).toBeTruthy();
  });

  it("does NOT treat omitted todayRows as a quiet day", async () => {
    answerPulseWith(undefined, whole());
    await renderTodayPage();
    await waitFor(() =>
      expect(screen.getByTestId("today-unavailable")).toHaveAttribute("data-state", "unavailable"),
    );
    expect(screen.queryByTestId("today-empty")).toBeNull();
  });

  it("says the quiet-day sentence in exactly those words, and only then", async () => {
    answerPulseWith([], whole());
    const { unmount } = await renderTodayPage();
    await waitFor(() => expect(screen.getByTestId("today-empty").textContent).toContain(TODAY_EMPTY_COPY));
    unmount();

    // The same zero rows, from a read the backend said it did not perform.
    answerPulseWith([], notSearched());
    const failed = await renderTodayPage();
    expect(screen.queryByText(TODAY_EMPTY_COPY)).toBeNull();
    failed.unmount();

    // And the same zero rows, from an answer the backend called partial.
    answerPulseWith([], partial());
    const degraded = await renderTodayPage();
    expect(screen.getByTestId("today-degraded-empty")).toHaveAttribute("data-state", "degraded");
    expect(screen.queryByText(TODAY_EMPTY_COPY)).toBeNull();
    expect(screen.queryByTestId("today-empty")).toBeNull();
    degraded.unmount();

    // A partial answer that still carried canonical Tasks says neither sentence:
    // the Tasks are the content, and the banner says the read was incomplete.
    answerPulseWith([], partial(), [{ taskId: "tsk_partial0001", title: "Still scheduled" }]);
    await renderTodayPage();
    expect(screen.queryByTestId("today-degraded-empty")).toBeNull();
    expect(screen.queryByTestId("today-empty")).toBeNull();
    expect(screen.getByTestId("today-task-card-title").textContent).toBe("Still scheduled");
    expect(screen.getByTestId("degraded-banner")).toBeTruthy();
  });
});

describe("Situations never calls a partial answer an empty board", () => {
  it("says the board is empty only when both halves were read whole", async () => {
    answerWith({ situations: [], projects: [] }, whole());
    await renderServerPage(() => SituationsPage());
    const empty = screen.getByTestId("situations-empty");
    expect(empty).toHaveAttribute("data-state", "empty");
    expect(empty.textContent).toMatch(/read successfully/i);
  });

  it("does NOT claim emptiness when a partial answer carried no rows", async () => {
    // Byte-identical payload to the case above; only the backend's own
    // `partial_result` differs. Rows may exist and simply not have come back.
    answerWith({ situations: [], projects: [] }, partial());
    await renderServerPage(() => SituationsPage());
    const state = screen.getByTestId("situations-degraded-empty");
    expect(state).toHaveAttribute("data-state", "degraded");
    expect(screen.getByTestId("degraded-banner")).toBeTruthy();
    // Neither the page's empty card nor the board's two emptiness sentences.
    expect(screen.queryByTestId("situations-empty")).toBeNull();
    expect(screen.queryByTestId("projects-empty")).toBeNull();
    expect(screen.queryByText(/you hold no situations yet/i)).toBeNull();
    expect(screen.queryByText(/you hold no projects yet/i)).toBeNull();
  });

  it("does NOT claim one half is empty because the other half carried rows", async () => {
    // The projects half answered with a row, so the board renders; the
    // situations half answered partial and carried none, and that half's
    // emptiness is therefore not established.
    answerWith({ situations: [], projects: [PROJECT] }, partial());
    await renderServerPage(() => SituationsPage());
    expect(screen.getByTestId("project-card")).toBeTruthy();
    expect(screen.getByTestId("situations-partial-empty").textContent).toMatch(/partial/i);
    expect(screen.queryByTestId("situations-empty")).toBeNull();
    expect(screen.queryByText(/you hold no situations yet/i)).toBeNull();
  });

  it("still says a whole answer's empty half is empty", async () => {
    // The counterpart to the case above, so the guard cannot be satisfied by
    // never making the claim at all: a complete answer that carried no
    // situations beside a real project still states that emptiness plainly.
    answerWith({ situations: [], projects: [PROJECT] }, whole());
    await renderServerPage(() => SituationsPage());
    expect(screen.getByTestId("project-card")).toBeTruthy();
    expect(screen.getByTestId("situations-empty").textContent).toMatch(
      /you hold no situations yet/i,
    );
    expect(screen.queryByTestId("situations-partial-empty")).toBeNull();
  });

  it("does NOT say empty when the backend answered that it did not search", async () => {
    answerWith({ situations: [], projects: [] }, notSearched());
    await renderServerPage(() => SituationsPage());
    expect(screen.getByTestId("situations-unavailable")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
    expect(screen.queryByTestId("situations-empty")).toBeNull();
    expect(screen.queryByTestId("situations-degraded-empty")).toBeNull();
  });
});

describe("System reports what it was told, and says so when it was told nothing", () => {
  /**
   * Root System is almost entirely diagnostics, so these assertions are about
   * the ON presentation and the suite turns diagnostics on for them. The
   * cookie is the real serialized value bound to `PRINCIPAL`, so the page is
   * gated by the shipped parser; a binding regression would turn this whole
   * block red rather than quietly leaving it asserting the OFF page.
   */
  beforeAll(async () => {
    diagnosticsCookie.value = diagnosticsPreferenceValue(
      true,
      await diagnosticsPrincipalBinding(PRINCIPAL.principalId),
    );
  });

  afterAll(() => {
    diagnosticsCookie.value = undefined;
  });

  const CAPABILITIES_GET = {
    manifest: {
      contract_version: "v1",
      contract_family: "my-pa-public-capabilities",
      capabilities: [
        {
          name: "capabilities.get",
          version: "v1",
          availability: "available",
          operator_only: false,
        },
      ],
      content_types: [{ media_type: "text/plain", availability: "available" }],
      limits: {
        max_page_size: 50,
        default_page_size: 20,
        max_fetch_bytes: 1_048_576,
        max_enrollment_depth: 8,
      },
    },
    readiness: {
      state: "degraded",
      contract_version: "v1",
      implemented_capabilities: 24,
      total_capabilities: 26,
      limitations: [],
    },
    worker_planes: [
      {
        plane: "capture",
        state: "idle_or_not_required",
        backlog: 0,
        dead_lettered: 0,
        last_heartbeat_at: null,
      },
    ],
  };

  const REPORTS_LIST = {
    items: [
      {
        report_id: "rpt_aaaaaaaa11111111",
        cycle_run_id: "micr_aaaaaaaa11111111",
        stage: "collector",
        artifact_kind: "collector_candidates",
        focus_area_id: "communications",
        source_lane: null,
        title: "E2E morning brief collector",
        content_sha256: "a".repeat(64),
        artifact_state: "final",
      },
    ],
    next_cursor: null,
  };

  const RESOLVE_SET = {
    cycle_run_id: "micr_aaaaaaaa11111111",
    cycle_id: "morning_intelligence",
    business_date: "2026-08-20",
    set_id: "morning_brief_inputs",
    aggregate: "BLOCKED",
    members: [
      {
        member_id: "communications",
        focus_area_id: "communications",
        source_lane: null,
        readiness: "READY",
        required: true,
        artifact_id: "rpt_aaaaaaaa11111111",
        producer_run_id: "prun_aaaaaaaa11111111",
        content_sha256: "a".repeat(64),
        committed_at: "2026-08-20T12:00:00Z",
        readiness_reason: "present",
      },
      {
        member_id: "people",
        focus_area_id: "people",
        source_lane: null,
        readiness: "MISSING",
        required: true,
        artifact_id: null,
        producer_run_id: null,
        content_sha256: null,
        committed_at: null,
        readiness_reason: "missing",
      },
    ],
  };

  function answerSystem(overrides: {
    capabilities?: unknown;
    list?: unknown;
    resolve?: unknown;
  } = {}) {
    answerByCapability({
      "capabilities.get": overrides.capabilities ?? CAPABILITIES_GET,
      "reports.list": overrides.list ?? REPORTS_LIST,
      "reports.resolve_set": overrides.resolve ?? RESOLVE_SET,
    });
  }

  it("prints the readiness count the application actually returned", async () => {
    answerWith(CAPABILITIES_GET, whole());
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-readiness").textContent).toMatch(/24 of 26/);
    expect(screen.queryByTestId("system-readiness-unknown")).toBeNull();
  });

  it("does NOT render '0 of 0' for a response that carried no readiness", async () => {
    // A successful-looking answer with the `readiness` key absent is a contract
    // failure after WP06 decode. Missing nested objects must not become a
    // confident claim that nothing is implemented.
    answerWith({ manifest: CAPABILITIES_GET.manifest }, whole());
    await renderServerPage(() => SystemPage());
    expect(screen.queryByTestId("system-readiness")).toBeNull();
    expect(screen.getByTestId("system-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(document.body.textContent).not.toMatch(/0 of 0/);
  });

  it("shows a gateway auth mode it cannot read as a misconfiguration", async () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "");
    answerWith(CAPABILITIES_GET, whole());
    await renderServerPage(() => SystemPage());
    const alert = screen.getByTestId("system-auth-mode-misconfigured");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toMatch(/MYPA_GATEWAY_AUTH_MODE is not set/);
    // And the disclosure it replaces is not silently substituted for it.
    expect(screen.queryByTestId("system-local-operator")).toBeNull();
  });

  it("still discloses the local_operator limit when the mode is readable", async () => {
    answerWith(CAPABILITIES_GET, whole());
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-local-operator").textContent).toMatch(/one fixed principal/);
    expect(screen.queryByTestId("system-auth-mode-misconfigured")).toBeNull();
  });

  it("renders an absent worker heartbeat as unknown, never healthy", async () => {
    answerSystem();
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-worker-heartbeat-unknown").textContent).toMatch(
      /last heartbeat unknown/,
    );
    expect(screen.queryByTestId("system-worker-heartbeat")).toBeNull();
    expect(screen.getByTestId("system-worker-planes").textContent).not.toMatch(/\bhealthy\b/);
  });

  it("keeps worker_absent visibly not-healthy", async () => {
    answerSystem({
      capabilities: {
        ...CAPABILITIES_GET,
        worker_planes: [
          {
            plane: "capture",
            state: "worker_absent",
            backlog: 1,
            dead_lettered: 0,
            last_heartbeat_at: null,
          },
        ],
      },
    });
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-worker-not-healthy").textContent).toMatch(/not healthy/);
    expect(screen.getByTestId("system-worker-planes").textContent).toMatch(/worker_absent/);
  });

  it("shows Intelligence aggregate and members without flattening READY to system health", async () => {
    answerSystem();
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-intelligence-aggregate").textContent).toBe("BLOCKED");
    const members = screen.getAllByTestId("system-intelligence-member");
    expect(members).toHaveLength(2);
    const states = screen.getAllByTestId("system-intelligence-member-readiness").map((el) => el.textContent);
    expect(states).toEqual(["READY", "MISSING"]);
    expect(states).not.toEqual(["BLOCKED"]);
    expect(screen.getByTestId("system-intelligence-not-system-health").textContent).toMatch(
      /not a claim that the system is healthy/,
    );
    expect(screen.getByTestId("system-pwa-client-side").textContent).toMatch(/this browser/);
    expect(screen.getByTestId("system-pwa-client-side").textContent).toMatch(/client-side/);
    expect(screen.getByTestId("system-pwa-client-side").textContent).not.toMatch(
      /PWA_FIELDS_PENDING_WP26/,
    );
    expect(screen.queryByTestId("system-pwa-pending")).toBeNull();
    expect(screen.getByTestId("system-pwa-this-browser").textContent).toMatch(/This browser/);
    expect(screen.getByTestId("system-sources-unknown").textContent).toMatch(/cannot list/);
    expect(screen.getByTestId("system-refresh")).toBeTruthy();
  });

  it("does not invent a cycle when reports.list is empty", async () => {
    answerSystem({ list: { items: [], next_cursor: null } });
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-intelligence-no-cycle").textContent).toMatch(/cycle_run_id is unknown/);
    expect(screen.queryByTestId("system-intelligence-members")).toBeNull();
    expect(screen.queryByTestId("system-intelligence-aggregate")).toBeNull();
  });
});

describe("Relationship timeline fails closed without relationship_events", () => {
  it("does not emit an empty timeline when the workspace group is absent", async () => {
    answerWith({ situations: [] }, whole());
    await renderServerPage(() =>
      RelationshipPage({ params: Promise.resolve({ personId: "per_aaaa0001aaaa0001aaaa0001" }) }),
    );
    expect(screen.getByTestId("relationship-unavailable")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
  });
});

describe("no surface accepts an identity from anything but the session", () => {
  it("refuses a principal supplied through the query string", async () => {
    // The Library page takes `searchParams`, which is the only caller-controlled
    // input any of these pages has. A principal named there must reach nothing:
    // the page reads `q` and nothing else, and the envelope's identifier is
    // derived from the session's `tid`/`oid` by `correlationPrincipalId`.
    const seen: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: unknown, init?: RequestInit) => {
        seen.push(JSON.parse(String(init?.body ?? "{}")));
        return new Response(JSON.stringify({ result: { captures: [] }, disclosure: whole() }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );
    const foreign = "prn_ffffffffffffffffffffffffffffffff";
    await renderServerPage(() =>
      LibraryPage({
        searchParams: Promise.resolve({ principalId: foreign, principal_id: foreign }),
      }),
    );
    expect(seen).toHaveLength(1);
    const wire = JSON.stringify(seen[0]);
    expect(wire).not.toContain(foreign);
    // And what was sent is the derivation of the session's own claims.
    expect(seen[0]["principal_id"]).toMatch(/^prn_[0-9a-f]{32}$/);
  });
});

const ENTITY_SUMMARY = {
  entity_id: "ent_aaaaaaaa11111111",
  entity_type: "person",
  canonical_name: "pat synthetic",
  display_name: "Pat Synthetic",
  status: "active",
  affiliated_organizations: ["Acme Synthetic"],
  project_roles: ["architect"],
};

const ENTITY_VIEW = {
  entity_id: "ent_aaaaaaaa11111111",
  entity_type: "person",
  canonical_name: "pat synthetic",
  display_name: "Pat Synthetic",
  status: "active",
  created_at: "2026-08-09T12:00:00.000Z",
  updated_at: "2026-08-09T12:00:00.000Z",
  version: 1,
  superseded_by_entity_id: null,
};

const PROFILE = {
  entity: ENTITY_VIEW,
  assembled_at: "2026-08-09T12:00:00.000Z",
  limitations: [],
  is_complete: true,
  organization_profile: null,
  names: [
    {
      entity_name_id: "enam_aaaaaaaa11111111",
      entity_id: ENTITY_VIEW.entity_id,
      name_type_code: "display",
      display_value: "Pat Synthetic",
      normalized_value: "pat synthetic",
      is_preferred: true,
      effective_from: null,
      effective_to: null,
      state: "active",
      version: 1,
      updated_at: "2026-08-09T12:00:00.000Z",
      retired_at: null,
      superseded_by_entity_name_id: null,
    },
  ],
  addresses: [],
  communication_methods: [],
  participations_as_project: [],
  participations_as_participant: [],
  affiliations_as_person: [],
  affiliations_as_organization: [],
};

const RESOLUTION = {
  outcome: "ambiguous",
  entity_id: null,
  candidates: [
    {
      entity_id: ENTITY_VIEW.entity_id,
      entity_type: "person",
      display_name: "Alex Chen",
      status: "active",
      superseded_by_entity_id: null,
      matched_on: ["canonical_name"],
      signals: [],
    },
  ],
  warnings: ["several_entities_share_this_name"],
  candidates_were_truncated: false,
};

describe("People reaches search, resolve, and profile instead of a directory", () => {
  it("does not list everyone when nothing was asked", async () => {
    socketFails();
    await renderServerPage(() => PeoplePage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("people-idle")).toHaveAttribute("data-state", "empty");
    expect(screen.getByRole("searchbox", { name: "Find a person" })).toBeTruthy();
    expect(screen.queryByText(/no admitted same-origin BFF exposure/i)).toBeNull();
  });

  it("renders the entities a successful search returned", async () => {
    answerWith({ entities: [ENTITY_SUMMARY] }, whole());
    await renderServerPage(() =>
      PeoplePage({ searchParams: Promise.resolve({ q: "Pat Synthetic" }) }),
    );
    expect(screen.getByTestId("people-search-hits")).toBeTruthy();
    expect(screen.getByText("Pat Synthetic")).toBeTruthy();
    expect(screen.queryByTestId("people-search-empty")).toBeNull();
  });

  it("says empty only when search actually matched none", async () => {
    answerWith({ entities: [] }, whole());
    await renderServerPage(() => PeoplePage({ searchParams: Promise.resolve({ q: "nobody" }) }));
    const empty = screen.getByTestId("people-search-empty");
    expect(empty).toHaveAttribute("data-state", "empty");
  });

  it("does NOT say empty when the backend answered that it did not search", async () => {
    answerWith({ entities: [] }, notSearched());
    await renderServerPage(() => PeoplePage({ searchParams: Promise.resolve({ q: "nobody" }) }));
    expect(screen.getByTestId("people-search-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("people-search-empty")).toBeNull();
  });

  it("keeps an ambiguous resolve outcome visible", async () => {
    answerWith({ resolution: RESOLUTION }, whole());
    await renderServerPage(() =>
      PeoplePage({ searchParams: Promise.resolve({ reference: "Alex Chen" }) }),
    );
    expect(screen.getByTestId("people-resolve-outcome").textContent).toMatch(/ambiguous/i);
    expect(screen.queryByRole("button", { name: /merge/i })).toBeNull();
  });

  it("reads a profile from entities.profile", async () => {
    answerByCapability({
      "entities.profile": { profile: PROFILE },
      "entities.assignments.list": { assignments: [] },
      "entities.relationships": { relationships: [] },
      "entities.identity_history": {
        entity_id: ENTITY_VIEW.entity_id,
        entries: [],
        is_truncated: false,
        next_cursor: null,
        audit_id: "audit_aaaaaaaa11111111",
      },
    });
    await renderServerPage(() =>
      PeopleEntityPage({ params: Promise.resolve({ entityId: ENTITY_VIEW.entity_id }) }),
    );
    expect(screen.getByTestId("people-profile")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Pat Synthetic", level: 1 })).toBeTruthy();
  });

  it("redirects a query-param entityId to the canonical profile path", async () => {
    const saved = Object.getOwnPropertyDescriptor(globalThis, "window");
    Reflect.deleteProperty(globalThis, "window");
    try {
      await expect(
        PeoplePage({ searchParams: Promise.resolve({ entityId: ENTITY_VIEW.entity_id }) }),
      ).rejects.toThrow();
    } finally {
      if (saved) Object.defineProperty(globalThis, "window", saved);
    }
  });
});

describe("Knowledge offers a GoodNotes entry without claiming notebooks exist", () => {
  it("links to /knowledge/goodnotes beside an unchanged capture library", async () => {
    answerWith({ captures: [CAPTURE] }, whole());
    await renderServerPage(() => KnowledgePage({ searchParams: NO_PARAMS }));
    const entry = screen.getByTestId("knowledge-goodnotes-entry");
    expect(entry.textContent).toMatch(/does not mean notebooks are present/i);
    expect(screen.getByRole("link", { name: "Open GoodNotes" })).toHaveAttribute(
      "href",
      "/knowledge/goodnotes",
    );
    expect(screen.getByTestId("library-listing")).toBeTruthy();
    expect(screen.queryByTestId("goodnotes-notebooks")).toBeNull();
  });

  it("still offers the entry when Library has nothing to serve synthetically", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await renderServerPage(() => KnowledgePage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("knowledge-goodnotes-entry")).toBeTruthy();
    expect(screen.getByTestId("library-synthetic")).toHaveAttribute("data-state", "not_implemented");
  });
});

/**
 * WP07 AC-43 / AC-44 / AC-48 — root System while diagnostics are OFF.
 *
 * This is the load-bearing half of the contract, and it is asserted three
 * different ways because "OFF" has three different meanings that can regress
 * independently: nothing diagnostic is in the **DOM**, nothing diagnostic is in
 * the **accessibility tree**, and no diagnostic-only **work is performed**.
 *
 * The third is the one a rendering test alone would miss. Root System's two
 * gateway reads — `capabilities.get` and the `reports.list` /
 * `reports.resolve_set` pair behind Morning Intelligence readiness — exist only
 * to produce diagnostic content at this callsite, so while OFF they must not be
 * invoked at all. Asserting `fetch` was never called is what distinguishes
 * gating *before* invocation from rendering and then hiding.
 */
describe("root System while diagnostics are off", () => {
  beforeEach(() => {
    diagnosticsCookie.value = undefined;
  });

  /** Every diagnostic hook the ON page renders. None may survive OFF. */
  const DIAGNOSTIC_TEST_IDS = [
    "system-principal-id",
    "system-identity-provider",
    "system-identity-subject",
    "system-tid",
    "system-oid",
    "system-readiness",
    "system-readiness-unknown",
    "system-available",
    "system-unavailable-caps",
    "system-worker-planes",
    "system-worker-planes-unknown",
    "system-worker-heartbeat",
    "system-worker-heartbeat-unknown",
    "system-intelligence-aggregate",
    "system-intelligence-members",
    "system-intelligence-member",
    "system-graph",
    "system-sources-unknown",
    "system-pwa-client-side",
    "system-pwa-this-browser",
    "system-source-commit",
    "system-refresh",
  ];

  it("renders the sole control and no diagnostic content", async () => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    await renderServerPage(() => SystemPage());

    // Exactly one visibility control, and it is a real accessible switch.
    const toggle = screen.getByTestId("show-diagnostics-toggle");
    expect(toggle).toHaveAttribute("role", "switch");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getAllByRole("switch")).toHaveLength(1);
    expect(screen.getByRole("switch", { name: /show diagnostics/i })).toBe(toggle);

    for (const testId of DIAGNOSTIC_TEST_IDS) {
      expect(screen.queryByTestId(testId)).toBeNull();
    }

    // No diagnostic-only server work was performed to build this page.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("leaves no diagnostic text, placeholder or reserved chrome behind", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
    await renderServerPage(() => SystemPage());
    const text = document.body.textContent ?? "";

    // No "diagnostics are hidden" placeholder, and none of the vocabulary the
    // ON page uses. The toggle's own label and helper copy are the exception
    // and are matched exactly rather than by the word "diagnostics".
    expect(text).not.toMatch(/hidden|unavailable in this view|turn on diagnostics to/i);
    for (const vocabulary of [
      /contracted capabilities/i,
      /worker plane/i,
      /last heartbeat/i,
      /source commit/i,
      /morning intelligence readiness/i,
      /capability manifest/i,
      /Microsoft Graph/i,
    ]) {
      expect(text).not.toMatch(vocabulary);
    }

    // The raw identity dump is diagnostics and is gone. The *sentence* about
    // `local_operator` partitioning is not: it tells the reader their data may
    // not be partitioned by who is signed in, which is product truth and stays
    // true in both modes. So the identifiers are asserted absent by value, not
    // by banning the word "principal" — which would have deleted the warning.
    expect(text).not.toMatch(/aaaa0001-0000-0000-0000-000000000001/);
    expect(text).not.toMatch(/11111111-2222-3333-4444-555555555555/);
    expect(text).not.toMatch(/synthetic\.a@moss\.example/);
    expect(screen.getByTestId("system-local-operator")).toBeTruthy();

    // No empty card or reserved wrapper left standing where content used to be.
    expect(document.querySelectorAll("dl")).toHaveLength(0);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });
});
