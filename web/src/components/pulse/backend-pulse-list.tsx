/**
 * The derived Pulse, rendered so a human can see *why now* rather than *what
 * happened*.
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
import { safeHref } from "@/lib/http/safe-href";

const TYPE_LABEL: Record<string, string> = {
  commitment: "Commitment",
  decision: "Decision",
  task: "Task",
  observation: "Observation",
  relationship_event: "Relationship event",
  situation: "Situation",
};

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

function nextStepHref(item: BackendPulseItem): string | null {
  switch (item.itemType) {
    case "task":
      return `/work?task=${encodeURIComponent(item.itemRef)}`;
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
                    Rank {item.priority}
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
