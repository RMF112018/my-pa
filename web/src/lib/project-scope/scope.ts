/** Closed global Project Scope semantic. */
export type ProjectScope =
  | { readonly kind: "ALL_PROJECTS" }
  | { readonly kind: "PROJECT"; readonly projectId: string };

export const ALL_PROJECTS: ProjectScope = Object.freeze({ kind: "ALL_PROJECTS" });

const PROJECT_ID = /^prj_[A-Za-z0-9]{8,64}$/;

/** Shape validation only. Ownership and eligibility come from the canonical Project read. */
export function isProjectId(value: unknown): value is string {
  return typeof value === "string" && PROJECT_ID.test(value);
}

export function projectScope(projectId: string): ProjectScope {
  if (!isProjectId(projectId)) throw new Error("invalid Project identifier");
  return Object.freeze({ kind: "PROJECT", projectId });
}

export function sameProjectScope(left: ProjectScope, right: ProjectScope): boolean {
  return (
    left.kind === right.kind &&
    (left.kind === "ALL_PROJECTS" ||
      (right.kind === "PROJECT" && left.projectId === right.projectId))
  );
}

