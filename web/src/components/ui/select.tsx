import { forwardRef, type SelectHTMLAttributes } from "react";

/*
  `h-[var(--control-height)]` is not redundant beside `min-h-[…]`, and removing
  it reintroduces a real defect. WebKit does not honour `min-height` on a
  default-appearance `<select>` — it resolves the control down to its intrinsic
  height, which the `mobile-webkit` browser lane measures at 22–23 CSS px
  against the shell's 44px coarse target. A *definite* height is what fixes it.
  Chromium and Gecko already render 44px from `min-height` alone, so only that
  lane catches a removal.

  This lives on the primitive rather than on each caller deliberately: the
  44px coarse target is part of the shared contract downstream surfaces
  consume, and making every call site re-add its own guard is exactly the
  local redefinition that contract exists to prevent. `task-status-control`
  keeps its own explicit `h-11` — the same 2.75rem, stated there because its
  own sizing test guards it in the blocking unit job. A caller that needs a
  *taller* control still wins by passing `min-h-*`, which beats `height`.
*/
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className = "", children, ...props }, ref) {
  return <select ref={ref} className={`h-[var(--control-height)] min-h-[var(--control-height)] min-w-0 max-w-full rounded-[var(--radius-md)] border border-border-subtle bg-surface px-3 text-[length:var(--control-font-size)] leading-[var(--control-line-height)] ${className}`} {...props}>{children}</select>;
});
