"use client";

/**
 * The portfolio's own live, row-level, cross-Project Constraint Register.
 *
 * Corrective to R02-WP10 Phases 5-6: the controlling plan (§6.1/§6.2) asks for
 * "one shared/adapted workspace rather than a parallel product", reusing
 * `ConstraintsRegister`/`RegisterTable` — not a per-Project card launcher.
 * This is that adaptation: a thin client wrapper around the exact-Project
 * Register's own components, reading `constraints.portfolio_list`/
 * `portfolio_search` (`readPortfolioRegister`) instead of the exact-Project
 * read, and never mounting Category filter/administration (`portfolioScope`
 * on `ConstraintsRegister` — Categories are Project-owned vocabulary with no
 * cross-Project meaning).
 *
 * **Row open navigates/binds the exact Project and Constraint.** There is no
 * Inspector on this page — selecting a row is a real navigation to that
 * Constraint's own canonical route (`constraintsRoute(projectId)` plus the
 * exact-Project Register's own `selectedConstraintId` URL-state, reused
 * unchanged), which is where the Inspector, authoring and lifecycle actions
 * already live. This file invents no second selection mechanism.
 *
 * **View state here is local, not URL-synced.** The exact-Project Register's
 * `constraint-url-state.ts` module is a *Project-scoped* route's own URL
 * vocabulary (`constraintsRoute(projectId)` is a path segment); this route has
 * no Project segment to carry that vocabulary in, and inventing a second,
 * portfolio-shaped URL-state module was judged out of this corrective's scope
 * (disclosed in the handoff). Filters/sort/grouping reset on navigation away
 * and back, exactly as any unbookmarked local UI state would.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { ConstraintListEntry, ConstraintListPage, ConstraintPartyRef } from "@/contracts/constraints";
import {
  DEFAULT_CONSTRAINT_URL_STATE,
  constraintsHref,
  type ConstraintUrlState,
} from "@/app/(app)/work/projects/[projectId]/constraints/constraint-url-state";
import {
  readPortfolioRegister,
  type LiveFailure,
} from "@/app/(app)/work/projects/[projectId]/constraints/constraint-live";
import { ConstraintsRegister } from "@/app/(app)/work/projects/[projectId]/constraints/constraints-register";
import { useConstraintViewport } from "@/app/(app)/work/projects/[projectId]/constraints/use-viewport";

const PORTFOLIO_DEFAULT_STATE: ConstraintUrlState = {
  ...DEFAULT_CONSTRAINT_URL_STATE,
  // "Category" is not offered as a grouping in portfolio scope either — see
  // `ConstraintsRegister`'s own `portfolioScope` — so the default never
  // starts on the one grouping this page cannot honour.
  group: "none",
};

const EMPTY_PAGE: ConstraintListPage = { entries: [], isTruncated: false, nextCursor: null, totalCount: null };

export function PortfolioConstraintsRegister() {
  const router = useRouter();
  const viewport = useConstraintViewport();
  const [state, setState] = useState<ConstraintUrlState>(PORTFOLIO_DEFAULT_STATE);
  const [entries, setEntries] = useState<readonly ConstraintListEntry[]>([]);
  const [isTruncated, setIsTruncated] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [omittedProjects, setOmittedProjects] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<LiveFailure | null>(null);
  const [retry, setRetry] = useState(0);

  const queryKey = JSON.stringify({ state: { ...state, selectedConstraintId: null }, retry });

  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setEntries([]);
      setIsTruncated(false);
      setNextCursor(null);
      setLoading(true);
      setFailure(null);
    });
    void readPortfolioRegister(state, null, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setLoading(false);
      if (!result.ok) {
        setFailure(result.error);
        return;
      }
      setEntries(result.value.entries);
      setIsTruncated(result.value.isTruncated);
      setNextCursor(result.value.nextCursor);
      setOmittedProjects(result.value.omittedProjects);
    });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  const loadMore = useCallback(() => {
    if (!nextCursor || loading) return;
    const controller = new AbortController();
    setLoading(true);
    void readPortfolioRegister(state, nextCursor, controller.signal).then((result) => {
      setLoading(false);
      if (!result.ok) {
        setFailure(result.error);
        return;
      }
      setEntries((prior) => {
        const byId = new Map(prior.map((item) => [item.constraintId, item]));
        for (const item of result.value.entries) byId.set(item.constraintId, item);
        return [...byId.values()];
      });
      setIsTruncated(result.value.isTruncated);
      setNextCursor(result.value.nextCursor);
      setOmittedProjects(result.value.omittedProjects);
    });
  }, [nextCursor, loading, state]);

  const partyOptions = useMemo(() => {
    const values = new Map<string, ConstraintPartyRef>();
    for (const item of entries) {
      for (const party of [...item.bic, ...item.responsible]) {
        if (party.partyRefId) values.set(party.partyRefId, party);
      }
    }
    return [...values.values()];
  }, [entries]);

  const livePage: ConstraintListPage = { entries, isTruncated, nextCursor, totalCount: null };

  const handleSelect = useCallback(
    (constraintId: string) => {
      const entry = entries.find((item) => item.constraintId === constraintId);
      if (!entry || entry.projectId === null) return;
      router.push(
        constraintsHref(entry.projectId, {
          ...DEFAULT_CONSTRAINT_URL_STATE,
          view: "register",
          selectedConstraintId: constraintId,
        }),
      );
    },
    [entries, router],
  );

  return (
    <div className="grid gap-3">
      {omittedProjects > 0 ? (
        <p className="text-sm text-muted" data-testid="portfolio-register-omitted-projects">
          {omittedProjects} owned Project{omittedProjects === 1 ? "" : "s"} could not be counted for
          this read and {omittedProjects === 1 ? "is" : "are"} not reflected in these rows.
        </p>
      ) : null}
      <ConstraintsRegister
        entries={[]}
        categories={[]}
        partyOptions={partyOptions}
        state={state}
        viewport={viewport}
        onStateChange={setState}
        onSelect={handleSelect}
        livePage={loading || failure ? EMPTY_PAGE : livePage}
        loading={loading}
        failure={failure}
        onRetry={() => setRetry((value) => value + 1)}
        onLoadMore={loadMore}
        portfolioScope
      />
    </div>
  );
}
