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
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

/**
 * WP07 — the raw-transport leg is governed by the global diagnostics policy.
 *
 * These tests drive the policy directly rather than standing up the provider,
 * because what is under test here is `SurfaceState`'s decomposition, not the
 * provider's plumbing (which `diagnostics-provider.test.tsx` covers). The
 * default is OFF, matching the product default, so any assertion that the
 * Diagnostics block exists has to say so explicitly — a test cannot drift into
 * passing because it forgot which mode it was in.
 */
let diagnosticsEnabled = false;

vi.mock("@/components/diagnostics/diagnostics-provider", () => ({
  useDiagnosticsEnabled: () => diagnosticsEnabled,
}));

beforeEach(() => {
  diagnosticsEnabled = false;
});
import { SurfaceState, DegradedBanner, LoadingStatus } from "@/components/ui/surface-state";

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

function firstParagraphOutsideDetails(root: HTMLElement): HTMLElement | undefined {
  return Array.from(root.querySelectorAll("p")).find((node) => !node.closest("details"));
}

describe("the four non-record answers are four different answers", () => {
  it("gives empty and unavailable different text, roles, and names", () => {
    const { unmount } = render(
      <SurfaceState kind="empty" title="You have not captured anything yet" />,
    );
    const empty = screen.getByTestId("state-empty");
    expect(empty).toHaveAttribute("data-state", "empty");
    expect(empty.getAttribute("role")).toBe("status");
    const emptyText = empty.textContent ?? "";
    const emptyDetails = within(empty).getByTestId("surface-state-details");
    expect(emptyDetails).toHaveTextContent(/read successfully/i);
    expect(emptyDetails).toHaveTextContent(/holds nothing/i);
    expect(firstParagraphOutsideDetails(empty)?.getAttribute("data-testid")).not.toBe(
      "surface-state-clarification",
    );
    unmount();

    render(
      <SurfaceState
        kind="unavailable"
        title="Your library could not be read"
        detail="This could not be read. Try again."
        diagnostic="boom"
      />,
    );
    const unavailable = screen.getByTestId("state-unavailable");
    expect(unavailable).toHaveAttribute("data-state", "unavailable");
    expect(unavailable.getAttribute("role")).toBe("alert");
    const unavailableText = unavailable.textContent ?? "";
    const unavailableDetails = within(unavailable).getByTestId("surface-state-details");
    expect(unavailableDetails).toHaveTextContent(/nothing was retrieved/i);
    expect(unavailableDetails).toHaveTextContent(/read that did not happen/i);
    expect(firstParagraphOutsideDetails(unavailable)).toHaveTextContent(
      "This could not be read. Try again.",
    );
    // Diagnostics are OFF by default, so the raw transport string is absent
    // from the DOM entirely — not hidden, not collapsed, not present-but-empty.
    expect(within(unavailable).queryByTestId("surface-state-diagnostic")).toBeNull();
    expect(within(unavailable).queryByTestId("surface-state-diagnostics")).toBeNull();
    expect(unavailableText).not.toMatch(/boom/);
    // The epistemic clarification is product truth and survives OFF; it is the
    // reason this component exists and is not diagnostics.
    expect(unavailableDetails).toHaveTextContent(/read that did not happen/i);

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
    expect(within(degraded).getByTestId("surface-state-details")).toHaveTextContent(
      /what is shown is real/i,
    );
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

  it("withholds the backend's own limitation strings while diagnostics are off", () => {
    // These read as product truth, and often are — but they are backend-authored
    // strings and the backend puts raw transport text in them (an unreachable
    // gateway yields the limitation "the application gateway did not answer").
    // Nothing about a string distinguishes the two, so the list is governed as
    // a whole and the partial-answer *consequence* is stated separately.
    render(
      <SurfaceState
        kind="degraded"
        title="Partial"
        limitations={["capture search does not stem words"]}
      />,
    );
    expect(screen.queryByTestId("surface-state-limitations")).toBeNull();
    expect(document.body.textContent ?? "").not.toMatch(/does not stem words/);
    // The state itself, and what it means, are unchanged.
    expect(screen.getByTestId("state-degraded")).toHaveAttribute("data-state", "degraded");
    expect(screen.getByTestId("surface-state-clarification").textContent).toMatch(
      /its own answer is incomplete/i,
    );
  });

  it("renders the backend's own limitations rather than a generic sentence", () => {
    diagnosticsEnabled = true;
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

  it("never uses empty-kind vocabulary for a failed read", () => {
    render(<SurfaceState kind="unavailable" title="Your captures could not be read" />);
    const unavailable = screen.getByTestId("state-unavailable");
    const text = unavailable.textContent ?? "";
    expect(unavailable).toHaveAttribute("data-state", "unavailable");
    expect(within(unavailable).queryByText("Empty")).toBeNull();
    for (const claim of EMPTINESS_CLAIMS) {
      expect(text).not.toMatch(claim);
    }
  });

  it("puts generic clarification behind a Details disclosure", () => {
    render(<SurfaceState kind="empty" title="You have not captured anything yet" />);
    const details = screen.getByTestId("surface-state-details");
    expect(details.tagName).toBe("DETAILS");
    expect(within(details).getByText("Details")).toBeTruthy();
    const clarification = screen.getByTestId("surface-state-clarification");
    expect(details.contains(clarification)).toBe(true);
    expect(clarification).toHaveTextContent(/read successfully/i);
    expect(firstParagraphOutsideDetails(screen.getByTestId("state-empty"))).toBeUndefined();
  });
});

describe("the degraded banner sits above real records", () => {
  it("says the rows are real and not all of them", () => {
    render(<DegradedBanner scope="this listing" limitations={["one scope was skipped"]} />);
    const banner = screen.getByTestId("degraded-banner");
    expect(banner).toHaveAttribute("data-state", "degraded");
    // The consequence is product truth and is stated in both modes.
    expect(banner.textContent).toMatch(/records below are real/i);
    expect(banner.textContent).toMatch(/not all of them/i);
    // The backend's own strings are not, and are absent by default.
    expect(banner.textContent).not.toContain("one scope was skipped");
    diagnosticsEnabled = true;
    cleanup();
    render(<DegradedBanner scope="this listing" limitations={["one scope was skipped"]} />);
    expect(screen.getByTestId("degraded-banner").textContent).toContain("one scope was skipped");
    expect(within(banner).getByTestId("surface-state-details")).toHaveTextContent(
      /this page guessing it/i,
    );
  });

  it("states truncation separately, because it is a different fact", () => {
    const { unmount } = render(<DegradedBanner scope="s" limitations={[]} />);
    expect(screen.queryByTestId("degraded-truncated")).toBeNull();
    unmount();
    render(<DegradedBanner scope="s" limitations={[]} truncated />);
    expect(screen.getByTestId("degraded-truncated").textContent).toMatch(/no continuation token/i);
  });
});

describe("compact empty is not an alert card", () => {
  it("keeps empty without a left-border card while unavailable stays an alert", () => {
    const { unmount } = render(<SurfaceState kind="empty" title="You have not captured anything yet" />);
    const empty = screen.getByTestId("state-empty");
    expect(empty.className).not.toMatch(/border-l-4/);
    expect(empty.tagName).toBe("DIV");
    unmount();

    render(<SurfaceState kind="unavailable" title="Your library could not be read" />);
    const unavailable = screen.getByTestId("state-unavailable");
    expect(unavailable.className).toMatch(/border-l-4/);
    expect(unavailable.getAttribute("role")).toBe("alert");
  });

  it("maps a transport error into Level 1 and withholds the raw string while diagnostics are off", () => {
    render(
      <SurfaceState
        kind="unavailable"
        title="Today could not be derived"
        error={{ message: "session authority unavailable", code: "authority_unavailable" }}
      />,
    );
    const root = screen.getByTestId("state-unavailable");
    // Level 1 — the product-language consequence — is unchanged by the policy.
    expect(firstParagraphOutsideDetails(root)).toHaveTextContent(/couldn't verify your session/i);
    expect(firstParagraphOutsideDetails(root)?.textContent).not.toMatch(/session authority/i);
    // The raw transport string reaches no part of the subtree, including the
    // accessibility tree, while diagnostics are off.
    expect(within(root).queryByTestId("surface-state-diagnostic")).toBeNull();
    expect(root.textContent ?? "").not.toMatch(/session authority unavailable/);
  });

  it("carries the raw string in Diagnostics once diagnostics are on", () => {
    diagnosticsEnabled = true;
    render(
      <SurfaceState
        kind="unavailable"
        title="Today could not be derived"
        error={{ message: "session authority unavailable", code: "authority_unavailable" }}
      />,
    );
    const root = screen.getByTestId("state-unavailable");
    // ON is presentation authority only: Level 1 still says the same thing, and
    // the raw string is additive rather than a replacement for product language.
    expect(firstParagraphOutsideDetails(root)).toHaveTextContent(/couldn't verify your session/i);
    expect(within(root).getByTestId("surface-state-diagnostic")).toHaveTextContent(
      "session authority unavailable",
    );
    const details = within(root).getByTestId("surface-state-details");
    expect(details.contains(within(root).getByTestId("surface-state-diagnostic"))).toBe(true);
  });
});

describe("loading is a status, not a bordered essay", () => {
  it("announces the label without a card border", () => {
    render(<LoadingStatus label="Loading work…" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading work…");
    expect(status.className).not.toMatch(/border/);
  });
});
