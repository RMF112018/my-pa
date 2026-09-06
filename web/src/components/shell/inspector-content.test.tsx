/**
 * The Inspector content slot, and the proof that adding it changed nothing.
 *
 * `shell.test.tsx` and `canvas-inspector.test.tsx` already cover the region and
 * the canvas body respectively; what neither can assert is the property this
 * generalization has to hold, which is that a *widened* selection type left the
 * canvas path alone. So this asserts it directly and from both ends: with no
 * feature registered the region still renders the canvas body under the heading
 * it always had, and a canvas selection still reads back through
 * `useInspectorSelection().selection` exactly as it was set.
 */
import { useCallback } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  InspectorSelectionProvider,
  useInspectorContent,
  useInspectorSelection,
  type CanvasInspectorSelection,
} from "@/components/shell/inspector-selection";
import { UtilityRegion } from "@/components/shell/utility-region";

vi.mock("next/navigation", () => ({
  usePathname: () => "/canvas",
  useRouter: () => ({ push: () => undefined, refresh: () => undefined }),
}));

const NODE: CanvasInspectorSelection = {
  kind: "node",
  node: {
    entity_id: "ent_aaaaaaaa11111111",
    display_name: "Synthetic Entity",
  } as CanvasInspectorSelection extends { kind: "node"; node: infer N } ? N : never,
};

beforeEach(() => {
  // `CanvasInspector` reads an entity's identity history on selection. The
  // subject here is where its body is placed, not what it says, so the socket
  // answers an empty success rather than being left to reject unhandled.
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ result: {}, disclosure: {} }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Region() {
  return (
    <UtilityRegion
      open
      onOpenChange={() => undefined}
      pinned={false}
      onPinnedChange={() => undefined}
      width={360}
      onWidthChange={() => undefined}
    />
  );
}

function SelectNode() {
  const { setSelection, selection } = useInspectorSelection();
  return (
    <>
      <button type="button" onClick={() => setSelection(NODE)}>
        select node
      </button>
      <span data-testid="canvas-selection-kind">{selection === null ? "none" : selection.kind}</span>
    </>
  );
}

function SelectConstraint() {
  const { setSelection } = useInspectorSelection();
  // Memoized, as the hook's contract requires.
  const render = useCallback(
    () => <p data-testid="feature-body">Feature-owned Inspector body.</p>,
    [],
  );
  useInspectorContent("constraint", { title: "Constraint 1.01", render });
  return (
    <button
      type="button"
      onClick={() => setSelection({ kind: "constraint", constraintId: "cst_syn_0001", projectId: "prj_syn_0001" })}
    >
      select constraint
    </button>
  );
}

describe("the shared Inspector region", () => {
  it("renders the canvas body under the default heading when nothing is registered", () => {
    render(
      <InspectorSelectionProvider>
        <Region />
      </InspectorSelectionProvider>,
    );
    expect(screen.getByRole("heading", { name: "Inspector" })).toBeInTheDocument();
    expect(screen.getByTestId("inspector-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("feature-body")).toBeNull();
  });

  it("still reports a canvas selection unchanged to canvas consumers", async () => {
    const user = userEvent.setup();
    render(
      <InspectorSelectionProvider>
        <SelectNode />
        <Region />
      </InspectorSelectionProvider>,
    );
    await user.click(screen.getByRole("button", { name: "select node" }));
    expect(screen.getByTestId("canvas-selection-kind")).toHaveTextContent("node");
    // The canvas body, not a feature body, and still under the shell's heading.
    expect(screen.getByRole("heading", { name: "Inspector" })).toBeInTheDocument();
    expect(screen.queryByTestId("feature-body")).toBeNull();
  });

  it("gives the region to the feature that owns the selected kind", async () => {
    const user = userEvent.setup();
    render(
      <InspectorSelectionProvider>
        <SelectConstraint />
        <Region />
      </InspectorSelectionProvider>,
    );
    await user.click(screen.getByRole("button", { name: "select constraint" }));
    expect(screen.getByTestId("feature-body")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Constraint 1.01" })).toBeInTheDocument();
    // One region, and the canvas body is not also mounted inside it.
    expect(screen.getAllByRole("complementary", { name: "Utility region" })).toHaveLength(1);
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });

  it("reads a Constraint selection as no canvas selection at all", async () => {
    const user = userEvent.setup();
    render(
      <InspectorSelectionProvider>
        <SelectNode />
        <SelectConstraint />
        <Region />
      </InspectorSelectionProvider>,
    );
    await user.click(screen.getByRole("button", { name: "select constraint" }));
    expect(screen.getByTestId("canvas-selection-kind")).toHaveTextContent("none");
  });

  it("hands the region back when the feature unmounts", async () => {
    const user = userEvent.setup();
    function Harness({ mounted }: { mounted: boolean }) {
      return (
        <InspectorSelectionProvider>
          {mounted ? <SelectConstraint /> : null}
          <Region />
        </InspectorSelectionProvider>
      );
    }
    const view = render(<Harness mounted />);
    await user.click(screen.getByRole("button", { name: "select constraint" }));
    expect(screen.getByTestId("feature-body")).toBeInTheDocument();
    view.rerender(<Harness mounted={false} />);
    expect(screen.queryByTestId("feature-body")).toBeNull();
  });
});
