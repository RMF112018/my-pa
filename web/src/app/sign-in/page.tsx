"use client";

/**
 * Sign-in — synthetic identity provider only in WP-02.
 *
 * The page names what it is: a development sign-in with fixed synthetic
 * principals. The real Entra/MSAL flow replaces this screen when a real
 * app registration exists (see `lib/auth/msal.config.ts`).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { SYNTHETIC_PRINCIPALS } from "@/lib/auth/synthetic";
import { Button } from "@/components/ui/button";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SignInPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(key: string) {
    setBusy(true);
    setError(null);
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ syntheticPrincipal: key }),
      credentials: "same-origin",
    });
    if (response.ok) {
      router.push("/today");
      router.refresh();
    } else {
      setBusy(false);
      setError("Sign-in failed. The synthetic provider rejected the request.");
    }
  }

  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-moss-green">my-pa</h1>
        <p className="mt-1 text-sm text-muted">MossAIc personal assistant</p>
      </div>
      <Card>
        <div className="flex items-center justify-between">
          <CardTitle>Sign in</CardTitle>
          <Badge tone="synthetic">Synthetic provider</Badge>
        </div>
        <CardBody>
          <p>
            No live Entra registration is configured. Choose a synthetic development principal.
            Identity is derived from validated claims only — never from anything you type.
          </p>
          <div className="mt-4 flex flex-col gap-2">
            {SYNTHETIC_PRINCIPALS.map((p) => (
              <Button
                key={p.key}
                variant="secondary"
                disabled={busy}
                onClick={() => signIn(p.key)}
                data-testid={`sign-in-${p.key}`}
              >
                {p.label}
              </Button>
            ))}
          </div>
          {error ? (
            <p role="alert" className="mt-3 text-sm text-moss-coral">
              {error}
            </p>
          ) : null}
        </CardBody>
      </Card>
    </main>
  );
}
