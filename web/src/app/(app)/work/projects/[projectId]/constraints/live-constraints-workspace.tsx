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
  detailToListEntry,
  mintIdempotencyKey,
  readCategories,
  readDetail,
  readHistory,
  readOverview,
  readProjects,
  readRegister,
  transitionConstraint,
  updateConstraint,
  type LiveConstraintHistoryEntry,
  type LiveConstraintView,
  type LiveFailure,
  type LiveMutationFailure,
} from "./constraint-live";
import { ConstraintsOverview } from "./constraints-overview";
import { ConstraintsRegister } from "./constraints-register";
import { ConstraintInspector, inspectorTitle, type ConstraintLifecycleAction } from "./constraint-inspector";
import { useConstraintViewport } from "./use-viewport";
import { safeDiagnostic, safeLimitations } from "@/lib/diagnostics/safe-detail";
import { useConstraintRuntime } from "@/components/project-controls/constraint-runtime-provider";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import { constraintLockKey } from "@/lib/constraint/mutation-coordinator";
import { ConstraintAuthoring } from "./constraint-authoring";
import { ConstraintDirectActions, type DirectAction } from "./constraint-direct-actions";
import { ConstraintCategoryAdmin } from "./constraint-category-admin";
import type { InlineEditRequest, InlineEditResult } from "./register-table";
import {
  useForegroundRevalidation,
  type ForegroundQuerySnapshot,
  type ForegroundReadCoordinator,
  type ForegroundReadResult,
} from "@/lib/task/use-foreground-revalidation";

interface Props {
  readonly projectId: string;
  readonly initialState: ConstraintUrlState;
}

/** `useForegroundRevalidation`'s own read-result shape, for this surface's revalidation. */
interface ConstraintForegroundResult extends ForegroundReadResult {
  readonly outcome: "applied" | "failed";
  readonly error?: LiveFailure;
}

interface ConstraintForegroundEntry {
  freshness: ForegroundQuerySnapshot<void>["freshness"];
  lastSuccessfulAt: number | null;
  readonly listeners: Set<(snapshot: ForegroundQuerySnapshot<void>) => void>;
}

/**
 * The smallest coordinator that satisfies `useForegroundRevalidation`'s seam
 * for this surface (`[PC-CM-UX-AC-018]`) — the repository's one shared
 * foreground-freshness policy (5s cadence; immediate on focus, visibility,
 * online; suspended while hidden/offline; 5→10→30s backoff; 401/403 suspend),
 * reused exactly as Task/Today/Pulse already do, never a second one authored
 * here. Unlike `PulseReadCoordinator` (`today-pulse-surface.tsx`), this
 * coordinator holds no confirmed payload and does no in-flight dedupe of its
 * own: this file's own `readRegister`/`readOverview`/`readCategories` effects
 * already own de-duplication, abort and ordering for the data itself (their
 * own `generation`/identity-gate state, unchanged by this fix) — the one
 * thing missing was ever being asked to run again on focus/visibility/online
 * at all. This coordinator exists only to satisfy the hook's structural seam
 * and track the freshness/backoff bookkeeping the hook itself needs; the
 * actual re-read and state application happens in `revalidateConstraints`
 * below, which is this surface's own `fetcher`.
 */
