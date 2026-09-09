import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "@/components/shell/app-shell";
import {
  DESKTOP_PRIMARY,
  DESTINATIONS,
  MOBILE_MORE,
  MOBILE_PRIMARY,
} from "@/components/shell/destinations";
import type { PrincipalSession } from "@/contracts/identity";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/today",
  useRouter: () => ({ push: navigation.push, refresh: vi.fn() }),
}));

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "11111111-2222-3333-4444-555555555555:aaaa0001-0000-0000-0000-000000000001",
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
  it("renders desktop workspaces and mobile primary Today, Work, People", () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    expect(DESKTOP_PRIMARY.map(({ label }) => label)).toEqual([
      "Today",
      "Work",
      "People",
      "Knowledge",
      "Intelligence",
    ]);
    expect(MOBILE_PRIMARY.map(({ label }) => label)).toEqual(["Today", "Work", "People"]);
    expect(MOBILE_MORE.map(({ label }) => label)).toEqual([
      "Intelligence",
      "Knowledge",
      "Map",
      "Review",
      "Search",
      "System",
    ]);
    expect(DESTINATIONS.map(({ label }) => label)).toEqual([
      "Today",
      "Work",
      "People",
      "Knowledge",
      "Intelligence",
      "Map",
      "Review",
      "Search",
    ]);
    const header = screen.getByRole("banner");
    expect(header).not.toHaveClass("lg:hidden");
    expect(within(header).getByText("My PA")).toBeTruthy();
    expect(within(header).getByRole("link", { name: "Review" })).toHaveAttribute("href", "/review");
    expect(within(header).getByRole("button", { name: "Account" })).toBeTruthy();
    const navs = screen.getAllByRole("navigation", { name: "Primary" });
    expect(navs).toHaveLength(2);
    const desktopLabels = within(navs[0]!).getAllByRole("link").map((el) => el.textContent?.trim());
    expect(desktopLabels).toEqual([
      "Today",
      "Work",
      "People",
      "Knowledge",
      "Intelligence",
      "Search",
      "Review",
      "Map",
      "System",
    ]);
    expect(within(navs[0]!).getByRole("button", { name: "Account" })).toBeTruthy();
    const mobileLabels = within(navs[1]!).getAllByRole("link").map((el) => el.textContent?.trim());
    expect(mobileLabels).toEqual(["Today", "Work", "People"]);
    expect(screen.getAllByRole("link", { name: "Review" })[0]).toHaveAttribute("href", "/review");
    expect(screen.getByTestId("capture-button-desktop")).toBeTruthy();
    const mobileCapture = screen.getByTestId("capture-button-mobile");
    expect(mobileCapture).toHaveClass("text-text-muted");
    expect(mobileCapture).not.toHaveClass("text-on-brand-accent");
    expect(mobileCapture.querySelector("span")).toHaveClass(
      "bg-brand-accent",
      "text-on-brand-accent",
    );
    expect(screen.queryByTestId("capture-button")).toBeNull();
  });

  it("groups More into Workspaces, Global, and Utilities", async () => {
    const user = userEvent.setup();
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    await user.click(screen.getByRole("button", { name: "More" }));
    const more = screen.getByRole("dialog", { name: "More" });
    expect(within(more).getByRole("heading", { name: "Workspaces" })).toBeTruthy();
    expect(within(more).getByRole("heading", { name: "Global" })).toBeTruthy();
    expect(within(more).getByRole("heading", { name: "Utilities" })).toBeTruthy();
    for (const label of ["Intelligence", "Knowledge", "Map"]) {
      expect(within(more).getByRole("link", { name: label })).toBeTruthy();
    }
    expect(within(more).getByRole("link", { name: "Review" })).toBeTruthy();
    expect(within(more).getByRole("link", { name: "Search" })).toBeTruthy();
    expect(within(more).getByRole("link", { name: "System" })).toBeTruthy();
    expect(within(more).queryByRole("link", { name: "Today" })).toBeNull();
    expect(within(more).queryByRole("link", { name: "People" })).toBeNull();
  });

  it("shows the signed-in principal and the synthetic badge", async () => {
    const user = userEvent.setup();
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    await user.click(within(screen.getByRole("banner")).getByRole("button", { name: "Account" }));
    expect(screen.getByTestId("principal-name")).toHaveTextContent("Synthetic A");
    expect(screen.getByTestId("principal-upn")).toHaveTextContent("synthetic.a@moss.example");
    expect(screen.getByText("Synthetic identity")).toBeInTheDocument();
  });

  it("marks the active destination with aria-current", () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    const todayLinks = screen.getAllByRole("link", { name: "Today" });
    expect(todayLinks.some((l) => l.getAttribute("aria-current") === "page")).toBe(true);
  });

  it("opens Search from the keyboard with idle copy, not a destination launcher", async () => {
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Search" });
    expect(dialog).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent(/cross-feature search is not available/i);
    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Start typing to search.");
    expect(within(dialog).queryByRole("link", { name: "Knowledge" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Knowledge" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Commands/ })).toBeNull();
  });

  it("closes Search on Escape even when the query field is not empty", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ shape: "backend", query: "morning brief", hits: [], coverage: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByRole("dialog", { name: "Search" });
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "morning brief");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Search" })).toBeNull();
  });

  it("keeps Appearance inside Account and collapses the rail from System", async () => {
    const user = userEvent.setup();
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    expect(screen.queryByRole("button", { name: "Use dark theme" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Commands/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open Inspector" })).toBeNull();

    const header = screen.getByRole("banner");
    expect(header).not.toHaveClass("lg:hidden");
    const rail = screen.getAllByRole("navigation", { name: "Primary" })[0]!;
    await user.click(within(rail).getByRole("button", { name: "Account" }));
    const account = screen.getByRole("dialog", { name: "Account" });
    expect(within(account).getByRole("button", { name: "Use dark theme" })).toBeTruthy();
    expect(within(account).getByRole("button", { name: "Use compact density" })).toBeTruthy();
    expect(within(account).getByRole("button", { name: "Sign out" })).toBeTruthy();
    await user.click(within(account).getByRole("button", { name: "Use dark theme" }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
    await user.click(within(account).getByRole("button", { name: "Use compact density" }));
    await waitFor(() => expect(document.documentElement.dataset.density).toBe("compact"));
    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await user.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeTruthy();
    expect(within(rail).getByRole("button", { name: "Account" })).toBeTruthy();
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
            { domain: "goodnotes", state: "searched", hitCount: 0 },
            { domain: "knowledge", state: "knowledge_not_enrolled", hitCount: 0 },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByRole("dialog", { name: "Search" });
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "morning");

    expect(await screen.findByTestId("search-group-tasks")).toHaveTextContent("Morning task");
    expect(screen.getByTestId("search-coverage")).toHaveTextContent("goodnotes: searched");
    expect(screen.getByTestId("search-coverage")).not.toHaveTextContent("goodnotes: omitted");
    expect(screen.getByTestId("search-coverage")).not.toHaveTextContent("goodnotes_not_activated");
    expect(screen.getByTestId("search-coverage")).toHaveTextContent("knowledge_not_enrolled");
    expect(screen.getByRole("dialog", { name: "Search" })).not.toHaveTextContent(
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
    await screen.findByRole("dialog", { name: "Search" });
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
    await user.click(screen.getByTestId("capture-button-desktop"));

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

  it("opens Capture from the mobile tab", async () => {
    const user = userEvent.setup();
    render(<AppShell principal={PRINCIPAL}>content</AppShell>);
    await user.click(screen.getByTestId("capture-button-mobile"));
    expect(screen.getByRole("dialog", { name: "Capture" })).toBeInTheDocument();
  });
});
