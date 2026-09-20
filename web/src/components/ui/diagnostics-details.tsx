"use client";

/**
 * The raw-transport leg of a surface state, and the global policy that governs it.
 *
 * **What was decomposed here, and why this is the line.** `SurfaceState` carries
 * two very different things behind one disclosure. The epistemic clarification
 * ("this is not an empty record — it is a read that did not happen") and the
 * backend's own disclosed limitations are *product truth*: they are the reason
 * that component exists, and withholding them would recreate the exact defect
 * it was built to prevent. The raw transport string — an `error.message`, a
 * gateway code, `request failed with status 503` — is *engineering detail*. So
 * the clarification and the limitations stay in both modes, and this block,
 * which is the only part that was ever raw, is governed by the global policy.
 *
 * **Why this file is a client component.** The gate has to be a real mount
 * decision rather than a CSS rule, and the policy lives in React context under
 * the signed-in shell. Returning `null` means the heading, the mono paragraph
 * and both test hooks are absent from the DOM and from the accessibility tree —
 * not hidden, not collapsed, not off-screen.
 *
 * **A note for server callers.** A React Server Component that renders
 * `SurfaceState` serialises whatever it passes into the RSC payload *before*
 * this gate runs, so passing a raw `error` from the server and relying on this
 * component to suppress it would ship the string to the browser anyway — the
 * "server-render then strip" pattern the contract rejects. Server callsites
 * therefore gate on the resolved preference themselves and simply do not pass
 * `error`/`diagnostic` while OFF. This component closes the client callsites,
 * which are the large majority; it does not excuse the server ones.
 */
import type { ReactNode } from "react";

import { useDiagnosticsEnabled } from "@/components/diagnostics/diagnostics-provider";
import {
  describeSafeDiagnostic,
  type SafeDiagnostic,
  type SafeLimitations,
} from "@/lib/diagnostics/safe-detail";

/**
 * **WP08-RT-F010: the prop type is the control.** This took a `string | null`
 * and rendered it verbatim, so the policy above it decided only *whether* an
 * arbitrary backend string reached the DOM. It now takes a `SafeDiagnostic`,
 * which is branded and can only be obtained from a constructor in
 * `lib/diagnostics/safe-detail.ts`, and renders it through
 * `describeSafeDiagnostic` — so the display text is produced here from a closed
 * vocabulary and a caller cannot supply prose at all. Passing a raw string is a
 * type error, not a review finding.
 */
export function DiagnosticsDetails({
  diagnostic,
  children,
}: {
  diagnostic?: SafeDiagnostic | null;
  children?: ReactNode;
}) {
  const enabled = useDiagnosticsEnabled();
  if (!enabled) return null;
  if (!diagnostic && !children) return null;
  return (
    <div className="mt-2" data-testid="surface-state-diagnostics">
      <p className="font-medium text-text-primary">Diagnostics</p>
      {diagnostic ? (
        <p className="mt-1 font-mono text-xs text-text-muted" data-testid="surface-state-diagnostic">
          {describeSafeDiagnostic(diagnostic)}
        </p>
      ) : null}
      {children}
    </div>
  );
}

/**
 * The backend's own "what is missing from this answer" list, under the policy.
 *
 * These read as product truth and often are, but they are backend-authored
 * strings and the backend puts raw transport text in them — a dead gateway
 * yields the limitation `the application gateway did not answer`. Nothing about
 * the string distinguishes a genuine limitation from a transport message, so
 * the list is governed as a whole.
 *
 * WP08-RT-F010 added the second half of that: the list is now a
 * `SafeLimitations`, every entry of which has been checked against an
 * allowlist of the values `application/disclosure.py`'s `Limitation` vocabulary
 * can actually produce, and an entry that is not in the set is replaced by a
 * sentence saying a limitation was withheld. `BACKEND_LIMITATIONS` in
 * `lib/diagnostics/safe-detail.ts` records why the instrument is an allowlist
 * rather than the prose-shape check that governed this first — the shape
 * check's run-length rule withheld eight of the thirteen real tokens — and why
 * the list keeps its own whole-list gate instead of being folded into the
 * closed diagnostic vocabulary. The *consequence* — that the answer is
 * partial, or that the read did not happen — is stated separately and is not
 * gated, so a reader with diagnostics off still knows not to trust the answer
 * as complete.
 */
export function DiagnosticsLimitations({
  limitations,
  heading = "What is missing from this answer:",
}: {
  limitations: SafeLimitations;
  heading?: string;
}) {
  const enabled = useDiagnosticsEnabled();
  if (!enabled || limitations.items.length === 0) return null;
  return (
    <>
      <p className="mt-2 font-medium text-text-primary">{heading}</p>
      <ul className="mt-1 list-inside list-disc" data-testid="surface-state-limitations">
        {/*
         * Keyed by position, not by text. Two withheld entries both become the
         * same `WITHHELD_LIMITATION` sentence, so the text is not unique and
         * keying by it produces duplicate keys and a React warning. The list is
         * render-only and never reordered, so the index is a stable key.
         */}
        {limitations.items.map((limitation, index) => (
          <li key={index}>{limitation}</li>
        ))}
      </ul>
    </>
  );
}
