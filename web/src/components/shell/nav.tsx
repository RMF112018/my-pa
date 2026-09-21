"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import {
  DESKTOP_GLOBAL,
  DESKTOP_PRIMARY,
  MOBILE_MORE,
  MOBILE_PRIMARY,
  UTILITY_DESTINATIONS,
  activeFor,
  groupedDestinations,
  type Destination,
  type DestinationGroup,
} from "@/components/shell/destinations";
import { AccountMenu, type AccountMenuProps } from "@/components/shell/context-header";
import { Icon } from "@/components/ui/icon";
import { IconButton } from "@/components/ui/icon-button";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";

const MORE_GROUP_HEADING: Record<DestinationGroup, string> = {
  workspace: "Workspaces",
  global: "Global",
  utility: "Utilities",
};

function NavLink({
  item,
  pathname,
  collapsed = false,
  onNavigate,
  minHeightClass = "min-h-11",
}: {
  item: Destination;
  pathname: string;
  collapsed?: boolean;
  onNavigate?: () => void;
  minHeightClass?: string;
}) {
  const active = activeFor(pathname, item.href);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={`flex ${minHeightClass} items-center gap-3 rounded-[var(--radius-md)] px-3 text-sm font-medium ${
        active
          ? "bg-interactive-subtle text-interactive"
          : "text-text-secondary hover:bg-surface-subtle hover:text-text-primary"
      }`}
    >
      <Icon icon={item.icon} size={19} />
      <span className={collapsed ? "sr-only" : ""}>{item.label}</span>
    </Link>
  );
}

export function NavRail({
  collapsed,
  onCollapsedChange,
  onCapture,
  account,
}: {
  collapsed: boolean;
  onCollapsedChange: (value: boolean) => void;
  onCapture: () => void;
  account?: Omit<AccountMenuProps, "collapsed" | "labeled">;
}) {
  const pathname = usePathname() ?? "";
  return (
    <nav
      aria-label="Primary"
      /*
       * The rail stretches the full height of the shell row inside
       * `min-h-screen`, so its bottom — which carries the collapse control
       * under `mt-auto` — is the physical bottom edge on a tablet, where the
       * home indicator lives. Its left edge is physical too, but no device that
       * reaches `lg` reports a non-zero left inset, so it keeps the plain 8px.
       */
      className={`hidden shrink-0 flex-col border-r bg-surface pt-2 pr-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pl-2 lg:flex ${collapsed ? "w-16" : "w-[232px]"}`}
    >
      <div className={`mb-3 px-2 ${collapsed ? "sr-only" : "text-lg font-semibold text-interactive"}`}>
        My PA
      </div>
      <Button
        variant="accent"
        className="mb-3 w-full"
        onClick={onCapture}
        aria-haspopup="dialog"
        data-testid="capture-button-desktop"
      >
        <Plus size={18} />
        <span className={collapsed ? "sr-only" : ""}>Capture</span>
      </Button>
      <div className="space-y-1">
        {DESKTOP_PRIMARY.map((item) => (
          <NavLink key={item.href} item={item} pathname={pathname} collapsed={collapsed} />
        ))}
      </div>
      <div className="mt-3 space-y-1 border-t pt-2">
        {DESKTOP_GLOBAL.map((item) => (
          <NavLink key={item.href} item={item} pathname={pathname} collapsed={collapsed} />
        ))}
      </div>
      <div className="mt-auto border-t pt-2">
        {UTILITY_DESTINATIONS.map((item) => (
          <NavLink key={item.href} item={item} pathname={pathname} collapsed={collapsed} />
        ))}
        {account ? <AccountMenu {...account} collapsed={collapsed} labeled /> : null}
        <IconButton
          label={collapsed ? "Expand navigation" : "Collapse navigation"}
          onClick={() => onCollapsedChange(!collapsed)}
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </IconButton>
      </div>
    </nav>
  );
}

export function MobileNav({ onCapture }: { onCapture: () => void }) {
  const pathname = usePathname() ?? "";
  const [moreOpen, setMoreOpen] = useState(false);
  const left = MOBILE_PRIMARY.slice(0, 2);
  const right = MOBILE_PRIMARY.slice(2);
  return (
    <>
      <nav
        aria-label="Primary"
        /*
         * `fixed inset-x-0 bottom-0`: bottom, left and right are all physical
         * edges under `viewport-fit=cover`. `lg:hidden` is no protection from
         * the side insets — the largest iPhone in landscape is still below
         * `lg`, and landscape is exactly where the ~44px side insets are live.
         * The bar has no base horizontal or vertical padding, so a bare `env()`
         * on a zero base *is* `max(0, env())`; this matches the bottom rule
         * that was already here, which is left untouched.
         */
        className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-surface pr-[env(safe-area-inset-right)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] lg:hidden"
      >
        {left.map((item) => {
          const active = activeFor(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px] ${
                active ? "text-interactive" : "text-text-muted"
              }`}
            >
              <Icon icon={item.icon} size={19} />
              {item.label}
            </Link>
          );
        })}
        <button
          type="button"
          className="flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px] text-text-muted"
          aria-haspopup="dialog"
          data-testid="capture-button-mobile"
          onClick={onCapture}
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-accent text-on-brand-accent">
            <Plus size={20} />
          </span>
          Capture
        </button>
        {right.map((item) => {
          const active = activeFor(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px] ${
                active ? "text-interactive" : "text-text-muted"
              }`}
            >
              <Icon icon={item.icon} size={19} />
              {item.label}
            </Link>
          );
        })}
        <button
          type="button"
          className={`flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px] ${
            MOBILE_MORE.some((item) => activeFor(pathname, item.href))
              ? "text-interactive"
              : "text-text-muted"
          }`}
          aria-haspopup="dialog"
          aria-label="More"
          onClick={() => setMoreOpen(true)}
        >
          <Menu size={19} />
          More
        </button>
      </nav>
      <Sheet open={moreOpen} onOpenChange={setMoreOpen} title="More" placement="menu">
        {groupedDestinations(MOBILE_MORE).map(({ group, items }) => (
          <section key={group} className="mb-4 last:mb-0">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
              {MORE_GROUP_HEADING[group]}
            </h2>
            <div className="space-y-1">
              {items.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  pathname={pathname}
                  onNavigate={() => setMoreOpen(false)}
                  minHeightClass="min-h-14"
                />
              ))}
            </div>
          </section>
        ))}
      </Sheet>
    </>
  );
}
