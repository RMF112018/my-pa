"use client";

/**
 * Focus-managed modal dialog built on the native <dialog> element.
 * Escape closes; focus moves into the dialog on open and returns to the
 * invoking element on close (native <dialog> behavior).
 */
import { useEffect, useRef, useId, type KeyboardEvent, type ReactNode } from "react";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export function Dialog({ open, onClose, title, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const invoker = useRef<HTMLElement | null>(null);
  const returnHeading = useRef<HTMLHeadingElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // Some test environments (jsdom) do not implement showModal; fall back
    // to the `open` attribute so behavior stays testable.
    if (open && !dialog.open) {
      invoker.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      returnHeading.current = invoker.current?.closest("main")?.querySelector("h1") ?? null;
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      // No deferred callback: descendants may establish a more specific stage
      // target afterwards, and later deliberate user focus belongs to them.
      const input = dialog.querySelector<HTMLElement>('input:not([disabled]):not([type="hidden"]), textarea:not([disabled]), select:not([disabled])');
      (input ?? titleRef.current)?.focus();
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      const target = invoker.current?.isConnected ? invoker.current : returnHeading.current;
      if (target?.isConnected) target.focus();
    }
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key === "Tab" && !event.ctrlKey && !event.metaKey) {
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]):not([type="hidden"]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.tabIndex >= 0 && element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
      return;
    }
    if (event.key !== "Escape") return;
    // type=search consumes Escape to clear the field and skips native cancel.
    // Own the close in React so the dialog actually dismisses.
    event.preventDefault();
    onClose();
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      onKeyDown={onKeyDown}
      aria-label={title}
      aria-labelledby={titleId}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] overflow-auto max-w-md rounded-lg border border-border bg-surface p-0 shadow-lg backdrop:bg-text-primary/50"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 ref={titleRef} id={titleId} tabIndex={-1} className="text-base font-semibold text-text-primary">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--radius-md)] text-muted hover:bg-surface-subtle"
        >
          ✕
        </button>
      </div>
      <div className="p-4">{children}</div>
    </dialog>
  );
}
