/**
 * `CaptureConstraintForm` — Quick Constraint, the fourth Capture type
 * (R02-WP10 Phase 7).
 *
 * Exercises: the chooser/selectors/Details/focus/retry surface required by
 * `PC-CM-CAPTURE-AC-029`; Project/Category/Description required
 * (`-007`/`-008`/`-009`); Category cleared on a Project switch (`-016`);
 * server-side defaults for Status/Date Identified/Due never invented here
 * (`-011`/`-012`/`-013`); Comments maps to `current_update` (`-014`); Details
 * collapsed by default (`-015`); one atomic `create_published` intent
 * (`-017`); success only from the authoritative response, with no internal
 * id in the product default (`-019`/`-020`); Open Constraint/Close
 * (`-021`); every authored value survives a refusal (`-022`); explicit
 * discard on a dirty Cancel (`-025`); the canonical `PartyRef` identity for
 * BIC, never a guess (`-010`).
 *
 * The real `ConstraintRuntimeProvider`/`ProjectScopeProvider`/
 * `MutationFeedbackProvider` stack is used — the same harness shape
 * `constraint-runtime-provider.test.tsx` uses — rather than a stub of the
 * coordinators, so this file proves the wiring, not a mock of it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useReducer } from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { CaptureConstraintForm } from "@/components/capture/capture-constraint-form";
import { beginCaptureExperience, captureSessionReducer } from "@/lib/capture/session";
import { ConstraintRuntimeProvider } from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";
// Test-only: decoding the committed Python fixture through the real,
// server-only decoder to derive a mechanically-authoritative pinned
// response body (see `realBffCreatePublishedBody` below). Never imported
// by `capture-constraint-form.tsx` itself — that file reads the already-
// decoded, camelCase response directly (`invokeGateway` decodes it
// server-side, before the browser ever sees it; see that file's own
// `readConfirmedSummary` doc comment).
import { decodeConstraintsCreatePublished } from "@/lib/api/decode/capabilities/constraints.create_published";

const { diagnostics } = vi.hoisted(() => ({ diagnostics: { enabled: false } }));
vi.mock("@/components/diagnostics/diagnostics-provider", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/diagnostics/diagnostics-provider")>();
  return {
    ...actual,
    useDiagnosticsEnabled: () => diagnostics.enabled,
    WhenDiagnostics: ({ children }: { children: React.ReactNode }) =>
      diagnostics.enabled ? children : null,
  };
});

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push, refresh: vi.fn() }),
  usePathname: () => "/today",
}));

const PRINCIPAL_ID = "aaaa0001-0000-0000-0000-000000000001";
const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";
const CATEGORY_A = "ccat_aaaaaaaa11111111";
const CATEGORY_B = "ccat_bbbbbbbb22222222";
const CONSTRAINT_ID = "cst_aaaaaaaa11111111";

function categoriesBody(projectId: string) {
  const seed = projectId === PROJECT_A ? CATEGORY_A : CATEGORY_B;
  return {
    categories: [
      {
        categoryId: seed,
        projectId,
        prefix: "1",
        title: "Design",
        description: null,
        displayOrder: 1,
        state: "active",
        nextSequence: 2,
        issuedCount: 1,
        version: 1,
        prefixLocked: false,
      },
      {
        categoryId: `${seed}-inactive`,
        projectId,
        prefix: "2",
        title: "Retired",
        description: null,
        displayOrder: 2,
        state: "inactive",
        nextSequence: 1,
        issuedCount: 0,
        version: 1,
        prefixLocked: false,
      },
    ],
  };
}

/**
 * The real backend response shape: already camelCase, already decoded.
 *
 * `POST /api/project-controls/projects/[projectId]/constraints` → `workPost`
 * → `dispatch()` → `invokeGateway()` (`web/src/lib/api/gateway.ts`) calls
 * `decodeCapability("constraints.create_published", outcome.result)`
 * **server-side**, before the route handler ever sees the result —
 * `constraints.create_published` is registered in `DECODERS` against exactly
 * `decodeConstraintsCreatePublished`. `dispatch()` sends that already-
 * decoded shape straight to the browser (`publicResult` only strips the
 * Principal identity, never case-converts it back to snake_case). This is
 * confirmed directly and independently below, in
 * `realBffCreatePublishedBody()` — which derives the same shape
 * mechanically, from the real decoder's own output — and is the same shape
 * `constraint-routes.test.ts`'s `it.each(ROWS)("%s", ...)` (R01-WP09)
 * already asserts end to end through the real route handler for all
 * thirteen authoring routes, including this one.
 */
