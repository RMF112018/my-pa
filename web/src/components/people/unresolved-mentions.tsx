import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { DegradedBanner } from "@/components/ui/surface-state";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { UnresolvedMentionView } from "@/lib/api/decode/capabilities/entities.unresolved_mentions";
import { peopleHome } from "@/lib/routes/people";
import { codeLabel, moment } from "./format";

/**
 * Bounded unread mentions. Renders only disclosed summaries.
 * Never prints `observed_value` or other withheld source text. No resolve/merge.
 */
export function UnresolvedMentionsPanel({
  mentions,
  disclosure,
}: {
  mentions: readonly UnresolvedMentionView[];
  disclosure: DisclosureEnvelope;
}) {
  const named = mentions.filter((row) => row.mention_display_name);
  if (named.length === 0) return null;

  return (
    <section className="mt-6" aria-labelledby="people-unresolved-heading" data-testid="people-unresolved">
      <h2 id="people-unresolved-heading" className="text-base font-semibold text-moss-slate">
        Unresolved mentions
      </h2>
      <p className="mt-1 text-sm text-muted">
        References nothing has placed yet. Source text is not shown. Nothing here resolves or merges.
      </p>
      {disclosure.coverage === "partial" ? (
        <DegradedBanner
          scope="unresolved mentions"
          limitations={disclosure.limitations}
          truncated={disclosure.truncated}
        />
      ) : null}
      <ul className="mt-3 space-y-2">
        {named.map((row) => (
          <li key={row.observation_id}>
            <Card>
              <CardTitle>{row.mention_display_name}</CardTitle>
              <CardBody>
                <p>
                  {codeLabel(row.kind)} · observed {moment(row.observed_at)}
                </p>
              </CardBody>
            </Card>
          </li>
        ))}
      </ul>
      {disclosure.nextCursor ? (
        <p className="mt-3 text-sm">
          <a
            href={`${peopleHome()}?mentionsAfter=${encodeURIComponent(disclosure.nextCursor)}`}
            className="text-moss-green underline"
          >
            Continue unresolved mentions
          </a>
        </p>
      ) : null}
    </section>
  );
}
