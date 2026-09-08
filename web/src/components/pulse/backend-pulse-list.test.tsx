import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { BackendPulseItem } from "@/contracts/views";
import { BackendPulseList } from "./backend-pulse-list";

afterEach(cleanup);

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
    priority: 8,
    generatedAt: "2026-08-10T12:00:00Z",
    ...overrides,
  };
}

describe("BackendPulseList", () => {
  it("uses subjectTitle as the card title when it is present and non-empty", () => {
    render(
      <BackendPulseList
        items={[item({ subjectTitle: "Draft the synthetic summary", itemRef: "tsk_hidden_id" })]}
      />,
    );
    const card = screen.getByTestId("pulse-item");
    expect(within(card).getByRole("heading", { level: 3 }).textContent).toBe(
      "Draft the synthetic summary",
    );
    expect(card.textContent).toContain("Why now:");
    expect(card.textContent).toContain("If ignored:");
    expect(card.textContent).toContain("Next step:");
  });

  it("does not use item refs or basis refs as the title", () => {
    const hidden = item({
      itemRef: "tsk_must_not_be_title",
      basisRefs: ["asr_must_not_be_title"],
      subjectTitle: undefined,
    });
    render(<BackendPulseList items={[hidden]} />);
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Task — past its date by two days");
    expect(title.textContent).not.toContain("tsk_must_not_be_title");
    expect(title.textContent).not.toContain("asr_must_not_be_title");
    expect(title.textContent).not.toContain(hidden.itemRef);
    for (const ref of hidden.basisRefs) {
      expect(title.textContent).not.toContain(ref);
    }
  });

  it("treats a blank subjectTitle as missing rather than inventing an identifier title", () => {
    render(
      <BackendPulseList
        items={[item({ subjectTitle: "   ", itemType: "commitment", itemRef: "cmt_not_a_title" })]}
      />,
    );
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Commitment — past its date by two days");
    expect(title.textContent).not.toContain("cmt_not_a_title");
  });

  it("keeps basis identifiers behind Evidence/Details, not in the visible title", () => {
    render(<BackendPulseList items={[item({ subjectTitle: "Named task" })]} />);
    const title = screen.getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Named task");
    expect(title.textContent).not.toContain("asr_aaaaaaaa11111111");
    const basis = screen.getByTestId("pulse-basis");
    expect(basis.tagName.toLowerCase()).toBe("details");
    expect(basis.textContent).toMatch(/Evidence\/Details/);
    expect(basis.textContent).toContain("asr_aaaaaaaa11111111");
    expect(basis).not.toHaveAttribute("open");
  });

  it("renders an empty state when there are no items, and items when there are", () => {
    const { rerender } = render(<BackendPulseList items={[]} />);
    expect(screen.getByTestId("pulse-empty").textContent).toMatch(/nothing needs attention/i);
    expect(screen.queryByTestId("pulse-item")).toBeNull();

    rerender(<BackendPulseList items={[item({ subjectTitle: "A real task" })]} />);
    expect(screen.queryByTestId("pulse-empty")).toBeNull();
    expect(screen.getByTestId("pulse-item")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe("A real task");
  });

  it("preserves backend array order and does not sort", () => {
    render(
      <BackendPulseList
        items={[
          item({ pulseId: "puls_second", subjectTitle: "Later rank", priority: 1 }),
          item({ pulseId: "puls_first", subjectTitle: "Earlier rank", priority: 9 }),
        ]}
      />,
    );
    const titles = screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
    expect(titles).toEqual(["Later rank", "Earlier rank"]);
  });

  it("links a task next step through the Work task query", () => {
    render(
      <BackendPulseList
        items={[item({ itemType: "task", itemRef: "tsk_link_me", nextStep: "Open the task." })]}
      />,
    );
    expect(screen.getByTestId("pulse-next-step-link")).toHaveAttribute(
      "href",
      "/work?task=tsk_link_me",
    );
  });

  it("links a commitment next step through the Work commitment query", () => {
    render(
      <BackendPulseList
        items={[
          item({
            itemType: "commitment",
            itemRef: "cmt_link_me",
            nextStep: "Open the commitment.",
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("pulse-next-step-link")).toHaveAttribute(
      "href",
      "/work?commitmentId=cmt_link_me",
    );
  });

  it("links a situation next step to the existing situations route", () => {
    render(
      <BackendPulseList
        items={[
          item({
            itemType: "situation",
            itemRef: "sit_no_item_route",
            nextStep: "Review the situation.",
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("pulse-next-step-link")).toHaveAttribute("href", "/situations");
  });

  it("does not invent a next-step link when the item type has no authorized route", () => {
    render(
      <BackendPulseList
        items={[item({ itemType: "decision", nextStep: "Name the authority point." })]}
      />,
    );
    expect(screen.getByTestId("pulse-next-step").textContent).toContain("Name the authority point.");
    expect(screen.queryByTestId("pulse-next-step-link")).toBeNull();
  });
});
