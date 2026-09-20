"use client";

/**
 * The one client-side diagnostics policy, seeded from accepted server state.
 *
 * **Why the seed is a prop and not a fetch.** The signed-in layout has already
 * resolved the preference against the authenticated Principal before it renders
 * anything, so this provider starts in the right state on the very first paint.
 * There is no moment at which the client believes ON before the server has said
 * so, which is what makes "no OFF flash" a property of the architecture rather
 * than a timing accident.
 *
 * **Why this provider does not key anything.** It sits *under* the signed-in
 * shell and publishes a boolean. It is deliberately not used as a React `key`
 * for the shell, TaskRuntime, drafts, selection, mutation coordinators or the
 * offline replay queue: remounting those on a presentation preference would
 * discard real user work to change what engineering detail is shown, which the
 * contract forbids and which would be a far worse defect than the one it fixed.
 *
 * **Fencing, and what it is actually defending against.** Four things can try
 * to hand this component a stale ON after an accepted OFF: a delayed response
 * to an earlier save, a late effect from a component that has since unmounted,
 * a back/forward restore of a document rendered under the old preference, and a
 * Principal change on the same browser. All four are handled the same way — a
 * monotonic generation is bumped on every save *and* whenever the server-side
 * epoch changes, and any result carrying a superseded generation is dropped
 * rather than applied. `epoch` is the session binding the layout already
 * computes, so a new session is a new epoch by construction.
 *
 * **Cross-tab is invalidation, never authority.** A peer tab may say "something
 * changed"; it may not say "you are ON". A message causes this tab to ask the
 * server again through `router.refresh()`, and the server's answer is the only
 * thing that can turn diagnostics on. A compromised or confused peer therefore
 * cannot enable diagnostics anywhere.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

/** How the last attempted change ended. `idle` is "nothing has been tried". */
export type DiagnosticsSaveState = "idle" | "pending" | "failed";

export type DiagnosticsPolicy = {
  /** The only question surfaces may ask. */
  readonly enabled: boolean;
  readonly saveState: DiagnosticsSaveState;
  /**
   * Which change was being attempted when `saveState` became `failed`.
   *
   * The two failures are not the same fact and must not share a sentence. A
   * failed *on* leaves the durable preference off, so "diagnostics are still
   * off" is true. A failed *off* leaves the durable preference **on**: this
   * document suppresses them, but a reload or a second tab brings them back.
   * Telling the reader "diagnostics are still off" there would assert a state
   * the mechanism did not establish, which is the one thing this contract is
   * most concerned to prevent.
   */
  readonly failedAttempt: boolean | null;
  /** Request a change. Resolves when the attempt has settled. */
  readonly setEnabled: (next: boolean) => Promise<void>;
};

const OFF_POLICY: DiagnosticsPolicy = {
  enabled: false,
  saveState: "idle",
  failedAttempt: null,
  setEnabled: async () => {},
};

/**
 * Default OFF.
 *
 * A surface rendered outside the provider — a test, a portal that escaped the
 * tree, a future route that forgets the wrapper — gets OFF rather than throwing
 * or inheriting ON. The fail-closed direction is the boring one.
 */
const DiagnosticsContext = createContext<DiagnosticsPolicy>(OFF_POLICY);

/*
 * Deliberately not the cookie name. The channel carries invalidation only
 * and has no authority; sharing a string with the one trusted preference
 * would invite a reader to think otherwise, and the no-bypass guard checks
 * the cookie name exactly.
 */
const CHANNEL_NAME = "my-pa:diagnostics-invalidation:v1";
const INVALIDATE = "invalidate";

