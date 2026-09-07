"use client";

/**
 * Which of the three presentations the Register should be in.
 *
 * There is no breakpoint hook in this repository — only an inline
 * `matchMedia("(max-width: 767px)")` subscribed through `useSyncExternalStore`
 * inside `components/shell/utility-region.tsx`. This mirrors that pattern
 * rather than adding a responsive library, and stays feature-local rather than
 * becoming a shared primitive nobody asked for.
 *
 * `useSyncExternalStore`'s third argument is the server snapshot, and it is
 * `"desktop"` deliberately: a server render has no viewport, and guessing
 * "mobile" would make the desktop first paint a card list that then reflowed.
 * The subscription corrects it on the client's first commit.
 */
import { useSyncExternalStore } from "react";

export type ConstraintViewport = "mobile" | "tablet" | "desktop";

const MOBILE_QUERY = "(max-width: 767px)";
const TABLET_QUERY = "(min-width: 768px) and (max-width: 1023px)";

function subscribe(onChange: () => void) {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => undefined;
  }
  const queries = [window.matchMedia(MOBILE_QUERY), window.matchMedia(TABLET_QUERY)];
  for (const query of queries) query.addEventListener("change", onChange);
  return () => {
    for (const query of queries) query.removeEventListener("change", onChange);
  };
}

function snapshot(): ConstraintViewport {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "desktop";
  if (window.matchMedia(MOBILE_QUERY).matches) return "mobile";
  if (window.matchMedia(TABLET_QUERY).matches) return "tablet";
  return "desktop";
}

export function useConstraintViewport(): ConstraintViewport {
  return useSyncExternalStore(subscribe, snapshot, () => "desktop" as const);
}
