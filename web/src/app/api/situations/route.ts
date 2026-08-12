/**
 * Situations — **not backend-backed at this head, and it says so.**
 *
 * Same measurement and same boundary as `/api/pulse`, and it is worth stating
 * separately because the underlying persistence here is further along than the
 * Pulse one. `SqlSituationRepository` is real: `open_situation`, `close_situation`,
 * `get_situation` and `list_situations` all stamp `principal_id` on every write
 * and filter by it on every read, so a Situation belonging to another Principal
 * is indistinguishable from one that does not exist. WP-03's chain created the
 * situation, frame, trace and project tables it writes to.
 *
 * What is missing is the transport, not the read model. `SituationService` is
 * deliberately outside `ApplicationService.invoke` — its commands carry an
 * already-resolved `principal_id` as a partition rather than as a caller-supplied
 * identity — and `POST /v1/{capability}` serves only the fifteen `Capability`
 * members. Adding a sixteenth means widening the frozen `audit_events.capability`
 * CHECK by forward `ALTER`, which is a migration, which this work package is not
 * authorised to write. See `/api/pulse` for the full form of that argument.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { notImplemented, resolveServing } from "@/lib/api/serving";
import { syntheticSituations } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

const SCOPE = "situations";

const NO_CAPABILITY =
  "Situations has no backend capability. A principal-scoped Situation read model exists " +
  "in PostgreSQL, but no member of the v1 capability set exposes it over the gateway, and " +
  "adding one requires widening a frozen audit CHECK constraint by migration.";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "backend") return notImplemented(SCOPE, NO_CAPABILITY);

  return NextResponse.json({
    shape: "synthetic",
    situations: syntheticSituations(guard.principal),
    disclosure: syntheticDisclosure(SCOPE),
  });
}
