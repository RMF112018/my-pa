/**
 * Canonical People addresses. Search and resolve stay on `/people`.
 * A profile is `/people/{entityId}`. Query-param `entityId` is compatibility only.
 */
export function peopleHome(): "/people" {
  return "/people";
}

export function peopleEntity(entityId: string): string {
  return `/people/${encodeURIComponent(entityId)}`;
}
