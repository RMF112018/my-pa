import { forwardRef, type SelectHTMLAttributes } from "react";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className = "", children, ...props }, ref) {
  return <select ref={ref} className={`min-h-[var(--control-height)] rounded-[var(--radius-md)] border border-border-subtle bg-surface px-3 text-sm ${className}`} {...props}>{children}</select>;
});
