"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type {
  ConstraintCategory,
  ConstraintListEntry,
  ConstraintListPage,
  ConstraintOverview,
} from "@/contracts/constraints";
import type { BackendProject } from "@/contracts/views";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { PageHeader } from "@/components/shell/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DegradedBanner, SurfaceState } from "@/components/ui/surface-state";
import { useInspectorContent, useInspectorSelection } from "@/components/shell/inspector-selection";
import {
  categoryRegisterState,
  constraintsHref,
  constraintsRoute,
  kpiRegisterState,
  parseConstraintUrlSearchParams,
  projectSwitchState,
  searchRegisterState,
  serializeConstraintUrlState,
  type ConstraintKpiTarget,
  type ConstraintUrlState,
} from "./constraint-url-state";
import {
  readCategories,
  readDetail,
  readHistory,
  readOverview,
  readProjects,
  readRegister,
  type LiveConstraintHistoryEntry,
  type LiveConstraintView,
  type LiveFailure,
} from "./constraint-live";
import { ConstraintsOverview } from "./constraints-overview";
import { ConstraintsRegister } from "./constraints-register";
import { ConstraintInspector, inspectorTitle } from "./constraint-inspector";
import { useConstraintViewport } from "./use-viewport";

interface Props {
  readonly projectId: string;
  readonly initialState: ConstraintUrlState;
}

const EMPTY_PAGE: ConstraintListPage = {
  entries: [],
  isTruncated: false,
  nextCursor: null,
  totalCount: null,
};

