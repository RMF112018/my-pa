/**
 * Reveal — **not backend-backed at this head, and it says so.**
 *
 * Reveal answers "why am I seeing this?" with the evidence spans and derivation
 * trace behind a subject. `application/disclosure.py` is not that: it assembles
 * the mandatory disclosure envelope that accompanies every result, which is a
 * different artefact from a per-subject evidence traversal. No capability in the
 * v1 set takes a subject identifier and returns its derivation.
 *
 * The nearest real thing is `knowledge.read`, which returns one stored record
 * and its provenance inside a stated enrollment — and `/api/library` exposes it.
 * It is not Reveal: it needs a `kn_…` and an `enr_…` rather than an arbitrary
 * subject, and it answers about a record rather than about why a derived item was
 * surfaced. Routing Reveal at it would make this route claim to explain things it
 * had not explained, so it does not.
 *
 * The synthetic path still says plainly that the subject is a fixture. In a
 * default build there is no synthetic path and no explanation is manufactured.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { notImplemented, resolveServing } from "@/lib/api/serving";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

const NO_CAPABILITY =
  "Reveal has no backend capability. No member of the v1 capability set takes a subject " +
  "identifier and returns its evidence spans and derivation trace; knowledge.read answers " +
  "a different question and is exposed at /api/library instead.";

export async function POST(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const subjectId = parsed.body["subjectId"];
  if (typeof subjectId !== "string" || subjectId.length === 0) {
    return NextResponse.json(
      { error: { errorClass: "validation", code: "missing_subject", message: "subjectId is required" } },
      { status: 400 },
    );
  }

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "backend") return notImplemented(`reveal:${subjectId}`, NO_CAPABILITY);

  return NextResponse.json({
    shape: "synthetic",
    reason:
      "This item is a synthetic fixture created to exercise the shell. When live sources are " +
      "connected, Reveal will show the exact evidence spans and derivation trace behind it.",
    disclosure: syntheticDisclosure(`reveal:${subjectId}`),
  });
}
