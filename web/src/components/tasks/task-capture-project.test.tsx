/**
 * T12 — Capture-launched Task creates and the Project that wins (C08).
 *
 * The case this file exists for: a Task create against Project A is already
 * under way, and Capture launches again proposing Project B. The unresolved
 * intent wins. It is not moved, it is not reissued under a new key, and the
 * surface says so rather than showing B over a request that named A.
 *
 * The runtime, the intent store and the canonical decoder are all real here;
 * only the network is faked.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskCreateSheet, TASK_CREATE_FROZEN_PROJECT_NOTE } from "@/components/tasks/task-create-sheet";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { taskCreateResponse } from "@/lib/task/testing/task-mutation-fixture";

const PRINCIPAL = "aaaa0001-0000-0000-0000-000000000001";
const SESSION_EPOCH = "syn-session-epoch";
const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";

const PROJECTS = [
  { projectId: PROJECT_A, name: "North tower" },
  { projectId: PROJECT_B, name: "South slab" },
];

interface Harness {
  readonly fetcher: ReturnType<typeof vi.fn>;
  readonly releaseCreate: (body?: unknown) => void;
}

/** Answers Project reads immediately; holds the create POST until released. */
function gatedStack(): Harness {
  let release!: (body: unknown) => void;
  const gate = new Promise<unknown>((resolve) => {
    release = resolve;
  });
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/tasks" && String(init?.method).toUpperCase() === "POST") {
      const body = await gate;
      return new Response(JSON.stringify(body), { status: 200 });
    }
    if (path.startsWith("/api/projects/")) {
      const id = path.slice("/api/projects/".length);
      const found = PROJECTS.find((row) => row.projectId === id);
      return found
        ? new Response(JSON.stringify({ project: { name: found.name } }), { status: 200 })
        : new Response("{}", { status: 404 });
    }
    if (path.startsWith("/api/projects")) {
      return new Response(JSON.stringify({ projects: PROJECTS, nextCursor: null }), { status: 200 });
    }
    return new Response(JSON.stringify({ tasks: [], commitments: [] }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetcher);
  return {
    fetcher,
    releaseCreate: (body = taskCreateResponse({ projectId: PROJECT_A })) => release(body),
  };
}

/** Every request answers immediately. */
function immediateStack() {
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/tasks" && String(init?.method).toUpperCase() === "POST") {
      const sent = JSON.parse(String(init?.body ?? "{}")) as { projectId?: string };
      return new Response(
        JSON.stringify(taskCreateResponse({ projectId: sent.projectId ?? null })),
        { status: 200 },
      );
    }
    if (path.startsWith("/api/projects/")) {
      const id = path.slice("/api/projects/".length);
      const found = PROJECTS.find((row) => row.projectId === id);
      return found
        ? new Response(JSON.stringify({ project: { name: found.name } }), { status: 200 })
        : new Response("{}", { status: 404 });
    }
    if (path.startsWith("/api/projects")) {
      return new Response(JSON.stringify({ projects: PROJECTS, nextCursor: null }), { status: 200 });
    }
    return new Response(JSON.stringify({ tasks: [], commitments: [] }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function createPosts(fetcher: ReturnType<typeof vi.fn>) {
  return fetcher.mock.calls
    .filter(
      ([input, init]) =>
        String(input) === "/api/tasks" &&
        String((init as RequestInit | undefined)?.method).toUpperCase() === "POST",
    )
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>);
}

function renderSheet(context?: { projectId?: string }) {
  const onBack = vi.fn();
  const view = render(
    <TaskRuntimeProvider principalId={PRINCIPAL} sessionEpoch={SESSION_EPOCH}>
      <TaskCreateSheet
        open
        onOpenChange={vi.fn()}
        entry="capture"
        context={context}
        principalId={PRINCIPAL}
        sessionEpoch={1}
        onBack={onBack}
      />
    </TaskRuntimeProvider>,
  );
  return { onBack, view };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Capture passes its Project into the canonical create", () => {
  it("sends the launcher's Project", async () => {
    const user = userEvent.setup();
    const fetcher = immediateStack();
    renderSheet({ projectId: PROJECT_A });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));
    expect(createPosts(fetcher)[0]!.projectId).toBe(PROJECT_A);
  });

  it("omits the field entirely for No Project rather than sending null", async () => {
    const user = userEvent.setup();
    const fetcher = immediateStack();
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));
    // The Task contract admits a string-only optional Project. Omission is No
    // Project; null would be a value the route does not accept.
    expect(createPosts(fetcher)[0]).not.toHaveProperty("projectId");
  });

  it("lets the Principal change the Project before dispatch", async () => {
    const user = userEvent.setup();
    const fetcher = immediateStack();
    renderSheet({ projectId: PROJECT_A });

    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(select).toHaveValue(PROJECT_A));
    await user.selectOptions(select, PROJECT_B);
    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));
    expect(createPosts(fetcher)[0]!.projectId).toBe(PROJECT_B);
  });
});

