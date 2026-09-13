/**
 * What Today is allowed to say once the client owns the reading.
 *
 * The whole subject here is the distinction between "the read succeeded and you
 * hold nothing" and every other reason rows might be missing. The server draws
 * it once; this surface has to keep drawing it on every refresh, including the
 * refreshes that fail — which is where it can quietly become a lie, because a
 * failed read and a quiet day produce the same empty array if nobody is careful.
 *
 * Every read below goes through the real `useForegroundRevalidation` and the
 * real `/api/pulse` path; what is stubbed is one HTTP response.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";

import {
  TODAY_EMPTY_COPY,
  TODAY_PULSE_QUERY_ID,
  TodayPulseSurface,
  classifyPulsePayload,
} from "@/components/pulse/today-pulse-surface";
import { TaskRuntimeProvider, useTaskRuntime } from "@/components/work/task-runtime-provider";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { BackendPulseItem, TodayPulseAnswer } from "@/contracts/views";

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = vi.fn(async () => pulseResponse([]));
  vi.stubGlobal("fetch", fetchSpy);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function item(overrides: Partial<BackendPulseItem> = {}): BackendPulseItem {
  return {
    pulseId: "puls_aaaaaaaa11111111",
    itemType: "commitment",
    itemRef: "cmt_aaaaaaaa11111111",
    reasonCode: "commitment_overdue",
    reason: "past its agreed moment by two days",
    basisRefs: ["asr_aaaaaaaa11111111"],
    consequence: "The agreement stays open.",
    nextStep: "Confirm it, or say now that it will not be met.",
    attentionRank: 5,
    generatedAt: "2026-09-13T12:00:00Z",
    ...overrides,
  };
}

function disclosure(overrides: Partial<DisclosureEnvelope> = {}): DisclosureEnvelope {
  return {
    scope: "pulse",
    coverage: "complete",
    freshnessAt: "2026-09-13T12:00:00Z",
    authority: "derived",
    limitations: [],
    truncated: false,
    ...overrides,
  };
}

function pulseResponse(
  items: readonly BackendPulseItem[],
  disclosureOverrides: Partial<DisclosureEnvelope> = {},
): Response {
  return new Response(
    JSON.stringify({ shape: "backend", items, disclosure: disclosure(disclosureOverrides) }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}

function renderSurface(initialAnswer: TodayPulseAnswer) {
  return render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <TodayPulseSurface initialAnswer={initialAnswer} />
    </TaskRuntimeProvider>,
  );
}

const TWO_ROWS: readonly BackendPulseItem[] = [
  item({ pulseId: "puls_one", subjectTitle: "First by rank", attentionRank: 9 }),
  item({ pulseId: "puls_two", subjectTitle: "Second by rank", attentionRank: 1 }),
];

function renderedTitles(): readonly (string | null)[] {
  return screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
}

/** Every URL the surface asked for, in order. */
function requestedUrls(): readonly string[] {
  return fetchSpy.mock.calls.map((call) => String(call[0]));
}

describe("TodayPulseSurface reads /api/pulse and nothing else", () => {
  it("asks only its own route, with no payload and no principal", async () => {
    renderSurface({ kind: "records", items: TWO_ROWS });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    for (const [url, init] of fetchSpy.mock.calls as [string, RequestInit][]) {
      expect(String(url)).toBe("/api/pulse");
      expect(init.method).toBe("GET");
      expect(init.body).toBeUndefined();
    }
  });

  it("reads no Task detail merely because Today is populated", async () => {
    const tasks = [
      item({ pulseId: "puls_t1", itemType: "task", itemRef: "tsk_one", subjectTitle: "One" }),
      item({ pulseId: "puls_t2", itemType: "task", itemRef: "tsk_two", subjectTitle: "Two" }),
    ];
    fetchSpy.mockImplementation(async () => pulseResponse(tasks));
    renderSurface({ kind: "records", items: tasks });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(screen.getAllByTestId("today-task-card")).toHaveLength(2);
    expect(requestedUrls().filter((url) => url.startsWith("/api/tasks"))).toEqual([]);
  });
});

