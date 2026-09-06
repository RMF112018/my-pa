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
 * path. Browser Entra/MSAL sign-in is retired; Graph activation remains a
 * separate, still-off concern.
 *
 * **The schema head is not restated here and must not be.** A migration revision
 * copied into the web tier is a claim nothing on this side can check, and it was
 * already stale by eight revisions the last time someone tried. Git SHA and
 * deployed artifact identity are likewise unreported (WP29).
 *
 * **Morning Intelligence is `reports.resolve_set` for `morning_brief_inputs`.**
 * `cycle_run_id` is taken from the first `reports.list` item, the same discovery
 * WP11 uses. Aggregate and per-member states stay visible. READY is not "the
 * system is healthy". A missing worker heartbeat is unknown, never healthy.
 * PWA live fields are this-browser observations, not server truth.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled, gatewayAuthMode } from "@/lib/api/gateway-config";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SurfaceState } from "@/components/ui/surface-state";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import type { PrincipalSession } from "@/contracts/identity";
import { SystemRefresh } from "./system-refresh";
import { ThisBrowserPwaStatus } from "./this-browser-pwa";

export const metadata = { title: "System — my-pa" };

/** What this page reports is what is true now, so it is never cached. */
export const dynamic = "force-dynamic";

const MORNING_BRIEF_SET_ID = "morning_brief_inputs";

const NOT_HEALTHY_PLANE_STATES = new Set(["worker_absent", "worker_stale", "unavailable"]);

const READINESS_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  ready: "green",
  degraded: "gold",
  contracts_only: "coral",
  not_implemented: "coral",
};

const AGGREGATE_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  READY: "green",
  DEGRADED: "gold",
  BLOCKED: "coral",
};

const MEMBER_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  READY: "green",
  MISSING: "coral",
  FAILED: "coral",
  PARTIAL: "gold",
  STALE: "gold",
  SUPERSEDED: "gold",
  NOT_EXPECTED: "neutral",
};

type IntelligenceTruth =
  | { state: "resolved"; result: ReportsResolveSetResult }
  | { state: "no_cycle"; detail: string }
  | { state: "unavailable"; detail: string };

/**
 * Discover `cycle_run_id` from `reports.list` (first listed item), then resolve
 * `morning_brief_inputs`. Same capabilities WP11 E2E uses; no new reports surface.
 */
async function loadMorningBriefIntelligence(
  principal: PrincipalSession,
): Promise<IntelligenceTruth> {
  const listed = await invokeGateway(principal, "reports.list");
  if (!listed.ok) {
    return { state: "unavailable", detail: listed.error.message };
  }
  const cycleRunId = listed.result.items[0]?.cycle_run_id;
  if (typeof cycleRunId !== "string") {
    return {
      state: "no_cycle",
      detail:
        "reports.list returned no artifact, so cycle_run_id is unknown and " +
        "morning_brief_inputs was not resolved.",
    };
  }
  const resolved = await invokeGateway(principal, "reports.resolve_set", {
    cycle_run_id: cycleRunId,
    set_id: MORNING_BRIEF_SET_ID,
  });
  if (!resolved.ok) {
    return { state: "unavailable", detail: resolved.error.message };
  }
  return { state: "resolved", result: resolved.result };
}

