/**
 * Reveal stub — WP-02. Returns a synthetic disclosure for a subject.
 * Real evidence traversal arrives with the backend read models.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function POST(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const subjectId = parsed.body["subjectId"];
  if (typeof subjectId !== "string" || subjectId.length === 0) {
    return NextResponse.json(
      { error: { code: "missing_subject", message: "subjectId is required" } },
      { status: 400 },
    );
  }

  return NextResponse.json({
    reason:
      "This item is a synthetic fixture created to exercise the shell. When live sources are " +
      "connected, Reveal will show the exact evidence spans and derivation trace behind it.",
    disclosure: syntheticDisclosure(`reveal:${subjectId}`),
  });
}
