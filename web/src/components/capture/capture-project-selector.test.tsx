/**
 * T11 — the bounded Project chooser (C04).
 *
 * Two things carry the weight. A selection is never silently dropped or
 * relabelled — not by paging, not by a failed load, not by a late answer from a
 * previous session. And "unavailable" is said out loud rather than shown as No
 * Project, because those are opposite claims about where a note will be filed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  CAPTURE_NO_PROJECT_LABEL,
  CAPTURE_PROJECT_LABEL,
  CAPTURE_PROJECT_MAX_VISITED_CURSORS,
  CAPTURE_PROJECT_PAGE_BOUND,
  CAPTURE_PROJECT_UNAVAILABLE,
  CaptureProjectSelector,
} from "@/components/capture/capture-project-selector";

const PRINCIPAL_A = "aaaa0001-0000-0000-0000-000000000001";
const PRINCIPAL_B = "bbbb0002-0000-0000-0000-000000000002";

/** Thirty Projects: more than one fixed page of 25. */
const ALL = Array.from({ length: 30 }, (_, index) => ({
  projectId: `prj_aaaaaaaa${String(index).padStart(8, "0")}`,
  name: `Project ${index}`,
}));
const PAGE_ONE = ALL.slice(0, 25);
const PAGE_TWO = ALL.slice(25);
/** The selected Project deliberately sits on the second page. */
const SECOND_PAGE_PROJECT = PAGE_TWO[0]!;

type FetchCall = [input: string | Request | URL, init?: RequestInit];
let fetchSpy: { mock: { calls: FetchCall[] } };

function pages(options: { readonly failAfter?: number; readonly cursors?: number } = {}) {
  let calls = 0;
  fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    calls += 1;
    if (options.failAfter !== undefined && calls > options.failAfter) {
      return new Response("{}", { status: 503 });
    }
    if (url.startsWith("/api/projects/")) {
      const id = url.slice("/api/projects/".length);
      const found = ALL.find((row) => row.projectId === id);
      return found
        ? new Response(JSON.stringify({ project: { name: found.name } }), { status: 200 })
        : new Response("{}", { status: 404 });
    }
    const after = new URL(url, "http://localhost").searchParams.get("after");
    if (after === null) {
      return new Response(
        JSON.stringify({ projects: PAGE_ONE, nextCursor: "cursor-1" }),
        { status: 200 },
      );
    }
    const depth = Number(after.split("-")[1] ?? 1);
    const last = options.cursors !== undefined && depth >= options.cursors;
    return new Response(
      JSON.stringify({
        projects: depth === 1 ? PAGE_TWO : PAGE_ONE,
        nextCursor: last ? null : `cursor-${depth + 1}`,
      }),
      { status: 200 },
    );
  });
  return fetchSpy;
}

function renderSelector(
  props: Partial<React.ComponentProps<typeof CaptureProjectSelector>> = {},
) {
  const onChange = vi.fn();
  const view = render(
    <CaptureProjectSelector
      id="project-field"
      value={null}
      onChange={onChange}
      disabled={false}
      principalId={PRINCIPAL_A}
      sessionEpoch={1}
      {...props}
    />,
  );
  return { onChange, view };
}

beforeEach(() => {
  pages();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the label and the explicit No Project choice", () => {
  it("has a visible associated label", async () => {
    renderSelector();
    const select = await screen.findByLabelText(CAPTURE_PROJECT_LABEL);
    expect(select).toBe(screen.getByTestId("capture-project-select"));
  });

  it("offers No Project explicitly and selects it for a null value", async () => {
    renderSelector();
    const select = await screen.findByTestId("capture-project-select");
    expect(within(select).getByText(CAPTURE_NO_PROJECT_LABEL)).toBeInTheDocument();
    expect(select).toHaveValue("");
  });

  it("reports an explicit No Project choice as null, not as an empty string", async () => {
    const user = userEvent.setup();
    const { onChange } = renderSelector({ value: ALL[0]!.projectId });
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(within(select).getByText("Project 0")).toBeInTheDocument());
    await user.selectOptions(select, "");
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("reports a chosen Project by its identifier", async () => {
    const user = userEvent.setup();
    const { onChange } = renderSelector();
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(within(select).getByText("Project 3")).toBeInTheDocument());
    await user.selectOptions(select, ALL[3]!.projectId);
    expect(onChange).toHaveBeenCalledWith(ALL[3]!.projectId);
  });
});

