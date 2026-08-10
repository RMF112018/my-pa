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

// The session is resolved server-side from a signed cookie. These two mocks
// stand in for the cookie jar and the signature check *only*; nothing here
// supplies an identity to the page through a payload, and the pages under test
// have no parameter one could arrive through.
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ name: "mypa_session", value: "stub" }) }),
}));
vi.mock("@/lib/auth/principal", () => ({
  resolveSessionPrincipal: async () => PRINCIPAL,
}));

import LibraryPage from "@/app/(app)/library/page";
import ReviewPage from "@/app/(app)/review/page";
import TodayPage from "@/app/(app)/today/page";
import SituationsPage from "@/app/(app)/situations/page";
import SystemPage from "@/app/(app)/system/page";

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
};

const REVIEW_CASE = {
  review_case_id: "rvc_aaaa0001aaaa0001aaaa0001",
  proposal_id: "prop_aaaa0001aaaa0001aaaa0001",
  capture_id: CAPTURE.capture_id,
  version_id: CAPTURE.latest_version_id,
  proposal_type: "commitment",
  proposal_state: "proposed",
  risk_class: "high",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 3,
  latest_disposition: null,
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
  priority: 1,
  generated_at: "2026-01-01T00:00:00Z",
};

const PROJECT = {
  project_id: "prj_aaaa0001aaaa0001aaaa0001",
  name: "North slab pour",
  state: "active",
  description: null,
  participants: [],
  opened_at: "2026-01-01T00:00:00Z",
  closed_at: null,
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
    answerWith({ matches: [] }, whole());
    const { unmount } = await renderServerPage(() => LibraryPage({ searchParams: Promise.resolve({ q: "slab" }) }));
    expect(screen.getByTestId("library-search-empty")).toHaveAttribute("data-state", "empty");
    unmount();

    answerWith({ matches: [] }, notSearched());
    await renderServerPage(() => LibraryPage({ searchParams: Promise.resolve({ q: "slab" }) }));
    expect(screen.getByTestId("library-search-unavailable")).toHaveAttribute(
      "data-state",
      "unavailable",
    );
  });

  it("offers no synthetic Library and says so rather than inventing one", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    await renderServerPage(() => LibraryPage({ searchParams: NO_PARAMS }));
    expect(screen.getByTestId("library-synthetic")).toHaveAttribute("data-state", "not_implemented");
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
  });
});

describe("Today distinguishes a quiet day from a failed derivation", () => {
  it("renders derived items when the derivation returned some", async () => {
    answerWith({ pulse_items: [PULSE_ITEM] }, whole());
    await renderServerPage(() => TodayPage());
    expect(screen.getByTestId("pulse-reason").textContent).toContain("two days past");
  });

  it("says nothing meets a condition only when the derivation ran", async () => {
    answerWith({ pulse_items: [] }, whole());
    const { unmount } = await renderServerPage(() => TodayPage());
    expect(screen.getByTestId("today-empty")).toHaveAttribute("data-state", "empty");
    unmount();

    answerWith({ pulse_items: [] }, notSearched());
    await renderServerPage(() => TodayPage());
    expect(screen.getByTestId("today-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("today-empty")).toBeNull();
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
  const MANIFEST = { contract_version: "v1", capabilities: [] };

  it("prints the readiness count the application actually returned", async () => {
    answerWith(
      {
        manifest: MANIFEST,
        readiness: { state: "degraded", implemented_capabilities: 24, total_capabilities: 26 },
      },
      whole(),
    );
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-readiness").textContent).toMatch(/24 of 26/);
    expect(screen.queryByTestId("system-readiness-unknown")).toBeNull();
  });

  it("does NOT render '0 of 0' for a response that carried no readiness", async () => {
    // A successful answer with the `readiness` key simply absent. `?? 0` on both
    // halves turned that into a confident claim that nothing is implemented.
    answerWith({ manifest: MANIFEST }, whole());
    await renderServerPage(() => SystemPage());
    expect(screen.queryByTestId("system-readiness")).toBeNull();
    const unknown = screen.getByTestId("system-readiness-unknown");
    expect(unknown.textContent).toMatch(/unknown/i);
    expect(document.body.textContent).not.toMatch(/0 of 0/);
  });

  it("shows a gateway auth mode it cannot read as a misconfiguration", async () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "");
    answerWith({ manifest: MANIFEST }, whole());
    await renderServerPage(() => SystemPage());
    const alert = screen.getByTestId("system-auth-mode-misconfigured");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toMatch(/MYPA_GATEWAY_AUTH_MODE is not set/);
    // And the disclosure it replaces is not silently substituted for it.
    expect(screen.queryByTestId("system-local-operator")).toBeNull();
  });

  it("still discloses the local_operator limit when the mode is readable", async () => {
    answerWith({ manifest: MANIFEST }, whole());
    await renderServerPage(() => SystemPage());
    expect(screen.getByTestId("system-local-operator").textContent).toMatch(/one fixed principal/);
    expect(screen.queryByTestId("system-auth-mode-misconfigured")).toBeNull();
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
