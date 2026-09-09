import { forwardRef, type ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "accent";
type Size = "sm" | "md" | "lg";

const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    "bg-interactive text-on-interactive hover:bg-interactive-hover disabled:bg-interactive/50",
  secondary:
    "border border-interactive text-interactive bg-surface hover:bg-interactive-subtle disabled:opacity-50",
  ghost: "text-text-primary hover:bg-surface-subtle disabled:opacity-50",
  danger: "bg-destructive text-on-destructive hover:opacity-90 disabled:opacity-50",
  accent:
    "bg-brand-accent text-on-brand-accent hover:bg-brand-accent-hover disabled:bg-brand-accent/50",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  pending?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", pending = false, disabled, children, className = "", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      className={`inline-flex min-h-[var(--control-height)] items-center justify-center gap-2 rounded-[var(--radius-md)] text-sm font-medium disabled:cursor-not-allowed ${size === "sm" ? "px-3" : size === "lg" ? "px-5 text-base" : "px-4"} ${VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    >
      {pending ? <span aria-hidden="true">•••</span> : null}
      {children}
    </button>
  );
});
