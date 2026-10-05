/**
 * One Knowledge Assertion — `GET /api/knowledge/assertions/:assertionId`.
 *
 * KLP R6 section 10.2: the Review workbench reads the fact a Knowledge
 * decision produced through `knowledge.assertions.read`, never through
 * extraction Reveal (`knowledge.reveal` is capture-oriented and refuses every
 * Knowledge identifier). Only a `kasr_` identifier is forwarded. An absent,
 * foreign or withheld assertion is the backend's indistinguishable
 * `not_found`; this tier adds no membership check of its own.
 */
import type { NextRequest } from "next/server";
import { invalidWorkRequest, isCanonicalId, workGet } from "@/lib/api/work-route";

type Context = { params: Promise<{ assertionId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { assertionId } = await context.params;
  if (!isCanonicalId(assertionId, "kasr")) return invalidWorkRequest("assertionId was malformed");
  return workGet(
    request,
    `knowledge-assertion:${assertionId}`,
    "knowledge.assertions.read",
    {},
    { assertion_id: assertionId },
    { strictQuery: true },
  );
}
