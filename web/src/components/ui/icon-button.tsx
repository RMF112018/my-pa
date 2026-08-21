import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

export const IconButton = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }>(function IconButton({ label, children, className = "", type = "button", ...props }, ref) {
  return <button ref={ref} type={type} aria-label={label} className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--radius-md)] text-text-secondary hover:bg-surface-subtle ${className}`} {...props}>{children}</button>;
});
