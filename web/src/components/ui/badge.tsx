import type { ReactNode } from "react";

type Tone = "neutral" | "green" | "gold" | "coral" | "synthetic";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-moss-sand text-moss-slate border-border",
  green: "bg-moss-green/10 text-moss-everglade border-moss-green/30",
  gold: "bg-moss-gold/10 text-moss-gold border-moss-gold/30",
  coral: "bg-moss-coral/10 text-moss-coral border-moss-coral/30",
  synthetic: "bg-moss-gold/15 text-moss-gold border-moss-gold/40",
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
