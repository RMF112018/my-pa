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

export function DiagnosticsDetails({
  diagnostic,
  children,
}: {
  diagnostic?: string | null;
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
          {diagnostic}
        </p>
      ) : null}
      {children}
    </div>
  );
}
