import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "@/components/shell/app-shell";
import { DESTINATIONS } from "@/components/shell/destinations";
import type { PrincipalSession } from "@/contracts/identity";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/today",
  useRouter: () => ({ push: navigation.push, refresh: vi.fn() }),
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
  it("renders the six primary destinations in successor order and System as utility", () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    expect(DESTINATIONS.map(({ label }) => label)).toEqual([
      "Today",
      "Work",
      "Intelligence",
      "People",
      "Knowledge",
      "Review",
    ]);
    for (const [index, destination] of DESTINATIONS.entries()) {
      // The first four appear in both desktop and mobile primary navigation;
      // Knowledge and Review move under mobile More.
      expect(screen.getAllByRole("link", { name: destination.label })).toHaveLength(
        index < 4 ? 2 : 1,
      );
    }
    expect(screen.getAllByRole("link", { name: "System" }).length).toBeGreaterThanOrEqual(1);
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

  it("opens the command menu from the keyboard and navigates only to supported routes", async () => {
    const user = userEvent.setup();
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(await screen.findByRole("dialog", { name: "Command menu" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Knowledge" }));

    expect(navigation.push).toHaveBeenCalledWith("/knowledge");
    expect(screen.queryByRole("dialog", { name: "Command menu" })).toBeNull();
  });

  it("opens Capture, focuses the field, and sends one attempt-keyed submission", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          shape: "backend",
          status: "persisted",
          created: true,
          receipt: { receiptId: "rcpt_aaaaaaaa11111111" },
        }),
        { status: 200 },
      ),
    );

    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    await user.click(screen.getByTestId("capture-button"));

    const field = screen.getByTestId("capture-field");
    await waitFor(() => expect(field).toHaveFocus());

    await user.type(field, "synthetic note delta");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(screen.getByTestId("capture-durable")).toHaveTextContent(
        "Saved. Your note is stored and will appear in Review.",
      ),
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/capture",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.text).toBe("synthetic note delta");
    // The kind is a default rather than a step: nothing was selected.
    expect(body.captureKind).toBe("quick_note");
    expect(body.idempotencyKey).toMatch(/^cap-[0-9a-f-]+$/);
    // The payload must never carry identity fields.
    expect(Object.keys(body)).not.toContain("principalId");
    expect(Object.keys(body)).not.toContain("oid");
  });
});
