"use client";

/**
 * Relationship timeline — WP-06 (R5).
 *
 * Shows a person's accepted relationship events in temporal order. The
 * timeline reads only accepted records: a proposed (not-accepted) event is
 * never presented here, mirroring the Python `list_accepted_events` filter and
 * satisfying the WP-06 gate that Today/Pulse and timelines read only accepted
 * records. The events reaching this component are already principal-scoped and
 * accepted-only by the server route; the component states that guarantee
 * plainly rather than implying completeness.
 */
import type { RelationshipEvent, RelationshipEventType } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const EVENT_LABEL: Record<RelationshipEventType, string> = {
  interaction: "Interaction",
  meeting: "Meeting",
  commitment: "Commitment",
  observation: "Observation",
  affiliation_change: "Affiliation change",
  project_link: "Project link",
};

function formatWhen(iso: string): string {
  // Deterministic, locale-independent rendering for stable tests/SSR.
  return iso.replace("T", " ").replace("+00:00", " UTC");
}

export function RelationshipTimeline({ events }: { events: readonly RelationshipEvent[] }) {
  const ordered = [...events].sort((a, b) => a.occurredAt.localeCompare(b.occurredAt));

  return (
    <div>
      <p className="mb-3 text-xs text-muted" data-testid="accepted-only-note">
        Only accepted records are shown. Proposed items stay in Review until you disposition them.
      </p>
      {ordered.length === 0 ? (
        <p className="text-sm text-muted">No accepted events on this timeline yet.</p>
      ) : (
        <ol className="flex flex-col gap-3">
          {ordered.map((e) => (
            <li key={e.eventId}>
              <Card data-testid="timeline-event">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle>{EVENT_LABEL[e.eventType]}</CardTitle>
                  <Badge tone="green">Accepted</Badge>
                </div>
                <CardBody>
                  <p className="text-xs text-muted">{formatWhen(e.occurredAt)}</p>
                  {e.context ? <p className="mt-1">{e.context}</p> : null}
                </CardBody>
              </Card>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
