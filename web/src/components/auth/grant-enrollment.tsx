"use client";

/**
 * First-user bootstrap and operator-recovery share one grant → create → complete
 * ceremony. The grant and one-time recovery codes live in React state only.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { createPasskey, WebAuthnBrowserError } from "@/lib/auth/webauthn-ceremony";

const INVALID_GRANT = "That grant is not valid.";
const CONNECTION_REQUIRED = "A connection is required.";

export type GrantEnrollmentKind = "bootstrap" | "operator-recovery";

function optionsPath(kind: GrantEnrollmentKind): string {
  return kind === "bootstrap"
    ? "/api/webauthn/bootstrap/registration/options"
    : "/api/webauthn/operator-recovery/registration/options";
}

function completePath(kind: GrantEnrollmentKind): string {
  return kind === "bootstrap"
    ? "/api/webauthn/bootstrap/registration/complete"
    : "/api/webauthn/operator-recovery/registration/complete";
}

function isOnline(): boolean {
  return typeof navigator === "undefined" || navigator.onLine;
}

export function GrantEnrollment({
  kind,
  grantLabel,
  submitLabel,
}: {
  kind: GrantEnrollmentKind;
  grantLabel: string;
  submitLabel: string;
}) {
  const router = useRouter();
  const [grant, setGrant] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(isOnline);

  useEffect(() => {
    function sync() {
      const next = navigator.onLine;
      setOnline(next);
      if (!next) {
        setGrant("");
        setCodes(null);
        setStatus(CONNECTION_REQUIRED);
      }
    }
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
      setGrant("");
      setCodes(null);
    };
  }, []);

  async function enroll(event: React.FormEvent) {
    event.preventDefault();
    if (!navigator.onLine) {
      setGrant("");
      setStatus(CONNECTION_REQUIRED);
      return;
    }
    setBusy(true);
    setStatus(null);
    let presented = grant;
    setGrant("");
    try {
      const optionsResponse = await fetch(optionsPath(kind), {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ grant: presented }),
      });
      presented = "";
      if (!optionsResponse.ok) {
        setStatus(optionsResponse.status >= 500 ? CONNECTION_REQUIRED : INVALID_GRANT);
        return;
      }
      const options = (await optionsResponse.json()) as Record<string, unknown>;
      const credential = await createPasskey(options);
      const complete = await fetch(completePath(kind), {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ credential }),
      });
      if (!complete.ok) {
        setStatus(complete.status >= 500 ? CONNECTION_REQUIRED : INVALID_GRANT);
        return;
      }
      const payload = (await complete.json()) as { codes?: string[] };
      if (Array.isArray(payload.codes) && payload.codes.every((item) => typeof item === "string")) {
        setCodes(payload.codes);
        setStatus("Store these recovery codes now. They will not be shown again.");
        return;
      }
      router.push("/today");
      router.refresh();
    } catch (error) {
      if (error instanceof TypeError) {
        setStatus(CONNECTION_REQUIRED);
      } else {
        setStatus(
          error instanceof WebAuthnBrowserError && error.code === "cancelled"
            ? "The passkey prompt was cancelled."
            : error instanceof WebAuthnBrowserError && error.code === "unsupported"
              ? "This browser does not support passkeys."
              : CONNECTION_REQUIRED,
        );
      }
    } finally {
      presented = "";
      setBusy(false);
    }
  }

  function continueIntoApp() {
    setCodes(null);
    router.push("/today");
    router.refresh();
  }

  if (!online) {
    return (
      <p role="alert" className="text-sm">
        {CONNECTION_REQUIRED}
      </p>
    );
  }

  if (codes) {
    return (
      <div className="flex flex-col gap-3">
        {status ? (
          <p role="status" className="text-sm">
            {status}
          </p>
        ) : null}
        <ol className="grid grid-cols-1 gap-2 font-mono text-sm sm:grid-cols-2">
          {codes.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ol>
        <Button type="button" onClick={continueIntoApp}>
          Continue
        </Button>
      </div>
    );
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={(event) => void enroll(event)} autoComplete="off">
      <label className="text-sm" htmlFor={`${kind}-grant`}>
        {grantLabel}
      </label>
      <input
        id={`${kind}-grant`}
        name="grant"
        autoComplete="off"
        spellCheck={false}
        className="min-h-11 rounded-md border border-border bg-surface px-3 text-sm"
        value={grant}
        onChange={(event) => setGrant(event.target.value)}
      />
      <Button type="submit" disabled={busy || grant.length === 0}>
        {submitLabel}
      </Button>
      {status ? (
        <p role="alert" className="text-sm">
          {status}
        </p>
      ) : null}
    </form>
  );
}
