"use client";

/**
 * The only control in this application that changes diagnostic visibility.
 *
 * It lives at the top of the root System page and nowhere else. Every other
 * surface reads the policy and renders accordingly; none of them offers a
 * second switch, a "show details" escape hatch, a query parameter or a keyboard
 * shortcut. That is the point of the contract, and it is why this file is the
 * single place the mutation is initiated from.
 *
 * **Why a native `button` with `role="switch"`.** A checkbox would announce as
 * "checked", which describes a form value waiting to be submitted; this control
 * takes effect on activation, and `switch` is the role that says so. The button
 * is a real focusable element, so Space and Enter work without a key handler,
 * and it carries a 44px minimum touch target for coarse pointers.
 *
 * **What it never does.** It does not read or write the preference itself. It
 * asks the provider, which asks the server, which owns the cookie. A failed
 * write therefore cannot leave this control claiming a state that nothing
 * persisted — the label follows the policy, not the click.
 */
import { useId } from "react";

import { useDiagnosticsPolicy } from "@/components/diagnostics/diagnostics-provider";

export function ShowDiagnosticsToggle() {
  const { enabled, saveState, setEnabled } = useDiagnosticsPolicy();
  const labelId = useId();
  const pending = saveState === "pending";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-3">
        <span id={labelId} className="text-sm font-medium text-text-primary">
          Show diagnostics
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-labelledby={labelId}
          disabled={pending}
          data-testid="show-diagnostics-toggle"
          onClick={() => void setEnabled(!enabled)}
          className={`inline-flex min-h-11 min-w-11 items-center gap-2 rounded-[var(--radius-md)] border border-border px-3 py-1.5 text-sm ${
            enabled ? "bg-interactive-subtle text-interactive" : "text-text-secondary"
          } disabled:opacity-60`}
        >
          {enabled ? "On" : "Off"}
        </button>
      </div>
      <p className="text-xs text-muted">
        Technical detail for diagnosing this system. Off by default, and off everywhere until you
        turn it on here.
      </p>
      {/*
        The failure is announced rather than merely printed, and it is stated in
        product language: which way the change was going and that nothing was
        kept. It never says "saved", because a write that failed did not save.
      */}
      {saveState === "failed" ? (
        <p role="alert" className="text-xs text-coral" data-testid="show-diagnostics-save-failed">
          That change could not be saved, so diagnostics are still off. Try again.
        </p>
      ) : null}
    </div>
  );
}