describe("names come only from an authorized read", () => {
  it("labels a selection that is on the loaded page from that page", async () => {
    renderSelector({ value: ALL[2]!.projectId });
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(select).toHaveValue(ALL[2]!.projectId));
    expect(within(select).getByText("Project 2")).toBeInTheDocument();
    // Once the page names it, no further exact read is issued for it. (One may
    // already have gone out before the page arrived — until it does, this
    // control genuinely does not know the name.)
    const exactReads = () =>
      fetchSpy.mock.calls.filter(([input]: FetchCall) => String(input).startsWith("/api/projects/")).length;
    const settled = exactReads();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(exactReads()).toBe(settled);
  });

  it("labels a selection from another page through the exact authorized read", async () => {
    renderSelector({ value: SECOND_PAGE_PROJECT.projectId });
    await waitFor(() =>
      expect(screen.getByTestId("capture-project-select")).toHaveValue(
        SECOND_PAGE_PROJECT.projectId,
      ),
    );
    await waitFor(() =>
      expect(
        within(screen.getByTestId("capture-project-select")).getByText(SECOND_PAGE_PROJECT.name),
      ).toBeInTheDocument(),
    );
    expect(
      fetchSpy.mock.calls.some(([input]: FetchCall) =>
        String(input).startsWith(`/api/projects/${SECOND_PAGE_PROJECT.projectId}`),
      ),
    ).toBe(true);
  });

  it("retains an unresolvable selection and says so, rather than falling back", async () => {
    // A foreign or revoked Project reads as the same nondisclosing refusal.
    renderSelector({ value: "prj_ffffffff99999999" });
    const notice = await screen.findByTestId("capture-project-unavailable");
    expect(notice).toHaveTextContent(CAPTURE_PROJECT_UNAVAILABLE);
    const select = screen.getByTestId("capture-project-select");
    // Still selected. Not No Project, and not renamed from anywhere.
    expect(select).toHaveValue("prj_ffffffff99999999");
    expect(select).not.toHaveValue("");
  });

  it("never offers a row whose shape it does not recognise", async () => {
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          projects: [
            { projectId: "not-a-project", name: "Bad identifier" },
            { projectId: ALL[0]!.projectId, name: "" },
            { projectId: ALL[1]!.projectId, name: "Good" },
          ],
          nextCursor: null,
        }),
        { status: 200 },
      ),
    );
    renderSelector();
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(within(select).getByText("Good")).toBeInTheDocument());
    expect(within(select).queryByText("Bad identifier")).toBeNull();
  });
});

