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

export interface Destination {
  readonly href: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly utility?: boolean;
}

const TODAY: Destination = { href: "/today", label: "Today", icon: Home };
const WORK: Destination = { href: "/work", label: "Work", icon: Workflow };
const INTELLIGENCE: Destination = { href: "/intelligence", label: "Intelligence", icon: Brain };
const PEOPLE: Destination = { href: "/people", label: "People", icon: Users };
const MAP: Destination = { href: canvasHome(), label: "Map", icon: Map };
const KNOWLEDGE: Destination = { href: "/knowledge", label: "Knowledge", icon: BookOpen };
const REVIEW: Destination = { href: "/review", label: "Review", icon: ClipboardCheck };
const SEARCH: Destination = { href: "/search", label: "Search", icon: SearchIcon };

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
  { href: "/system", label: "System", icon: Settings, utility: true },
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
