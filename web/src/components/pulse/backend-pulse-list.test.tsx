/**
 * What each kind of Today row is allowed to say, and to offer.
 *
 * Since WP-TUX-07 this file guards two presentations at once, and since
 * WP-POSTUX-06 they are two different row types rather than two branches over
 * one. A `task` row is a canonical Today Task rendered as a `TodayTaskCard`: one
 * concise reason and the two operations that answer it. An `attention` row —
 * anything the derivation raised that is not a Task — is unchanged: the
 * evidentiary card, its Evidence/Details disclosure, and its next-step routing,
 * and no write controls, because nothing on this surface can write those types.
 *
 * Several assertions here replace earlier ones that pinned superseded behaviour
 * (the `"Why now:"` / `"If ignored:"` chrome on a Task card, a visible
 * `"Rank 8"` on a Task card, the Task next-step link, and a Task title derived
 * from the Pulse projection's `subjectTitle`). Each is replaced by the assertion
 * for the behaviour that superseded it, never deleted.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { BackendPulseItem, TodayRow } from "@/contracts/views";
import { BackendPulseList } from "./backend-pulse-list";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function item(overrides: Partial<BackendPulseItem> = {}): BackendPulseItem {
  return {
    pulseId: "puls_aaaaaaaa11111111",
    itemType: "task",
    itemRef: "tsk_aaaaaaaa11111111",
    reasonCode: "task_overdue",
    reason: "past its date by two days",
    basisRefs: ["asr_aaaaaaaa11111111", "tsk_aaaaaaaa11111111"],
    consequence: "The agreed work stays open.",
    nextStep: "Close it or re-date it.",
    attentionRank: 8,
    generatedAt: "2026-08-10T12:00:00Z",
    ...overrides,
  };
}

/**
 * A canonical Today Task row. `attention` is passed only when the derivation
 * flagged the Task; omitting it is how an unflagged canonical Task is expressed,
 * and there is no other way to express one.
 */
function taskRow(
  title: string,
  options: { readonly taskId?: string; readonly attention?: BackendPulseItem } = {},
): TodayRow {
  return {
    kind: "task",
    taskId: options.taskId ?? "tsk_aaaaaaaa11111111",
    title,
    ...(options.attention ? { attention: options.attention } : {}),
  };
}

/** A derived row about something that is not a Task. */
function attentionRow(overrides: Partial<BackendPulseItem> = {}): TodayRow {
  return { kind: "attention", item: item({ itemType: "commitment", ...overrides }) };
}

/**
 * Task cards bind the shared Task operation runtime, which is session-scoped and
 * provided by the shell. The provider is the harness, not the subject: nothing
 * below asserts anything about it.
 */
function renderList(items: readonly TodayRow[]) {
  return render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <BackendPulseList items={items} />
    </TaskRuntimeProvider>,
  );
}

