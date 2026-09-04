import { forwardRef, useId, type ReactNode, type TextareaHTMLAttributes } from "react";

export interface TextFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: ReactNode;
  /** Visible error copy. Sets aria-invalid and is linked via aria-describedby. */
  error?: ReactNode;
  /** Explicit invalid state when error copy is not yet available. */
  invalid?: boolean;
}

/** Labeled multi-line text field. The label is always visible and associated. */
export const TextField = forwardRef<HTMLTextAreaElement, TextFieldProps>(function TextField(
  { label, hint, error, invalid, id, required, disabled, ...props },
  ref,
) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const isInvalid = Boolean(error) || invalid === true;

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={fieldId} className="text-sm font-medium text-moss-slate">
        {label}
        {required ? (
          <span className="ml-1 font-normal text-muted" aria-hidden="true">
            (required)
          </span>
        ) : null}
      </label>
      <textarea
        ref={ref}
        id={fieldId}
        required={required}
        disabled={disabled}
        aria-invalid={isInvalid || undefined}
        aria-describedby={describedBy}
        aria-required={required || undefined}
        className="min-h-24 rounded-md border border-border bg-surface p-2 text-sm text-moss-slate aria-[invalid=true]:border-moss-coral-strong"
        {...props}
      />
      {hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-moss-coral-strong">
          {error}
        </p>
      ) : null}
    </div>
  );
});
