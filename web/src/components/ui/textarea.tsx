import { forwardRef, type TextareaHTMLAttributes } from "react";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className = "", ...props }, ref) {
  return <textarea ref={ref} className={`min-h-24 w-full rounded-[var(--radius-md)] border border-border-subtle bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted disabled:opacity-60 ${className}`} {...props} />;
});
