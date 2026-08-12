/**
 * The Library's records, in the two shapes the backend actually produces.
 *
 * Two components rather than one, because a listing entry and a search match are
 * two different rows and merging them would mean inventing the fields each one
 * lacks — the same argument `BackendReviewCase` makes against merging with the
 * fixture `ReviewCase`.
 *
 * **Neither renders capture text, because neither answer carries any.** The
 * Python listing and search shapes have no field content could occupy
 * (`QC-AC-041`), so there is nothing to omit here and nothing to summarise. What
 * is shown instead is what a person can actually act on: which capture, how many
 * versions it has, when it was recorded, and — for a search — how long the
 * matching version is. A preview would have to be fabricated, and fabricating
 * one is the specific thing this surface exists not to do.
 *
 * **Empty is not rendered here.** A component that drew its own "nothing found"
 * line could not know whether the read succeeded; that decision belongs to
 * `lib/api/surface-answer.ts` and is rendered by `SurfaceState`. These two
 * components are given rows and render rows.
 */
import type { BackendCaptureEntry, BackendCaptureMatch } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/** A moment, rendered so it is legible without claiming a precision it lacks. */
function moment(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function CaptureListing({ entries }: { entries: readonly BackendCaptureEntry[] }) {
  return (
    <ul className="flex flex-col gap-3" data-testid="library-listing">
      {entries.map((entry) => (
        <li key={entry.captureId}>
          <Card data-testid="library-capture">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <CardTitle>
                <span className="font-mono text-sm break-all">{entry.captureId}</span>
              </CardTitle>
              <Badge tone={entry.versionCount > 1 ? "gold" : "neutral"}>
                {entry.versionCount === 1 ? "1 version" : `${entry.versionCount} versions`}
              </Badge>
            </div>
            <CardBody>
              <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                <dt className="text-muted">first captured</dt>
                <dd>{moment(entry.createdAt)}</dd>
                <dt className="text-muted">latest version</dt>
                <dd className="font-mono text-xs break-all">
                  #{entry.latestVersionNumber} · {entry.latestVersionId}
                </dd>
                <dt className="text-muted">latest recorded</dt>
                <dd>{moment(entry.latestRecordedAt)}</dd>
                <dt className="text-muted">owner</dt>
                <dd className="font-mono text-xs break-all">{entry.ownerPrincipalId}</dd>
              </dl>
              <p className="mt-2 text-xs">
                The captured text is not shown here. A listing carries no content by design, so it
                cannot become a second, unaudited read of what you wrote.
              </p>
            </CardBody>
          </Card>
        </li>
      ))}
    </ul>
  );
}

export function CaptureMatches({ matches }: { matches: readonly BackendCaptureMatch[] }) {
  return (
    <ul className="flex flex-col gap-3" data-testid="library-matches">
      {matches.map((match) => (
        <li key={match.versionId}>
          <Card data-testid="library-match">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <CardTitle>
                <span className="font-mono text-sm break-all">{match.captureId}</span>
              </CardTitle>
              <Badge tone="neutral">version {match.versionNumber}</Badge>
            </div>
            <CardBody>
              <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                <dt className="text-muted">matched version</dt>
                <dd className="font-mono text-xs break-all">{match.versionId}</dd>
                <dt className="text-muted">recorded</dt>
                <dd>{moment(match.recordedAt)}</dd>
                <dt className="text-muted">length</dt>
                <dd>{match.characterCount} characters</dd>
              </dl>
              <p className="mt-2 text-xs">
                This version matched your terms. The answer says which version matched and not
                which words did, so no part of the text is quoted back through search.
              </p>
            </CardBody>
          </Card>
        </li>
      ))}
    </ul>
  );
}
