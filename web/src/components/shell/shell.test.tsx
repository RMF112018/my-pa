import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "@/components/shell/app-shell";
import { DESTINATIONS, MOBILE_MORE, MOBILE_PRIMARY } from "@/components/shell/destinations";
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
  it("renders desktop destinations and mobile primary Today, Work, Review, Search", () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    expect(MOBILE_PRIMARY.map(({ label }) => label)).toEqual([
      "Today",
      "Work",
      "Review",
      "Search",
    ]);
    expect(MOBILE_MORE.map(({ label }) => label)).toEqual([
      "People",
      "Intelligence",
      "Knowledge",
      "Map",
      "System",
    ]);
    expect(DESTINATIONS.map(({ label }) => label)).toEqual([
      "Today",
      "Work",
      "Intelligence",
      "People",
      "Map",
      "Knowledge",
      "Review",
      "Search",
    ]);
    for (const destination of MOBILE_PRIMARY) {
      expect(screen.getAllByRole("link", { name: destination.label }).length).toBeGreaterThanOrEqual(
        2,
      );
    }
    // People is in More, not the mobile primary bar, so only the desktop rail link is mounted.
    expect(screen.getAllByRole("link", { name: "People" })).toHaveLength(1);
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
    const dialog = await screen.findByRole("dialog", { name: "Command menu" });
    expect(dialog).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent(/cross-feature search is not available/i);
    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Knowledge" }));

    expect(navigation.push).toHaveBeenCalledWith("/knowledge");
    expect(screen.queryByRole("dialog", { name: "Command menu" })).toBeNull();
  });

  it("federates a typed query through GET /api/search and keeps omitted coverage honest", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          shape: "backend",
          query: "morning",
          hits: [
            {
              domain: "tasks",
              item: {
                task_id: "tsk_aaaaaaaa11111111",
                title: "Morning task",
                lifecycle_state: "open",
                priority: null,
                due_at: null,
                scheduled_at: null,
                deferred_until: null,
                archived_at: null,
                created_at: "2026-01-01T00:00:00Z",
                updated_at: "2026-01-01T00:00:00Z",
                version: 1,
              },
            },
          ],
          coverage: [
            { domain: "tasks", state: "searched", hitCount: 1 },
            { domain: "goodnotes", state: "omitted", hitCount: 0, reason: "goodnotes_not_activated" },
            { domain: "knowledge", state: "knowledge_not_enrolled", hitCount: 0 },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByRole("dialog", { name: "Command menu" });
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "morning");

    expect(await screen.findByTestId("search-group-tasks")).toHaveTextContent("Morning task");
    expect(screen.getByTestId("search-coverage")).toHaveTextContent("goodnotes: omitted");
    expect(screen.getByTestId("search-coverage")).toHaveTextContent("knowledge_not_enrolled");
    expect(screen.getByRole("dialog", { name: "Command menu" })).not.toHaveTextContent(
      /cross-feature search is not available/i,
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/search?q=morning",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("maps synthetic 501 search to not-implemented rather than empty success", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          state: "not_implemented",
          error: {
            errorClass: "unavailable",
            code: "not_implemented",
            message: "The synthetic provider has no federated search fixture.",
          },
        }),
        { status: 501, headers: { "content-type": "application/json" } },
      ),
    );

    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByRole("dialog", { name: "Command menu" });
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "morning");

    expect(await screen.findByTestId("search-not-implemented")).toBeInTheDocument();
    expect(screen.queryByTestId("search-empty")).toBeNull();
    expect(screen.queryByTestId("search-group-tasks")).toBeNull();
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
