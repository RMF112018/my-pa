/**
 * The one control this work package turns on: **empty, unavailable and degraded
 * do not render the same.**
 *
 * The failure being guarded is not hypothetical and is not cosmetic. Every one
 * of these surfaces reads a Principal's own record, and the sentence a person
 * takes away from an empty page is *I have none of these*. If a failed call
 * produces that same page, the product has told someone a fact about their own
 * record that nothing established — and it has told them silently, so there is
 * nothing to notice and nothing to retry.
 *
 * So the assertions below are deliberately not "the three components exist".
 * They are: the three differ in the **text** a reader sees, in the **role** the
 * accessibility tree exposes, in their **accessible name**, and in a machine
 * attribute a later refactor cannot collapse without a test going red. The
 * negative assertions matter as much as the positive ones — the unavailable
 * state must not contain the vocabulary of emptiness anywhere in its subtree.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";

afterEach(() => {
  cleanup();
});

/** Words that assert the reader holds nothing. Forbidden on a failed read. */
const EMPTINESS_CLAIMS = [
  /holds nothing/i,
  /you have none/i,
  /no results/i,
  /nothing found/i,
  /nothing here yet/i,
];

describe("the four non-record answers are four different answers", () => {
  it("gives empty and unavailable different text, roles, and names", () => {
    const { unmount } = render(
      <SurfaceState kind="empty" title="You have not captured anything yet" />,
    );
    const empty = screen.getByTestId("state-empty");
    expect(empty).toHaveAttribute("data-state", "empty");
    expect(empty.getAttribute("role")).toBe("status");
    const emptyText = empty.textContent ?? "";
    expect(emptyText).toMatch(/read successfully/i);
    expect(emptyText).toMatch(/holds nothing/i);
    unmount();

    render(
      <SurfaceState kind="unavailable" title="Your library could not be read" detail="boom" />,
    );
    const unavailable = screen.getByTestId("state-unavailable");
    expect(unavailable).toHaveAttribute("data-state", "unavailable");
    expect(unavailable.getAttribute("role")).toBe("alert");
    const unavailableText = unavailable.textContent ?? "";
    expect(unavailableText).toMatch(/nothing was retrieved/i);
    expect(unavailableText).toMatch(/read that did not happen/i);

    // The whole point: a failure never carries the vocabulary of emptiness.
    for (const claim of EMPTINESS_CLAIMS) {
      expect(unavailableText).not.toMatch(claim);
    }

    // And the two never render the same string.
    expect(unavailableText).not.toBe(emptyText);
  });

  it("gives degraded its own text and never claims completeness", () => {
    render(<SurfaceState kind="degraded" title="The listing was incomplete" />);
    const degraded = screen.getByTestId("state-degraded");
    expect(degraded).toHaveAttribute("data-state", "degraded");
    expect(degraded.getAttribute("role")).toBe("status");
    const text = degraded.textContent ?? "";
    expect(text).toMatch(/incomplete/i);
    expect(text).toMatch(/what is shown is real/i);
    for (const claim of EMPTINESS_CLAIMS) {
      expect(text).not.toMatch(claim);
    }
  });

  it("separates not_implemented from unavailable, because retrying differs", () => {
    render(<SurfaceState kind="not_implemented" title="Not readable in this build" />);
    const text = screen.getByTestId("state-not_implemented").textContent ?? "";
    expect(text).toMatch(/no capability behind this surface/i);
    expect(text).toMatch(/retrying cannot change that/i);
    // `unavailable` says the opposite about retrying, so the two are not
    // interchangeable and neither may borrow the other's sentence.
    expect(text).not.toMatch(/nothing was retrieved/i);
  });

  it("gives every state a distinct accessible name taken from its own heading", () => {
    render(
      <>
        <SurfaceState kind="empty" title="Nothing is waiting on your decision" />
        <SurfaceState kind="unavailable" title="Your review queue could not be read" />
      </>,
    );
    expect(screen.getByRole("status", { name: "Nothing is waiting on your decision" })).toBeTruthy();
    expect(screen.getByRole("alert", { name: "Your review queue could not be read" })).toBeTruthy();
  });

  it("carries the distinction in text, not only in colour", () => {
    // A reader who cannot tell the sand, gold and coral tones apart still gets
    // three different words. The badge label is asserted, not the class.
    const kinds = [
      ["empty", "Empty"],
      ["unavailable", "Could not be read"],
      ["degraded", "Partial"],
      ["not_implemented", "Not built"],
    ] as const;
    for (const [kind, label] of kinds) {
      const { unmount } = render(<SurfaceState kind={kind} title={`t-${kind}`} />);
      expect(within(screen.getByTestId(`state-${kind}`)).getByText(label)).toBeTruthy();
      unmount();
    }
  });

  it("renders the backend's own limitations rather than a generic sentence", () => {
    render(
      <SurfaceState
        kind="degraded"
        title="Partial"
        limitations={["capture search does not stem words", "the listing has no continuation"]}
      />,
    );
    const list = screen.getByTestId("surface-state-limitations");
    expect(list.textContent).toContain("does not stem words");
    expect(list.textContent).toContain("no continuation");
  });
});

describe("the degraded banner sits above real records", () => {
  it("says the rows are real and not all of them", () => {
    render(<DegradedBanner scope="this listing" limitations={["one scope was skipped"]} />);
    const banner = screen.getByTestId("degraded-banner");
    expect(banner).toHaveAttribute("data-state", "degraded");
    expect(banner.textContent).toMatch(/records below are real/i);
    expect(banner.textContent).toMatch(/not all of them/i);
    expect(banner.textContent).toContain("one scope was skipped");
  });

  it("states truncation separately, because it is a different fact", () => {
    const { unmount } = render(<DegradedBanner scope="s" limitations={[]} />);
    expect(screen.queryByTestId("degraded-truncated")).toBeNull();
    unmount();
    render(<DegradedBanner scope="s" limitations={[]} truncated />);
    expect(screen.getByTestId("degraded-truncated").textContent).toMatch(/no continuation token/i);
  });
});
