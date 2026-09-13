import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { PROJECT_SCOPE_COOKIE } from "@/lib/project-scope/preference";
import { resolveServerProjectScope } from "@/lib/project-scope/server";
import { ProjectRouteScopeBinding } from "./project-scope-binding";

/**
 * The parent layout owns the persistent provider, but only this segment gets
 * authoritative Next route params. Resolve the explicit segment here on the
 * server and bind it into that provider; no request/header pathname inference.
 */
export default async function ProjectRouteLayout({
  children,
  params,
}: {
  readonly children: React.ReactNode;
  readonly params: Promise<{ projectId: string }>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");
  const { projectId } = await params;
  const preferenceValue = cookieStore.get(PROJECT_SCOPE_COOKIE)?.value;
  const fallbackResolution = await resolveServerProjectScope({
    principal,
    invokeProjectCapability: invokeGateway,
    preferenceValue,
  });
  const resolution = await resolveServerProjectScope({
    principal,
    invokeProjectCapability: invokeGateway,
    deepLinkProjectId: projectId,
    preferenceValue,
  });
  return (
    <ProjectRouteScopeBinding
      resolution={resolution}
      fallbackResolution={fallbackResolution}
    >
      {children}
    </ProjectRouteScopeBinding>
  );
}
