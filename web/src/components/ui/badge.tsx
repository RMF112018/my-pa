import type { ReactNode } from "react";

type Tone = "neutral" | "green" | "gold" | "coral" | "synthetic";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-subtle text-text-primary border-border",
  green: "bg-success/10 text-success border-success/30",
  gold: "bg-brand-accent-subtle text-brand-accent border-brand-accent/30",
  coral: "bg-destructive/10 text-destructive border-destructive/30",
  synthetic: "bg-brand-accent-subtle text-brand-accent border-brand-accent/40",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
