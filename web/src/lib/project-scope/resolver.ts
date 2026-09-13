import { parseProjectScopePreference } from "./preference";
import { ALL_PROJECTS, isProjectId, projectScope, type ProjectScope } from "./scope";

/** Current canonical lifecycle vocabulary from continuity.projects(.read). */
export type CanonicalProjectState = "active" | "on_hold" | "closed";

/** Fields scope consumes from the canonical exact Project read; no parallel Project model. */
export interface CanonicalProjectScopeRecord {
  readonly project_id: string;
  readonly state: CanonicalProjectState;
  readonly version: number;
}

export type CanonicalProjectRead =
  | { readonly kind: "found"; readonly project: CanonicalProjectScopeRecord }
  | { readonly kind: "not_found" }
  | { readonly kind: "unavailable" };

/**
 * Adapter boundary for authenticated canonical capabilities. Implementations
 * must use `continuity.projects.read` for exact resolution and
 * `continuity.projects` for bounded discovery; they must not infer ownership
 * from caller input or create another Project repository.
 */
export interface CanonicalProjectScopeReader {
  readProject(projectId: string): Promise<CanonicalProjectRead>;
  listProjects(input: {
    readonly after?: string;
    readonly state?: CanonicalProjectState;
    readonly query?: string;
    readonly pageSize: number;
  }): Promise<readonly CanonicalProjectScopeRecord[]>;
}

export type ScopeResolutionSource = "deep_link" | "preference" | "default";

export interface ResolvedProjectScope {
  readonly scope: ProjectScope;
  readonly source: ScopeResolutionSource;
  /** Present only after an authenticated canonical read accepted a Project. */
  readonly project: CanonicalProjectScopeRecord | null;
  /** Generic and deliberately non-oracular. */
  readonly normalized: boolean;
}

export const DEFAULT_PROJECT_SCOPE_RESOLUTION: ResolvedProjectScope = Object.freeze({
  scope: ALL_PROJECTS,
  source: "default",
  project: null,
  normalized: false,
});

export interface ResolveProjectScopeInput {
  /** `undefined`: no Project deep link. `null`: an explicit malformed deep link. */
  readonly deepLinkProjectId?: string | null;
  readonly preferenceValue?: string;
  readonly projects: CanonicalProjectScopeReader;
}

/**
 * Bounded discovery composition over `continuity.projects`. This is not a
 * directory or validator: it forwards the canonical filters, caps one page,
 * and retains only well-formed, versioned, non-closed canonical rows.
 */
export async function discoverProjectScopes(
  projects: CanonicalProjectScopeReader,
  input: {
    readonly after?: string;
    readonly state?: CanonicalProjectState;
    readonly query?: string;
    readonly pageSize?: number;
  } = {},
): Promise<readonly CanonicalProjectScopeRecord[]> {
  const requested = input.pageSize ?? 25;
  const pageSize = Number.isSafeInteger(requested) ? Math.min(100, Math.max(1, requested)) : 25;
  const found = await projects.listProjects({
    ...(input.after === undefined ? {} : { after: input.after }),
    ...(input.state === undefined ? {} : { state: input.state }),
    ...(input.query === undefined ? {} : { query: input.query }),
    pageSize,
  });
  return found.filter(
    (project) =>
      isProjectId(project.project_id) &&
      project.state !== "closed" &&
      Number.isSafeInteger(project.version) &&
      project.version >= 1,
  );
}

/**
 * Deep link wins over preference. A malformed or unreadable candidate becomes
 * ALL_PROJECTS and never falls through to a different saved Project. Unknown,
 * foreign, closed, and otherwise unreadable Projects share the same outward
 * normalization, preserving the canonical exact read's nondisclosure.
 */
export async function resolveAuthenticatedProjectScope(
  input: ResolveProjectScopeInput,
): Promise<ResolvedProjectScope> {
  let candidate: ProjectScope;
  let source: ScopeResolutionSource;

  if (input.deepLinkProjectId !== undefined) {
    source = "deep_link";
    if (!isProjectId(input.deepLinkProjectId)) return normalizedAll(source);
    candidate = projectScope(input.deepLinkProjectId);
  } else {
    source = "preference";
    const parsed = parseProjectScopePreference(input.preferenceValue);
    if (parsed === null) {
      return input.preferenceValue === undefined
        ? DEFAULT_PROJECT_SCOPE_RESOLUTION
        : normalizedAll(source);
    }
    candidate = parsed;
  }

  if (candidate.kind === "ALL_PROJECTS") {
    return { scope: candidate, source, project: null, normalized: false };
  }

  const answer = await input.projects.readProject(candidate.projectId);
  if (
    answer.kind !== "found" ||
    answer.project.project_id !== candidate.projectId ||
    answer.project.state === "closed" ||
    !Number.isSafeInteger(answer.project.version) ||
    answer.project.version < 1
  ) {
    return normalizedAll(source);
  }
  return { scope: candidate, source, project: answer.project, normalized: false };
}

function normalizedAll(source: ScopeResolutionSource): ResolvedProjectScope {
  return { scope: ALL_PROJECTS, source, project: null, normalized: true };
}