function confirmedBody({
  projectId = PROJECT_A,
  constraintId = CONSTRAINT_ID,
}: { readonly projectId?: string; readonly constraintId?: string } = {}) {
  return {
    shape: "backend",
    disposition: "applied",
    constraint: {
      constraintId,
      lifecycleState: "identified",
      origin: "product",
      createdAt: "2026-09-24T12:00:00Z",
      updatedAt: "2026-09-24T12:00:00Z",
      version: 1,
      projectId,
      categoryId: CATEGORY_A,
      constraintCode: "1.1",
      description: "synthetic constraint description",
      dateIdentified: "2026-09-24",
      dueDate: "2026-10-08",
      reference: null,
      currentUpdate: null,
      bic: [],
      responsible: [],
      completionDate: null,
      closureCommentary: null,
      voidedDate: null,
      voidReason: null,
      recordQuality: "normal",
      publishedAt: "2026-09-24T12:00:00Z",
    },
    receipt: {
      historyId: "chst_aaaaaaaa11111111",
      constraintId,
      operation: "create",
      actor: "principal",
      outcome: "applied",
      beforeVersion: 0,
      afterVersion: 1,
      occurredAt: "2026-09-24T12:00:00Z",
      projectId,
      revisionId: null,
      safeFailureReason: null,
    },
    disclosure: {},
  };
}

/**
 * Pins the real BFF wire shape — mechanically, not hand-typed.
 *
 * Decodes the same committed Python fixture (`src/lib/api/decode/fixtures/
 * python/success.json`, the shared, campaign-wide ground truth for what the
 * gateway actually sends) through the real, production
 * `decodeConstraintsCreatePublished`, the exact function `invokeGateway`
 * calls server-side. The result is therefore the real, authoritative
 * camelCase shape this component's `readConfirmedSummary()` must handle —
 * not a fixture that merely happens to agree with the implementation. If the
 * committed Python fixture or the decoder's output shape ever drifts, this
 * fails here rather than silently.
 */
function realBffCreatePublishedBody(): Record<string, unknown> {
  const python = JSON.parse(
    readFileSync(
      join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json"),
      "utf8",
    ),
  ) as Record<string, unknown>;
  const decoded = decodeConstraintsCreatePublished(python["constraints.create_published"]);
  if (!decoded.ok) {
    throw new Error(
      "the committed Python fixture for constraints.create_published no longer decodes — update this pin",
    );
  }
  return { shape: "backend", ...decoded.value, disclosure: {} };
}

interface FetchPlan {
  readonly postResponses?: readonly { readonly body: unknown; readonly status: number }[];
}

/** Route every fetch this surface issues: Project list, Categories, the create POST. */
function stubFetch(plan: FetchPlan = {}) {
  let postCall = 0;
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const method = String(init?.method ?? "GET").toUpperCase();
    if (path.startsWith("/api/projects/")) {
      const id = path.slice("/api/projects/".length);
      const name = id === PROJECT_A ? "Harbor Migration" : id === PROJECT_B ? "North Tower" : null;
      return name
        ? new Response(JSON.stringify({ project: { name } }), { status: 200 })
        : new Response("{}", { status: 404 });
    }
    if (path.startsWith("/api/projects")) {
      return new Response(
        JSON.stringify({
          projects: [
            { projectId: PROJECT_A, name: "Harbor Migration" },
            { projectId: PROJECT_B, name: "North Tower" },
          ],
          nextCursor: null,
        }),
        { status: 200 },
      );
    }
    if (path.includes("/constraint-categories")) {
      const projectId = path.match(/projects\/([^/]+)\/constraint-categories/)?.[1] ?? PROJECT_A;
      return new Response(JSON.stringify(categoriesBody(decodeURIComponent(projectId))), {
        status: 200,
      });
    }
    if (method === "POST" && path.includes("/constraints")) {
      const plans = plan.postResponses ?? [{ body: confirmedBody(), status: 200 }];
      const entry = plans[Math.min(postCall, plans.length - 1)];
      postCall += 1;
      return new Response(JSON.stringify(entry.body), { status: entry.status });
    }
    return new Response("{}", { status: 200 });
  });
  return spy;
}

