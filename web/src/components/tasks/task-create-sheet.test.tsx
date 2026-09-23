import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { taskCreateResponse } from "@/lib/task/testing/task-mutation-fixture";
import { TaskCreateSheet } from "@/components/tasks/task-create-sheet";
import {
  TaskRuntimeProvider,
  useTaskRuntime,
  type TaskRuntimeValue,
} from "@/components/work/task-runtime-provider";
import { browserWorkClock } from "@/lib/api/work-client";
import type { TaskCreateRequest } from "@/lib/task/create-intent";
import { civilDayEndIso, civilDayInZone } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// The create surface verifies the whole canonical mutation before it announces
// anything, so the stub has to be one.
const CREATED = taskCreateResponse();

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

/**
 * Acceptance traceability: TASK-AC-001, TASK-AC-002, TASK-AC-003, TASK-AC-004,
 * TASK-AC-005, TASK-AC-006, TASK-AC-010.
 *
 * The canonical create form offers exactly Title, Description, Priority and Due (001, 004),
 * names priorities in product language (002), sends no origin, commitment or role (003),
 * creates through /api/tasks whether entered from Work or from Capture (005), issues exactly
 * one POST when Create is double-activated (006), and serializes a chosen Due as the end of
 * that civil day (010).
 */
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

  it("renders Priority as a labeled native combobox through the shared Select, keeping its 44px coarse target", () => {
    vi.stubGlobal("fetch", immediateFetch());
    renderSheet();

    // Priority moved from a raw <select> to the shared Select primitive. The
    // accessible role and name must be unchanged, and the caller's min-h-11
    // coarse-pointer target must survive the primitive's class composition.
    const select = screen.getByRole("combobox", { name: "Priority" });
    expect(select.tagName).toBe("SELECT");
    expect(select).toBe(screen.getByLabelText("Priority"));
    expect(select.className).toMatch(/\bmin-h-11\b/);
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
    // The confirmed result is now the *verified* canonical mutation, not the raw
    // body: the surface only announces what it could check.
    await waitFor(() =>
      expect(onConfirmed).toHaveBeenCalledWith(
        expect.objectContaining({
          task: expect.objectContaining({ task_id: CREATED.task.task_id, project_id: null }),
          history: expect.objectContaining({ action: "create", outcome: "applied" }),
          replayed: false,
        }),
      ),
    );
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

/**
 * WP-POSTUX-02, finding F-001: one shared create intent across every mounted
 * launcher.
 *
 * `TaskCreateSheet` is mounted independently by Work and by AppShell/Capture,
 * over one runtime `CreateIntentStore`. An unresolved intent is therefore a
 * property of the session, not of whichever copy of the form happens to be on
 * screen: opening a second (or re-opening the same) sheet must resume the
 * unresolved create — with the exact frozen request visible — rather than mint
 * a fresh intent that would create the Task twice.
 *
 * Everything here is synthetic.
 */

/** The browser zone for the resume cases; its civil day differs from UTC's. */
const RESUMED_ZONE = "America/New_York";
/** 2026-03-10 23:59:59 in New York — an instant whose *UTC* date is 2026-03-11. */
const RESUMED_DUE_DAY = "2026-03-10";
const RESUMED_DUE_ISO = civilDayEndIso(RESUMED_DUE_DAY, RESUMED_ZONE);

const RESUMED_REQUEST: TaskCreateRequest = {
  title: "Resumed create from Capture",
  description: "first\nsecond",
  priority: "p1",
  dueAt: RESUMED_DUE_ISO,
};

const REAL_DATE_TIME_FORMAT = Intl.DateTimeFormat;

/**
 * Fix the zone the *browser* reports, leaving explicit-zone formatting alone.
 *
 * `browserWorkClock()` asks `Intl.DateTimeFormat().resolvedOptions()`, so only
 * the no-zone default is substituted; `civilDayInZone` / `civilDayEndIso` pass
 * their own `timeZone` and keep answering for it.
 */
function stubBrowserTimezone(timezone: string): void {
  const patched = function (
    locales?: Intl.LocalesArgument,
    options?: Intl.DateTimeFormatOptions,
  ) {
    return new REAL_DATE_TIME_FORMAT(
      locales,
      options?.timeZone ? options : { ...options, timeZone: timezone },
    );
  } as unknown as typeof Intl.DateTimeFormat;
  patched.supportedLocalesOf = REAL_DATE_TIME_FORMAT.supportedLocalesOf.bind(
    REAL_DATE_TIME_FORMAT,
  );
  Object.defineProperty(Intl, "DateTimeFormat", {
    value: patched,
    configurable: true,
    writable: true,
  });
}

function restoreBrowserTimezone(): void {
  Object.defineProperty(Intl, "DateTimeFormat", {
    value: REAL_DATE_TIME_FORMAT,
    configurable: true,
    writable: true,
  });
}

/**
 * The runtime under a provider, with the sheets mounted separately so a session
 * can be seeded *before* any create surface exists — which is the real order:
 * Capture starts the create, Work's already-mounted sheet is opened afterwards.
 */
function renderRuntimeHarness(): {
  readonly runtime: () => TaskRuntimeValue;
  readonly revalidate: ReturnType<typeof vi.fn>;
  readonly show: (ui: React.ReactNode) => void;
} {
  const revalidate = vi.fn();
  const box: { current?: TaskRuntimeValue } = {};

  function Probe() {
    const runtime = useTaskRuntime();
    box.current = runtime;
    useEffect(
      () => runtime.reconciliation.registerActiveTaskQuery("probe-task-list", revalidate),
      [runtime],
    );
    return null;
  }

  const tree = (mounted: React.ReactNode) => (
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <Probe />
      {mounted}
    </TaskRuntimeProvider>
  );

  const view = render(tree(null));
  return {
    runtime: () => {
      if (!box.current) throw new Error("runtime was not captured");
      return box.current;
    },
    revalidate,
    show: (ui) => view.rerender(tree(ui)),
  };
}

/** An unresolved (ambiguous) create the Principal started somewhere else. */
async function seedAmbiguousSession(runtime: TaskRuntimeValue) {
  const session = runtime.createIntents.openSession(RESUMED_REQUEST);
  await expect(
    session.submit(async () => {
      // Transport loss: the create may still have been applied.
      throw new TypeError("Failed to fetch");
    }),
  ).rejects.toThrow();
  expect(session.getPhase()).toBe("ambiguous");
  expect(session.getFrozenRequest()?.title).toBe(RESUMED_REQUEST.title);
  return session;
}

/** Success feedback items published for a confirmed create, whoever published them. */
function createConfirmedFeedbackCount(): number {
  return document.querySelectorAll(
    '[data-testid^="mutation-feedback-item-task:create:confirmed:"]',
  ).length;
}

function forms(): HTMLElement[] {
  return screen.getAllByTestId("task-create-sheet");
}

function primaryAction(form: HTMLElement): HTMLElement {
  // `hidden: true`: with two modal sheets on screen Radix marks the other one
  // aria-hidden, which is an overlay artifact, not the behaviour under test.
  return within(form).getByRole("button", {
    name: /^(Create|Retry same create|Creating…)$/,
    hidden: true,
  });
}

describe("TaskCreateSheet resumes the session's unresolved create", () => {
  afterEach(() => {
    restoreBrowserTimezone();
  });

  it("adopts an unresolved session held by another launcher when it is opened, minting no second intent", async () => {
    const user = userEvent.setup();
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    const harness = renderRuntimeHarness();

    // Work keeps its create surface mounted while closed.
    harness.show(
      <TaskCreateSheet open={false} onOpenChange={vi.fn()} entry="work" />,
    );
    const seeded = await seedAmbiguousSession(harness.runtime());

    // The Principal now opens that already-mounted sheet.
    harness.show(<TaskCreateSheet open onOpenChange={vi.fn()} entry="work" />);
    await screen.findByTestId("task-create-sheet");

    // The one unresolved intent is resumed, not replaced.
    expect(screen.getByRole("button", { name: "Retry same create" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Retry same create" }));
    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    expect(postBodies(fetcher)[0].idempotencyKey).toBe(seeded.idempotencyKey);
    expect(postBodies(fetcher)[0].title).toBe(RESUMED_REQUEST.title);
  });

  it("shows the resumed intent's exact frozen Title, Description and Priority", async () => {
    vi.stubGlobal("fetch", immediateFetch());
    const harness = renderRuntimeHarness();

    harness.show(<TaskCreateSheet open={false} onOpenChange={vi.fn()} entry="work" />);
    await seedAmbiguousSession(harness.runtime());
    harness.show(<TaskCreateSheet open onOpenChange={vi.fn()} entry="work" />);
    await screen.findByTestId("task-create-sheet");

    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(
      RESUMED_REQUEST.title,
    );
    expect((screen.getByLabelText("Description") as HTMLTextAreaElement).value).toBe(
      "first\nsecond",
    );
    const priority = screen.getByLabelText("Priority") as HTMLSelectElement;
    expect(priority.value).toBe("p1");
    // Still product language, never the raw token.
    expect(priority.selectedOptions[0]?.textContent).toBe("Critical");
  });

  it("shows the resumed Due as its civil day in the browser zone, not its UTC date", async () => {
    stubBrowserTimezone(RESUMED_ZONE);
    vi.stubGlobal("fetch", immediateFetch());
    // The fixture only proves anything if the two answers genuinely differ.
    expect(RESUMED_DUE_ISO.slice(0, 10)).toBe("2026-03-11");
    expect(civilDayInZone(RESUMED_DUE_ISO, RESUMED_ZONE)).toBe(RESUMED_DUE_DAY);
    expect(browserWorkClock().timezone).toBe(RESUMED_ZONE);

    const harness = renderRuntimeHarness();
    harness.show(<TaskCreateSheet open={false} onOpenChange={vi.fn()} entry="work" />);
    await seedAmbiguousSession(harness.runtime());
    harness.show(<TaskCreateSheet open onOpenChange={vi.fn()} entry="work" />);
    await screen.findByTestId("task-create-sheet");

    const due = screen.getByLabelText("Due") as HTMLInputElement;
    expect(due.value).toBe(RESUMED_DUE_DAY);
    // A UTC truncation of the frozen instant would answer the next day.
    expect(due.value).not.toBe(RESUMED_DUE_ISO.slice(0, 10));
  });

  it("keeps two mounted sheets on the one session, before and after it settles", async () => {
    // Two modal sheets stack, and Radix drops `pointer-events` on the lower one.
    // That is an overlay artifact of mounting both at once, not the behaviour
    // under test, so the CSS pointer check is switched off for these two cases.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    const harness = renderRuntimeHarness();

    harness.show(
      <>
        <TaskCreateSheet open={false} onOpenChange={vi.fn()} entry="work" />
        <TaskCreateSheet open={false} onOpenChange={vi.fn()} entry="capture" onBack={vi.fn()} />
      </>,
    );
    await seedAmbiguousSession(harness.runtime());
    harness.show(
      <>
        <TaskCreateSheet open onOpenChange={vi.fn()} entry="work" />
        <TaskCreateSheet open onOpenChange={vi.fn()} entry="capture" onBack={vi.fn()} />
      </>,
    );
    await waitFor(() => expect(forms()).toHaveLength(2));

    // Both launchers show the same unresolved create.
    for (const form of forms()) {
      expect(primaryAction(form).textContent).toBe("Retry same create");
      expect((within(form).getByLabelText("Title") as HTMLInputElement).value).toBe(
        RESUMED_REQUEST.title,
      );
    }

    // One of them settles it.
    await user.click(primaryAction(forms()[0]));
    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));

    // The other observes the settle instead of holding a divergent local phase.
    await waitFor(() => {
      const other = forms()[1];
      expect(primaryAction(other).textContent).toBe("Create");
      expect((within(other).getByLabelText("Title") as HTMLInputElement).value).toBe("");
    });
  });

  it("reconciles and announces a confirmed create exactly once across two mounted sheets", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const fetcher = immediateFetch();
    vi.stubGlobal("fetch", fetcher);
    const harness = renderRuntimeHarness();

    harness.show(
      <>
        <TaskCreateSheet open={false} onOpenChange={vi.fn()} entry="work" />
        <TaskCreateSheet open={false} onOpenChange={vi.fn()} entry="capture" onBack={vi.fn()} />
      </>,
    );
    await seedAmbiguousSession(harness.runtime());
    harness.show(
      <>
        <TaskCreateSheet open onOpenChange={vi.fn()} entry="work" />
        <TaskCreateSheet open onOpenChange={vi.fn()} entry="capture" onBack={vi.fn()} />
      </>,
    );
    await waitFor(() => expect(forms()).toHaveLength(2));

    // The Principal retypes the same Task in each surface. Neither keystroke may
    // move a frozen, unresolved intent, and neither surface owns its own create.
    for (const form of forms()) {
      fireEvent.change(within(form).getByLabelText("Title"), {
        target: { value: RESUMED_REQUEST.title },
      });
    }

    await user.click(primaryAction(forms()[0]));
    await waitFor(() => expect(postBodies(fetcher)).toHaveLength(1));
    await user.click(primaryAction(forms()[1]));

    // One human intent: one reconciliation pass and one success announcement,
    // however many launchers were on screen.
    await waitFor(() => expect(harness.revalidate).toHaveBeenCalledTimes(1));
    expect(harness.revalidate).toHaveBeenCalledTimes(1);
    expect(createConfirmedFeedbackCount()).toBe(1);
    // And one idempotency key across every POST the session ever issued.
    expect(Array.from(new Set(postBodies(fetcher).map((body) => String(body.idempotencyKey))))).toHaveLength(1);
  });

  it("drops the stale announcement once the shared retry fails definitively", async () => {
    // The observer branch used to fall through without touching anything when a
    // session left `ambiguous`/`pending` for `failed`. The retry announces
    // "Creating task…" on its way through pending, so an observer was left
    // claiming a create was still in flight under a session that had since been
    // definitively refused. Asserting the live region is gone catches that;
    // asserting only the absence of the ambiguous copy would not, because the
    // pending copy had already replaced it.
    const harness = renderRuntimeHarness();
    const runtime = harness.runtime();
    const seeded = await seedAmbiguousSession(runtime);

    harness.show(<TaskCreateSheet open onOpenChange={() => {}} entry="work" />);
    await waitFor(() => expect(primaryAction(sheet())).toHaveTextContent("Retry same create"));
    expect(screen.getByRole("status")).toHaveTextContent(/may still have succeeded/i);

    // Someone else's retry comes back definitively refused: not applied, not ambiguous.
    await expect(
      seeded.retry(async () => {
        throw Object.assign(new Error("bad title"), { status: 400, code: "validation" });
      }),
    ).rejects.toMatchObject({ status: 400 });

    await waitFor(() => {
      // No announcement at all: not the ambiguous copy, not a stale "Creating task…".
      expect(screen.queryByRole("status")).toBeNull();
    });
  });

  it("mints no replacement intent when the shared create confirms in another launcher", async () => {
    // One confirm emits more than once. Minting a session per emission stranded a
    // fresh draft in the store on every one of them, and `pruneTerminal` never
    // reclaims a draft that was never dispatched.
    const harness = renderRuntimeHarness();
    const runtime = harness.runtime();
    const seeded = await seedAmbiguousSession(runtime);

    harness.show(<TaskCreateSheet open onOpenChange={() => {}} entry="work" />);
    await waitFor(() => expect(primaryAction(sheet())).toHaveTextContent("Retry same create"));

    const mint = vi.spyOn(runtime.createIntents, "openSession");
    const outcome = await seeded.retry(async () => CREATED);
    expect(outcome.refused).toBe(false);

    await waitFor(() => expect(screen.queryByText(/may still have succeeded/i)).toBeNull());
    // The observer settles; it does not mint. The next open re-resolves instead.
    expect(mint).not.toHaveBeenCalled();
  });
});
