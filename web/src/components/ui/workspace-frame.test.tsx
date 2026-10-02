import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkspaceFrame } from "@/components/ui/workspace-frame";
import { SurfaceState, type SafeProductCopy, type SurfaceStateKind } from "@/components/ui/surface-state";
import { FoundationExample, RemovedInvokerExample } from "@/components/ui/workspace-frame.stories";

afterEach(cleanup);

describe("WP01 WorkspaceFrame", () => {
  it("names one main and one h1, preserving actions and essential source content", () => {
    render(<WorkspaceFrame title="Records" actions={<button>Refresh records</button>}><p>Source title, state and due</p></WorkspaceFrame>);
    expect(screen.getByRole("main", { name: "Records" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Refresh records" })).toBeVisible();
    expect(screen.getByText("Source title, state and due")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open details" })).toBeNull();
  });

  it("offers narrow detail with named modal, title focus, Escape and invoker restoration", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFrame title="Records" detail={<p>Source provenance</p>}><p>Confirmed records</p></WorkspaceFrame>);
    const invoker = screen.getByRole("button", { name: "Open details" });
    await user.click(invoker);
    expect(screen.getByRole("dialog", { name: "Records details" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Records details" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(invoker).toHaveFocus();
  });

  it("focuses a dialog input without a deferred callback and restores its invoker", async () => {
    const user = userEvent.setup();
    render(<FoundationExample />);
    const invoker = screen.getByRole("button", { name: "Open foundation dialog" });
    await user.click(invoker);
    expect(screen.getByRole("textbox", { name: "Record title" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(invoker).toHaveFocus();
  });
  it("returns Dialog focus to the surviving heading when its action disappears", async () => {
    const user = userEvent.setup();
    render(<RemovedInvokerExample />);
    await user.click(screen.getByRole("button", { name: "Open removable dialog" }));
    await user.click(screen.getByRole("button", { name: "Remove originating action" }));
    expect(screen.queryByRole("button", { name: "Open removable dialog" })).toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("heading", { name: "Changing workspace" })).toHaveFocus();
  });

});

describe("WP01 ordinary state semantics", () => {
  const states: readonly [SurfaceStateKind, string, string][] = [
    ["loading", "status", "Loading"], ["empty", "status", "Empty"], ["partial", "status", "Partial"],
    ["unavailable", "alert", "Could not be read"], ["not_found", "status", "Not available"],
    ["validation", "alert", "Check input"], ["conflict", "alert", "Changed elsewhere"],
  ];
  it.each(states)("keeps %s distinct in text and accessibility", (kind, role, badge) => {
    render(<SurfaceState kind={kind} title={`${kind} records`} />);
    const region = screen.getByRole(role, { name: `${kind} records` });
    expect(region).toHaveAttribute("data-state", kind);
    expect(screen.getByText(badge)).toBeVisible();
    if (kind === "loading") expect(region).toHaveAttribute("aria-busy", "true");
    else expect(region).not.toHaveAttribute("aria-busy");
  });

  it("rejects raw copy and leaves safe error/provenance disclosure distinct", () => {
    render(<SurfaceState kind="unavailable" title="Read unavailable" message={"UNTRUSTED_TRANSPORT_BODY" as SafeProductCopy} />);
    expect(screen.queryByText("UNTRUSTED_TRANSPORT_BODY")).toBeNull();
    expect(screen.getByRole("alert", { name: "Read unavailable" })).toBeVisible();
  });

  it("does not turn an unavailable read into an empty claim through conflicting product copy", () => {
    render(<SurfaceState kind="unavailable" title="Read unavailable" message="No records were returned." />);
    expect(screen.queryByText("No records were returned.")).toBeNull();
    expect(screen.getByRole("alert", { name: "Read unavailable" })).toBeVisible();
  });

  it("offers explicit conflict review, never automatic retry or a success claim", async () => {
    const user = userEvent.setup(); const review = vi.fn();
    render(<SurfaceState kind="conflict" title="Changed record" message="Your draft is preserved. Review the current record before trying again." onRetry={review} />);
    expect(review).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Review current" }));
    expect(review).toHaveBeenCalledTimes(1);
  });

  it("preserves legacy not-built and partial backend provenance", () => {
    render(<><SurfaceState kind="not_implemented" title="Not built here" /><SurfaceState kind="degraded" title="Backend disclosed partial" /></>);
    expect(screen.getByText("Not built")).toBeVisible();
    expect(screen.getByText("Partial")).toBeVisible();
    expect(screen.queryByText("Empty")).toBeNull();
  });
});
