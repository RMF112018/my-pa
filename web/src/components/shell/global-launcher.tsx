"use client";

import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { CaptureDialog } from "@/components/shell/capture-dialog";
import { TaskCreateSheet } from "@/components/tasks/task-create-sheet";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useProjectScope } from "@/components/shell/project-scope-provider";
import { beginCaptureExperience, captureSessionReducer } from "@/lib/capture/session";
import type { CaptureProjectId, PersistedCaptureAck } from "@/lib/capture/contract";
import type { TaskMutationResult } from "@/lib/api/decode/capabilities/_mutation-helpers";
import { decodeTaskMutation } from "@/lib/api/decode/capabilities/_mutation-helpers";

/** Existing canonical contracts, named for the launcher boundary. */
export type ProjectId = NonNullable<CaptureProjectId>;
export type CaptureReceipt = PersistedCaptureAck;
export type TaskCreateReceipt = TaskMutationResult;

export interface GlobalLauncherProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly initialMode?: "capture" | "task";
  readonly projectId?: ProjectId;
  readonly onConfirmed: (receipt: CaptureReceipt | TaskCreateReceipt) => void;
}

// The Principal comes only from the verified shell session, never a launcher
// caller or browser field. The public launcher props stay the frozen contract.
const PrincipalContext = createContext<{ principalId: string; sessionEpoch: string } | null>(null);