function postCalls(spy: ReturnType<typeof stubFetch>) {
  return spy.mock.calls.filter(
    ([input, init]) =>
      String(input).includes("/constraints") &&
      !String(input).includes("constraint-categories") &&
      String((init as RequestInit | undefined)?.method).toUpperCase() === "POST",
  );
}

function postBody(spy: ReturnType<typeof stubFetch>, index = 0): Record<string, unknown> {
  const call = postCalls(spy)[index];
  if (!call) throw new Error("no create POST was issued");
  return JSON.parse(String((call[1] as RequestInit).body));
}

function Harness({
  projectId = PROJECT_A,
  onClose = () => {},
  onBack = () => {},
}: {
  readonly projectId?: string | null;
  readonly onClose?: () => void;
  readonly onBack?: () => void;
}) {
  const [session, dispatch] = useReducer(captureSessionReducer, undefined, () =>
    beginCaptureExperience({
      experienceId: "constraint-test",
      principalId: PRINCIPAL_ID,
      sessionEpoch: 1,
      projectId,
    }),
  );
  return (
    <ProjectScopeProvider principalId={PRINCIPAL_ID} sessionEpoch="test-session-binding">
      <MutationFeedbackProvider>
        <ConstraintRuntimeProvider principalId={PRINCIPAL_ID} sessionEpoch="test-session-binding">
          <CaptureConstraintForm
            principalId={PRINCIPAL_ID}
            session={session}
            dispatch={dispatch}
            onClose={onClose}
            onBack={onBack}
          />
        </ConstraintRuntimeProvider>
      </MutationFeedbackProvider>
    </ProjectScopeProvider>
  );
}

async function fillRequired(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() =>
    expect(within(screen.getByTestId("capture-constraint-category")).getByText("1 · Design")).toBeInTheDocument(),
  );
  await user.selectOptions(screen.getByTestId("capture-constraint-category"), CATEGORY_A);
  await user.type(screen.getByTestId("capture-constraint-description"), "synthetic constraint description");
}

afterEach(() => {
  diagnostics.enabled = false;
  navigation.push.mockClear();
  cleanup();
  vi.restoreAllMocks();
});

describe("required fields", () => {
  it("refuses to file without a Project, and issues no request", async () => {
    const spy = stubFetch();
    const user = userEvent.setup();
    render(<Harness projectId={null} />);
    await user.type(await screen.findByTestId("capture-constraint-description"), "x");
    await user.click(screen.getByTestId("capture-constraint-save"));

    expect(await screen.findByTestId("capture-constraint-project-error")).toBeInTheDocument();
    expect(postCalls(spy)).toHaveLength(0);
  });

  it("requires a Category once a Project is set, and issues no request", async () => {
    const spy = stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(await screen.findByTestId("capture-constraint-description"), "x");
    await user.click(screen.getByTestId("capture-constraint-save"));

    expect(await screen.findByTestId("capture-constraint-category-error")).toBeInTheDocument();
    expect(postCalls(spy)).toHaveLength(0);
  });

  it("requires a Description, and issues no request", async () => {
    const spy = stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    await waitFor(() =>
      expect(within(screen.getByTestId("capture-constraint-category")).getByText("1 · Design")).toBeInTheDocument(),
    );
    await user.selectOptions(screen.getByTestId("capture-constraint-category"), CATEGORY_A);
    await user.click(screen.getByTestId("capture-constraint-save"));

    expect(await screen.findByText("Enter a description.")).toBeInTheDocument();
    expect(postCalls(spy)).toHaveLength(0);
  });

  it("only offers the Project's active Categories", async () => {
    stubFetch();
    render(<Harness />);
    const select = await screen.findByTestId("capture-constraint-category");
    await waitFor(() => expect(within(select).getByText("1 · Design")).toBeInTheDocument());
    expect(within(select).queryByText("2 · Retired")).toBeNull();
  });
});

