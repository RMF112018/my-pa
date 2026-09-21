"use client";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useRef, type ReactNode } from "react";

export type SheetPlacement = "menu" | "detail" | "inspector";
export type SheetTitleVisibility = "visible" | "sr-only";

/*
 * Safe-area contract (WP09 corrective).
 *
 * Every placement is `fixed` and flush to at least one viewport edge. Under
 * `viewport-fit=cover` those edges are the *physical* screen edges, so a plain
 * `p-5` leaves content under the notch or the home indicator. Each edge that a
 * placement actually touches therefore takes `max(1.25rem, env(...))`: `max`
 * rather than a sum, so the inset never stacks on top of the 1.25rem it
 * replaces, and the uniform `p-5` shorthand is dropped because it cannot
 * express a per-edge inset. An edge a placement does not touch keeps the plain
 * 1.25rem — the mobile `menu` is bottom-anchored under a `max-h`, so its top is
 * nowhere near the notch and spending an inset there would only waste height.
 *
 * The sheet container is the single supplier of these insets for its subtree;
 * descendants must not add their own or the space double-counts.
 */
const PLACEMENT_CLASS: Record<SheetPlacement, string> = {
  menu:
    "fixed inset-x-0 bottom-0 z-50 max-h-[min(85dvh,32rem)] overflow-auto rounded-t-[var(--radius-lg)] border-t bg-surface px-5 pt-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-[var(--shadow-elevated)] duration-[var(--motion-normal)] motion-reduce:duration-0 lg:inset-y-0 lg:right-0 lg:left-auto lg:max-h-none lg:w-[min(90vw,32rem)] lg:rounded-none lg:border-l lg:border-t-0 lg:pt-[max(1.25rem,env(safe-area-inset-top))]",
  detail:
    "fixed inset-0 z-50 overflow-auto bg-surface px-5 pt-[max(1.25rem,env(safe-area-inset-top))] pb-[max(1.25rem,env(safe-area-inset-bottom))] duration-[var(--motion-normal)] motion-reduce:duration-0 lg:inset-y-0 lg:left-auto lg:w-[min(90vw,32rem)] lg:border-l",
  inspector:
    "fixed inset-y-0 right-0 z-50 w-[min(90vw,32rem)] overflow-auto border-l bg-surface px-5 pt-[max(1.25rem,env(safe-area-inset-top))] pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-[var(--shadow-elevated)] duration-[var(--motion-normal)] motion-reduce:duration-0",
};

/*
 * The close control is absolutely positioned against the Content's padding box,
 * so the container padding above does NOT move it: a bare `top-3` would stay
 * 12px from the physical screen top, i.e. under the notch, no matter how much
 * the container pads. It carries its own inset-aware offset, on exactly the
 * placements whose top edge is the physical top.
 */
const CLOSE_CLASS: Record<SheetPlacement, string> = {
  menu: "top-3 lg:top-[max(0.75rem,env(safe-area-inset-top))]",
  detail: "top-[max(0.75rem,env(safe-area-inset-top))]",
  inspector: "top-[max(0.75rem,env(safe-area-inset-top))]",
};

export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  placement = "inspector",
  titleVisibility = "visible",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  placement?: SheetPlacement;
  titleVisibility?: SheetTitleVisibility;
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-text-primary/45" />
        <DialogPrimitive.Content
          ref={contentRef}
          className={PLACEMENT_CLASS[placement]}
          data-placement={placement}
          onEscapeKeyDown={(event) => {
            // Inline alertdialog (Close confirmation) owns Escape.
            if (contentRef.current?.querySelector('[role="alertdialog"]')) {
              event.preventDefault();
            }
          }}
        >
          <DialogPrimitive.Title
            className={titleVisibility === "sr-only" ? "sr-only" : "text-lg font-semibold"}
          >
            {title}
          </DialogPrimitive.Title>
          {description ? (
            <DialogPrimitive.Description className="mt-1 text-sm text-text-secondary">
              {description}
            </DialogPrimitive.Description>
          ) : null}
          <div className="mt-5">{children}</div>
          <DialogPrimitive.Close
            className={`absolute right-3 min-h-11 min-w-11 rounded ${CLOSE_CLASS[placement]}`}
            aria-label="Close panel"
          >
            ×
          </DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
