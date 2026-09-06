export type MutationRouteClassification =
  | "AUTHENTICATED_BROWSER_MUTATION"
  | "PRE_AUTH_BROWSER_MUTATION"
  | "INTERNAL_NOT_BROWSER";

export type MutationHttpMethod = "POST" | "PUT" | "PATCH" | "DELETE";

export type MutationRouteManifestEntry = {
  readonly method: MutationHttpMethod;
  readonly path: string;
  readonly classification: MutationRouteClassification;
};

/**
 * Inventory of Next.js mutating handlers. Classification is the product policy
 * for each (path, method); INTERNAL_NOT_BROWSER is reserved and currently unused.
 */
export const MUTATION_ROUTE_MANIFEST: readonly MutationRouteManifestEntry[] = [
  {
    method: "POST",
    path: "src/app/api/capture/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/review/[id]/decide/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/reveal/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/tasks/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/tasks/bulk/preview/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/tasks/bulk/confirm/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/tasks/[taskId]/transition/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "PATCH",
    path: "src/app/api/tasks/[taskId]/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/commitments/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "PATCH",
    path: "src/app/api/commitments/[commitmentId]/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/commitments/[commitmentId]/close/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/canvas/workspace/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/canvas/relationships/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/canvas/relationships/revise/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/canvas/relationships/end/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/goodnotes/correct/route.ts",
    classification: "AUTHENTICATED_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/session/route.ts",
    classification: "PRE_AUTH_BROWSER_MUTATION",
  },
  {
    method: "DELETE",
    path: "src/app/api/session/route.ts",
    classification: "PRE_AUTH_BROWSER_MUTATION",
  },
  {
    method: "POST",
    path: "src/app/api/webauthn/[...action]/route.ts",
    classification: "PRE_AUTH_BROWSER_MUTATION",
  },
];