describe("the exact Empty sentence is reserved for an authoritative quiet day", () => {
  it("says it for a whole, successful answer that carried no rows", async () => {
    fetchSpy.mockImplementation(async () => pulseResponse([]));
    renderSurface({ kind: "records", items: TWO_ROWS });
    await waitFor(() => expect(screen.getByTestId("today-empty")).toBeTruthy());
    expect(screen.getByTestId("today-empty").textContent).toContain(TODAY_EMPTY_COPY);
    expect(screen.queryByTestId("today-stale")).toBeNull();
  });

  it("never says it for a refresh that failed", async () => {
    fetchSpy.mockRejectedValue(new TypeError("fetch failed"));
    renderSurface({ kind: "records", items: TWO_ROWS });
    await waitFor(() => expect(screen.getByTestId("today-stale")).toBeTruthy());
    expect(screen.queryByTestId("today-empty")).toBeNull();
    expect(screen.queryByText(TODAY_EMPTY_COPY)).toBeNull();
    // The last confirmed answer stands, in the backend's order.
    expect(renderedTitles()).toEqual(["First by rank", "Second by rank"]);
  });

  it("never says it for a refresh the backend answered as degraded with no rows", async () => {
    fetchSpy.mockImplementation(async () =>
      pulseResponse([], { coverage: "partial", limitations: ["one scope was skipped"] }),
    );
    renderSurface({ kind: "records", items: TWO_ROWS });
    await waitFor(() => expect(screen.getByTestId("today-degraded-empty")).toBeTruthy());
    expect(screen.queryByTestId("today-empty")).toBeNull();
    expect(screen.queryByText(TODAY_EMPTY_COPY)).toBeNull();
    expect(screen.getByTestId("degraded-banner")).toBeTruthy();
  });

  it("never says it for a refresh the backend answered as not searched", async () => {
    fetchSpy.mockImplementation(async () =>
      pulseResponse([], { coverage: "unavailable", limitations: ["the scope was not searched"] }),
    );
    renderSurface({ kind: "records", items: TWO_ROWS });
    await waitFor(() => expect(screen.getByTestId("today-stale")).toBeTruthy());
    expect(screen.queryByTestId("today-empty")).toBeNull();
    expect(renderedTitles()).toEqual(["First by rank", "Second by rank"]);
  });

  it("keeps an unavailable server answer unavailable when the refresh also fails", async () => {
    fetchSpy.mockRejectedValue(new TypeError("fetch failed"));
    renderSurface({
      kind: "unavailable",
      error: { errorClass: "unavailable", code: "gateway_unreachable", message: "no answer" },
      limitations: ["the gateway did not answer"],
    });
    await waitFor(() => expect(screen.getByTestId("today-stale")).toBeTruthy());
    expect(screen.getByTestId("today-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("today-empty")).toBeNull();
  });

  it("marks the surface stale and says so without implying anything was cleared", async () => {
    fetchSpy.mockResolvedValue(new Response("", { status: 503 }));
    renderSurface({ kind: "records", items: TWO_ROWS });
    await waitFor(() => expect(screen.getByTestId("today-refresh-notice")).toBeTruthy());
    const notice = screen.getByTestId("today-refresh-notice").textContent ?? "";
    expect(notice).toMatch(/last confirmed read/i);
    expect(notice).not.toMatch(/nothing needs/i);
    expect(screen.getByTestId("today-stale")).toBeTruthy();
    expect(renderedTitles()).toEqual(["First by rank", "Second by rank"]);
  });
});

describe("answers replace one another atomically, in the backend's order", () => {
  it("keeps the new answer in the order the backend returned it", async () => {
    const reordered = [
      item({ pulseId: "puls_two", subjectTitle: "Second by rank", attentionRank: 1 }),
      item({ pulseId: "puls_one", subjectTitle: "First by rank", attentionRank: 9 }),
      item({ pulseId: "puls_three", subjectTitle: "Third", attentionRank: 4 }),
    ];
    fetchSpy.mockImplementation(async () => pulseResponse(reordered));
    renderSurface({ kind: "records", items: TWO_ROWS });
    await waitFor(() => expect(renderedTitles()).toHaveLength(3));
    expect(renderedTitles()).toEqual(["Second by rank", "First by rank", "Third"]);
  });

  it("never falls through Empty between the old answer and the new one", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    fetchSpy.mockImplementation(async () => {
      await gate;
      return pulseResponse([item({ pulseId: "puls_new", subjectTitle: "Replacement" })]);
    });
    renderSurface({ kind: "records", items: TWO_ROWS });
    // While the read is in flight the confirmed answer is still the whole answer.
    expect(screen.queryByTestId("today-empty")).toBeNull();
    expect(renderedTitles()).toEqual(["First by rank", "Second by rank"]);
    release?.();
    await waitFor(() => expect(renderedTitles()).toEqual(["Replacement"]));
    expect(screen.queryByTestId("today-empty")).toBeNull();
  });
});

describe("a Task confirmed anywhere in the session refreshes Today", () => {
  function Harness({ onRuntime }: { onRuntime: (runtime: ReturnType<typeof useTaskRuntime>) => void }) {
    onRuntime(useTaskRuntime());
    return null;
  }

  it("registers under a plain string id and re-reads on a confirmed mutation", async () => {
    let runtime: ReturnType<typeof useTaskRuntime> | undefined;
    render(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <Harness onRuntime={(value) => (runtime = value)} />
        <TodayPulseSurface initialAnswer={{ kind: "records", items: TWO_ROWS }} />
      </TaskRuntimeProvider>,
    );
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(runtime?.reconciliation.activeTaskQueryIds()).toContain(TODAY_PULSE_QUERY_ID);

    const before = fetchSpy.mock.calls.length;
    fetchSpy.mockImplementation(async () =>
      pulseResponse([item({ pulseId: "puls_after", subjectTitle: "After the write" })]),
    );
    runtime?.reconciliation.notifyTaskMutationConfirmed({ kind: "close", taskId: "tsk_elsewhere" });

    await waitFor(() => expect(fetchSpy.mock.calls.length).toBeGreaterThan(before));
    await waitFor(() => expect(renderedTitles()).toEqual(["After the write"]));
  });

  it("drops its registration when it unmounts", async () => {
    let runtime: ReturnType<typeof useTaskRuntime> | undefined;
    const { unmount } = render(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <Harness onRuntime={(value) => (runtime = value)} />
        <TodayPulseSurface initialAnswer={{ kind: "records", items: TWO_ROWS }} />
      </TaskRuntimeProvider>,
    );
    await waitFor(() => expect(runtime?.reconciliation.activeTaskQueryIds()).toContain(TODAY_PULSE_QUERY_ID));
    unmount();
    expect(runtime?.reconciliation.activeTaskQueryIds()).not.toContain(TODAY_PULSE_QUERY_ID);
  });
});

describe("classification reads coverage before it counts rows", () => {
  it("calls a zero-row unavailable answer unavailable, not empty", () => {
    const answer = classifyPulsePayload({
      items: [],
      disclosure: disclosure({ coverage: "unavailable" }),
    });
    expect(answer.kind).toBe("unavailable");
  });

  it("calls a zero-row partial answer degraded, not empty", () => {
    const answer = classifyPulsePayload({ items: [], disclosure: disclosure({ coverage: "partial" }) });
    expect(answer.kind).toBe("degraded");
  });

  it("calls a zero-row whole answer empty, and a populated one records", () => {
    expect(classifyPulsePayload({ items: [], disclosure: disclosure() }).kind).toBe("empty");
    expect(classifyPulsePayload({ items: TWO_ROWS, disclosure: disclosure() }).kind).toBe("records");
  });
});

/**
 * Focus after Today's authoritative re-read has removed the card the user was
 * standing in.
 *
 * The shared row engine returns focus to the control the user operated, or — a
 * Today card's affordances withdraw when the Task becomes terminal — to the card
 * root. That return is correct and it is not the whole story: the Pulse re-read
 * then removes that very card, so focus lands and evaporates, and a keyboard
 * user who closed a Task is left on `document.body` at the top of the document.
 * Only this surface owns the list, so only this surface can see it happen.
 *
 * jsdom does not blur a focused element when it is disabled, so the test that
 * depends on that behaviour emulates it — a test that passed only because jsdom
 * differs from a browser would be worse than no test here.
 */
describe("focus survives the card leaving Today", () => {
  function Probe({ onRuntime }: { onRuntime: (runtime: ReturnType<typeof useTaskRuntime>) => void }) {
    onRuntime(useTaskRuntime());
    return null;
  }

  function taskItem(taskId: string, title: string): BackendPulseItem {
    return item({
      pulseId: `puls_${taskId}`,
      itemType: "task",
      itemRef: taskId,
      reasonCode: "task_overdue",
      subjectTitle: title,
      nextStep: undefined,
    });
  }

  const ONE = taskItem("tsk_one", "First task");
  const TWO = taskItem("tsk_two", "Second task");

  /** Emulate the browser dropping focus when the focused control is disabled. */
  function emulateDisableBlur(): () => void {
    const original = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function patched(name: string, value: string) {
      if (name === "disabled" && document.activeElement === this) {
        (this as HTMLElement).blur();
      }
      return original.call(this, name, value);
    };
    return () => {
      Element.prototype.setAttribute = original;
    };
  }

  function card(taskId: string): HTMLElement {
    const found = document.querySelector<HTMLElement>(`[data-today-task="${taskId}"]`);
    if (!found) throw new Error(`no Today card for ${taskId}`);
    return found;
  }

  function cardCount(): number {
    return document.querySelectorAll("[data-today-task]").length;
  }

  function renderToday(items: readonly BackendPulseItem[]) {
    let runtime: ReturnType<typeof useTaskRuntime> | undefined;
    fetchSpy.mockImplementation(async () => pulseResponse(items));
    render(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <Probe onRuntime={(value) => (runtime = value)} />
        <button type="button" data-testid="elsewhere">
          Somewhere else entirely
        </button>
        <TodayPulseSurface initialAnswer={{ kind: "records", items }} />
      </TaskRuntimeProvider>,
    );
    return {
      /**
       * Answer the next re-read with exactly these items, ask for one, and do
       * not return until it has been applied and the restoration frame it
       * scheduled has had its turn.
       *
       * Waiting on the request alone is not enough, and neither is waiting on a
       * card count that the new answer happens to share with the old one: the
       * restoration runs in `requestAnimationFrame`, and a later answer cancels
       * a frame that has not fired. A test that did not wait for the frame would
       * report a guard as unreached rather than as wrong.
       */
      async reread(next: readonly BackendPulseItem[], settled: () => void) {
        const before = fetchSpy.mock.calls.length;
        fetchSpy.mockImplementation(async () => pulseResponse(next));
        runtime?.reconciliation.notifyTaskMutationConfirmed({ kind: "close", taskId: "tsk_one" });
        await waitFor(() => expect(fetchSpy.mock.calls.length).toBeGreaterThan(before));
        await waitFor(settled);
        await new Promise((resolve) => setTimeout(resolve, 50));
      },
    };
  }

  it("places focus on the card that now stands where the closed one was", async () => {
    const today = renderToday([ONE, TWO]);
    await waitFor(() => expect(cardCount()).toBe(2));

    card("tsk_one").focus();
    expect(document.activeElement).toBe(card("tsk_one"));

    await today.reread([TWO], () => expect(cardCount()).toBe(1));

    await waitFor(() => expect(document.activeElement).toBe(card("tsk_two")));
    expect(document.activeElement).not.toBe(document.body);
  });

  it("keeps the record while the control is merely disabled, and spends it when the card goes", async () => {
    const restore = emulateDisableBlur();
    try {
      const today = renderToday([ONE, TWO]);
      await waitFor(() => expect(cardCount()).toBe(2));

      /*
        The hand is on a control of the first card, and the write disables it —
        which is exactly how a browser drops focus to the body mid-write.
      */
      const control = within(card("tsk_one")).getAllByRole("button")[0];
      control.focus();
      expect(document.activeElement).toBe(control);
      control.setAttribute("disabled", "");
      expect(document.activeElement).toBe(document.body);

      /*
        A refresh lands while the write is still running and leaves both cards
        standing. The record must survive it: a disabled control is why focus is
        on the body, and reading that as "the user put it down" throws away the
        only thing that can catch them when the write then takes the card.
      */
      const REFRESHED = taskItem("tsk_one", "First task, refreshed");
      await today.reread([REFRESHED, TWO], () =>
        expect(screen.getByText("First task, refreshed")).toBeTruthy(),
      );
      expect(document.activeElement).toBe(document.body);

      // Now the write confirms and the authoritative re-read takes the card.
      await today.reread([TWO], () => expect(cardCount()).toBe(1));

      await waitFor(() => expect(document.activeElement).toBe(card("tsk_two")));
    } finally {
      restore();
    }
  });

  it("does not yank focus back from wherever the user deliberately went", async () => {
    const today = renderToday([ONE, TWO]);
    await waitFor(() => expect(cardCount()).toBe(2));

    card("tsk_one").focus();
    const elsewhere = screen.getByTestId("elsewhere");
    elsewhere.focus();
    expect(document.activeElement).toBe(elsewhere);

    // The restoration frame is given every chance to misfire before we look.
    await today.reread([TWO], () => expect(cardCount()).toBe(1));

    expect(document.activeElement).toBe(elsewhere);
  });

  it("leaves focus alone when the card the user is in survives the write", async () => {
    const today = renderToday([ONE, TWO]);
    await waitFor(() => expect(cardCount()).toBe(2));

    const control = within(card("tsk_one")).getAllByRole("button")[0];
    control.focus();
    expect(document.activeElement).toBe(control);

    // A Reschedule that keeps the Task in Today: both cards come back.
    await today.reread([taskItem("tsk_one", "First task, rescheduled"), TWO], () =>
      expect(screen.getByText("First task, rescheduled")).toBeTruthy(),
    );

    // Still on the control, not hauled up to the card root or anywhere else.
    expect(document.activeElement).toBe(control);
  });

  it("falls to a stable heading when the last card leaves, never to the body", async () => {
    const today = renderToday([ONE]);
    await waitFor(() => expect(cardCount()).toBe(1));

    card("tsk_one").focus();
    expect(document.activeElement).toBe(card("tsk_one"));

    await today.reread([], () => expect(screen.getByTestId("today-empty")).toBeTruthy());

    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByTestId("today-pulse-heading")),
    );
    expect(document.activeElement).not.toBe(document.body);
  });
});
