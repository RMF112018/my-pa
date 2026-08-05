import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth/session";
import { msalSeamConfig } from "@/lib/auth/msal.config";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export const metadata = { title: "System — my-pa" };

/**
 * System — full disclosure. What the system is, what it can and cannot do,
 * who you are to it, and what is connected. Honesty over polish.
 */
export default async function SystemPage() {
  const cookieStore = await cookies();
  const principal = await verifySession(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const msal = msalSeamConfig();

  return (
    <section aria-labelledby="system-heading" className="mx-auto flex max-w-2xl flex-col gap-3">
      <h1 id="system-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        System
      </h1>

      <Card>
        <CardTitle>Who you are to this system</CardTitle>
        <CardBody>
          <dl className="grid grid-cols-[8rem_1fr] gap-1 font-mono text-xs">
            <dt className="text-muted">principal</dt>
            <dd data-testid="system-principal-id">{principal.principalId}</dd>
            <dt className="text-muted">tenant (tid)</dt>
            <dd data-testid="system-tid">{principal.tid}</dd>
            <dt className="text-muted">object (oid)</dt>
            <dd data-testid="system-oid">{principal.oid}</dd>
            <dt className="text-muted">upn</dt>
            <dd>{principal.upn}</dd>
            <dt className="text-muted">provider</dt>
            <dd>{principal.synthetic ? "synthetic development provider" : "Microsoft Entra ID"}</dd>
          </dl>
          <p className="mt-2">
            Your identity derives only from validated token claims. Everything you see is scoped
            to this principal; no other principal&apos;s data is reachable from this session.
          </p>
        </CardBody>
      </Card>

      <Card>
        <div className="flex items-center justify-between">
          <CardTitle>Connected sources</CardTitle>
          <Badge tone="gold">None connected</Badge>
        </div>
        <CardBody>
          <p>
            No live sources (Outlook, Teams, OneDrive, To&nbsp;Do) are connected. The Microsoft
            Graph connector arrives with WP-07 (R6). Until then, all content is synthetic and
            labeled as such.
          </p>
          <p className="mt-2 font-mono text-xs text-muted">
            Entra sign-in: {msal.enabled ? "configured" : "not configured (synthetic provider active)"}
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Capabilities and limits</CardTitle>
        <CardBody>
          <ul className="list-inside list-disc">
            <li>
              Capture is acknowledged with per-principal idempotent receipts (WP-03); the web
              gateway is not yet wired to the Python capture pipeline.
            </li>
            <li>Nothing is asserted on your behalf; proposals always wait for your disposition.</li>
            <li>Offline capture and sync arrive with WP-04 (R3).</li>
            <li>Isolation diagnostics will surface here once the backend read models are wired.</li>
          </ul>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Build</CardTitle>
        <CardBody>
          <dl className="grid grid-cols-[8rem_1fr] gap-1 font-mono text-xs">
            <dt className="text-muted">work package</dt>
            <dd>WP-03 (R2 — principal-partitioned capture)</dd>
            <dt className="text-muted">frontend</dt>
            <dd>Next.js App Router (see ADR-004)</dd>
            <dt className="text-muted">schema head</dt>
            <dd>e7f3a9c2d514 (18 revisions)</dd>
          </dl>
        </CardBody>
      </Card>
    </section>
  );
}
