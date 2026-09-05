import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OfflineQueueStatus } from "@/components/offline/offline-queue-status";
import { useShellPreferences } from "@/components/shell/shell-preferences";
import { UtilityRegion } from "@/components/shell/utility-region";

const offline = vi.hoisted(() => ({
  drain: vi.fn(async () => ({
    counts: { pending: 0, stalled: 0, quarantined: 0, needsReauth: 0 },
  })),
  held: vi.fn(async () => []),
}));

vi.mock("@/lib/offline/capture-queue", () => ({
  drainCaptureQueue: offline.drain,
  heldCaptures: offline.held,
  releaseHeldCapture: vi.fn(),
  deleteHeldCapture: vi.fn(),
}));

afterEach(() => {
  cleanup();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.density;
  vi.clearAllMocks();
});

describe("foreground offline replay", () => {
  it("runs once after mount, again online, and removes the online listener on unmount", async () => {
    const { unmount } = render(<OfflineQueueStatus principalId="syn-aaaa0001" />);
    await waitFor(() => expect(offline.drain).toHaveBeenCalledTimes(1));

    fireEvent(window, new Event("online"));
    await waitFor(() => expect(offline.drain).toHaveBeenCalledTimes(2));

    unmount();
    fireEvent(window, new Event("online"));
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(offline.drain).toHaveBeenCalledTimes(2);
  });
});

function PreferenceHarness() {
  const { preferences, update } = useShellPreferences();
  return (
    <div>
      <output data-testid="preferences">
        {preferences.theme}:{preferences.density}:{String(preferences.navCollapsed)}
      </output>
      <button type="button" onClick={() => update({ navCollapsed: true })}>
        Collapse
      </button>
    </div>
  );
}

describe("shell preferences", () => {
  it("restores stored preferences before persistence can write hydration defaults", async () => {
    localStorage.setItem(
      "my-pa:shell-preferences:v1",
      JSON.stringify({ theme: "dark", density: "compact", navCollapsed: false }),
    );
    const user = userEvent.setup();
    render(<PreferenceHarness />);

    expect(JSON.parse(localStorage.getItem("my-pa:shell-preferences:v1") ?? "{}")).toMatchObject({
      theme: "dark",
      density: "compact",
    });
    await waitFor(() =>
      expect(screen.getByTestId("preferences")).toHaveTextContent("dark:compact:false"),
    );
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.density).toBe("compact");

    await user.click(screen.getByRole("button", { name: "Collapse" }));
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem("my-pa:shell-preferences:v1") ?? "{}")).toMatchObject({
        theme: "dark",
        density: "compact",
        navCollapsed: true,
      }),
    );
  });
});

describe("utility region", () => {
  it("supports open, resize, pin, and collapse behavior", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const onPinnedChange = vi.fn();
    const onWidthChange = vi.fn();
    const { rerender } = render(
      <UtilityRegion
        open={false}
        onOpenChange={onOpenChange}
        pinned={false}
        onPinnedChange={onPinnedChange}
        width={360}
        onWidthChange={onWidthChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Open Inspector" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);

    rerender(
      <UtilityRegion
        open
        onOpenChange={onOpenChange}
        pinned={false}
        onPinnedChange={onPinnedChange}
        width={360}
        onWidthChange={onWidthChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Pin Inspector" }));
    expect(onPinnedChange).toHaveBeenCalledWith(true);
    expect(screen.getByTestId("inspector-empty")).toHaveTextContent(
      /Select supported evidence to inspect source, freshness, provenance, and limitations/,
    );
    fireEvent.change(screen.getByRole("slider", { name: "Inspector width" }), {
      target: { value: "420" },
    });
    expect(onWidthChange).toHaveBeenCalledWith(420);
    await user.click(screen.getByRole("button", { name: "Collapse Inspector" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps the honest empty inspector copy and does not persist a selection", async () => {
    render(
      <UtilityRegion
        open
        onOpenChange={vi.fn()}
        pinned={false}
        onPinnedChange={vi.fn()}
        width={360}
        onWidthChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "Inspector" })).toBeTruthy();
    expect(screen.getByTestId("inspector-empty")).toHaveTextContent(
      "Select supported evidence to inspect source, freshness, provenance, and limitations. Nothing sensitive is persisted here.",
    );
    expect(localStorage.getItem("my-pa:inspector-selection")).toBeNull();
  });
});
