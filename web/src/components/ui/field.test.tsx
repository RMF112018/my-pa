import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

/**
 * TextField now composes the shared `Textarea` primitive instead of a raw
 * `<textarea>`. These tests pin the API the refactor had to preserve.
 */
describe("TextField over the shared Textarea primitive", () => {
  it("still renders a real textarea element", () => {
    render(<TextField label="Notes" />);
    expect(screen.getByLabelText(/Notes/).tagName).toBe("TEXTAREA");
  });

  it("forwards the ref all the way to that textarea", () => {
    const ref = createRef<HTMLTextAreaElement>();
    render(<TextField ref={ref} label="Notes" />);
    expect(ref.current).toBe(screen.getByLabelText(/Notes/));
  });

  it("keeps the label associated by htmlFor and the generated control id", () => {
    render(<TextField label="Notes" />);
    const field = screen.getByLabelText(/Notes/);
    const label = document.querySelector("label");
    expect(field.id).toBeTruthy();
    expect(label?.getAttribute("for")).toBe(field.id);
  });

  it("derives the hint id from the control id and links it alone when there is no error", () => {
    render(<TextField label="Notes" hint="Kept for the record." />);
    const field = screen.getByLabelText(/Notes/);
    expect(field).toHaveAttribute("aria-describedby", `${field.id}-hint`);
    expect(document.getElementById(`${field.id}-hint`)).toHaveTextContent("Kept for the record.");
  });

  it("derives the error id, gives it role=alert, and links it alone when there is no hint", () => {
    render(<TextField label="Notes" error="Say what changed." />);
    const field = screen.getByLabelText(/Notes/);
    expect(field).toHaveAttribute("aria-describedby", `${field.id}-error`);
    const alert = screen.getByRole("alert");
    expect(alert.id).toBe(`${field.id}-error`);
  });

  it("orders aria-describedby as hint then error when both are present", () => {
    render(<TextField label="Notes" hint="Kept for the record." error="Say what changed." />);
    const field = screen.getByLabelText(/Notes/);
    expect(field).toHaveAttribute("aria-describedby", `${field.id}-hint ${field.id}-error`);
  });

  it("sets both required and aria-required when the field is required", () => {
    render(<TextField label="Notes" required />);
    const field = screen.getByLabelText(/Notes/);
    expect(field).toBeRequired();
    expect(field).toHaveAttribute("aria-required", "true");
  });

  it("disables the control through the primitive", () => {
    render(<TextField label="Notes" disabled />);
    expect(screen.getByLabelText(/Notes/)).toBeDisabled();
  });

  it("marks the control invalid from the explicit invalid flag even without error copy", () => {
    render(<TextField label="Notes" invalid />);
    const field = screen.getByLabelText(/Notes/);
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("carries no aria-invalid and no describedby when the field is clean", () => {
    render(<TextField label="Notes" />);
    const field = screen.getByLabelText(/Notes/);
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(field).not.toHaveAttribute("aria-describedby");
  });

  it("keeps the field's intentional p-2! override composed with the primitive's px-3 py-2", () => {
    // The `!` override is the contract: the field's own padding must win over the
    // primitive's default padding, which stays on the element beneath it.
    render(<TextField label="Notes" />);
    const className = screen.getByLabelText(/Notes/).className;
    expect(className).toMatch(/p-2!/);
    expect(className).toMatch(/\bpx-3\b/);
    expect(className).toMatch(/\bpy-2\b/);
  });

  it("spreads caller-supplied props through to the textarea", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <TextField
        label="Notes"
        name="notes"
        rows={7}
        placeholder="What changed?"
        defaultValue="seed"
        onChange={onChange}
      />,
    );
    const field = screen.getByLabelText(/Notes/) as HTMLTextAreaElement;
    expect(field.name).toBe("notes");
    expect(field.rows).toBe(7);
    expect(field.placeholder).toBe("What changed?");
    expect(field.value).toBe("seed");
    await user.type(field, "!");
    expect(onChange).toHaveBeenCalled();
  });
});
