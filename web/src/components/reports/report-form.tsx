"use client";

/**
 * The shared draft model and field editor of the new and edit report forms
 * (Reports Modernization WP07, contract U6/U7, Amendments A1/A2).
 *
 * A draft is what the user typed, as text. `validateDraft` checks it the way
 * the server bounds it (title 1..256 code points after NFC, summary up to 2000,
 * at most 24 topics/tags of up to 64 code points each, no duplicates; JSON must
 * parse), so nothing unparsable is ever sent; the type token pattern is a hint
 * only and the server decides. `contentOf` builds the inline content a format
 * takes; `buildPatch` (edit) names only what changed and the cleared optional
 * fields (`type`, `summary`, `reportDate`) through `clearFields`.
 *
 * The local file picker only reads a text file into the editor, in the
 * browser: nothing is uploaded and no path is sent. Nothing here logs.
 */
import Link from "next/link";
import { useId, useState, type ChangeEvent, type InputHTMLAttributes, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import type { InlineReportContent, ReportPatch } from "@/lib/reports/client";
import { MAX_STAGED_BYTES, stagedBytes, type ReportFormat } from "@/lib/reports/transfer-client";
import { RenderedReportContent } from "./report-content";

// --- bounds (domain/reports/vocabulary.py) -------------------------------------

export const TITLE_MAX_CHARACTERS = 256;
export const SUMMARY_MAX_CHARACTERS = 2000;
export const REASON_MAX_CHARACTERS = 500;
export const MAX_TERMS = 24;
export const TERM_MAX_CHARACTERS = 64;
/** The type token pattern, shown as a hint: the server decides. */
export const TYPE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

export const FORMATS: readonly { readonly value: ReportFormat; readonly label: string }[] = [
  { value: "markdown", label: "Markdown" },
  { value: "text", label: "Plain text" },
  { value: "json", label: "JSON" },
  { value: "mixed", label: "Text and JSON" },
];

export const FORM_MESSAGES = {
  titleRequired: "Enter a title.",
  titleTooLong: `The title is longer than ${TITLE_MAX_CHARACTERS} characters.`,
  jsonRequired: "Enter the JSON data.",
  jsonInvalid: "This is not valid JSON.",
  summaryTooLong: `The summary is longer than ${SUMMARY_MAX_CHARACTERS} characters.`,
  reasonRequired: "Say why you are changing the report.",
  reasonTooLong: `The reason is longer than ${REASON_MAX_CHARACTERS} characters.`,
  nothingChanged: "Nothing changed.",
  fileTooLarge: "The file is larger than 16 MB.",
  fileNotText: "The file is not a text file.",
  fileUnreadable: "The file could not be read.",
  uploading: "Uploading large content…",
  sending: "Saving…",
} as const;

const termsTooMany = (field: string) => `At most ${MAX_TERMS} ${field}.`;
const termTooLong = (field: string) => `Each of the ${field} may have at most ${TERM_MAX_CHARACTERS} characters.`;
const termDuplicate = (field: string) => `The ${field} repeat an entry.`;

// --- the draft -------------------------------------------------------------------

export interface ReportDraft {
  readonly title: string;
  readonly format: ReportFormat;
  readonly body: string;
  /** JSON data as typed (json and mixed). */
  readonly json: string;
  readonly type: string;
  /** Comma-separated. */
  readonly topics: string;
  /** Comma-separated. */
  readonly tags: string;
  readonly summary: string;
  /** `YYYY-MM-DD` or empty. */
  readonly reportDate: string;
}

export const EMPTY_DRAFT: ReportDraft = {
  title: "",
  format: "markdown",
  body: "",
  json: "",
  type: "",
  topics: "",
  tags: "",
  summary: "",
  reportDate: "",
};

export const usesBody = (format: ReportFormat) => format !== "json";
export const usesData = (format: ReportFormat) => format === "json" || format === "mixed";

/** Code points after NFC, as the server counts them. */
export function codePoints(value: string): number {
  return [...value.normalize("NFC")].length;
}

/** "a, b ,, c" -> ["a", "b", "c"]. */
export function splitTerms(value: string): string[] {
  return value.split(",").map((term) => term.trim()).filter((term) => term.length > 0);
}

export type JsonParse = { readonly ok: true; readonly value: unknown } | { readonly ok: false; readonly empty: boolean };

export function parseJsonText(text: string): JsonParse {
  if (text.trim() === "") return { ok: false, empty: true };
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch {
    return { ok: false, empty: false };
  }
}

export type DraftField = "title" | "json" | "summary" | "topics" | "tags";
export type DraftErrors = Partial<Record<DraftField, string>>;

function termError(text: string, field: string): string | undefined {
  const terms = splitTerms(text);
  if (terms.length > MAX_TERMS) return termsTooMany(field);
  if (terms.some((term) => codePoints(term) > TERM_MAX_CHARACTERS)) return termTooLong(field);
  const folded = terms.map((term) => term.normalize("NFC").toLocaleLowerCase("en"));
  if (new Set(folded).size !== folded.length) return termDuplicate(field);
  return undefined;
}

/** Client checks; `content: false` skips the content (an edit whose content is not loaded). */
export function validateDraft(draft: ReportDraft, options: { readonly content: boolean }): DraftErrors {
  const errors: DraftErrors = {};
  const title = draft.title.trim();
  if (title === "") errors.title = FORM_MESSAGES.titleRequired;
  else if (codePoints(title) > TITLE_MAX_CHARACTERS) errors.title = FORM_MESSAGES.titleTooLong;
  if (options.content && usesData(draft.format)) {
    const parsed = parseJsonText(draft.json);
    if (!parsed.ok) errors.json = parsed.empty ? FORM_MESSAGES.jsonRequired : FORM_MESSAGES.jsonInvalid;
  }
  if (codePoints(draft.summary.trim()) > SUMMARY_MAX_CHARACTERS) errors.summary = FORM_MESSAGES.summaryTooLong;
  const topics = termError(draft.topics, "topics");
  if (topics) errors.topics = topics;
  const tags = termError(draft.tags, "tags");
  if (tags) errors.tags = tags;
  return errors;
}

export const hasErrors = (errors: DraftErrors) => Object.keys(errors).length > 0;

/** The inline content of a valid draft, or `null` when its JSON does not parse. */
export function contentOf(draft: ReportDraft): InlineReportContent | null {
  if (draft.format === "markdown" || draft.format === "text") return { format: draft.format, body: draft.body };
  const parsed = parseJsonText(draft.json);
  if (!parsed.ok) return null;
  return draft.format === "json"
    ? { format: "json", data: parsed.value }
    : { format: "mixed", body: draft.body, data: parsed.value };
}

/** WP06 T3 staged bytes of inline content. */
export function stagedBytesOf(content: InlineReportContent): Uint8Array {
  if ("data" in content) {
    return "body" in content ? stagedBytes("mixed", content.body, content.data) : stagedBytes("json", undefined, content.data);
  }
  return stagedBytes(content.format, content.body);
}

/** The publish fields of a valid draft (title trimmed; empty optional fields left out). */
export function publishFields(draft: ReportDraft): {
  readonly title: string;
  readonly type?: string;
  readonly topics?: readonly string[];
  readonly tags?: readonly string[];
  readonly summary?: string;
  readonly reportDate?: string;
} {
  const type = draft.type.trim();
  const topics = splitTerms(draft.topics);
  const tags = splitTerms(draft.tags);
  const summary = draft.summary.trim();
  return {
    title: draft.title.trim(),
    ...(type ? { type } : {}),
    ...(topics.length > 0 ? { topics } : {}),
    ...(tags.length > 0 ? { tags } : {}),
    ...(summary ? { summary } : {}),
    ...(draft.reportDate ? { reportDate: draft.reportDate } : {}),
  };
}

/** The draft text of JSON data. */
export const jsonText = (data: unknown) => (data === undefined ? "" : JSON.stringify(data, null, 2));

/** The metadata half of a draft from a read report (content fields left empty). */
export function metadataDraft(report: {
  readonly title: string;
  readonly type: string | null;
  readonly topics: readonly string[];
  readonly tags: readonly string[];
  readonly summary: string | null;
  readonly report_date: string | null;
  readonly content: { readonly format: ReportFormat };
}): ReportDraft {
  return {
    ...EMPTY_DRAFT,
    title: report.title,
    format: report.content.format,
    type: report.type ?? "",
    topics: report.topics.join(", "),
    tags: report.tags.join(", "),
    summary: report.summary ?? "",
    reportDate: report.report_date ?? "",
  };
}

/** The draft's content fields set from a body/data pair. */
export function withContent(draft: ReportDraft, content: { readonly body?: string; readonly data?: unknown }): ReportDraft {
  return { ...draft, body: content.body ?? "", json: jsonText(content.data) };
}

export type ClearableField = "type" | "summary" | "reportDate";

export interface ReportChange {
  readonly patch: ReportPatch;
  readonly clearFields: readonly ClearableField[];
}

function sameData(left: string, right: string): boolean {
  const a = parseJsonText(left);
  const b = parseJsonText(right);
  if (!a.ok || !b.ok) return left === right;
  return JSON.stringify(a.value) === JSON.stringify(b.value);
}

/** Whether the draft's content differs from the baseline's. */
export function contentChanged(baseline: ReportDraft, draft: ReportDraft): boolean {
  if (draft.format !== baseline.format) return true;
  if (usesBody(draft.format) && draft.body !== baseline.body) return true;
  if (usesData(draft.format) && !sameData(baseline.json, draft.json)) return true;
  return false;
}

/**
 * Only what changed (edit): each changed field in `patch`, each emptied
 * optional field in `clearFields` (never both). Content is considered only
 * when it was loaded and editable.
 */
export function buildPatch(
  baseline: ReportDraft,
  draft: ReportDraft,
  options: { readonly content: boolean },
): ReportChange {
  const patch: { -readonly [K in keyof ReportPatch]: ReportPatch[K] } = {};
  const clearFields: ClearableField[] = [];
  if (draft.title !== baseline.title && draft.title.trim() !== baseline.title) patch.title = draft.title.trim();
  if (options.content && contentChanged(baseline, draft)) {
    const content = contentOf(draft);
    if (content) patch.content = content;
  }
  const optional = (field: ClearableField, set: (value: string) => void) => {
    const now = draft[field];
    const before = baseline[field];
    if (now === before || now.trim() === before) return;
    if (now.trim() === "") {
      if (before !== "") clearFields.push(field);
      return;
    }
    set(now.trim());
  };
  optional("type", (value) => { patch.type = value; });
  optional("summary", (value) => { patch.summary = value; });
  optional("reportDate", (value) => { patch.reportDate = value; });
  for (const field of ["topics", "tags"] as const) {
    const now = splitTerms(draft[field]);
    if (JSON.stringify(now) !== JSON.stringify(splitTerms(baseline[field]))) patch[field] = now;
  }
  return { patch, clearFields };
}

export const isNoChange = (change: ReportChange) =>
  Object.keys(change.patch).length === 0 && change.clearFields.length === 0;

// --- the local file picker -------------------------------------------------------

export type FileRead = { readonly ok: true; readonly text: string } | { readonly ok: false; readonly message: string };

function readBytes(file: Blob): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (result === null || typeof result === "string") reject(new Error("unreadable"));
      else resolve(result);
    };
    reader.onerror = () => reject(new Error("unreadable"));
    reader.readAsArrayBuffer(file);
  });
}

