import { forwardRef, useId, type ReactNode, type TextareaHTMLAttributes } from "react";

export interface TextFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: ReactNode;
}

/** Labeled multi-line text field. The label is always visible and associated. */
export const TextField = forwardRef<HTMLTextAreaElement, TextFieldProps>(function TextField(
  { label, hint, id, ...props },
  ref,
) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={fieldId} className="text-sm font-medium text-moss-slate">
        {label}
      </label>
      <textarea
        ref={ref}
        id={fieldId}
        aria-describedby={hintId}
        className="min-h-24 rounded-md border border-border bg-surface p-2 text-sm text-moss-slate"
        {...props}
      />
      {hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
});