describe("a frozen Project A wins over a launcher proposing B", () => {
  it("resumes A, says so, and does not edit or reissue it", async () => {
    const user = userEvent.setup();
    const { releaseCreate, fetcher } = gatedStack();
    const { view } = renderSheet({ projectId: PROJECT_A });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));
    const firstKey = createPosts(fetcher)[0]!.idempotencyKey;
    expect(createPosts(fetcher)[0]!.projectId).toBe(PROJECT_A);

    // Capture launches again, now proposing B, while A is still unresolved.
    view.rerender(
      <TaskRuntimeProvider principalId={PRINCIPAL} sessionEpoch={SESSION_EPOCH}>
        <TaskCreateSheet
          open
          onOpenChange={vi.fn()}
          entry="capture"
          context={{ projectId: PROJECT_B }}
          principalId={PRINCIPAL}
          sessionEpoch={1}
          onBack={vi.fn()}
        />
      </TaskRuntimeProvider>,
    );

    // A is still what the surface shows, and it cannot be edited.
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(select).toHaveValue(PROJECT_A));
    expect(select).toBeDisabled();
    // And no second create was issued by the relaunch.
    expect(createPosts(fetcher)).toHaveLength(1);

    releaseCreate();
    await waitFor(() => expect(createPosts(fetcher)[0]!.idempotencyKey).toBe(firstKey));
  });

  it("explains that the create was not moved", async () => {
    const user = userEvent.setup();
    const { fetcher } = gatedStack();

    /** Two launchers over the one shared intent store, as the shell mounts them. */
    function TwoLaunchers({ secondOpen }: { secondOpen: boolean }) {
      return (
        <TaskRuntimeProvider principalId={PRINCIPAL} sessionEpoch={SESSION_EPOCH}>
          <TaskCreateSheet
            open
            onOpenChange={vi.fn()}
            entry="capture"
            context={{ projectId: PROJECT_A }}
            principalId={PRINCIPAL}
            sessionEpoch={1}
          />
          <TaskCreateSheet
            open={secondOpen}
            onOpenChange={vi.fn()}
            entry="capture"
            context={{ projectId: PROJECT_B }}
            principalId={PRINCIPAL}
            sessionEpoch={1}
          />
        </TaskRuntimeProvider>
      );
    }

    const view = render(<TwoLaunchers secondOpen={false} />);
    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));

    // The second launcher opens proposing B while A is unresolved.
    view.rerender(<TwoLaunchers secondOpen />);

    const note = await screen.findByTestId("task-create-frozen-project");
    expect(note).toHaveTextContent(TASK_CREATE_FROZEN_PROJECT_NOTE);
    // And still exactly one create.
    expect(createPosts(fetcher)).toHaveLength(1);
  });

  it("retries an ambiguous create with the same key and the same Project", async () => {
    const user = userEvent.setup();
    const { releaseCreate, fetcher } = gatedStack();
    renderSheet({ projectId: PROJECT_A });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));

    // An unreadable success: ambiguous, not a refusal.
    releaseCreate({ shape: "backend", nothing: true });
    const retry = await screen.findByRole("button", { name: "Retry same create" });
    await user.click(retry);

    await waitFor(() => expect(createPosts(fetcher).length).toBeGreaterThanOrEqual(2));
    const posts = createPosts(fetcher);
    expect(posts[1]!.idempotencyKey).toBe(posts[0]!.idempotencyKey);
    expect(posts[1]!.projectId).toBe(PROJECT_A);
  });
});

describe("the result gate runs before anything is announced", () => {
  it("does not confirm a create whose canonical Project is not the one requested", async () => {
    const user = userEvent.setup();
    const { releaseCreate } = gatedStack();
    renderSheet({ projectId: PROJECT_A });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));
    // A canonical answer that names a different Project.
    releaseCreate(taskCreateResponse({ projectId: PROJECT_B }));

    // Ambiguous, held for the same retry — never "Task created".
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Retry same create" })).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("mutation-feedback-region")?.textContent ?? "").not.toContain(
      "Task created",
    );
  });

  it("confirms a create whose canonical Project matches", async () => {
    const user = userEvent.setup();
    immediateStack();
    renderSheet({ projectId: PROJECT_A });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    const region = await screen.findByTestId("mutation-feedback-region");
    await waitFor(() => expect(region.textContent).toContain("Task created"));
  });
});

describe("Back carries what the sheet actually holds", () => {
  it("returns the editable draft's Project", async () => {
    const user = userEvent.setup();
    immediateStack();
    const { onBack } = renderSheet({ projectId: PROJECT_A });

    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(select).toHaveValue(PROJECT_A));
    await user.selectOptions(select, PROJECT_B);
    await user.click(screen.getByTestId("task-create-back"));

    expect(onBack).toHaveBeenCalledWith({ projectId: PROJECT_B });
  });

  it("returns No Project as null", async () => {
    const user = userEvent.setup();
    immediateStack();
    const { onBack } = renderSheet();

    await screen.findByTestId("capture-project-select");
    await user.click(screen.getByTestId("task-create-back"));

    expect(onBack).toHaveBeenCalledWith({ projectId: null });
  });

  it("returns the frozen request's Project while an intent is unresolved", async () => {
    const user = userEvent.setup();
    const { fetcher } = gatedStack();
    const { onBack } = renderSheet({ projectId: PROJECT_A });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));

    await user.click(screen.getByTestId("task-create-back"));
    expect(onBack).toHaveBeenCalledWith({ projectId: PROJECT_A });
  });
});

describe("no capture happens on this path", () => {
  it("never posts to /api/capture and never touches the offline queue", async () => {
    const user = userEvent.setup();
    const fetcher = immediateStack();
    renderSheet({ projectId: PROJECT_A });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createPosts(fetcher)).toHaveLength(1));

    expect(
      fetcher.mock.calls.some(([input]) => String(input).startsWith("/api/capture")),
    ).toBe(false);
  });
});
