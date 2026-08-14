"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

export function LocalOperatorSignInForm() {
  const router = useRouter();
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ operatorSecret: secret }),
      credentials: "same-origin",
    });
    setSecret("");
    if (response.ok) {
      router.push("/today");
      router.refresh();
      return;
    }
    setBusy(false);
    setError("Sign-in failed.");
  }

  return (
    <form className="mt-4 flex flex-col gap-3" onSubmit={signIn}>
      <label className="text-sm" htmlFor="operator-secret">
        Operator secret
      </label>
      <input
        id="operator-secret"
        name="operator-secret"
        type="password"
        autoComplete="current-password"
        required
        value={secret}
        onChange={(event) => setSecret(event.target.value)}
        className="rounded-md border border-border bg-surface px-3 py-2"
      />
      <Button type="submit" disabled={busy}>
        Sign in
      </Button>
      {error ? <p role="alert" className="text-sm text-moss-coral-strong">{error}</p> : null}
    </form>
  );
}