class ConstraintForegroundCoordinator
  implements
    ForegroundReadCoordinator<
      void,
      string,
      () => Promise<ConstraintForegroundResult>,
      ConstraintForegroundResult,
      ForegroundQuerySnapshot<void>
    >
{
  private readonly entries = new Map<string, ConstraintForegroundEntry>();

  private ensure(key: string): ConstraintForegroundEntry {
    const existing = this.entries.get(key);
    if (existing) return existing;
    const created: ConstraintForegroundEntry = { freshness: "idle", lastSuccessfulAt: null, listeners: new Set() };
    this.entries.set(key, created);
    return created;
  }

  private snapshot(entry: ConstraintForegroundEntry): ForegroundQuerySnapshot<void> {
    return { freshness: entry.freshness, lastConfirmed: undefined, lastSuccessfulAt: entry.lastSuccessfulAt };
  }

  private emit(entry: ConstraintForegroundEntry): void {
    const snapshot = this.snapshot(entry);
    for (const listener of Array.from(entry.listeners)) listener(snapshot);
  }

  retain(key: string): ForegroundQuerySnapshot<void> {
    return this.snapshot(this.ensure(key));
  }

  release(): void {
    // Nothing owned per-subscriber; entries are cheap and keyed by query
    // identity, which already changes (and is naturally abandoned) on
    // Project/query switch.
  }

  subscribe(key: string, listener: (snapshot: ForegroundQuerySnapshot<void>) => void): () => void {
    const entry = this.ensure(key);
    entry.listeners.add(listener);
    listener(this.snapshot(entry));
    return () => {
      entry.listeners.delete(listener);
    };
  }

  getSnapshot(key: string): ForegroundQuerySnapshot<void> | undefined {
    const entry = this.entries.get(key);
    return entry ? this.snapshot(entry) : undefined;
  }

  async read(key: string, fetcher: () => Promise<ConstraintForegroundResult>): Promise<ConstraintForegroundResult> {
    const entry = this.ensure(key);
    entry.freshness = "loading";
    this.emit(entry);
    const result = await fetcher();
    entry.freshness = result.outcome === "applied" ? "fresh" : "stale";
    if (result.outcome === "applied") entry.lastSuccessfulAt = Date.now();
    this.emit(entry);
    return result;
  }

  markFresh(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "fresh";
    this.emit(entry);
  }

  markStale(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "stale";
    this.emit(entry);
  }

  markSuspended(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "suspended";
    this.emit(entry);
  }

  applyConfirmed(key: string): ForegroundQuerySnapshot<void> {
    // Never called here: this surface's mutation confirmations already go
    // through `refreshAfterMutation`, unrelated to foreground revalidation.
    return this.snapshot(this.ensure(key));
  }

  raiseMutationBarrier(): number {
    return 0;
  }
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
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  const [authoring, setAuthoring] = useState<{ readonly mode: "create" | "edit" } | null>(null);
  // [PC-CM-UX-AC-020] `authoringKey` bumps only when the authoring dialog is
  // *opened* (`openAuthoring` below), never when it closes. A genuinely new
  // session (a different record, or a fresh "New Constraint") still gets a
  // clean remount (form state can never carry over, unchanged from before),
  // but *closing* no longer remounts the component immediately.
  //
  // Closing used to unmount `<ConstraintAuthoring>` in the very same render
  // that cleared `authoring` (`{authoring ? <.../> : null}`), tearing the
  // still-open native `<dialog>` element out of the DOM without ever calling
  // `.close()` on it — `ui/dialog.tsx`'s own close effect never got the
  // chance to run, since React had already discarded the fiber — so the
  // browser's built-in invoker-focus-restore, which fires only as part of an
  // actual `.close()` call, never ran either, stranding focus on
  // `document.body`. Confirmed reproducible via two independent close paths
  // (a completed mutation, and a plain Escape with no mutation at all).
  //
  // The fix keeps the *identity* stable across a close (so `Dialog`'s own
  // effect sees a real `open: true → false` transition on a still-attached
  // node and calls the real `.close()`), but still removes the node from the
  // DOM once closed — not by unmounting in the same render, but one tick
  // later, via `authoringMounted`. `closeAuthoring` clears `authoring`
  // (`open` flips to `false`, `Dialog`'s effect runs synchronously and calls
  // `dialog.close()` — the browser's own focus restoration is itself
  // synchronous, completing inside that same call) and defers
  // `setAuthoringMounted(false)` to the next macrotask, strictly after that
  // effect has already run. This keeps `register-new-constraint`'s own node
  // identity stable through the transition (fixing the focus bug) while
  // still leaving the DOM exactly as every existing close-time assertion —
  // this component's own tests, and `project-controls-run02.spec.ts`'s own
  // `createPublishedConstraint()` helper's `toHaveCount(0)` — already
  // expect: gone shortly after close, not merely hidden forever.
  const [authoringKey, setAuthoringKey] = useState(0);
  const [authoringMounted, setAuthoringMounted] = useState(false);
  const authoringUnmountTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openAuthoring = useCallback((mode: "create" | "edit") => {
    if (authoringUnmountTimer.current !== null) {
      clearTimeout(authoringUnmountTimer.current);
      authoringUnmountTimer.current = null;
    }
    setAuthoringKey((key) => key + 1);
    setAuthoringMounted(true);
    setAuthoring({ mode });
  }, []);
  const closeAuthoring = useCallback(() => {
    setAuthoring(null);
    if (authoringUnmountTimer.current !== null) clearTimeout(authoringUnmountTimer.current);
    authoringUnmountTimer.current = setTimeout(() => {
      authoringUnmountTimer.current = null;
      setAuthoringMounted(false);
    }, 0);
  }, []);
  useEffect(
    () => () => {
      if (authoringUnmountTimer.current !== null) clearTimeout(authoringUnmountTimer.current);
    },
    [],
  );
  const [directAction, setDirectAction] = useState<DirectAction | null>(null);
  const [categoriesOpen, setCategoriesOpen] = useState(false);
  const state = useMemo(
    () => (searchParams === null ? initialState : parseConstraintUrlSearchParams(searchParams)),
    [searchParams, initialState],
  );
  const queryKey = serializeConstraintUrlState({ ...state, selectedConstraintId: null });
  const generation = useRef(0);
  // Shared with `revalidateConstraints` below (`[PC-CM-UX-AC-018]`) so a
  // background foreground-revalidation read and *this* effect's own
  // identity/retry-triggered read can never race each other: whichever one
  // most recently bumped this counter is the only one allowed to apply its
  // result to `overview`/`categories`, regardless of which one's network
  // response actually resolves first.
  const summaryGeneration = useRef(0);
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
    const current = ++summaryGeneration.current;
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
      if (controller.signal.aborted || current !== summaryGeneration.current) return;
      if (result.ok) {
        setOverview(result.value);
        setOverviewDisclosure(result.disclosure);
      }
      else setOverviewFailure(result.error);
    });
    void readCategories(projectId, controller.signal).then((result) => {
      if (controller.signal.aborted || current !== summaryGeneration.current) return;
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
      // `setRegisterLoading(false)` runs whenever *this* fetch settles
      // without having been aborted — even when its own data is then
      // discarded as stale below: `generation` is now shared with
      // `revalidateConstraints`'s own background reads (`[PC-CM-UX-AC-018]`),
      // so a mount-time foreground poll racing this effect's own initial
      // load can legitimately supersede it (by generation) before it
      // resolves, without this effect's own cleanup ever running (no
      // identity/query change happened — nothing aborted `controller`). If
      // this callback bailed out on a generation mismatch before clearing
      // "loading" too, it would stay stuck `true` forever whenever that
      // happens — the superseding read never touches this flag,
      // deliberately, so it never flashes the workspace back to "loading"
      // on an ordinary background poll (see that hook's own call site
      // comment). This is deliberately gated on `aborted`, not on
      // `generation`: an aborted, genuinely superseded fetch (a real
      // Project/scope change, this effect's own cleanup already ran) must
      // still leave "loading" alone — the new effect run's own fetch, for
      // the *new* identity, owns clearing it next.
      if (!controller.signal.aborted) setRegisterLoading(false);
      if (current !== generation.current) return;
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

  /** Bumps the summary/register/detail effects' shared retry key, forcing a re-read from the backend. */
  const refreshAfterMutation = useCallback(() => setRetry((value) => value + 1), []);

  // --- [PC-CM-UX-AC-018] foreground revalidation ---------------------------
  //
  // A silent background re-read, not a `retry` bump: `retry` deliberately
  // resets Register/Overview/Category state to loading/empty first (correct
  // for a person-initiated Retry after a failure, or a just-confirmed
  // mutation), which would otherwise flash the whole workspace to "loading"
  // on every 5s poll / window focus — exactly what a foreground revalidation
  // must not do. This reads fresh data the same way the initial effects do
  // and applies it directly to the same state setters, guarded by the same
  // identity comparison those effects already use, so a slow background read
  // can never clobber a newer navigation's state.
  const registerIdentityRef = useRef(registerIdentity);
  const summaryIdentityRef = useRef(summaryIdentity);
  useEffect(() => {
    registerIdentityRef.current = registerIdentity;
  }, [registerIdentity]);
  useEffect(() => {
    summaryIdentityRef.current = summaryIdentity;
  }, [summaryIdentity]);

  // `useForegroundRevalidation`'s own "interval" trigger only dedupes
  // against another "interval" tick already in flight — a "focus"/"online"
  // trigger (a real window focus, or reconnect) is allowed to start a
  // second, fully concurrent `revalidateConstraints()` call while an earlier
  // one is still pending, and this same fetcher runs *alongside*, entirely
  // uncoordinated with, the identity/`retry`-triggered effects above (the
  // register effect and the overview/categories effect) that read the exact
  // same data into the exact same state. All of these calls share the same
  // register/summary identity (identity only changes on a scope/Project
  // change, never between two ordinary polls or a Retry), so an
  // identity-only guard cannot tell any of them apart from one another —
  // without a stronger guard, whichever call happens to *resolve* last wins,
  // even when it *started* first or is already stale. This surfaced live as
  // exactly that: a just-deactivated Category's `authoring-category` option
  // flickering back to enabled once a straggling, earlier-started read (be
  // it another foreground poll, or the pre-existing `retry`-bump effect's
  // own read) finally landed after a fresher one had already applied.
  //
  // Fixed by having this fetcher participate in the *same* generation
  // counters those sibling effects already own and check
  // (`generation` — register; `summaryGeneration` — overview/categories),
  // rather than a separate counter of its own: every one of these
  // read-triggering mechanisms — a Project/scope change, a Retry, a
  // foreground poll — bumps the same counter its own kind of read is gated
  // on, so whichever one most recently *started* is the only one ever
  // allowed to apply its result, regardless of which resolves first and
  // regardless of which mechanism started it.
  const revalidateConstraints = useCallback(async (): Promise<ConstraintForegroundResult> => {
    const controller = new AbortController();
    const requestRegisterIdentity = registerIdentity;
    const requestSummaryIdentity = summaryIdentity;
    const myRegisterGen = ++generation.current;
    const mySummaryGen = ++summaryGeneration.current;
    const [registerResult, overviewResult, categoriesResult] = await Promise.all([
      readRegister(projectId, state, null, controller.signal),
      readOverview(projectId, controller.signal),
      readCategories(projectId, controller.signal),
    ]);
    const isLatestRegister = myRegisterGen === generation.current;
    const isLatestSummary = mySummaryGen === summaryGeneration.current;

    if (
      isLatestRegister &&
      requestRegisterIdentity === registerIdentityRef.current
    ) {
      if (registerResult.ok) {
        setPage(registerResult.value);
        setRegisterDisclosure(registerResult.disclosure);
        setRegisterFailure(null);
      } else {
        setRegisterFailure(registerResult.error);
      }
    }
    if (
      isLatestSummary &&
      requestSummaryIdentity === summaryIdentityRef.current
    ) {
      if (overviewResult.ok) {
        setOverview(overviewResult.value);
        setOverviewDisclosure(overviewResult.disclosure);
        setOverviewFailure(null);
      } else {
        setOverviewFailure(overviewResult.error);
      }
      if (categoriesResult.ok) {
        setCategories(categoriesResult.value.filter((item) => item.projectId === projectId));
        setCategoriesFailure(null);
      } else {
        setCategoriesFailure(categoriesResult.error);
      }
    }

    const failed = [registerResult, overviewResult, categoriesResult].find(
      (result): result is { ok: false; error: LiveFailure } => !result.ok,
    );
    return failed ? { outcome: "failed", error: failed.error } : { outcome: "applied" };
  }, [projectId, registerIdentity, state, summaryIdentity]);

  const [foregroundCoordinator] = useState(() => new ConstraintForegroundCoordinator());
  useForegroundRevalidation<void, string, () => Promise<ConstraintForegroundResult>, ConstraintForegroundResult, ForegroundQuerySnapshot<void>>({
    queryId: `constraints:${projectId}`,
    queryKey: `constraints:${projectId}`,
    enabled: true,
    coordinator: foregroundCoordinator,
    fetcher: revalidateConstraints,
  });

  const handleLifecycleAction = useCallback((action: ConstraintLifecycleAction) => {
    if (action === "edit" || action === "publish") {
      // Both open the same live edit surface; the Publish button inside it
      // is what dispatches `constraints.publish` for an existing Draft.
      openAuthoring("edit");
      return;
    }
    setDirectAction(action as DirectAction);
  }, [openAuthoring]);

  /**
   * The Register's one inline-edit seam (`register-table.tsx`'s `OnInlineEdit`).
   *
   * Status dispatches `constraints.transition`; Due/BIC/Current Update
   * dispatch `constraints.update` — two different capabilities, chosen by
   * `field`, never one generic "patch" call. On a confirmed write this reads
   * the record's canonical detail fresh and returns it as the replacement row
   * (`PC-CM-FE-AC-059`) rather than a locally recomputed guess; if that
   * follow-up read itself fails, the whole Register/Overview is refreshed
   * instead so nothing stale is left pinned in place.
   */
  const handleInlineEdit = useCallback(
    async (edit: InlineEditRequest): Promise<InlineEditResult> => {
      const isTransition = edit.field === "status";
      const idempotencyKey = mintIdempotencyKey();
      const request: Record<string, unknown> =
        edit.field === "status"
          ? { toState: edit.value }
          : edit.field === "due"
            ? { dueDate: edit.value }
            : edit.field === "bic"
              ? { bic: edit.value }
              : { currentUpdate: edit.value };

      const outcome = await runtime.mutationCoordinator.mutate({
        kind: isTransition ? "constraintTransition" : "constraintUpdate",
        lockRequest: { kind: "constraint-record", key: constraintLockKey(edit.constraintId) },
        idempotencyKey,
        expectedVersion: edit.expectedVersion,
        request,
        epoch: runtime.scopeEpoch,
        isCurrentEpoch: runtime.isCurrentEpoch,
        dispatch: async ({ request: dispatchRequest, idempotencyKey: key, expectedVersion }) => {
          const body: Record<string, unknown> = {
            ...(dispatchRequest as Record<string, unknown>),
            idempotencyKey: key,
            expectedVersion,
          };
          return isTransition
            ? transitionConstraint(projectId, edit.constraintId, body)
            : updateConstraint(projectId, edit.constraintId, body);
        },
        hooks: {
          feedback: async (_result, phase) => {
            if (phase === "confirmed") {
              feedback.publish({ eventId: `register-inline-${idempotencyKey}`, kind: "success", message: "The change was saved." });
            } else if (phase === "conflict") {
              feedback.publish({
                eventId: `register-inline-${idempotencyKey}-conflict`,
                kind: "conflict",
                message: "This row changed since it was read.",
              });
            } else if (phase === "failed" || phase === "ambiguous") {
              feedback.publish({ eventId: `register-inline-${idempotencyKey}-failed`, kind: "error", message: "The change was not saved." });
            }
          },
        },
      });

      if (outcome.refused) {
        return { ok: false, message: "This row is already being written to. Wait for that write to finish." };
      }
      if (outcome.state.phase === "conflict") {
        return { ok: false, message: "This row changed since it was read. Open it to see the current state." };
      }
      if (outcome.state.phase === "ambiguous") {
        return { ok: false, message: "The change's outcome could not be confirmed. Open the record to check it." };
      }
      if (outcome.state.phase !== "confirmed") {
        const failure = outcome.state.error as LiveMutationFailure | undefined;
        return { ok: false, message: failure?.message ?? "The change was not saved." };
      }

      const controller = new AbortController();
      const detailResult = await readDetail(projectId, edit.constraintId, controller.signal);
      if (!detailResult.ok) {
        refreshAfterMutation();
        return { ok: true };
      }
      const priorGroupKeys =
        visiblePage.entries.find((item) => item.constraintId === edit.constraintId)?.groupKeys ?? [];
      const freshEntry = detailToListEntry(detailResult.value, priorGroupKeys);
      setPage((prior) => ({
        ...prior,
        entries: prior.entries.map((item) => (item.constraintId === freshEntry.constraintId ? freshEntry : item)),
      }));
      return { ok: true, entry: freshEntry };
    },
    [feedback, projectId, refreshAfterMutation, runtime, visiblePage.entries],
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
        onLifecycleAction={handleLifecycleAction}
      />
    ),
    [
      closeDetail,
      handleLifecycleAction,
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
        {/*
          `min-w-0`: without it, this flex item's own preferred width is
          driven by the `<select>`'s widest `<option>` text (a Project name,
          unbounded length) even once it has wrapped onto its own row at a
          narrow width — a flex item does not shrink below its content's
          intrinsic min-content size by default, wrapping alone does not fix
          that, and `<select>` itself already carries `min-w-0 max-w-full`
          (`components/ui/select.tsx`) precisely so an ancestor that also
          opts in can let it shrink. This is that ancestor.
        */}
        <label className="ml-auto flex min-w-0 items-center gap-1">
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
        <Button size="sm" variant="secondary" data-testid="open-categories" onClick={() => setCategoriesOpen(true)}>
          Categories
        </Button>
      </div>
      {/*
        Moved here from inside the Overview tab's own `TabsContent`: Category
        data backs the Register's own filter/grouping and the "New
        Constraint" dialog's Category picker just as much as it backs the
        Overview tab, so a failed Categories read must be stated regardless
        of which tab happens to be selected — the old placement meant this
        notice was silently unreachable from the Register tab entirely
        (confirmed live: `project-controls-run02-degraded.spec.ts`'s own
        "a malformed Category list answer..." test opens directly on
        `?view=register` and never finds it).
      */}
      {visibleCategoriesFailure ? <p role="alert" className="text-sm text-moss-coral-strong">Categories could not be read.</p> : null}
      <Tabs value={state.view} onValueChange={(view: string) => navigate({ ...state, view: view as ConstraintUrlState["view"] })}>
        <TabsList aria-label="Constraint workspace">
          <TabsTrigger value="overview" data-testid="tab-overview">Overview</TabsTrigger>
          <TabsTrigger value="register" data-testid="tab-register">Register</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="mt-4">
          {visibleOverviewFailure ? (
            <SurfaceState kind="unavailable" title="Constraint Overview could not be read" error={safeDiagnostic(visibleOverviewFailure)} testId="overview-unavailable">
              <Button size="sm" variant="secondary" onClick={() => setRetry((value) => value + 1)}>Retry</Button>
            </SurfaceState>
          ) : visibleOverview === null ? (
            <p role="status" className="text-sm text-muted" data-testid="overview-loading">Reading the Constraint Overview…</p>
          ) : (
            <>
            {visibleOverviewDisclosure?.coverage === "partial" ? <DegradedBanner scope="Constraint Overview" limitations={safeLimitations(visibleOverviewDisclosure.limitations)} truncated={visibleOverviewDisclosure.truncated} /> : null}
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
            onNewConstraint={() => openAuthoring("create")}
            onInlineEdit={handleInlineEdit}
            livePage={visiblePage}
            loading={visibleRegisterLoading}
            failure={visibleRegisterFailure}
            disclosure={visibleRegisterDisclosure}
            onRetry={() => setRetry((value) => value + 1)}
            onLoadMore={loadMore}
          />
        </TabsContent>
      </Tabs>
      {authoringMounted ? (
        <ConstraintAuthoring
          // Bumped only on open (see `openAuthoring`), never on close — a
          // genuinely new session still gets a clean remount (form state
          // can never carry over), but closing updates this same instance
          // in place first (see `authoringMounted`'s own doc comment above)
          // instead of unmounting it in the same render.
          key={authoringKey}
          mode={authoring?.mode ?? "create"}
          open={authoring !== null}
          projectId={projectId}
          categories={visibleCategories}
          entry={authoring?.mode === "edit" ? selected : null}
          detail={authoring?.mode === "edit" ? (visibleDetail ?? null) : null}
          onClose={closeAuthoring}
          onCreated={(constraintId) => {
            closeAuthoring();
            refreshAfterMutation();
            selectConstraint(constraintId);
          }}
          onUpdated={() => {
            closeAuthoring();
            refreshAfterMutation();
          }}
        />
      ) : null}
      <ConstraintDirectActions
        action={directAction}
        projectId={projectId}
        entry={selected}
        expectedVersion={visibleDetail?.version ?? selected?.version}
        onClose={() => setDirectAction(null)}
        onCompleted={({ successorId }) => {
          refreshAfterMutation();
          if (successorId) selectConstraint(successorId);
        }}
      />
      <ConstraintCategoryAdmin
        open={categoriesOpen}
        projectId={projectId}
        categories={visibleCategories}
        onClose={() => setCategoriesOpen(false)}
        onChanged={refreshAfterMutation}
      />
    </div>
  );
}

export function LiveConstraintsWorkspace(props: Props) {
  return <Suspense fallback={<p className="text-sm text-muted">Loading the Constraint workspace…</p>}><LiveConstraintsWorkspaceInner {...props} /></Suspense>;
}
