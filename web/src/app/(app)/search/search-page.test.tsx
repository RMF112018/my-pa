import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SearchPage } from "./search-page";
import { collectLevel1Copy } from "@/lib/ui/user-copy";

vi.mock("next/navigation", () => ({
  usePathname: () => "/search",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const TASK_HIT = {
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
};

describe("Search page", () => {
  it("is Search-only, focuses the query field, and is not a destination launcher", () => {
    render(<SearchPage initialQuery="" />);
    const field = screen.getByTestId("search-command-input");
    expect(field).toHaveFocus();
    expect(screen.getByRole("heading", { name: "Search", level: 1 })).toBeTruthy();
    expect(screen.getByTestId("search-command-list")).toHaveTextContent("Start typing to search.");
    expect(screen.queryByRole("link", { name: "Today" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Work" })).toBeNull();
    expect(screen.queryByRole("link", { name: "People" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Review" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Quick Capture" })).toBeNull();
  });

  it("summarizes coverage with omitted domains still omitted", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          shape: "backend",
          query: "morning",
          hits: [TASK_HIT],
          coverage: [
            { domain: "tasks", state: "searched", hitCount: 1 },
            { domain: "goodnotes", state: "searched", hitCount: 0 },
            { domain: "knowledge", state: "knowledge_not_enrolled", hitCount: 0 },
            { domain: "meetings", state: "omitted", hitCount: 0, reason: "no_search_capability" },
          ],
          disclosure: {
            scope: "search",
            coverage: "partial",
            freshnessAt: null,
            authority: "derived",
            limitations: ["knowledge is not enrolled"],
            truncated: false,
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    render(<SearchPage initialQuery="" />);
    await user.type(screen.getByTestId("search-command-input"), "morning");

    expect(await screen.findByTestId("search-group-tasks")).toHaveTextContent("Morning task");
    const coverage = screen.getByTestId("search-coverage");
    expect(coverage).toHaveTextContent("goodnotes: searched");
    expect(coverage).not.toHaveTextContent("goodnotes: omitted");
    expect(coverage).toHaveTextContent("meetings: omitted (no_search_capability)");
    expect(coverage).toHaveTextContent("knowledge_not_enrolled");
    expect(screen.getByRole("button", { name: "Quick Capture" })).toBeTruthy();
    expect(collectLevel1Copy(document.body)).not.toMatch(/coverage token/i);
  });

  it("does not treat all-unavailable zero hits as empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          shape: "backend",
          query: "morning",
          hits: [],
          coverage: [
            { domain: "tasks", state: "unavailable", hitCount: 0 },
            { domain: "meetings", state: "omitted", hitCount: 0, reason: "no_search_capability" },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    render(<SearchPage initialQuery="morning" />);
    expect(await screen.findByTestId("search-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("search-empty")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("search-coverage")).toHaveTextContent("meetings: omitted"));
  });
});
