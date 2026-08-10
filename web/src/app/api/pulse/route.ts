/**
 * Today / Pulse — **not backend-backed at this head, and it says so.**
 *
 * The measurement, so the next reader does not have to repeat it: a real
 * principal-scoped Pulse read model *does* exist in Python.
 * `SqlPulseRepository.generate_pulse` reads `knowledge.pulse_items` filtered by
 * `principal_id`, returns only accepted and undismissed rows — the migration
 * CHECK `pulse_reads_only_accepted_records` pins that — and `SituationService`
 * routes to it. What does not exist is any way to *reach* it over the transport:
 * `POST /v1/{capability}` dispatches the fifteen members of `Capability`, and
 * none of them is a Pulse read. `SituationService` is deliberately not wired
 * behind `ApplicationService.invoke`.
 *
 * Exposing it needs a new `Capability` member, and that is what puts it outside
 * this work package rather than a preference. `audit_events.capability` carries a
 * frozen `IN (...)` CHECK listing exactly fifteen names, widened by an explicit
 * forward `ALTER` each time the vocabulary grows (`3c8f1e2a5b74` did it last).
 * A member added without one leaves every test green — every test builds its
 * database from scratch — and is refused by the stored constraint on the first
 * audited operation in the field. So a sixteenth capability requires a migration,
 * and this work package is authorised to write none.
 *
 * Until then this route answers `not_implemented` rather than serving fixtures
 * in a default build, and rather than returning an empty list that would read as
 * "nothing needs your attention today".
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { notImplemented, resolveServing } from "@/lib/api/serving";
import { syntheticPulse, syntheticDisclosure } from "@/lib/fixtures/pulse";

const SCOPE = "pulse";

const NO_CAPABILITY =
  "Today/Pulse has no backend capability. A principal-scoped Pulse read model exists in " +
  "PostgreSQL, but no member of the v1 capability set exposes it over the gateway, and " +
  "adding one requires widening a frozen audit CHECK constraint by migration.";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "backend") return notImplemented(SCOPE, NO_CAPABILITY);

  return NextResponse.json({
    shape: "synthetic",
    items: syntheticPulse(guard.principal),
    disclosure: syntheticDisclosure(SCOPE),
  });
}
