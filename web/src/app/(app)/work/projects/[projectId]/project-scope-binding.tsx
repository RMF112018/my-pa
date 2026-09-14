"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { useProjectScope } from "@/components/shell/project-scope-provider";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";

/** Apply the server-resolved route scope to the one authenticated shell owner. */
export function ProjectRouteScopeBinding({
  resolution,
  fallbackResolution,
  children,
}: {
  readonly resolution: ResolvedProjectScope;
  readonly fallbackResolution: ResolvedProjectScope;
  readonly children: ReactNode;
}) {
  const { applyResolution } = useProjectScope();
  const fallbackRef = useRef(fallbackResolution);
  useLayoutEffect(() => {
    fallbackRef.current = fallbackResolution;
  }, [fallbackResolution]);

  useLayoutEffect(() => applyResolution(resolution), [applyResolution, resolution]);
  // Separate cleanup from the apply effect: a refreshed canonical Project
  // resolution must not restore the parent scope between versions. Cleanup
  // runs only when the route binding itself leaves the tree.
  useLayoutEffect(
    () => () => applyResolution(fallbackRef.current),
    [applyResolution],
  );
  return children;
}
