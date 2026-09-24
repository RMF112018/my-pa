/**
 * `POST /api/project-scope` — persist the browser's Project-scope preference.
 *
 * Replaces the whole preference by value: `{"scope":"ALL_PROJECTS"}` or
 * `{"scope":"PROJECT","projectId":"<id>"}`. There is deliberately no `PUT` —
 * this route never partially updates the preference, so last-write-wins is
 * the entire concurrency story and no idempotency key is needed.
 *
 * Gate order (cheapest, least-disclosing refusal first):
 * 1. Same-origin admission (`admitBrowserMutation`, the same seam every other
 *    browser mutation in this tier uses).
 * 2. Session Principal required (`requirePrincipal`).
 * 3. A clean, closed JSON body — exactly the two accepted shapes above, no
 *    unknown fields, no caller-supplied identity (`readCleanBody`).
 * 4. For the `PROJECT` case, an exact read via the same
 *    `canonicalGatewayProjectReader` composition `gateway-reader.ts`
 *    establishes for the server-rendered resolver — not a second invocation
 *    path. Unknown, foreign, and closed Projects all answer the identical
 *    generic `404`; nothing here distinguishes them.
 *
 * Every response carries `Cache-Control: private, no-store` — the same
 * disclosure posture as every other Constraint/Project-control BFF route,
 * because a successful answer here is session-Principal-derived and
 * Project-membership-implying.
 */
import { NextResponse, type NextRequest } from "next/server";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import { readCleanBody, requirePrincipal } from "@/lib/api/guard";
import { invokeGateway } from "@/lib/api/gateway";
import { resolveServing } from "@/lib/api/serving";
import { canonicalGatewayProjectReader } from "@/lib/project-scope/gateway-reader";
import { isProjectId, projectScope, ALL_PROJECTS } from "@/lib/project-scope/scope";
import { serializeProjectScopePreference } from "@/lib/project-scope/preference";

const GENERIC_NOT_FOUND = {
  error: {
    errorClass: "not_found",
    code: "not_found",
    message: "the Project could not be read",
  },
} as const;

const GATEWAY_UNAVAILABLE = {
  error: {
    errorClass: "unavailable",
    code: "gateway_unavailable",
    message: "the application gateway did not answer",
  },
} as const;

function noStore(response: NextResponse): NextResponse {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

function invalid(message: string): NextResponse {
  return NextResponse.json(
    { error: { errorClass: "validation", code: "invalid_request", message } },
    { status: 400 },
  );
}

function notFound(): NextResponse {
  return NextResponse.json(GENERIC_NOT_FOUND, { status: 404 });
}

function unavailable(): NextResponse {
  return NextResponse.json(GATEWAY_UNAVAILABLE, { status: 503 });
}

type ParsedScopeBody =
  | { readonly kind: "all" }
  | { readonly kind: "project"; readonly projectId: string };

/**
 * The two accepted shapes, exactly, and nothing else: no extra field, no
 * `projectId` alongside `ALL_PROJECTS`, no malformed Project identifier.
 */
function parseScopeBody(
  body: Record<string, unknown>,
): { readonly ok: true; readonly value: ParsedScopeBody } | { readonly ok: false; readonly response: NextResponse } {
  const keys = Object.keys(body);
  const { scope } = body;
  if (scope === "ALL_PROJECTS") {
    if (keys.length !== 1) {
      return { ok: false, response: invalid("ALL_PROJECTS accepts no other field") };
    }
    return { ok: true, value: { kind: "all" } };
  }
  if (scope === "PROJECT") {
    if (keys.length !== 2 || !("projectId" in body)) {
      return { ok: false, response: invalid("PROJECT requires exactly projectId") };
    }
    const { projectId } = body;
    if (typeof projectId !== "string" || !isProjectId(projectId)) {
      return { ok: false, response: invalid("projectId was malformed") };
    }
    return { ok: true, value: { kind: "project", projectId } };
  }
  return { ok: false, response: invalid("scope must be ALL_PROJECTS or PROJECT") };
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const blocked = admitBrowserMutation(request);
  if (blocked) return noStore(blocked as NextResponse);

  const guard = await requirePrincipal(request);
  if (!guard.ok) return noStore(guard.response);

  const parsedBody = await readCleanBody(request);
  if (!parsedBody.ok) return noStore(parsedBody.response);

  const parsed = parseScopeBody(parsedBody.body);
  if (!parsed.ok) return noStore(parsed.response);

  if (parsed.value.kind === "all") {
    const response = NextResponse.json({ scope: "ALL_PROJECTS" });
    // The cookie's full attribute string (`HttpOnly`, `Path`, `Max-Age`,
    // `SameSite`, `Secure`) is authored once by `serializeProjectScopePreference`
    // and set verbatim here, so this route cannot silently drift from the seam
    // every other reader of `PROJECT_SCOPE_COOKIE` already trusts.
    response.headers.set(
      "set-cookie",
      serializeProjectScopePreference(ALL_PROJECTS, {
        secure: process.env.NODE_ENV === "production",
      }),
    );
    return noStore(response);
  }

  const { projectId } = parsed.value;
  const serving = resolveServing();
  if (serving.kind === "refused") return noStore(serving.response);
  // The synthetic provider has no canonical Project store to read an exact,
  // versioned answer from; refusing rather than fabricating a resolution
  // matches `GET /api/projects/[projectId]`'s own synthetic-mode refusal.
  if (serving.kind === "synthetic") return noStore(notFound());

  const read = await canonicalGatewayProjectReader(guard.principal, invokeGateway).readProject(
    projectId,
  );
  if (read.kind === "unavailable") return noStore(unavailable());
  if (read.kind === "not_found") return noStore(notFound());
  if (read.project.state === "closed") return noStore(notFound());

  const response = NextResponse.json({
    scope: "PROJECT",
    project: {
      id: read.project.project_id,
      name: read.project.name,
      state: read.project.state,
      version: read.project.version,
    },
  });
  response.headers.set(
    "set-cookie",
    serializeProjectScopePreference(projectScope(projectId), {
      secure: process.env.NODE_ENV === "production",
    }),
  );
  return noStore(response);
}
