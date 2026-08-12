/**
 * The four answers a surface may give when it is not showing records, kept
 * apart from one another in text, in colour, and in the accessibility tree.
 *
 * This module exists because the failure it prevents is the one this tier can
 * most easily commit and the hardest for a reader to detect: a surface that
 * renders "nothing here" for a call that failed. The person reading it then
 * believes a fact about their own record — *I have no captures* — that nothing
 * established. `WP-09` built the distinction on the server (`INV-PKL-007`, and
 * the `coverage` discriminator `lib/api/gateway.ts` reads off the gateway's own
 * disclosure); this is where it becomes something a human and a screen reader
 * can both tell apart.
 *
 * The four states, and what each one is a claim about:
 *
 * * **empty** — the read succeeded and the Principal holds nothing. This is the
 *   only one of the four that is a claim about the record, and it is only ever
 *   rendered when a successful answer came back carrying no rows.
 * * **unavailable** — the read did not succeed. Nothing was retrieved, so
 *   nothing is claimed about what is held. Rendered `role="alert"` because it
 *   is a failure the reader must not miss, and worded so that no sentence in it
 *   can be read as "you have none".
 * * **degraded** — the read succeeded and the backend said its own answer is
 *   partial. What came back is shown *and* the limitation is stated, because
 *   showing partial rows without saying so is the same lie as an empty page for
 *   a failure, one row at a time.
 * * **not_implemented** — there is nothing on the backend to ask. Different
 *   from `unavailable` for the reason `lib/api/serving.ts` gives: `unavailable`
 *   implies a retry could succeed and this does not.
 *
 * **Nothing here is conveyed by colour alone.** Every state carries a word (the
 * badge label), a distinct heading, and a distinct `data-state` attribute, so a
 * reader who cannot distinguish the sand, gold and coral tones still gets the
 * whole distinction from the text. The badge tone is redundant reinforcement and
 * never the carrier.
 *
 * **The accessibility tree separates them too.** Each state is a labelled
 * region whose accessible name is its own heading, so two states never present
 * as the same node to assistive technology, and `role="alert"` versus
 * `role="status"` distinguishes the failure from the three non-failures at the
 * live-region level.
 */
import type { ReactNode } from "react";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/** The four answers. There is deliberately no fifth and no default. */
export type SurfaceStateKind = "empty" | "unavailable" | "degraded" | "not_implemented";

interface Presentation {
  readonly badge: string;
  readonly tone: "neutral" | "gold" | "coral" | "green";
  /** `alert` for the failure; `status` for the three that are not failures. */
  readonly role: "alert" | "status";
  /** The sentence that fixes what this state is a claim about, and what it is not. */
  readonly clarification: string;
}

const PRESENTATION: Record<SurfaceStateKind, Presentation> = {
  empty: {
    badge: "Empty",
    tone: "neutral",
    role: "status",
    clarification:
      "This was read successfully and it holds nothing. That is a fact about your record, " +
      "not a failure to reach it.",
  },
  unavailable: {
    badge: "Could not be read",
    tone: "coral",
    role: "alert",
    clarification:
      "Nothing was retrieved, so nothing here is a result and nothing is claimed about what " +
      "you hold. This is not an empty record — it is a read that did not happen.",
  },
  degraded: {
    badge: "Partial",
    tone: "gold",
    role: "status",
    clarification:
      "The backend answered, and said its own answer is incomplete. What is shown is real; " +
      "what is missing is stated below rather than silently absent.",
  },
  not_implemented: {
    badge: "Not built",
    tone: "gold",
    role: "status",
    clarification:
      "There is no capability behind this surface in this build, so there is nothing to ask " +
      "and retrying cannot change that. No data was invented to fill the space.",
  },
};

export interface SurfaceStateProps {
  readonly kind: SurfaceStateKind;
  /** The heading. Distinct per state per surface; it is the accessible name. */
  readonly title: string;
  /** What the backend, or this tier, actually said. Rendered verbatim. */
  readonly detail?: string | null;
  /** Limitations the backend disclosed. Shown for `degraded` above all. */
  readonly limitations?: readonly string[];
  /** Extra content — a retry affordance, a link — placed after the sentences. */
  readonly children?: ReactNode;
  /** Distinguishes two states of the same kind on one page. */
  readonly testId?: string;
}

/**
 * One non-record answer, rendered so it cannot be mistaken for another.
 *
 * `kind` is required and has no default: a caller that has not decided which of
 * the four this is has not got an answer to render.
 */
export function SurfaceState({
  kind,
  title,
  detail,
  limitations = [],
  children,
  testId,
}: SurfaceStateProps) {
  const presentation = PRESENTATION[kind];
  const headingId = `surface-state-${testId ?? kind}`;
  return (
    <Card
      role={presentation.role}
      aria-labelledby={headingId}
      data-state={kind}
      data-testid={testId ?? `state-${kind}`}
      className="border-l-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span id={headingId}>
          <CardTitle>{title}</CardTitle>
        </span>
        <Badge tone={presentation.tone}>{presentation.badge}</Badge>
      </div>
      <CardBody>
        <p data-testid="surface-state-clarification">{presentation.clarification}</p>
        {detail ? (
          <p className="mt-2" data-testid="surface-state-detail">
            {detail}
          </p>
        ) : null}
        {limitations.length > 0 ? (
          <>
            <p className="mt-2 font-medium text-moss-slate">What is missing from this answer:</p>
            <ul className="mt-1 list-inside list-disc" data-testid="surface-state-limitations">
              {limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </>
        ) : null}
        {children}
      </CardBody>
    </Card>
  );
}

/**
 * The disclosure banner that sits *above* real records when the answer is
 * partial.
 *
 * Separate from `SurfaceState` because a degraded answer still has rows, and the
 * rows must be rendered. A surface that replaced them with a state card would be
 * withholding real data; a surface that showed them with no banner would be
 * presenting a partial answer as a whole one. This is the third option and the
 * only honest one.
 */
export function DegradedBanner({
  scope,
  limitations,
  truncated = false,
}: {
  scope: string;
  limitations: readonly string[];
  truncated?: boolean;
}) {
  return (
    <div
      role="status"
      data-state="degraded"
      data-testid="degraded-banner"
      className="mb-3 rounded-md border border-moss-gold/40 border-l-4 border-l-moss-gold bg-moss-gold/10 p-3 text-sm"
    >
      <p className="font-medium text-moss-slate">
        Partial answer — {scope} returned less than the whole.
      </p>
      <p className="mt-1 text-muted">
        The records below are real. They are not all of them, and the backend said so rather than
        this page guessing it.
      </p>
      {truncated ? (
        <p className="mt-1 text-muted" data-testid="degraded-truncated">
          The answer was cut off at this build&rsquo;s page limit, and there is no continuation
          token to ask for the rest.
        </p>
      ) : null}
      {limitations.length > 0 ? (
        <ul className="mt-1 list-inside list-disc text-muted">
          {limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
