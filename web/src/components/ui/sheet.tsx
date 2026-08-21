"use client";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

export function Sheet({ open, onOpenChange, title, description, children }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description?: string; children: ReactNode }) {
  return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}><DialogPrimitive.Portal><DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-text-primary/45" /><DialogPrimitive.Content className="fixed inset-y-0 right-0 z-50 w-[min(90vw,32rem)] overflow-auto border-l bg-surface p-5 shadow-[var(--shadow-elevated)]"><DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title>{description ? <DialogPrimitive.Description className="mt-1 text-sm text-text-secondary">{description}</DialogPrimitive.Description> : null}<div className="mt-5">{children}</div><DialogPrimitive.Close className="absolute right-3 top-3 min-h-11 min-w-11 rounded" aria-label="Close panel">×</DialogPrimitive.Close></DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>;
}