function LiveConstraintsWorkspaceInner({ projectId, initialState }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const viewport = useConstraintViewport();
  const { setSelection, shellSelection } = useInspectorSelection();
  const state = useMemo(
    () => (searchParams === null ? initialState : parseConstraintUrlSearchParams(searchParams)),
    [searchParams, initialState],
  );
  const queryKey = serializeConstraintUrlState({ ...state, selectedConstraintId: null });
  const generation = useRef(0);
  const historyGeneration = useRef(0);
  const historyPageController = useRef<AbortController | null>(null);
  const pendingRegisterFocus = useRef(false);
  const pendingProjectFocus = useRef(false);
  const pendingRowFocus = useRef<string | null>(null);
  const registerHeadingNode = useRef<HTMLHeadingElement | null>(null);

  const attachRegisterHeading = useCallback((node: HTMLHeadingElement | null) => {
    registerHeadingNode.current = node;
    if (node !== null && pendingRegisterFocus.current) {
      pendingRegisterFocus.current = false;
      node.focus();
    }
  }, []);

  const attachProjectSelector = useCallback((node: HTMLSelectElement | null) => {
    if (node !== null && pendingProjectFocus.current) {
      pendingProjectFocus.current = false;
      node.focus();
    }
  }, []);

  const attachRowTrigger = useCallback((constraintId: string, node: HTMLButtonElement | null) => {
    if (node !== null && pendingRowFocus.current === constraintId) {
      pendingRowFocus.current = null;
      node.focus();
    }
  }, []);

  const [projects, setProjects] = useState<readonly BackendProject[]>([]);
  const [overview, setOverview] = useState<ConstraintOverview | null>(null);
  const [overviewFailure, setOverviewFailure] = useState<LiveFailure | null>(null);
  const [overviewDisclosure, setOverviewDisclosure] = useState<DisclosureEnvelope | null>(null);
  const [categories, setCategories] = useState<readonly ConstraintCategory[]>([]);
  const [categoriesFailure, setCategoriesFailure] = useState<LiveFailure | null>(null);
  const [page, setPage] = useState<ConstraintListPage>(EMPTY_PAGE);
  const [registerLoading, setRegisterLoading] = useState(true);
  const [registerFailure, setRegisterFailure] = useState<LiveFailure | null>(null);
  const [registerDisclosure, setRegisterDisclosure] = useState<DisclosureEnvelope | null>(null);
  const [retry, setRetry] = useState(0);
  const [detail, setDetail] = useState<LiveConstraintView | null | undefined>(undefined);
  const [history, setHistory] = useState<readonly LiveConstraintHistoryEntry[] | undefined>(undefined);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyFailure, setHistoryFailure] = useState<string | null>(null);
  const summaryIdentity = `${projectId}\u0000${retry}`;
  const registerIdentity = `${projectId}\u0000${queryKey}\u0000${retry}`;
  const inspectorIdentity =
    state.selectedConstraintId === null
      ? null
      : `${projectId}\u0000${queryKey}\u0000${state.selectedConstraintId}`;
  const [summaryStateIdentity, setSummaryStateIdentity] = useState(summaryIdentity);
  const [registerStateIdentity, setRegisterStateIdentity] = useState(registerIdentity);
  const [inspectorStateIdentity, setInspectorStateIdentity] = useState<string | null>(
    inspectorIdentity,
  );

  // Effects abort obsolete work, while these identity gates prevent the previous
  // Project/query's state from surviving even the render before cleanup runs.
  const summaryStateIsCurrent = summaryStateIdentity === summaryIdentity;
  const registerStateIsCurrent = registerStateIdentity === registerIdentity;
  const inspectorStateIsCurrent = inspectorStateIdentity === inspectorIdentity;
  const visibleOverview = summaryStateIsCurrent ? overview : null;
  const visibleOverviewFailure = summaryStateIsCurrent ? overviewFailure : null;
  const visibleOverviewDisclosure = summaryStateIsCurrent ? overviewDisclosure : null;
  const visibleCategories = summaryStateIsCurrent ? categories : [];
  const visibleCategoriesFailure = summaryStateIsCurrent ? categoriesFailure : null;
  const visiblePage = registerStateIsCurrent ? page : EMPTY_PAGE;
  const visibleRegisterLoading = registerStateIsCurrent ? registerLoading : true;
  const visibleRegisterFailure = registerStateIsCurrent ? registerFailure : null;
  const visibleRegisterDisclosure = registerStateIsCurrent ? registerDisclosure : null;
  const visibleDetail = inspectorStateIsCurrent ? detail : undefined;
  const visibleHistory = inspectorStateIsCurrent ? history : undefined;
  const visibleHistoryCursor = inspectorStateIsCurrent ? historyCursor : null;
  const visibleHistoryLoading = inspectorStateIsCurrent
    ? historyLoading
    : state.selectedConstraintId !== null;
  const visibleHistoryFailure = inspectorStateIsCurrent ? historyFailure : null;

  const navigate = useCallback(
    (next: ConstraintUrlState, options?: { readonly replace?: boolean }) => {
      const href = constraintsHref(projectId, next);
      if (options?.replace) router.replace(href);
      else router.push(href);
    },
    [projectId, router],
  );

  useEffect(() => {
    if (!state.search.trim()) return;
    const canonical = searchRegisterState(state, state.search, { preserveSelection: true });
    if (serializeConstraintUrlState(canonical) !== serializeConstraintUrlState(state)) {
      router.replace(constraintsHref(projectId, canonical));
    }
  }, [projectId, router, state]);

  useEffect(() => {
    const controller = new AbortController();
    void readProjects(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) setProjects(result.value);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setSummaryStateIdentity(summaryIdentity);
      setOverview(null);
      setOverviewFailure(null);
      setOverviewDisclosure(null);
      setCategories([]);
      setCategoriesFailure(null);
    });
    void readOverview(projectId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setOverview(result.value);
        setOverviewDisclosure(result.disclosure);
      }
      else setOverviewFailure(result.error);
    });
    void readCategories(projectId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) setCategories(result.value.filter((item) => item.projectId === projectId));
      else setCategoriesFailure(result.error);
    });
    return () => controller.abort();
  }, [projectId, retry, summaryIdentity]);

  useEffect(() => {
    const controller = new AbortController();
    const current = ++generation.current;
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setRegisterStateIdentity(registerIdentity);
      setPage(EMPTY_PAGE);
      setRegisterLoading(true);
      setRegisterFailure(null);
      setRegisterDisclosure(null);
    });
    void readRegister(projectId, state, null, controller.signal).then((result) => {
      if (current !== generation.current) return;
      setRegisterLoading(false);
      if (!result.ok) {
        setRegisterFailure(result.error);
        return;
      }
      setPage(result.value);
      setRegisterDisclosure(result.disclosure);
    });
    return () => controller.abort();
    // queryKey deliberately excludes Inspector selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, queryKey, registerIdentity, retry]);

  const loadMore = useCallback(() => {
    if (!registerStateIsCurrent || !visiblePage.nextCursor || visibleRegisterLoading) return;
    const controller = new AbortController();
    const current = generation.current;
    setRegisterLoading(true);
    void readRegister(projectId, state, visiblePage.nextCursor, controller.signal).then((result) => {
      if (current !== generation.current) return;
      setRegisterLoading(false);
      if (!result.ok) {
        setRegisterFailure(result.error);
        return;
      }
      setPage((prior) => {
        const byId = new Map(prior.entries.map((item) => [item.constraintId, item]));
        for (const item of result.value.entries) byId.set(item.constraintId, item);
        return { ...result.value, entries: [...byId.values()] };
      });
      setRegisterDisclosure(result.disclosure);
    });
  }, [projectId, registerStateIsCurrent, state, visiblePage.nextCursor, visibleRegisterLoading]);

  const selected = useMemo(
    () =>
      visiblePage.entries.find((item) => item.constraintId === state.selectedConstraintId) ?? null,
    [state.selectedConstraintId, visiblePage.entries],
  );

  useEffect(() => {
    const id = state.selectedConstraintId;
    const current = ++historyGeneration.current;
    historyPageController.current?.abort();
    historyPageController.current = null;
    if (id === null) {
      void Promise.resolve().then(() => {
        if (current !== historyGeneration.current) return;
        setInspectorStateIdentity(inspectorIdentity);
        setDetail(undefined);
        setHistory(undefined);
        setHistoryCursor(null);
        setHistoryFailure(null);
      });
      return;
    }
    const detailController = new AbortController();
    const historyController = new AbortController();
    void Promise.resolve().then(() => {
      if (detailController.signal.aborted) return;
      setInspectorStateIdentity(inspectorIdentity);
      setDetail(undefined);
      setHistory(undefined);
      setHistoryCursor(null);
      setHistoryFailure(null);
      setHistoryLoading(true);
    });
    void readDetail(projectId, id, detailController.signal).then((result) => {
      if (detailController.signal.aborted || current !== historyGeneration.current) return;
      setDetail(result.ok ? result.value : null);
    });
    void readHistory(projectId, id, null, historyController.signal).then((result) => {
      if (historyController.signal.aborted || current !== historyGeneration.current) return;
      setHistoryLoading(false);
      if (result.ok) {
        setHistory(result.value.entries);
        setHistoryCursor(result.value.nextCursor);
      } else {
        setHistoryFailure(result.error.message);
      }
    });
    return () => {
      detailController.abort();
      historyController.abort();
      historyPageController.current?.abort();
      historyPageController.current = null;
    };
  }, [inspectorIdentity, projectId, state.selectedConstraintId]);

  const loadMoreHistory = useCallback(() => {
    const id = state.selectedConstraintId;
    if (!id || !historyCursor || historyLoading) return;
    historyPageController.current?.abort();
    const controller = new AbortController();
    historyPageController.current = controller;
    const current = historyGeneration.current;
    setHistoryLoading(true);
    setHistoryFailure(null);
    void readHistory(projectId, id, historyCursor, controller.signal).then((result) => {
      if (controller.signal.aborted || current !== historyGeneration.current) return;
      if (historyPageController.current === controller) historyPageController.current = null;
      setHistoryLoading(false);
      if (!result.ok) {
        setHistoryFailure(result.error.message);
        return;
      }
      setHistory((prior) => {
        const byId = new Map((prior ?? []).map((item) => [item.historyId, item]));
        for (const item of result.value.entries) byId.set(item.historyId, item);
        return [...byId.values()];
      });
      setHistoryFailure(null);
      setHistoryCursor(result.value.nextCursor);
    });
  }, [historyCursor, historyLoading, projectId, state.selectedConstraintId]);

  useEffect(() => {
    const id = state.selectedConstraintId;
    if (id === null) {
      if (shellSelection?.kind === "constraint") setSelection(null);
    } else if (shellSelection?.kind !== "constraint" || shellSelection.constraintId !== id) {
      setSelection({ kind: "constraint", constraintId: id, projectId });
    }
  }, [projectId, setSelection, shellSelection, state.selectedConstraintId]);

  const closeDetail = useCallback(() => {
    const id = state.selectedConstraintId;
    const rowIsLoaded =
      id !== null &&
      registerStateIsCurrent &&
      visiblePage.entries.some((entry) => entry.constraintId === id);
    pendingRowFocus.current = rowIsLoaded ? id : null;
    navigate({ ...state, selectedConstraintId: null });
    if (!rowIsLoaded) {
      pendingRegisterFocus.current = true;
      const heading = registerHeadingNode.current;
      if (heading !== null) {
        pendingRegisterFocus.current = false;
        heading.focus();
      }
    }
  }, [navigate, registerStateIsCurrent, state, visiblePage.entries]);

  const selectConstraint = useCallback(
    (constraintId: string) => navigate({ ...state, view: "register", selectedConstraintId: constraintId }),
    [navigate, state],
  );

  const inspectorRender = useCallback(
    () => (
      <ConstraintInspector
        entry={selected}
        detail={visibleDetail}
        history={visibleHistory}
        historyLoading={visibleHistoryLoading}
        historyFailure={visibleHistoryFailure}
        historyNextCursor={visibleHistoryCursor}
        selectedConstraintId={state.selectedConstraintId}
        onLoadMoreHistory={loadMoreHistory}
        onClose={closeDetail}
        onNavigateToConstraint={selectConstraint}
        onLifecycleAction={() => undefined}
        readOnly
      />
    ),
    [
      closeDetail,
      visibleDetail,
      visibleHistory,
      visibleHistoryCursor,
      visibleHistoryFailure,
      visibleHistoryLoading,
      loadMoreHistory,
      selectConstraint,
      selected,
      state.selectedConstraintId,
    ],
  );

  useInspectorContent("constraint", {
    title: inspectorTitle(selected ?? visibleDetail ?? null),
    render: inspectorRender,
  });

  const partyOptions = useMemo(() => {
    const values = new Map<string, ConstraintListEntry["bic"][number]>();
    for (const item of visiblePage.entries) {
      for (const party of [...item.bic, ...item.responsible]) {
        if (party.partyRefId) values.set(party.partyRefId, party);
      }
    }
    return [...values.values()];
  }, [visiblePage.entries]);

  function toRegister(target: ConstraintKpiTarget) {
    pendingRegisterFocus.current = true;
    navigate(kpiRegisterState(state, target));
  }

  const projectName = projects.find((item) => item.projectId === projectId)?.name ?? projectId;

  return (
    <div
      className="grid gap-4 [&_tr[data-selected]]:bg-surface [&_tr[data-selected]]:shadow-[inset_3px_0_0_var(--interactive)]"
      data-testid="constraints-live-workspace"
    >
      <PageHeader title="Constraints" description={`Project Controls · ${projectName}`} />
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="project-context">
        <Badge tone="neutral">Project {projectId}</Badge>
        <Badge tone="green">Live read plane</Badge>
        <label className="ml-auto flex items-center gap-1">
          <span className="text-muted">Project</span>
          <Select
            key={projectId}
            ref={attachProjectSelector}
            value={projectId}
            data-testid="project-selector"
            onChange={(event) => {
              pendingProjectFocus.current = true;
              const next = projectSwitchState(state);
              const query = serializeConstraintUrlState(next);
              const base = constraintsRoute(event.target.value);
              router.push(query ? `${base}?${query}` : base);
            }}
          >
            {projects.length === 0 ? <option value={projectId}>{projectName}</option> : null}
            {projects.map((project) => <option key={project.projectId} value={project.projectId}>{project.name}</option>)}
          </Select>
        </label>
      </div>
      <Tabs value={state.view} onValueChange={(view: string) => navigate({ ...state, view: view as ConstraintUrlState["view"] })}>
        <TabsList aria-label="Constraint workspace">
          <TabsTrigger value="overview" data-testid="tab-overview">Overview</TabsTrigger>
          <TabsTrigger value="register" data-testid="tab-register">Register</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="mt-4">
          {visibleOverviewFailure ? (
            <SurfaceState kind="unavailable" title="Constraint Overview could not be read" detail={visibleOverviewFailure.message} testId="overview-unavailable">
              <Button size="sm" variant="secondary" onClick={() => setRetry((value) => value + 1)}>Retry</Button>
            </SurfaceState>
          ) : visibleOverview === null ? (
            <p role="status" className="text-sm text-muted" data-testid="overview-loading">Reading the Constraint Overview…</p>
          ) : (
            <>
            {visibleOverviewDisclosure?.coverage === "partial" ? <DegradedBanner scope="Constraint Overview" limitations={visibleOverviewDisclosure.limitations} truncated={visibleOverviewDisclosure.truncated} /> : null}
            <ConstraintsOverview
              overview={visibleOverview}
              categoryOpenCounts={[]}
              oldestOpen={[]}
              categories={visibleCategories}
              state={state}
              onKpiNavigate={toRegister}
              onCategoryNavigate={(categoryId) => navigate(categoryRegisterState(state, categoryId))}
              onSelect={selectConstraint}
            />
            </>
          )}
          {visibleCategoriesFailure ? <p role="alert" className="mt-2 text-sm text-moss-coral-strong">Categories could not be read: {visibleCategoriesFailure.message}</p> : null}
        </TabsContent>
        <TabsContent value="register" className="mt-4">
          <h2 ref={attachRegisterHeading} tabIndex={-1} className="sr-only" data-testid="register-heading">Register</h2>
          <ConstraintsRegister
            projectId={projectId}
            entries={[]}
            categories={visibleCategories}
            partyOptions={partyOptions}
            state={state}
            viewport={viewport}
            onStateChange={navigate}
            onSelect={selectConstraint}
            onTriggerMount={attachRowTrigger}
            livePage={visiblePage}
            loading={visibleRegisterLoading}
            failure={visibleRegisterFailure}
            disclosure={visibleRegisterDisclosure}
            onRetry={() => setRetry((value) => value + 1)}
            onLoadMore={loadMore}
            readOnly
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export function LiveConstraintsWorkspace(props: Props) {
  return <Suspense fallback={<p className="text-sm text-muted">Loading the Constraint workspace…</p>}><LiveConstraintsWorkspaceInner {...props} /></Suspense>;
}
