/** The five MossAIc destinations. Order is the navigation order. */
export interface Destination {
  readonly href: string;
  readonly label: string;
}

export const DESTINATIONS: readonly Destination[] = [
  { href: "/today", label: "Today" },
  { href: "/situations", label: "Situations" },
  { href: "/review", label: "Review" },
  { href: "/library", label: "Library" },
  { href: "/system", label: "System" },
] as const;
