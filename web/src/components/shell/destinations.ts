import {
  BookOpen,
  Brain,
  ClipboardCheck,
  Home,
  Map,
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

export const DESTINATIONS: readonly Destination[] = [
  { href: "/today", label: "Today", icon: Home },
  { href: "/work", label: "Work", icon: Workflow },
  { href: "/intelligence", label: "Intelligence", icon: Brain },
  { href: "/people", label: "People", icon: Users },
  { href: canvasHome(), label: "Map", icon: Map },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/review", label: "Review", icon: ClipboardCheck },
] as const;

export const UTILITY_DESTINATIONS: readonly Destination[] = [
  { href: "/system", label: "System", icon: Settings, utility: true },
] as const;
