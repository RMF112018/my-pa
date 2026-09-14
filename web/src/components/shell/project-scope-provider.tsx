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
  principalId,
  sessionEpoch,
  initialResolution = DEFAULT_PROJECT_SCOPE_RESOLUTION,
  children,
}: {
  /** Server-authenticated canonical Principal identifier. */
  readonly principalId: string;
  /** Authenticated Principal/session binding; never sent to an API. */
  readonly sessionEpoch: string;
  readonly initialResolution?: ResolvedProjectScope;
  readonly children: ReactNode;
}) {
  const [state, setState] = useState({
    resolution: initialResolution,
    initialResolution,
    epoch: 0,
    principalId,
    sessionEpoch,
  });
  const epochRef = useRef(0);

  // The authenticated layout can be re-resolved without remounting AppShell.
  // Adjust during the provider render so children never render a prior
  // Principal's Project. This guarded update is also why route-local scope can
  // differ from the last initial resolution without being reset on every render.
  const sessionChanged =
    state.principalId !== principalId || state.sessionEpoch !== sessionEpoch;
  const initialResolutionChanged = !sameResolution(
    state.initialResolution,
    initialResolution,
  );
  if (sessionChanged || initialResolutionChanged) {
    const epoch = state.epoch + 1;
    epochRef.current = epoch;
    setState({
      resolution: initialResolution,
      initialResolution,
      epoch,
      principalId,
      sessionEpoch,
    });
  }

  const applyResolution = useCallback((resolution: ResolvedProjectScope) => {
    setState((current) => {
      const sameScope = sameProjectScope(current.resolution.scope, resolution.scope);
      const sameVersion = current.resolution.project?.version === resolution.project?.version;
      const sameState = current.resolution.project?.state === resolution.project?.state;
      if (sameScope && sameVersion && sameState) return { ...current, resolution };
      const epoch = current.epoch + 1;
      epochRef.current = epoch;
      return { ...current, resolution, epoch };
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

function sameResolution(left: ResolvedProjectScope, right: ResolvedProjectScope): boolean {
  return (
    sameProjectScope(left.scope, right.scope) &&
    left.project?.project_id === right.project?.project_id &&
    left.project?.version === right.project?.version &&
    left.project?.state === right.project?.state &&
    left.source === right.source &&
    left.normalized === right.normalized
  );
}

export function useProjectScope(): ProjectScopeContextValue {
  const value = useContext(ProjectScopeContext);
  if (!value) throw new Error("useProjectScope is only valid inside ProjectScopeProvider");
  return value;
}