describe("server-side defaults are never invented here", () => {
  it("omits Status/Date Identified/Due/BIC when Details is left untouched", async () => {
    const spy = stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    await waitFor(() => expect(postCalls(spy)).toHaveLength(1));
    const body = postBody(spy);
    expect(body).toMatchObject({ categoryId: CATEGORY_A, description: "synthetic constraint description" });
    expect(body).not.toHaveProperty("toState");
    expect(body).not.toHaveProperty("dateIdentified");
    expect(body).not.toHaveProperty("dueDate");
    expect(body).not.toHaveProperty("bic");
    expect(body).not.toHaveProperty("currentUpdate");
  });

  it("Details starts collapsed and sends every override explicitly once opened", async () => {
    const spy = stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByTestId("capture-constraint-details")).toBeNull();

    await user.click(screen.getByTestId("capture-constraint-details-toggle"));
    await fillRequired(user);
    await user.selectOptions(screen.getByTestId("capture-constraint-status"), "pending");
    await user.type(screen.getByTestId("capture-constraint-date-identified"), "2026-09-01");
    await user.type(screen.getByTestId("capture-constraint-due-date"), "2026-09-15");
    await user.type(screen.getByTestId("capture-constraint-comments"), "a comment");
    await user.selectOptions(screen.getByTestId("capture-constraint-bic"), "me");
    await user.click(screen.getByTestId("capture-constraint-save"));

    await waitFor(() => expect(postCalls(spy)).toHaveLength(1));
    const body = postBody(spy);
    expect(body.toState).toBe("pending");
    expect(body.dateIdentified).toBe("2026-09-01");
    expect(body.dueDate).toBe("2026-09-15");
    // Comments map to the canonical `current_update` (`PC-CM-CAPTURE-AC-014`).
    expect(body.currentUpdate).toBe("a comment");
    expect(body.bic).toEqual([{ kind: "principal", entityId: null, label: null }]);
  });
});

describe("BIC is the canonical PartyRef identity, never a guess", () => {
  it("sends an unresolved party for a typed name, never a fabricated entityId", async () => {
    const spy = stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("capture-constraint-details-toggle"));
    await fillRequired(user);
    await user.selectOptions(screen.getByTestId("capture-constraint-bic"), "other");
    await user.type(screen.getByTestId("capture-constraint-bic-other"), "Jordan Blake");
    await user.click(screen.getByTestId("capture-constraint-save"));

    await waitFor(() => expect(postCalls(spy)).toHaveLength(1));
    expect(postBody(spy).bic).toEqual([
      { kind: "unresolved", entityId: null, label: "Jordan Blake" },
    ]);
  });
});

describe("Project change clears Category and Details options", () => {
  it("clears Category, keeps a Principal-scoped BIC selection", async () => {
    stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    await waitFor(() =>
      expect(within(screen.getByTestId("capture-constraint-category")).getByText("1 · Design")).toBeInTheDocument(),
    );
    await user.selectOptions(screen.getByTestId("capture-constraint-category"), CATEGORY_A);
    await user.click(screen.getByTestId("capture-constraint-details-toggle"));
    await user.selectOptions(screen.getByTestId("capture-constraint-bic"), "me");
    await user.selectOptions(screen.getByTestId("capture-constraint-status"), "pending");

    await user.selectOptions(screen.getByTestId("capture-project-select"), PROJECT_B);

    await waitFor(() => expect(screen.getByTestId("capture-constraint-category")).toHaveValue(""));
    expect(screen.getByTestId("capture-constraint-bic")).toHaveValue("me");
    expect(screen.getByTestId("capture-constraint-status")).toHaveValue("identified");
  });
});

