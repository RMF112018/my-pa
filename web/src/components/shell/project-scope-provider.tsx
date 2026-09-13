"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  DEFAULT_PROJECT_SCOPE_RESOLUTION,
  type ResolvedProjectScope,
} from "@/lib/project-scope/resolver";
import { sameProjectScope } from "@/lib/project-scope/scope";

export interface ProjectScopeContextValue {
  readonly resolution: ResolvedProjectScope;
  /** Monotonic within this mounted authenticated shell. */
  readonly epoch: number;
  /** Accept only a result produced by the authenticated resolver. */
  readonly applyResolution: (resolution: ResolvedProjectScope) => void;
  readonly isCurrentEpoch: (epoch: number) => boolean;
}

const ProjectScopeContext = createContext<ProjectScopeContextValue | null>(null);

export function ProjectScopeProvider({
  initialResolution = DEFAULT_PROJECT_SCOPE_RESOLUTION,
  children,
}: {
  readonly initialResolution?: ResolvedProjectScope;
  readonly children: ReactNode;
}) {
  const [state, setState] = useState({ resolution: initialResolution, epoch: 0 });
  const epochRef = useRef(0);

  const applyResolution = useCallback((resolution: ResolvedProjectScope) => {
    setState((current) => {
      const sameScope = sameProjectScope(current.resolution.scope, resolution.scope);
      const sameVersion = current.resolution.project?.version === resolution.project?.version;
      const sameState = current.resolution.project?.state === resolution.project?.state;
      if (sameScope && sameVersion && sameState) return { ...current, resolution };
      const epoch = current.epoch + 1;
      epochRef.current = epoch;
      return { resolution, epoch };
    });
  }, []);

  const isCurrentEpoch = useCallback((epoch: number) => epochRef.current === epoch, []);
  const value = useMemo<ProjectScopeContextValue>(
    () => ({ resolution: state.resolution, epoch: state.epoch, applyResolution, isCurrentEpoch }),
    [applyResolution, isCurrentEpoch, state],
  );

  return (
    <ProjectScopeContext.Provider value={value}>
      {children}
    </ProjectScopeContext.Provider>
  );
}

export function useProjectScope(): ProjectScopeContextValue {
  const value = useContext(ProjectScopeContext);
  if (!value) throw new Error("useProjectScope is only valid inside ProjectScopeProvider");
  return value;
}
