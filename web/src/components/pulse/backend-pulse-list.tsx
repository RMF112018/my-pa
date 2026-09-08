/**
 * The derived Pulse, rendered so a human can see *why now* rather than *what
 * happened*.
 *
 * **The order is the backend's and this component does not touch it.** No
 * `sort`, no `reverse`, no grouping by date. The rank is by evidentiary urgency
 * and it is the answer; re-ordering here — by `generatedAt`, say, which is
 * identical on every item — would discard it.
 *
 * Titles come from `subjectTitle` when the backend named the subject. Identifiers
 * and basis refs are never used as a title.
 */
import Link from "next/link";
import type { BackendPulseItem } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { safeHref } from "@/lib/http/safe-href";

const TYPE_LABEL: Record<string, string> = {
  commitment: "Commitment",
  decision: "Decision",
  task: "Task",
  observation: "Observation",
  relationship_event: "Relationship event",
  situation: "Situation",
};

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
        Nothing needs attention right now. This is about today, not everything you hold.
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
              <div className="flex items-start justify-between gap-2">
                <CardTitle>{pulseTitle(item)}</CardTitle>
                <Badge tone="neutral">Urgency {item.priority}</Badge>
              </div>
              <CardBody>
                <p data-testid="pulse-reason">
                  <span className="font-medium text-moss-slate">Why now:</span> {item.reason}
                </p>
                {item.consequence ? (
                  <p className="mt-1">
                    <span className="font-medium text-moss-slate">If ignored:</span>{" "}
                    {item.consequence}
                  </p>
                ) : null}
                {item.nextStep ? (
                  <p className="mt-1" data-testid="pulse-next-step">
                    <span className="font-medium text-moss-slate">Next step:</span> {item.nextStep}
                    {href ? (
                      <>
                        {" "}
                        <Link
                          href={href}
                          className="text-moss-green underline"
                          data-testid="pulse-next-step-link"
                        >
                          Open {typeLabel(item.itemType)}
                        </Link>
                      </>
                    ) : null}
                  </p>
                ) : null}
                <details className="mt-2 text-xs text-muted" data-testid="pulse-basis">
                  <summary className="cursor-pointer font-medium text-moss-slate">
                    Evidence/Details
                  </summary>
                  <p className="mt-2">
                    <span className="font-medium">Basis:</span> {item.basisRefs.join(", ")}
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