describe("the success Project name comes from the persisted response, not the picker", () => {
  /**
   * `PC-CM-CAPTURE-PROJECT-AC-011` (corrective, Manager ruling, Drive
   * Artifact 23 §9/§11): a browser success state MUST NOT claim a Project
   * association merely because the picker held one before submission. The
   * picker/session is left at Project A throughout; the stubbed create
   * response decodes to Project B's id — a different Project, with a
   * visibly different name ("North Tower" vs. "Harbor Migration") — so a
   * success screen reading the picker instead of the decoded response would
   * fail this assertion, not pass it by coincidence.
   */
  it("shows the response's Project name, never the picker's, when they differ", async () => {
    stubFetch({ postResponses: [{ body: confirmedBody({ projectId: PROJECT_B }), status: 200 }] });
    const user = userEvent.setup();
    render(<Harness projectId={PROJECT_A} />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    const projectRow = await screen.findByTestId("capture-constraint-success-project");
    await waitFor(() => expect(projectRow).toHaveTextContent("North Tower"));
    expect(projectRow).not.toHaveTextContent("Harbor Migration");
  });

  it("shows no Project row when the persisted record carries no Project", async () => {
    const base = confirmedBody();
    const noProjectBody = {
      ...base,
      constraint: { ...base.constraint, projectId: null, categoryId: null },
      // The real backend's receipt and record always agree on Project; kept
      // consistent here too, still null, together.
      receipt: { ...base.receipt, projectId: null },
    };
    stubFetch({ postResponses: [{ body: noProjectBody, status: 200 }] });
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    await screen.findByTestId("capture-constraint-success");
    expect(screen.queryByTestId("capture-constraint-success-project")).toBeNull();
  });
});

/**
 * Pins the real BFF wire shape end to end (corrective-2): `postConstraint()`/
 * `readConfirmedSummary()` must read the response **directly** — the real
 * shape `invokeGateway`/`decodeCapability` already produces server-side —
 * and must never re-decode it client-side (that decoder expects raw
 * snake_case and fails unconditionally against this already-camelCase
 * shape, which is exactly the regression this test exists to catch).
 */
describe("the create response is read as the real BFF sends it, never re-decoded", () => {
  it("renders success from the exact shape the real decodeConstraintsCreatePublished produces", async () => {
    const body = realBffCreatePublishedBody();
    stubFetch({ postResponses: [{ body, status: 200 }] });
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    // The committed Python fixture's own Code — proving this reads the real,
    // decoder-produced shape rather than a hand-typed stand-in for it.
    const success = await screen.findByTestId("capture-constraint-success");
    expect(success).toHaveTextContent("2.01");
    expect(screen.queryByTestId("capture-constraint-refused")).toBeNull();
    expect(screen.queryByTestId("capture-constraint-unavailable")).toBeNull();
  });
});

describe("success is derived only from the authoritative response", () => {
  it("shows a read-only summary and no internal id by default", async () => {
    stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    const success = await screen.findByTestId("capture-constraint-success");
    expect(success).toHaveTextContent("1.1");
    expect(success.textContent).not.toContain(CONSTRAINT_ID);
  });

  it("shows the internal id only under diagnostics", async () => {
    diagnostics.enabled = true;
    stubFetch();
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    const success = await screen.findByTestId("capture-constraint-success");
    expect(success.textContent).toContain(CONSTRAINT_ID);
  });

  it("offers Open Constraint and Close, both of which close Capture", async () => {
    stubFetch();
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));
    await screen.findByTestId("capture-constraint-success");

    await user.click(screen.getByTestId("capture-constraint-open"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(navigation.push).toHaveBeenCalledWith(
      expect.stringContaining(`constraint=${CONSTRAINT_ID}`),
    );
  });

  it("Close alone also closes Capture, without navigating", async () => {
    stubFetch();
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));
    await screen.findByTestId("capture-constraint-success");

    await user.click(screen.getByTestId("capture-constraint-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(navigation.push).not.toHaveBeenCalled();
  });
});

describe("a refusal preserves every authored value", () => {
  it("keeps Description and the chosen Category after a validation refusal", async () => {
    stubFetch({
      postResponses: [
        {
          status: 422,
          body: { error: { errorClass: "validation", code: "invalid_request", message: "synthetic refusal" } },
        },
      ],
    });
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    expect(await screen.findByTestId("capture-constraint-refused")).toBeInTheDocument();
    expect(screen.getByTestId("capture-constraint-description")).toHaveValue(
      "synthetic constraint description",
    );
    expect(screen.getByTestId("capture-constraint-category")).toHaveValue(CATEGORY_A);
  });
});

describe("an unreachable backend is ambiguous, not a refusal", () => {
  it("offers Retry, which resends the same idempotency key, and Discard attempt", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      const method = String(init?.method ?? "GET").toUpperCase();
      if (path.startsWith("/api/projects/")) {
        return new Response(JSON.stringify({ project: { name: "Harbor Migration" } }), { status: 200 });
      }
      if (path.startsWith("/api/projects")) {
        return new Response(JSON.stringify({ projects: [], nextCursor: null }), { status: 200 });
      }
      if (path.includes("/constraint-categories")) {
        return new Response(JSON.stringify(categoriesBody(PROJECT_A)), { status: 200 });
      }
      if (method === "POST" && path.includes("/constraints")) {
        throw new TypeError("network error");
      }
      return new Response("{}", { status: 200 });
    });
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    await user.click(screen.getByTestId("capture-constraint-save"));

    expect(await screen.findByTestId("capture-constraint-unavailable")).toBeInTheDocument();
    const firstKey = postBody(spy).idempotencyKey;
    expect(screen.getByTestId("capture-constraint-description")).toBeDisabled();

    await user.click(screen.getByTestId("capture-constraint-retry"));
    await waitFor(() => expect(postCalls(spy)).toHaveLength(2));
    expect(postBody(spy, 1).idempotencyKey).toBe(firstKey);

    await user.click(screen.getByTestId("capture-constraint-discard-attempt"));
    await waitFor(() => expect(screen.getByTestId("capture-constraint-description")).toBeEnabled());
    expect(screen.getByTestId("capture-constraint-description")).toHaveValue(
      "synthetic constraint description",
    );
  });
});

