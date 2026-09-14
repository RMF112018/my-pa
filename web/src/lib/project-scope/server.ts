/** Authenticated server composition for the initial Project Scope. */
import type { PrincipalSession } from "@/contracts/identity";
import { resolveServing } from "@/lib/api/serving";
import {
  canonicalGatewayProjectReader,
  type ProjectCapabilityInvoker,
} from "./gateway-reader";
import {
  resolveAuthenticatedProjectScope,
  type CanonicalProjectScopeReader,
  type ResolvedProjectScope,
} from "./resolver";

const UNAVAILABLE_READER: CanonicalProjectScopeReader = {
  readProject: async () => ({ kind: "unavailable" }),
  listProjects: async () => ({ projects: [], nextCursor: null }),
};

export async function resolveServerProjectScope(input: {
  readonly principal: PrincipalSession;
  readonly invokeProjectCapability: ProjectCapabilityInvoker;
  readonly preferenceValue?: string;
  readonly deepLinkProjectId?: string | null;
}): Promise<ResolvedProjectScope> {
  const serving = resolveServing();
  const projects =
    serving.kind === "backend"
      ? canonicalGatewayProjectReader(input.principal, input.invokeProjectCapability)
      : UNAVAILABLE_READER;
  return resolveAuthenticatedProjectScope({
    projects,
    ...(input.preferenceValue === undefined ? {} : { preferenceValue: input.preferenceValue }),
    ...(input.deepLinkProjectId === undefined
      ? {}
      : { deepLinkProjectId: input.deepLinkProjectId }),
  });
}
