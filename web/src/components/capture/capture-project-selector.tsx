"use client";

/**
 * The minimum reusable Project chooser for Capture (C04).
 *
 * One controlled nullable Project identifier, the existing native `Select`, and
 * no new UI dependency. Note, Conversation log and a Capture-launched Task all
 * use this one adapter; Run 02's fourth form will too. It is deliberately not a
 * redesigned global picker and has no search.
 *
 * **A name comes from an authorized read or it does not come at all.** The
 * options are one validated `/api/projects` page; the selected Project's name,
 * when it is not on that page, is the exact `/api/projects/[projectId]` read.
 * While neither has answered, the control says *"Project unavailable — selection
 * retained"*. It never shows a cached name from another session, never invents
 * one, never shows the raw identifier as the ordinary label, and — the one that
 * matters most — never quietly falls back to No Project. An explicit *choice* of
 * No Project is a person's to make; a fallback to it is this component filing
 * someone's note against nothing while the screen said otherwise.
 *
 * **Paging is bounded and never exhaustive.** One page is cached at a time plus
 * the selected option, with a cursor stack for Previous and Next. At 100 visited
 * cursors it refuses to load further rather than paging forever, and it refuses
 * without dropping the selection. Nothing here auto-fetches every page: this is
 * a UI memory bound, not evidence that all Projects were enumerated.
 *
 * **It writes nothing outside itself.** No `applyResolution`, no preference
 * cookie or `localStorage`, no router rewrite, no new capability, no Project
 * Controls filter. A change here changes this control's value and nothing else.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { apiGet } from "@/lib/api/client";
import { isProjectId } from "@/lib/project-scope/scope";

/** The fixed page this picker asks for. Not caller-controllable. */
export const CAPTURE_PROJECT_PAGE_SIZE = 25;

/** How many cursors one experience may visit before it refuses to go further. */
export const CAPTURE_PROJECT_MAX_VISITED_CURSORS = 100;

export const CAPTURE_PROJECT_LABEL = "Project";
export const CAPTURE_NO_PROJECT_LABEL = "No Project";
export const CAPTURE_PROJECT_UNAVAILABLE = "Project unavailable — selection retained";
export const CAPTURE_PROJECT_PAGE_BOUND =
  "No more Project pages can be loaded here. Your selection is unchanged.";
/**
 * R02-WP10 Phase 7: appended to the label when a caller marks the picker
 * `required` (Constraint — `PC-CM-CAPTURE-PROJECT-AC-002`). Every existing
 * caller (Note, Conversation log, Task) leaves `required` unset, so their
 * label is exactly {@link CAPTURE_PROJECT_LABEL}, unchanged.
 */
export const CAPTURE_PROJECT_REQUIRED_SUFFIX = " (required)";

interface ProjectOption {
  readonly projectId: string;
  readonly name: string;
}

interface ProjectsPage {
  readonly projects?: readonly { readonly projectId?: unknown; readonly name?: unknown }[];
  readonly nextCursor?: unknown;
}

interface ProjectRead {
  readonly project?: { readonly name?: unknown };
}

function readOptions(body: ProjectsPage | undefined): readonly ProjectOption[] {
  if (!body || !Array.isArray(body.projects)) return [];
  const options: ProjectOption[] = [];
  for (const row of body.projects) {
    // Shape-validated before it can become a label: a row this tier cannot
    // recognise is not offered as a choice.
    if (isProjectId(row?.projectId) && typeof row?.name === "string" && row.name.length > 0) {
      options.push({ projectId: row.projectId, name: row.name });
    }
  }
  return options;
}

