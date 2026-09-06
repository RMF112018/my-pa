"use client";

/**
 * What the shell's one Inspector is currently showing, and who supplies its body.
 *
 * The region itself is `components/shell/utility-region.tsx`: one right-hand
 * panel on desktop, one Sheet on mobile, one pin state, one width, one set of
 * preferences. A feature that wanted its own detail surface would have to
 * duplicate all of that, and the duplicate would immediately disagree with the
 * original about where detail appears. So features do not bring drawers; they
 * bring a selection kind and a body, and the shell places both
 * (`CM-FE-AC-090`).
 *
 * The generalization here is strictly additive. `CanvasInspectorSelection` is
 * the union that existed before — a graph node or a graph edge — unchanged, and
 * `useInspectorSelection().selection` still has exactly that type, so every
 * canvas consumer sees the same values it always did and needed no edit. What
 * is new sits alongside: a `constraint` member on the wider
 * `InspectorSelection`, readable through `shellSelection`, and a registry that
 * lets a feature publish the body for its own kind. With nothing registered —
 * every case that existed before this file changed — the shell behaves exactly
 * as it did.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

/**
 * The graph selections the Map publishes. Unchanged, and deliberately kept as
 * its own type so that widening what the shell can hold does not widen what a
 * canvas consumer must handle.
 */
export type CanvasInspectorSelection =
  | { readonly kind: "node"; readonly node: GraphNode }
  | {
      readonly kind: "edge";
      readonly edge: GraphEdge;
      readonly from?: GraphNode;
      readonly to?: GraphNode;
    };

/**
 * A Constraint selected in the Project Controls workspace.
 *
 * Identity only — the Constraint's id and the Project it belongs to. A
 * selection is a fact about what the reader picked, not a place to park a
 * record: the feature already holds the row it read, and copying it in here
 * would give the shell a second copy that could go stale.
 */
export type ConstraintInspectorSelection = {
  readonly kind: "constraint";
  readonly constraintId: string;
  readonly projectId: string;
};

/** Everything the one Inspector can be showing. */
export type InspectorSelection =
  | CanvasInspectorSelection
  | ConstraintInspectorSelection
  | null;

/** The kinds a selection can have, without the `null`. */
export type InspectorSelectionKind = NonNullable<InspectorSelection>["kind"];

/**
 * A feature's Inspector body, and the heading the region shows over it.
 *
 * A feature registers one for the selection kind it owns while it is mounted;
 * unmounting withdraws it and hands the region straight back.
 */
export interface InspectorContent {
  /** Heading for the region. The shell shows "Inspector" when none applies. */
  readonly title: string;
  readonly render: () => ReactNode;
}

export type InspectorSelectionValue = {
  /**
   * The selection as the canvas surfaces see it: a node, an edge, or nothing.
   * A Constraint selection reads as `null` here, which is the truthful answer
   * to "what graph object is selected" and keeps every existing consumer's
   * behaviour identical for every value it can itself produce.
   */
  readonly selection: CanvasInspectorSelection | null;
  /** The selection in full, for the shell and for the feature that owns it. */
  readonly shellSelection: InspectorSelection;
  readonly setSelection: (next: InspectorSelection) => void;
  /**
   * Publish the Inspector body for one selection kind; returns the withdrawal.
   */
  readonly registerInspectorContent: (
    kind: InspectorSelectionKind,
    content: InspectorContent,
  ) => () => void;
  /** The content registered for the current selection, if any. */
  readonly inspectorContent: InspectorContent | null;
};

const InspectorSelectionContext = createContext<InspectorSelectionValue>({
  selection: null,
  shellSelection: null,
  setSelection: () => undefined,
  registerInspectorContent: () => () => undefined,
  inspectorContent: null,
});

export function InspectorSelectionProvider({
  children,
  onSelectionPublished,
}: {
  children: ReactNode;
  onSelectionPublished?: () => void;
}) {
  const [selection, setSelectionState] = useState<InspectorSelection>(null);
  const [contents, setContents] = useState<
    Readonly<Partial<Record<InspectorSelectionKind, InspectorContent>>>
  >({});
  const setSelection = useCallback(
    (next: InspectorSelection) => {
      setSelectionState(next);
      if (next !== null) onSelectionPublished?.();
    },
    [onSelectionPublished],
  );
  const registerInspectorContent = useCallback(
    (kind: InspectorSelectionKind, content: InspectorContent) => {
      setContents((current) => ({ ...current, [kind]: content }));
      return () => {
        setContents((current) => {
          if (!(kind in current)) return current;
          const rest = { ...current };
          delete rest[kind];
          return rest;
        });
      };
    },
    [],
  );
  const inspectorContent = selection === null ? null : (contents[selection.kind] ?? null);
  const value = useMemo(
    () => ({
      selection: selection === null || selection.kind === "constraint" ? null : selection,
      shellSelection: selection,
      setSelection,
      registerInspectorContent,
      inspectorContent,
    }),
    [selection, setSelection, registerInspectorContent, inspectorContent],
  );
  return (
    <InspectorSelectionContext.Provider value={value}>{children}</InspectorSelectionContext.Provider>
  );
}

export function useInspectorSelection(): InspectorSelectionValue {
  return useContext(InspectorSelectionContext);
}

/**
 * Register an Inspector body for as long as the calling component is mounted.
 *
 * `title` and `render` are the registration's identity, exactly as a dependency
 * list is: when either changes the body is published again, which is what makes
 * a heading follow the selected record and a body follow the record's detail
 * read. **`render` must therefore be memoized by the caller** — an inline
 * closure is a new function on every render and would re-register on every
 * render, which is the same mistake as an unmemoized `useEffect` dependency and
 * has the same cure.
 */
export function useInspectorContent(kind: InspectorSelectionKind, content: InspectorContent): void {
  const { registerInspectorContent } = useInspectorSelection();
  const { title, render } = content;
  useEffect(
    () => registerInspectorContent(kind, { title, render }),
    [kind, title, render, registerInspectorContent],
  );
}
