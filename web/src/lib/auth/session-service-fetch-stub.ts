/**
 * Test-only fetch interceptor for Python session-service URLs.
 *
 * Route tests stub `fetch` as the Capture `/v1/...` gateway. Sign-in and
 * `requirePrincipal` now POST `/webauthn/v1/sessions/...` on the same global;
 * those calls must not enter Capture `sent` arrays or empty `vi.fn()` mocks.
 * Production dual-authority is not added here.
 */

const SYNTHETIC_A = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active" as const,
  synthetic: true,
};

const SYNTHETIC_B = {
  ...SYNTHETIC_A,
  principalId: "syn-bbbb0002",
  oid: "bbbb0002-0000-0000-0000-000000000002",
  upn: "synthetic.b@moss.example",
  displayName: "Synthetic B",
};

let sidSeq = 0;

function nextSid(): string {
  sidSeq += 1;
  return sidSeq.toString(16).padStart(64, "0");
}

function hrefOf(url: string | URL | Request): string {
  if (typeof url === "string") return url;
  if (url instanceof URL) return url.href;
  return url.url;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function principalFor(init?: RequestInit) {
  try {
    const raw = init?.body;
    if (typeof raw === "string") {
      const key = (JSON.parse(raw) as { key?: unknown }).key;
      if (key === "synthetic-b") return SYNTHETIC_B;
    }
  } catch {
    /* catalogue default below */
  }
  return SYNTHETIC_A;
}

/** Answer a session-service URL, or `null` so the Capture stub can run. */
export function sessionServiceFetchResponse(
  url: string | URL | Request,
  init?: RequestInit,
): Response | null {
  const href = hrefOf(url);
  if (!href.includes("/webauthn/v1/sessions/")) return null;
  if (href.includes("/sessions/issue-synthetic")) {
    return json({ issuedSid: nextSid(), principal: principalFor(init) });
  }
  if (href.includes("/sessions/touch") || href.includes("/sessions/resolve")) {
    return json({ principal: SYNTHETIC_A });
  }
  if (href.includes("/sessions/revoke")) {
    return json({ revoked: true });
  }
  if (href.includes("/sessions/rotate")) {
    return json({ issuedSid: nextSid() });
  }
  return json({ error: { code: "invalid_request" } }, 400);
}

type FetchLike = (url: string | URL | Request, init?: RequestInit) => unknown;

/** Wrap a Capture/gateway `fetch` stub so session-service URLs never reach it. */
export function withSessionServiceFetch(inner: FetchLike): typeof fetch {
  return (async (url: string | URL | Request, init?: RequestInit) => {
    const intercepted = sessionServiceFetchResponse(url, init);
    if (intercepted) return intercepted;
    return inner(url, init) as Response;
  }) as typeof fetch;
}
