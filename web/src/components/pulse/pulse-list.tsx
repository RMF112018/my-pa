"use client";

import { useState } from "react";
import type { PulseItem } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RevealDialog } from "@/components/shell/reveal-dialog";

export function PulseList({ items }: { items: readonly PulseItem[] }) {
  const [revealSubject, setRevealSubject] = useState<string | null>(null);

  if (items.length === 0) {
    return <p className="text-sm text-muted">Nothing needs your attention right now.</p>;
  }

  return (
    <ul className="flex flex-col gap-3">
      {items.map((item) => (
        <li key={item.pulseItemId}>
          <Card data-testid="pulse-item">
            <div className="flex items-start justify-between gap-2">
              <CardTitle>{item.title}</CardTitle>
              {item.disclosure.coverage === "synthetic" ? (
                <Badge tone="synthetic">Synthetic</Badge>
              ) : null}
            </div>
            <CardBody>
              <p>
                <span className="font-medium text-moss-slate">Why:</span> {item.reason}
              </p>
              <p className="mt-1">
                <span className="font-medium text-moss-slate">If ignored:</span>{" "}
                {item.consequence}
              </p>
              {item.uncertainty ? (
                <p className="mt-1 text-moss-gold-strong">
                  <span className="font-medium">Uncertain:</span> {item.uncertainty}
                </p>
              ) : null}
              <p className="mt-1">
                <span className="font-medium text-moss-slate">Next step:</span> {item.nextStep}
              </p>
              <div className="mt-3">
                <Button
                  variant="secondary"
                  onClick={() => setRevealSubject(item.pulseItemId)}
                  data-testid={`reveal-${item.pulseItemId}`}
                >
                  Why am I seeing this?
                </Button>
              </div>
            </CardBody>
          </Card>
        </li>
      ))}
      <RevealDialog
        open={revealSubject !== null}
        onClose={() => setRevealSubject(null)}
        subjectId={revealSubject ?? ""}
      />
    </ul>
  );
}
