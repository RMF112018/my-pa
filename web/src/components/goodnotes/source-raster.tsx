import type { GoodNotesReadResult } from "@/lib/api/decode/capabilities/goodnotes.read";
import { Card, CardBody } from "@/components/ui/card";

export function goodnotesRasterSrc(
  runId: string,
  pageVersionId: string,
  contentSha256: string,
): string {
  const params = new URLSearchParams({
    runId,
    pageVersionId,
    contentSha256,
  });
  return `/api/goodnotes/raster?${params.toString()}`;
}

/**
 * The admitted source raster. Bytes come from the BFF; this component never
 * invents them and does not keep a client copy.
 */
export function SourceRaster({
  record,
  contentSha256,
}: {
  record: GoodNotesReadResult;
  contentSha256: string;
}) {
  const src = goodnotesRasterSrc(record.run_id, record.page_version_id, contentSha256);
  const alt =
    `GoodNotes source raster (${record.media_type}); renderer ${record.renderer_name} ` +
    `${record.renderer_version}; page version ${record.page_version_id}; run ${record.run_id}`;

  return (
    <figure data-testid="goodnotes-source-raster">
      {/* Bytes are served by the BFF with no-store; Next Image would invent a cache. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className="max-w-full rounded border border-border" />
      <figcaption className="mt-2 text-xs text-muted">
        <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
          <dt>media type</dt>
          <dd>{record.media_type}</dd>
          <dt>renderer</dt>
          <dd>
            {record.renderer_name} {record.renderer_version}
          </dd>
          <dt>content sha256</dt>
          <dd className="font-mono break-all">{contentSha256}</dd>
        </dl>
      </figcaption>
    </figure>
  );
}

export function MissingRaster() {
  return (
    <Card data-testid="goodnotes-source-missing-digest">
      <CardBody>
        The source raster was not shown because contentSha256 is required and was not
        supplied on the query or by the read. No bytes were invented.
      </CardBody>
    </Card>
  );
}
