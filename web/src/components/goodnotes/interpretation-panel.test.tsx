import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { InterpretationPanel } from "@/components/goodnotes/interpretation-panel";
import type { GoodNotesInterpretation } from "@/lib/api/decode/capabilities/goodnotes.read";

describe("InterpretationPanel", () => {
  it("renders a server transcription through RichContent and does not invent one", () => {
    const interpretation: GoodNotesInterpretation = {
      authority: "interpretation",
      items: [{ occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb", transcription: "synthetic note" }],
    };
    render(<InterpretationPanel interpretation={interpretation} />);
    expect(screen.getByTestId("goodnotes-transcription").textContent).toBe("synthetic note");
    expect(screen.getByTestId("goodnotes-correction-form")).toBeTruthy();
    expect(screen.queryByTestId("goodnotes-no-transcription")).toBeNull();
  });

  it("says the record carries no transcription when the server sent none", () => {
    const interpretation: GoodNotesInterpretation = {
      authority: "source",
      items: [{ occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb" }],
    };
    render(<InterpretationPanel interpretation={interpretation} />);
    expect(screen.getByTestId("goodnotes-no-transcription").textContent).toMatch(
      /carries no transcription/i,
    );
    expect(screen.queryByTestId("goodnotes-transcription")).toBeNull();
  });

  it("links pending review cases to Review and does not offer goodnotes.correct", () => {
    const interpretation: GoodNotesInterpretation = {
      authority: "pending_review",
      items: [
        {
          occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
          review_case_id: "rvc_aaaa0001aaaa0001aaaa0001",
          transcription: "pending note",
        },
      ],
    };
    render(<InterpretationPanel interpretation={interpretation} />);
    const pending = screen.getByTestId("goodnotes-pending-review");
    expect(pending.textContent).toMatch(/pending review case/i);
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute("href", "/review");
    expect(screen.queryByTestId("goodnotes-correction-form")).toBeNull();
  });
});
