"use client";

import {
  Component,
  createContext,
  useContext,
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

interface ProjectScopeProviderProps {
  /** Server-authenticated canonical Principal identifier. */
  readonly principalId: string;
  /** Authenticated Principal/session binding; never sent to an API. */
  readonly sessionEpoch: string;
  readonly initialResolution?: ResolvedProjectScope;
  readonly children: ReactNode;
}

interface ProjectScopeOwnerProps extends ProjectScopeProviderProps {
  readonly initialResolution: ResolvedProjectScope;
}

interface ProjectScopeOwnerState {
  readonly resolution: ResolvedProjectScope;
  readonly initialResolution: ResolvedProjectScope;
  readonly epoch: number;
  readonly principalId: string;
  readonly sessionEpoch: string;
}

class ProjectScopeOwner extends Component<ProjectScopeOwnerProps, ProjectScopeOwnerState> {
  state: ProjectScopeOwnerState = {
    resolution: this.props.initialResolution,
    initialResolution: this.props.initialResolution,
    epoch: 0,
    principalId: this.props.principalId,
    sessionEpoch: this.props.sessionEpoch,
  };

  // The authenticated layout can be re-resolved without remounting AppShell.
  // Derive the replacement before descendant render so children never observe
  // a prior Principal's Project, while route-local scope remains independent.
  static getDerivedStateFromProps(
    props: ProjectScopeOwnerProps,
    state: ProjectScopeOwnerState,
  ): ProjectScopeOwnerState | null {
    const sessionChanged =
      state.principalId !== props.principalId || state.sessionEpoch !== props.sessionEpoch;
    const initialResolutionChanged = !sameResolution(
      state.initialResolution,
      props.initialResolution,
    );
    if (!sessionChanged && !initialResolutionChanged) return null;
    return {
      resolution: props.initialResolution,
      initialResolution: props.initialResolution,
      epoch: state.epoch + 1,
      principalId: props.principalId,
      sessionEpoch: props.sessionEpoch,
    };
  }

  private readonly applyResolution = (resolution: ResolvedProjectScope) => {
    this.setState((current) => {
      const sameScope = sameProjectScope(current.resolution.scope, resolution.scope);
      const sameVersion = current.resolution.project?.version === resolution.project?.version;
      const sameState = current.resolution.project?.state === resolution.project?.state;
      if (sameScope && sameVersion && sameState) return { ...current, resolution };
      return { ...current, resolution, epoch: current.epoch + 1 };
    });
  };

  private readonly isCurrentEpoch = (epoch: number) => this.state.epoch === epoch;

  render() {
    const value: ProjectScopeContextValue = {
      resolution: this.state.resolution,
      epoch: this.state.epoch,
      applyResolution: this.applyResolution,
      isCurrentEpoch: this.isCurrentEpoch,
    };
    return (
      <ProjectScopeContext.Provider value={value}>
        {this.props.children}
      </ProjectScopeContext.Provider>
    );
  }
}

export function ProjectScopeProvider({
  initialResolution = DEFAULT_PROJECT_SCOPE_RESOLUTION,
  ...props
}: ProjectScopeProviderProps) {
  return <ProjectScopeOwner {...props} initialResolution={initialResolution} />;
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
