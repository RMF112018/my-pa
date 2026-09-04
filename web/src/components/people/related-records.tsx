import Link from "next/link";
import { Card, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DegradedBanner, SurfaceState } from "@/components/ui/surface-state";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { AssignmentView } from "@/lib/api/decode/capabilities/entities.assignments.list";
import type { RelationshipView } from "@/lib/api/decode/capabilities/entities.relationships";
import type { IdentityHistoryEntry } from "@/lib/api/decode/capabilities/entities.identity_history";
import { peopleEntity } from "@/lib/routes/people";
import { directedIsCurrent, partitionByCurrency } from "./currency";
import { codeLabel, effectiveWindow, moment } from "./format";

function currentBadge(current: boolean) {
  return <Badge tone={current ? "green" : "gold"}>{current ? "Current" : "Historical"}</Badge>;
}

export function AssignmentsPanel({
  assignments,
  disclosure,
  unavailable,
}: {
  assignments: readonly AssignmentView[] | null;
  disclosure: DisclosureEnvelope | null;
  unavailable: string | null;
}) {
  if (unavailable) {
    return (
      <section className="mt-6" aria-labelledby="people-assignments-heading">
        <h2 id="people-assignments-heading" className="text-base font-semibold text-moss-slate">
          Assignments
        </h2>
        <div className="mt-2">
          <SurfaceState
            kind="unavailable"
            title="Assignments could not be read"
            detail={unavailable}
            testId="people-assignments-unavailable"
          />
        </div>
      </section>
    );
  }
  if (assignments === null) return null;
  const { current, historical } = partitionByCurrency(assignments, directedIsCurrent);
  return (
    <section className="mt-6" aria-labelledby="people-assignments-heading" data-testid="people-assignments">
      <h2 id="people-assignments-heading" className="text-base font-semibold text-moss-slate">
        Assignments
      </h2>
      {disclosure?.coverage === "partial" ? (
        <DegradedBanner
          scope="assignments"
          limitations={disclosure.limitations}
          truncated={disclosure.truncated}
        />
      ) : null}
      {assignments.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No assignments were returned for this entity.</p>
      ) : (
        <>
          {current.length > 0 ? (
            <div className="mt-3" data-testid="people-assignments-current">
              <h3 className="text-sm font-medium text-moss-slate">Current</h3>
              <ul className="mt-2 space-y-2">
                {current.map((row) => (
                  <AssignmentItem key={row.assignment_id} row={row} />
                ))}
              </ul>
            </div>
          ) : null}
          {historical.length > 0 ? (
            <div className="mt-3" data-testid="people-assignments-historical">
              <h3 className="text-sm font-medium text-moss-slate">Historical</h3>
              <ul className="mt-2 space-y-2">
                {historical.map((row) => (
                  <AssignmentItem key={row.assignment_id} row={row} />
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function AssignmentItem({ row }: { row: AssignmentView }) {
  const window = effectiveWindow(row.effective_from, row.effective_to);
  const current = directedIsCurrent(row);
  return (
    <li>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-sm font-medium text-moss-slate">
            {row.role ?? codeLabel(row.assignment_type)}
          </p>
          {currentBadge(current)}
        </div>
        <CardBody>
          <p>
            {codeLabel(row.assignment_type)} · {codeLabel(row.status)}
            {row.discipline ? ` · ${row.discipline}` : ""}
          </p>
          {row.scope_entity_id ? (
            <p className="mt-1">
              Scope{" "}
              <Link href={peopleEntity(row.scope_entity_id)} className="underline decoration-moss-green/40">
                {row.scope_entity_id}
              </Link>
            </p>
          ) : null}
          {window ? <p className="mt-1 text-xs text-muted">{window}</p> : null}
        </CardBody>
      </Card>
    </li>
  );
}

export function RelationshipsPanel({
  relationships,
  subjectId,
  disclosure,
  unavailable,
}: {
  relationships: readonly RelationshipView[] | null;
  subjectId: string;
  disclosure: DisclosureEnvelope | null;
  unavailable: string | null;
}) {
  if (unavailable) {
    return (
      <section className="mt-6" aria-labelledby="people-relationships-heading">
        <h2 id="people-relationships-heading" className="text-base font-semibold text-moss-slate">
          Relationships
        </h2>
        <div className="mt-2">
          <SurfaceState
            kind="unavailable"
            title="Relationships could not be read"
            detail={unavailable}
            testId="people-relationships-unavailable"
          />
        </div>
      </section>
    );
  }
  if (relationships === null) return null;
  const { current, historical } = partitionByCurrency(relationships, directedIsCurrent);
  return (
    <section className="mt-6" aria-labelledby="people-relationships-heading" data-testid="people-relationships">
      <h2 id="people-relationships-heading" className="text-base font-semibold text-moss-slate">
        Relationships
      </h2>
      {disclosure?.coverage === "partial" ? (
        <DegradedBanner
          scope="relationships"
          limitations={disclosure.limitations}
          truncated={disclosure.truncated}
        />
      ) : null}
      {relationships.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No relationships were returned for this entity.</p>
      ) : (
        <>
          {current.length > 0 ? (
            <div className="mt-3" data-testid="people-relationships-current">
              <h3 className="text-sm font-medium text-moss-slate">Current</h3>
              <ul className="mt-2 space-y-2">
                {current.map((row) => (
                  <RelationshipItem key={row.relationship_id} row={row} subjectId={subjectId} />
                ))}
              </ul>
            </div>
          ) : null}
          {historical.length > 0 ? (
            <div className="mt-3" data-testid="people-relationships-historical">
              <h3 className="text-sm font-medium text-moss-slate">Historical</h3>
              <ul className="mt-2 space-y-2">
                {historical.map((row) => (
                  <RelationshipItem key={row.relationship_id} row={row} subjectId={subjectId} />
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function RelationshipItem({ row, subjectId }: { row: RelationshipView; subjectId: string }) {
  const outbound = row.from_entity_id === subjectId;
  const relatedId = outbound ? row.to_entity_id : row.from_entity_id;
  const direction = outbound ? "from this entity" : "toward this entity";
  const current = directedIsCurrent(row);
  const window = effectiveWindow(row.effective_from, row.effective_to);
  const relatedIsCanonical = relatedId.length > 0;
  return (
    <li>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-sm font-medium text-moss-slate">{codeLabel(row.relationship_type)}</p>
          {currentBadge(current)}
        </div>
        <CardBody>
          <p>
            {direction} · {codeLabel(row.state)}
          </p>
          {relatedIsCanonical ? (
            <p className="mt-1">
              Related entity{" "}
              <Link href={peopleEntity(relatedId)} className="font-mono text-xs underline decoration-moss-green/40">
                {relatedId}
              </Link>
            </p>
          ) : (
            <p className="mt-1 text-muted">No canonical related entity identifier was supplied.</p>
          )}
          {window ? <p className="mt-1 text-xs text-muted">{window}</p> : null}
        </CardBody>
      </Card>
    </li>
  );
}

export function IdentityHistoryPanel({
  entries,
  truncated,
  nextCursor,
  entityId,
  unavailable,
}: {
  entries: readonly IdentityHistoryEntry[] | null;
  truncated: boolean;
  nextCursor: string | null;
  entityId: string;
  unavailable: string | null;
}) {
  if (unavailable) {
    return (
      <section className="mt-6" aria-labelledby="people-history-heading">
        <h2 id="people-history-heading" className="text-base font-semibold text-moss-slate">
          Identity history
        </h2>
        <div className="mt-2">
          <SurfaceState
            kind="unavailable"
            title="Identity history could not be read"
            detail={unavailable}
            testId="people-history-unavailable"
          />
        </div>
      </section>
    );
  }
  if (entries === null) return null;
  return (
    <section className="mt-6" aria-labelledby="people-history-heading" data-testid="people-history">
      <h2 id="people-history-heading" className="text-base font-semibold text-moss-slate">
        Identity history
      </h2>
      {truncated ? (
        <DegradedBanner
          scope="identity history"
          limitations={["This page of the ledger is not the whole history."]}
          truncated
        />
      ) : null}
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No identity-history entries were returned.</p>
      ) : (
        <ol className="mt-3 space-y-2">
          {entries.map((entry) => (
            <li key={entry.history_id}>
              <Card>
                <p className="text-sm font-medium text-moss-slate">{codeLabel(entry.operation)}</p>
                <CardBody>
                  <p>
                    {codeLabel(entry.source)} · {moment(entry.occurred_at)}
                  </p>
                  {entry.reason ? <p className="mt-1">{entry.reason}</p> : null}
                  {entry.changes.length > 0 ? (
                    <ul className="mt-2 list-inside list-disc text-xs text-muted">
                      {entry.changes.map((change) => (
                        <li key={`${change.family}:${change.record_id}:${change.effect_kind}`}>
                          {codeLabel(change.family)} · {codeLabel(change.effect_kind)}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </CardBody>
              </Card>
            </li>
          ))}
        </ol>
      )}
      {nextCursor ? (
        <p className="mt-3 text-sm">
          <Link
            href={`${peopleEntity(entityId)}?historyAfter=${encodeURIComponent(nextCursor)}`}
            className="text-moss-green underline"
          >
            Continue identity history
          </Link>
        </p>
      ) : null}
    </section>
  );
}