export function DiagnosticsProvider({
  initialEnabled,
  generation: serverGeneration = 0,
  epoch,
  children,
}: {
  readonly initialEnabled: boolean;
  /**
   * The stored preference's monotonic generation.
   *
   * This is what makes "the server says ON" distinguishable from "the server
   * said ON before you turned it off". A server payload older than the last one
   * this browser applied is a payload about a world that has moved on, and is
   * ignored rather than obeyed.
   */
  readonly generation?: number;
  readonly epoch: string;
  readonly children: React.ReactNode;
}) {
  const router = useRouter();
  const [enabled, setEnabledState] = useState(initialEnabled);
  const [saveState, setSaveState] = useState<DiagnosticsSaveState>("idle");
  const [failedAttempt, setFailedAttempt] = useState<boolean | null>(null);

  // Bumped on every save and on every epoch change. A result that does not
  // carry the current value is a result about a world that no longer exists.
  const generation = useRef(0);
  const lastEpoch = useRef(epoch);
  const lastServerValue = useRef(initialEnabled);
  // The highest server generation this browser has applied.
  const appliedGeneration = useRef(serverGeneration);

  // The server re-resolves on every navigation and refresh. When its answer
  // changes, or when the session epoch changes, the server wins and any save in
  // flight is fenced out.
  useEffect(() => {
    const epochChanged = lastEpoch.current !== epoch;
    const serverChanged = lastServerValue.current !== initialEnabled;
    if (!epochChanged && !serverChanged) return;

    // A different Principal is a different world: its preference replaces ours
    // outright, whatever the counters say.
    if (!epochChanged && serverGeneration < appliedGeneration.current) {
      // A stale RSC payload — rendered before a write this browser has already
      // applied. Obeying it would restore an older ON after an accepted OFF.
      return;
    }

    lastEpoch.current = epoch;
    lastServerValue.current = initialEnabled;
    appliedGeneration.current = epochChanged
      ? serverGeneration
      : Math.max(appliedGeneration.current, serverGeneration);
    generation.current += 1;
    setEnabledState(initialEnabled);
    setSaveState("idle");
    setFailedAttempt(null);
  }, [epoch, initialEnabled, serverGeneration]);

  const setEnabled = useCallback(
    async (next: boolean) => {
      const ticket = (generation.current += 1);
      setSaveState("pending");
      setFailedAttempt(null);

      // OFF -> ON stays OFF until the write is accepted. ON -> OFF suppresses
      // immediately: withdrawing detail early is safe, showing it early is not.
      if (!next) setEnabledState(false);

      let accepted = false;
      let acceptedGeneration: number | null = null;
      try {
        const response = await fetch("/api/system/diagnostics", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ enabled: next }),
          // The preference is a cookie this origin owns.
          credentials: "same-origin",
        });
        if (response.ok) {
          const payload = (await response.json()) as {
            enabled?: unknown;
            generation?: unknown;
          };
          accepted = payload.enabled === next;
          if (accepted && typeof payload.generation === "number") {
            acceptedGeneration = payload.generation;
          }
        }
      } catch {
        accepted = false;
      }

      // Superseded while we were waiting — a newer save, a navigation that
      // re-resolved, or a new session. Drop this result entirely.
      if (ticket !== generation.current) return;

      if (!accepted) {
        // Never report a state the mechanism did not establish. A failed ON
        // stays OFF; a failed OFF also stays OFF in this document, and the
        // failure is stated rather than swallowed.
        setEnabledState(false);
        setSaveState("failed");
        setFailedAttempt(next);
        return;
      }

      lastServerValue.current = next;
      if (acceptedGeneration !== null) {
        appliedGeneration.current = Math.max(appliedGeneration.current, acceptedGeneration);
      }
      setEnabledState(next);
      setSaveState("idle");
      setFailedAttempt(null);
      announceChange();
      // Replace this tab's own cached payloads, which were rendered under the
      // previous value; the generation check above is the backstop for any that
      // still arrive.
      router.refresh();
    },
    [router],
  );

  /*
   * A document restored from the back/forward cache keeps its React heap and
   * never re-renders the layout, so the re-seed effect above cannot fire — and
   * `BroadcastChannel` messages posted while the page was frozen are never
   * delivered. Without this, a tab that was on when it was frozen shows
   * diagnostics again after a peer accepted off. `pageshow` with `persisted`
   * is the one signal that distinguishes a restore from an ordinary load.
   */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) router.refresh();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [router]);

  // Peer tabs re-resolve from the server; they are never told what to believe.
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = (event: MessageEvent) => {
      if (event.data === INVALIDATE) router.refresh();
    };
    return () => channel.close();
  }, [router]);

  const value = useMemo<DiagnosticsPolicy>(
    () => ({ enabled, saveState, failedAttempt, setEnabled }),
    [enabled, saveState, failedAttempt, setEnabled],
  );

  return <DiagnosticsContext.Provider value={value}>{children}</DiagnosticsContext.Provider>;
}

function announceChange(): void {
  if (typeof BroadcastChannel === "undefined") return;
  try {
    const channel = new BroadcastChannel(CHANNEL_NAME);
    channel.postMessage(INVALIDATE);
    channel.close();
  } catch {
    // A browser that refuses the channel simply re-resolves on its own next
    // navigation. Cross-tab promptness is a convenience, not a contract.
  }
}

/** The one question a surface may ask about diagnostic visibility. */
export function useDiagnosticsEnabled(): boolean {
  return useContext(DiagnosticsContext).enabled;
}

/** Full policy, for the single System control. No other caller needs this. */
export function useDiagnosticsPolicy(): DiagnosticsPolicy {
  return useContext(DiagnosticsContext);
}

/**
 * Render diagnostic presentation only when diagnostics are on.
 *
 * Returning `null` means the subtree is never mounted, so its effects, fetches
 * and portals never start — which is the difference between the contract's
 * "not rendered" and the CSS-hiding it explicitly rejects.
 */
export function WhenDiagnostics({ children }: { readonly children: React.ReactNode }) {
  return useDiagnosticsEnabled() ? <>{children}</> : null;
}
