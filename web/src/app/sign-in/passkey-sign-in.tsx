"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  getPasskey,
  WebAuthnBrowserError,
} from "@/lib/auth/webauthn-ceremony";
import { safeReturnPath } from "@/lib/auth/return-path";

type AuthState = "uninitialized" | "ready" | "inconsistent" | "unavailable";

const CONNECTION_REQUIRED = "A connection is required.";
const OPERATOR_GUIDANCE =
  "Sign-in is unavailable until an operator restores a consistent authentication state.";

function isOnline(): boolean {
  return typeof navigator === "undefined" || navigator.onLine;
}

export function PasskeySignIn() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(isOnline);

  useEffect(() => {
    function sync() {
      const next = navigator.onLine;
      setOnline(next);
      if (!next) {
        setCode("");
        setStatus(CONNECTION_REQUIRED);
      }
    }
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
      setCode("");
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!navigator.onLine) {
        if (!cancelled) setAuthState("unavailable");
        return;
      }
      try {
        const response = await fetch("/api/webauthn/auth-state", {
          method: "POST",
          credentials: "same-origin",
          headers: { "content-type": "application/json" },
          body: "{}",
        });
        if (!response.ok) {
          if (!cancelled) setAuthState("unavailable");
          return;
        }
        const payload = (await response.json()) as { state?: unknown };
        if (payload.state === "uninitialized" || payload.state === "ready" || payload.state === "inconsistent") {
          if (!cancelled) setAuthState(payload.state);
          return;
        }
        if (!cancelled) setAuthState("unavailable");
      } catch {
        if (!cancelled) setAuthState("unavailable");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  function destination(fallback: string): string {
    return safeReturnPath(searchParams.get("next")) ?? fallback;
  }

  async function authenticate() {
    setBusy(true);
    setStatus(null);
    try {
      if (!navigator.onLine) {
        setStatus(CONNECTION_REQUIRED);
        return;
      }
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
      router.push(destination("/today"));
      router.refresh();
    } catch (error) {
      setStatus(
        error instanceof TypeError
          ? CONNECTION_REQUIRED
          : error instanceof WebAuthnBrowserError && error.code === "cancelled"
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
    if (!navigator.onLine) {
      setCode("");
      setStatus(CONNECTION_REQUIRED);
      setBusy(false);
      return;
    }
    const presented = code;
    setCode("");
    const response = await fetch("/api/webauthn/recovery/consume", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: presented }),
    });
    if (!response.ok) {
      setStatus("Recovery failed.");
      setBusy(false);
      return;
    }
    router.push(destination("/system/security"));
    router.refresh();
  }

  if (!online || authState === "unavailable") {
    return (
      <p role="alert" className="mt-6 text-sm" data-testid="auth-state-unavailable">
        {!online ? CONNECTION_REQUIRED : OPERATOR_GUIDANCE}
      </p>
    );
  }

  if (authState === null) {
    return (
      <p className="mt-6 text-sm" data-testid="auth-state-loading">
        Checking sign-in readiness.
      </p>
    );
  }

  if (authState === "uninitialized") {
    return (
      <section className="mt-6 flex flex-col gap-3" data-testid="owner-setup-required">
        <p>Owner setup is required before anyone can sign in.</p>
        <Link className="text-moss-green underline" href="/setup">
          Continue to owner setup
        </Link>
      </section>
    );
  }

  if (authState === "inconsistent") {
    return (
      <p role="alert" className="mt-6 text-sm" data-testid="auth-state-inconsistent">
        {OPERATOR_GUIDANCE}
      </p>
    );
  }

  return (
    <section className="mt-6 flex flex-col gap-3" aria-label="Passkey and recovery">
      <Button type="button" disabled={busy} onClick={() => void authenticate()}>
        Sign in with a passkey
      </Button>
      <form className="flex flex-col gap-2" onSubmit={(event) => void recover(event)} autoComplete="off">
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
