/**
 * A live `sid` is live **for one principal**, and for no other.
 *
 * This closes WP-07's NOTE 2. The registry always recorded which principal a
 * `sid` belonged to; `touchSession` never checked it, so a session envelope
 * naming principal B while carrying principal A's live `sid` resolved to B and
 * refreshed A's session on the way past.
 *
 * **The honest framing, unchanged from the NOTE:** reaching that state requires
 * the HMAC signing secret, and anyone holding that can mint an envelope for any
 * identity outright, so this was never a reachable isolation hole. It is closed
 * because it is one comparison and because the property is worth being able to
 * point at rather than argue.
 *
 * Every identifier below is synthetic.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { encodeSession, newSessionId } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import {
  IDLE_TIMEOUT_SECONDS,
  registerSession,
  resetSessionRegistry,
  touchSession,
} from "@/lib/auth/session-registry";
import type { PrincipalSession } from "@/contracts/identity";

const A: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const B: PrincipalSession = {
  ...A,
  principalId: "syn-bbbb0002",
  oid: "bbbb0002-0000-0000-0000-000000000002",
  upn: "synthetic.b@moss.example",
  displayName: "Synthetic B",
};

beforeEach(() => {
  resetSessionRegistry();
});

describe("touchSession binds a sid to its principal", () => {
  it("accepts the principal the sid was registered for", () => {
    const sid = newSessionId();
    registerSession(A.principalId, sid);
    expect(touchSession(sid, A.principalId)).toBe(true);
  });

  it("refuses a different principal presenting a live sid", () => {
    const sid = newSessionId();
    registerSession(A.principalId, sid);
    expect(touchSession(sid, B.principalId)).toBe(false);
  });

  it("does not refresh the session it refused", () => {
    const sid = newSessionId();
    const registeredAt = 1_000_000;
    registerSession(A.principalId, sid, registeredAt);
    // A foreign touch late in the idle window must not extend it.
    expect(touchSession(sid, B.principalId, registeredAt + IDLE_TIMEOUT_SECONDS - 1)).toBe(false);
    expect(touchSession(sid, A.principalId, registeredAt + IDLE_TIMEOUT_SECONDS + 1)).toBe(false);
  });

  it("still refuses an unregistered sid", () => {
    expect(touchSession(newSessionId(), A.principalId)).toBe(false);
  });
});

describe("resolveSessionPrincipal carries the binding through", () => {
  it("resolves an envelope whose principal matches the registered one", async () => {
    const sid = newSessionId();
    registerSession(A.principalId, sid);
    const token = await encodeSession(A, sid);
    await expect(resolveSessionPrincipal(token)).resolves.toMatchObject({
      principalId: A.principalId,
    });
  });

  it("refuses an envelope naming B that carries A's live sid", async () => {
    const sid = newSessionId();
    registerSession(A.principalId, sid);
    // A validly signed envelope for B carrying A's sid. Producing one requires
    // the signing secret, which is the whole reason this was a NOTE rather than
    // a finding — it is closed anyway.
    const token = await encodeSession(B, sid);
    await expect(resolveSessionPrincipal(token)).resolves.toBeNull();
  });
});

/**
 * **The state is process-global, and this is the structural half of a defect a
 * browser found and no unit test could.**
 *
 * Next compiles route handlers and server components into separate module
 * graphs, so a module-level `const live = new Map()` is instantiated once per
 * graph. `POST /api/session` registered a `sid` in the route handler's copy and
 * the server component rendering `/today` asked the RSC copy, which had never
 * seen it — so every signed-in page redirected back to `/sign-in`. Reproduced
 * with two `curl`s against a real Next server: the same cookie was accepted by
 * `GET /api/system` (200) and refused by `GET /today` (307 to `/sign-in`) in the
 * same second.
 *
 * A vitest process has one module graph, so no test here can reproduce the split
 * — and this one does not pretend to. What it asserts is the mechanism that
 * makes the two graphs agree: the maps hang off a process-global symbol slot, so
 * a second evaluation of this module in the same process finds the same object
 * rather than making a new one. The end-to-end proof is `e2e/journeys.spec.ts`,
 * in a real browser against a real server, and it is the only proof that can be.
 */
describe("the registry is one object per process, not one per module graph", () => {
  it("keeps its maps in a process-global slot a second graph would also find", () => {
    resetSessionRegistry();
    registerSession(A.principalId, "sid-global-check");

    const slot = (globalThis as Record<symbol, unknown>)[
      Symbol.for("my-pa.web.auth.session-registry.v1")
    ] as { live: Map<string, unknown>; current: Map<string, string> } | undefined;

    expect(slot, "the registry must be reachable from the process global").toBeDefined();
    expect(slot?.live.has("sid-global-check")).toBe(true);
    expect(slot?.current.get(A.principalId)).toBe("sid-global-check");

    // And the exported functions read that same object rather than a private one.
    expect(touchSession("sid-global-check", A.principalId)).toBe(true);
    slot?.live.delete("sid-global-check");
    expect(touchSession("sid-global-check", A.principalId)).toBe(false);
  });
});
