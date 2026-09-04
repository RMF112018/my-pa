/**
 * Compact Morning Intelligence pulse for Today. Not a second Intelligence screen.
 *
 * READY is specialist coverage for morning_brief_inputs, never "system healthy".
 * An unavailable list is unavailable, not all-clear. An empty list is "no
 * artifact", not an error and not all-clear.
 */
import Link from "next/link";
import { invokeGateway, type GatewayOutcome } from "@/lib/api/gateway";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LiveAnnouncement } from "@/components/ui/live-region";
import type { PrincipalSession } from "@/contracts/identity";
import type { ReportsListResult } from "@/lib/api/decode/capabilities/reports.list";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import {
  currentCycleRunId,
  nonReadyRequiredCount,
  resolveSetPayload,
} from "@/components/intelligence/cycle-selection";
import { readinessAnswerFromOutcome } from "@/components/intelligence/readiness-load";
import { intelligenceHome } from "@/lib/routes/intelligence";

const AGGREGATE_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  READY: "green",
  DEGRADED: "gold",
  BLOCKED: "coral",
};

export async function IntelligencePulse({
  principal,
}: {
  readonly principal: PrincipalSession;
}) {
  const listAnswer = surfaceAnswer(
    "today:intelligence:reports.list",
    (await invokeGateway(principal, "reports.list")) as GatewayOutcome<ReportsListResult>,
    (result) => result.items.length,
  );

  if (listAnswer.kind === "unavailable") {
    return (
      <Card className="mt-6" data-testid="intelligence-pulse" data-state="unavailable">
        <CardTitle>Morning Intelligence</CardTitle>
        <CardBody>
          <LiveAnnouncement tone="alert" testId="intelligence-pulse-unavailable">
            Morning Intelligence could not be read. That is not all-clear.
          </LiveAnnouncement>
          <p className="mt-2 text-xs">{listAnswer.error.message}</p>
          <Link
            href={intelligenceHome()}
            className="mt-2 inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
          >
            Open Intelligence
          </Link>
        </CardBody>
      </Card>
    );
  }

  if (listAnswer.kind === "empty") {
    return (
      <Card className="mt-6" data-testid="intelligence-pulse" data-state="empty">
        <CardTitle>Morning Intelligence</CardTitle>
        <CardBody>
          <p data-testid="intelligence-pulse-none" role="status">
            No Morning Intelligence artifact. That is not all-clear and not a Pulse error.
          </p>
          <Link
            href={intelligenceHome()}
            className="mt-2 inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
          >
            Open Intelligence
          </Link>
        </CardBody>
      </Card>
    );
  }

  if (listAnswer.kind === "degraded" && listAnswer.rowCount === 0) {
    return (
      <Card className="mt-6" data-testid="intelligence-pulse" data-state="degraded">
        <CardTitle>Morning Intelligence</CardTitle>
        <CardBody>
          <LiveAnnouncement tone="status" testId="intelligence-pulse-degraded">
            The report plane was read incompletely and returned nothing. That is not all-clear.
          </LiveAnnouncement>
          <Link
            href={intelligenceHome()}
            className="mt-2 inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
          >
            Open Intelligence
          </Link>
        </CardBody>
      </Card>
    );
  }

  const items = listAnswer.result.items;
  const cycleRunId = currentCycleRunId(items);
  if (cycleRunId === null) {
    return (
      <Card className="mt-6" data-testid="intelligence-pulse" data-state="empty">
        <CardTitle>Morning Intelligence</CardTitle>
        <CardBody>
          <p data-testid="intelligence-pulse-none" role="status">
            No Morning Intelligence artifact. That is not all-clear and not a Pulse error.
          </p>
        </CardBody>
      </Card>
    );
  }

  const readinessAnswer = readinessAnswerFromOutcome(
    "today:intelligence:reports.resolve_set",
    (await invokeGateway(
      principal,
      "reports.resolve_set",
      resolveSetPayload(cycleRunId),
    )) as GatewayOutcome<ReportsResolveSetResult>,
  );

  if (readinessAnswer.kind === "unavailable") {
    return (
      <Card className="mt-6" data-testid="intelligence-pulse" data-state="unavailable">
        <CardTitle>Morning Intelligence</CardTitle>
        <CardBody>
          <LiveAnnouncement tone="alert" testId="intelligence-pulse-unavailable">
            Specialist readiness could not be read for cycle {cycleRunId}. Listed artifacts are not
            all-clear.
          </LiveAnnouncement>
          <Link
            href={intelligenceHome()}
            className="mt-2 inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
          >
            Open Intelligence
          </Link>
        </CardBody>
      </Card>
    );
  }

  const readiness = readinessAnswer.result;
  const missing = nonReadyRequiredCount(readiness.members);
  const allClearForbidden = readiness.aggregate !== "READY" || missing > 0;
  const tone = AGGREGATE_TONE[readiness.aggregate] ?? "neutral";

  return (
    <Card className="mt-6" data-testid="intelligence-pulse" data-state={readiness.aggregate.toLowerCase()}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <CardTitle>Morning Intelligence</CardTitle>
        <Badge tone={tone}>{readiness.aggregate}</Badge>
      </div>
      <CardBody>
        <p data-testid="intelligence-pulse-summary" role="status">
          Business date {readiness.business_date}. Specialist coverage {readiness.aggregate}
          {allClearForbidden
            ? ` — ${missing} required member${missing === 1 ? " is" : "s are"} not READY. Not all-clear.`
            : " — Brief/specialist coverage ready, not system healthy."}
        </p>
        <Link
          href={intelligenceHome()}
          className="mt-2 inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
        >
          Open Intelligence
        </Link>
      </CardBody>
    </Card>
  );
}
