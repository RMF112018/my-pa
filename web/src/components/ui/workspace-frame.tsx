"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";

export interface WorkspaceFrameProps {
  readonly title: string;
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  readonly detail?: ReactNode;
}

/** One workspace landmark. Detail stays secondary and never squeezes source below 320px. */
export function WorkspaceFrame({ title, actions, children, detail }: WorkspaceFrameProps) {
  const headingId = useId();
  const frame = useRef<HTMLDivElement>(null);
  const [inlineDetail, setInlineDetail] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  useEffect(() => {
    const element = frame.current;
    if (!element || detail == null) return;
    const measure = () => {
      const style = getComputedStyle(element);
      const sourceMin = parseFloat(style.getPropertyValue("--workspace-source-min")) || 320;
      const detailMin = parseFloat(style.getPropertyValue("--workspace-detail-min")) || 420;
      const detailMax = parseFloat(style.getPropertyValue("--workspace-detail-max")) || 560;
      const detailWidth = window.innerWidth >= 1024
        ? Math.min(detailMax, Math.max(detailMin, window.innerWidth * .44))
        : detailMin;
      setInlineDetail(window.innerWidth >= 768 && element.getBoundingClientRect().width - detailWidth >= sourceMin);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [detail]);

  return (
    <div ref={frame} className="workspace-frame" data-detail-presentation={inlineDetail ? "inline" : "sheet"}>
      <main aria-labelledby={headingId}>
        <header className="workspace-header">
          <h1 id={headingId} tabIndex={-1} className="text-2xl font-semibold">{title}</h1>
          <div className="workspace-actions">
            {actions}
            {detail != null && !inlineDetail ? (
              <Button variant="secondary" className="min-h-11" onClick={() => setDetailOpen(true)}>Open details</Button>
            ) : null}
          </div>
        </header>
        <div className={detail != null && inlineDetail && !detailOpen ? "workspace-body workspace-with-detail" : "workspace-body"}>
          <div className="workspace-content">{children}</div>
          {detail != null && inlineDetail && !detailOpen ? <aside aria-label={`${title} details`} className="workspace-detail">{detail}</aside> : null}
        </div>
      </main>
      {detail != null && detailOpen ? (
        <Sheet open onOpenChange={setDetailOpen} title={`${title} details`} placement="detail">{detail}</Sheet>
      ) : null}
    </div>
  );
}