/**
 * Read one local file as UTF-8 text, in the browser (FileReader). Nothing is
 * uploaded, and the file's name or path is never used. A file larger than one
 * transfer may stage, or one that is not UTF-8 text, is refused.
 */
export async function readTextFile(file: Blob): Promise<FileRead> {
  if (file.size > MAX_STAGED_BYTES) return { ok: false, message: FORM_MESSAGES.fileTooLarge };
  let buffer: ArrayBuffer;
  try {
    buffer = await readBytes(file);
  } catch {
    return { ok: false, message: FORM_MESSAGES.fileUnreadable };
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(buffer));
  } catch {
    return { ok: false, message: FORM_MESSAGES.fileNotText };
  }
  if (text.includes("\u0000")) return { ok: false, message: FORM_MESSAGES.fileNotText };
  return { ok: true, text };
}

// --- the editor -------------------------------------------------------------------

function LabeledInput({
  label,
  hint,
  error,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { readonly label: string; readonly hint?: ReactNode; readonly error?: string }) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-text-primary">
        {label}
        {props.required ? <span className="ml-1 font-normal text-muted" aria-hidden="true">(required)</span> : null}
      </label>
      <Input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        {...props}
      />
      {hint ? <p id={hintId} className="text-xs text-muted">{hint}</p> : null}
      {error ? <p id={errorId} role="alert" className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}

export function ReportFieldsEditor({
  draft,
  onChange,
  errors,
  contentEditable,
  contentNotice,
  disabled,
}: {
  readonly draft: ReportDraft;
  readonly onChange: (next: ReportDraft) => void;
  /** Shown once the user tried to submit. */
  readonly errors: DraftErrors;
  /** False while an edit's large content is not loaded: content controls are not shown. */
  readonly contentEditable: boolean;
  readonly contentNotice?: ReactNode;
  readonly disabled: boolean;
}) {
  const formatId = useId();
  const fileId = useId();
  const [preview, setPreview] = useState(false);
  const [fileMessage, setFileMessage] = useState<string | null>(null);
  const set = (patch: Partial<ReportDraft>) => onChange({ ...draft, ...patch });

  async function pickFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    const read = await readTextFile(file);
    if (!read.ok) {
      setFileMessage(read.message);
      return;
    }
    setFileMessage(null);
    onChange(draft.format === "json" ? { ...draft, json: read.text } : { ...draft, body: read.text });
  }

  const previewContent = contentEditable && preview ? contentOf(draft) : null;
  const typeTrimmed = draft.type.trim();

  return (
    <div className="grid gap-4">
      <LabeledInput
        label="Title"
        required
        value={draft.title}
        disabled={disabled}
        error={errors.title}
        onChange={(event) => set({ title: event.target.value })}
      />
      {contentEditable ? (
        <fieldset className="grid gap-3 rounded-lg border border-border p-3" aria-label="Content">
          <legend className="px-1 text-sm font-medium">Content</legend>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={formatId} className="text-sm font-medium">Format</label>
            <Select
              id={formatId}
              value={draft.format}
              disabled={disabled}
              onChange={(event) => set({ format: event.target.value as ReportFormat })}
            >
              {FORMATS.map((format) => <option key={format.value} value={format.value}>{format.label}</option>)}
            </Select>
            <Button size="sm" variant="ghost" aria-pressed={preview} onClick={() => setPreview((value) => !value)}>
              {preview ? "Back to editing" : "Preview"}
            </Button>
          </div>
          {preview ? (
            <div data-testid="report-form-preview" className="rounded-lg border border-border-subtle p-3">
              {previewContent ? (
                <RenderedReportContent
                  format={previewContent.format}
                  body={"body" in previewContent ? previewContent.body : undefined}
                  data={"data" in previewContent ? previewContent.data : undefined}
                />
              ) : (
                <p className="text-sm text-text-muted">Fix the JSON data to see a preview.</p>
              )}
            </div>
          ) : (
            <>
              {usesBody(draft.format) ? (
                <TextField
                  label={draft.format === "mixed" ? "Text" : "Body"}
                  rows={12}
                  value={draft.body}
                  disabled={disabled}
                  onChange={(event) => set({ body: event.target.value })}
                />
              ) : null}
              {usesData(draft.format) ? (
                <TextField
                  label="JSON data"
                  rows={10}
                  className="font-mono"
                  value={draft.json}
                  disabled={disabled}
                  error={errors.json}
                  spellCheck={false}
                  onChange={(event) => set({ json: event.target.value })}
                />
              ) : null}
              <div className="flex flex-col gap-1">
                <label htmlFor={fileId} className="text-sm font-medium">
                  {draft.format === "json" ? "Read JSON from a local file" : "Read text from a local file"}
                </label>
                <input
                  id={fileId}
                  type="file"
                  accept=".md,.markdown,.txt,.json,text/plain,text/markdown,application/json"
                  disabled={disabled}
                  className="text-sm"
                  aria-describedby={`${fileId}-hint`}
                  onChange={(event) => void pickFile(event)}
                />
                <p id={`${fileId}-hint`} className="text-xs text-muted">
                  The file is read into the editor on this device; it is not uploaded. Up to 16 MB of text.
                </p>
                {fileMessage ? <p role="alert" className="text-xs text-destructive">{fileMessage}</p> : null}
              </div>
            </>
          )}
        </fieldset>
      ) : contentNotice}
      <LabeledInput
        label="Type"
        value={draft.type}
        disabled={disabled}
        hint={typeTrimmed !== "" && !TYPE_PATTERN.test(typeTrimmed)
          ? "Types are usually lower-case letters, digits and underscores, starting with a letter (for example weekly_note). The server decides."
          : "Optional. Lower-case letters, digits and underscores, starting with a letter."}
        onChange={(event) => set({ type: event.target.value })}
      />
      <LabeledInput
        label="Topics"
        value={draft.topics}
        disabled={disabled}
        hint="Optional. Separate topics with commas."
        error={errors.topics}
        onChange={(event) => set({ topics: event.target.value })}
      />
      <LabeledInput
        label="Tags"
        value={draft.tags}
        disabled={disabled}
        hint="Optional. Separate tags with commas."
        error={errors.tags}
        onChange={(event) => set({ tags: event.target.value })}
      />
      <TextField
        label="Summary"
        rows={3}
        value={draft.summary}
        disabled={disabled}
        error={errors.summary}
        onChange={(event) => set({ summary: event.target.value })}
      />
      <LabeledInput
        label="Report date"
        type="date"
        value={draft.reportDate}
        disabled={disabled}
        hint="Optional."
        onChange={(event) => set({ reportDate: event.target.value })}
      />
    </div>
  );
}

/** The breadcrumb of the form pages. */
export function FormBreadcrumb({ trail }: { readonly trail: readonly { readonly label: string; readonly href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-2 text-sm">
      <ol className="flex flex-wrap items-center gap-1 text-text-muted">
        {trail.map((step, index) => (
          <li key={`${index}:${step.label}`} className="flex items-center gap-1">
            {index > 0 ? <span aria-hidden="true">›</span> : null}
            {step.href
              ? <Link href={step.href} className="underline underline-offset-2">{step.label}</Link>
              : <span aria-current="page" className="text-text-primary">{step.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}