describe("BackendPulseList", () => {
  it("gives a Task the concise reason and none of the derivation's chrome", () => {
    // Replaces the assertion that a card contains "Why now:" and "If ignored:".
    // That chrome describes the derivation; a Task card asks for an action.
    renderList([
      taskRow("Draft the synthetic summary", {
        taskId: "tsk_hidden_id",
        attention: item({ itemRef: "tsk_hidden_id" }),
      }),
    ]);
    const card = screen.getByTestId("today-task-card");
    expect(within(card).getByTestId("today-task-card-title").textContent).toBe(
      "Draft the synthetic summary",
    );
    expect(within(card).getByTestId("today-task-card-reason").textContent).toBe("Overdue");
    expect(card.textContent).not.toContain("Why now:");
    expect(card.textContent).not.toContain("If ignored:");
    expect(card.textContent).not.toContain("The agreed work stays open.");
    expect(screen.queryByTestId("pulse-item")).toBeNull();
    expect(screen.queryByTestId("pulse-reason")).toBeNull();
    expect(within(card).queryByText(/urgency/i)).toBeNull();
  });

  it("renders a canonical Task the derivation never flagged", () => {
    /*
      The point of the row shape. This Task has no Pulse row at all, so it has no
      reason code, no rank and no pulse id — and it is still in Today, because
      the canonical predicate returned it. It renders, with the one sentence that
      is true of every row here.
    */
    renderList([taskRow("Unflagged but scheduled", { taskId: "tsk_unflagged" })]);
    const card = screen.getByTestId("today-task-card");
    expect(within(card).getByTestId("today-task-card-title").textContent).toBe(
      "Unflagged but scheduled",
    );
    expect(within(card).getByTestId("today-task-card-reason").textContent).toBe("Needs you today");
    expect(card.textContent).not.toContain("puls_");
    expect(card.textContent).not.toContain("tsk_unflagged");
    expect(screen.queryByTestId("pulse-empty")).toBeNull();
  });

  it("derives the Task reason from the reason code, not from backend prose", () => {
    const { rerender } = renderList([
      taskRow("Named task", { attention: item({ reasonCode: "task_overdue" }) }),
    ]);
    expect(screen.getByTestId("today-task-card-reason").textContent).toBe("Overdue");
    rerender(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <BackendPulseList
          items={[taskRow("Named task", { attention: item({ reasonCode: "task_due_soon" }) })]}
        />
      </TaskRuntimeProvider>,
    );
    expect(screen.getByTestId("today-task-card-reason").textContent).toBe("Due soon");
  });

  it("falls back to the one true sentence for a reason code this build does not know", () => {
    renderList([
      taskRow("Named task", { attention: item({ reasonCode: "task_invented_by_a_later_build" }) }),
    ]);
    const card = screen.getByTestId("today-task-card");
    expect(within(card).getByTestId("today-task-card-reason").textContent).toBe("Needs you today");
    expect(card.textContent).not.toContain("task_invented_by_a_later_build");
  });

  it("does not use item refs or basis refs as the title", () => {
    /*
      A Task row's title is the canonical Task's own, so the assertion for it is
      that no identifier reaches the heading. An attention row has no canonical
      title to use and falls back to its type and reason, never to a reference.
    */
    renderList([
      taskRow("A canonical title", {
        taskId: "tsk_must_not_be_title",
        attention: item({
          itemRef: "tsk_must_not_be_title",
          basisRefs: ["asr_must_not_be_title"],
          subjectTitle: undefined,
        }),
      }),
    ]);
    const taskTitle = screen.getByTestId("today-task-card-title");
    expect(taskTitle.textContent).toBe("A canonical title");
    expect(taskTitle.textContent).not.toContain("tsk_must_not_be_title");
    expect(taskTitle.textContent).not.toContain("asr_must_not_be_title");
    cleanup();

    const hidden = attentionRow({
      itemRef: "cmt_must_not_be_title",
      basisRefs: ["asr_must_not_be_title"],
      subjectTitle: undefined,
    });
    renderList([hidden]);
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Commitment — past its date by two days");
    expect(title.textContent).not.toContain("cmt_must_not_be_title");
    expect(title.textContent).not.toContain("asr_must_not_be_title");
  });

  it("prints no identifier, rank or basis reference anywhere on a Task card", () => {
    renderList([
      taskRow("Named task", {
        taskId: "tsk_never_render_me",
        attention: item({
          pulseId: "puls_never_render_me",
          itemRef: "tsk_never_render_me",
          basisRefs: ["asr_never_render_me", "cap_never_render_me"],
          attentionRank: 8,
        }),
      }),
    ]);
    const card = screen.getByTestId("today-task-card");
    for (const forbidden of [
      "puls_never_render_me",
      "tsk_never_render_me",
      "asr_never_render_me",
      "cap_never_render_me",
      "task_overdue",
      "Basis:",
      "Rank",
    ]) {
      expect(card.textContent).not.toContain(forbidden);
    }
    expect(screen.queryByTestId("pulse-rank")).toBeNull();
    expect(screen.queryByTestId("pulse-basis")).toBeNull();
  });

  it("treats a blank subjectTitle as missing rather than inventing an identifier title", () => {
    renderList([attentionRow({ subjectTitle: "   ", itemRef: "cmt_not_a_title" })]);
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Commitment — past its date by two days");
    expect(title.textContent).not.toContain("cmt_not_a_title");
  });

  it("keeps basis identifiers behind Evidence/Details, not in the visible title", () => {
    // An attention row: the evidentiary disclosure is that presentation's, and a
    // Task card publishes no basis at all (asserted above).
    renderList([attentionRow({ subjectTitle: "Named commitment" })]);
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Named commitment");
    expect(title.textContent).not.toContain("asr_aaaaaaaa11111111");
    const basis = screen.getByTestId("pulse-basis");
    expect(basis.tagName.toLowerCase()).toBe("details");
    expect(basis.textContent).toMatch(/Evidence\/Details/);
    expect(basis.textContent).toContain("asr_aaaaaaaa11111111");
    expect(basis).not.toHaveAttribute("open");
  });

  it("renders an empty state when there are no rows, and rows when there are", () => {
    const { rerender } = renderList([]);
    expect(screen.getByTestId("pulse-empty").textContent).toMatch(/nothing needs attention/i);
    expect(screen.queryByTestId("today-task-card")).toBeNull();

    rerender(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <BackendPulseList items={[taskRow("A real task")]} />
      </TaskRuntimeProvider>,
    );
    expect(screen.queryByTestId("pulse-empty")).toBeNull();
    expect(screen.getByTestId("today-task-card")).toBeTruthy();
    expect(screen.getByTestId("today-task-card-title").textContent).toBe("A real task");
  });

  it("preserves the composed row order and does not sort by rank", () => {
    renderList([
      taskRow("Later rank", { taskId: "tsk_second", attention: item({ attentionRank: 1 }) }),
      taskRow("Earlier rank", { taskId: "tsk_first", attention: item({ attentionRank: 9 }) }),
    ]);
    const titles = screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
    expect(titles).toEqual(["Later rank", "Earlier rank"]);
  });

  it("preserves the composed order across mixed Task and attention rows", () => {
    renderList([
      attentionRow({ pulseId: "puls_1", subjectTitle: "First" }),
      taskRow("Second", { taskId: "tsk_2" }),
      attentionRow({ pulseId: "puls_3", itemType: "situation", subjectTitle: "Third" }),
      taskRow("Fourth", { taskId: "tsk_4" }),
    ]);
    const titles = screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
    expect(titles).toEqual(["First", "Second", "Third", "Fourth"]);
  });

  it("presents nextStep as the primary action on an attention row, not a buried field", () => {
    renderList([attentionRow({ itemRef: "cmt_link_me", nextStep: "Open the commitment." })]);
    const action = screen.getByTestId("pulse-next-step-link");
    expect(action).toHaveAttribute("href", "/work?commitmentId=cmt_link_me");
    expect(action.textContent).toBe("Open the commitment.");
    expect(screen.getByTestId("pulse-next-step").textContent).toBe("Open the commitment.");
  });

  it("shows no rank anywhere on a Task card", () => {
    // Replaces the assertion that `pulse-rank` reads exactly "Rank 8" for this
    // item. `attentionRank` is the derivation's own ordering rank; it is not a
    // fact about the Task and a Task card does not publish it.
    renderList([taskRow("Named task", { attention: item({ attentionRank: 8 }) })]);
    const card = screen.getByTestId("today-task-card");
    expect(within(card).getByTestId("today-task-card-title").textContent).toBe("Named task");
    expect(card.textContent).not.toMatch(/urgency/i);
    expect(card.textContent).not.toMatch(/rank/i);
    expect(card.textContent).not.toContain("8");
    expect(screen.queryByTestId("pulse-rank")).toBeNull();
  });

  it("keeps the rank behind Evidence/Details on an attention row", () => {
    renderList([attentionRow({ subjectTitle: "Named commitment", attentionRank: 8 })]);
    const details = screen.getByTestId("pulse-basis");
    expect(within(details).getByTestId("pulse-rank").textContent).toBe("Rank 8");
    expect(details).not.toHaveAttribute("open");
  });

  it("answers a Task in place instead of routing to it", () => {
    // Replaces the assertion that a Task next step links to `/work?task=…`.
    // The Task row now carries the operations themselves.
    renderList([
      taskRow("Named task", {
        taskId: "tsk_link_me",
        attention: item({ itemRef: "tsk_link_me", nextStep: "Open the task." }),
      }),
    ]);
    expect(screen.queryByTestId("pulse-next-step-link")).toBeNull();
    expect(screen.queryByTestId("pulse-next-step")).toBeNull();
    expect(screen.getByRole("button", { name: "Reschedule Named task" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Close Named task" })).toBeTruthy();
  });

  it("offers no Reschedule or Close on any attention row", () => {
    for (const itemType of ["commitment", "decision", "observation", "relationship_event", "situation"]) {
      const { unmount } = renderList([attentionRow({ itemType, subjectTitle: `A ${itemType}` })]);
      expect(screen.getByTestId("pulse-item")).toBeTruthy();
      expect(screen.queryByTestId("today-task-card")).toBeNull();
      expect(screen.queryByRole("button", { name: `Reschedule A ${itemType}` })).toBeNull();
      expect(screen.queryByRole("group", { name: `Close A ${itemType}` })).toBeNull();
      expect(screen.queryByTestId("today-card-more")).toBeNull();
      unmount();
    }
  });

  it("reads no Task detail merely to render a populated list", () => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    renderList([
      taskRow("One", { taskId: "tsk_one", attention: item({ itemRef: "tsk_one" }) }),
      taskRow("Two", { taskId: "tsk_two" }),
      attentionRow({ pulseId: "puls_3", subjectTitle: "Three" }),
    ]);
    expect(screen.getAllByTestId("today-task-card")).toHaveLength(2);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("links a commitment next step through the Work commitment query", () => {
    renderList([
      attentionRow({
        itemRef: "cmt_link_me",
        nextStep: "Open the commitment.",
      }),
    ]);
    expect(screen.getByTestId("pulse-next-step-link")).toHaveAttribute(
      "href",
      "/work?commitmentId=cmt_link_me",
    );
  });

  it("links a situation next step to the existing situations route", () => {
    renderList([
      attentionRow({
        itemType: "situation",
        itemRef: "sit_no_item_route",
        nextStep: "Review the situation.",
      }),
    ]);
    expect(screen.getByTestId("pulse-next-step-link")).toHaveAttribute("href", "/situations");
  });

  it("does not invent a next-step link when the item type has no authorized route", () => {
    renderList([attentionRow({ itemType: "decision", nextStep: "Name the authority point." })]);
    expect(screen.getByTestId("pulse-next-step").textContent).toContain("Name the authority point.");
    expect(screen.queryByTestId("pulse-next-step-link")).toBeNull();
  });
});
