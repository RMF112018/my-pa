import { ALL_PROJECTS, isProjectId, projectScope, type ProjectScope } from "./scope";

export const PROJECT_SCOPE_COOKIE = "my-pa-project-scope";
const ALL_VALUE = "ALL_PROJECTS";
const PROJECT_PREFIX = "PROJECT:";

/**
 * Parse only values written by this application. No trim, case folding, URI
 * decoding, legacy aliases, or partial matches: malformed preferences carry no
 * authority and are ignored.
 */
export function parseProjectScopePreference(value: string | undefined): ProjectScope | null {
  if (value === ALL_VALUE) return ALL_PROJECTS;
  if (!value?.startsWith(PROJECT_PREFIX)) return null;
  const projectId = value.slice(PROJECT_PREFIX.length);
  return isProjectId(projectId) ? projectScope(projectId) : null;
}

export function projectScopePreferenceValue(scope: ProjectScope): string {
  return scope.kind === "ALL_PROJECTS" ? ALL_VALUE : `${PROJECT_PREFIX}${scope.projectId}`;
}

/** Strict first-party Set-Cookie value for a server-owned preference endpoint. */
export function serializeProjectScopePreference(
  scope: ProjectScope,
  { secure = true }: { secure?: boolean } = {},
): string {
  return [
    `${PROJECT_SCOPE_COOKIE}=${projectScopePreferenceValue(scope)}`,
    "Path=/",
    "Max-Age=31536000",
    "HttpOnly",
    "SameSite=Lax",
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}
