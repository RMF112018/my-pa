/** Exact Principal-scoped Project read over the canonical gateway capability. */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { isProjectId } from "@/lib/project-scope/scope";

const GENERIC_NOT_FOUND = {
  error: {
    errorClass: "not_found",
    code: "not_found",
    message: "the Project could not be read",
  },
} as const;

function projectNotFound(): NextResponse {
  return NextResponse.json(GENERIC_NOT_FOUND, { status: 404 });
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const { projectId } = await context.params;
  if (!isProjectId(projectId)) {
    return NextResponse.json(
      {
        error: {
          errorClass: "validation",
          code: "invalid_request",
          message: "projectId was malformed",
        },
      },
      { status: 400 },
    );
  }

  const scope = `project:${projectId}`;
  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  // The legacy Project fixture has no canonical version and cannot satisfy an
  // exact read. Do not call the real gateway or invent missing authority while
  // the explicit synthetic provider is selected.
  if (serving.kind === "synthetic") return projectNotFound();

  const outcome = await invokeGateway(guard.principal, "continuity.projects.read", {
    project_id: projectId,
  });
  if (!outcome.ok) {
    // The canonical command already makes absence and foreign ownership the
    // same not_found. Preserve that nondisclosure if an auth policy reports a
    // denial at this boundary as well.
    if (outcome.status === 404 || outcome.status === 403) return projectNotFound();
    return gatewayRefusal(scope, outcome.status, outcome.error);
  }
  if (outcome.result.state === "closed") return projectNotFound();

  return NextResponse.json({
    shape: "backend",
    project: outcome.result,
    disclosure: backendDisclosure(scope, outcome.disclosure, transportLimitations()),
  });
}
