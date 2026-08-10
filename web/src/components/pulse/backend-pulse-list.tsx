/**
 * The derived Pulse, rendered so a human can see *why now* rather than *what
 * happened*.
 *
 * Four things are on every card and none of them is optional decoration:
 *
 * * **the reason code**, from the closed backend vocabulary, so the condition
 *   has a name and two items surfaced for the same reason look the same;
 * * **the reason**, which states the measurement the condition was computed
 *   from — how far past due, how close, how many obligations stand;
 * * **the basis**, the identifiers a reader can go and open. A Pulse that asked
 *   to be trusted would omit this, and omitting it is what makes a feed;
 * * **the next step**, so the item is actionable rather than merely alarming.
 *
 * **The order is the backend's and this component does not touch it.** No
 * `sort`, no `reverse`, no grouping by date. The rank is by evidentiary urgency
 * and it is the answer; re-ordering here — by `generatedAt`, say, which is
 * identical on every item — would discard it and produce exactly the list this
 * package exists to avoid.
 *
 * The empty state says nothing needs attention *and why that is a claim*: the
 * derivation found no accepted object with a why-now condition, which is not the
 * same as "you have no commitments".
 */
import type { BackendPulseItem } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/** The closed reason vocabulary, as a sentence a person reads. */
const REASON_LABEL: Record<string, string> = {
  commitment_overdue: "Commitment past its agreed moment",
  commitment_due_soon: "Commitment due shortly",
  task_overdue: "Task past its date",
  task_due_soon: "Task due shortly",
  decision_awaiting_authority: "Decision blocked on a named authority point",
  situation_obligation_unmet: "Situation with obligations still unmet",
};

export function BackendPulseList({ items }: { items: readonly BackendPulseItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted" data-testid="pulse-empty">
        No accepted commitment, decision, task or situation currently meets a why-now condition.
        That is a statement about today, not about what you hold.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {items.map((item) => (
        <li key={item.pulseId}>
          <Card data-testid="pulse-item">
            <div className="flex items-start justify-between gap-2">
              <CardTitle>{REASON_LABEL[item.reasonCode] ?? item.reasonCode}</CardTitle>
              <Badge tone="neutral">
                Urgency {item.priority}
              </Badge>
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
                </p>
              ) : null}
              <p className="mt-2 text-xs text-muted" data-testid="pulse-basis">
                <span className="font-medium">Basis:</span> {item.basisRefs.join(", ")}
              </p>
            </CardBody>
          </Card>
        </li>
      ))}
    </ul>
  );
}