export default async function SystemPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

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
    : await invokeGateway(principal, "capabilities.get");
  const intelligence = synthetic ? null : await loadMorningBriefIntelligence(principal);

  const result = outcome?.ok ? outcome.result : undefined;
  const manifest = result?.manifest;
  const readiness = result?.readiness;
  const workerPlanes = result?.worker_planes;
  const available = manifest
    ? manifest.capabilities.filter((entry) => entry.availability === "available")
    : [];
  const unavailable = manifest
    ? manifest.capabilities.filter((entry) => entry.availability !== "available")
    : [];

  return (
    <section aria-labelledby="system-heading" className="mx-auto flex max-w-2xl flex-col gap-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h1 id="system-heading" className="text-xl font-semibold text-moss-slate">
          System
        </h1>
        <SystemRefresh />
      </div>

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
            Browser Entra/MSAL sign-in is retired. Graph connector activation remains a
            separate, still-off concern from identity.
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

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Progressive web app</CardTitle>
          <Badge tone="neutral">This browser</Badge>
        </div>
        <CardBody>
          <p data-testid="system-pwa-client-side">
            PWA observation is <strong>client-side</strong> and describes{" "}
            <strong>this browser</strong>, not server truth.{" "}
            <code>GET /api/system</code> does not report this browser&rsquo;s service-worker
            controller, Cache Storage, online bit, or IndexedDB queue counts — those are
            per-browser observations the server cannot know.
          </p>
          <ThisBrowserPwaStatus />
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
              {readiness && readiness.limitations.length > 0 ? (
                <ul className="mt-2 list-inside list-disc" data-testid="system-limitations">
                  {readiness.limitations.map((limitation) => (
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
              {workerPlanes === undefined ? (
                <p role="alert" data-testid="system-worker-planes-unknown">
                  Worker-plane health is unavailable. This is not reported as healthy.
                </p>
              ) : workerPlanes.length === 0 ? (
                <p role="alert" data-testid="system-worker-planes-unknown">
                  No worker planes were reported. That is not a healthy claim.
                </p>
              ) : (
                <ul className="space-y-2" data-testid="system-worker-planes">
                  {workerPlanes.map((plane) => (
                    <li key={plane.plane} data-testid="system-worker-plane" data-plane={plane.plane}>
                      <strong>{plane.plane}</strong>: {plane.state}
                      {typeof plane.backlog === "number" ? ` — ${plane.backlog} queued/running` : ""}
                      {typeof plane.dead_lettered === "number"
                        ? `, ${plane.dead_lettered} dead-lettered`
                        : ""}
                      {plane.last_heartbeat_at ? (
                        <span data-testid="system-worker-heartbeat">
                          {" "}
                          — last heartbeat {plane.last_heartbeat_at}
                        </span>
                      ) : (
                        <span data-testid="system-worker-heartbeat-unknown">
                          {" "}
                          — last heartbeat unknown
                        </span>
                      )}
                      {NOT_HEALTHY_PLANE_STATES.has(plane.state) ? (
                        <span data-testid="system-worker-not-healthy"> — not healthy</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
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

      {intelligence ? (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Morning Intelligence readiness</CardTitle>
            {intelligence.state === "resolved" ? (
              <Badge tone={AGGREGATE_TONE[intelligence.result.aggregate] ?? "neutral"}>
                <span data-testid="system-intelligence-aggregate">{intelligence.result.aggregate}</span>
              </Badge>
            ) : (
              <Badge tone="gold">unknown</Badge>
            )}
          </div>
          <CardBody>
            <p data-testid="system-intelligence-not-system-health">
              This is the <code>{MORNING_BRIEF_SET_ID}</code> resolver aggregate, not a claim that
              the system is healthy. BLOCKED, DEGRADED, and MISSING members stay visible.
            </p>
            {intelligence.state === "unavailable" ? (
              <p className="mt-2" role="alert" data-testid="system-intelligence-unavailable">
                Morning Intelligence readiness could not be resolved. {intelligence.detail}
              </p>
            ) : intelligence.state === "no_cycle" ? (
              <p className="mt-2" role="alert" data-testid="system-intelligence-no-cycle">
                {intelligence.detail}
              </p>
            ) : (
              <ul className="mt-2 space-y-1" data-testid="system-intelligence-members">
                {intelligence.result.members.map((member) => (
                  <li
                    key={member.member_id}
                    data-testid="system-intelligence-member"
                    data-member-id={member.member_id}
                  >
                    <Badge tone={MEMBER_TONE[member.readiness] ?? "neutral"}>
                      <span data-testid="system-intelligence-member-readiness">{member.readiness}</span>
                    </Badge>{" "}
                    <span data-testid="system-intelligence-member-id">{member.member_id}</span>
                    {member.required ? " (required)" : ""}
                    {member.readiness_reason ? ` — ${member.readiness_reason}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      ) : null}

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
            <li>
              No page here restates a git revision or deployed artifact identity. That claim
              belongs to WP29, which this tier cannot check.
            </li>
          </ul>
        </CardBody>
      </Card>
    </section>
  );
}
