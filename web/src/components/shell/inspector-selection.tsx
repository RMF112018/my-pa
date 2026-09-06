"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

export type InspectorSelection =
  | { readonly kind: "node"; readonly node: GraphNode }
  | {
      readonly kind: "edge";
      readonly edge: GraphEdge;
      readonly from?: GraphNode;
      readonly to?: GraphNode;
    }
  | null;

export type InspectorSelectionValue = {
  readonly selection: InspectorSelection;
  readonly setSelection: (next: InspectorSelection) => void;
};

const InspectorSelectionContext = createContext<InspectorSelectionValue>({
  selection: null,
  setSelection: () => undefined,
});

export function InspectorSelectionProvider({
  children,
  onSelectionPublished,
}: {
  children: ReactNode;
  onSelectionPublished?: () => void;
}) {
  const [selection, setSelectionState] = useState<InspectorSelection>(null);
  const setSelection = useCallback(
    (next: InspectorSelection) => {
      setSelectionState(next);
      if (next !== null) onSelectionPublished?.();
    },
    [onSelectionPublished],
  );
  const value = useMemo(() => ({ selection, setSelection }), [selection, setSelection]);
  return (
    <InspectorSelectionContext.Provider value={value}>{children}</InspectorSelectionContext.Provider>
  );
}

export function useInspectorSelection(): InspectorSelectionValue {
  return useContext(InspectorSelectionContext);
}
