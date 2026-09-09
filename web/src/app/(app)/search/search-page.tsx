"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
import { mapUserError } from "@/lib/ui/user-error";
import {
  admittedEnrollmentId,
  fetchFederatedSearch,
  type FederatedSearchResponse,
} from "@/lib/search/client";
import {
  federatedZeroHitKind,
  formatCoverageRow,
  presentFederatedHits,
  presentSearchCoverage,
  searchCoverageHeadline,
  type PresentedGroup,
  type SearchCoverage,
} from "@/lib/search/presentation";
import type { ApiFailure } from "@/lib/api/work-client";

type SearchAnswer =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly result: FederatedSearchResponse }
  | { readonly kind: "not_implemented"; readonly error: unknown }
  | { readonly kind: "unavailable"; readonly error: unknown };

function isAbort(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

function classifyFailure(error: unknown): SearchAnswer {
  const failure = error as ApiFailure;
  if (failure.status === 501 || failure.code === "not_implemented") {
    return { kind: "not_implemented", error };
  }
  return { kind: "unavailable", error };
}

function heldEnrollment(explicit?: string): string | undefined {
  const fromProp = admittedEnrollmentId(explicit);
  if (fromProp) return fromProp;
  if (typeof window === "undefined") return undefined;
  return admittedEnrollmentId(new URLSearchParams(window.location.search).get("enrollmentId"));
}

function SearchCoverageSummary({
  coverage,
  limitations,
}: {
  coverage: readonly SearchCoverage[];
  limitations?: readonly string[];
}) {
  const summary = presentSearchCoverage(coverage);
  const rows = [...summary.searched, ...summary.unavailable, ...summary.limited, ...summary.omitted];
  return (
    <details data-testid="search-coverage" className="mt-4 text-sm">
      <summary className="cursor-pointer font-medium text-text-primary">
        {searchCoverageHeadline(coverage)}
      </summary>
      <ul className="mt-2 space-y-1 text-xs text-muted">
        {rows.map((row) => (
          <li
            key={`${row.domain}:${row.state}:${row.reason ?? ""}`}
            data-domain={row.domain}
            data-coverage-state={row.state}
          >
            {formatCoverageRow(row)}
          </li>
        ))}
      </ul>
      {limitations && limitations.length > 0 ? (
        <div className="mt-3" data-testid="search-coverage-limitations">
          <p className="font-medium text-text-primary">Limitations</p>
          <ul className="mt-1 list-inside list-disc text-xs text-muted">
            {limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </details>
  );
}

function HitGroups({ groups }: { groups: readonly PresentedGroup[] }) {
  return (
    <>
      {groups.map((group) => (
        <section key={group.domain} data-testid={`search-group-${group.domain}`} className="mb-4">
          <h2 className="pb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
            {group.heading}
          </h2>
          <ul className="space-y-1">
            {group.hits.map((hit) => (
              <li key={hit.key}>
                {hit.href ? (
                  <Link
                    href={hit.href}
                    className="flex min-h-11 w-full items-center rounded px-3 hover:bg-surface-subtle"
                  >
                    <span className="flex min-w-0 flex-1 flex-col items-start py-1">
                      <span className="flex w-full items-center justify-between gap-2">
                        <span>{hit.label}</span>
                        {group.domain === "knowledge" && hit.rank ? (
                          <Badge tone="neutral">{hit.rank}</Badge>
                        ) : null}
                      </span>
                      {hit.detail ? <span className="text-xs text-muted">{hit.detail}</span> : null}
                    </span>
                  </Link>
                ) : (
                  <div data-testid={`search-hit-${group.domain}-static`} className="rounded px-3 py-2">
                    <p className="text-sm">{hit.label}</p>
                    {group.domain === "knowledge" && hit.rank ? (
                      <Badge tone="neutral">{hit.rank}</Badge>
                    ) : null}
                    {hit.detail ? <p className="text-xs text-muted">{hit.detail}</p> : null}
                    <p className="mt-1 text-xs text-muted">No truthful address is available for this hit.</p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

export function SearchPage({
  initialQuery,
  enrollmentId,
}: {
  initialQuery: string;
  enrollmentId?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const [query, setQuery] = useState(initialQuery);
  const [fetched, setFetched] = useState<SearchAnswer>(
    initialQuery.trim() ? { kind: "loading" } : { kind: "idle" },
  );
  const enrollment = heldEnrollment(enrollmentId);
  const trimmed = query.trim();
  const idle = trimmed.length === 0;
  const answer = useMemo<SearchAnswer>(() => (idle ? { kind: "idle" } : fetched), [idle, fetched]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (idle) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setFetched({ kind: "loading" });
      void fetchFederatedSearch(trimmed, { enrollmentId: enrollment, signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted) setFetched({ kind: "ready", result });
        })
        .catch((error: unknown) => {
          if (isAbort(error) || controller.signal.aborted) return;
          setFetched(classifyFailure(error));
        });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, idle, enrollment]);

  const groups = useMemo<readonly PresentedGroup[]>(() => {
    if (answer.kind !== "ready") return [];
    return presentFederatedHits(answer.result.hits, enrollment);
  }, [answer, enrollment]);

  const zeroKind =
    answer.kind === "ready"
      ? federatedZeroHitKind(answer.result.coverage, answer.result.hits.length)
      : null;
  const unavailableError = answer.kind === "unavailable" ? mapUserError(answer.error) : null;

  return (
    <section className="mx-auto max-w-3xl">
      <PageHeader title="Search" description="Search tasks, people, notes, and reports." />
      <form
        role="search"
        action="/search"
        method="get"
        onSubmit={(event) => event.preventDefault()}
        className="mb-4"
      >
        <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-text-primary">
          Search
        </label>
        <Input
          ref={inputRef}
          id={inputId}
          name="q"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          autoFocus
          aria-describedby={`${inputId}-hint`}
          data-testid="search-page-input"
          placeholder="Search my-pa"
        />
        <p id={`${inputId}-hint`} className="mt-1 text-xs text-muted">
          Type to search. Destinations are in navigation.
        </p>
      </form>
      {idle ? (
        <p className="text-sm text-muted" data-testid="search-page-idle">
          Start typing to search.
        </p>
      ) : null}
      {answer.kind === "loading" ? <LoadingStatus label="Searching…" testId="search-page-loading" /> : null}
      {answer.kind === "not_implemented" ? (
        <SurfaceState
          kind="not_implemented"
          title="Search is not available in this build"
          error={answer.error}
          testId="search-not-implemented"
        />
      ) : null}
      {answer.kind === "unavailable" || zeroKind === "unavailable" ? (
        <SurfaceState
          kind="unavailable"
          title={unavailableError?.title ?? "Search could not be read"}
          error={answer.kind === "unavailable" ? answer.error : undefined}
          detail={
            answer.kind === "unavailable"
              ? undefined
              : "No domain could be searched. That is not a fact about what you hold."
          }
          limitations={answer.kind === "ready" ? answer.result.disclosure?.limitations : undefined}
          testId="search-unavailable"
        />
      ) : null}
      {zeroKind === "empty" && groups.length === 0 ? (
        <SurfaceState
          kind="empty"
          title="No matches in the domains that were searched"
          detail="Omitted and unavailable sources are listed in coverage."
          limitations={answer.kind === "ready" ? answer.result.disclosure?.limitations : undefined}
          testId="search-empty"
        />
      ) : null}
      {answer.kind === "ready" && zeroKind !== "unavailable" ? <HitGroups groups={groups} /> : null}
      {answer.kind === "ready" ? (
        <SearchCoverageSummary
          coverage={answer.result.coverage}
          limitations={answer.result.disclosure?.limitations}
        />
      ) : null}
    </section>
  );
}
