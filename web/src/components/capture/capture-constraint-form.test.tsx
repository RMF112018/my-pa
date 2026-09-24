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
import { CaptureConstraintForm } from "@/components/capture/capture-constraint-form";
import { beginCaptureExperience, captureSessionReducer } from "@/lib/capture/session";
import { ConstraintRuntimeProvider } from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";

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

function confirmedBody(overrides: Record<string, unknown> = {}) {
  return {
    shape: "backend",
    disposition: "applied",
    constraint: {
      constraintId: CONSTRAINT_ID,
      lifecycleState: "identified",
      origin: "product",
      createdAt: "2026-09-24T12:00:00Z",
      updatedAt: "2026-09-24T12:00:00Z",
      version: 1,
      projectId: PROJECT_A,
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
      ...overrides,
    },
    receipt: {
      historyId: "chist_aaaaaaaa11111111",
      constraintId: CONSTRAINT_ID,
      operation: "create",
      actor: "principal",
      outcome: "applied",
      beforeVersion: 0,
      afterVersion: 1,
      occurredAt: "2026-09-24T12:00:00Z",
      projectId: PROJECT_A,
      revisionId: null,
      safeFailureReason: null,
    },
    disclosure: {},
  };
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
