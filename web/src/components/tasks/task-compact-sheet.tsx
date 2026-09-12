"use client";

import { Sheet } from "@/components/ui/sheet";
import { TaskDetailViewConnected } from "@/components/work/work-detail";
import type { TaskRow } from "@/contracts/work";

/**
 * The compact Task experience (WP-TUX-03).
 *
 * Composes the existing adaptive `Sheet` at `placement="detail"`, which is already
 * full-screen on mobile and a bounded right-side panel on desktop, and which carries
 * Radix dialog semantics: focus trap, Escape, and title/description association.
 * A separate drawer would duplicate solved infrastructure.
 *
 * Boundaries: this owns Sheet composition and the seeded-versus-canonical rule. It
 * owns no endpoint detail — the canonical read, mutation coordination and freshness
 * all belong to the shared Task runtime the detail consumes.
 */
export interface TaskCompactSheetProps {
  taskId: string;
  open: boolean;
  onOpenChange(open: boolean): void;
  /**
   * A list or search projection used only to paint the header and a read-only
   * summary while the canonical Task hydrates. It never authorizes a mutation.
   */
  seed?: TaskRow | null;
}

export function TaskCompactSheet({ taskId, open, onOpenChange, seed }: TaskCompactSheetProps) {
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={seed?.title ?? "Task detail"}
      description="Closing restores your place in Work."
      placement="detail"
    >
      <div data-testid="task-compact-sheet" className="pb-[env(safe-area-inset-bottom)]">
        <TaskDetailViewConnected taskId={taskId} embedded seed={seed} />
      </div>
    </Sheet>
  );
}
