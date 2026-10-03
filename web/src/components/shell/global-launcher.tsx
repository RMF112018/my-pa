"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { CaptureDialog } from "@/components/shell/capture-dialog";
import { SearchCommandPanel } from "@/components/shell/command-palette";
import { TaskCreateSheet } from "@/components/tasks/task-create-sheet";
import { TaskCompactSheet } from "@/components/tasks/task-compact-sheet";
import { Dialog } from "@/components/ui/dialog";
import { Sheet } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { useProjectScope } from "@/components/shell/project-scope-provider";
import { beginCaptureExperience, captureSessionReducer, hasUnresolvedIntent } from "@/lib/capture/session";
import type { CaptureProjectId } from "@/lib/capture/contract";
import type { PresentedTaskActivation } from "@/lib/search/presentation";

const PHONE_QUERY = "(max-width: 767px)";

function subscribeToPhoneViewport(onChange: () => void) {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia(PHONE_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function phoneViewportSnapshot() {
  return typeof window.matchMedia === "function" && window.matchMedia(PHONE_QUERY).matches;
}

export type ProjectId = NonNullable<CaptureProjectId>;
type Mode = "initial" | "search" | "new" | "quick_note" | "conversation_log" | "task";

export interface GlobalLauncherProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly initialMode?: Mode;
  readonly projectId?: ProjectId;
}

const PrincipalContext = createContext<{ principalId: string; sessionEpoch: string } | null>(null);

export function LauncherPrincipalProvider({ principalId, sessionEpoch, children }: {
  principalId: string;
  sessionEpoch: string;
  children: ReactNode;
}) {
  const identity = useMemo(() => ({ principalId, sessionEpoch }), [principalId, sessionEpoch]);
  return <PrincipalContext.Provider value={identity}>{children}</PrincipalContext.Provider>;
}

function taskFormHasUnsentDraft(projectId: string | null): boolean {
  const form = document.querySelector<HTMLFormElement>('[data-testid="task-create-sheet"]');
  if (!form) return false;
  const fields = Array.from(form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("input, textarea, select"));
  return fields.some((field) => {
    if (field instanceof HTMLInputElement && field.type === "hidden") return false;
    if (field instanceof HTMLSelectElement && field.value === (projectId ?? "")) return false;
    return field.value.trim() !== "";
  });
}

/** The shell owns one Search/New experience and the return-focus target. */
export function GlobalLauncher({ open, onOpenChange, initialMode = "initial", projectId }: GlobalLauncherProps) {
  const principal = useContext(PrincipalContext);
  if (!principal) throw new Error("GlobalLauncher requires the verified shell Principal");
  const { principalId } = principal;
  const sessionIdentity = `${principal.principalId}:${principal.sessionEpoch}`;
  const router = useRouter();
  const phone = useSyncExternalStore(subscribeToPhoneViewport, phoneViewportSnapshot, () => false);
  const scope = useProjectScope();
  const scopeProjectId = scope.resolution.scope.kind === "PROJECT" ? scope.resolution.scope.projectId : null;
  const [capture, dispatchCapture] = useReducer(
    captureSessionReducer,
    { principalId, sessionEpoch: scope.epoch, projectId: null },
    (seed: { principalId: string; sessionEpoch: number; projectId: string | null }) =>
      beginCaptureExperience({ experienceId: "capture-initial", ...seed }),
  );
  const [mode, setMode] = useState<Mode>("initial");
  const [searchSeed, setSearchSeed] = useState("");
  const [searchEntry, setSearchEntry] = useState(0);
  const [searchTask, setSearchTask] = useState<PresentedTaskActivation | null>(null);
  const [searchTaskReady, setSearchTaskReady] = useState(false);
  const [searchTaskReturning, setSearchTaskReturning] = useState(false);
  const [taskReady, setTaskReady] = useState(false);
  const [taskProjectId, setTaskProjectId] = useState<string | null>(null);
  const [taskGeneration, setTaskGeneration] = useState(0);
  const [taskDirty, setTaskDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<string | null>(null);
  const [pendingTaskClose, setPendingTaskClose] = useState(false);
  const [online, setOnline] = useState(true);
  const invoker = useRef<HTMLElement | null>(null);
  const fallbackHeading = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  const openRef = useRef(open);
  const openedSessionIdentity = useRef(sessionIdentity);
  const currentSessionIdentity = useRef(sessionIdentity);
  const focusGeneration = useRef(0);
  const confirmedClose = useRef(false);
  const searchChoice = useRef<HTMLButtonElement>(null);
  const searchTaskTrigger = useRef<HTMLElement | null>(null);
  const newChoice = useRef<HTMLButtonElement>(null);
  const quickNoteChoice = useRef<HTMLButtonElement>(null);
  const conversationChoice = useRef<HTMLButtonElement>(null);
  const initialReturnChoice = useRef<"search" | "new">("search");
  const newReturnChoice = useRef<"task" | "quick_note" | "conversation_log">("task");
  const keepEditing = useRef<HTMLButtonElement>(null);
  const mounted = useRef(true);
  const taskContext = useMemo(() => taskProjectId ? { projectId: taskProjectId } : undefined, [taskProjectId]);
  const captureDirty = capture.noteDraft.trim() !== "" || capture.conversationDraft.trim() !== "";
  const hasDrafts = captureDirty || taskDirty;
  const dialogOpen = open && !searchTask && (mode !== "task" || confirmDiscard || !online);

  useLayoutEffect(() => { openRef.current = open; }, [open]);
  useLayoutEffect(() => { currentSessionIdentity.current = sessionIdentity; }, [sessionIdentity]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  useLayoutEffect(() => {
    if (!open || wasOpen.current) {
      wasOpen.current = open;
      return;
    }
    wasOpen.current = true;
    const sameSession = openedSessionIdentity.current === sessionIdentity;
    openedSessionIdentity.current = sessionIdentity;
    initialReturnChoice.current = "search";
    newReturnChoice.current = "task";
    focusGeneration.current += 1;
    const active = document.activeElement;
    // WebKit pointer clicks can leave the document body focused. It is not a
    // usable return target; let the visible shell launcher fallback handle it.
    invoker.current = active instanceof HTMLElement && active !== document.body && active !== document.documentElement
      ? active : null;
    fallbackHeading.current = document.querySelector<HTMLElement>("main h1");
    const proposedProject = projectId ?? scopeProjectId;
    setTaskProjectId(proposedProject);
    searchTaskTrigger.current = null;
    setMode(initialMode);
    setSearchSeed("");
    setSearchEntry((entry) => entry + 1);
    setConfirmDiscard(false);
    setPendingNavigation(null);
    setPendingTaskClose(false);
    setSearchTask(null);
    setSearchTaskReady(false);
    setSearchTaskReturning(false);
    setTaskReady(false);
    setTaskDirty(false);
    confirmedClose.current = false;
    if (hasUnresolvedIntent(capture) || (sameSession && captureDirty)) dispatchCapture({ type: "reopen" });
    else dispatchCapture({
      type: "open",
      experienceId: `capture-${crypto.randomUUID()}`,
      principalId,
      sessionEpoch: scope.epoch,
      projectId: proposedProject,
    });
  }, [open, initialMode, principalId, projectId, scope.epoch, scopeProjectId, sessionIdentity, capture, captureDirty]);

  // The launcher overlay closes its trap first. Only a later commit opens
  // the canonical Task sheet, so the two traps never overlap.
  useEffect(() => {
    if (!open || mode !== "task" || !online || confirmDiscard || pendingTaskClose || taskReady) return;
    const frame = requestAnimationFrame(() => setTaskReady(true));
    return () => cancelAnimationFrame(frame);
  }, [open, mode, online, confirmDiscard, pendingTaskClose, taskReady]);
  useEffect(() => {
    if (!searchTask || searchTaskReady || searchTaskReturning) return;
    const frame = requestAnimationFrame(() => setSearchTaskReady(true));
    return () => cancelAnimationFrame(frame);
  }, [searchTask, searchTaskReady, searchTaskReturning]);
  useEffect(() => {
    if (!searchTaskReturning || searchTaskReady) return;
    const frame = requestAnimationFrame(() => {
      setSearchTask(null);
      setSearchTaskReturning(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [searchTaskReturning, searchTaskReady]);
  useEffect(() => {
    if (!pendingTaskClose || taskReady) return;
    const frame = requestAnimationFrame(() => {
      setPendingTaskClose(false);
      setConfirmDiscard(true);
    });
    return () => cancelAnimationFrame(frame);
  }, [pendingTaskClose, taskReady]);
  const focusDialogEntry = useCallback(() => {
    if (confirmDiscard) keepEditing.current?.focus();
    else if (mode === "initial") (initialReturnChoice.current === "new" ? newChoice : searchChoice).current?.focus();
    else if (mode === "new") {
      const target = newReturnChoice.current === "quick_note" ? quickNoteChoice
        : newReturnChoice.current === "conversation_log" ? conversationChoice : newChoice;
      target.current?.focus();
    }
    else if (mode === "search" && searchTaskTrigger.current?.isConnected) {
      searchTaskTrigger.current.focus();
      searchTaskTrigger.current = null;
    }
  }, [mode, confirmDiscard]);

  useEffect(() => {
    if (dialogOpen) focusDialogEntry();
  }, [dialogOpen, focusDialogEntry]);
  useEffect(() => {
    if (!open || mode !== "task") return;
    const update = () => setTaskDirty(taskFormHasUnsentDraft(taskProjectId));
    // Observe after the canonical sheet's React onChange has accepted the
    // value. A capture-phase parent update can restore its controlled input
    // before onChange sees it, erasing the first edit.
    document.addEventListener("input", update);
    document.addEventListener("change", update);
    return () => {
      document.removeEventListener("input", update);
      document.removeEventListener("change", update);
    };
  }, [open, mode, taskProjectId]);
  useEffect(() => {
    if (!open || !dialogOpen) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        escapeFromDialog();
      } else if (mode !== "initial" || confirmDiscard) {
        return;
      } else if (event.key.length === 1 && !event.isComposing) {
        event.preventDefault();
        setSearchSeed(event.key);
        setSearchEntry((entry) => entry + 1);
        setMode("search");
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        (document.activeElement === searchChoice.current ? newChoice : searchChoice).current?.focus();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  useEffect(() => {
    if (!open || mode !== "task" || !taskReady || confirmDiscard) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const back = document.querySelector<HTMLButtonElement>('[data-testid="task-create-back"]');
      if (!back || back.disabled) return;
      event.preventDefault();
      event.stopPropagation();
      // Let the canonical Back action retain its editable/frozen Project.
      back.click();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, mode, taskReady, confirmDiscard]);

  function finishClose(discard: boolean) {
    if (discard) {
      dispatchCapture({ type: "discard_unsent" });
      setTaskGeneration((generation) => generation + 1);
      setTaskDirty(false);
    }
    dispatchCapture({ type: "close" });
    setConfirmDiscard(false);
    setPendingNavigation(null);
    setTaskReady(false);
    onOpenChange(false);
    const generation = ++focusGeneration.current;
    requestAnimationFrame(() => {
      if (generation !== focusGeneration.current || openRef.current) return;
      const active = document.activeElement;
      if (active instanceof HTMLElement && active !== document.body && active !== document.documentElement
        && active !== invoker.current && !active.closest('dialog, [role="dialog"], [role="alertdialog"]')) return;
      const launcherControls = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="launcher-button-desktop"], [data-testid="launcher-button-mobile"]'));
      const fallback = launcherControls.find((control) => control.getClientRects().length > 0) ?? launcherControls[0]
        ?? Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((button) => button.textContent?.trim() === "Search or create")
        ?? (fallbackHeading.current?.isConnected ? fallbackHeading.current : document.querySelector<HTMLElement>("main h1"));
      const target = invoker.current?.isConnected ? invoker.current : fallback;
      if (target?.tagName === "H1") target.tabIndex = -1;
      target?.focus();
    });
  }

  function requestClose() {
    if (!open) return;
    if (hasUnresolvedIntent(capture)) return;
    if (mode === "task") {
      const form = document.querySelector<HTMLFormElement>('[data-testid="task-create-sheet"]');
      if (form?.getAttribute("aria-busy") === "true" || form?.textContent?.includes("may still have succeeded")) return;
      if (taskFormHasUnsentDraft(taskProjectId)) setTaskDirty(true);
    }
    if (hasDrafts || (mode === "task" && taskFormHasUnsentDraft(taskProjectId))) {
      if (mode === "task" && taskReady) {
        setTaskReady(false);
        setPendingTaskClose(true);
      } else setConfirmDiscard(true);
      return;
    }
    finishClose(false);
  }

  function navigateFromSearch(href: string) {
    if (hasUnresolvedIntent(capture)) return;
    if (hasDrafts) {
      setPendingNavigation(href);
      setConfirmDiscard(true);
      return;
    }
    finishClose(false);
    router.push(href);
  }

  function chooseNote(kind: "quick_note" | "conversation_log") {
    newReturnChoice.current = kind;
    dispatchCapture({ type: "select_form", form: kind });
    setMode(kind);
  }

  function toTask() {
    newReturnChoice.current = "task";
    setTaskReady(false);
    // Task's editable Project starts from the launcher-open snapshot. Capture
    // keeps its own selection; Back preserves any later Task selection below.
    dispatchCapture({ type: "to_task" });
    setMode("task");
  }

  function backFromTask(context: { projectId: string | null }) {
    setTaskDirty(taskFormHasUnsentDraft(taskProjectId));
    setTaskReady(false);
    setTaskProjectId(context.projectId);
    // Task's explicit Project must not rewrite either Capture subdraft.
    dispatchCapture({ type: "task_back", projectId: capture.projectId });
    setMode("new");
  }

  function taskOpenChange(next: boolean) {
    if (next || confirmedClose.current) return;
    requestClose();
  }

  function taskConfirmed() {
    if (!mounted.current || openedSessionIdentity.current !== currentSessionIdentity.current) return;
    // TaskCreateSheet has already verified its receipt, published feedback,
    // reconciled active queries, and retired the canonical intent.
    confirmedClose.current = true;
    finishClose(false);
  }

  function escapeFromDialog() {
    if (!dialogOpen || searchTask) return;
    if (confirmDiscard) { setConfirmDiscard(false); return; }
    if (mode === "search" || mode === "new") {
      initialReturnChoice.current = mode;
      setMode("initial");
      return;
    }
    if (mode === "quick_note" || mode === "conversation_log") { setMode("new"); return; }
    requestClose();
  }

  function closeLauncherDialog() {
    // Controlled branch changes also emit a native close event.
    if (!dialogOpen || searchTask) return;
    if (confirmDiscard) { setConfirmDiscard(false); return; }
    requestClose();
  }

  const launcherContent = confirmDiscard ? <div role="alertdialog" aria-label="Discard drafts">
        <p>Discard unsent drafts? Held offline notes are not deleted.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button ref={keepEditing} onClick={() => { setPendingNavigation(null); setConfirmDiscard(false); if (mode === "task") setTaskReady(true); }}>Keep editing</Button>
          <Button variant="secondary" onClick={() => {
            const href = pendingNavigation;
            finishClose(true);
            if (href) router.push(href);
          }}>Discard drafts</Button>
        </div>
      </div> : <div>
        {mode === "initial" ? <div role="group" aria-label="Search or New" className="flex flex-col gap-2">
          <Button ref={searchChoice} variant="ghost" onClick={() => { setSearchSeed(""); setSearchEntry((entry) => entry + 1); setMode("search"); }}>Search</Button>
          <Button ref={newChoice} variant="ghost" onClick={() => setMode("new")}>New</Button>
        </div> : null}
        {mode === "search" ? <SearchCommandPanel key={searchEntry} autoFocus initialQuery={searchSeed}
          includeCapture={false} onCapture={() => undefined} onDismiss={() => setMode("initial")}
          onNavigate={navigateFromSearch} onTaskActivate={(task, trigger) => {
            searchTaskTrigger.current = trigger;
            setSearchTaskReady(false);
            setSearchTask(task);
          }} /> : null}
        {mode === "new" ? <div role="group" aria-label="Create new" className="flex flex-col gap-2"
          onKeyDown={(event) => {
            if (event.altKey || event.ctrlKey || event.metaKey || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
            const choices = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
            const current = choices.findIndex((choice) => choice === document.activeElement);
            event.preventDefault();
            const step = event.key === "ArrowDown" ? 1 : -1;
            choices[(current + step + choices.length) % choices.length]?.focus();
          }}>
          <Button ref={newChoice} variant="ghost" onClick={toTask}>Create Task</Button>
          <Button ref={quickNoteChoice} variant="ghost" onClick={() => chooseNote("quick_note")}>Quick Note</Button>
          <Button ref={conversationChoice} variant="ghost" onClick={() => chooseNote("conversation_log")}>Conversation Log</Button>
        </div> : null}
        <CaptureDialog embedded open={mode === "quick_note" || mode === "conversation_log"}
          onClose={requestClose} onBack={() => setMode("new")}
          principalId={principalId} session={capture} dispatch={dispatchCapture} initialStage="entry" />
        {mode === "task" && !online ? <div role="status" className="space-y-4 text-sm text-text-secondary">
          <p>Tasks can’t be created offline. Keep this draft open and try again when you’re online.</p>
          <Button variant="secondary" onClick={() => setMode("new")}>Back</Button>
        </div> : null}
      </div>;

  return <>
    <div hidden={!dialogOpen}
      onFocusCapture={(event) => {
        // The canonical phone Sheet mounts its portal after the launcher effect
        // and defaults to its title. Choose this feature's stage synchronously.
        if (phone && event.target instanceof HTMLElement && event.target.tagName === "H2") focusDialogEntry();
      }}
      onKeyDownCapture={(event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopPropagation();
        escapeFromDialog();
      }}
      className="[&_dialog]:max-w-[680px] [&_dialog]:w-[80vw] [&_dialog]:max-h-[80vh]">
    {phone ? <Sheet open={dialogOpen} onOpenChange={(next) => { if (!next) closeLauncherDialog(); }}
      title="Search or create" placement="menu">{launcherContent}</Sheet>
      : <Dialog open={dialogOpen} onClose={closeLauncherDialog} title="Search or create">{launcherContent}</Dialog>}

    </div>
    {searchTask ? <TaskCompactSheet taskId={searchTask.taskId} seed={searchTask.seed}
      open={searchTaskReady} onOpenChange={(next) => {
        if (!next) { setSearchTaskReady(false); setSearchTaskReturning(true); }
      }} /> : null}
    <TaskCreateSheet key={taskGeneration} open={open && mode === "task" && taskReady && online && !confirmDiscard}
      onOpenChange={taskOpenChange} entry="capture" context={taskContext} principalId={principalId}
      sessionEpoch={scope.epoch} onBack={backFromTask} onConfirmed={taskConfirmed} />
  </>;
}
