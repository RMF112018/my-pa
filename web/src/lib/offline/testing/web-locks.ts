/**
 * A controllable Web Locks implementation, for tests only.
 *
 * jsdom implements no Web Locks API, and the capture queue fails closed without
 * one — correctly, since an origin that cannot serialize the queue must not
 * mutate it. That means every offline test would otherwise exercise the
 * `locks_unavailable` path and nothing else.
 *
 * This is a faithful-enough stand-in for the two behaviours the coordinator
 * depends on: exclusive ownership per name, and `ifAvailable` handing back
 * `null` rather than waiting. It is deliberately *not* installed globally — each
 * test that needs locks installs it, so a test that means to exercise the absent
 * API simply does not.
 *
 * Not part of the shipped bundle: nothing under `src/lib/offline` imports it,
 * and it is not a `.test.ts` file, so Vitest does not collect it as a suite.
 */

type LockCallback = (lock: unknown) => Promise<unknown>;

interface InstalledLocks {
  /** Names currently held. Exposed so a test can assert release happened. */
  readonly held: ReadonlySet<string>;
  /** Take a name and keep it until the returned function is called. */
  hold(name: string): () => void;
  /** Release a name taken with `hold`. */
  release(name: string): void;
  /** Put `navigator.locks` back the way it was. */
  restore(): void;
}

/**
 * Install the stand-in on `globalThis.navigator` and return its controls.
 *
 * `ifAvailable: false` is not supported and is not needed: the coordinator only
 * ever asks with `ifAvailable: true`, and a stub that queued waiters would be
 * modelling behaviour nothing under test relies on.
 */
export function installTestWebLocks(): InstalledLocks {
  const navigatorObject = (globalThis as unknown as { navigator?: Record<string, unknown> }).navigator;
  if (!navigatorObject) throw new Error("no navigator to install Web Locks on");
  const previous = Object.getOwnPropertyDescriptor(navigatorObject, "locks");
  const held = new Set<string>();

  const manager = {
    async request(
      name: string,
      options: { mode?: string; ifAvailable?: boolean },
      callback: LockCallback,
    ): Promise<unknown> {
      if (held.has(name)) {
        if (options.ifAvailable) return callback(null);
        throw new Error("this stand-in does not queue waiters");
      }
      held.add(name);
      try {
        return await callback({ name, mode: options.mode ?? "exclusive" });
      } finally {
        held.delete(name);
      }
    },
  };

  Object.defineProperty(navigatorObject, "locks", {
    value: manager,
    configurable: true,
    writable: true,
  });

  return {
    held,
    hold(name: string) {
      held.add(name);
      return () => held.delete(name);
    },
    release(name: string) {
      held.delete(name);
    },
    restore() {
      if (previous) Object.defineProperty(navigatorObject, "locks", previous);
      else delete navigatorObject["locks"];
    },
  };
}

/** Remove any Web Locks API, so the fail-closed path is what runs. */
export function removeWebLocks(): () => void {
  const navigatorObject = (globalThis as unknown as { navigator?: Record<string, unknown> }).navigator;
  if (!navigatorObject) return () => undefined;
  const previous = Object.getOwnPropertyDescriptor(navigatorObject, "locks");
  Object.defineProperty(navigatorObject, "locks", {
    value: undefined,
    configurable: true,
    writable: true,
  });
  return () => {
    if (previous) Object.defineProperty(navigatorObject, "locks", previous);
    else delete navigatorObject["locks"];
  };
}
