/**
 * System — full disclosure, read from the build rather than asserted about it.
 *
 * **Every claim this page made about the build was a constant, and four of them
 * had gone false.** It stated a schema head of `e7f3a9c2d514 (18 revisions)`
 * against an actual head of `8f2b6c4d1a37` over 26; it said "the web gateway is
 * not yet wired to the Python capture pipeline" after WP-11 wired it; it said
 * offline capture "arrives with WP-04" after WP-08 shipped it; and it reported
 * connected sources as **None connected**, which is a claim no capability in the
 * v1 set can support — `sources.list` takes a container and `sources.status`
 * takes a named subject, so nothing here can enumerate a Principal's sources at
 * all. A hardcoded sentence about the build is a sentence that keeps being
 * printed after it stops being true, which is why they are gone rather than
 * corrected: what is left is derived.
 *
 * What replaces them is `capabilities.get`, whose manifest the application
 * derives from its own dispatch table — a capability reports `available` exactly
 * when a handler is bound to it — and whose readiness is counted off that
 * manifest. When the gateway cannot be reached, this page says the build could
 * not be described, and does **not** fall back to a list of guesses.
 *
 * **A disabled Microsoft Graph connector is shown as deliberately off, and is
 * given its own region so it cannot be read as a degraded or failing source.**
 * Graph is retained in the product definition and is not the active ingestion
 * path; the Entra sign-in this shell uses for identity is a separate concern
 * from Graph activation, and the two are stated separately here for exactly that
 * reason.
 *
 * **The schema head is not restated here and must not be.** A migration revision
 * copied into the web tier is a claim nothing on this side can check, and it was
 * already stale by eight revisions the last time someone tried.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { msalSeamConfig } from "@/lib/auth/msal.config";
import { callGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled, gatewayAuthMode } from "@/lib/api/gateway-config";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SurfaceState } from "@/components/ui/surface-state";

export const metadata = { title: "System — my-pa" };

/** What this page reports is what is true now, so it is never cached. */
export const dynamic = "force-dynamic";

interface CapabilityStatus {
  readonly name: string;
  readonly availability: string;
  readonly operator_only: boolean;
}

interface Manifest {
  readonly contract_version?: string;
  readonly capabilities?: readonly CapabilityStatus[];
  readonly limits?: {
    readonly max_page_size?: number;
    readonly default_page_size?: number;
    readonly max_fetch_bytes?: number;
  };
}

interface Readiness {
  readonly state?: string;
  readonly implemented_capabilities?: number;
  readonly total_capabilities?: number;
  readonly limitations?: readonly string[];
}

interface WorkerPlane {
  readonly plane?: string;
  readonly state?: string;
  readonly backlog?: number | null;
  readonly dead_lettered?: number | null;
  readonly last_heartbeat_at?: string | null;
}

const READINESS_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  ready: "green",
  degraded: "gold",
  contracts_only: "coral",
  not_implemented: "coral",
};

