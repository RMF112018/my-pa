import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskCreateSheet } from "@/components/tasks/task-create-sheet";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { browserWorkClock } from "@/lib/api/work-client";
import { civilDayEndIso } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CREATED = {
  task: {
    task_id: "tsk_bbbbbbbb22222222",
    title: "Coordinate the review",
    lifecycle_state: "open",
  },
};

/** Every create POST answers immediately; nothing else is expected to be called. */
function immediateFetch() {
  return vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path === "/api/tasks" && init?.method === "POST") return Response.json(CREATED);
    throw new Error(`unexpected request: ${path} ${init?.method ?? "GET"}`);
  });
}

/** A create POST that only resolves when the test releases it. */
function gatedFetch() {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path === "/api/tasks" && init?.method === "POST") {
      await gate;
      return Response.json(CREATED);
    }
    throw new Error(`unexpected request: ${path} ${init?.method ?? "GET"}`);
  });
  return { fetcher, release };
}

function postBodies(fetcher: ReturnType<typeof immediateFetch>): Record<string, unknown>[] {
  return fetcher.mock.calls
    .filter(([input, init]) => String(input) === "/api/tasks" && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}

function renderSheet(
  props: Partial<React.ComponentProps<typeof TaskCreateSheet>> = {},
): { onOpenChange: ReturnType<typeof vi.fn>; onConfirmed: ReturnType<typeof vi.fn> } {
  const onOpenChange = vi.fn();
  const onConfirmed = vi.fn();
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <TaskCreateSheet
        open
        onOpenChange={onOpenChange}
        onConfirmed={onConfirmed}
        entry="work"
        {...props}
      />
    </TaskRuntimeProvider>,
  );
  return { onOpenChange, onConfirmed };
}

function sheet() {
  return screen.getByTestId("task-create-sheet");
}

