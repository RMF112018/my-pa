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

/** Semantic nav grouping. Does not change hrefs, labels, or membership. */
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
const INTELLIGENCE: Destination = {
  href: "/intelligence",
  label: "Intelligence",
  icon: Brain,
  group: "workspace",
};
const PEOPLE: Destination = { href: "/people", label: "People", icon: Users, group: "workspace" };
const MAP: Destination = { href: canvasHome(), label: "Map", icon: Map, group: "workspace" };
const KNOWLEDGE: Destination = {
  href: "/knowledge",
  label: "Knowledge",
  icon: BookOpen,
  group: "workspace",
};
const REVIEW: Destination = {
  href: "/review",
  label: "Review",
  icon: ClipboardCheck,
  group: "workspace",
};
const SEARCH: Destination = {
  href: "/search",
  label: "Search",
  icon: SearchIcon,
  group: "global",
};

export const DESTINATIONS: readonly Destination[] = [
  TODAY,
  WORK,
  INTELLIGENCE,
  PEOPLE,
  MAP,
  KNOWLEDGE,
  REVIEW,
  SEARCH,
] as const;

export const UTILITY_DESTINATIONS: readonly Destination[] = [
  { href: "/system", label: "System", icon: Settings, utility: true, group: "utility" },
] as const;

/** Mobile bottom bar. Explicit — never a DESTINATIONS prefix slice. */
export const MOBILE_PRIMARY: readonly Destination[] = [TODAY, WORK, REVIEW, SEARCH] as const;

/** Mobile More sheet. People is not a primary destination. */
export const MOBILE_MORE: readonly Destination[] = [
  PEOPLE,
  INTELLIGENCE,
  KNOWLEDGE,
  MAP,
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
