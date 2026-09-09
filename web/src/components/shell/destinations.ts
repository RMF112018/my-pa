import {
  BookOpen,
  Brain,
  ClipboardCheck,
  Home,
  Map,
  Search as SearchIcon,
  Settings,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { canvasHome } from "@/lib/routes/canvas";

export type DestinationGroup = "workspace" | "global" | "utility";

export interface Destination {
  readonly href: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly utility?: boolean;
  readonly group?: DestinationGroup;
}

const TODAY: Destination = { href: "/today", label: "Today", icon: Home, group: "workspace" };
const WORK: Destination = { href: "/work", label: "Work", icon: Workflow, group: "workspace" };
const PEOPLE: Destination = { href: "/people", label: "People", icon: Users, group: "workspace" };
const KNOWLEDGE: Destination = {
  href: "/knowledge",
  label: "Knowledge",
  icon: BookOpen,
  group: "workspace",
};
const INTELLIGENCE: Destination = {
  href: "/intelligence",
  label: "Intelligence",
  icon: Brain,
  group: "workspace",
};
const MAP: Destination = { href: canvasHome(), label: "Map", icon: Map, group: "workspace" };
const REVIEW: Destination = {
  href: "/review",
  label: "Review",
  icon: ClipboardCheck,
  group: "global",
};
const SEARCH: Destination = {
  href: "/search",
  label: "Search",
  icon: SearchIcon,
  group: "global",
};
const SYSTEM: Destination = { href: "/system", label: "System", icon: Settings, utility: true, group: "utility" };

/** Desktop primary rail. Explicit — not the command-palette union. */
export const DESKTOP_PRIMARY: readonly Destination[] = [
  TODAY,
  WORK,
  PEOPLE,
  KNOWLEDGE,
  INTELLIGENCE,
] as const;

export const DESKTOP_GLOBAL: readonly Destination[] = [SEARCH, REVIEW, MAP] as const;

export const UTILITY_DESTINATIONS: readonly Destination[] = [SYSTEM] as const;

/** Mobile bottom bar. More is a control, not a destination. */
export const MOBILE_PRIMARY: readonly Destination[] = [TODAY, WORK, PEOPLE] as const;

/** Mobile More sheet: workspaces, then global, then utilities. */
export const MOBILE_MORE: readonly Destination[] = [
  INTELLIGENCE,
  KNOWLEDGE,
  MAP,
  REVIEW,
  SEARCH,
  SYSTEM,
] as const;

/** Palette and tests: every canonical destination remains command-reachable. */
export const DESTINATIONS: readonly Destination[] = [
  TODAY,
  WORK,
  PEOPLE,
  KNOWLEDGE,
  INTELLIGENCE,
  MAP,
  REVIEW,
  SEARCH,
] as const;

export const COMMAND_DESTINATIONS: readonly Destination[] = [
  ...DESTINATIONS,
  ...UTILITY_DESTINATIONS,
] as const;

const GROUP_ORDER: readonly DestinationGroup[] = ["workspace", "global", "utility"];

export function destinationGroup(item: Destination): DestinationGroup {
  if (item.group) return item.group;
  return item.utility ? "utility" : "workspace";
}

export function destinationsByGroup(
  items: readonly Destination[],
  group: DestinationGroup,
): readonly Destination[] {
  return items.filter((item) => destinationGroup(item) === group);
}

export function groupedDestinations(
  items: readonly Destination[],
): readonly { readonly group: DestinationGroup; readonly items: readonly Destination[] }[] {
  return GROUP_ORDER.map((group) => ({ group, items: destinationsByGroup(items, group) })).filter(
    (entry) => entry.items.length > 0,
  );
}

/** Which primary/global destination owns this pathname. */
export function activeFor(pathname: string, href: string): boolean {
  if (pathname === href || pathname.startsWith(`${href}/`)) return true;
  if (href === "/work" && pathname.startsWith("/situations")) return true;
  if (href === "/knowledge" && pathname.startsWith("/library")) return true;
  if (href === "/people" && pathname.startsWith("/relationships")) return true;
  return false;
}
