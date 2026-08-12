"use client";

/**
 * The sign-in screen's interactive half.
 *
 * It renders the principals it is handed and knows of no others. The admissible
 * set is resolved on the server by `page.tsx` from `MYPA_GATEWAY_AUTH_MODE`,
 * which is server configuration a browser must never see, so this component
 * takes the answer rather than computing it — and takes only `key` and `label`,
 * never the claims, which stay on the server where they are validated.
 *
 * A button for a principal `POST /api/session` would refuse is not offered
 * (`D-15`): showing a person a control that is guaranteed to fail is a worse
 * failure UX than not showing it, and the two halves are consistent because they
 * read the same set.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

export interface OfferedPrincipal {
  readonly key: string;
  readonly label: string;
}

export function SignInForm({ principals }: { principals: readonly OfferedPrincipal[] }) {
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
    <>
      <div className="mt-4 flex flex-col gap-2">
        {principals.map((p) => (
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
    </>
  );
}
