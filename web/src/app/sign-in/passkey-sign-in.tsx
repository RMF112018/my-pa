"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  getPasskey,
  webAuthnSupported,
  WebAuthnBrowserError,
} from "@/lib/auth/webauthn-ceremony";

export function PasskeySignIn() {
  const [status, setStatus] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const supported = webAuthnSupported();

  async function authenticate() {
    setBusy(true);
    setStatus(null);
    try {
      const optionsResponse = await fetch("/api/webauthn/authentication/options", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: "{}",
      });
      if (!optionsResponse.ok) {
        setStatus("Passkey sign-in is not available.");
        return;
      }
      const options = (await optionsResponse.json()) as Record<string, unknown>;
      const credential = await getPasskey(options);
      const complete = await fetch("/api/webauthn/authentication/complete", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ credential }),
      });
      if (!complete.ok) {
        setStatus("Passkey sign-in failed.");
        return;
      }
      window.location.assign("/today");
    } catch (error) {
      setStatus(
        error instanceof WebAuthnBrowserError && error.code === "cancelled"
          ? "The passkey prompt was cancelled."
          : error instanceof WebAuthnBrowserError && error.code === "unsupported"
            ? "This browser does not support passkeys."
            : "Passkey sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function recover(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setStatus(null);
    const response = await fetch("/api/webauthn/recovery/consume", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!response.ok) {
      setStatus("Recovery failed.");
      setBusy(false);
      return;
    }
    window.location.assign("/system/security");
  }

  return (
    <section className="mt-6 flex flex-col gap-3" aria-label="Passkey and recovery">
      <Button type="button" disabled={busy || !supported} onClick={() => void authenticate()}>
        Sign in with a passkey
      </Button>
      <form className="flex flex-col gap-2" onSubmit={(event) => void recover(event)}>
        <label className="text-sm" htmlFor="recovery-code">
          Recovery code
        </label>
        <input
          id="recovery-code"
          name="code"
          autoComplete="off"
          className="min-h-11 rounded-md border border-border bg-surface px-3 text-sm"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        <Button type="submit" variant="secondary" disabled={busy}>
          Use a recovery code
        </Button>
      </form>
      {status ? (
        <p role="alert" className="text-sm">
          {status}
        </p>
      ) : null}
    </section>
  );
}
