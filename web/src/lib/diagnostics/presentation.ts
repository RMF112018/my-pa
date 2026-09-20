/**
 * Stripping the diagnostic-bearing props before they can be rendered or serialized.
 *
 * **Why this is a prop filter and not a component.** `SurfaceState` renders
 * client components (`DiagnosticsDetails`, `DiagnosticsLimitations`), and when a
 * *server* component renders `SurfaceState`, React serializes the props those
 * client components receive into the RSC Flight payload — which ships inside the
 * HTML, before any client code runs. A gate that lives in the client component
 * therefore hides the text on screen while the text is still in the bytes the
 * browser received. That is the "server-render then strip" pattern the contract
 * rejects, and no DOM assertion can see it.
 *
 * So server callsites decide *before* they build the element, and this is the
 * one place that decision is expressed. It is a plain synchronous function
 * rather than an async wrapper component on purpose: an async component in the
 * middle of a tree cannot be rendered by a synchronous parent, which would have
 * pushed the problem into every shared presentation component.
 *
 * **Three props carry engineering detail, not one.**
 *
 * - `error` — `mapUserError` turns this into a raw transport string: an
 *   `error.message`, a gateway `code`, an `errorClass`, or `request failed with
 *   status N`.
 * - `diagnostic` — the same thing, passed explicitly.
 * - `limitations` — the subtle one. These read as product truth ("what is
 *   missing from this answer") and often are, but they are *backend-authored*
 *   strings and the backend puts raw transport text in them: an unreachable
 *   gateway produces the limitation `the application gateway did not answer`,
 *   which rendered under "What is missing from this answer" on every failed
 *   read. Nothing about the string distinguishes a genuine limitation from a
 *   transport message, so the list is governed as a whole.
 *
 * Everything that makes the state truthful survives: the title, the badge, the
 * `role`, the `data-state`, the product-language `detail`, the children
 * (Retry), the partial-answer consequence, and the epistemic clarification that
 * separates an empty record from a read that did not happen.
 */
import type { UserErrorInput } from "@/lib/ui/user-error";

/** The failure object, or nothing at all, so `mapUserError` is never consulted. */
export function diagnosticError(
  enabled: boolean,
  error: UserErrorInput | undefined,
): UserErrorInput | undefined {
  return enabled ? error : undefined;
}

/** An explicit raw/transport string, or nothing. */
export function diagnosticText(
  enabled: boolean,
  diagnostic: string | null | undefined,
): string | null {
  return enabled ? (diagnostic ?? null) : null;
}

/** The backend's own limitation strings, or an empty list. */
export function diagnosticLimitations(
  enabled: boolean,
  limitations: readonly string[] | undefined,
): readonly string[] {
  return enabled && limitations ? limitations : [];
}
