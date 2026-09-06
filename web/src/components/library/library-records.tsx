/**
 * The Library's records, in the two shapes the backend actually produces.
 *
 * Listing and search-match cards remain two components rather than one, because
 * merging them would invent the fields each lacks. **Those cards still render no
 * capture text** (`QC-AC-041`): list/search have no content field. Canonical
 * `text` appears only on `CaptureItem` / `KnowledgeItem`, which are the
 * `capture.read` / `knowledge.read` item projections Search deep-links into.
 *
 * **Empty is not rendered here.** A component that drew its own "nothing found"
 * line could not know whether the read succeeded; that decision belongs to
 * `lib/api/surface-answer.ts` and is rendered by `SurfaceState`. These two
 * components are given rows and render rows.
 */
import type { BackendCaptureEntry, BackendCaptureMatch } from "@/contracts/views";
import type { CaptureReadResult } from "@/lib/api/decode/capabilities/capture.read";
import type { KnowledgeReadResult } from "@/lib/api/decode/capabilities/knowledge.read";
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

/**
 * One capture version from `capture.read`. This is the only Library renderer
 * that may show capture `text`: listing and search cards have no such field.
 */
export function CaptureItem({ version }: { version: CaptureReadResult }) {
  return (
    <article data-testid="library-capture-item">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle>
            <span className="font-mono text-sm break-all">{version.capture_id}</span>
          </CardTitle>
          <Badge tone={version.is_current ? "gold" : "neutral"}>
            {version.is_current ? "current version" : `version ${version.version_number}`}
          </Badge>
        </div>
        <CardBody>
          <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
            <dt className="text-muted">version</dt>
            <dd className="font-mono text-xs break-all">
              #{version.version_number} · {version.version_id}
            </dd>
            <dt className="text-muted">recorded</dt>
            <dd>{moment(version.recorded_at)}</dd>
            <dt className="text-muted">length</dt>
            <dd>{version.character_count} characters</dd>
            <dt className="text-muted">classification</dt>
            <dd>{version.classification}</dd>
          </dl>
          <p
            className="mt-3 whitespace-pre-wrap text-sm text-moss-slate"
            data-testid="library-capture-text"
          >
            {version.text}
          </p>
        </CardBody>
      </Card>
    </article>
  );
}

/**
 * One knowledge record from `knowledge.read`. Renders the capability's own
 * `text` field when present and invents no second snippet.
 */
export function KnowledgeItem({ record }: { record: KnowledgeReadResult }) {
  return (
    <article data-testid="library-knowledge-item">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle>
            <span className="font-mono text-sm break-all">{record.knowledge_id}</span>
          </CardTitle>
          <Badge tone="neutral">{record.label}</Badge>
        </div>
        <CardBody>
          <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
            <dt className="text-muted">media type</dt>
            <dd>{record.media_type}</dd>
            <dt className="text-muted">length</dt>
            <dd>{record.character_count} characters</dd>
            <dt className="text-muted">source</dt>
            <dd className="font-mono text-xs break-all">{record.provenance.source_id}</dd>
          </dl>
          {record.text !== undefined ? (
            <p
              className="mt-3 whitespace-pre-wrap text-sm text-moss-slate"
              data-testid="library-knowledge-text"
            >
              {record.text}
            </p>
          ) : (
            <p className="mt-3 text-xs" data-testid="library-knowledge-metadata-only">
              This record was returned without text. No snippet is invented in its place.
            </p>
          )}
        </CardBody>
      </Card>
    </article>
  );
}