describe("one lock per mounted instance", () => {
  it("issues exactly one create request when Save is double-activated", async () => {
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      const method = String(init?.method ?? "GET").toUpperCase();
      if (path.startsWith("/api/projects")) {
        return new Response(JSON.stringify({ projects: [], nextCursor: null }), { status: 200 });
      }
      if (path.includes("/constraint-categories")) {
        return new Response(JSON.stringify(categoriesBody(PROJECT_A)), { status: 200 });
      }
      if (method === "POST" && path.includes("/constraints")) return gate;
      return new Response("{}", { status: 200 });
    });
    const user = userEvent.setup();
    render(<Harness />);
    await fillRequired(user);
    const save = screen.getByTestId("capture-constraint-save");
    await act(async () => {
      save.click();
      save.click();
      save.click();
    });

    expect(postCalls(spy)).toHaveLength(1);
    release(new Response(JSON.stringify(confirmedBody()), { status: 200 }));
    await screen.findByTestId("capture-constraint-success");
    expect(postCalls(spy)).toHaveLength(1);
  });
});

describe("cancelling a dirty Quick Constraint requires explicit discard", () => {
  it("keeps the form open when discard is declined, closes it when confirmed", async () => {
    stubFetch();
    const user = userEvent.setup();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<Harness onClose={onClose} />);
    await user.type(await screen.findByTestId("capture-constraint-description"), "unsent text");

    await user.click(screen.getByTestId("capture-constraint-cancel"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByTestId("capture-constraint-description")).toHaveValue("unsent text");

    await user.click(screen.getByTestId("capture-constraint-cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("cancels without confirming when nothing was authored", async () => {
    stubFetch();
    const user = userEvent.setup();
    const onClose = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm");
    render(<Harness onClose={onClose} />);
    await screen.findByTestId("capture-constraint-description");

    await user.click(screen.getByTestId("capture-constraint-cancel"));
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("Back returns to the chooser", () => {
  it("calls the supplied onBack", async () => {
    stubFetch();
    const user = userEvent.setup();
    const onBack = vi.fn();
    render(<Harness onBack={onBack} />);
    await user.click(await screen.findByTestId("capture-entry-back"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
