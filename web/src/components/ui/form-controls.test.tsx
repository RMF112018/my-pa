import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

afterEach(cleanup);

/** Exact class-token membership: `\bw-full\b` would also match `max-w-full`. */
function classTokens(element: Element): string[] {
  return element.className.split(/\s+/).filter(Boolean);
}

/**
 * The shared form primitives carry a WP01 contract that callers depend on:
 * a caller className always composes last, native element semantics survive the
 * wrapper, and the sizing contract (full-width for Input/Textarea but never for
 * Select, deterministic shrink for all three, tokenised control type) is stable.
 *
 * jsdom does not evaluate `@media (pointer: coarse)` and does not resolve custom
 * properties into computed styles, so the coarse-pointer 16px proof is out of
 * reach here — that is the Playwright mobile lane's job. What is asserted here is
 * that the primitives reference the shared token at all, never a literal `text-sm`.
 */

describe("shared control caller class composition", () => {
  it("appends the caller className last on the Input so callers can override", () => {
    render(<Input aria-label="Caller styled input" className="caller-marker" />);
    const input = screen.getByLabelText("Caller styled input");
    expect(input.className).toMatch(/caller-marker/);
    expect(input.className.trim().endsWith("caller-marker")).toBe(true);
  });

  it("appends the caller className last on the Select so callers can override", () => {
    render(<Select aria-label="Caller styled select" className="caller-marker" />);
    const select = screen.getByLabelText("Caller styled select");
    expect(select.className).toMatch(/caller-marker/);
    expect(select.className.trim().endsWith("caller-marker")).toBe(true);
  });

  it("appends the caller className last on the Textarea so callers can override", () => {
    render(<Textarea aria-label="Caller styled textarea" className="caller-marker" />);
    const textarea = screen.getByLabelText("Caller styled textarea");
    expect(textarea.className).toMatch(/caller-marker/);
    expect(textarea.className.trim().endsWith("caller-marker")).toBe(true);
  });

  it("keeps a caller height class on every primitive — the Task Status WebKit safeguard pattern", () => {
    render(
      <>
        <Input aria-label="Fixed height input" className="h-11" />
        <Select aria-label="Fixed height select" className="h-11" />
        <Textarea aria-label="Fixed height textarea" className="h-11" />
      </>,
    );
    expect(classTokens(screen.getByLabelText("Fixed height input"))).toContain("h-11");
    expect(classTokens(screen.getByLabelText("Fixed height select"))).toContain("h-11");
    expect(classTokens(screen.getByLabelText("Fixed height textarea"))).toContain("h-11");
  });
});

describe("Input keeps native input semantics", () => {
  it("renders a real input element and forwards its ref", () => {
    const ref = createRef<HTMLInputElement>();
    render(<Input ref={ref} aria-label="Native input" />);
    const input = screen.getByLabelText("Native input");
    expect(input.tagName).toBe("INPUT");
    expect(ref.current).toBe(input);
  });

  it("passes through type, placeholder and aria attributes", () => {
    render(
      <Input
        aria-label="Search field"
        aria-describedby="search-hint"
        type="search"
        placeholder="Find a task"
      />,
    );
    const input = screen.getByLabelText("Search field") as HTMLInputElement;
    expect(input.type).toBe("search");
    expect(input.placeholder).toBe("Find a task");
    expect(input).toHaveAttribute("aria-describedby", "search-hint");
    expect(screen.getByRole("searchbox", { name: "Search field" })).toBe(input);
  });

  it("remains a controlled input: value renders and onChange receives every keystroke", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Input aria-label="Controlled input" value="draft" onChange={onChange} />);
    const input = screen.getByLabelText("Controlled input") as HTMLInputElement;
    expect(input.value).toBe("draft");
    await user.type(input, "x");
    expect(onChange).toHaveBeenCalled();
  });

  it("honours required, readOnly and disabled", () => {
    render(
      <>
        <Input aria-label="Required input" required />
        <Input aria-label="Read only input" readOnly defaultValue="fixed" />
        <Input aria-label="Disabled input" disabled />
      </>,
    );
    expect(screen.getByLabelText("Required input")).toBeRequired();
    expect(screen.getByLabelText("Read only input")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Disabled input")).toBeDisabled();
  });
});

describe("Select keeps native select semantics", () => {
  it("renders a real select exposed as a combobox and forwards its ref", () => {
    const ref = createRef<HTMLSelectElement>();
    render(
      <Select ref={ref} aria-label="Native select">
        <option value="a">Alpha</option>
      </Select>,
    );
    const select = screen.getByRole("combobox", { name: "Native select" });
    expect(select.tagName).toBe("SELECT");
    expect(ref.current).toBe(select);
  });

  it("renders its option children in the order the caller declared them", () => {
    render(
      <Select aria-label="Ordered select">
        <option value="">No priority</option>
        <option value="p1">Critical</option>
        <option value="p2">High</option>
      </Select>,
    );
    const labels = screen
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(labels).toEqual(["No priority", "Critical", "High"]);
  });

  it("honours a controlled value and reports selections through onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Select aria-label="Controlled select" value="p2" onChange={onChange}>
        <option value="p1">Critical</option>
        <option value="p2">High</option>
      </Select>,
    );
    const select = screen.getByRole("combobox", { name: "Controlled select" }) as HTMLSelectElement;
    expect(select.value).toBe("p2");
    await user.selectOptions(select, "Critical");
    expect(onChange).toHaveBeenCalled();
  });

  it("honours disabled", () => {
    render(
      <Select aria-label="Disabled select" disabled>
        <option value="a">Alpha</option>
      </Select>,
    );
    expect(screen.getByRole("combobox", { name: "Disabled select" })).toBeDisabled();
  });
});

