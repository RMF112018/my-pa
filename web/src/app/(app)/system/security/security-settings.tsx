"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { SurfaceState } from "@/components/ui/surface-state";
import { createPasskey, getPasskey, webAuthnSupported, WebAuthnBrowserError } from "@/lib/auth/webauthn-ceremony";

interface CredentialRow {
  readonly credentialId: string;
  readonly label: string | null;
  readonly createdAt: string;
  readonly lastUsedAt: string | null;
}

function messageFor(code: string): string {
  switch (code) {
    case "unsupported":
      return "This browser does not support passkeys.";
    case "cancelled":
      return "The passkey prompt was cancelled.";
    case "step_up_required":
      return "Confirm with a passkey before continuing.";
    case "duplicate_credential":
      return "That passkey is already registered.";
    case "last_passkey_requires_recovery":
      return "Add recovery codes before removing the last passkey.";
    case "invalid_challenge":
      return "The sign-in challenge expired. Try again.";
    default:
      return "The security action could not be completed.";
  }
}

async function post(action: string, body: Record<string, unknown> = {}): Promise<Response> {
  return fetch(`/api/webauthn/${action}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function SecuritySettings() {
  const [credentials, setCredentials] = useState<CredentialRow[]>([]);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const supported = webAuthnSupported();

  const refresh = useCallback(async () => {
    const response = await post("credentials/list");
    if (!response.ok) return;
    const payload = (await response.json()) as { credentials: CredentialRow[] };
    setCredentials(payload.credentials);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function withStepUp(): Promise<string | null> {
    const optionsResponse = await post("step-up/options");
    if (!optionsResponse.ok) {
      setStatus(messageFor((await optionsResponse.json() as { error?: { code?: string } }).error?.code ?? "failed"));
      return null;
    }
    const options = (await optionsResponse.json()) as Record<string, unknown>;
    const assertion = await getPasskey(options);
    const complete = await post("step-up/complete", { credential: assertion });
    if (!complete.ok) {
      setStatus(messageFor((await complete.json() as { error?: { code?: string } }).error?.code ?? "failed"));
      return null;
    }
    const payload = (await complete.json()) as { administrationGrant: string };
    return payload.administrationGrant;
  }

  async function enroll() {
    setBusy(true);
    setStatus(null);
    try {
      const optionsResponse = await post("registration/options");
      if (!optionsResponse.ok) {
        setStatus(messageFor((await optionsResponse.json() as { error?: { code?: string } }).error?.code ?? "failed"));
        return;
      }
      const options = (await optionsResponse.json()) as Record<string, unknown>;
      const credential = await createPasskey(options);
      const complete = await post("registration/complete", { credential, label: "Passkey" });
      if (!complete.ok) {
        setStatus(messageFor((await complete.json() as { error?: { code?: string } }).error?.code ?? "failed"));
        return;
      }
      await refresh();
      setStatus("Passkey added.");
    } catch (error) {
      setStatus(messageFor(error instanceof WebAuthnBrowserError ? error.code : "failed"));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(credentialId: string) {
    setBusy(true);
    setStatus(null);
    try {
      const grant = await withStepUp();
      if (!grant) return;
      const response = await post("credentials/revoke", { credentialId, administrationGrant: grant });
      if (!response.ok) {
        setStatus(messageFor((await response.json() as { error?: { code?: string } }).error?.code ?? "failed"));
        return;
      }
      await refresh();
      setStatus("Passkey revoked.");
    } catch (error) {
      setStatus(messageFor(error instanceof WebAuthnBrowserError ? error.code : "failed"));
    } finally {
      setBusy(false);
    }
  }

  async function issueRecovery() {
    setBusy(true);
    setStatus(null);
    try {
      const grant = await withStepUp();
      if (!grant) return;
      const response = await post("recovery/issue", { administrationGrant: grant });
      if (!response.ok) {
        setStatus(messageFor((await response.json() as { error?: { code?: string } }).error?.code ?? "failed"));
        return;
      }
      const payload = (await response.json()) as { codes: string[] };
      setCodes(payload.codes);
      setStatus("Store these recovery codes now. They will not be shown again.");
    } catch (error) {
      setStatus(messageFor(error instanceof WebAuthnBrowserError ? error.code : "failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {!supported ? (
        <SurfaceState
          kind="unavailable"
          title="Passkeys unavailable"
          detail="This browser does not expose the Web Authentication API."
        />
      ) : null}
      {status ? (
        <p role="status" className="text-sm">
          {status}
        </p>
      ) : null}
      <Card>
        <CardTitle>Passkeys</CardTitle>
        <CardBody>
          {credentials.length === 0 ? (
            <p>No passkeys are registered yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {credentials.map((item) => (
                <li key={item.credentialId} className="flex flex-wrap items-center justify-between gap-2">
                  <span>{item.label ?? "Passkey"}</span>
                  <Button
                    type="button"
                    disabled={busy}
                    onClick={() => void revoke(item.credentialId)}
                  >
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <Button className="mt-4 min-h-11" type="button" disabled={busy || !supported} onClick={() => void enroll()}>
            Add a passkey
          </Button>
        </CardBody>
      </Card>
      <Card>
        <CardTitle>Recovery codes</CardTitle>
        <CardBody>
          <p>One-time codes. They are hashed on the server and shown only once.</p>
          {codes ? (
            <ol className="mt-3 grid grid-cols-1 gap-2 font-mono text-sm sm:grid-cols-2">
              {codes.map((code) => (
                <li key={code}>{code}</li>
              ))}
            </ol>
          ) : null}
          <Button className="mt-4 min-h-11" type="button" disabled={busy} onClick={() => void issueRecovery()}>
            Generate recovery codes
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
