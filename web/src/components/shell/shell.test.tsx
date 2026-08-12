import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "@/components/shell/app-shell";
import { DESTINATIONS } from "@/components/shell/destinations";
import type { PrincipalSession } from "@/contracts/identity";

vi.mock("next/navigation", () => ({
  usePathname: () => "/today",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("app shell", () => {
  it("renders all five destinations in the navigation", () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    expect(DESTINATIONS).toHaveLength(5);
    for (const d of DESTINATIONS) {
      // Desktop rail + mobile nav each render the label once.
      expect(screen.getAllByRole("link", { name: d.label }).length).toBeGreaterThanOrEqual(2);
    }
  });

  it("shows the signed-in principal and the synthetic badge", () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    expect(screen.getByTestId("principal-name")).toHaveTextContent("Synthetic A");
    expect(screen.getByTestId("principal-upn")).toHaveTextContent("synthetic.a@moss.example");
    expect(screen.getByText("Synthetic identity")).toBeInTheDocument();
  });

  it("marks the active destination with aria-current", () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    const todayLinks = screen.getAllByRole("link", { name: "Today" });
    expect(todayLinks.some((l) => l.getAttribute("aria-current") === "page")).toBe(true);
  });

  it("opens Capture, focuses the field, and saves to the stub", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ receiptId: "rcpt-1", created: true, status: "acknowledged_not_persisted" }),
        { status: 200 },
      ),
    );

    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    await user.click(screen.getByTestId("capture-button"));

    const field = screen.getByTestId("capture-field");
    await waitFor(() => expect(field).toHaveFocus());

    await user.type(field, "confirm pour window");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Captured. It will appear in Review."),
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/capture",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.text).toBe("confirm pour window");
    expect(body.mode).toBe("text");
    expect(body.idempotencyKey).toMatch(/^cap-[0-9a-f-]+$/);
    // The payload must never carry identity fields.
    expect(Object.keys(body)).not.toContain("principalId");
    expect(Object.keys(body)).not.toContain("oid");
  });
});
