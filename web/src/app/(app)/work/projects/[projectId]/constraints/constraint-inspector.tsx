"use client";

/**
 * Constraint detail, rendered *into* the shell's one Inspector.
 *
 * There is no drawer, sheet, overlay or right rail in this file. It returns a
 * body, and `UtilityRegion` places it — which is what keeps one pin state, one
 * width, one mobile Sheet and one answer to "where does detail appear"
 * (`CM-FE-AC-090`).
 *
 * The section order is the accepted hierarchy: identity and actions, then
 * attention and urgency, then details, relationships, evidence, history, and
 * synchronisation last. Each is a labelled `<section>` with a heading, so a
 * screen reader can move between them rather than reading one long slab.
 *
 * **A detail read can fail while the Register stands.** When it does, this
 * states that the detail could not be read and the Register behind it is
 * untouched — clearing the workspace because one record would not load would
 * lose work the reader still has (`08` §3).
 *
 * **Nothing legacy is filled in.** A `LEGACY_INCOMPLETE` record shows the
 * callout, and then shows *the backend's* `missingFields` and
 * `needsAttentionReasons` and nothing else. A field the backend did not list is
 * not listed here, however obviously blank it looks (`CM-FE-AC-098`).
 */
import type {
  ConstraintHistoryEntry,
  ConstraintListEntry,
  ConstraintView,
} from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SurfaceState } from "@/components/ui/surface-state";
import {
  attentionReasonLabel,
  codeLabel,
  dateLabel,
  fieldLabel,
  LEGACY_CALLOUT_BODY,
  LEGACY_CALLOUT_TITLE,
  lifecycleLabel,
  lifecycleTone,
  operationLabel,
  partyLabel,
  syncLabel,
  urgencyLabels,
} from "./presentation";

/** The lifecycle operations this feature offers. All fixture-only. */
export type ConstraintLifecycleAction =
  | "publish"
  | "edit"
  | "transition"
  | "close"
  | "closeWithFollowUp"
  | "void"
  | "reopen";

function Section({
  title,
  testId,
  children,
}: {
  readonly title: string;
  readonly testId: string;
  readonly children: React.ReactNode;
}) {
  return (
    <section aria-label={title} data-testid={testId} className="mt-4">
      <h3 className="text-sm font-semibold text-moss-slate">{title}</h3>
      <div className="mt-1 text-sm">{children}</div>
    </section>
  );
}

function Detail({ label, value }: { readonly label: string; readonly value: React.ReactNode }) {
  return (
    <>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mb-1 text-sm text-moss-slate">{value}</dd>
    </>
  );
}

/** The heading the shell shows over the region. Code, or the Draft wording. */
export function inspectorTitle(entry: ConstraintListEntry | null): string {
  if (entry === null) return "Constraint";
  return `Constraint ${codeLabel(entry.constraintCode)}`;
}

export interface ConstraintInspectorProps {
  /** The list-level row, always available once a row was selected. */
  readonly entry: ConstraintListEntry | null;
  /**
   * The canonical detail, read lazily after selection. `undefined` while the
   * read is in flight, `null` when the read failed.
   */
  readonly detail: ConstraintView | null | undefined;
  readonly history: readonly ConstraintHistoryEntry[] | undefined;
  readonly onClose: () => void;
  readonly onNavigateToConstraint: (constraintId: string) => void;
  readonly onLifecycleAction: (action: ConstraintLifecycleAction) => void;
}

