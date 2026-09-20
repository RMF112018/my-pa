/**
 * Deciding *whether* engineering detail is built, and handing on only a value
 * whose content is already decided.
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
 * **WP08-RT-F010: these were once pass-through filters, and that was the gap.**
 * Each of the three used to be `return enabled ? value : nothing`. They decided
 * *whether*, never *what*, so with diagnostics on an arbitrary backend string
 * reached the DOM verbatim. They now return values from
 * `lib/diagnostics/safe-detail.ts`: a `SafeDiagnostic` whose every field is a
 * closed union, a constrained integer or an allowlisted code, and a
 * `SafeLimitations` whose entries have each been checked against an allowlist
 * of the backend's own `Limitation` vocabulary — see `BACKEND_LIMITATIONS` in
 * `lib/diagnostics/safe-detail.ts` for why an allowlist replaced the
 * prose-shape check that governed this first. Those types are branded, so the
 * components below them accept nothing else and a raw string at the prop is a
 * compile error rather than something a reviewer has to notice.
 *
 * **Three props carry engineering detail, not one.**
 *
 * - `error` — a caught failure of any shape, read down to the closed
 *   vocabulary. Its `message` is dropped; its `code` is allowlisted; its
 *   `correlationId` is acknowledged but never carried.
 * - `diagnostic` — the same thing, passed explicitly.
 * - `limitations` — the subtle one. These read as product truth ("what is
 *   missing from this answer") and often are, but they are *backend-authored*
 *   strings and the backend puts raw transport text in them: an unreachable
 *   gateway produces the limitation `the application gateway did not answer`,
 *   which rendered under "What is missing from this answer" on every failed
 *   read. Nothing about the string distinguishes a genuine limitation from a
 *   transport message, so the list is still governed as a whole — and each
 *   entry must now also *be* one of the values the backend's own
 *   `Limitation` vocabulary can produce, or it is replaced by a sentence saying
 *   one was withheld. `safe-detail.ts` records why the instrument is an
 *   allowlist rather than a shape check, and why limitations are not folded
 *   into the closed diagnostic vocabulary instead.
 *
 * Everything that makes the state truthful survives: the title, the badge, the
 * `role`, the `data-state`, the product-language `detail`, the children
 * (Retry), the partial-answer consequence, and the epistemic clarification that
 * separates an empty record from a read that did not happen.
 */
import {
  NO_LIMITATIONS,
  safeDiagnostic,
  safeLimitations,
  type FailureInput,
  type SafeDiagnostic,
  type SafeLimitations,
} from "@/lib/diagnostics/safe-detail";

/** The failure, read down to the closed vocabulary — or nothing at all. */
export function diagnosticError(
  enabled: boolean,
  error: FailureInput | undefined,
): SafeDiagnostic | undefined {
  return enabled && error !== undefined ? safeDiagnostic(error) : undefined;
}

/** An explicitly passed failure, read down to the closed vocabulary — or nothing. */
export function diagnosticText(
  enabled: boolean,
  diagnostic: FailureInput | null | undefined,
): SafeDiagnostic | null {
  return enabled && diagnostic != null ? safeDiagnostic(diagnostic) : null;
}

/**
 * The backend's own limitation strings, each allowlisted against its
 * `Limitation` vocabulary — or an empty list.
 */
export function diagnosticLimitations(
  enabled: boolean,
  limitations: readonly string[] | undefined,
): SafeLimitations {
  return enabled && limitations ? safeLimitations(limitations) : NO_LIMITATIONS;
}
