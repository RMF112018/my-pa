/**
 * Review — the Principal's own consequential proposal cases, from the backend.
 *
 * **What this page did until now.** It called `syntheticReviewCases` with no
 * provider check at all. In a default build that is not a page that shows
 * fixtures — `lib/fixtures/gate.ts` throws — it is a page that raises an
 * unhandled error, so the one destination whose entire purpose is *deciding*
 * was unreachable while `/api/review` and `/api/review/:id/decide` had both been
 * wired to `review.list` and `review.decide` since WP-11. This page now reaches
 * the same capability directly, exactly as `today` and `situations` do.
 *
 * The four answers are the four `lib/api/surface-answer.ts` decides between, and
 * the distinction that matters most here is the one between **empty** and
 * **unavailable**: an empty review queue means "nothing is waiting on you", and
 * showing that sentence because the gateway was unreachable would tell someone
 * their queue is clear when it may be full.
 *
 * **The synthetic branch is still available and still explicit.** It requires
 * `MYPA_DATA_PROVIDER=synthetic`, renders the fixture workbench, and is never a
 * fallback from a failed backend call — the two switches stay separate for the
 * reason `lib/api/serving.ts` sets out.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { syntheticReviewCases } from "@/lib/fixtures/review";
import { invokeGateway, type GatewayOutcome } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { ReviewWorkbench } from "@/components/review/review-workbench";
import { BackendReviewWorkbench } from "@/components/review/backend-review-workbench";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import type { ReviewCase } from "@/lib/api/decode/capabilities/review.list";
import type { ReviewListResult } from "@/lib/api/decode/capabilities/review.list";
import type { BackendReviewCase } from "@/contracts/views";

export const metadata = { title: "Review — my-pa" };

/** A review queue read at request time, never a cached one. */
export const dynamic = "force-dynamic";

const SCOPE = "review";

const BLURB =
  "Proposals wait here for your disposition. Nothing is asserted on your behalf — a captured " +
  "item becomes a canonical record only when you accept or correct-and-accept it.";

function toCase(row: ReviewCase): BackendReviewCase {
  const captureId = row.subject_kind === "capture_proposal" ? row.capture_id : row.review_case_id;
  const versionId = row.subject_kind === "capture_proposal" ? row.version_id : row.proposal_id;
  const proposalType =
    row.subject_kind === "capture_proposal" ? row.proposal_type : row.subject_kind;
  return {
    reviewCaseId: row.review_case_id,
    proposalId: row.proposal_id,
    captureId,
    versionId,
    proposalType,
    proposalState: row.proposal_state,
    riskClass: row.risk_class,
    openedAt: row.opened_at,
    reviewVersion: row.review_version,
    latestDisposition: row.latest_disposition,
  };
}

export default async function ReviewPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <>
      <h1 id="review-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Review
      </h1>
      <p className="mb-4 text-sm text-muted">{BLURB}</p>
    </>
  );

  const frame = (children: React.ReactNode) => (
    <section aria-labelledby="review-heading" className="mx-auto max-w-2xl">
      {heading}
      {children}
    </section>
  );

  if (syntheticDataEnabled()) {
    return frame(
      <>
        <p className="mb-3 text-sm text-muted">
          This build is serving the synthetic provider. Every case below is a principal-scoped
          fixture and no decision made on it is stored.
        </p>
        <ReviewWorkbench cases={syntheticReviewCases(principal)} />
      </>,
    );
  }

  const answer = surfaceAnswer(
    `${SCOPE}:review.list`,
    (await invokeGateway(principal, "review.list")) as GatewayOutcome<ReviewListResult>,
    (result) => result.review_cases.length,
  );

  if (answer.kind === "unavailable") {
    return frame(
      <SurfaceState
        kind="unavailable"
        title="Your review queue could not be read"
        detail={answer.error.message}
        limitations={answer.disclosure.limitations}
        testId="review-queue-unavailable"
      />,
    );
  }

  if (answer.kind === "empty") {
    return frame(
      <SurfaceState
        kind="empty"
        title="Nothing is waiting on your decision"
        detail={
          "The review queue was read and it holds no open case. Proposals appear here when a " +
          "capture derives something consequential enough to need you."
        }
        testId="review-queue-empty"
      />,
    );
  }

  if (answer.kind === "degraded") {
    return frame(
      <>
        <DegradedBanner
          scope="this review queue"
          limitations={answer.disclosure.limitations}
          truncated={answer.disclosure.truncated}
        />
        {answer.rowCount === 0 ? (
          <SurfaceState
            kind="degraded"
            title="The queue was read incompletely and returned nothing"
            detail={
              "An empty queue is not established by an incomplete read. Cases may be waiting " +
              "that this answer did not cover."
            }
            testId="review-queue-degraded-empty"
          />
        ) : (
          <BackendReviewWorkbench cases={answer.result.review_cases.map(toCase)} />
        )}
      </>,
    );
  }

  return frame(
    <BackendReviewWorkbench cases={answer.result.review_cases.map(toCase)} />,
  );
}
