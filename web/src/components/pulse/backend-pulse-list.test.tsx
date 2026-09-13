/**
 * What each kind of Pulse row is allowed to say, and to offer.
 *
 * Since WP-TUX-07 this file guards two presentations at once. A Task row is a
 * `TodayTaskCard`: one concise reason and the two operations that answer it. A
 * row of any other type is unchanged — the evidentiary card, its
 * Evidence/Details disclosure, and its next-step routing — and gains no write
 * controls, because nothing on this surface can write those types.
 *
 * Several assertions here replace earlier ones that pinned the superseded
 * behaviour (the `"Why now:"` / `"If ignored:"` chrome on a Task card, a visible
 * `"Rank 8"` on a Task card, and the Task next-step link). Each is replaced by
 * the assertion for the behaviour that superseded it, never deleted.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { BackendPulseItem } from "@/contracts/views";
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
 * Task cards bind the shared Task operation runtime, which is session-scoped and
 * provided by the shell. The provider is the harness, not the subject: nothing
 * below asserts anything about it.
 */
function renderList(items: readonly BackendPulseItem[]) {
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
      item({ subjectTitle: "Draft the synthetic summary", itemRef: "tsk_hidden_id" }),
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

  it("derives the Task reason from the reason code, not from backend prose", () => {
    const { rerender } = renderList([item({ subjectTitle: "Named task" })]);
    expect(screen.getByTestId("today-task-card-reason").textContent).toBe("Overdue");
    rerender(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <BackendPulseList
          items={[item({ subjectTitle: "Named task", reasonCode: "task_due_soon" })]}
        />
      </TaskRuntimeProvider>,
    );
    expect(screen.getByTestId("today-task-card-reason").textContent).toBe("Due soon");
  });

  it("does not use item refs or basis refs as the title", () => {
    const hidden = item({
      itemRef: "tsk_must_not_be_title",
      basisRefs: ["asr_must_not_be_title"],
      subjectTitle: undefined,
    });
    renderList([hidden]);
    const title = screen.getByTestId("today-task-card-title");
    expect(title.textContent).toBe("Task — past its date by two days");
    expect(title.textContent).not.toContain("tsk_must_not_be_title");
    expect(title.textContent).not.toContain("asr_must_not_be_title");
    expect(title.textContent).not.toContain(hidden.itemRef);
    for (const ref of hidden.basisRefs) {
      expect(title.textContent).not.toContain(ref);
    }
  });

  it("prints no identifier, rank or basis reference anywhere on a Task card", () => {
    renderList([
      item({
        pulseId: "puls_never_render_me",
        itemRef: "tsk_never_render_me",
        basisRefs: ["asr_never_render_me", "cap_never_render_me"],
        subjectTitle: "Named task",
        attentionRank: 8,
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
    renderList([item({ subjectTitle: "   ", itemType: "commitment", itemRef: "cmt_not_a_title" })]);
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Commitment — past its date by two days");
    expect(title.textContent).not.toContain("cmt_not_a_title");
  });

  it("keeps basis identifiers behind Evidence/Details, not in the visible title", () => {
    // A non-Task item: the evidentiary disclosure is that presentation's, and a
    // Task card publishes no basis at all (asserted above).
    renderList([item({ itemType: "commitment", subjectTitle: "Named commitment" })]);
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Named commitment");
    expect(title.textContent).not.toContain("asr_aaaaaaaa11111111");
    const basis = screen.getByTestId("pulse-basis");
    expect(basis.tagName.toLowerCase()).toBe("details");
    expect(basis.textContent).toMatch(/Evidence\/Details/);
    expect(basis.textContent).toContain("asr_aaaaaaaa11111111");
    expect(basis).not.toHaveAttribute("open");
  });

  it("renders an empty state when there are no items, and items when there are", () => {
    const { rerender } = renderList([]);
    expect(screen.getByTestId("pulse-empty").textContent).toMatch(/nothing needs attention/i);
    expect(screen.queryByTestId("today-task-card")).toBeNull();

    rerender(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <BackendPulseList items={[item({ subjectTitle: "A real task" })]} />
      </TaskRuntimeProvider>,
    );
    expect(screen.queryByTestId("pulse-empty")).toBeNull();
    expect(screen.getByTestId("today-task-card")).toBeTruthy();
    expect(screen.getByTestId("today-task-card-title").textContent).toBe("A real task");
  });

  it("preserves backend array order and does not sort", () => {
    renderList([
      item({ pulseId: "puls_second", subjectTitle: "Later rank", attentionRank: 1 }),
      item({ pulseId: "puls_first", subjectTitle: "Earlier rank", attentionRank: 9 }),
    ]);
    const titles = screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
    expect(titles).toEqual(["Later rank", "Earlier rank"]);
  });

  it("preserves backend order across mixed Task and non-Task rows", () => {
    renderList([
      item({ pulseId: "puls_1", itemType: "commitment", subjectTitle: "First" }),
      item({ pulseId: "puls_2", itemType: "task", subjectTitle: "Second" }),
      item({ pulseId: "puls_3", itemType: "situation", subjectTitle: "Third" }),
      item({ pulseId: "puls_4", itemType: "task", subjectTitle: "Fourth" }),
    ]);
    const titles = screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
    expect(titles).toEqual(["First", "Second", "Third", "Fourth"]);
  });

  it("presents nextStep as the primary action on a non-Task row, not a buried field", () => {
    renderList([
      item({ itemType: "commitment", itemRef: "cmt_link_me", nextStep: "Open the commitment." }),
    ]);
    const action = screen.getByTestId("pulse-next-step-link");
    expect(action).toHaveAttribute("href", "/work?commitmentId=cmt_link_me");
    expect(action.textContent).toBe("Open the commitment.");
    expect(screen.getByTestId("pulse-next-step").textContent).toBe("Open the commitment.");
  });

  it("shows no rank anywhere on a Task card", () => {
    // Replaces the assertion that `pulse-rank` reads exactly "Rank 8" for this
    // item. `attentionRank` is the derivation's own ordering rank; it is not a
    // fact about the Task and a Task card does not publish it.
    renderList([item({ subjectTitle: "Named task", attentionRank: 8 })]);
    const card = screen.getByTestId("today-task-card");
    expect(within(card).getByTestId("today-task-card-title").textContent).toBe("Named task");
    expect(card.textContent).not.toMatch(/urgency/i);
    expect(card.textContent).not.toMatch(/rank/i);
    expect(card.textContent).not.toContain("8");
    expect(screen.queryByTestId("pulse-rank")).toBeNull();
  });

  it("keeps the rank behind Evidence/Details on a non-Task row", () => {
    renderList([item({ itemType: "commitment", subjectTitle: "Named commitment", attentionRank: 8 })]);
    const details = screen.getByTestId("pulse-basis");
    expect(within(details).getByTestId("pulse-rank").textContent).toBe("Rank 8");
    expect(details).not.toHaveAttribute("open");
  });

  it("answers a Task in place instead of routing to it", () => {
    // Replaces the assertion that a Task next step links to `/work?task=…`.
    // The Task row now carries the operations themselves.
    renderList([item({ subjectTitle: "Named task", itemRef: "tsk_link_me", nextStep: "Open the task." })]);
    expect(screen.queryByTestId("pulse-next-step-link")).toBeNull();
    expect(screen.queryByTestId("pulse-next-step")).toBeNull();
    expect(screen.getByRole("button", { name: "Reschedule Named task" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Close Named task" })).toBeTruthy();
  });

  it("offers no Reschedule or Close on any non-Task row", () => {
    for (const itemType of ["commitment", "decision", "observation", "relationship_event", "situation"]) {
      const { unmount } = renderList([item({ itemType, subjectTitle: `A ${itemType}` })]);
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
      item({ pulseId: "puls_1", subjectTitle: "One", itemRef: "tsk_one" }),
      item({ pulseId: "puls_2", subjectTitle: "Two", itemRef: "tsk_two" }),
      item({ pulseId: "puls_3", itemType: "commitment", subjectTitle: "Three" }),
    ]);
    expect(screen.getAllByTestId("today-task-card")).toHaveLength(2);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("links a commitment next step through the Work commitment query", () => {
    renderList([
      item({
        itemType: "commitment",
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
      item({
        itemType: "situation",
        itemRef: "sit_no_item_route",
        nextStep: "Review the situation.",
      }),
    ]);
    expect(screen.getByTestId("pulse-next-step-link")).toHaveAttribute("href", "/situations");
  });

  it("does not invent a next-step link when the item type has no authorized route", () => {
    renderList([item({ itemType: "decision", nextStep: "Name the authority point." })]);
    expect(screen.getByTestId("pulse-next-step").textContent).toContain("Name the authority point.");
    expect(screen.queryByTestId("pulse-next-step-link")).toBeNull();
  });
});
