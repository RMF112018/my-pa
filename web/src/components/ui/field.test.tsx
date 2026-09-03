import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TextField } from "@/components/ui/field";
import { LiveAnnouncement } from "@/components/ui/live-region";

afterEach(cleanup);

describe("TextField error and required semantics", () => {
  it("associates label, hint, and error and marks the control invalid", () => {
    render(
      <TextField
        label="Corrected value"
        hint="The original proposal is preserved."
        error="A correction has to carry the value you are accepting instead."
        required
      />,
    );
    const field = screen.getByLabelText(/Corrected value/);
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAttribute("aria-required", "true");
    const describedBy = field.getAttribute("aria-describedby") ?? "";
    expect(describedBy.split(" ")).toHaveLength(2);
    expect(screen.getByRole("alert")).toHaveTextContent("A correction has to carry");
  });
});

describe("LiveAnnouncement", () => {
  it("separates polite status from assertive alerts", () => {
    const { rerender } = render(
      <LiveAnnouncement tone="status">Task update persisted.</LiveAnnouncement>,
    );
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    rerender(<LiveAnnouncement tone="alert">Conflict: compare every canonical field.</LiveAnnouncement>);
    expect(screen.getByRole("alert")).toHaveAttribute("aria-live", "assertive");
  });
});
