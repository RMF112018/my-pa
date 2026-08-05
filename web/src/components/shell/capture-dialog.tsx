"use client";

/**
 * Capture — the one-field, always-available entry point.
 *
 * WP-02 posts to the stub `/api/capture` route, which acknowledges receipt
 * with a synthetic-coverage disclosure. Real capture semantics (source
 * spans, proposals) arrive in WP-03; the affordance and its contract are
 * pinned now.
 */
import { useEffect, useRef, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { apiPost } from "@/lib/api/client";

interface CaptureAck {
  receiptId: string;
  status: string;
}

export function CaptureDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const fieldRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setStatus("idle");
      // Move focus into the single capture field once the dialog is open.
      const t = setTimeout(() => fieldRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
  }, [open]);

  async function save() {
    if (!text.trim()) return;
    setStatus("saving");
    try {
      const result = await apiPost<CaptureAck>({ hasSession: true }, "/api/capture", {
        text: text.trim(),
        mode: "text",
      });
      if (result.ok) {
        setStatus("saved");
        setText("");
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Capture">
      <div className="flex flex-col gap-3">
        <TextField
          ref={fieldRef}
          label="What happened?"
          hint="Mode: text. Captured items are held for review — nothing is asserted on your behalf."
          value={text}
          onChange={(e) => setText(e.target.value)}
          data-testid="capture-field"
        />
        {status === "saved" ? (
          <p role="status" className="text-sm text-moss-green">
            Captured. It will appear in Review.
          </p>
        ) : null}
        {status === "error" ? (
          <p role="alert" className="text-sm text-moss-coral">
            Capture failed. Nothing was saved.
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={save} disabled={status === "saving" || !text.trim()}>
            {status === "saving" ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
