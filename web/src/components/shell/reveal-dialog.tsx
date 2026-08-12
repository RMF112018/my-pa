"use client";

/**
 * Reveal — "why am I seeing this?" disclosure affordance.
 *
 * WP-02 posts to the stub `/api/reveal` route and shows the returned
 * synthetic disclosure. Real evidence traversal arrives with later
 * work packages; the affordance and its honesty contract are pinned now.
 */
import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api/client";
import type { DisclosureEnvelope } from "@/contracts/envelope";

interface RevealResponse {
  disclosure: DisclosureEnvelope;
  reason: string;
}

export function RevealDialog({
  open,
  onClose,
  subjectId,
}: {
  open: boolean;
  onClose: () => void;
  subjectId: string;
}) {
  const [result, setResult] = useState<RevealResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");

  async function reveal() {
    setStatus("loading");
    try {
      const response = await apiPost<RevealResponse>({ hasSession: true }, "/api/reveal", {
        subjectId,
      });
      if (response.ok && response.data) {
        setResult(response.data);
        setStatus("idle");
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Why am I seeing this?">
      <div className="flex flex-col gap-3 text-sm text-moss-slate">
        {result ? (
          <>
            <p data-testid="reveal-reason">{result.reason}</p>
            <p className="text-xs text-muted">
              Coverage: {result.disclosure.coverage}. {result.disclosure.limitations.join(" ")}
            </p>
          </>
        ) : (
          <p className="text-muted">
            Reveal shows the evidence and reasoning behind an item. Nothing is hidden from you.
          </p>
        )}
        {status === "error" ? (
          <p role="alert" className="text-moss-coral">
            Reveal failed.
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={reveal} disabled={status === "loading"}>
            {status === "loading" ? "Loading…" : "Reveal"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
