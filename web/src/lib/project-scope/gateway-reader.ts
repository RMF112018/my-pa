/** Server-only composition over the canonical Project capabilities. */
import type { PrincipalSession } from "@/contracts/identity";
import type { ContinuityProjectsResult } from "@/lib/api/decode/capabilities/continuity.projects";
import type {
  ContinuityProjectsReadResult,
} from "@/lib/api/decode/capabilities/continuity.projects.read";
import type {
  CanonicalProjectListPage,
  CanonicalProjectRead,
  CanonicalProjectScopeReader,
  CanonicalProjectScopeRecord,
} from "./resolver";

type ProjectGatewayFailure = { readonly ok: false; readonly status: number };
type ProjectReadGatewayOutcome =
  | {
      readonly ok: true;
      readonly result: ContinuityProjectsReadResult;
      readonly disclosure: { readonly truncation: { readonly next_cursor?: string } };
    }
  | ProjectGatewayFailure;
type ProjectListGatewayOutcome =
  | {
      readonly ok: true;
      readonly result: ContinuityProjectsResult;
      readonly disclosure: { readonly truncation: { readonly next_cursor?: string } };
    }
  | ProjectGatewayFailure;

/** Narrow injection contract implemented by the server-only `invokeGateway`. */
export interface ProjectCapabilityInvoker {
  (
    principal: PrincipalSession,
    capability: "continuity.projects.read",
    payload: Record<string, unknown>,
  ): Promise<ProjectReadGatewayOutcome>;
  (
    principal: PrincipalSession,
    capability: "continuity.projects",
    payload: Record<string, unknown>,
  ): Promise<ProjectListGatewayOutcome>;
}

function scopeRecord(project: {
  readonly project_id: string;
  readonly state: "active" | "on_hold" | "closed";
  readonly version: number;
}): CanonicalProjectScopeRecord {
  return {
    project_id: project.project_id,
    state: project.state,
    version: project.version,
  };
}

/**
 * Principal is supplied only by the verified server session. The returned
 * reader adds no Project store, ownership inference, or lifecycle vocabulary.
 */
export function canonicalGatewayProjectReader(
  principal: PrincipalSession,
  invoke: ProjectCapabilityInvoker,
): CanonicalProjectScopeReader {
  return {
    async readProject(projectId: string): Promise<CanonicalProjectRead> {
      const outcome = await invoke(principal, "continuity.projects.read", {
        project_id: projectId,
      });
      if (!outcome.ok) {
        return outcome.status === 404 ? { kind: "not_found" } : { kind: "unavailable" };
      }
      return { kind: "found", project: scopeRecord(outcome.result) };
    },

    async listProjects(input): Promise<CanonicalProjectListPage> {
      const outcome = await invoke(principal, "continuity.projects", {
        page_size: input.pageSize,
        after: input.after,
        state: input.state,
        query: input.query,
      });
      if (!outcome.ok) return { projects: [], nextCursor: null };
      return {
        projects: outcome.result.projects.map(scopeRecord),
        nextCursor: outcome.disclosure.truncation.next_cursor ?? null,
      };
    },
  };
}