describe("TaskCreateSheet", () => {
  it("offers exactly Title, Description, Priority and Due — no Origin, Commitment or Role", () => {
    vi.stubGlobal("fetch", immediateFetch());
    renderSheet();

    expect(screen.getByLabelText("Title")).toBeTruthy();
    expect(screen.getByLabelText("Description")).toBeTruthy();
    expect(screen.getByLabelText("Priority")).toBeTruthy();
    expect(screen.getByLabelText("Due")).toBeTruthy();

    expect(screen.queryByLabelText("Origin")).toBeNull();
    expect(screen.queryByLabelText("Commitment")).toBeNull();
    expect(screen.queryByLabelText("Role")).toBeNull();
    // There is no time affordance: Due is a civil day, not an appointment.
    expect(screen.queryByText("Add time")).toBeNull();
    expect((screen.getByLabelText("Due") as HTMLInputElement).type).toBe("date");
  });

  it("issues no commitments request when the sheet opens", async () => {
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await waitFor(() => expect(screen.getByLabelText("Title")).toBeTruthy());
    expect(fetcher.mock.calls.some(([input]) => String(input).includes("/api/commitments"))).toBe(
      false,
    );
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("names every priority choice in product language and never shows a raw token", () => {
    vi.stubGlobal("fetch", immediateFetch());
    renderSheet();

    const select = screen.getByLabelText("Priority");
    const labels = within(select).getAllByRole("option").map((option) => option.textContent);
    expect(labels).toEqual(["No priority", "Critical", "High", "Medium", "Low"]);
    expect(sheet().textContent ?? "").not.toMatch(/\bp[1-4]\b/);
  });

  it("serializes a chosen priority and omits it when there is no priority", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.selectOptions(screen.getByLabelText("Priority"), "Critical");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(postBodies(fetcher)[0].priority).toBe("p1");

    cleanup();
    fetcher.mockClear();
    renderSheet();
    await user.type(screen.getByLabelText("Title"), "No priority at all");
    await user.selectOptions(screen.getByLabelText("Priority"), "No priority");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(postBodies(fetcher)[0].priority).toBeUndefined();
    expect("priority" in postBodies(fetcher)[0]).toBe(false);
  });

  it("gives Title the initial focus", async () => {
    vi.stubGlobal("fetch", immediateFetch());
    renderSheet();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Title")));
  });

  it("refuses a whitespace-only Title, says so, posts nothing and focuses Title", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    const title = screen.getByLabelText("Title");
    await user.type(title, "   ");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Enter a task title.")).toBeTruthy();
    expect(title.getAttribute("aria-invalid")).toBe("true");
    const describedBy = title.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(String(describedBy))?.textContent).toBe("Enter a task title.");
    expect(fetcher).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(title);
  });

  it("treats Enter in Description as a newline, never as a submit", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    const description = screen.getByLabelText("Description") as HTMLTextAreaElement;
    await user.type(description, "first{Enter}second");

    expect(description.value).toBe("first\nsecond");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("submits once on Enter in Title and preserves the authored description", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await user.type(screen.getByLabelText("Description"), "first{Enter}second");
    await user.type(screen.getByLabelText("Title"), "  Coordinate the review  {Enter}");

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    const body = postBodies(fetcher)[0];
    // Outer trim only: internal whitespace and line breaks are the Principal's.
    expect(body.title).toBe("Coordinate the review");
    expect(body.description).toBe("first\nsecond");
  });

  it("normalizes a whitespace-only Description to an absent description", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.type(screen.getByLabelText("Description"), "   ");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(postBodies(fetcher)[0].description).toBeUndefined();
  });

  it("issues exactly one POST when Create is double-clicked", async () => {
    const user = userEvent.setup();
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.dblClick(screen.getByRole("button", { name: "Create" }));

    release();
    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    // A second dispatch never reaches the network under the same intent.
    expect(postBodies(fetcher)).toHaveLength(1);
  });

  it("serializes Due as the end of the chosen civil day, and omits it once cleared", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    const { timezone } = browserWorkClock();
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    fireEvent.change(screen.getByLabelText("Due"), { target: { value: "2026-09-15" } });
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(postBodies(fetcher)[0].dueAt).toBe(civilDayEndIso("2026-09-15", timezone));

    cleanup();
    fetcher.mockClear();
    renderSheet();
    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    fireEvent.change(screen.getByLabelText("Due"), { target: { value: "2026-09-15" } });
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect((screen.getByLabelText("Due") as HTMLInputElement).value).toBe("");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(postBodies(fetcher)[0].dueAt).toBeUndefined();
  });

  it("creates the Task through /api/tasks and never through /api/capture", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet({ entry: "capture", onBack: vi.fn() });

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(fetcher.mock.calls.filter(([input]) => String(input) === "/api/tasks")).toHaveLength(1);
    expect(fetcher.mock.calls.filter(([input]) => String(input).includes("/api/capture"))).toHaveLength(0);
    // One human intent, one idempotency key.
    expect(String(postBodies(fetcher)[0].idempotencyKey)).toMatch(/^task-create-/);
  });

  it("publishes the confirmed create globally, naming the Task, then closes", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    const { onOpenChange, onConfirmed } = renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    const region = await screen.findByTestId("mutation-feedback-region");
    expect(region.textContent).toContain("Task created: Coordinate the review");
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith(CREATED));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("holds the form busy while the create is in flight and disables Create", async () => {
    const user = userEvent.setup();
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    const creating = await screen.findByRole("button", { name: "Creating…" });
    expect(creating).toBeDisabled();
    expect(sheet().getAttribute("aria-busy")).toBe("true");
    // Fields stay visible, but no longer editable, while the intent is unresolved.
    expect(screen.getByLabelText("Title")).toBeTruthy();
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.getByLabelText("Priority")).toBeDisabled();

    release();
    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
  });

  it("shows a scoped context by its label and never by a raw identifier", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet({
      entry: "scoped_context",
      context: { projectId: "prj_cccccccc33333333", situationId: "sit_dddddddd44444444", label: "Project Atlas" },
    });

    expect(sheet().textContent).toContain("Project Atlas");
    expect(sheet().textContent).not.toContain("prj_cccccccc33333333");
    expect(sheet().textContent).not.toContain("sit_dddddddd44444444");
    expect(sheet().textContent ?? "").not.toMatch(/\bp[1-4]\b/);

    // The ids still travel with the request.
    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(postBodies(fetcher)[0].projectId).toBe("prj_cccccccc33333333");
    expect(postBodies(fetcher)[0].situationId).toBe("sit_dddddddd44444444");
  });

  it("offers Back only for the Capture chooser entry", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", immediateFetch());
    const onBack = vi.fn();

    renderSheet({ entry: "capture", onBack });
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(onBack).toHaveBeenCalledTimes(1);

    cleanup();
    renderSheet({ entry: "work", onBack });
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
  });

  it("sends no principal, origin, commitment or role in the create request", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    renderSheet();

    await user.type(screen.getByLabelText("Title"), "Coordinate the review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    const body = postBodies(fetcher)[0];
    for (const forbidden of ["principalId", "originKind", "originEvidenceRef", "commitmentId", "role"]) {
      expect(body[forbidden]).toBeUndefined();
    }
  });
});
