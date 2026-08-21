"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Dialog } from "@/components/ui/dialog";
import { DESTINATIONS, UTILITY_DESTINATIONS } from "@/components/shell/destinations";

export function CommandPalette({
  open,
  onOpenChange,
  onCapture,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCapture: () => void;
}) {
  const router = useRouter();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpenChange, open]);

  return (
    <Dialog open={open} onClose={() => onOpenChange(false)} title="Command menu">
      <p className="mb-3 text-sm text-text-secondary">
        Navigate or open Quick Capture. Cross-feature search is not available yet.
      </p>
      <ul className="space-y-1">
        {[...DESTINATIONS, ...UTILITY_DESTINATIONS].map((item) => (
          <li key={item.href}>
            <button
              type="button"
              className="flex min-h-11 w-full items-center rounded px-3 text-left hover:bg-surface-subtle"
              onClick={() => {
                router.push(item.href);
                onOpenChange(false);
              }}
            >
              {item.label}
            </button>
          </li>
        ))}
        <li>
          <button
            type="button"
            className="flex min-h-11 w-full items-center rounded px-3 text-left font-medium text-interactive hover:bg-interactive-subtle"
            onClick={() => {
              onOpenChange(false);
              onCapture();
            }}
          >
            Quick Capture
          </button>
        </li>
      </ul>
    </Dialog>
  );
}
