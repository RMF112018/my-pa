/**
 * Level-1 copy scanner for non-System surfaces.
 *
 * Tests use this to catch doctrine vocabulary that must not be the first thing
 * a reader sees. It is not a runtime copy framework.
 */

export type UserCopySurface = "product" | "system";

type ForbiddenTerm = {
  readonly id: string;
  readonly pattern: RegExp;
};

const FORBIDDEN_LEVEL1_TERMS: readonly ForbiddenTerm[] = [
  { id: "Principal", pattern: /\bPrincipal\b/ },
  { id: "plane", pattern: /\bplane\b/i },
  { id: "canonical", pattern: /\bcanonical\b/i },
  { id: "persisted", pattern: /\bpersisted\b/i },
  { id: "replayed", pattern: /\breplayed\b/i },
  { id: "idempotency", pattern: /\bidempotency\b/i },
  { id: "coverage token", pattern: /\bcoverage token\b/i },
  { id: "worker", pattern: /\bworkers?\b/i },
  { id: "gateway", pattern: /\bgateway\b/i },
  { id: "Retry Work read", pattern: /Retry Work read/ },
];

function hasStorageArtifact(text: string): boolean {
  return /\bartifacts?\b/i.test(text) && /\b(storage|stored|persisted|persist)\b/i.test(text);
}

/** Returns the forbidden Level-1 terms found in `text`. System surfaces are skipped. */
export function classifyForbiddenLevel1Copy(
  text: string,
  surface: UserCopySurface = "product",
): string[] {
  if (surface === "system") return [];
  const hits: string[] = [];
  for (const term of FORBIDDEN_LEVEL1_TERMS) {
    if (term.pattern.test(text)) hits.push(term.id);
  }
  if (hasStorageArtifact(text)) hits.push("artifact");
  return hits;
}
