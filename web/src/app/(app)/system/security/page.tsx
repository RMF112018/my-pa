import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { callWebAuthnGateway } from "@/lib/auth/webauthn-server";
import { PageHeader } from "@/components/shell/page-header";
import {
  SecuritySettings,
  type CredentialRow,
} from "@/app/(app)/system/security/security-settings";

export const metadata = { title: "Security — my-pa" };
export const dynamic = "force-dynamic";

export default async function SecurityPage() {
  const token = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  const principal = await resolveSessionPrincipal(token);
  if (!principal) redirect("/sign-in");
  const headerStore = await headers();
  const host = headerStore.get("x-forwarded-host") ?? headerStore.get("host") ?? "localhost";
  const proto = headerStore.get("x-forwarded-proto") ?? "http";
  const origin = `${proto}://${host}`;
  let initialCredentials: CredentialRow[] = [];
  try {
    const request = new Request(`${origin}/api/webauthn/credentials/list`, {
      method: "POST",
      headers: {
        origin,
        "content-type": "application/json",
        cookie: `${SESSION_COOKIE_NAME}=${token}`,
      },
    });
    const response = await callWebAuthnGateway("credentials/list", {}, request, principal);
    if (response.ok) {
      const payload = (await response.json()) as { credentials?: CredentialRow[] };
      initialCredentials = payload.credentials ?? [];
    }
  } catch {
    initialCredentials = [];
  }
  return (
    <section aria-labelledby="security-heading" className="mx-auto flex max-w-2xl flex-col gap-6">
      <PageHeader
        headingId="security-heading"
        title="Security"
        description="Passkeys sign you in with this device. Recovery codes are shown once. Sensitive changes require a fresh passkey confirmation."
      />
      <SecuritySettings initialCredentials={initialCredentials} />
    </section>
  );
}
