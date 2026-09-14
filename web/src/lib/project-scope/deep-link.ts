import { isProjectId } from "./scope";

export type DeepLinkProject =
  | { readonly kind: "absent" }
  | { readonly kind: "present"; readonly projectId: string | null };

/**
 * Extract the explicit Project segment from canonical `/work/projects/:id`
 * routes. A malformed segment remains present and therefore outranks a saved
 * preference; callers normalize it safely instead of silently selecting some
 * other Project.
 */
export function projectFromDeepLink(pathname: string): DeepLinkProject {
  const match = /^\/work\/projects\/([^/]+)(?:\/|$)/.exec(pathname);
  if (!match) return { kind: "absent" };
  let decoded: string;
  try {
    decoded = decodeURIComponent(match[1]!);
  } catch {
    return { kind: "present", projectId: null };
  }
  return { kind: "present", projectId: isProjectId(decoded) ? decoded : null };
}
