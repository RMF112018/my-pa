/**
 * The one gate every synthetic fixture passes through.
 *
 * It is here, in the fixture package itself, rather than in the route handlers,
 * and that placement is the whole of the guarantee. Routes are not the only
 * consumer: `app/(app)/today`, `/review`, `/situations` and
 * `/relationships/[personId]` are server components that import these modules
 * directly and never call an API route at all. A gate written into the ten route
 * handlers would have left those four pages serving fixtures in a default build
 * while every route-level test went green — which is exactly the shape of defect
 * this work package exists to remove.
 *
 * So the refusal lives at the source of the data. Nothing in this tree can
 * produce a synthetic record, or a synthetic disclosure label, unless
 * `MYPA_DATA_PROVIDER=synthetic` is explicitly set, and a production build
 * refuses that value outright.
 *
 * It **throws** rather than returning an empty result, deliberately. An empty
 * list is a claim — "you have nothing" — and a page that rendered one would be
 * lying quietly. A route that wants a typed answer instead of an exception asks
 * `syntheticDataEnabled()` first and returns its own honest state; the throw is
 * what catches everything that does not ask.
 */
import { syntheticDataEnabled } from "@/lib/api/gateway-config";

/** Raised when synthetic data is requested from a build that has not enabled it. */
export class SyntheticProviderDisabledError extends Error {
  constructor() {
    super(
      "The synthetic data provider is not enabled. Fixture data is available only when " +
        "MYPA_DATA_PROVIDER=synthetic is set explicitly, and never in a production build. " +
        "A default build serves the Python gateway or states that it cannot.",
    );
    this.name = "SyntheticProviderDisabledError";
  }
}

/** Refuse unless this deployment has explicitly asked for the synthetic provider. */
export function requireSyntheticProvider(): void {
  if (!syntheticDataEnabled()) throw new SyntheticProviderDisabledError();
}
