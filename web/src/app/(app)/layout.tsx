import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  parseOpaqueSessionSid,
  SESSION_COOKIE_NAME,
  sessionReplayBinding,
} from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { AppShell } from "@/components/shell/app-shell";
import { invokeGateway } from "@/lib/api/gateway";
import { PROJECT_SCOPE_COOKIE } from "@/lib/project-scope/preference";
import { resolveServerProjectScope } from "@/lib/project-scope/server";
import { DIAGNOSTICS_COOKIE } from "@/lib/diagnostics/preference";
import { resolveDiagnosticsPreference } from "@/lib/diagnostics/server";
import { DiagnosticsProvider } from "@/components/diagnostics/diagnostics-provider";

/**
 * Signed-in layout. Middleware already guards these routes; this layout
 * re-verifies server-side (defense in depth) and supplies the principal
 * to the shell. No identity ever comes from the client.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const sessionSid = parseOpaqueSessionSid(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!sessionSid) {
    redirect("/sign-in");
  }
  const principal = await resolveSessionPrincipal(sessionSid);
  if (!principal) {
    redirect("/sign-in");
  }
  // The SID has just been authenticated by Python. Expose only the established
  // browser-safe one-way binding, never the HttpOnly credential itself.
  const sessionEpoch = await sessionReplayBinding(sessionSid);
  const initialProjectScope = await resolveServerProjectScope({
    principal,
    invokeProjectCapability: invokeGateway,
    preferenceValue: cookieStore.get(PROJECT_SCOPE_COOKIE)?.value,
  });
  // Resolved here, after the Principal, so that nothing diagnostic is ever
  // server-rendered while the preference is OFF. There is consequently no
  // diagnostic markup to strip at hydration and no OFF flash to suppress.
  const diagnosticsEnabled = await resolveDiagnosticsPreference({
    principal,
    cookieValue: cookieStore.get(DIAGNOSTICS_COOKIE)?.value,
  });
  return (
    <DiagnosticsProvider initialEnabled={diagnosticsEnabled} epoch={sessionEpoch}>
      <AppShell
        principal={principal}
        sessionEpoch={sessionEpoch}
        initialProjectScope={initialProjectScope}
      >
        {children}
      </AppShell>
    </DiagnosticsProvider>
  );
}
