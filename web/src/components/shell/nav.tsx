"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DESTINATIONS } from "@/components/shell/destinations";

function linkClasses(active: boolean): string {
  return active
    ? "bg-moss-green text-white"
    : "text-moss-slate hover:bg-moss-sand";
}

/** Desktop navigation rail — hidden on small screens. */
export function NavRail() {
  const pathname = usePathname();
  return (
    <nav aria-label="Primary" className="hidden w-48 shrink-0 flex-col gap-1 p-3 md:flex">
      {DESTINATIONS.map((d) => {
        const active = pathname === d.href || pathname.startsWith(`${d.href}/`);
        return (
          <Link
            key={d.href}
            href={d.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-2 text-sm font-medium ${linkClasses(active)}`}
          >
            {d.label}
          </Link>
        );
      })}
    </nav>
  );
}

/** Mobile bottom navigation — hidden on medium and larger screens. */
export function MobileNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-10 flex border-t border-border bg-surface md:hidden"
    >
      {DESTINATIONS.map((d) => {
        const active = pathname === d.href || pathname.startsWith(`${d.href}/`);
        return (
          <Link
            key={d.href}
            href={d.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-12 flex-1 items-center justify-center text-xs font-medium ${
              active ? "text-moss-green" : "text-muted"
            }`}
          >
            {d.label}
          </Link>
        );
      })}
    </nav>
  );
}