export function ConstraintInspector({
  entry,
  detail,
  history,
  onClose,
  onNavigateToConstraint,
  onLifecycleAction,
}: ConstraintInspectorProps) {
  if (entry === null) {
    return (
      <SurfaceState
        kind="empty"
        title="No Constraint selected"
        detail="Choose a Constraint in the Register to read it here."
        testId="inspector-none"
      />
    );
  }

  const legacy = entry.recordQuality === "LEGACY_INCOMPLETE";

  return (
    <div data-testid="constraint-inspector">
      {/* A. Identity, status and the actions that belong beside it. */}
      <section aria-label="Identity and status" data-testid="inspector-identity">
        <p className="text-lg font-semibold text-moss-slate">{codeLabel(entry.constraintCode)}</p>
        <p className="mt-1 text-sm text-moss-slate">{entry.description ?? "Not recorded"}</p>
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge tone={lifecycleTone(entry.status)}>{lifecycleLabel(entry.status)}</Badge>
          {entry.status === null ? null : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {entry.status === "DRAFT" ? (
            <Button size="sm" onClick={() => onLifecycleAction("publish")} data-testid="inspector-publish">
              Publish
            </Button>
          ) : null}
          <Button size="sm" variant="secondary" onClick={() => onLifecycleAction("edit")} data-testid="inspector-edit">
            Edit
          </Button>
          {entry.status !== null && entry.status !== "DRAFT" && entry.status !== "CLOSED" && entry.status !== "VOID" ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => onLifecycleAction("transition")} data-testid="inspector-transition">
                Change status
              </Button>
              <Button size="sm" variant="secondary" onClick={() => onLifecycleAction("close")} data-testid="inspector-close">
                Close
              </Button>
              <Button size="sm" variant="secondary" onClick={() => onLifecycleAction("closeWithFollowUp")} data-testid="inspector-close-follow-up">
                Close + Follow-up
              </Button>
              <Button size="sm" variant="danger" onClick={() => onLifecycleAction("void")} data-testid="inspector-void">
                Void
              </Button>
            </>
          ) : null}
          {entry.status === "CLOSED" ? (
            <Button size="sm" variant="secondary" onClick={() => onLifecycleAction("reopen")} data-testid="inspector-reopen">
              Reopen
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="inspector-close-panel">
            Close detail
          </Button>
        </div>
      </section>

      {/* B. Attention, urgency and synchronisation — all backend fields. */}
      <Section title="Attention and urgency" testId="inspector-attention">
        {legacy ? (
          <div
            role="status"
            data-testid="inspector-legacy-callout"
            className="mb-2 rounded-md border border-moss-gold/40 bg-moss-gold/10 p-2"
          >
            <p className="font-medium text-moss-slate">{LEGACY_CALLOUT_TITLE}</p>
            <p className="mt-1 text-muted">{LEGACY_CALLOUT_BODY}</p>
          </div>
        ) : null}
        <div className="flex flex-wrap gap-1">
          {urgencyLabels(entry).map((label) => (
            <Badge key={label} tone={label === "Overdue" ? "coral" : "gold"}>
              {label}
            </Badge>
          ))}
          {entry.inMyCourt ? <Badge tone="gold">In my court</Badge> : null}
          {entry.needsAttention ? <Badge tone="gold">Needs attention</Badge> : null}
          {urgencyLabels(entry).length === 0 && !entry.inMyCourt && !entry.needsAttention ? (
            <span className="text-muted">The backend flags nothing on this record.</span>
          ) : null}
        </div>
        {detail && detail.needsAttentionReasons.length > 0 ? (
          <ul className="mt-2 list-inside list-disc text-muted" data-testid="inspector-attention-reasons">
            {detail.needsAttentionReasons.map((reason) => (
              <li key={reason}>{attentionReasonLabel(reason)}</li>
            ))}
          </ul>
        ) : null}
        {detail && detail.missingFields.length > 0 ? (
          <>
            <p className="mt-2 text-muted">Fields the backend recorded as missing:</p>
            <ul className="list-inside list-disc text-muted" data-testid="inspector-missing-fields">
              {detail.missingFields.map((field) => (
                <li key={field}>{fieldLabel(field)}</li>
              ))}
            </ul>
          </>
        ) : null}
      </Section>

      {detail === undefined ? (
        <p className="mt-4 text-sm text-muted" data-testid="inspector-detail-loading">
          Reading the canonical record…
        </p>
      ) : detail === null ? (
        <div className="mt-4">
          <SurfaceState
            kind="unavailable"
            title="This Constraint's detail could not be read"
            detail="The Register above is unaffected and still shows what was read successfully."
            testId="inspector-detail-unavailable"
          />
        </div>
      ) : (
        <>
          {/* C. Canonical details. */}
          <Section title="Details" testId="inspector-details">
            <dl>
              <Detail label="Project" value={detail.projectId ?? "Not recorded"} />
              <Detail
                label="Category"
                value={detail.category === null ? "Not recorded" : detail.category.title}
              />
              <Detail label="Date Identified" value={dateLabel(detail.dateIdentified)} />
              <Detail label="Due Date" value={dateLabel(detail.dueDate)} />
              <Detail label="Days open" value={detail.daysElapsed === null ? "Not recorded" : String(detail.daysElapsed)} />
              {/* Two names, two accessible labels. `CM-FE-AC-143`. */}
              <Detail label="Ball in Court" value={partyLabel(detail.bic)} />
              <Detail label="Responsible party" value={partyLabel(detail.responsible)} />
              <Detail label="Reference" value={detail.reference ?? "Not recorded"} />
              <Detail label="Current update" value={detail.currentUpdate ?? "Not recorded"} />
              <Detail label="Record quality" value={legacy ? LEGACY_CALLOUT_TITLE : "Current record"} />
              <Detail label="Version" value={String(detail.version)} />
              {detail.completion ? (
                <>
                  <Detail label="Completion date" value={dateLabel(detail.completion.completionDate)} />
                  <Detail
                    label="Closure commentary"
                    value={detail.completion.closureCommentary ?? "Not recorded"}
                  />
                </>
              ) : null}
              {detail.void ? (
                <>
                  <Detail label="Voided date" value={dateLabel(detail.void.voidedDate)} />
                  <Detail label="Void reason" value={detail.void.voidReason ?? "Not recorded"} />
                </>
              ) : null}
            </dl>
          </Section>

          {/* D. Relationships, navigated by backend relationship identity. */}
          <Section title="Relationships" testId="inspector-relationships">
            {detail.relationships.length === 0 ? (
              <p className="text-muted">The backend records no relationships for this Constraint.</p>
            ) : (
              <ul className="grid gap-1">
                {detail.relationships.map((relationship) => (
                  <li key={relationship.relationshipId}>
                    <button
                      type="button"
                      data-testid={`inspector-relationship-${relationship.relationshipId}`}
                      onClick={() => onNavigateToConstraint(relationship.relatedConstraintId)}
                      className="min-h-11 rounded text-left text-moss-green underline"
                    >
                      {relationship.direction === "OUTGOING"
                        ? `Follow-up Constraint ${relationship.relatedConstraintCode ?? "(no Code)"}`
                        : `Originated from ${relationship.relatedConstraintCode ?? "(no Code)"}`}
                    </button>{" "}
                    <span className="text-muted">
                      {relationship.relationshipType} ·{" "}
                      {lifecycleLabel(relationship.relatedStatus)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* E. Evidence. Typed references only, and safe links only. */}
          <Section title="Evidence" testId="inspector-evidence">
            {detail.evidenceLinks.length === 0 ? (
              <p className="text-muted">No evidence is linked to this Constraint.</p>
            ) : (
              <ul className="grid gap-1">
                {detail.evidenceLinks.map((link) => (
                  <li key={link.evidenceLinkId} data-testid={`inspector-evidence-${link.evidenceLinkId}`}>
                    <span className="text-muted">{link.evidenceKind}</span>{" "}
                    {link.isSafeUrl ? (
                      <a
                        href={link.evidenceRef}
                        rel="noreferrer noopener"
                        target="_blank"
                        className="text-moss-green underline"
                      >
                        {link.evidenceRef}
                      </a>
                    ) : (
                      // Not validated as a link by the backend, so not made one
                      // here. Auto-linking arbitrary reference text is exactly
                      // what `CM-FE-AC-095` forbids.
                      <span data-testid={`inspector-evidence-text-${link.evidenceLinkId}`}>
                        {link.evidenceRef}
                      </span>
                    )}{" "}
                    <span className="text-muted">({link.role})</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* F. History — a timeline, not audit JSON. */}
          <Section title="History" testId="inspector-history">
            {history === undefined || history.length === 0 ? (
              <p className="text-muted">No history has been read for this Constraint.</p>
            ) : (
              <ol className="grid gap-2">
                {history.map((item) => (
                  <li key={item.historyId} data-testid={`inspector-history-${item.historyId}`}>
                    <p className="font-medium text-moss-slate">
                      {operationLabel(item.operation)}{" "}
                      <span className="font-normal text-muted">
                        · {item.occurredAt} · {item.actor.toLowerCase()} ·{" "}
                        {item.outcome.toLowerCase()}
                      </span>
                    </p>
                    <p className="text-muted">
                      Version {item.beforeVersion} → {item.afterVersion}
                    </p>
                    {item.provenance ? (
                      <p className="text-muted" data-testid={`inspector-provenance-${item.historyId}`}>
                        {item.provenance}
                      </p>
                    ) : null}
                    {item.safeFailureReason ? (
                      <p className="text-moss-coral-strong">{item.safeFailureReason}</p>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </Section>

          {/* G. Synchronisation, kept visually separate from canonical state. */}
          <Section title="Synchronisation" testId="inspector-sync">
            <p>
              <Badge tone="neutral">{syncLabel(detail.sync.state)}</Badge>
            </p>
            <p className="mt-1 text-muted">
              {detail.sync.conflictCount} open conflict
              {detail.sync.conflictCount === 1 ? "" : "s"}. Last verified{" "}
              {detail.sync.lastVerifiedAt ?? "never"}.
            </p>
            <p className="mt-1 text-muted">
              This is the workbook&rsquo;s condition, not the canonical record&rsquo;s. The record
              above is saved regardless of what this says.
            </p>
          </Section>
        </>
      )}
    </div>
  );
}
