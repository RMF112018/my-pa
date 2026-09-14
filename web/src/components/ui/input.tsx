import { forwardRef, type InputHTMLAttributes } from "react";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className = "", ...props }, ref) {
  return <input ref={ref} className={`min-h-[var(--control-height)] w-full min-w-0 max-w-full rounded-[var(--radius-md)] border border-border-subtle bg-surface px-3 text-[length:var(--control-font-size)] leading-[var(--control-line-height)] text-text-primary placeholder:text-text-muted disabled:opacity-60 ${className}`} {...props} />;
});
