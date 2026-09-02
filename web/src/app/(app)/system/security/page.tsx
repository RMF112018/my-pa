import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { SecuritySettings } from "@/app/(app)/system/security/security-settings";

export const metadata = { title: "Security — my-pa" };
export const dynamic = "force-dynamic";

export default async function SecurityPage() {
  const token = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  const principal = await resolveSessionPrincipal(token);
  if (!principal) redirect("/sign-in");
  return (
    <main id="main" className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Security</h1>
        <p className="mt-2 text-sm">
          Passkeys sign you in with this device. Recovery codes are shown once. Sensitive
          changes require a fresh passkey confirmation.
        </p>
      </header>
      <SecuritySettings />
    </main>
  );
}
