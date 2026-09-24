"use client";

import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { useProjectScope } from "@/components/shell/project-scope-provider";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";
import { apiPost } from "@/lib/api/client";

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

  /**
   * Accepted deep-link persistence (`PC-CM-SCOPE-AC-009`, and the first half of
   * `PC-CM-SCOPE-AC-016`): an authorized Project deep link is written back as
   * the remembered preference, through the same `POST /api/project-scope`
   * Phase 2 built, so leaving and returning without the link later still lands
   * on this Project rather than whatever was previously saved.
   *
   * This never gates rendering. The apply effect above already bound this
   * route's runtime Project scope from the server-resolved `resolution` —
   * before this effect runs, and regardless of whether this write ever
   * completes or succeeds. A malformed or otherwise rejected deep link
   * normalizes to `ALL_PROJECTS` upstream in `resolveAuthenticatedProjectScope`
   * before it ever reaches this component, so `resolution.scope.kind` is
   * `"PROJECT"` here only for an accepted deep link, and only an accepted one
   * is ever persisted.
   */
  useEffect(() => {
    if (resolution.scope.kind !== "PROJECT") return;
    void apiPost({ hasSession: true }, "/api/project-scope", {
      scope: "PROJECT",
      projectId: resolution.scope.projectId,
    }).catch(() => {
      // Best-effort. This route's authority already came from `resolution`,
      // never from this write succeeding — see the comment above.
    });
  }, [resolution]);

  return children;
}