export function LauncherPrincipalProvider({
  principalId,
  sessionEpoch,
  children,
}: {
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
  if (form.getAttribute("aria-busy") === "true") return true;
  const fields = Array.from(form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("input, textarea, select"));
  return fields.some((field) => {
    if (field instanceof HTMLInputElement && field.type === "hidden") return false;
    if (field instanceof HTMLSelectElement && field.value === (projectId ?? "")) return false;
    return field.value.trim() !== "";
  });
}

/** One overlay owner for the existing Capture and Task creators. */
export function GlobalLauncher({
  open,
  onOpenChange,
  initialMode,
  projectId,
  onConfirmed,
}: GlobalLauncherProps) {
  const principal = useContext(PrincipalContext);
  if (!principal) throw new Error("GlobalLauncher requires the verified shell Principal");
  const { principalId } = principal;
  const sessionIdentity = `${principal.principalId}:${principal.sessionEpoch}`;
  const router = useRouter();
  const scope = useProjectScope();
  const scopeProjectId = scope.resolution.scope.kind === "PROJECT"
    ? scope.resolution.scope.projectId : null;
  const [capture, dispatchCapture] = useReducer(
    captureSessionReducer,
    { principalId, sessionEpoch: scope.epoch, projectId: null },
    (seed: { principalId: string; sessionEpoch: number; projectId: string | null }) =>
      beginCaptureExperience({ experienceId: "capture-initial", ...seed }),
  );
  const [mode, setMode] = useState<"capture" | "task" | "confirmed">("capture");
  const [captureStartStage, setCaptureStartStage] = useState<"choose" | "entry">("choose");
  const [taskProjectId, setTaskProjectId] = useState<string | null>(null);
  const [taskGeneration, setTaskGeneration] = useState(0);
  const [confirmedTask, setConfirmedTask] = useState<TaskCreateReceipt | null>(null);
  const invoker = useRef<HTMLElement | null>(null);
  const fallbackHeading = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  const openRef = useRef(open);
  const focusGeneration = useRef(0);
  const confirmedClose = useRef(false);
  const openedSessionIdentity = useRef(sessionIdentity);
  const currentSessionIdentity = useRef(sessionIdentity);
  const mounted = useRef(true);
  const taskContext = useMemo(() => taskProjectId ? { projectId: taskProjectId } : undefined, [taskProjectId]);
  const [online, setOnline] = useState(true);

  useLayoutEffect(() => {
    openRef.current = open;
  }, [open]);
  useLayoutEffect(() => {
    currentSessionIdentity.current = sessionIdentity;
  }, [sessionIdentity]);
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
    openedSessionIdentity.current = sessionIdentity;
    focusGeneration.current += 1;
    invoker.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    fallbackHeading.current = document.querySelector<HTMLElement>("main h1");
    confirmedClose.current = false;
    setConfirmedTask(null);
    setCaptureStartStage(initialMode === "capture" ? "entry" : "choose");
    const proposedProject = projectId ?? scopeProjectId;
    setTaskProjectId(proposedProject);
    dispatchCapture({
      type: "open",
      experienceId: `capture-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      principalId,
      sessionEpoch: scope.epoch,
      projectId: proposedProject,
    });
    setMode(initialMode === "task" ? "task" : "capture");
  }, [open, initialMode, principalId, projectId, scope.epoch, scopeProjectId, sessionIdentity]);

  function close() {
    dispatchCapture({ type: "close" });
    onOpenChange(false);
    const generation = ++focusGeneration.current;
    // Radix closes the Task sheet after the callback. Restore on its next
    // frame only if this launcher stayed closed; an immediate reopen owns focus.
    requestAnimationFrame(() => {
      if (generation === focusGeneration.current && !openRef.current) {
        const target = invoker.current?.isConnected
          ? invoker.current
          : fallbackHeading.current?.isConnected
            ? fallbackHeading.current
            : document.querySelector<HTMLElement>("main h1");
        if (target?.tagName === "H1") target.tabIndex = -1;
        target?.focus();
      }
    });
  }

  function toTask(nextProjectId: string | null) {
    setCaptureStartStage("choose");
    setTaskProjectId(nextProjectId);
    dispatchCapture({ type: "to_task" });
    setMode("task");
  }

  function backToCapture(context: { projectId: string | null }) {
    setCaptureStartStage("choose");
    dispatchCapture({ type: "task_back", projectId: context.projectId });
    setMode("capture");
  }

  function taskOpenChange(next: boolean) {
    if (next) return;
    if (confirmedClose.current) {
      confirmedClose.current = false;
      return;
    }
    // The canonical Task form owns the draft and frozen intent. Preserve both
    // when dismissal is cancelled; pending work cannot be dismissed.
    const form = document.querySelector<HTMLFormElement>('[data-testid="task-create-sheet"]');
    if (form?.getAttribute("aria-busy") === "true") return;
    if (taskFormHasUnsentDraft(taskProjectId)) {
      if (!window.confirm("Discard the unsent Task draft?")) return;
      // The canonical sheet remains mounted while closed. Replace its local
      // editable form only after the Principal accepted discard; unresolved
      // create intents live in the shared runtime and resume on the next open.
      setTaskGeneration((generation) => generation + 1);
    }
    close();
  }

  function taskConfirmed(value: unknown) {
    if (!mounted.current || openedSessionIdentity.current !== currentSessionIdentity.current) return;
    // TaskCreateSheet verifies before invoking its callback. Re-decode at the
    // public launcher boundary because that callback is intentionally unknown.
    const decoded = decodeTaskMutation(value);
    if (!decoded.ok) return;
    confirmedClose.current = true;
    setConfirmedTask(decoded.value);
    setMode("confirmed");
    onConfirmed(decoded.value);
  }

  function captureConfirmed(receipt: CaptureReceipt) {
    if (!mounted.current || openedSessionIdentity.current !== currentSessionIdentity.current) return;
    onConfirmed(receipt);
  }

  return (
    <>
      <CaptureDialog
        open={open && mode === "capture"}
        onClose={close}
        principalId={principalId}
        session={capture}
        dispatch={dispatchCapture}
        onCreateTask={toTask}
        onConfirmed={captureConfirmed}
        initialStage={captureStartStage}
      />
      <TaskCreateSheet
        key={taskGeneration}
        open={open && mode === "task" && online}
        onOpenChange={taskOpenChange}
        entry="capture"
        context={taskContext}
        principalId={principalId}
        sessionEpoch={scope.epoch}
        onBack={backToCapture}
        onConfirmed={taskConfirmed}
      />
      <Dialog open={open && mode === "task" && !online} onClose={() => {
        // A controlled handoff also emits native `close`; only the current
        // offline Task dialog owns a user dismissal of this launcher.
        if (open && mode === "task" && !online) close();
      }} title="Create Task">
        <p className="text-sm text-text-secondary" role="status">
          Creating a Task requires a connection. Your Capture notes can still be held on this device.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => setMode("capture")}>Quick Capture</Button>
          <Button variant="secondary" onClick={close}>Close</Button>
        </div>
      </Dialog>
      <Dialog open={open && mode === "confirmed"} onClose={close} title="Task created">
        <p className="text-sm text-text-secondary">Your Task is ready.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => {
            const taskId = confirmedTask?.task.task_id;
            if (!taskId) return;
            close();
            router.push(`/work/tasks/${encodeURIComponent(taskId)}`);
          }}>Open Task</Button>
          <Button variant="secondary" onClick={close}>Close</Button>
        </div>
      </Dialog>
    </>
  );
}
