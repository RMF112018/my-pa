"use client";

import { useSyncExternalStore } from "react";
import { PanelRightClose, PanelRightOpen, Pin, PinOff } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import { Sheet } from "@/components/ui/sheet";
import { CanvasInspector } from "@/components/canvas/canvas-inspector";

const MOBILE_QUERY = "(max-width: 767px)";

function subscribeToMobileViewport(onChange: () => void) {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia(MOBILE_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function mobileViewportSnapshot() {
  return typeof window.matchMedia === "function" && window.matchMedia(MOBILE_QUERY).matches;
}

function InspectorContent({
  pinned,
  onPinnedChange,
}: {
  pinned: boolean;
  onPinnedChange: (value: boolean) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Inspector</h2>
        <IconButton
          label={pinned ? "Unpin Inspector" : "Pin Inspector"}
          onClick={() => onPinnedChange(!pinned)}
        >
          {pinned ? <PinOff size={18} /> : <Pin size={18} />}
        </IconButton>
      </div>
      <CanvasInspector />
    </div>
  );
}

export function UtilityRegion({
  open,
  onOpenChange,
  pinned,
  onPinnedChange,
  width,
  onWidthChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pinned: boolean;
  onPinnedChange: (value: boolean) => void;
  width: number;
  onWidthChange: (value: number) => void;
}) {
  const mobile = useSyncExternalStore(
    subscribeToMobileViewport,
    mobileViewportSnapshot,
    () => false,
  );

  return (
    <>
      <aside
        aria-label="Utility region"
        className="relative hidden shrink-0 border-l bg-surface md:block"
        style={{ width: open ? width : 48 }}
      >
        <IconButton
          label={open ? "Collapse Inspector" : "Open Inspector"}
          onClick={() => onOpenChange(!open)}
        >
          {open ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
        </IconButton>
        {open ? (
          <div className="p-4">
            <InspectorContent pinned={pinned} onPinnedChange={onPinnedChange} />
            <label className="mt-6 block text-xs text-text-muted">
              Inspector width
              <input
                aria-label="Inspector width"
                type="range"
                min="320"
                max="520"
                value={width}
                onChange={(event) => onWidthChange(Number(event.target.value))}
                className="mt-2 w-full"
              />
            </label>
          </div>
        ) : null}
      </aside>
      {mobile ? (
        <Sheet open={open} onOpenChange={onOpenChange} title="Inspector">
          <InspectorContent pinned={pinned} onPinnedChange={onPinnedChange} />
        </Sheet>
      ) : null}
    </>
  );
}
