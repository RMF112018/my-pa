/**
 * The derived Pulse, rendered so a human can see *why now* rather than *what
 * happened*.
 *
 * **Two presentations, decided by `itemType`.**
 *
 * A Task is the one item type this surface can *answer* rather than merely
 * route to, so since WP-TUX-07 a Task row renders `TodayTaskCard`: a title, one
 * concise attention reason, and the two operations that dispose of it
 * (Reschedule, Close). It carries none of the evidentiary chrome below — no
 * "Why now:" / "If ignored:" labels, no "Rank N", no basis refs, no pulse or
 * item identifiers, no lifecycle token. That chrome describes the derivation,
 * and a card whose point is *act on this now* is not the place to publish the
 * derivation's own bookkeeping. The concise reason is derived from the closed
 * `reasonCode`, not from any Task state — this list has read no Task.
 *
 * Every other item type keeps exactly the presentation and the next-step routing
 * it already had, and gains no Reschedule or Close: nothing here can write a
 * commitment, a decision, an observation or a situation, so offering the
 * controls would be offering an action this surface cannot perform.
 *
 * **The order is the backend's and this component does not touch it.** No
 * `sort`, no `reverse`, no grouping by date. The rank is by evidentiary urgency
 * and it is the answer; re-ordering here — by `generatedAt`, say, which is
 * identical on every item — would discard it. The rank itself is not the
 * primary visual; it stays behind Details.
 *
 * Titles come from `subjectTitle` when the backend named the subject. Identifiers
 * and basis refs are never used as a title. `nextStep` is the one primary action.
 */
import Link from "next/link";
import type { BackendPulseItem } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { TodayTaskCard } from "@/components/pulse/today-task-card";
import { safeHref } from "@/lib/http/safe-href";

const TYPE_LABEL: Record<string, string> = {
  commitment: "Commitment",
  decision: "Decision",
  task: "Task",
  observation: "Observation",
  relationship_event: "Relationship event",
  situation: "Situation",
};

/**
 * Concise attention language per closed reason code. Derived from the code, so
 * no backend sentence, lifecycle token or identifier can leak into it, and a
 * code this build does not know still says something true and short.
 */
const TASK_ATTENTION_REASON: Record<string, string> = {
  task_overdue: "Overdue",
  task_due_soon: "Due soon",
};

const TASK_ATTENTION_FALLBACK = "Needs you today";

function taskAttentionReason(item: BackendPulseItem): string {
  return TASK_ATTENTION_REASON[item.reasonCode] ?? TASK_ATTENTION_FALLBACK;
}

const NEXT_STEP_LINK_CLASS =
  "mt-3 inline-flex min-h-[var(--control-height)] items-center justify-center rounded-[var(--radius-md)] bg-interactive px-4 text-sm font-medium text-on-interactive hover:bg-interactive-hover";

function typeLabel(itemType: string): string {
  return TYPE_LABEL[itemType] ?? "Item";
}

function pulseTitle(item: BackendPulseItem): string {
  const named = item.subjectTitle?.trim();
  if (named) return named;
  return `${typeLabel(item.itemType)} — ${item.reason}`;
}

/**
 * The authorized destination for an item's next step, or `null` when this build
 * has no route for that type. Tasks are absent on purpose: a Task never reaches
 * this branch, because it is answered in place by `TodayTaskCard`.
 */
function nextStepHref(item: BackendPulseItem): string | null {
  switch (item.itemType) {
    case "commitment":
      return `/work?commitmentId=${encodeURIComponent(item.itemRef)}`;
    case "situation":
      return "/situations";
    default:
      return null;
  }
}

export function BackendPulseList({ items }: { items: readonly BackendPulseItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted" data-testid="pulse-empty">
        Nothing needs attention right now.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {items.map((item) => {
        if (item.itemType === "task") {
          return (
            <li key={item.pulseId}>
              {/*
                The card is given a Task id, a display title and one concise
                reason, and nothing else — it holds no Task state it has not
                read, and prints no identifier it was handed.
              */}
              <TodayTaskCard
                taskId={item.itemRef}
                title={pulseTitle(item)}
                reason={taskAttentionReason(item)}
              />
            </li>
          );
        }
        const rawHref = item.nextStep ? nextStepHref(item) : null;
        const href = rawHref ? safeHref(rawHref) : null;
        return (
          <li key={item.pulseId}>
            <Card data-testid="pulse-item">
              <CardTitle>{pulseTitle(item)}</CardTitle>
              <CardBody>
                <p data-testid="pulse-reason">
                  <span className="font-medium text-text-primary">Why now:</span> {item.reason}
                </p>
                {item.consequence ? (
                  <p className="mt-1">
                    <span className="font-medium text-text-primary">If ignored:</span>{" "}
                    {item.consequence}
                  </p>
                ) : null}
                {item.nextStep ? (
                  href ? (
                    <Link
                      href={href}
                      className={NEXT_STEP_LINK_CLASS}
                      data-testid="pulse-next-step-link"
                    >
                      <span data-testid="pulse-next-step">{item.nextStep}</span>
                    </Link>
                  ) : (
                    <p className="mt-3 font-medium text-text-primary" data-testid="pulse-next-step">
                      {item.nextStep}
                    </p>
                  )
                ) : null}
                <details className="mt-2 text-xs text-muted" data-testid="pulse-basis">
                  <summary className="cursor-pointer font-medium text-text-primary">
                    Evidence/Details
                  </summary>
                  <p className="mt-2">
                    <span className="font-medium">Basis:</span> {item.basisRefs.join(", ")}
                  </p>
                  <p className="mt-1" data-testid="pulse-rank">
                    Rank {item.attentionRank}
                  </p>
                </details>
              </CardBody>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}
