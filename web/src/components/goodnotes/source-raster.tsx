"use client";

import type { GoodNotesReadResult } from "@/lib/api/decode/capabilities/goodnotes.read";
import { Card, CardBody } from "@/components/ui/card";
import {
  WhenDiagnostics,
  useDiagnosticsEnabled,
} from "@/components/diagnostics/diagnostics-provider";

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
  const diagnosticsEnabled = useDiagnosticsEnabled();
  const src = goodnotesRasterSrc(record.run_id, record.page_version_id, contentSha256);
  /*
   * WP07 §8.7. Alternative text is accessibility output, and the contract
   * names it explicitly: a screen-reader user must not be the only person in
   * the product who is still told the renderer name, the renderer version, the
   * page version id and the run id while diagnostics are off. Gating the
   * `<figcaption>` alone would have done exactly that.
   *
   * What survives is the part that is actually *alternative text*: what this
   * image is. The identifiers are additive and return with diagnostics.
   */
  const alt = diagnosticsEnabled
    ? `GoodNotes source raster (${record.media_type}); renderer ${record.renderer_name} ` +
      `${record.renderer_version}; page version ${record.page_version_id}; run ${record.run_id}`
    : "Scanned GoodNotes page";

  return (
    <figure data-testid="goodnotes-source-raster">
      {/* Bytes are served by the BFF with no-store; Next Image would invent a cache. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className="max-w-full rounded border border-border" />
      <WhenDiagnostics>
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
      </WhenDiagnostics>
    </figure>
  );
}

export function MissingRaster() {
  return (
    <Card data-testid="goodnotes-source-missing-digest">
      <CardBody>
        {/* WP07: that nothing was shown and nothing was invented is the product
            truth. `contentSha256` is this application's own query-parameter
            name, so it is governed like every other internal field name. */}
        The source raster was not shown because this page was not given the digest that
        identifies it. No bytes were invented.
        <WhenDiagnostics>
          <span className="ml-1">
            `contentSha256` is required and was not supplied on the query or by the read.
          </span>
        </WhenDiagnostics>
      </CardBody>
    </Card>
  );
}
