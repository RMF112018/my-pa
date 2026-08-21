import type { LucideIcon, LucideProps } from "lucide-react";

export function Icon({ icon: Glyph, label, ...props }: LucideProps & { icon: LucideIcon; label?: string }) {
  return <Glyph aria-hidden={label ? undefined : true} aria-label={label} focusable="false" {...props} />;
}