describe("Textarea keeps native textarea semantics", () => {
  it("renders a real textarea element and forwards its ref", () => {
    const ref = createRef<HTMLTextAreaElement>();
    render(<Textarea ref={ref} aria-label="Native textarea" />);
    const textarea = screen.getByLabelText("Native textarea");
    expect(textarea.tagName).toBe("TEXTAREA");
    expect(ref.current).toBe(textarea);
  });

  it("honours required, readOnly and disabled", () => {
    render(
      <>
        <Textarea aria-label="Required textarea" required />
        <Textarea aria-label="Read only textarea" readOnly defaultValue="fixed" />
        <Textarea aria-label="Disabled textarea" disabled />
      </>,
    );
    expect(screen.getByLabelText("Required textarea")).toBeRequired();
    expect(screen.getByLabelText("Read only textarea")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Disabled textarea")).toBeDisabled();
  });

  it("accepts typed multi-line input through onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Textarea aria-label="Typed textarea" onChange={onChange} />);
    await user.type(screen.getByLabelText("Typed textarea"), "a");
    expect(onChange).toHaveBeenCalled();
  });
});

describe("WP01 shared sizing contract", () => {
  it("gives Input and Textarea a full-width default because they own their row", () => {
    render(
      <>
        <Input aria-label="Width input" />
        <Textarea aria-label="Width textarea" />
      </>,
    );
    expect(classTokens(screen.getByLabelText("Width input"))).toContain("w-full");
    expect(classTokens(screen.getByLabelText("Width textarea"))).toContain("w-full");
  });

  it("never gives Select a global w-full — the class IS the contract, since Select sits beside other controls", () => {
    render(
      <Select aria-label="Width select">
        <option value="a">Alpha</option>
      </Select>,
    );
    // Regression guard: a future edit must not hand Select a global full-width
    // contract. Callers that want a full-width Select opt in via className.
    expect(classTokens(screen.getByRole("combobox", { name: "Width select" }))).not.toContain(
      "w-full",
    );
  });

  it("gives all three the deterministic shrink and parent-bounding contract", () => {
    render(
      <>
        <Input aria-label="Shrink input" />
        <Select aria-label="Shrink select" />
        <Textarea aria-label="Shrink textarea" />
      </>,
    );
    for (const label of ["Shrink input", "Shrink select", "Shrink textarea"]) {
      const control = screen.getByLabelText(label);
      expect(classTokens(control)).toContain("min-w-0");
      expect(classTokens(control)).toContain("max-w-full");
    }
  });

  it("reads its control type from the shared tokens and hard-codes text-sm nowhere", () => {
    render(
      <>
        <Input aria-label="Token input" />
        <Select aria-label="Token select" />
        <Textarea aria-label="Token textarea" />
      </>,
    );
    // The token reference is what can be proven here: jsdom neither evaluates
    // `@media (pointer: coarse)` nor resolves custom properties, so the 16px
    // coarse-pointer outcome is proven in the Playwright mobile lane instead.
    for (const label of ["Token input", "Token select", "Token textarea"]) {
      const control = screen.getByLabelText(label);
      expect(control.className).toMatch(/text-\[length:var\(--control-font-size\)\]/);
      expect(control.className).toMatch(/leading-\[var\(--control-line-height\)\]/);
      expect(classTokens(control)).not.toContain("text-sm");
    }
  });

  it("keeps the Task Status 44px override intact when a caller sets h-11, min-h-11 and min-w-11 on Select", () => {
    render(<Select aria-label="Status select" className="h-11 min-h-11 min-w-11" />);
    const select = screen.getByRole("combobox", { name: "Status select" });
    expect(classTokens(select)).toContain("h-11");
    expect(classTokens(select)).toContain("min-h-11");
    expect(classTokens(select)).toContain("min-w-11");
  });

  it("gives Select a definite height, not only a minimum — the WebKit coarse-target safeguard", () => {
    render(<Select aria-label="Height select" />);
    const select = screen.getByRole("combobox", { name: "Height select" });
    // The class IS the contract here, and this assertion is the only lane that
    // catches its removal cheaply. WebKit resolves a default-appearance
    // `<select>` down to its ~22px intrinsic height and ignores `min-height`,
    // so the shared primitive must carry a *definite* height to hold the 44px
    // coarse target. Chromium and Gecko render 44px from `min-height` alone,
    // which is why no other browser lane fails when this is dropped. The
    // `mobile-webkit` Playwright project measures the real computed outcome.
    expect(classTokens(select)).toContain("h-[var(--control-height)]");
    expect(classTokens(select)).toContain("min-h-[var(--control-height)]");
  });
});
