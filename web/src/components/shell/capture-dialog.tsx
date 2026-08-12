"use client";

/**
 * Capture — the one-field, always-available entry point.
 *
 * WP-03 semantics: every submission attempt carries a stable idempotency
 * key, minted when the attempt starts and kept across retries of the same
 * text, so a network-level replay returns the original receipt instead of
 * admitting a duplicate. Editing the text starts a new attempt with a new
 * key. The route scopes the key to the authenticated principal (ADR-005,
 * PKL-MYPA-D-WP03-001).
 */
import { useEffect, useRef, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { apiPost } from "@/lib/api/client";

interface CaptureAck {
  receiptId: string;
  created: boolean;
  status: string;
}

export function CaptureDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "replayed" | "error">("idle");
  const [receiptId, setReceiptId] = useState<string | null>(null);
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  // One idempotency key per submission attempt: minted at first save, kept
  // across retries of the same text, discarded when the text changes.
  const attemptKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (open) {
      setStatus("idle");
      setReceiptId(null);
      // Move focus into the single capture field once the dialog is open.
      const t = setTimeout(() => fieldRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
  }, [open]);

  async function save() {
    if (!text.trim()) return;
    setStatus("saving");
    if (!attemptKeyRef.current) {
      attemptKeyRef.current = `cap-${crypto.randomUUID()}`;
    }
    try {
      const result = await apiPost<CaptureAck>({ hasSession: true }, "/api/capture", {
        text: text.trim(),
        mode: "text",
        idempotencyKey: attemptKeyRef.current,
      });
      if (result.ok && result.data) {
        setReceiptId(result.data.receiptId);
        setStatus(result.data.created ? "saved" : "replayed");
        setText("");
        attemptKeyRef.current = null;
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
          onChange={(e) => {
            setText(e.target.value);
            // Edited text is a new submission attempt, not a retry.
            attemptKeyRef.current = null;
          }}
          data-testid="capture-field"
        />
        {status === "saved" ? (
          <p role="status" className="text-sm text-moss-green">
            Captured. It will appear in Review.
            {receiptId ? <span className="ml-1 font-mono text-xs">({receiptId})</span> : null}
          </p>
        ) : null}
        {status === "replayed" ? (
          <p role="status" className="text-sm text-moss-green">
            Already captured — original receipt returned.
            {receiptId ? <span className="ml-1 font-mono text-xs">({receiptId})</span> : null}
          </p>
        ) : null}
        {status === "error" ? (
          <p role="alert" className="text-sm text-moss-coral">
            Capture failed. Nothing was saved. Retrying resubmits the same attempt.
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
