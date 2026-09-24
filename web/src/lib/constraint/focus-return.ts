/**
 * Dispatch-time focus token / fallback registry — R02-WP10 Phase 4.
 *
 * A fresh design for the Constraint runtime. Every Constraint mutation
 * dispatch captures the identity of the element that invoked it; when the
 * mutation settles, focus is deliberately returned to that origin, or to a
 * documented, deterministic fallback if the origin element no longer exists
 * in the DOM (e.g. the Register row it lived on was removed by the same
 * confirmed mutation). Focus is never silently dropped, and it is never
 * retargeted arbitrarily — every resolution reports exactly which of the
 * three deterministic outcomes it took.
 *
 * This module is React-free and touches the DOM only inside `resolve()`.
 * `mutation-coordinator.ts` calls `resolve()` (via a caller-supplied hook)
 * on every mutation settle except a stale-epoch drop (Artifact 05 SP3.6),
 * which must not resolve a focus-return token at all — the Project scope
 * itself changed, so the captured origin no longer describes anything the
 * person can still see; `abandon()` is used for that case, and for any
 * other caller-initiated cancellation, to clear the token's bookkeeping
 * without moving focus.
 */

export type FocusReturnOutcome = "returned-to-origin" | "returned-to-fallback" | "no-target";

export interface FocusReturnCaptureInput {
  /** Caller-supplied id; a UUID is minted when omitted. */
  readonly tokenId?: string;
  /**
   * The element that invoked the mutation, normally `document.activeElement`
   * read at dispatch time. `null` is accepted (nothing focused) and always
   * resolves through the fallback chain.
   */
  readonly origin: HTMLElement | null;
  /**
   * Deterministic fallback resolver, evaluated only when `origin` is gone.
   * Callers should return the same kind of target every time for a given
   * surface (e.g. "the row's container", "the Close button") — never an
   * arbitrary or most-recently-clicked element.
   */
  readonly fallback?: () => HTMLElement | null;
}

export interface FocusReturnToken {
  readonly tokenId: string;
}

export interface FocusReturnResolution {
  readonly tokenId: string;
  readonly outcome: FocusReturnOutcome;
}

interface Entry {
  readonly tokenId: string;
  readonly origin: HTMLElement | null;
  readonly fallback?: () => HTMLElement | null;
  resolved: boolean;
}

function mintTokenId(): string {
  return crypto.randomUUID();
}

function isFocusable(element: HTMLElement | null | undefined): element is HTMLElement {
  return !!element && element.isConnected;
}

/**
 * The registry's own last-resort target when neither the origin nor the
 * caller's fallback is available: the shell's `main` landmark
 * (`id="main"` in `app-shell.tsx`), falling back to `document.body`. This is
 * what makes "never silently drops focus" true even when a caller supplies
 * no `fallback` at all.
 */
function ultimateFallback(): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const main = document.getElementById("main");
  if (isFocusable(main)) return main;
  return isFocusable(document.body) ? document.body : null;
}

function focusElement(element: HTMLElement): void {
  // Not every deterministic target (e.g. `main`) is natively focusable;
  // make it programmatically focusable for the duration of this call rather
  // than mutating the DOM permanently.
  const hadTabIndex = element.hasAttribute("tabindex");
  if (!hadTabIndex && element.tabIndex < 0) {
    element.setAttribute("tabindex", "-1");
  }
  element.focus();
}

export class FocusReturnRegistry {
  private readonly entries = new Map<string, Entry>();

  /** Capture the invoking element's identity at mutation-dispatch time. */
  capture(input: FocusReturnCaptureInput): FocusReturnToken {
    const tokenId = input.tokenId ?? mintTokenId();
    this.entries.set(tokenId, {
      tokenId,
      origin: input.origin,
      fallback: input.fallback,
      resolved: false,
    });
    return { tokenId };
  }

  /** True while a token is captured and not yet resolved or abandoned. */
  isPending(tokenId: string): boolean {
    const entry = this.entries.get(tokenId);
    return !!entry && !entry.resolved;
  }

  /**
   * Return focus to the captured origin, or a deterministic fallback. Always
   * removes the token from the registry (a token resolves at most once).
   * Resolving an unknown or already-resolved token is a no-op that reports
   * `"no-target"` rather than throwing — callers never need to guard this.
   */
  resolve(tokenId: string): FocusReturnResolution {
    const entry = this.entries.get(tokenId);
    if (!entry || entry.resolved) {
      return { tokenId, outcome: "no-target" };
    }
    entry.resolved = true;
    this.entries.delete(tokenId);

    if (isFocusable(entry.origin)) {
      focusElement(entry.origin);
      return { tokenId, outcome: "returned-to-origin" };
    }

    const declaredFallback = entry.fallback?.() ?? null;
    const target = isFocusable(declaredFallback) ? declaredFallback : ultimateFallback();
    if (target) {
      focusElement(target);
      return { tokenId, outcome: "returned-to-fallback" };
    }
    return { tokenId, outcome: "no-target" };
  }

  /**
   * Explicitly abandon a token without moving focus — the deliberate escape
   * hatch for a stale-epoch mutation settle (SP3.6) and for any surface that
   * unmounts before its mutation resolves. This is not "silently dropping"
   * focus in the sense the module's contract forbids: it is the documented,
   * single exception, used only when the captured origin's whole scope has
   * already changed out from under it.
   */
  abandon(tokenId: string): void {
    this.entries.delete(tokenId);
  }

  /** Diagnostics / tests only. */
  peek(tokenId: string): { readonly captured: boolean; readonly resolved: boolean } {
    const entry = this.entries.get(tokenId);
    return { captured: !!entry, resolved: entry?.resolved ?? false };
  }

  /** Abandon every outstanding token (runtime disposal). */
  dispose(): void {
    this.entries.clear();
  }
}

export function createFocusReturnRegistry(): FocusReturnRegistry {
  return new FocusReturnRegistry();
}
