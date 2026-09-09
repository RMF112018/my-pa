"use client";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

export type SheetPlacement = "menu" | "detail" | "inspector";

const PLACEMENT_CLASS: Record<SheetPlacement, string> = {
  menu:
    "fixed inset-x-0 bottom-0 z-50 max-h-[min(85dvh,32rem)] overflow-auto rounded-t-[var(--radius-lg)] border-t bg-surface p-5 shadow-[var(--shadow-elevated)] duration-[var(--motion-normal)] motion-reduce:duration-0 lg:inset-y-0 lg:right-0 lg:left-auto lg:max-h-none lg:w-[min(90vw,32rem)] lg:rounded-none lg:border-l lg:border-t-0",
  detail:
    "fixed inset-0 z-50 overflow-auto bg-surface p-5 duration-[var(--motion-normal)] motion-reduce:duration-0 lg:inset-y-0 lg:left-auto lg:w-[min(90vw,32rem)] lg:border-l",
  inspector:
    "fixed inset-y-0 right-0 z-50 w-[min(90vw,32rem)] overflow-auto border-l bg-surface p-5 shadow-[var(--shadow-elevated)] duration-[var(--motion-normal)] motion-reduce:duration-0",
};

export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  placement = "inspector",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  placement?: SheetPlacement;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-text-primary/45" />
        <DialogPrimitive.Content
          className={PLACEMENT_CLASS[placement]}
          data-placement={placement}
        >
          <DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title>
          {description ? (
            <DialogPrimitive.Description className="mt-1 text-sm text-text-secondary">
              {description}
            </DialogPrimitive.Description>
          ) : null}
          <div className="mt-5">{children}</div>
          <DialogPrimitive.Close
            className="absolute right-3 top-3 min-h-11 min-w-11 rounded"
            aria-label="Close panel"
          >
            ×
          </DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
