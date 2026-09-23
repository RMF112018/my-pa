/**
 * Projects — **real-backed as of WP-11.**
 *
 * `SqlProjectRepository` was real and principal-scoped and unreachable, for
 * exactly the reason `/api/situations` records. `continuity.projects` reaches
 * it, and revision `8f2b6c4d1a37` admits the name to the audited vocabulary.
 *
 * `participants` are opaque person references and carry no display name, no
 * contact detail, and no ranking of any kind. Nothing on this path scores a
 * person (`§22`), and there is no field one could go in.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticProjects } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { ProjectRow } from "@/lib/api/decode/capabilities/continuity.projects";
import type { BackendProject, ProjectState } from "@/contracts/views";

const SCOPE = "projects";

/**
 * The page size this browser projection asks the canonical list for.
 *
 * Fixed, and fixed deliberately: the Capture Project selector pages with
 * Previous/Next rather than searching, and a caller-chosen size would be a new
 * browser directory contract this tier has no authority to publish.
 */
const PAGE_SIZE = 25;

/**
 * One Project row as this projection returns it.
 *
 * Every existing field keeps its existing name. `version` is added because it is
 * the canonical row's own optimistic-concurrency value and a selector that
 * retains a selection across pages needs to know which row it retained — it is
 * read off the decoded canonical row and is not derived here.
 */
interface BrowserProject extends BackendProject {
  readonly version: number;
}

function toBackendProject(row: ProjectRow): BrowserProject {
  return {
    projectId: row.project_id,
    name: row.name,
    state: row.state as ProjectState,
    description: row.description,
    participants: row.participants,
    openedAt: row.opened_at,
    closedAt: row.closed_at,
    version: row.version,
  };
}

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  // One optional opaque cursor, forwarded unchanged. Repeating the parameter or
  // supplying an empty one is a caller error rather than something to guess at,
  // and it is refused before the gateway is invoked. No cursor is minted, parsed
  // or interpreted here: the canonical capability owns that vocabulary.
  const cursors = new URL(request.url).searchParams.getAll("after");
  if (cursors.length > 1 || (cursors.length === 1 && cursors[0]!.length === 0)) {
    return NextResponse.json(
      {
        error: {
          errorClass: "validation",
          code: "invalid_cursor",
          message: "after must be supplied at most once and must not be empty",
        },
      },
      { status: 400 },
    );
  }
  const after = cursors.length === 1 ? cursors[0]! : undefined;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  if (serving.kind === "synthetic") {
    return NextResponse.json({
      shape: "synthetic",
      projects: syntheticProjects(guard.principal),
      nextCursor: null,
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await invokeGateway(guard.principal, "continuity.projects", {
    page_size: PAGE_SIZE,
    after,
  });
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);
  const result = outcome.result;

  // A truncated page with no cursor to continue from is a partial answer that
  // cannot be continued. Returning it would present an incomplete Project list
  // as the whole list, so it fails closed instead.
  const truncation = outcome.disclosure.truncation;
  const nextCursor =
    typeof truncation.next_cursor === "string" && truncation.next_cursor.length > 0
      ? truncation.next_cursor
      : null;
  if (truncation.is_truncated && nextCursor === null) {
    return NextResponse.json(
      {
        error: {
          errorClass: "unavailable",
          code: "upstream_contract_invalid",
          message: "the gateway reported a truncated Project page without a cursor",
        },
      },
      { status: 503 },
    );
  }

  return NextResponse.json({
    shape: "backend",
    projects: result.projects.map(toBackendProject),
    nextCursor,
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, transportLimitations()),
  });
}
