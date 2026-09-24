/**
 * `ConstraintPartySelector` — `PC-CM-CAPTURE-AC-010`: a party is never
 * guessed. Three explicit paths only: Me (Principal), a canonical search
 * result (Entity), or deliberate "not on file" wording (Unresolved).
 */
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConstraintPartySelector, type RequestPartyRef } from "./constraint-party-selector";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function Harness({ initial = [] as readonly RequestPartyRef[] }) {
  const [value, setValue] = useState<readonly RequestPartyRef[]>(initial);
  return <ConstraintPartySelector label="Ball in Court" value={value} onChange={setValue} testIdPrefix="bic" />;
}

describe("ConstraintPartySelector", () => {
  it("adds the Principal party via explicit 'Add me', once only", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("bic-add"));
    const addMe = await screen.findByTestId("bic-add-me");
    expect(addMe).toBeEnabled();
    await user.click(addMe);
    expect(within(screen.getByTestId("bic-chips")).getByText("Me")).toBeInTheDocument();
    // The popover stays open across an add; a second "Add me" is disabled
    // rather than letting the list accumulate a duplicate Principal party.
    expect(screen.getByTestId("bic-add-me")).toBeDisabled();
  });

  it("adds an Entity only from a canonical search result, carrying its entity_id forward", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (url: unknown) => {
      expect(String(url)).toContain("/api/people?q=");
      return new Response(
        JSON.stringify({ entities: [{ entity_id: "ent_aaaaaaaa11111111", display_name: "Harbor Design Ltd", entity_type: "organization" }] }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness />);
    await user.click(screen.getByTestId("bic-add"));
    await user.type(await screen.findByTestId("bic-search"), "Harbor");
    const result = await screen.findByTestId("bic-result-ent_aaaaaaaa11111111");
    await user.click(result);
    expect(within(screen.getByTestId("bic-chips")).getByText("Harbor Design Ltd")).toBeInTheDocument();
  });

  it("adds an Unresolved party only through deliberate 'not on file' wording", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("bic-add"));
    const unresolvedButton = await screen.findByTestId("bic-add-unresolved");
    expect(unresolvedButton).toBeDisabled();
    await user.type(screen.getByTestId("bic-unresolved-text"), "Third-party surveyor, TBC");
    expect(unresolvedButton).toBeEnabled();
    await user.click(unresolvedButton);
    expect(within(screen.getByTestId("bic-chips")).getByText("Third-party surveyor, TBC")).toBeInTheDocument();
  });

  it("removes a party by its own chip control", async () => {
    const user = userEvent.setup();
    render(<Harness initial={[{ kind: "principal" }]} />);
    expect(within(screen.getByTestId("bic-chips")).getByText("Me")).toBeInTheDocument();
    await user.click(screen.getByTestId("bic-remove-0"));
    expect(screen.getByTestId("bic-chips")).toHaveTextContent("Not recorded");
  });
});