export default async function SystemPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const msal = msalSeamConfig();
  const synthetic = syntheticDataEnabled();
  // **A gateway auth mode this build cannot read is a misconfiguration, and it
  // is shown as one.** The previous default of `"not configured"` fell through
  // every branch below, which meant a build that had not said how its gateway
  // establishes an acting Principal simply stopped disclosing the
  // `local_operator` limit — the page grew quieter exactly as it became less
  // trustworthy. The refusal `gatewayAuthMode` raises is surfaced instead.
  let authMode: string | null = null;
  let authModeRefusal: string | null = null;
  try {
    authMode = gatewayAuthMode();
  } catch (error) {
    authModeRefusal = error instanceof Error ? error.message : String(error);
  }

  const outcome = synthetic
    ? null
    : await callGateway<{
        manifest?: Manifest;
        readiness?: Readiness;
        worker_planes?: readonly WorkerPlane[];
      }>(
        principal,
        "capabilities.get",
      );

  const manifest = outcome?.ok ? outcome.result.manifest : undefined;
  const readiness = outcome?.ok ? outcome.result.readiness : undefined;
  const workerPlanes = outcome?.ok ? outcome.result.worker_planes : undefined;
  const available = (manifest?.capabilities ?? []).filter(
    (entry) => entry.availability === "available",
  );
  const unavailable = (manifest?.capabilities ?? []).filter(
    (entry) => entry.availability !== "available",
  );

  return (
    <section aria-labelledby="system-heading" className="mx-auto flex max-w-2xl flex-col gap-3">
      <h1 id="system-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        System
      </h1>

      <Card>
        <CardTitle>Who you are to this system</CardTitle>
        <CardBody>
          <dl className="grid grid-cols-[8rem_1fr] gap-1 font-mono text-xs break-all">
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
            Your identity here derives only from the signed server-side session; nothing you or
            your browser can send names a principal, and a request that tries to is refused rather
            than ignored.
          </p>
          {authModeRefusal !== null ? (
            <p className="mt-2" role="alert" data-testid="system-auth-mode-misconfigured">
              <strong>This build is misconfigured, and that is worse than either mode.</strong> It
              cannot say how the gateway it talks to establishes an acting principal, so it cannot
              tell you whether what you are shown is partitioned by who is signed in to this
              browser. Nothing here is claimed to be yours alone until an operator fixes it.{" "}
              {authModeRefusal}
            </p>
          ) : authMode === "local_operator" ? (
            <p className="mt-2" data-testid="system-local-operator">
              <strong>And here is the limit of that.</strong> The application gateway this build
              talks to runs in <code>local_operator</code> mode: it serves one fixed principal for
              the life of its process, so what you are shown is that deployment&rsquo;s data and is
              not partitioned by who is signed in to this browser.
            </p>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Microsoft Graph connector</CardTitle>
          <Badge tone="neutral">Off by decision</Badge>
        </div>
        <CardBody>
          <p data-testid="system-graph">
            Microsoft Graph is retained in the product definition and is <strong>deliberately
            off</strong>. It is not a degraded source and not a failing one — it is not the active
            personal-data ingestion path in this build, and nothing is waiting on it.
          </p>
          <p className="mt-2">
            Entra sign-in for <em>identity</em> is a separate concern from Graph connector
            activation: {msal.enabled ? "Entra sign-in is configured" : "Entra sign-in is not configured, and the synthetic development provider is active"}.
          </p>
        </CardBody>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Connected sources</CardTitle>
          <Badge tone="gold">Cannot be enumerated</Badge>
        </div>
        <CardBody>
          <p data-testid="system-sources-unknown">
            This build <strong>cannot list</strong> which sources you have configured. No v1
            capability enumerates a principal&rsquo;s sources — one takes a container and lists its
            children, the other requires a named subject — so the honest answer is that the list is
            unknown. It is not reported as <em>none</em>, because &ldquo;none&rdquo; is a claim
            nothing here can check.
          </p>
        </CardBody>
      </Card>

      {synthetic ? (
        <SurfaceState
          kind="not_implemented"
          title="This build is serving synthetic data"
          detail={
            "MYPA_DATA_PROVIDER is set to 'synthetic', so no capability manifest is read from " +
            "the application. Surfaces that have no fixture say so rather than inventing one."
          }
          testId="system-synthetic"
        />
      ) : outcome && !outcome.ok ? (
        <SurfaceState
          kind="unavailable"
          title="The build could not describe itself"
          detail={outcome.error.message}
          testId="system-unavailable"
        />
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>What this build can do</CardTitle>
              <Badge tone={READINESS_TONE[readiness?.state ?? ""] ?? "neutral"}>
                {readiness?.state ?? "unknown"}
              </Badge>
            </div>
            <CardBody>
              {/*
                **A missing count is unknown, never zero.** `?? 0` on both halves
                rendered "0 of 0 contracted capabilities are implemented" for a
                successful response that simply carried no `readiness` — a
                specific, alarming, and entirely invented claim about the build,
                and one that satisfies a `\d+ of \d+` assertion perfectly. Both
                numbers must be present or neither is printed.
              */}
              {typeof readiness?.implemented_capabilities === "number" &&
              typeof readiness?.total_capabilities === "number" ? (
                <p data-testid="system-readiness">
                  {readiness.implemented_capabilities} of {readiness.total_capabilities} contracted
                  capabilities are implemented in the application this shell is talking to. The
                  count is derived from the application&rsquo;s own dispatch table, not written
                  down here.
                </p>
              ) : (
                <p role="alert" data-testid="system-readiness-unknown">
                  The application answered, and its answer carried no readiness count. How many
                  contracted capabilities are implemented is therefore <strong>unknown</strong>. It
                  is not reported as none, and it is not reported as zero of zero &mdash; neither
                  is something this page was told.
                </p>
              )}
              {(readiness?.limitations ?? []).length > 0 ? (
                <ul className="mt-2 list-inside list-disc" data-testid="system-limitations">
                  {(readiness?.limitations ?? []).map((limitation) => (
                    <li key={limitation}>{limitation}</li>
                  ))}
                </ul>
              ) : null}
              {available.length > 0 ? (
                <>
                  <p className="mt-3 font-medium text-moss-slate">Available</p>
                  <ul className="mt-1 flex flex-wrap gap-1" data-testid="system-available">
                    {available.map((entry) => (
                      <li key={entry.name}>
                        <Badge tone="green">{entry.name}</Badge>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
              {unavailable.length > 0 ? (
                <>
                  <p className="mt-3 font-medium text-moss-slate">Not available in this build</p>
                  <ul className="mt-1 flex flex-wrap gap-1" data-testid="system-unavailable-caps">
                    {unavailable.map((entry) => (
                      <li key={entry.name}>
                        <Badge tone="gold">
                          {entry.name} — {entry.availability}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardTitle>Background workers</CardTitle>
            <CardBody>
              {workerPlanes && workerPlanes.length > 0 ? (
                <ul className="space-y-2" data-testid="system-worker-planes">
                  {workerPlanes.map((plane) => (
                    <li key={plane.plane ?? "unknown"}>
                      <strong>{plane.plane ?? "unknown"}</strong>: {plane.state ?? "unknown"}
                      {typeof plane.backlog === "number" ? ` — ${plane.backlog} queued/running` : ""}
                      {typeof plane.dead_lettered === "number"
                        ? `, ${plane.dead_lettered} dead-lettered`
                        : ""}
                    </li>
                  ))}
                </ul>
              ) : (
                <p role="alert" data-testid="system-worker-planes-unknown">
                  Worker-plane health is unavailable. This is not reported as healthy.
                </p>
              )}
            </CardBody>
          </Card>

          {manifest?.limits ? (
            <Card>
              <CardTitle>Limits you can rely on</CardTitle>
              <CardBody>
                <dl className="grid grid-cols-[10rem_1fr] gap-1 font-mono text-xs">
                  <dt className="text-muted">page size</dt>
                  <dd>
                    {manifest.limits.default_page_size} default, {manifest.limits.max_page_size} max
                  </dd>
                  <dt className="text-muted">fetch bytes</dt>
                  <dd>{manifest.limits.max_fetch_bytes}</dd>
                  <dt className="text-muted">contract</dt>
                  <dd>{manifest.contract_version ?? "unknown"}</dd>
                </dl>
              </CardBody>
            </Card>
          ) : null}
        </>
      )}

      <Card>
        <CardTitle>What is still true regardless</CardTitle>
        <CardBody>
          <ul className="list-inside list-disc">
            <li>Nothing is asserted on your behalf; a proposal waits for your disposition.</li>
            <li>
              A capture is called saved only when the application returns a receipt for a stored
              row. A note held on this device because the network was unreachable is shown as held
              on this device, never as saved.
            </li>
            <li>
              An empty answer and an unreachable one are shown differently everywhere in this
              shell, because they mean opposite things.
            </li>
            <li>
              No page here restates the database schema version. That claim belongs to the
              migration history, which this tier cannot read.
            </li>
          </ul>
        </CardBody>
      </Card>
    </section>
  );
}