describe("paging is bounded and never loses the selection", () => {
  it("asks for the next page with the disclosed cursor, unchanged", async () => {
    const user = userEvent.setup();
    renderSelector();
    await screen.findByTestId("capture-project-select");
    await user.click(screen.getByTestId("capture-project-next"));
    await waitFor(() =>
      expect(
        fetchSpy.mock.calls.some(([input]: FetchCall) => String(input).includes("after=cursor-1")),
      ).toBe(true),
    );
  });

  it("keeps the selected Project offerable while paging away from it", async () => {
    const user = userEvent.setup();
    renderSelector({ value: ALL[0]!.projectId });
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(within(select).getByText("Project 0")).toBeInTheDocument());

    await user.click(screen.getByTestId("capture-project-next"));
    // Page two does not contain Project 0, and it is still selected and named.
    await waitFor(() =>
      expect(within(select).getByText(SECOND_PAGE_PROJECT.name)).toBeInTheDocument(),
    );
    expect(select).toHaveValue(ALL[0]!.projectId);
  });

  it("goes back through the cursor stack", async () => {
    const user = userEvent.setup();
    renderSelector();
    const select = await screen.findByTestId("capture-project-select");
    expect(screen.getByTestId("capture-project-previous")).toBeDisabled();
    await user.click(screen.getByTestId("capture-project-next"));
    await waitFor(() =>
      expect(within(select).getByText(SECOND_PAGE_PROJECT.name)).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("capture-project-previous"));
    await waitFor(() => expect(within(select).getByText("Project 0")).toBeInTheDocument());
  });

  it("refuses beyond the visited-cursor bound without dropping the selection", async () => {
    const user = userEvent.setup();
    pages({ cursors: 500 });
    renderSelector({ value: ALL[0]!.projectId });
    await screen.findByTestId("capture-project-select");

    for (let step = 1; step < CAPTURE_PROJECT_MAX_VISITED_CURSORS; step += 1) {
      await user.click(screen.getByTestId("capture-project-next"));
    }
    await user.click(screen.getByTestId("capture-project-next"));

    const notice = await screen.findByTestId("capture-project-notice");
    expect(notice).toHaveTextContent(CAPTURE_PROJECT_PAGE_BOUND);
    expect(screen.getByTestId("capture-project-select")).toHaveValue(ALL[0]!.projectId);
  });

  it("does not auto-fetch every page", async () => {
    renderSelector();
    await screen.findByTestId("capture-project-select");
    await waitFor(() =>
      expect(
        fetchSpy.mock.calls.filter(([input]: FetchCall) => String(input).startsWith("/api/projects")).length,
      ).toBeGreaterThan(0),
    );
    // One page, and nothing that walks the cursor on its own.
    expect(
      fetchSpy.mock.calls.filter(([input]: FetchCall) => String(input).includes("after=")),
    ).toHaveLength(0);
  });

  it("leaves the selection intact when a page fails to load", async () => {
    const user = userEvent.setup();
    pages({ failAfter: 1 });
    renderSelector({ value: ALL[0]!.projectId });
    await screen.findByTestId("capture-project-select");
    await user.click(screen.getByTestId("capture-project-next"));

    await screen.findByTestId("capture-project-notice");
    expect(screen.getByTestId("capture-project-select")).toHaveValue(ALL[0]!.projectId);
  });
});

describe("a change here is local", () => {
  it("writes nothing but its own callback", async () => {
    const user = userEvent.setup();
    const { onChange } = renderSelector();
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(within(select).getByText("Project 1")).toBeInTheDocument());

    const writes = fetchSpy.mock.calls.filter(
      ([, init]: FetchCall) => String(init?.method ?? "GET").toUpperCase() !== "GET",
    );
    await user.selectOptions(select, ALL[1]!.projectId);

    expect(onChange).toHaveBeenCalledWith(ALL[1]!.projectId);
    // No preference write, no scope resolution, no mutation of any kind.
    expect(writes).toHaveLength(0);
    expect(localStorage.length).toBe(0);
  });

  it("disables every control while the surface is inert", async () => {
    renderSelector({ disabled: true, value: ALL[0]!.projectId });
    const select = await screen.findByTestId("capture-project-select");
    expect(select).toBeDisabled();
    expect(screen.getByTestId("capture-project-next")).toBeDisabled();
    expect(screen.getByTestId("capture-project-previous")).toBeDisabled();
  });
});

describe("a stale session can never relabel a later one", () => {
  it("discards a page that resolves after the Principal changed", async () => {
    let releaseA!: () => void;
    const gateA = new Promise<void>((resolve) => {
      releaseA = resolve;
    });
    let call = 0;
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      call += 1;
      if (call === 1) {
        // A's page is held open across the account switch.
        await gateA;
        return new Response(
          JSON.stringify({
            projects: [{ projectId: ALL[0]!.projectId, name: "A's project" }],
            nextCursor: null,
          }),
          { status: 200 },
        );
      }
      return new Response(
        JSON.stringify({
          projects: [{ projectId: ALL[1]!.projectId, name: "B's project" }],
          nextCursor: null,
        }),
        { status: 200 },
      );
    });

    const onChange = vi.fn();
    const { rerender } = render(
      <CaptureProjectSelector
        id="project-field"
        value={null}
        onChange={onChange}
        disabled={false}
        principalId={PRINCIPAL_A}
        sessionEpoch={1}
      />,
    );
    rerender(
      <CaptureProjectSelector
        id="project-field"
        value={null}
        onChange={onChange}
        disabled={false}
        principalId={PRINCIPAL_B}
        sessionEpoch={2}
      />,
    );

    // B's page lands first and is what the control shows.
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(within(select).getByText("B's project")).toBeInTheDocument());

    // Now A's page finally arrives. It must not replace B's.
    releaseA();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(within(select).getByText("B's project")).toBeInTheDocument();
    expect(within(select).queryByText("A's project")).toBeNull();
  });
});