export function CaptureProjectSelector({
  value,
  onChange,
  disabled,
  principalId,
  sessionEpoch,
  id,
  required,
  placeholderLabel,
}: {
  readonly value: string | null;
  readonly onChange: (value: string | null) => void;
  readonly disabled: boolean;
  readonly principalId: string;
  readonly sessionEpoch: number;
  readonly id: string;
  /**
   * R02-WP10 Phase 7, additive: marks this picker as a required field for the
   * caller's own submit-time validation (Constraint — `PC-CM-CAPTURE-PROJECT-
   * AC-002`, "required for Constraint"). Adds the visible " (required)" label
   * suffix and `aria-required`. It never adds the native `required` attribute
   * and never removes the empty option — this control still reports an
   * explicit "nothing chosen yet" exactly as it always has, and the caller
   * enforces the requirement itself, the same way `task-create-sheet.tsx`
   * enforces Title without native constraint validation. Defaults to `false`,
   * so every existing caller (Note, Conversation log, Task) is unaffected.
   */
  readonly required?: boolean;
  /**
   * R02-WP10 Phase 7, additive: overrides the empty option's text. Note,
   * Conversation log and Task keep {@link CAPTURE_NO_PROJECT_LABEL} ("No
   * Project" is a real, valid choice for them); Constraint, which has no valid
   * "No Project" choice, passes a placeholder such as "Select a Project"
   * instead. Defaults to {@link CAPTURE_NO_PROJECT_LABEL}.
   */
  readonly placeholderLabel?: string;
}) {
  const [options, setOptions] = useState<readonly ProjectOption[]>([]);
  const [selectedOption, setSelectedOption] = useState<ProjectOption | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<readonly (string | null)[]>([null]);
  const [notice, setNotice] = useState<string | null>(null);

  /**
   * The generation this control is reading for.
   *
   * Bumped whenever the Principal or the authentication epoch changes, so a
   * response issued for one session can never relabel a later one. A delayed
   * answer that renamed a selection made after it would be exactly the wrong
   * kind of confident.
   */
  const generation = useRef(0);
  const [renderedSession, setRenderedSession] = useState(`${principalId}:${sessionEpoch}`);
  if (renderedSession !== `${principalId}:${sessionEpoch}`) {
    // Adjusted during render so no frame ever shows the previous session's
    // options or name under the new one.
    setRenderedSession(`${principalId}:${sessionEpoch}`);
    setOptions([]);
    setSelectedOption(null);
    setNextCursor(null);
    setCursorStack([null]);
    setNotice(null);
  }
  useEffect(() => {
    // Invalidates reads already in flight; a ref may not be written in render.
    generation.current += 1;
  }, [principalId, sessionEpoch]);

  const cursor = cursorStack[cursorStack.length - 1] ?? null;

  /** Load one page. A failure leaves the current selection and page intact. */
  useEffect(() => {
    let cancelled = false;
    const epoch = generation.current;
    const path =
      cursor === null
        ? "/api/projects"
        : `/api/projects?after=${encodeURIComponent(cursor)}`;
    void (async () => {
      let result: Awaited<ReturnType<typeof apiGet<ProjectsPage>>>;
      try {
        result = await apiGet<ProjectsPage>({ hasSession: true }, path);
      } catch {
        // A transport that never answered is not a reason to empty the control.
        if (!cancelled && epoch === generation.current) setNotice(CAPTURE_PROJECT_UNAVAILABLE);
        return;
      }
      if (cancelled || epoch !== generation.current) return;
      if (!result.ok || !result.data) {
        // Loading failed. The control keeps whatever it already had; it does not
        // empty itself, because an empty list reads as "you have no Projects".
        setNotice(CAPTURE_PROJECT_UNAVAILABLE);
        return;
      }
      setOptions(readOptions(result.data));
      setNextCursor(typeof result.data.nextCursor === "string" ? result.data.nextCursor : null);
      setNotice(null);
    })();
    return () => {
      cancelled = true;
    };
  }, [cursor, principalId, sessionEpoch]);

  /**
   * The selected Project's authorized name, through the exact read.
   *
   * Only when the selection is not on the page already loaded — a Project the
   * current page names needs no second request.
   */
  useEffect(() => {
    if (value === null) return;
    // A Project the loaded page already names needs no second request, and the
    // rendering below prefers the page's own row, so nothing is stored here.
    if (options.some((option) => option.projectId === value)) return;
    let cancelled = false;
    const epoch = generation.current;
    void (async () => {
      let result: Awaited<ReturnType<typeof apiGet<ProjectRead>>>;
      try {
        result = await apiGet<ProjectRead>(
          { hasSession: true },
          `/api/projects/${encodeURIComponent(value)}`,
        );
      } catch {
        // Unnamed, retained, and said to be unavailable — never guessed at.
        return;
      }
      if (cancelled || epoch !== generation.current) return;
      // A refused or unreadable answer leaves the selection unnamed. Not found
      // and not yours are the same nondisclosing answer and are treated alike.
      if (!result.ok || typeof result.data?.project?.name !== "string") return;
      setSelectedOption({ projectId: value, name: result.data.project.name });
    })();
    return () => {
      cancelled = true;
    };
  }, [value, options]);

  const goNext = useCallback(() => {
    if (nextCursor === null) return;
    if (cursorStack.length >= CAPTURE_PROJECT_MAX_VISITED_CURSORS) {
      // Refuse, and say so. The selection is untouched.
      setNotice(CAPTURE_PROJECT_PAGE_BOUND);
      return;
    }
    setNotice(null);
    setCursorStack((stack) => [...stack, nextCursor]);
  }, [cursorStack.length, nextCursor]);

  const goPrevious = useCallback(() => {
    setNotice(null);
    setCursorStack((stack) => (stack.length > 1 ? stack.slice(0, -1) : stack));
  }, []);

  // The selected Project is always offerable, even when it is not on this page,
  // so paging can never silently drop what somebody chose.
  const onPage = value === null ? null : options.find((option) => option.projectId === value);
  // Only a resolution for the *current* value counts: a name fetched for an
  // earlier selection must never label a later one.
  const resolved =
    onPage ?? (selectedOption && selectedOption.projectId === value ? selectedOption : null);
  const offered = resolved && !onPage ? [resolved, ...options] : options;
  const selectedIsNamed = value !== null && resolved !== null;

  return (
    <div className="flex flex-col gap-1" data-testid="capture-project-selector">
      <label htmlFor={id} className="text-sm font-medium text-text-primary">
        {CAPTURE_PROJECT_LABEL}
        {required ? (
          <span className="font-normal text-muted">{CAPTURE_PROJECT_REQUIRED_SUFFIX}</span>
        ) : null}
      </label>
      <Select
        id={id}
        value={value ?? ""}
        disabled={disabled}
        aria-required={required || undefined}
        data-testid="capture-project-select"
        onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        className="min-h-11 text-text-primary disabled:opacity-60"
      >
        <option value="">{placeholderLabel ?? CAPTURE_NO_PROJECT_LABEL}</option>
        {offered.map((option) => (
          <option key={option.projectId} value={option.projectId}>
            {option.name}
          </option>
        ))}
        {value !== null && !selectedIsNamed ? (
          // The selection is retained and shown as unavailable rather than being
          // dropped, renamed from a cache, or replaced with No Project.
          <option value={value}>{CAPTURE_PROJECT_UNAVAILABLE}</option>
        ) : null}
      </Select>
      {value !== null && !selectedIsNamed ? (
        <p data-testid="capture-project-unavailable" className="text-xs text-muted">
          {CAPTURE_PROJECT_UNAVAILABLE}
        </p>
      ) : null}
      {notice ? (
        <p role="status" data-testid="capture-project-notice" className="text-xs text-muted">
          {notice}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button
          type="button"
          variant="ghost"
          className="min-h-11"
          disabled={disabled || cursorStack.length <= 1}
          data-testid="capture-project-previous"
          onClick={goPrevious}
        >
          Previous
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="min-h-11"
          disabled={disabled || nextCursor === null}
          data-testid="capture-project-next"
          onClick={goNext}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
