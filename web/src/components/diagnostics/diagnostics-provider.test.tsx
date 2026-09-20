/**
 * WP07 AC-42 / AC-46 / WP07-AC-056 / WP07-AC-057 — the client policy and its fencing.
 *
 * The transitions asserted here are the ones that can silently fail open. A
 * provider that simply mirrored the toggle would pass a naive test and still
 * show diagnostics after a write that never persisted, or restore an old ON
 * when a slow response landed after the user had already turned it off. So each
 * test below drives a race or a failure deliberately, rather than a happy path.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn() }) }));

import {
  DiagnosticsProvider,
  WhenDiagnostics,
  useDiagnosticsPolicy,
} from "./diagnostics-provider";

/** A probe that both reports the policy and proves the subtree's mount state. */
function Probe() {
  const { enabled, saveState, setEnabled } = useDiagnosticsPolicy();
  return (
    <div>
      <span data-testid="enabled">{String(enabled)}</span>
      <span data-testid="save-state">{saveState}</span>
      <button type="button" onClick={() => void setEnabled(true)}>
        turn on
      </button>
      <button type="button" onClick={() => void setEnabled(false)}>
        turn off
      </button>
      <WhenDiagnostics>
        <span data-testid="diagnostic-child">technical detail</span>
      </WhenDiagnostics>
    </div>
  );
}

function renderProvider({ initialEnabled = false, epoch = "epoch-1" } = {}) {
  return render(
    <DiagnosticsProvider initialEnabled={initialEnabled} epoch={epoch}>
      <Probe />
    </DiagnosticsProvider>,
  );
}

function accepts(enabled: boolean) {
  return new Response(JSON.stringify({ enabled }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  refresh.mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the default is off, and off means unmounted", () => {
  it("renders no diagnostic child when seeded off", () => {
    renderProvider();
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });

  it("renders the diagnostic child when seeded on from accepted server state", () => {
    renderProvider({ initialEnabled: true });
    expect(screen.getByTestId("diagnostic-child")).toBeTruthy();
  });

  it("falls back to off outside any provider", () => {
    render(<Probe />);
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });
});

describe("turning diagnostics on", () => {
  it("stays off until the write is accepted", async () => {
    let release!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    );
    const user = userEvent.setup();
    renderProvider();

    await user.click(screen.getByRole("button", { name: "turn on" }));

    // Pending is not ON. Nothing diagnostic may render on optimism.
    expect(screen.getByTestId("save-state").textContent).toBe("pending");
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();

    await act(async () => {
      release(accepts(true));
    });

    expect(screen.getByTestId("enabled").textContent).toBe("true");
    expect(screen.getByTestId("diagnostic-child")).toBeTruthy();
  });

  it("stays off and reports failure when the write is refused", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 403 })));
    const user = userEvent.setup();
    renderProvider();

    await user.click(screen.getByRole("button", { name: "turn on" }));

    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.getByTestId("save-state").textContent).toBe("failed");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });

  it("stays off when the network throws", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("offline");
      }),
    );
    const user = userEvent.setup();
    renderProvider();
    await user.click(screen.getByRole("button", { name: "turn on" }));
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.getByTestId("save-state").textContent).toBe("failed");
  });

  it("stays off when a 200 does not confirm the value that was asked for", async () => {
    // A success status is not proof of acceptance. If the server did not say it
    // stored `true`, the UI must not claim it did.
    vi.stubGlobal("fetch", vi.fn(async () => accepts(false)));
    const user = userEvent.setup();
    renderProvider();
    await user.click(screen.getByRole("button", { name: "turn on" }));
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.getByTestId("save-state").textContent).toBe("failed");
  });
});

describe("turning diagnostics off", () => {
  it("unmounts immediately rather than waiting for the write", async () => {
    let release!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    );
    const user = userEvent.setup();
    renderProvider({ initialEnabled: true });
    expect(screen.getByTestId("diagnostic-child")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "turn off" }));

    // Withdrawing detail early is safe; showing it early is not.
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
    await act(async () => {
      release(accepts(false));
    });
    expect(screen.getByTestId("enabled").textContent).toBe("false");
  });

  it("stays suppressed and reports failure when the off write fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    const user = userEvent.setup();
    renderProvider({ initialEnabled: true });
    await user.click(screen.getByRole("button", { name: "turn off" }));

    // Conservatively off in this document, and truthful that it did not save.
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.getByTestId("save-state").textContent).toBe("failed");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });
});

describe("fencing", () => {
  it("drops a late ON response that a newer OFF has superseded", async () => {
    let releaseOn!: (response: Response) => void;
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (releaseOn = resolve)))
      .mockImplementationOnce(async () => accepts(false));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderProvider();

    await user.click(screen.getByRole("button", { name: "turn on" }));
    await user.click(screen.getByRole("button", { name: "turn off" }));

    // The ON write now lands, after the user has already asked for OFF.
    await act(async () => {
      releaseOn(accepts(true));
    });

    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });

  it("re-seeds from the server when the session epoch changes", async () => {
    const { rerender } = render(
      <DiagnosticsProvider initialEnabled epoch="epoch-1">
        <Probe />
      </DiagnosticsProvider>,
    );
    expect(screen.getByTestId("diagnostic-child")).toBeTruthy();

    // A different Principal on the same browser: new epoch, server says off.
    rerender(
      <DiagnosticsProvider initialEnabled={false} epoch="epoch-2">
        <Probe />
      </DiagnosticsProvider>,
    );

    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });

  it("drops an in-flight ON when the epoch changes before it lands", async () => {
    let release!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    );
    const user = userEvent.setup();
    const { rerender } = render(
      <DiagnosticsProvider initialEnabled={false} epoch="epoch-1">
        <Probe />
      </DiagnosticsProvider>,
    );
    await user.click(screen.getByRole("button", { name: "turn on" }));

    rerender(
      <DiagnosticsProvider initialEnabled={false} epoch="epoch-2">
        <Probe />
      </DiagnosticsProvider>,
    );
    await act(async () => {
      release(accepts(true));
    });

    // The acceptance belonged to a session that no longer exists.
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });

  it("follows the server when a navigation re-resolves the preference", () => {
    const { rerender } = render(
      <DiagnosticsProvider initialEnabled epoch="epoch-1">
        <Probe />
      </DiagnosticsProvider>,
    );
    expect(screen.getByTestId("diagnostic-child")).toBeTruthy();
    rerender(
      <DiagnosticsProvider initialEnabled={false} epoch="epoch-1">
        <Probe />
      </DiagnosticsProvider>,
    );
    expect(screen.queryByTestId("diagnostic-child")).toBeNull();
  });
});

describe("the write contract", () => {
  it("posts JSON to the one endpoint, same-origin, with only `enabled`", async () => {
    const fetchMock = vi.fn(async () => accepts(true));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderProvider();
    await user.click(screen.getByRole("button", { name: "turn on" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/system/diagnostics");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(String(init.body))).toEqual({ enabled: true });
  });

  it("never mutates through a GET or a query parameter", async () => {
    const fetchMock = vi.fn(async () => accepts(true));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderProvider();
    await user.click(screen.getByRole("button", { name: "turn on" }));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).not.toBe("GET");
    expect(url).not.toContain("?");
  });
});
