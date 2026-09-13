import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { AppShell } from "@/components/shell/app-shell";
import { DEFAULT_PROJECT_SCOPE_RESOLUTION } from "@/lib/project-scope/resolver";

/**
 * Signed-in layout. Middleware already guards these routes; this layout
 * re-verifies server-side (defense in depth) and supplies the principal
 * to the shell. No identity ever comes from the client.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) {
    redirect("/sign-in");
  }
  // Fail closed until the canonical `continuity.projects.read` decoder and
  // exact-read BFF adapter are integrated. A Project preference must never be
  // trusted merely because the browser supplied a well-shaped cookie.
  return (
    <AppShell principal={principal} initialProjectScope={DEFAULT_PROJECT_SCOPE_RESOLUTION}>
      {children}
    </AppShell>
  );
}
